-- WRITE_WHOLE tables are written whole at their _G path, db.Units children
-- without records are logged, and the dump format marker precedes the
-- version marker.
-- Usage: lua5.1 test_whole_tables.lua <tests/lua dir> <writedir/ with the hook in Scripts/Hooks>
local here = assert(arg[1], 'usage: test_whole_tables.lua <tests-lua-dir> <writedir/>')
WRITEDIR = assert(arg[2], 'usage: test_whole_tables.lua <tests-lua-dir> <writedir/>')
dofile(here .. '/stub_env.lua')

__DCS_VERSION__ = '9.9.9.3'
_G.db = {
  Callnames = {
    [2] = { Air = { { Name = 'Enfield', WorldID = 1 }, { Name = 'Springfield', WorldID = 2 } } },
    [0] = { Air = { { Name = '1', WorldID = 1 } } },
  },
  callnamesRussia = { 'Russia', 'Ukraine' },
  DefaultCountry = { [1] = 0 },
  FormationID = { NO_FORMATION = 0, TRAIL = 2 },
  Units = {
    Planes = { Plane = { { type = 'A-10C' } } },
    Skills = { { Name = 'Average', WorldID = 0 }, { Name = 'Good', WorldID = 1 } },
    WWIIstructures = { WWIIstructure = {} },
  },
  roles = { observer = 'OBSERVER' },
  Targets = { Tasks = { [31] = { Planes = true, Point = false } } },
  getCallnames = function() end,
}
_G.FuzeDescriptions = { M905 = 'Mechanical, impact' }
_G.SchemeFuzeParameters = { FAB = { ED = { default_delays = { 0, 0.05 } } } }
dofile(WRITEDIR .. 'Scripts/Hooks/dump-globals.lua')

local G = WRITEDIR .. 'DCS.Lua.Exporter/_G/'
local function load(p)
  local f = assert(io.open(G .. p), 'missing ' .. p)
  local text = f:read('*a')
  f:close()
  local env = { _G = { db = { Units = {} } } }
  local chunk = assert(loadstring(text))
  setfenv(chunk, env)
  chunk()
  return env._G
end

local g = load('db/Callnames.lua')
assert(g.db.Callnames[2].Air[2].Name == 'Springfield', 'Callnames')
assert(g.db.Callnames[0].Air[1].WorldID == 1, 'Callnames country 0')
assert(load('db/callnamesRussia.lua').db.callnamesRussia[2] == 'Ukraine', 'callnamesRussia')
assert(load('db/DefaultCountry.lua').db.DefaultCountry[1] == 0, 'DefaultCountry')
assert(load('db/FormationID.lua').db.FormationID.TRAIL == 2, 'FormationID')
assert(load('db/Units/Skills.lua').db.Units.Skills[2].Name == 'Good', 'Skills')
assert(load('db/roles.lua').db.roles.observer == 'OBSERVER', 'roles')
assert(load('db/Targets.lua').db.Targets.Tasks[31].Planes == true, 'Targets')
assert(load('FuzeDescriptions.lua').FuzeDescriptions.M905 == 'Mechanical, impact', 'FuzeDescriptions')
assert(load('SchemeFuzeParameters.lua').SchemeFuzeParameters.FAB.ED.default_delays[2] == 0.05,
  'SchemeFuzeParameters')
assert(io.open(G .. 'db/Units/Planes/Plane/A-10C.lua'), 'unit record')
assert(not io.open(G .. 'db/Units/Skills/Average.lua'), 'Skills entries dumped as records')

local f = assert(io.open(G .. '__DUMP_FORMAT__.lua'), 'format marker not written')
assert(f:read('*a') == '3', 'format marker')
f:close()
assert(io.open(G .. '__DCS_VERSION__.lua'), 'version marker not written')
print('WHOLE TABLES TEST PASSED')
