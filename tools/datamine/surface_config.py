"""Surface-unit fields typed by ``F`` specs (ground vehicles, ships,
structures): DCS keys the hand-written property builders do not read, added
to the record block that reads the same DCS table.

* ``mobility``      - ``chassis`` drive-train keys (vehicles), top-level
  acceleration, obstacle and periscope keys (ships);
* ``dimensions``    - top-level waterline length and wake points (ships);
* ``detection``     - top-level radar periods, ``Sensors.Mount_WS_ID`` and
  ``noVisualDetectorInAlarmedState``; ``detection.sensor`` gets
  ``sensor.beamWidth``;
* ``fireControl``   - named keys of ``WS``;
* ``weaponSystems`` - each launcher entry gets its mount ``WS[i]`` keys, its
  ``WS[i].LN[j]`` keys (``sensor`` as a block) and its payloads' ``PL[k]``
  keys;
* structures        - top-level ``mass``, ``minMass``, ``maxMass``.

Values are copied exactly. A field name carries a unit suffix where an install
script states the unit; other numbers are raw DCS values.
"""

from __future__ import annotations

from typing import Any

from .lua_reader import array_entries, as_dict
from .typed_fields import F, typed_block

# --- mobility, dimensions, mass -----------------------------------------------

VEHICLE_MOBILITY = (  # chassis
    F("r_max", "rMaxM", unit="m"),
    F("max_acceleration", "maxAcceleration"),
    F("trace_width", "traceWidth"),
    F("gear_type", "gearType"),
    F("mainGearRatio", "mainGearRatio"),
    F("gearRatios", "gearRatios", "numbers"),
    F("engineMaxRPM", "engineMaxRpm"),
    F("engineMinRPM", "engineMinRpm"),
    F("engineMaxPowerRPM", "engineMaxPowerRpm"),
    F("engineMOI", "engineMoi"),
    F("waterline_level", "waterlineLevel"),
    F("max_trench_width", "maxTrenchWidth"),
    F("canWade", "canWade", "boolean"),
    F("automaticTransmission", "automaticTransmission", "boolean"),
)
SHIP_MOBILITY = (
    F("speedup", "speedup"),
    F("distFindObstacles", "distFindObstacles"),
    F("riverCraft", "riverCraft", "boolean"),
    F("minPeriscopeDepth", "minPeriscopeDepth"),
    F("maxPeriscopeDepth", "maxPeriscopeDepth"),
    F("periscopeHeight", "periscopeHeight"),
)
SHIP_DIMENSIONS = (
    F("shipLength", "shipLengthM", unit="m"),
    F("X_nose", "xNoseM", unit="m"),
    F("X_tail", "xTailM", unit="m"),
    F("Tail_Width", "tailWidth"),
)
STRUCTURE_MASS = (F("mass", "mass"), F("minMass", "minMass"), F("maxMass", "maxMass"))

# --- detection ------------------------------------------------------------------

DETECTION = (
    F("radar1_period", "radar1Period"),
    F("radar2_period", "radar2Period"),
    F("radar3_period", "radar3Period"),
)
SENSOR_MOUNTS = (  # Sensors
    F("Mount_WS_ID", "sensorMountWs"),
    F("noVisualDetectorInAlarmedState", "noVisualDetectorInAlarmedState", "boolean"),
)
SENSOR = (F("beamWidth", "beamWidthRad", unit="rad"),)  # sensor

# --- weapons --------------------------------------------------------------------

