---
seeAlso:
  - Controller.pushTask
  - Controller.resetTask
  - DcsTask.Task.Orbit
---

## Example

Make an airborne group orbit a point at 6000 m. `setTask` replaces the current task;
`pushTask` stacks one on top of it.

```lua
local group = Group.getByName("CAP North")
local point = trigger.misc.getZone("CAP North").point
group:getController():setTask({
  id = "Orbit",
  params = {
    pattern = "Circle",
    point = { x = point.x, y = point.z },
    altitude = 6000,
    speed = 220,
  },
})
```

## Notes

The task table's `id` is case-sensitive (`"Orbit"`, not `"orbit"`). Ground groups ignore air
tasks without an error.
