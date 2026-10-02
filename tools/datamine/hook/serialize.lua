--[[----------------------------------------------------------------------------
  serialize.lua - deterministic Lua table serializer for the DCS _G dump hook.

  Renders a Lua value as a loadable Lua literal. Pure Lua with no DCS globals,
  so it is usable outside the game.

    local serialize = require 'serialize'
    local text = serialize(value, { indent = '\t', newline = '\n' })

  Options:
    indent   string per nesting level (default two spaces)
    newline  line separator (default '\n')
    process  optional (item, path) -> item transform applied to every value
             before rendering; `path` is the key trail from the root. The path
             table is reused between calls, so do not keep a reference to it.
    onCycle  optional (path) callback, called with the key trail of each
             back-reference dropped by `process` rendering (same path reuse).
    maxTables  most tables one call may render (default MAX_TABLES); beyond
             it the call raises an error rather than truncating the output.

  Output rules:
    * Sequence part (1..n) first, then the remaining keys sorted by type, then
      value, so output is stable across runs.
    * A table reached from several places (shared, not cyclic) is rendered in
      full at each occurrence. A table that contains itself, directly or
      through its descendants, is a cycle: the back-reference is written as
      `nil`. Functions, userdata, threads and NaN are also written as `nil`,
      so the entry is absent once loaded.
    * Such a `nil` is only ever written under an explicit key (`fn = nil`,
      `[2] = nil`), never as a positional element: the sequence part ends
      before the first value written as `nil`, and every later integer key
      is written as `[i] = value`. `{ 1, nil }` never appears, so a reader
      can tell a positional `nil` (a table an older hook dropped) from a
      value that cannot be written.
    * Entries whose key is not a string, number or boolean (table, function,
      userdata keys) are skipped.
    * Numbers use %.14g with a locale decimal comma normalized to a dot; -0 is
      written as 0 and +/-inf as +/-1e309.
    * A proxy table (DCS `set_recursive_metatable`: a metatable whose __index
      is a table) is written with its effective fields: its raw entries, then
      each key of its __index table that is still absent, then of that table's
      own __index table, and so on (first found wins, as for t[k]). The chain
      stops at a non-table __index (functions are never called), at `_G`, at a
      table already in the chain, or after MAX_INHERIT hops. Inherited tables
      are rendered by the same rule. Live tables are never modified.
------------------------------------------------------------------------------]]

local serialize = {}

local floor = math.floor
local huge = math.huge
local rep = string.rep
local fmt = string.format

local function formatNumber(x)
  if x ~= x then return 'nil' end
  if x == huge then return '1e309' end
  if x == -huge then return '-1e309' end
  if x == 0 then return '0' end
  -- DCS may run under a C locale with a decimal comma.
  local s = fmt('%.14g', x)
  if s:find(',', 1, true) then s = (s:gsub(',', '.')) end
  return s
end

local shortControlEscapes = {
  ['\a'] = '\\a', ['\b'] = '\\b', ['\f'] = '\\f', ['\n'] = '\\n',
  ['\r'] = '\\r', ['\t'] = '\\t', ['\v'] = '\\v', ['\127'] = '\\127',
}
local longControlEscapes = { ['\127'] = '\127' }
for i = 0, 31 do
  local ch = string.char(i)
  if not shortControlEscapes[ch] then
    shortControlEscapes[ch] = '\\' .. i
    longControlEscapes[ch] = fmt('\\%03d', i)
  end
end

-- A control char followed by a digit is written as a 3-digit escape (\001) so
-- the digit cannot extend the escape; the rest use the short form.
local function escapeString(str)
  return (str:gsub('\\', '\\\\')
             :gsub('(%c)%f[0-9]', longControlEscapes)
             :gsub('%c', shortControlEscapes))
end

-- Double-quoted, unless the string holds a double quote but no single quote.
local function quoteString(str)
  if not str:find('[%c"\\]') then return '"' .. str .. '"' end
  local escaped = escapeString(str)
  if escaped:find('"', 1, true) and not escaped:find("'", 1, true) then
    return "'" .. escaped .. "'"
  end
  return '"' .. escaped:gsub('"', '\\"') .. '"'
end

local luaKeywords = {
  ['and'] = true, ['break'] = true, ['do'] = true, ['else'] = true,
  ['elseif'] = true, ['end'] = true, ['false'] = true, ['for'] = true,
  ['function'] = true, ['goto'] = true, ['if'] = true, ['in'] = true,
  ['local'] = true, ['nil'] = true, ['not'] = true, ['or'] = true,
  ['repeat'] = true, ['return'] = true, ['then'] = true, ['true'] = true,
  ['until'] = true, ['while'] = true,
}

-- Bare `key = value` lines keep scalar fields greppable for the extractors.
local function isIdentifier(str)
  return type(str) == 'string'
    and str:match('^[_%a][_%a%d]*$') ~= nil
    and not luaKeywords[str]
end

-- Key types that can be written as a literal.
local keyTypes = { number = 1, boolean = 2, string = 3 }

local function isSequenceKey(k, seqLen)
  return type(k) == 'number' and floor(k) == k and 1 <= k and k <= seqLen
end

local function sortKeys(a, b)
  local ta, tb = type(a), type(b)
  if ta ~= tb then return keyTypes[ta] < keyTypes[tb] end
  if ta == 'boolean' then return (not a) and b end
  return a < b
