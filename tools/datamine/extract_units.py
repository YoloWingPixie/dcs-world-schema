"""Extract aircraft, ground vehicles, personnel, ships and structures from ``_G/db/Units``,
plus the attribute and gun-ammunition id sets."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import unit_properties as props
from .common import (
    HAND_AUTHORED,
    UNIT_SERIES_KEYS,
    assign_defined,
    fail,
    list_lua,
    walk_lua,
    warn,
)
from .dcs_constants import RADAR_TYPE, Constants
from .extract_stores import UNNAMED
from .lua_reader import (
    LuaReader,
    array_entries,
    as_dict,
    as_number,
    as_numeric,
    as_string,
    first_number,
    km,
    number_tuple,
    strings_of,
)
from .overlays import Overlays, unused_keys

_SHELLS_SUBPATH = ("weapons_table", "weapons", "shells")

# db/Units category dirs per series.
AIRCRAFT_DIRS = {"Planes": "fixedwing", "Helicopters": "rotary"}
SURFACE_DIRS = {
    "ground_vehicles": ["Cars"],
    "personnel": ["Personnel"],
    "ships": ["Ships"],
    "structures": [
        "Fortifications",
        "GroundObjects",
        "Cargos",
        "ADEquipments",
        "Heliports",
        "Warehouses",
        "GrassAirfields",
        "Effects",
        "LTAvehicles",
        "Animals",
    ],
}


@dataclass
class RawUnits:
    by_category: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    guns: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )  # unit type -> Entity.Gun
    attributes: set[str] = field(default_factory=set)
    gun_ammo: set[str] = field(default_factory=set)
    # unit type -> why its guns' supply.mixes do not resolve
    gun_problems: dict[str, list[str]] = field(default_factory=dict)

    def category(self, *names: str) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for name in names:
            out.update(self.by_category.get(name, {}))
        return out


def _sensor_names(raw: dict[str, Any]) -> list[str]:
    """Sensor ids under every role of the unit's ``Sensors`` block, sorted."""
    names: set[str] = set()
    for val in as_dict(raw.get("Sensors")).values():
        values = [val] if isinstance(val, str) else array_entries(val)
        names.update(s for s in values if isinstance(s, str) and s != "Redacted")
    return sorted(names)


def _collect_shell_names(ws: Any, out: set[str]) -> None:
    """Every ``shell_name`` under a unit's ``WS`` weapon-system table."""
    if isinstance(ws, list):
        for entry in ws:
            _collect_shell_names(entry, out)
        return
    if not isinstance(ws, dict):
        return
    shells = strings_of(ws.get("shell_name"))
    if shells:
        out.update(shells)
        return
    for key, child in ws.items():
        if key in ("LN", "PL") or key.isdigit():
            _collect_shell_names(child, out)


# Markup a mod put in a wsType slot (`</WSTYPE>`): no attribute name.
_MARKUP = re.compile(r"[<>]")


def _attributes(rec: dict[str, Any]) -> list[str]:
    """The attribute names of a unit's ``attribute`` list, sorted."""
    return sorted(a for a in strings_of(rec.get("attribute")) if not _MARKUP.search(a))


def load_units(reader: LuaReader, g_dir: Path) -> RawUnits:
    raw = RawUnits()
    dirs = [*AIRCRAFT_DIRS, *(d for ds in SURFACE_DIRS.values() for d in ds)]
    for dbcat in dirs:
        bucket: dict[str, dict[str, Any]] = {}
        for file, rec in reader.read_many(walk_lua(g_dir / "db" / "Units" / dbcat)):
            if not isinstance(rec, dict):
                continue
            uid = as_string(rec.get("type"))
            if not uid:
                fail(f"unit without type: {file}")
            bucket[uid] = rec
            raw.attributes.update(_attributes(rec))
            _collect_shell_names(rec.get("WS"), raw.gun_ammo)
            problems: list[str] = []
            gun = _gun(rec, problems)
            if problems:
                raw.gun_problems[uid] = problems
            if gun is not None:
                raw.guns[uid] = gun
                raw.gun_ammo.update(gun["ammo"])
        raw.by_category[dbcat] = bucket
    return raw


