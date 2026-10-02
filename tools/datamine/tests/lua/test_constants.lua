-- The hook writes the numeric DCS constant families and the country names to
-- _G/__constants__.lua, and nothing else.
-- Usage: lua5.1 test_constants.lua <tests/lua dir> <writedir/ with the hook in Scripts/Hooks>
local here = assert(arg[1], 'usage: test_constants.lua <tests-lua-dir> <writedir/>')
WRITEDIR = assert(arg[2], 'usage: test_constants.lua <tests-lua-dir> <writedir/>')
dofile(here .. '/stub_env.lua')

__DCS_VERSION__ = '9.9.9.2'
_G.wsType_Weapon = 4
_G.wsType_Missile = 4
_G.CAT_PODS = 6
_G.SENSOR_RADAR = 1
_G.OPTIC_SENSOR_IR = 2
_G.RADAR_AS = 0
_G.MODULATION_FM = 1
_G.wsType_Label = 'not a number'
_G.NOT_A_CONSTANT = 7
country = { names = { [0] = 'RUSSIA', [2] = 'USA' } }
dofile(WRITEDIR .. 'Scripts/Hooks/dump-globals.lua')

local path = WRITEDIR .. 'DCS.Lua.Exporter/_G/__constants__.lua'
local env = { _G = {} }
local chunk = assert(loadfile(path))
setfenv(chunk, env)
chunk()
local c = assert(env._G.__constants__, '__constants__ not assigned')
assert(c.wsType.wsType_Weapon == 4 and c.wsType.wsType_Missile == 4, 'wsType')
assert(c.wsType.wsType_Label == nil, 'non-numeric global captured')
assert(c.CAT.CAT_PODS == 6 and c.SENSOR.SENSOR_RADAR == 1, 'CAT/SENSOR')
assert(c.OPTIC_SENSOR.OPTIC_SENSOR_IR == 2 and c.RADAR.RADAR_AS == 0, 'OPTIC/RADAR')
assert(c.MODULATION.MODULATION_FM == 1, 'MODULATION')
assert(c.SENSOR.OPTIC_SENSOR_IR == nil, 'OPTIC_SENSOR_ leaked into SENSOR')
assert(c.country.RUSSIA == 0 and c.country.USA == 2, 'country')
for _, t in pairs(c) do
  for name in pairs(t) do assert(name ~= 'NOT_A_CONSTANT', 'unrelated global captured') end
end
print('CONSTANTS TEST PASSED')