end

-- Longest __index chain followed when flattening a proxy table.
local MAX_INHERIT = 16

-- The table to read `t`'s entries from: `t` itself unless it is a proxy, else
-- a fresh table holding its raw entries plus the inherited keys absent raw.
local function effective(t)
  local merged, seen, node = nil, { [t] = true }, t
  for _ = 1, MAX_INHERIT do
    local mt = getmetatable(node)
    local idx = type(mt) == 'table' and rawget(mt, '__index') or nil
    if type(idx) ~= 'table' or seen[idx] or rawequal(idx, _G) then break end
    seen[idx] = true
    if merged == nil then
      merged = {}
      for k, v in next, t, nil do merged[k] = v end
    end
    for k, v in next, idx, nil do
      if rawget(merged, k) == nil then merged[k] = v end
    end
    node = idx
  end
  return merged or t
end

-- Default cap on tables rendered by one call; shared tables count once per
-- occurrence, so a deeply shared structure fails here instead of exhausting
-- memory.
local MAX_TABLES = 1000000

local function countTable(state)
  state.tables = state.tables + 1
  if state.tables > state.maxTables then
    error('serialize: more than ' .. state.maxTables
      .. ' tables rendered (shared tables expand at every occurrence)', 0)
  end
end

-- `active` holds the tables on the path from the root to `item`, so only a
-- back-reference to an ancestor is dropped; shared tables are processed again
-- at each occurrence, as `process` may treat them differently by path.
local function processRecursive(state, item, path, active)
  if active[item] then
    if state.onCycle then state.onCycle(path) end
    return nil
  end

  local processed = state.process(item, path)
  if type(processed) ~= 'table' then return processed end
  if active[processed] then
    if state.onCycle then state.onCycle(path) end
    return nil
  end
  countTable(state)

  local copy = {}
  active[item] = true
  active[processed] = true
  local depth = #path + 1
  for k, v in next, effective(processed), nil do
    if keyTypes[type(k)] then
      path[depth] = k
      copy[k] = processRecursive(state, v, path, active)
      path[depth] = nil
    end
  end
  active[item] = nil
  active[processed] = nil
  return copy
end

-- Whether `render` writes `value` as something other than `nil`.
local function writable(value, active)
  local tv = type(value)
  if tv == 'number' then return value == value end
  if tv == 'table' then return not active[value] end
  return tv == 'string' or tv == 'boolean'
end

-- `active` holds the tables on the path from the root to `value`: a
-- back-reference to one of them is a cycle and becomes `nil`; any other
-- repeated table is rendered again.
local function render(value, level, buf, indent, newline, active, state)
  local tv = type(value)
  if tv == 'string' then
    buf[#buf + 1] = quoteString(value)
  elseif tv == 'number' then
    buf[#buf + 1] = formatNumber(value)
  elseif tv == 'boolean' then
    buf[#buf + 1] = value and 'true' or 'false'
  elseif tv ~= 'table' or active[value] then
    buf[#buf + 1] = 'nil'
  else
    local live = value
    active[live] = true
    value = effective(value)
    if state then countTable(state) end

    -- Positional elements stop before the first one written as `nil`.
    local seqLen = 0
    while writable(rawget(value, seqLen + 1), active) do seqLen = seqLen + 1 end

    local keys = {}
    for k in pairs(value) do
      if keyTypes[type(k)] and not isSequenceKey(k, seqLen) then
        keys[#keys + 1] = k
      end
    end
    table.sort(keys, sortKeys)
    local keysLen = #keys

    if seqLen == 0 and keysLen == 0 then
      buf[#buf + 1] = '{}'
      active[live] = nil
      return
    end

    buf[#buf + 1] = '{'
    local childLevel = level + 1
    for i = 1, seqLen do
      if i > 1 then buf[#buf + 1] = ',' end
      buf[#buf + 1] = ' '
      render(rawget(value, i), childLevel, buf, indent, newline, active, state)
    end
    for i = 1, keysLen do
      if (seqLen + i) > 1 then buf[#buf + 1] = ',' end
      buf[#buf + 1] = newline .. rep(indent, childLevel)
      local k = keys[i]
      if isIdentifier(k) then
        buf[#buf + 1] = k
      else
        buf[#buf + 1] = '['
        render(k, childLevel, buf, indent, newline, active, state)
        buf[#buf + 1] = ']'
      end
      buf[#buf + 1] = ' = '
      render(rawget(value, k), childLevel, buf, indent, newline, active, state)
    end

    if keysLen > 0 then
      buf[#buf + 1] = newline .. rep(indent, level)
    else
      buf[#buf + 1] = ' '
    end
    buf[#buf + 1] = '}'
    active[live] = nil
  end
end

function serialize.serialize(root, options)
  options = options or {}
  local indent = options.indent or '  '
  local newline = options.newline or '\n'

  local state = {
    tables = 0,
    maxTables = options.maxTables or MAX_TABLES,
    process = options.process,
    onCycle = options.onCycle,
  }

  -- The processed copy is already bounded and acyclic, so it renders uncounted.
  if options.process then
    root = processRecursive(state, root, {}, {})
    state = nil
  end

  local buf = {}
  render(root, 0, buf, indent, newline, {}, state)
  return table.concat(buf)
end

setmetatable(serialize, {
  __call = function(_, root, options) return serialize.serialize(root, options) end,
})

return serialize
