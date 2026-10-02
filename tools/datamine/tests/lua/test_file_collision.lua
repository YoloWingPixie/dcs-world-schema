-- Records whose files differ only by case or by stripped characters must not
-- overwrite each other on Windows: all but the first get a ~N suffix, and
-- references name the file each record was written to.
-- Usage: lua5.1 test_file_collision.lua <tests/lua dir> <writedir/ with the hook in Scripts/Hooks>
local here = assert(arg[1], 'usage: test_file_collision.lua <tests-lua-dir> <writedir/>')
WRITEDIR = assert(arg[2], 'usage: test_file_collision.lua <tests-lua-dir> <writedir/>')
dofile(here .. '/stub_env.lua')

__DCS_VERSION__ = '9.9.9.1'
local upper = { name = 'B-20', Shape = 'upper' }
local lower = { name = 'b-20', Shape = 'lower' }
_G.Pylons = {
  ['B-20'] = upper,
  ['b-20'] = lower,
  ['b-20~2'] = { name = 'b-20~2', Shape = 'taken' },
  ['a:b'] = { name = 'a:b', Shape = 'colon' },
  ab = { name = 'ab', Shape = 'plain' },
}
_G.launcher = {
  ['{X}'] = { CLSID = '{X}', Elements = { lower } },
  ['{Y}'] = { CLSID = '{Y}', Elements = { lower, upper } },
}
dofile(WRITEDIR .. 'Scripts/Hooks/dump-globals.lua')

local G = WRITEDIR .. 'DCS.Lua.Exporter/_G/'
local function read(p)
  local f = io.open(G .. p)
  if not f then return nil end
  local text = f:read('*a')
  f:close()
  return text
end
local function shape(p)
  local text = assert(read(p), p .. ' missing')
  return text:match('Shape = "([^"]+)"')
end

assert(shape('Pylons/B-20.lua') == 'upper', 'B-20 keeps its name')
assert(shape('Pylons/b-20~3.lua') == 'lower', 'b-20 skips the taken ~2')
assert(shape('Pylons/b-20~2.lua') == 'taken', 'a real b-20~2 keeps its name')
assert(shape('Pylons/ab.lua') == 'colon', 'a:b sorts first')
assert(shape('Pylons/ab~2.lua') == 'plain', 'ab gets the suffix')
assert(read('Pylons/b-20.lua') == nil, 'no lower-case b-20.lua')
local refs = {}
for ref in read('launcher/{Y}.lua'):gmatch('"(_G/Pylons/[^"]+)"') do refs[#refs + 1] = ref end
assert(refs[1] == '_G/Pylons/b-20~3.lua' and refs[2] == '_G/Pylons/B-20.lua',
  'refs: ' .. table.concat(refs, ', '))
assert(read('__DCS_VERSION__.lua'), 'version marker not written')
print('FILE COLLISION TEST PASSED')
