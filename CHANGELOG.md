# Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- SQLite: `schema_types` (every entity type with its fields), `ref_paths` (every reference), a `search` table with an FTS5 index, and the Lua API (`api_symbols`, `api_type_uses`).
- Reference site in `site/`: search, record pages, compare and the Lua API, read live from the SQLite in the browser.

### Changed
- Breaking: `weapon_flight.launchTables` is replaced by `launchEnvelopes`: maximum and minimum launch range (m) and aspect (deg) by launch altitude (m) and true airspeed (m/s).

## [0.5.0] - 2026-10-04

### Added
- `weapon_flight` series: each weapon's flight model (`Cx0`, `CxB`, `K1`, `K2`, `Cya`, trim tables...), motor stages, autopilot, seeker, gimbal, proximity fuze, `PN_coeffs` and launch range tables.
- `aircraft_flight` series: each aircraft's AI flight model (`SFM_Data` aerodynamics and engine tables, helicopter rotor and engine keys).
- More fields read from the DCS unit, sensor and shell tables on aircraft, ground units, ships, structures, sensors and gun ammo (mobility, chassis, launchers, detection tables, ballistics...).
- `sourcePaths` on records: the `_G` dump files each was read from.
- `task datamine:coverage`: diff dumps against each other or Quaggles' datamine.

### Changed
- Numbers are exact: the dump no longer rounds to 14 significant digits (`3.1415926535898` is now `3.141592653589793`). Values in 198 existing fields change in their last digits.
- The dump keeps functions, shared tables, cycles and numeric keys it used to drop or rename.
- A unit type DCS defines twice is reported instead of the later record replacing the earlier.

## [0.4.0] - 2026-10-01

### Added
- Reference data from DCS 2.9.30 (units, weapons, stores, sensors, radios, airbases, beacons, liveries and more) as Lua, npm, Python, Go and SQLite packages, attached to releases.
- `DcsId.*`: completion for DCS ids (unit, weapon and sensor types, airbases, attributes, tasks, skills, formations).
- `DcsTask.*`: typed AI tasks, en-route tasks, commands and options with their DCS ids.
- Annotations for the hooks (`dcs-world-api-hooks.lua`) and Export (`dcs-world-api-export.lua`) environments.
- TypeScript, Go and Python API definitions and the entity JSON Schema are attached to releases.
- `Unit.isAlive`, `isBroken`, `isDead`, `isEffective`, `trigger.action.userEvent`, `coalition.RED`/`BLUE`/`NEUTRAL`, the `radio` global and new `world.event`/`AI.Option` values.

### Changed
- Breaking: task, en-route task and command ids are PascalCase (`Orbit`, `EngageTargets`), as DCS requires.
- Breaking: ids and enums are typed where the API takes them (`getTypeName`, `getDescByName`, `hasAttribute`, `Airbase.getByName`, spawn data, task parameters); `DcsId.Attribute` replaces `Attributes`.
- Breaking: enums that are not DCS globals (`MarkupLineType`, `BeaconType`, ...) are types only, not tables.
- `country.id` keys `Argentina`, `Cyprus`, `Slovenia` are `ARGENTINA`, `CYPRUS`, `SLOVENIA`.

### Fixed
- `country.name` is keyed by country id (#22).
- LuaLS no longer marks every function deprecated.
- `trigger.action`, `trigger.misc` and `world.weather` functions are in `dcs-world-api.lua`.
- `BeaconType`, `BeaconSystemName`, `AI.Skill`, `world.BirthPlace` and `RadioModulation` values match DCS.
- The Go export compiles; the Python export includes all of `env` and `land`.

### Removed
- Hand-written `Task*`, `Command*`, `WrappedAction`, `FormationType` and related types, replaced by `DcsTask.*`.

## [0.3.5] - 2025-09-27

### Added
- Selene standard library export, `dist/dcs-world-selene.yml` (`task build:selene`).

## [0.3.4] - 2025-05-25

### Fixed
- `env.info`, `env.error`, `env.warning`: `showMessageBox` is optional (#17).

## [0.3.3] - 2025-05-24

### Fixed
- `coalition.addStaticObject()` takes no `coalition.side` parameter; DCS infers it from the country (#14).
- `coalition.addStaticObject()` returns `StaticObject`, not `function`.

## [0.3.2] - 2025-05-24

### Added

- `EventHandlerTable` type: a table with an `onEvent` method.

### Fixed
- `world.addEventHandler()` and `world.removeEventHandler()` take an `EventHandlerTable`, not a function (#13).

## [0.3.1]

### Added

- `Disposition` singleton

## [0.3.0]

Initial public release.

- Mission scripting API schema: core objects (Unit, Group, Airbase, ...), events and enums.
- Validation and verification tooling.

[unreleased]: https://github.com/YoloWingPixie/dcs-world-schema/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/YoloWingPixie/dcs-world-schema/releases/tag/v0.4.0
[0.3.5]: https://github.com/YoloWingPixie/dcs-world-schema/releases/tag/v0.3.5
[0.3.4]: https://github.com/YoloWingPixie/dcs-world-schema/releases/tag/v0.3.4
[0.3.3]: https://github.com/YoloWingPixie/dcs-world-schema/releases/tag/v0.3.3
[0.3.2]: https://github.com/YoloWingPixie/dcs-world-schema/releases/tag/v0.3.2
[0.3.1]: https://github.com/YoloWingPixie/dcs-world-schema/releases/tag/v0.3.1
[0.3.0]: https://github.com/YoloWingPixie/dcs-world-schema/releases/tag/v0.3.0
