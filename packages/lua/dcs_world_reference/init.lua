-- DCS World reference data as Lua tables, one file per series, each loaded on
-- first access. Works with `require` (package.path) and with `dofile`:
--
--   local ref = require("dcs_world_reference")
--   local ref = dofile(lfs.writedir() .. "Scripts/dcs_world_reference/init.lua")
--   print(ref.aircraft["F-16C_50"].displayName, ref.dcsVersion)

---@type DcsWorldReference
local M = {}
local loaded = {}
local dir

local function own_dir()
    local info = debug and debug.getinfo and debug.getinfo(1, "S")
    local source = info and info.source or ""
    if source:sub(1, 1) ~= "@" then
        return nil
    end
    local path = source:sub(2):gsub("\\", "/")
    return path:match("^(.*/)") or "./"
end

dir = own_dir()

---@param path string?
function M.setDir(path)
    dir = path
end

---@param name string
---@return table
function M.load(name)
    if loaded[name] == nil then
        if type(name) ~= "string" or not name:match("^[%w_]+$") or name == "init" or name == "annotations" then
            error("dcs_world_reference: no series " .. tostring(name), 2)
        end
        if dir then
            local chunk, err = loadfile(dir .. name .. ".lua")
            if not chunk then
                error("dcs_world_reference: " .. tostring(err), 2)
            end
            loaded[name] = chunk()
        else
            loaded[name] = require("dcs_world_reference." .. name)
        end
    end
    return loaded[name]
end

-- Reverse and name lookups over the `_index_<name>.lua` files, each loaded on
-- first use. Every function returns a new array.

local function index(name)
    return M.load("_index_" .. name)
end

local function copy(list)
    local out = {}
    for i, v in ipairs(list or {}) do
        out[i] = v
    end
    return out
end

local function contains(list, value)
    for _, v in ipairs(list) do
        if v == value then
            return true
        end
    end
    return false
end

