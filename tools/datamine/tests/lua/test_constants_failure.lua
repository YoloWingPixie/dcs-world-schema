-- A failed constants capture fails the dump: records are written but the
-- version marker is not. A marker for the running version does not skip the
-- dump; the previous dump is always cleared.
-- Usage: lua5.1 test_constants_failure.lua <tests/lua dir> <writedir/ with the hook in Scripts/Hooks>
local here = assert(arg[1], 'usage: test_constants_failure.lua <tests-lua-dir> <writedir/>')
WRITEDIR = assert(arg[2], 'usage: test_constants_failure.lua <tests-lua-dir> <writedir/>')
dofile(here .. '/stub_env.lua')

__DCS_VERSION__ = '9.9.9.4'
local G = WRITEDIR .. 'DCS.Lua.Exporter/_G/'
os.execute("mkdir -p '" .. G .. "'")
local function put(rel, text) local f = assert(io.open(G .. rel, 'w')); f:write(text); f:close() end
put('__DCS_VERSION__.lua', __DCS_VERSION__)
put('stale.lua', 'stale')

_G.wsType_Weapon = 4
country = setmetatable({}, { __index = function() error('boom') end })
_G.Pylons = { P = { name = 'p1' } }
dofile(WRITEDIR .. 'Scripts/Hooks/dump-globals.lua')

local function exists(p) local f = io.open(G .. p); if f then f:close() end; return f ~= nil end
assert(exists('Pylons/p1.lua'), 'record not written (skip gate?)')
assert(not exists('stale.lua'), 'previous dump not cleared')
assert(not exists('__DCS_VERSION__.lua'), 'version marker written despite constants failure')
print('CONSTANTS FAILURE TEST PASSED')
