#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from tools.datamine.common import load_json
from tools.spec_types import (
    STRING,
    Array,
    Literal,
    Map,
    Primitive,
    Ref,
    TypeNode,
    Union,
    api_spec,
    is_type_only,
    members,
    parse_type,
    runtime_roots,
    strip_null,
)

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
processed_types: set[str] = set()
forward_declarations: set[str] = set()
namespace_declarations: dict[str, list[str]] = {}
# The DCS globals of the spec being exported: an enum under any other root is
# only a type, a union of its values (``spec_types.is_type_only``)
ts_runtime_roots: set[str] = set()


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
        escaped_name = name.replace('"', '\\"')
        return f'"{escaped_name}"'
    return name


def process_description(desc: str | None) -> str:
    """Format description as JSDoc comment"""
    if not desc:
        return ""

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


# ``string`` beside a ref or literal: plain ``string`` would absorb the
# literals editors offer; ``string & {}`` keeps them.
OPEN_STRING = "(string & {})"


def map_type(type_str: str) -> str:
    """Map DCS schema type to TypeScript type"""
    if not type_str:
        return "any"
    return render_type(parse_type(type_str))


def render_type(node: TypeNode) -> str:
    """The TypeScript type of a typeRef node."""
    if isinstance(node, Union):
        open_string = any(isinstance(m, Ref | Literal) for m in node.members)
        return " | ".join(
            OPEN_STRING if open_string and m == STRING else render_type(m)
            for m in node.members
        )
    if isinstance(node, Array):
        return f"Array<{render_type(node.item)}>"
    if isinstance(node, Map):
        return f"Record<{_key_type(node.key)}, {render_type(node.value)}>"
    if isinstance(node, Literal):
        return f'"{node.value}"'
    if isinstance(node, Primitive):
        return TYPE_MAPPING[node.name]
    return _ref_type(node.name)


def _key_type(key: TypeNode) -> str:
    """A record key type: ``string`` or ``number``, anything else ``string``."""
    if isinstance(key, Primitive) and key.name in ("string", "number"):
        return TYPE_MAPPING[key.name]
    return "string"


def _ref_type(type_str: str) -> str:
    # Special case for Object/unknown references
    if type_str == "Object":
        return "DCSObject"
    if type_str == "Object.Category":
        return "DCSObject.Category"
    if type_str == "object":
        return "Record<string, any>"
    if type_str == "unknown":
        return "any"

    if "." in type_str:
        if type_str.startswith("Object."):
            # Replace Object with DCSObject
            fixed_type = type_str.replace("Object.", "DCSObject.")
            forward_declarations.add(fixed_type)
            return fixed_type
        forward_declarations.add(type_str)

        # Special case for Unit and StaticObject
        if type_str in ["Unit.Class", "StaticObject.Class"]:
            # Return the class name without namespace for these
            return f"{type_str.split('.')[0]}Class"

        return type_str  # Keep the namespaced reference

    return type_str  # Keep the original type name


def record_field_type(type_str: str) -> tuple[str, bool]:
    """TS type of a record field's typeRef and whether it admits ``nil``.

    ``nil``/``void`` members are dropped (the field is rendered optional
    instead); function types are parenthesised inside unions.
    """
    return _field_type(parse_type(type_str or "any"))


def _field_type(node: TypeNode) -> tuple[str, bool]:
    non_null, nullable = strip_null(node)
    parts = members(non_null) if non_null is not None else ()
    open_string = any(isinstance(p, Ref | Literal) for p in parts)
    rendered: list[str] = []
    for part in parts:
        if open_string and part == STRING:
            ts = OPEN_STRING
        elif isinstance(part, Map):
            value_ts, value_nullable = _field_type(part.value)
            if value_nullable:
                value_ts = f"{value_ts} | undefined"
            ts = f"Record<{_key_type(part.key)}, {value_ts}>"
        else:
            ts = render_type(part)
        if len(parts) > 1 and "=>" in ts:
            ts = f"({ts})"
        if ts not in rendered:
            rendered.append(ts)
    if not rendered:
        return "undefined", True
    return " | ".join(rendered), nullable


