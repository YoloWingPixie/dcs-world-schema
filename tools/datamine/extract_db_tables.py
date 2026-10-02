"""Series from the tables the dump hook writes whole (its ``WRITE_WHOLE``):
``callsigns``, ``formations``, ``tasks``, ``skills`` and ``fuzes``.

The dump must hold the file of every ``REQUIRED`` table, else extraction
fails (DCS renamed or dropped the table).

* ``callsigns``: per country (``db.Countries``), each category's callsign list
  as the mission editor resolves it (MissionEditor/data/MissionGenerator/
  GeneratorData/callsign.lua ``getCallnames``): the country's own
  ``db.Callnames[WorldID][category]``, else that of ``db.DefaultCountry[WorldID]``,
  else of USA. ``numeric``: the country is in ``db.callnamesRussia``.
* ``formations``: ``db.Formations`` records named by their ``db.FormationID``
  constant.
* ``tasks``: the task ``WorldID``/``Name``/``OldID`` of every unit's
  ``Tasks``/``DefaultTask``, with the ``db.Targets.Tasks`` target categories.
* ``skills``: ``db.Units.Skills``.
* ``fuzes``: ``FuzeDescriptions`` and ``SchemeFuzeParameters`` by key.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import unit_properties as props
from .common import WRITE_WHOLE, assign_defined, fail, walk_lua, warn
from .dcs_constants import COUNTRY_TYPE, Constants
from .lua_reader import LuaReader, array_entries, as_dict, as_number, as_string

SERIES_NAMES = ("callsigns", "formations", "tasks", "skills", "fuzes")

# Key -> the hook's WRITE_WHOLE table (dotted _G path) the series read.
REQUIRED = {
    "callnames": "db.Callnames",
    "callnamesRussia": "db.callnamesRussia",
    "defaultCountry": "db.DefaultCountry",
    "formationId": "db.FormationID",
    "skills": "db.Units.Skills",
    "targets": "db.Targets",
    "fuzeDescriptions": "FuzeDescriptions",
    "schemeFuzeParameters": "SchemeFuzeParameters",
}
if _unwritten := sorted(set(REQUIRED.values()) - set(WRITE_WHOLE)):
    raise RuntimeError(f"dump-globals.lua WRITE_WHOLE lacks {_unwritten}")
# FormationID entries that name no formation.
_NOT_FORMATIONS = {"NO_FORMATION", "MAX"}


def table_file(dotted: str) -> str:
    """The dump file of a WRITE_WHOLE table: ``db.Callnames`` ->
    ``db/Callnames.lua``."""
    return dotted.replace(".", "/") + ".lua"


def load(reader: LuaReader, g_dir: Path) -> dict[str, Any]:
    """The ``REQUIRED`` tables by key."""
    out: dict[str, Any] = {}
    for key, dotted in REQUIRED.items():
        rel = table_file(dotted)
        path = g_dir / rel
        if not path.is_file():
            fail(f"the dump lacks {rel}: the hook found no such table in DCS")
        value = reader.read_file(path)
        if value is None:
            fail(f"{path} failed to parse")
        out[key] = value
    return out


def _int_keyed(value: Any, what: str) -> dict[int, Any]:
    """A Lua table keyed by integers (read as a list or digit-keyed dict)."""
    if isinstance(value, list):
        return {i + 1: v for i, v in enumerate(value)}
    if isinstance(value, dict) and all(k.lstrip("-").isdigit() for k in value):
        return {int(k): v for k, v in value.items()}
    fail(f"{what} is not keyed by integers: {str(value)[:120]}")


def _callsign_lists(value: Any) -> dict[int, dict[str, list[dict[str, Any]]]]:
    out: dict[int, dict[str, list[dict[str, Any]]]] = {}
    for wid, cats in _int_keyed(value, "db.Callnames").items():
        if not isinstance(cats, dict):
            fail(f"db.Callnames[{wid}] is not a table of categories")
        out[wid] = {}
        for cat, entries in cats.items():
            items = []
            for entry in array_entries(entries):
                e = as_dict(entry)
                num, name = as_number(e.get("WorldID")), as_string(e.get("Name"))
                if num is None or not name:
                    fail(
                        f"db.Callnames[{wid}][{cat!r}] entry without WorldID/Name: {entry!r}"
                    )
                items.append({"id": int(num), "name": name})
            if not items:
                warn(f"db.Callnames[{wid}][{cat!r}] holds no callsigns (skipped)")
                continue
            out[wid][cat] = items
    return out


def build_callsigns(
    tables: dict[str, Any], raw_countries: list[dict[str, Any]], constants: Constants
) -> dict[str, dict[str, Any]]:
    lists = _callsign_lists(tables["callnames"])
    defaults = _int_keyed(tables["defaultCountry"], "db.DefaultCountry")
    if bad := {k: v for k, v in defaults.items() if as_number(v) is None}:
        fail(f"db.DefaultCountry values are not country ids: {bad}")
    defaults = {k: int(v) for k, v in defaults.items()}
    usa = constants.value("country", "USA")
    if usa is None:
        fail("no USA country constant: the callsign fallback country")
    names = {c["Name"]: int(c["WorldID"]) for c in raw_countries}
    numeric = set(array_entries(tables["callnamesRussia"]))
    if unknown := sorted(set(lists) - set(names.values())):
        fail(f"db.Callnames countries not in db.Countries: {unknown}")
    if unknown := sorted(n for n in numeric if n not in names):
        fail(f"db.callnamesRussia names no country: {unknown}")

    out: dict[str, dict[str, Any]] = {}
    for name, wid in sorted(names.items()):
        fallback = defaults.get(wid, usa)
        if fallback not in lists:
            fail(f"callsign fallback country {fallback} of {name} has no db.Callnames")
        own, other = lists.get(wid, {}), lists[fallback]
        categories = []
        for cat in sorted(own.keys() | other.keys()):
            src = wid if cat in own else fallback
            categories.append(
                {"category": cat, "country": src, "callsigns": lists[src][cat]}
            )
        record: dict[str, Any] = {"country": wid}
        assign_defined(record, {"countryName": constants.name(COUNTRY_TYPE, wid)})
        record.update(
            {
                "numeric": name in numeric,
                "fallbackCountry": fallback,
                "categories": categories,
            }
        )
        out[name] = record
    return out


def _xyz(value: Any, where: str) -> dict[str, Any]:
    p = as_dict(value)
    xyz = {k: as_number(p.get(k)) for k in ("x", "y", "z")}
    if any(v is None for v in xyz.values()):
        fail(f"{where}: position without x/y/z: {value!r}")
    return xyz


def _position(value: Any, where: str) -> dict[str, Any]:
    """``{x, y, z}``, or a big formation's ``{name, positions = {x, y, z}}``."""
    p = as_dict(value)
    if "x" in p:
        return _xyz(p, where)
    name = as_string(p.get("name"))
    if not name:
        fail(f"{where}: unknown position shape: {value!r}")
    return {"name": name, **_xyz(p.get("positions"), where)}


