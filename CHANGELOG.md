# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.2] - 2025-05-24

### Added

- `EventHandlerTable` type definition to properly represent the expected table structure with onEvent method

### Fixed
- Fixed `world.addEventHandler()` and `world.removeEventHandler()` to accept EventHandlerTable instead of function parameter (#13)

## [0.3.1]

### Added

- `Disposition` singleton

## [0.3.0]
Initial Public Release

- Initial DCS World API schema definition
- Comprehensive type definitions for DCS World Lua scripting environment
- Event system type definitions and enumerations
- Unit, Group, Airbase, and other core DCS objects
- Mission scripting environment types
- Validation and verification tooling

[unreleased]: https://github.com/YourUsername/dcs-world-schema/compare/v0.3.2...HEAD
[0.3.2]: https://github.com/YourUsername/dcs-world-schema/releases/tag/v0.3.2 
