-- lua5.1 helpers.lua <package dir> <cases file>: run every conformance vector
-- (the cases file returns {{fn=, n=, args={...}}, ...}) and print the results
-- as a JSON array, {"value": ...} or {"throws": true} each (checked by
-- test_helpers.py). Results are shaped as the vectors are: a fit assignment
-- keyed by station strings, conflict indices from 0.
local ref = dofile(arg[1] .. "/dcs_world_reference/init.lua")
local cases = dofile(arg[2])

local encode

local function sorted_keys(t)
    local keys = {}
    for k in pairs(t) do
        keys[#keys + 1] = k
    end
    table.sort(keys, function(a, b)
        return tostring(a) < tostring(b)
    end)
    return keys
end

local function is_array(t)
    local n = 0
    for _ in pairs(t) do
        n = n + 1
    end
    return n == #t
end

function encode(v)
    local kind = type(v)
    if v == nil then
        return "null"
    elseif kind == "boolean" then
        return tostring(v)
    elseif kind == "number" then
        return string.format("%.17g", v)
    elseif kind == "string" then
        return '"' .. v:gsub('[%c"\\]', function(c)
            return string.format("\\u%04x", c:byte())
        end) .. '"'
    elseif next(v) == nil then
        return "[]"
    elseif is_array(v) then
        local parts = {}
        for i, x in ipairs(v) do
            parts[i] = encode(x)
        end
        return "[" .. table.concat(parts, ",") .. "]"
    end
    local parts = {}
    for _, k in ipairs(sorted_keys(v)) do
        parts[#parts + 1] = encode(tostring(k)) .. ":" .. encode(v[k])
    end
    return "{" .. table.concat(parts, ",") .. "}"
end

local calls = {
    theatreByName = function(name)
        local t = ref.theatreByName(name)
        return t and t.id
    end,
    threatRingGeoJSON = function(id, lat, lon, segments)
        return ref.threatRingGeoJSON(id, lat, lon, { segments = segments })
    end,
    fitStores = function(id, clsids)
        local fit = ref.fitStores(id, clsids)
        if fit.conflicts then
            for _, c in ipairs(fit.conflicts) do
                c.index = c.index - 1
            end
            return fit
        end
        local assignment = {}
        for station, clsid in pairs(fit.assignment) do
            assignment[tostring(station)] = clsid
        end
        return { assignment = assignment }
    end,
    loadoutMass = function(id, loadout, fuel)
        local stations = {}
        for k, v in pairs(loadout) do
            stations[tonumber(k)] = v
        end
        return ref.loadoutMass(id, stations, fuel)
    end,
}

local out = {}
for i, c in ipairs(cases) do
    local fn = calls[c.fn] or ref[c.fn]
    local ok, result = pcall(fn, unpack(c.args, 1, c.n))
    if ok then
        out[i] = '{"value":' .. encode(result) .. "}"
    else
        out[i] = '{"throws":true,"error":' .. encode(tostring(result)) .. "}"
    end
end
print("[" .. table.concat(out, ",\n") .. "]")
