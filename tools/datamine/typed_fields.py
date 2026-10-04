"""Shared machinery of the typed (normalized) object-configuration fields.

A typed block holds the named fields read from one DCS table (the default
reading of ``lua_reader``): each ``F`` spec copies one DCS key verbatim into a
camelCase field when the value has the expected JSON kind. Values are never
rounded or converted. Keys without a typed field, and values of another kind,
are not copied: they are only in the ``_G`` dump.

Used by ``weapon_flight`` and the ``*_config`` modules.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class F:
    """A typed field: DCS ``key`` -> ``name`` of JSON ``kind`` (``number``,
    ``numbers``, ``rows``, ``boolean``, ``string``, ``strings``) and its
    ``unit`` when known (the field name then carries it as a suffix)."""

    key: str
    name: str
    kind: str = "number"
    unit: str | None = None


def camel(key: str) -> str:
    """DCS key -> camelCase field name (``table_scale`` -> ``tableScale``,
    ``Cx0`` -> ``cx0``, ``A1trim`` -> ``a1Trim``)."""
    parts = [p for p in re.split(r"_+", key) if p]
    head, *rest = parts
    return head[0].lower() + head[1:] + "".join(p[0].upper() + p[1:] for p in rest)


def is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def fits(kind: str, value: Any) -> bool:
    """Whether ``value`` has the JSON ``kind`` of a typed field."""
    if kind == "number":
        return is_number(value)
    if kind == "numbers":
        return isinstance(value, list) and bool(value) and all(map(is_number, value))
    if kind == "rows":
        return (
            isinstance(value, list)
            and bool(value)
            and all(fits("numbers", row) for row in value)
        )
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "string":
        return isinstance(value, str)
    if kind == "strings":
        return (
            isinstance(value, list)
            and bool(value)
            and all(isinstance(v, str) for v in value)
        )
    raise ValueError(kind)


def typed_block(
    raw: dict[str, Any], specs: Iterable[F], skip: Iterable[str] = ()
) -> dict[str, Any]:
    """The typed fields of the DCS block ``raw``: the keys of ``specs`` (minus
    ``skip``, typed elsewhere) whose values fit their kind."""
    skipped = set(skip)
    return {
        f.name: raw[f.key]
        for f in specs
        if f.key in raw and f.key not in skipped and fits(f.kind, raw[f.key])
    }
