import argparse
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from tools.datamine.common import load_json
from tools.spec_types import (
    Primitive,
    Ref,
    api_spec,
    is_literal_union,
    is_type_only,
    parse_type,
    runtime_roots,
)

PRIMITIVE_TYPE_MAP: dict[str, str] = {
    "string": "string",
    "number": "number",
    "boolean": "bool",
    "bool": "bool",
    "table": "table",
    "nil": "nil",
    "any": "any",
    "function": "function",
    "...": "...",
}


def normalize_arg_type(type_string: str) -> tuple[str, Any]:
    t = (type_string or "").strip()
    if not t:
        return ("primitive", "any")
    if t == "...":
        return ("primitive", "...")
    node = parse_type(t)
    # A string literal, or a union of them, is a string to Selene.
    if is_literal_union(node):
        return ("primitive", "string")
    if isinstance(node, (Primitive, Ref)):
        mapped = PRIMITIVE_TYPE_MAP.get(node.name.lower())
        if mapped is not None:
            return ("primitive", mapped)
    return ("display", {"display": t})


def build_function_args(params: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in params:
        type_str = p.get("type") or p.get("luaType") or "any"
        required = not bool(p.get("optional") or (p.get("required") is False))
        kind, value = normalize_arg_type(type_str)
        arg: dict[str, Any] = {}
        if kind == "primitive":
            arg["type"] = value
        else:
            arg["type"] = value
        if not required:
            arg["required"] = False
        out.append(arg)
    return out


def export_to_selene_yaml(schema: dict[str, Any]) -> dict[str, Any]:
    schema = api_spec(schema)
    globals_out: dict[str, Any] = {}

    globals_def: dict[str, Any] = schema.get("globals", {})

    for global_name, global_def in sorted(globals_def.items()):
        # Properties
        for prop_name, prop_def in (global_def.get("properties") or {}).items():
            key = f"{global_name}.{prop_name}"
            prop_type = (prop_def or {}).get("type")
            if isinstance(prop_type, str) and prop_type.lower() == "table":
                # Allow nested fields on table-like properties
                globals_out[key] = {"property": "new-fields"}
                globals_out[f"{key}.*"] = {"property": "full-write"}
                globals_out[f"{key}.*.*"] = {"property": "full-write"}
            else:
                globals_out[key] = {"property": "read-only"}

            # If the property defines nested static functions, emit them as functions
            if isinstance(prop_def, dict):
                nested_static = prop_def.get("static") or {}
                if isinstance(nested_static, dict):
                    for func_name, func_def in nested_static.items():
                        params = func_def.get("params") or []
                        func_key = f"{key}.{func_name}"
                        globals_out[func_key] = {
                            "args": build_function_args(params),
                        }

        # Static entries
        for static_name, static_def in (global_def.get("static") or {}).items():
            params = static_def.get("params")
            key = f"{global_name}.{static_name}"
            if isinstance(params, list):
                globals_out[key] = {
                    "args": build_function_args(params),
                }
            else:
                static_type = static_def.get("type")
                if isinstance(static_type, str) and static_type.lower() == "table":
                    globals_out[key] = {"property": "new-fields"}
                    globals_out[f"{key}.*"] = {"property": "full-write"}
                    globals_out[f"{key}.*.*"] = {"property": "full-write"}
                else:
                    globals_out[key] = {"property": "read-only"}

        # Instance methods (colon calls)
        for method_name, method_def in (global_def.get("instance") or {}).items():
            params = method_def.get("params") or []
            key = f"{global_name}.{method_name}"
            globals_out[key] = {
                "method": True,
                "args": build_function_args(params),
            }

    # Export enums as read-only properties for each constant, but only where
    # DCS has the table: a type-only enum (DcsTask.OptionName) is no global
    types_def: dict[str, Any] = schema.get("types", {})
    roots = runtime_roots(schema)
    for type_name, type_def in sorted(types_def.items()):
        if not isinstance(type_def, dict) or is_type_only(type_name, roots):
            continue
        if (type_def.get("kind") or "").lower() != "enum":
            continue
        values = type_def.get("values")
        if isinstance(values, dict):
            for const_name in values:
                const_key = f"{type_name}.{const_name}"
                globals_out[const_key] = {"property": "read-only"}

    return {"base": "lua51", "name": "dcs-world", "globals": globals_out}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export DCS schema to Selene standard library (YAML)"
    )
    parser.add_argument("schema", help="Path to the DCS schema JSON file")
    parser.add_argument(
        "--output",
        "-o",
        default="dist/dcs-world-selene.yml",
        help="Output Selene YAML file",
    )
    args = parser.parse_args()

    schema = load_json(Path(args.schema))
    data = export_to_selene_yaml(schema)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
    print(f"Selene YAML exported to {args.output}")


if __name__ == "__main__":
    main()
