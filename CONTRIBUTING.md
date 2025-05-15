# Contributing to DCS World Schema

Thank you for your interest in contributing to the DCS World Schema project! This document provides guidelines and instructions for contributing to this project.

## 🛠️ Development Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/yolowingpixie/dcs-world-schema.git
   cd dcs-world-schema
   ```

2. Install Task (if not already installed):
   This project uses [Task](https://taskfile.dev/) to run commands. If you don't have it installed yet, follow the instructions at [taskfile.dev/installation](https://taskfile.dev/installation/).

3. Set up the environment (installs uv and syncs dependencies):
   ```bash
   task setup
   ```

## 📝 Development Commands

This project uses [Task](https://taskfile.dev/) to manage all commands. **Always use the task commands instead of running scripts directly**, as the task commands ensure proper environment setup and dependencies.

### Schema Validation

```bash
task validate
```

The validation process checks that all YAML schema files follow the correct format and structure as defined by `./dcs_yaml_schema.yaml`

**What it does**: 
- Verifies that each YAML file conforms to the schema specification
- Checks for syntax errors, formatting issues, and structural problems
- Validates that references between types are consistent

To validate a specific file:
```bash
task validate:file -- path/to/file.yaml
```

### Type Validation

```bash
task validate-types
```

 Type validation ensures that all referenced types in the schema actually exist and are properly defined. This prevents "ghost references" to non-existent types that would cause problems for language servers and IDEs.

**What it does**:
- Cross-references all type declarations across the entire schema
- Verifies that every referenced type is properly defined
- Checks for circular dependencies or inheritance issues
- Ensures consistent type naming throughout the schema

### API Verification

```bash
task verify
```

This critical step compares our schema against the actual DCS World API to ensure complete fidelity. Without this verification, our schema might diverge from the real API and cause incorrect linting or completions in editors.

**What it does**:
- Compares the merged schema against a reference dump of the actual DCS World API
- Identifies missing functions, methods, or properties
- Highlights structural differences between our schema and the actual API
- Ensures our schema correctly matches the DCS World environment

### Building the Schema

Generate both JSON and YAML schemas:
```bash
task merge
```

Generate only JSON schema:
```bash
task merge:json
```

Generate only YAML schema:
```bash
task merge:yaml
```

### Generating Type Definitions

Generate all export formats:
```bash
task build
```

Generate EmmyLua annotations:
```bash
task build:lua
```

Generate TypeScript definitions:
```bash
task build:typescript
```

Generate Go struct definitions:
```bash
task build:golang
```

### Complete CI Pipeline

Run the complete validation pipeline:
```bash
task ci
```

## 🧪 Development Workflow

When working with this project:

1. Fork the repository and create a new branch for your feature or bug fix
2. Create or modify type definitions in the appropriate YAML files
3. Validate the specific file with `task validate:file -- path/to/file.yaml`
4. Run `task validate-types` to ensure all type references are valid
5. Run `task verify` to ensure the schema matches the DCS API
6. Generate exports with `task build`
7. Submit a PR for review

## ⚠️ Important Notes

- Always validate your changes before committing. The CI pipeline will reject PRs that don't pass validation.
- The validation process is designed to catch common issues early, saving time in the review process.

## 📚 Project Structure

- `dcs-world-schema/` - Core schema files in YAML format
  - `globals/` - Global namespace definitions
  - `types/` - Type definitions
- `tools/` - Utilities for validation and building
  - `export_lua.py` - Tool for generating EmmyLua annotations (don't call directly, use `task build:lua`)
  - `export_typescript.py` - Tool for generating TypeScript definitions (don't call directly, use `task build:typescript`)
  - `export_golang.py` - Tool for generating Go struct definitions (don't call directly, use `task build:golang`)
  - `validate.py` - Schema validation (don't call directly, use `task validate`)
  - `verify.py` - API verification (don't call directly, use `task verify`)
- `dist/` - Generated schema files and exports
  - `dcs-world-api.lua` - EmmyLua annotations for Lua editor integration
  - `dcs-world-api.d.ts` - TypeScript definitions for JS/TS development
  - `dcs-world-api.go` - Go struct definitions for Go applications
- `reference_data/` - DCS API reference data

## 🔍 Working with Language Exporters

### Lua Exporter

The Lua exporter (`export_lua.py`) generates EmmyLua annotations for DCS World API. The annotations follow the EmmyLua format, which provides type hinting and autocompletion in editors like VSCode with the Lua Language Server.

When working with the Lua exporter:
- Annotations use the `---@class` and `---@field` syntax for types
- Function parameters use `---@param` annotations
- Return types use `---@return` annotations

### TypeScript Exporter

The TypeScript exporter (`export_typescript.py`) generates TypeScript definition files (`.d.ts`) that can be used with TypeScript or JavaScript projects

When working with the TypeScript exporter:
- Enums are converted to TypeScript enum declarations
- Objects are converted to interfaces
- Methods are properly typed with parameters and return types
- Namespace relationships are preserved

### Go Exporter

The Go exporter (`export_golang.py`) generates Go struct definitions for working with DCS World API data in Go applications. The exporter:

1. Converts DCS types to appropriate Go types:
   - `number` → `float64`
   - `string` → `string`
   - `boolean` → `bool`
   - `table` → `map[string]interface{}`
   - etc.

2. Handles special cases:
   - Array types (`Type[]`) → Go slices (`[]Type`)
   - Namespaced types (`Namespace.Type`) → CamelCase Go types (`NamespaceType`)
   - Enum types → Go string constants with type safety
   - Union types → `interface{}` in Go

3. Generates struct definitions with JSON tags for marshaling/unmarshaling

When working with the Go exporter, remember that:
- Go doesn't have direct equivalents for some Lua concepts (like metatables)
- The generated structs are intended for data representation, not execution
- Method implementations are stubs that panic with "Not implemented"

## 📋 Contribution Guidelines

Please make sure to follow these guidelines when contributing:

1. Follow the naming conventions:
   - Use dot notation for types that appear in the global namespace in DCS World's Lua environment
   - Use PascalCase for types that are not in the global namespace that this project uses to represent specific table structures

2. Avoid using primitive `table` type:
   - Instead, create a shared type in `/dcs-world-schema/types` and use that
   - This helps ensure strict and detailed linting

3. Code quality:
   - Always validate your changes before submitting
   - Delete comments from YAML files
   - Follow the style used in existing files

4. When using types:
   - Simply use the type name, like it is defined
   - For example, if you have a type called `MyType` in the global namespace, use it as `MyType`
   - If you have a type called `MyNamespace.MyType`, use it as `MyNamespace.MyType`
   - The merge tool will handle dereferencing the type for you

5. Validation workflow:
   - Always run `task validate:file` on files you modify
   - Run `task validate-types` to ensure all type references are valid
   - Run `task verify` to ensure that your changes maintain compatibility with the DCS API
   - All three validation steps must pass before submitting a PR

## 🔄 Pull Request Process

1. Ensure your code follows the contribution guidelines above
2. Update documentation if necessary
3. The PR should work in the CI pipeline
4. Once approved, a maintainer will merge your PR 