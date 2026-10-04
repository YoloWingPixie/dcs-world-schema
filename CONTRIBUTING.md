# Contributing

```bash
task setup                         # install uv if missing, sync dependencies
task validate:file -- <path>       # after editing a YAML file
task ci                            # before opening a PR; CI runs the same
```

Branch from `main`. `task --list` describes every task.

## Tasks

| Task | What it does |
| --- | --- |
| `validate` | Validate `dcs-world-schema/` against `dcs_yaml_schema.yaml` |
| `merge` | Merge the YAML into `dist/dcs-world-api-schema.{json,yaml}` |
| `validate-types` | Missing, duplicate and unused types in the merged schema |
| `verify` | Compare the merged schema with `dcs-world-reference/latest/api/scripting.json` and its argument probe |
| `check-enums` | Enums against DCS: scripting API tables, constant families, Mission Editor values, `AI.Option` tables (`tools/datamine/check_enums.py`, known gaps in `ALLOWED`) |
| `test:luals` | `dist/dcs-world-api.lua` in a pinned LuaLS against the fixtures in `tools/luals/` |
| `build` | All exports (`build:lua`, `:selene`, `:typescript`, `:golang`, `:python`, `:jsonschema`, `:envs`) |
| `validate-data` | Validate `dcs-world-reference/latest/` and its cross-references |
| `test` | Datamine and packaging unit tests |
| `fmt:py` | ruff lint and format check (`fmt:py:fix` applies fixes) |
| `lint` | `fmt:py`, mypy, selene and the schema conventions below (`lint:schema`) |
| `coverage` | `test` with branch coverage of `tools/` |
| `package`, `package:test` | Build and test the reference-data packages |
| `package:vectors` | Regenerate the helper conformance vectors from the Python package |
| `ci` | From a clean `dist/`: the checks above, the four `datamine:*:check` tasks and `package:test`; fails if `package.json` or `pyproject.toml` changed |
| `datamine` | Refresh `dcs-world-reference` from a DCS install (not in `ci`) |
| `datamine:extract` | Re-extract from the cached dumps without DCS |
| `datamine:dcs-database-types`, `datamine:api-schema`, `datamine:action-types`, `datamine:id-types` | Regenerate `types/dcs-database/`, `globals/{hooks,server,export}/`, `types/ai/` and `types/ids/` (`:check` variants run in `ci`) |
| `datamine:coverage` | Diff a dump against another, or against Quaggles' datamine ([docs/dcs-dump.md](docs/dcs-dump.md#coverage)) |
| `datamine:actions` | Print the Mission Editor actions/options extraction without writing |
| `datamine:probe:plan`, `datamine:actions-probe:plan` | Show what the argument or actions probe would run |

## Schema conventions

- DCS global namespace types use dot notation (`Unit`, `AI.Option`); types this project adds for
  table shapes use PascalCase (`EventHandlerTable`).
- No bare `table` type: add a shared type under `dcs-world-schema/types/` and reference it by
  full name.
- No comments in schema YAML.
- Descriptions are sentences: they don't start lowercase and end with a period.
- Entity fields are camelCase. A number field with a unit carries it as a suffix (`massKg`,
  `lengthM`, `rangeKm`, `speedMs` for m/s, `timeS`, `bearingDeg`, `frequencyHz`) and its
  description, or its type's, names the unit; raw DCS values and coordinates keep plain names.
- `task lint:schema` checks these.
- `*.generated*.yaml` and `types/country.enum.yaml` are generated from DCS; don't edit them.

## Reference data

- `dcs-world-reference/` is generated: change the extractors in `tools/datamine/` or
  `tools/datamine/overlays.yaml` (format in its header; every entry needs `note` and `evidence`).
- It holds only `latest/`, the newest DCS version's data. `task datamine` replaces it on a new
  version; earlier versions are in git history.
- A field holding ids of other records declares their type with `ref` (`ref: Entity.Weapon`, or a
  union `"Entity.Aircraft | Entity.GroundVehicle"`).
- A curated field is added only when its meaning is known; the rest stays in the `_G` dump
  ([docs/dcs-dump.md](docs/dcs-dump.md)).
- After a DCS patch, check what changed against the previous version's records before committing:

  ```bash
  cp -r .datamine/_G .datamine/_G.previous          # the previous version's dump
  task datamine
  task datamine:coverage -- diff .datamine/_G .datamine/_G.previous
  task datamine:coverage -- diff .datamine/_G --quaggles-ref <dcs version>
  task datamine:coverage -- typed dcs-world-reference/latest
  task validate-data
  ```
- Extractor rules are in each module's docstring; the DCS hooks are described in
  [tools/datamine/hook/README.md](tools/datamine/hook/README.md).

## Releases

Add user-visible changes to `CHANGELOG.md` under `[Unreleased]`. To release, bump `VERSION`, run
`task package` (syncs package versions) and move `[Unreleased]` to `## [<version>] - <YYYY-MM-DD>`.
On `main`, CD tags `v<version>` and `packages/go/v<version>` and publishes a GitHub release with
that section as notes.
