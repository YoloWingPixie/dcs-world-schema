# Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
