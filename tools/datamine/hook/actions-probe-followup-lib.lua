--[[----------------------------------------------------------------------------
  actions-probe-followup-lib.lua - the actions probe follow-up's additions to
  actions-probe-lib.lua.

  Not a hook by itself: actions_probe.Probe.lib_lua appends it to the lib (as
  `local M = (function(...) <lib> end)(...)`), and the run installs the result
  as actions-probe-lib.lua. It changes two phases for steps with `spawn` (their
  `sample` is a late-activated copy of the sample, one per step):

    reset(G, P, n)     activates the step's group instead (its own route
                       goes straight ahead; the hook's reset wait follows)
    cleanup(G, P, n)   destroys it

  and, for `shoot` steps with a `targetGroup` (the plan's target object):

    setup(G, P)        also counts S_EVENT_HIT on a target group per
                       initiator group (P.hits)
    measure(G, P, n)   end values `shots` (since after, as the lib's) and
                       `hits`: the step group's hits on the target group
------------------------------------------------------------------------------]]

-- M is the lib's local this file is appended after (see above).
--# selene: allow(undefined_variable)
local pcall, ipairs, next = pcall, ipairs, next
local errorText, groupOf = M.errorText, M.groupOf
local baseReset, baseCleanup = M.reset, M.cleanup
local baseSetup, baseMeasure = M.setup, M.measure

local function spawnStep(P, n)
  local s = P.plan.steps[n]
  if s and s.spawn then return s end
  return nil
end

function M.reset(G, P, n)
  local s = spawnStep(P, n)
  if not s then return baseReset(G, P, n) end
  local g, err = groupOf(G, s.sample)
  if not g then return M.encode({ ok = false, error = err }) end
  local ok, e = pcall(g.activate, g)
  return M.encode({ ok = ok, spawned = ok, error = (not ok) and errorText(e) or nil })
end

local function groupName(object)
  local ok, g = pcall(function() return object:getGroup() end)
  if not ok or not g then return nil end
  local okName, name = pcall(g.getName, g)
  return okName and name or nil
end

function M.setup(G, P)
  local out = baseSetup(G, P)
  P.hits = {}
  local targets = {}
  for _, s in ipairs(P.plan.steps) do
    if s.effect and s.effect.targetGroup then targets[s.effect.targetGroup] = true end
  end
  if next(targets) == nil then return out end
  local ev = G.world and G.world.event or {}
  local handler = {}
  function handler:onEvent(e)
    if not (e and e.id == ev.S_EVENT_HIT and e.initiator and e.target) then return end
    if not targets[groupName(e.target) or ''] then return end
    local name = groupName(e.initiator)
    if name then P.hits[name] = (P.hits[name] or 0) + 1 end
  end
  pcall(G.world.addEventHandler, handler)
  return out
end

function M.measure(G, P, n)
  local s = P.plan.steps[n]
  local e = s and s.effect
  if not (e and e.targetGroup and e.measure == 'shoot') then return baseMeasure(G, P, n) end
  local st = P.state[n] or {}
  local name = st.group or s.sample
  local start = st.start and st.start.shots or 0
  return M.encode({ ['end'] = {
    shots = (P.shots[name] or 0) - start,
    hits = P.hits[name] or 0,
  } })
end

function M.cleanup(G, P, n)
  local s = spawnStep(P, n)
  if not s then return baseCleanup(G, P, n) end
  local out = {}
  local g = groupOf(G, s.sample)
  if g then
    local ok, e = pcall(g.destroy, g)
    out.destroyed, out.error = ok, (not ok) and errorText(e) or nil
  end
  P.state[n] = nil
  return M.encode(out)
end

return M
