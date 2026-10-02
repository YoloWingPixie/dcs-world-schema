--[[----------------------------------------------------------------------------
  api-probe.lua - DCS World Lua API argument probe hook.

  A DCS GameGUI hook. `task datamine -- --probe` (tools/datamine/refresh.py,
  api_probe.py) runs DCS headless after the API dump, with this file,
  probe-call.lua and the plan api-probe-plan.lua as hooks and the probe
  mission (probe_mission.py). The plan holds every function of the dumped
  envs (scripting, hooks, export) in probe order, each with its keys,
  debug.getinfo `what`, owner class and context argument values; the
  doNotCall patterns (overlays.yaml probe/doNotCall plus earlier crashes);
  and the mission's sample object names.

  When: SETTLE_SECONDS of model time after onSimulationStart, the hook
  installs probe-call.lua as __apiProbe.lib in the scripting and export
  states (hooks uses it directly) with each env's entries as
  __apiProbe.plan, sets up the samples (setupMission) and finds aliases
  (entries that are an earlier entry's function, or no function).
  WARMUP_SECONDS later (SHORT_WARMUP_SECONDS when no Weapon entry is left)
  it probes a few entries per frame (FRAME_BUDGET seconds of os.clock), so
  model time runs and the mortar keeps a shell in the air. Weapon-owner
  entries go first and wait up to WEAPON_WAIT_SECONDS for that sample.

  Each entry, in plan order, gets one record:
    denied     its path, or the path of any entry that is the same function,
               matches a doNotCall pattern (`*` matches any text) for its env:
               never called; { status = "denied", reason }
    sameAs     the same function as an earlier entry: { status, sameAs = path }
    missing    no function at its keys in this run
    otherwise  probe-call.lua probeIndex's record, or { status =
               "unavailable", error } when the state cannot be reached

  Crash resilience: <writedir>/DCS.Lua.Exporter/probe/progress.tsv is
  appended (and closed) line by line:
    P <tab> plan id                 first line; another id restarts the file
    V <tab> DCS version             second line
    X <tab> JSON                    sample steps and availability (first run)
    H <tab> model time              while waiting (warm-up, the Weapon
                                    sample), every HEARTBEAT_SECONDS
    S <tab> env <tab> path          written before the entry is called
    R <tab> env <tab> path <tab> JSON   its record
  On start an S without its R is the entry DCS died (or hung) in: it gets
  R { status = "crashed" } and the run resumes after it; entries with an R
  are skipped. H lines keep the file growing while the probe waits, so only
  a hung call stops it (and dcs.log) and the runner's stall check ends the
  run. When every entry
  has an R, probe/done (the DCS version) is written. `API probe failed:
  <reason>` is logged when the probe cannot go on.
------------------------------------------------------------------------------]]

local LOG_NAME = 'DCS.Lua.Exporter'
local OUT_DIR = 'DCS.Lua.Exporter/probe/'
local PLAN_FILE = 'api-probe-plan.lua'
local LIB_FILE = 'probe-call.lua'
local SETTLE_SECONDS = 1
local WARMUP_SECONDS = 15
local SHORT_WARMUP_SECONDS = 2
local WEAPON_WAIT_SECONDS = 90
local HEARTBEAT_SECONDS = 10
local FRAME_BUDGET = 0.25
local REMOTE = { scripting = true, export = true }

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

local function readHookFile(name)
  for _, dir in ipairs(HOOK_DIRS) do
    local f = io.open(dir .. name, 'r')
    if f then
      local text = f:read('*a')
      f:close()
      return text
    end
  end
  error(name .. ' not found next to the hook')
end

-- Whether path matches a doNotCall pattern (`*` matches any text).
local function globMatch(pattern, path)
  local p = pattern:gsub('[%^%$%(%)%%%.%[%]%+%-%?]', '%%%0'):gsub('%*', '.*')
  return path:find('^' .. p .. '$') ~= nil
end

-- The reason env/path is denied, or nil.
local function denyReason(deny, env, path)
  for _, d in ipairs(deny) do
    local envOk = not d.envs
    for _, e in ipairs(d.envs or {}) do
      if e == env then envOk = true end
    end
    if envOk and globMatch(d.pattern, path) then return d.reason end
  end
  return nil
