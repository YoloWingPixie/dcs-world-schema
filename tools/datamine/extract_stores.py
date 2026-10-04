"""Extract stores, weapons, warheads and racks from the projectile and launcher tables:

* ``Entity.Weapon``  - one per projectile (missile/bomb/rocket/torpedo), id = its ``name``.
* ``Entity.Warhead`` - one per projectile with a warhead, keyed by the weapon id.
* ``Entity.Store``   - one per launcher CLSID, with the weapons it delivers, aero and fuzes.
* ``Entity.Rack``    - one per adapter shape seen in launcher ``Elements``.

A store delivers what its ``Elements[].payload_CLSID`` stores deliver
(``nested``), else the projectile its ``wsTypeOfWeapon`` (or ``attribute``, also
through the raw tuples of ``__wstype_ids__.lua``) names (``exact``). Dumps
redact the name when the numeric wsType does not identify one projectile; those
stores fall back to matching ``Elements[].ShapeName`` against projectile names
and models (``shape``). Gun pods carry the shells of their ``gun_mounts`` (else
of their ``weapons_table.aircraft_gunpods`` entry) as ``gunAmmo``. Cluster
weapons carry their submunition block and its warheads (``add_weapon_details``).
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any

from . import weapon_flight
from .common import HAND_AUTHORED, assign_defined, fail, walk_lua, warn
from .dcs_constants import Constants
from .lua_reader import (
    LuaReader,
    array_entries,
    as_dict,
    as_flag,
    as_number,
    as_string,
    first_number,
    km,
    strings_of,
)
from .overlays import Overlays, unused_keys
from .rwr import WsTypeIds

# Projectile source dirs in precedence order (first definition of a name wins).
PROJECTILE_DIRS: list[tuple[str, ...]] = [
    ("weapons_table", "weapons", "missiles"),
    ("weapons_table", "weapons", "bombs"),
    ("weapons_table", "weapons", "nurs"),
    ("weapons_table", "weapons", "torpedoes"),
    ("bombs",),
    ("rockets",),
    ("torpedoes",),
]

# Launcher ``category`` names that fix a store kind; a weapon category makes it
# single or a rack by its load count.
_CATEGORY_KIND = {"CAT_FUEL_TANKS": "fuel-tank", "CAT_PODS": "pod"}
_WEAPON_CATEGORIES = {"CAT_BOMBS", "CAT_MISSILES", "CAT_ROCKETS", "CAT_AIR_TO_AIR"}


def ws_type_levels(raw: dict[str, Any], constants: Constants) -> tuple[Any, Any]:
    """Levels 2 and 3 of ``ws_type``/``wsTypeOfWeapon`` when level 1 is
    wsType_Weapon (None for a level the tuple lacks)."""
    weapon = constants.value("wsType", "wsType_Weapon")
    for key in ("ws_type", "wsTypeOfWeapon"):
        ws = array_entries(raw.get(key))
        if len(ws) >= 2 and as_number(ws[0]) == weapon:
            return as_number(ws[1]), as_number(ws[2]) if len(ws) >= 3 else None
    return None, None


def set_subcategory(record: dict[str, Any], level3: Any, constants: Constants) -> bool:
    """``subcategory`` = wsType level 3, with ``subcategoryName`` its constant
    name among the level-3 constants of the record's ``categoryName``
    (``WEAPON_LEVEL3``; left out, and counted unresolved, when none has it)."""
    if as_number(level3) is None or "categoryName" not in record:
        return False
    record["subcategory"] = int(level3)
    if (name := constants.level3_name(record["categoryName"], level3)) is not None:
        record["subcategoryName"] = name
    return True


# ``_source`` values: taken from the delivering launchers' ``wsTypeOfWeapon``;
# from membership of DCS's own ``bombs`` table.
LAUNCHER = "launcher"
TABLE = "table"

# Slot-4 values that name no projectile: the dump's redaction and a DCS placeholder.
UNNAMED = {"Redacted", "</WSTYPE>"}


@dataclass
class Projectile:
    name: str
    raw: dict[str, Any]
    mass_kg: float | int | None


@dataclass(frozen=True)
class SameName:
    """A projectile record among those sharing its name: its source dir, the
    record, its DCS identity (``_unique_resource_name``, ``ws_type``) and its
    dump path (``_G/...`` without ``.lua``; empty when unknown)."""

    source_dir: str
    raw: dict[str, Any]
    resource: str | None
    ws_type: tuple[Any, ...] | None
    path: str = ""

    def same_object(self, other: SameName) -> bool:
        """Whether both records define one DCS object: equal resource names
        when both have one, else equal complete ``ws_type`` tuples."""
        if self.resource and other.resource:
            return self.resource == other.resource
        return self.ws_type is not None and self.ws_type == other.ws_type


def _ws_identity(raw: dict[str, Any]) -> tuple[Any, ...] | None:
    """The record's ``ws_type`` when it names one object: four levels, the
    last a projectile name or number (not ``UNNAMED``)."""
    ws = array_entries(raw.get("ws_type"))
    if len(ws) != 4 or ws[3] in UNNAMED:
        return None
    return tuple(ws)


@dataclass
class ProjectileIndex:
    by_name: dict[str, Projectile] = field(default_factory=dict)
    bombs: list[Projectile] = field(default_factory=list)  # every _G/bombs record
    lookup: dict[str, str] = field(default_factory=dict)  # lowercased ShapeName -> name
    # _unique_resource_name -> name
    by_resource: dict[str, str] = field(default_factory=dict)
    # name -> every projectile record of that name, PROJECTILE_DIRS order
    same_name: dict[str, list[SameName]] = field(default_factory=dict)
    no_mass: list[str] = field(default_factory=list)
    no_name: list[str] = field(default_factory=list)
    # "<name>: <first record> vs <record>" for a later same-name record that
    # does not define the first one's DCS object (SameName.same_object); the
    # name stays the first record's (PROJECTILE_DIRS precedence), reported.
    ambiguous: list[str] = field(default_factory=list)


def _mass(raw: dict[str, Any]) -> float | int | None:
    client = as_dict(raw.get("client"))
    return first_number(
        raw.get("M"), raw.get("mass"), client.get("M"), client.get("mass")
    )


def _shapes(raw: dict[str, Any]) -> list[str]:
    """The projectile's ``model``/``shape_name`` values."""
    return [
        v for k in ("model", "shape_name", "ShapeName") if (v := as_string(raw.get(k)))
    ]


