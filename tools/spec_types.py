"""Type-reference vocabulary shared by the spec tools.

A typeRef (``"Unit | nil"``, ``"number[]"``, ``"map<string, Vec3>"``,
``'"on" | "off"'``) is parsed once by ``parse_type`` into a tree of the node
kinds below; the exporters map nodes, never strings. Grammar::

    union   := postfix ("|" postfix)*
    postfix := atom ("[]")*
    atom    := literal | "map<" union ["," union] ">" | name | "(" union ")"
    literal := '"' chars without '"', '\\' or '|' '"'
    name    := [A-Za-z_][A-Za-z0-9_.]*

``map<V>`` is ``map<string, V>``. ``nil`` / ``void`` stay ``Primitive``
members of a ``Union`` (in their written position, which some outputs keep);
``strip_null`` splits them off. Anything else raises ``TypeRefError`` naming
the typeRef.
"""

from __future__ import annotations

from collections.abc import Iterator, Set
from dataclasses import dataclass
from functools import cache
from typing import Any

# Built-in type names a typeRef may use; anything else must be a defined type.
PRIMITIVES: frozenset[str] = frozenset(
    {"string", "number", "boolean", "table", "function", "any", "nil", "void"}
)
NULL_TYPES: frozenset[str] = frozenset({"nil", "void"})
# Reference-data record types: exported only as the entity JSON Schema
# (export_jsonschema) and the package record types, not with the scripting API.
ENTITY_PREFIX = "Entity."
# Shapes of the _G database tables (tools/datamine/dcs_database_types.py): kept
# in the schema source, left out of the merged schema and the API outputs.
DCS_DB_PREFIX = "DcsDb."
# DCS globals the spec has types under (``country.id``) but no global entry for.
TYPE_ROOT_GLOBALS: frozenset[str] = frozenset({"country"})


@dataclass(frozen=True)
class Primitive:
    """A built-in type (``PRIMITIVES``)."""

    name: str


@dataclass(frozen=True)
class Ref:
    """A defined type, global or class, by name."""

    name: str


@dataclass(frozen=True)
class Literal:
    """A string literal: exactly ``value``."""

    value: str


@dataclass(frozen=True)
class Array:
    item: TypeNode


@dataclass(frozen=True)
class Map:
    key: TypeNode
    value: TypeNode


@dataclass(frozen=True)
class Union:
    """Two or more members, none a ``Union``, without duplicates."""

    members: tuple[TypeNode, ...]


TypeNode = Primitive | Ref | Literal | Array | Map | Union
STRING = Primitive("string")


class TypeRefError(ValueError):
    """An unparseable or unsupported typeRef."""


def without_types(spec: dict[str, Any], *prefixes: str) -> dict[str, Any]:
    """``spec`` without the types named with any of ``prefixes``."""
    types = spec.get("types", {})
    return {
        **spec,
        "types": {n: t for n, t in types.items() if not n.startswith(prefixes)},
    }


def api_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """``spec`` as the API outputs export it: without its ``Entity.*`` and
    ``DcsDb.*`` types."""
    return without_types(spec, ENTITY_PREFIX, DCS_DB_PREFIX)


def runtime_roots(spec: dict[str, Any]) -> frozenset[str]:
    """Names of the DCS globals ``spec`` describes."""
    return frozenset(spec.get("globals", {})) | TYPE_ROOT_GLOBALS


def is_type_only(name: str, roots: Set[str]) -> bool:
    """Whether type ``name`` is only a type: its root (``DcsTask`` of
    ``DcsTask.OptionName``, an undotted name itself) is no DCS global in
    ``roots``, so no table of that name exists at runtime."""
    return name.split(".", 1)[0] not in roots


