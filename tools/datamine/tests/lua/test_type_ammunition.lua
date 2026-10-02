-- Slot 4 of type_ammunition becomes the projectile name, like ws_type, and the
-- tuple is written whole: when it is the missile's own wsTypeOfWeapon table,
-- when it recurs in one record, and when the launcher is a metatable proxy of
-- a GT_t template (scalar slots only reachable through __index).
-- Usage: lua5.1 test_type_ammunition.lua <tests/lua dir> <writedir/ with the hook in Scripts/Hooks>
local here = assert(arg[1], 'usage: test_type_ammunition.lua <tests-lua-dir> <writedir/>')
WRITEDIR = assert(arg[2], 'usage: test_type_ammunition.lua <tests-lua-dir> <writedir/>')
dofile(here .. '/stub_env.lua')

__DCS_VERSION__ = '9.9.9.4'

-- A missile declared the DCS way: wsTypeOfWeapon and ws_type are one table.
local hq7Type = { 4, 4, 34, 50 }
_G.HQ_7 = { name = 'HQ-7', ws_type = hq7Type, wsTypeOfWeapon = hq7Type }
_G.rockets = {
  HQ_7 = _G.HQ_7,
  M9 = { name = '9M331', ws_type = { 4, 4, 34, 51 } },
  SM2 = { name = 'SM_2', ws_type = { 4, 4, 34, 52 } },
  A1 = { name = 'AMB-1', ws_type = { 4, 4, 34, 60 } },
}
_G.weapons_table = { weapons = { missiles = {
  A2 = { name = 'AMB-2', ws_type = { 4, 4, 34, 60 } },
} } }

-- Like DCS set_recursive_metatable: nested tables become raw proxies, scalars
-- stay behind __index, so pairs() over a proxy tuple yields nothing.
local function proxy(src)
  local t = {}
  for k, v in pairs(src) do
    if type(v) == 'table' then t[k] = proxy(v) end
  end
  return setmetatable(t, { __index = src })
end

local torLN = { distanceMax = 12000, PL = { { ammo_capacity = 8, type_ammunition = { 4, 4, 34, 51 } } } }
local sm2 = { 4, 4, 34, 52 }

_G.db = { Units = {
  GT_t = { LN_t = { _9A330 = torLN } },
  Cars = { Car = {
    -- Shared table: the launcher's ammunition IS the missile's wsTypeOfWeapon.
    { type = 'HQ-7_LN', WS = { { LN = { { PL = { { type_ammunition = _G.HQ_7.wsTypeOfWeapon } } } } } } },
    -- Proxy of a GT_t template (the {[4] = "Redacted"} shape of old dumps).
    { type = 'Tor 9A331', WS = { { LN = { proxy(torLN) } } } },
    { type = 'AMB_LN', WS = { { LN = { { PL = { { type_ammunition = { 4, 4, 34, 60 } } } } } } } },
    { type = 'UNK_LN', WS = { { LN = { { PL = { { type_ammunition = { 4, 4, 34, 999 } } } } } } } },
    { type = 'STR_LN', WS = { { LN = { { PL = { { type_ammunition = 'weapons.missiles.SA2V755' } } } } } } },
    { type = 'ADAPTER', adapter_type = { 4, 4, 34, 51 }, attribute = { 4, 4, 34, 51 } },
  } },
  Ships = { Ship = {
    -- One tuple table shared by three PL entries of one record.
    { type = 'CG', WS = { { LN = { { PL = {
      { type_ammunition = sm2 }, { type_ammunition = sm2 }, { type_ammunition = sm2 },
    } } } } } },
  } },
} }
dofile(WRITEDIR .. 'Scripts/Hooks/dump-globals.lua')

local G = WRITEDIR .. 'DCS.Lua.Exporter/_G/'
local function load(rel)
  local f = assert(io.open(G .. rel), rel)
  local text = f:read('*a')
  f:close()
  return assert(loadstring('return ' .. text:match('^[^\n]- = (.*)$')))()
end
local function same(t, expect, what)
  assert(type(t) == 'table', what .. ': not a table')
  local n = 0
  for _ in pairs(t) do n = n + 1 end
  assert(n == #expect, what .. ': ' .. n .. ' keys, want ' .. #expect)
  for i, v in ipairs(expect) do
    assert(t[i] == v, what .. ' slot ' .. i .. ': ' .. tostring(t[i]) .. ' ~= ' .. tostring(v))
  end
end
local function ammo(rel, pl)
  return load(rel).WS[1].LN[1].PL[pl or 1].type_ammunition
end

same(ammo('db/Units/Cars/Car/HQ-7_LN.lua'), { 4, 4, 34, 'HQ-7' }, 'shared wsTypeOfWeapon table')
local hq7 = load('rockets/HQ-7.lua')
same(hq7.ws_type, { 4, 4, 34, 'HQ-7' }, 'missile ws_type')
same(hq7.wsTypeOfWeapon, { 4, 4, 34, 'HQ-7' }, 'missile wsTypeOfWeapon')
same(ammo('db/Units/Cars/Car/Tor 9A331.lua'), { 4, 4, 34, '9M331' }, 'proxy launcher')
-- The proxy launcher's inherited scalars are written too.
local torUnitLN = load('db/Units/Cars/Car/Tor 9A331.lua').WS[1].LN[1]
assert(torUnitLN.distanceMax == 12000, 'proxy launcher distanceMax')
assert(torUnitLN.PL[1].ammo_capacity == 8, 'proxy launcher ammo_capacity')
same(load('db/Units/GT_t/LN_t/_9A330.lua').PL[1].type_ammunition, { 4, 4, 34, '9M331' }, 'GT_t template')
same(ammo('db/Units/Cars/Car/AMB_LN.lua'), { 4, 4, 34, 'Redacted' }, 'ambiguous')
same(ammo('db/Units/Cars/Car/UNK_LN.lua'), { 4, 4, 34, 'Redacted' }, 'unmapped')
assert(ammo('db/Units/Cars/Car/STR_LN.lua') == 'weapons.missiles.SA2V755', 'string ammunition')
for pl = 1, 3 do
  same(ammo('db/Units/Ships/Ship/CG.lua', pl), { 4, 4, 34, 'SM_2' }, 'recurring tuple PL ' .. pl)
end
local adapter = load('db/Units/Cars/Car/ADAPTER.lua')
same(adapter.adapter_type, { 4, 4, 34, 'Redacted' }, 'adapter_type still redacted')
same(adapter.attribute, { 4, 4, 34, 'Redacted' }, 'attribute still redacted')
assert(hq7Type[4] == 50 and torLN.PL[1].type_ammunition[4] == 51, 'live _G mutated')
print('TYPE_AMMUNITION TEST PASSED')
