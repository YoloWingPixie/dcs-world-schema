#!/usr/bin/env python3
import argparse
import json
import os
import sys
import re
from typing import Any, Dict, List, Optional, Set

# Go type mapping
TYPE_MAPPING = {
    "number": "float64",
    "string": "string",
    "boolean": "bool",
    "table": "map[string]interface{}",
    "function": "func(...interface{}) interface{}",
    "any": "interface{}",
    "nil": "interface{}",
    "void": "",
}

# Track processed types to avoid duplicates
processed_types: Set[str] = set()
namespace_declarations: Dict[str, List[str]] = {}


def load_schema(path: str) -> Dict[str, Any]:
    """Load the schema from a JSON file"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def sanitize_go_name(name: str) -> str:
    """Make a name safe for Go"""
    # Replace dots with underscores for non-namespaced names
    if "." in name:
        parts = name.split(".")
        return "".join(p.capitalize() for p in parts)

    # Ensure name starts with capital letter for export
    if name and name[0].islower():
        name = name[0].upper() + name[1:]

    return name


def sanitize_field_name(name: str) -> str:
    """Make a field name safe for Go struct"""
    # Handle reserved words and invalid characters
    go_keywords = [
        "break",
        "default",
        "func",
        "interface",
        "select",
        "case",
        "defer",
        "go",
        "map",
        "struct",
        "chan",
        "else",
        "goto",
        "package",
        "switch",
        "const",
        "fallthrough",
        "if",
        "range",
        "type",
        "continue",
        "for",
        "import",
        "return",
        "var",
    ]

    # Remove special characters
    sanitized = re.sub(r"[^\w]", "_", name)

    # Capitalize first letter for export
    sanitized = sanitized[0].upper() + sanitized[1:] if sanitized else "Field"

    # Handle keywords
    if sanitized.lower() in go_keywords:
        sanitized += "_"

    return sanitized


def format_description(desc: Optional[str]) -> str:
    """Format description as Go comment"""
    if not desc:
        return ""

    # Clean up description
    desc = desc.strip()
    if not desc:
        return ""

    # Format as Go comment
    lines = desc.split("\n")
    if len(lines) == 1:
        return f"// {desc}\n"

    result = "/*\n"
    for line in lines:
        result += f" * {line}\n"
    result += " */\n"
    return result


def map_type(type_str: Any) -> str:
    """Map DCS schema type to Go type"""
    if not type_str:
        return "interface{}"

    # Ensure type_str is a string
    if not isinstance(type_str, str):
        return "interface{}"

    # Handle union types - Go doesn't have direct union types, use interface{}
    if "|" in type_str:
        return "interface{}"

    # Handle array types
    if type_str.endswith("[]"):
        base_type = type_str[:-2].strip()
        return f"[]{map_type(base_type)}"

    # Handle map types
    if type_str.startswith("map<") and type_str.endswith(">"):
        # Extract key and value types
        inner = type_str[4:-1].strip()
        # Simplification: assuming maps have string keys
        return f"map[string]{map_type(inner)}"

    # Handle primitive types
    if type_str in TYPE_MAPPING:
        return TYPE_MAPPING[type_str]

    # Handle namespaced types
    if "." in type_str:
        # Convert dot notation to CamelCase
        return sanitize_go_name(type_str)

    # Return type with first letter capitalized for Go exports
    return sanitize_go_name(type_str)


def process_enum(name: str, enum_def: Dict[str, Any]) -> str:
    """Process an enum into Go constants"""
    values = enum_def.get("values", [])
    desc = enum_def.get("description", "")

    # Handle different formats of enum values
    const_lines = []
    type_name = sanitize_go_name(name)

    # Add description
    result = format_description(desc)
    result += f"type {type_name} string\n\n"
    result += "const (\n"

    if isinstance(values, list):
        # List format
        for i, val in enumerate(values):
            if isinstance(val, str):
                const_name = f"{type_name}_{sanitize_field_name(val)}"
                const_lines.append(f'\t{const_name} {type_name} = "{val}"')
    elif isinstance(values, dict):
        # Object format
        for key, value in values.items():
            const_name = f"{type_name}_{sanitize_field_name(str(key))}"
            if isinstance(value, str):
                const_lines.append(f'\t{const_name} {type_name} = "{value}"')
            else:
                const_lines.append(f'\t{const_name} {type_name} = "{key}"')

    if const_lines:
        result += "\n".join(const_lines)
    else:
        result += f"\t// No enum values defined for {type_name}"

    result += "\n)\n"
    return result


def get_namespace_parts(full_name: str) -> tuple:
    """Split a namespace.Type name into parts"""
    if "." not in full_name:
        return "", full_name

    parts = full_name.split(".")
    namespace = ".".join(parts[:-1])
    type_name = parts[-1]
    return namespace, type_name


def process_struct(name: str, type_def: Dict[str, Any]) -> str:
    """Process a type into Go struct definition"""
    if name in processed_types:
        return ""

    processed_types.add(name)

    # Handle namespace
    namespace, type_name = get_namespace_parts(name)
    go_type_name = sanitize_go_name(name)  # Full name for Go

    # Different handling based on type
    kind = type_def.get("kind", "")

    if kind == "enum":
        return process_enum(name, type_def)

    # For regular types, create a struct
    properties = {}

    # Properties section
    if "properties" in type_def:
        properties.update(type_def["properties"])

    # Static section
    if "static" in type_def:
        properties.update(type_def["static"])

    # Start with description
    result = format_description(type_def.get("description", ""))

    # Add struct definition
    result += f"type {go_type_name} struct {{\n"

    # Add properties with JSON tags
    for prop_name, prop_def in properties.items():
        prop_type = prop_def.get("type", "interface{}")
        prop_desc = prop_def.get("description", "")
        field_name = sanitize_field_name(prop_name)

        # Convert property type
        go_prop_type = map_type(prop_type)

        # Add field with JSON tag
        if prop_desc:
            result += f"\t// {prop_desc}\n"
        result += f'\t{field_name} {go_prop_type} `json:"{prop_name}"`\n'

    # If no properties, add a comment
    if not properties:
        result += "\t// No fields defined\n"

    result += "}\n"

    # Add methods as function declarations with receiver
    if "instance" in type_def:
        instance_methods = type_def["instance"]
        if instance_methods:
            result += "\n// Methods for " + go_type_name + "\n"

        for method_name, method_def in instance_methods.items():
            params = method_def.get("params", [])
            returns = method_def.get("returns", "")
            desc = method_def.get("description", "")

            # Format method parameters
            param_list = []
            for param in params:
                param_name = param.get("name", "param")
                param_type = param.get("type", "interface{}")
                sanitized_name = re.sub(r"[^\w]", "_", param_name)
                param_list.append(f"{sanitized_name} {map_type(param_type)}")

            # Format return type
            return_type = ""
            if returns and returns != "void":
                return_type = map_type(returns)
                if return_type:
                    return_type = " " + return_type

            # Add method
            if desc:
                result += f"// {desc}\n"
            result += f"func (r *{go_type_name}) {sanitize_field_name(method_name)}({', '.join(param_list)}){return_type} {{\n"
            result += "\t// Method implementation would go here\n"
            result += '\tpanic("Not implemented")\n'
            result += "}\n"

    # Add to namespace declarations if needed
    if namespace:
        if namespace not in namespace_declarations:
            namespace_declarations[namespace] = []
        namespace_declarations[namespace].append(result)
        return ""

    return result


def generate_go_package(schema: Dict[str, Any], package_name: str) -> str:
    """Generate Go package with all types"""
    # Start with package declaration and imports
    result = f"// Package {package_name} provides types for the DCS World API\n"
    result += "// Generated from DCS World Schema - DO NOT EDIT\n\n"
    result += f"package {package_name}\n\n"

    # Process types
    enums = []
    structs = []

    if "types" in schema:
        for type_name, type_def in sorted(schema["types"].items()):
            # Skip namespace types for now
            if "." not in type_name:
                if type_def.get("kind", "") == "enum":
                    enums.append(process_struct(type_name, type_def))
                else:
                    structs.append(process_struct(type_name, type_def))

    # Process globals
    if "globals" in schema:
        for global_name, global_def in sorted(schema["globals"].items()):
            # Create a struct for each global namespace
            props = {}

            # Combine properties and static items
            if "properties" in global_def:
                props.update(global_def["properties"])
            if "static" in global_def:
                props.update(global_def["static"])

            # Create type definition
            global_def_dict = {
                "properties": props,
                "description": global_def.get(
                    "description", f"{global_name} global namespace"
                ),
            }

            # If there are instance methods, add them
            if "instance" in global_def:
                global_def_dict["instance"] = global_def["instance"]

            structs.append(process_struct(global_name, global_def_dict))

    # Add enums first, then structs
    for enum in enums:
        if enum:
            result += enum + "\n"

    for struct in structs:
        if struct:
            result += struct + "\n"

    # Process namespace types
    for namespace, types in sorted(namespace_declarations.items()):
        result += f"// Namespace: {namespace}\n"
        for type_def in types:
            result += type_def + "\n"

    return result


def export_to_golang(
    schema: Dict[str, Any], output_path: str, package_name: str = "dcsapi"
) -> None:
    """Export schema to Go code"""
    output_dir = os.path.dirname(output_path)
    os.makedirs(output_dir, exist_ok=True)

    # Reset global state
    processed_types.clear()
    namespace_declarations.clear()

    # Generate Go code
    go_code = generate_go_package(schema, package_name)

    # Write to file
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(go_code)

    print(f"Go code exported to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Export DCS schema to Go")
    parser.add_argument("schema", help="Path to the DCS schema JSON file")
    parser.add_argument(
        "--output",
        "-o",
        default="dist/dcs-world-api.go",
        help="Output Go file (default: dist/dcs-world-api.go)",
    )
    parser.add_argument(
        "--package", "-p", default="dcsapi", help="Go package name (default: dcsapi)"
    )

    args = parser.parse_args()

    try:
        schema = load_schema(args.schema)
        export_to_golang(schema, args.output, args.package)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