end

-- Lua literal of a plan value (strings, numbers, booleans, tables).
local function literal(v)
  local t = type(v)
  if t == 'string' then return string.format('%q', v) end
  if t == 'number' or t == 'boolean' then return tostring(v) end
  local parts = {}
  local n = #v
  for i = 1, n do parts[#parts + 1] = literal(v[i]) end
  local keys = {}
  for k in pairs(v) do
    if type(k) ~= 'number' or k < 1 or k > n or k % 1 ~= 0 then keys[#keys + 1] = k end
  end
  table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
  for _, k in ipairs(keys) do
    parts[#parts + 1] = '[' .. literal(k) .. ']=' .. literal(v[k])
  end
  return '{' .. table.concat(parts, ',') .. '}'
end

local function appendLine(path, line)
  local f, err = io.open(path, 'ab')
  if not f then error('could not write ' .. path .. ': ' .. tostring(err)) end
  f:write(line, '\n')
  f:close()
end

local function writeFile(path, text)
  local f, err = io.open(path, 'wb')
  if not f then error('could not write ' .. path .. ': ' .. tostring(err)) end
  f:write(text)
  f:close()
end

-- The text a chunk run in state returns, or nil and why it failed.
local function runIn(state, chunk)
  local called, text, ok = pcall(net.dostring_in, state, chunk)
  if not called then return nil, 'net.dostring_in raised: ' .. tostring(text) end
  if ok == false then return nil, 'net.dostring_in failed: ' .. tostring(text) end
  if type(text) ~= 'string' then return nil, 'no result (' .. type(text) .. ')' end
  return text
end

local probe = {}

-- Read progress.tsv: { done = { [env .. '\t' .. path] = true }, inFlight =
-- list of { env, path }, hasSamples }; a file of another plan is started over
-- (its P and V lines).
function probe.readProgress(file, planId, version)
  local state = { done = {}, inFlight = {}, hasSamples = false }
  local f = io.open(file, 'rb')
  local lines = {}
  if f then
    for line in f:lines() do lines[#lines + 1] = line end
    f:close()
  end
  if lines[1] ~= 'P\t' .. planId then
    writeFile(file, 'P\t' .. planId .. '\nV\t' .. tostring(version) .. '\n')
    return state
  end
  local started, order = {}, {}
  for i = 2, #lines do
    local kind, env, path = lines[i]:match('^(%u)\t([^\t]*)\t([^\t]*)')
    if kind == 'S' then
      local key = env .. '\t' .. path
      if not started[key] then order[#order + 1] = { env, path } end
      started[key] = true
    elseif kind == 'R' then
      state.done[env .. '\t' .. path] = true
    elseif lines[i]:sub(1, 2) == 'X\t' then
      state.hasSamples = true
    end
  end
  for _, e in ipairs(order) do
    if not state.done[e[1] .. '\t' .. e[2]] then state.inFlight[#state.inFlight + 1] = e end
  end
  return state
end

local ctx

local function recordLine(env, path, json)
  appendLine(ctx.progress, 'R\t' .. env .. '\t' .. path .. '\t' .. json)
  ctx.done[env .. '\t' .. path] = true
end

local function jsonRecord(t)
  return ctx.lib.encode(t)
end

-- Run a chunk in env's state (or here for hooks); the returned text.
local function evalIn(env, chunk)
  if REMOTE[env] then return runIn(env, chunk) end
  local fn, err = loadstring(chunk)
  if not fn then return nil, err end
  local ok, res = pcall(fn)
  if not ok then return nil, tostring(res) end
  return res
end

local function prepare()
  local libSource = readHookFile(LIB_FILE)
  local plan = assert(loadstring(readHookFile(PLAN_FILE), PLAN_FILE))()
  ctx.lib = assert(loadstring(libSource, '=' .. LIB_FILE))()
  ctx.plan = plan
  local dir = lfs.writedir() .. OUT_DIR
  lfs.mkdir(lfs.writedir() .. 'DCS.Lua.Exporter')
  lfs.mkdir(dir)
  os.remove(dir .. 'done')
  ctx.dir = dir
  ctx.progress = dir .. 'progress.tsv'
  local progress = probe.readProgress(ctx.progress, plan.id, plan.version)
  ctx.done = progress.done
  for _, e in ipairs(progress.inFlight) do
    logInfo('API probe: ' .. e[1] .. ' ' .. e[2] .. ' crashed in an earlier run')
    recordLine(e[1], e[2], jsonRecord({ status = 'crashed' }))
  end
  ctx.firstRun = not progress.hasSamples

  -- Per env: its entries (plan order), the state's lib and the alias map.
  ctx.envs = {}
  for _, env in ipairs(plan.envs) do
    local entries = {}
    for _, e in ipairs(plan.entries) do
      if e.env == env then entries[#entries + 1] = e end
    end
    local list, index = {}, {}
    for i, e in ipairs(entries) do
      list[i] = { keys = e.keys, name = e.name, owner = e.owner, context = e.context }
      index[e] = i
    end
    local install = '__apiProbe = __apiProbe or {}\n'
      .. '__apiProbe.lib = assert(loadstring('
      .. string.format('%q', libSource) .. ", '=" .. LIB_FILE .. "'))()\n"
      .. '__apiProbe.plan = ' .. literal(list) .. '\n'
      .. '__apiProbe.mission = ' .. literal(plan.samples or {}) .. '\n'
      .. 'return __apiProbe.lib.aliases(_G, __apiProbe.plan)\n'
    local text, err = evalIn(env, install)
    local info = { entries = entries, index = index, alias = {}, missing = {}, error = err }
    if text then
      for i, j in text:gmatch('(%d+)\t(%d+)') do
        i, j = tonumber(i), tonumber(j)
        if j == 0 then info.missing[i] = true else info.alias[i] = j end
      end
    else
      logError('API probe: ' .. env .. ' unavailable: ' .. tostring(err))
    end
    -- A function is denied under every path it has when one of them is.
    local denied = {}
    for i, e in ipairs(entries) do
      local reason = denyReason(plan.deny, env, e.path)
      local root = info.alias[i] or i
      if reason and not denied[root] then denied[root] = { e.path, reason } end
    end
    info.denied = {}
    for i, e in ipairs(entries) do
      local d = denied[info.alias[i] or i]
      if d then
        info.denied[i] = d[1] == e.path and d[2] or ('same function as ' .. d[1] .. ': ' .. d[2])
      end
    end
    ctx.envs[env] = info
  end

  if ctx.envs.scripting and not ctx.envs.scripting.error then
    local steps, err = runIn('scripting', 'return __apiProbe.lib.setupMission(_G, __apiProbe)')
    ctx.setup = steps or ctx.lib.encode({ error = tostring(err) })
    logInfo('API probe samples: ' .. ctx.setup)
  end
end

local function sampleStatus()
  local text = runIn('scripting', 'return __apiProbe.lib.sampleStatus(__apiProbe)')
  return text or '{}'
end

local function weaponReady()
  local text = runIn('scripting',
    "return __apiProbe.lib.make('Weapon', __apiProbe.samples or {}) ~= nil and 'yes' or 'no'")
  return text == 'yes'
end

-- The queue: every entry, in plan order.
local function buildQueue()
  local queue = {}
  for _, e in ipairs(ctx.plan.entries) do
    local info = ctx.envs[e.env]
    if info then queue[#queue + 1] = { env = e.env, index = info.index[e], entry = e } end
  end
  return queue
end

-- Whether a scripting Weapon entry has no record yet.
local function weaponPending()
  for _, e in ipairs(ctx.plan.entries) do
    if e.env == 'scripting' and e.owner == 'Weapon' and not ctx.done[e.env .. '\t' .. e.path] then
      return true
    end
  end
  return false
end

local lastBeat = -math.huge

-- A heartbeat line while waiting, so progress.tsv keeps growing.
local function heartbeat(now)
  if now - lastBeat >= HEARTBEAT_SECONDS then
    lastBeat = now
    appendLine(ctx.progress, 'H\t' .. string.format('%.1f', now))
  end
end

local function probeOne(item)
  local env, i, e = item.env, item.index, item.entry
  local info = ctx.envs[env]
  if info.denied[i] then
    return recordLine(env, e.path, jsonRecord({ status = 'denied', reason = info.denied[i] }))
  end
  if info.error then
    return recordLine(env, e.path, jsonRecord({ status = 'unavailable', error = info.error }))
  end
  if info.alias[i] then
    return recordLine(env, e.path,
      jsonRecord({ status = 'sameAs', sameAs = info.entries[info.alias[i]].path }))
  end
  if info.missing[i] then
    return recordLine(env, e.path, jsonRecord({ status = 'missing' }))
  end
  appendLine(ctx.progress, 'S\t' .. env .. '\t' .. e.path)
  logInfo('API probe ' .. env .. ' ' .. e.path)
  local chunk = 'return __apiProbe.lib.probeIndex(_G, __apiProbe, ' .. i .. ')'
  local text, err = evalIn(env, chunk)
  if not text or text:sub(1, 1) ~= '{' then
    text = jsonRecord({ status = 'unavailable', error = tostring(err or text) })
  end
  recordLine(env, e.path, text)
end

local armed, finished = false, false
local phase, startedAt, readyAt, weaponDeadline
local queue, qi = nil, 1

-- One frame of work; returns true when every entry has a record.
local function step(now)
  if phase == 'setup' then
    prepare()
    local warmup = weaponPending() and WARMUP_SECONDS or SHORT_WARMUP_SECONDS
    phase, readyAt = 'warmup', now + warmup
    heartbeat(now)
    return false
  end
  if phase == 'warmup' then
    if now < readyAt then
      heartbeat(now)
      return false
    end
    queue, qi = buildQueue(), 1
    weaponDeadline = now + WEAPON_WAIT_SECONDS
    if ctx.firstRun then
      appendLine(ctx.progress, 'X\t{"setup":' .. (ctx.setup or '{}')
        .. ',"available":' .. (ctx.setup and sampleStatus() or '{}') .. '}')
    end
    phase = 'probe'
  end
  local clock = os.clock()
  local weaponWaited = false
  while qi <= #queue do
    local item = queue[qi]
    local key = item.env .. '\t' .. item.entry.path
    if not ctx.done[key] then
      if item.entry.owner == 'Weapon' and item.env == 'scripting' and not ctx.weaponSeen then
        if weaponReady() then
          ctx.weaponSeen = true
        elseif now < weaponDeadline then
          heartbeat(now)
          return false
        else
          ctx.weaponSeen = true
          weaponWaited = true
        end
        if ctx.firstRun then
          appendLine(ctx.progress, 'X\t{"weapon":' .. (weaponWaited and 'false' or 'true') .. '}')
        end
      end
      probeOne(item)
    end
    qi = qi + 1
    if os.clock() - clock > FRAME_BUDGET then return false end
  end
  return true
end

local function finish()
  writeFile(ctx.dir .. 'done', ctx.version)
  logInfo('API probe complete: ' .. ctx.dir)
end

probe.globMatch = globMatch
probe.denyReason = denyReason

if DCS and DCS.setUserCallbacks then
  DCS.setUserCallbacks({
    onSimulationStart = function()
      if finished or armed then return end
      armed = true
      phase = 'settle'
      startedAt = DCS.getModelTime()
    end,
    onSimulationFrame = function()
      if not armed or finished then return end
      local now = DCS.getModelTime()
      if phase == 'settle' then
        if now - startedAt < SETTLE_SECONDS then return end
        ctx = { version = tostring(_G['__DCS_VERSION__'] or _G['_APP_VERSION']) }
        phase = 'setup'
      end
      local ok, res = pcall(step, now)
      if not ok then
        finished = true
        logError('API probe failed: ' .. tostring(res))
      elseif res then
        finished = true
        local wrote, err = pcall(finish)
        if not wrote then logError('API probe failed: ' .. tostring(err)) end
      end
    end,
  })
end

return probe
