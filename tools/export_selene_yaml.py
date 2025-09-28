import argparse
import json
import os
from typing import Any, Dict, Iterable, List, Tuple

try:
    import yaml  # type: ignore
except Exception as exc:  # noqa: BLE001
    raise RuntimeError(
        "PyYAML is required to export Selene YAML. Add pyyaml to dependencies."
    ) from exc


PRIMITIVE_TYPE_MAP: Dict[str, str] = {
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


def load_schema(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def normalize_arg_type(type_string: str) -> Tuple[str, Any]:
    t = (type_string or "").strip()
    if not t:
        return ("primitive", "any")
    if t == "...":
        return ("primitive", "...")
    if "|" in t or "," in t or "[" in t or "]" in t:
        return ("display", {"display": t})
    mapped = PRIMITIVE_TYPE_MAP.get(t.lower())
    if mapped is not None:
        return ("primitive", mapped)
    return ("display", {"display": t})


def build_function_args(params: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for p in params:
        type_str = p.get("type") or p.get("luaType") or "any"
        required = not bool(p.get("optional") or (p.get("required") is False))
        kind, value = normalize_arg_type(type_str)
        arg: Dict[str, Any] = {}
        if kind == "primitive":
            arg["type"] = value
        else:
            arg["type"] = value
        if not required:
            arg["required"] = False
        out.append(arg)
    return out


def export_to_selene_yaml(schema: Dict[str, Any]) -> Dict[str, Any]:
    globals_out: Dict[str, Any] = {}

    globals_def: Dict[str, Any] = schema.get("globals", {})

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
                nested_static = (prop_def.get("static") or {})
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

    # Export enums as read-only properties for each constant
    types_def: Dict[str, Any] = schema.get("types", {})
    for type_name, type_def in sorted(types_def.items()):
        if not isinstance(type_def, dict):
            continue
        if (type_def.get("kind") or "").lower() != "enum":
            continue
        values = type_def.get("values")
        if isinstance(values, dict):
            for const_name in values.keys():
                const_key = f"{type_name}.{const_name}"
                globals_out[const_key] = {"property": "read-only"}

    doc: Dict[str, Any] = {
        "base": "lua51",
        "name": "dcs-world",
        "globals": globals_out,
    }
    return doc


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

    schema = load_schema(args.schema)
    data = export_to_selene_yaml(schema)
    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
    print(f"Selene YAML exported to {args.output}")


if __name__ == "__main__":
    main()
