-- U, the Mission Editor's unit-conversion tables: read from _G.U, else from the
-- me_utilities module a dedicated server's GUI script loaded, and written under
-- _G/U. With `absent`, neither exists and the dump fails without a version
-- marker.
-- Usage: lua5.1 test_me_units.lua <tests/lua dir> <writedir/ with the hook in Scripts/Hooks> [absent|empty|global]
local here = assert(arg[1], 'usage: test_me_units.lua <tests-lua-dir> <writedir/> [mode]')
WRITEDIR = assert(arg[2], 'usage: test_me_units.lua <tests-lua-dir> <writedir/> [mode]')
local mode = arg[3]
dofile(here .. '/stub_env.lua')

__DCS_VERSION__ = '9.9.9.5'
_G.Pylons = { P = { name = 'p1' } }
local units = {
  timeUnits = { imperial = { name = 's', coeff = 1 }, metric = { name = 's', coeff = 1 } },
  speedUnitsAlt = { imperial = { name = 'fps', coeff = 3.28 }, metric = { name = 'm/s', coeff = 1 } },
  months = { { name = 'January', days = 31 }, { name = 'February', days = 28 } },
  addBoxItem = function() end,
  panel_w = 390,
}
units._M = units
if mode == 'absent' then
  _G.me_utilities = nil
elseif mode == 'empty' then
  _G.me_utilities = { panel_w = 390, fonts = {} }
elseif mode == 'global' then
  _G.U = units
  _G.me_utilities = { speedUnits = { imperial = { name = 'stale' } } }
else
  _G.me_utilities = units
end
dofile(WRITEDIR .. 'Scripts/Hooks/dump-globals.lua')

local G = WRITEDIR .. 'DCS.Lua.Exporter/_G/'
local function exists(p) local f = io.open(G .. p); if f then f:close() end; return f ~= nil end

if mode == 'absent' or mode == 'empty' then
  assert(exists('Pylons/p1.lua'), 'other records not written')
  assert(not exists('__DCS_VERSION__.lua'), 'version marker written without U')
  print('ME UNITS FAILURE TEST PASSED')
  return
end

local function load(p)
  local f = assert(io.open(G .. p), 'missing ' .. p)
  local text = f:read('*a')
  f:close()
  local env = { _G = { U = { timeUnits = {}, speedUnitsAlt = {}, months = {} } } }
  local chunk = assert(loadstring(text))
  setfenv(chunk, env)
  chunk()
  return env._G.U, text
end

local u, text = load('U/speedUnitsAlt/ms.lua')
assert(text:find('^_G%["U"%]%["speedUnitsAlt"%]%["metric"%] = '), 'record path: ' .. text)
assert(u.speedUnitsAlt.metric.name == 'm/s' and u.speedUnitsAlt.metric.coeff == 1, 'm/s record')
assert(load('U/speedUnitsAlt/fps.lua').speedUnitsAlt.imperial.coeff == 3.28, 'fps record')
u, text = load('U/months/February.lua')
-- Format 4 keeps the numeric record key (format 3 wrote "#Index").
assert(text:find('^_G%["U"%]%["months"%]%[2%] = '), 'month key: ' .. text)
assert(u.months[2].days == 28, 'month record')
-- Both time units are named "s": the second by key gets a suffix.
assert(load('U/timeUnits/s.lua').timeUnits.imperial.name == 's', 'first s')
assert(load('U/timeUnits/s~2.lua').timeUnits.metric.name == 's', 'second s')
assert(not exists('U/speedUnits'), 'read me_utilities although U is set')
assert(not exists('me_utilities'), 'module written under its own name')
assert(exists('__DCS_VERSION__.lua'), 'version marker not written')
print('ME UNITS TEST PASSED')
