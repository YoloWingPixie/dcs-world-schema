-- A record file writes tables DCS shares between siblings in full at every
-- place, keeps shared top-level records as path references, and drops only
-- true cycles (logged).
-- Usage: lua5.1 test_shared_record.lua <tests/lua dir> <writedir/ with the hook in Scripts/Hooks>
local here = assert(arg[1], 'usage: test_shared_record.lua <tests-lua-dir> <writedir/>')
WRITEDIR = assert(arg[2], 'usage: test_shared_record.lua <tests-lua-dir> <writedir/>')
dofile(here .. '/stub_env.lua')

__DCS_VERSION__ = '9.9.9.1'
local pylon = { name = 'LAU-129', Shape = 'lau-129' }
_G.Pylons = { ['LAU-129'] = pylon }
_G.launcher = {
  ['{X}'] = { CLSID = '{X}', Elements = { pylon, pylon } },
}
local aim9 = { CLSID = '{AIM-9M}' }
local mk82 = { CLSID = '{MK-82}' }
local transport = { WorldID = 35, Name = 'Transport' }
local unit = {
  type = 'F-16C_50',
  Pylons = {
    { Number = 1, Launchers = { aim9, mk82 } },
    { Number = 9, Launchers = { aim9, mk82 } },
  },
  Tasks = { transport, transport },
  DefaultTask = transport,
}
unit.self = unit
_G.db = { Units = { Planes = { Plane = { unit } } } }
dofile(WRITEDIR .. 'Scripts/Hooks/dump-globals.lua')

local G = WRITEDIR .. 'DCS.Lua.Exporter/_G/'
local function read(p)
  local f = assert(io.open(G .. p))
  local text = f:read('*a')
  f:close()
  return text
end

local text = read('db/Units/Planes/Plane/F-16C_50.lua')
assert(not text:find('= nil', 1, true) and not text:find(' nil,', 1, true), 'nil in record:\n' .. text)
_G.db = { Units = { Planes = { Plane = {} } } }
assert(loadstring(text))()
local u = _G.db.Units.Planes.Plane['#Index']
assert(#u.Pylons[1].Launchers == 2 and #u.Pylons[2].Launchers == 2, 'launcher counts')
assert(u.Pylons[2].Launchers[1].CLSID == '{AIM-9M}' and u.Pylons[2].Launchers[2].CLSID == '{MK-82}',
  'mirrored pylon launchers written in full')
assert(#u.Tasks == 2 and u.Tasks[2].WorldID == 35 and u.DefaultTask.WorldID == 35, 'shared Tasks')
assert(u.self == nil, 'cycle not dropped')

local lt = read('launcher/{X}.lua')
local refs = {}
for ref in lt:gmatch('"(_G/Pylons/[^"]+)"') do refs[#refs + 1] = ref end
assert(#refs == 2 and refs[1] == '_G/Pylons/LAU-129.lua' and refs[2] == refs[1],
  'cross-file refs: ' .. table.concat(refs, ' '))
assert(io.open(G .. '__DCS_VERSION__.lua'), 'version marker not written')
print('SHARED RECORD TEST PASSED')
