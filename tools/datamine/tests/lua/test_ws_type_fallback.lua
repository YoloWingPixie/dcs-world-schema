-- Slot-4 fallback: when the exact 4-tuple is unmapped, (l1, l2, l4) is matched
-- (level 3 ignored) and used only when exactly one projectile name carries it.
-- Shape from DCS: the 2S6 Tunguska's type_ammunition is {4,4,11,n} while the
-- 9M311's own ws_type is {4,4,34,n}.
-- Usage: lua5.1 test_ws_type_fallback.lua <tests/lua dir> <writedir/ with the hook in Scripts/Hooks>
local here = assert(arg[1], 'usage: test_ws_type_fallback.lua <tests-lua-dir> <writedir/>')
WRITEDIR = assert(arg[2], 'usage: test_ws_type_fallback.lua <tests-lua-dir> <writedir/>')
dofile(here .. '/stub_env.lua')

__DCS_VERSION__ = '9.9.9.5'

_G.rockets = {
  EXACT = { name = 'EXACT', ws_type = { 4, 4, 34, 70 } },
  M311 = { name = '9M311', ws_type = { 4, 4, 34, 80 } },
  AMB_A = { name = 'AMB-A', ws_type = { 4, 4, 34, 90 } },
  DUP = { name = 'DUP', ws_type = { 4, 4, 34, 95 } },
  -- The only level-4 id 0 projectile (DCS: M485_FLARE {4,5,49,0}).
  FLARE = { name = 'FLARE', ws_type = { 4, 5, 49, 0 } },
}
_G.weapons_table = { weapons = { missiles = {
  -- Shares (l1,l2,l4) with EXACT under another name: exact must still win.
  OTHER = { name = 'OTHER', ws_type = { 4, 4, 35, 70 } },
  -- Same (l1,l2,l4) as AMB_A, other name: fallback refused.
  AMB_B = { name = 'AMB-B', ws_type = { 4, 4, 35, 90 } },
  -- Same (l1,l2,l4) and same name as rockets.DUP: still one name.
  DUP2 = { name = 'DUP', ws_type = { 4, 4, 36, 95 } },
} } }

local function ln(t)
  return { WS = { { LN = { { PL = { { type_ammunition = t } } } } } } }
end
local units = {}
for _, spec in ipairs({
  { 'EXACT_LN', { 4, 4, 34, 70 } },
  { '2S6 Tunguska', { 4, 4, 11, 80 } },
  { 'AMB_LN', { 4, 4, 11, 90 } },
  { 'DUP_LN', { 4, 4, 11, 95 } },
  { 'UNK_LN', { 4, 4, 11, 999 } },
  -- Cluster launcher.cluster.ws_type {4,5,38,0}: placeholder id, no fallback.
  { 'CLUSTER_LN', { 4, 5, 38, 0 } },
  { 'FLARE_LN', { 4, 5, 49, 0 } },
}) do
  local u = ln(spec[2])
  u.type = spec[1]
  units[#units + 1] = u
end
_G.db = { Units = { Cars = { Car = units } } }
dofile(WRITEDIR .. 'Scripts/Hooks/dump-globals.lua')

local G = WRITEDIR .. 'DCS.Lua.Exporter/_G/'
local function ammo(file)
  local f = assert(io.open(G .. 'db/Units/Cars/Car/' .. file .. '.lua'), file)
  local text = f:read('*a')
  f:close()
  local rec = assert(loadstring('return ' .. text:match('^[^\n]- = (.*)$')))()
  return rec.WS[1].LN[1].PL[1].type_ammunition
end
local function same(t, expect, what)
  assert(type(t) == 'table', what .. ': not a table')
  for i, v in ipairs(expect) do
    assert(t[i] == v, what .. ' slot ' .. i .. ': ' .. tostring(t[i]) .. ' ~= ' .. tostring(v))
  end
end

same(ammo('EXACT_LN'), { 4, 4, 34, 'EXACT' }, 'exact wins over ambiguous fallback')
same(ammo('2S6 Tunguska'), { 4, 4, 11, '9M311' }, 'Tunguska fallback')
same(ammo('AMB_LN'), { 4, 4, 11, 'Redacted' }, 'ambiguous (l1,l2,l4) refused')
same(ammo('DUP_LN'), { 4, 4, 11, 'DUP' }, 'one name under several level-3 ids')
same(ammo('UNK_LN'), { 4, 4, 11, 'Redacted' }, 'unmapped')
same(ammo('CLUSTER_LN'), { 4, 5, 38, 'Redacted' }, 'level-4 id 0 has no fallback')
same(ammo('FLARE_LN'), { 4, 5, 49, 'FLARE' }, 'level-4 id 0 still matches exactly')
same(_G.rockets.M311.ws_type, { 4, 4, 34, 80 }, 'live _G untouched')
print('WS_TYPE FALLBACK TEST PASSED')
