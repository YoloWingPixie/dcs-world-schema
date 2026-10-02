-- _G/__wstype_ids__.lua holds the raw numeric tuples the record files redact:
-- unit attribute and type_ammunition (also behind GT_t proxies), launcher
-- attribute and projectile ws_type; records without a numeric tuple are absent.
-- Usage: lua5.1 test_wstype_ids.lua <tests/lua dir> <writedir/ with the hook in Scripts/Hooks>
local here = assert(arg[1], 'usage: test_wstype_ids.lua <tests-lua-dir> <writedir/>')
WRITEDIR = assert(arg[2], 'usage: test_wstype_ids.lua <tests-lua-dir> <writedir/>')
dofile(here .. '/stub_env.lua')

__DCS_VERSION__ = '9.9.9.6'

_G.rockets = {
  M311 = { name = '9M311', ws_type = { 4, 4, 34, 90 } },
}
_G.weapons_table = { weapons = { missiles = {
  -- The same name on a second tuple: both are kept.
  M311 = { name = '9M311', ws_type = { 4, 4, 35, 90 } },
} } }

local function proxy(src)
  local t = {}
  for k, v in pairs(src) do
    if type(v) == 'table' then t[k] = proxy(v) end
  end
  return setmetatable(t, { __index = src })
end

local ln2S6 = { PL = { { type_ammunition = { 4, 4, 11, 90 } } } }
_G.db = { Units = {
  GT_t = { LN_t = { _2S6 = ln2S6 } },
  Cars = { Car = {
    { type = '2S6 Tunguska', attribute = { 2, 16, 103, 29, 'SAM TR', 'AAA' },
      WS = { { LN = { proxy(ln2S6) } }, { LN = { { PL = { { type_ammunition = { 4, 4, 11, 90 } } } } } } } },
    -- Placeholder slot 4: nothing numeric to record.
    { type = 'NEW_UNIT', attribute = { 2, 16, 101, '</WSTYPE>', 'SAM SR' } },
    -- A nested `attribute` is not the unit's.
    { type = 'NESTED', Sensors = { attribute = { 9, 9, 9, 9 } } },
  } },
} }
_G.launcher = {
  ['{R-73}'] = { CLSID = '{R-73}', attribute = { 4, 4, 7, 72 } },
}
dofile(WRITEDIR .. 'Scripts/Hooks/dump-globals.lua')

local G = WRITEDIR .. 'DCS.Lua.Exporter/_G/'
local function load(rel)
  local f = assert(io.open(G .. rel), rel)
  local text = f:read('*a')
  f:close()
  return assert(loadstring('return ' .. text:match('^[^\n]- = (.*)$')))()
end
local function tuples(list, expect, what)
  assert(type(list) == 'table' and #list == #expect, what .. ': ' .. tostring(list and #list))
  for i, t in ipairs(expect) do
    for j = 1, 4 do
      assert(list[i][j] == t[j], what .. ' tuple ' .. i .. ' slot ' .. j .. ': ' .. tostring(list[i][j]))
    end
  end
end

local ids = load('__wstype_ids__.lua')
tuples(ids.units['2S6 Tunguska'], { { 2, 16, 103, 29 } }, 'unit attribute')
tuples(ids.ammunition['2S6 Tunguska'], { { 4, 4, 11, 90 } }, 'unit type_ammunition (proxy and plain, deduplicated)')
tuples(ids.projectiles['9M311'], { { 4, 4, 34, 90 }, { 4, 4, 35, 90 } }, 'projectile ws_type')
tuples(ids.stores['{R-73}'], { { 4, 4, 7, 72 } }, 'launcher attribute')
assert(ids.units.NEW_UNIT == nil, 'placeholder slot 4 recorded')
assert(ids.units.NESTED == nil, 'nested attribute recorded')
assert(ids.units._2S6 == nil and ids.ammunition._2S6 == nil, 'GT_t template recorded')
-- The record files still redact the ids.
assert(load('db/Units/Cars/Car/2S6 Tunguska.lua').attribute[4] == 'Redacted', 'unit attribute not redacted')
assert(load('launcher/{R-73}.lua').attribute[4] == 'Redacted', 'launcher attribute not redacted')
assert(io.open(G .. '__DCS_VERSION__.lua'), 'version marker missing')
print('WSTYPE IDS TEST PASSED')
