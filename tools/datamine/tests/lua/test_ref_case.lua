-- A shared table's reference must name the exact file it was written to.
-- DCS keys the pylon "B-20" but its `name` is "b-20"; the file is named by
-- `name`, so the reference must be too (case-sensitive filesystems).
-- Usage: lua5.1 test_ref_case.lua <tests/lua dir> <writedir/ with the hook in Scripts/Hooks>
local here = assert(arg[1], 'usage: test_ref_case.lua <tests-lua-dir> <writedir/>')
WRITEDIR = assert(arg[2], 'usage: test_ref_case.lua <tests-lua-dir> <writedir/>')
dofile(here .. '/stub_env.lua')

__DCS_VERSION__ = '9.9.9.1'
local pylon = { name = 'b-20', Shape = 'b-20' }
_G.Pylons = { ['B-20'] = pylon }
_G.launcher = {
  ['{X}'] = { CLSID = '{X}', Elements = { pylon } },
  ['{Y}'] = { CLSID = '{Y}', Elements = { pylon } },
}
dofile(WRITEDIR .. 'Scripts/Hooks/dump-globals.lua')

local G = WRITEDIR .. 'DCS.Lua.Exporter/_G/'
local function exists(p) local f = io.open(G .. p); if f then f:close() end; return f ~= nil end
local f = assert(io.open(G .. 'launcher/{X}.lua'))
local ref = f:read('*a'):match('"(_G/Pylons/[^"]+)"')
f:close()
assert(ref == '_G/Pylons/b-20.lua', 'ref was ' .. tostring(ref))
assert(exists('Pylons/b-20.lua'), 'pylon file missing')
assert(not exists('Pylons/B-20.lua'), 'unexpected key-named file')
assert(exists('__DCS_VERSION__.lua'), 'version marker not written')
print('REF CASE TEST PASSED')
