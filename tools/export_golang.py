#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from tools.datamine.common import load_json
from tools.spec_types import (
    Array,
    Literal,
    Map,
    Primitive,
    TypeNode,
    Union,
    api_spec,
    is_literal_union,
    members,
    parse_type,
    strip_null,
)

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
processed_types: set[str] = set()
namespace_declarations: dict[str, list[str]] = {}


def sanitize_go_name(name: str) -> str:
    """Make a name safe for Go"""
    if "." in name:
        parts = name.split(".")
        return "".join(p[:1].upper() + p[1:] for p in parts)

    # Ensure name starts with capital letter for export
    if name and name[0].islower():
        name = name[0].upper() + name[1:]

    return name


GO_KEYWORDS = frozenset(
    {
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
    }
)


def sanitize_field_name(name: str) -> str:
    """Make a field name safe for Go struct"""
    sanitized = re.sub(r"[^\w]", "_", name)

    # Capitalize first letter for export
    sanitized = sanitized[0].upper() + sanitized[1:] if sanitized else "Field"

    if sanitized.lower() in GO_KEYWORDS:
        sanitized += "_"

    return sanitized


def format_description(desc: str | None) -> str:
    """Format description as Go comment"""
    if not desc:
        return ""

    desc = desc.strip()
    if not desc:
        return ""

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

    if not isinstance(type_str, str) or type_str == "interface{}":
        return "interface{}"

    return render_type(parse_type(type_str))


def render_type(node: TypeNode) -> str:
    """The Go type of a typeRef node."""
    if isinstance(node, Union):
        # Go has no literal types: a union of string literals is a string
        # (see literal_constants); other unions (no sum types) interface{}.
        return "string" if is_literal_union(node) else "interface{}"
    if isinstance(node, Array):
        return f"[]{render_type(node.item)}"
    if isinstance(node, Map):
        return f"map[{_key_type(node.key)}]{render_type(node.value)}"
    if isinstance(node, Literal):
        return "string"
    if isinstance(node, Primitive):
        return TYPE_MAPPING[node.name]
    # Exported (capitalised) Go name of the referenced type
    return sanitize_go_name(node.name)


def _key_type(key: TypeNode) -> str:
    """A Go map key: ``string`` / ``float64`` for those primitives, else string."""
    if isinstance(key, Primitive) and key.name in ("string", "number"):
        return TYPE_MAPPING[key.name]
    return "string"


def record_field_type(type_str: str) -> tuple[str, bool]:
    """Go type of a record field's typeRef and whether it admits ``nil``.

    ``nil`` members are dropped; a union of several remaining types becomes
    ``interface{}`` (Go has no sum types).
    """
    return _field_type(parse_type(type_str or "any"))


def _field_type(node: TypeNode) -> tuple[str, bool]:
    non_null, nullable = strip_null(node)
    if non_null is None:
        return "interface{}", True
    if is_literal_union(non_null):
        return "string", nullable
    if isinstance(non_null, Union):
        return "interface{}", nullable
    if isinstance(non_null, Array):
        elem, _ = _field_type(non_null.item)
        return f"[]{elem}", nullable
    if isinstance(non_null, Map):
        value_go, _ = _field_type(non_null.value)
        return f"map[{_key_type(non_null.key)}]{value_go}", nullable
    return render_type(non_null), nullable


def is_nilable_go_type(go_type: str) -> bool:
    """Whether a Go type already has a nil zero value (no pointer needed)."""
    return go_type.startswith(("[]", "map[", "func(", "*")) or go_type in (
        "interface{}",
        "any",
    )


def go_field_name(field_name: str, used: set[str]) -> str:
    """Exported Go name of a record field, unique among ``used`` (updated)."""
    # Go only serialises exported fields: drop leading underscores
    # (e.g. ``_source``); the json tag keeps the original key.
    go_name = sanitize_field_name(field_name.lstrip("_") or field_name)
    if not go_name[:1].isalpha():
        go_name = f"F{go_name}"
    while go_name in used:
        go_name += "_"
    used.add(go_name)
    return go_name


