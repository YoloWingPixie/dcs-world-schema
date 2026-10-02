"""Generate ``dcs-world-schema/types/ids/*.generated.yaml``: the ``DcsId.*``
types of the ids DCS's functions and mission tables take, from the series of
``dcs-world-reference/latest``.

``DcsId`` is no DCS global: these are types only (EmmyLua ``---@alias`` of
the values, TypeScript literal unions). Each id enum is keyed by the record's
display name (its id when it has none or shares it) with the DCS id as value,
so completions show the display name beside each id. The schema takes them as
``DcsId.X | string``: mods add ids. An enum holds at most ``MAX_MEMBERS``.

* ``Units``: ``AircraftType``, ``HelicopterType``, ``GroundUnitType``,
  ``ShipType``, ``StructureType``, ``PersonnelType``, ``UnitType`` (a unit's)
  and ``StaticType`` (a static object's);
* ``Weapons``: ``WeaponType`` (weapons and gun shells);
* ``Airbases``: ``Theatre.<theatre>.AirbaseName`` and ``.AirdromeId``, and
  their unions ``AirbaseName`` and ``AirdromeId``;
* ``Misc``: ``Attribute`` (with ``EXTRA_ATTRIBUTES``), ``SensorName``,
  ``MainTask``, ``Skill``, ``FormationId`` and ``FormationValue`` (the
  ``FORMATION`` option's values, ``DcsTask.OptionValue.FORMATION_*``).

    uv run python -m tools.datamine.id_types [--data-dir DIR] [--out DIR] [--check]
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from .action_types import option_value_type
from .common import (
    LATEST,
    MANIFEST,
    REFERENCE_DATA_DIR,
    REPO_ROOT,
    fail,
    generated_drift,
    load_json,
    load_series,
    pmap,
    write_generated,
)

OUT_DIR = REPO_ROOT / "dcs-world-schema" / "types" / "ids"
SUFFIX = ".generated.yaml"
NS = "DcsId"
MAX_MEMBERS = 1000
# Attributes no record of the unit series carries.
EXTRA_ATTRIBUTES = {
    # Weapon attributes (the dump has no weapon attribute lists): target types
    # of the Mission Editor's lists (MissionEditor/modules/me_action_db.lua
    # noTargetTypes*) that install missions use.
    "AA Missiles": "weapon",
    "AG Missiles": "weapon",
    "Antiship Missiles": "weapon",
    "Cruise missiles": "weapon",
    "SA Missiles": "weapon",
}
# The completion comment of each kind of extra.
_EXTRA_TEXT = {"weapon": "weapons"}


def _enum(description: str, values: dict[str, Any]) -> dict[str, Any]:
    if len(values) > MAX_MEMBERS:
        fail(f"{description}: {len(values)} members, over {MAX_MEMBERS}")
    return {"kind": "enum", "description": description, "values": values}


def _union(description: str, names: list[str]) -> dict[str, Any]:
    return {"kind": "union", "description": description, "anyOf": names}


def keyed(records: list[tuple[str, str | None]]) -> dict[str, str]:
    """``{key: id}`` of ``(id, display name)`` pairs: keyed by display name,
    by id where there is none or several records share it."""
    names = Counter(name for _, name in records if name)
    out: dict[str, str] = {}
    for rid, name in sorted(records, key=lambda r: ((r[1] or r[0]).lower(), r[0])):
        key = name if name and names[name] == 1 else rid
        if key in out:
            fail(f"DcsId key {key!r} is both {out[key]!r} and {rid!r}")
        out[key] = rid
    return out


def _named(series: dict[str, dict[str, Any]]) -> dict[str, str]:
    return keyed([(r["id"], r.get("displayName")) for r in series.values()])


def unit_types(data: Path) -> dict[str, Any]:
    aircraft = load_series(data, "aircraft", required=True)
    sets = {
        "AircraftType": (
            {k: r for k, r in aircraft.items() if r["kind"] == "fixedwing"},
            "Airplane unit types (`Unit:getTypeName()`, a mission unit's `type`).",
        ),
        "HelicopterType": (
            {k: r for k, r in aircraft.items() if r["kind"] == "rotary"},
            "Helicopter unit types.",
        ),
        "GroundUnitType": (
            load_series(data, "ground_vehicles", required=True),
            "Ground unit types.",
        ),
        "ShipType": (load_series(data, "ships", required=True), "Ship unit types."),
        "StructureType": (
            load_series(data, "structures", required=True),
            "Static-only object types: structures, cargos, FARPs and the like.",
        ),
        "PersonnelType": (
            load_series(data, "personnel", required=True),
            "Static-only personnel types (deck crew and the like).",
        ),
    }
    types = {
        f"{NS}.{name}": _enum(f"{text} Keyed by display name.", _named(series))
        for name, (series, text) in sets.items()
    }
    units = [f"{NS}.{n}" for n in ("AircraftType", "HelicopterType")]
    units += [f"{NS}.{n}" for n in ("GroundUnitType", "ShipType")]
    types[f"{NS}.UnitType"] = _union(
        "Any unit type: what `Unit.getDescByName` takes and `Unit:getTypeName` returns.",
        units,
    )
    types[f"{NS}.StaticType"] = _union(
        "Any static object type (`StaticObject:getTypeName`): a unit's, a "
        "structure's or personnel's.",
        [f"{NS}.UnitType", f"{NS}.StructureType", f"{NS}.PersonnelType"],
    )
    return types


def weapon_types(data: Path) -> dict[str, Any]:
    weapons = load_series(data, "weapons", required=True)
    shells = load_series(data, "gun_ammo", required=True)
    pairs = [(r["id"], r.get("displayName")) for r in weapons.values()]
    pairs += [(r["id"], r.get("displayName")) for r in shells.values()]
    return {
        f"{NS}.WeaponType": _enum(
            "Weapon and gun shell types (`Weapon:getTypeName()`). Keyed by "
            "display name.",
            keyed(pairs),
        )
    }


def airbase_types(data: Path) -> dict[str, Any]:
    by_theatre: dict[str, list[dict[str, Any]]] = {}
    paths = sorted((data / "airbases").glob("*/*.json"))
    if not paths:
        fail(f"no airbases series in {data}")
    for rec in pmap(load_json, paths):
        by_theatre.setdefault(rec["theatre"], []).append(rec)
    types: dict[str, Any] = {}
    names, ids = [], []
    for theatre, recs in sorted(by_theatre.items()):
        if len({r["name"] for r in recs}) < len(recs):
            fail(f"airbases of {theatre} share a name")
        prefix = f"{NS}.Theatre.{theatre}"
        types[f"{prefix}.AirbaseName"] = _enum(
            f"Airfield names of {theatre} (`Airbase.getByName`).",
            {r["name"]: r["name"] for r in sorted(recs, key=lambda r: r["name"])},
        )
        types[f"{prefix}.AirdromeId"] = _enum(
            f"Airfield ids of {theatre} (a mission waypoint's `airdromeId`), "
            "keyed by name.",
            {
                r["name"]: r["airdromeId"]
                for r in sorted(recs, key=lambda r: r["airdromeId"])
            },
        )
        names.append(f"{prefix}.AirbaseName")
        ids.append(f"{prefix}.AirdromeId")
    types[f"{NS}.AirbaseName"] = _union("Airfield names of any theatre.", names)
    types[f"{NS}.AirdromeId"] = _union("Airfield ids of any theatre.", ids)
    return types


def misc_types(data: Path) -> dict[str, Any]:
    attributes = {r["id"]: r["id"] for r in load_series(data, "attributes").values()}
    overlap = sorted(set(attributes) & set(EXTRA_ATTRIBUTES))
    if overlap:
        fail(f"EXTRA_ATTRIBUTES now in the attributes series: {overlap}")
    extra = {
        f"{name} ({_EXTRA_TEXT[why]})": name for name, why in EXTRA_ATTRIBUTES.items()
    }
    tasks = load_series(data, "tasks", required=True)
    formations = load_series(data, "formations", required=True)
    options = load_series(data, "options", required=True)
    formation_sets = [
        option_value_type(o, s)
        for o in options.values()
        if o["id"] == "FORMATION"
        for s in o.get("valueSets") or []
    ]
    return {
        f"{NS}.Attribute": _enum(
            "Unit attributes (`Object:hasAttribute`, task `targetTypes`): those of "
            "the unit series, then a few of weapons and airbases.",
            {**dict(sorted(attributes.items(), key=lambda kv: kv[0].lower())), **extra},
        ),
        f"{NS}.SensorName": _enum(
            "Sensor names (`Unit:getSensors()` `typeName`).",
            {
                k: k
                for k in sorted(r["id"] for r in load_series(data, "sensors").values())
            },
        ),
        f"{NS}.MainTask": _enum(
            "A group's main task as missions write it (`task`), keyed by name.",
            {
                r["id"]: r.get("oldId", r["id"])
                for r in sorted(tasks.values(), key=lambda r: r["worldId"])
            },
        ),
        f"{NS}.Skill": _enum(
            "Unit skills as missions write them, `Random` included.",
            {
                r["id"]: r["id"]
                for r in sorted(
                    load_series(data, "skills", required=True).values(),
                    key=lambda r: r["worldId"],
                )
            },
        ),
        f"{NS}.FormationId": _enum(
            "Formation ids (`db.FormationID`; `FollowBigFormation` `formationType`), "
            "keyed by formation.",
            {
                r["id"]: r["worldId"]
                for r in sorted(formations.values(), key=lambda r: r["worldId"])
            },
        ),
        f"{NS}.FormationValue": _union(
            "A `FORMATION` option value: formation, side and variant.",
            sorted(formation_sets),
        ),
    }


FILES = {
    "Units": unit_types,
    "Weapons": weapon_types,
    "Airbases": airbase_types,
    "Misc": misc_types,
}


def _render(types: dict[str, Any], version: str, stem: str) -> str:
    header = (
        f"# DcsId types: {stem.lower()} ids (dcs-world-reference series).\n"
        f"# DCS version: {version}\n"
        "# Generated by tools/datamine/id_types.py; do not edit.\n"
    )
    body = yaml.safe_dump(
        {"globals": {}, "types": types},
        sort_keys=False,
        allow_unicode=True,
        width=100,
        default_flow_style=False,
    )
    return header + body


def generate(data_dir: Path) -> dict[str, str]:
    """``{file name: text}`` for ``OUT_DIR`` from a data dir's series."""
    version = load_json(data_dir / MANIFEST)["dcsVersion"]
    return {
        f"{stem}{SUFFIX}": _render(build(data_dir), version, stem)
        for stem, build in FILES.items()
    }


def write(files: dict[str, str], out: Path = OUT_DIR) -> None:
    """Make the generated files under ``out`` exactly ``files``."""
    write_generated(out, files, SUFFIX)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=REFERENCE_DATA_DIR / LATEST)
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--check", action="store_true", help="fail on drift")
    args = parser.parse_args(argv)
    files = generate(args.data_dir)
    if args.check:
        stale = generated_drift(args.out, files, SUFFIX)
        if stale:
            fail(
                f"DcsId types out of date ({', '.join(stale)}); run `task datamine:id-types`"
            )
        print(f"DcsId types match {args.data_dir}")
        return 0
    write(files, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
