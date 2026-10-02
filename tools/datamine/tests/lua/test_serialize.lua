package.path = assert(arg[1], 'usage: test_serialize.lua <hook-dir>') .. '/?.lua;' .. package.path
local serialize = require 'serialize'

local shared = { x = 1, y = { 'deep' } }
local cyc = { name = 'cyc' }
cyc.self = cyc
local tkey = { 'k' }
local input = {
  nested = { a = { b = { c = 'd' } } },
  arr = { 1, 2, 3, 'four', { 5 } },
  -- selene: allow(mixed_table) -- the serializer's mixed-table case
  mixed = { 10, 20, extra = true },
  str = 'q"uote\'s \\ back\nnl\ttab\0nul\0019\127del',
  onlydq = 'say "hi"',
  ['not ident'] = 1, ['end'] = 2, [1.5] = 'float key', [true] = 'bool key', [false] = 'f',
  [tkey] = 'table key',
  [print] = 'function key',
  fn = print,
  s1 = shared, s2 = shared,
  cyc = cyc,
  negzero = -0.0, intfloat = 3.0, big = 1e300, tiny = 1e-300, frac = 0.1,
  inf = math.huge, ninf = -math.huge, nan = 0/0,
  [math.huge] = 'inf key',
  empty = {},
}

local text = serialize(input, { indent = '\t', newline = '\n' })
print(text)
local chunk = assert(loadstring('return ' .. text))
local out = chunk()

local function eq(a, b, path)
  if type(a) ~= type(b) then error(path .. ': type ' .. type(a) .. ' vs ' .. type(b)) end
  if type(a) == 'table' then
    for k, v in pairs(a) do eq(v, b[k], path .. '.' .. tostring(k)) end
    for k in pairs(b) do if a[k] == nil then error(path .. ': extra key ' .. tostring(k)) end end
  elseif a ~= b then error(path .. ': ' .. tostring(a) .. ' vs ' .. tostring(b)) end
end

-- expected: dropped entries removed, shared table in full twice, cycle -> absent
local expect = {
  nested = input.nested, arr = input.arr, mixed = input.mixed, str = input.str, onlydq = input.onlydq,
  ['not ident'] = 1, ['end'] = 2, [1.5] = 'float key', [true] = 'bool key', [false] = 'f',
  s1 = { x = 1, y = { 'deep' } },
  s2 = { x = 1, y = { 'deep' } },
  cyc = { name = 'cyc' },
  negzero = 0, intfloat = 3, big = 1e300, tiny = 1e-300, frac = 0.1,
  inf = math.huge, ninf = -math.huge,
  [math.huge] = 'inf key',
  empty = {},
}
eq(expect, out, 'root')
assert(1 / out.negzero > 0, '-0 normalised')
-- determinism
assert(serialize(input, { indent = '\t', newline = '\n' }) == text, 'deterministic')
-- file round trip via loadfile
local tmp = os.tmpname()
local f = io.open(tmp, 'w'); f:write('_G["t"] = ' .. text); f:close()
_G.t = nil
assert(loadfile(tmp))()
eq(expect, _G.t, 'file')
os.remove(tmp)

-- process callback + path stack
local seenPaths = {}
local p = serialize({ a = { b = 1 }, c = { 2 } }, { process = function(item, path)
  seenPaths[#seenPaths + 1] = table.concat(path, '.')
  if path[#path] == 'b' then return 'swapped' end
  return item
end })
table.sort(seenPaths)
print(p)
print('process paths: ' .. table.concat(seenPaths, ' | '))
assert(assert(loadstring('return ' .. p))().a.b == 'swapped')

-- shared tables, replaced by `process` or not, are rendered at every occurrence
local tuple, plain = { 1, 2 }, { 3 }
local r = assert(loadstring('return ' .. serialize({ a = tuple, b = tuple, c = plain, d = plain },
  { process = function(item)
    if item == tuple then return { item[1], 'x' } end
    return item
  end })))()
assert(r.a[2] == 'x' and r.b[2] == 'x', 'replaced table rendered at each occurrence')
assert(r.c[1] == 3 and r.d[1] == 3, 'unreplaced shared table rendered at each occurrence')

-- array elements written as nil: the sequence stops before them, the rest keyed
local loop = { 'a' }
loop[2] = loop
local holes = {
  fns = { 1, print, 3 },
  nans = { 0/0, 2 },
  tail = { 'x', print },
  loop = loop,
}
local htext = serialize(holes, { indent = '\t', newline = '\n' })
print(htext)
assert(not htext:find('[{,] nil'), 'positional nil written')
assert(htext:find('fns = { 1,\n\t\t[2] = nil,\n\t\t[3] = 3\n\t}', 1, true), 'fns layout')
assert(htext:find('nans = {\n\t\t[1] = nil,\n\t\t[2] = 2\n\t}', 1, true), 'nans layout')
assert(htext:find('tail = { "x",\n\t\t[2] = nil\n\t}', 1, true), 'tail layout')
local h = assert(loadstring('return ' .. htext))()
eq({ fns = { 1, nil, 3 }, nans = { [2] = 2 }, tail = { 'x' }, loop = { 'a' } }, h, 'holes')
assert(serialize(holes, { indent = '\t', newline = '\n' }) == htext, 'holes deterministic')
-- with `process`, a cycle in the sequence is dropped from the copy
local ptext = serialize({ loop = loop, fns = { 1, print, 3 } },
  { process = function(item) return item end, onCycle = function() end })
assert(not ptext:find('[{,] nil'), 'positional nil written with process')
local pv = assert(loadstring('return ' .. ptext))()
assert(pv.loop[1] == 'a' and pv.loop[2] == nil and pv.fns[3] == 3, 'process holes')
print('SERIALIZE TESTS PASSED (' .. _VERSION .. ')')