def _dump_path(g_dir: Path, file: Path) -> str:
    """``_G/<path>`` of a dump file without ``.lua`` (its dump path, ``dump_paths``)."""
    try:
        rel = Path(file).relative_to(g_dir)
    except ValueError:
        return ""
    return "/".join(("_G", *rel.with_suffix("").parts))


def collect_projectiles(reader: LuaReader, g_dir: Path) -> ProjectileIndex:
    index = ProjectileIndex()
    for parts in PROJECTILE_DIRS:
        source_dir = "/".join(parts)
        for file, raw in reader.read_many(walk_lua(g_dir.joinpath(*parts))):
            if not isinstance(raw, dict):
                continue
            name = as_string(raw.get("name"))
            if not name:
                index.no_name.append(str(file))
                continue
            proj = Projectile(name, raw, _mass(raw))
            res = as_string(raw.get("_unique_resource_name"))
            if parts[0] == "weapons_table":
                # weapons_table.weapons.<dir>.<name> is resource weapons.<dir>.<name>;
                # a few records omit the field.
                path = f"weapons.{parts[-1]}.{name}"
                if res not in (None, path):
                    fail(
                        f"{source_dir}/{name}: _unique_resource_name {res!r} != {path!r}"
                    )
                res = path
            if res:
                index.by_resource.setdefault(res, name)
            if source_dir == "bombs":
                index.bombs.append(proj)
            record = SameName(
                source_dir, raw, res, _ws_identity(raw), _dump_path(g_dir, file)
            )
            index.same_name.setdefault(name, []).append(record)
            if name in index.by_name:
                first = index.same_name[name][0]
                if not first.same_object(record):
                    index.ambiguous.append(
                        f"{name}: {first.path or first.source_dir} vs {record.path or source_dir}"
                    )
                continue
            index.by_name[name] = proj
            if proj.mass_kg is None:
                index.no_mass.append(f"{source_dir}/{name}")
    # Launcher Elements[].ShapeName -> projectile, matched against each
    # projectile's name and shapes; the first projectile (dir precedence) wins.
    for name, proj in index.by_name.items():
        for key in (name, *_shapes(proj.raw)):
            index.lookup.setdefault(key.lower(), name)
    return index


def _warhead_table(raw: dict[str, Any]) -> dict[str, Any] | None:
    """A record's ``warhead`` (else ``client.warhead``) table with a numeric
    ``mass`` (the reader links ``"_G/warheads/X.lua"`` refs)."""
    for value in (raw.get("warhead"), as_dict(raw.get("client")).get("warhead")):
        if isinstance(value, dict) and as_number(value.get("mass")) is not None:
            return value
    return None


def _warhead(
    name: str, index: ProjectileIndex
) -> tuple[dict[str, Any], str | None] | None:
    """The weapon's warhead table, with the source dir when it is not the
    weapon's own record: its own record's, else that of the later same-name
    records defining the same DCS object (``SameName.same_object``); two of
    those with warheads of different masses are an error. None when none
    has one."""
    own, *others = index.same_name[name]
    if (wh := _warhead_table(own.raw)) is not None:
        return wh, None
    found = [
        (o.source_dir, t)
        for o in others
        if own.same_object(o) and (t := _warhead_table(o.raw)) is not None
    ]
    # A record without a numeric mass sorts first.
    masses = sorted(
        {as_number(t["mass"]) for _, t in found},
        key=lambda m: -math.inf if m is None else m,
    )
    if len(masses) > 1:
        fail(
            f"weapon {name}: its same-object records "
            f"{', '.join(d for d, _ in found)} give warhead masses {masses}"
        )
    return (found[0][1], found[0][0]) if found else None


def _warhead_type(wh: dict[str, Any]) -> str | None:
    """shaped-charge / AP / HE from the warhead's charge fields; None when the
    record has no charge to classify."""
    mass = as_number(wh.get("mass")) or 0
    expl = as_number(wh.get("expl_mass")) or 0
    if (as_number(wh.get("cumulative_factor")) or 0) > 0:
        return "shaped-charge"
    if (as_number(wh.get("piercing_mass")) or 0) > 0 and (
        mass <= 0 or expl < 0.5 * mass
    ):
        return "AP"
    if expl > 0:
        return "HE"
    return None


# ``_source`` value of a field read from the weapon's same-name ``_G/rockets``
# record (DCS's flat missile table) because its own record lacks it.
ROCKETS = "rockets"

# Flat missile-table fields a ``weapons_table`` record may lack while its
# same-object ``_G/rockets`` record carries them; where both carry one they must
# agree (asserted on every extraction).
ROCKETS_FIELDS = (
    "Head_Type",
    "Range_max",
    "D_max",
    "D_min",
    "LaunchDistData",
    "SeekerGen",
    "SeekerCooled",
    "SeekerSensivityDistance",
    "active_radar_lock_dist",
)


def _client(raw: dict[str, Any]) -> dict[str, Any]:
    """The record's ``client`` block, else the record (legacy flat records)."""
    client = raw.get("client")
    return client if isinstance(client, dict) else raw


def rockets_records(records: list[SameName]) -> list[SameName]:
    """The ``_G/rockets`` records among a weapon's same-name ``records``
    defining its DCS object: its own (the first) when it is one, and those
    of the same object (``SameName.same_object``)."""
    own = records[0]
    return [
        r
        for r in records
        if r.source_dir == ROCKETS and (r is own or own.same_object(r))
    ]


