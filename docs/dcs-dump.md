# The `_G` dump

The reference data is extracted from a dump of DCS's Lua global table, `_G`
(`tools/datamine/hook/dump-globals.lua`), cached in `.datamine/_G/`: one Lua file per table, such as
`_G/weapons_table/weapons/missiles/AIM_120C.lua`. It is not committed; only the curated series are.

## sourcePaths

A record's `sourcePaths` are the dump files it was read from, without `.lua`: the AIM-120C weapon
has `["_G/rockets/AIM_120C", "_G/weapons_table/weapons/missiles/AIM_120C"]`. Joins use exact ids
only (`_unique_resource_name`, CLSID, unit `type`, sensor name). Ones that don't resolve are in
`manifest.json` under `dumpJoins`; on 2.9.30 that is `YJ-83` (its `_G/rockets` record has a
different wsType), the `M272` rack and two warheads.

Blocks of `weapon_flight` and `aircraft_flight` carry a `sourcePath` such as
`_G/weapons_table/weapons/missiles/AIM_120C#/client/fm`: the dump path, `#`, then the Lua keys
separated by `/`. String keys escape `~` as `~0`, `/` as `~1` and a leading `[` as `~2`; other
keys are written as Lua literals (`[1]`, `[true]`). `tools/datamine/dump_paths.py` resolves them,
and the extraction fails if one doesn't resolve in the dump.

## Dump format

`tools/datamine/hook/serialize.lua` writes numbers with the shortest decimal that reads back as
the same double, and writes functions, shared tables, cycles and redactions as `__dcs{...}`
markers instead of dropping them (dump format 4).

## Coverage

`task datamine:coverage` compares a dump with another (a previous DCS version) or with
[Quaggles' datamine](https://github.com/Quaggles/dcs-lua-datamine), and lists missing, added,
changed and unresolved paths. Known differences from Quaggles are in
`tools/datamine/coverage-explanations.yaml`; any other path it has and we lack fails the command.

```bash
task datamine:coverage -- diff .datamine/_G .datamine/_G.previous           # vs the previous dump
task datamine:coverage -- diff .datamine/_G --quaggles-ref 2.9.30.28536     # vs Quaggles
task datamine:coverage -- typed dcs-world-reference/latest                  # flight fields vs the dump
```
