-- serialize.lua renders proxy tables (metatable __index is a table) with their
-- effective fields: raw keys, then inherited keys absent raw, down the chain.
-- Usage: lua5.1 test_serialize_proxy.lua <hook-dir>
package.path = assert(arg[1], 'usage: test_serialize_proxy.lua <hook-dir>') .. '/?.lua;' .. package.path
local serialize = require 'serialize'

local OPTS = { indent = '\t', newline = '\n' }
local function ser(v, opts) return serialize(v, opts or OPTS) end
local function load(text) return assert(loadstring('return ' .. text))() end

-- Like DCS set_recursive_metatable: nested tables become raw proxies, scalars
-- stay behind __index.
local function proxy(src)
  local t = {}
  for k, v in pairs(src) do
    if type(v) == 'table' then t[k] = proxy(v) end
  end
  return setmetatable(t, { __index = src })
end

-- 1. Nested __index chain: base <- mid <- unit; raw and nearer keys win.
-- selene: allow(mixed_table) -- array part inherited through __index
local base = { distanceMax = 12000, distanceMin = 1500, reactionTime = 6, { 'seq-from-base' } }
local mid = setmetatable({ distanceMin = 1000, PL = { { ammo_capacity = 8 } } }, { __index = base })
local unit = setmetatable({ reactionTime = 3 }, { __index = mid })
local out = load(ser({ LN = { unit } }))
local ln = out.LN[1]
assert(ln.distanceMax == 12000, 'inherited from depth 2')
assert(ln.distanceMin == 1000, 'nearer __index wins')
assert(ln.reactionTime == 3, 'raw key wins')
assert(ln.PL[1].ammo_capacity == 8, 'inherited nested table rendered')
assert(ln[1][1] == 'seq-from-base', 'inherited sequence entry')

-- The set_recursive_metatable shape: scalars at every level come back.
local tmpl = { distanceMax = 12000, PL = { { ammo_capacity = 8, type_ammunition = { 4, 4, 34, 51 } } } }
local p = load(ser(proxy(tmpl)))
assert(p.distanceMax == 12000 and p.PL[1].ammo_capacity == 8, 'recursive proxy scalars')
assert(p.PL[1].type_ammunition[1] == 4 and p.PL[1].type_ammunition[4] == 51, 'proxy tuple slots')
-- Same through the `process` path the dump hook uses.
local pp = load(ser(proxy(tmpl), { indent = '\t', newline = '\n', process = function(item) return item end }))
assert(pp.distanceMax == 12000 and pp.PL[1].type_ammunition[3] == 34, 'process path flattens')
-- Output equals that of the equivalent plain table, byte for byte.
assert(ser(proxy(tmpl)) == ser(tmpl), 'proxy renders as its template')

-- 2. A function __index is never called, and contributes nothing.
local calls = 0
local fnProxy = setmetatable({ a = 1 }, { __index = function() calls = calls + 1; return 99 end })
assert(ser(fnProxy) == ser({ a = 1 }), 'function __index ignored')
-- A table chain ending in a function __index keeps the table part only.
local tail = setmetatable({ b = 2 }, { __index = function() calls = calls + 1 end })
assert(ser(setmetatable({ a = 1 }, { __index = tail })) == ser({ a = 1, b = 2 }), 'chain stops at function')
assert(calls == 0, 'function __index called')
-- A protected metatable (__metatable) is not followed.
assert(ser(setmetatable({ a = 1 }, { __index = { b = 2 }, __metatable = 'locked' })) == ser({ a = 1 }),
  '__metatable-protected proxy')
-- __index = _G is not followed.
assert(ser(setmetatable({ a = 1 }, { __index = _G })) == ser({ a = 1 }), '_G not inherited')

-- 3. Cycles terminate: self-index, a two-table loop, and a very long chain.
local selfIdx = { a = 1 }
setmetatable(selfIdx, { __index = selfIdx })
assert(ser(selfIdx) == ser({ a = 1 }), 'self __index')
local x, y = { x = 1 }, { y = 2 }
setmetatable(x, { __index = y }); setmetatable(y, { __index = x })
assert(ser(x) == ser({ x = 1, y = 2 }), 'two-table __index loop')
local chain = { k0 = 0 }
for i = 1, 40 do chain = setmetatable({ ['k' .. i] = i }, { __index = chain }) end
local long = load(ser(chain))
assert(long.k40 == 40 and long.k24 == 24 and long.k23 == nil, 'chain bounded to 16 hops')
-- A proxy whose inherited value is the proxy itself renders it once.
local loopy = setmetatable({}, { __index = {} })
getmetatable(loopy).__index.me = loopy
assert(load(ser({ v = loopy })).v.me == nil, 'inherited back-reference is nil')

-- 4. Deterministic, and live tables are not modified.
assert(ser(unit) == ser(unit), 'deterministic')
assert(rawget(unit, 'distanceMax') == nil and rawget(unit, 'distanceMin') == nil, 'live proxy mutated')
assert(next(proxy({})) == nil, 'sanity')

-- 5. Non-proxy output unchanged (golden text).
local golden = '{ 1, 2,\n\tb = {\n\t\tc = "d"\n\t},\n\tz = true\n}'
-- selene: allow(mixed_table) -- the golden mixed-table output
assert(ser({ 1, 2, z = true, b = { c = 'd' } }) == golden, 'non-proxy output changed')
-- Metatables without a table __index (e.g. __call only) do not change output.
assert(ser(setmetatable({ q = 1 }, { __call = print })) == ser({ q = 1 }), 'non-__index metatable')

print('SERIALIZE PROXY TESTS PASSED (' .. _VERSION .. ')')
