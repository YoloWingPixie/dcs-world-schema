"""Data-shaped types for the reference-data records, from the entity JSON Schema.

The entity JSON Schema (``tools/export_jsonschema.py``) is what ``task
validate-data`` checks every record against, so types generated from it describe
the JSON exactly: a record type lists its properties (absent from ``required``:
optional), arrays, unions, ``$ref``s and string literals (``const``) map one to
one. Enums become unions of their literal values plus a name -> value table.
``_source`` (provenance, open in the JSON Schema) is typed as a string map, the
shape every record has. Descriptions come from the merged spec. Names drop the
``Entity.`` prefix (``country.id`` -> ``CountryId``) for TypeScript and Python;
EmmyLua keeps the spec names.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from keyword import iskeyword
from typing import Any

from tools.export_jsonschema import ENUM_NAMES, X_REF
from tools.spec_types import (
    ENTITY_PREFIX,
    STRING,
    Array,
    Literal,
    Map,
    Primitive,
    Ref,
    TypeNode,
    Union,
    union_of,
)

from .lua_data import is_lua_name

SOURCE_FIELD = "_source"
ANY = Primitive("any")
# JSON Schema ``type`` -> typeRef primitive.
_SCHEMA_PRIMITIVES = {
    "string": "string",
    "number": "number",
    "boolean": "boolean",
    "null": "nil",
}
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class Field:
    name: str
    node: dict[str, Any]
    required: bool
    doc: str


@dataclass(frozen=True)
class Definition:
    name: str  # spec name, e.g. ``Entity.Beacon``
    kind: str  # record | enum | array
    doc: str
    fields: tuple[Field, ...] = ()
    values: tuple[tuple[str, Any], ...] = ()  # enum (name, value)
    items: dict[str, Any] | None = None  # array item schema


def pascal(name: str) -> str:
    """``country.id`` / ``gun_ammo`` -> ``CountryId`` / ``GunAmmo``."""
    return "".join(p[:1].upper() + p[1:] for p in re.split(r"[._]", name))


def type_name(spec_name: str) -> str:
    """``Entity.Beacon`` -> ``Beacon``; ``country.id`` -> ``CountryId``."""
    if spec_name.startswith(ENTITY_PREFIX):
        return spec_name[len(ENTITY_PREFIX) :]
    return pascal(spec_name)


def ref_name(node: dict[str, Any]) -> str:
    ref: str = node["$ref"]
    return ref.rsplit("/", 1)[-1]


def definitions(schema: dict[str, Any], spec: dict[str, Any]) -> list[Definition]:
    """Every definition of the entity JSON Schema, sorted by name."""
    spec_types = spec.get("types", {})
    out: list[Definition] = []
    for name, node in sorted(schema["definitions"].items()):
        spec_type = spec_types.get(name, {})
        doc = spec_type.get("description", "")
        if "enum" in node:
            names = node.get(ENUM_NAMES) or {str(v): v for v in node["enum"]}
            out.append(Definition(name, "enum", doc, values=tuple(names.items())))
        elif node.get("type") == "array":
            out.append(Definition(name, "array", doc, items=node["items"]))
        elif node.get("type") == "object":
            required = set(node.get("required", []))
            spec_fields = spec_type.get("fields", {})
            fields = tuple(
                Field(
                    f,
                    sub,
                    f in required,
                    spec_fields.get(f, {}).get("description", "")
                    if f != SOURCE_FIELD
                    else "Provenance of fields not datamined as-is: field -> source.",
                )
                for f, sub in node["properties"].items()
            )
            out.append(Definition(name, "record", doc, fields=fields))
        else:
            raise ValueError(f"unsupported definition {name!r}: {node}")
    return out


def schema_type(node: dict[str, Any]) -> TypeNode:
    """The typeRef tree of an entity JSON Schema node: an annotations-only node
    is ``any``, ``null`` is ``nil``, a string map (``additionalProperties``) a
    ``map``; anything else is an error."""
    if not node.keys() - {"title", "description", X_REF}:  # any value
        return ANY
    if "const" in node:  # a string literal typeRef
        return Literal(node["const"])
    if "$ref" in node:
        return Ref(ref_name(node))
    if "anyOf" in node:
        union = union_of([schema_type(b) for b in node["anyOf"]])
        if union is None:
            raise ValueError(f"empty anyOf in schema node {node}")
        return union
    t = node.get("type")
    if t == "array":
        return Array(schema_type(node["items"]))
    if t == "object" and "additionalProperties" in node:
        return Map(STRING, schema_type(node["additionalProperties"]))
    if t in _SCHEMA_PRIMITIVES:
        return Primitive(_SCHEMA_PRIMITIVES[t])
    raise ValueError(f"unsupported schema node {node}")


def field_type(f: Field) -> TypeNode:
    """The type of a record field (``_source``: a string map)."""
    if f.name == SOURCE_FIELD:
        return Map(STRING, STRING)
    return schema_type(f.node)


def _render(
    node: TypeNode,
    prim: dict[str, str],
    ref: Callable[[str], str],
    array: Callable[[TypeNode, str], str],
    union: Callable[[list[str]], str],
    mapping: Callable[[str], str],
    const: Callable[[str], str] = json.dumps,
) -> str:
    def go(n: TypeNode) -> str:
        if isinstance(n, Primitive):
            return prim[n.name]
        if isinstance(n, Literal):
            return const(n.value)
        if isinstance(n, Ref):
            return ref(n.name)
        if isinstance(n, Union):
            return union([go(m) for m in n.members])
        if isinstance(n, Array):
            return array(n.item, go(n.item))
        return mapping(go(n.value))  # Map: string keys

    return go(node)


# TypeScript ---------------------------------------------------------------

_TS_PRIM = {
    "string": "string",
    "number": "number",
    "boolean": "boolean",
    "nil": "null",
    "any": "unknown",
}


def _ts_doc(doc: str, indent: str = "") -> list[str]:
    if not doc:
        return []
    return [f"{indent}/** {doc.replace('*/', '*\\/')} */"]


def ts_type(node: TypeNode) -> str:
    return _render(
        node,
        _TS_PRIM,
        type_name,
        lambda _, t: f"Array<{t}>",
        lambda ts: " | ".join(ts),
        lambda v: f"Record<string, {v}>",
    )


def typescript(defs: list[Definition]) -> str:
    lines = ["// Generated by tools/package/entity_types.py; do not edit.", ""]
    for d in defs:
        name = type_name(d.name)
        lines += _ts_doc(d.doc)
        if d.kind == "enum":
            lines.append(
                f"export type {name} = "
                + " | ".join(json.dumps(v) for _, v in d.values)
                + ";"
            )
            lines += _ts_doc(f"`{d.name}` values by DCS name.")
            lines.append(f"export const {name} = {{")
            for k, v in d.values:
                key = k if _IDENT.match(k) else json.dumps(k)
                lines.append(f"  {key}: {json.dumps(v)},")
            lines.append("} as const;")
        elif d.kind == "array":
            assert d.items is not None
            lines.append(
                f"export type {name} = Array<{ts_type(schema_type(d.items))}>;"
            )
        else:
            lines.append(f"export interface {name} {{")
            for f in d.fields:
                key = f.name if _IDENT.match(f.name) else json.dumps(f.name)
                opt = "" if f.required else "?"
                lines += _ts_doc(f.doc, "  ")
                lines.append(f"  {key}{opt}: {ts_type(field_type(f))};")
            lines.append("}")
        lines.append("")
    return "\n".join(lines)


# Python -------------------------------------------------------------------

_PY_PRIM = {
    "string": "str",
    "number": "float",
    "boolean": "bool",
    "nil": "None",
    "any": "object",
}


def py_type(node: TypeNode) -> str:
    """A type expression that evaluates at import time in any definition order:
    references to generated names are quoted."""
    return _render(
        node,
        _PY_PRIM,
        lambda n: json.dumps(type_name(n)),
        lambda _, t: f"list[{t}]",
        lambda ts: f"Union[{', '.join(ts)}]",
        lambda v: f"dict[str, {v}]",
        lambda v: f"Literal[{json.dumps(v)}]",
    )


def _py_doc(doc: str) -> str:
    return doc.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')


def python(defs: list[Definition]) -> str:
    lines = [
        '"""Record types of the DCS World reference data.',
        "",
        "Generated by tools/package/entity_types.py; do not edit.",
        '"""',
        "",
        "from types import MappingProxyType",
        "from typing import Final, Literal, Mapping, NotRequired, TypedDict, Union",
    ]
    exported: list[str] = []
    for d in defs:
        name = type_name(d.name)
        exported.append(name)
        lines += ["", ""]
        if d.kind == "enum":
            literal = ", ".join(json.dumps(v) for _, v in d.values)
            lines.append(f"{name} = Literal[{literal}]")
            if d.doc:
                lines.append(f'"""{_py_doc(d.doc)}"""')
            table = f"{name}Values"
            exported.append(table)
            lines.append(f"{table}: Final[Mapping[str, {name}]] = MappingProxyType({{")
            for k, v in d.values:
                lines.append(f"    {json.dumps(k)}: {json.dumps(v)},")
            lines.append("})")
        elif d.kind == "array":
            assert d.items is not None
            lines.append(f"{name} = list[{py_type(schema_type(d.items))}]")
            if d.doc:
                lines.append(f'"""{_py_doc(d.doc)}"""')
        else:

            def ann(f: Field) -> str:
                t = py_type(field_type(f))
                return t if f.required else f"NotRequired[{t}]"

            if all(_IDENT.match(f.name) and not iskeyword(f.name) for f in d.fields):
                lines.append(f"class {name}(TypedDict):")
                if d.doc:
                    lines.append(f'    """{_py_doc(d.doc)}"""')
                for f in d.fields:
                    if f.doc:
                        lines.append(f"    #: {f.doc}")
                    lines.append(f"    {f.name}: {ann(f)}")
                if not d.doc and not d.fields:
                    lines.append("    pass")
            else:
                # A field name that is not a Python identifier: functional form.
                lines.append(f"{name} = TypedDict(")
                lines.append(f"    {json.dumps(name)},")
                lines.append("    {")
                for f in d.fields:
                    lines.append(f"        {json.dumps(f.name)}: {ann(f)},")
                lines.append("    },")
                lines.append(")")
                if d.doc:
                    lines.append(f'"""{_py_doc(d.doc)}"""')
    lines += ["", "", "__all__ = ["]
    lines += [f"    {json.dumps(n)}," for n in exported]
    lines += ["]", ""]
    return "\n".join(lines)


