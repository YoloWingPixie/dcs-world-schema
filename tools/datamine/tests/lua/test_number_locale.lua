-- api-walk.lua's and probe-call.lua's JSON numbers under a DCS-like C runtime:
-- a locale with a decimal comma, and %d casting to a 32-bit long (Windows).
-- Prints dump() of a small env, then encode() of a table. test_api_hook.py
-- runs it.
-- Usage: lua5.1 test_number_locale.lua <hook dir>
local hook = assert(arg[1], 'usage: test_number_locale.lua <hook dir>')

local realFormat = string.format
-- selene: allow(incorrect_standard_library_use) -- stands in for a locale-broken %d
string.format = function(f, ...)
  if f == '%d' then
    local v = (...) % 2 ^ 32
    if v >= 2 ^ 31 then v = v - 2 ^ 32 end
    return realFormat('%.0f', v)
  end
  local s = realFormat(f, ...)
  if f == '%.17g' or f == '%.14g' or f == '%.0f' then s = s:gsub('%.', ',') end
  return s
end

local W = dofile(hook .. '/api-walk.lua')
local P = dofile(hook .. '/probe-call.lua')
local values = { half = 0.5, big = 2 ^ 40, neg = -2 ^ 33, tiny = 1.25e-7 }
io.write(W.dump(values), '\n', P.encode(values), '\n')
