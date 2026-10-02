"""Schema types for DCS's internal database tables, inferred from a ``_G`` dump.

Every record of a table kind (``KINDS``) is walked and the observed shapes are
merged: per field the Lua types seen and how many tables held it; per table
whether it was an array (consecutive or sparse integer keys), a record, or
both. A table is a map when listed in ``MAPS`` or when it has ``MAP_MIN_KEYS``
or more keys, none in more than ``MAP_MAX_SHARE`` of the tables; its values
merge into one type. Functions dump as nil and are absent. A
path-string ref is typed as the kind it points into (``REF_KINDS``).

A nested table's type is named from its parent's name and field
(``DcsDb.UnitCar`` + ``Sensors`` -> ``DcsDb.UnitCarSensors``); ``SHARED``
routes a field of every table in a family to one type, and ``NAMES`` renames a
type. Array elements take their container's name, or ``<name>Item`` when the
container is a record too; nested arrays are ``<name>List``, element unions
``<name>Entry``, scalar unions ``DcsDb.NumberOrString`` and the like. Types of
identical shape held by fields of the same name are merged.

    uv run python -m tools.datamine.dcs_database_types [--g-dir DIR] [--out DIR] [--check]
        [--if-dumped]

The DCS version of the dump is recorded in each file's header; ``--if-dumped``
skips when no dump of that version is at hand (CI has none). A passing
``--check`` is remembered in ``.datamine`` for the dump, the committed files and
this code, so an unchanged check is not redone.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools import spec_types
from tools.spec_types import union_parts

from . import lua_reader
from .common import (
    CACHE_DIR,
    CACHED_G_DIR,
    REPO_ROOT,
    VERSION_MARKER,
    fail,
    generated_drift,
    list_lua,
    read_version,
    write_generated,
    write_text_if_changed,
    yaml_key,
)
from .lua_reader import LuaReader

OUT_DIR = REPO_ROOT / "dcs-world-schema" / "types" / "dcs-database"
CHECK_CACHE = CACHE_DIR / "dcs-database-types.check"
SUFFIX = ".generated.yaml"
VERSION_TAG = "DCS version: "


@dataclass(frozen=True)
class Kind:
    key: str  # type the records merge into
    path: str  # under the _G dir: a directory of record files, or one file
    family: str  # output file


KINDS: tuple[Kind, ...] = (
    Kind("DcsDb.WeaponSystems[]", "db/Units/GT_t/WS_t", "WeaponSystems"),
    Kind("DcsDb.WeaponSystems[]", "db/Units/GT_t/SS_t", "WeaponSystems"),
    Kind("DcsDb.WeaponLaunchers[]", "db/Units/GT_t/LN_t", "WeaponSystems"),
    Kind("DcsDb.WeaponSensor", "db/Units/GT_t/WSN_t", "WeaponSystems"),
    Kind("DcsDb.GroundChassis", "db/Units/GT_t/CH_t", "WeaponSystems"),
    Kind("DcsDb.UnitPlane", "db/Units/Planes/Plane", "Units"),
    Kind("DcsDb.UnitHelicopter", "db/Units/Helicopters/Helicopter", "Units"),
    Kind("DcsDb.UnitCar", "db/Units/Cars/Car", "Units"),
    Kind("DcsDb.UnitTrain", "db/Units/Cars/Train.lua", "Units"),
    Kind("DcsDb.UnitShip", "db/Units/Ships/Ship", "Units"),
    Kind("DcsDb.UnitFortification", "db/Units/Fortifications/Fortification", "Units"),
    Kind("DcsDb.UnitPersonnel", "db/Units/Personnel/Personnel", "Units"),
    Kind("DcsDb.UnitWarehouse", "db/Units/Warehouses/Warehouse", "Units"),
    Kind("DcsDb.UnitADEquipment", "db/Units/ADEquipments/ADEquipment", "Units"),
    Kind("DcsDb.UnitAnimal", "db/Units/Animals/Animal", "Units"),
    Kind("DcsDb.UnitCargo", "db/Units/Cargos/Cargo", "Units"),
    Kind("DcsDb.UnitEffect", "db/Units/Effects/Effect", "Units"),
    Kind("DcsDb.UnitGrassAirfield", "db/Units/GrassAirfields/GrassAirfield", "Units"),
    Kind("DcsDb.UnitGroundObject", "db/Units/GroundObjects/GroundObject", "Units"),
    Kind("DcsDb.UnitHeliport", "db/Units/Heliports/Heliport", "Units"),
    Kind("DcsDb.UnitLTAvehicle", "db/Units/LTAvehicles/LTAvehicle", "Units"),
    Kind("DcsDb.Launcher", "launcher", "Weapons"),
    Kind("DcsDb.Pylon", "Pylons", "Weapons"),
    Kind("DcsDb.Rocket", "rockets", "Weapons"),
    Kind("DcsDb.Bomb", "bombs", "Weapons"),
    Kind("DcsDb.Torpedo", "torpedoes", "Weapons"),
    Kind("DcsDb.Warhead", "warheads", "Weapons"),
    Kind("DcsDb.WeaponMissile", "weapons_table/weapons/missiles", "Weapons"),
    Kind("DcsDb.WeaponBomb", "weapons_table/weapons/bombs", "Weapons"),
    Kind("DcsDb.WeaponNurs", "weapons_table/weapons/nurs", "Weapons"),
    Kind("DcsDb.WeaponShell", "weapons_table/weapons/shells", "Weapons"),
    Kind("DcsDb.WeaponTorpedo", "weapons_table/weapons/torpedoes", "Weapons"),
    Kind("DcsDb.WeaponJatoCont", "weapons_table/weapons/jato_conts", "Weapons"),
    Kind("DcsDb.AircraftGunpod", "weapons_table/aircraft_gunpods", "Weapons"),
    Kind("DcsDb.Country", "db/Countries", "Countries"),
)

# (family, field) -> (type, its family): every such field of the family merges
# into that type.
SHARED: dict[tuple[str, str], tuple[str, str]] = {
    ("Units", "WS"): ("DcsDb.WeaponSystems", "WeaponSystems"),
    ("Units", "mechanimations"): ("DcsDb.Mechanimations", "Units"),
    ("WeaponSystems", "LN"): ("DcsDb.WeaponLaunchers", "WeaponSystems"),
    ("WeaponSystems", "sensor"): ("DcsDb.WeaponSensor", "WeaponSystems"),
    ("Weapons", "warhead"): ("DcsDb.Warhead", "Weapons"),
    ("Weapons", "warhead_air"): ("DcsDb.Warhead", "Weapons"),
    ("Weapons", "warhead_water"): ("DcsDb.Warhead", "Weapons"),
}
# Type key -> name, where the derived one reads badly.
NAMES: dict[str, str] = {
    "DcsDb.WeaponSystems[]": "DcsDb.WeaponSystem",
    "DcsDb.WeaponLaunchers[]": "DcsDb.WeaponLauncher",
    "DcsDb.WeaponLauncherPL[]": "DcsDb.WeaponPayload",
    "DcsDb.WeaponLauncherBR[]": "DcsDb.WeaponBarrel",
    "DcsDb.LauncherElements[]": "DcsDb.LauncherElement",
    "DcsDb.Mechanimations[]": "DcsDb.Mechanimation",
}
# Tables keyed by name however few their keys.
MAPS = {"DcsDb.Mechanimations", "DcsDb.CountryRankByName"}
# Directory under _G of a ref's target -> the kind it is typed as.
REF_KINDS = {"warheads": "DcsDb.Warhead", "Pylons": "DcsDb.Pylon"}

MAP_MIN_KEYS = 24
MAP_MAX_SHARE = 0.5

_REF = re.compile(r"^_G/([^/]+)/.+\.lua$")
_SCALARS = {bool: "boolean", int: "number", float: "number", str: "string"}
_SCALAR_NAMES = ("boolean", "number", "string")


@dataclass
class _Slot:
    """Merged observations of one value position (a field, or array elements)."""

    present: int = 0
    types: Counter[str] = field(default_factory=Counter)  # scalar or ref kind
    tables: int = 0
    child: str | None = None


@dataclass
class _Shape:
    """Merged observations of the tables of one type."""

    family: str
    count: int = 0
    records: int = 0  # tables with non-integer keys
    arrays: int = 0  # tables with integer keys
    sparse: int = 0  # integer keys with holes
    empty: int = 0
    fields: dict[str, _Slot] = field(default_factory=dict)
    items: _Slot = field(default_factory=_Slot)
    origins: set[tuple[str, str]] = field(default_factory=set)  # (parent, field)


def _pascal(key: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", key)
    return "".join(w[0].upper() + w[1:] for w in words) or "Field"


def _base(key: str) -> str:
    if key in NAMES:
        return NAMES[key]
    while key.endswith("[]"):
        key = key[:-2]
    return key


class _Collector:
    def __init__(self, maps: set[str], renames: dict[tuple[str, str], str]) -> None:
        self.maps = maps
        self.renames = renames  # (parent, field) -> child, where names collide
        self.fields_of: dict[str, set[tuple[str, str]]] = {}  # child -> sources
        self.shapes: dict[str, _Shape] = {}
        self.aliases = 0  # records that are a ref to another record

    def shape(self, key: str, family: str) -> _Shape:
        if key not in self.shapes:
            self.shapes[key] = _Shape(family)
        return self.shapes[key]

    def add_record(self, kind: Kind, value: Any) -> None:
        if isinstance(value, (dict, list)):
            self._table(kind.key, kind.family, value)
        else:
            self.aliases += 1

    def _table(self, key: str, family: str, value: dict[str, Any] | list[Any]) -> None:
        s = self.shape(key, family)
        s.count += 1
        if isinstance(value, list):
            items, named = value, {}
        else:
            ints = {k: v for k, v in value.items() if _is_index(k)}
            named = {k: v for k, v in value.items() if not _is_index(k)}
            items = [ints[k] for k in sorted(ints, key=int)]
            if ints and sorted(map(int, ints)) != list(range(1, len(ints) + 1)):
                s.sparse += 1
        if key in self.maps:
            items, named = items + list(named.values()), {}
        if not items and not named:
            s.empty += 1
            return
        if items:
            s.arrays += 1
            for v in items:
                self._value(s.items, f"{key}[]", family, v)
        if named:
            s.records += 1
            for k, v in named.items():
                slot = s.fields.setdefault(k, _Slot())
                if (family, k) in SHARED:
                    child, child_family = SHARED[(family, k)]
                else:
                    child = self.renames.get((key, k)) or _base(key) + _pascal(k)
                    child_family = family
                    self.fields_of.setdefault(child, set()).add((key, k))
                self._value(slot, child, child_family, v, (key, k))

    def _value(
        self,
        slot: _Slot,
        child: str,
        family: str,
        v: Any,
        origin: tuple[str, str] | None = None,
    ) -> None:
        slot.present += 1
        if isinstance(v, (dict, list)):
            slot.tables += 1
            slot.child = child
            if origin:
                self.shape(child, family).origins.add(origin)
            self._table(child, family, v)
        elif isinstance(v, str) and (m := _REF.match(v)):
            slot.types[REF_KINDS.get(m.group(1), "table")] += 1
        elif type(v) in _SCALARS:
            slot.types[_SCALARS[type(v)]] += 1


def _is_index(key: str) -> bool:
    return key.isascii() and key.isdigit()


def _is_map(s: _Shape) -> bool:
    if len(s.fields) < MAP_MIN_KEYS or not s.records:
        return False
    return max(f.present for f in s.fields.values()) <= MAP_MAX_SHARE * s.records


def collect(records: list[tuple[Kind, Any]]) -> _Collector:
    """Merge ``records`` into shapes, re-walking until the set of map-typed
    tables is stable (a map's values merge into one type) and no two fields
    name the same type (``a_b`` and ``aB``: the later-sorted gets ``_2``...)."""
    maps = set(MAPS)
    renames: dict[tuple[str, str], str] = {}
    while True:
        c = _Collector(maps, renames)
        for kind, value in records:
            c.add_record(kind, value)
        found = {k for k, s in c.shapes.items() if _is_map(s)}
        clashes: dict[tuple[str, str], str] = {}
        for child, sources in c.fields_of.items():
            names = sorted({f for _, f in sources})
            for i, name in enumerate(names[1:], 2):
                clashes.update(
                    (src, f"{child}_{i}") for src in sources if src[1] == name
                )
        if found <= maps and not clashes:
            _merge_identical(
                c, {k.key for k, _ in records} | {v for v, _ in SHARED.values()}
            )
            return c
        maps = maps | found
        renames = renames | clashes


def _merge_identical(c: _Collector, preferred: set[str]) -> None:
    """Fold types of identical shape (fields, their types and whether each is
    in every table, recursively) held by fields of the same name into one,
    preferring a ``preferred`` key, then the shallowest, shortest, first-sorted
    one."""
    ids: dict[Any, int] = {}
    sig: dict[str, int] = {}

    def slot_sig(slot: _Slot) -> Any:
        child = shape_sig(slot.child) if slot.tables and slot.child else None
        return tuple(sorted(slot.types)), child

    def shape_sig(key: str) -> int:
        if key not in sig:
            s = c.shapes[key]
            fields = tuple(
                (n, slot_sig(f), f.present == s.records)
                for n, f in sorted(s.fields.items())
            )
            items = slot_sig(s.items) if s.arrays else None
            whole = (key in c.maps, s.records > 0, s.arrays > 0, fields, items)
            sig[key] = ids.setdefault(whole, len(ids))
        return sig[key]

    def role(key: str) -> Any:
        s = c.shapes[key]
        if s.origins:
            return frozenset(f for _, f in s.origins)
        if key.endswith("[]") and key[:-2] in c.shapes:
            return ("[]", role(key[:-2]))
        return key

    groups: dict[tuple[Any, int], list[str]] = {}
    for key in sorted(c.shapes):
        groups.setdefault((role(key), shape_sig(key)), []).append(key)
    canon: dict[str, str] = {}
    for keys in groups.values():
        first = min(keys, key=lambda k: (k not in preferred, k.count("[]"), len(k), k))
        canon.update((k, first) for k in keys)

    def remap(slot: _Slot) -> None:
        if slot.child:
            slot.child = canon[slot.child]
        slot.types = Counter({canon.get(t, t): n for t, n in slot.types.items()})

    merged: dict[str, _Shape] = {}
    for key in sorted(c.shapes, key=lambda k: canon[k] != k):
        s = c.shapes[key]
        for slot in (s.items, *s.fields.values()):
            remap(slot)
        s.origins = {(canon[p], f) for p, f in s.origins}
        target = merged.setdefault(canon[key], s)
        if target is not s:
            _add(target, s)
    c.shapes = merged
    c.maps = {canon[k] for k in c.maps if k in canon}


def _add(into: _Shape, s: _Shape) -> None:
    for attr in ("count", "records", "arrays", "sparse", "empty"):
        setattr(into, attr, getattr(into, attr) + getattr(s, attr))
    into.origins |= s.origins
    for mine, theirs in [(into.items, s.items)] + [
        (into.fields[n], f) for n, f in s.fields.items()
    ]:
        mine.present += theirs.present
        mine.tables += theirs.tables
        mine.types += theirs.types


@dataclass
class _Type:
    name: str
    family: str
    body: dict[str, Any]


class _Renderer:
    def __init__(self, c: _Collector) -> None:
        self.c = c
        self.names: dict[tuple[str, str], str] = {}  # (key, role) -> type name
        self.claimed: set[str] = set()
        self.types: dict[str, _Type] = {}
        self._claim_records()

    def _claim(self, key: str, role: str, suffixes: tuple[str, ...]) -> str:
        if (key, role) in self.names:
            return self.names[(key, role)]
        base = _base(key)
        for i in itertools.count(1):
            for suffix in suffixes:
                name = base + suffix + (str(i) if i > 1 else "")
                if name not in self.claimed:
                    self.claimed.add(name)
                    self.names[(key, role)] = name
                    return name
        raise AssertionError("unreachable")

    def _is_record(self, key: str) -> bool:
        s = self.c.shapes[key]
        return key not in self.c.maps and bool(s.fields)

    def _claim_records(self) -> None:
        for key in sorted(self.c.shapes, key=lambda k: (k.count("[]"), k)):
            if self._is_record(key):
                self._claim(key, "record", ("", "Item"))

    def render(self) -> dict[str, _Type]:
        for key in sorted(self.c.shapes):
            if self._is_record(key):
                self.table_type(key)
        return dict(sorted(self.types.items()))

    def table_type(self, key: str) -> str:
        """A typeRef for the tables at ``key``: a single name, ``X[]``,
        ``map<X>``, ``table``, or ``X[] | Name`` for a record with an array
        part (the format has no intersection)."""
        s = self.c.shapes[key]
        if self._is_record(key):
            name = self.names[(key, "record")]
            if name not in self.types:
                self.types[name] = _Type(name, s.family, {})
                self.types[name].body = self._record(key, s)
            return f"{self.element(key)}[] | {name}" if s.arrays else name
        if key in self.c.maps:
            return f"map<{self.element(key)}>"
        if s.arrays:
            return f"{self.element(key)}[]"
        return "table"

    def element(self, key: str) -> str:
        """A single type name for the array elements (or map values) of ``key``."""
        s = self.c.shapes[key]
        parts = self.slot_parts(s.items)
        if len(parts) == 1 and not _compound(parts[0]):
            return parts[0]
        child = s.items.child or f"{key}[]"
        if len(parts) == 1:
            name = self._claim(child, "list", ("", "List"))
            if name not in self.types:
                body: dict[str, Any] = {"kind": "array", "arrayOf": parts[0][:-2]}
                if parts[0].startswith("map<"):
                    body = {"kind": "union", "anyOf": parts}
                body["description"] = self._observed(child)
                self.types[name] = _Type(name, s.family, body)
            return name
        if all(p in _SCALAR_NAMES for p in parts):
            name = "DcsDb." + "Or".join(p.capitalize() for p in parts)
            self.types.setdefault(
                name,
                _Type(
                    name,
                    s.family,
                    {
                        "kind": "union",
                        "description": f"A {' or '.join(parts)}.",
                        "anyOf": parts,
                    },
                ),
            )
            return name
        name = self._claim(child, "union", ("Entry",))
        if name not in self.types:
            self.types[name] = _Type(
                name,
                s.family,
                {
                    "kind": "union",
                    "description": self._where("Array element", key)
                    + " "
                    + _breakdown(s.items),
                    "anyOf": parts,
                },
            )
        return name

    def slot_parts(self, slot: _Slot) -> list[str]:
        parts = sorted(t for t in slot.types if t in _SCALAR_NAMES)
        tables = [
            self.table_type(t) if t in self.c.shapes else "table"
            for t in sorted(slot.types)
            if t not in _SCALAR_NAMES
        ]
        if slot.tables and slot.child:
            tables.append(self.table_type(slot.child))
        for t in tables:
            parts += (p for p in union_parts(t) if p not in parts)
        return parts

    def _origins(self, key: str) -> list[str]:
        s = self.c.shapes[key]
        if s.origins:
            return sorted(
                f"{self.names.get((p, 'record'), _base(p))}.{f}" for p, f in s.origins
            )
        if key.endswith("[]") and key[:-2] in self.c.shapes:
            return [f"{o}[]" for o in self._origins(key[:-2])]
        return []

    def _where(self, text: str, key: str) -> str:
        origins = self._origins(key)
        if origins:
            shown = ", ".join(f"`{o}[]`" for o in origins[:4])
            more = f" and {len(origins) - 4} more" if len(origins) > 4 else ""
            text += f" at {shown}{more}"
        return text + "."

    def _observed(self, key: str) -> str:
        s = self.c.shapes[key]
        text = f"Inferred from {s.count} tables of the _G dump"
        origins = self._origins(key)
        if origins:
            shown = ", ".join(f"`{o}`" for o in origins[:4])
            more = f" and {len(origins) - 4} more" if len(origins) > 4 else ""
            text += f", at {shown}{more}"
        text += "."
        if s.sparse:
            text += f" {s.sparse} have holes in their integer keys."
        return text

    def _record(self, key: str, s: _Shape) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        for name in sorted(s.fields):
            slot = s.fields[name]
            parts = self.slot_parts(slot)
            desc = f"Present in {slot.present} of {s.records} tables."
            if len(parts) > 1 and len(slot.types) + bool(slot.tables) > 1:
                desc += " " + _breakdown(slot)
            fields[name] = {"type": " | ".join(parts) or "any", "description": desc}
        body: dict[str, Any] = {"kind": "record", "description": self._observed(key)}
        if s.arrays:
            body["description"] += (
                f" Also holds array entries in {s.arrays} of them: "
                f"`{self.element(key)}`."
            )
        body["fields"] = fields
        body["required"] = sorted(
            n for n, f in s.fields.items() if f.present == s.records
        )
        return body


def _compound(t: str) -> bool:
    return "|" in t or t.endswith("[]") or t.startswith("map<")


def _breakdown(slot: _Slot) -> str:
    counts = Counter(slot.types)
    if slot.tables:
        counts["table"] += slot.tables
    return (
        "Observed as "
        + ", ".join(f"{t} ({n})" for t, n in sorted(counts.items()))
        + "."
    )


def render_yaml(
    types: list[_Type], family: str, total: int, version: str | None
) -> str:
    out = [
        "# Types of DCS's internal database tables (db.Units, weapons_table, "
        f"launcher, Pylons, db.Countries), inferred from a dump of DCS "
        f"{version or 'unknown'}. For published reference data use Entity.*",
        f"# {family} tables: {total} records of the _G dump.",
        f"# {VERSION_TAG}{version or 'unknown'}",
        "# Generated by tools/datamine/dcs_database_types.py; do not edit.",
        "globals: {}",
        "",
        "types:",
    ]
    for t in types:
        out.append(f"  {yaml_key(t.name)}:")
        for k, v in t.body.items():
            if k == "fields":
                out.append("    fields:")
                for fname, fdef in v.items():
                    out.append(f"      {yaml_key(fname)}:")
                    out.append(f"        type: {json.dumps(fdef['type'])}")
                    out.append(
                        f"        description: {json.dumps(fdef['description'])}"
                    )
            elif isinstance(v, list):
                out.append(f"    {k}: [{', '.join(json.dumps(i) for i in v)}]")
            else:
                out.append(f"    {k}: {json.dumps(v)}")
        out.append("")
    return "\n".join(out[:-1]) + "\n"


def read_records(
    g_dir: Path, kinds: tuple[Kind, ...] = KINDS, texts: dict[Path, str] | None = None
) -> list[tuple[Kind, Any]]:
    """Every record of ``kinds``, refs left as path strings (``texts``:
    ``LuaReader.texts`` of an extraction of the same dump)."""
    reader = LuaReader(link_refs=False, texts=texts)
    kind_of: list[Kind] = []
    files: list[Path] = []
    for kind in kinds:
        path = g_dir / kind.path
        found = [path] if path.suffix == ".lua" else list_lua(path)
        if not found or not found[0].exists():
            fail(f"no records for {kind.key} under {path}")
        kind_of += [kind] * len(found)
        files += found
    out = [
        (kind, value)
        for kind, (_, value) in zip(kind_of, reader.read_many(files), strict=True)
    ]
    if reader.stats.failures:
        name, err = reader.stats.failures[0]
        fail(
            f"{len(reader.stats.failures)} unreadable dump file(s), first {name}: {err}"
        )
    return out


def generate(
    g_dir: Path, kinds: tuple[Kind, ...] = KINDS, texts: dict[Path, str] | None = None
) -> dict[str, str]:
    """``{file name: YAML}`` for every family of ``kinds``."""
    records = read_records(g_dir, kinds, texts)
    types = _Renderer(collect(records)).render()
    totals = Counter(k.family for k, _ in records)
    by_family: dict[str, list[_Type]] = {f: [] for f in totals}
    for t in types.values():
        by_family[t.family].append(t)
    version = read_version(g_dir)
    return {
        f"{family}{SUFFIX}": render_yaml(
            by_family[family], family, totals[family], version
        )
        for family in sorted(by_family)
    }


def committed_version(out: Path) -> str | None:
    """The DCS version the files under ``out`` were generated from."""
    for path in sorted(out.glob(f"*{SUFFIX}")) if out.is_dir() else []:
        for line in path.read_text(encoding="utf-8").splitlines()[:5]:
            if line.startswith(f"# {VERSION_TAG}"):
                return line[len(f"# {VERSION_TAG}") :]
    return None


def write(files: dict[str, str], out: Path) -> None:
    """Make the generated files under ``out`` exactly ``files``."""
    write_generated(out, files, SUFFIX)


def _check_key(g_dir: Path, out: Path) -> str | None:
    """Identifies a check: the dump (version marker and its mtime), the
    committed files and the code that generates them; None without a marker."""
    marker = g_dir / VERSION_MARKER
    try:
        stamp = f"{marker.resolve()}\0{marker.stat().st_mtime_ns}\0"
        h = hashlib.sha256(stamp.encode() + marker.read_bytes())
    except FileNotFoundError:
        return None
    code = (Path(__file__), Path(lua_reader.__file__), Path(spec_types.__file__))
    generated = sorted(out.glob(f"*{SUFFIX}")) if out.is_dir() else []
    for path in (*code, *generated):
        h.update(f"\0{path.name}\0".encode() + path.read_bytes())
    return h.hexdigest()


def _cached_check(key: str | None) -> bool:
    if key is None:
        return False
    try:
        return CHECK_CACHE.read_text(encoding="utf-8") == key
    except FileNotFoundError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--g-dir",
        type=Path,
        default=CACHED_G_DIR,
        help="_G dump dir (default: .datamine/_G).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=OUT_DIR,
        help="Schema types dir (default: dcs-world-schema/types/dcs-database).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if the files under --out differ from what the dump produces.",
    )
    parser.add_argument(
        "--if-dumped",
        action="store_true",
        help="Skip (exit 0) when there is no dump, or it is of another DCS "
        "version than the files under --out.",
    )
    args = parser.parse_args(argv)
    if args.if_dumped:
        dumped = read_version(args.g_dir) if args.g_dir.is_dir() else None
        committed = committed_version(args.out)
        if dumped is None or dumped != committed:
            print(
                f"Skipping DCS database types: dump {args.g_dir} is "
                f"{dumped or 'absent'}, {args.out} is {committed or 'absent'}"
            )
            return 0
    if not args.g_dir.is_dir():
        parser.error(f"_G dir not found: {args.g_dir}")
    if args.check:
        key = _check_key(args.g_dir, args.out)
        if _cached_check(key):
            print(
                f"DCS database types in {args.out} match {args.g_dir} (checked before)"
            )
            return 0
    files = generate(args.g_dir)
    if args.check:
        stale = generated_drift(args.out, files, SUFFIX)
        if stale:
            fail(
                f"DCS database types out of date ({', '.join(stale)}); "
                "run `task datamine:dcs-database-types`"
            )
        if key is not None:
            write_text_if_changed(CHECK_CACHE, key)
        print(f"DCS database types in {args.out} match {args.g_dir}")
        return 0
    write(files, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
