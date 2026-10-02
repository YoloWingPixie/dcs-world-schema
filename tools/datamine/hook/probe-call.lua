--[[----------------------------------------------------------------------------
  probe-call.lua - infers a function's arguments from its own argument errors.

  A module (returns a table, no side effects), so DCS running it as a GameGUI
  hook does nothing. api-probe.lua loads it in the GameGUI state and installs
  it in the scripting and export states (net.dostring_in), as
  __apiProbe.lib; everything the probe keeps in such a state is under the
  __apiProbe global.

  probe(f, opts) calls f with pcall and no arguments, then repeatedly: parses
  the error (parse), supplies a sample value of the expected type at the
  position it names, and calls again, until the call succeeds, fails with an
  error that names no argument, or MAX_ATTEMPTS calls were made. Error forms
  (a leading "<source>:<line>: " is ignored):
    bad argument #N to 'name' (T expected, got X)    luaL_typerror
    bad argument #N to 'name' (T expected)           luaL_argerror, custom text
    bad argument #N (T expected, got X)              no function name
    calling 'name' on bad self (T expected, got X)   a method's self
    Parameter #self missed                           DCS: self, type not named
    Parameter #N<text> missed                        DCS: argument N (after self
                                                     when a #self error was
                                                     seen), type not named
    attempt to <op> local 'p' (a nil value)          Lua functions: p is the
                                                     function's parameter p
                                                     (index, get length of ->
                                                     table; call -> function;
                                                     perform arithmetic on ->
                                                     number; concatenate ->
                                                     string), only when raised
                                                     inside the function itself
  A bad-argument error naming another function (a nested call's) is not the
  probed function's and ends the probe. T is mapped to a sample kind: number,
  string, boolean, table, function, vec3 ({x, y, z}), vec2 ({x, y}), or a
  class sample (opts.samples, e.g. Unit) by name, case-insensitively. When
  the error names no type, candidates are tried in order: for self the
  owner class's sample, then the other samples; else kinds the hint text
  suggests (name -> string, point -> vec3, ...), then number, string, table,
  boolean, function, vec3, vec2 and the class samples. The same error after
  every candidate for its position was tried is `stuck`.

  Safety while f runs: a count hook ends the call after INSTRUCTION_LIMIT Lua
  instructions (`timeout`; a C call that never returns is not interrupted);
  io.open for writing, io.output, io.popen, os.remove, os.rename, os.exit,
  os.execute, os.tmpname and lfs.mkdir, rmdir, chdir, touch, link and
  create_lockfile of the state raise `probe: blocked <name>` (`blocked`).
  Both are undone after the call.

  The record (JSON via encode):
    status      ok | error | stuck | limit | timeout | blocked | noSample |
                notFunction
    attempts    calls made
    params      [ { position, expected (the type text, or the hint), from =
                "error" (a luaL type error) | "self" | "missed" (DCS, no
                type) | "usage" (Lua usage error), sample (the kind that was
                accepted or last tried), value (the context value passed,
                when the last call had it), message (the error, cleaned),
                dcsIndex (a "Parameter #N" N) } ] by position
    minArgs     (ok) the highest position supplied
    returns     (ok) [ { type, className (a DCS object's class), keys (up to
                KEY_LIMIT sorted string keys of another table), keyCount
                (when more), array (it has [1]) } ]
    extraArgs   (ok, opts.extra) true when a call with one more argument
                succeeded, else false with extraError
    error       the final error (cleaned: no "<source>:<line>: " of the
                probe's own chunks, addresses as 0x?)
    blocked     (blocked) the blocked function's name
    sample      (noSample) the kind that had no sample
    paramNames  (Lua functions, with debug) the parameter names
------------------------------------------------------------------------------]]

local M = {}

local type, pcall, select, tostring, tonumber, next, rawget, getmetatable, error =
  type, pcall, select, tostring, tonumber, next, rawget, getmetatable, error
-- selene: allow(incorrect_standard_library_use) -- Lua 5.2+ (lupa) fallback
local unpack = unpack or table.unpack
local sformat, sgsub, smatch, sfind, slower, ssub, sbyte =
  string.format, string.gsub, string.match, string.find, string.lower, string.sub, string.byte
local tsort, tconcat = table.sort, table.concat
local dbg = debug

M.MAX_ARGS = 8
M.MAX_ATTEMPTS = 32
M.HOOK_COUNT = 10000
M.INSTRUCTION_LIMIT = 20000000
M.KEY_LIMIT = 24
M.ERROR_LENGTH = 500
local TIMEOUT = 'probe: instruction limit'
local BLOCKED = 'probe: blocked '

local function noop() end

-- Sample kinds that need no DCS object; each call gets a fresh value.
local BASIC = {
  number = function() return 1 end,
  string = function() return 'probe' end,
  boolean = function() return true end,
  table = function() return {} end,
  ['function'] = function() return noop end,
  vec3 = function() return { x = 0, y = 0, z = 0 } end,
  vec2 = function() return { x = 0, y = 0 } end,
}
local TRIAL = { 'number', 'string', 'table', 'boolean', 'function', 'vec3', 'vec2' }
local TYPE_KINDS = {
  number = 'number', integer = 'number', int = 'number', float = 'number',
  double = 'number', string = 'string', boolean = 'boolean', bool = 'boolean',
  table = 'table', ['function'] = 'function', vec3 = 'vec3', vec2 = 'vec2',
  point = 'vec3', position = 'vec3',
}
-- Hint words (DCS "Parameter #N (<hint>) missed") -> the kind tried first.
local HINTS = {
  { 'vec2', 'vec2' }, { 'vec3', 'vec3' }, { 'point', 'vec3' }, { 'pos', 'vec3' },
  { 'name', 'string' }, { 'text', 'string' }, { 'message', 'string' }, { 'str', 'string' },
  { 'func', 'function' }, { 'callback', 'function' }, { 'handler', 'table' },
  { 'id', 'number' }, { 'time', 'number' }, { 'coalition', 'number' },
  { 'country', 'number' }, { 'side', 'number' }, { 'number', 'number' },
  { 'count', 'number' }, { 'frequency', 'number' }, { 'flag', 'boolean' },
  { 'table', 'table' }, { 'task', 'table' }, { 'volume', 'table' },
}
local USAGE_KINDS = {
  index = 'table', ['get length of'] = 'table', call = 'function',
  ['perform arithmetic on'] = 'number', concatenate = 'string',
}
M.BASIC = BASIC

local function sortedKeys(t)
  local keys = {}
  for k in next, t do
    if type(k) == 'string' then keys[#keys + 1] = k end
  end
  tsort(keys)
  return keys
end

-- ---------------------------------------------------------------------------
-- JSON
-- ---------------------------------------------------------------------------

local ESCAPES = { ['"'] = '\\"', ['\\'] = '\\\\', ['\b'] = '\\b', ['\f'] = '\\f',
                  ['\n'] = '\\n', ['\r'] = '\\r', ['\t'] = '\\t' }

local function jsonString(s)
  return '"' .. sgsub(s, '[%c"\\]', function(c)
    return ESCAPES[c] or sformat('\\u%04x', sbyte(c))
  end) .. '"'
end
M.jsonString = jsonString

local function isArray(t)
  local n = 0
  for _ in next, t do n = n + 1 end
  for i = 1, n do
    if rawget(t, i) == nil then return false end
  end
  return n > 0
end

-- JSON text of a value made of tables (arrays or string-keyed), strings,
-- numbers and booleans; object keys sorted.
function M.encode(v)
  local t = type(v)
  if t == 'string' then return jsonString(v) end
  if t == 'boolean' then return tostring(v) end
  if t == 'number' then
    if v ~= v or v == math.huge or v == -math.huge then return jsonString(tostring(v)) end
    -- %.0f, not %d: %d casts to a C long, 32-bit on Windows.
    if v == math.floor(v) and v > -2 ^ 53 and v < 2 ^ 53 then return sformat('%.0f', v) end
    -- DCS may run under a C locale with a decimal comma.
    return (sgsub(sformat('%.17g', v), ',', '.'))
  end
  if t ~= 'table' then return 'null' end
  local parts = {}
  if isArray(v) then
    for i = 1, #v do parts[i] = M.encode(v[i]) end
    return '[' .. tconcat(parts, ',') .. ']'
  end
  for _, k in ipairs(sortedKeys(v)) do
    parts[#parts + 1] = jsonString(k) .. ':' .. M.encode(v[k])
  end
  return '{' .. tconcat(parts, ',') .. '}'
end

-- ---------------------------------------------------------------------------
-- Error parsing
-- ---------------------------------------------------------------------------

-- msg without a leading "<source>:<line>: ", and that source and line.
local function splitWhere(msg)
  local src, line, body = smatch(msg, '^(.-):(%d+): (.*)$')
  if src and not sfind(src, '\n', 1, true) then return body, src, tonumber(line) end
  return msg, nil, nil
end

function M.clean(msg)
  msg = tostring(msg)
  msg = sgsub(msg, '0x%x+', '0x?')
  msg = sgsub(msg, ': %x%x%x%x%x%x%x%x+', ': 0x?')
  if #msg > M.ERROR_LENGTH then msg = ssub(msg, 1, M.ERROR_LENGTH) .. '...' end
  return msg
end

local function trim(s)
  return (sgsub(sgsub(s or '', '^[%s%(]+', ''), '[%s%)]+$', ''))
end

-- The argument an error message names: { pos, expected | hint, from,
-- dcsIndex, usage } or nil (the error names no argument, or another
-- function's). name is the probed function's name.
function M.parse(msg, name)
  if type(msg) ~= 'string' then return nil end
  local body, src, line = splitWhere(msg)
  local n, fname, rest = smatch(body, "^bad argument #(%d+) to '(.-)' %((.*)%)$")
  if not n then n, rest = smatch(body, '^bad argument #(%d+) %((.*)%)$') end
  if n then
    if fname and fname ~= '?' and name and fname ~= name then return nil end
    local exp = smatch(rest, '^(.-) expected, got .*$') or smatch(rest, '^(%S+) expected$')
    if not exp then return nil end
    return { pos = tonumber(n), expected = exp, from = 'error' }
  end
  fname, rest = smatch(body, "^calling '(.-)' on bad self %((.*)%)$")
  if fname then
    local exp = smatch(rest, '^(.-) expected, got .*$') or smatch(rest, '^(%S+) expected$')
    if exp then return { pos = 1, expected = exp, from = 'error' } end
    return { pos = 1, hint = 'self', from = 'self' }
  end
  local which, hint = smatch(body, '^[Pp]arameter #(%w+)(.-) missed')
  if which == 'self' then return { pos = 1, hint = 'self', from = 'self' } end
  if which and tonumber(which) then
    return { pos = tonumber(which), hint = trim(hint), from = 'missed', dcsIndex = tonumber(which) }
  end
  local op, var = smatch(body, "^attempt to (.-) local '(.-)' %(a nil value%)$")
  if op and USAGE_KINDS[op] then
    return { usage = var, kind = USAGE_KINDS[op], src = src, line = line, from = 'usage' }
  end
  return nil
end

-- ---------------------------------------------------------------------------
-- Samples
-- ---------------------------------------------------------------------------

local function classNames(samples)
  local names = {}
  for k in next, samples do
    if type(k) == 'string' and not BASIC[k] then names[#names + 1] = k end
  end
  tsort(names)
  return names
end

-- The sample kind a type name stands for, or nil.
function M.kindFor(expected, samples)
  local low = slower(trim(expected))
  if TYPE_KINDS[low] then return TYPE_KINDS[low] end
  for _, k in ipairs(classNames(samples)) do
    if slower(k) == low then return k end
  end
  return nil
end

-- A fresh value of kind, or nil when that sample is unavailable.
function M.make(kind, samples)
  if BASIC[kind] then return BASIC[kind]() end
  local get = samples[kind]
  if type(get) ~= 'function' then return nil end
  local ok, v = pcall(get)
  if ok then return v end
  return nil
end

local function append(list, seen, kind)
  if kind and not seen[kind] then
    seen[kind] = true
    list[#list + 1] = kind
  end
end

-- Kinds to try for an error that names no type, in order.
function M.candidates(e, samples, owner)
  local list, seen = {}, {}
  local classes = classNames(samples)
  if e.hint == 'self' then
    if owner and samples[owner] then append(list, seen, owner) end
    for _, k in ipairs(classes) do append(list, seen, k) end
    append(list, seen, 'table')
    return list
  end
  local low = slower(e.hint or '')
  for _, h in ipairs(HINTS) do
    if sfind(low, h[1], 1, true) then append(list, seen, h[2]) end
  end
  for _, k in ipairs(classes) do
    if sfind(low, slower(k), 1, true) then append(list, seen, k) end
  end
  for _, k in ipairs(TRIAL) do append(list, seen, k) end
  for _, k in ipairs(classes) do append(list, seen, k) end
  return list
end

-- ---------------------------------------------------------------------------
-- One guarded call
-- ---------------------------------------------------------------------------

local GUARDED = {
  { 'os', 'remove' }, { 'os', 'rename' }, { 'os', 'exit' }, { 'os', 'execute' },
  { 'os', 'tmpname' }, { 'io', 'output' }, { 'io', 'popen' },
  { 'lfs', 'mkdir' }, { 'lfs', 'rmdir' }, { 'lfs', 'chdir' }, { 'lfs', 'touch' },
  { 'lfs', 'link' }, { 'lfs', 'create_lockfile' },
}

local function blocker(name)
  return function() error(BLOCKED .. name, 0) end
end

-- Replace G's file-writing and process functions with ones that raise;
-- returns the function that puts the originals back.
function M.guard(G)
  local saved = {}
  local function swap(lib, key, fn)
    local t = rawget(G, lib)
    if type(t) == 'table' and rawget(t, key) ~= nil then
      saved[#saved + 1] = { t, key, rawget(t, key) }
      t[key] = fn
    end
  end
  for _, g in ipairs(GUARDED) do swap(g[1], g[2], blocker(g[1] .. '.' .. g[2])) end
  local io = rawget(G, 'io')
  local open = type(io) == 'table' and rawget(io, 'open')
  if type(open) == 'function' then
    swap('io', 'open', function(path, mode)
      if mode ~= nil and (type(mode) ~= 'string' or not sfind(mode, '^r') or sfind(mode, '+', 1, true)) then
        error(BLOCKED .. 'io.open', 0)
      end
      return open(path, mode)
    end)
  end
  return function()
    for i = #saved, 1, -1 do
      local s = saved[i]
      s[1][s[2]] = s[3]
    end
  end
end

-- selene: allow(mixed_table) -- table.pack's { n = ..., ... } shape
local function pack(...) return { n = select('#', ...), ... } end

-- pcall(f, args[1..n]) under the guard and the instruction limit; returns
-- the packed results and, with names wanted, f's parameter names.
local function guardedCall(G, f, args, n, wantNames)
  local restore = M.guard(G)
  local sethook, gethook, getinfo, getlocal =
    dbg and dbg.sethook, dbg and dbg.gethook, dbg and dbg.getinfo, dbg and dbg.getlocal
  local names
  local oldHook, oldMask, oldCount
  if sethook then
    oldHook, oldMask, oldCount = gethook()
    local ticks = 0
    local limit = M.INSTRUCTION_LIMIT / M.HOOK_COUNT
    sethook(function(event)
      if event == 'count' then
        ticks = ticks + 1
        if ticks > limit then error(TIMEOUT, 0) end
      elseif wantNames and not names then
        local info = getinfo(2, 'f')
        if info and info.func == f then
          names = {}
          for i = 1, 255 do
            local nm = getlocal(2, i)
            if not nm or ssub(nm, 1, 1) == '(' then break end
            names[i] = nm
          end
        end
      end
    end, wantNames and 'c' or '', M.HOOK_COUNT)
  end
  local r = pack(pcall(f, unpack(args, 1, n)))
  if sethook then
    if oldHook then sethook(oldHook, oldMask, oldCount) else sethook() end
  end
  restore()
  return r, names
end

-- ---------------------------------------------------------------------------
-- Probe
-- ---------------------------------------------------------------------------

local function describe(v)
  local d = { type = type(v) }
  if type(v) ~= 'table' then return d end
  local mt = getmetatable(v)
  local cls = type(mt) == 'table' and rawget(mt, 'className_')
  if type(cls) == 'string' then
    d.className = cls
    return d
  end
  local keys = sortedKeys(v)
  if #keys > M.KEY_LIMIT then
    d.keyCount = #keys
    for i = #keys, M.KEY_LIMIT + 1, -1 do keys[i] = nil end
  end
  if #keys > 0 then d.keys = keys end
  if rawget(v, 1) ~= nil then d.array = true end
  return d
end

local function where(f)
  if not (dbg and dbg.getinfo) then return nil end
  local info = dbg.getinfo(f, 'S')
  if info and info.what == 'Lua' then return info end
  return nil
end

-- The error e of a Lua usage message as an argument error, or nil when it
-- was not raised inside f or names no parameter of f.
local function usageArg(e, f, names)
  local info = where(f)
  if not info or not names then return nil end
  if e.src ~= info.short_src or not e.line
    or e.line < info.linedefined or e.line > info.lastlinedefined then
    return nil
  end
  for i, nm in ipairs(names) do
    if nm == e.usage then
      return { pos = i, expected = e.kind, hint = nm, from = 'usage' }
    end
  end
  return nil
end

--[[ probe(f, opts) -> record (see the header). opts:
  G        the state's globals, for the guard (default _G)
  name     f's name, to tell its errors from nested calls'
  owner    the class of the table f was found in, tried first for self
  samples  { <class> = function returning a fresh object or nil }
  context  { [position] = { <kind> = value } }: tried before the kind's
           plain sample at that position (a mission object's name for a
           string, ...); when the call then fails with an error that names
           no argument, or the same error again, the plain sample replaces it
  extra    also try one more argument after a success ]]
function M.probe(f, opts)
  opts = opts or {}
  local G = opts.G or _G
  local samples = opts.samples or {}
  local context = opts.context or {}
  local rec = { attempts = 0 }
  if type(f) ~= 'function' then
    rec.status = 'notFunction'
    return rec
  end
  local isLua = where(f) ~= nil
  local args, n, params, tried = {}, 0, {}, {}
  local fromContext, contextTried = {}, {}
  local selfSeen = false
  local names
  local r

  -- A value of kind for pos: the context value the first time, else the
  -- plain sample.
  local function take(pos, kind)
    local c = context[pos]
    if c and c[kind] ~= nil and not contextTried[pos] then
      contextTried[pos] = true
      fromContext[pos] = kind
      return c[kind]
    end
    return M.make(kind, samples)
  end

  -- Put the plain sample where a context value is; true when there was one.
  local function dropContext()
    for pos = 1, M.MAX_ARGS do
      local kind = fromContext[pos]
      if kind then
        fromContext[pos] = nil
        args[pos] = M.make(kind, samples)
        return true
      end
    end
    return false
  end

  for attempt = 1, M.MAX_ATTEMPTS do
    rec.attempts = attempt
    local got
    r, got = guardedCall(G, f, args, n, isLua and not names)
    names = names or got
    if r[1] then break end
    local msg = r[2]
    if msg == TIMEOUT then
      rec.status = 'timeout'
      break
    end
    if type(msg) == 'string' and ssub(msg, 1, #BLOCKED) == BLOCKED then
      rec.status, rec.blocked = 'blocked', ssub(msg, #BLOCKED + 1)
      break
    end
    local e = M.parse(msg, opts.name)
    if e and e.usage then e = usageArg(e, f, names) end
    if not e or e.pos < 1 or e.pos > M.MAX_ARGS then
      if not dropContext() then
        rec.status, rec.error = 'error', M.clean(msg)
        break
      end
    else
      if e.hint == 'self' then selfSeen = true end
      if e.from == 'missed' and selfSeen then e.pos = e.pos + 1 end
      local pos = e.pos
      tried[pos] = tried[pos] or {}
      local kind, value
      if e.expected then
        kind = M.kindFor(e.expected, samples)
        if not kind then
          rec.status, rec.sample, rec.error = 'noSample', e.expected, M.clean(msg)
        elseif tried[pos][kind] and fromContext[pos] == kind then
          fromContext[pos] = nil
          value = M.make(kind, samples)
        elseif tried[pos][kind] then
          rec.status, rec.error = 'stuck', M.clean(msg)
        else
          tried[pos][kind] = true
          value = take(pos, kind)
          if value == nil then rec.status, rec.sample, rec.error = 'noSample', kind, M.clean(msg) end
        end
      else
        if fromContext[pos] then
          kind = fromContext[pos]
          fromContext[pos] = nil
          value = M.make(kind, samples)
        else
          for _, k in ipairs(M.candidates(e, samples, opts.owner)) do
            if not tried[pos][k] then
              tried[pos][k] = true
              value = take(pos, k)
              if value ~= nil then
                kind = k
                break
              end
            end
          end
        end
        if value == nil then rec.status, rec.error = 'stuck', M.clean(msg) end
      end
      params[pos] = {
        position = pos, expected = e.expected or e.hint, from = e.from,
        sample = kind or rec.sample, message = M.clean(msg), dcsIndex = e.dcsIndex,
      }
      if rec.status then break end
      args[pos] = value
      if pos > n then n = pos end
    end
  end
  for pos in next, fromContext do
    if params[pos] then params[pos].value = args[pos] end
  end
  if names then rec.paramNames = names end
  local list = {}
  for pos = 1, M.MAX_ARGS do
    if params[pos] then list[#list + 1] = params[pos] end
  end
  if #list > 0 then rec.params = list end
  if rec.status then return rec end
  if not r[1] then
    rec.status, rec.error = 'limit', M.clean(r[2])
    return rec
  end
  rec.status, rec.minArgs = 'ok', n
  local returns = {}
  for i = 2, r.n do returns[i - 1] = describe(r[i]) end
  if #returns > 0 then rec.returns = returns end
  if opts.extra then
    args[n + 1] = 1
    local x = guardedCall(G, f, args, n + 1, false)
    rec.extraArgs = x[1] and true or false
    if not x[1] then rec.extraError = M.clean(x[2]) end
  end
  return rec
end

-- ---------------------------------------------------------------------------
-- Plan entries in a state
-- ---------------------------------------------------------------------------

-- The value at an entry's keys (a key { m = true } is the metatable), or nil.
function M.resolve(G, keys)
  local v = G
  for _, k in ipairs(keys) do
    if type(k) == 'table' then
      v = dbg and dbg.getmetatable and dbg.getmetatable(v) or getmetatable(v)
    elseif type(v) == 'table' then
      v = rawget(v, k)
    else
      return nil
    end
    if v == nil then return nil end
  end
  return v
end

-- Which entries are another entry's function ("i\tj": entry i is the same
-- function as the earlier entry j) or no function ("i\t0").
function M.aliases(G, entries)
  local first, lines = {}, {}
  for i, e in ipairs(entries) do
    local f = M.resolve(G, e.keys)
    if type(f) ~= 'function' then
      lines[#lines + 1] = i .. '\t0'
    elseif first[f] then
      lines[#lines + 1] = i .. '\t' .. first[f]
    else
      first[f] = i
    end
  end
  return tconcat(lines, '\n')
end

local EXTRA = { '^get', '^is', '^has', '^count' }

-- JSON of the probe record of entry i of P.plan (P is __apiProbe).
function M.probeIndex(G, P, i)
  local e = P.plan[i]
  local f = M.resolve(G, e.keys)
  local extra = false
  for _, p in ipairs(EXTRA) do
    if sfind(e.name or '', p) then extra = true end
  end
  local rec = M.probe(f, {
    G = G, name = e.name, owner = e.owner, samples = P.samples or {},
    context = e.context, extra = extra,
  })
  return M.encode(rec)
end

-- ---------------------------------------------------------------------------
-- Mission scripting samples
-- ---------------------------------------------------------------------------

-- The sample objects' names when the plan names none (no probe mission).
local NAMES = {
  air = 'probe-air', ground = 'probe-ground', arty = 'probe-arty', static = 'probe-static',
}
M.NAMES = NAMES
-- Offsets (m) from the sample airbase of the objects spawned when the
-- mission lacks them; the mortar fires at a point TARGET from itself.
local GROUND, ARTY, STATIC, TARGET = { 600, 600 }, { 900, 600 }, { 700, 400 }, { 3000, 0 }

local function at(p, d) return { x = p.x + d[1], y = p.z + d[2] } end

--[[ setupMission(G, P): finds the sample objects in the mission scripting
  state, spawning any the mission lacks, and sets P.samples (getters by class
  name). P.mission (the plan's samples) names them: airbase, air (a group),
  ground, arty (a mortar group), static and target (the mortar's aim point,
  an offset from it). The airbase is P.mission.airbase, else the AIRDROME
  with the smallest name; a missing group or static is spawned next to it
  with country.id.USA (an orbiting F-15C, an M 818, a 2B11 mortar, a
  Windsock). Samples: Unit, Object, CoalitionObject, Group, Controller and
  Communicator (from the aircraft, else the airbase) from air; GroundGroup
  and GroundUnit from ground; StaticObject; Airbase and its Warehouse; an
  infrared Spot from the aircraft; the scenery object with the smallest name
  within 3 km of the airbase; the Weapon: the latest S_EVENT_SHOT weapon,
  else any weapon near the target (the mortar is ordered to fire at it).
  Returns JSON { <step> = "mission" (found in the mission) | "spawned" |
  "ok" | error text }. ]]
function M.setupMission(G, P)
  local steps, S = {}, {}
  P.samples = S
  local m = P.mission or {}
  local names = {}
  for k, v in next, NAMES do names[k] = m[k] or v end
  local function step(name, fn)
    local ok, res = pcall(fn)
    steps[name] = ok and (res or 'ok') or M.clean(res)
  end
  local ab, p
  step('airbase', function()
    local best = m.airbase and G.Airbase.getByName(m.airbase)
    local how = best and 'mission' or 'ok'
    if not best then
      for _, a in ipairs(G.world.getAirbases()) do
        local desc = a:getDesc()
        if desc and desc.category == G.Airbase.Category.AIRDROME then
          if not best or a:getName() < best:getName() then best = a end
        end
      end
    end
    ab = assert(best, 'no airdrome')
    p = ab:getPoint()
    local name = ab:getName()
    S.Airbase = function() return G.Airbase.getByName(name) end
    S.Warehouse = function() return G.Airbase.getByName(name):getWarehouse() end
    return how
  end)
  if not p then return M.encode(steps) end
  local usa = G.country.id.USA
  local function ground(name, type_, d)
    if G.Group.getByName(name) then return 'mission' end
    local pt = at(p, d)
    G.coalition.addGroup(usa, G.Group.Category.GROUND, {
      name = name, task = 'Ground Nothing',
      units = { { name = name .. '-1', type = type_, x = pt.x, y = pt.y, heading = 0,
                  skill = 'Average' } },
      route = { points = { { x = pt.x, y = pt.y, type = 'Turning Point',
                             action = 'Off Road', speed = 0 } } },
    })
    return 'spawned'
  end
  step('ground', function()
    S.GroundGroup = function() return G.Group.getByName(names.ground) end
    S.GroundUnit = function() return G.Unit.getByName(names.ground .. '-1') end
    return ground(names.ground, 'M 818', GROUND)
  end)
  step('air', function()
    local function unit() return G.Unit.getByName(names.air .. '-1') end
    S.Unit, S.Object, S.CoalitionObject = unit, unit, unit
    S.Group = function() return G.Group.getByName(names.air) end
    S.Controller = function() return G.Group.getByName(names.air):getController() end
    S.Communicator = function()
      local u = unit()
      local c = u and u.getCommunicator and u:getCommunicator()
      if c then return c end
      return G.Airbase.getByName(ab:getName()):getCommunicator()
    end
    if G.Group.getByName(names.air) then return 'mission' end
    local alt = p.y + 3000
    G.coalition.addGroup(usa, G.Group.Category.AIRPLANE, {
      name = names.air, task = 'Nothing',
      units = { { name = names.air .. '-1', type = 'F-15C', x = p.x, y = p.z, alt = alt,
                  alt_type = 'BARO', speed = 150, heading = 0, skill = 'Average',
                  payload = { fuel = 6103, flare = 60, chaff = 120, gun = 100, pylons = {} },
                  -- selene: allow(mixed_table) -- DCS's mission callsign format
                  callsign = { 1, 1, 1, name = 'Enfield11' }, onboard_num = '010' } },
      route = { points = { { x = p.x, y = p.z, alt = alt, alt_type = 'BARO',
                             type = 'Turning Point', action = 'Turning Point', speed = 150,
                             task = { id = 'ComboTask', params = { tasks = {
                               { number = 1, auto = false, enabled = true, id = 'Orbit',
                                 params = { pattern = 'Circle' } } } } } } } },
    })
    return 'spawned'
  end)
  step('static', function()
    S.StaticObject = function() return G.StaticObject.getByName(names.static) end
    if G.StaticObject.getByName(names.static) then return 'mission' end
    local pt = at(p, STATIC)
    G.coalition.addStaticObject(usa, { name = names.static, type = 'Windsock',
      category = 'Fortifications', x = pt.x, y = pt.y, heading = 0 })
    return 'spawned'
  end)
  step('spot', function()
    local spot = G.Spot.createInfraRed(G.Unit.getByName(names.air .. '-1'),
      { x = 0, y = 1, z = 0 }, { x = p.x, y = p.y, z = p.z })
    S.Spot = function() return spot end
  end)
  step('scenery', function()
    local found
    G.world.searchObjects(G.Object.Category.SCENERY,
      { id = G.world.VolumeType.SPHERE, params = { point = p, radius = 3000 } },
      function(o)
        local ok, name = pcall(o.getName, o)
        if ok and (not found or tostring(name) < found[1]) then found = { tostring(name), o } end
        return true
      end)
    assert(found, 'no scenery object within 3 km')
    S.SceneryObject = function() return found[2] end
  end)
  local target
  step('arty', function()
    local how = ground(names.arty, '2B11 mortar', ARTY)
    local u = assert(G.Unit.getByName(names.arty .. '-1'), 'no mortar unit')
    target = at(u:getPoint(), m.target or TARGET)
    G.timer.scheduleFunction(function()
      G.Group.getByName(names.arty):getController():setTask({ id = 'FireAtPoint',
        params = { point = target, radius = 50, expendQty = 500, expendQtyEnabled = true } })
    end, nil, G.timer.getTime() + 2)
    return how
  end)
  step('weapon', function()
    G.world.addEventHandler({ onEvent = function(_, ev)
      if ev.id == G.world.event.S_EVENT_SHOT and ev.weapon then P.weapon = ev.weapon end
    end })
    local aim = target or at(p, TARGET)
    S.Weapon = function()
      local w = P.weapon
      if w and w:isExist() then return w end
      local hit
      G.world.searchObjects(G.Object.Category.WEAPON,
        { id = G.world.VolumeType.SPHERE,
          params = { point = { x = aim.x, y = p.y, z = aim.y }, radius = 6000 } },
        function(o) hit = hit or o; return true end)
      return hit
    end
  end)
  return M.encode(steps)
end

-- JSON { <class> = true | false }: which samples resolve now.
function M.sampleStatus(P)
  local out = {}
  for _, k in ipairs(classNames(P.samples or {})) do
    out[k] = M.make(k, P.samples) ~= nil
  end
  return M.encode(out)
end

return M