# Parsing -----------------------------------------------------------------


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    def fail(self, why: str) -> TypeRefError:
        return TypeRefError(f"typeRef {self.text!r}: {why} at offset {self.pos}")

    def skip(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def peek(self, token: str) -> bool:
        self.skip()
        return self.text.startswith(token, self.pos)

    def take(self, token: str) -> bool:
        if self.peek(token):
            self.pos += len(token)
            return True
        return False

    def expect(self, token: str) -> None:
        if not self.take(token):
            raise self.fail(f"expected {token!r}")

    def union(self) -> TypeNode:
        members: list[TypeNode] = []
        while True:
            node = self.postfix()
            for m in node.members if isinstance(node, Union) else (node,):
                if m not in members:
                    members.append(m)
            if not self.take("|"):
                break
        return members[0] if len(members) == 1 else Union(tuple(members))

    def postfix(self) -> TypeNode:
        node = self.atom()
        while self.take("[]"):
            node = Array(node)
        return node

    def atom(self) -> TypeNode:
        self.skip()
        text, start = self.text, self.pos
        if self.take('"'):
            end = text.find('"', self.pos)
            if end < 0:
                raise self.fail("unterminated string literal")
            literal = text[self.pos : end]
            if "\\" in literal or "|" in literal:
                raise self.fail("string literal holding '\\' or '|'")
            self.pos = end + 1
            return Literal(literal)
        if self.take("("):
            node = self.union()
            self.expect(")")
            return node
        if self.take("map<"):
            first = self.union()
            if self.take(","):
                key, value = first, self.union()
            else:
                key, value = STRING, first
            self.expect(">")
            return Map(key, value)
        end = start
        if end < len(text) and (text[end].isalpha() or text[end] == "_"):
            while end < len(text) and (text[end].isalnum() or text[end] in "_."):
                end += 1
        name = text[start:end]
        if not name or name.endswith(".") or ".." in name:
            raise self.fail("expected a type")
        self.pos = end
        return Primitive(name) if name in PRIMITIVES else Ref(name)


@cache
def parse_type(text: str) -> TypeNode:
    """The tree of typeRef ``text``; ``TypeRefError`` if it is not one."""
    if not isinstance(text, str):
        raise TypeRefError(f"typeRef {text!r}: not a string")
    parser = _Parser(text)
    node = parser.union()
    parser.skip()
    if parser.pos != len(text):
        raise parser.fail("unexpected text")
    return node


def format_type(node: TypeNode) -> str:
    """The canonical typeRef of ``node`` (``parse_type`` round-trips it)."""
    if isinstance(node, Primitive | Ref):
        return node.name
    if isinstance(node, Literal):
        return f'"{node.value}"'
    if isinstance(node, Array):
        item = format_type(node.item)
        return f"({item})[]" if isinstance(node.item, Union) else f"{item}[]"
    if isinstance(node, Map):
        value = format_type(node.value)
        if node.key == STRING:
            return f"map<{value}>"
        return f"map<{format_type(node.key)}, {value}>"
    return " | ".join(format_type(m) for m in node.members)


# Queries -----------------------------------------------------------------


def members(node: TypeNode) -> tuple[TypeNode, ...]:
    """The members of a union, else ``(node,)``."""
    return node.members if isinstance(node, Union) else (node,)


def union_of(nodes: list[TypeNode] | tuple[TypeNode, ...]) -> TypeNode | None:
    """The union of ``nodes`` (deduplicated; one node is itself), None if none."""
    out: list[TypeNode] = []
    for n in nodes:
        for m in members(n):
            if m not in out:
                out.append(m)
    if not out:
        return None
    return out[0] if len(out) == 1 else Union(tuple(out))


def is_null(node: TypeNode) -> bool:
    return isinstance(node, Primitive) and node.name in NULL_TYPES


def strip_null(node: TypeNode) -> tuple[TypeNode | None, bool]:
    """``node`` without its ``nil`` / ``void`` members (None if nothing else)
    and whether it had any."""
    parts = members(node)
    rest = [m for m in parts if not is_null(m)]
    return union_of(rest), len(rest) < len(parts)


def is_literal_union(node: TypeNode | None) -> bool:
    """Whether every member of ``node`` is a string literal."""
    return node is not None and all(isinstance(m, Literal) for m in members(node))


def walk(node: TypeNode) -> Iterator[TypeNode]:
    """``node`` and every node under it, depth first."""
    yield node
    if isinstance(node, Array):
        yield from walk(node.item)
    elif isinstance(node, Map):
        yield from walk(node.key)
        yield from walk(node.value)
    elif isinstance(node, Union):
        for m in node.members:
            yield from walk(m)


def type_names(node: TypeNode) -> list[str]:
    """Every primitive and type name ``node`` mentions, in order, once."""
    out: list[str] = []
    for n in walk(node):
        if isinstance(n, Primitive | Ref) and n.name not in out:
            out.append(n.name)
    return out


def union_parts(t: str) -> list[str]:
    """The canonical typeRefs of the members of typeRef ``t``."""
    return [format_type(m) for m in members(parse_type(t))]
