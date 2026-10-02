-- Stand-ins for the DCS GameGUI globals the dump hook uses (lfs, log, net,
-- DCS), backed by the shell so the hook can run under a plain Lua 5.1.
-- Usage: dofile(this file) after setting the global WRITEDIR (trailing '/').

local function sh(q) return "'" .. q:gsub("'", "'\\''") .. "'" end
local function test(flag, p) return os.execute('test ' .. flag .. ' ' .. sh(p)) == 0 end

lfs = {
  writedir = function() return WRITEDIR end,
  mkdir = function(p) return os.execute('mkdir ' .. sh(p) .. ' 2>/dev/null') == 0 end,
  rmdir = function(p) return os.execute('rmdir ' .. sh(p) .. ' 2>/dev/null') == 0 end,
  attributes = function(p, what)
    local mode = (test('-d', p) and 'directory') or (test('-e', p) and 'file') or nil
    if not mode then return nil end
    if what == 'mode' then return mode end
    return { mode = mode }
  end,
  -- Like LuaFileSystem: returns the iterator and a dir object it must be called with.
  dir = function(p)
    if not test('-d', p) then error('cannot open ' .. p) end
    local entries = {}
    local h = io.popen('ls -a ' .. sh(p))
    for line in h:lines() do entries[#entries + 1] = line end
    h:close()
    local obj = { i = 0, entries = entries }
    local function iter(o)
      assert(o == obj, 'dir iterator called without its dir object')
      o.i = o.i + 1
      return o.entries[o.i]
    end
    return iter, obj
  end,
}

log = { INFO = 0, ERROR = 2, write = function(name, level, msg)
  print(string.format('[%s][%s] %s', name, level == 2 and 'ERROR' or 'INFO', msg))
end }
net = { log = print }
DCS = { getRealTime = os.clock }

-- The Mission Editor module a dedicated server's GUI script has loaded (the
-- hook dumps it as U); a test replaces or clears it.
_G.me_utilities = { speedUnits = { imperial = { name = 'kts', coeff = 1.9459459459459 } } }
