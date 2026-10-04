"""Exact-id joins of the curated records to the ``_G`` dump files that
define them: each joined record gets ``sourcePaths`` (dump paths,
``dump_paths``). Joins are by exact DCS ids only, never by display name:

* weapons: the projectile records named the weapon's ``name`` in
  ``extract_stores.PROJECTILE_DIRS``: the first (the extractor's) and every
  other one that is provably the same object (equal ``_unique_resource_name``,
  else equal complete ``ws_type``; ``extract_stores.SameName``). A same-name
  record that is not is reported ambiguous, not joined.
* warheads: the ``_G/warheads`` records the weapon's files refer to at
  ``warhead`` (top level, ``client``, ``server``) and those files holding
  one inline; a cluster warhead (``<weapon>.cluster``) the weapon's first
  file holding that cluster block.
* stores: ``launcher`` records by ``CLSID``; racks: ``Pylons`` records by
  ``ShapeName``; sensors: ``db/Sensors`` records by ``Name``; gun ammo:
  ``weapons_table/weapons/shells`` records by ``name``; units: the
  ``db/Units/<category>`` records of the series' categories by ``type``.

Several candidates for one entity are ambiguous and none is joined. The
counts and the failed joins go into the extraction manifest
(``Joins.manifest``) and its warnings.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from .common import walk_lua
from .dump_paths import DumpPaths
from .extract_stores import _CLUSTER_WARHEADS, PROJECTILE_DIRS, UNNAMED, SameName
from .extract_units import AIRCRAFT_DIRS, SURFACE_DIRS
from .lua_reader import LuaTable, Marker, SourceRef

# Join categories, in report order: (series, entity type).
JOIN_SERIES: tuple[tuple[str, str], ...] = (
    ("weapons", "Entity.Weapon"),
    ("warheads", "Entity.Warhead"),
    ("weapon_flight", "Entity.WeaponFlight"),
    ("aircraft_flight", "Entity.AircraftFlight"),
    ("stores", "Entity.Store"),
    ("racks", "Entity.Rack"),
    ("gun_ammo", "Entity.GunAmmo"),
    ("sensors", "Entity.Sensor"),
    ("aircraft", "Entity.Aircraft"),
    ("ground_vehicles", "Entity.GroundVehicle"),
    ("personnel", "Entity.Personnel"),
    ("ships", "Entity.Ship"),
    ("structures", "Entity.Structure"),
)
UNIT_DIRS: dict[str, tuple[str, ...]] = {
    "aircraft": tuple(AIRCRAFT_DIRS),
    **{s: tuple(dirs) for s, dirs in SURFACE_DIRS.items()},
}
# The dump dirs whose files the joins read.
JOIN_DIRS: tuple[str, ...] = (
    *("/".join(parts) for parts in PROJECTILE_DIRS),
    "warheads",
    "launcher",
    "Pylons",
    "weapons_table/weapons/shells",
    "db/Sensors",
    *(f"db/Units/{d}" for dirs in UNIT_DIRS.values() for d in dirs),
)
# Top-level identity fields kept for the joins.
_ID_FIELDS = ("name", "_unique_resource_name", "CLSID", "type", "Name", "ShapeName")
_WARHEAD_KEYS = ("warhead",)
_VARIANTS = (None, "client", "server")


@dataclass
class Source:
    """One dump file and the identity fields the joins read."""

    path: str  # dump path: _G/<file path without .lua>
    ids: dict[str, Any]
    ws_type: tuple[Any, ...] | None
    warhead_refs: list[str]
    inline_warhead: bool
    # Suffixes (``cluster``, ``cluster2``) of the cluster warheads it holds.
    cluster_warheads: set[str] = field(default_factory=set)


@dataclass
class JoinIssue:
    entity: str
    reason: str
    candidates: list[str] = field(default_factory=list)

    def json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"entity": self.entity, "reason": self.reason}
        if self.candidates:
            out["candidates"] = self.candidates
        return out

    def line(self) -> str:
        more = f" (candidates: {', '.join(self.candidates)})" if self.candidates else ""
        return f"{self.entity}: {self.reason}{more}"


@dataclass
class Sources:
    by_path: dict[str, Source] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    joins: dict[str, Counter[str]] = field(default_factory=dict)
    ambiguous: list[JoinIssue] = field(default_factory=list)
    unresolved: list[JoinIssue] = field(default_factory=list)

    def manifest(self) -> dict[str, Any]:
        """The ``dumpJoins`` of the extraction manifest (``Entity.DumpJoins``)."""
        joins = []
        for _, type_name in JOIN_SERIES:
            c = self.joins.get(type_name, Counter())
            joins.append(
                {
                    "entityType": type_name,
                    "resolved": c["resolved"],
                    "ambiguous": c["ambiguous"],
                    "unresolved": c["unresolved"],
                }
            )
        return {
            "counts": joins,
            "ambiguous": [i.json() for i in self.ambiguous],
            "unresolved": [i.json() for i in self.unresolved],
        }

    def warnings(self) -> list[str]:
        return [
            *(f"ambiguous dump join {i.line()}" for i in self.ambiguous),
            *(f"unresolved dump join {i.line()}" for i in self.unresolved),
        ]


# --- reading ----------------------------------------------------------------


def _record(tree: Any) -> Any:
    """The record table: a record holding a ref to itself is an anchor."""
    if isinstance(tree, Marker) and tree.kind == "anchor":
        return tree.fields.get("value")
    return tree


def _scalar_ids(tree: Any) -> dict[str, Any]:
    if not isinstance(tree, LuaTable):
        return {}
    return {
        k: v
        for k in _ID_FIELDS
        if isinstance(v := tree.get(k), (str, int, float)) and not isinstance(v, bool)
    }


def _ws_type(tree: Any) -> tuple[Any, ...] | None:
    """The record's complete ``ws_type`` naming one object (as
    ``extract_stores._ws_identity``: four levels, the last no redaction)."""
    ws = tree.get("ws_type") if isinstance(tree, LuaTable) else None
    seq = ws.sequence() if isinstance(ws, LuaTable) else None
    if seq is None or len(seq) != 4:
        return None
    if isinstance(seq[3], Marker) or seq[3] in UNNAMED:
        return None
    if not all(isinstance(v, (str, int, float)) for v in seq):
        return None
    return tuple(int(v) if isinstance(v, float) and v.is_integer() else v for v in seq)


def _warheads(tree: Any) -> tuple[list[str], bool]:
    """(the ``_G/warheads`` refs at ``warhead`` of the record and its
    ``client``/``server`` blocks, whether one of those is inline)."""
    refs: list[str] = []
    inline = False
    if not isinstance(tree, LuaTable):
        return refs, inline
    for variant in _VARIANTS:
        block = tree if variant is None else tree.get(variant)
        if not isinstance(block, LuaTable):
            continue
        for key in _WARHEAD_KEYS:
            value = block.get(key)
            if isinstance(value, SourceRef):
                refs.append(value.path)
            elif isinstance(value, LuaTable) and value.entries:
                inline = True
    return sorted(set(refs)), inline


def _path_get(tree: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(tree, LuaTable):
            return None
        tree = tree.get(key)
    return tree


def _cluster_warheads(tree: Any) -> set[str]:
    """Suffixes of the warheads of the record's cluster block
    (``client.launcher.cluster``, else ``launcher.cluster``; as
    ``extract_stores._cluster``)."""
    block = _path_get(tree, "client", "launcher", "cluster")
    if not isinstance(block, LuaTable) or not block.entries:
        block = _path_get(tree, "launcher", "cluster")
    client = _path_get(block, "client")
    return {
        suffix
        for key, suffix in _CLUSTER_WARHEADS.items()
        if isinstance(client, LuaTable) and isinstance(client.get(key), LuaTable)
    }


def build_sources(dump: DumpPaths) -> Sources:
    """The identity fields of every dump file under ``JOIN_DIRS``."""
    sources = Sources()
    for directory in JOIN_DIRS:
        for file in walk_lua(dump.g_dir / directory):
            rel = file.relative_to(dump.g_dir).as_posix().removesuffix(".lua")
            path = f"_G/{rel}"
            if path in sources.by_path:
                continue
            try:
                value = dump.file(path)
            except KeyError as e:
                sources.failures.append(str(e))
                continue
            table = _record(value)
            refs, inline = _warheads(table)
            sources.by_path[path] = Source(
                path,
                _scalar_ids(table),
                _ws_type(table),
                refs,
                inline,
                _cluster_warheads(table),
            )
    return sources


# --- joins ------------------------------------------------------------------


def _under(src: Source, prefix: str) -> bool:
    return src.path.startswith(f"_G/{prefix}/")


class _Linker:
    def __init__(self, sources: Sources, series: dict[str, dict[str, Any]]) -> None:
        self.sources = sources
        self.series = series

    def link(
        self, type_name: str, record: dict[str, Any], key: str, paths: list[str]
    ) -> None:
        record["sourcePaths"] = sorted(paths)
        self.sources.joins.setdefault(type_name, Counter())["resolved"] += 1

    def ambiguous(
        self, type_name: str, key: str, reason: str, candidates: list[str]
    ) -> None:
        self.sources.joins.setdefault(type_name, Counter())["ambiguous"] += 1
        self.sources.ambiguous.append(
            JoinIssue(f"{type_name}:{key}", reason, sorted(candidates))
        )

    def unresolved(self, type_name: str, key: str, reason: str) -> None:
        self.sources.joins.setdefault(type_name, Counter())["unresolved"] += 1
        self.sources.unresolved.append(JoinIssue(f"{type_name}:{key}", reason))

    def by_field(
        self,
        series: str,
        type_name: str,
        prefixes: Iterable[str],
        id_field: str,
        what: str,
    ) -> None:
        """Join each record of ``series`` to the one source under
        ``prefixes`` whose ``id_field`` equals its id."""
        index: dict[Any, list[str]] = {}
        prefixes = tuple(prefixes)
        for src in self.sources.by_path.values():
            if any(_under(src, p) for p in prefixes) and id_field in src.ids:
                index.setdefault(src.ids[id_field], []).append(src.path)
        for key, record in sorted(self.series.get(series, {}).items()):
            found = index.get(key, [])
            if len(found) == 1:
                self.link(type_name, record, key, found)
            elif found:
                self.ambiguous(
                    type_name,
                    key,
                    f"several {what} records have {id_field} {key!r}",
                    found,
                )
            else:
                self.unresolved(
                    type_name, key, f"no {what} record has {id_field} {key!r}"
                )

    def weapons(self) -> dict[str, list[str]]:
        """Join the weapons; ``{weapon id: its source paths}``."""
        by_name: dict[str, list[tuple[str, Source]]] = {}
        for parts in PROJECTILE_DIRS:
            source_dir = "/".join(parts)
            for path in sorted(
                (p for p, s in self.sources.by_path.items() if _under(s, source_dir)),
                key=lambda p: f"{p}.lua",  # walk_lua's order
            ):
                src = self.sources.by_path[path]
                name = src.ids.get("name")
                if isinstance(name, str) and name:
                    by_name.setdefault(name, []).append((source_dir, src))
        out: dict[str, list[str]] = {}
        for wid, record in sorted(self.series.get("weapons", {}).items()):
            found = by_name.get(wid)
            if not found:
                self.unresolved(
                    "Entity.Weapon", wid, f"no projectile record has name {wid!r}"
                )
                continue
            same = [_same_name(d, s) for d, s in found]
            joined = [found[0][1].path]
            for (_, src), other in zip(found[1:], same[1:], strict=True):
                if same[0].same_object(other):
                    joined.append(src.path)
                else:
                    self.ambiguous(
                        "Entity.Weapon",
                        wid,
                        f"{src.path} has name {wid!r} but neither the "
                        "_unique_resource_name nor the complete ws_type of "
                        f"{found[0][1].path}; not joined",
                        [src.path],
                    )
            self.link("Entity.Weapon", record, wid, joined)
            out[wid] = joined
        return out

    def warheads(self, weapon_sources: dict[str, list[str]]) -> None:
        for wid, record in sorted(self.series.get("warheads", {}).items()):
            weapon, _, suffix = wid.rpartition(".")
            if wid not in weapon_sources and weapon in weapon_sources:
                # A cluster warhead ``<weapon>.<suffix>``: the extractor reads
                # it from the weapon's first source.
                first = self.sources.by_path[weapon_sources[weapon][0]]
                if suffix in first.cluster_warheads:
                    self.link("Entity.Warhead", record, wid, [first.path])
                else:
                    self.unresolved(
                        "Entity.Warhead",
                        wid,
                        f"{first.path} holds no cluster warhead {suffix!r}",
                    )
                continue
            srcs = [self.sources.by_path[p] for p in weapon_sources.get(wid, [])]
            refs = sorted({r for s in srcs for r in s.warhead_refs})
            missing = [r for r in refs if r not in self.sources.by_path]
            if missing:
                self.unresolved(
                    "Entity.Warhead",
                    wid,
                    f"warhead ref(s) to no dump file: {missing}",
                )
                continue
            paths = sorted({*refs, *(s.path for s in srcs if s.inline_warhead)})
            if paths:
                self.link("Entity.Warhead", record, wid, paths)
            else:
                self.unresolved(
                    "Entity.Warhead",
                    wid,
                    "no dump file of the weapon holds a warhead at warhead, "
                    "client.warhead or server.warhead",
                )


def _same_name(source_dir: str, src: Source) -> SameName:
    res = src.ids.get("_unique_resource_name")
    if source_dir.startswith("weapons_table/"):
        res = f"weapons.{source_dir.rsplit('/', 1)[-1]}.{src.ids['name']}"
    return SameName(source_dir, {}, res if isinstance(res, str) else None, src.ws_type)


def link_entities(sources: Sources, series: dict[str, dict[str, Any]]) -> None:
    """Set ``sourcePaths`` on the joined entity records of ``series``; record
    the ambiguous and unresolved joins."""
    linker = _Linker(sources, series)
    weapon_sources = linker.weapons()
    linker.warheads(weapon_sources)
    # The flight series name the dump files their extractor read.
    for name, type_name in (
        ("weapon_flight", "Entity.WeaponFlight"),
        ("aircraft_flight", "Entity.AircraftFlight"),
    ):
        for key, record in sorted(series.get(name, {}).items()):
            linker.link(type_name, record, key, record["sourcePaths"])
    linker.by_field("stores", "Entity.Store", ["launcher"], "CLSID", "launcher")
    linker.by_field("racks", "Entity.Rack", ["Pylons"], "ShapeName", "Pylons")
    linker.by_field(
        "gun_ammo", "Entity.GunAmmo", ["weapons_table/weapons/shells"], "name", "shell"
    )
    linker.by_field("sensors", "Entity.Sensor", ["db/Sensors"], "Name", "db.Sensors")
    for series_name, type_name in JOIN_SERIES:
        if series_name in UNIT_DIRS:
            linker.by_field(
                series_name,
                type_name,
                [f"db/Units/{d}" for d in UNIT_DIRS[series_name]],
                "type",
                "db.Units",
            )


def report(sources: Sources) -> list[str]:
    """Summary lines of the joins."""
    lines = []
    for _, type_name in JOIN_SERIES:
        c = sources.joins.get(type_name, Counter())
        lines.append(
            f"Dump joins {type_name}: {c['resolved']} resolved, "
            f"{c['ambiguous']} ambiguous, {c['unresolved']} unresolved"
        )
    return lines
