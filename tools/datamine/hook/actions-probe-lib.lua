--[[----------------------------------------------------------------------------
  actions-probe-lib.lua - the AI actions probe's calls in the mission
  scripting state.

  actions-probe.lua (the GameGUI hook) installs this file in the `scripting`
  state as __actionsProbe.lib, with the plan (actions-probe-plan.lua,
  tools/datamine/actions_probe.py) as __actionsProbe.plan, and calls one
  function per phase of a step. Each returns a JSON object text (the
  encoder of probe-call.lua, which the hook passes as this chunk's argument).

    setup(G, P)        counts S_EVENT_SHOT / S_EVENT_SHOOTING_START per
                       initiator group (P.shots) and reports which sample
                       groups exist
    reset(G, P, n)     effect steps outside `route`: resetTask, then (with the
                       effect's `leg`) a `Mission` task `leg` m straight ahead
                       of the lead unit (`turnToward`: at its speed and
                       altitude; `stop`: off road at `routeSpeed`)
    apply(G, P, n)     the call under test, in a pcall: `setTask`,
                       `pushTask`, `comboTask` / `wrappedAction` (setTask of
                       the plan's wrapper), `setCommand`, `setOption`, or
                       `route` (Group.activate of the step's late-activated
                       group). API contexts reset the controller first
                       (resetTask) unless the step has an effect. Records
                       accepted, error, hasTaskBefore, hasTaskImmediate; an
                       effect step also its target and start values
    after(G, P, n)     a frame later: hasTaskAfter (the route group's
                       controller for `route`)
    measure(G, P, n)   when the effect's seconds are over: its end values
    cleanup(G, P, n)   destroys a route group; after an option step sets
                       ROE weapon hold (option 0 = 4) on the sample again

  Effect measures (the plan's step.effect):
    turnToward  target `distance` m from the lead unit at `bearing` degrees
                from its velocity (route: the plan's target); start/end:
                distance to the target and the angle between velocity and
                the bearing to it (0 = flying at it)
    stop        start/end ground speed of the lead unit
    shoot       shots of the group since apply

  Task placeholders (strings in the plan's task tables), resolved at apply
  from the effect target: `$target` = { x, y } (map x, z), `$target.x`,
  `$target.y`, `$alt` (lead unit altitude m), `$speed` (m/s, at least 1).
------------------------------------------------------------------------------]]

local M = {}

-- The JSON encoder: probe-call.lua's module, this chunk's argument (the hook
-- loads both).
local json = ...

local type, pairs, ipairs, tostring, pcall = type, pairs, ipairs, tostring, pcall
local atan2, sqrt, cos, sin, pi = math.atan2, math.sqrt, math.cos, math.sin, math.pi

M.ERROR_LENGTH = 500
M.encode = json.encode

local function errorText(e)
  local s = tostring(e)
  if #s > M.ERROR_LENGTH then s = s:sub(1, M.ERROR_LENGTH) end
  return s
end
M.errorText = errorText

-- ---------------------------------------------------------------------------
-- Objects
-- ---------------------------------------------------------------------------

local function groupOf(G, name)
  local ok, g = pcall(G.Group.getByName, name)
  if not ok then return nil, errorText(g) end
  if g == nil then return nil, 'no group ' .. tostring(name) end
  return g
end
M.groupOf = groupOf

local function controllerOf(G, name)
  local g, err = groupOf(G, name)
  if not g then return nil, err end
  local ok, c = pcall(g.getController, g)
  if not ok then return nil, errorText(c) end
  if c == nil then return nil, 'group ' .. name .. ' has no controller' end
  return c, nil, g
end

local function leadOf(g)
  local ok, u = pcall(g.getUnit, g, 1)
  if ok and u then return u end
  return nil
end

local function hasTask(c)
  local ok, v = pcall(c.hasTask, c)
  if ok then return v end
  return nil
end

local function horizontal(v) return sqrt(v.x * v.x + v.z * v.z) end

local function heading(u)
  local v = u:getVelocity()
  if horizontal(v) >= 1 then return atan2(v.z, v.x) end
  local pos = u:getPosition()
  return atan2(pos.x.z, pos.x.x)
end

local function angleTo(u, target)
  local p = u:getPoint()
  local b = atan2(target.z - p.z, target.x - p.x)
  local d = (b - heading(u)) % (2 * pi)
  if d > pi then d = 2 * pi - d end
  return d * 180 / pi, sqrt((target.x - p.x) ^ 2 + (target.z - p.z) ^ 2)
end

-- A deep copy of v with the placeholders resolved.
local function resolve(v, ctx)
  if type(v) == 'string' and v:sub(1, 1) == '$' then
    local t = ctx.target
    if v == '$target' and t then return { x = t.x, y = t.z } end
    if v == '$target.x' and t then return t.x end
    if v == '$target.y' and t then return t.z end
    if v == '$alt' and ctx.alt then return ctx.alt end
    if v == '$speed' and ctx.speed then return ctx.speed end
    error('unresolved placeholder ' .. v, 0)
  end
  if type(v) ~= 'table' then return v end
  local out = {}
  for k, x in pairs(v) do out[k] = resolve(x, ctx) end
  return out
end
M.resolve = resolve

-- ---------------------------------------------------------------------------
-- Phases
-- ---------------------------------------------------------------------------

function M.setup(G, P)
  P.shots, P.state = {}, {}
  local ev = G.world and G.world.event or {}
  local handler = {}
  function handler:onEvent(e)
    if e and (e.id == ev.S_EVENT_SHOT or e.id == ev.S_EVENT_SHOOTING_START) and e.initiator then
      local ok, g = pcall(function() return e.initiator:getGroup() end)
      if ok and g then
        local okName, name = pcall(g.getName, g)
        if okName and name then P.shots[name] = (P.shots[name] or 0) + 1 end
      end
    end
  end
  local ok, err = pcall(G.world.addEventHandler, handler)
  local samples = {}
  for _, name in ipairs(P.plan.samples or {}) do
    samples[name] = groupOf(G, name) ~= nil
  end
  return M.encode({ eventHandler = ok, error = (not ok) and errorText(err) or nil, samples = samples })
end

local function step(P, n)
  local s = P.plan.steps[n]
  if not s then error('no plan step ' .. tostring(n), 0) end
  return s
end

function M.reset(G, P, n)
  local s = step(P, n)
  local c, err, g = controllerOf(G, s.sample)
  if not c then return M.encode({ ok = false, error = err }) end
  local ok, e = pcall(function()
    c:resetTask()
    local length = s.effect.leg
    if not length then return end
    local u = assert(leadOf(g), 'no lead unit')
    local p, h = u:getPoint(), heading(u)
    local ground = s.effect.measure == 'stop'
    local speed = ground and s.effect.routeSpeed or math.max(horizontal(u:getVelocity()), 1)
    local function point(d)
      return {
        x = p.x + d * cos(h), y = p.z + d * sin(h), alt = ground and 0 or p.y,
        alt_type = 'BARO', speed = speed,
        type = 'Turning Point', action = ground and 'Off Road' or 'Turning Point',
      }
    end
    c:setTask({ id = 'Mission', params = { route = { points = { point(0), point(length) } } } })
  end)
  return M.encode({ ok = ok, error = (not ok) and errorText(e) or nil })
end

local function effectStart(_, P, _n, s, g, ctx)
  local u = leadOf(g)
  if not u then return { error = 'no lead unit' } end
  local m = s.effect.measure
  if m == 'turnToward' then
    local angle, dist = angleTo(u, ctx.target)
    return { angle = angle, distance = dist }
  elseif m == 'stop' then
    return { speed = horizontal(u:getVelocity()) }
  elseif m == 'shoot' then
    return { shots = P.shots[g:getName()] or 0 }
  end
  return { error = 'unknown measure ' .. tostring(m) }
end

-- The effect target and placeholder values: the plan's (route) or from the
-- lead unit now.
local function effectContext(s, g)
  local ctx = {}
  if not s.effect then return ctx end
  if s.effect.target then
    ctx.target = { x = s.effect.target[1], z = s.effect.target[2] }
    return ctx
  end
  local u = leadOf(g)
  if not u then return ctx end
  local p, h = u:getPoint(), heading(u)
  local b = h + (s.effect.bearing or 0) * pi / 180
  local d = s.effect.distance or 0
  ctx.target = { x = p.x + d * cos(b), z = p.z + d * sin(b) }
  ctx.alt = p.y
  ctx.speed = math.max(horizontal(u:getVelocity()), 1)
  return ctx
end

local CALLS = {
  setTask = function(c, _, task) return c:setTask(task) end,
  comboTask = function(c, _, task) return c:setTask(task) end,
  wrappedAction = function(c, _, task) return c:setTask(task) end,
  pushTask = function(c, _, task) return c:pushTask(task) end,
  setCommand = function(c, _, task) return c:setCommand(task) end,
  setOption = function(c, s) return c:setOption(s.optionName, s.optionValue) end,
}

function M.apply(G, P, n)
  local s = step(P, n)
  local out = {}
  if s.context == 'route' then
    local g, err = groupOf(G, s.route)
    if not g then return M.encode({ accepted = false, error = err }) end
    local ok, e = pcall(g.activate, g)
    out.accepted, out.error = ok, (not ok) and errorText(e) or nil
    local okC, c = pcall(g.getController, g)
    if okC and c then out.hasTaskImmediate = hasTask(c) end
    P.state[n] = { group = s.route }
    return M.encode(out)
  end
  local c, err, g = controllerOf(G, s.sample)
  if not c then return M.encode({ accepted = false, error = err }) end
  if not s.effect then pcall(c.resetTask, c) end
  out.hasTaskBefore = hasTask(c)
  local ctx = effectContext(s, g)
  local call = CALLS[s.context]
  if not call then error('unknown context ' .. tostring(s.context), 0) end
  local ok, e = pcall(function() return call(c, s, s.task and resolve(s.task, ctx)) end)
  out.accepted, out.error = ok, (not ok) and errorText(e) or nil
  out.hasTaskImmediate = hasTask(c)
  P.state[n] = { group = s.sample, ctx = ctx }
  if ctx.target then out.target = { ctx.target.x, ctx.target.z } end
  return M.encode(out)
end

function M.after(G, P, n)
  local s = step(P, n)
  local st = P.state[n] or {}
  local c, err, g = controllerOf(G, st.group or s.sample)
  if not c then return M.encode({ error = err }) end
  local out = { hasTaskAfter = hasTask(c) }
  if s.effect then
    local ctx = st.ctx or effectContext(s, g)
    st.ctx = ctx
    local ok, v = pcall(effectStart, G, P, n, s, g, ctx)
    out.effectStart = ok and v or { error = errorText(v) }
    st.start = ok and v or nil
    P.state[n] = st
  end
  return M.encode(out)
end

function M.measure(G, P, n)
  local s = step(P, n)
  local st = P.state[n] or {}
  local g, err = groupOf(G, st.group or s.sample)
  if not g then return M.encode({ error = err }) end
  local ok, v = pcall(effectStart, G, P, n, s, g, st.ctx or {})
  if not ok then return M.encode({ error = errorText(v) }) end
  if s.effect.measure == 'shoot' and st.start and st.start.shots then
    v.shots = v.shots - st.start.shots
  end
  return M.encode({ ['end'] = v })
end

function M.cleanup(G, P, n)
  local s = step(P, n)
  local out = {}
  if s.context == 'route' then
    local g = groupOf(G, s.route)
    if g then
      local ok, e = pcall(g.destroy, g)
      out.destroyed, out.error = ok, (not ok) and errorText(e) or nil
    end
  elseif s.kind == 'option' then
    local c = controllerOf(G, s.sample)
    if c then
      local ok, e = pcall(c.setOption, c, 0, 4)
      out.roeHold, out.error = ok, (not ok) and errorText(e) or nil
    end
  end
  P.state[n] = nil
  return M.encode(out)
end

return M
