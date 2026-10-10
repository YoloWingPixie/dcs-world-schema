---
seeAlso:
  - Group.getByName
  - StaticObject.getByName
---

## Caveats

Returns `nil` for a unit that is dead, already removed or not spawned yet (late activation
groups return their units only after `Group:activate`). Check the result. Call
`Unit:isExist()` before using a unit looked up earlier:

```lua
local unit = Unit.getByName("Pilot #001")
if unit and unit:isExist() then
  env.info(unit:getTypeName())
end
```
