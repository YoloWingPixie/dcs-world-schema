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
             it the call raises an error rather than truncating the output
             (lossless mode: a truncated marker, see below).
    lossless   write dump format 4 (see "Lossless mode" below)
    maxDepth   lossless mode: deepest table level written (default MAX_DEPTH)
    onDrop, onTruncate, onProxy  lossless mode callbacks (see below)

  Output rules (format 3, without `lossless`):
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
  Lossless mode (`lossless = true`; dump format 4, used by dump-globals.lua):
  nothing is written as `nil` and nothing is dropped silently.
    * Numbers are written exactly: integers up to 2^53 in full, others as the
      shortest of %.15g, %.16g, %.17g that reads back as the same double.
      NaN, +/-inf and negative zero are markers (below): Lua 5.1 merges the
      constants 0 and -0 of a chunk and Lua 5.3+ reads `-0` as integer 0, so
      a literal `-0` would not survive loading.
    * Values Lua text cannot hold are markers, calls of a global `__dcs`
      with one table argument (fields: kind first, then id, reason,
      lua_type, name, value):
        __dcs{kind="function"}, __dcs{kind="userdata"}, __dcs{kind="thread"}
        __dcs{kind="number", value="nan"|"inf"|"-inf"|"-0"}
        __dcs{kind="anchor", id=N, value={...}}  first occurrence of a table
                                                 referenced more than once
        __dcs{kind="ref", id=N}                  every later occurrence, and
                                                 cycle back-references
        __dcs{kind="truncated", reason="depth"|"size", lua_type="table"}
        __dcs{kind="unsupported", lua_type="..."}
      plus any marker `process` returns (serialize.marker), e.g. dump-globals'
      __dcs{kind="redacted", reason="patch-volatile", lua_type="number"}.
      Anchor ids count from 1 per call, in output order. Keys use the same
      number rules; an infinite key is written [__dcs{kind="number", ...}].
    * A table shared within one call (or holding a cycle) is written once,
      as an anchor, and referenced after: the output size is linear in the
      number of distinct tables.
    * Past `maxTables` distinct tables or `maxDepth` levels (default
      MAX_DEPTH) a table is written as a truncated marker and `onTruncate`
      (path, reason) is called; nothing raises.
    * Keys that are tables, functions or userdata cannot be written; each is
      reported to `onDrop` (path, lua type of the key), the path ending in a
      "<type key>" placeholder.
    * `onProxy` (path, proxy, chain) is called for each proxy table flattened
      (chain: the __index tables followed, nearest first), so a caller can
      record which keys were the proxy's own. `onCycle` is called for each
      back-reference (now written as a ref, not dropped).
    * `process` sees every occurrence of a table until it returns a table it
      already returned: that table's copy is reused (the ref), so `process`
      must treat a table the same at every place it returns it.
  Without `lossless` the format-3 rules above apply unchanged (terrain-dump.lua
  and me-action-db.lua read that output).
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
-- Second result: the __index tables followed (nearest first), or nil.
local function effective(t)
  local merged, seen, node, chain = nil, { [t] = true }, t, nil
  for _ = 1, MAX_INHERIT do
    local mt = getmetatable(node)
    local idx = type(mt) == 'table' and rawget(mt, '__index') or nil
    if type(idx) ~= 'table' or seen[idx] or rawequal(idx, _G) then break end
    seen[idx] = true
    if merged == nil then
      merged, chain = {}, {}
      for k, v in next, t, nil do merged[k] = v end
    end
    chain[#chain + 1] = idx
    for k, v in next, idx, nil do
      if rawget(merged, k) == nil then merged[k] = v end
    end
    node = idx
  end
  return merged or t, chain
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

------------------------------------------------------------------------------
-- Lossless mode (dump format 4)
------------------------------------------------------------------------------

-- Deepest table level a lossless call writes; deeper tables are truncated.
local MAX_DEPTH = 200

-- Tables made by serialize.marker: written as __dcs{...}, never recursed.
local markers = setmetatable({}, { __mode = 'k' })

local function isMarker(v)
  return type(v) == 'table' and markers[v] == true
end

-- A marker value: `fields` (kind = ..., plus scalar fields) written as
-- __dcs{...}. The same marker table may be returned at many places.
function serialize.marker(fields)
  markers[fields] = true
  return fields
end

local FIELD_ORDER = { 'kind', 'id', 'reason', 'lua_type', 'name', 'value' }
local FIELD_RANK = {}
for i, f in ipairs(FIELD_ORDER) do FIELD_RANK[f] = i end

local function fieldBefore(a, b)
  local ra, rb = FIELD_RANK[a], FIELD_RANK[b]
  if ra and rb then return ra < rb end
  if ra or rb then return ra ~= nil end
  return a < b
end

local TWO53 = 2 ^ 53
local PRECISIONS = { '%.15g', '%.16g', '%.17g' }

-- `x` as an exact literal, or nil and the number marker's value.
local function exactNumber(x)
  if x ~= x then return nil, 'nan' end
  if x == huge then return nil, 'inf' end
  if x == -huge then return nil, '-inf' end
  if x == 0 then
    if 1 / x < 0 then return nil, '-0' end
    return '0'
  end
  local s
  if x == floor(x) and -TWO53 <= x and x <= TWO53 then
    s = fmt('%.0f', x)
  else
    for i = 1, #PRECISIONS do
      s = fmt(PRECISIONS[i], x)
      -- tonumber parses in the same C locale string.format wrote in; try
      -- the dot form as well in case only one of them honours a comma.
      if tonumber(s) == x then break end
      local dotted = s:gsub(',', '.')
      if tonumber(dotted) == x then break end
    end
  end
  if s:find(',', 1, true) then s = (s:gsub(',', '.')) end
  return s
end

local function truncated(st, path, reason)
  if st.onTruncate then st.onTruncate(path, reason) end
  return serialize.marker({ kind = 'truncated', reason = reason, lua_type = 'table' })
end

-- Copy `item` into a plain, metatable-free graph: `process` applied, proxies
-- flattened, unwritable values replaced by markers. A table `process` returns
-- again maps to the same copy, so sharing and cycles survive as identity.
local function copyLossless(st, item, path)
  if isMarker(item) then return item end
  local processed = item
  if st.process then processed = st.process(item, path) end
  if isMarker(processed) then return processed end
  local tp = type(processed)
  if tp == 'string' or tp == 'number' or tp == 'boolean' or tp == 'nil' then
    return processed
  elseif tp == 'function' or tp == 'userdata' or tp == 'thread' then
    return serialize.marker({ kind = tp })
  elseif tp ~= 'table' then
    return serialize.marker({ kind = 'unsupported', lua_type = tp })
  end

  local done = st.memo[processed]
  if done then
    if st.open[done] and st.onCycle then st.onCycle(path) end
    return done
  end
  local depth = #path + 1
  if depth > st.maxDepth then return truncated(st, path, 'depth') end
  st.tables = st.tables + 1
  if st.tables > st.maxTables then return truncated(st, path, 'size') end

  local copy = {}
  st.memo[processed] = copy
  st.open[copy] = true
  local view, chain = effective(processed)
  if chain and st.onProxy then st.onProxy(path, processed, chain) end
  for k, v in next, view, nil do
    local tk = type(k)
    if keyTypes[tk] then
      path[depth] = k
      copy[k] = copyLossless(st, v, path)
    else
      path[depth] = '<' .. tk .. ' key>'
      if st.onDrop then st.onDrop(path, tk) end
    end
    path[depth] = nil
  end
  st.open[copy] = nil
  return copy
end

-- refs[t] = number of places the copy graph holds table `t`.
local function countRefs(refs, t)
  for _, v in next, t, nil do
    if type(v) == 'table' and not markers[v] then
      local n = (refs[v] or 0) + 1
      refs[v] = n
      if n == 1 then countRefs(refs, v) end
    end
  end
end

local renderLossless

local function renderMarker(m, level, buf, st)
  local fields = {}
  for f in pairs(m) do fields[#fields + 1] = f end
  table.sort(fields, fieldBefore)
  buf[#buf + 1] = '__dcs{'
  for i, f in ipairs(fields) do
    if i > 1 then buf[#buf + 1] = ', ' end
    buf[#buf + 1] = isIdentifier(f) and f or ('[' .. quoteString(tostring(f)) .. ']')
    buf[#buf + 1] = '='
    renderLossless(m[f], level, buf, st)
  end
  buf[#buf + 1] = '}'
end

local function renderNumber(x, level, buf, st)
  local s, special = exactNumber(x)
  if s then
    buf[#buf + 1] = s
  else
    renderMarker({ kind = 'number', value = special }, level, buf, st)
  end
end

local function renderTableBody(value, level, buf, st)
  local seqLen = 0
  while rawget(value, seqLen + 1) ~= nil do seqLen = seqLen + 1 end

  local keys = {}
  for k in next, value, nil do
    if not isSequenceKey(k, seqLen) then keys[#keys + 1] = k end
  end
  table.sort(keys, sortKeys)
  local keysLen = #keys

  if seqLen == 0 and keysLen == 0 then
    buf[#buf + 1] = '{}'
    return
  end

  local indent, newline = st.indent, st.newline
  buf[#buf + 1] = '{'
  local childLevel = level + 1
  for i = 1, seqLen do
    if i > 1 then buf[#buf + 1] = ',' end
    buf[#buf + 1] = ' '
    renderLossless(rawget(value, i), childLevel, buf, st)
  end
  for i = 1, keysLen do
    if (seqLen + i) > 1 then buf[#buf + 1] = ',' end
    buf[#buf + 1] = newline .. rep(indent, childLevel)
    local k = keys[i]
    if isIdentifier(k) then
      buf[#buf + 1] = k
    else
      buf[#buf + 1] = '['
      if k == 0 then buf[#buf + 1] = '0' else renderLossless(k, childLevel, buf, st) end
      buf[#buf + 1] = ']'
    end
    buf[#buf + 1] = ' = '
    renderLossless(rawget(value, k), childLevel, buf, st)
  end

  if keysLen > 0 then
    buf[#buf + 1] = newline .. rep(indent, level)
  else
    buf[#buf + 1] = ' '
  end
  buf[#buf + 1] = '}'
end

renderLossless = function(value, level, buf, st)
  local tv = type(value)
  if tv == 'string' then
    buf[#buf + 1] = quoteString(value)
  elseif tv == 'number' then
    renderNumber(value, level, buf, st)
  elseif tv == 'boolean' then
    buf[#buf + 1] = value and 'true' or 'false'
  elseif markers[value] then
    renderMarker(value, level, buf, st)
  elseif (st.refs[value] or 0) > 1 then
    local id = st.ids[value]
    if id then
      buf[#buf + 1] = '__dcs{kind="ref", id=' .. id .. '}'
      return
    end
    id = st.nextId
    st.nextId = id + 1
    st.ids[value] = id
    buf[#buf + 1] = '__dcs{kind="anchor", id=' .. id .. ', value='
    renderTableBody(value, level, buf, st)
    buf[#buf + 1] = '}'
  else
    renderTableBody(value, level, buf, st)
  end
end

local function serializeLossless(root, options)
  local st = {
    indent = options.indent or '  ',
    newline = options.newline or '\n',
    process = options.process,
    onCycle = options.onCycle,
    onDrop = options.onDrop,
    onTruncate = options.onTruncate,
    onProxy = options.onProxy,
    maxTables = options.maxTables or MAX_TABLES,
    maxDepth = options.maxDepth or MAX_DEPTH,
    tables = 0,
    memo = {},
    open = {},
  }
  local copy = copyLossless(st, root, {})
  st.memo, st.open, st.process = nil, nil, nil
  st.refs, st.ids, st.nextId = {}, {}, 1
  if type(copy) == 'table' and not markers[copy] then
    st.refs[copy] = 1
    countRefs(st.refs, copy)
  end
  local buf = {}
  renderLossless(copy, 0, buf, st)
  return table.concat(buf)
end

function serialize.serialize(root, options)
  options = options or {}
  if options.lossless then return serializeLossless(root, options) end
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

serialize.MAX_DEPTH = MAX_DEPTH
serialize.exactNumber = exactNumber

setmetatable(serialize, {
  __call = function(_, root, options) return serialize.serialize(root, options) end,
})

return serialize
