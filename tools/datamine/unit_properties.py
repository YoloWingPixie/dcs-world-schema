"""Per-unit property blocks read from a ``db/Units`` record: model, life,
detection, mobility, armour, crew, cargo, ship facilities and aircraft
performance. Each builder returns None when DCS defines none of its fields;
a field DCS omits is absent. Units stay DCS's own where DCS or its data files
state them; fields of unstated unit keep their raw values."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .common import assign_defined, fail, warn
from .lua_reader import (
    array_entries,
    as_dict,
    as_number,
    as_string,
    first_string,
    number_tuple,
    strings_of,
)


def _bool(raw: dict[str, Any], key: str, uid: str) -> bool | None:
    value = raw.get(key)
    if value is None or isinstance(value, bool):
        return value
    fail(f"{uid}: {key} {value!r} is not a boolean")


def _merged(raw: dict[str, Any], keys: tuple[str, ...], uid: str) -> Any:
    """The value of whichever of ``keys`` (DCS spellings of one field) is set;
    two set to different values is an error."""
    values = {k: raw[k] for k in keys if raw.get(k) is not None}
    first = next(iter(values.values()), None)
    if any(v != first for v in values.values()):
        fail(f"{uid}: {values} disagree")
    return first


def _block(fields: dict[str, Any]) -> dict[str, Any] | None:
    """The non-``None`` ``fields``; None when there are none."""
    out: dict[str, Any] = {}
    assign_defined(out, fields)
    return out or None


def _numbers(table: dict[str, Any], keys: dict[str, str]) -> dict[str, Any]:
    """``{field: as_number(table[dcs key])}`` for ``keys`` (field -> DCS key)."""
    return {name: as_number(table.get(dcs)) for name, dcs in keys.items()}


def _shape_table(raw: dict[str, Any]) -> dict[str, Any]:
    entries = array_entries(raw.get("shape_table_data"))
    return as_dict(entries[0]) if entries else {}


def _arg_values(value: Any, uid: str) -> list[dict[str, Any]] | None:
    """``[{arg, value}]`` of an ``encyclopediaAnimation.args`` table (a Lua
    array's entries are arguments 1..n), sorted by argument."""
    if value is None:
        return None
    table = (
        {str(i): v for i, v in enumerate(value, 1)}
        if isinstance(value, list)
        else as_dict(value)
    )
    out = []
    for key, v in table.items():
        if not key.isdigit() or as_number(v) is None:
            fail(
                f"{uid}: encyclopediaAnimation.args[{key!r}] = {v!r} is not arg -> number"
            )
        out.append({"arg": int(key), "value": v})
    return sorted(out, key=lambda e: e["arg"]) or None


def _encyclopedia(raw: dict[str, Any], uid: str) -> dict[str, Any] | None:
    """``Entity.EncyclopediaPose`` from ``encyclopediaAnimation``."""
    block = as_dict(raw.get("encyclopediaAnimation"))
    if extra := sorted(set(block) - {"args", "children"}):
        fail(f"{uid}: encyclopediaAnimation has unknown fields {extra}")
    children = []
    for child in array_entries(block.get("children")):
        child = as_dict(child)
        if extra := sorted(set(child) - {"args", "connector", "model", "attach_point"}):
            fail(f"{uid}: encyclopediaAnimation child has unknown fields {extra}")
        entry: dict[str, Any] = {}
        assign_defined(
            entry,
            {
                "connector": as_string(child.get("connector")),
                "model": as_string(child.get("model")),
                "attachPoint": as_string(child.get("attach_point")),
                "args": _arg_values(child.get("args"), uid),
            },
        )
        children.append(entry)
    return _block(
        {"args": _arg_values(block.get("args"), uid), "children": children or None}
    )


def _damage_args(value: Any, uid: str) -> list[dict[str, Any]] | None:
    """``[{cell, args}]`` of the ``Damage`` cells that name model arguments,
    sorted by cell."""
    out = []
    for cell, entry in as_dict(value).items():
        args = array_entries(as_dict(entry).get("args"))
        if not args:
            continue
        if not cell.isdigit() or any(as_number(a) is None for a in args):
            fail(f"{uid}: Damage[{cell!r}].args {args!r} is not cell -> numbers")
        out.append({"cell": int(cell), "args": args})
    return sorted(out, key=lambda e: e["cell"]) or None


def model(raw: dict[str, Any], uid: str = "") -> dict[str, Any] | None:
    """``Entity.UnitModel``."""
    table = _shape_table(raw)
    visual = as_dict(raw.get("visual"))
    return _block(
        {
            "lightsData": raw.get("lights_data"),
            "encyclopediaAnimation": _encyclopedia(raw, uid),
            "animationArguments": raw.get("animation_arguments") or None,
            "damageArgs": _damage_args(raw.get("Damage"), uid),
            "canopyGeometry": raw.get("CanopyGeometry"),
            "shape": first_string(
                raw.get("Shape"), visual.get("shape"), raw.get("ShapeName")
            ),
            "shapeDestroyed": first_string(
                visual.get("shape_dstr"),
                raw.get("ShapeNameDestr"),
                raw.get("ShapeNameDstr"),
                table.get("desrt"),
            ),
            "file": first_string(table.get("file")),
            "className": first_string(table.get("classname")),
            "positioning": first_string(table.get("positioning")),
            "mapClassKey": first_string(raw.get("mapclasskey")),
            "liveryEntry": first_string(raw.get("livery_entry")),
        }
    )


# (``Entity.UnitLifeSource`` value, getter): every DCS field that carries a
# life value; they are on different scales.
_LIFE_SOURCES: tuple[tuple[str, Callable[[dict[str, Any]], Any]], ...] = (
    ("Life", lambda r: r.get("Life")),
    ("life", lambda r: r.get("life")),
    ("chassis.life", lambda r: as_dict(r.get("chassis")).get("life")),
    ("shape_table_data[1].life", lambda r: _shape_table(r).get("life")),
)


def life(raw: dict[str, Any]) -> list[dict[str, Any]] | None:
    """``Entity.UnitLife`` per DCS field that sets one, in ``_LIFE_SOURCES``
    order."""
    out = [
        {"source": source, "value": n}
        for source, get in _LIFE_SOURCES
        if (n := as_number(get(raw))) is not None
    ]
    return out or None


def _sensor_envelope(raw: dict[str, Any], uid: str) -> dict[str, Any] | None:
    sensor = as_dict(raw.get("sensor"))
    return _block(
        {
            **_numbers(
                sensor,
                {
                    "minRangeM": "min_range_finding_target",
                    "maxRangeM": "max_range_finding_target",
                    "minAltM": "min_alt_finding_target",
                    "maxAltM": "max_alt_finding_target",
                    "heightM": "height",
                },
            ),
            "position": number_tuple(sensor.get("pos"), 3),
            "laser": _bool(sensor, "laser", uid),
        }
    )


def detection(raw: dict[str, Any], uid: str) -> dict[str, Any] | None:
    """``Entity.UnitDetection``."""
    return _block(
        {
            **_numbers(
                raw,
                {
                    "detectionRangeM": "DetectionRange",
                    "detectionRangeMax": "detection_range_max",
                    "threatRangeM": "ThreatRange",
                    "threatRangeMinM": "ThreatRangeMin",
                    "airWeaponDistM": "airWeaponDist",
                    "airFindDistM": "airFindDist",
                    "irEmissionCoeff": "IR_emission_coeff",
                    "rcsM2": "RCS",
                },
            ),
            "sensor": _sensor_envelope(raw, uid),
        }
    )


def vehicle_mobility(raw: dict[str, Any], uid: str) -> dict[str, Any] | None:
    """``Entity.VehicleMobility`` from ``MaxSpeed``, ``mobile`` and ``chassis``."""
    chassis = as_dict(raw.get("chassis"))
    return _block(
        {
            "mobile": _bool(raw, "mobile", uid),
            "maxSpeedKmh": as_number(raw.get("MaxSpeed")),
            **_numbers(
                chassis,
                {
                    "maxRoadSpeedMs": "max_road_velocity",
                    "maxSlopeRad": "max_slope",
                    "maxVertObstacleM": "max_vert_obstacle",
                    "minTurnRadiusM": "min_turn_radius",
                    "fordingDepthM": "fordingDepth",
                    "enginePower": "engine_power",
                },
            ),
            "canSwim": _bool(chassis, "canSwim", uid),
        }
    )


def ship_mobility(raw: dict[str, Any], uid: str) -> dict[str, Any] | None:
    """``Entity.ShipMobility``."""
    return _block(
        {
            **_numbers(
                raw,
                {
                    "maxSpeedKmh": "MaxSpeed",
                    "maxSpeedMs": "max_velocity",
                    "minTurnRadiusM": "R_min",
                    "economyDistance": "economy_distance",
                    "economyVelocity": "economy_velocity",
                    "raceDistance": "race_distance",
                    "raceVelocity": "race_velocity",
                },
            ),
            "draftM": as_number(_merged(raw, ("draft", "Draft"), uid)),
        }
    )


def vehicle_dimensions(raw: dict[str, Any]) -> dict[str, Any] | None:
    """``Entity.SurfaceDimensions`` from ``chassis``."""
    return _block(
        _numbers(
            as_dict(raw.get("chassis")),
            {"lengthM": "length", "widthM": "width", "massKg": "mass"},
        )
    )


def ship_dimensions(raw: dict[str, Any]) -> dict[str, Any] | None:
    """``Entity.SurfaceDimensions`` from ``Length``/``Width``/``Height``/``mass``."""
    return _block(
        _numbers(
            raw,
            {
                "lengthM": "Length",
                "widthM": "Width",
                "heightM": "Height",
                "massKg": "mass",
            },
        )
    )


_ARMOUR_SCHEME = {
    "hullAzimuth": "hull_azimuth",
    "hullElevation": "hull_elevation",
    "turretAzimuth": "turret_azimuth",
    "turretElevation": "turret_elevation",
}


def armour(raw: dict[str, Any], uid: str) -> dict[str, Any] | None:
    """``Entity.UnitArmour``."""
    scheme_raw = as_dict(raw.get("armour_scheme"))
    unknown = set(scheme_raw) - set(_ARMOUR_SCHEME.values())
    if unknown:
        fail(f"{uid}: armour_scheme has unknown sectors {sorted(unknown)}")
    scheme: dict[str, Any] = {}
    for key, dcs in _ARMOUR_SCHEME.items():
        rows = array_entries(scheme_raw.get(dcs))
        if rows:
            scheme[key] = [array_entries(row) for row in rows]
    return _block(
        {
            "thickness": as_number(as_dict(raw.get("chassis")).get("armour_thickness")),
            "scheme": scheme or None,
        }
    )


def surface_crew(raw: dict[str, Any]) -> dict[str, Any] | None:
    """``Entity.SurfaceCrew`` from ``Crew`` and ``crew_members``."""
    count = as_number(raw.get("Crew"))
    return _block(
        {
            "count": int(count) if count is not None else None,
            "members": strings_of(raw.get("crew_members")) or None,
        }
    )


def cargo(raw: dict[str, Any], uid: str) -> dict[str, Any] | None:
    """``Entity.UnitCargo``."""
    internal = as_dict(raw.get("InternalCargo"))
    transportable = raw.get("Transportable")
    carried: dict[str, Any] | None = None
    if transportable is not None:
        if not isinstance(transportable, dict):
            fail(f"{uid}: Transportable {transportable!r} is not a table")
        carried = {}
        assign_defined(
            carried,
            {
                "valid": _bool(transportable, "valide", uid),
                "size": as_number(transportable.get("size")),
            },
        )
    return _block(
        {
            **_numbers(
                internal,
                {
                    "nominalCapacity": "nominalCapacity",
                    "maximalCapacity": "maximalCapacity",
                },
            ),
            "transportable": carried,
            "canTow": strings_of(raw.get("canTow")) or None,
            "canBeTowedBy": strings_of(raw.get("canBeTowedBy")) or None,
        }
    )


def _ols(raw: dict[str, Any], uid: str) -> dict[str, Any] | None:
    ols = raw.get("OLS")
    if ols is None:
        return None
    if not isinstance(ols, dict) or as_number(ols.get("Type")) is None:
        fail(f"{uid}: OLS {ols!r} has no numeric Type")
    return _block(
        {
            "type": int(ols["Type"]),
            **_numbers(
                ols,
                {
                    "meatBallArg": "MeatBallArg",
                    "cutLightsArg": "CutLightsArg",
                    "datumAndWaveOffLightsArg": "DatumAndWaveOffLightsArg",
                    "glideslopeBasicAngleDeg": "GlideslopeBasicAngle",
                    "verticalCoverageAngleDeg": "VerticalCoverageAngle",
                },
            ),
        }
    )


_GLIDE_PATH = ("low", "slightlyLow", "onLower", "onUpper", "slightlyHigh", "high")


def _runways(raw: dict[str, Any], uid: str) -> list[dict[str, Any]] | None:
    """``RunWays[i]``: ``{start xyz, azimuth, length, width, alsArgument,
    <six glide-path values>}`` as the DCS carrier files' own comment lays it
    out; the first is the landing strip."""
    value = raw.get("RunWays")
    if value is None:
        return None
    entries = array_entries(value, mixed=True)
    out: list[dict[str, Any]] = []
    for i, entry in enumerate(entries, 1):
        items = array_entries(entry)
        start = number_tuple(items[0], 3) if items else None
        numbers = [as_number(v) for v in items[1:]]
        if start is None or len(numbers) != 10 or None in numbers:
            fail(f"{uid}: RunWays[{i}] {entry!r} is not {{xyz, 10 numbers}}")
        out.append(
            {
                "start": start,
                "azimuthDeg": numbers[0],
                "lengthM": numbers[1],
                "widthM": numbers[2],
                "alsArgument": numbers[3],
                "glidePath": dict(zip(_GLIDE_PATH, numbers[4:], strict=True)),
            }
        )
    return out


def _position(raw: dict[str, Any], key: str, n: int, uid: str) -> list[Any] | None:
    """``raw[key]`` as exactly ``n`` numbers (absent: None; else an error)."""
    value = raw.get(key)
    if value is None:
        return None
    numbers = number_tuple(value, n)
    if numbers is None:
        fail(f"{uid}: {key} {value!r} is not {n} numbers")
    return numbers


def _counted(table: dict[str, Any], count_key: str, uid: str, what: str) -> list[Any]:
    """The numbered entries of a DCS table that states their number in
    ``count_key`` (checked)."""
    entries = array_entries(table, mixed=True)
    count = as_number(table.get(count_key))
    if count is not None and count != len(entries):
        fail(f"{uid}: {what}.{count_key} {count} but {len(entries)} entries")
    return entries


def _points(value: Any, uid: str, what: str) -> list[dict[str, Any]]:
    """``Entity.PathPoint`` per ``{{x, y, z}, n, ...}`` entry."""
    out = []
    for entry in array_entries(value):
        items = array_entries(entry)
        position = array_entries(items[0]) if items else []
        values = items[1:]
        if len(position) < 3 or any(as_number(v) is None for v in (*position, *values)):
            fail(f"{uid}: {what} point {entry!r} is not {{xyz, numbers}}")
        out.append({"position": position, "values": values})
    return out


def _taxi_routes(raw: dict[str, Any], uid: str) -> list[dict[str, Any]] | None:
    table = raw.get("TaxiRoutes")
    if table is None:
        return None
    routes = _counted(as_dict(table), "RoutesNumber", uid, "TaxiRoutes")
    return [{"points": _points(r, uid, "TaxiRoutes")} for r in routes] or None


def _spawn_terminals(raw: dict[str, Any], uid: str) -> list[dict[str, Any]] | None:
    table = raw.get("HelicopterSpawnTerminal")
    if table is None:
        return None
    out = []
    for entry in _counted(
        as_dict(table), "TerminalNumber", uid, "HelicopterSpawnTerminal"
    ):
        entry = as_dict(entry)
        terminal = as_number(entry.get("TerminalIdx"))
        if terminal is None:
            fail(f"{uid}: HelicopterSpawnTerminal entry without TerminalIdx")
        out.append(
            {
                "terminal": terminal,
                "points": _points(entry.get("Points"), uid, "HelicopterSpawnTerminal"),
            }
        )
    return out or None


def _arresting_gears(raw: dict[str, Any], uid: str) -> list[dict[str, Any]] | None:
    table = raw.get("ArrestingGears")
    if table is None:
        return None
    out = []
    for entry in _counted(
        as_dict(table), "ArrestingGearsNumber", uid, "ArrestingGears"
    ):
        gear: dict[str, Any] = {}
        for side in ("Left", "Right"):
            end = as_dict(as_dict(entry).get(side))
            fields = {
                f"{side.lower()}Connector": as_string(end.get("connector_name")),
                f"{side.lower()}Position": number_tuple(end.get("pos"), 3),
            }
            if sum(v is not None for v in fields.values()) != 1 or set(end) - {
                "connector_name",
                "pos",
            }:
                fail(f"{uid}: ArrestingGears {side} {end!r} is not a connector or pos")
            assign_defined(gear, fields)
        out.append(gear)
    return out or None


def facilities(raw: dict[str, Any], uid: str) -> dict[str, Any] | None:
    """``Entity.UnitFacilities``."""
    counts = _numbers(
        raw,
        {
            "numParking": "numParking",
            "planeNum": "Plane_Num_",
            "helicopterNum": "Helicopter_Num_",
        },
    )
    return _block(
        {
            "tacan": _bool(raw, "TACAN", uid),
            "icls": _bool(raw, "ICLS", uid),
            "lrls": _bool(raw, "LRLS", uid),
            "ols": _ols(raw, uid),
            **{k: int(v) for k, v in counts.items() if v is not None},
            "runways": _runways(raw, uid),
            "deckLevelM": as_number(raw.get("DeckLevel")),
            "tacanPosition": _position(raw, "TACAN_position", 3, uid),
            "tacanDefaultChannel": as_number(raw.get("TACAN_def_channel")),
            "iclsLocalizerPosition": _position(raw, "ICLS_Localizer_position", 4, uid),
            "iclsGlideslopePosition": _position(
                raw, "ICLS_Glideslope_position", 4, uid
            ),
            "landingPoint": _position(raw, "Landing_Point", 3, uid),
            "arrestingGears": _arresting_gears(raw, uid),
            "taxiRoutes": _taxi_routes(raw, uid),
            "helicopterSpawnTerminals": _spawn_terminals(raw, uid),
        }
    )


def _task(value: Any, uid: str) -> dict[str, Any]:
    task = as_dict(value)
    wid, name = as_number(task.get("WorldID")), as_string(task.get("Name"))
    if wid is None or not name:
        fail(f"{uid}: task {value!r} has no WorldID/Name")
    return {"id": int(wid), "name": name}


def tasks(raw: dict[str, Any], uid: str) -> dict[str, Any]:
    """``tasks`` (``Tasks``, in DCS order) and ``defaultTask`` (``DefaultTask``)."""
    out: dict[str, Any] = {}
    value = raw.get("Tasks")
    if value is not None:
        entries = array_entries(value)
        if value and not entries:
            fail(f"{uid}: Tasks {value!r} is not an array")
        out["tasks"] = [_task(t, uid) for t in entries]
    if raw.get("DefaultTask") is not None:
        out["defaultTask"] = _task(raw["DefaultTask"], uid)
    return out


def performance(raw: dict[str, Any]) -> dict[str, Any] | None:
    """``Entity.AircraftPerformance``."""
    engines = as_number(raw.get("engines_count"))
    return _block(
        {
            **_numbers(
                raw,
                {
                    "hMaxM": "H_max",
                    "machMax": "Mach_max",
                    "vMaxSeaLevelMs": "V_max_sea_level",
                    "vMaxHMs": "V_max_h",
                    "vOptMs": "V_opt",
                    "rangeKm": "range",
                    "vTakeOffMs": "V_take_off",
                    "vLandMs": "V_land",
                    "casMin": "CAS_min",
                    "nyMax": "Ny_max",
                    "bankAngleMaxDeg": "bank_angle_max",
                    "averageFuelConsumptionKgS": "average_fuel_consumption",
                },
            ),
            "enginesCount": int(engines) if engines is not None else None,
        }
    )


def _names(value: Any, uid: str, key: str) -> list[str] | None:
    """``{{Name = ...}, ...}`` as its names; an empty table is none."""
    if value is None:
        return None
    entries = array_entries(value)
    names = [as_string(as_dict(e).get("Name")) for e in entries]
    if (value and not entries) or None in names:
        fail(f"{uid}: {key} {value!r} is not a list of {{Name}}")
    return [n for n in names if n is not None]


def operations(raw: dict[str, Any], uid: str) -> dict[str, Any] | None:
    """``Entity.AircraftOperations``."""
    laser = as_dict(raw.get("laserEquipment"))
    if set(laser) - {"laserDesignator", "laserRangefinder"}:
        fail(f"{uid}: laserEquipment {laser!r} has unknown fields")
    date = raw.get("date_of_introduction")
    if date is not None and as_number(date) is None:
        fail(f"{uid}: date_of_introduction {date!r} is not a number")
    return _block(
        {
            "takeOffRunwayCategories": _names(
                raw.get("TakeOffRWCategories"), uid, "TakeOffRWCategories"
            ),
            "landRunwayCategories": _names(
                raw.get("LandRWCategories"), uid, "LandRWCategories"
            ),
            "bigParkingRamp": _bool(raw, "bigParkingRamp", uid),
            "laserDesignator": _bool(laser, "laserDesignator", uid),
            "laserRangefinder": _bool(laser, "laserRangefinder", uid),
            "eplrs": _bool(raw, "EPLRS", uid),
            "dateOfIntroduction": as_number(date),
        }
    )


def failures(raw: dict[str, Any], uid: str) -> list[dict[str, Any]] | None:
    """``Failures`` as ``{id, label}``, in DCS order."""
    value = raw.get("Failures")
    if value is None:
        return None
    entries = array_entries(value)
    out = [
        {
            "id": as_string(as_dict(e).get("id")),
            "label": as_string(as_dict(e).get("label")),
        }
        for e in entries
    ]
    if (value and not entries) or any(None in f.values() for f in out):
        fail(f"{uid}: Failures {value!r} is not a list of {{id, label}}")
    return out


_CM_SYSTEMS = {"ECM": "ecm", "IRCM": "ircm", "DISPENSER": "dispenserSystems"}


def countermeasure_systems(raw: dict[str, Any], uid: str) -> dict[str, Any]:
    """``Countermeasures.ECM``/``IRCM``/``DISPENSER`` as name lists."""
    table = as_dict(raw.get("Countermeasures"))
    if set(table) - set(_CM_SYSTEMS):
        fail(f"{uid}: Countermeasures {table!r} has unknown fields")
    out: dict[str, Any] = {}
    for dcs, name in _CM_SYSTEMS.items():
        if dcs in table:
            names = (
                [table[dcs]] if isinstance(table[dcs], str) else strings_of(table[dcs])
            )
            if not names:
                fail(f"{uid}: Countermeasures.{dcs} {table[dcs]!r} names nothing")
            out[name] = names
    return out


def refuelling(raw: dict[str, Any], uid: str) -> dict[str, Any] | None:
    """``Entity.AircraftRefuelling``."""
    tanker = raw.get("is_tanker")
    if tanker is not None and not isinstance(tanker, (bool, int, float)):
        fail(f"{uid}: is_tanker {tanker!r} is neither boolean nor number")
    tanker_type = as_number(raw.get("tanker_type"))
    return _block(
        {
            "isTanker": tanker,
            "tankerType": int(tanker_type) if tanker_type is not None else None,
            "receptaclePosition": number_tuple(raw.get("air_refuel_receptacle_pos"), 3),
        }
    )


def _charge(value: Any) -> dict[str, Any] | None:
    return _block(
        _numbers(
            as_dict(value),
            {"chargeSize": "chargeSz", "default": "default", "increment": "increment"},
        )
    )


def countermeasures(raw: dict[str, Any], uid: str) -> dict[str, Any] | None:
    """``Entity.AircraftCountermeasures`` from ``passivCounterm``,
    ``chaff_flare_dispenser`` and ``Countermeasures``; a dispenser entry that
    is not ``{dir, pos}`` is reported and left out."""
    passive = as_dict(raw.get("passivCounterm"))
    dispensers: list[dict[str, Any]] = []
    value = raw.get("chaff_flare_dispenser")
    entries = array_entries(value)
    bad: list[Any] = [] if entries or not value else [value]
    for entry in entries:
        pos = number_tuple(as_dict(entry).get("pos"), 3)
        direction = number_tuple(as_dict(entry).get("dir"), 3)
        if pos is None or direction is None:
            bad.append(entry)
            continue
        dispensers.append({"position": pos, "direction": direction})
    if bad:
        warn(f"{uid}: chaff_flare_dispenser entries without dir/pos left out: {bad}")
    return _block(
        {
            "cmdsEdit": _bool(passive, "CMDS_Edit", uid),
            "singleChargeTotal": as_number(passive.get("SingleChargeTotal")),
            "chaff": _charge(passive.get("chaff")),
            "flare": _charge(passive.get("flare")),
            "dispensers": dispensers or None,
            **countermeasure_systems(raw, uid),
        }
    )


def country_of_origin(raw: dict[str, Any], uid: str) -> str | None:
    """``country_of_origin``, or its misspelling ``country_of_orgin``."""
    return as_string(_merged(raw, ("country_of_origin", "country_of_orgin"), uid))


# Mission-editor layout fields of an ``AddProp*`` entry, left out.
_OPTION_LAYOUT = {"wCtrl", "xCtrl", "wLbl", "xLbl"}
_OPTION_FIELDS = {
    "id": "id",
    "control": "control",
    "label": "label",
    "playerOnly": "playerOnly",
    "defValue": "default",
    "min": "min",
    "max": "max",
    "dimension": "dimension",
    "maxLength": "maxLength",
    "hint": "hint",
    "arg": "arg",
    "argTbl": "argTable",
    "boolean_inverted": "booleanInverted",
    "weight": "weightKg",
    "weightWhenOn": "weightWhenOnKg",
    "values": "values",
    "forcedPylons": "forcedPylons",
    "weaponRestricted": "weaponRestricted",
    "removeWeapons": "removeWeapons",
}
_VALUE_FIELDS = {
    "id": "id",
    "dispName": "label",
    "value": "value",
    "weightWhenOn": "weightWhenOnKg",
    "weightDependentOfFuel": "weightDependentOfFuel",
    "guiAction": "guiAction",
}


def _renamed(entry: Any, names: dict[str, str], where: str) -> dict[str, Any]:
    table = as_dict(entry)
    unknown = set(table) - set(names) - _OPTION_LAYOUT
    if not table or unknown:
        fail(f"{where}: {entry!r} has unknown fields {sorted(unknown)}")
    return {names[k]: v for k, v in table.items() if k in names}


def mission_options(
    raw: dict[str, Any], key: str, uid: str
) -> list[dict[str, Any]] | None:
    """``Entity.MissionOption`` per ``AddPropAircraft``/``AddPropVehicle``
    entry, in DCS order."""
    value = raw.get(key)
    if value is None:
        return None
    entries = array_entries(value)
    if value and not entries:
        fail(f"{uid}: {key} {value!r} is not an array")
    out: list[dict[str, Any]] = []
    for i, entry in enumerate(entries, 1):
        where = f"{uid}: {key}[{i}]"
        option = _renamed(entry, _OPTION_FIELDS, where)
        if not isinstance(option.get("id"), str) or not isinstance(
            option.get("control"), str
        ):
            fail(f"{where}: no string id/control")
        if "values" in option:
            option["values"] = [
                _renamed(v, _VALUE_FIELDS, f"{where}.values")
                for v in array_entries(option["values"])
            ]
        out.append(option)
    return out
