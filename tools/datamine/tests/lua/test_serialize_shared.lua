-- serialize.lua writes a table shared by siblings in full at every occurrence
-- and drops only back-references to an enclosing table (true cycles).
-- Usage: lua5.1 test_serialize_shared.lua <hook-dir>
package.path = assert(arg[1], 'usage: test_serialize_shared.lua <hook-dir>') .. '/?.lua;' .. package.path
local serialize = require 'serialize'

local OPTS = { indent = '\t', newline = '\n' }
local function identity(item) return item end
local PROC = { indent = '\t', newline = '\n', process = identity }
local function load(text) return assert(loadstring('return ' .. text))() end

-- 1. F-16C_50 style pylon: the same launcher entry table in several pylons
-- and several times in one pylon's Launchers.
local aim9 = { CLSID = '{AIM-9M}', Weight = 85 }
local mk82 = { CLSID = '{MK-82}', arg_value = 0.1 }
local pylons = {
  { Number = 1, Launchers = { aim9, mk82 } },
  { Number = 9, Launchers = { aim9, mk82, aim9 } },
}
for _, opts in ipairs({ OPTS, PROC }) do
  local text = serialize({ Pylons = pylons }, opts)
  assert(not text:find('nil', 1, true), 'shared table written as nil:\n' .. text)
  local out = load(text).Pylons
  assert(#out[1].Launchers == 2 and #out[2].Launchers == 3, 'launcher counts')
  for _, pylon in ipairs(out) do
    for i, entry in ipairs(pylon.Launchers) do
      local src = pylons[pylon.Number == 1 and 1 or 2].Launchers[i]
      assert(entry.CLSID == src.CLSID, 'launcher ' .. i .. ' of pylon ' .. pylon.Number)
    end
  end
  assert(out[2].Launchers[3].Weight == 85, 'repeat within one array in full')
end

-- 2. An array whose elements are all the same table has no holes.
local task = { WorldID = 32, Name = 'Transport' }
local tasks = load(serialize({ Tasks = { task, task, task } }, PROC)).Tasks
assert(#tasks == 3, 'Tasks has holes')
for i = 1, 3 do assert(tasks[i].WorldID == 32, 'Tasks[' .. i .. ']') end

-- 3. Shared nested sub-tables (depends_on_unit style) survive at every level.
local dep = { { 'Arleigh Burke' } }
local ws = { { LN = { { depends_on_unit = dep } } }, { LN = { { depends_on_unit = dep } } } }
local w = load(serialize(ws, PROC))
assert(w[1].LN[1].depends_on_unit[1][1] == 'Arleigh Burke', 'first depends_on_unit')
assert(w[2].LN[1].depends_on_unit[1][1] == 'Arleigh Burke', 'second depends_on_unit')

-- 4. A true cycle is broken (written as nil) and reported with its path;
-- the shared sibling next to it is still written in full.
local leaf = { v = 1 }
local node = { a = leaf, b = leaf }
node.back = node
node.kids = { { up = node } }
local cycles = {}
local cyc = load(serialize({ node = node }, { process = identity, onCycle = function(path)
  cycles[#cycles + 1] = table.concat(path, '/')
end }))
assert(cyc.node.back == nil and cyc.node.kids[1].up == nil, 'cycle not broken')
assert(cyc.node.a.v == 1 and cyc.node.b.v == 1, 'shared sibling beside a cycle')
table.sort(cycles)
assert(table.concat(cycles, ' ') == 'node/back node/kids/1/up', 'cycles: ' .. table.concat(cycles, ' '))
local plain = load(serialize({ node = node }, OPTS))
assert(plain.node.back == nil and plain.node.kids[1].up == nil and plain.node.b.v == 1, 'plain cycle')

-- 5. Output stays deterministic.
assert(serialize({ Pylons = pylons }, PROC) == serialize({ Pylons = pylons }, PROC), 'deterministic')

-- 6. A shared DAG past the table cap raises instead of truncating.
local dag = { 'leaf' }
for _ = 1, 20 do dag = { dag, dag } end
local ok, err = pcall(serialize, dag, { process = identity, maxTables = 1000 })
assert(not ok and tostring(err):find('more than 1000 tables', 1, true), 'cap in process mode: ' .. tostring(err))
ok, err = pcall(serialize, dag, { maxTables = 1000 })
assert(not ok and tostring(err):find('more than 1000 tables', 1, true), 'cap in plain mode: ' .. tostring(err))
local small = { 'leaf' }
for _ = 1, 5 do small = { small, small } end
assert(#load(serialize(small, { maxTables = 63 })) == 2, '63 tables fit in a cap of 63')

print('SERIALIZE SHARED TESTS PASSED (' .. _VERSION .. ')')
