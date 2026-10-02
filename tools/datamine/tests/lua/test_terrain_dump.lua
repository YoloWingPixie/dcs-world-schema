-- The terrain dump hook against stubbed GUI (Terrain, magvar, DCS) and mission
-- (world, land, coord via net.dostring_in) environments.
-- Usage: lua5.1 test_terrain_dump.lua <tests/lua dir> <writedir/ with the hooks> <mode>
--   mode: ok | mission_error | wrong_terrain
local here = assert(arg[1], 'usage: test_terrain_dump.lua <tests-lua-dir> <writedir/> <mode>')
WRITEDIR = assert(arg[2], 'usage: test_terrain_dump.lua <tests-lua-dir> <writedir/> <mode>')
local mode = assert(arg[3], 'mode')
dofile(here .. '/stub_env.lua')

__DCS_VERSION__ = '9.9.9.7'
local modelTime = 0
local callbacks
DCS.getModelTime = function() return modelTime end
DCS.setUserCallbacks = function(t) callbacks = t end
DCS.getCurrentMission = function()
  return { mission = { theatre = 'TestMap', date = { Year = 2026, Month = 1, Day = 1 } } }
end

local magvarInit
package.preload['magvar'] = function()
  return {
    init = function(month, year) magvarInit = { month, year } end,
    get_mag_decl = function(_lat, _lon) return math.rad(6) end,
  }