def literal_constants(go_type_name: str, type_def: dict[str, Any]) -> str:
    """Constants for record fields typed by string literals.

    Go has no literal types, so such a field is a ``string``; the value(s) it
    must hold are exported as ``<Type>_<Field>`` (``_<Value>`` appended when
    there are several), in the manner of ``http.MethodGet``.
    """
    used: set[str] = set()
    lines: list[str] = []
    for field_name, field_def in type_def.get("fields", {}).items():
        go_name = go_field_name(field_name, used)
        non_null, _ = strip_null(parse_type(field_def.get("type") or "any"))
        if non_null is None or not is_literal_union(non_null):
            continue
        values = [m.value for m in members(non_null) if isinstance(m, Literal)]
        for value in values:
            const = f"{go_type_name}_{go_name}"
            if len(values) > 1:
                const += f"_{sanitize_field_name(str(value))}"
            which = "a" if len(values) > 1 else "the only"
            lines.append(f"// {const} is {which} value of {go_type_name}.{go_name}.")
            lines.append(f"const {const} = {json.dumps(value)}")
    return "\n" + "\n".join(lines) + "\n" if lines else ""


def process_record_fields(type_def: dict[str, Any]) -> str:
    """Struct fields for a ``kind: record`` type's ``fields``.

    Fields not in ``required`` (or whose typeRef admits ``nil``) are optional:
    tagged ``omitempty`` and, unless the Go type is already nilable, held by
    pointer so absence is distinguishable from the zero value.
    """
    required = set(type_def.get("required") or [])
    out = ""
    used: set[str] = set()
    for field_name, field_def in type_def.get("fields", {}).items():
        go_type, nullable = record_field_type(field_def.get("type", "any"))
        optional = nullable or field_name not in required
        if optional and not is_nilable_go_type(go_type):
            go_type = f"*{go_type}"
        go_name = go_field_name(field_name, used)
        tag = f"{field_name},omitempty" if optional else field_name
        desc = " ".join((field_def.get("description") or "").split())
        if desc:
            out += f"\t// {go_name}: {desc}\n"
        out += f'\t{go_name} {go_type} `json:"{tag}"`\n'
    return out


def process_enum(name: str, enum_def: dict[str, Any]) -> str:
    """Process an enum into Go constants"""
    values = enum_def.get("values", [])
    desc = enum_def.get("description", "")

    const_lines = []
    type_name = sanitize_go_name(name)

    result = format_description(desc)
    result += f"type {type_name} string\n\n"
    result += "const (\n"

    if isinstance(values, list):
        for val in values:
            if isinstance(val, str):
                const_name = f"{type_name}_{sanitize_field_name(val)}"
                const_lines.append(f'\t{const_name} {type_name} = "{val}"')
    elif isinstance(values, dict):
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


def get_namespace_parts(full_name: str) -> tuple[str, str]:
    """Split a namespace.Type name into parts"""
    if "." not in full_name:
        return "", full_name

    parts = full_name.split(".")
    namespace = ".".join(parts[:-1])
    type_name = parts[-1]
    return namespace, type_name


