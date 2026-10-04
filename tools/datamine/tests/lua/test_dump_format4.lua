-- dump-globals.lua writes dump format 4: exact numbers, markers, anchors and
-- refs, numeric record keys, narrowed redactions, the format-4 whole tables
-- and _G/__inheritance__.lua. Its output tree is also the reader fixture
-- tests/fixtures/dump_format4 (test_hook.py compares them).
-- Usage: lua5.1 test_dump_format4.lua <tests/lua dir> <writedir/ with the hook in Scripts/Hooks>
local here = assert(arg[1], 'usage: test_dump_format4.lua <tests-lua-dir> <writedir/>')
WRITEDIR = assert(arg[2], 'usage: test_dump_format4.lua <tests-lua-dir> <writedir/>')
local stub = dofile(here .. '/stub_env.lua')
local M = dofile(here .. '/dcs_markers.lua')

__DCS_VERSION__ = '9.9.9.4'
local z = 0

local warhead = { expl_mass = 21.5, caliber = 127, other_factors = { 1, 1, 1 } }
_G.warheads = { TEST_WH = warhead }

-- A table the missile uses twice (an anchor) and a cycle back to the record.
local fins = { 0.3490658503988659, 0.1 + 0.2 }
local aam = {
  name = 'TEST_AAM',
  display_name = 'Test AAM',
  ws_type = { 4, 4, 7, 2001 },
  warhead = warhead,
  shape_table_data = { { name = 'test_aam', file = 'test_aam', index = 2001, life = 1 } },
  modes = { index = 3 },
  fm = {
    mass = 85.5, caliber = 0.127, I = 1 / 12 * 85.5 * 2.87 ^ 2,
    cx_coeff = { 1, 0.39, 0.38, 0.236, 1.31 }, fins = fins,
  },
  actuator = { max_delta = math.rad(20), fins = fins },
  controller = { boost_start = 0.5, tiny = 1e-300, big = 2 ^ 53 },
  get_mass = function() end,
  negzero = -z,
  flag = false,
  zero = 0,
  sparse = { [1] = 'a', [3] = 'c', [10] = 'j' },
  -- selene: allow(mixed_table) -- the dump's mixed-table case
  mixed = { 'x', 'y', mode = 'z', [2.5] = 'half', [true] = 'yes' },
  empty = {},
}
aam.controller.owner = aam
_G.weapons_table = { weapons = { missiles = { TEST_AAM = aam } } }

-- A rocket keyed by its own level-4 id (DCS `rockets`): key and Name withheld.
_G.rockets = {
  [2002] = {
    name = 'TEST_ROCKET', Name = 2002, ws_type = { 4, 4, 7, 2002 },
    M = 11.3, Life_Time = 30, inf = math.huge, ninf = -math.huge, nan = 0 / 0,
    thread = coroutine.create(function() end),
  },
}
_G.launcher = {
  ['{TEST-LAU}'] = {
    CLSID = '{TEST-LAU}', attribute = { 4, 4, 32, 77 }, wsTypeOfWeapon = { 4, 4, 7, 2002 },
    Elements = { { ShapeName = 'test-lau' } },
  },
}

-- A unit built from a GT_t template proxy (set_recursive_metatable).
local template = { distanceMax = 40000, reactionTime = 5, PL = { { ammo_capacity = 4 } } }
local ln = setmetatable({ reactionTime = 2 }, { __index = template })
_G.db = {
  Units = {
    Cars = { Car = { [1] = { type = 'TEST_SAM', WS = { { LN = { ln } } } } } },
    GT_t = { LN_t = { test_ln = template } },
  },
}

-- Format-4 whole tables.
_G.SchemeFMParameters = { TEST = { I = 96.52423333333333, L = 3.02 } }
_G.resource_by_unique_name = { TEST_AAM = aam, LOOSE = { only = 'here' } }
_G.TEST_CLUSTER_DATA = { name = 'TEST', scheme = { bomblets = { count = 247 } }, type_name = 'cluster' }
_G.UNRELATED_DATA = { x = 1 }
_G.Test_cells_properties = { [0] = { critical_damage = 5, args = { 213 } }, [9] = { critical_damage = 3 } }

dofile(WRITEDIR .. 'Scripts/Hooks/dump-globals.lua')

local G = WRITEDIR .. 'DCS.Lua.Exporter/_G/'
local function read(p)
  local f = assert(io.open(G .. p), 'missing ' .. p)
  local text = f:read('*a')
  f:close()
  return text
end
local function exists(p)
  local f = io.open(G .. p)
  if f then f:close() end
  return f ~= nil
end

