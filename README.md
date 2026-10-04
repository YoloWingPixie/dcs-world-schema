# DCS World Schema

![CI](https://github.com/YoloWingPixie/dcs-world-schema/actions/workflows/ci.yml/badge.svg)

A YAML schema of the DCS World Lua API, compiled to editor annotations and type definitions, and
reference data (units, weapons, airbases, ...) extracted from a DCS install.

## Outputs

`task build` writes to `dist/`. Released files are attached to each
[GitHub release](https://github.com/YoloWingPixie/dcs-world-schema/releases), with the
[packages](#packages).

| File | Contents | Released |
| --- | --- | --- |
| `dcs-world-api-schema.json`, `.yaml` | Merged mission scripting schema | yes |
| `dcs-world-api.lua` | [EmmyLua](https://emmylua.github.io/annotation.html) annotations for LuaLS | yes |
| `dcs-world-selene.yml` | [Selene](https://kampfkarren.github.io/selene/) standard library (extends `lua51`) | yes |
| `dcs-world-api.d.ts`, `dcs-world-api.go`, `dcs_world_api.py` | TypeScript, Go, Python definitions (experimental) | yes |
| `dcs-world-api-<env>-schema.json`, `.lua`, `.d.ts` | `hooks` and `export` environments | yes |
| `dcs-world-entities.schema.json` | JSON Schema of the `Entity.*` reference-data types | yes |
| `schemas/<series>.schema.json` | The same, one file per series (editor validation) | no |

LuaLS (`.vscode/settings.json`):

```json
{ "Lua.workspace.library": ["/path/to/dcs-world-api.lua"] }
```

Selene: put `dcs-world-selene.yml` next to `selene.toml` and set `std = "dcs-world-selene"`.

## Reference data

`latest/` holds the newest DCS version's data (`manifest.json` names the version); earlier
versions are in git history.

```
dcs-world-reference/latest/
  manifest.json                     # DCS version, extraction time, modules
  api/<env>.json                    # Lua API dump: scripting, hooks, server, export
  api/states.json                   # net.dostring_in states
  api/export.docs.json              # Lo* docs from Scripts/Export.lua
  api/probe.json                    # argument probe (--probe)
  api/actions-probe.json            # AI actions probe (--actions-probe)
  api/actions-probe-followup.json   # follow-up probe (--actions-probe-followup), when run
  <series>/<id>.json                # one record per entity
  airbases/<theatre>/<name>.json
  beacons/<theatre>/<typeName>/<beaconId>.json
```

Series: `aircraft`, `ground_vehicles`, `personnel`, `ships`, `structures`, `sensors`, `radios`,
`datalink`, `weapons`, `weapon_flight`, `aircraft_flight`, `warheads`, `stores`, `racks`, `gun_ammo`, `fuzes`,
`attributes`, `countries`, `callsigns`, `formations`, `tasks`, `skills`, `actions`, `options`, `threats`, `liveries`,
`theatres`, `beacons`, `navaids`, `airbases`. Each is an `Entity.*` type in
`dcs-world-schema/types/entities/`. File names are the DCS id made safe for Windows file systems;
the record carries the true id. Hand-authored facts are in `tools/datamine/overlays.yaml`.

`weapon_flight` holds each weapon's flight model, motor stages, autopilot, seeker and fuze
([docs/weapon-flight.md](docs/weapon-flight.md)); `aircraft_flight` each aircraft's AI flight
model (`SFM_Data`, helicopter rotor and engine keys). Records list the `_G` dump files they were
read from in `sourcePaths`; keys without a field are only in the dump ([docs/dcs-dump.md](docs/dcs-dump.md)).

A version extracted without its own probe run carries the previous version's probe results
forward, marked `probedOn: <version>` (in `api/probe.json`, `api/actions-probe.json` and each
`actions` record).

`task validate-data` checks `latest/` against the entity JSON Schema and resolves
cross-references (fields with `ref`). `.vscode/settings.json`
maps the record files to `dist/schemas/` for validation and hover docs in VS Code.

### AI tasks

`actions` and `options` hold every Mission Editor AI task, en-route task, command and option.
From them, `task datamine:action-types` generates the `DcsTask.*` types in
`dcs-world-schema/types/ai/`, keyed by DCS's ids (`DcsTask.Task.Orbit`, `DcsTask.Command.SetFrequency`).
Their `id` fields are literal types, so `{ id: 'orbit' }` is a type error; DCS ignores or rejects
ids in other casings (`api/actions-probe.json`). `Controller.setTask` takes
`DcsTask.AnyTask | DcsTask.AnyEnrouteTask | DcsTask.WrappedAction | ComboTask | ControlledTask | Mission`.

### Refreshing

Needs Windows with WSL, a DCS install and a Saved Games profile you have logged in with. Runs DCS
headless through [dcs-headless](https://github.com/YoloWingPixie/dcs-headless) in an isolated
`DCS.datamine` profile; a DCS process it did not start is left alone and the run stops.

```bash
task datamine                                   # dump _G, the Lua APIs and each terrain; extract, validate, install
task datamine -- --force                        # re-extract an existing version
task datamine -- --probe                        # also run the Lua API argument probe
task datamine -- --actions-probe                # also run the live AI actions probe
task datamine -- --actions-probe-followup       # also run its follow-up plan
task datamine -- --install-dir DIR --auth-from DIR
task datamine:extract -- --install-dir DIR      # re-extract from the cached dumps in .datamine/
task datamine:probe:plan                        # what --probe would call, without DCS
task datamine:actions-probe:plan                # what --actions-probe would run (-- --followup: the follow-up)
```

Each DCS pass is cached in `.datamine/` per DCS version; a rerun resumes. Nothing is written
unless validation passes. `--install-dir` of `datamine:extract` defaults to `$DCS_INSTALL_DIR`.
`--probe-restarts N` and `--probe-stall S` bound the probes' crash restarts and hang detection.

## Packages

`task package` bundles `dcs-world-reference/latest/` into `dist/reference/<series>.json`, with the
reverse-reference, name and lookup indexes the helpers use in `dist/reference/_index/`, and builds:

| Package | Source | Output |
| --- | --- | --- |
| npm `dcs-world-reference` ([README](packages/typescript/README.md)) | `packages/typescript/` | `dist/dcs-world-reference-<version>.tgz` |
| Python `dcs-world-reference` ([README](packages/python/README.md)) | `packages/python/` | `dist/dcs_world_reference-<version>-py3-none-any.whl`, `.tar.gz` |
| Lua 5.1 / DCS ([README](packages/lua/README.md)) | `packages/lua/` | `dist/dcs-world-reference-lua-<version>-dcs<dcs version>.zip` |
| Go `dcsref` ([README](packages/go/README.md)) | `packages/go/` | generated files in `packages/go/`, committed on release tags |
| SQLite | `tools/package/sqlite.py` | `dist/dcs-world-reference-<version>-dcs<dcs version>.sqlite` |

Records are keyed by id (`clsid` for `stores`). The package version is `VERSION`; the DCS version
is in each package's metadata. Every output but the Go module is attached to each GitHub release
(the Go module is fetched with `go get` at the release tag); nothing is published to npm, PyPI or
LuaRocks. Install a release file with `npm install <file>.tgz` or `pip install <file>.whl`. For
DCS, unzip the Lua zip into `Saved Games/DCS/Scripts/` and load it with `dofile`: from a mission,
`dofile([[C:\Users\<you>\Saved Games\DCS\Scripts\dcs_world_reference\init.lua]])` (no `lfs`
there); from a hook, `dofile(lfs.writedir() .. "Scripts/dcs_world_reference/init.lua")`. Recipes:
[`docs/cookbook.md`](docs/cookbook.md).

## Building

Requires Python 3.12, [uv](https://docs.astral.sh/uv/) and [Task](https://taskfile.dev/);
`task package` and `task ci` also need Node >= 20.10, Go >= 1.24 and `lua5.1` (Lua tests are
skipped without it).

```bash
task setup     # install uv if missing, sync dependencies
task build     # dist/
task package   # reference-data packages
task ci        # every check CI runs
task --list    # all tasks
```

## Layout

| Path | Contents |
| --- | --- |
| `dcs-world-schema/globals/` | Mission scripting globals; `hooks/`, `export/` generated from the API dump |
| `dcs-world-schema/types/` | Types; `entities/` reference-data types (`Entity.*`) |
| `dcs-world-schema/types/ai/` | `DcsTask.*`: AI tasks, commands and options, generated from `actions`/`options` |
| `dcs-world-schema/types/ids/` | `DcsId.*`: DCS's ids (unit, weapon and sensor types, airbases, attributes, ...) for completion, generated from the series |
| `dcs-world-schema/types/dcs-database/` | `DcsDb.*`: DCS's internal database tables (`db.Units`, `weapons_table`, `launcher`, ...), inferred from a `_G` dump, not exported to `dist/`; for reference data use `Entity.*` |
| `dcs_yaml_schema.yaml` | Schema of the YAML source files |
| `tools/` | Merge, validation and exporters; `datamine/` extraction; `package/` packaging |
| `packages/` | Reference-data packages |
| `dcs-world-reference/latest/` | The newest DCS version's data, one JSON file per record, by series; earlier versions are in git history |
| `.../aircraft/`, `ground_vehicles/`, `ships/`, `structures/` | Units: stations, sensors, radios, attributes |
| `.../weapons/`, `stores/`, `warheads/` | Weapons, the stores that carry them (by CLSID) and their warheads |
| `.../weapon_flight/` | Weapon flight models, motors, autopilots, seekers and fuzes |
| `.../aircraft_flight/` | Aircraft AI flight models (`SFM_Data`, helicopter rotor and engine) |
| `.../airbases/<theatre>/`, `beacons/<theatre>/` | Airbases (runways, parking stands, ATC frequencies and callsigns) and beacons per map |
| `.../actions/`, `options/` | AI tasks, commands and options; source of `DcsTask.*` |
| `.../api/` | API dumps of each Lua environment and the probe results |
| `.../manifest.json` | DCS version, counts and provenance |

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Credits

`Disposition` descriptions and parameters by [@WirtLegs](https://github.com/WirtLegs) ([#11](https://github.com/YoloWingPixie/dcs-world-schema/issues/11)).

## License

The schema, tooling and packages are [MIT](LICENSE). The data in `dcs-world-reference/` is extracted from a DCS World install; DCS World and its content are the property of Eagle Dynamics SA and the respective module developers. This project is not affiliated with or endorsed by Eagle Dynamics.