def _aero(raw: dict[str, Any]) -> dict[str, Any]:
    aero: dict[str, Any] = {}
    assign_defined(
        aero,
        {
            "emptyMassKg": first_number(
                as_numeric(raw.get("EmptyWeight")), raw.get("M_empty")
            ),
            "maxTakeoffKg": first_number(
                as_numeric(raw.get("MaxTakeOffWeight")), raw.get("M_max")
            ),
            "internalFuelKg": first_number(
                as_numeric(raw.get("MaxFuelWeight")), raw.get("M_fuel_max")
            ),
            "maxSpeedKmh": as_numeric(raw.get("MaxSpeed")),
        },
    )
    return aero


def _dimensions(raw: dict[str, Any]) -> dict[str, Any] | None:
    """``Entity.AircraftDimensions`` from the unit's ``wing_span``, ``rotor_diameter``,
    ``length`` and ``height`` (the fields the mission editor's stand fit reads)."""
    dims: dict[str, Any] = {}
    assign_defined(
        dims,
        {
            "wingSpanM": as_number(raw.get("wing_span")),
            "rotorDiameterM": as_number(raw.get("rotor_diameter")),
            "lengthM": as_number(raw.get("length")),
            "heightM": as_number(raw.get("height")),
        },
    )
    return dims or None


def _crew(raw: dict[str, Any]) -> int | None:
    size = as_number(raw.get("crew_size"))
    if size is not None:
        return int(size)
    members = array_entries(raw.get("crew_members"))
    return len(members) if members else None


def _supply(supply: dict[str, Any]) -> tuple[int | None, list[str | None]]:
    """A gun ``supply``'s round count and shell names in DCS order. A
    single-box gun has ``count`` and ``shells`` (shell tables); a dual-feed gun
    (Ka-50, Mi-28N) has ``count1``/``count2`` and ``shell1``/``shell2``, and may
    list the names as ``shells`` strings."""
    count = as_number(supply.get("count"))
    boxes = [as_number(supply.get(f"count{i}")) for i in (1, 2)]
    if count is None and any(b is not None for b in boxes):
        count = sum(b or 0 for b in boxes)
    entries = array_entries(supply.get("shells")) or [
        s for i in (1, 2) if (s := supply.get(f"shell{i}")) is not None
    ]
    names = [
        as_string(s) if isinstance(s, str) else as_string(as_dict(s).get("name"))
        for s in entries
    ]
    return (int(count) if count is not None else None), names


def _gun(raw: dict[str, Any], problems: list[str]) -> dict[str, Any] | None:
    """``Entity.Gun`` from ``Guns[]``: summed ``supply.count`` rounds, the first
    gun's model id, the loadable shell ids, the ``ammo_type`` labels and one
    ``Entity.GunMount`` per gun; None without guns. Why a gun's
    ``supply.mixes`` do not resolve is added to ``problems``."""
    uid = raw.get("type")
    labels = strings_of(raw.get("ammo_type"))
    if raw.get("ammo_type") is not None and len(labels) != len(
        array_entries(raw["ammo_type"])
    ):
        fail(f"{uid}: ammo_type {raw['ammo_type']!r} is not a list of strings")
    rounds = 0
    ammo: set[str] = set()
    model: str | None = None
    mounts: list[dict[str, Any]] = []
    for i, gun in enumerate(array_entries(raw.get("Guns")), 1):
        if not isinstance(gun, dict):
            continue
        supply = as_dict(gun.get("supply"))
        count, names = _supply(supply)
        shells = [n for n in names if n is not None]
        if count is None or not shells or len(shells) != len(names):
            fail(f"{uid}: Guns[{i}].supply lacks a round count or a shell name")
        rounds += count
        ammo.update(shells)
        gun_type = as_string(gun.get("short_name")) or as_string(
            gun.get("display_name")
        )
        model = model or gun_type
        mount: dict[str, Any] = {"ammo": shells, "rounds": count}
        assign_defined(
            mount,
            {
                "type": gun_type,
                "mixes": _mixes(supply, shells, labels, f"Guns[{i}]", problems),
            },
        )
        mounts.append(mount)
    if not mounts:
        return None
    gun_rec: dict[str, Any] = {"ammo": sorted(ammo), "rounds": rounds}
    default = raw.get("ammo_type_default")
    if default is not None and _int(default) is None:
        fail(f"{uid}: ammo_type_default {default!r} is not an integer")
    assign_defined(
        gun_rec,
        {
            "type": model,
            "mixes": [{"label": label} for label in labels] or None,
            "defaultMix": _int(default),
            "mounts": mounts,
        },
    )
    return gun_rec


