# DCS hooks

GameGUI hooks `task datamine` (`tools/datamine/refresh.py`) installs in an isolated Saved Games
profile, one DCS run per pass.

| File | Purpose |
| --- | --- |
| `dump-globals.lua` | Walks `_G` (plus the Mission Editor's `U` tables), writes one file per table and `_G/__DCS_VERSION__.lua` last |
| `serialize.lua` | Deterministic Lua table serializer used by the hooks |
| `terrain-dump.lua` | Per-terrain pass: airbases, runways, stands, heights, magnetic variation |
| `api-dump.lua` | Lua API pass: scripting, hooks, server and export environments; state probe |
| `api-walk.lua` | API globals walker and JSON writer used by `api-dump.lua` |
| `api-probe.lua` | Argument probe (`--probe`): samples, deny list, resumable progress |
| `probe-call.lua` | Infers one function's arguments from its argument errors; its JSON encoder also serves the actions probe |
| `actions-probe.lua` | AI actions probe (`--actions-probe`): per step reset, apply, measure; dcs.log markers; resumable progress |
| `actions-probe-lib.lua` | The actions probe's controller calls and effect measures in the scripting state |
| `actions-probe-followup-lib.lua` | Follow-up additions appended to `actions-probe-lib.lua` (`--actions-probe-followup`): spawned step groups, shot and hit counts |

Each file's header specifies its output format; the extractors and `refresh.py` depend on it.
`../me-action-db.lua` is not a hook: `extract_actions.py` runs it under `lua5.1` on the install's
Mission Editor modules at extract time.