-- Missile: exact numbers, markers, anchor/ref, cross-file ref, narrowed index.
local text = read('weapons_table/weapons/missiles/TEST_AAM.lua')
assert(text:find('^_G%["weapons_table"%]%["weapons"%]%["missiles"%]%["TEST_AAM"%] = __dcs{kind="anchor", id=1, value={'),
  'record anchor:\n' .. text)
for _, needle in ipairs({
  'max_delta = 0.3490658503988659',
  'fins = __dcs{kind="anchor", id=2, value={ 0.3490658503988659, 0.30000000000000004 }}',
  'fins = __dcs{kind="ref", id=2}',
  'owner = __dcs{kind="ref", id=1}',
  'get_mass = __dcs{kind="function"}',
  'negzero = __dcs{kind="number", value="-0"}',
  'big = 9007199254740992',
  'tiny = 1e-300',
  'warhead = "_G/warheads/TEST_WH.lua"',
  'index = __dcs{kind="redacted", reason="patch-volatile", lua_type="number"}',
  'modes = {\n\t\tindex = 3\n\t}',
  'ws_type = { 4, 4, 7, "TEST_AAM" }',
}) do
  assert(text:find(needle, 1, true), 'missing ' .. needle .. ' in\n' .. text)
end
local back = M.load(text)
assert(back.actuator.fins == back.fm.fins and back.controller.owner == back, 'sharing lost')
assert(back.fm.I == 1 / 12 * 85.5 * 2.87 ^ 2, 'fm.I not exact')
assert(back.shape_table_data[1].index == M.REDACTED and back.get_mass == M.FUNCTION, 'markers')

-- The extractors' view (stub_env's __dcs) is format 3's.
stub.dcs_reset()
local view = assert(loadstring('return ' .. text:match('^[^\n]- = (.*)$')))()
assert(view.shape_table_data[1].index == 'Redacted' and view.get_mass == nil, 'default view')
assert(view.controller.owner == nil and view.actuator.fins[1] == math.rad(20), 'default view cycle')

-- Rocket: key withheld (it is the level-4 id), Name redacted, specials.
local rocket = read('rockets/TEST_ROCKET.lua')
assert(rocket:find('^_G%["rockets"%]%["#Index"%] = {'), 'rocket key:\n' .. rocket)
for _, needle in ipairs({
  'Name = __dcs{kind="redacted", reason="patch-volatile", lua_type="number"}',
  'inf = __dcs{kind="number", value="inf"}',
  'nan = __dcs{kind="number", value="nan"}',
  'ninf = __dcs{kind="number", value="-inf"}',
  'thread = __dcs{kind="thread"}',
  'M = 11.3',
}) do
  assert(rocket:find(needle, 1, true), 'missing ' .. needle .. ' in\n' .. rocket)
end

-- Unit: numeric key kept, proxy flattened, inheritance in the sidecar.
local unit = read('db/Units/Cars/Car/TEST_SAM.lua')
assert(unit:find('^_G%["db"%]%["Units"%]%["Cars"%]%["Car"%]%[1%] = {'), 'unit key:\n' .. unit)
local u = M.load(unit)
assert(u.WS[1].LN[1].reactionTime == 2 and u.WS[1].LN[1].distanceMax == 40000, 'proxy flattened')
local inh = M.load(read('__inheritance__.lua'))
local entry = inh['_G/db/Units/Cars/Car/TEST_SAM.lua'][1]
M.same({ path = { 'WS', 1, 'LN', 1 }, own = { 'reactionTime' },
  chain = { { 'db', 'Units', 'GT_t', 'LN_t', 'test_ln' } } }, entry, 'inheritance entry')

-- Format-4 whole tables; records inside REF_RECORDS tables become path refs.
assert(M.load(read('SchemeFMParameters.lua')).TEST.I == 96.52423333333333, 'SchemeFMParameters')
local res = M.load(read('resource_by_unique_name.lua'))
assert(res.TEST_AAM == '_G/weapons_table/weapons/missiles/TEST_AAM.lua' and res.LOOSE.only == 'here',
  'resource_by_unique_name')
assert(M.load(read('TEST_CLUSTER_DATA.lua')).scheme.bomblets.count == 247, 'cluster data')
assert(M.load(read('Test_cells_properties.lua'))[0].critical_damage == 5, 'cells')
assert(not exists('UNRELATED_DATA.lua'), 'unrelated _DATA table dumped')

local f = assert(io.open(G .. '__DUMP_FORMAT__.lua'))
assert(f:read('*a') == '4', 'format marker')
f:close()
assert(exists('__DCS_VERSION__.lua'), 'version marker not written')
print('DUMP FORMAT 4 TEST PASSED')