end
package.preload['terrain'] = function()
  local configs = {
    [12] = { display_name = 'Anapa-Vityazevo', roadnet = 'x/anapa.rn', reference_point = { x = -5000, y = 240000 } },
    [13] = { display_name = 'Far', reference_point = { x = 50000, y = 300000 }, abandoned = true },
  }
  return {
    GetTerrainConfig = function(key)
      if key == 'id' then return mode == 'wrong_terrain' and 'Other' or 'TestMap' end
      if key == 'Airdromes' then return configs end
      if key == 'standDescriptionVersion' then return 2 end
    end,
    getRunwayList = function(roadnet)
      assert(roadnet == 'x/anapa.rn')
      return { { edge1name = '04', edge2name = '22', course = math.rad(45),
                 edge1x = -6000, edge1y = 239000, edge2x = -4000, edge2y = 241000 } }
    end,
    getRunwayHeading = function() return math.rad(45) end,
    getStandList = function(_roadnet, params)
      assert(#params == 6 and params[6] == 'HEIGHT')
      return { { crossroad_index = 7, name = '01', x = -5100, y = 240100,
                 params = { WIDTH = '20', LENGTH = '22', SHELTER = '0', FOR_HELICOPTERS = '1', FOR_AIRPLANES = '1' } } }
    end,
  }
end

-- Mission environment.
local function height(p) return 10 + p.x * 0.001 end
local airbase = {
  getID = function() return 12 end,
  getName = function() return 'Anapa-Vityazevo' end,
  getPoint = function() return { x = -5010, y = 12, z = 240010 } end,
  getDesc = function() return { category = 0, typeName = 'Anapa-Vityazevo', displayName = 'Anapa', life = 3600 } end,
  getRunways = function()
    return { { Name = 4, course = -math.rad(45), length = 2000 * math.sqrt(2), width = 50,
               position = { x = -5000, y = 10, z = 240000 } } }
  end,
  getParking = function()
    return { { Term_Index = 7, Term_Index_0 = 6, Term_Type = 72, fDistToRW = 500, TO_AC = false,
               vTerminalPos = { x = -5100, y = 10, z = 240100 } } }
  end,
}
local missionEnv = {
  ipairs = ipairs, pairs = pairs, next = next, type = type, tostring = tostring, tonumber = tonumber,
  pcall = pcall, error = error, select = select, setmetatable = setmetatable,
  getmetatable = getmetatable, rawget = rawget, rawequal = rawequal, math = math, string = string, table = table,
  world = { getAirbases = function()
    return { setmetatable({}, { __index = function(_, k) return function() return airbase[k]() end end }) }
  end },
  land = { getHeight = function(p)
    if mode == 'mission_error' then error('land exploded') end
    return height(p)
  end },
  Airbase = { Category = { AIRDROME = 0, HELIPAD = 1, SHIP = 2 } },
  coord = { LOtoLL = function(p) return p.x / 111000, p.z / 111000, 0 end },
}
missionEnv._G = missionEnv
local calls = 0
local missionState = { a_do_script = function() return '' end }
net.dostring_in = function(state, code)
  local fn = assert(loadstring(code))
  if state == 'scripting' then
    calls = calls + 1
    setfenv(fn, missionEnv)
  else
    setfenv(fn, missionState)
  end
  return fn(), true
end

dofile(WRITEDIR .. 'Scripts/Hooks/terrain-dump.lua')
assert(callbacks and callbacks.onSimulationStart and callbacks.onSimulationFrame, 'callbacks not set')

local base = WRITEDIR .. 'DCS.Lua.Exporter/terrains/TestMap'
local function exists(p) local f = io.open(p); if f then f:close() end; return f ~= nil end

callbacks.onSimulationFrame()
callbacks.onSimulationStart()
modelTime = 0.5
callbacks.onSimulationFrame()
assert(calls == 0 and not exists(base .. '.done'), 'ran before settling')
modelTime = 1.5
callbacks.onSimulationFrame()

if mode ~= 'ok' then
  assert(not exists(base .. '.done'), 'marker written despite failure')
  print('TERRAIN DUMP FAILURE TEST PASSED')
  return
end

local f = assert(io.open(base .. '.done')); assert(f:read('*a') == '9.9.9.7'); f:close()
local function near(a, b) return math.abs(a - b) < 1e-9 * math.max(1, math.abs(b)) end
local env = {}
local chunk = assert(loadfile(base .. '.lua'))
setfenv(chunk, env)
chunk()
local t = assert(env.terrain)
assert(t.theatre == 'TestMap' and t.dcsVersion == '9.9.9.7' and t.standDescriptionVersion == 2)
assert(t.magvar.year == 2026 and t.magvar.month == 1 and magvarInit[1] == 1 and magvarInit[2] == 2026)
local ad = assert(t.airdromes[12])
assert(ad.config.display_name == 'Anapa-Vityazevo' and ad.config.roadnet == nil)
assert(ad.stands[1].crossroad_index == 7 and ad.stands[1].params.WIDTH == '20')
assert(ad.runwayList[1].edge1name == '04' and math.abs(ad.runwayHeading - math.rad(45)) < 1e-12)
assert(math.abs(ad.reference.magDeclRad - math.rad(6)) < 1e-12)
assert(near(ad.reference.h, height({ x = -5000 })) and near(ad.reference.lat, -5000 / 111000))
local e = ad.edges[1]
assert(e.from.x == -6000 and e.from.z == 239000 and e.to.x == -4000 and e.to.z == 241000)
assert(e.spacingM <= 10 and #e.heights == math.ceil(2000 * math.sqrt(2) / 10) + 1, 'edge profile')
assert(near(e.heights[1], height({ x = -6000 })) and near(e.heights[#e.heights], height({ x = -4000 })))
assert(t.airdromes[13].config.abandoned == true and t.airdromes[13].runwayList == nil)
local ab = assert(t.airbases[1])
assert(ab.id == 12 and ab.name == 'Anapa-Vityazevo' and ab.desc.category == 0 and ab.desc.life == nil)
assert(ab.runways[1].Name == 4 and ab.parking[1].Term_Index == 7 and ab.parking[1].vTerminalPos.z == 240100)
assert(near(ab.parkingGeo[1].lat, -5100 / 111000))
assert(ab.ends == nil)
assert(t.airbaseCategories.HELIPAD == 1)
assert(#t.grid == 81 and t.grid[1].x == -5000 and t.grid[81].z == 300000)
assert(calls == 2, 'mission env calls: ' .. calls)
-- Only once.
callbacks.onSimulationFrame()
assert(calls == 2)
print('TERRAIN DUMP TEST PASSED')