def _with_rockets(
    name: str, records: list[SameName]
) -> tuple[dict[str, Any], set[str]]:
    """The record's ``client`` fields plus the ``ROCKETS_FIELDS`` only its
    other ``rockets_records`` carry, and the names of those."""
    own = records[0]
    view = _client(own.raw)
    rockets = [r for r in rockets_records(records) if r is not own]
    if not rockets:
        return view, set()
    view, filled = dict(view), set()
    for other in rockets:
        for key in ROCKETS_FIELDS:
            if key not in other.raw:
                continue
            if key not in view:
                view[key] = other.raw[key]
                filled.add(key)
            elif view[key] != other.raw[key]:
                fail(
                    f"weapon {name}: {key} {view[key]!r} disagrees with _G/rockets "
                    f"{other.raw[key]!r}, so the rockets table no longer stands in for it"
                )
    return view, filled


# Range field -> the field naming the DCS field it was read from.
RANGE_FIELD_KEYS = {"rangeKm": "rangeField", "rangeMinKm": "rangeMinField"}


def _positive(value: Any) -> float | int | None:
    """A range number; DCS writes 0 for an unset range."""
    n = as_number(value)
    return n if n is not None and n > 0 else None


def launch_table_max(value: Any, where: str) -> float | int | None:
    """Largest cell of a DCS ``LaunchDistData`` table: ``{rows, cols, cols
    column headers, then per row its header and cols cells}``, in metres."""
    v = array_entries(value)
    if not v:
        return None
    rows, cols = as_number(v[0]), as_number(v[1])
    if (
        rows is None
        or cols is None
        or len(v) != 2 + cols + rows * (cols + 1)
        or any(as_number(x) is None for x in v)
    ):
        fail(f"{where}: LaunchDistData is not a {rows}x{cols} table: {v[:14]}...")
    width = int(cols) + 1
    start = 2 + int(cols)
    cells = [
        v[start + r * width + 1 + c] for r in range(int(rows)) for c in range(int(cols))
    ]
    return _positive(max(cells))


def _ranges(
    name: str, raw: dict[str, Any], view: dict[str, Any]
) -> dict[str, tuple[Any, str]]:
    """``{field: (km, DCS field)}`` of the record's ranges. ``rangeKm``: the
    first positive of ``Range_max``, ``D_max``, the largest ``LaunchDistData``
    cell, ``dist_max``. ``rangeMinKm``: ``D_min``, else ``dist_min`` (read with
    a positive ``dist_max``). ``launchRangeMaxKm``: ``D_max``."""
    out: dict[str, tuple[Any, str]] = {}
    dist_max = _positive(raw.get("dist_max"))
    for key, value in (
        ("Range_max", partial(_positive, view.get("Range_max"))),
        ("D_max", partial(_positive, view.get("D_max"))),
        ("LaunchDistData", partial(launch_table_max, view.get("LaunchDistData"), name)),
        ("dist_max", partial(_positive, raw.get("dist_max"))),
    ):
        if (metres := value()) is not None:
            out["rangeKm"] = (km(metres), key)
            break
    if (d_min := _positive(view.get("D_min"))) is not None:
        out["rangeMinKm"] = (km(d_min), "D_min")
    elif dist_max is not None and (d := _positive(raw.get("dist_min"))) is not None:
        out["rangeMinKm"] = (km(d), "dist_min")
    if (d_max := _positive(view.get("D_max"))) is not None:
        out["launchRangeMaxKm"] = (km(d_max), "D_max")
    return out


def _deg(radians: Any) -> float | None:
    n = as_number(radians)
    return round(math.degrees(n), 3) if n is not None else None


def _agreed(name: str, key: str, values: list[Any]) -> Any:
    """The one value the seeker blocks give for ``key`` (fail when they differ)."""
    found = {v for v in values if v is not None}
    if len(found) > 1:
        fail(f"weapon {name}: seeker blocks disagree on {key}: {sorted(found)}")
    return next(iter(found), None)


# Seeker blocks of the newer weapon schemes that carry ``max_seeker_range`` or ``cooled``.
_SEEKER_BLOCKS = (
    "seeker",
    "laser_seeker",
    "laser_spot_seeker",
    "sensor",
    "simple_IR_seeker",
    "IR_seeker",
)


def _seeker(name: str, view: dict[str, Any]) -> tuple[dict[str, Any], set[str]]:
    """The ``seeker`` parameters DCS types plainly, and the DCS fields they
    came from."""
    blocks = [as_dict(view.get(b)) for b in _SEEKER_BLOCKS]
    gimbal = as_dict(view.get("gimbal"))
    cooled = [
        v
        for v in [view.get("SeekerCooled"), *(b.get("cooled") for b in blocks)]
        if v is not None
    ]
    if any(not isinstance(v, bool) for v in cooled):
        fail(f"weapon {name}: seeker cooled flag is not a boolean: {cooled}")
    fields = {
        "generation": ("SeekerGen", as_number(view.get("SeekerGen"))),
        "cooled": ("SeekerCooled", _agreed(name, "cooled", cooled)),
        "irSensitivityRangeKm": (
            "SeekerSensivityDistance",
            km(_positive(view.get("SeekerSensivityDistance"))),
        ),
        "activeRadarLockRangeKm": (
            "active_radar_lock_dist",
            km(_positive(view.get("active_radar_lock_dist"))),
        ),
        "maxLockRangeKm": (
            "seeker.max_lock_dist",
            km(_positive(as_dict(view.get("seeker")).get("max_lock_dist"))),
        ),
        "maxSeekerRangeKm": (
            "max_seeker_range",
            km(
                _agreed(
                    name,
                    "max_seeker_range",
                    [_positive(b.get("max_seeker_range")) for b in blocks],
                )
            ),
        ),
        "gimbalAzimuthMaxDeg": (
            "gimbal",
            _deg(first_number(gimbal.get("yaw_max"), gimbal.get("az_max"))),
        ),
        "gimbalElevationMaxDeg": (
            "gimbal",
            _deg(first_number(gimbal.get("pitch_max"), gimbal.get("el_max"))),
        ),
    }
    seeker = {k: v for k, (_, v) in fields.items() if v is not None}
    return seeker, {src for k, (src, v) in fields.items() if v is not None}