# EmmyLua ------------------------------------------------------------------

_LUA_PRIM = {
    "string": "string",
    "number": "number",
    "boolean": "boolean",
    "nil": "nil",
    "any": "any",
}


def lua_type(node: TypeNode) -> str:
    return _render(
        node,
        _LUA_PRIM,
        lambda n: n,
        lambda item, t: f"({t})[]" if isinstance(item, Union) else f"{t}[]",
        lambda ts: "|".join(ts),
        lambda v: f"table<string, {v}>",
    )


def _lua_doc(doc: str) -> str:
    return " ".join(doc.split())


def emmylua(defs: list[Definition]) -> str:
    lines = [
        "---@meta",
        "-- Generated by tools/package/entity_types.py; do not edit.",
        "",
    ]
    for d in defs:
        if d.doc:
            lines.append(f"---{_lua_doc(d.doc)}")
        if d.kind == "enum":
            lines.append(
                f"---@alias {d.name} " + "|".join(json.dumps(v) for _, v in d.values)
            )
        elif d.kind == "array":
            assert d.items is not None
            lines.append(f"---@alias {d.name} {lua_type(Array(schema_type(d.items)))}")
        else:
            lines.append(f"---@class {d.name}")
            for f in d.fields:
                key = f.name if is_lua_name(f.name) else f"[{json.dumps(f.name)}]"
                opt = "" if f.required else "?"
                doc = f" {_lua_doc(f.doc)}" if f.doc else ""
                lines.append(f"---@field {key}{opt} {lua_type(field_type(f))}{doc}")
        lines.append("")
    return "\n".join(lines)