def _mixes(
    supply: dict[str, Any],
    names: list[str],
    labels: list[str],
    where: str,
    problems: list[str],
) -> list[dict[str, Any]] | None:
    """A gun's ``supply.mixes`` as ``Entity.GunBelt`` (shell indices as
    ``supply.shells`` names, repeats kept), DCS order. None, and a problem,
    when an index names no shell; a problem too when there are ``ammo_type``
    labels but not one mix per label (the editor's choice i is mix i)."""
    entries = array_entries(supply.get("mixes"))
    if labels and len(entries) != len(labels):
        problems.append(
            f"{where}: {len(entries)} supply.mixes for {len(labels)} ammo_type labels"
        )
    belts: list[dict[str, Any]] = []
    for mix in entries:
        idx = [_int(i) for i in array_entries(mix)]
        shells = [
            names[i - 1] if i is not None and 1 <= i <= len(names) else None
            for i in idx
        ]
        if not shells or None in shells:
            problems.append(f"{where}: supply.mixes entry {mix} names no shell")
            return None
        belts.append({"ammo": [s for s in shells if s is not None]})
    return belts or None


MIX_GAPS_TABLE = "gunMixUpstreamGaps"


def check_gun_mixes(raw: RawUnits, gaps: Mapping[str, str]) -> None:
    """Fail on an aircraft whose gun mixes do not resolve unless ``gaps`` (the
    ``aircraft`` ``gunMixUpstreamGaps`` overlay table) explains it, and on a
    ``gaps`` key that now resolves. A gun whose mixes name no shell keeps none."""
    aircraft = raw.category(*AIRCRAFT_DIRS)
    found = {u: p for u, p in raw.gun_problems.items() if u in aircraft}
    where = f"overlays aircraft/{MIX_GAPS_TABLE}"
    unknown = sorted(set(found) - set(gaps))
    if unknown:
        fail(
            "aircraft gun mixes DCS does not resolve: "
            + "; ".join(f"{u} ({'; '.join(found[u])})" for u in unknown)
            + f"; fix the extraction or explain them in {where}"
        )
    unused_keys(gaps, set(found), where)


def _rules(value: Any, kind: str, where: str) -> list[dict[str, Any]]:
    """A launcher's ``forbidden``/``required`` rules ``{station, loadout?}``,
    normalised: ``forbidden`` as ``{station, clsids}`` or, without a
    ``loadout``, ``{station, anyStore: true}``; ``required`` as ``{station,
    clsids, allowEmpty}``, DCS's ``""`` (an empty station) lifted out of
    ``clsids`` into ``allowEmpty``. An empty table is no rules."""
    out: list[dict[str, Any]] = []
    for rule in array_entries(value):
        station = _int(as_dict(rule).get("station"))
        loadout = as_dict(rule).get("loadout")
        clsids = [c for c in array_entries(loadout) if isinstance(c, str)]
        if (
            station is None
            or set(as_dict(rule)) - {"station", "loadout"}
            or (loadout is not None and (not clsids or len(clsids) != len(loadout)))
            or (kind == "required" and loadout is None)
            or (kind == "forbidden" and "" in clsids)
        ):
            fail(f"{where}: {kind} rule {rule!r} is not {{station, loadout}}")
        entry: dict[str, Any] = {"station": station}
        if kind == "required":
            entry["clsids"] = [c for c in clsids if c]
            entry["allowEmpty"] = "" in clsids
        elif loadout is None:
            entry["anyStore"] = True
        else:
            entry["clsids"] = clsids
        out.append(entry)
    if value and not out:
        fail(f"{where}: {kind} {value!r} is not a list of rules")
    return out


