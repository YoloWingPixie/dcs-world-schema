#!/usr/bin/env python3
import argparse
import json
import os
import sys
from typing import Any, Dict, Set


# LUA primitive type mapping
TYPE_MAPPING = {
    "number": "number",
    "string": "string",
    "boolean": "boolean",
    "table": "table",
    "function": "fun(...)",
    "any": "any",
    "nil": "nil",
    "void": "nil",
}

# Track processed types to avoid duplicates
processed_types: Set[str] = set()


def load_schema(path: str) -> Dict[str, Any]:
    """Load the schema from a JSON file"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def sanitize_lua_name(name: str) -> str:
    """Make a name safe for Lua"""
    return name.replace(".", "_")


def map_type(type_str: str) -> str:
    """Map DCS schema type to Lua type annotation"""
    if not type_str:
        return "any"

    # Handle union types
    if "|" in type_str:
        types = [map_type(t.strip()) for t in type_str.split("|")]
        return "|".join(types)

    # Handle array types
    if type_str.endswith("[]"):
        base_type = type_str[:-2].strip()
        return f"{map_type(base_type)}[]"

    # Handle map types
    if type_str.startswith("map<") and type_str.endswith(">"):
        # Extract key and value types
        inner = type_str[4:-1].strip()
        # EmmyLua map notation
        return f"table<string, {map_type(inner)}>"

    # Handle primitive types
    if type_str in TYPE_MAPPING:
        return TYPE_MAPPING[type_str]

    # Reference to another type
    return type_str  # Keep original type reference


def format_description(desc: str, indent: str = "") -> str:
    """Format description as Lua comment"""
    if not desc:
        return ""

    lines = desc.split("\n")
    if len(lines) == 1:
        return f"{indent}--- {desc}\n"

    result = f"{indent}---\n"
    for line in lines:
        result += f"{indent}-- {line}\n"
    result += f"{indent}---\n"
    return result


def process_param(param):
    """Process a parameter into a LuaDoc param annotation"""
    name = param.get("name", "param")
    type_str = param.get("type", "any")
    # The description is actually processed by the caller in process_method
    # No need to extract it here

    # Special case for parameter names containing 'enum' or special characters
    if " enum" in name:
        name = name.replace(" enum", "")
    if "/" in name:
        name = name.replace("/", "_or_")  # Replace slashes with "_or_"

    # Special case for type strings containing 'enum'
    if isinstance(type_str, str) and "enum" in type_str:
        # Replace 'enum' with the actual type
        type_str = type_str.replace("enum ", "")

    lua_type = map_type(type_str)

    if lua_type:
        result = f"---@param {name} {lua_type}"
    else:
        result = f"---@param {name} any"

    return result


def process_enum(name: str, enum_def: Dict[str, Any]) -> str:
    """Process an enum into Lua annotation"""
    values = enum_def.get("values", [])
    desc = enum_def.get("description", "")

    result = format_description(desc)
    result += f"---@enum {name}\n"
    result += f"{name} = {{\n"

    # Handle different formats of enum values
    if isinstance(values, list):
        # List format
        for i, val in enumerate(values):
            if isinstance(val, str):
                # Clean key and use square bracket notation for keys with special characters
                if any(c in val for c in " -+/."):
                    result += f'    ["{val}"] = "{val}"'
                else:
                    result += f'    {val} = "{val}"'

                if i < len(values) - 1:
                    result += ","
                result += "\n"
    elif isinstance(values, dict):
        # Object format (key-value pairs)
        items = list(values.items())
        for i, (key, value) in enumerate(items):
            # Skip empty keys
            if not key:
                continue

            # Format value based on its type
            if isinstance(value, str):
                formatted_value = f'"{value}"'
            elif isinstance(value, (int, float)):
                formatted_value = str(value)
            else:
                formatted_value = f'"{key}"'  # Default fallback

            # Format the key correctly based on key type
            if isinstance(key, (int, float)):
                # Numeric keys use brackets in Lua
                result += f"    [{key}] = {formatted_value}"
            elif isinstance(key, str):
                if key.isdigit():
                    # String keys that are all digits should be treated as numbers
                    result += f"    [{key}] = {formatted_value}"
                elif any(c in key for c in " -+/."):
                    # String keys with special characters use quoted brackets
                    result += f'    ["{key}"] = {formatted_value}'
                else:
                    # Normal identifiers
                    result += f"    {key} = {formatted_value}"
            else:
                # Fallback
                result += f'    ["{key}"] = {formatted_value}'

            if i < len(items) - 1:
                result += ","
            result += "\n"
    elif isinstance(values, str):
        # Single string value
        if any(c in values for c in " -+/."):
            result += f'    ["{values}"] = "{values}"\n'
        else:
            result += f'    {values} = "{values}"\n'

    # Ensure there's at least one dummy value if the enum is empty to avoid syntax errors
    if not values:
        result += "    _EMPTY = 0\n"

    result += "}\n"
    return result


def process_type_definition(name: str, type_def: Dict[str, Any]) -> str:
    """Process a type into Lua class definition"""
    if name in processed_types:
        return ""

    processed_types.add(name)

    # Different handling based on type
    kind = type_def.get("kind", "")

    if kind == "enum":
        return process_enum(name, type_def)

    # For regular types, create a class
    desc = type_def.get("description", "")
    inherits = type_def.get("inherits", "")

    result = format_description(desc)
    result += f"---@class {name}"
    if inherits:
        result += f" : {inherits}"
    result += "\n"

    # Properties
    properties = type_def.get("properties", {})
    for prop_name, prop_def in properties.items():
        prop_type = prop_def.get("type", "any")
        prop_desc = prop_def.get("description", "")

        if prop_desc:
            result += format_description(prop_desc, "")

        # Handle list of types
        if isinstance(prop_type, list):
            # In EmmyLua, use the first type or join with |
            types = [map_type(t) for t in prop_type if isinstance(t, str)]
            type_str = "|".join(types) if types else "any"
            result += f"---@field {prop_name} {type_str}\n"
        else:
            result += f"---@field {prop_name} {map_type(prop_type)}\n"

    # Static properties
    static_props = type_def.get("static", {})
    for prop_name, prop_def in static_props.items():
        prop_type = prop_def.get("type", "any")
        prop_desc = prop_def.get("description", "")

        if prop_desc:
            result += format_description(prop_desc, "")

        # Handle list of types
        if isinstance(prop_type, list):
            # In EmmyLua, use the first type or join with |
            types = [map_type(t) for t in prop_type if isinstance(t, str)]
            type_str = "|".join(types) if types else "any"
            result += f"---@field {prop_name} {type_str}\n"
        else:
            result += f"---@field {prop_name} {map_type(prop_type)}\n"

    # Add placeholder
    result += f"{name} = {{}}\n\n"

    # Add methods
    instance_methods = type_def.get("instance", {})
    for method_name, method_def in instance_methods.items():
        result += process_method(name, method_name, method_def)

    return result


def process_method(
    class_name: str, method_name: str, method_def: Dict[str, Any]
) -> str:
    """Process a method into Lua function definition"""
    params = method_def.get("params", [])
    returns = method_def.get("returns", "void")
    desc = method_def.get("description", "")

    # Format description
    result = format_description(desc)

    # Add parameter documentation
    for param in params:
        param_desc = param.get("description", "")

        result += process_param(param)
        if param_desc:
            result += f" {param_desc}"
        result += "\n"

    # Add return documentation
    if returns and returns != "void":
        if isinstance(returns, list):
            # For multiple return values in Lua, we document each one separately
            # Each @return annotation documents one return value
            for i, rt in enumerate(returns):
                if isinstance(rt, str) and rt != "void":
                    result += f"---@return {map_type(rt)}"
                    # Add comment to indicate return value position if there are multiple
                    if len(returns) > 1:
                        result += f" # Return value {i + 1}"
                    result += "\n"
        else:
            result += f"---@return {map_type(returns)}\n"

    # Add function definition
    # Handle parameters with Lua reserved keywords or special characters
    param_list = []
    for i, p in enumerate(params):
        param_name = p.get("name", f"p{i}")

        # Handle parameter names with spaces, slashes, and reserved words
        if " enum" in param_name:
            param_name = param_name.replace(" enum", "")
        if "/" in param_name:
            param_name = param_name.replace("/", "_or_")  # Replace slashes with "_or_"

        # Handle problematic parameter types with 'enum' or other keywords
        if isinstance(param_name, str) and param_name == "enum":
            param_name = "_enum"

        # Sanitize any parameter name that's a Lua keyword or contains special characters
        if param_name in [
            "end",
            "function",
            "if",
            "else",
            "then",
            "local",
            "and",
            "or",
            "not",
            "type",
            "repeat",
        ]:
            param_name = f"_{param_name}"

        param_list.append(param_name)

    result += f"function {class_name}:{method_name}({', '.join(param_list)}) end\n\n"

    return result


def process_global(name: str, global_def: Dict[str, Any]) -> str:
    """Process a global namespace into Lua"""
    desc = global_def.get("description", "")

    result = format_description(desc)
    result += f"---@class {name}\n"

    # Properties
    properties = global_def.get("properties", {})
    for prop_name, prop_def in properties.items():
        prop_type = prop_def.get("type", "any")
        prop_desc = prop_def.get("description", "")

        if prop_desc:
            result += format_description(prop_desc, "")

        # Handle list of types
        if isinstance(prop_type, list):
            types = [map_type(t) for t in prop_type if isinstance(t, str)]
            type_str = "|".join(types) if types else "any"
            result += f"---@field {prop_name} {type_str}\n"
        else:
            result += f"---@field {prop_name} {map_type(prop_type)}\n"

    # Static properties (same as properties for globals)
    static_props = global_def.get("static", {})
    for prop_name, prop_def in static_props.items():
        prop_type = prop_def.get("type", "any")
        prop_desc = prop_def.get("description", "")

        if prop_desc:
            result += format_description(prop_desc, "")

        # Handle list of types
        if isinstance(prop_type, list):
            types = [map_type(t) for t in prop_type if isinstance(t, str)]
            type_str = "|".join(types) if types else "any"
            result += f"---@field {prop_name} {type_str}\n"
        else:
            result += f"---@field {prop_name} {map_type(prop_type)}\n"

    # Add global declaration
    result += f"{name} = {{}}\n\n"

    # Add methods
    instance_methods = global_def.get("instance", {})
    for method_name, method_def in instance_methods.items():
        result += process_method(name, method_name, method_def)

    return result


def export_to_lua(schema: Dict[str, Any], output_path: str) -> None:
    """Export schema to Lua EmmyLua annotations"""
    output_dir = os.path.dirname(output_path)
    os.makedirs(output_dir, exist_ok=True)

    output = [
        "--[[ DCS World Lua Type Definitions",
        "Generated from DCS World Schema",
        "DO NOT MODIFY - AUTO-GENERATED FILE",
        "--]]",
        "",
        "---@meta",
        "",
    ]

    # Process standalone types first
    if "types" in schema:
        output.append("-- Type Definitions")
        for type_name, type_def in sorted(schema["types"].items()):
            # Skip namespace types for now
            if "." in type_name:
                continue

            type_definition = process_type_definition(type_name, type_def)
            if type_definition:
                output.append(type_definition)

    # Process globals
    if "globals" in schema:
        output.append("-- Global Namespaces")
        for global_name, global_def in sorted(schema["globals"].items()):
            output.append(process_global(global_name, global_def))

    # Process namespace types
    if "types" in schema:
        output.append("-- Namespace Types")
        for type_name, type_def in sorted(schema["types"].items()):
            if "." in type_name and type_name not in processed_types:
                output.append(process_type_definition(type_name, type_def))

    # Write to file
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(output))

    print(f"Lua type definitions exported to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Export DCS schema to Lua EmmyLua annotations"
    )
    parser.add_argument("schema", help="Path to the DCS schema JSON file")
    parser.add_argument(
        "--output",
        "-o",
        default="dist/dcs-world-api.lua",
        help="Output Lua definition file (default: dist/dcs-world-api.lua)",
    )

    args = parser.parse_args()

    try:
        schema = load_schema(args.schema)
        export_to_lua(schema, args.output)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
