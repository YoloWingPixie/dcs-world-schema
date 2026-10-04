---
seeAlso:
  - Group.getByName
  - StaticObject.getByName
---

## Caveats

Returns `nil` for a unit that is dead, already removed or not spawned yet (late activation
groups return their units only after `Group:activate`). Check the result, and prefer
`Unit:isExist()` before calling methods on a unit you looked up earlier:

```lua
local unit = Unit.getByName("Pilot #001")
if unit and unit:isExist() then
  env.info(unit:getTypeName())
end
```