def _accepts(
    pylon: dict[str, Any], where: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """One entry per launcher CLSID in DCS order; the rules of a CLSID listed
    twice are merged (the mission editor applies every matching entry's).
    Split into those offered and those every entry of which is ``obsolete =
    true``, which the mission editor hides (me_loadoututils.lua
    ``getPylonLaunchers``)."""
    by_clsid: dict[str, dict[str, Any]] = {}
    current: set[str] = set()
    for launcher in array_entries(pylon.get("Launchers")):
        if not isinstance(launcher, dict) or not (
            clsid := as_string(launcher.get("CLSID"))
        ):
            continue
        obsolete = launcher.get("obsolete", False)
        if not isinstance(obsolete, bool):
            fail(f"{where} {clsid}: obsolete {obsolete!r} is not a boolean")
        if not obsolete:
            current.add(clsid)
        entry = by_clsid.setdefault(clsid, {"clsid": clsid})
        for kind in ("forbidden", "required"):
            for rule in _rules(launcher.get(kind), kind, f"{where} {clsid}"):
                if rule not in entry.get(kind, []):
                    entry.setdefault(kind, []).append(rule)
    entries = [by_clsid[c] for c in sorted(by_clsid)]
    return (
        [e for e in entries if e["clsid"] in current],
        [e for e in entries if e["clsid"] not in current],
    )


def _stations(
    raw: dict[str, Any], fuel_clsids: set[str], uid: str
) -> list[dict[str, Any]]:
    """Every ``Pylons`` entry, as the mission editor lists them."""
    stations: list[dict[str, Any]] = []
    for i, pylon in enumerate(array_entries(raw.get("Pylons"))):
        if not isinstance(pylon, dict):
            continue
        number = as_number(pylon.get("Number"))
        station = int(number) if number is not None else i + 1
        accepts, obsolete = _accepts(pylon, f"{uid} station {station}")
        record: dict[str, Any] = {
            "station": station,
            "wet": any(a["clsid"] in fuel_clsids for a in accepts),
            "accepts": accepts,
        }
        assign_defined(
            record,
            {
                "type": _int(pylon.get("Type")),
                "displayName": as_string(pylon.get("DisplayName")),
                "order": as_number(pylon.get("Order")),
                "obsoleteAccepts": obsolete or None,
            },
        )
        x, y, z = (as_number(pylon.get(k)) for k in ("X", "Y", "Z"))
        if x is not None and y is not None and z is not None:
            record["position"] = {"lateral": z, "longitudinal": x, "vertical": y}
        stations.append(record)
    stations.sort(key=lambda s: s["station"])
    return stations


def build_aircraft(
    raw: RawUnits,
    flyable: set[str],
    radios_by_aircraft: dict[str, list[str]],
    datalinks: dict[str, dict[str, Any]],
    fuel_clsids: set[str],
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for dbcat, kind in AIRCRAFT_DIRS.items():
        for atype, rec in raw.by_category.get(dbcat, {}).items():
            record: dict[str, Any] = {
                "id": atype,
                "displayName": as_string(rec.get("DisplayName"))
                or as_string(rec.get("Name"))
                or atype,
                "kind": kind,
                "flyable": atype in flyable,
                "attributes": _attributes(rec),
                "aero": _aero(rec),
                "sensors": _sensor_names(rec),
                "radios": radios_by_aircraft.get(atype, []),
                "stations": _stations(rec, fuel_clsids, atype),
            }
            assign_defined(
                record,
                {
                    "module": as_string(rec.get("_origin")),
                    "crew": _crew(rec),
                    "dimensions": _dimensions(rec),
                    "datalink": atype if atype in datalinks else None,
                    "gun": raw.guns.get(atype),
                    "model": props.model(rec),
                    "life": props.life(rec),
                    "detection": props.detection(rec, atype),
                    "cargo": props.cargo(rec, atype),
                    "performance": props.performance(rec),
                    "operations": props.operations(rec, atype),
                    "failures": props.failures(rec, atype),
                    "missionOptions": props.mission_options(
                        rec, "AddPropAircraft", atype
                    ),
                    **props.tasks(rec, atype),
                    "refuelling": props.refuelling(rec, atype),
                    "countermeasures": props.countermeasures(rec, atype),
                    "countryOfOrigin": props.country_of_origin(rec, atype),
                },
            )
            out[atype] = record
    return out


# Series whose units carry DCS ``WS`` weapon systems.
WEAPON_SYSTEM_SERIES = ("ground_vehicles", "ships")


def _ammo_weapon(
    ammo: Any, weapon_ids: set[str], by_resource: Mapping[str, str]
) -> str | None:
    """The ``Entity.Weapon`` id a PL ``type_ammunition`` names, if it resolves:
    a resource name (``weapons.missiles.X``) or the projectile name the dump
    hook writes into slot 4 of the wsType tuple."""
    if isinstance(ammo, str):
        name = by_resource.get(ammo)
    elif isinstance(ammo, list) and len(ammo) == 4:
        name = ammo[3]
    elif isinstance(ammo, dict):  # dumps before the proxy fix: {[4] = ...}
        name = ammo.get("4")
    else:
        return None
    if not isinstance(name, str) or name in UNNAMED:
        return None
    return name if name in weapon_ids else None


def _int(value: Any) -> int | None:
    n = as_number(value)
    return int(n) if n is not None and n == int(n) else None


def _requirement(value: Any) -> dict[str, Any] | None:
    """One ``depends_on_unit`` requirement: ``{"self", ws}``, ``{"none"}``,
    ``{unit}`` or ``{unit, ws}``; None for any other shape."""
    items = array_entries(value)
    if items == ["none"]:
        return {"none": True}
    if len(items) == 2 and items[0] == "self" and (ws := _int(items[1])) is not None:
        return {"selfWs": ws}
    if not items or not isinstance(items[0], str) or items[0] in ("self", "none"):
        return None
    if len(items) == 1:
        return {"unit": items[0]}
    if len(items) == 2 and (ws := _int(items[1])) is not None:
        return {"unit": items[0], "ws": ws}
    return None


def _depends_on(value: Any) -> list[list[dict[str, Any]]] | None:
    """``depends_on_unit`` as alternatives of requirements; None when it is
    not a list of lists of requirements."""
    if not isinstance(value, list):
        return None
    out: list[list[dict[str, Any]]] = []
    for alt in value:
        if not isinstance(alt, list):
            return None
        reqs = [r for r in map(_requirement, alt) if r is not None]
        if len(reqs) != len(alt):
            return None
        out.append(reqs)
    return out


def _payload(
    pl: dict[str, Any], weapon_ids: set[str], by_resource: Mapping[str, str]
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    assign_defined(
        out,
        {
            "weapon": _ammo_weapon(pl.get("type_ammunition"), weapon_ids, by_resource),
            "gunAmmo": sorted(set(strings_of(pl.get("shell_name")))) or None,
            "ammoName": as_string(pl.get("name_ammunition")),
            "ammoDisplayName": as_string(pl.get("shell_display_name")),
            "ammoCapacity": as_number(pl.get("ammo_capacity")),
            "portionAmmoCapacity": as_number(pl.get("portionAmmoCapacity")),
            "reloadTimeS": as_number(pl.get("reload_time")),
            "portionReloadTimeS": as_number(pl.get("portion_reload_time")),
            "shotDelayS": as_number(pl.get("shot_delay")),
        },
    )
    return out


def weapon_systems(
    rec: dict[str, Any],
    weapon_ids: set[str],
    by_resource: Mapping[str, str],
    problems: list[str] | None = None,
) -> list[dict[str, Any]]:
    """One ``Entity.WeaponSystem`` per launcher ``WS[i].LN[j]``, in WS then LN
    order, with its ``PL`` payloads. Range comes from the launcher's
    ``distanceMin``/``distanceMax`` (else the weapon system's), name and
    display name from the launcher (else the weapon system). A
    ``depends_on_unit`` or ``frequencyRange`` in a shape this cannot read is
    left out and reported in ``problems`` (one line per unit)."""
    uid = as_string(rec.get("type")) or "?"
    bad: list[str] = []
    out: list[dict[str, Any]] = []
    # A WS table mixes its weapon systems (WS[1..n]) with named fields.
    for i, ws in enumerate(array_entries(rec.get("WS"), mixed=True), 1):
        if not isinstance(ws, dict):
            continue
        sectors = [array_entries(a) for a in array_entries(ws.get("angles"))]
        slew: dict[str, Any] = {}
        assign_defined(
            slew,
            {"yaw": as_number(ws.get("omegaY")), "pitch": as_number(ws.get("omegaZ"))},
        )
        for j, ln in enumerate(array_entries(ws.get("LN")), 1):
            if not isinstance(ln, dict):
                continue
            where = f"WS[{i}].LN[{j}]"
            payloads = [
                _payload(pl, weapon_ids, by_resource)
                for pl in array_entries(ln.get("PL"))
                if isinstance(pl, dict)
            ]
            channels = [
                ln[k]
                for k in (
                    "max_number_of_missiles_channels",
                    "max_number_of_missile_channels",
                )
                if ln.get(k) is not None
            ]
            if len(channels) == 2 and channels[0] != channels[1]:
                fail(f"{uid}: {where} missile channel counts disagree: {channels}")
            requires = None
            if ln.get("depends_on_unit") is not None:
                requires = _depends_on(ln["depends_on_unit"])
                if requires is None:
                    bad.append(f"{where}.depends_on_unit {ln['depends_on_unit']!r}")
            frequency = None
            if ln.get("frequencyRange") is not None:
                frequency = number_tuple(ln["frequencyRange"], 2)
                if frequency is None:
                    bad.append(f"{where}.frequencyRange {ln['frequencyRange']!r}")
            awacs = ln.get("external_tracking_awacs")
            barrels = ln.get("BR")
            entry: dict[str, Any] = {"ws": i, "ln": j}
            assign_defined(
                entry,
                {
                    "launcherType": _int(ln.get("type")),
                    "name": as_string(ln.get("name")) or as_string(ws.get("name")),
                    "displayName": as_string(ln.get("display_name"))
                    or as_string(ws.get("display_name")),
                    "weapons": sorted({p["weapon"] for p in payloads if "weapon" in p})
                    or None,
                    "gunAmmo": sorted(
                        {a for p in payloads for a in p.get("gunAmmo", [])}
                    )
                    or None,
                    "payloads": payloads or None,
                    "rMinKm": km(
                        first_number(ln.get("distanceMin"), ws.get("distanceMin"))
                    ),
                    "rMaxKm": km(
                        first_number(ln.get("distanceMax"), ws.get("distanceMax"))
                    ),
                    "hMinM": as_number(ln.get("min_trg_alt")),
                    "hMaxM": as_number(ln.get("max_trg_alt")),
                    "missileChannels": as_number(channels[0]) if channels else None,
                    "dependsOn": requires,
                    "reactionTimeS": as_number(ln.get("reactionTime")),
                    "launchDelayS": as_number(ln.get("launch_delay")),
                    "ecmK": as_number(ln.get("ECM_K")),
                    "reflectionLimit": as_number(ln.get("reflection_limit")),
                    "beamWidthRad": as_number(ln.get("beamWidth")),
                    "frequencyRangeHz": frequency,
                    "externalTrackingAwacs": awacs if isinstance(awacs, bool) else None,
                    "maxShootingSpeed": as_number(ln.get("maxShootingSpeed")),
                    "barrels": len(array_entries(barrels))
                    if barrels is not None
                    else None,
                    "sectorsRad": sectors or None,
                    "slewRateRadS": slew or None,
                },
            )
            out.append(entry)
    if bad and problems is not None:
        problems.append(
            f"{uid}: unreadable launcher field(s) left out: {'; '.join(bad)}"
        )
    return out


def fire_control(
    rec: dict[str, Any], constants: Constants | None
) -> dict[str, Any] | None:
    """``Entity.FireControl`` from the named fields of the unit's ``WS``."""
    ws = as_dict(rec.get("WS"))
    out: dict[str, Any] = {}
    radar = _int(ws.get("radar_type"))
    for key, dcs in (("fireOnMove", "fire_on_march"), ("isDetector", "isDetector")):
        if isinstance(ws.get(dcs), bool):
            out[key] = ws[dcs]
    assign_defined(
        out,
        {
            "maxTargetDetectionRangeM": as_number(ws.get("maxTargetDetectionRange")),
            "radarType": radar,
            "radarTypeName": constants.name(RADAR_TYPE, radar)
            if constants is not None and radar is not None
            else None,
        },
    )
    return out or None


def build_surface(
    raw: RawUnits,
    weapon_ids: set[str] | None = None,
    by_resource: Mapping[str, str] | None = None,
    constants: Constants | None = None,
) -> dict[str, dict[str, dict[str, Any]]]:
    """Surface-unit series. ``weapon_ids`` (the ``Entity.Weapon`` ids) and
    ``by_resource`` (projectile resource name -> weapon id) resolve the
    ``weaponSystems`` weapons; a launcher's weapon outside ``weapon_ids`` is
    left out. ``constants`` names ``fireControl.radarType``."""
    weapon_ids = weapon_ids or set()
    by_resource = by_resource or {}
    problems: list[str] = []
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for series, dirs in SURFACE_DIRS.items():
        records: dict[str, dict[str, Any]] = {}
        for uid, rec in raw.category(*dirs).items():
            record: dict[str, Any] = {
                "id": uid,
                "displayName": as_string(rec.get("DisplayName"))
                or as_string(rec.get("Name"))
                or uid,
                "attributes": _attributes(rec),
            }
            sensors = _sensor_names(rec)
            if sensors:
                record["sensors"] = sensors
            blocks: dict[str, Any] = {
                "model": props.model(rec, uid),
                "life": props.life(rec),
            }
            if series in WEAPON_SYSTEM_SERIES:
                blocks["tags"] = strings_of(rec.get("tags")) or None
            if series == "ground_vehicles":
                blocks |= {
                    "dimensions": props.vehicle_dimensions(rec),
                    "mobility": props.vehicle_mobility(rec, uid),
                    "crew": props.surface_crew(rec),
                    "missionOptions": props.mission_options(rec, "AddPropVehicle", uid),
                }
            if series == "ships":
                blocks |= {
                    "dimensions": props.ship_dimensions(rec),
                    "mobility": props.ship_mobility(rec, uid),
                }
            if series in WEAPON_SYSTEM_SERIES:
                blocks |= {
                    "detection": props.detection(rec, uid),
                    "armour": props.armour(rec, uid),
                    "cargo": props.cargo(rec, uid),
                    "fireControl": fire_control(rec, constants),
                    "weaponSystems": weapon_systems(
                        rec, weapon_ids, by_resource, problems
                    )
                    or None,
                }
            if series != "personnel":
                blocks["facilities"] = props.facilities(rec, uid)
            assign_defined(record, blocks)
            records[uid] = record
        result[series] = records
    for line in problems:
        warn(line)
    return result


_QUOTED = re.compile(r'"([^"]+)"')
AIR_DEFENCE = "Air Defence"


def name_reporting(
    surface: Mapping[str, dict[str, dict[str, Any]]], overlays: Overlays
) -> None:
    """Set ``natoReportingName`` on ground vehicles and ships: the one
    double-quoted part of an ``Air Defence`` unit's ``displayName`` (``SA-11
    Buk "Gadfly" LN`` -> ``Gadfly``; other units' quotes are nicknames, e.g.
    Truck GMC "Jimmy"), unless its ``units/natoReportingName`` overlay entry
    (``hand-authored``) fills it or overrides a system name DCS quotes with the
    unit's own (``Grumble`` -> ``Flap Lid A``). An overlay entry for a unit
    type no such record defines, or equal to DCS's name, stops the
    extraction."""
    records = {u: r for s in WEAPON_SYSTEM_SERIES for u, r in surface[s].items()}
    named: dict[str, str] = {}
    for uid, rec in records.items():
        quoted = _QUOTED.findall(rec["displayName"])
        if AIR_DEFENCE not in rec["attributes"] or not quoted:
            continue
        if len(set(quoted)) > 1:
            warn(f"{uid}: displayName quotes {quoted}; natoReportingName left out")
            continue
        named[uid] = quoted[0].strip()
    hand = overlays.table("units", "natoReportingName")
    stale = [
        *(
            f"units/natoReportingName {u!r}: no ground vehicle or ship"
            for u in sorted(hand.keys() - records.keys())
        ),
        *(
            f"units/natoReportingName {u!r}: DCS already names it {named[u]!r}"
            for u in sorted(hand.keys() & named.keys())
            if hand[u] == named[u]
        ),
    ]
    if stale:
        fail("stale NATO reporting name entries: " + "; ".join(stale))
    for uid, name in named.items():
        records[uid]["natoReportingName"] = name
    for uid, name in hand.items():
        records[uid]["natoReportingName"] = name
        records[uid].setdefault("_source", {})["natoReportingName"] = HAND_AUTHORED


def weapon_system_summary(surface: dict[str, dict[str, dict[str, Any]]]) -> str:
    """One report line counting the extracted ``weaponSystems``."""
    systems = [
        rec.get("weaponSystems", [])
        for key in WEAPON_SYSTEM_SERIES
        for rec in surface.get(key, {}).values()
    ]
    launchers = [ws for unit in systems for ws in unit]
    return (
        f"Surface weapon systems: {len(launchers)} launcher(s) on "
        f"{sum(1 for unit in systems if unit)} unit(s), "
        f"{sum(1 for ws in launchers if 'payloads' in ws)} with a payload, "
        f"{sum(1 for ws in launchers if 'weapons' in ws)} naming a weapon, "
        f"{sum(1 for ws in launchers if 'rMaxKm' in ws)} with a range"
    )


def build_attributes(raw: RawUnits) -> dict[str, dict[str, Any]]:
    # The dump has no attribute-description table.
    return {a: {"id": a} for a in sorted(raw.attributes)}


def index_attribute_units(series: dict[str, dict[str, Any]]) -> None:
    """Set each attribute's ``units``: the ids of the unit records carrying it,
    per unit series. An attribute no unit record defines is left to
    ``check_refs``."""
    attributes = series["attributes"]
    for name, key in UNIT_SERIES_KEYS.items():
        for unit in series[name].values():
            for attr in unit.get("attributes") or []:
                if attr in attributes:
                    units = attributes[attr].setdefault("units", {})
                    units.setdefault(key, []).append(unit["id"])
    for record in attributes.values():
        for ids in record.get("units", {}).values():
            ids.sort()


def build_gun_ammo(
    raw: RawUnits, reader: LuaReader, g_dir: Path
) -> dict[str, dict[str, Any]]:
    """One ``Entity.GunAmmo`` per collected shell id, with massKg (``round_mass``,
    else ``mass``), type (``type_name``) and displayName (``display_name``) from
    ``weapons_table/weapons/shells/<name>.lua`` where that file has them."""
    names = sorted(raw.gun_ammo)
    files = [
        f for f in list_lua(g_dir.joinpath(*_SHELLS_SUBPATH)) if f.stem in raw.gun_ammo
    ]
    shells = {
        f.stem: rec for f, rec in reader.read_many(files) if isinstance(rec, dict)
    }
    out: dict[str, dict[str, Any]] = {}
    for name in names:
        record: dict[str, Any] = {"id": name}
        shell = shells.get(name, {})
        assign_defined(
            record,
            {
                "massKg": first_number(shell.get("round_mass"), shell.get("mass")),
                "type": as_string(shell.get("type_name")),
                "displayName": as_string(shell.get("display_name")),
            },
        )
        out[name] = record
    return out
