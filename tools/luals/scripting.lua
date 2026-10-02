-- Mission scripting as LuaLS sees dist/dcs-world-api.lua: DCS globals
-- resolve, enum parameters take their values, wrong values warn.
local unit = Unit.getByName("Enfield11")
if unit then
  local point = unit:getPoint()
  trigger.action.smoke(point, trigger.smokeColor.Red)
  trigger.action.smoke(point, "red") --! param-type-mismatch
  trigger.action.outTextForCoalition(coalition.side.BLUE, unit:getTypeName(), 10)
  local controller = unit:getController()
  controller:setOption(AI.Option.Air.id.ROE, AI.Option.Air.val.ROE.WEAPON_HOLD)
  trigger.action.$smoke(point, trigger.smokeColor.Green) --! hover color: trigger.smokeColor
end
timer.scheduleFunction(function(_, time) return time + 1 end, nil, timer.getTime() + 1)
env.info(tostring(land.getHeight({ x = 0, y = 0 })))
missionCommands.addCommand("Status", nil, function() end)
world.weather.setFogThickness(100)
local globals = { AI, Airbase, atmosphere, coalition, coord, country.id.USA, Group, Object, Spot, StaticObject, Weapon, world.event.S_EVENT_SHOT }
local typo = Units.getByName("Enfield11") --! undefined-global
---@type DcsTask.Task.Orbit
local orbit = { id = "Orbit", params = { pattern = "Race-Track" } }
---@type DcsTask.Task.Orbit
local lower = { id = "orbit" } --! assign-type-mismatch
---@type DcsTask.Task.Orbit
local triangle = { id = "Orbit", params = { pattern = "Triangle" } } --! assign-type-mismatch
---@type DcsTask.Task.AttackGroup
local attack = { id = "AttackGroup", params = { expend = "Auto" } }
---@type DcsTask.Task.Orbit
local completed = { id = "Orbit", params = { pattern = "$" } } --! complete "Race-Track"; assign-type-mismatch
