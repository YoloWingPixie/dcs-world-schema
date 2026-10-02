-- Slot 4 of ws_type / wsTypeOfWeapon becomes the projectile name when the
-- numeric 4-tuple maps to exactly one projectile, else "Redacted".
-- Usage: lua5.1 test_ws_type.lua <tests/lua dir> <writedir/ with the hook in Scripts/Hooks>
local here = assert(arg[1], 'usage: test_ws_type.lua <tests-lua-dir> <writedir/>')
WRITEDIR = assert(arg[2], 'usage: test_ws_type.lua <tests-lua-dir> <writedir/>')
dofile(here .. '/stub_env.lua')

__DCS_VERSION__ = '9.9.9.3'
_G.rockets = {
  S5 = { name = 'S-5', ws_type = { 4, 4, 7, 123 } },
  -- Two names on one tuple: ambiguous.
  A1 = { name = 'AMB-1', ws_type = { 4, 4, 7, 200 } },
}
_G.weapons_table = { weapons = { nurs = {
  A2 = { name = 'AMB-2', ws_type = { 4, 4, 7, 200 } },
  -- Same name again (alias of the rocket): not ambiguous.
  S5 = { name = 'S-5', ws_type = { 4, 4, 7, 123 } },
} } }
_G.launcher = {
  ['{MAPPED}']    = { CLSID = '{MAPPED}',    wsTypeOfWeapon = { 4, 4, 7, 123 }, attribute = { 4, 4, 32, 9 } },
  ['{AMBIG}']     = { CLSID = '{AMBIG}',     wsTypeOfWeapon = { 4, 4, 7, 200 } },
  ['{UNMAPPED}']  = { CLSID = '{UNMAPPED}',  wsTypeOfWeapon = { 4, 4, 7, 999 } },
  -- Level 3 differs: no exact match, so the unique (l1,l2,l4) fallback applies.
  ['{OTHERCAT}']  = { CLSID = '{OTHERCAT}',  wsTypeOfWeapon = { 4, 4, 8, 123 } },
  ['{SHORT}']     = { CLSID = '{SHORT}',     wsTypeOfWeapon = { 4, 5, 9 } },
}
dofile(WRITEDIR .. 'Scripts/Hooks/dump-globals.lua')

local G = WRITEDIR .. 'DCS.Lua.Exporter/_G/'
local function load(rel)
  local f = assert(io.open(G .. rel), rel)
  local text = f:read('*a')
  f:close()
  return assert(loadstring('return ' .. text:match('^[^\n]- = (.*)$')))()
end
local function slot4(rel, key) return load(rel)[key][4] end

assert(slot4('launcher/{MAPPED}.lua', 'wsTypeOfWeapon') == 'S-5', 'mapped launcher')
assert(slot4('rockets/S-5.lua', 'ws_type') == 'S-5', 'projectile own ws_type')
assert(slot4('launcher/{AMBIG}.lua', 'wsTypeOfWeapon') == 'Redacted', 'ambiguous')
assert(slot4('rockets/AMB-1.lua', 'ws_type') == 'Redacted', 'ambiguous projectile')
assert(slot4('launcher/{UNMAPPED}.lua', 'wsTypeOfWeapon') == 'Redacted', 'unmapped')
assert(slot4('launcher/{OTHERCAT}.lua', 'wsTypeOfWeapon') == 'S-5', 'level-3 fallback')
assert(slot4('launcher/{SHORT}.lua', 'wsTypeOfWeapon') == nil, '3-tuple untouched')
assert(slot4('launcher/{MAPPED}.lua', 'attribute') == 'Redacted', 'attribute still redacted')
assert(_G.rockets.S5.ws_type[4] == 123, 'live _G mutated')
print('WS_TYPE TEST PASSED')
