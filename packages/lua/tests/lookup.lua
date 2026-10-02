-- lua5.1 lookup.lua <package dir>: call every lookup helper for every record
-- and print the results as JSON on stdout (checked by test_lua.py).
local ref = dofile(arg[1] .. "/dcs_world_reference/init.lua")

local function str(s)
    return '"' .. s:gsub('[%c"\\]', function(c)
        return string.format("\\u%04x", c:byte())
    end) .. '"'
end

local function list(t)
    local parts = {}
    for i, v in ipairs(t) do
        parts[i] = str(v)
    end
    return "[" .. table.concat(parts, ",") .. "]"
end

local function object(entries)
    return "{" .. table.concat(entries, ",") .. "}"
end

local function sorted_keys(t)
    local keys = {}
    for k in pairs(t) do
        keys[#keys + 1] = k
    end
    table.sort(keys)
    return keys
end

local function ascii_upper(s)
    return (s:gsub("%l", string.upper))
end

local meta = ref.load("_index_meta")
local all_series = {}
for _, r in ipairs(meta.relations) do
    all_series[r.series] = true
end
for _, s in ipairs(meta.references) do
    all_series[s] = true
end
for _, s in ipairs(meta.names) do
    all_series[s] = true
end

local refs, names = {}, {}
for _, series in ipairs(sorted_keys(all_series)) do
    local by_id, by_name = {}, {}
    for _, id in ipairs(sorted_keys(ref[series])) do
        local found = {}
        for i, r in ipairs(ref.referencesTo(series, id)) do
            found[i] = r.series .. "|" .. r.id .. "|" .. r.path
        end
        if #found > 0 then
            by_id[#by_id + 1] = str(id) .. ":" .. list(found)
        end
        local record = ref[series][id]
        for _, field in ipairs({ "displayName", "name" }) do
            if type(record[field]) == "string" and ref.nameKey(record[field]) ~= "" then
                local query = " " .. ascii_upper(record[field]) .. " "
                by_name[#by_name + 1] = str(field .. ":" .. id) .. ":" .. list(ref.findByName(series, query))
            end
        end
    end
    refs[#refs + 1] = str(series) .. ":" .. object(by_id)
    names[#names + 1] = str(series) .. ":" .. object(by_name)
end

local stores, carriers = {}, {}
for _, w in ipairs(sorted_keys(ref.weapons)) do
    stores[#stores + 1] = str(w) .. ":" .. list(ref.storesDelivering(w))
    carriers[#carriers + 1] = str(w) .. ":" .. list(ref.aircraftCarrying(w))
end

local threats = {}
for _, series in ipairs(meta.unitSeries) do
    for _, u in ipairs(sorted_keys(ref[series])) do
        threats[#threats + 1] = str(u) .. ":" .. list(ref.threatsForUnit(u))
    end
end

local airbases = {}
for _, id in ipairs(sorted_keys(ref.airbases)) do
    local a = ref.airbases[id]
    airbases[#airbases + 1] = str(id) .. ":" .. list(ref.airbaseByName(ascii_upper(a.name), a.theatre:lower()))
end

print(object({
    '"refs":' .. object(refs),
    '"names":' .. object(names),
    '"stores":' .. object(stores),
    '"carriers":' .. object(carriers),
    '"threats":' .. object(threats),
    '"airbases":' .. object(airbases),
    '"batumi":' .. list(ref.airbaseByName("batumi", "Caucasus")),
    '"none":' .. list(ref.findByName("racks", "x")),
    '"nameKey":' .. str(ref.nameKey("  F-16C Viper\t")),
}))