def jsdoc_line(desc: str) -> str:
    """A one-line JSDoc comment (``*/`` escaped, newlines folded)."""
    text = " ".join(desc.split()).replace("*/", "*\\/")
    return f"/** {text} */"


def process_record_fields(type_def: dict[str, Any], indent: str) -> str:
    """Interface members for a ``kind: record`` type's ``fields``.

    A field is optional (``?``) unless listed in ``required``; a field whose
    typeRef includes ``nil`` is optional too.
    """
    required = set(type_def.get("required") or [])
    out = ""
    for field_name, field_def in type_def.get("fields", {}).items():
        ts_type, nullable = record_field_type(field_def.get("type", "any"))
        optional = nullable or field_name not in required
        desc = field_def.get("description", "")
        if desc:
            out += f"{indent}{jsdoc_line(desc)}\n"
        mark = "?" if optional else ""
        out += f"{indent}{sanitize_property_name(field_name)}{mark}: {ts_type};\n"
    return out


def process_parameter(param: dict[str, Any]) -> str:
    """Process a function parameter into TypeScript"""
    name = param.get("name", "param")
    type_str = param.get("type", "any")
    optional = param.get("optional", False)

    if not name.isidentifier() or re.search(r"[^\w$]", name) or name[0].isdigit():
        clean_name = name.replace(" ", "_").replace("-", "_").replace("/", "_")
        if not clean_name.isidentifier() or clean_name[0].isdigit():
            clean_name = "p_" + clean_name
        name = clean_name

    ts_type = map_type(type_str)
    param_line = f"{name}{': ' + ts_type if ts_type else ''}"
    if optional:
        param_line = f"{name}?: {ts_type}"

    return param_line


def _literal_enum(name: str, desc: str, values: dict[str, Any]) -> str:
    """An enum with boolean values (a TS enum holds only numbers and strings):
    a union of the values and a same-named constant of them by key."""
    namespace, enum_name = get_namespace_parts(name)
    lead = "" if namespace else "declare "
    union = " | ".join(json.dumps(v) for v in dict.fromkeys(values.values()))
    definition = process_description(desc)
    definition += f"{lead}type {enum_name} = {union};\n"
    definition += f"{lead}const {enum_name}: {{\n"
    for key, value in values.items():
        definition += (
            f"    readonly {sanitize_property_name(str(key))}: {json.dumps(value)};\n"
        )
    definition += "};"
    if namespace:
        namespace_declarations.setdefault(namespace, []).append(definition)
        return ""
    return definition


def _type_only_enum(name: str, desc: str, values: Any) -> str:
    """An enum no DCS table holds: a union of its values, each named in a
    comment unless its name is the value; no runtime value."""
    namespace, enum_name = get_namespace_parts(name)
    if isinstance(values, dict):
        pairs = [(str(k), v) for k, v in values.items()]
    else:
        pairs = [(str(v), v) for v in values or []]
    definition = process_description(desc)
    definition += f"{'' if namespace else 'declare '}type {enum_name} ="
    if not pairs:
        definition += " never;"
    for i, (key, value) in enumerate(pairs):
        last = ";" if i == len(pairs) - 1 else ""
        name_note = "" if key == str(value) else f" // {key}"
        definition += f"\n    | {json.dumps(value)}{last}{name_note}"
    if namespace:
        namespace_declarations.setdefault(namespace, []).append(definition)
        return ""
    return definition