def _variant(value: Any, where: str) -> dict[str, Any]:
    v = as_dict(value)
    positions = array_entries(v.get("positions"))
    if not positions:
        fail(f"{where}: variant without positions: {value!r}")
    out: dict[str, Any] = {}
    assign_defined(out, {"name": as_string(v.get("name"))})
    out["positions"] = [_position(p, where) for p in positions]
    return out


def read_formations(reader: LuaReader, g_dir: Path) -> list[tuple[Path, Any]]:
    """The ``db.Formations`` record files of the dump and their values."""
    root = g_dir / "db" / "Formations"
    if not root.is_dir():
        fail(f"no db.Formations in {g_dir}")
    return reader.read_many(walk_lua(root))


def build_formations(
    formations: list[tuple[Path, Any]], g_dir: Path, tables: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    ids: dict[int, str] = {}
    for const_name, num in as_dict(tables["formationId"]).items():
        if const_name in _NOT_FORMATIONS:
            continue
        if as_number(num) is None or int(num) in ids:
            fail(f"db.FormationID.{const_name} = {num!r} is not a unique number")
        ids[int(num)] = const_name
    root = g_dir / "db" / "Formations"
    out: dict[str, dict[str, Any]] = {}
    for path, raw in formations:
        rec = as_dict(raw)
        where = str(path.relative_to(root))
        wid, name = as_number(rec.get("WorldID")), as_string(rec.get("Name"))
        if wid is None or not name:
            fail(f"formation {where} without WorldID/Name")
        const = ids.get(int(wid))
        if const is None:
            fail(f"formation {where}: WorldID {wid} has no db.FormationID name")
        if "variants" in rec:
            variants = [_variant(v, where) for v in array_entries(rec["variants"])]
        else:
            positions = array_entries(rec.get("positions"))
            if positions and "x" not in as_dict(positions[0]):
                variants = [_variant(v, where) for v in positions]
            else:
                variants = [_variant(rec, where)]
        record: dict[str, Any] = {
            "id": const,
            "worldId": int(wid),
            "name": name,
            "group": path.relative_to(root).parts[0],
        }
        assign_defined(
            record,
            {
                "clsid": as_string(rec.get("CLSID")),
                "defaultVariantIndex": as_number(rec.get("defaultVariantIndex")),
                "zInverse": rec.get("zInverse")
                if isinstance(rec.get("zInverse"), bool)
                else None,
            },
        )
        record["variants"] = variants
        out[const] = record
    if unused := sorted(set(ids.values()) - set(out)):
        warn(f"db.FormationID names without a db.Formations record: {unused}")
    return out


def build_tasks(
    units: dict[str, dict[str, Any]], tables: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    names: dict[int, str] = {}
    old_ids: dict[int, str] = {}
    for uid, rec in sorted(units.items()):
        found = props.tasks(rec, uid)
        for task in [
            *found.get("tasks", []),
            *filter(None, [found.get("defaultTask")]),
        ]:
            prev = names.setdefault(task["id"], task["name"])
            if prev != task["name"]:
                fail(f"task {task['id']} is {prev!r} and {task['name']!r} ({uid})")
        for raw in [*array_entries(rec.get("Tasks")), rec.get("DefaultTask")]:
            task = as_dict(raw)
            wid, old = as_number(task.get("WorldID")), as_string(task.get("OldID"))
            if wid is not None and old:
                prev = old_ids.setdefault(int(wid), old)
                if prev != old:
                    fail(f"task {int(wid)} has OldID {prev!r} and {old!r} ({uid})")
    targets = _int_keyed(as_dict(tables["targets"]).get("Tasks"), "db.Targets.Tasks")
    if unnamed := sorted(set(targets) - set(names)):
        warn(f"db.Targets.Tasks ids no unit task names (skipped): {unnamed}")
    out: dict[str, dict[str, Any]] = {}
    for wid, name in sorted(names.items()):
        record: dict[str, Any] = {"id": name, "worldId": wid}
        if wid in old_ids:
            record["oldId"] = old_ids[wid]
        if wid in targets:
            flags = as_dict(targets[wid])
            if any(not isinstance(v, bool) for v in flags.values()):
                fail(f"db.Targets.Tasks[{wid}] holds a non-boolean: {flags!r}")
            record["targets"] = [
                {"category": c, "default": flags[c]} for c in sorted(flags)
            ]
        if name in out:
            fail(f"task name {name!r} has several ids")
        out[name] = record
    return out


def build_skills(tables: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for entry in array_entries(tables["skills"]):
        e = as_dict(entry)
        num, name = as_number(e.get("WorldID")), as_string(e.get("Name"))
        if num is None or not name or name in out:
            fail(f"db.Units.Skills entry {entry!r}: no WorldID/Name or repeated")
        out[name] = {"id": name, "worldId": int(num)}
    if not out:
        fail("db.Units.Skills is empty")
    return out


def _param_value(value: Any, where: str) -> dict[str, Any]:
    """``{flag}``, ``{number}`` or ``{numbers}`` of a DCS value."""
    if isinstance(value, bool):
        return {"flag": value}
    if as_number(value) is not None:
        return {"number": value}
    items = array_entries(value)
    if items and all(as_number(v) is not None for v in items):
        return {"numbers": items}
    fail(f"{where}: fuze parameter is not a number, boolean or number list: {value!r}")


def _parameters(value: Any, fuze: str) -> list[dict[str, Any]]:
    params: list[dict[str, Any]] = []
    for key, val in sorted(as_dict(value).items()):
        if isinstance(val, dict):
            for name, sub in sorted(val.items()):
                where = f"SchemeFuzeParameters.{fuze}.{key}.{name}"
                params.append({"mode": key, "name": name, **_param_value(sub, where)})
        else:
            where = f"SchemeFuzeParameters.{fuze}.{key}"
            params.append({"name": key, **_param_value(val, where)})
    return params


def build_fuzes(tables: dict[str, Any]) -> dict[str, dict[str, Any]]:
    descriptions = as_dict(tables["fuzeDescriptions"])
    schemes = as_dict(tables["schemeFuzeParameters"])
    out: dict[str, dict[str, Any]] = {}
    for fid in sorted(descriptions.keys() | schemes.keys()):
        record: dict[str, Any] = {"id": fid}
        if fid in descriptions:
            text = as_string(descriptions[fid])
            if text is None:
                fail(f"FuzeDescriptions.{fid} is not a string")
            record["description"] = text
        if fid in schemes:
            record["parameters"] = _parameters(schemes[fid], fid)
        out[fid] = record
    return out


def build(
    reader: LuaReader,
    g_dir: Path,
    formations: list[tuple[Path, Any]],
    raw_countries: list[dict[str, Any]],
    units: dict[str, dict[str, Any]],
    constants: Constants,
) -> dict[str, dict[str, Any]]:
    """The five series by name (``formations``: ``read_formations``)."""
    tables = load(reader, g_dir)
    return {
        "callsigns": build_callsigns(tables, raw_countries, constants),
        "formations": build_formations(formations, g_dir, tables),
        "tasks": build_tasks(units, tables),
        "skills": build_skills(tables),
        "fuzes": build_fuzes(tables),
    }
