# DCS World Schema

![CI Status](https://github.com/yolowingpixie/dcs-world-schema/actions/workflows/ci.yml/badge.svg)

YAML Representation of the DCS World Mission Scripting Environment's API Signature

## 📋 Overview

This project provides a comprehensive YAML-based schema definition for the DCS World API. The goal is to create a complete schema that can be used by LSP servers to provide extremely strict and detailed linting for DCS World mission scripting in Lua. Currently we support exporting the schema to [EmmyLua Annotations](https://emmylua.github.io/annotation.html) for use with existing Lua language servers like LuaLS.

Just an end user and want linting in your IDE? Go to [Using Pre-Built Releases](https://github.com/YoloWingPixie/dcs-world-schema/tree/main?tab=readme-ov-file#-using-pre-built-releases)

## ✨ Features

- Complete API signature definitions in YAML format
- Type checking for DCS functions, methods, and properties
- Schema validation tools
- JSON schema output for use with language servers
- EmmyLua annotations export for Lua editor integration

## 🚀 Using Pre-built Releases

For most users, the easiest way to use this project is to download the pre-built releases:

1. Go to the [Releases](https://github.com/yolowingpixie/dcs-world-schema/releases) page
2. Download the latest release
3. Extract the files to your desired location

Each release includes:
- `dcs-world-api-schema.json` - JSON schema for the DCS World API
- `dcs-world-api-schema.yaml` - YAML schema for the DCS World API
- `dcs-world-api.lua` - EmmyLua annotations for Lua editor integration  **<-- End Users: you probably only care about this**

### Using with Lua Editors

To use the EmmyLua annotations with your Lua editor:
1. Set up your editor to use EmmyLua annotation compatible LSP
2. Include the `dcs-world-api.lua` file in your project or configure your editor to reference it

#### VSCode
0. Install a popular Lua LSP extension like sumneko's Lua extension.
1. Create a `.vscode/settings.json` in your DCS World Lua project if it does not alreaady exist.
2. For LuaLS or sumeneko's Lua extension, or other popular Lua LSP for VSCode, all you should have to do is add the following to your `settings.json`:

```lua
{
    "Lua.workspace.library": [
        "$PATH_TO_YOUR_LUA_DIST_FILE_CHANGE_ME/dcs-world-api.lua",
    ]
}
```
3. Type checking, hover information, and autocomplete should now function in `.lua` files in VSCode

*Note*
For whatever reason, LuaLS marks all functions as deprecated despite not having the flag. This is a bug that I am working on fixing.
But you can disable that by adding the following to your `settings.json`:

```lua
{
    "Lua.workspace.library": [
        "$PATH_TO_YOUR_LUA_DIST_FILE_CHANGE_ME/dcs-world-api.lua",
    ],
    "Lua.diagnostics.disable": ["deprecated"]
}
```

### Future Features
Aspirationally, we would like to be able to provide, correct, valid packages for valdidating the DCS schema in the following languages natively:
- TypeScript definitions export for JavaScript/TypeScript development
- Go struct definitions for Go development
- Python type hints for Python development

The exporters for these languages exists in `/tools` at this time but a release process has not been formalized and the exports are not *great*.

The exporters can be used via `task build:golang`, `task build:python`, `task build:typscript` :

And they output as follows in `/dist`

- `dcs-world-api.d.ts` - TypeScript definitions for JavaScript/TypeScript development
- `dcs-world-api.go` - Go struct definitions for Go applications
- `dcs_world_api.py` - Python type hints for Python development

## 🛠️ Building From Source

If you need to build from source or want to contribute to the project:

1. Clone the repository:
   ```bash
   git clone https://github.com/yolowingpixie/dcs-world-schema.git
   cd dcs-world-schema
   ```

2. Install Task (if not already installed):
   This project uses [Task](https://taskfile.dev/) to run commands. Installation instructions are available at [taskfile.dev/installation](https://taskfile.dev/installation/).

3. Set up the environment:
   ```bash
   task setup
   ```

4. Generate all schema files and type definitions:
   ```bash
   task build
   ```

The generated files will be in the `dist/` directory.

## 📚 Project Structure

- `dcs-world-schema/` - Core schema files in YAML format
  - `globals/` - Global namespace definitions
  - `types/` - Type definitions
- `tools/` - Utilities for validation and building
- `dist/` - Generated schema files and exports
- `reference_data/` - DCS API reference data

## 🤝 Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for detailed development setup, workflow, and contribution guidelines.

## 📄 License

This project is licensed under [MIT](LICENSE.md).
