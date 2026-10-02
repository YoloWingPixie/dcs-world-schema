-- The actions probe hook against a stubbed scripting state. The stub's
-- controllers take only DCS-cased ids (Orbit, NoTask, SetInvisible, Option and
-- the wrappers), log an error line for a lower-case id and raise for an
-- unknown command; an accepted Orbit with a `point` turns the lead unit
-- towards it, an accepted StopRoute command stops it. `Boom` exits the process with status 3 the first time it is
-- set, as a crash would; a second run resumes. test_actions_probe.py writes
-- the plan hook file and checks the progress file and the printed log.
-- Usage: lua5.1 test_actions_probe.lua <tests/lua dir> <writedir/ with the hooks>
local here = assert(arg[1], 'usage: test_actions_probe.lua <tests-lua-dir> <writedir/> [out-dir]')
WRITEDIR = assert(arg[2], 'usage: test_actions_probe.lua <tests-lua-dir> <writedir/> [out-dir]')
dofile(here .. '/stub_env.lua')

__DCS_VERSION__ = '9.9.9.7'
local modelTime = 0
local callbacks
DCS.getModelTime = function() return modelTime end
DCS.setUserCallbacks = function(t) callbacks = t end

local function exists(p) local f = io.open(p); if f then f:close() end; return f ~= nil end
local function touch(p) local f = assert(io.open(p, 'w')); f:close() end
local realExit = os.exit

local ACCEPT = { Orbit = true, NoTask = true, SetInvisible = true, Option = true, Mission = true,
                 StopRoute = true }

local Unit = {}
Unit.__index = Unit
function Unit:getPoint() return { x = self.p.x, y = self.p.y, z = self.p.z } end
function Unit:getVelocity() return { x = self.v.x, y = 0, z = self.v.z } end
function Unit:getPosition() return { x = { x = 1, y = 0, z = 0 }, p = self:getPoint() } end
function Unit:turnTo(point)
  local dx, dz = point.x - self.p.x, point.y - self.p.z
  local d = math.sqrt(dx * dx + dz * dz)
  self.v = { x = 150 * dx / d, z = 150 * dz / d }
end

local function newController(unit)
  local c = { tasks = {} }
  function c:hasTask() return #self.tasks > 0 end
  function c:resetTask() self.tasks = {} end
  local function take(self, task)
    if type(task) ~= 'table' then error('bad task', 0) end
    local inner = task
    if inner.id == 'ComboTask' then inner = inner.params.tasks[1] end
    if inner.id == 'WrappedAction' then inner = inner.params.action end
    if inner.id == 'Boom' and not exists(WRITEDIR .. 'boom-once') then
      touch(WRITEDIR .. 'boom-once')
      realExit(3)
    end
    if ACCEPT[inner.id] then
      self.tasks[#self.tasks + 1] = task
      if inner.id == 'Orbit' and inner.params and inner.params.point then unit:turnTo(inner.params.point) end
      if inner.id == 'Mission' then unit.v = { x = 150, z = 0 } end
    elseif inner.id:sub(1, 1) ~= inner.id:sub(1, 1):upper() then
      log.write('SCRIPTING', log.ERROR, 'unknown task ' .. inner.id)
    end
  end
  c.setTask, c.pushTask = take, take
  function c:setCommand(cmd)
    if not ACCEPT[cmd.id] then error('unknown command ' .. tostring(cmd.id), 0) end
    if cmd.id == 'StopRoute' then unit.v = { x = 0, z = 0 } end
  end
  function c:setOption(name)
    if type(name) ~= 'number' then error('bad option name', 0) end
  end
  return c
end

local Group = {}
Group.__index = Group
local groups = {}
function Group.getByName(name)
  if type(name) ~= 'string' then error('bad name', 0) end
  if not groups[name] then
    local unit = setmetatable({ p = { x = 0, y = 3000, z = 0 }, v = { x = 150, z = 0 } }, Unit)
    groups[name] = setmetatable({ name = name, unit = unit, controller = newController(unit) }, Group)
  end
  return groups[name]
end
function Group:getName() return self.name end
function Group:getUnit(i) return i == 1 and self.unit or nil end
function Group:getController() return self.controller end
function Group:activate() self.active = true end
function Group:destroy() groups[self.name] = nil end

local s = {
  assert = assert, error = error, ipairs = ipairs, next = next, pairs = pairs,
  pcall = pcall, select = select, setmetatable = setmetatable, tonumber = tonumber,
  tostring = tostring, type = type, unpack = unpack, math = math, string = string,
  table = table, loadstring = loadstring,
}
s._G = s
s.Group = Group
s.world = { addEventHandler = function() end, event = { S_EVENT_SHOT = 1, S_EVENT_SHOOTING_START = 23 } }

net.dostring_in = function(state, code)
  if state ~= 'scripting' then return 'Lua state "' .. tostring(state) .. '" not found', false end
  local fn = assert(loadstring(code))
  setfenv(fn, s)
  return fn(), true
end

dofile(WRITEDIR .. 'Scripts/Hooks/actions-probe.lua')
assert(callbacks and callbacks.onSimulationStart and callbacks.onSimulationFrame, 'callbacks not set')

-- The units fly on between frames.
local function fly(dt)
  for _, g in pairs(groups) do
    g.unit.p.x = g.unit.p.x + g.unit.v.x * dt
    g.unit.p.z = g.unit.p.z + g.unit.v.z * dt
  end
end

local done = WRITEDIR .. (arg[3] or 'DCS.Lua.Exporter/actions-probe') .. '/done'
callbacks.onSimulationStart()
for frame = 1, 20000 do
  modelTime = frame * 0.5
  fly(0.5)
  callbacks.onSimulationFrame()
  if exists(done) then break end
end
assert(exists(done), 'actions probe did not finish')
local f = assert(io.open(done)); assert(f:read('*a') == '9.9.9.7'); f:close()
print('ACTIONS PROBE TEST DONE')
