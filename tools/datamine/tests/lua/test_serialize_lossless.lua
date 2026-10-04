-- serialize.lua lossless mode (dump format 4): exact numbers, markers for
-- values Lua text cannot hold, anchors/refs for shared tables and cycles,
-- truncation markers. Checks the exact text and that the text loads back
-- (with a lossless `__dcs`) to an equal value, sharing included.
-- Usage: lua5.1 test_serialize_lossless.lua <hook-dir> <tests/lua dir>
local hookDir = assert(arg[1], 'usage: test_serialize_lossless.lua <hook-dir> <tests-lua-dir>')
local here = assert(arg[2], 'usage: test_serialize_lossless.lua <hook-dir> <tests-lua-dir>')
package.path = hookDir .. '/?.lua;' .. package.path
local serialize = require 'serialize'
local M = dofile(here .. '/dcs_markers.lua')

local OPTS = { indent = '\t', newline = '\n', lossless = true }
local function check(name, value, expected, expectBack)
  local text = serialize(value, OPTS)
  if text ~= expected then
    error(name .. ': text differs\n--- got\n' .. text .. '\n--- expected\n' .. expected, 0)
  end
  assert(serialize(value, OPTS) == text, name .. ': not deterministic')
  M.same(expectBack or value, M.load(text), name)
  return text
end

local z = 0
local negzero = -z

-- 1. Numbers: shortest round trip, integers in full, specials as markers.
check('numbers', {
  0.3490658503988659, 0.1 + 0.2, 1e-300, 2 ^ 53, 2 ^ 63, 123456789012, -7, 0.5, 1 / 3,
  math.rad(20), 1e300, 4.9406564584124654e-324,
}, '{ 0.3490658503988659, 0.30000000000000004, 1e-300, 9007199254740992,'
  .. ' 9.223372036854776e+18, 123456789012, -7, 0.5, 0.3333333333333333,'
  .. ' 0.3490658503988659, 1e+300, 4.94065645841247e-324 }')

-- Every double of a sample reads back exactly.
for _, x in ipairs({ 0.1, 2 / 3, 1e-5, 96.52423333333333, 0.34906585039887, 5e-324, 1.7976931348623157e308 }) do
  local s = assert(serialize.exactNumber(x))
  assert(tonumber(s) == x, 'round trip ' .. s)
end

check('specials', { nz = negzero, inf = math.huge, ninf = -math.huge, nan = 0 / 0, zero = 0 },
  '{\n'
  .. '\tinf = __dcs{kind="number", value="inf"},\n'
  .. '\tnan = __dcs{kind="number", value="nan"},\n'
  .. '\tninf = __dcs{kind="number", value="-inf"},\n'
  .. '\tnz = __dcs{kind="number", value="-0"},\n'
  .. '\tzero = 0\n'
  .. '}')

-- 2. Functions, userdata and threads are markers, also inside sequences.
local ud = newproxy and newproxy(false) or io.stdout
local co = coroutine.create(function() end)
check('unwritable', { fn = print, ud = ud, co = co, seq = { 1, print, 3 } },
  '{\n'
  .. '\tco = __dcs{kind="thread"},\n'
  .. '\tfn = __dcs{kind="function"},\n'
  .. '\tseq = { 1, __dcs{kind="function"}, 3 },\n'
  .. '\tud = __dcs{kind="userdata"}\n'
  .. '}',
  { fn = M.FUNCTION, ud = M.USERDATA, co = M.THREAD, seq = { 1, M.FUNCTION, 3 } })

-- 3. Shared tables: anchor at the first occurrence in output order, refs after.
local shared = { 1, 2 }
local tuple = { x = 1 }
check('shared', { a = shared, b = shared, list = { tuple, tuple, shared } },
  '{\n'
  .. '\ta = __dcs{kind="anchor", id=1, value={ 1, 2 }},\n'
  .. '\tb = __dcs{kind="ref", id=1},\n'
  .. '\tlist = { __dcs{kind="anchor", id=2, value={\n'
  .. '\t\t\tx = 1\n'
  .. '\t\t}}, __dcs{kind="ref", id=2}, __dcs{kind="ref", id=1} }\n'
  .. '}')

-- 4. Cycles: the back-reference is a ref to the enclosing anchor (the root too).
local root = { name = 'root' }
root.self = root
root.kids = { { up = root } }
check('cycle', root,
  '__dcs{kind="anchor", id=1, value={\n'
  .. '\tkids = { {\n'
  .. '\t\t\tup = __dcs{kind="ref", id=1}\n'
  .. '\t\t} },\n'
  .. '\tname = "root",\n'
  .. '\tself = __dcs{kind="ref", id=1}\n'
  .. '}}')

-- 5. Keys: sparse, mixed, float, boolean, negative, empty tables, false, zero.
check('keys', {
  sparse = { [1] = 'a', [3] = 'c', [10] = 'j' },
  -- selene: allow(mixed_table) -- the serializer's mixed-table case
  mixed = { 'x', 'y', [2.5] = 'half', [true] = 'yes', [false] = 'no', [-1] = 'neg', mode = 'z' },
  [0] = 'zero key', [0.1] = 'tenth', ['not ident'] = 1, ['end'] = 2,
  empty = {}, nested_empty = { {} }, f = false, z = 0,
},
  '{\n'
  .. '\t[0] = "zero key",\n'
  .. '\t[0.1] = "tenth",\n'
  .. '\tempty = {},\n'
  .. '\t["end"] = 2,\n'
  .. '\tf = false,\n'
  .. '\tmixed = { "x", "y",\n'
  .. '\t\t[-1] = "neg",\n'
  .. '\t\t[2.5] = "half",\n'
  .. '\t\t[false] = "no",\n'
  .. '\t\t[true] = "yes",\n'
  .. '\t\tmode = "z"\n'
  .. '\t},\n'
  .. '\tnested_empty = { {} },\n'
  .. '\t["not ident"] = 1,\n'
  .. '\tsparse = { "a",\n'
  .. '\t\t[3] = "c",\n'
  .. '\t\t[10] = "j"\n'
  .. '\t},\n'
  .. '\tz = 0\n'
  .. '}')

