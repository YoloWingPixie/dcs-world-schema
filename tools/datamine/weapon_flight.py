"""The ``weapon_flight`` series (``Entity.WeaponFlight``): the named flight
configuration of a weapon, one record per weapon.

A record is read from the weapon's ``weapons_table`` record: its ``client``
block, plus the record's own plain keys the block does not set. A weapon
without a ``weapons_table`` record is read from its flat ``_G/rockets``,
``_G/bombs`` or ``_G/torpedoes`` record. Only fields with a known meaning are
typed; values are copied exactly (no rounding or conversion). Everything else
is only in the ``_G`` dump, which ``sourcePaths`` and each block's
``sourcePath`` point into (``dump_paths``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .dump_paths import pointer
from .typed_fields import F, typed_block
from .typed_fields import is_number as _is_number

AERODYNAMICS: tuple[F, ...] = (
    F("mass", "massKg", unit="kg"),
    F("caliber", "caliberM", unit="m"),
    F("L", "lengthM", unit="m"),
    F("S", "referenceArea"),
    F("table_scale", "machStep"),
    F("Cx0", "cx0", "numbers"),
    F("CxB", "cxB", "numbers"),
    F("K1", "k1", "numbers"),
    F("K2", "k2", "numbers"),
    F("Cya", "cya", "numbers"),
    F("Cza", "cza", "numbers"),
    F("Mya", "mya", "numbers"),
    F("Mza", "mza", "numbers"),
    F("Myw", "myw", "numbers"),
    F("Mzw", "mzw", "numbers"),
    F("A1trim", "a1Trim", "numbers"),
    F("A2trim", "a2Trim", "numbers"),
    F("cx_coeff", "cxCoeff", "numbers"),
    F("Ix", "ix"),
    F("Iy", "iy"),
    F("Iz", "iz"),
    F("delta_max", "finDeflectionMaxRad", unit="rad"),
    F("maxAoa", "maxAoaRad", unit="rad"),
)

# A motor stage: a block with impulse/fuel_mass/work_time, or a torpedo
# engine with a thrust value.
STAGE_MARKERS = ("impulse", "fuel_mass", "work_time")
THRUST_MARKERS = ("thrust", "default_thrust")
MOTOR_STAGE: tuple[F, ...] = (
    F("impulse", "impulseS", unit="s"),
    F("fuel_mass", "fuelMassKg", unit="kg"),
    F("work_time", "workTimeS", unit="s"),
    F("boost_factor", "boostFactor"),
    F("thrust", "thrust"),
    F("default_thrust", "thrust"),
)
# Controller keys giving a stage's start time: ``<stage>_start``.
START_KEY = re.compile(r"^(boost|march2?|booster)_start$")

OP_TIME = F("op_time", "operatingTime")
AUTOPILOT_NAMES = ("autopilot", "ap")
AUTOPILOT: tuple[F, ...] = (
    F("Knav", "navigationGain"),
    F("gload_limit", "gLoadLimit"),
    F("fins_limit", "finsLimitRad", unit="rad"),
    OP_TIME,
)
SEEKER_NAMES = ("seeker", "sensor")
SEEKER: tuple[F, ...] = (
    F("FOV", "fovRad", unit="rad"),
    F("sens_near_dist", "nearDistance"),
    F("sens_far_dist", "farDistance"),
    OP_TIME,
)
GIMBAL: tuple[F, ...] = (
    F("yaw_max", "yawMaxRad", unit="rad"),
    F("pitch_max", "pitchMaxRad", unit="rad"),
    F("max_tracking_rate", "trackingRateMaxRadS", unit="rad/s"),
    OP_TIME,
)
PROXIMITY_FUZE: tuple[F, ...] = (
    F("radius", "radius"),
    F("arm_delay", "armDelay"),
)
TOP: tuple[F, ...] = (
    F("Life_Time", "batteryLifeS", unit="s"),
    F("KillDistance", "killDistanceM", unit="m"),
    F("Range_max", "rangeMaxM", unit="m"),
    F("Mach_max", "machMax"),
)
# Launch envelope tables (DCS key, envelope field), in envelope field order.
# Rows are launch altitude (m), columns launch TAS (m/s): the AJS37 entry's
# Weapons.lua labels them `Alt` and `TAS`.
LAUNCH_TABLES = (
    ("LaunchDistData", "maxRangeM"),
    ("MinLaunchDistData", "minRangeM"),
    ("AspectDistData", "aspectDeg"),
)
# The typed record fields holding a block, in schema order.
BLOCKS = (
    "aerodynamics",
    "motorStages",
    "autopilot",
    "seeker",
    "gimbal",
    "proximityFuze",
)
# Spec tables per record field (the coverage check maps fields back to keys).
SPECS: dict[str, tuple[F, ...]] = {
    "": TOP,
    "aerodynamics": AERODYNAMICS,
    "motorStages": MOTOR_STAGE,
    "autopilot": AUTOPILOT,
    "seeker": SEEKER,
    "gimbal": GIMBAL,
    "proximityFuze": PROXIMITY_FUZE,
}


@dataclass(frozen=True)
class Source:
    """One dump file of a weapon: its dump path (``_G/...`` without
    ``.lua``), whether it is a ``weapons_table`` record and its raw table."""

    path: str
    weapons_table: bool
    raw: dict[str, Any]


def _block(view: dict[str, Any], name: str, specs: tuple[F, ...], path: str) -> Any:
    block = view.get(name)
    if not isinstance(block, dict):
        return None
    typed = typed_block(block, specs)
    return {"sourcePath": path + pointer(name), **typed} if typed else None


def _launch_table(value: Any) -> tuple[list[Any], list[Any], list[list[Any]]] | None:
    """(row headers, column headers, cells by row) of a ``{rows, cols, cols
    column headers, then per row its header and cols cells}`` list; None for
    another layout."""
    if not isinstance(value, list) or len(value) < 2:
        return None
    v: list[Any] = value
    rows, cols = v[0], v[1]
    if not (
        all(_is_number(x) for x in v)
        and float(rows).is_integer()
        and float(cols).is_integer()
        and rows > 0
        and cols > 0
        and len(v) == 2 + cols + rows * (cols + 1)
    ):
        return None
    r, c = int(rows), int(cols)
    body = [v[2 + c + i * (c + 1) : 2 + c + (i + 1) * (c + 1)] for i in range(r)]
    return [row[0] for row in body], v[2 : 2 + c], [row[1:] for row in body]


def _launch_envelopes(view: dict[str, Any], path: str) -> list[dict[str, Any]]:
    """``Entity.WeaponLaunchEnvelope`` list: the tables of ``LAUNCH_TABLES``
    that decode, one envelope per distinct (altitudes, speeds) axes pair, in
    ``LAUNCH_TABLES`` order of each pair's first table."""
    out: list[dict[str, Any]] = []
    for key, field in LAUNCH_TABLES:
        table = _launch_table(view.get(key))
        if table is None:
            continue
        altitudes, speeds, cells = table
        env = next(
            (
                e
                for e in out
                if e["altitudesM"] == altitudes and e["speedsMs"] == speeds
            ),
            None,
        )
        if env is None:
            env = {"sourcePath": path, "altitudesM": altitudes, "speedsMs": speeds}
            out.append(env)
        env[field] = cells
    return out