def _guidance(name: str, records: list[SameName], record: dict[str, Any]) -> None:
    """Set the record's ``className``, ``scheme``, ``seekerType``, ``seeker``
    and ranges from its same-name ``records`` (its own first), stamping
    ``_source`` ``rockets`` on those read from a same-object ``_G/rockets``
    record."""
    view, filled = _with_rockets(name, records)
    stamps: dict[str, str] = {}
    assign_defined(
        record,
        {
            "className": as_string(view.get("class_name")),
            "scheme": as_string(view.get("scheme")),
        },
    )
    head = view.get("Head_Type")
    if head is not None:
        if as_number(head) is None or not float(head).is_integer():
            fail(f"weapon {name}: Head_Type {head!r} is not an integer")
        record["seekerType"] = int(head)
        if "Head_Type" in filled:
            stamps["seekerType"] = ROCKETS
    for key, (value, source) in _ranges(name, records[0].raw, view).items():
        record[key] = value
        if key in RANGE_FIELD_KEYS:
            record[RANGE_FIELD_KEYS[key]] = source
        if source in filled:
            stamps[key] = ROCKETS
    seeker, sources = _seeker(name, view)
    if seeker:
        record["seeker"] = seeker
        if sources & filled:
            stamps["seeker"] = ROCKETS
    if stamps:
        record.setdefault("_source", {}).update(stamps)