local function sorted_ids(refs, series)
    local seen, out = {}, {}
    for _, r in ipairs(refs) do
        if r.series == series and not seen[r.id] then
            seen[r.id] = true
            out[#out + 1] = r.id
        end
    end
    table.sort(out)
    return out
end

---@param name string
---@return string
function M.nameKey(name)
    return (name:gsub("^[ \t\n\r\f\v]+", ""):gsub("[ \t\n\r\f\v]+$", ""):gsub("%u", string.lower))
end

---@param series string
---@param id string
---@return DcsReference[]
function M.referencesTo(series, id)
    if not contains(index("meta").references, series) then
        return {}
    end
    return copy(index("references_" .. series)[id])
end

---@param weaponId string
---@return string[]
function M.storesDelivering(weaponId)
    return sorted_ids(M.referencesTo("weapons", weaponId), "stores")
end

---@param weaponId string
---@return string[]
function M.aircraftCarrying(weaponId)
    return copy(index("carriers")[weaponId])
end

---@param unitId string
---@return string[]
function M.threatsForUnit(unitId)
    local refs = {}
    for _, series in ipairs(index("meta").unitSeries) do
        for _, r in ipairs(M.referencesTo(series, unitId)) do
            refs[#refs + 1] = r
        end
    end
    return sorted_ids(refs, "threats")
end

---@param name string
---@param theatre string?
---@return string[]
function M.airbaseByName(name, theatre)
    local key, want = M.nameKey(name), theatre and M.nameKey(theatre)
    local seen, out = {}, {}
    for t, names in pairs(index("airbases_by_name")) do
        if want == nil or M.nameKey(t) == want then
            for _, id in ipairs(names[key] or {}) do
                if not seen[id] then
                    seen[id] = true
                    out[#out + 1] = id
                end
            end
        end
    end
    table.sort(out)
    return out
end

---@param series string
---@param name string
---@return string[]
function M.findByName(series, name)
    if not contains(index("meta").names, series) then
        return {}
    end
    return copy(index("names_" .. series)[M.nameKey(name)])
end

-- Reference helpers: pure functions of the published data (map projection,
-- threat rings, unit classification, loadout fit and mass, radio tuning, weapons
-- and detection, TACAN channels, runways and stands, countries, liveries and
-- datalinks) and pure geo maths (distances, coordinate formats, MGRS). The
-- Python package is the reference implementation; the shared vectors in
-- tools/package/tests/vectors/ hold this one to its results. Unknown ids and
-- impossible inputs raise errors.

local function record(series, id)
    local found = M.load(series)[id]
    if found == nil then
        error("dcs_world_reference: no " .. series .. " record " .. tostring(id), 3)
    end
    return found
end

-- Theatre projection: WGS84 and the Krueger series to order n^6 (Karney 2011),
-- as tools/datamine/tmerc.py fitted the projections with.

local F = 1 / 298.257223563
local N = F / (2 - F)
local E = math.sqrt(F * (2 - F))
local A_RECT = 6378137.0 / (1 + N) * (1 + N ^ 2 / 4 + N ^ 4 / 64 + N ^ 6 / 256)
local ALPHA = {
    N / 2 - 2 / 3 * N ^ 2 + 5 / 16 * N ^ 3 + 41 / 180 * N ^ 4 - 127 / 288 * N ^ 5 + 7891 / 37800 * N ^ 6,
    13 / 48 * N ^ 2 - 3 / 5 * N ^ 3 + 557 / 1440 * N ^ 4 + 281 / 630 * N ^ 5 - 1983433 / 1935360 * N ^ 6,
    61 / 240 * N ^ 3 - 103 / 140 * N ^ 4 + 15061 / 26880 * N ^ 5 + 167603 / 181440 * N ^ 6,
    49561 / 161280 * N ^ 4 - 179 / 168 * N ^ 5 + 6601661 / 7257600 * N ^ 6,
    34729 / 80640 * N ^ 5 - 3418889 / 1995840 * N ^ 6,
    212378941 / 319334400 * N ^ 6,
}
local RAD = math.pi / 180
local DEG = 180 / math.pi

local function atanh(x)
    return 0.5 * math.log((1 + x) / (1 - x))
end

local function tm(lat, dlon)
    local phi, lam = lat * RAD, dlon * RAD
    local s = math.sin(phi)
    local t = math.sinh(atanh(s) - E * atanh(E * s))
    local xi_p = math.atan2(t, math.cos(lam))
    local eta_p = atanh(math.sin(lam) / math.sqrt(1 + t * t))
    local xi, eta = xi_p, eta_p
    for j, a in ipairs(ALPHA) do
        xi = xi + a * math.sin(2 * j * xi_p) * math.cosh(2 * j * eta_p)
        eta = eta + a * math.cos(2 * j * xi_p) * math.sinh(2 * j * eta_p)
    end
    return A_RECT * eta, A_RECT * xi
end

local function to_map(p, lat, lon)
    local e, n = tm(lat, lon - p.centralMeridian)
    local k = p.scaleFactor
    return p.falseNorthing + k * n, p.falseEasting + k * e
end

---@param name string
---@return Entity.Theatre?
function M.theatreByName(name)
    local key = M.nameKey(name)
    for _, t in pairs(M.load("theatres")) do
        local names = { t.id, t.displayName or "", t.directory }
        for _, alias in ipairs(t.aliases or {}) do
            names[#names + 1] = alias
        end
        for _, n in ipairs(names) do
            if n ~= "" and M.nameKey(n) == key then
                return t
            end
        end
    end
    return nil
end

local function projection(theatre)
    local t = M.theatreByName(theatre)
    if t == nil then
        error("dcs_world_reference: no theatre " .. tostring(theatre), 3)
    end
    if t.projection == nil then
        error("dcs_world_reference: theatre " .. t.id .. " has no map projection", 3)
    end
    return t.projection
end

---@param theatre string
---@param lat number
---@param lon number
---@return DcsMapXZ
function M.toMapXZ(theatre, lat, lon)
    local x, z = to_map(projection(theatre), lat, lon)
    return { x = x, z = z }
end

-- Newton iteration on to_map from (0, central meridian) until both residuals
-- are under a micrometre (at most 50 steps).
local function inverse(p, x, z)
    local lat, lon, h = 0, p.centralMeridian, 1e-6
    for _ = 1, 50 do
        local px, pz = to_map(p, lat, lon)
        local dx, dz = x - px, z - pz
        if math.abs(dx) < 1e-6 and math.abs(dz) < 1e-6 then
            return { lat = lat, lon = lon }
        end
        local x1, z1 = to_map(p, lat + h, lon)
        local x2, z2 = to_map(p, lat, lon + h)
        local a, b = (x1 - px) / h, (x2 - px) / h
        local c, d = (z1 - pz) / h, (z2 - pz) / h
        local det = a * d - b * c
        lat = lat + (d * dx - b * dz) / det
        lon = lon + (a * dz - c * dx) / det
    end
    error("dcs_world_reference: toLatLon did not converge for (" .. x .. ", " .. z .. ")", 3)
end

---@param theatre string
---@param x number
---@param z number
---@return DcsLatLon
function M.toLatLon(theatre, x, z)
    return inverse(projection(theatre), x, z)
end

-- Threats

---@param threatId string
---@return DcsThreatRange
function M.threatRange(threatId)
    local threat = record("threats", threatId)
    local envelopes = {}
    for _, c in ipairs(threat.components or {}) do
        envelopes[#envelopes + 1] = c.envelope
        envelopes[#envelopes + 1] = c.gunEnvelope
    end
    local out = {}
    for _, pick in ipairs({ { "rMinKm", math.min }, { "rMaxKm", math.max }, { "hMinM", math.min }, { "hMaxM", math.max } }) do
        local key, fn, value, count = pick[1], pick[2], nil, 0
        for _, e in ipairs(envelopes) do
            if e[key] ~= nil then
                count = count + 1
                value = value == nil and e[key] or fn(value, e[key])
            end
        end
        if #envelopes > 0 and count == #envelopes then
            out[key] = value
        end
    end
    local sensors = M.load("sensors")
    for _, s in ipairs(threat.sensors or {}) do
        local km = sensors[s] and sensors[s].detectionRangeKm
        if km ~= nil and (out.detectionKm == nil or km > out.detectionKm) then
            out.detectionKm = km
        end
    end
    return out
end

local function unit_series(unitId)
    for _, s in ipairs(index("meta").unitSeries) do
        if M.load(s)[unitId] ~= nil then
            return s
        end
    end
    return nil
end

---@param unitType string
---@return string[]
function M.threatForUnitType(unitType)
    if unit_series(unitType) == nil then
        error("dcs_world_reference: no unit type " .. tostring(unitType), 2)
    end
    return M.threatsForUnit(unitType)
end

M.EARTH_RADIUS_M = 6371008.8

local function destination(lat, lon, bearing, dist_m)
    local phi, lam = lat * RAD, lon * RAD
    local theta, delta = bearing * RAD, dist_m / M.EARTH_RADIUS_M
    local phi2 = math.asin(math.sin(phi) * math.cos(delta) + math.cos(phi) * math.sin(delta) * math.cos(theta))
    local lam2 = lam
        + math.atan2(math.sin(theta) * math.sin(delta) * math.cos(phi), math.cos(delta) - math.sin(phi) * math.sin(phi2))
    return { (lam2 * DEG + 180) % 360 - 180, phi2 * DEG }
end

local function ring(lat, lon, km, segments, clockwise)
    local points = {}
    for i = 0, segments do
        local step = i % segments
        local bearing
        if clockwise then
            bearing = 360 * step / segments
        else
            bearing = (360 * (segments - step) / segments) % 360
        end
        points[#points + 1] = destination(lat, lon, bearing, km * 1000)
    end
    return points
end

---@param threatId string
---@param lat number
---@param lon number
---@param options { segments: integer? }?
---@return table GeoJSON FeatureCollection of one Polygon feature
function M.threatRingGeoJSON(threatId, lat, lon, options)
    local segments = options and options.segments or 64
    if segments < 3 then
        error("dcs_world_reference: segments must be at least 3, got " .. segments, 2)
    end
    local range = M.threatRange(threatId)
    if range.rMaxKm == nil then
        error("dcs_world_reference: threat " .. threatId .. " has no engagement range", 2)
    end
    local rings = { ring(lat, lon, range.rMaxKm, segments, false) }
    if (range.rMinKm or 0) > 0 then
        rings[2] = ring(lat, lon, range.rMinKm, segments, true)
    end
    local properties = { threat = threatId }
    for k, v in pairs(range) do
        properties[k] = v
    end
    return {
        type = "FeatureCollection",
        features = {
            { type = "Feature", properties = properties, geometry = { type = "Polygon", coordinates = rings } },
        },
    }
end

-- Classification

local function matches(when, facts)
    for fact, tests in pairs(when) do
        local have = {}
        for _, v in ipairs(facts[fact] or {}) do
            have[v] = true
        end
        if tests.any then
            local hit = false
            for _, v in ipairs(tests.any) do
                hit = hit or have[v] == true
            end
            if not hit then
                return false
            end
        end
        for _, v in ipairs(tests.all or {}) do
            if not have[v] then
                return false
            end
        end
        for _, v in ipairs(tests.none or {}) do
            if have[v] then
                return false
            end
        end
    end
    return true
end

---@param aircraftId string
---@return string[]
function M.aircraftRoles(aircraftId)
    local a = record("aircraft", aircraftId)
    local tasks = {}
    for i, t in ipairs(a.tasks or {}) do
        tasks[i] = t.name
    end
    local tanker = a.refuelling and a.refuelling.isTanker
    local facts = {
        attributes = a.attributes or {},
        kind = { a.kind },
        tasks = tasks,
        defaultTask = a.defaultTask and { a.defaultTask.name } or {},
        isTanker = (tanker ~= nil and tanker ~= false and tanker ~= 0) and { "true" } or {},
    }
    local seen, out = {}, {}
    for _, r in ipairs(index("classification").aircraftRoles) do
        if not seen[r.role] and matches(r.when, facts) then
            seen[r.role] = true
            out[#out + 1] = r.role
        end
    end
    table.sort(out)
    return out
end

---@param unitId string
---@return string
function M.unitClass(unitId)
    local series = unit_series(unitId)
    if series == nil then
        error("dcs_world_reference: no unit type " .. tostring(unitId), 2)
    end
    local u = M.load(series)[unitId]
    local facts = {
        series = { series },
        attributes = u.attributes or {},
        kind = series == "aircraft" and { u.kind } or {},
    }
    for _, r in ipairs(index("classification").unitClasses) do
        if matches(r.when, facts) then
            return r.class
        end
    end
    return "other"
end

-- Loadouts

local function stations(aircraftId)
    local out = copy(record("aircraft", aircraftId).stations)
    table.sort(out, function(p, q)
        return p.station < q.station
    end)
    return out
end

---@param aircraftId string
---@param clsid string
---@return integer[]
local function accepted(station, clsid)
    for _, a in ipairs(station.accepts) do
        if a.clsid == clsid then
            return a
        end
    end
    return nil
end

function M.stationsAccepting(aircraftId, clsid)
    record("stores", clsid)
    local out = {}
    for _, s in ipairs(stations(aircraftId)) do
        if accepted(s, clsid) then
            out[#out + 1] = s.station
        end
    end
    return out
end

---@param aircraftId string
---@param station integer
---@param clsid string
---@return boolean
function M.canMount(aircraftId, station, clsid)
    record("stores", clsid)
    for _, s in ipairs(stations(aircraftId)) do
        if s.station == station then
            return accepted(s, clsid) ~= nil
        end
    end
    error("dcs_world_reference: aircraft " .. aircraftId .. " has no station " .. tostring(station), 2)
end

-- Size of a maximum matching of stores (each a list of candidate stations) to
-- distinct stations (Kuhn's augmenting paths).
local function matching(options)
    local owner = {}
    local function augment(i, seen)
        for _, s in ipairs(options[i]) do
            if not seen[s] then
                seen[s] = true
                if owner[s] == nil or augment(owner[s], seen) then
                    owner[s] = i
                    return true
                end
            end
        end
        return false
    end
    local size = 0
    for i = 1, #options do
        if augment(i, {}) then
            size = size + 1
        end
    end
    return size
end

-- Whether occupant (nil: empty) of the rule's station breaks it: a required
-- rule wants one of clsids (or nothing with allowEmpty), a forbidden rule none
-- of clsids (no store with anyStore).
local function breaks(rule, occupant, required)
    if required then
        if occupant == nil then
            return not rule.allowEmpty
        end
        return not contains(rule.clsids, occupant)
    end
    return occupant ~= nil and (rule.anyStore == true or contains(rule.clsids, occupant))
end

local RULE_KINDS = { { "forbidden", false }, { "required", true } }

-- Whether store c can join a (station -> CLSID) on station s without breaking
-- a rule of either side; a required rule on a station still empty is left to
-- the complete assignment.
local function allowed(a, rules, s, c)
    for _, kr in ipairs(RULE_KINDS) do
        local kind, required = kr[1], kr[2]
        for _, r in ipairs(rules[s][c][kind] or {}) do
            local occupant = r.station == s and c or a[r.station]
            if occupant ~= nil and breaks(r, occupant, required) then
                return false
            end
        end
        for t, o in pairs(a) do
            for _, r in ipairs(rules[t][o][kind] or {}) do
                if r.station == s and breaks(r, c, required) then
                    return false
                end
            end
        end
    end
    return true
end

-- Whether stores of pool (indexes, each used once) can fill every station a
-- required rule of a needs, keeping every rule; a is restored.
local function complete(a, rules, clsids, options, pool)
    local need
    for t, o in pairs(a) do
        for _, r in ipairs(rules[t][o].required or {}) do
            if breaks(r, a[r.station], true) then
                need = r
                break
            end
        end
        if need ~= nil then
            break
        end
    end
    if need == nil then
        return true
    end
    local s = need.station
    if a[s] ~= nil then
        return false
    end
    local tried = {}
    for n, j in ipairs(pool) do
        local c = clsids[j]
        if not tried[c] and contains(need.clsids, c) and contains(options[j], s) then
            tried[c] = true
            if allowed(a, rules, s, c) then
                local rest = {}
                for m, k in ipairs(pool) do
                    if m ~= n then
                        rest[#rest + 1] = k
                    end
                end
                a[s] = c
                local done = complete(a, rules, clsids, options, rest)
                a[s] = nil
                if done then
                    return true
                end
            end
        end
    end
    return false
end

-- The first assignment of stores idx (in order, each on its lowest station
-- that leaves the rest placeable) keeping every rule, stations required rules
-- need left empty only where stores of pool (nil: none) can fill them; nil if
-- none.
local function place(clsids, options, idx, rules, pool)
    local a, at = {}, {}
    local function step(k)
        if k > #idx then
            return complete(a, rules, clsids, options, pool or {})
        end
        local i = idx[k]
        -- A store equal to an earlier one goes above it (same fits, fewer tries).
        local low
        for m = 1, k - 1 do
            local j = idx[m]
            if clsids[j] == clsids[i] and (low == nil or at[j] > low) then
                low = at[j]
            end
        end
        for _, s in ipairs(options[i]) do
            if a[s] == nil and (low == nil or s > low) and allowed(a, rules, s, clsids[i]) then
                a[s], at[i] = clsids[i], s
                local rest = {}
                for m = k + 1, #idx do
                    local free = {}
                    for _, t in ipairs(options[idx[m]]) do
                        if a[t] == nil then
                            free[#free + 1] = t
                        end
                    end
                    rest[#rest + 1] = free
                end
                if matching(rest) == #rest and step(k + 1) then
                    return true
                end
                a[s], at[i] = nil, nil
            end
        end
        return false
    end
    if step(1) then
        return a
    end
    return nil
end

---@param aircraftId string
---@param clsids string[]
---@return DcsFitResult
function M.fitStores(aircraftId, clsids)
    -- Same lookup order, hence same error, as stationsAccepting per store.
    if #clsids > 0 then
        record("stores", clsids[1])
    end
    local all = stations(aircraftId)
    for i = 2, #clsids do
        record("stores", clsids[i])
    end
    local rules, accepting = {}, {}
    for _, c in ipairs(clsids) do
        accepting[c] = {}
    end
    for _, s in ipairs(all) do
        rules[s.station] = {}
        local here = {}
        for _, a in ipairs(s.accepts) do
            local opts = accepting[a.clsid]
            if opts ~= nil then
                rules[s.station][a.clsid] = a
                if not here[a.clsid] then
                    here[a.clsid] = true
                    opts[#opts + 1] = s.station
                end
            end
        end
    end
    local options, ruled = {}, false
    for i, c in ipairs(clsids) do
        options[i] = accepting[c]
        for _, s in ipairs(options[i]) do
            local r = rules[s][c]
            ruled = ruled or #(r.forbidden or {}) > 0 or #(r.required or {}) > 0
        end
    end
    local function later(i)
        local pool = {}
        for k = i + 1, #clsids do
            if #options[k] > 0 then
                pool[#pool + 1] = k
            end
        end
        return pool
    end
    local conflicts, kept = {}, {}
    local placed
    for i, opts in ipairs(options) do
        local reason
        local trial, idx = {}, {}
        for k, j in ipairs(kept) do
            trial[k], idx[k] = options[j], j
        end
        trial[#trial + 1], idx[#idx + 1] = opts, i
        if #opts == 0 then
            reason = "unsupported"
        elseif matching(trial) ~= #trial then
            reason = "noFreeStation"
        elseif ruled then
            -- Without rules every placement that fits keeps them.
            placed = place(clsids, options, idx, rules, later(i))
            if placed == nil then
                reason = "loadoutRules"
            end
        end
        if reason == nil then
            kept[#kept + 1] = i
        else
            conflicts[#conflicts + 1] = { index = i, clsid = clsids[i], reason = reason }
        end
    end
    if #conflicts > 0 then
        return { conflicts = conflicts }
    end
    -- With no conflicts the last store's placement is that of every store.
    return { assignment = placed or place(clsids, options, kept, rules) or {} }
end

---@param aircraftId string
---@param loadout table<integer, string>
---@param fuelKg number?
---@return DcsLoadoutMass
function M.loadoutMass(aircraftId, loadout, fuelKg)
    local aero = record("aircraft", aircraftId).aero or {}
    if aero.emptyMassKg == nil then
        error("dcs_world_reference: aircraft " .. aircraftId .. " has no aero.emptyMassKg", 2)
    end
    local capacity = aero.internalFuelKg
    if fuelKg == nil then
        if capacity == nil then
            error("dcs_world_reference: aircraft " .. aircraftId .. " has no aero.internalFuelKg; pass fuelKg", 2)
        end
        fuelKg = capacity
    end
    if fuelKg < 0 or (capacity ~= nil and fuelKg > capacity) then
        error("dcs_world_reference: fuel " .. fuelKg .. " kg outside 0.." .. tostring(capacity) .. " kg", 2)
    end
    local keys = {}
    for station in pairs(loadout) do
        keys[#keys + 1] = station
    end
    table.sort(keys)
    local storesKg = 0
    for _, station in ipairs(keys) do
        local clsid = loadout[station]
        if not M.canMount(aircraftId, station, clsid) then
            error("dcs_world_reference: station " .. station .. " of " .. aircraftId .. " does not accept " .. clsid, 2)
        end
        local mass = record("stores", clsid).aero
        mass = mass and mass.massKg
        if mass == nil then
            error("dcs_world_reference: store " .. clsid .. " has no aero.massKg", 2)
        end
        storesKg = storesKg + mass
    end
    local total = aero.emptyMassKg + storesKg + fuelKg
    local out = { totalKg = total, emptyKg = aero.emptyMassKg, storesKg = storesKg, fuelKg = fuelKg }
    if aero.maxTakeoffKg ~= nil then
        out.maxTakeoffKg = aero.maxTakeoffKg
        out.overMtow = total > aero.maxTakeoffKg
    end
    return out
end

-- Radios

---@param aircraftId string
---@return DcsRadioBands[]
function M.radioBands(aircraftId)
    local radios, out = M.load("radios"), {}
    for _, rid in ipairs(record("aircraft", aircraftId).radios or {}) do
        local r = radios[rid]
        if r == nil then
            error("dcs_world_reference: no radios record " .. rid, 2)
        end
        local head, idx = rid:match("^(.*)__radio(%d+)$")
        if head ~= aircraftId then
            error("dcs_world_reference: radio id " .. rid .. " is not " .. aircraftId .. "__radio<index>", 2)
        end
        local ranges = {}
        for i, s in ipairs(r.segments) do
            ranges[i] = { minMHz = s.minMHz, maxMHz = s.maxMHz, modulations = { s.modulationName } }
        end
        out[#out + 1] = {
            index = tonumber(idx),
            id = rid,
            band = r.band,
            ranges = ranges,
            presets = r.presets,
            guard = r.guard,
            stepKHz = r.stepKHz,
        }
    end
    table.sort(out, function(p, q)
        return p.index < q.index
    end)
    return out
end

M.STEP_TOLERANCE = 1e-6

---@param aircraftId string
---@param radioIndex integer
---@param mhz number
---@return DcsFrequencyCheck
function M.isValidFrequency(aircraftId, radioIndex, mhz)
    for _, r in ipairs(M.radioBands(aircraftId)) do
        if r.index == radioIndex then
            local inside = false
            for _, g in ipairs(r.ranges) do
                inside = inside or (g.minMHz <= mhz and mhz <= g.maxMHz)
            end
            if not inside then
                return { ok = false, reason = "outOfRange" }
            end
            if r.stepKHz ~= nil then
                local steps = mhz * 1000 / r.stepKHz
                if math.abs(steps - math.floor(steps + 0.5)) > M.STEP_TOLERANCE then
                    return { ok = false, reason = "offStep" }
                end
            end
            return { ok = true }
        end
    end
    error("dcs_world_reference: aircraft " .. aircraftId .. " has no radio " .. tostring(radioIndex), 2)
end

-- Weapons

local function shallow(t, drop)
    local out = {}
    for k, v in pairs(t) do
        if not (drop and drop[k]) then
            out[k] = v
        end
    end
    return out
end

local function sorted(list)
    table.sort(list)
    return list
end

local function is_integer(v)
    return type(v) == "number" and v == math.floor(v)
end

---@param idOrClsid string
---@return DcsWeaponInfo
function M.weaponInfo(idOrClsid)
    local id = idOrClsid
    if M.load("weapons")[id] == nil then
        local store = M.load("stores")[idOrClsid]
        if store == nil then
            error("dcs_world_reference: no weapon or store " .. tostring(idOrClsid), 2)
        end
        local seen, delivered = {}, {}
        for _, d in ipairs(store.delivers or {}) do
            if not seen[d.weapon] then
                seen[d.weapon] = true
                delivered[#delivered + 1] = d.weapon
            end
        end
        if #delivered ~= 1 then
            error("dcs_world_reference: store " .. idOrClsid .. " delivers " .. #delivered .. " weapon types, not one", 2)
        end
        id = delivered[1]
    end
    local weapon = record("weapons", id)
    local out = shallow(weapon, { _source = true })
    if weapon.warhead ~= nil then
        out.warhead = shallow(record("warheads", weapon.warhead))
    end
    return out
end

local function surface_launchers(series, weaponId)
    local out = {}
    for uid, u in pairs(M.load(series)) do
        local hit = false
        for _, ws in ipairs(u.weaponSystems or {}) do
            hit = hit or contains(ws.weapons or {}, weaponId)
        end
        if hit then
            out[#out + 1] = uid
        end
    end
    return sorted(out)
end

---@param weaponId string
---@return DcsLaunchPlatforms
function M.launchPlatforms(weaponId)
    record("weapons", weaponId)
    return {
        aircraft = M.aircraftCarrying(weaponId),
        groundVehicles = surface_launchers("ground_vehicles", weaponId),
        ships = surface_launchers("ships", weaponId),
    }
end

---@param shape string
---@return string[]
function M.modelToUnits(shape)
    local key, out = M.nameKey(shape), {}
    for _, s in ipairs(index("meta").unitSeries) do
        for uid, u in pairs(M.load(s)) do
            local model = u.model and u.model.shape
            if type(model) == "string" and M.nameKey(model) == key then
                out[#out + 1] = uid
            end
        end
    end
    return sorted(out)
end

---@param unitId string
---@return DcsUnitDetection
function M.unitDetection(unitId)
    local series = unit_series(unitId)
    if series == nil then
        error("dcs_world_reference: no unit type " .. tostring(unitId), 2)
    end
    local u = M.load(series)[unitId]
    local out = shallow(u.detection or {})
    local sensors = {}
    for i, sid in ipairs(u.sensors or {}) do
        local s = record("sensors", sid)
        sensors[i] = { id = sid, kind = s.kind, detectionRangeKm = s.detectionRangeKm }
    end
    out.sensors = sensors
    return out
end

-- TACAN and navaids

M.FREQUENCY_TOLERANCE_MHZ = 1e-6

---@param channel number
---@param band string
---@return boolean
function M.isValidTacan(channel, band)
    local plan = index("tacan")
    return is_integer(channel)
        and plan.channels.first <= channel
        and channel <= plan.channels["last"]
        and contains(plan.bands, band)
end

local function in_range(ranges, channel)
    for _, r in ipairs(ranges) do
        if r.from <= channel and channel <= r.to then
            return r
        end
    end
    return nil
end

-- interrogation MHz, reply MHz, paired VHF MHz or nil
local function tacan(channel, band)
    local plan = index("tacan")
    local air = plan.interrogationMHz.base + channel - plan.channels.first
    local reply = in_range(plan.replyOffsetMHz[band], channel)
    local pairing = plan.vhfPairing
    local hit, vhf = in_range(pairing.ranges, channel), nil
    if hit ~= nil then
        local khz = hit.baseKHz + (channel - hit.from) * pairing.stepKHz
        vhf = (khz + pairing.bandOffsetKHz[band]) / 1000
    end
    return air, air + reply.offset, vhf
end

---@param channel integer
---@param band 'X'|'Y'
---@param role 'air'|'ground'
---@return DcsTacanFrequency
function M.tacanFrequency(channel, band, role)
    if not M.isValidTacan(channel, band) then
        error("dcs_world_reference: no TACAN channel " .. tostring(channel) .. tostring(band), 2)
    end
    if role ~= "air" and role ~= "ground" then
        error("dcs_world_reference: role must be air or ground, got " .. tostring(role), 2)
    end
    local air, reply, vhf = tacan(channel, band)
    local out
    if role == "air" then
        out = { txMHz = air, rxMHz = reply }
    else
        out = { txMHz = reply, rxMHz = air }
    end
    out.pairedVhfMHz = vhf
    return out
end

---@param mhz number
---@param role 'air'|'ground'|'vhf'
---@return DcsTacanChannel[]
function M.tacanChannel(mhz, role)
    if role ~= "air" and role ~= "ground" and role ~= "vhf" then
        error("dcs_world_reference: role must be air, ground or vhf, got " .. tostring(role), 2)
    end
    local plan, out = index("tacan"), {}
    for ch = plan.channels.first, plan.channels["last"] do
        for _, band in ipairs(plan.bands) do
            local air, reply, vhf = tacan(ch, band)
            local value = ({ air = air, ground = reply, vhf = vhf })[role]
            if value ~= nil and math.abs(value - mhz) <= M.FREQUENCY_TOLERANCE_MHZ then
                out[#out + 1] = { channel = ch, band = band }
            end
        end
    end
    return out
end

local function airbase(airbaseId)
    return record("airbases", airbaseId)
end

---@param airbaseId string
---@param runway string?
---@return string[]
function M.navaidsFor(airbaseId, runway)
    local ab = airbase(airbaseId)
    if runway == nil then
        return sorted(copy(ab.navaids))
    end
    local key = M.nameKey(runway)
    for _, rwy in ipairs(ab.runways or {}) do
        for _, d in ipairs(rwy.directions) do
            if M.nameKey(d.designator) == key then
                return sorted(copy(d.navaids))
            end
        end
    end
    error("dcs_world_reference: airbase " .. airbaseId .. " has no runway end " .. tostring(runway), 2)
end

-- Runways and stands

---@param airbaseId string
---@return DcsRunwayEnd[]
function M.runwayEnds(airbaseId)
    local out = {}
    for _, rwy in ipairs(airbase(airbaseId).runways or {}) do
        for _, d in ipairs(rwy.directions) do
            local t = d.threshold
            out[#out + 1] = {
                runway = rwy.designator,
                designator = d.designator,
                name = d.name,
                trueDeg = d.trueBearingDeg,
                magDeg = d.magneticBearingDeg,
                threshold = { lat = t.latitude, lon = t.longitude, elevationM = t.elevationM },
                lengthM = rwy.lengthM,
            }
        end
    end
    return out
end

M.WIND_TOLERANCE_KT = 1e-9

local function better(a, b)
    if math.abs(a.headwindKt - b.headwindKt) > M.WIND_TOLERANCE_KT then
        return a.headwindKt > b.headwindKt
    end
    if math.abs(a.crosswindKt - b.crosswindKt) > M.WIND_TOLERANCE_KT then
        return a.crosswindKt < b.crosswindKt
    end
    if a["end"].lengthM ~= b["end"].lengthM then
        return a["end"].lengthM > b["end"].lengthM
    end
    return a["end"].designator < b["end"].designator
end

---@param airbaseId string
---@param windFromDegTrue number
---@param windKt number
---@return DcsBestRunway
function M.bestRunway(airbaseId, windFromDegTrue, windKt)
    if not (windKt >= 0) then
        error("dcs_world_reference: wind speed must be >= 0 kt, got " .. tostring(windKt), 2)
    end
    local best
    for _, e in ipairs(M.runwayEnds(airbaseId)) do
        local a = (windFromDegTrue - e.trueDeg) * RAD
        local cand = { ["end"] = e, headwindKt = windKt * math.cos(a), crosswindKt = math.abs(windKt * math.sin(a)) }
        if best == nil or better(cand, best) then
            best = cand
        end
    end
    if best == nil then
        error("dcs_world_reference: airbase " .. airbaseId .. " has no runway data", 2)
    end
    return best
end

M.NM_M = 1852.0

---@param theatre string
---@param lat number
---@param lon number
---@param options { minRunwayM: number?, n: integer?, category: string? }?
---@return DcsNearbyAirbase[]
function M.nearestAirbases(theatre, lat, lon, options)
    options = options or {}
    local n = options.n
    if n == nil then
        n = 5
    end
    if not is_integer(n) or n < 1 then
        error("dcs_world_reference: n must be an integer of at least 1, got " .. tostring(n), 2)
    end
    local t = M.theatreByName(theatre)
    if t == nil then
        error("dcs_world_reference: no theatre " .. tostring(theatre), 2)
    end
    local found = {}
    for aid, ab in pairs(M.load("airbases")) do
        local p = ab.referencePoint
        if ab.theatre == t.id and p ~= nil
            and (options.minRunwayM == nil or (ab.longestRunwayM or -1) >= options.minRunwayM)
            and (options.category == nil or M.nameKey(ab.categoryName or "") == M.nameKey(options.category))
        then
            local db = M.distanceBearing(lat, lon, p.latitude, p.longitude)
            found[#found + 1] = { d = db.distM, id = aid, b = db.bearingDeg }
        end
    end
    table.sort(found, function(p, q)
        if p.d ~= q.d then
            return p.d < q.d
        end
        return p.id < q.id
    end)
    local out = {}
    for i = 1, math.min(n, #found) do
        out[i] = { id = found[i].id, distNm = found[i].d / M.NM_M, bearingDeg = found[i].b }
    end
    return out
end

---@param airbaseId string
---@param aircraftId string
---@return integer[]
function M.standsFor(airbaseId, aircraftId)
    local a = record("aircraft", aircraftId)
    local dims = a.dimensions or {}
    local width = dims.wingSpanM
    if width == nil then
        width = dims.rotorDiameterM
    end
    if width == nil or dims.lengthM == nil or dims.heightM == nil then
        error("dcs_world_reference: aircraft " .. aircraftId .. " lacks the dimensions stands check", 2)
    end
    local use = a.kind == "rotary" and "helicopters" or "airplanes"
    local out = {}
    for _, s in ipairs(airbase(airbaseId).stands or {}) do
        local lim = s.limits
        if lim ~= nil
            and width < lim.maxWidthM
            and dims.lengthM < lim.maxLengthM
            and dims.heightM < (lim.maxHeightM or 1000)
            and lim[use]
        then
            out[#out + 1] = s.termIndex
        end
    end
    return sorted(out)
end

-- Countries, liveries and datalinks

local COUNTRY_NAMES = { "name", "shortName", "internationalName", "idName", "oldId" }

---@param nameOrAlias string
---@return integer?
function M.countryId(nameOrAlias)
    local key = M.nameKey(nameOrAlias)
    for _, c in pairs(M.load("countries")) do
        for _, f in ipairs(COUNTRY_NAMES) do
            if type(c[f]) == "string" and M.nameKey(c[f]) == key then
                return c.id
            end
        end
    end
    return index("countryAliases")[key]
end

---@param countryId integer
---@return string
function M.countryName(countryId)
    return record("countries", tostring(countryId)).name
end

---@param unitType string
---@param countryId integer?
---@return string[]
function M.liveriesFor(unitType, countryId)
    if unit_series(unitType) == nil then
        error("dcs_world_reference: no unit type " .. tostring(unitType), 2)
    end
    if countryId ~= nil then
        record("countries", tostring(countryId))
        -- The Combined Joint Task Forces get every livery (loadLiveries.lua).
        if index("allLiveryCountries")[tostring(countryId)] ~= nil then
            countryId = nil
        end
    end
    local out = {}
    for lid, lv in pairs(M.load("liveries")) do
        if contains(lv.unitTypes, unitType)
            and (countryId == nil or lv.countries == nil or contains(lv.countries, countryId))
        then
            out[#out + 1] = lid
        end
    end
    return sorted(out)
end

---@param aircraftId string
---@return DcsDatalinkCapability?
function M.datalinkCapability(aircraftId)
    local dl = record("aircraft", aircraftId).datalink
    if dl == nil then
        return nil
    end
    return shallow(record("datalink", dl), { id = true })
end

-- Geo

local function check_lat_lon(lat, lon)
    if not (-90 <= lat and lat <= 90 and -180 <= lon and lon <= 180) then
        error("dcs_world_reference: latitude " .. tostring(lat) .. " / longitude " .. tostring(lon) .. " out of range", 3)
    end
end

---@param lat1 number
---@param lon1 number
---@param lat2 number
---@param lon2 number
---@return DcsDistanceBearing
function M.distanceBearing(lat1, lon1, lat2, lon2)
    check_lat_lon(lat1, lon1)
    check_lat_lon(lat2, lon2)
    local p1, p2 = lat1 * RAD, lat2 * RAD
    local dp, dl = p2 - p1, (lon2 - lon1) * RAD
    local a = math.sin(dp / 2) ^ 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ^ 2
    local dist = 2 * M.EARTH_RADIUS_M * math.asin(math.sqrt(math.min(1, a)))
    local theta = math.atan2(math.sin(dl) * math.cos(p2), math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl))
    local deg = theta * DEG
    if deg < 0 then
        deg = deg + 360
    end
    if deg >= 360 then
        deg = deg - 360
    end
    return { distM = dist, bearingDeg = deg }
end

---@param lat number
---@param lon number
---@param bearingDeg number
---@param distM number
---@return DcsLatLon
function M.destination(lat, lon, bearingDeg, distM)
    check_lat_lon(lat, lon)
    local p = destination(lat, lon, bearingDeg, distM)
    return { lat = p[2], lon = p[1] }
end

-- format -> { default, largest } precision
local PRECISION = { DD = { 6, 8 }, DMS = { 0, 4 }, DDM = { 3, 6 }, MGRS = { 5, 5 } }

local function pad(n, width)
    return string.format("%0" .. width .. "d", n)
end

local function angle(value, fmt, precision, hemis)
    local unit = 10 ^ precision
    local scale = ({ DD = 1, DDM = 60, DMS = 3600 })[fmt] * unit
    local total = math.floor(math.abs(value) * scale + 0.5)
    local hemi = (value < 0 and total > 0) and hemis:sub(2, 2) or hemis:sub(1, 1)
    local whole = math.floor(total / unit)
    local frac = total - whole * unit
    local tail = precision > 0 and ("." .. pad(frac, precision)) or ""
    if fmt == "DD" then
        return hemi .. " " .. string.format("%d", whole) .. tail .. "\194\176"
    end
    if fmt == "DDM" then
        return hemi .. " " .. string.format("%d", math.floor(whole / 60)) .. "\194\176" .. pad(whole % 60, 2) .. tail .. "'"
    end
    return hemi .. " " .. string.format("%d", math.floor(whole / 3600)) .. "\194\176"
        .. pad(math.floor(whole / 60) % 60, 2) .. "'" .. pad(whole % 60, 2) .. tail .. '"'
end

-- UTM/MGRS (WGS84): the Transverse Mercator above with k0 0.9996, false
-- easting 500 km and false northing 10000 km south of the equator.
local BANDS = "CDEFGHJKLMNPQRSTUVWX"
local COLUMNS = { "ABCDEFGH", "JKLMNPQR", "STUVWXYZ" }
local ROWS = "ABCDEFGHJKLMNPQRSTUV"

local function utm(zone, south)
    return {
        centralMeridian = zone * 6 - 183,
        scaleFactor = 0.9996,
        falseEasting = 500000.0,
        falseNorthing = south and 10000000.0 or 0.0,
    }
end

local function band_lat(band)
    local south = -80 + 8 * (BANDS:find(band, 1, true) - 1)
    return south, band == "X" and 84.0 or south + 8
end

local function mgrs(lat, lon, precision)
    if not (-80 <= lat and lat <= 84) then
        error("dcs_world_reference: MGRS covers latitudes -80 to 84 (UTM), got " .. tostring(lat), 3)
    end
    local zone = math.min(math.floor((lon + 180) / 6) + 1, 60)
    local bi = math.min(math.floor((lat + 80) / 8), 19)
    local band = BANDS:sub(bi + 1, bi + 1)
    if band == "V" and zone == 31 and lon >= 3 then
        zone = 32
    elseif band == "X" and 0 <= lon and lon < 42 then
        zone = lon < 9 and 31 or lon < 21 and 33 or lon < 33 and 35 or 37
    end
    local n, e = to_map(utm(zone, lat < 0), lat, lon)
    local col = math.floor(e / 100000)
    local row = (math.floor(n / 100000) + (zone % 2 == 0 and 5 or 0)) % 20
    local columns = COLUMNS[(zone - 1) % 3 + 1]
    local letters = string.format("%d", zone) .. " " .. band .. " " .. columns:sub(col, col) .. ROWS:sub(row + 1, row + 1)
    if precision == 0 then
        return letters
    end
    local div = 10 ^ (5 - precision)
    local de = math.floor((math.floor(e) % 100000) / div)
    local dn = math.floor((math.floor(n) % 100000) / div)
    return letters .. " " .. pad(de, precision) .. " " .. pad(dn, precision)
end

---@param lat number
---@param lon number
---@param fmt 'DD'|'DMS'|'DDM'|'MGRS'
---@param precision integer?
---@return string
function M.formatCoord(lat, lon, fmt, precision)
    local limits = PRECISION[fmt]
    if limits == nil then
        error("dcs_world_reference: format must be one of DD, DMS, DDM, MGRS, got " .. tostring(fmt), 2)
    end
    local p = precision
    if p == nil then
        p = limits[1]
    end
    if not is_integer(p) or p < 0 or p > limits[2] then
        error("dcs_world_reference: " .. fmt .. " precision must be an integer 0-" .. limits[2] .. ", got " .. tostring(p), 2)
    end
    check_lat_lon(lat, lon)
    if fmt == "MGRS" then
        return mgrs(lat, lon, p)
    end
    return angle(lat, fmt, p, "NS") .. "   " .. angle(lon, fmt, p, "EW")
end

-- {kind, text} tokens: num (sign, digits, optional decimals), word (letters),
-- mark (* for the degree sign, ', "); blanks and commas separate. Upper-cased,
-- after the first colon.
local function tokens(text)
    local s = text
    local colon = s:find(":", 1, true)
    if colon then
        s = s:sub(colon + 1)
    end
    s = s:gsub("\194\176", "*")
    if s:find("[\128-\255]") then
        error("dcs_world_reference: unexpected non-ASCII text in " .. text, 4)
    end
    s = s:upper()
    local out, i, len = {}, 1, #s
    local function digit(k)
        local b = s:byte(k)
        return b ~= nil and b >= 48 and b <= 57
    end
    local function letter(k)
        local b = s:byte(k)
        return b ~= nil and b >= 65 and b <= 90
    end
    while i <= len do
        local c = s:sub(i, i)
        if c == " " or c == "\t" or c == "," then
            i = i + 1
        elseif c == "*" or c == "'" or c == '"' then
            out[#out + 1] = { "mark", c }
            i = i + 1
        elseif letter(i) then
            local j = i
            while letter(j) do
                j = j + 1
            end
            out[#out + 1] = { "word", s:sub(i, j - 1) }
            i = j
        elseif c == "+" or c == "-" or digit(i) then
            local j = (c == "+" or c == "-") and i + 1 or i
            local k = j
            while digit(k) do
                k = k + 1
            end
            if k == j then
                error("dcs_world_reference: bad number in " .. text, 4)
            end
            if s:sub(k, k) == "." then
                local m = k + 1
                while digit(m) do
                    m = m + 1
                end
                if m == k + 1 then
                    error("dcs_world_reference: bad number in " .. text, 4)
                end
                k = m
            end
            out[#out + 1] = { "num", s:sub(i, k - 1) }
            i = k
        else
            error("dcs_world_reference: unexpected " .. c .. " in " .. text, 4)
        end
    end
    return out
end

local function number(t)
    local sign, rest = 1, t
    if rest:sub(1, 1) == "+" then
        rest = rest:sub(2)
    elseif rest:sub(1, 1) == "-" then
        sign, rest = -1, rest:sub(2)
    end
    return sign * tonumber(rest)
end

local function unsigned(t)
    return t[1] == "num" and t[2]:find("^%d+$") ~= nil
end

local function parse_mgrs(toks, text)
    local zone = tonumber(toks[1][2])
    local i, letters = 2, ""
    while i <= #toks and toks[i][1] == "word" do
        letters = letters .. toks[i][2]
        i = i + 1
    end
    local rest = {}
    for k = i, #toks do
        rest[#rest + 1] = toks[k]
    end
    local ok = #letters == 3 and #rest <= 2
    for _, t in ipairs(rest) do
        ok = ok and unsigned(t)
    end
    if not ok then
        error("dcs_world_reference: not an MGRS reference: " .. text, 3)
    end
    local es, ns = "", ""
    if #rest == 2 then
        es, ns = rest[1][2], rest[2][2]
    elseif #rest == 1 then
        local half = math.floor(#rest[1][2] / 2)
        es, ns = rest[1][2]:sub(1, half), rest[1][2]:sub(half + 1)
    end
    if #es ~= #ns or #es > 5 then
        error("dcs_world_reference: MGRS easting and northing need 0-5 digits each: " .. text, 3)
    end
    local band, col, row = letters:sub(1, 1), letters:sub(2, 2), letters:sub(3, 3)
    local columns = COLUMNS[(zone - 1) % 3 + 1]
    local ci, ri = columns:find(col, 1, true), ROWS:find(row, 1, true)
    if BANDS:find(band, 1, true) == nil or ci == nil or ri == nil then
        error("dcs_world_reference: bad MGRS letters " .. letters .. " for zone " .. zone .. ": " .. text, 3)
    end
    local size = 10 ^ (5 - #es)
    local e = ci * 100000 + ((tonumber(es) or 0) + 0.5) * size
    local n = ((ri - 1 - (zone % 2 == 0 and 5 or 0)) % 20) * 100000 + ((tonumber(ns) or 0) + 0.5) * size
    local lo, hi = band_lat(band)
    local p = utm(zone, lo < 0)
    local mid = to_map(p, (lo + hi) / 2, p.centralMeridian)
    n = n + math.floor((mid - n) / 2000000 + 0.5) * 2000000
    local ll = inverse(p, n, e)
    if not (lo - 0.5 <= ll.lat and ll.lat <= hi + 0.5) then
        error("dcs_world_reference: MGRS square " .. col .. row .. " is not in band " .. band .. ": " .. text, 3)
    end
    return { format = "MGRS", lat = ll.lat, lon = ll.lon }
end

-- signed degrees, component count, next index of `H d [m [s]]`
local function parse_half(toks, i, hemis, text)
    local t = toks[i]
    if t == nil or t[1] ~= "word" or (t[2] ~= hemis:sub(1, 1) and t[2] ~= hemis:sub(2, 2)) then
        error("dcs_world_reference: expected " .. hemis:sub(1, 1) .. " or " .. hemis:sub(2, 2) .. " in " .. text, 3)
    end
    local sign = t[2] == hemis:sub(2, 2) and -1 or 1
    i = i + 1
    local parts = {}
    while i <= #toks and toks[i][1] == "num" and #parts < 3 do
        if toks[i][2]:find("^[%d%.]+$") == nil then
            error("dcs_world_reference: signed angle component in " .. text, 3)
        end
        parts[#parts + 1] = toks[i][2]
        i = i + 1
        if i <= #toks and toks[i][1] == "mark" then
            local want = ("*'\""):sub(#parts, #parts)
            if toks[i][2] ~= want then
                error("dcs_world_reference: misplaced " .. toks[i][2] .. " in " .. text, 3)
            end
            i = i + 1
        end
    end
    if #parts == 0 then
        error("dcs_world_reference: no angle after " .. hemis:sub(1, 1) .. "/" .. hemis:sub(2, 2) .. " in " .. text, 3)
    end
    for k = 1, #parts - 1 do
        if parts[k]:find(".", 1, true) then
            error("dcs_world_reference: only the last component may have decimals: " .. text, 3)
        end
    end
    local values = {}
    for k, p in ipairs(parts) do
        values[k] = tonumber(p)
        if k > 1 and values[k] >= 60 then
            error("dcs_world_reference: minutes and seconds must be below 60: " .. text, 3)
        end
    end
    local deg = values[1]
    if #values > 1 then
        deg = deg + values[2] / 60
    end
    if #values > 2 then
        deg = deg + values[3] / 3600
    end
    return sign * deg, #parts, i
end

---@param text string
---@return DcsParsedCoord
function M.parseCoord(text)
    local toks = tokens(text)
    local kinds = {}
    for k, t in ipairs(toks) do
        kinds[k] = t[1]
    end
    local shape = table.concat(kinds, ",")
    if shape == "word,num,word,num" and toks[1][2] == "X" and toks[3][2] == "Z" then
        return { format = "METRIC", x = number(toks[2][2]), z = number(toks[4][2]) }
    end
    if kinds[1] == "num" and kinds[2] == "word" and unsigned(toks[1]) and #toks[1][2] <= 2 then
        local zone = tonumber(toks[1][2])
        if zone >= 1 and zone <= 60 then
            return parse_mgrs(toks, text)
        end
    end
    local lat, lon, fmt
    if shape == "num,num" then
        lat, lon, fmt = number(toks[1][2]), number(toks[2][2]), "DD"
    else
        local nLat, nLon, i
        lat, nLat, i = parse_half(toks, 1, "NS", text)
        lon, nLon, i = parse_half(toks, i, "EW", text)
        if i ~= #toks + 1 or nLat ~= nLon then
            error("dcs_world_reference: latitude and longitude need the same form: " .. text, 2)
        end
        fmt = nLat == 1 and "DD" or nLat == 2 and "DDM" or "DMS"
    end
    check_lat_lon(lat, lon)
    return { format = fmt, lat = lat, lon = lon }
end

setmetatable(M, {
    __index = function(_, name)
        if name == "dcsVersion" then
            return M.load("manifest").dcsVersion
        end
        return M.load(name)
    end,
})

return M