def process_enum(name: str, enum_def: dict[str, Any]) -> str:
    """Process an enum into TypeScript definition"""
    values = enum_def.get("values", [])
    desc = enum_def.get("description", "")
    if is_type_only(name, ts_runtime_roots):
        return _type_only_enum(name, desc, values)

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

    if isinstance(values, dict) and any(isinstance(v, bool) for v in values.values()):
        return _literal_enum(name, desc, values)

    enum_lines = []

    if isinstance(values, list):
        for val in values:
            if isinstance(val, str):
                safe_key = sanitize_property_name(val)
                # String enum values
                enum_lines.append(f'    {safe_key} = "{val}"')
    elif isinstance(values, dict):
        for key, value in values.items():
            # For numeric keys, prepend with a letter to make it valid
            if str(key).isdigit():
                safe_key = f"KEY_{key}"
            else:
                safe_key = sanitize_property_name(str(key))

            if isinstance(value, str):
                formatted_value = f'"{value}"'
            elif isinstance(value, (int, float)):
                formatted_value = str(value)
            else:
                formatted_value = f'"{key}"'  # Default fallback

            enum_lines.append(f"    {safe_key} = {formatted_value}")
    elif isinstance(values, str):
        safe_key = sanitize_property_name(values)
        enum_lines.append(f'    {safe_key} = "{values}"')

    safe_type_name = name.split(".")[-1] if "." in name else name

    namespace = name[: name.rfind(".")] if "." in name else ""

    enum_ts = process_description(desc)
    if namespace:
        enum_ts += f"enum {safe_type_name} {{\n"
    else:
        enum_ts += f"declare enum {safe_type_name} {{\n"

    enum_ts += ",\n".join(enum_lines)
    enum_ts += "\n}"

    if namespace:
        namespace_declarations.setdefault(namespace, []).append(enum_ts)
        return ""

    return enum_ts


def get_namespace_parts(full_name: str) -> tuple[str, str]:
    """Split a namespace.Type name into parts"""
    if "." not in full_name:
        return "", full_name

    last_dot = full_name.rfind(".")
    namespace = full_name[:last_dot]
    type_name = full_name[last_dot + 1 :]
    return namespace, type_name


def process_type(name: str, type_def: dict[str, Any]) -> str:
    """Process a type into TypeScript definition"""
    if name in processed_types:
        return ""

    processed_types.add(name)

    namespace, type_name = get_namespace_parts(name)

    # Special handling for reserved names
    if type_name == "unknown":
        type_name = "UnknownType"  # Rename to avoid conflict

    kind = type_def.get("kind", "")

    if kind == "enum":
        return process_enum(name, type_def)

    if kind == "union":
        members = [_union_member(map_type(t)) for t in type_def.get("anyOf") or []]
        definition = process_description(type_def.get("description", ""))
        definition += f"type {type_name} = {' | '.join(members) or 'any'};"
        if namespace:
            namespace_declarations.setdefault(namespace, []).append(definition)
            return ""
        return definition

    properties = {}
    methods = {}

    if "properties" in type_def:
        properties.update(type_def["properties"])

    if "static" in type_def:
        properties.update(type_def["static"])

    if "instance" in type_def:
        methods.update(type_def["instance"])

    # Use class if it has methods, otherwise use interface
    inherits = type_def.get("inherits", "")
    extends_clause = f" extends {map_type(inherits)}" if inherits else ""

    definition = process_description(type_def.get("description", ""))

    # If in namespace and has instance methods, treat it as a class
    if namespace and methods:
        definition += f"class {type_name}{extends_clause} {{\n"

        for prop_name, prop_def in properties.items():
            prop_type = prop_def.get("type", "any")
            prop_desc = prop_def.get("description", "")

            if isinstance(prop_type, list):
                type_strings = [map_type(t) for t in prop_type if isinstance(t, str)]
                ts_type = " | ".join(type_strings) if type_strings else "any"
            else:
                ts_type = map_type(prop_type)

            if prop_desc:
                definition += f"    /** {prop_desc} */\n"
            definition += f"    {sanitize_property_name(prop_name)}: {ts_type};\n"

        for method_name, method_def in methods.items():
            params = method_def.get("params", [])
            returns = method_def.get("returns", "void")
            desc = method_def.get("description", "")

            param_list = []
            for param in params:
                param_list.append(process_parameter(param))

            if isinstance(returns, list):
                return_types = [map_type(rt) for rt in returns if isinstance(rt, str)]
                return_type = " | ".join(return_types) if return_types else "any"
            else:
                return_type = map_type(returns)

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

        for prop_name, prop_def in properties.items():
            prop_type = prop_def.get("type", "any")
            prop_desc = prop_def.get("description", "")

            if isinstance(prop_type, list):
                type_strings = [map_type(t) for t in prop_type if isinstance(t, str)]
                ts_type = " | ".join(type_strings) if type_strings else "any"
            else:
                ts_type = map_type(prop_type)

            if prop_desc:
                definition += f"    /** {prop_desc} */\n"
            definition += f"    {sanitize_property_name(prop_name)}: {ts_type};\n"

        record_fields = kind == "record" and bool(type_def.get("fields"))
        if record_fields:
            definition += process_record_fields(type_def, "    ")

        if not properties and not methods and not record_fields:
            definition += "    // No properties or methods defined\n"

        definition += "}"

    if namespace:
        namespace_declarations.setdefault(namespace, []).append(definition)
        return ""  # Will be added through namespace later

    return definition