def process_struct(name: str, type_def: dict[str, Any]) -> str:
    """Process a type into Go struct definition"""
    if name in processed_types:
        return ""

    processed_types.add(name)

    namespace, _ = get_namespace_parts(name)
    go_type_name = sanitize_go_name(name)  # Full name for Go

    kind = type_def.get("kind", "")

    if kind == "enum":
        return process_enum(name, type_def)

    if kind == "union":
        # Go has no sum types: any of the members.
        result = format_description(type_def.get("description", ""))
        members = ", ".join(type_def.get("anyOf") or [])
        result += f"// One of: {members}.\n" if members else ""
        result += f"type {go_type_name} = interface{{}}\n"
        if namespace:
            namespace_declarations.setdefault(namespace, []).append(result)
            return ""
        return result

    properties = {}

    if "properties" in type_def:
        properties.update(type_def["properties"])

    if "static" in type_def:
        properties.update(type_def["static"])

    result = format_description(type_def.get("description", ""))

    result += f"type {go_type_name} struct {{\n"

    for prop_name, prop_def in properties.items():
        prop_type = prop_def.get("type", "interface{}")
        prop_desc = prop_def.get("description", "")
        field_name = sanitize_field_name(prop_name)

        go_prop_type = map_type(prop_type)

        if prop_desc:
            result += f"\t// {' '.join(prop_desc.split())}\n"
        result += f'\t{field_name} {go_prop_type} `json:"{prop_name}"`\n'

    record_fields = kind == "record" and bool(type_def.get("fields"))
    if record_fields:
        result += process_record_fields(type_def)

    if not properties and not record_fields:
        result += "\t// No fields defined\n"

    result += "}\n"
    if record_fields:
        result += literal_constants(go_type_name, type_def)

    if "instance" in type_def:
        instance_methods = type_def["instance"]
        if instance_methods:
            result += "\n// Methods for " + go_type_name + "\n"

        for method_name, method_def in instance_methods.items():
            params = method_def.get("params", [])
            returns = method_def.get("returns", "")
            desc = method_def.get("description", "")

            param_list = []
            for param in params:
                param_name = param.get("name", "param")
                param_type = param.get("type", "interface{}")
                sanitized_name = re.sub(r"[^\w]", "_", param_name)
                if sanitized_name in GO_KEYWORDS:
                    sanitized_name += "_"
                param_list.append(f"{sanitized_name} {map_type(param_type)}")

            return_type = ""
            if returns and returns != "void":
                return_type = map_type(returns)
                if return_type:
                    return_type = " " + return_type

            if desc:
                result += f"// {' '.join(desc.split())}\n"
            result += f"func (r *{go_type_name}) {sanitize_field_name(method_name)}({', '.join(param_list)}){return_type} {{\n"
            result += "\t// Method implementation would go here\n"
            result += '\tpanic("Not implemented")\n'
            result += "}\n"

    if namespace:
        if namespace not in namespace_declarations:
            namespace_declarations[namespace] = []
        namespace_declarations[namespace].append(result)
        return ""

    return result


def generate_go_package(schema: dict[str, Any], package_name: str) -> str:
    """Generate Go package with all types"""
    result = f"// Package {package_name} provides types for the DCS World API\n"
    result += "// Generated from DCS World Schema - DO NOT EDIT\n\n"
    result += f"package {package_name}\n\n"

    enums = []
    structs = []

    if "types" in schema:
        for type_name, type_def in sorted(schema["types"].items()):
            # Namespaced (dotted) types are collected into namespace_declarations
            if type_def.get("kind", "") == "enum":
                enums.append(process_struct(type_name, type_def))
            else:
                structs.append(process_struct(type_name, type_def))

    if "globals" in schema:
        for global_name, global_def in sorted(schema["globals"].items()):
            props = {}

            if "properties" in global_def:
                props.update(global_def["properties"])
            if "static" in global_def:
                props.update(global_def["static"])

            global_def_dict = {
                "properties": props,
                "description": global_def.get(
                    "description", f"{global_name} global namespace"
                ),
            }

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

    for namespace, types in sorted(namespace_declarations.items()):
        result += f"// Namespace: {namespace}\n"
        for type_def in types:
            result += type_def + "\n"

    return result


def export_to_golang(
    schema: dict[str, Any], output_path: str, package_name: str = "dcsapi"
) -> None:
    """Export schema to Go code"""
    schema = api_spec(schema)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Reset global state
    processed_types.clear()
    namespace_declarations.clear()

    go_code = generate_go_package(schema, package_name)

    with Path(output_path).open("w", encoding="utf-8") as f:
        f.write(go_code)

    print(f"Go code exported to {output_path}")


def main() -> None:
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
        schema = load_json(Path(args.schema))
        export_to_golang(schema, args.output, args.package)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