FIRE_CONTROL = (  # WS named keys
    F("radar_rotation_type", "radarRotationType"),
    F("searchRadarMaxElevation", "searchRadarMaxElevationRad", unit="rad"),
    F("searchRadarFrequencies", "searchRadarFrequencies", "rows"),
    F("smoke", "smoke", "strings"),
)
MOUNT = (  # WS[i]
    F("angles_mech", "anglesMechRad", "rows", unit="rad"),
    F("reference_angle_X", "referenceAngleXRad", unit="rad"),
    F("reference_angle_Y", "referenceAngleYRad", unit="rad"),
    F("reference_angle_Z", "referenceAngleZRad", unit="rad"),
    F("reloadAngleY", "reloadAngleY"),
    F("reloadAngleZ", "reloadAngleZ"),
    F("maxLeft", "maxLeft"),
    F("maxRight", "maxRight"),
    F("maxTop", "maxTop"),
    F("maxBottom", "maxBottom"),
    F("base", "baseWs"),
    F("ECM_K", "mountEcmK"),
    F("radar_type", "radarType"),
    F("moveable", "moveable", "boolean"),
    F("stabilizer", "stabilizer", "boolean"),
    F("laser", "laser", "boolean"),
    F("canSetTacticalDir", "canSetTacticalDir", "boolean"),
    F("mount_before_move", "mountBeforeMove", "boolean"),
    F("sharesBarrelsBetweenLaunchers", "sharesBarrelsBetweenLaunchers", "boolean"),
)
LAUNCHER = (  # WS[i].LN[j]
    F("distanceMaxForFCS", "distanceMaxForFcs"),
    F("combatRange", "combatRange"),
    F("launch_delay_human", "launchDelayHuman"),
    F("sightMaxTanVel", "sightMaxTanVel"),
    F("min_launch_angle", "minLaunchAngle"),
    F("rail_length", "railLength"),
    F("inclination_correction_bias", "inclinationCorrectionBias"),
    F("inclination_correction_upper_limit", "inclinationCorrectionUpperLimit"),
    F("dispertionReductionFactor", "dispertionReductionFactor"),
    F("radialDisperse", "radialDisperse"),
    F("missileControlInterval", "missileControlInterval"),
    F("out_velocity", "outVelocity"),
    F("maxTrackingSpeed", "maxTrackingSpeed"),
    F("reload_time", "reloadTime"),
    F("barrels_reload_type", "barrelsReloadType"),
    F("primaryWeapon", "primaryWeapon", "boolean"),
    F("secondary", "secondary", "boolean"),
    F("useTargetAccelInSight", "useTargetAccelInSight", "boolean"),
    F("automaticLoader", "automaticLoader", "boolean"),
)
LAUNCHER_SENSOR = (  # WS[i].LN[j].sensor
    F("type", "type"),
    F("deviation_error_azimuth", "deviationErrorAzimuth"),
    F("deviation_error_elevation", "deviationErrorElevation"),
    F("deviation_error_distance", "deviationErrorDistance"),
    F("deviation_error_speed_sensor", "deviationErrorSpeedSensor"),
    F("deviation_error_stability", "deviationErrorStability"),
)
PAYLOAD = (  # WS[i].LN[j].PL[k]
    F("switch_on_delay", "switchOnDelay"),
    F("feedSlot", "feedSlot"),
    F("automaticLoader", "automaticLoader", "boolean"),
)


def _extend(blocks: dict[str, Any], name: str, extra: dict[str, Any]) -> None:
    """Add ``extra`` to ``blocks[name]`` (creating it when absent)."""
    if extra:
        blocks[name] = {**(blocks.get(name) or {}), **extra}


def _weapon_systems(rec: dict[str, Any], entries: list[dict[str, Any]]) -> None:
    """Add the ``MOUNT``, ``LAUNCHER`` and ``PAYLOAD`` fields to the public
    ``weaponSystems`` entries (one per ``WS[i].LN[j]``, payloads in ``PL``
    order), in place."""
    systems = array_entries(rec.get("WS"), mixed=True)
    for entry in entries:
        ws = as_dict(systems[entry["ws"] - 1])
        ln = as_dict(array_entries(ws.get("LN"))[entry["ln"] - 1])
        entry |= typed_block(ws, MOUNT) | typed_block(ln, LAUNCHER)
        if sensor := typed_block(as_dict(ln.get("sensor")), LAUNCHER_SENSOR):
            entry["sensor"] = sensor
        pls = [p for p in array_entries(ln.get("PL")) if isinstance(p, dict)]
        for payload, pl in zip(entry.get("payloads", []), pls, strict=True):
            payload |= typed_block(pl, PAYLOAD)


def extend(blocks: dict[str, Any], rec: dict[str, Any], series: str) -> None:
    """Add the typed fields of the unit record ``rec`` of ``series`` to its
    built ``blocks`` (``mobility``, ``dimensions``, ``detection``,
    ``fireControl``, ``weaponSystems``; a structure's mass fields), in place."""
    if series == "ground_vehicles":
        _extend(
            blocks,
            "mobility",
            typed_block(as_dict(rec.get("chassis")), VEHICLE_MOBILITY),
        )
    elif series == "ships":
        _extend(blocks, "mobility", typed_block(rec, SHIP_MOBILITY))
        _extend(blocks, "dimensions", typed_block(rec, SHIP_DIMENSIONS))
    elif series == "structures":
        blocks |= typed_block(rec, STRUCTURE_MASS)
    if series not in ("ground_vehicles", "ships"):
        return
    _extend(
        blocks,
        "detection",
        typed_block(rec, DETECTION)
        | typed_block(as_dict(rec.get("Sensors")), SENSOR_MOUNTS),
    )
    if sensor := typed_block(as_dict(rec.get("sensor")), SENSOR):
        detection = blocks["detection"] = blocks.get("detection") or {}
        detection["sensor"] = {**(detection.get("sensor") or {}), **sensor}
    _extend(blocks, "fireControl", typed_block(as_dict(rec.get("WS")), FIRE_CONTROL))
    _weapon_systems(rec, blocks.get("weaponSystems") or [])
