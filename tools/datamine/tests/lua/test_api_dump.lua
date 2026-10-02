-- The API dump hook against stubbed Lua states: the GameGUI state is this
-- one, the scripting, server and export states are tables net.dostring_in
-- runs the chunk in. test_hook.py checks the JSON files it writes.
-- Usage: lua5.1 test_api_dump.lua <tests/lua dir> <writedir/ with the hooks> <mode>
--   mode: ok | export_unavailable | export_raises | no_debug | server_is_scripting
local here = assert(arg[1], 'usage: test_api_dump.lua <tests-lua-dir> <writedir/> <mode>')
WRITEDIR = assert(arg[2], 'usage: test_api_dump.lua <tests-lua-dir> <writedir/> <mode>')
local mode = assert(arg[3], 'mode')
dofile(here .. '/stub_env.lua')

__DCS_VERSION__ = '9.9.9.7'
lfs.currentdir = function() return 'C:/DCS World/' end
local modelTime = 0
local callbacks
DCS.getModelTime = function() return modelTime end
DCS.setUserCallbacks = function(t) callbacks = t end
DCS.getVersion = function() return '9.9.9.7' end

local function baseEnv()
  local env = {
    assert = assert, error = error, ipairs = ipairs, next = next, pairs = pairs,
    pcall = pcall, rawget = rawget, select = select, setmetatable = setmetatable,
    getmetatable = getmetatable, tonumber = tonumber, tostring = tostring, type = type,
    unpack = unpack, math = math, string = string, table = table,
    debug = mode ~= 'no_debug' and debug or nil,
  }
  env._G = env
  return env
end

-- Mission scripting state: classes, a shared table, a cycle, odd values.
local scripting = baseEnv()
local Object = { className_ = 'Object', parentClass_ = { className_ = 'void' } }
function Object.isExist() end
local CoalitionObject = { className_ = 'CoalitionObject', parentClass_ = Object }
function CoalitionObject.getCoalition() end
local Unit = { className_ = 'Unit', parentClass_ = CoalitionObject,
               Category = { AIRPLANE = 0, HELICOPTER = 1 } }
function Unit.getByName() end
setmetatable(Unit, { __index = CoalitionObject })
scripting.Object, scripting.CoalitionObject, scripting.Unit = Object, CoalitionObject, Unit
local shared = { a = 1 }
local loop = { name = 'loop' }
loop.self = loop
-- A function at every level, so each is an API table (see api-walk.lua).
local deep, node = {}, nil
node = deep
for i = 1, 8 do
  local nextNode = { f = function() end }
  node['l' .. i] = nextNode
  node = nextNode
end
local data = {}
for i = 1, 600 do data[i] = i end
scripting.misc = {
  shared1 = shared, shared2 = shared, loop = loop,
  inf = math.huge, ninf = -math.huge, nan = 0 / 0,
  [1] = 'one', ['1'] = 'string one', [2.5] = 'half',
  [true] = 'boolean key',
  bad = 'caf\233', utf = 'caf\195\169', ctl = 'a\0b\n',
  deep = deep,
  luaFn = function() end,
  big = 2 ^ 40, frac = 0.1,
  long = string.rep('x', 5000),
  data = data,
  records = { { name = 'a', list = data }, { name = 'b' } },
  enum = { A = 1, B = { C = 'c', D = { E = { F = { G = 1 } } } } },
  tooDeep = { a = { b = { c = { d = { e = { f = 1 } } } } } },
  str = string,
  obj = setmetatable({ x = 1 }, { __index = { get = function() end } }),
  -- A big record with a callback two tables down (as a gun mount's supply.get_mass).
  records2 = { { supply = { get_mass = function() end }, list = data } },
}
scripting.env = { info = function() end }

-- Server and export states.
local server = baseEnv()
server.net = { get_player_list = function() end }
local export = baseEnv()
export.LoGetModelTime = function() end
export.LoGetSelfData = function() end

-- GameGUI state (this one).
_G.Export = { LoGetModelTime = function() end }
_G.guiTable = { answer = 42 }

local mission = baseEnv()
mission.mission = { theatre = 'Caucasus' }
mission.a_do_script = function() return '' end
if mode == 'server_is_scripting' then server = scripting end
local states = { scripting = scripting, server = server, export = export,
                 mission = mission, gui = _G }
local calls = {}
net.dostring_in = function(state, code)
  if code:find('W.dump', 1, true) then calls[#calls + 1] = state end
  if state == 'config' then return 'Lua state "config" not found', false end
  if state == 'export' and mode == 'export_unavailable' then
    return 'Lua state "export" not found', false
  end
  if state == 'export' and mode == 'export_raises' then error('no such state') end
  local env = assert(states[state], 'unexpected state ' .. tostring(state))
  local fn = assert(loadstring(code))
  setfenv(fn, env)
  return fn(), true
end

dofile(WRITEDIR .. 'Scripts/Hooks/api-dump.lua')
assert(callbacks and callbacks.onSimulationStart and callbacks.onSimulationFrame, 'callbacks not set')

local out = WRITEDIR .. 'DCS.Lua.Exporter/api/'
local function exists(p) local f = io.open(p); if f then f:close() end; return f ~= nil end

callbacks.onSimulationFrame()
callbacks.onSimulationStart()
modelTime = 0.5
callbacks.onSimulationFrame()
assert(#calls == 0 and not exists(out .. 'done'), 'ran before settling')
modelTime = 1.5
callbacks.onSimulationFrame()
local walked = mode == 'server_is_scripting' and 'scripting,export' or 'scripting,server,export'
if mode:find('^export_') then walked = 'scripting,server' end
assert(table.concat(calls, ',') == walked, 'states: ' .. table.concat(calls, ','))
local f = assert(io.open(out .. 'done')); assert(f:read('*a') == '9.9.9.7'); f:close()
-- Only once.
local n = #calls
callbacks.onSimulationFrame()
assert(#calls == n)
print('API DUMP TEST DONE')
