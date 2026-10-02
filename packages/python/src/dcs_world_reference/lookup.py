"""Reverse and name lookups over the indexes in ``data/_index/`` (built by
``tools/package/indexes.py``), each index read on first use and cached."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from functools import cache
from importlib.resources import files
from typing import Any, Final, TypedDict, cast

from . import SeriesName


class Reference(TypedDict):
    """A record referencing another: its series, id and the referencing field
    (path from the record, arrays as ``[]``)."""

    series: SeriesName
    id: str
    path: str


_ASCII_UPPER: Final = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"
)
_ASCII_SPACE: Final = " \t\n\r\f\v"


@cache
def _index(name: str) -> Any:
    path = files(__package__ or "dcs_world_reference").joinpath(
        "data", "_index", f"{name}.json"
    )
    return json.loads(path.read_text("utf-8"))


def _meta() -> Mapping[str, Any]:
    return cast(Mapping[str, Any], _index("meta"))


def _ids(index: str, key: str) -> list[str]:
    return list(cast(Mapping[str, list[str]], _index(index)).get(key, ()))


def name_key(name: str) -> str:
    """The key the name indexes use: trimmed of ASCII whitespace, ASCII
    letters lowercased."""
    return name.strip(_ASCII_SPACE).translate(_ASCII_UPPER)


def references_to(series: SeriesName, id: str) -> list[Reference]:
    """Every record referencing record ``id`` of ``series``, by any ``x-ref``
    field."""
    if series not in _meta()["references"]:
        return []
    index = cast(Mapping[str, list[Reference]], _index(f"references_{series}"))
    return list(index.get(id, ()))


def _ids_of(refs: Sequence[Reference], series: str) -> list[str]:
    return sorted({r["id"] for r in refs if r["series"] == series})


def stores_delivering(weapon_id: str) -> list[str]:
    """CLSIDs of the stores delivering weapon ``weapon_id``."""
    return _ids_of(references_to("weapons", weapon_id), "stores")


def aircraft_carrying(weapon_id: str) -> list[str]:
    """Aircraft with a station accepting a store that delivers weapon
    ``weapon_id``."""
    return _ids("carriers", weapon_id)


def threats_for_unit(unit_id: str) -> list[str]:
    """Threat systems (``threats`` ids) the unit ``unit_id`` is or is a
    component of."""
    unit_series = cast(list[SeriesName], _meta()["unitSeries"])
    refs = [r for s in unit_series for r in references_to(s, unit_id)]
    return _ids_of(refs, "threats")


def airbase_by_name(name: str, theatre: str | None = None) -> list[str]:
    """Airbase ids named ``name`` (case-insensitive), in theatre ``theatre``
    (its id, case-insensitive) or any."""
    index = cast(Mapping[str, Mapping[str, list[str]]], _index("airbases_by_name"))
    key = name_key(name)
    return sorted(
        {
            i
            for t, names in index.items()
            if theatre is None or name_key(t) == name_key(theatre)
            for i in names.get(key, ())
        }
    )


def find_by_name(series: SeriesName, name: str) -> list[str]:
    """Ids of the ``series`` records whose displayName or name is ``name``
    (case-insensitive)."""
    if series not in _meta()["names"]:
        return []
    return _ids(f"names_{series}", name_key(name))
