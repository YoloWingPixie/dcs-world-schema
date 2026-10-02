-- probe-call.lua against stand-ins for DCS's C functions: they raise the
-- errors luaL_checktype / luaL_argerror and DCS's own checks raise (no
-- "<source>:<line>: " prefix, as from C). test_api_probe.py runs it.
-- Usage: lua5.1 test_probe_call.lua <hook dir>
local hookDir = assert(arg[1], 'usage: test_probe_call.lua <hook dir>')
local P = dofile(hookDir .. '/probe-call.lua')

local function typeName(v) return v == nil and 'no value' or type(v) end
-- luaL_checktype(L, n, t) as a C function called through pcall ('?' name).
local function check(n, t, v, name)
  if type(v) ~= t then
    error(string.format("bad argument #%d to '%s' (%s expected, got %s)",
      n, name or '?', t, typeName(v)), 0)
  end
end

local Unit = { className_ = 'Unit' }
Unit.__index = Unit
local unit = setmetatable({ id_ = 1 }, Unit)
local samples = { Unit = function() return unit end, Weapon = function() return nil end }

local function eq(a, b, what)
  if a ~= b then error(what .. ': ' .. tostring(a) .. ' ~= ' .. tostring(b), 2) end
end

-- Parsing.
local e = P.parse("bad argument #2 to '?' (number expected, got no value)", 'f')
eq(e.pos, 2, 'pos'); eq(e.expected, 'number', 'expected'); eq(e.from, 'error', 'from')
e = P.parse("[string \"x\"]:3: bad argument #1 to 'f' (table expected, got nil)", 'f')
eq(e.expected, 'table', 'prefixed')
assert(P.parse("bad argument #1 to 'ipairs' (table expected, got nil)", 'f') == nil, 'nested')
e = P.parse("bad argument #1 (string expected, got no value)")
eq(e.expected, 'string', 'no name')
e = P.parse("calling 'getName' on bad self (Unit expected, got table)", 'getName')
eq(e.pos, 1, 'self pos'); eq(e.expected, 'Unit', 'self type')
e = P.parse('Parameter #self missed', 'getName')
eq(e.hint, 'self', 'dcs self')
e = P.parse('Parameter #2 (unit name) missed', 'f')
eq(e.pos, 2, 'dcs pos'); eq(e.hint, 'unit name', 'dcs hint'); eq(e.from, 'missed', 'dcs from')
assert(P.parse("bad argument #1 to 'f' (invalid option 'x')", 'f') == nil, 'value error')
assert(P.parse('Unit does not exist', 'f') == nil, 'plain error')
eq(P.kindFor('Unit', samples), 'Unit', 'class kind')
eq(P.kindFor('integer', samples), 'number', 'integer kind')

-- A C function with two typed arguments, returning a vec3-like table.
local function twoArgs(a, b)
  check(1, 'number', a); check(2, 'string', b)
  return { x = a, y = 0, z = 0 }, b
