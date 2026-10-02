"""Extract ``Entity.Country`` records and per-unit operator lists from
``_G/db/Countries``. Country records are used by check_refs to resolve country
references.

Each country file lists the unit types it fields under
``Units.{Planes.Plane|Helicopters.Helicopter|Ships.Ship|Cars.Car|Personnel.Personnel}``.
Inverting that gives ``unitType -> [operators]``, each operator's ``country``
being the country's ``WorldID`` (a ``country.id`` value) with its constant name
in ``countryName``.

The static ``in_service``/``out_of_service`` fields are DCS defaults (0/40000)
and are not emitted. Real per-(unit, country) years exist only at runtime
(``DB.db.getYearsLocal``); the dump hook writes them to ``_G/__years__.lua``
when available, and those populate ``operators[].years``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import assign_defined, fail, list_lua
from .dcs_constants import COUNTRY_TYPE, Constants
from .lua_reader import LuaReader, array_entries, as_dict, as_number, as_string

_UNIT_CATEGORIES = [
    ("Planes", "Plane"),
    ("Helicopters", "Helicopter"),
    ("Ships", "Ship"),
    ("Cars", "Car"),
    ("Personnel", "Personnel"),
]

_YEARS_FILE = "__years__.lua"


def load_countries(reader: LuaReader, g_dir: Path) -> list[dict[str, Any]]:
    out = []
    for file, rec in reader.read_many(list_lua(g_dir / "db" / "Countries")):
        if isinstance(rec, dict):
            if as_number(rec.get("WorldID")) is None or not as_string(rec.get("Name")):
                fail(f"country without WorldID/Name: {file}")
            out.append(rec)
    return out


def build_countries(
    raw_countries: list[dict[str, Any]], constants: Constants
) -> dict[str, dict[str, Any]]:
    countries: dict[str, dict[str, Any]] = {}
    for raw in raw_countries:
        name = raw["Name"]
        record: dict[str, Any] = {"id": int(raw["WorldID"]), "name": name}
        assign_defined(record, {"idName": constants.name(COUNTRY_TYPE, record["id"])})
        assign_defined(
            record,
            {
                "shortName": as_string(raw.get("ShortName")),
                "internationalName": as_string(raw.get("InternationalName")),
                "oldId": as_string(raw.get("OldID")),
                **{
                    field_name: _entries(raw, key, fields)
                    for field_name, (key, fields) in _LISTS.items()
                },
            },
        )
        countries[name] = record
    return countries


# Country field -> (DCS list, {DCS entry key: field}).
_LISTS = {
    "awards": (
        "Awards",
        {
            "name": "name",
            "nativeName": "nativeName",
            "picture": "picture",
            "threshold": "threshold",
        },
    ),
    "ranks": (
        "Ranks",
        {
            "name": "name",
            "nativeName": "nativeName",
            "stripes": "stripes",
            "pictureRect": "pictureRect",
            "threshold": "threshold",
        },
    ),
    "troops": (
        "Troops",
        {"name": "name", "nativeName": "nativeName", "picture": "picture"},
    ),
}


def _entries(
    raw: dict[str, Any], key: str, fields: dict[str, str]
) -> list[dict[str, Any]] | None:
    """The country's ``key`` entries in DCS order, with ``fields`` renamed;
    an ``Awards`` entry's ``countryID`` must be the country's."""
    out = []
    for entry in array_entries(raw.get(key)):
        entry = dict(as_dict(entry))
        if key == "Awards" and entry.pop("countryID", raw["WorldID"]) != raw["WorldID"]:
            fail(f"country {raw['Name']}: an award names another countryID")
        if unknown := sorted(set(entry) - set(fields)):
            fail(f"country {raw['Name']}: {key} entry has unknown fields {unknown}")
        out.append({fields[k]: v for k, v in entry.items()})
    return out or None


def _load_years(reader: LuaReader, g_dir: Path) -> dict[str, Any]:
    """``{unitType: {countryOldID: {from, to}}}`` from ``__years__.lua``, or {}."""
    return as_dict(reader.read_file(g_dir / _YEARS_FILE))


def _years_for(
    years: dict[str, Any], unit: str, old_id: str | None
) -> dict[str, Any] | None:
    entry = as_dict(as_dict(years.get(unit)).get(old_id)) if old_id else {}
    frm, to = as_number(entry.get("from")), as_number(entry.get("to"))
    # getYearsLocal returns 0/0 for a country that lists the unit but never
    # operated it; that is "no service period", not a range.
    if frm is None or (frm == 0 and to in (0, None)):
        return None
    out: dict[str, Any] = {"from": frm}
    assign_defined(out, {"to": to})
    return out


def build_operators(
    reader: LuaReader,
    g_dir: Path,
    raw_countries: list[dict[str, Any]],
    constants: Constants,
) -> dict[str, list[dict[str, Any]]]:
    """``{unitType: [{country, countryName?, years?}]}`` sorted by country id. Units a
    country names but that are not an emitted entity are included; the caller
    attaches only the ids it owns."""
    years = _load_years(reader, g_dir)
    fielded: dict[str, dict[int, str | None]] = {}
    for rec in raw_countries:
        world = int(rec["WorldID"])
        old_id = as_string(rec.get("OldID"))
        units = as_dict(rec.get("Units"))
        for cat, item in _UNIT_CATEGORIES:
            for entry in array_entries(as_dict(units.get(cat)).get(item)):
                name = as_string(entry.get("Name")) if isinstance(entry, dict) else None
                if name:
                    fielded.setdefault(name, {})[world] = old_id

    operators: dict[str, list[dict[str, Any]]] = {}
    for name, by_world in fielded.items():
        ops = []
        for world in sorted(by_world):
            op: dict[str, Any] = {"country": world}
            assign_defined(
                op,
                {
                    "countryName": constants.name(COUNTRY_TYPE, world),
                    "years": _years_for(years, name, by_world[world]),
                },
            )
            ops.append(op)
        operators[name] = ops
    return operators