-- 6. Infinite keys are markers; table and function keys are reported, not written.
local drops = {}
local text = serialize({ [math.huge] = 'inf key', [{}] = 'table key', [print] = 'fn key', ok = 1 },
  { lossless = true, indent = '\t', onDrop = function(path, kind) drops[#drops + 1] = table.concat(path, '/') .. ':' .. kind end })
assert(text == '{\n\t[__dcs{kind="number", value="inf"}] = "inf key",\n\tok = 1\n}', text)
table.sort(drops)
assert(table.concat(drops, ' ') == '<function key>:function <table key>:table', table.concat(drops, ' '))
local back = M.load(text)
assert(back[math.huge] == 'inf key' and back.ok == 1, 'inf key round trip')

-- 7. Markers from `process` (dump-globals' redaction) are written as given.
local REDACTED = serialize.marker({ kind = 'redacted', reason = 'patch-volatile', lua_type = 'number' })
check('redacted', { ws_type = { 4, 4, 7, REDACTED }, Name = REDACTED },
  '{\n'
  .. '\tName = __dcs{kind="redacted", reason="patch-volatile", lua_type="number"},\n'
  .. '\tws_type = { 4, 4, 7, __dcs{kind="redacted", reason="patch-volatile", lua_type="number"} }\n'
  .. '}',
  { ws_type = { 4, 4, 7, M.REDACTED }, Name = M.REDACTED })
-- The same through `process`, as dump-globals.lua redacts.
local function redact(item, path)
  local key = path[#path]
  if key == 'Name' or (path[#path - 1] == 'ws_type' and key == 4) then return REDACTED end
  return item
end
local rtext = serialize({ ws_type = { 4, 4, 7, 2001 }, Name = 2001 },
  { lossless = true, indent = '\t', process = redact })
assert(rtext == '{\n'
  .. '\tName = __dcs{kind="redacted", reason="patch-volatile", lua_type="number"},\n'
  .. '\tws_type = { 4, 4, 7, __dcs{kind="redacted", reason="patch-volatile", lua_type="number"} }\n'
  .. '}', rtext)

-- 8. Proxies are flattened; onProxy reports the chain.
local template = { distanceMax = 40000, PL = { { ammo_capacity = 4 } } }
local proxy = setmetatable({ reactionTime = 2 }, { __index = template })
local seen = {}
local ptext = serialize({ LN = proxy }, { lossless = true, indent = '\t',
  onProxy = function(path, t, chain) seen[#seen + 1] = { table.concat(path, '/'), t, chain[1] } end })
assert(ptext == '{\n'
  .. '\tLN = {\n'
  .. '\t\tPL = { {\n'
  .. '\t\t\t\tammo_capacity = 4\n'
  .. '\t\t\t} },\n'
  .. '\t\tdistanceMax = 40000,\n'
  .. '\t\treactionTime = 2\n'
  .. '\t}\n'
  .. '}', ptext)
assert(#seen == 1 and seen[1][1] == 'LN' and seen[1][2] == proxy and seen[1][3] == template, 'onProxy')

-- 9. Limits: truncated markers instead of errors.
local deep = { 'leaf' }
for _ = 1, 10 do deep = { deep } end
local truncs = {}
local dtext = serialize(deep, { lossless = true, maxDepth = 3,
  onTruncate = function(path, reason) truncs[#truncs + 1] = reason .. '@' .. #path end })
assert(dtext == '{ { { __dcs{kind="truncated", reason="depth", lua_type="table"} } } }', dtext)
assert(truncs[1] == 'depth@3' and #truncs == 1, table.concat(truncs, ' '))
local wide = {}
for i = 1, 5 do wide[i] = { i } end
local wtext = serialize(wide, { lossless = true, maxTables = 3 })
assert(wtext == '{ { 1 }, { 2 }, __dcs{kind="truncated", reason="size", lua_type="table"},'
  .. ' __dcs{kind="truncated", reason="size", lua_type="table"},'
  .. ' __dcs{kind="truncated", reason="size", lua_type="table"} }', wtext)
-- A shared DAG that format 3 expanded past the cap is linear here.
local dag = { 'leaf' }
for _ = 1, 40 do dag = { dag, dag } end
local dagText = serialize(dag, { lossless = true, maxTables = 100 })
assert(not dagText:find('truncated', 1, true) and #dagText < 4000, 'DAG not shared')

-- 10. Decimal-comma locale: string.format writes ',' (DCS under some C locales).
local realFormat = string.format
-- selene: allow(incorrect_standard_library_use) -- stands in for a locale-broken %g
string.format = function(f, ...)
  local s = realFormat(f, ...)
  if f:find('g$') or f == '%.0f' then s = s:gsub('%.', ',') end
  return s
end
local localeSerialize = dofile(hookDir .. '/serialize.lua')
local ltext = localeSerialize({ 0.3490658503988659, 0.5, 12, 1e-300 }, OPTS)
-- selene: allow(incorrect_standard_library_use) -- restores the real one
string.format = realFormat
assert(ltext == '{ 0.3490658503988659, 0.5, 12, 1e-300 }', 'locale: ' .. ltext)

print('SERIALIZE LOSSLESS TESTS PASSED (' .. _VERSION .. ')')
