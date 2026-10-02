"""Check the merged schema's enums against DCS:

a. an enum named for a table of the scripting API dump (``AI.Skill``) has
   exactly that table's keys and values;
b. an enum mirroring a DCS constant family (``FAMILIES``) has its values;
c. every Mission Editor value list (``ME_VALUES``: an action parameter's
   install mission strings, the ``skills`` series) is admitted by the type
   that takes it;
d. each ``DcsTask.OptionValue.*`` enum has the values of the scripting API's
   ``AI.Option.<table>.val.<option>`` tables of its categories, no more.

Known disagreements are in ``ALLOWED`` with the reason; an entry that matches
no finding is an error.

    uv run python -m tools.datamine.check_enums [SPEC] [--data-dir DIR]
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from tools.spec_types import Literal, Primitive, Ref, members, parse_type

from .action_types import KIND_TYPES, NS, OPTION_TABLES, option_value_type
from .api_dump import legacy, scalars_at
from .common import (
    API_DIR,
    LATEST,
    REFERENCE_DATA_DIR,
    SPEC_PATH,
    fail,
    load_json,
    load_series,
)

# (enum, entity enum of the constant family, prefix its keys drop, whether
# the enum may hold only some of the family).
FAMILIES = (
    ("BeaconType", "Entity.BeaconType", "", False),
    ("RadioModulation", "Entity.RadioModulation", "MODULATION_", False),
    ("Unit.RadarType", "Entity.RadarType", "RADAR_", True),
)
# Series whose record ids are values the Mission Editor writes -> the type
# (or ``Record.field``) that takes them.
ME_VALUES = {"skills": "UnitSpawnData.skill"}
ALLOWED = {
    "d DcsTask.OptionValue.ROE_vehicle_ship: 0 (WEAPON_FREE) not in "
    "AI.Option.Ground.val.ROE": (
        "The Mission Editor writes 0 for ground units; the runtime table has "
        "2 (OPEN_FIRE) instead. Typed as both until probed."
    ),
    "d DcsTask.OptionValue.ROE_vehicle_ship: 0 (WEAPON_FREE) not in "
    "AI.Option.Naval.val.ROE": (
        "As for ground units: the Mission Editor writes 0 for ships, the "
        "runtime table has 2 (OPEN_FIRE)."
    ),
    "d DcsTask.OptionValue.REACTION_ON_THREAT: 5 (HORIZONTAL_AAA_FIRE_EVADE) "
    "not in AI.Option.Air.val.REACTION_ON_THREAT": (
        "A Mission Editor value newer than the runtime table."
    ),
}


def _values(td: dict[str, Any]) -> dict[str, Any]:
    values = td.get("values") or {}
    return values if isinstance(values, dict) else {v: v for v in values}


def runtime_tables(types: dict[str, Any], api: dict[str, Any]) -> list[str]:
    """(a): enums whose keys or values differ from the dump table of their name."""
    out = []
    for name, td in sorted(types.items()):
        if td.get("kind") != "enum":
            continue
        dcs = scalars_at(api, name)
        if dcs is None:
            continue
        ours = _values(td)
        for key in sorted(set(ours) | set(dcs)):
            if ours.get(key, ...) != dcs.get(key, ...):
                out.append(
                    f"a {name}.{key}: schema {ours.get(key, 'missing')!r}, "
                    f"DCS {dcs.get(key, 'missing')!r}"
                )
    return out


def families(types: dict[str, Any]) -> list[str]:
    """(b): enums whose values differ from their constant family's."""
    out = []
    for name, entity, prefix, subset in FAMILIES:
        if name not in types or entity not in types:
            out.append(f"b {name}: no {name if name not in types else entity} type")
            continue
        ours = _values(types[name])
        dcs = {k.removeprefix(prefix): v for k, v in _values(types[entity]).items()}
        keys = set(ours) if subset else set(ours) | set(dcs)
        for key in sorted(keys):
            if ours.get(key, ...) != dcs.get(key, ...):
                out.append(
                    f"b {name}.{key}: {ours.get(key, 'missing')!r}, "
                    f"{entity} {dcs.get(key, 'missing')!r}"
                )
    return out


