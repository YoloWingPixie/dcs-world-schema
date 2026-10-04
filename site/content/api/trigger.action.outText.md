---
seeAlso:
  - trigger.action.outTextForCoalition
  - trigger.action.outTextForGroup
  - trigger.action.outTextForUnit
---

## Example

Show a ten-second message to everyone, replacing what is on screen:

```lua
trigger.action.outText("Bandits, bullseye 090 for 30", 10, true)
```

## Notes

- `displayTime` is in seconds. Messages stack top to bottom unless `clearview` is `true`.
- Use `\n` for line breaks; long single lines are not wrapped.
