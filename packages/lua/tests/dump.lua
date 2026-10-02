-- lua5.1 dump.lua <package dir> <series>...: load each series through init.lua
-- and print {"dcsVersion": ..., "<series>": <table as JSON>} on stdout.
local pkg, names = arg[1], { select(2, unpack(arg)) }
local ref = dofile(pkg .. "/dcs_world_reference/init.lua")

local encode

local function encode_string(s)
    return '"' .. s:gsub('[%c"\\]', function(c)
        return string.format("\\u%04x", c:byte())
    end) .. '"'
end

local function is_array(t)
    local n = 0
    for _ in pairs(t) do
        n = n + 1
    end
    for i = 1, n do
        if t[i] == nil then
            return false
        end
    end
    return true
end

function encode(v)
    local kind = type(v)
    if kind == "string" then
        return encode_string(v)
    elseif kind == "number" then
        return string.format("%.17g", v)
    elseif kind == "boolean" then
        return tostring(v)
    elseif kind == "table" then
        local out = {}
        if is_array(v) then
            for i = 1, #v do
                out[i] = encode(v[i])
            end
            return "[" .. table.concat(out, ",") .. "]"
        end
        for k, x in pairs(v) do
            out[#out + 1] = encode_string(tostring(k)) .. ":" .. encode(x)
        end
        return "{" .. table.concat(out, ",") .. "}"
    end
    error("cannot encode a " .. kind)
end

local parts = { '"dcsVersion":' .. encode(ref.dcsVersion) }
for _, name in ipairs(names) do
    parts[#parts + 1] = encode_string(name) .. ":" .. encode(ref[name])
end
io.write("{" .. table.concat(parts, ",") .. "}")
