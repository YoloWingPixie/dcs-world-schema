--[[----------------------------------------------------------------------------
  dump-globals.lua - DCS World `_G` dump hook.

  A DCS GameGUI hook. `task datamine` (tools/datamine/refresh.py) runs DCS
  headless with this file and serialize.lua as hooks in an isolated Saved Games
  profile. On launch it walks `_G` and writes the game's static databases
  (weapons, unit DB, sensors, countries, ...) under <profile>\DCS.Lua.Exporter\_G\,
  one loadable Lua file per record. refresh.py copies that snapshot to
  .datamine/_G, which `tools/datamine/extract.py` reads.

  On-disk format (the extractors depend on it):

  The tree mirrors `_G`: the record at _G.db.Units.Planes.Plane["A-10C"] is
  written to _G/db/Units/Planes/Plane/A-10C.lua. Each file is one assignment,
  tab-indented, LF line endings, no trailing newline:

      _G["db"]["Units"]["Planes"]["Plane"]["#Index"] = {
      	...
      }

  A numeric record key is written as the literal key "#Index". The filename
  comes from the record's marker field (`name`, `CLSID`, ...) when it is a
  non-empty string, else the table key; characters illegal in Windows filenames
  are stripped. File paths are compared case-insensitively, as on Windows:
  when several records of a folder would get the same file (pylons "B-20" and
  "b-20"), the first by exact name, then by key (numbers ascending, then
  strings), keeps it and the others are written as <name>~2.lua, <name>~3.lua,
  ... (the next number whose file is free). Each is logged; references name
  the file actually written.

  A nested table that is itself a top-level record dumped to its own file (a
  bomb's shared warhead, a launcher's pylon) is written as a path string, e.g.
  warhead = "_G/warheads/AN_M65.lua", instead of being inlined. Any other
  table DCS reuses in several places (mirrored pylon Launchers, Tasks entries,
  depends_on_unit) is written in full at each place; only a back-reference to
  an enclosing table (a true cycle) is written as `nil`, and each one is
  logged. A record that would expand past serialize.lua's table cap fails the
  dump instead of being truncated.

  Proxy tables are written with their effective fields. Unit launchers built
  from a GT_t template (DCS `set_recursive_metatable`) hold nested tables as
  raw keys but scalars (distanceMax, ammo_capacity, ...) only behind a
  metatable __index table; serialize.lua merges the __index chain (see its
  header), so a unit's WS/LN/PL entries carry the same fields as the
  GT_t/*_t template files.

  Level-4 wsType ids change between patches, so record files never hold them
  (raw ids: __wstype_ids__.lua below). Slot 4 of every `ws_type`,
  `wsTypeOfWeapon` and `type_ammunition` tuple is the `name` of the projectile
  record (rockets, bombs, torpedoes, weapons_table) whose own ws_type equals
  the full 4-tuple, or "Redacted" when several names carry it. When none
  does, (l1, l2, l4) is matched instead and used only if exactly one name
  carries it: DCS level 3 sometimes disagrees (2S6 launcher {4,4,11,n} vs
  the 9M311's own {4,4,34,n}). Level-4 id 0 is a placeholder and never takes
  part in the fallback. The tuple is always written whole
  ({ l1, l2, l3, <name or "Redacted"> }), also for proxies and tables that
  recur in the record, so a launcher's `type_ammunition` is the fired
  missile's name; a string `type_ammunition` ("weapons.missiles.X") is
  written as is. Slot 4 of `adapter_type`, slot 4 (else 3) of `attribute`,
  `index`, and numeric `Name` values are always "Redacted".

  _G/__wstype_ids__.lua holds the raw numeric ids the record files redact, so
  DCS tables keyed by wsType tuples (RWR symbols, HARM codes) can be joined
  exactly within one dump:
      { units       = { [unit type] = { {l1, l2, l3, l4}, ... } },  -- db.Units `attribute`
        stores      = { [CLSID]     = { ... } },                    -- launcher `attribute`
        projectiles = { [name]      = { ... } },                    -- projectile `ws_type`
        ammunition  = { [unit type] = { ... } } }                   -- `type_ammunition` in a unit
  Each list holds the record's distinct fully numeric tuples (slots 1-4 read
  by indexing, so proxies count), sorted; a record without one is absent (e.g.
  a unit whose attribute slot 4 is a placeholder string). GT_t templates are
  not included. The ids are only comparable within one dump.

  _G/__constants__.lua holds the numeric DCS constants the extractors name enum
  values by: { <family> = { <NAME> = <number> } } for the wsType_, CAT_,
  SENSOR_, OPTIC_SENSOR_, RADAR_ and MODULATION_ globals, plus
  country = { <NAME> = <WorldID> } from the db_countries `country` table.

  WRITE_WHOLE tables (db.Callnames, db.FormationID, db.Units.Skills, the fuze
  GUI tables, ...) are written whole, one file each at their _G path
  (_G/db/Callnames.lua, _G/FuzeDescriptions.lua); an absent one is logged.

  _G/U/ (format 3) holds the Mission Editor's unit-conversion tables, one file
  per `name` record: _G/U/speedUnits/kts.lua is
  _G["U"]["speedUnits"]["imperial"] = { coeff = ..., name = "kts" }, and
  _G/U/months/<Month>.lua the month records ({ days, name }, "#Index" keys).
  The full Mission Editor sets the global U = require('me_utilities'); a
  dedicated server (`--server`) never sets U, but its GUI script
  (MissionEditor/dedicatedServerGUI.lua) has already loaded me_utilities
  through me_db_api, so the hook reads that module table. The hook never
  loads a Mission Editor module itself. Names are localised with the DCS
  language (_('kts')). A dump without U, or with no records under it, fails.

  _G/__DUMP_FORMAT__.lua holds the dump format number (bare integer).
  _G/__DCS_VERSION__.lua holds the raw DCS version string
  (no Lua wrapper). Every launch clears _G/ and dumps again; the version
  marker is written last, and only if every record, __constants__.lua,
  __wstype_ids__.lua and __DUMP_FORMAT__.lua were written.
------------------------------------------------------------------------------]]

local LOG_NAME = 'DCS.Lua.Exporter'

-- Output root, relative to lfs.writedir(). Forward slashes work on Windows.
local DUMP_FOLDER = 'DCS.Lua.Exporter/'
local VERSION_FILE = '__DCS_VERSION__.lua'
local FORMAT_FILE = '__DUMP_FORMAT__.lua'
-- Bumped when the dump gains files the extractors require; common.py reads
-- DUMP_FORMAT and WRITE_WHOLE from this file.
local DUMP_FORMAT = 3

-- Depth below _G to which the pre-scan records tables, so shared records
-- (warheads, pylons, ...) become path references. 2 == _G.<top>.<record>.
local SCAN_DEPTH = 2

-- Replaces volatile numeric type-ids that churn every patch.
local REDACTED = 'Redacted'

-- Tables whose `name` records are projectiles; their ws_type ids resolve slot 4
-- of ws_type / wsTypeOfWeapon tuples to a projectile name.
local PROJECTILE_TABLES = { 'rockets', 'bombs', 'torpedoes', 'weapons_table' }

-- Separator for internal path keys ("_G\tdb\tUnits"). Never written out.
local SEP = '\t'

-- Keys never traversed (they lead back to the global table / module env).
local IGNORE_KEYS = { _G = true, _M = true }

-- Tables dumped record by record: recurse until a table carrying `field` is
-- found; that table becomes one file. `excludeKeys` are top-level children to
-- skip. `from` lists the globals to read the table from, first present wins
-- (default: `path`); the files are written under `path`. A `required` table
-- that is absent or holds no record fails the dump.
local WRITE_RECURSIVE = {
  { path = 'U',              field = 'name', from = { 'U', 'me_utilities' }, required = true },
  { path = 'rockets',        field = 'name' },
  { path = 'bombs',          field = 'name' },
  { path = 'weapons_table',  field = 'name' },
  { path = 'warheads',       field = 'expl_mass' },
  { path = 'torpedoes',      field = 'name' },
  { path = 'launcher',       field = 'CLSID' },
  { path = 'Pylons',         field = 'name' },
  { path = 'db.Pods',        field = 'DisplayName' },
  { path = 'db.Sensors',     field = 'Name' },
  { path = 'db.Countries',   field = 'Name' },
  { path = 'db.Formations',  field = 'Name' },
  { path = 'db.Seasons',     field = 'Name' },
  { path = 'db.Units',       field = 'type', excludeKeys = { GT_t = true, Skills = true } },
}

-- Tables dumped whole, one file each: _G.db.Callnames -> _G/db/Callnames.lua.
-- db.Weapons is not dumped: its ByCLSID/Categories hold the launcher records.
local WRITE_WHOLE = {
  'db.Callnames',
  'db.callnamesRussia',
  'db.DefaultCountry',
  'db.FormationID',
  'db.Units.Skills',
  'db.roles',
  'db.Targets',
  'db.drop_systems',
  'db.rates',
  'FuzeDescriptions',
  'IndividualFuzeGUISettings',
  'SchemeFuzeParameters',
  'GUIWeaponSettingsData',
  'prbCoeff',
}

-- Tables dumped one level deep (each direct child is a file): the GT_t
-- templates that db.Units excludes above.
local WRITE_SHALLOW = {
  'db.Units.GT_t.CH_t',
  'db.Units.GT_t.LN_t',
  'db.Units.GT_t.SS_t',
  'db.Units.GT_t.WSN_t',
  'db.Units.GT_t.WS_t',
}

-- Top-level _G keys covered by WRITE_RECURSIVE; the pre-scan only enters these.
-- FIELD_OF_TOP maps single-level specs (rockets, Pylons, ...) to their id field.
local RECURSIVE_TOP, FIELD_OF_TOP = {}, {}
for _, spec in ipairs(WRITE_RECURSIVE) do
  RECURSIVE_TOP[spec.path:match('^[^.]+')] = true
  if not spec.path:find('.', 1, true) then FIELD_OF_TOP[spec.path] = spec.field end
end

-- File name a record is named after: its `field` value when that is a
-- non-empty string, else its key. planFiles makes the names unique.
local function recordFileName(key, value, field)
  local chosen = field and value[field]
  if type(chosen) ~= 'string' or chosen == '' then chosen = key end
  return tostring(chosen) .. '.lua'
end

-- Set before run(); required inside the guarded run so a missing module is
-- logged instead of breaking the hook chunk.
local serialize

------------------------------------------------------------------------------
-- Logging
------------------------------------------------------------------------------

local function logAt(level, message)
  if log and log.write then
    log.write(LOG_NAME, level, message)
  elseif net and net.log then
    net.log('[' .. LOG_NAME .. '] ' .. tostring(message))
  end
end
local function logInfo(message)  logAt(log and log.INFO or 0, message) end
local function logError(message) logAt(log and log.ERROR or 2, message) end

local function now()
  return (DCS and DCS.getRealTime and DCS.getRealTime()) or os.clock()
end

-- Run fn(...) and log how long it took.
local function timed(label, fn, ...)
  local startedAt = now()
  fn(...)
  logInfo(string.format('%s: %.2f s', label, now() - startedAt))
end

------------------------------------------------------------------------------
-- Paths
------------------------------------------------------------------------------

-- "db.Units" -> { "_G", "db", "Units" }
local function gPath(dotted)
  local out = { '_G' }
  for part in dotted:gmatch('[^.]+') do out[#out + 1] = part end
  return out
end

-- Follow a gPath list from _G; nil if any hop is missing.
local function resolve(list)
  local node = _G
  for i = 2, #list do
    if type(node) ~= 'table' then return nil end
    node = node[list[i]]
    if node == nil then return nil end
  end
  return node
end

local function pathDepth(pathKey)
  local n = 0
  for _ in pathKey:gmatch(SEP) do n = n + 1 end
  return n
end

-- { "_G", "warheads" } + "9M120" -> _G["warheads"]["9M120"]
local function toLuaIndex(list, key)
  local parts = { '_G' }
  for i = 2, #list do parts[#parts + 1] = string.format('[%q]', list[i]) end
  parts[#parts + 1] = string.format('[%q]', key)
  return table.concat(parts)
end

local function stripChars(str, chars)
  for i = 1, #chars do
    str = str:gsub('%' .. chars:sub(i, i), '')
  end
  return str
end
local function sanitiseFilename(name) return stripChars(name, '<>:"\\/|?*') end
local function sanitisePath(name)     return stripChars(name, '<>:"|?*')     end

-- pathKey of every record -> the (sanitised) file name it is written under.
-- Set by planFiles before any record is written.
local fileOf = {}

-- The dump path of the file holding a shared table's canonical copy, or nil
-- when that copy is not written as its own file (the caller then inlines it).
-- Only `_G.<top>.<key>` records written by a single-level WRITE_RECURSIVE
-- walker are referenced.
local function refPathFor(canonical)
  local segs = {}
  for part in (canonical .. SEP):gmatch('(.-)' .. SEP) do segs[#segs + 1] = part end
  if #segs ~= 3 or FIELD_OF_TOP[segs[2]] == nil then return nil end
  local file = fileOf[canonical]
  if file == nil then return nil end
  return '_G/' .. sanitisePath(segs[2]) .. '/' .. file
end

------------------------------------------------------------------------------
-- Filesystem
------------------------------------------------------------------------------

local DUMP_ROOT = lfs.writedir() .. DUMP_FOLDER

-- lfs.mkdir creates one level only, so make parents first.
local madeDirs = {}
local function ensureDir(absDir)
  if madeDirs[absDir] then return end
  if lfs.attributes(absDir, 'mode') ~= 'directory' then
    local parent = absDir:match('^(.*)[/\\][^/\\]+[/\\]?$')
    if parent and parent ~= '' then ensureDir(parent) end
    lfs.mkdir(absDir)
  end
  madeDirs[absDir] = true
end

-- Write text to <DUMP_ROOT><folder>/<file>. Returns true on success.
local function writeRaw(text, folder, file)
  local absDir = DUMP_ROOT .. sanitisePath(folder)
  ensureDir(absDir)
  local filepath = absDir .. '/' .. sanitiseFilename(file)
  local handle, err = io.open(filepath, 'w')
  if not handle then
    logError('Could not write ' .. filepath .. ': ' .. tostring(err))
    return false
  end
  handle:write(text)
  handle:close()
  return true
end

-- Every file and directory under `dir`; directories come after their contents.
local function listTree(dir, files, dirs)
  local ok, iter, state = pcall(lfs.dir, dir)
  if not ok then return end
  for entry in iter, state do
    if entry ~= '.' and entry ~= '..' then
      local full = dir .. '/' .. entry
      if lfs.attributes(full, 'mode') == 'directory' then
        listTree(full, files, dirs)
        dirs[#dirs + 1] = full
      else
        files[#files + 1] = full
      end
    end
  end
end

------------------------------------------------------------------------------
-- Version marker
------------------------------------------------------------------------------

local function dcsVersion()
  return _G['__DCS_VERSION__'] or _G['_APP_VERSION']
end

-- Remove the previous dump, version marker included.
local function clearPreviousDump()
  local files, dirs = {}, {}
  listTree(DUMP_ROOT .. '_G', files, dirs)
  for _, file in ipairs(files) do os.remove(file) end
  for _, dir in ipairs(dirs) do lfs.rmdir(dir) end
end

------------------------------------------------------------------------------
-- Shared-record references
------------------------------------------------------------------------------

-- seen:    pathKey -> table found there by the pre-scan
-- pathsOf: table -> list of pathKeys it was found at
-- canonOf: table -> its shallowest remaining pathKey (ties: lowest string)
local seen, pathsOf, canonOf = {}, {}, {}
local seenCount = 0
local written = {}
-- pathKey of the record being serialized; read by `process`.
local currentPath = nil
-- "<dir>/<file>" of the record being serialized, for log lines.
local currentRecord = nil

local function shallower(a, b)
  if b == nil then return true end
  local da, db = pathDepth(a), pathDepth(b)
  if da ~= db then return da < db end
  return a < b
end

local function scanShared(tbl, pathKey, depth)
  if depth > SCAN_DEPTH then return end
  seen[pathKey] = tbl
  seenCount = seenCount + 1
  local paths = pathsOf[tbl]
  if not paths then paths = {}; pathsOf[tbl] = paths end
  paths[#paths + 1] = pathKey
  if shallower(pathKey, canonOf[tbl]) then canonOf[tbl] = pathKey end

  for key, value in pairs(tbl) do
    if type(value) == 'table' and not IGNORE_KEYS[key]
        and (depth > 0 or RECURSIVE_TOP[key]) then
      scanShared(value, pathKey .. SEP .. tostring(key), depth + 1)
    end
  end
end

-- A table emitted as a reference no longer has children at `pathKey`, so drop
-- them from `seen` and re-pick the canonical path of any table that used one.
local function forgetSubtree(tbl, pathKey, depth)
  if depth >= SCAN_DEPTH then return end
  for key, value in pairs(tbl) do
    local child = pathKey .. SEP .. tostring(key)
    if type(value) == 'table' and seen[child] == value then
      seen[child] = nil
      if canonOf[value] == child then
        local best = nil
        for _, p in ipairs(pathsOf[value]) do
          if seen[p] == value and shallower(p, best) then best = p end
        end
        canonOf[value] = best
      end
      forgetSubtree(value, child, depth + 1)
    end
  end
end

local function shallowCopy(t)
  local copy = {}
  for k, v in pairs(t) do copy[k] = v end
  return copy
end

------------------------------------------------------------------------------
-- wsType slot-4 translation
------------------------------------------------------------------------------

-- "l1 l2 l3 l4" -> projectile name, or false when several names share it.
local weaponNameOf = {}
-- "l1 l2 l4" (level 3 ignored) -> projectile name, or false when several
-- names share it. Fallback for launchers whose level 3 disagrees with the
-- projectile's own ws_type (2S6 Tunguska {4,4,11,n} vs 9M311 {4,4,34,n}).
local weaponNameOfL124 = {}
local slot4 = { exact = 0, fallback = 0, unmapped = 0, ambiguous = 0 }

-- Key of a fully numeric 4-level wsType tuple, else nil.
local function tupleKey(t)
  if type(t) ~= 'table' then return nil end
  local a, b, c, d = t[1], t[2], t[3], t[4]
  if type(a) ~= 'number' or type(b) ~= 'number'
      or type(c) ~= 'number' or type(d) ~= 'number' then
    return nil
  end
  return string.format('%.14g %.14g %.14g %.14g', a, b, c, d)
end

-- Key of a fully numeric 4-level wsType tuple without level 3, else nil.
-- Level 4 id 0 is a placeholder (cluster submunition launchers {4,5,38,0}),
-- not an id: it never keys the fallback.
local function tupleKeyL124(t)
  if not tupleKey(t) or t[4] == 0 then return nil end
  return string.format('%.14g %.14g %.14g', t[1], t[2], t[4])
end

local function addName(map, k, name)
  local prev = map[k]
  if prev == nil then
    map[k] = name
  elseif prev ~= name then
    map[k] = false
  end
end

------------------------------------------------------------------------------
-- Raw wsType ids (_G/__wstype_ids__.lua)
------------------------------------------------------------------------------

-- map -> id -> { tupleKey -> {l1, l2, l3, l4} }; written as lists sorted by key.
local wsTypeIds = { units = {}, projectiles = {}, stores = {}, ammunition = {} }
-- { map = 'units' | 'stores', id = unit type | CLSID } of the record being
-- serialized, else nil. Set by writeRecord, read by `process`.
local currentIds = nil

-- Record the raw numeric 4-tuple `t` (read by indexing: proxies) under map/id.
local function addIds(map, id, t)
  local k = tupleKey(t)
  if not k then return end
  local byKey = wsTypeIds[map][id]
  if not byKey then byKey = {}; wsTypeIds[map][id] = byKey end
  byKey[k] = { t[1], t[2], t[3], t[4] }
end

-- Recurse like dumpRecursive (a table with `name` is a record) and map each
-- record's numeric ws_type to its name.
local function collectProjectiles(tbl, visited)
  if visited[tbl] then return end
  visited[tbl] = true
  for key, value in pairs(tbl) do
    if type(value) == 'table' and not IGNORE_KEYS[key] then
      if value.name ~= nil then
        local k = tupleKey(value.ws_type)
        local name = value.name
        if k and type(name) == 'string' and name ~= '' then
          addIds('projectiles', name, value.ws_type)
          addName(weaponNameOf, k, name)
          local k124 = tupleKeyL124(value.ws_type)
          if k124 then addName(weaponNameOfL124, k124, name) end
        end
      else
        collectProjectiles(value, visited)
      end
    end
  end
end

-- Named and ambiguous (false) entries of a tuple -> name map.
local function countNames(map)
  local named, ambiguous = 0, 0
  for _, name in pairs(map) do
    if name then named = named + 1 else ambiguous = ambiguous + 1 end
  end
  return named, ambiguous
end

local function buildWeaponNames()
  local visited = {}
  for _, top in ipairs(PROJECTILE_TABLES) do
    if type(_G[top]) == 'table' then collectProjectiles(_G[top], visited) end
  end
  local named, ambiguous = countNames(weaponNameOf)
  logInfo('wsType map: ' .. named .. ' projectile tuples, ' .. ambiguous .. ' ambiguous')
  named, ambiguous = countNames(weaponNameOfL124)
  logInfo('wsType (l1,l2,l4) fallback map: ' .. named .. ' unique, ' .. ambiguous .. ' ambiguous')
end

-- A serialize key trail as "a/b/c".
local function pathString(path)
  local where = {}
  for i = 1, #path do where[i] = tostring(path[i]) end
  return table.concat(where, '/')
end

-- Fixed-shape tuples carry the volatile id at index 4.
local function redactTuple(value)
  if type(value) == 'number' then return REDACTED end
  if type(value) ~= 'table' or type(value[4]) ~= 'number' then return value end
  local copy = shallowCopy(value)
  copy[4] = REDACTED
  return copy
end

-- As redactTuple, but slot 4 becomes the projectile name when the full tuple
-- maps to exactly one, else the unique (l1, l2, l4) match. Slots are read by
-- indexing, not pairs: GT_t launcher proxies keep scalar slots behind
-- __index, so a pairs() copy would keep only slot 4.
local function translateTuple(value, path)
  local out = redactTuple(value)
  if type(out) ~= 'table' or rawequal(out, value) then return out end
  for i = 1, 3 do out[i] = value[i] end
  local name = weaponNameOf[tupleKey(value) or '']
  if name then
    out[4] = name
    slot4.exact = slot4.exact + 1
  elseif name == false then
    slot4.ambiguous = slot4.ambiguous + 1
  else
    local fb = weaponNameOfL124[tupleKeyL124(value) or '']
    if fb then
      out[4] = fb
      slot4.fallback = slot4.fallback + 1
      logInfo(string.format('wsType slot 4 fallback (l1,l2,l4): %s [%s] {%s} -> %s',
        tostring(currentRecord), pathString(path),
        string.format('%.14g, %.14g, %.14g, %.14g', value[1], value[2], value[3], value[4]), fb))
    elseif fb == false then
      slot4.ambiguous = slot4.ambiguous + 1
    else
      slot4.unmapped = slot4.unmapped + 1
    end
  end
  return out
end

-- `attribute` tuples carry it at index 4, or 3 when shorter.
local function redactAttribute(value)
  if type(value) ~= 'table' then return value end
  local index = (type(value[4]) == 'number' and 4)
    or (type(value[3]) == 'number' and 3) or nil
  if not index then return value end
  local copy = shallowCopy(value)
  copy[index] = REDACTED
  return copy
end

-- serialize `process` callback: redactions, then shared tables -> path refs.
local function process(item, path)
  local key = path[#path]
  if key == 'ws_type' or key == 'wsTypeOfWeapon' or key == 'type_ammunition' then
    if key == 'type_ammunition' and currentIds and currentIds.map == 'units' then
      addIds('ammunition', currentIds.id, item)
    end
    return translateTuple(item, path)
  elseif key == 'adapter_type' then
    return redactTuple(item)
  elseif key == 'attribute' then
    if currentIds and #path == 1 then addIds(currentIds.map, currentIds.id, item) end
    return redactAttribute(item)
  elseif key == 'index' then
    return REDACTED
  elseif key == 'Name' and type(item) == 'number' then
    return REDACTED
  end

  if type(item) ~= 'table' then return item end
  local canonical = canonOf[item]
  if canonical == nil then return item end

  local here = currentPath
  for i = 1, #path do here = here .. SEP .. tostring(path[i]) end
  if canonical == here then return item end
  local ref = refPathFor(canonical)
  if ref == nil then return item end
  forgetSubtree(item, here, pathDepth(here))
  return ref
end

local function onCycle(path)
  logInfo('Cycle dropped: ' .. tostring(currentRecord) .. ' [' .. pathString(path) .. ']')
end

local SERIALIZE_OPTS = { indent = '\t', newline = '\n', process = process, onCycle = onCycle }
local SERIALIZE_PLAIN = { indent = '\t', newline = '\n' }

------------------------------------------------------------------------------
-- Dump walkers
------------------------------------------------------------------------------

local failures = 0

-- Records whose key sorts first keep a contested file name: by exact file
-- name, then key (numbers ascending, then strings, then others by tostring).
local function recordBefore(a, b)
  if a.file ~= b.file then return a.file < b.file end
  local ta, tb = type(a.key), type(b.key)
  if ta ~= tb then return ta < tb end
  if ta == 'number' or ta == 'string' then return a.key < b.key end
  return tostring(a.key) < tostring(b.key)
end

-- Give every record of `plan` ({ dir, key, pathKey, file }) a file name unique
-- case-insensitively within the dump, and record it in fileOf.
local function planFiles(plan)
  local groups, ids, taken = {}, {}, {}
  for _, r in ipairs(plan) do
    local id = (r.dir .. '/' .. r.file):lower()
    taken[id] = true
    local group = groups[id]
    if not group then
      group = {}
      groups[id] = group
      ids[#ids + 1] = id
    end
    group[#group + 1] = r
  end
  table.sort(ids)
  for _, id in ipairs(ids) do
    local group = groups[id]
    if #group > 1 then
      table.sort(group, recordBefore)
      for i = 2, #group do
        local r = group[i]
        local stem = r.file:gsub('%.lua$', '')
        local n, file = i, nil
        repeat
          file = stem .. '~' .. n .. '.lua'
          n = n + 1
        until not taken[(r.dir .. '/' .. file):lower()]
        taken[(r.dir .. '/' .. file):lower()] = true
        logInfo('File name collision: ' .. r.dir .. '/' .. r.file .. ' [' .. tostring(r.key)
          .. '] matches ' .. group[1].file .. ' [' .. tostring(group[1].key)
          .. ']; written as ' .. file)
        r.file = file
      end
    end
  end
  for _, r in ipairs(plan) do fileOf[r.pathKey] = r.file end
end

-- Serialize one record, then write it. `list` is the parent path
-- ({ "_G", "warheads" }), `key` the record's key in it.
local function writeRecord(list, key, record)
  local pathKey = table.concat(list, SEP) .. SEP .. tostring(key)
  if written[pathKey] then return end
  written[pathKey] = true
  local filename = fileOf[pathKey]

  local target = toLuaIndex(list, type(key) == 'number' and '#Index' or tostring(key))
  currentPath = pathKey
  currentRecord = table.concat(list, '/') .. '/' .. tostring(filename)
  if list[2] == 'db' and list[3] == 'Units' and list[4] ~= 'GT_t'
      and type(record.type) == 'string' then
    currentIds = { map = 'units', id = record.type }
  elseif list[2] == 'launcher' and type(record.CLSID) == 'string' then
    currentIds = { map = 'stores', id = record.CLSID }
  end
  local ok, body = pcall(serialize, record, SERIALIZE_OPTS)
  currentPath = nil
  currentRecord = nil
  currentIds = nil
  if not ok then
    logError('Serialize failed for ' .. target .. ': ' .. tostring(body))
    failures = failures + 1
    return
  end
  if not writeRaw(target .. ' = ' .. body, table.concat(list, '/'), filename) then
    failures = failures + 1
  end
end

-- Recurse through `tbl` until a table carrying `field` is found, then
-- visit(list, key, record, filename) it. `list` is used as a push/pop stack.
local function dumpRecursive(tbl, list, field, excludeKeys, depth, visit)
  for key, value in pairs(tbl) do
    if type(value) == 'table' and not IGNORE_KEYS[key]
        and not (depth == 0 and excludeKeys and excludeKeys[key]) then
      if value[field] ~= nil then
        visit(list, key, value, recordFileName(key, value, field))
      else
        list[#list + 1] = tostring(key)
        dumpRecursive(value, list, field, excludeKeys, depth + 1, visit)
        list[#list] = nil
      end
    end
  end
end

-- Visit each direct child of `tbl` as a record.
local function dumpShallow(tbl, list, visit)
  for key, value in pairs(tbl) do
    visit(list, key, value, recordFileName(key, value, nil))
  end
end

-- Log each direct child of a WRITE_RECURSIVE table that holds no record (a
-- table without `field`, e.g. an empty db.Units.WWIIstructures), so a table
-- DCS keys differently does not vanish silently. `filled`: the children
-- (tostring of their keys) the walk found a record under.
local function logEmptyChildren(spec, node, filled)
  for key, value in pairs(node) do
    if type(value) == 'table' and not IGNORE_KEYS[key]
        and not (spec.excludeKeys and spec.excludeKeys[key]) and value[spec.field] == nil
        and not filled[tostring(key)] then
      logInfo('No records (no `' .. spec.field .. '`) under _G.' .. spec.path .. '.' .. tostring(key))
    end
  end
end

-- Walk every record of WRITE_RECURSIVE, WRITE_SHALLOW and WRITE_WHOLE with `visit`; with
-- `logged`, each table's walk is timed and absent tables are logged.
local function walkRecords(visit, logged)
  local function run(label, fn, ...)
    if logged then timed(label, fn, ...) else fn(...) end
  end
  for _, spec in ipairs(WRITE_RECURSIVE) do
    local list = gPath(spec.path)
    local node, source = nil, nil
    for _, dotted in ipairs(spec.from or { spec.path }) do
      node = resolve(gPath(dotted))
      if type(node) == 'table' then source = dotted; break end
    end
    if source then
      local count, filled, depth = 0, {}, #list
      local function counted(path, ...)
        count = count + 1
        if #path > depth then filled[path[depth + 1]] = true end
        return visit(path, ...)
      end
      run('_G.' .. spec.path .. (source ~= spec.path and ' (from _G.' .. source .. ')' or ''),
        dumpRecursive, node, list, spec.field, spec.excludeKeys, 0, counted)
      if logged then
        logEmptyChildren(spec, node, filled)
        if spec.required and count == 0 then
          logError('No records (no `' .. spec.field .. '`) under _G.' .. source)
          failures = failures + 1
        end
      end
    elseif logged and spec.required then
      logError('Required table _G.' .. spec.path .. ' is absent (looked in _G.'
        .. table.concat(spec.from or { spec.path }, ', _G.') .. ')')
      failures = failures + 1
    elseif logged then
      logInfo('Skipping absent table _G.' .. spec.path)
    end
  end

  for _, dotted in ipairs(WRITE_SHALLOW) do
    local list = gPath(dotted)
    local node = resolve(list)
    if type(node) == 'table' then run('_G.' .. dotted, dumpShallow, node, list, visit) end
  end

  for _, dotted in ipairs(WRITE_WHOLE) do
    local list = gPath(dotted)
    local key = table.remove(list)
    local node = resolve(list)
    node = type(node) == 'table' and node[key] or nil
    if type(node) == 'table' then
      visit(list, key, node, key .. '.lua')
    elseif logged then
      logInfo('Skipping absent table _G.' .. dotted)
    end
  end
end

-- The records walkRecords visits, with their file names.
local function planRecords()
  local plan, planned = {}, {}
  walkRecords(function(list, key, _, filename)
    local pathKey = table.concat(list, SEP) .. SEP .. tostring(key)
    if planned[pathKey] then return end
    planned[pathKey] = true
    plan[#plan + 1] = { dir = sanitisePath(table.concat(list, '/')), key = key,
      pathKey = pathKey, file = sanitiseFilename(filename) }
  end, false)
  planFiles(plan)
end

------------------------------------------------------------------------------
-- Service years
------------------------------------------------------------------------------
-- db.Countries in_service/out_of_service are all defaults (0 / 40000). The real
-- per-(unit type, country) years come from getYearsLocal(unitType, OldID), the
-- function the Mission Editor era filter uses. They are written to
--   _G/__years__.lua  ==  _G["__years__"] = { [unitType] = { [OldID] = { from = , to = } } }
-- getYearsLocal is only available in a running DCS; if it is missing or fails,
-- __years__.lua is not written.

local YEAR_UNIT_CATEGORIES = {
  { 'Planes', 'Plane' },
  { 'Helicopters', 'Helicopter' },
  { 'Ships', 'Ship' },
  { 'Cars', 'Car' },
  { 'Personnel', 'Personnel' },
}

local function findGetYears()
  if _G.DB and _G.DB.db and type(_G.DB.db.getYearsLocal) == 'function' then
    return _G.DB.db.getYearsLocal
  end
  if _G.db and type(_G.db.getYearsLocal) == 'function' then
    return _G.db.getYearsLocal
  end
  return nil
end

-- Accepts (from, to), { from =, to = } or { from, to }.
local function yearsFromResult(a, b)
  if type(a) == 'table' then
    return a.from or a[1], a.to or a[2]
  end
  return a, b
end

-- Only the (unit, country) pairs a country lists in its Units table.
local function exportYears()
  local getYears = findGetYears()
  if getYears == nil then
    logInfo('getYearsLocal not available; __years__.lua not written.')
    return
  end
  local countries = _G.db and _G.db.Countries
  if type(countries) ~= 'table' then return end

  local out, count = {}, 0
  for _, country in pairs(countries) do
    local oldID = type(country) == 'table' and country.OldID
    local units = type(country) == 'table' and country.Units
    if type(oldID) == 'string' and type(units) == 'table' then
      for _, cat in ipairs(YEAR_UNIT_CATEGORIES) do
        local group = units[cat[1]]
        local entries = type(group) == 'table' and group[cat[2]]
        if type(entries) == 'table' then
          for _, entry in pairs(entries) do
            local unitType = type(entry) == 'table' and entry.Name
            if type(unitType) == 'string' and unitType ~= ''
                and not (out[unitType] and out[unitType][oldID]) then
              local ok, a, b = pcall(getYears, unitType, oldID)
              if ok then
                local from, to = yearsFromResult(a, b)
                if type(from) == 'number' then
                  out[unitType] = out[unitType] or {}
                  out[unitType][oldID] = { from = from, to = type(to) == 'number' and to or nil }
                  count = count + 1
                end
              end
            end
          end
        end
      end
    end
  end

  if count > 0 then
    writeRaw('_G["__years__"] = ' .. serialize(out, SERIALIZE_PLAIN), '_G', '__years__.lua')
    logInfo('Captured service years for ' .. count .. ' (unit, country) pairs.')
  else
    logInfo('getYearsLocal returned no usable pairs; __years__.lua not written.')
  end
end

------------------------------------------------------------------------------
-- DCS constants
------------------------------------------------------------------------------

-- Family -> name pattern of the numeric globals written to __constants__.lua.
local CONSTANT_FAMILIES = {
  wsType = '^wsType_',
  CAT = '^CAT_',
  SENSOR = '^SENSOR_',
  OPTIC_SENSOR = '^OPTIC_SENSOR_',
  RADAR = '^RADAR_',
  MODULATION = '^MODULATION_',
}

local function exportConstants()
  local out, count = {}, 0
  local function add(family, name, value)
    out[family] = out[family] or {}
    out[family][name] = value
    count = count + 1
  end
  for name, value in pairs(_G) do
    if type(name) == 'string' and type(value) == 'number' then
      for family, pattern in pairs(CONSTANT_FAMILIES) do
        if name:find(pattern) then add(family, name, value) end
      end
    end
  end
  -- db_countries.lua: country.names[WorldID] = 'RUSSIA', ...
  local names = type(country) == 'table' and country.names
  if type(names) == 'table' then
    for id, name in pairs(names) do
      if type(id) == 'number' and type(name) == 'string' then add('country', name, id) end
    end
  end
  if count > 0 and not writeRaw('_G["__constants__"] = ' .. serialize(out, SERIALIZE_PLAIN),
      '_G', '__constants__.lua') then
    error('could not write __constants__.lua')
  end
  logInfo('Captured ' .. count .. ' DCS constants.')
end

local function exportWsTypeIds()
  local out, count = {}, 0
  for map, ids in pairs(wsTypeIds) do
    out[map] = {}
    for id, byKey in pairs(ids) do
      local keys = {}
      for k in pairs(byKey) do keys[#keys + 1] = k end
      table.sort(keys)
      local list = {}
      for i, k in ipairs(keys) do list[i] = byKey[k] end
      out[map][id] = list
      count = count + 1
    end
  end
  if not writeRaw('_G["__wstype_ids__"] = ' .. serialize(out, SERIALIZE_PLAIN),
      '_G', '__wstype_ids__.lua') then
    error('could not write __wstype_ids__.lua')
  end
  logInfo('Captured raw wsType ids of ' .. count .. ' records.')
end

------------------------------------------------------------------------------
-- Main
------------------------------------------------------------------------------

local function exportAll()
  timed('Pre-scan', scanShared, _G, '_G', 0)
  logInfo('Pre-scan recorded ' .. seenCount .. ' tables')
  timed('wsType map', buildWeaponNames)
  timed('File names', planRecords)
  walkRecords(writeRecord, true)
  logInfo('wsType slot 4: ' .. slot4.exact .. ' exact, ' .. slot4.fallback
    .. ' fallback (l1,l2,l4), ' .. slot4.unmapped .. ' unmapped, '
    .. slot4.ambiguous .. ' ambiguous')

  timed('Constants', function()
    local ok, err = pcall(exportConstants)
    if not ok then
      logError('Constants capture failed: ' .. tostring(err))
      failures = failures + 1
    end
  end)

  timed('wsType ids', function()
    local ok, err = pcall(exportWsTypeIds)
    if not ok then
      logError('wsType ids capture failed: ' .. tostring(err))
      failures = failures + 1
    end
  end)

  timed('Service years', function()
    local ok, err = pcall(exportYears)
    if not ok then
      logError('Service years capture failed (ignored): ' .. tostring(err))
    end
  end)
end

local function run()
  serialize = require 'serialize'
  logInfo('Dumping _G for DCS ' .. tostring(dcsVersion()))
  timed('Clear previous dump', clearPreviousDump)

  local startedAt = now()
  exportAll()
  local endedAt = now()

  if failures > 0 then
    logError('Export aborted: ' .. failures .. ' failures; version marker not written.')
    return
  end
  if not writeRaw(tostring(DUMP_FORMAT), '_G', FORMAT_FILE) then
    logError('Could not write ' .. FORMAT_FILE .. '; version marker not written.')
    return
  end
  if writeRaw(tostring(dcsVersion()), '_G', VERSION_FILE) then
    logInfo(string.format('Export complete in %.2f s', endedAt - startedAt))
  end
end

do
  -- serialize.lua sits next to this hook (Saved Games or game-dir Hooks folder).
  local savedPath = package.path
  package.path = package.path
    .. ';' .. lfs.writedir() .. 'Scripts/Hooks/?.lua'
    .. ';./Scripts/Hooks/?.lua'

  local ok, err = pcall(run)
  if not ok then
    logError('Export aborted: ' .. tostring(err))
  end

  package.path = savedPath
end
