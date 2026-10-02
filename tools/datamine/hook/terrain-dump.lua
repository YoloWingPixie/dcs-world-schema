--[[----------------------------------------------------------------------------
  terrain-dump.lua - DCS World per-terrain runtime dump hook.

  A DCS GameGUI hook. `task datamine` (tools/datamine/refresh.py) runs DCS
  headless once per installed terrain with this file and serialize.lua as
  hooks and an empty mission on that terrain (tools/datamine/terrain_mission.py).
  terrain.cfg.lua is encrypted, so airbases, runways and stands are only
  available from the running game; this hook records them as DCS reports them.

  When: the first onSimulationFrame at least SETTLE_SECONDS of model time after
  onSimulationStart, so the mission is simulating. The work (a few thousand
  land.getHeight / coord.LOtoLL calls) runs once, in one frame, which a
  headless server tolerates.

  Sources:
    GUI env   require('terrain') (the mission editor's Terrain module):
              GetTerrainConfig('id' | 'Airdromes' | 'standDescriptionVersion'),
              getRunwayList(roadnet), getRunwayHeading(roadnet),
              getStandList(roadnet, STAND_PARAMS) as me_parking.lua calls it;
              require('magvar'): init(month, year) with the mission's date,
              get_mag_decl(lat, lon) (radians, east positive).
    mission   net.dostring_in('scripting', code); the chunk embeds
              serialize.lua and returns a serialised table:
              world.getAirbases() with getID, getName, getPoint, getDesc,
              getRunways, getParking; land.getHeight; coord.LOtoLL.

  Output: <writedir>/DCS.Lua.Exporter/terrains/<theatre>.lua, one assignment
  `terrain = { ... }` (serialize.lua, tab-indented):

    theatre, dcsVersion, standDescriptionVersion
    magvar      = { year, month, source = 'magvar.get_mag_decl' }
    airdromes   = { [airdromeId] = {
                      config = <GetTerrainConfig('Airdromes')[id], less roadnet>,
                      runwayList = <getRunwayList>, runwayHeading = <radians>,
                      stands = <getStandList>,
                      reference = <sample of config.reference_point, + magDeclRad>,
                      edges = { [i] = <runwayList[i] edge line, see LINE> } } }
    airbases    = { [n] = { id, name, point, desc = {category, typeName,
                      displayName}, runways = <getRunways>, parking = <getParking>,
                      reference = <sample of point, + magDeclRad>,
                      parkingGeo = { [i] = {lat, lon} of parking[i].vTerminalPos } } }
    airbaseCategories = { <name> = <number> }  -- the mission env's Airbase.Category
    grid        = { {x, z, lat, lon}, ... }  -- GRID_N x GRID_N over the airdromes

  A sample is {x, z, h = land.getHeight, lat, lon} (map metres, x north, z
  east). A LINE is {from = sample, to = sample, spacingM, heights = {...}}:
  land.getHeight every spacingM (<= PROFILE_SPACING_M, the line split into
  equal steps) from `from` to `to`, both included. A getRunwayList entry's
  line runs edge1 (edge1x, edge1y) -> edge2 when it has them. Every value is
  DCS's; the extractor derives thresholds, bearings and TDZE from them.

  standDescriptionVersion is queried exactly as me_terrainDATA.lua does
  (GetTerrainConfig('standDescriptionVersion')); DCS 2.9.29 returns nil on
  every terrain, so the editor (and the extractor) use the stand params.

  Then <theatre>.done (the DCS version) is written last, only if every step
  succeeded. On any error the hook logs `Terrain dump failed: <reason>` and
  writes no marker.
------------------------------------------------------------------------------]]

local LOG_NAME = 'DCS.Lua.Exporter'
local OUT_DIR = 'DCS.Lua.Exporter/terrains/'
local SETTLE_SECONDS = 1
local PROFILE_SPACING_M = 10
local GRID_N = 9
local STAND_PARAMS = { 'SHELTER', 'FOR_HELICOPTERS', 'FOR_AIRPLANES', 'WIDTH', 'LENGTH', 'HEIGHT' }
local SERIALIZE_OPTS = { indent = '\t', newline = '\n' }

local function logAt(level, message)
  if log and log.write then
    log.write(LOG_NAME, level, message)
  elseif net and net.log then
    net.log('[' .. LOG_NAME .. '] ' .. tostring(message))
  end
end
local function logInfo(message) logAt(log and log.INFO or 0, message) end
local function logError(message) logAt(log and log.ERROR or 2, message) end

-- serialize.lua sits next to this hook; its source is also embedded in the
-- mission-env chunks so they can return tables as text.
local HOOK_DIRS = { lfs.writedir() .. 'Scripts/Hooks/', './Scripts/Hooks/' }

local function readSerializeSource()
  for _, dir in ipairs(HOOK_DIRS) do
    local f = io.open(dir .. 'serialize.lua', 'r')
    if f then
      local text = f:read('*a')
      f:close()
      return text
    end
  end
  error('serialize.lua not found next to the hook')
end

local serializeSource
local serialize

local function parse(text, what)
  if type(text) ~= 'string' then error(what .. ': no text result (' .. tostring(text) .. ')') end
  local fn, err = loadstring('return ' .. text, what)
  if not fn then error(what .. ': unparseable result: ' .. tostring(err) .. ': ' .. text:sub(1, 200)) end
  setfenv(fn, {})
  return fn()
end

-- Run `body` (a Lua chunk defining `function run(input)`) in the mission env
-- with `input`; return run's result.
local function inMission(what, body, input)
  local code = 'local serialize = (function() ' .. serializeSource .. '\nend)()\n'
    .. body .. '\n'
    .. 'local input = ' .. serialize(input or {}, SERIALIZE_OPTS) .. '\n'
    .. 'local ok, res = pcall(run, input)\n'
    .. 'if ok then return serialize({ ok = true, value = res })\n'
    .. 'else return serialize({ ok = false, err = tostring(res) }) end\n'
  local text, ok = net.dostring_in('scripting', code)
  if ok == false then error(what .. ': dostring_in failed: ' .. tostring(text)) end
  local result = parse(text, what)
  if type(result) ~= 'table' then error(what .. ': result is not a table') end
  if not result.ok then error(what .. ' (mission env): ' .. tostring(result.err)) end
  return result.value
end

-- Mission env: every airbase as DCS reports it.
local AIRBASES_CHUNK = [[
function run()
  local out = {}
  for i, ab in ipairs(world.getAirbases()) do
    local desc = ab:getDesc() or {}
    local p = ab:getPoint()
    local parking = {}
    for j, spot in ipairs(ab:getParking() or {}) do
      local v = spot.vTerminalPos
      parking[j] = {
        Term_Index = spot.Term_Index, Term_Index_0 = spot.Term_Index_0,
        Term_Type = spot.Term_Type, fDistToRW = spot.fDistToRW,
        vTerminalPos = v and { x = v.x, y = v.y, z = v.z } or nil,
      }
    end
    local runways = {}
    for j, r in ipairs(ab:getRunways() or {}) do
      local q = r.position
      runways[j] = {
        Name = r.Name, course = r.course, length = r.length, width = r.width,
        position = q and { x = q.x, y = q.y, z = q.z } or nil,
      }
    end
    out[i] = {
      id = ab:getID(), name = ab:getName(),
      point = { x = p.x, y = p.y, z = p.z },
      desc = { category = desc.category, typeName = desc.typeName, displayName = desc.displayName },
      runways = runways, parking = parking,
    }
  end
  local categories = {}
  for k, v in pairs(Airbase.Category or {}) do
    if type(k) == 'string' and type(v) == 'number' then categories[k] = v end
  end
  return { airbases = out, categories = categories }
end
]]

-- Mission env: heights and geographic coordinates of points.
-- input = { points = { {x, z, geo = bool}, ... }, lines = { {x1, z1, x2, z2, n}, ... } }
local MEASURE_CHUNK = [[
function run(input)
  local points, lines = {}, {}
  for i, p in ipairs(input.points) do
    local h = land.getHeight({ x = p[1], y = p[2] })
    local s = { x = p[1], z = p[2], h = h }
    if p.geo then
      s.lat, s.lon = coord.LOtoLL({ x = p[1], y = h, z = p[2] })
    end
    points[i] = s
  end
  for i, l in ipairs(input.lines) do
    local hs = {}
    for k = 0, l[5] do
      local t = k / l[5]
      hs[k + 1] = land.getHeight({ x = l[1] + t * (l[3] - l[1]), y = l[2] + t * (l[4] - l[2]) })
    end
    lines[i] = hs
  end
  return { points = points, lines = lines }
end
]]

-- Batches the points and lines of the whole terrain into one mission-env call.
local function newBatch()
  local b = { points = {}, lines = {}, pointSinks = {}, lineSinks = {} }
  function b.point(x, z, geo, sink)
    -- selene: allow(mixed_table) -- the { x, z, geo = } point record
    b.points[#b.points + 1] = { x, z, geo = geo or nil }
    b.pointSinks[#b.points] = sink
  end
  function b.line(x1, z1, x2, z2, sink)
    local len = math.sqrt((x2 - x1) ^ 2 + (z2 - z1) ^ 2)
    local n = math.max(1, math.ceil(len / PROFILE_SPACING_M))
    b.lines[#b.lines + 1] = { x1, z1, x2, z2, n }
    b.lineSinks[#b.lines] = function(heights) sink(heights, len / n) end
  end
  function b.run()
    local res = inMission('measure', MEASURE_CHUNK, { points = b.points, lines = b.lines })
    for i, sink in ipairs(b.pointSinks) do
      local s = res.points[i]
      if type(s) ~= 'table' or type(s.h) ~= 'number' then error('no height for point ' .. i) end
      sink(s)
    end
    for i, sink in ipairs(b.lineSinks) do
      local hs = res.lines[i]
      if type(hs) ~= 'table' or #hs ~= b.lines[i][5] + 1 then error('incomplete profile ' .. i) end
      sink(hs)
    end
  end
  return b
end

local function requireNumber(v, what)
  if type(v) ~= 'number' then error(what .. ' is not a number (' .. tostring(v) .. ')') end
  return v
end

-- A LINE between two map points: both ends sampled (with geo), heights between.
local function addLine(batch, x1, z1, x2, z2, into)
  local line = {}
  batch.point(x1, z1, true, function(s) line.from = s end)
  batch.point(x2, z2, true, function(s) line.to = s end)
  batch.line(x1, z1, x2, z2, function(hs, spacing) line.heights = hs; line.spacingM = spacing end)
  into[#into + 1] = line
end

local function copyConfig(cfg)
  local out = {}
  for k, v in pairs(cfg) do
    if k ~= 'roadnet' and type(v) ~= 'function' and type(v) ~= 'userdata' then out[k] = v end
  end
  return out
end

local function collect()
  local Terrain = require('terrain')
  local magvar = require('magvar')

  local current = DCS.getCurrentMission()
  local mission = current and current.mission
  if type(mission) ~= 'table' then error('DCS.getCurrentMission() has no mission') end
  local theatre = mission.theatre
  if type(theatre) ~= 'string' or theatre == '' then error('mission has no theatre') end
  local terrainId = Terrain.GetTerrainConfig('id')
  if terrainId ~= theatre then
    error('Terrain module is on ' .. tostring(terrainId) .. ', the mission on ' .. theatre)
  end
  local date = mission.date or {}
  local year, month = requireNumber(date.Year, 'mission date Year'), requireNumber(date.Month, 'mission date Month')
  magvar.init(month, year)

  local out = {
    theatre = theatre,
    dcsVersion = tostring(_G['__DCS_VERSION__'] or _G['_APP_VERSION']),
    standDescriptionVersion = Terrain.GetTerrainConfig('standDescriptionVersion'),
    magvar = { year = year, month = month, source = 'magvar.get_mag_decl' },
    airdromes = {},
    airbases = {},
    grid = {},
  }
  local batch = newBatch()
  local function withMagvar(s)
    s.magDeclRad = requireNumber(magvar.get_mag_decl(s.lat, s.lon), 'magvar.get_mag_decl')
    return s
  end

  local configs = Terrain.GetTerrainConfig('Airdromes')
  if type(configs) ~= 'table' then error("GetTerrainConfig('Airdromes') is not a table") end
  local minX, maxX, minZ, maxZ
  local count = 0
  for id, cfg in pairs(configs) do
    local rec = { config = copyConfig(cfg), edges = {} }
    out.airdromes[id] = rec
    count = count + 1
    local rp = cfg.reference_point
    if type(rp) == 'table' and type(rp.x) == 'number' and type(rp.y) == 'number' then
      batch.point(rp.x, rp.y, true, function(s) rec.reference = withMagvar(s) end)
      minX, maxX = math.min(minX or rp.x, rp.x), math.max(maxX or rp.x, rp.x)
      minZ, maxZ = math.min(minZ or rp.y, rp.y), math.max(maxZ or rp.y, rp.y)
    end
    if cfg.roadnet then
      rec.runwayList = Terrain.getRunwayList(cfg.roadnet)
      rec.runwayHeading = Terrain.getRunwayHeading(cfg.roadnet)
      rec.stands = Terrain.getStandList(cfg.roadnet, STAND_PARAMS)
      for _, r in ipairs(rec.runwayList or {}) do
        if type(r.edge1x) == 'number' and type(r.edge1y) == 'number'
            and type(r.edge2x) == 'number' and type(r.edge2y) == 'number' then
          addLine(batch, r.edge1x, r.edge1y, r.edge2x, r.edge2y, rec.edges)
        else
          rec.edges[#rec.edges + 1] = { missing = true }
        end
      end
    end
  end
  logInfo('Terrain dump ' .. theatre .. ': ' .. count .. ' airdromes in the terrain config')

  local listed = inMission('airbases', AIRBASES_CHUNK)
  if type(listed) ~= 'table' or type(listed.airbases) ~= 'table' then
    error('world.getAirbases() result is not a table')
  end
  out.airbases, out.airbaseCategories = listed.airbases, listed.categories
  for _, ab in ipairs(out.airbases) do
    ab.parkingGeo = {}
    batch.point(requireNumber(ab.point.x, 'airbase point x'), requireNumber(ab.point.z, 'airbase point z'),
      true, function(s) ab.reference = withMagvar(s) end)
    for j, spot in ipairs(ab.parking) do
      local v = spot.vTerminalPos
      if v then
        batch.point(v.x, v.z, true, function(s) ab.parkingGeo[j] = { lat = s.lat, lon = s.lon } end)
      end
    end
  end
  logInfo('Terrain dump ' .. theatre .. ': ' .. #out.airbases .. ' airbases in the mission')

  if minX then
    for i = 0, GRID_N - 1 do
      for k = 0, GRID_N - 1 do
        local x = minX + (maxX - minX) * i / (GRID_N - 1)
        local z = minZ + (maxZ - minZ) * k / (GRID_N - 1)
        batch.point(x, z, true, function(s)
          out.grid[#out.grid + 1] = { x = s.x, z = s.z, lat = s.lat, lon = s.lon }
        end)
      end
    end
  end

  batch.run()
  logInfo('Terrain dump ' .. theatre .. ': ' .. #batch.points .. ' points, '
    .. #batch.lines .. ' profiles measured')
  return out
end

local function writeFile(path, text)
  local f, err = io.open(path, 'w')
  if not f then error('could not write ' .. path .. ': ' .. tostring(err)) end
  f:write(text)
  f:close()
end

local function dump()
  serializeSource = readSerializeSource()
  local chunk = loadstring(serializeSource, 'serialize.lua')
  serialize = chunk()
  local data = collect()
  local dir = lfs.writedir() .. OUT_DIR
  lfs.mkdir(lfs.writedir() .. 'DCS.Lua.Exporter')
  lfs.mkdir(dir)
  local base = dir .. data.theatre
  os.remove(base .. '.done')
  writeFile(base .. '.lua', 'terrain = ' .. serialize(data, SERIALIZE_OPTS))
  writeFile(base .. '.done', data.dcsVersion)
  logInfo('Terrain dump complete: ' .. base .. '.lua')
end

local armed, done = false, false
local startedAt

DCS.setUserCallbacks({
  onSimulationStart = function()
    if done then return end
    armed = true
    startedAt = DCS.getModelTime()
  end,
  onSimulationFrame = function()
    if not armed or done then return end
    if DCS.getModelTime() - startedAt < SETTLE_SECONDS then return end
    done = true
    local ok, err = pcall(dump)
    if not ok then logError('Terrain dump failed: ' .. tostring(err)) end
  end,
})
