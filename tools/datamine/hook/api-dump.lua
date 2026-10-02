--[[----------------------------------------------------------------------------
  api-dump.lua - DCS World Lua API dump hook.

  A DCS GameGUI hook. `task datamine` (tools/datamine/refresh.py) runs DCS
  headless once with this file and api-walk.lua as hooks and an empty mission
  (tools/datamine/terrain_mission.py), so every Lua state of a running mission
  exists. The other states are reached from GameGUI via net.dostring_in, so no
  desanitized MissionScripting.lua is needed.

  When: the first onSimulationFrame at least SETTLE_SECONDS of model time after
  onSimulationStart (as terrain-dump.lua).

  Environments (ENVS), each walked by api-walk.lua's dump() (see its header):
    scripting  net.dostring_in('scripting', chunk): the mission scripting env
    hooks      this GameGUI state's _G, walked directly
    server     net.dostring_in('server', chunk)
    export     net.dostring_in('export', chunk)
  The chunk embeds api-walk.lua and returns dump()'s JSON text, or
  'ERROR: <message>' when the walk raised. A state that cannot be reached, or
  returns no JSON, is recorded as unavailable with the error; the other
  states are still dumped.

  State identity: a state whose tostring(_G) matches an env already dumped is
  the same Lua state under another name (DCS 2.9.29: 'server' is 'scripting');
  it is recorded as sameAs, not walked again.

  Output: <writedir>/DCS.Lua.Exporter/api/<env>.json, one JSON object per env:
    format      "dcs-api-dump/2"
    env, state  the env name and its net.dostring_in state (absent for hooks)
    dcsVersion  __DCS_VERSION__ or _APP_VERSION of the GameGUI state
    paths       { installDir = lfs.currentdir(), writeDir = lfs.writedir() },
                which the extractor strips from function sources
    status      "ok" with dump()'s keys (excluded, globals, limits,
                skippedKeys, stats); "sameAs" with sameAs = the env name; or
                "unavailable" with error
  and api/states.json, a probe of every net.dostring_in state name in PROBES:
    format, dcsVersion
    states      { <state> = { status = "ok" and one of: env = the env whose
                _G it is; sameAs = an earlier probed state with the same _G;
                globals = { <name> = <Lua type> } of its string keys but the
                standard library } or { status = "unavailable", error } }
  Then api/done (the DCS version) is written last. Only a failure to load
  api-walk.lua or to write a file logs `API dump failed: <reason>` and writes
  no marker.
------------------------------------------------------------------------------]]

local LOG_NAME = 'DCS.Lua.Exporter'
local OUT_DIR = 'DCS.Lua.Exporter/api/'
local SETTLE_SECONDS = 1
local FORMAT = 'dcs-api-dump/2'
local WALK_OPTS = '{ maxDepth = 8, maxTables = 20000, maxString = 4096,'
  .. ' apiDepth = 1, scanBudget = 200000, enumEntries = 500, enumDepth = 4 }'
local ENVS = {
  { name = 'scripting', state = 'scripting' },
  { name = 'hooks' },
  { name = 'server', state = 'server' },
  { name = 'export', state = 'export' },
}
-- net.dostring_in state names probed into states.json.
local PROBES = { 'config', 'export', 'gui', 'mission', 'scripting', 'server' }

local function logAt(level, message)
  if log and log.write then
    log.write(LOG_NAME, level, message)
  elseif net and net.log then
    net.log('[' .. LOG_NAME .. '] ' .. tostring(message))
  end
end
local function logInfo(message) logAt(log and log.INFO or 0, message) end
local function logError(message) logAt(log and log.ERROR or 2, message) end

local HOOK_DIRS = { lfs.writedir() .. 'Scripts/Hooks/', './Scripts/Hooks/' }

local function readWalkSource()
  for _, dir in ipairs(HOOK_DIRS) do
    local f = io.open(dir .. 'api-walk.lua', 'r')
    if f then
      local text = f:read('*a')
      f:close()
      return text
    end
  end
  error('api-walk.lua not found next to the hook')
end

-- The text a chunk run in state returns, or nil and why it is unavailable.
local function runIn(state, chunk)
  local called, text, ok = pcall(net.dostring_in, state, chunk)
  if not called then return nil, 'net.dostring_in raised: ' .. tostring(text) end
  if ok == false then return nil, 'net.dostring_in failed: ' .. tostring(text) end
  if type(text) ~= 'string' or text == '' then
    return nil, 'no result (' .. type(text) .. ')'
  end
  return text
end

local IDENTITY_CHUNK = 'return tostring(_G)'

-- dump()'s JSON text of another Lua state, or nil and why it is unavailable.
local function dumpState(state, walkSource)
  local chunk = 'local W = (function() ' .. walkSource .. '\nend)()\n'
    .. 'local ok, res = pcall(W.dump, _G, ' .. WALK_OPTS .. ')\n'
    .. 'if ok then return res end\n'
    .. "return 'ERROR: ' .. tostring(res)\n"
  local text, err = runIn(state, chunk)
  if not text then return nil, err end
  if text:sub(1, 7) == 'ERROR: ' then return nil, 'walk failed: ' .. text:sub(8) end
  if text:sub(1, 1) ~= '{' then return nil, 'not a JSON object: ' .. text:sub(1, 200) end
  return text