def admits(types: dict[str, Any], type_ref: str, value: str) -> bool:
    """Whether ``type_ref`` admits the string ``value``."""
    for m in members(parse_type(type_ref)):
        if isinstance(m, Primitive) and m.name in ("string", "any"):
            return True
        if isinstance(m, Literal) and m.value == value:
            return True
        if isinstance(m, Ref) and m.name in types:
            td = types[m.name]
            if td.get("kind") == "enum" and value in _values(td).values():
                return True
            if td.get("kind") == "union" and any(
                admits(types, t, value) for t in td.get("anyOf") or []
            ):
                return True
    return False


def _type_of(types: dict[str, Any], target: str) -> str | None:
    """A type name, or the type of a ``Record.field``."""
    if target in types:
        return target
    record, _, field = target.rpartition(".")
    fields = (types.get(record) or {}).get("fields") or {}
    return fields.get(field, {}).get("type") if field in fields else None


def mission_values(types: dict[str, Any], data_dir: Path) -> list[str]:
    """(c): Mission Editor values the type taking them does not admit."""
    out = []
    for rec in load_series(data_dir, "actions").values():
        if rec["kind"] not in KIND_TYPES:
            continue
        params = f"{NS}.{KIND_TYPES[rec['kind']][0]}.{rec['dcsId']}Params"
        fields = (types.get(params) or {}).get("fields") or {}
        for p in rec["params"]:
            if p["name"] not in fields:
                continue
            type_ref = fields[p["name"]]["type"]
            for v in p.get("missionStrings") or []:
                if not admits(types, type_ref, v["value"]):
                    out.append(
                        f"c {params}.{p['name']}: {v['value']!r} ({v['count']} "
                        f"uses) not admitted by {type_ref}"
                    )
    for series, target in ME_VALUES.items():
        type_ref = _type_of(types, target)
        if type_ref is None:
            out.append(f"c {series}: no type {target}")
            continue
        for rid in sorted(load_series(data_dir, series)):
            if not admits(types, type_ref, rid):
                out.append(f"c {series}: {rid!r} not admitted by {type_ref}")
    return out


def option_values(
    types: dict[str, Any], data_dir: Path, api: dict[str, Any]
) -> list[str]:
    """(d): option value enums against the runtime ``AI.Option`` tables."""
    out = []
    for o in sorted(load_series(data_dir, "options").values(), key=lambda o: o["id"]):
        for s in o.get("valueSets") or []:
            name = option_value_type(o, s)
            if name not in types:
                continue
            ours = _values(types[name])
            cats = s.get("categories") or o["categories"]
            for table in sorted({OPTION_TABLES[c] for c in cats if c in OPTION_TABLES}):
                path = f"AI.Option.{table}.val.{o['id']}"
                dcs = scalars_at(api, path)
                if dcs is None:
                    continue
                out += [
                    f"d {name}: {v} ({k}) not in {path}"
                    for k, v in ours.items()
                    if v not in dcs.values()
                ]
                out += [
                    f"d {name}: lacks {path} {v} ({k})"
                    for k, v in dcs.items()
                    if v not in ours.values()
                ]
    return out


def check(spec: dict[str, Any], data_dir: Path) -> list[str]:
    """Every finding not in ``ALLOWED``, then every stale ``ALLOWED`` entry."""
    types = spec.get("types", {})
    api = legacy(load_json(data_dir / API_DIR / "scripting.json"))
    found = [
        *runtime_tables(types, api),
        *families(types),
        *mission_values(types, data_dir),
        *option_values(types, data_dir, api),
    ]
    stale = [f"stale ALLOWED entry: {k}" for k in ALLOWED if k not in found]
    return [f for f in found if f not in ALLOWED] + stale


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("spec", nargs="?", type=Path, default=SPEC_PATH)
    parser.add_argument("--data-dir", type=Path, default=REFERENCE_DATA_DIR / LATEST)
    args = parser.parse_args(argv)
    problems = check(load_json(args.spec), args.data_dir)
    if problems:
        fail("enums disagree with DCS:\n  " + "\n  ".join(problems))
    print(f"Enums match DCS ({len(ALLOWED)} known disagreements allowed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
