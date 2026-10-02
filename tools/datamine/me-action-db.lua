--[[----------------------------------------------------------------------------
  me-action-db.lua - load the Mission Editor's action tables outside DCS.

  Run by tools/datamine/extract_actions.py under lua5.1 (DCS's Lua) at extract
  time; not a DCS hook:

    lua5.1 me-action-db.lua <MissionEditor/modules dir> <tools/datamine/hook dir> < formations

  stdin is a Lua chunk returning db.Formations as the _G dump holds it
  ({ plane = { list = { { WorldID = 1, Name = "..." }, ... } }, ... }).
  stdout is one Lua chunk, `result = { ... }` (hook/serialize.lua), of plain
  data:

    actionTypes      me_action_db.ActionType
    actionTypeData   me_action_db.actionTypeData keyed by ActionType name
    actionIds        me_action_db.ActionId
    optionNames      the file's local OptionName table (read by a debug line
                     hook on its main chunk)
    actions          { [ActionId name] = { id, type, displayName, desc, task,
                     verifyGroupCapability, makeParams, onRemove, tblForUnit,
                     getDescription } }; task is the default task table, the
                     function fields are { name, line, lastLine } (name: the
                     module global or file local holding that function, absent
                     for an inline one)
    functions        { [name] = { line, lastLine } } of the module's functions
                     and the file's top-level local functions
    optionValues, optionValueDisplayName, weaponTable, aerobatics
                     the module tables of those names (AerobaticsManeuversData)
    availableActions { [group type] = { [ActionType name] = { [group task] =
                     { names = { ActionId name, ... }, holes = n } } } }; holes
                     counts list slots holding nil (an ActionId the file does
                     not define)
    availableActionsEdPublic
                     the same with the global ED_PUBLIC_AVAILABLE set (the
                     file drops some entries then; DCS sets it in some builds)
    static           me_staticAction_db: actionIds, actions (verifyUnitCapability
                     in place of verifyGroupCapability), availableActions
                     ({ Default = { names, holes } })

  Stubs: only what the two files touch while loading, each a table that raises
  on any other key, so a new load-time dependency fails loudly:
    me_utilities            timeUnits, altitudeUnits: { unitsTable = <name> }
                            markers (the option value tables name them)
    me_db_api               db.Formations from stdin
    me_ProductType          getType() -> "DCS" (not the "LOFAC" product)
    i18n                    setup(m) sets m._ to the identity, so display names
                            are DCS's untranslated source strings
    me_mission, Options.Data, dictionary, Mission.TriggerZoneController
                            empty (used only inside functions)
------------------------------------------------------------------------------]]

local modulesDir = assert(arg[1], 'usage: me-action-db.lua <modules dir> <hook dir> < formations')
local hookDir = assert(arg[2], 'usage: me-action-db.lua <modules dir> <hook dir> < formations')
local serialize = dofile(hookDir .. '/serialize.lua')

local formations = assert(loadstring(io.read('*a'), '=formations'))()

local function strict(name, t)
  return setmetatable(t, {
    __index = function(_, k)
      error(name .. '.' .. tostring(k) .. ' is not stubbed (me-action-db.lua)', 2)
    end,
  })
end

local STUBS = {
  me_utilities = function()
    return strict('me_utilities', {
      timeUnits = { unitsTable = 'timeUnits' },
      altitudeUnits = { unitsTable = 'altitudeUnits' },
    })
  end,
  me_db_api = function()
    return strict('me_db_api', { db = strict('me_db_api.db', { Formations = formations }) })
  end,
  me_ProductType = function()
    return strict('me_ProductType', { getType = function() return 'DCS' end })
  end,
  i18n = function()
    return strict('i18n', { setup = function(m) m._ = function(s) return s end end })
  end,
  me_mission = function() return strict('me_mission', {}) end,
  ['Options.Data'] = function() return strict('Options.Data', {}) end,
  dictionary = function() return strict('dictionary', {}) end,
  ['Mission.TriggerZoneController'] = function()
    return strict('Mission.TriggerZoneController', {})
  end,
}

local realRequire = require
-- selene: allow(incorrect_standard_library_use) -- stubs the ME modules' requires
require = function(name)
  local stub = STUBS[name]
  if not stub then error('require of unstubbed module ' .. tostring(name) .. ' (me-action-db.lua)', 2) end
  return stub()
end

-- Load a module file; its module table and the main chunk's locals.
local function load(file, name)
  package.loaded[name] = nil
  _G[name] = nil
  local chunk = assert(loadfile(modulesDir .. '/' .. file))
  local locals = {}
  -- At each line of the main chunk, the locals then in scope; the last
  -- line's are the file's top-level locals.
  debug.sethook(function()
    local info = debug.getinfo(2, 'f')
    if info and info.func == chunk then
      local i = 1
      while true do
        local k, v = debug.getlocal(2, i)
        if not k then break end
        if k:sub(1, 1) ~= '(' then locals[k] = v end
        i = i + 1
      end
    end
  end, 'l')
  local ok, err = pcall(chunk, name)
  debug.sethook()
  if not ok then error(file .. ': ' .. tostring(err), 0) end
  local M = package.loaded[name]
  if type(M) ~= 'table' then error(file .. ' did not define module ' .. name, 0) end
  return M, locals
end

