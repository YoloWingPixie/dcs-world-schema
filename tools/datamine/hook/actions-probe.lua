--[[----------------------------------------------------------------------------
  actions-probe.lua - DCS World AI actions probe hook.

  A DCS GameGUI hook. `task datamine -- --actions-probe`
  (tools/datamine/refresh.py, actions_probe.py) runs DCS headless with this
  file, actions-probe-lib.lua, probe-call.lua (the JSON encoder the lib is
  given) and the plan actions-probe-plan.lua as hooks
  and the actions probe mission (the argument probe's mission plus one
  late-activated group per `route` step). The plan lists steps: one call of
  an AI action (task, en-route task, command, option) in one context and id
  casing on one sample group's controller (see actions-probe-lib.lua).

  When: SETTLE_SECONDS of model time after onSimulationStart it installs
  the lib and the plan in the `scripting` state (__actionsProbe) and runs
  setup; WARMUP_SECONDS later it works through the steps in plan order, one
  at a time:
    reset    effect steps outside `route`: lib.reset, then RESET_SECONDS
    apply    lib.apply; dcs.log gets `ACTIONS PROBE BEGIN <plan> <n>`
    after    the next frame: lib.after
    wait     effect steps: the effect's seconds, then lib.measure
    finish   lib.cleanup; the record; `ACTIONS PROBE END <plan> <n>`
  so the dcs.log lines from one BEGIN to the next belong to one step
  (actions_probe.py attributes them).

  Crash resilience, as api-probe.lua: <writedir>/<outDir>/progress.tsv
  (the plan's outDir, default DCS.Lua.Exporter/actions-probe; each probe plan
  has its own) is appended line by line:
    P <tab> plan id          first line; another id restarts the file
    V <tab> DCS version      second line
    X <tab> JSON             setup result (first run)
    H <tab> model time       while waiting, every HEARTBEAT_SECONDS
    S <tab> n                before a step's apply
    R <tab> n <tab> JSON     its record
  An S without its R is the step DCS died (or hung) in: it gets R { status =
  "crashed" } on the next start and the run goes on after it. Denied steps
  (the plan's `denied` reason) get R { status = "denied" } uncalled. When
  every step has an R, <outDir>/done (the DCS version) is written.
  `Actions probe failed: <reason>` is logged when it cannot go on.
------------------------------------------------------------------------------]]

local LOG_NAME = 'DCS.Lua.Exporter'
local OUT_DIR = 'DCS.Lua.Exporter/actions-probe'
local PLAN_FILE = 'actions-probe-plan.lua'
local LIB_FILE = 'actions-probe-lib.lua'
local JSON_FILE = 'probe-call.lua'
local STATE = 'scripting'
local SETTLE_SECONDS = 1
local WARMUP_SECONDS = 10
local RESET_SECONDS = 5
local HEARTBEAT_SECONDS = 10
local MARKER = 'ACTIONS PROBE'

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

-- The text a chunk run in the scripting state returns, or nil and why not.
local function runIn(chunk)
  local called, text, ok = pcall(net.dostring_in, STATE, chunk)
  if not called then return nil, 'net.dostring_in raised: ' .. tostring(text) end
  if ok == false then return nil, 'net.dostring_in failed: ' .. tostring(text) end
  if type(text) ~= 'string' then return nil, 'no result (' .. type(text) .. ')' end
  return text
end

local probe = {}

-- Read progress.tsv: { done = { [n] = true }, inFlight = { n, ... },
-- hasSetup }; a file of another plan is started over.
function probe.readProgress(file, planId, version)
  local state = { done = {}, inFlight = {}, hasSetup = false }
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
    local kind, n = lines[i]:match('^(%u)\t(%d+)')
    n = tonumber(n)
    if kind == 'S' then
      if not started[n] then order[#order + 1] = n end
      started[n] = true
    elseif kind == 'R' then
      state.done[n] = true
    elseif lines[i]:sub(1, 2) == 'X\t' then
      state.hasSetup = true
    end
  end
  for _, n in ipairs(order) do
    if not state.done[n] then state.inFlight[#state.inFlight + 1] = n end
  end
  return state
end

local ctx

local function record(n, json)
  appendLine(ctx.progress, 'R\t' .. n .. '\t' .. json)
  ctx.done[n] = true
end

local function marker(what, n)
  logInfo(MARKER .. ' ' .. what .. ' ' .. ctx.plan.id .. ' ' .. n)
end

-- A lib call's JSON text, or a JSON error object.
local function lib(fn, n)
  local text, err = runIn('return __actionsProbe.lib.' .. fn .. '(_G, __actionsProbe'
    .. (n and (', ' .. n) or '') .. ')')
  if not text or text:sub(1, 1) ~= '{' then
    return '{"error":' .. ctx.encode(tostring(err or text)) .. '}', false
  end
  return text, true
end

local function prepare()
  local libSource = readHookFile(LIB_FILE)
  local jsonSource = readHookFile(JSON_FILE)
  local planSource = readHookFile(PLAN_FILE)
  local plan = assert(loadstring(planSource, '=' .. PLAN_FILE))()
  local json = assert(loadstring(jsonSource, '=' .. JSON_FILE))()
  ctx.plan, ctx.encode = plan, json.encode
  local dir = lfs.writedir() .. (plan.outDir or OUT_DIR) .. '/'
  lfs.mkdir(lfs.writedir() .. 'DCS.Lua.Exporter')
  lfs.mkdir(dir)
  os.remove(dir .. 'done')
  ctx.dir = dir
  ctx.progress = dir .. 'progress.tsv'
  local progress = probe.readProgress(ctx.progress, plan.id, plan.version)
  ctx.done = progress.done
  for _, n in ipairs(progress.inFlight) do
    logInfo('Actions probe: step ' .. n .. ' crashed in an earlier run')
    record(n, '{"status":"crashed"}')
  end
  local install = '__actionsProbe = {}\n'
    .. '__actionsProbe.lib = assert(loadstring(' .. string.format('%q', libSource)
    .. ", '=" .. LIB_FILE .. "'))(assert(loadstring(" .. string.format('%q', jsonSource)
    .. ", '=" .. JSON_FILE .. "'))())\n"
    .. '__actionsProbe.plan = assert(loadstring(' .. string.format('%q', planSource)
    .. ", '=" .. PLAN_FILE .. "'))()\n"
    .. 'return __actionsProbe.lib.setup(_G, __actionsProbe)\n'
  local text, err = runIn(install)
  if not text then error('scripting state unavailable: ' .. tostring(err)) end
  if not progress.hasSetup then appendLine(ctx.progress, 'X\t' .. text) end
  logInfo('Actions probe setup: ' .. text)
end

local lastBeat = -math.huge

local function heartbeat(now)
  if now - lastBeat >= HEARTBEAT_SECONDS then
    lastBeat = now
    appendLine(ctx.progress, 'H\t' .. string.format('%.1f', now))
  end
end

local armed, finished = false, false
local phase, startedAt, readyAt
local qi, cur = 1, nil

-- One frame of work; true when every step has a record.
local function step(now)
  if phase == 'setup' then
    prepare()
    phase, readyAt = 'warmup', now + WARMUP_SECONDS
    return false
  end
  if phase == 'warmup' then
    if now < readyAt then heartbeat(now) return false end
    phase = 'steps'
  end
  local steps = ctx.plan.steps
  while true do
    if not cur then
      while qi <= #steps and ctx.done[qi] do qi = qi + 1 end
      if qi > #steps then return true end
      local s = steps[qi]
      if s.denied then
        record(qi, '{"status":"denied","reason":' .. ctx.encode(s.denied) .. '}')
      else
        cur = { n = qi, s = s, parts = {} }
        if s.effect and s.context ~= 'route' then
          cur.parts.reset = lib('reset', qi)
          cur.phase, cur.at = 'settle', now + RESET_SECONDS
        else
          cur.phase = 'apply'
        end
      end
    end
    if cur then
      if cur.phase == 'settle' then
        if now < cur.at then heartbeat(now) return false end
        cur.phase = 'apply'
      end
      if cur.phase == 'apply' then
        appendLine(ctx.progress, 'S\t' .. cur.n)
        marker('BEGIN', cur.n)
        cur.parts.apply = lib('apply', cur.n)
        cur.phase = 'after'
        return false
      end
      if cur.phase == 'after' then
        cur.parts.after = lib('after', cur.n)
        if cur.s.effect then
          cur.phase, cur.at = 'wait', now + cur.s.effect.seconds
        else
          cur.phase = 'finish'
        end
      end
      if cur.phase == 'wait' then
        if now < cur.at then heartbeat(now) return false end
        cur.parts.measure = lib('measure', cur.n)
        cur.phase = 'finish'
      end
      if cur.phase == 'finish' then
        cur.parts.cleanup = lib('cleanup', cur.n)
        local fields = { '"status":"done"' }
        for _, k in ipairs({ 'reset', 'apply', 'after', 'measure', 'cleanup' }) do
          if cur.parts[k] then fields[#fields + 1] = '"' .. k .. '":' .. cur.parts[k] end
        end
        record(cur.n, '{' .. table.concat(fields, ',') .. '}')
        marker('END', cur.n)
        cur = nil
        return false
      end
    end
  end
end

local function finish()
  writeFile(ctx.dir .. 'done', ctx.version)
  logInfo('Actions probe complete: ' .. ctx.dir)
end

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
        logError('Actions probe failed: ' .. tostring(res))
      elseif res then
        finished = true
        local wrote, err = pcall(finish)
        if not wrote then logError('Actions probe failed: ' .. tostring(err)) end
      end
    end,
  })
end

return probe