def returns_type(returns: Any) -> str:
    """The TypeScript type of a methodDef's returns (several: their union)."""
    if isinstance(returns, list):
        types = [_union_member(map_type(rt)) for rt in returns if isinstance(rt, str)]
        return " | ".join(types) if types else "any"
    return map_type(returns)


def _union_member(ts_type: str) -> str:
    """A type as a union member: a function type in parentheses."""
    return f"({ts_type})" if "=>" in ts_type else ts_type


def static_method_type(method_def: dict[str, Any]) -> str:
    """A static methodDef as a function type; a parameter after an optional
    one is optional too (TypeScript has no required one after it)."""
    params, optional = [], False
    for p in method_def.get("params") or []:
        optional = optional or bool(p.get("optional"))
        name = re.sub(r"\W", "_", str(p.get("name") or "param"))
        params.append(process_parameter({**p, "name": name, "optional": optional}))
    ret = returns_type(method_def["returns"])
    return f"({', '.join(params)}) => {ret}"


def process_global(name: str, global_def: dict[str, Any]) -> str:
    """Process a global namespace into TypeScript definition"""
    properties = global_def.get("properties", {})
    static_items = global_def.get("static", {})
    instance_methods = global_def.get("instance", {})

    all_properties = {**properties, **static_items}

    has_content = (
        bool(all_properties) or bool(instance_methods) or name in namespace_declarations
    )

    declaration = process_description(global_def.get("description", ""))

    if has_content:
        declaration += f"declare namespace {name} {{\n"

        # Add class declaration instead of interface methods
        if all_properties or instance_methods:
            declaration += "    /** Main class for this namespace */\n"
            declaration += f"    class {name} {{\n"

            for prop_name, prop_def in all_properties.items():
                prop_type = prop_def.get("type", "any")
                prop_desc = prop_def.get("description", "")

                if "type" not in prop_def and "returns" in prop_def:
                    # A static method: a function-typed property.
                    ts_type = static_method_type(prop_def)
                elif isinstance(prop_type, list):
                    type_strings = [
                        map_type(t) for t in prop_type if isinstance(t, str)
                    ]
                    ts_type = " | ".join(type_strings) if type_strings else "any"
                else:
                    ts_type = map_type(prop_type)

                if prop_desc:
                    declaration += f"        /** {prop_desc} */\n"
                declaration += (
                    f"        {sanitize_property_name(prop_name)}: {ts_type};\n"
                )

            for method_name, method_def in instance_methods.items():
                params = method_def.get("params", [])
                returns = method_def.get("returns", "void")
                desc = method_def.get("description", "")

                param_list = []
                for param in params:
                    param_list.append(process_parameter(param))

                if isinstance(returns, list):
                    return_types = [
                        map_type(rt) for rt in returns if isinstance(rt, str)
                    ]
                    return_type = " | ".join(return_types) if return_types else "any"
                else:
                    return_type = map_type(returns)

                if desc:
                    declaration += f"        /** {desc} */\n"
                declaration += f"        {sanitize_property_name(method_name)}({', '.join(param_list)}): {return_type};\n"

            declaration += "    }\n\n"

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