end
local r = P.probe(twoArgs, { name = 'twoArgs' })
eq(r.status, 'ok', 'twoArgs'); eq(r.minArgs, 2, 'twoArgs minArgs'); eq(r.attempts, 3, 'attempts')
eq(r.params[1].expected, 'number', 'p1'); eq(r.params[2].sample, 'string', 'p2')
eq(#r.returns, 2, 'returns'); eq(table.concat(r.returns[1].keys, ','), 'x,y,z', 'keys')
eq(r.returns[2].type, 'string', 'return 2')

-- No arguments needed; extra arguments rejected (lua_gettop check).
local function strict(...)
  if select('#', ...) > 0 then error("bad argument #1 to '?' (no value expected, got number)", 0) end
  return unit
end
r = P.probe(strict, { name = 'getX', extra = true })
eq(r.status, 'ok', 'strict'); eq(r.minArgs, 0, 'strict minArgs')
eq(r.returns[1].className, 'Unit', 'className'); eq(r.extraArgs, false, 'extra rejected')
r = P.probe(function() return 1 end, { name = 'getY', extra = true })
eq(r.extraArgs, true, 'extra accepted')

-- A DCS method: self missed, then a named parameter with no type.
local function method(self, name)
  if self == nil then error('Parameter #self missed', 0) end
  if getmetatable(self) ~= Unit then error("calling 'm' on bad self (Unit expected, got table)", 0) end
  if name == nil then error('Parameter #1 (unit name) missed', 0) end
  if type(name) ~= 'string' then error('Parameter #1 (unit name) missed', 0) end
  return true
end
r = P.probe(method, { name = 'm', owner = 'Unit', samples = samples })
eq(r.status, 'ok', 'method'); eq(r.minArgs, 2, 'method minArgs')
eq(r.params[1].sample, 'Unit', 'self sample'); eq(r.params[1].from, 'self', 'self from')
eq(r.params[2].sample, 'string', 'hinted string'); eq(r.params[2].dcsIndex, 1, 'dcsIndex')

-- An unknown parameter type is found by trial.
local function wantsBool(v)
  if type(v) ~= 'boolean' then error('Parameter #1 missed', 0) end
end
r = P.probe(wantsBool, { name = 'b' })
eq(r.status, 'ok', 'trial'); eq(r.params[1].sample, 'boolean', 'trial kind')

-- A value error ends the probe with its text.
r = P.probe(function(a) check(1, 'number', a); error('value out of range: 0x1234abcd', 0) end, { name = 'v' })
eq(r.status, 'error', 'value error'); eq(r.error, 'value out of range: 0x?', 'cleaned')
eq(r.params[1].expected, 'number', 'typed before error')

-- A class with no sample; a sample that is gone.
r = P.probe(function(o) check(1, 'Airbase', o) end, { name = 'a', samples = samples })
eq(r.status, 'noSample', 'no sample'); eq(r.sample, 'Airbase', 'no sample kind')
r = P.probe(function(o) check(1, 'Weapon', o) end, { name = 'w', samples = samples })
eq(r.status, 'noSample', 'gone sample'); eq(r.sample, 'Weapon', 'gone kind')

-- The same error after the right type: stuck.
r = P.probe(function(_) check(1, 'string', nil) end, { name = 's' })
eq(r.status, 'stuck', 'stuck')

-- Never satisfiable positions beyond MAX_ARGS: an error, not a loop.
r = P.probe(function() error("bad argument #9 to '?' (number expected, got no value)", 0) end, { name = 'n' })
eq(r.status, 'error', 'past max args')

-- Instruction limit.
P.INSTRUCTION_LIMIT = 200000
-- selene: allow(empty_loop) -- spins until the instruction limit
r = P.probe(function() while true do end end, { name = 'loop' })
eq(r.status, 'timeout', 'timeout')

-- Writes are blocked, and the originals are back afterwards.
local G = { os = { remove = os.remove }, io = { open = io.open }, lfs = { mkdir = function() end } }
local realOpen, realMkdir = G.io.open, G.lfs.mkdir
r = P.probe(function() G.os.remove('x') end, { name = 'rm', G = G })
eq(r.status, 'blocked', 'blocked'); eq(r.blocked, 'os.remove', 'blocked name')
r = P.probe(function() return G.io.open('/nonexistent/probe', 'w') end, { name = 'w', G = G })
eq(r.blocked, 'io.open', 'write open')
r = P.probe(function() return G.io.open('/nonexistent/probe') end, { name = 'r', G = G })
eq(r.status, 'ok', 'read open allowed')
assert(G.io.open == realOpen and G.lfs.mkdir == realMkdir, 'guard restored')

-- Lua functions: parameter names, and usage errors inside the function.
local function luaFn(opts, count)
  local x = opts.field
  return x, count + 1
end
r = P.probe(luaFn, { name = 'luaFn' })
eq(table.concat(r.paramNames, ','), 'opts,count', 'param names')
eq(r.params[1].from, 'usage', 'usage from'); eq(r.params[1].sample, 'table', 'usage table')
eq(r.params[2].expected, 'number', 'usage arithmetic'); eq(r.status, 'ok', 'lua ok')
local function outer(t) return ipairs(t) end
r = P.probe(outer, { name = 'outer' })
eq(r.status, 'error', 'nested error not ours')

-- Context values: a mission object's name before the plain sample, which
-- replaces it when the call fails with an error that names no argument.
local groups = { PROBE_GROUP = true }
local function getByName(name)
  check(1, 'string', name)
  if groups[name] then return unit end
  return nil
end
r = P.probe(getByName, { name = 'getByName', context = { [1] = { string = 'PROBE_GROUP' } } })
eq(r.status, 'ok', 'context'); eq(r.returns[1].className, 'Unit', 'context return')
eq(r.params[1].value, 'PROBE_GROUP', 'context value recorded')
local function strictName(name)
  check(1, 'string', name)
  if name ~= 'probe' then error('unknown name ' .. name, 0) end
  return true
end
r = P.probe(strictName, { name = 'strictName', context = { [1] = { string = 'PROBE_GROUP' } } })
eq(r.status, 'ok', 'context dropped'); eq(r.params[1].value, nil, 'plain value not recorded')
eq(r.attempts, 3, 'context then plain')
local function side(n) check(1, 'number', n); return n end
r = P.probe(side, { name = 'side', context = { [1] = { number = 2 } } })
eq(r.params[1].value, 2, 'number context')
local function missedName(self, name)
  if self == nil then error('Parameter #self missed', 0) end
  if name ~= 'probe' then error('Parameter #1 (name) missed', 0) end
  return true
end
r = P.probe(missedName, { name = 'm', owner = 'Unit', samples = samples,
  context = { [2] = { string = 'PROBE_GROUP' } } })
eq(r.status, 'ok', 'missed context dropped'); eq(r.params[2].sample, 'string', 'missed kind')

-- resolve and aliases.
local shared = function() end
local env = { a = { f = shared, n = 1 }, b = shared }
setmetatable(env.a, { __index = { g = shared } })
eq(P.resolve(env, { 'a', { m = true }, '__index', 'g' }), shared, 'metatable key')
eq(P.aliases(env, { { keys = { 'a', 'f' } }, { keys = { 'b' } }, { keys = { 'a', 'n' } } }),
  '2\t1\n3\t0', 'aliases')

-- JSON.
eq(P.encode({ b = { 1, 'x' }, a = true, c = 'q"\n' }), '{"a":true,"b":[1,"x"],"c":"q\\"\\n"}', 'json')
eq(P.encode({}), '{}', 'empty json')

print('PROBE CALL TEST DONE')
