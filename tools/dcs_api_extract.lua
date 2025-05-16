local targets={
    Unit=true,
    Group=true,
    Object=true,
    SceneryObject=true,
    Spot=true,
    StaticObject=true,
    Warehouse=true,
    Weapon=true,
    atmosphere=true,
    coalition=true,
    coord=true,
    dcs=true,
    env=true,
    land=true,
    missionCommands=true,
    net=true,
    timer=true,
    trigger=true,
    VoiceChat=true,
    world=true,
    Airbase=true,
    Controller=true,
    CoalitionObject=true, -- Non-final class. Not actually accessible via API.
    AI=true,
    country=false,
    Beacons=true,
    Formation=true,
    Disposition=true,
    }
local esc={}for i=0,31 do esc[i]=string.format("\\u%04x",i)end esc[34]="\\\"" esc[92]="\\\\"
local function js(s)return"\""..s:gsub(".",function(c)return esc[c:byte()]or c end).."\""end
local function encode(x,seen,lv)
  local t=type(x)
  if t=="number"or t=="boolean"then return tostring(x)end
  if t=="string"then return js(x)end
  if t~="table"then return js("<"..t..">")end
  if seen[x]then return js("<cycle>")end
  seen[x]=true
  local indent=string.rep("  ",lv)
  local indent2=indent.."  "
  local arr=true local i=1
  for k in pairs(x)do if k~=i then arr=false break end i=i+1 end
  local r={}
  if arr then
    for _,v in ipairs(x)do r[#r+1]=indent2..encode(v,seen,lv+1)end
    return "[\n"..table.concat(r,",\n").."\n"..indent.."]"
  else
    for k,v in pairs(x)do r[#r+1]=indent2..encode(k,seen,lv+1)..": "..encode(v,seen,lv+1)end
    return "{\n"..table.concat(r,",\n").."\n"..indent.."}"
  end
end
local function snap(tbl,depth,seen)
  if depth==0 or seen[tbl]then return{kind="table",members={}}end
  seen[tbl]=true
  local mem={}
  for k,v in pairs(tbl)do
    local ok,tp=pcall(function()return type(v)end)
    if ok then
      local m={name=tostring(k),type=tp}
      if tp=="table"then m.sub=snap(v,depth-1,seen)end
      if tp=="number"or tp=="string"or tp=="boolean"then m.value=v end
      mem[#mem+1]=m
    end
  end
  return{kind="table",members=mem}
end
local root={}
for k,v in pairs(_G)do
  if targets[k]then
    local tp=type(v)
    if tp=="table"then root[k]=snap(v,10,{})else root[k]={kind=tp}end
  end
end
local f=io.open(lfs.writedir().."/DCS_API.json","w")
f:write(encode(root,{},0))
f:close()