def export_to_typescript(schema: dict[str, Any], output_path: str) -> None:
    """Export schema to TypeScript definitions"""
    schema = api_spec(schema)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    output = [
        "// DCS World TypeScript Definitions",
        "// Generated from DCS World Schema",
        "// DO NOT MODIFY - AUTO-GENERATED FILE",
        "",
    ]

    processed_types.clear()
    namespace_declarations.clear()
    forward_declarations.clear()

    # Set of namespaces that need interface versions because they're used as types
    namespace_interfaces = set()

    # Rename the Object namespace to DCSObject
    if "globals" in schema and "Object" in schema["globals"]:
        schema["globals"]["DCSObject"] = schema["globals"].pop("Object")

        # Update all references from Object to DCSObject in the schema
        if "types" in schema:
            for type_def in schema["types"].values():
                if type_def.get("inherits") == "Object":
                    type_def["inherits"] = "DCSObject"

                if "properties" in type_def:
                    for prop_def in type_def["properties"].values():
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

                if "instance" in type_def:
                    for method_def in type_def["instance"].values():
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

    ts_runtime_roots.clear()
    ts_runtime_roots.update(runtime_roots(schema))

    # First pass: collect namespaced types
    if "types" in schema:
        for type_name, type_def in schema["types"].items():
            if "." in type_name:
                if type_name.startswith("Object."):
                    new_type_name = type_name.replace("Object.", "DCSObject.")
                    process_type(new_type_name, type_def)
                else:
                    process_type(type_name, type_def)

    # Identify which namespaces need interface versions
    if "globals" in schema:
        # Any namespace used as a return type or parameter type needs an interface
        for global_name in schema["globals"]:
            namespace_interfaces.add(global_name)  # All namespaces need interfaces

    # Process globals first to collect more namespace types
    if "globals" in schema:
        for global_def in schema["globals"].values():
            properties = global_def.get("properties", {})
            static_items = global_def.get("static", {})
            instance_items = global_def.get("instance", {})

            for prop_def in {**properties, **static_items}.values():
                type_str = prop_def.get("type", "any")
                if isinstance(type_str, str):
                    map_type(type_str)  # This adds to forward_declarations
                elif isinstance(type_str, list):
                    for t in type_str:
                        if isinstance(t, str):
                            map_type(t)  # This adds to forward_declarations

            for method_def in instance_items.values():
                for param in method_def.get("params", []):
                    param_type = param.get("type", "any")
                    map_type(param_type)  # This adds to forward_declarations

                returns = method_def.get("returns", "void")
                if isinstance(returns, str):
                    map_type(returns)  # This adds to forward_declarations
                elif isinstance(returns, list):
                    for rt in returns:
                        if isinstance(rt, str):
                            map_type(rt)  # This adds to forward_declarations

    namespace_interface_declarations = []
    for namespace in sorted(namespace_interfaces):
        namespace_interface_declarations.append(
            f"declare interface {namespace} {{ /* Interface for namespace {namespace} */ }}"
        )

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

    if "globals" in schema:
        output.append("// Global Namespaces")
        for global_name, global_def in sorted(schema["globals"].items()):
            global_declaration = process_global(global_name, global_def)
            if global_declaration:
                output.append(global_declaration)
                output.append("")

    remaining_namespaces = [
        ns for ns in namespace_declarations if ns not in schema.get("globals", {})
    ]
    if remaining_namespaces:
        output.append("// Additional Namespaces")
        for namespace in sorted(remaining_namespaces):
            output.append(f"declare namespace {namespace} {{")
            for type_def in namespace_declarations[namespace]:
                output.append("    " + type_def.replace("\n", "\n    "))
            output.append("}")
            output.append("")

    with Path(output_path).open("w", encoding="utf-8") as f:
        f.write("\n".join(output))

    print(f"TypeScript definitions exported to {output_path}")


def main() -> None:
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
        schema = load_json(Path(args.schema))
        export_to_typescript(schema, args.output)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