-- Plain data: tables of strings, numbers and booleans; functions and
-- metatables dropped.
local function data(v, seen)
  if type(v) ~= 'table' then
    if type(v) == 'function' then return nil end
    return v
  end
  seen = seen or {}
  if seen[v] then error('cyclic table in action data', 0) end
  seen[v] = true
  local out = {}
  for k, x in pairs(v) do
    if type(k) == 'string' or type(k) == 'number' or type(k) == 'boolean' then
      out[k] = data(x, seen)
    end
  end
  seen[v] = nil
  return out
end

local function functionLines(M, locals)
  local out = {}
  for _, t in ipairs({ locals, M }) do
    for k, v in pairs(t) do
      if type(v) == 'function' and type(k) == 'string' then
        local info = debug.getinfo(v, 'S')
        if info.what == 'Lua' then out[k] = { line = info.linedefined, lastLine = info.lastlinedefined } end
      end
    end
  end
  return out
end

local function namer(M, locals)
  local names = {}
  for k, v in pairs(M) do
    if type(v) == 'function' and type(k) == 'string' then names[v] = k end
  end
  for k, v in pairs(locals) do
    if type(v) == 'function' and not names[v] then names[v] = k end
  end
  return function(f)
    if type(f) ~= 'function' then return nil end
    local info = debug.getinfo(f, 'S')
    return { name = names[f], line = info.linedefined, lastLine = info.lastlinedefined }
  end
end

local FUNCTION_FIELDS = {
  'verifyGroupCapability', 'verifyUnitCapability', 'makeParams', 'onRemove',
  'tblForUnit', 'getDescription',
}

local function actions(M, locals)
  local fn = namer(M, locals)
  local byNumber = {}
  for name, id in pairs(M.ActionId) do byNumber[id] = name end
  local out = {}
  for id, a in pairs(M.actionsData) do
    local name = byNumber[id]
    if not name then error('actionsData key ' .. tostring(id) .. ' is no ActionId', 0) end
    local rec = {
      id = id,
      type = a.type,
      displayName = a.displayName,
      desc = a.desc,
      task = data(a.task),
    }
    for _, f in ipairs(FUNCTION_FIELDS) do rec[f] = fn(a[f]) end
    out[name] = rec
  end
  return out, byNumber
end

local function idList(list, byNumber)
  local names, holes = {}, 0
  for i = 1, table.maxn(list) do
    local id = list[i]
    if id == nil then
      holes = holes + 1
    else
      names[#names + 1] = byNumber[id] or error('availableActions lists unknown id ' .. tostring(id), 0)
    end
  end
  return { names = names, holes = holes }
end

local function typeName(M, actionType)
  for name, n in pairs(M.ActionType) do
    if n == actionType then return name end
  end
  error('unknown ActionType ' .. tostring(actionType), 0)
end

local function available(M, byNumber)
  local out = {}
  for groupType, byType in pairs(M.availableActions) do
    out[groupType] = {}
    for actionType, byTask in pairs(byType) do
      local kind = typeName(M, actionType)
      out[groupType][kind] = {}
      for task, list in pairs(byTask) do
        out[groupType][kind][task] = idList(list, byNumber)
      end
    end
  end
  return out
end

local function typeData(M)
  local out = {}
  for actionType, t in pairs(M.actionTypeData) do out[typeName(M, actionType)] = data(t) end
  return out
end

local function need(M, file, names)
  for _, k in ipairs(names) do
    if type(M[k]) ~= 'table' then error(file .. ' defines no table ' .. k, 0) end
  end
end

local ACTION_DB_TABLES = {
  'ActionType', 'ActionId', 'actionTypeData', 'actionsData', 'availableActions',
  'optionValues', 'optionValueDisplayName', 'weaponTable', 'AerobaticsManeuversData',
}

_G.ED_PUBLIC_AVAILABLE = nil
local M, locals = load('me_action_db.lua', 'me_action_db')
need(M, 'me_action_db.lua', ACTION_DB_TABLES)
if type(locals.OptionName) ~= 'table' then error('me_action_db.lua has no local OptionName table', 0) end
local actionData, byNumber = actions(M, locals)
local result = {
  actionTypes = data(M.ActionType),
  actionTypeData = typeData(M),
  actionIds = data(M.ActionId),
  optionNames = data(locals.OptionName),
  actions = actionData,
  functions = functionLines(M, locals),
  optionValues = data(M.optionValues),
  optionValueDisplayName = data(M.optionValueDisplayName),
  weaponTable = data(M.weaponTable),
  aerobatics = data(M.AerobaticsManeuversData),
  availableActions = available(M, byNumber),
}

_G.ED_PUBLIC_AVAILABLE = true
local P = load('me_action_db.lua', 'me_action_db')
local _, publicByNumber = actions(P, {})
result.availableActionsEdPublic = available(P, publicByNumber)
_G.ED_PUBLIC_AVAILABLE = nil

local S, staticLocals = load('me_staticAction_db.lua', 'me_staticAction_db')
need(S, 'me_staticAction_db.lua', { 'ActionType', 'ActionId', 'actionsData', 'availableActions' })
local staticActions, staticByNumber = actions(S, staticLocals)
local staticAvailable = {}
for task, list in pairs(S.availableActions) do
  staticAvailable[task] = idList(list, staticByNumber)
end
result.static = {
  actionIds = data(S.ActionId),
  actions = staticActions,
  availableActions = staticAvailable,
}

require = realRequire
io.write('result = ', serialize(result, { indent = ' ', newline = '\n' }), '\n')
