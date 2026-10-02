--[[----------------------------------------------------------------------------
  api-walk.lua - walks a Lua environment's globals into deterministic JSON.

  A module (returns a table, no side effects), so DCS running it as a GameGUI
  hook does nothing. api-dump.lua calls it directly for the GameGUI env and
  embeds its source in the chunks it runs through net.dostring_in for the
  other Lua states; there dump() returns the JSON text to the caller. It never
  calls a DCS function or triggers a metamethod: tables are read with next and
  rawget, metatables with debug.getmetatable when available.

  API-only walk. The dump describes the API (functions, classes, metatables and
  their constants), not the data a state has loaded:
    - An API table has a function among its values or its metatable's
      values, or among those of a table up to apiDepth levels below (values
      and metatable values are followed; keys are not). apiDepth 1 makes a
      namespace of modules or classes API, and leaves out data records that
      carry a callback deep inside (weapons' gun mount supply.get_mass). At
      most scanBudget entries are read per table; a table whose search ends
      there without a function counts as data.
    - A data table (not an API table) is walked only when it is small: at
      most enumEntries entries in all, nested at most enumDepth tables deep
      (the table's members are depth 1). That keeps constant tables such as
      AI.Option, world.event and coalition.side. Any other data table is
      summarised as { type = "table", summary = "data", entries = <its key
      count> }; what is below it is not read.
    - Scalars (numbers, strings, booleans) in walked tables are always kept.
  Each table is written once. The first time it is reached it is walked (or
  summarised); every later occurrence is { type = "table", ref = <path> } of
  that place. Global tables come first: a table that is the value of a global
  is owned by the global's name (the first name in byte order when several
  globals hold it, standard-library globals included, so `string` reached
  inside another table is ref = "string"); any other table by its first path
  in walk order (globals in byte order, members in the order below, a table's
  metatable after its members). A cycle is a ref to its ancestor. A table cut
  by maxDepth or maxTables is not owned, so a later, shallower occurrence is
  walked in full.

  dump(env, opts) -> JSON text of one object (keys sorted at every level):

    excluded     sorted names of env's standard-library globals (STDLIB) that
                 are present; they are not walked
    globals      { <name> = NODE } for every other string key of env
    limits       { maxDepth, maxTables, maxString, apiDepth, scanBudget,
                 enumEntries, enumDepth }
    skippedKeys  { <key type> = count } of env keys that are not strings
    stats        { tables, refs, summarised, truncatedDepth, truncatedBudget }

  opts: maxDepth (default 8), maxTables (tables walked per global, default
  20000, so one huge global cannot starve the rest), maxString (default 4096),
  apiDepth (default 1), scanBudget (default 200000), enumEntries (default 500),
  enumDepth (default 4: AI.Option.Air.val.ROE is 4 below AI).

  A NODE is an object with `type` (the Lua type) and, by type:
    number    value; a non-finite value is the string "inf", "-inf" or "nan"
              with nonFinite = true
    string    value (invalid UTF-8 bytes as U+00XX with invalidUtf8 = true);
              one longer than maxString is cut, with truncated = "length" and
              length = its byte length
    boolean   value
    function  what = "C" | "Lua" | "main" (debug.getinfo), for Lua functions
              source, linedefined, lastlinedefined; what = "unknown" without
              debug.getinfo
    table     members = [ { key, keyType = "number" | "string", value = NODE } ]
              (number keys ascending, then string keys in byte order),
              skippedKeys = { <key type> = count } of other keys,
              className / parentClass: the table's className_ string and its
              parentClass_'s className_ (or parentClass_ when a string),
              metatable = NODE of its metatable.
              Instead of members: ref = <path> (written there, see above);
              summary = "data" with entries (see above); truncated = "depth"
              with size = key count at maxDepth; truncated = "budget" once
              maxTables tables of its global were walked.
    userdata, thread: metatable = NODE when it has one.

  A path is the global's name, then `.key` for identifier keys, `[n]` for
  number keys, `["key"]` otherwise and `<metatable>` for a metatable.
------------------------------------------------------------------------------]]

local M = {}

M.STDLIB = {
  '_G', '_VERSION', 'assert', 'bit', 'bit32', 'collectgarbage', 'coroutine',
  'debug', 'dofile', 'error', 'gcinfo', 'getfenv', 'getmetatable', 'io',
  'ipairs', 'jit', 'load', 'loadfile', 'loadstring', 'math', 'module',
  'newproxy', 'next', 'os', 'package', 'pairs', 'pcall', 'print', 'rawequal',
  'rawget', 'rawlen', 'rawset', 'require', 'select', 'setfenv', 'setmetatable',
  'string', 'table', 'tonumber', 'tostring', 'type', 'unpack', 'utf8', 'xpcall',
}

local DEFAULTS = {
  maxDepth = 8, maxTables = 20000, maxString = 4096,
  apiDepth = 1, scanBudget = 200000, enumEntries = 500, enumDepth = 4,
}

local type, next, rawget, tostring, tonumber = type, next, rawget, tostring, tonumber
local pairs, ipairs, pcall, setmetatable = pairs, ipairs, pcall, setmetatable
local format, byte, char, sub, find, gsub =
  string.format, string.byte, string.char, string.sub, string.find, string.gsub
local sort, concat, floor, huge = table.sort, table.concat, math.floor, math.huge
local dbg = type(debug) == 'table' and debug or nil
local getmt = (dbg and dbg.getmetatable) or getmetatable
local getinfo = dbg and dbg.getinfo

local ESC = { ['"'] = '\\"', ['\\'] = '\\\\', ['\b'] = '\\b', ['\f'] = '\\f',
              ['\n'] = '\\n', ['\r'] = '\\r', ['\t'] = '\\t' }
for i = 0, 31 do
  local c = char(i)
  if not ESC[c] then ESC[c] = format('\\u%04x', i) end
end
ESC[char(127)] = '\\u007f'

-- s as a JSON string literal; bytes that are not valid UTF-8 become \u00XX.
local function jsonString(s)
  local body = s:gsub('[%c"\\]', ESC)
  if not find(body, '[\128-\255]') then return '"' .. body .. '"', false end
  local out, i, n, bad = {}, 1, #body, false
  while i <= n do
    local c = byte(body, i)
    local len = (c < 0x80 and 1) or (c >= 0xC2 and c <= 0xDF and 2)
      or (c >= 0xE0 and c <= 0xEF and 3) or (c >= 0xF0 and c <= 0xF4 and 4) or 0
    local ok = len > 0 and i + len - 1 <= n
    if ok and len > 1 then
      for j = i + 1, i + len - 1 do
        local d = byte(body, j)
        if d < 0x80 or d > 0xBF then ok = false break end
      end
      local d = byte(body, i + 1)
      if ok and ((c == 0xE0 and d < 0xA0) or (c == 0xED and d > 0x9F)
          or (c == 0xF0 and d < 0x90) or (c == 0xF4 and d > 0x8F)) then
        ok = false
      end
    end
    if ok then
      out[#out + 1] = sub(body, i, i + len - 1)
      i = i + len
    else
      out[#out + 1] = format('\\u%04x', c)
      bad = true
      i = i + 1
    end
  end
  return '"' .. concat(out) .. '"', bad
end

local function jsonNumber(v)
  if v ~= v then return nil, 'nan' end
  if v == huge then return nil, 'inf' end
  if v == -huge then return nil, '-inf' end
  -- %.0f, not %d: %d casts to a C long, 32-bit on Windows.
  if v == floor(v) and v > -2^53 and v < 2^53 then return format('%.0f', v) end
  -- DCS may run under a C locale with a decimal comma.
  return (gsub(format('%.17g', v), ',', '.'))
end

local function isIdent(s)
  return find(s, '^[%a_][%w_]*$') ~= nil
end

local function childPath(path, k, kt)
  if kt == 'number' then return path .. '[' .. (jsonNumber(k) or tostring(k)) .. ']' end
  if isIdent(k) then return path .. '.' .. k end
  return path .. '[' .. (jsonString(k)) .. ']'
end

-- Keys of t: numbers ascending, then strings; counts of other key types.
local function sortedKeys(t)
  local nums, strs, skipped = {}, {}, nil
  for k in next, t do
    local kt = type(k)
    if kt == 'number' and k == k then
      nums[#nums + 1] = k
    elseif kt == 'string' then
      strs[#strs + 1] = k
    else
      skipped = skipped or {}
      skipped[kt] = (skipped[kt] or 0) + 1
    end
  end
  sort(nums)
  sort(strs)
  return nums, strs, skipped
end

local function countKeys(t)
  local n = 0
  for _ in next, t do n = n + 1 end
  return n
end

local function writeCounts(out, counts)
  local names = {}
  for k in pairs(counts) do names[#names + 1] = k end
  sort(names)
  out[#out + 1] = '{'
  for i, k in ipairs(names) do
    out[#out + 1] = (i > 1 and ',' or '') .. jsonString(k) .. ':' .. counts[k]
  end
  out[#out + 1] = '}'
end

local function className(v)
  if type(v) ~= 'table' then return nil end
  local c = rawget(v, 'className_')
  return type(c) == 'string' and c or nil
end

local Walker = {}
Walker.__index = Walker

function Walker:emit(s) local out = self.out; out[#out + 1] = s end

function Walker:metatableField(v, path, depth)
  local ok, mt = pcall(getmt, v)
  if not ok or mt == nil then return end
  self:emit(',"metatable":')
  self:value(mt, path .. '<metatable>', depth + 1)
end

function Walker:functionNode(f)
  if not getinfo then
    self:emit('{"type":"function","what":"unknown"}')
    return
  end
  local ok, info = pcall(getinfo, f, 'S')
  if not ok or type(info) ~= 'table' then
    self:emit('{"type":"function","what":"unknown"}')
    return
  end
  local what = tostring(info.what)
  if what == 'C' then
    self:emit('{"type":"function","what":"C"}')
    return
  end
  self:emit('{"lastlinedefined":' .. (tonumber(info.lastlinedefined) or -1)
    .. ',"linedefined":' .. (tonumber(info.linedefined) or -1)
    .. ',"source":' .. (jsonString(tostring(info.source)))
    .. ',"type":"function","what":' .. (jsonString(what)) .. '}')
end

-- Whether t is an API table (see the header); kept per table.
function Walker:isApi(t)
  local known = self.api
  if known[t] ~= nil then return known[t] end
  local level, seen, budget = { t }, { [t] = true }, self.opts.scanBudget
  local found = false
  for _ = 0, self.opts.apiDepth do
    local nextLevel = {}
    local function scan(x)
      for _, v in next, x do
        local vt = type(v)
        if vt == 'function' then found = true return end
        if vt == 'table' and not seen[v] then
          seen[v] = true
          nextLevel[#nextLevel + 1] = v
        end
        budget = budget - 1
        if budget <= 0 then return end
      end
    end
    for _, x in ipairs(level) do
      scan(x)
      if found or budget <= 0 then break end
      local ok, mt = pcall(getmt, x)
      if ok and type(mt) == 'table' and not seen[mt] then
        seen[mt] = true
        scan(mt)
        if found or budget <= 0 then break end
      end
    end
    if found or budget <= 0 or #nextLevel == 0 then break end
    level = nextLevel
  end
  known[t] = found
  return found
end

-- Whether data table t is a small constant table (see the header).
function Walker:isEnum(t)
  local left, maxDepth, seen = self.opts.enumEntries, self.opts.enumDepth, {}
  local function fits(x, depth)
    seen[x] = true
    for _, v in next, x do
      left = left - 1
      if left < 0 then return false end
      if type(v) == 'table' and not seen[v] then
        if depth >= maxDepth or not fits(v, depth + 1) then return false end
      end
    end
    return true
  end
  return fits(t, 0)
end

function Walker:tableNode(t, path, depth)
  local st = self.stats
  local at = self.owner[t]
  if at and at ~= path then
    st.refs = st.refs + 1
    self:emit('{"ref":' .. (jsonString(at)) .. ',"type":"table"}')
    return
  end
  if not self:isApi(t) and not self:isEnum(t) then
    self.owner[t] = path
    st.summarised = st.summarised + 1
    self:emit('{"entries":' .. countKeys(t) .. ',"summary":"data","type":"table"}')
    return
  end
  if depth >= self.opts.maxDepth then
    st.truncatedDepth = st.truncatedDepth + 1
    self:emit('{"size":' .. countKeys(t) .. ',"truncated":"depth","type":"table"}')
    return
  end
  if self.globalTables >= self.opts.maxTables then
    st.truncatedBudget = st.truncatedBudget + 1
    self:emit('{"truncated":"budget","type":"table"}')
    return
  end
  st.tables = st.tables + 1
  self.globalTables = self.globalTables + 1
  self.owner[t] = path

  local nums, strs, skipped = sortedKeys(t)
  local cls = className(t)
  local parent = rawget(t, 'parentClass_')
  local parentName = type(parent) == 'string' and parent or className(parent)

  self:emit('{')
  if cls then self:emit('"className":' .. (jsonString(cls)) .. ',') end
  self:emit('"members":[')
  local first = true
  local function member(k, kt, key)
    self:emit((first and '' or ',') .. '{"key":' .. key .. ',"keyType":"' .. kt .. '","value":')
    first = false
    self:value(rawget(t, k), childPath(path, k, kt), depth + 1)
    self:emit('}')
  end
  for _, k in ipairs(nums) do
    local text, special = jsonNumber(k)
    member(k, 'number', text or jsonString(special))
  end
  for _, k in ipairs(strs) do member(k, 'string', (jsonString(k))) end
  self:emit(']')
  self:metatableField(t, path, depth)
  if parentName then self:emit(',"parentClass":' .. (jsonString(parentName))) end
  if skipped then
    self:emit(',"skippedKeys":')
    writeCounts(self.out, skipped)
  end
  self:emit(',"type":"table"}')
end

function Walker:value(v, path, depth)
  local vt = type(v)
  if vt == 'number' then
    local text, special = jsonNumber(v)
    if text then
      self:emit('{"type":"number","value":' .. text .. '}')
    else
      self:emit('{"nonFinite":true,"type":"number","value":"' .. special .. '"}')
    end
  elseif vt == 'string' then
    local max, cut = self.opts.maxString, nil
    if #v > max then cut, v = #v, sub(v, 1, max) end
    local text, bad = jsonString(v)
    self:emit('{' .. (bad and '"invalidUtf8":true,' or '')
      .. (cut and ('"length":' .. cut .. ',"truncated":"length",') or '')
      .. '"type":"string","value":' .. text .. '}')
  elseif vt == 'boolean' then
    self:emit('{"type":"boolean","value":' .. tostring(v) .. '}')
  elseif vt == 'function' then
    self:functionNode(v)
  elseif vt == 'table' then
    self:tableNode(v, path, depth)
  else
    self:emit('{')
    local before = #self.out
    self:metatableField(v, path, depth)
    if #self.out > before then
      self.out[before + 1] = '"metatable":'  -- drop the leading comma
      self:emit(',')
    end
    self:emit('"type":' .. (jsonString(vt)) .. '}')
  end
end

-- JSON text of env's globals (see the header).
function M.dump(env, opts)
  local o = {}
  for k, v in pairs(DEFAULTS) do o[k] = (opts and opts[k]) or v end
  local w = setmetatable({
    out = {}, opts = o, owner = {}, api = {}, globalTables = 0,
    stats = { tables = 0, refs = 0, summarised = 0, truncatedDepth = 0, truncatedBudget = 0 },
  }, Walker)
  local stdlib = {}
  for _, name in ipairs(M.STDLIB) do stdlib[name] = true end

  local nums, names, skipped = sortedKeys(env)
  if #nums > 0 then
    skipped = skipped or {}
    skipped.number = #nums
  end
  local excluded, walked = {}, {}
  for _, name in ipairs(names) do
    if stdlib[name] then excluded[#excluded + 1] = name else walked[#walked + 1] = name end
    local v = rawget(env, name)
    if type(v) == 'table' and not w.owner[v] then w.owner[v] = name end
  end

  w:emit('{"excluded":[')
  for i, name in ipairs(excluded) do w:emit((i > 1 and ',' or '') .. (jsonString(name))) end
  w:emit('],"globals":{')
  for i, name in ipairs(walked) do
    w:emit((i > 1 and ',' or '') .. (jsonString(name)) .. ':')
    w.globalTables = 0
    w:value(rawget(env, name), name, 0)
  end
  w:emit('},"limits":{"apiDepth":' .. o.apiDepth .. ',"enumDepth":' .. o.enumDepth .. ',"enumEntries":' .. o.enumEntries
    .. ',"maxDepth":' .. o.maxDepth .. ',"maxString":' .. o.maxString
    .. ',"maxTables":' .. o.maxTables .. ',"scanBudget":' .. o.scanBudget .. '},"skippedKeys":')
  writeCounts(w.out, skipped or {})
  local st = w.stats
  w:emit(',"stats":{"refs":' .. st.refs .. ',"summarised":' .. st.summarised
    .. ',"tables":' .. st.tables .. ',"truncatedBudget":' .. st.truncatedBudget
    .. ',"truncatedDepth":' .. st.truncatedDepth .. '}}')
  return concat(w.out)
end

M.jsonString = function(s) return (jsonString(s)) end

return M