def build_weapons_and_warheads(
    index: ProjectileIndex, constants: Constants
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """(weapons, warheads)."""
    if index.no_mass or index.no_name:
        fail(
            f"projectiles without mass: {index.no_mass}; without name: {index.no_name}"
        )
    for line in index.ambiguous:
        warn(
            f"same-name projectile record of another DCS object (not a flight source): {line}"
        )
    for line in client_server_differences(index):
        warn(line)
    weapons: dict[str, dict[str, Any]] = {}
    warheads: dict[str, dict[str, Any]] = {}
    for name, proj in sorted(index.by_name.items()):
        raw = proj.raw
        record: dict[str, Any] = {
            "id": name,
            "displayName": as_string(raw.get("display_name")) or name,
            "massKg": proj.mass_kg,
            "attributes": sorted(strings_of(raw.get("attribute"))),
        }
        level2, level3 = ws_type_levels(raw, constants)
        constants.set_pair(record, "category", "Entity.WsTypeWeaponLevel2", level2)
        set_subcategory(record, level3, constants)
        constants.set_pair(
            record, "launcherCategory", "Entity.LauncherCategory", raw.get("category")
        )
        _guidance(name, index.same_name[name], record)
        found = _warhead(name, index)
        if found is not None:
            wh, wh_dir = found
            record["warhead"] = name
            if wh_dir is not None:
                record.setdefault("_source", {})["warhead"] = wh_dir
            warhead = _warhead_record(name, wh)
            assert warhead is not None  # _warhead only finds tables with a mass
            warheads[name] = warhead
        weapons[name] = record
    return weapons, warheads


def build_weapon_flight(index: ProjectileIndex) -> dict[str, dict[str, Any]]:
    """The ``weapon_flight`` series: ``Entity.WeaponFlight`` by weapon id."""
    out = {
        name: record
        for name in sorted(index.by_name)
        if (record := weapon_flight.flight(name, flight_sources(index.same_name[name])))
        is not None
    }
    print(f"Weapon flight records: {len(out)}; blocks: {weapon_flight.counts(out)}")
    return out


def flight_sources(records: list[SameName]) -> list[weapon_flight.Source]:
    """The flight sources of a weapon: its own record and the later same-name
    records defining the same DCS object."""
    own = records[0]
    return [
        weapon_flight.Source(r.path, r.source_dir.startswith("weapons_table/"), r.raw)
        for r in records
        if r is own or own.same_object(r)
    ]


# Keys the ``server`` block may differ from ``client`` in without affecting the
# public fields: the warheads' ``fantom`` flag and the launcher's ``server`` flag.
_SERVER_ONLY = {
    ("warhead", "fantom"),
    ("warhead_air", "fantom"),
    ("warhead_water", "fantom"),
    ("launcher", "server"),
}


def client_server_differences(index: ProjectileIndex) -> list[str]:
    """One line per ``weapons_table`` record whose ``server`` block differs
    from its ``client`` block beyond ``_SERVER_ONLY`` (the public fields read
    ``client``, as does ``weapon_flight``)."""
    out = []
    for name, records in sorted(index.same_name.items()):
        for r in records:
            client, server = r.raw.get("client"), r.raw.get("server")
            if not isinstance(client, dict) or not isinstance(server, dict):
                continue
            keys = sorted(
                k
                for k in set(client) | set(server)
                if _strip_server_only(k, client.get(k))
                != _strip_server_only(k, server.get(k))
            )
            if keys:
                out.append(
                    f"weapon {name} ({r.path or r.source_dir}): server block differs from client in "
                    f"{keys}; public fields and weapon_flight read client"
                )
    return out


def _strip_server_only(key: str, value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    return {k: v for k, v in value.items() if (key, k) not in _SERVER_ONLY}


# ``_source`` value of a weapon ``warhead`` taken from its cluster block.
CLUSTER = "cluster"
# Cluster ``client`` blocks whose ``count`` is the submunition count, in order.
_SUBMUNITION_BLOCKS = ("bomblets", "cluster")
# Cluster warhead fields -> ``Entity.Warhead`` id suffix.
_CLUSTER_WARHEADS = {"warhead": "cluster", "warhead2": "cluster2"}


def _warhead_record(wid: str, wh: dict[str, Any]) -> dict[str, Any] | None:
    mass = as_number(wh.get("mass"))
    if mass is None:
        return None
    expl = as_number(wh.get("expl_mass"))
    record: dict[str, Any] = {"id": wid, "massKg": mass}
    assign_defined(
        record,
        {
            "type": _warhead_type(wh),
            "explosiveMassKg": expl,
            "fragmentation": expl > 0 if expl is not None else None,
            "hardTargetPenetrator": as_flag(wh.get("is_htp"), f"{wid}: is_htp"),
        },
    )
    return record


def _cluster(
    name: str, raw: dict[str, Any], warheads: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    """``Entity.Cluster`` from ``client.launcher.cluster`` (else
    ``launcher.cluster``); its warheads are added to ``warheads``."""
    block = as_dict(as_dict(_client(raw).get("launcher")).get("cluster")) or as_dict(
        as_dict(raw.get("launcher")).get("cluster")
    )
    if not block:
        return None
    client = as_dict(block.get("client"))
    submunition = as_string(block.get("name"))
    if not submunition or not client:
        fail(f"weapon {name}: cluster block without name or client: {sorted(block)}")
    elements = []
    for key, value in sorted(client.items()):
        if isinstance(value, dict) and (n := as_number(value.get("count"))) is not None:
            element: dict[str, Any] = {"name": key, "count": int(n)}
            assign_defined(
                element,
                {
                    "model": as_string(value.get("model_name")),
                    "massKg": as_number(value.get("mass")),
                },
            )
            elements.append(element)
    cluster: dict[str, Any] = {"submunition": submunition, "elements": elements}
    assign_defined(
        cluster,
        {
            "displayName": as_string(block.get("display_name")),
            "count": next(
                (
                    e["count"]
                    for b in _SUBMUNITION_BLOCKS
                    for e in elements
                    if e["name"] == b
                ),
                None,
            ),
        },
    )
    for key, suffix in _CLUSTER_WARHEADS.items():
        wh = client.get(key)
        if wh is None:
            continue
        record = _warhead_record(f"{name}.{suffix}", as_dict(wh))
        if record is None:
            fail(f"weapon {name}: cluster {key} has no mass: {wh!r}")
        warheads[record["id"]] = record
        cluster[key] = record["id"]
    return cluster


def _arming(name: str, raw: dict[str, Any]) -> dict[str, Any] | None:
    """``Entity.Arming`` from the ``client`` block's ``arming_delay`` and
    ``arming_vane``."""
    client = _client(raw)
    out: dict[str, Any] = {}
    for key, field_name, value_key, value_name in (
        ("arming_delay", "delay", "delay_time", "timeS"),
        ("arming_vane", "vane", "velK", "velK"),
    ):
        block = client.get(key)
        if block is None:
            continue
        block = as_dict(block)
        enabled, value = block.get("enabled"), as_number(block.get(value_key))
        if not isinstance(enabled, bool) or value is None:
            fail(f"weapon {name}: {key} {block!r} is not {{enabled, {value_key}}}")
        out[field_name] = {"enabled": enabled, value_name: value}
    return out or None


def add_weapon_details(
    weapons: dict[str, dict[str, Any]],
    warheads: dict[str, dict[str, Any]],
    index: ProjectileIndex,
) -> list[str]:
    """``cluster``, ``arming`` and ``natoName`` of each weapon. A weapon
    without a warhead of its own takes its cluster's ``warhead``
    (``_source.warhead: cluster``). Returns the ids of those."""
    effective = []
    for name, record in weapons.items():
        raw = index.by_name[name].raw
        cluster = _cluster(name, raw, warheads)
        assign_defined(
            record,
            {
                "cluster": cluster,
                "arming": _arming(name, raw),
                "natoName": as_string(raw.get("NatoName")),
            },
        )
        if cluster and "warhead" in cluster and "warhead" not in record:
            record["warhead"] = cluster["warhead"]
            record.setdefault("_source", {})["warhead"] = CLUSTER
            effective.append(name)
    return sorted(effective)


def _scalar_str(v: Any) -> str | None:
    if isinstance(v, str):
        return v
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(int(v)) if float(v).is_integer() else str(v)
    return None


def _fuzes(raw: dict[str, Any]) -> list[dict[str, str]]:
    """Nose-fuze options of the ``NFP_fuze_type_nose`` setting control."""
    for entry in array_entries(raw.get("settings")):
        if isinstance(entry, dict) and entry.get("id") == "NFP_fuze_type_nose":
            out = []
            for opt in array_entries(entry.get("values")):
                if (
                    isinstance(opt, dict)
                    and (value := _scalar_str(opt.get("id"))) is not None
                ):
                    fuze = {"id": value}
                    if (disp := _scalar_str(opt.get("dispName"))) is not None:
                        fuze["displayName"] = disp
                    out.append(fuze)
            return out
    return []


def _weapon_store_kind(loads: int, count: Any) -> str:
    """``rack`` for a weapon store carrying more than one item or declaring
    ``Count = 0`` (an empty rack or adapter), else ``single``."""
    return "rack" if loads > 1 or count == 0 else "single"


def _store_kind(
    raw: dict[str, Any], loads: int, category: str | None, constants: Constants
) -> str | None:
    """The store kind: from the launcher ``category`` name when present, else
    from the wsType in ``attribute`` (wsType_Air/wsType_Free_Fall/wsType_FuelTank
    fuel tank, wsType_Weapon/wsType_GContainer container), else from the load
    count alone for weapon stores (``_weapon_store_kind``)."""
    count = as_number(raw.get("Count"))
    if category in _CATEGORY_KIND:
        return _CATEGORY_KIND[category]
    if category in _WEAPON_CATEGORIES:
        return _weapon_store_kind(loads, count)
    ws = array_entries(raw.get("attribute"))[:3]
    air, free_fall, fuel_tank, weapon, container = (
        constants.value("wsType", n)
        for n in (
            "wsType_Air",
            "wsType_Free_Fall",
            "wsType_FuelTank",
            "wsType_Weapon",
            "wsType_GContainer",
        )
    )
    if ws == [air, free_fall, fuel_tank]:
        return "fuel-tank"
    if ws[:2] == [weapon, container]:
        return "pod"
    if ws[:1] == [weapon]:
        return _weapon_store_kind(loads, count)
    return None


@dataclass
class StoreStats:
    basis: Counter[str] = field(
        default_factory=Counter
    )  # nested/exact/loader/shape/none
    no_delivers: Counter[str] = field(default_factory=Counter)  # by store kind
    unknown_kind: list[str] = field(default_factory=list)
    unknown_weapon: Counter[str] = field(default_factory=Counter)  # unresolved names
    # CLSID -> (shape-matched weapons, loader name) / loader names that disagree
    loader_overrides: dict[str, tuple[list[str], str]] = field(default_factory=dict)
    loader_conflicts: dict[str, list[str]] = field(default_factory=dict)
    # CLSID -> projectiles sharing the store's raw attribute tuple
    ids_ambiguous: dict[str, list[str]] = field(default_factory=dict)
    # gunpods / db.Pods entries no store takes
    unused_gunpods: list[str] = field(default_factory=list)
    unused_pods: list[str] = field(default_factory=list)


def _slot4(raw: dict[str, Any]) -> str | None:
    """Slot 4 of ``wsTypeOfWeapon``: a projectile name, ``Redacted``, or None."""
    ws = array_entries(raw.get("wsTypeOfWeapon"))
    return as_string(ws[3]) if len(ws) == 4 else None


def _named(
    raw: dict[str, Any],
    index: ProjectileIndex,
    ids: list[tuple[int, int, int, int]],
    by_tuple: dict[tuple[int, int, int, int], list[str]],
) -> tuple[str | None, str | None, list[str]]:
    """(projectile, unresolved name, ambiguous names) the launcher names:
    ``wsTypeOfWeapon`` as slot 4 or as the ``_unique_resource_name`` the dump
    translated it to, else an ``attribute`` translated to a projectile's
    resource name, else the one projectile whose raw ``ws_type`` is the
    store's raw ``attribute`` tuple (``ids``, from ``__wstype_ids__.lua``); in
    both last cases the store's own wsType is that projectile's."""
    ws = raw.get("wsTypeOfWeapon")
    if isinstance(ws, str):
        name = index.by_resource.get(ws)
        return (name, None, []) if name else (None, ws, [])
    slot4 = _slot4(raw)
    if slot4 is not None and slot4 not in UNNAMED:
        return (slot4, None, []) if slot4 in index.by_name else (None, slot4, [])
    attribute = raw.get("attribute")
    if isinstance(attribute, str) and attribute in index.by_resource:
        return index.by_resource[attribute], None, []
    names = sorted({n for t in ids for n in by_tuple.get(t, []) if n in index.by_name})
    if len(names) == 1:
        return names[0], None, []
    return None, None, names


# ``_source`` values of store fields: taken from ``weapons_table.aircraft_gunpods``
# (the store's CLSID is its ``gunpod_name``); from the ``db.Pods`` entry of the
# store's ``displayName``.
GUNPODS = "aircraft_gunpods"
PODS = "pods"


def load_gunpods(entries: list[tuple[Path, Any]]) -> dict[str, dict[str, Any]]:
    """``weapons_table.aircraft_gunpods`` keyed by ``gunpod_name``."""
    out: dict[str, dict[str, Any]] = {}
    for file, raw in entries:
        name = as_string(as_dict(raw).get("gunpod_name"))
        if not name or name in out:
            fail(f"aircraft gunpod {file}: gunpod_name {name!r} missing or repeated")
        out[name] = raw
    return out


def load_pod_sensors(entries: list[tuple[Path, Any]]) -> dict[str, list[str]]:
    """``{DisplayName: sensor ids}`` of the ``db.Pods`` entries (their ``Name``
    is redacted in dumps), from every role under the entry."""
    out: dict[str, list[str]] = {}
    for file, raw in entries:
        name = as_string(as_dict(raw).get("DisplayName"))
        if not name or name in out:
            fail(f"db.Pods {file}: DisplayName {name!r} missing or repeated")
        out[name] = sensor_ids(raw, ("OPTIC", "RADAR", "RWR", "IRST"))
    return out


def sensor_ids(block: Any, roles: tuple[str, ...] | None = None) -> list[str]:
    """Sorted sensor ids under the roles (``OPTIC``, ``RADAR``...) of a DCS
    sensors table; a role holds one id or a list."""
    names: set[str] = set()
    for role, val in as_dict(block).items():
        if roles is not None and role not in roles:
            continue
        values = [val] if isinstance(val, str) else array_entries(val)
        names.update(s for s in values if isinstance(s, str) and s != "Redacted")
    return sorted(names)


def _gun_ammo(mounts: list[Any]) -> set[str]:
    """Shell names of ``mounts[].supply.shells[]``."""
    return {
        name
        for mount in mounts
        for shell in array_entries(as_dict(as_dict(mount).get("supply")).get("shells"))
        if (name := as_string(as_dict(shell).get("name")))
    }


def _guns(mounts: list[Any]) -> list[dict[str, Any]]:
    """``Entity.StoreGun`` per gun mount."""
    out = []
    for mount in mounts:
        mount = as_dict(mount)
        gun, supply = as_dict(mount.get("gun")), as_dict(mount.get("supply"))
        record: dict[str, Any] = {}
        rates = [r for r in array_entries(gun.get("rates")) if as_number(r) is not None]
        count = as_number(supply.get("count"))
        assign_defined(
            record,
            {
                "displayName": as_string(mount.get("display_name")),
                "shortName": as_string(mount.get("short_name")),
                "rates": rates or None,
                "rounds": int(count) if count is not None else None,
                "gunAmmo": sorted(_gun_ammo([mount])) or None,
                "effectiveFireDistance": as_number(
                    mount.get("effective_fire_distance")
                ),
            },
        )
        out.append(record)
    return out


def build_stores_and_racks(
    launchers: list[tuple[Path, Any]],
    index: ProjectileIndex,
    constants: Constants,
    ws_ids: WsTypeIds,
    gunpods: dict[str, dict[str, Any]] | None = None,
    pod_sensors: dict[str, list[str]] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], StoreStats]:
    """A store delivers, in order of precedence: the sum of the stores its
    ``Elements[].payload_CLSID`` load (``nested``); ``Count`` (else the mounts)
    of the projectile it names (``exact``, see ``_named``) or, failing that, the
    one projectile every store loading only it names (``loader``); the projectiles
    its ``Elements[].ShapeName`` match (``shape``). Its gun mounts are its own
    ``gun_mounts``, else those of the ``gunpods`` entry named by its CLSID
    (``_source: aircraft_gunpods``); ``gunAmmo`` is their shells, else those of
    its nested stores. ``sensors`` is its ``Sensors`` table, else that of the
    ``pod_sensors`` entry of its ``displayName`` (``_source: pods``)."""
    gunpods = gunpods or {}
    pod_sensors = pod_sensors or {}
    stats = StoreStats()
    by_tuple = ws_ids.by_tuple("projectiles")
    store_ids = ws_ids.stores
    stores: dict[str, dict[str, Any]] = {}
    racks: dict[str, dict[str, Any]] = {}
    nested: dict[str, list[str]] = {}
    own: dict[str, tuple[Counter[str], set[str], str]] = {}
    own_loads: dict[str, int] = {}
    parent_names: dict[str, set[str]] = {}  # payload CLSID -> names of its sole loaders
    used_gunpods: set[str] = set()
    used_pods: set[str] = set()
    count_zero: set[str] = set()
    for file, raw in launchers:
        if not isinstance(raw, dict):
            continue
        clsid = as_string(raw.get("CLSID"))
        if not clsid:
            fail(f"launcher without CLSID: {file}")
        adapter: str | None = None
        mounts = 0
        payloads: list[str] = []
        per_weapon: Counter[str] = Counter()
        for element in array_entries(raw.get("Elements")):
            if not isinstance(element, dict):
                continue
            shape = as_string(element.get("ShapeName"))
            if element.get("IsAdapter") is True:
                adapter = shape or adapter
                continue
            mounts += 1
            if payload := as_string(element.get("payload_CLSID")):
                payloads.append(payload)
            weapon = index.lookup.get(shape.lower()) if shape else None
            if weapon is not None:
                per_weapon[weapon] += 1

        count = as_number(raw.get("Count"))
        named, unresolved, ambiguous = _named(
            raw, index, store_ids.get(clsid, []), by_tuple
        )
        if ambiguous:
            stats.ids_ambiguous[clsid] = ambiguous
        if payloads:
            per_weapon, basis = Counter(), "nested"
            if len(payloads) != mounts:
                fail(f"store {clsid}: only some Elements carry payload_CLSID")
            nested[clsid] = payloads
        elif named is not None:
            per_weapon, basis = Counter({named: mounts}), "exact"
        elif unresolved is not None:
            per_weapon, basis = Counter(), "none"
            stats.unknown_weapon[unresolved] += 1
        else:
            basis = "shape"
        if len(per_weapon) == 1 and count is not None:
            per_weapon = Counter({next(iter(per_weapon)): int(count)})
        gun_mounts = array_entries(raw.get("gun_mounts"))
        if clsid in gunpods:
            used_gunpods.add(clsid)
        from_gunpods = not gun_mounts and clsid in gunpods
        if from_gunpods:
            gun_mounts = array_entries(gunpods[clsid].get("mounts"))
        own[clsid] = (per_weapon, _gun_ammo(gun_mounts), basis)
        if named is not None and len(set(payloads)) == 1:  # a mixed load names one
            parent_names.setdefault(payloads[0], set()).add(named)

        loads = int(count) if count is not None else sum(per_weapon.values()) or mounts
        own_loads[clsid] = int(count) if count is not None else mounts
        if count == 0:
            count_zero.add(clsid)
        record: dict[str, Any] = {
            "clsid": clsid,
            "displayName": as_string(raw.get("displayName"))
            or as_string(raw.get("name"))
            or clsid,
            "delivers": [],
            "aero": _store_aero(raw),
            "fuzes": _fuzes(raw),
        }
        constants.set_pair(
            record, "category", "Entity.LauncherCategory", raw.get("category")
        )
        kind = _store_kind(raw, loads, record.get("categoryName"), constants)
        if kind is None:
            stats.unknown_kind.append(clsid)
        record["kind"] = kind or "unknown"
        sensors = sensor_ids(raw.get("Sensors"))
        pod = pod_sensors.get(record["displayName"])
        source: dict[str, str] = {}
        if pod is not None:
            used_pods.add(record["displayName"])
            if sensors and pod and sensors != pod:
                fail(f"store {clsid}: Sensors {sensors} but its db.Pods entry {pod}")
            if not sensors and pod:
                sensors, source["sensors"] = pod, PODS
        if from_gunpods:
            source["guns"] = GUNPODS
            if own[clsid][1]:
                source["gunAmmo"] = GUNPODS
        assign_defined(
            record,
            {
                "rack": adapter,
                "guns": _guns(gun_mounts) or None,
                "sensors": sensors or None,
                "picture": as_string(raw.get("Picture")),
                "natoName": as_string(raw.get("NatoName")),
                "_source": source or None,
                "required": sorted(strings_of(raw.get("Required"))) or None,
            },
        )
        stores[clsid] = record

        if adapter is not None and adapter not in racks:
            racks[adapter] = {"id": adapter, "ejectors": mounts}

    # A store without a name of its own takes the one its loaders name.
    for clsid, names in parent_names.items():
        weapons, ammo, basis = own.get(clsid, (Counter(), set(), ""))
        if basis in ("shape", "none") and clsid not in nested:
            if len(names) == 1:
                weapon = next(iter(names))
                own[clsid] = (Counter({weapon: own_loads[clsid]}), ammo, "loader")
                if weapons and set(weapons) != names:
                    stats.loader_overrides[clsid] = (sorted(weapons), weapon)
            else:
                stats.loader_conflicts[clsid] = sorted(names)

    resolved: dict[str, tuple[Counter[str], set[str]]] = {}

    def resolve(clsid: str, path: tuple[str, ...]) -> tuple[Counter[str], set[str]]:
        if clsid in path:
            fail(f"store payload_CLSID cycle: {' -> '.join((*path, clsid))}")
        if clsid not in resolved:
            if clsid not in own:
                fail(f"store {path[-1]}: payload_CLSID {clsid!r} is not a launcher")
            weapons, ammo, _ = own[clsid]
            weapons, ammo = Counter(weapons), set(ammo)
            for payload in nested.get(clsid, []):
                sub_weapons, sub_ammo = resolve(payload, (*path, clsid))
                weapons += sub_weapons
                if not own[clsid][1]:
                    ammo |= sub_ammo
            resolved[clsid] = (weapons, ammo)
        return resolved[clsid]

    for clsid, record in stores.items():
        weapons, ammo = resolve(clsid, ())
        record["delivers"] = [
            {"weapon": w, "count": n} for w, n in sorted(weapons.items()) if n
        ]
        if ammo:
            record["gunAmmo"] = sorted(ammo)
        stats.basis[own[clsid][2] if record["delivers"] else "none"] += 1
        if not record["delivers"] and not ammo:
            stats.no_delivers[record["kind"]] += 1
        elif clsid in count_zero:
            fail(f"store {clsid}: Count 0 but delivers {record['delivers']}")
    stats.unused_gunpods = sorted(set(gunpods) - used_gunpods)
    stats.unused_pods = sorted(set(pod_sensors) - used_pods)
    unknown = {
        f"{c} -> {r}"
        for c, s in stores.items()
        for r in s.get("required", [])
        if r not in stores
    }
    if unknown:
        fail(f"launcher Required names no store: {sorted(unknown)}")
    return stores, racks, stats


def categories_from_launchers(
    weapons: dict[str, dict[str, Any]],
    launchers: list[tuple[Path, Any]],
    constants: Constants,
) -> None:
    """Give a weapon without its own wsType the level 2 of the launchers that
    deliver it exactly (slot 4 names it) when they all agree, stamped
    ``_source.category: launcher``."""
    levels: dict[str, set[tuple[Any, Any]]] = {}
    for _, raw in launchers:
        name = _slot4(raw) if isinstance(raw, dict) else None
        if name in weapons and "category" not in weapons[name]:
            levels.setdefault(name, set()).add(ws_type_levels(raw, constants))
    for name, found in levels.items():
        record = weapons[name]
        if len({level2 for level2, _ in found}) != 1:
            continue
        level2, level3 = next(iter(found))
        if constants.set_pair(record, "category", "Entity.WsTypeWeaponLevel2", level2):
            record.setdefault("_source", {})["category"] = LAUNCHER
            if len(found) == 1 and set_subcategory(record, level3, constants):
                record["_source"]["subcategory"] = LAUNCHER


def name_seeker_types(weapons: dict[str, dict[str, Any]], overlays: Overlays) -> None:
    """``seekerTypeName`` from the overlays' ``weapons/seekerTypes`` table
    (stamped hand-authored). A ``seekerType`` in neither it nor
    ``weapons/seekerTypeUpstreamGaps`` fails, as does a key of either that no
    weapon uses."""
    names = {
        int(k): str(v) for k, v in overlays.table("weapons", "seekerTypes").items()
    }
    gaps = {
        int(k): v
        for k, v in overlays.table("weapons", "seekerTypeUpstreamGaps").items()
    }
    unknown: dict[int, list[str]] = {}
    used: set[str] = set()
    for wid, record in sorted(weapons.items()):
        code = record.get("seekerType")
        if code is None:
            continue
        used.add(str(code))
        if code in names:
            record["seekerTypeName"] = names[code]
            record.setdefault("_source", {})["seekerTypeName"] = HAND_AUTHORED
        elif code not in gaps:
            unknown.setdefault(code, []).append(wid)
    if unknown:
        fail(
            "Head_Type codes with no name in overlays weapons/seekerTypes and not "
            f"listed in weapons/seekerTypeUpstreamGaps: {unknown}"
        )
    unused_keys({str(k) for k in names}, used, "overlays weapons/seekerTypes")
    unused_keys({str(k) for k in gaps}, used, "overlays weapons/seekerTypeUpstreamGaps")


def categories_from_bombs_table(
    weapons: dict[str, dict[str, Any]], index: ProjectileIndex, constants: Constants
) -> list[str]:
    """Lowest-precedence category source: a weapon still without a category
    that is defined in DCS's own ``_G/bombs`` table is wsType_Bomb, stamped
    ``_source.category: table``. Sound only while every ``_G/bombs`` record that
    carries a wsType is wsType_Weapon/wsType_Bomb, so that is asserted on every
    extraction. Returns the ids still without a category."""
    weapon = constants.value("wsType", "wsType_Weapon")
    bomb = constants.value("wsType", "wsType_Bomb")
    if weapon is None or bomb is None:
        fail("dump constants lack wsType_Weapon/wsType_Bomb")
    wrong = []
    for proj in index.bombs:
        for key in ("ws_type", "wsTypeOfWeapon"):
            ws = array_entries(proj.raw.get(key))
            if ws and [as_number(v) for v in ws[:2]] != [weapon, bomb]:
                wrong.append(f"{proj.name} {key}={ws}")
    if wrong:
        fail(
            "_G/bombs holds non-bomb wsTypes, so bombs-table membership no longer "
            "implies wsType_Bomb: " + "; ".join(wrong)
        )
    members = {p.name for p in index.bombs}
    for name, record in weapons.items():
        if (
            name in members
            and "category" not in record
            and constants.set_pair(
                record, "category", "Entity.WsTypeWeaponLevel2", bomb
            )
        ):
            record.setdefault("_source", {})["category"] = TABLE
    return sorted(n for n, r in weapons.items() if "category" not in r)


def _store_aero(raw: dict[str, Any]) -> dict[str, Any]:
    aero: dict[str, Any] = {}
    assign_defined(
        aero,
        {
            "massKg": as_number(raw.get("Weight")),
            "emptyMassKg": as_number(raw.get("Weight_Empty")),
            "dragIndex": as_number(raw.get("Cx_pil")),
        },
    )
    return aero
