"""Extract ``Entity.Sensor`` records from ``_G/db/Sensors/Sensor``.

``category`` (SENSOR_*) and ``type`` (OPTIC_SENSOR_* for optics, RADAR_* for
radars) are kept as DCS numbers with their constant names; ``kind`` is read
from those names. The detection range is ``max_measuring_distance`` (metres),
else for an IRST the largest of its ``detection_distance_for_tail_on_Su_27``.
The keys of the ``detection_distance`` tables are DCS constants the install's
sensor scripts define as locals (``sensor_keys``)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .common import assign_defined, fail, list_lua, read_text, warn
from .dcs_constants import Constants
from .lua_reader import (
    LuaReader,
    as_dict,
    as_flag,
    as_number,
    as_string,
    km,
    number_tuple,
)

_KIND = {
    "OPTIC_SENSOR_TV": "tv",
    "OPTIC_SENSOR_LLTV": "lltv",
    "OPTIC_SENSOR_IR": "ir",
    "SENSOR_RADAR": "radar",
    "SENSOR_IRST": "irst",
    "SENSOR_RWR": "rwr",
}
_TYPE_ENUM = {
    "SENSOR_OPTICAL": "Entity.OpticSensorType",
    "SENSOR_RADAR": "Entity.RadarType",
}

# Install sensor scripts that define the detection-table key constants as
# locals (``local HEMISPHERE_UPPER = 0``); they must all agree.
SENSOR_KEY_FILES = (
    "CoreMods/aircraft/AJS37/Entry/Sensors.lua",
    "CoreMods/aircraft/A-6E/Entry/Sensors.lua",
    "CoreMods/aircraft/F-4E/Entry/Sensors.lua",
    "CoreMods/aircraft/ChinaAssetPack/Entries/Loadouts/sensors.lua",
)
# DCS constant -> field name.
_HEMISPHERES = {"HEMISPHERE_UPPER": "upper", "HEMISPHERE_LOWER": "lower"}
_ASPECTS = {"ASPECT_HEAD_ON": "HeadOnM", "ASPECT_TAIL_ON": "TailOnM"}
_ENGINE_MODES = {
    "ENGINE_MODE_FORSAGE": "afterburnerM",
    "ENGINE_MODE_MAXIMAL": "maximalM",
    "ENGINE_MODE_MINIMAL": "minimalM",
}
_LOCAL = re.compile(r"^\s*local\s+([A-Z_]+)\s*=\s*(\d+)\s*$", re.MULTILINE)


def sensor_keys(install_dir: Path) -> dict[str, int]:
    """``{constant: value}`` of the detection-table keys, read from
    ``SENSOR_KEY_FILES`` (absent files skipped; disagreement or a missing
    constant fails)."""
    wanted = {*_HEMISPHERES, *_ASPECTS, *_ENGINE_MODES}
    found: dict[str, int] = {}
    for rel in SENSOR_KEY_FILES:
        path = install_dir / rel
        if not path.is_file():
            continue
        for name, value in _LOCAL.findall(read_text(path)):
            if name in wanted and found.setdefault(name, int(value)) != int(value):
                fail(f"{rel}: {name} = {value}, another script has {found[name]}")
    if missing := sorted(wanted - set(found)):
        fail(f"install sensor scripts {SENSOR_KEY_FILES} define none of {missing}")
    return found


def sensor_enums(raw: dict[str, Any], constants: Constants) -> dict[str, Any]:
    """``category``/``categoryName`` and, for optics and radars, ``type``/``typeName``."""
    out: dict[str, Any] = {}
    constants.set_pair(out, "category", "Entity.SensorCategory", raw.get("category"))
    type_enum = _TYPE_ENUM.get(out.get("categoryName", ""))
    if type_enum and as_number(raw.get("type")) is not None:
        constants.set_pair(out, "type", type_enum, raw.get("type"))
    return out


def sensor_kind(enums: dict[str, Any]) -> str | None:
    category = enums.get("categoryName")
    if category == "SENSOR_OPTICAL":
        return _KIND.get(enums.get("typeName", ""))
    return _KIND.get(category or "")


def _keyed(table: Any, key: int) -> Any:
    """``table[key]`` of a Lua table read with string or list keys."""
    if isinstance(table, list):
        return table[key - 1] if 0 < key <= len(table) else None
    return as_dict(table).get(str(key))


def _detection_distance(name: str, table: Any, keys: dict[str, int]) -> Any:
    """``Entity.RadarDetectionDistance`` from ``detection_distance``
    (``[hemisphere][aspect]``, metres)."""
    if table is None:
        return None
    out: dict[str, Any] = {}
    for hemi, prefix in _HEMISPHERES.items():
        row = _keyed(table, keys[hemi])
        for aspect, suffix in _ASPECTS.items():
            value = as_number(_keyed(row, keys[aspect]))
            if value is None:
                fail(f"sensor {name}: detection_distance[{hemi}][{aspect}] missing")
            out[prefix + suffix] = value
    return out


def _volume(value: Any) -> dict[str, Any] | None:
    """``{azimuthDeg, elevationDeg}`` of a ``{azimuth, elevation}`` pair table."""
    block = as_dict(value)
    return (
        _block(
            {
                "azimuthDeg": number_tuple(block.get("azimuth"), 2),
                "elevationDeg": number_tuple(block.get("elevation"), 2),
            }
        )
        if block
        else None
    )


def _block(fields: dict[str, Any]) -> dict[str, Any] | None:
    out: dict[str, Any] = {}
    assign_defined(out, fields)
    return out or None


def _search(name: str, block: dict[str, Any], keys: dict[str, int]) -> dict[str, Any]:
    """Fields shared by a radar and its ``air_search`` block."""
    centred = as_dict(block.get("centered_scan_volume"))
    return {
        "detectionDistance": _detection_distance(
            name, block.get("detection_distance"), keys
        ),
        "rcs": as_number(block.get("RCS")),
        "lockOnDistanceCoeff": as_number(block.get("lock_on_distance_coeff")),
        "twsMaxTargets": as_number(block.get("TWS_max_targets")),
        "multipleTargetsTracking": as_flag(
            block.get("multiple_targets_tracking"),
            f"sensor {name}: multiple_targets_tracking",
        ),
        "centeredScanVolume": _block(
            {
                "azimuthSectorDeg": as_number(centred.get("azimuth_sector")),
                "elevationSectorDeg": as_number(centred.get("elevation_sector")),
            }
        ),
    }


def _surface_search(name: str, value: Any) -> dict[str, Any] | None:
    block = as_dict(value)
    return _block(
        {
            "rcs": as_number(block.get("RCS")),
            "vehiclesDetection": as_flag(
                block.get("vehicles_detection"), f"sensor {name}: vehicles_detection"
            ),
            "rbmDetectionDistanceM": as_number(block.get("RBM_detection_distance")),
            "gmtiDetectionDistanceM": as_number(block.get("GMTI_detection_distance")),
            "hrmDetectionDistanceM": as_number(block.get("HRM_detection_distance")),
        }
    )


def _irst_distance(name: str, value: Any, keys: dict[str, int]) -> Any:
    """``Entity.IrstDetectionDistance`` from ``detection_distance_for_tail_on_Su_27``."""
    if value is None:
        return None
    out: dict[str, Any] = {}
    for mode, field_name in _ENGINE_MODES.items():
        distance = as_number(_keyed(value, keys[mode]))
        if distance is None:
            fail(f"sensor {name}: detection_distance_for_tail_on_Su_27[{mode}] missing")
        out[field_name] = distance
    return out


def build_sensors(
    reader: LuaReader,
    g_dir: Path,
    constants: Constants,
    keys: dict[str, int],
    pod_sensors: dict[str, list[str]] | None = None,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Return (sensors keyed by ``Name``, names whose kind is not determinable).
    ``keys``: ``sensor_keys``; ``pod_sensors``: ``{db.Pods DisplayName: sensor
    ids}``, inverted into each sensor's ``pods``."""
    pods: dict[str, list[str]] = {}
    for pod, ids in sorted((pod_sensors or {}).items()):
        for sid in ids:
            pods.setdefault(sid, []).append(pod)
    sensors: dict[str, dict[str, Any]] = {}
    unknown: list[str] = []
    for file, raw in reader.read_many(list_lua(g_dir / "db" / "Sensors" / "Sensor")):
        if not isinstance(raw, dict):
            continue
        name = as_string(raw.get("Name"))
        if not name:
            fail(f"sensor without Name: {file}")
        enums = sensor_enums(raw, constants)
        kind = sensor_kind(enums)
        if kind is None:
            unknown.append(name)
        record: dict[str, Any] = {
            "id": name,
            "kind": kind or "unknown",
            **enums,
        }
        irst = _irst_distance(
            name, raw.get("detection_distance_for_tail_on_Su_27"), keys
        )
        detection: tuple[float | None, str | None]
        if (measuring := raw.get("max_measuring_distance")) is not None:
            detection = (km(measuring), "max_measuring_distance")
        elif irst is not None:
            detection = (km(max(irst.values())), "detection_distance_for_tail_on_Su_27")
        else:
            detection = (None, None)
        air = as_dict(raw.get("air_search"))
        assign_defined(
            record,
            {
                "detectionRangeKm": detection[0],
                "detectionRangeField": detection[1],
                **_search(name, raw, keys),
                "scanVolume": _volume(raw.get("scan_volume")),
                "trackVolume": _volume(raw.get("track_volume")),
                "airSearch": _block(_search(name, air, keys)) if air else None,
                "surfaceSearch": _surface_search(name, raw.get("surface_search")),
                "irstDetectionDistance": irst,
                "pods": pods.get(name),
            },
        )
        sensors[name] = record
    if dangling := sorted(set(pods) - set(sensors)):
        warn(f"db.Pods name sensors db.Sensors lacks (upstream gap): {dangling}")
    return sensors, unknown
