-- DcsId and enum types where DCS takes them: completions, and warnings on
-- values DCS does not know.
local desc = Unit.getDescByName("$") --! complete "F-16C_50"
local base = Airbase.getByName("$") --! complete "Anapa-Vityazevo"
local unit = Unit.getByName("Enfield11")
if unit then
  local fighter = unit:hasAttribute("$") --! complete "Fighters"
  local typeName = unit:$getTypeName() --! hover Any unit type
  local controller = unit:getController()
  controller:setAltitude(1000, true, "BARO")
  controller:setAltitude(1000, true, "AGL") --! param-type-mismatch
  controller:setOption(AI.Option.Air.id.ROE, AI.Option.Air.val.ROE.OPEN_FIRE)
end
land.getClosestPointOnRoads("railroads", 0, 0)
land.getClosestPointOnRoads("rails", 0, 0) --! param-type-mismatch
coalition.addGroup(coalition.side.BLUE, country.id.USA, {
  name = "Viper",
  task = "CAP",
  units = { { type = "F-16C_50", x = 0, y = 0, skill = "Random", payload = { pylons = { [1] = { CLSID = "{AIM-9X}" } } } } },
  route = { points = { { type = "TakeOffParking", action = "From Parking Area", x = 0, y = 0, speed = 0, airdromeId = 12 } } },
})
---@type UnitSpawnData
local expert = { type = "F-16C_50", x = 0, y = 0, skill = "Expert" } --! assign-type-mismatch
---@type MissionWaypoint
local fly = { type = "Turning Point", action = "Turning Point", x = 0, y = 0, speed = 200, alt_type = "$" } --! complete "RADIO"; assign-type-mismatch
---@type DcsTask.Command.SetFrequency
local frequency = { id = "SetFrequency", params = { frequency = 251000000, modulation = radio.modulation.AM } }
---@type DcsTask.EnrouteTask.EngageTargets
local engage = { id = "EngageTargets", params = { targetTypes = { "Air", "MyModAttribute" }, weaponType = 1073741822 } }
---@type DcsTask.Command.ActivateBeacon
local tacan = { id = "ActivateBeacon", params = { type = 4, modeChannel = "Z" } } --! assign-type-mismatch
