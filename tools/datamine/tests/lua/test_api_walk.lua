-- api-walk.lua's table budget: prints dump() of a small env with maxTables = 2.
-- Usage: lua5.1 test_api_walk.lua <hook dir>
local hook = assert(arg[1], 'usage: test_api_walk.lua <hook dir>')
local W = dofile(hook .. '/api-walk.lua')
local env = { a = { x = {}, y = {} }, b = {}, [1] = 'number key', pairs = pairs }
io.write(W.dump(env, { maxTables = 2 }))
