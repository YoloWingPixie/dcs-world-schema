#!/usr/bin/env python3
import argparse
import json
import os
import sys
import re
from typing import Any, Dict, List, Optional, Set

# TypeScript primitive type mapping
TYPE_MAPPING = {
    "number": "number",
    "string": "string",
    "boolean": "boolean",
    "table": "Record<string, any>",
    "function": "(...args: any[]) => any",
    "any": "any",
    "nil": "null | undefined",
    "void": "void",
}

# Track processed types to avoid duplicates
processed_types: Set[str] = set()
forward_declarations: Set[str] = set()
namespace_declarations: Dict[str, List[str]] = {}


def load_schema(path: str) -> Dict[str, Any]:
    """Load the schema from a JSON file"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def sanitize_ts_name(name: str) -> str:
    """Make a name safe for TypeScript"""
    # Replace dots with underscores for non-namespace names
    if "." not in name:
        return name.replace(".", "_")
    return name


def sanitize_property_name(name: str) -> str:
    """Make a property name safe for TypeScript"""
    # Check if the property name needs quotes
    if (
        not name.isidentifier()
        or re.search(r"[^\w$]", name)
        or name[0].isdigit()
        or "-" in name
        or " " in name
        or name
        in ["class", "function", "var", "let", "const", "enum", "interface", "type"]
    ):
        # Escape quotes in the name
        escaped_name = name.replace('"', '\\"')
        return f'"{escaped_name}"'
    return name


def process_description(desc: Optional[str]) -> str:
    """Format description as JSDoc comment"""
    if not desc:
        return ""

    # Clean up the description
    desc = desc.strip()
    if not desc:
        return ""

    lines = desc.split("\n")
    if len(lines) == 1:
        return f"/** {desc} */\n"

    result = "/**\n"
    for line in lines:
        result += f" * {line}\n"
    result += " */\n"
    return result


def map_type(type_str: str) -> str:
    """Map DCS schema type to TypeScript type"""
    if not type_str:
        return "any"

    # Handle union types
    if "|" in type_str:
        types = [map_type(t.strip()) for t in type_str.split("|")]
        return " | ".join(types)

    # Handle array types
    if type_str.endswith("[]"):
        base_type = type_str[:-2].strip()
        return f"Array<{map_type(base_type)}>"

    # Handle map types
    if type_str.startswith("map<") and type_str.endswith(">"):
        # Extract key and value types
        inner = type_str[4:-1].strip()
        # Simplification: assuming maps are always string keys in TypeScript
        return f"Record<string, {map_type(inner)}>"

    # Special case for Object/unknown references
    if type_str == "Object":
        return "DCSObject"
    elif type_str == "Object.Category":
        return "DCSObject.Category"
    elif type_str == "object":
        return "Record<string, any>"
    elif type_str == "unknown":
        return "any"

    # Handle primitive types
    if type_str in TYPE_MAPPING:
        return TYPE_MAPPING[type_str]

    # Reference to another type - handle special cases
    if "." in type_str:
        # It's a namespaced type
        if type_str.startswith("Object."):
            # Replace Object with DCSObject
            fixed_type = type_str.replace("Object.", "DCSObject.")
            forward_declarations.add(fixed_type)
            return fixed_type
        else:
            forward_declarations.add(type_str)

        # Special case for Unit and StaticObject
        if type_str in ["Unit.Class", "StaticObject.Class"]:
            # Return the class name without namespace for these
            return f"{type_str.split('.')[0]}Class"

        return type_str  # Keep the namespaced reference

    # Special handling for known type conflicts
    if type_str == "unknown":
        return "UnknownType"  # Rename to avoid conflict

    # Custom type
    return type_str  # Keep the original type name


def process_parameter(param: Dict[str, Any]) -> str:
    """Process a function parameter into TypeScript"""
    name = param.get("name", "param")
    type_str = param.get("type", "any")
    optional = param.get("optional", False)

    # Handle parameter names with spaces or special characters
    if not name.isidentifier() or re.search(r"[^\w$]", name) or name[0].isdigit():
        # Sanitize parameter name
        clean_name = name.replace(" ", "_").replace("-", "_").replace("/", "_")
        if not clean_name.isidentifier() or clean_name[0].isdigit():
            clean_name = "p_" + clean_name
        name = clean_name

    ts_type = map_type(type_str)
    param_line = f"{name}{': ' + ts_type if ts_type else ''}"
    if optional:
        param_line = f"{name}?: {ts_type}"

    return param_line


def process_enum(name: str, enum_def: Dict[str, Any]) -> str:
    """Process an enum into TypeScript definition"""
    values = enum_def.get("values", [])
    desc = enum_def.get("description", "")

    # Special handling for country.name enum that has numeric keys
    namespace, enum_name = get_namespace_parts(name)
    if namespace == "country" and enum_name == "name":
        # Create as const object instead of enum
        definition = f"/** {desc} */\n" if desc else ""
        definition += f"const {enum_name}: Record<string, string> = {{\n"

        if isinstance(values, dict):
            entries = []
            for key, value in values.items():
                entries.append(f'    "{key}": "{value}"')
            definition += ",\n".join(entries)

        definition += "\n};"
        return definition

    # Build enum definition
    enum_lines = []

    # Handle different formats of enum values
    if isinstance(values, list):
        # List format
        for val in values:
            if isinstance(val, str):
                # Sanitize enum value name if needed
                safe_key = sanitize_property_name(val)
                # String enum values
                enum_lines.append(f'    {safe_key} = "{val}"')
    elif isinstance(values, dict):
        # Object format (key-value pairs)
        for key, value in values.items():
            # For numeric keys, prepend with a letter to make it valid
            if str(key).isdigit():
                safe_key = f"KEY_{key}"
            else:
                # Sanitize enum key name if needed
                safe_key = sanitize_property_name(str(key))

            # Format value based on its type
            if isinstance(value, str):
                formatted_value = f'"{value}"'
            elif isinstance(value, (int, float)):
                formatted_value = str(value)
            else:
                formatted_value = f'"{key}"'  # Default fallback

            enum_lines.append(f"    {safe_key} = {formatted_value}")
    elif isinstance(values, str):
        # Single string value
        # Sanitize enum value name if needed
        safe_key = sanitize_property_name(values)
        enum_lines.append(f'    {safe_key} = "{values}"')

    # Get sanitized name for the enum
    safe_type_name = name.split(".")[-1] if "." in name else name

    # Create namespace part if needed
    namespace = name[: name.rfind(".")] if "." in name else ""

    # Enum declaration
    enum_def = process_description(desc)
    if namespace:
        enum_def += f"enum {safe_type_name} {{\n"
    else:
        enum_def += f"declare enum {safe_type_name} {{\n"

    enum_def += ",\n".join(enum_lines)
    enum_def += "\n}"

    # If it's a namespaced enum, add it to the namespace
    if namespace:
        namespace_declarations.setdefault(namespace, []).append(enum_def)
        return ""

    return enum_def


def get_namespace_parts(full_name: str) -> tuple:
    """Split a namespace.Type name into parts"""
    if "." not in full_name:
        return "", full_name

    last_dot = full_name.rfind(".")
    namespace = full_name[:last_dot]
    type_name = full_name[last_dot + 1 :]
    return namespace, type_name


def process_type(name: str, type_def: Dict[str, Any]) -> str:
    """Process a type into TypeScript definition"""
    if name in processed_types:
        return ""

    processed_types.add(name)

    # Handle namespace
    namespace, type_name = get_namespace_parts(name)

    # Special handling for reserved names
    if type_name == "unknown":
        type_name = "UnknownType"  # Rename to avoid conflict

    # Different handling based on type
    kind = type_def.get("kind", "")

    if kind == "enum":
        definition = process_enum(name, type_def)
        return definition

    # For regular types, determine if it should be a class or interface
    properties = {}
    methods = {}

    # Properties section
    if "properties" in type_def:
        properties.update(type_def["properties"])

    # Static section
    if "static" in type_def:
        properties.update(type_def["static"])

    # Instance section
    if "instance" in type_def:
        methods.update(type_def["instance"])

    # Use class if it has methods, otherwise use interface
    inherits = type_def.get("inherits", "")
    extends_clause = f" extends {map_type(inherits)}" if inherits else ""

    # Start with description
    definition = process_description(type_def.get("description", ""))

    # If in namespace and has instance methods, treat it as a class
    if namespace and methods:
        # Use class
        definition += f"class {type_name}{extends_clause} {{\n"

        # Add properties
        for prop_name, prop_def in properties.items():
            prop_type = prop_def.get("type", "any")
            prop_desc = prop_def.get("description", "")

            # Handle list of types
            if isinstance(prop_type, list):
                # Join multiple types with a union operator
                type_strings = [map_type(t) for t in prop_type if isinstance(t, str)]
                ts_type = " | ".join(type_strings) if type_strings else "any"
            else:
                ts_type = map_type(prop_type)

            # Add property with JSDoc
            if prop_desc:
                definition += f"    /** {prop_desc} */\n"
            definition += f"    {sanitize_property_name(prop_name)}: {ts_type};\n"

        # Add methods
        for method_name, method_def in methods.items():
            # Process parameters
            params = method_def.get("params", [])
            returns = method_def.get("returns", "void")
            desc = method_def.get("description", "")

            # Build parameter list
            param_list = []
            for param in params:
                param_list.append(process_parameter(param))

            # Convert return type
            if isinstance(returns, list):
                return_types = [map_type(rt) for rt in returns if isinstance(rt, str)]
                return_type = " | ".join(return_types) if return_types else "any"
            else:
                return_type = map_type(returns)

            # Add method with JSDoc
            if desc:
                definition += f"    /** {desc} */\n"
            definition += f"    {sanitize_property_name(method_name)}({', '.join(param_list)}): {return_type};\n"

        definition += "}"
    else:
        # Use interface for types without methods or non-namespaced types
        if namespace:
            definition += f"interface {type_name}{extends_clause} {{\n"
        else:
            definition += f"declare interface {type_name}{extends_clause} {{\n"

        # Add properties
        for prop_name, prop_def in properties.items():
            prop_type = prop_def.get("type", "any")
            prop_desc = prop_def.get("description", "")

            # Handle list of types
            if isinstance(prop_type, list):
                # Join multiple types with a union operator
                type_strings = [map_type(t) for t in prop_type if isinstance(t, str)]
                ts_type = " | ".join(type_strings) if type_strings else "any"
            else:
                ts_type = map_type(prop_type)

            # Add property with JSDoc
            if prop_desc:
                definition += f"    /** {prop_desc} */\n"
            definition += f"    {sanitize_property_name(prop_name)}: {ts_type};\n"

        # If there are no properties and no methods, add a comment
        if not properties and not methods:
            definition += "    // No properties or methods defined\n"

        definition += "}"

    # Store in namespace if needed
    if namespace:
        namespace_declarations.setdefault(namespace, []).append(definition)
        return ""  # Will be added through namespace later

    return definition


def process_global(name: str, global_def: Dict[str, Any]) -> str:
    """Process a global namespace into TypeScript definition"""
    # Handle properties and methods
    properties = global_def.get("properties", {})
    static_items = global_def.get("static", {})
    instance_methods = global_def.get("instance", {})

    # Combine static properties with regular properties
    all_properties = {**properties, **static_items}

    # Check if there's anything to include
    has_content = (
        bool(all_properties) or bool(instance_methods) or name in namespace_declarations
    )

    # Build namespace
    declaration = process_description(global_def.get("description", ""))

    if has_content:
        declaration += f"declare namespace {name} {{\n"

        # Add class declaration instead of interface methods
        if all_properties or instance_methods:
            declaration += "    /** Main class for this namespace */\n"
            declaration += f"    class {name} {{\n"

            # Add properties
            for prop_name, prop_def in all_properties.items():
                prop_type = prop_def.get("type", "any")
                prop_desc = prop_def.get("description", "")

                # Handle list of types
                if isinstance(prop_type, list):
                    # Join multiple types with a union operator
                    type_strings = [
                        map_type(t) for t in prop_type if isinstance(t, str)
                    ]
                    ts_type = " | ".join(type_strings) if type_strings else "any"
                else:
                    ts_type = map_type(prop_type)

                # Add property with JSDoc
                if prop_desc:
                    declaration += f"        /** {prop_desc} */\n"
                declaration += (
                    f"        {sanitize_property_name(prop_name)}: {ts_type};\n"
                )

            # Add methods
            for method_name, method_def in instance_methods.items():
                # Process parameters
                params = method_def.get("params", [])
                returns = method_def.get("returns", "void")
                desc = method_def.get("description", "")

                # Build parameter list
                param_list = []
                for param in params:
                    param_list.append(process_parameter(param))

                # Convert return type
                if isinstance(returns, list):
                    return_types = [
                        map_type(rt) for rt in returns if isinstance(rt, str)
                    ]
                    return_type = " | ".join(return_types) if return_types else "any"
                else:
                    return_type = map_type(returns)

                # Add method with JSDoc
                if desc:
                    declaration += f"        /** {desc} */\n"
                declaration += f"        {sanitize_property_name(method_name)}({', '.join(param_list)}): {return_type};\n"

            declaration += "    }\n\n"

        # Add collected namespace types
        if name in namespace_declarations:
            for type_def in namespace_declarations[name]:
                declaration += "    " + type_def.replace("\n", "\n    ") + "\n\n"

        declaration += "}"
    else:
        # Empty namespace, add minimal declaration
        declaration += f"declare namespace {name} {{ /* Empty namespace */ }}"

    return declaration


def generate_forward_declarations() -> str:
    """Generate forward declarations for types"""
    declarations = []
    for type_name in sorted(forward_declarations):
        if type_name not in processed_types:
            namespace, name = get_namespace_parts(type_name)
            if namespace:
                # Create a declaration for the namespace if it doesn't exist in the main schema
                if namespace not in namespace_declarations:
                    declarations.append(
                        f"declare namespace {namespace} {{ interface {name} {{ }} }}"
                    )
            else:
                declarations.append(f"interface {type_name} {{ }}")

    return "\n".join(declarations)


def export_to_typescript(schema: Dict[str, Any], output_path: str) -> None:
    """Export schema to TypeScript definitions"""
    output_dir = os.path.dirname(output_path)
    os.makedirs(output_dir, exist_ok=True)

    output = [
        "// DCS World TypeScript Definitions",
        "// Generated from DCS World Schema",
        "// DO NOT MODIFY - AUTO-GENERATED FILE",
        "",
    ]

    # Process types
    processed_types.clear()
    namespace_declarations.clear()
    forward_declarations.clear()

    # Set of namespaces that need interface versions because they're used as types
    namespace_interfaces = set()

    # Handle namespace conflict resolution - rename Object to DCSObject
    if "globals" in schema and "Object" in schema["globals"]:
        schema["globals"]["DCSObject"] = schema["globals"].pop("Object")

        # Update all references from Object to DCSObject in the schema
        if "types" in schema:
            for type_name, type_def in schema["types"].items():
                # Update inherits
                if type_def.get("inherits") == "Object":
                    type_def["inherits"] = "DCSObject"

                # Update properties
                if "properties" in type_def:
                    for prop_name, prop_def in type_def["properties"].items():
                        if (
                            isinstance(prop_def.get("type"), str)
                            and prop_def.get("type") == "Object"
                        ):
                            prop_def["type"] = "DCSObject"
                        elif (
                            isinstance(prop_def.get("type"), str)
                            and prop_def.get("type") == "Object.Category"
                        ):
                            prop_def["type"] = "DCSObject.Category"

                # Update method parameters and returns
                if "instance" in type_def:
                    for method_name, method_def in type_def["instance"].items():
                        # Update parameters
                        for param in method_def.get("params", []):
                            if (
                                isinstance(param.get("type"), str)
                                and param.get("type") == "Object"
                            ):
                                param["type"] = "DCSObject"
                            elif (
                                isinstance(param.get("type"), str)
                                and param.get("type") == "Object.Category"
                            ):
                                param["type"] = "DCSObject.Category"

                        # Update returns
                        if isinstance(method_def.get("returns"), str):
                            if method_def.get("returns") == "Object":
                                method_def["returns"] = "DCSObject"
                            elif method_def.get("returns") == "Object.Category":
                                method_def["returns"] = "DCSObject.Category"
                        elif isinstance(method_def.get("returns"), list):
                            for i, ret in enumerate(method_def.get("returns", [])):
                                if ret == "Object":
                                    method_def["returns"][i] = "DCSObject"
                                elif ret == "Object.Category":
                                    method_def["returns"][i] = "DCSObject.Category"

    # First pass: collect namespaced types
    if "types" in schema:
        for type_name, type_def in schema["types"].items():
            if "." in type_name:
                # Handle Object namespace conflict
                if type_name.startswith("Object."):
                    new_type_name = type_name.replace("Object.", "DCSObject.")
                    process_type(new_type_name, type_def)
                else:
                    process_type(type_name, type_def)

    # Identify which namespaces need interface versions
    if "globals" in schema:
        # Any namespace used as a return type or parameter type needs an interface
        for global_name, global_def in schema["globals"].items():
            namespace_interfaces.add(global_name)  # All namespaces need interfaces

    # Process globals first to collect more namespace types
    if "globals" in schema:
        for global_name, global_def in schema["globals"].items():
            # Check properties and methods for references
            properties = global_def.get("properties", {})
            static_items = global_def.get("static", {})
            instance_items = global_def.get("instance", {})

            # Check property types
            for prop_name, prop_def in {**properties, **static_items}.items():
                type_str = prop_def.get("type", "any")
                if isinstance(type_str, str):
                    map_type(type_str)  # This adds to forward_declarations
                elif isinstance(type_str, list):
                    for t in type_str:
                        if isinstance(t, str):
                            map_type(t)  # This adds to forward_declarations

            # Check method parameters and returns
            for method_name, method_def in instance_items.items():
                # Check parameters
                for param in method_def.get("params", []):
                    param_type = param.get("type", "any")
                    map_type(param_type)  # This adds to forward_declarations

                # Check returns
                returns = method_def.get("returns", "void")
                if isinstance(returns, str):
                    map_type(returns)  # This adds to forward_declarations
                elif isinstance(returns, list):
                    for rt in returns:
                        if isinstance(rt, str):
                            map_type(rt)  # This adds to forward_declarations

    # Generate interface definitions for namespaces
    namespace_interface_declarations = []
    for namespace in sorted(namespace_interfaces):
        namespace_interface_declarations.append(
            f"declare interface {namespace} {{ /* Interface for namespace {namespace} */ }}"
        )

    # Process non-namespaced types
    if "types" in schema:
        output.append("// Type Definitions")
        for type_name, type_def in sorted(schema["types"].items()):
            # Skip namespace types, they'll be processed with their namespaces
            if "." in type_name:
                continue

            type_declaration = process_type(type_name, type_def)
            if type_declaration:
                output.append(type_declaration)
                output.append("")

    # Add interface definitions for namespaces
    if namespace_interface_declarations:
        output.append("// Namespace Interface Definitions")
        output.extend(namespace_interface_declarations)
        output.append("")

    # Add forward declarations for types that are referenced but not defined
    forward_decls = generate_forward_declarations()
    if forward_decls:
        output.append("// Forward Declarations")
        output.append(forward_decls)
        output.append("")

    # Process globals
    if "globals" in schema:
        output.append("// Global Namespaces")
        for global_name, global_def in sorted(schema["globals"].items()):
            global_declaration = process_global(global_name, global_def)
            if global_declaration:
                output.append(global_declaration)
                output.append("")

    # Process remaining namespace types
    remaining_namespaces = [
        ns for ns in namespace_declarations if ns not in schema.get("globals", {})
    ]
    if remaining_namespaces:
        output.append("// Additional Namespaces")
        for namespace in sorted(remaining_namespaces):
            output.append(f"declare namespace {namespace} {{")
            for type_def in namespace_declarations[namespace]:
                output.append(f"    {type_def.replace('    ', '        ')}")
            output.append("}")
            output.append("")

    # Write to file
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(output))

    print(f"TypeScript definitions exported to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Export DCS schema to TypeScript definitions"
    )
    parser.add_argument("schema", help="Path to the DCS schema JSON file")
    parser.add_argument(
        "--output",
        "-o",
        default="dist/dcs-world-api.d.ts",
        help="Output TypeScript definition file (default: dist/dcs-world-api.d.ts)",
    )

    args = parser.parse_args()

    try:
        schema = load_schema(args.schema)
        export_to_typescript(schema, args.output)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
