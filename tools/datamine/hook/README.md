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

The `_G` dump is format 4 (`DUMP_FORMAT` in `dump-globals.lua`, also written to
`_G/__DUMP_FORMAT__.lua`). It keeps what format 3 dropped:

- Exact numbers (shortest decimal that reads back as the same double; format 3 used `%.14g`).
- `__dcs{kind=...}` markers instead of `nil` for functions, userdata, threads, NaN, ±inf
  and `-0`; tables shared within a file are written once (`anchor`) and referenced after
  (`ref`), cycles included; limits write `truncated` markers; the patch-volatile wsType
  level-4 ids are `redacted` markers. A loader must define `__dcs`.
- Numeric record keys (`_G["db"]["Units"]["Cars"]["Car"][12]`), except keys that are
  the record's own level-4 id, still `"#Index"`.
- More object tables (`SchemeFMParameters`, `resource_by_unique_name` as a path index,
  cluster `*_DATA`, damage cells, ...) and `_G/__inheritance__.lua` (GT_t proxy linkage).

`serialize.lua` writes format 4 only with `lossless = true`; `terrain-dump.lua` and
`../me-action-db.lua` keep the format-3 rules. `../tests/fixtures/dump_format4/` is a small
hook-written format-4 tree for reader tests (`test_hook.py` keeps it in sync;
`DCS_UPDATE_FIXTURES=1` rewrites it).
`../me-action-db.lua` is not a hook: `extract_actions.py` runs it under `lua5.1` on the install's
Mission Editor modules at extract time.