def _pn_entries(value: Any) -> list[dict[str, Any]] | None:
    """``PN_coeffs`` ``{n, d1, pn1, ..., dn, pnn}`` as ``[{distanceM, gain}]``;
    None for another layout."""
    if (
        not isinstance(value, list)
        or not value
        or not all(_is_number(x) for x in value)
        or not float(value[0]).is_integer()
        or len(value) != 1 + 2 * int(value[0])
    ):
        return None
    n = int(value[0])
    return [{"distanceM": value[1 + 2 * i], "gain": value[2 + 2 * i]} for i in range(n)]


def _stages(view: dict[str, Any], path: str) -> list[dict[str, Any]]:
    starts: dict[str, Any] = {}
    for block in view.values():
        if isinstance(block, dict):
            for k, v in block.items():
                if isinstance(k, str) and START_KEY.match(k) and _is_number(v):
                    starts.setdefault(k.removesuffix("_start"), v)
    out = []
    for name in sorted(view):
        block = view[name]
        if not isinstance(block, dict) or not any(
            k in block for k in (*STAGE_MARKERS, *THRUST_MARKERS)
        ):
            continue
        typed = typed_block(block, MOTOR_STAGE)
        if not typed:
            continue
        stage = {"stage": name, "sourcePath": path + pointer(name), **typed}
        if name in starts:
            stage["startTime"] = starts[name]
        out.append(stage)
    return out


def _view(sources: list[Source]) -> tuple[str, str, dict[str, Any]] | None:
    """(record path, variant pointer, view) of the weapon's flight record."""
    own = next((s for s in sources if s.weapons_table), None)
    if own is not None:
        client = own.raw.get("client")
        if isinstance(client, dict):
            top = {k: v for k, v in own.raw.items() if not isinstance(v, dict)}
            return own.path, pointer("client"), {**top, **client}
        return own.path, "", own.raw
    if sources:
        return sources[0].path, "", sources[0].raw
    return None


def flight(weapon: str, sources: list[Source]) -> dict[str, Any] | None:
    """``Entity.WeaponFlight`` of ``weapon``; None when nothing is typed."""
    found = _view(sources)
    if found is None:
        return None
    record_path, ptr, view = found
    path = f"{record_path}#{ptr}"
    out: dict[str, Any] = typed_block(view, TOP)
    if (pn := _pn_entries(view.get("PN_coeffs"))) is not None:
        out["pnCoefficients"] = pn
    if envelopes := _launch_envelopes(view, path):
        out["launchEnvelopes"] = envelopes
    blocks: dict[str, Any] = {
        "aerodynamics": _block(view, "fm", AERODYNAMICS, path),
        "motorStages": _stages(view, path) or None,
        "autopilot": next(
            (b for n in AUTOPILOT_NAMES if (b := _block(view, n, AUTOPILOT, path))),
            None,
        ),
        "seeker": next(
            (b for n in SEEKER_NAMES if (b := _block(view, n, SEEKER, path))), None
        ),
        "gimbal": _block(view, "gimbal", GIMBAL, path),
        "proximityFuze": _block(view, "proximity_fuze", PROXIMITY_FUZE, path),
    }
    out.update({k: v for k, v in blocks.items() if v is not None})
    if not out:
        return None
    return {"weapon": weapon, "sourcePaths": [record_path], "sourcePath": path, **out}


def counts(records: dict[str, dict[str, Any]]) -> dict[str, int]:
    """Records with each block (for the extraction log)."""
    out: dict[str, int] = {}
    for record in records.values():
        for b in BLOCKS:
            if b in record:
                out[b] = out.get(b, 0) + 1
    return dict(sorted(out.items()))
