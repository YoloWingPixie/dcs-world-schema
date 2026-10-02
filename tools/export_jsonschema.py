"""Export the ``Entity.*`` types of the merged spec as one draft-07 JSON Schema.

Every ``Entity.*`` type (and every type they reference) becomes an entry of
``definitions``; validate a record with ``{"$ref": "#/definitions/<type>"}``
against the document. Mapping:

  string / number / boolean     -> that JSON type
  any / table / function        -> {} (permissive)
  nil / void                    -> null
  X[]                           -> array of X
  A | B (| nil)                 -> anyOf (nullable)
  enum type                     -> {"enum": [values], "x-values": {name: value}}
  record type                   -> closed object; ``_source`` (provenance) always allowed
  field ``ref``                 -> ``"x-ref": [entity types]`` on each string it holds

Each definition carries its type's ``title`` (the type name) and
``description``, each property its field's ``description``; annotations only,
validation is unchanged. An undefined type name or unsupported kind is an error.

``--editor-dir`` also writes one self-contained schema per series
(``<series>.schema.json``, validating one record file) and
``manifest.schema.json`` for editors; ``--vscode-settings`` writes the VS Code
``json.schemas`` mapping of ``dcs-world-reference`` files to them, generated
from ``common.SERIES`` (the committed ``.vscode/settings.json``).

    uv run python -m tools.export_jsonschema <spec.json> --output <schema.json>
        [--editor-dir DIR]
    uv run python -m tools.export_jsonschema --vscode-settings .vscode/settings.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from tools.datamine.common import MANIFEST, MANIFEST_TYPE, REFERENCE_DATA_DIR, SERIES
from tools.spec_types import (
    ENTITY_PREFIX,
    Array,
    Literal,
    Primitive,
    Ref,
    TypeNode,
    Union,
    format_type,
    members,
    parse_type,
    strip_null,
)

ENUM_NAMES = "x-values"  # an enum's {name: value} map, kept beside "enum"
X_REF = "x-ref"  # the entity types whose ids a string holds
SOURCE_FIELD = "_source"
SOURCE_DESCRIPTION = "Provenance of fields not datamined as-is: field -> source."
EDITOR_DIR = "dist/schemas"  # --editor-dir as the VS Code mapping points at it
MANIFEST_SCHEMA = "manifest"
_PRIMITIVE_SCHEMA: dict[str, dict[str, Any]] = {
    "string": {"type": "string"},
    "number": {"type": "number"},
    "boolean": {"type": "boolean"},
    "nil": {"type": "null"},
    "void": {"type": "null"},
}


class _Exporter:
    def __init__(self, types: dict[str, Any]) -> None:
        self.types = types
        self.defs: dict[str, Any] = {}

    def ref(self, name: str) -> dict[str, Any]:
        if name not in self.defs:
            self.defs[name] = {}  # guards recursion
            self.defs[name] = _annotate(
                self._define(name), name, self.types[name].get("description")
            )
        return {"$ref": f"#/definitions/{name}"}

    def _define(self, name: str) -> dict[str, Any]:
        spec = self.types.get(name)
        if not isinstance(spec, dict):
            raise KeyError(f"type {name!r} is not defined in the spec")
        kind = spec.get("kind")
        if kind == "enum":
            values = spec.get("values", {})
            return {"enum": list(values.values()), ENUM_NAMES: values}
        if kind == "array":
            return {"type": "array", "items": self.type_schema(spec["arrayOf"])}
        if kind != "record":
            raise ValueError(f"type {name!r} has unsupported kind {kind!r}")
        props = {
            f: _annotate(self.field_schema(name, f, s), None, s.get("description"))
            for f, s in spec["fields"].items()
        }
        props.setdefault(SOURCE_FIELD, {"description": SOURCE_DESCRIPTION})
        return {
            "type": "object",
            "properties": props,
            "required": list(spec.get("required") or []),
            "additionalProperties": False,
        }

    def field_schema(
        self, owner: str, name: str, spec: dict[str, Any]
    ) -> dict[str, Any]:
        schema = self.type_schema(spec["type"])
        if "ref" in spec:
            targets: list[str] = []
            for t in members(parse_type(spec["ref"])):
                if not (
                    isinstance(t, Ref)
                    and t.name.startswith(ENTITY_PREFIX)
                    and t.name in self.types
                ):
                    raise KeyError(
                        f"{owner}.{name}: ref {format_type(t)!r} is no entity type"
                    )
                targets.append(t.name)
            if not _mark_strings(schema, targets):
                raise ValueError(f"{owner}.{name}: ref on a field holding no string")
        return schema

    def type_schema(self, typ: str) -> dict[str, Any]:
        return self.node_schema(parse_type(typ))

    def node_schema(self, node: TypeNode) -> dict[str, Any]:
        if isinstance(node, Union):
            non_null, nullable = strip_null(node)
            branches = (
                [self.node_schema(m) for m in members(non_null)] if non_null else []
            )
            if nullable:
                branches.append({"type": "null"})
            return branches[0] if len(branches) == 1 else {"anyOf": branches}
        if isinstance(node, Array):
            return {"type": "array", "items": self.node_schema(node.item)}
        if isinstance(node, Literal):
            return {"type": "string", "const": node.value}
        if isinstance(node, Primitive):
            return dict(_PRIMITIVE_SCHEMA.get(node.name, {}))
        if isinstance(node, Ref) and node.name in self.types:
            return self.ref(node.name)
        raise KeyError(f"unknown type {format_type(node)!r}")


def _annotate(
    schema: dict[str, Any], title: str | None, description: Any
) -> dict[str, Any]:
    """``schema`` with ``title`` and ``description`` (when given) first."""
    notes: dict[str, Any] = {}
    if title:
        notes["title"] = title
    if isinstance(description, str) and description.strip():
        notes["description"] = description.strip()
    return {**notes, **schema}


def _mark_strings(schema: dict[str, Any], targets: list[str]) -> bool:
    """Put ``x-ref`` on every string schema in ``schema`` (through arrays and
    unions); whether there was one."""
    if schema.get("type") == "string":
        schema[X_REF] = targets
        return True
    if schema.get("type") == "array":
        return _mark_strings(schema["items"], targets)
    # Mark every member, so no short-circuit.
    marked = [_mark_strings(s, targets) for s in schema.get("anyOf", [])]
    return any(marked)


def export(types: dict[str, Any]) -> dict[str, Any]:
    """The JSON Schema document for every ``Entity.*`` type in ``types``."""
    exporter = _Exporter(types)
    for name in sorted(types):
        if name.startswith(ENTITY_PREFIX):
            exporter.ref(name)
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "DCS World entity reference data",
        "definitions": dict(sorted(exporter.defs.items())),
    }


def schema_for(document: dict[str, Any], type_name: str) -> dict[str, Any]:
    """A schema validating one ``type_name`` record against ``document``."""
    if type_name not in document["definitions"]:
        raise KeyError(f"type {type_name!r} is not in the JSON Schema")
    return {**document, "$ref": f"#/definitions/{type_name}"}


def editor_schemas(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """``{file stem: schema}``: one self-contained schema per series validating
    one record file, and one for ``manifest.json``."""
    types = {s.name: s.type_name for s in SERIES.values()}
    types[MANIFEST_SCHEMA] = MANIFEST_TYPE
    out: dict[str, dict[str, Any]] = {}
    for stem, type_name in types.items():
        definition = document["definitions"][type_name]
        schema = schema_for(document, type_name)
        schema["title"] = f"DCS World reference: {stem} ({type_name})"
        if "description" in definition:
            schema["description"] = definition["description"]
        out[stem] = schema
    return out


def vscode_settings(editor_dir: str = EDITOR_DIR) -> dict[str, Any]:
    """VS Code ``json.schemas`` mapping each series' record files (and
    ``manifest.json``) under ``dcs-world-reference/latest/`` to its editor
    schema; a grouped series sits one directory deeper per group field."""
    root = REFERENCE_DATA_DIR.name
    entries = [
        {
            "fileMatch": [f"**/{root}/*/{MANIFEST}"],
            "url": f"./{editor_dir}/{MANIFEST_SCHEMA}.schema.json",
        }
    ]
    for series in SERIES.values():
        groups = "*/" * len(series.group_fields)
        entries.append(
            {
                "fileMatch": [f"**/{root}/*/{series.name}/{groups}*.json"],
                "url": f"./{editor_dir}/{series.name}.schema.json",
            }
        )
    return {"json.schemas": entries}


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("spec", type=Path, nargs="?", help="Merged spec JSON.")
    parser.add_argument("--output", type=Path, help="The entity JSON Schema.")
    parser.add_argument(
        "--editor-dir", type=Path, help="Also write the per-series editor schemas."
    )
    parser.add_argument(
        "--vscode-settings", type=Path, help="Write the VS Code json.schemas mapping."
    )
    args = parser.parse_args()
    if args.vscode_settings:
        _write_json(args.vscode_settings, vscode_settings())
        print(f"Wrote the VS Code schema mapping to {args.vscode_settings}")
        if args.spec is None and args.output is None:
            return 0
    if args.spec is None or args.output is None:
        parser.error("give the spec and --output (or only --vscode-settings)")
    types = json.loads(args.spec.read_text(encoding="utf-8")).get("types", {})
    document = export(types)
    _write_json(args.output, document)
    print(f"Wrote {len(document['definitions'])} definitions to {args.output}")
    if args.editor_dir:
        schemas = editor_schemas(document)
        for stem, schema in schemas.items():
            _write_json(args.editor_dir / f"{stem}.schema.json", schema)
        print(f"Wrote {len(schemas)} editor schemas to {args.editor_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
