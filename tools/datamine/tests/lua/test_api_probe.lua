-- The argument probe hook against stubbed Lua states: the GameGUI state is
-- this one, the scripting and export states are tables net.dostring_in runs
-- the chunk in. test_api_probe.py writes the plan hook file and checks the
-- progress file this leaves.
-- Usage: lua5.1 test_api_probe.lua <tests/lua dir> <writedir/ with the hooks>
-- `boom` (scripting) exits the process with status 3 the first time it is
-- called, as a crash in a C function would; a second run resumes.
local here = assert(arg[1], 'usage: test_api_probe.lua <tests-lua-dir> <writedir/>')
WRITEDIR = assert(arg[2], 'usage: test_api_probe.lua <tests-lua-dir> <writedir/>')
dofile(here .. '/stub_env.lua')

__DCS_VERSION__ = '9.9.9.7'
local modelTime = 0
local callbacks
DCS.getModelTime = function() return modelTime end
DCS.setUserCallbacks = function(t) callbacks = t end

local function exists(p) local f = io.open(p); if f then f:close() end; return f ~= nil end
local function touch(p) local f = assert(io.open(p, 'w')); f:close() end
-- A denied function records that it was called.
local function called(name) return function() touch(WRITEDIR .. 'called-' .. name) end end
local function typeName(v) return v == nil and 'no value' or type(v) end
local function check(n, t, v)
  if type(v) ~= t then
    error(string.format("bad argument #%d to '?' (%s expected, got %s)", n, t, typeName(v)), 0)
  end
end
local realExit = os.exit

local function baseEnv()
  local env = {
    assert = assert, error = error, ipairs = ipairs, next = next, pairs = pairs,
    pcall = pcall, rawget = rawget, select = select, setmetatable = setmetatable,
    getmetatable = getmetatable, tonumber = tonumber, tostring = tostring, type = type,
    unpack = unpack, math = math, string = string, table = table, debug = debug,
    loadstring = loadstring, os = { remove = os.remove, exit = os.exit },
  }
  env._G = env
  return env
end

-- Mission scripting state: enough of the API for setupMission's airbase and
-- aircraft; the other sample steps fail and are reported.
local s = baseEnv()
local function class(name)
  local c = { className_ = name }
  c.__index = c
  return c
end
local Airbase, Unit, Group, Weapon = class('Airbase'), class('Unit'), class('Group'), class('Weapon')
Airbase.Category = { AIRDROME = 0 }
local ab = setmetatable({}, Airbase)
function Airbase.getDesc() return { category = 0 } end
function Airbase.getName() return 'Batumi' end
function Airbase.getPoint() return { x = 0, y = 10, z = 0 } end
function Airbase.getByName(name) return name == 'Batumi' and ab or nil end
local spawned = {}
Group.Category = { AIRPLANE = 0, GROUND = 2 }
function Group.getByName(name)
  check(1, 'string', name)
  return spawned[name] and setmetatable({ name = name }, Group) or nil
end
function Unit.getByName(name)
  return spawned[(name:gsub('%-1$', ''))] and setmetatable({ name = name }, Unit) or nil
end
function Unit.getName(self)
  if self == nil then error('Parameter #self missed', 0) end
  if getmetatable(self) ~= Unit then error("calling 'getName' on bad self (Unit expected, got table)", 0) end
  return self.name
end
function Weapon.isExist() return true end
function Weapon.getLauncher(self)
  if self == nil then error('Parameter #self missed', 0) end
  if getmetatable(self) ~= Weapon then error('Parameter #self missed', 0) end
  return Unit.getByName('probe-air-1')
end
local shotHandler
s.Airbase, s.Unit, s.Group, s.Weapon = Airbase, Unit, Group, Weapon
s.world = {
  getAirbases = function() return { ab } end,
  addEventHandler = function(h) shotHandler = h end,
  event = { S_EVENT_SHOT = 1 },
}
s.country = { id = { USA = 2 } }
s.coalition = { addGroup = function(_, _, g) spawned[g.name] = true end }
s.trigger = { action = { outText = function(text, t) check(1, 'string', text); check(2, 'number', t) end } }
s.env = { crash = called('env.crash'), info = function(m) check(1, 'string', m) end }
s.alias = s.env.crash
s.boom = function()
  local marker = WRITEDIR .. 'boom-once'
  if not exists(marker) then
    touch(marker)
    realExit(3)
  end
  return 1
end
s.writer = function() s.os.remove('x') end

local export = baseEnv()
export.LoGetModelTime = function() return modelTime end

-- GameGUI state (this one).
net.stop_game = called('net.stop_game')
function _G.hooksFn(n) check(1, 'number', n); return n end

local states = { scripting = s, export = export }
net.dostring_in = function(state, code)
  local env = states[state]
  if not env then return 'Lua state "' .. tostring(state) .. '" not found', false end
  local fn = assert(loadstring(code))
  setfenv(fn, env)
  return fn(), true
end

dofile(WRITEDIR .. 'Scripts/Hooks/api-probe.lua')
assert(callbacks and callbacks.onSimulationStart and callbacks.onSimulationFrame, 'callbacks not set')

local done = WRITEDIR .. 'DCS.Lua.Exporter/probe/done'
callbacks.onSimulationStart()
for frame = 1, 600 do
  modelTime = frame * 0.5
  if modelTime == 40 and shotHandler then
    shotHandler:onEvent({ id = 1, weapon = setmetatable({}, Weapon) })
  end
  callbacks.onSimulationFrame()
  if exists(done) then break end
end
assert(exists(done), 'probe did not finish')
local f = assert(io.open(done)); assert(f:read('*a') == '9.9.9.7'); f:close()
print('API PROBE TEST DONE')