end

-- JSON of states.json's `states` (see the header); identities maps a _G's
-- tostring to the env it was dumped as.
local function probeStates(W, identities)
  local q = W.jsonString
  local chunk = 'local stdlib = {}\n'
    .. 'for _, n in ipairs({' .. table.concat((function()
      local names = {}
      for i, n in ipairs(W.STDLIB) do names[i] = string.format('%q', n) end
      return names
    end)(), ',') .. '}) do stdlib[n] = true end\n'
    .. 'local out = { tostring(_G) }\n'
    .. 'for k, v in next, _G do\n'
    .. "  if type(k) == 'string' and not stdlib[k] then out[#out + 1] = k .. '=' .. type(v) end\n"
    .. 'end\n'
    .. "return table.concat(out, '\\n')\n"
  local parts, probed = {}, {}
  for _, state in ipairs(PROBES) do
    local text, err = runIn(state, chunk)
    local body
    if text then
      local lines = {}
      for line in (text .. '\n'):gmatch('([^\n]*)\n') do lines[#lines + 1] = line end
      local id = table.remove(lines, 1)
      table.sort(lines)
      local globals = {}
      for i, line in ipairs(lines) do
        local name, t = line:match('^(.*)=([^=]*)$')
        globals[i] = q(name or line) .. ':' .. q(t or '?')
      end
      if identities[id] then
        body = '{"env":' .. q(identities[id]) .. ',"status":"ok"}'
      elseif probed[id] then
        body = '{"sameAs":' .. q(probed[id]) .. ',"status":"ok"}'
      else
        probed[id] = state
        body = '{"globals":{' .. table.concat(globals, ',') .. '},"status":"ok"}'
      end
    else
      body = '{"error":' .. q(err) .. ',"status":"unavailable"}'
    end
    parts[#parts + 1] = q(state) .. ':' .. body
  end
  return '{' .. table.concat(parts, ',') .. '}'
end

local function writeFile(path, text)
  local f, err = io.open(path, 'wb')
  if not f then error('could not write ' .. path .. ': ' .. tostring(err)) end
  f:write(text)
  f:close()
end

local function dump()
  local walkSource = readWalkSource()
  local W = assert(loadstring(walkSource, 'api-walk.lua'))()
  local q = W.jsonString
  local version = tostring(_G['__DCS_VERSION__'] or _G['_APP_VERSION'])
  local dir = lfs.writedir() .. OUT_DIR
  lfs.mkdir(lfs.writedir() .. 'DCS.Lua.Exporter')
  lfs.mkdir(dir)
  os.remove(dir .. 'done')

  local identities = {}  -- tostring(_G) -> env name
  for _, env in ipairs(ENVS) do
    local body, err, same
    if env.state then
      local id
      id, err = runIn(env.state, IDENTITY_CHUNK)
      if id then
        same = identities[id]
        if not same then
          identities[id] = env.name
          body, err = dumpState(env.state, walkSource)
        end
      end
    else
      identities[tostring(_G)] = env.name
      local ok, res = pcall(W.dump, _G, assert(loadstring('return ' .. WALK_OPTS))())
      if ok then body = res else err = 'walk failed: ' .. tostring(res) end
    end
    local head = '{"dcsVersion":' .. q(version) .. ',"env":' .. q(env.name)
      .. ',"format":' .. q(FORMAT)
      .. ',"paths":{"installDir":' .. q(tostring(lfs.currentdir()))
      .. ',"writeDir":' .. q(tostring(lfs.writedir())) .. '}'
      .. (env.state and (',"state":' .. q(env.state)) or '')
    local text
    if same then
      text = head .. ',"sameAs":' .. q(same) .. ',"status":"sameAs"}'
      logInfo('API dump ' .. env.name .. ': same state as ' .. same)
    elseif body then
      text = head .. ',"status":"ok",' .. body:sub(2)
      logInfo('API dump ' .. env.name .. ': ' .. #text .. ' bytes')
    else
      text = head .. ',"error":' .. q(err) .. ',"status":"unavailable"}'
      logInfo('API dump ' .. env.name .. ': unavailable: ' .. err)
    end
    writeFile(dir .. env.name .. '.json', text)
  end
  writeFile(dir .. 'states.json', '{"dcsVersion":' .. q(version) .. ',"format":' .. q(FORMAT)
    .. ',"states":' .. probeStates(W, identities) .. '}')
  writeFile(dir .. 'done', version)
  logInfo('API dump complete: ' .. dir)
end

local armed, done = false, false
local startedAt

DCS.setUserCallbacks({
  onSimulationStart = function()
    if done then return end
    armed = true
    startedAt = DCS.getModelTime()
  end,
  onSimulationFrame = function()
    if not armed or done then return end
    if DCS.getModelTime() - startedAt < SETTLE_SECONDS then return end
    done = true
    local ok, err = pcall(dump)
    if not ok then logError('API dump failed: ' .. tostring(err)) end
  end,
})
