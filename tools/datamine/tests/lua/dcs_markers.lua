-- `__dcs` marker functions for loading dump format 4 text under plain Lua.
--   local M = dofile('dcs_markers.lua')
--   M.default()   -> __dcs, reset: the extractors' view (lua_reader.py's
--                    default reading): anchors and refs resolve to the same
--                    table, a cycle back-reference is absent, redacted ->
--                    "Redacted", number markers -> numbers (NaN absent), every
--                    other marker absent.
--   M.load(text)  -> the value of `<target> = <value>` text read losslessly:
--                    numbers exact (nan, inf, -0), anchors and refs (cycles
--                    too) as shared tables, other markers as M.FUNCTION, ...
--                    tables or { marker = kind, ... } for unknown kinds.
local M = {}

local NUMBERS = { inf = math.huge, ['-inf'] = -math.huge }
local function number(value)
  if value == 'nan' then return 0 / 0 end
  if value == '-0' then local z = 0; return -z end
  return assert(NUMBERS[value], 'number marker ' .. tostring(value))
end
M.number = number

function M.default()
  local anchors = {}
  local function dcs(t)
    local kind = t.kind
    if kind == 'anchor' then
      anchors[t.id] = t.value
      return t.value
    elseif kind == 'ref' then
      return anchors[t.id]
    elseif kind == 'redacted' then
      return 'Redacted'
    elseif kind == 'number' then
      local v = number(t.value)
      if v ~= v then return nil end
      return v
    end
    return nil
  end
  return dcs, function() anchors = {} end
end

M.FUNCTION = { marker = 'function' }
M.USERDATA = { marker = 'userdata' }
M.THREAD = { marker = 'thread' }
M.REDACTED = { marker = 'redacted' }
local SINGLETONS = { ['function'] = M.FUNCTION, userdata = M.USERDATA, thread = M.THREAD,
  redacted = M.REDACTED }

function M.load(text)
  local anchors, pending = {}, {}
  local function dcs(t)
    local kind = t.kind
    if kind == 'anchor' then
      anchors[t.id] = t.value
      return t.value
    elseif kind == 'ref' then
      if anchors[t.id] then return anchors[t.id] end
      local placeholder = { pending_ref = t.id }
      pending[placeholder] = true
      return placeholder
    elseif kind == 'number' then
      return number(t.value)
    elseif SINGLETONS[kind] then
      return SINGLETONS[kind]
    end
    local copy = { marker = kind }
    for k, v in pairs(t) do if k ~= 'kind' then copy[k] = v end end
    return copy
  end
  local rhs = assert(text:match('^[^\n]- = (.*)$') or text, 'no assignment')
  local chunk = assert(loadstring('return ' .. rhs))
  setfenv(chunk, { __dcs = dcs })
  local root = chunk()
  -- Cycle back-references were written before their anchor completed.
  local seen = {}
  local function fix(v)
    if type(v) ~= 'table' then return v end
    if pending[v] then return assert(anchors[v.pending_ref], 'unresolved ref') end
    if seen[v] then return v end
    seen[v] = true
    for k, child in pairs(v) do
      local fixed = fix(child)
      if fixed ~= child then v[k] = fixed end
    end
    return v
  end
  return fix(root)
end

-- Structural equality that also checks the sharing: a table of `a` maps to
-- one table of `b` (shared tables and cycles must correspond). NaN equals NaN;
-- 0 and -0 differ.
function M.same(a, b, path, map)
  path = path or 'root'
  map = map or {}
  if type(a) ~= type(b) then error(path .. ': type ' .. type(a) .. ' vs ' .. type(b), 0) end
  if type(a) == 'number' then
    if a ~= a and b ~= b then return true end
    if a ~= b then error(path .. ': ' .. tostring(a) .. ' vs ' .. tostring(b), 0) end
    if a == 0 and (1 / a > 0) ~= (1 / b > 0) then error(path .. ': signed zero', 0) end
    return true
  end
  if type(a) ~= 'table' then
    if a ~= b then error(path .. ': ' .. tostring(a) .. ' vs ' .. tostring(b), 0) end
    return true
  end
  if map[a] then
    if map[a] ~= b then error(path .. ': sharing differs', 0) end
    return true
  end
  map[a] = b
  for k, v in pairs(a) do M.same(v, b[k], path .. '.' .. tostring(k), map) end
  for k in pairs(b) do
    if a[k] == nil then error(path .. ': extra key ' .. tostring(k), 0) end
  end
  return true
end

return M
