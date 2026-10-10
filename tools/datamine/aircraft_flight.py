"""The ``aircraft_flight`` series (``Entity.AircraftFlight``): the AI / simple
flight model of an aircraft, one record per aircraft with one.

Read from the unit's ``db.Units.Planes``/``db.Units.Helicopters`` record:

* ``aerodynamics``, ``engine`` - ``SFM_Data``'s blocks, their ``table_data``
  rows named by the column legend of the install scripts;
* ``helicopter`` - the rotorcraft keys of the record's top level
  (``rotor_*``, ``*_area``, ``V_max``...) and its ``engine_data`` block.

This is not the player flight model: EFM/PFM modules keep theirs in DLLs,
which are not read. Values are copied exactly (no rounding, no conversion);
keys without a field are only in the ``_G`` dump, which ``sourcePaths`` and
each block's ``sourcePath`` point into (``dump_paths``).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .dump_paths import pointer
from .typed_fields import F, fits, typed_block

# The flight model's masses (top level of the unit record).
MASSES: tuple[F, ...] = (
    F("M_empty", "emptyMassKg", unit="kg"),
    F("M_nominal", "nominalMassKg", unit="kg"),
    F("M_max", "maxMassKg", unit="kg"),
    F("M_fuel_max", "maxFuelMassKg", unit="kg"),
)
AERODYNAMICS: tuple[F, ...] = (
    F("Cy0", "cy0"),
    F("Czbe", "czbe"),
    F("Mzalfa", "mzalfa"),
    F("Mzalfadt", "mzalfadt"),
    F("kjx", "kjx"),
    F("kjz", "kjz"),
    F("cx_gear", "cxGear"),
    F("cx_flap", "cxFlap"),
    F("cy_flap", "cyFlap"),
    F("cx_brk", "cxBrake"),
)
# ``table_data`` columns by row length (the install scripts' legend).
AERO_ROW: dict[int, tuple[str, ...]] = {
    8: ("mach", "cx0", "cya", "b", "b4", "rollRateMaxRadS", "aoaMaxDeg", "cyMax")
}
ENGINE: tuple[F, ...] = (
    F("type", "type", kind="string"),
    F("typeng", "engineKind"),
    F("Nmg", "idleRpm"),
    F("MinRUD", "throttleMin"),
    F("MaxRUD", "throttleMax"),
    F("MaksRUD", "throttleMilitary"),
    F("ForsRUD", "throttleAfterburner"),
    F("hMaxEng", "altitudeMaxKm", unit="km"),
    F("dcx_eng", "cxEngine"),
    F("cemax", "fuelConsumptionMilitary"),
    F("cefor", "fuelConsumptionAfterburner"),
    F("dpdh_m", "thrustAltitudeCoeffMilitary"),
    F("dpdh_f", "thrustAltitudeCoeffAfterburner"),
)
ENGINE_ROW: dict[int, tuple[str, ...]] = {
    3: ("mach", "thrustMilitary", "thrustAfterburner"),
    2: ("mach", "thrustMilitary"),
}
TABLE = F("table_data", "table", kind="rows")
HELICOPTER: tuple[F, ...] = (
    F("rotor_height", "rotorHeight"),
    F("rotor_pos", "rotorPosition", kind="numbers"),
    F("rotor_RPM", "rotorRpm"),
    F("rotor_MOI", "rotorMomentOfInertia"),
    F("blade_area", "bladeArea"),
    F("fuselage_area", "fuselageArea"),
    F("tail_fin_area", "tailFinArea"),
    F("tail_stab_area", "tailStabilizerArea"),
    F("tail_rotor_RPM", "tailRotorRpm"),
    F("thrust_correction", "thrustCorrection"),
    F("V_max", "speedMaxKmh", unit="km/h"),
    F("V_max_cruise", "cruiseSpeedMaxKmh", unit="km/h"),
)
HELICOPTER_ENGINE: tuple[F, ...] = (
    F("power_max", "powerMax"),
    F("power_take_off", "powerTakeOff"),
    F("power_WEP", "powerWep"),
    F("power_RPM_min", "powerRpmMin"),
    F("power_RPM_k", "powerRpmCoeffs", kind="numbers"),
    F("power_TH_k", "powerAltitudeCoeffs", kind="rows"),
    F("SFC_k", "fuelConsumptionCoeffs", kind="numbers"),
    F("Nmg_Ready", "idleRpmReady"),
)
# Blocks and their specs (the coverage check maps fields back to DCS keys):
# (record field, DCS key path from the unit record, specs).
BLOCKS: tuple[tuple[str, tuple[str, ...], tuple[F, ...]], ...] = (
    ("aerodynamics", ("SFM_Data", "aerodynamics"), AERODYNAMICS),
    ("engine", ("SFM_Data", "engine"), ENGINE),
    ("helicopter", (), HELICOPTER),
    ("helicopter.engine", ("engine_data",), HELICOPTER_ENGINE),
)


def _rows(raw: Any, columns: dict[int, tuple[str, ...]]) -> list[dict[str, Any]] | None:
    """``table_data`` as named rows when every row has one legend length."""
    if not fits(TABLE.kind, raw):
        return None
    lengths = {len(r) for r in raw}
    names = columns.get(lengths.pop()) if len(lengths) == 1 else None
    if names is None:
        return None
    return [dict(zip(names, row, strict=True)) for row in raw]


def _block(
    raw: Any,
    specs: Iterable[F],
    path: str,
    columns: dict[int, tuple[str, ...]] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    out = typed_block(raw, specs)
    if columns is not None and (rows := _rows(raw.get(TABLE.key), columns)):
        out["table"] = rows
    return {"sourcePath": path, **out} if out else None


def _sub(rec: dict[str, Any], keys: tuple[str, ...]) -> Any:
    value: Any = rec
    for k in keys:
        value = value.get(k) if isinstance(value, dict) else None
    return value


def flight(
    aircraft: str, rec: dict[str, Any], record_path: str
) -> dict[str, Any] | None:
    """``Entity.AircraftFlight`` of the unit record ``rec`` read from
    ``record_path`` (``_G/db/Units/...``); None when nothing is typed."""
    base = f"{record_path}#"
    sfm = ("SFM_Data",)
    out: dict[str, Any] = typed_block(rec, MASSES)
    aero = _block(
        _sub(rec, (*sfm, "aerodynamics")),
        AERODYNAMICS,
        base + pointer(*sfm, "aerodynamics"),
        AERO_ROW,
    )
    engine = _block(
        _sub(rec, (*sfm, "engine")),
        ENGINE,
        base + pointer(*sfm, "engine"),
        ENGINE_ROW,
    )
    heli = typed_block(rec, HELICOPTER)
    heli_engine = _block(
        rec.get("engine_data"), HELICOPTER_ENGINE, base + pointer("engine_data")
    )
    if heli_engine is not None:
        heli["engine"] = heli_engine
    if aero is not None:
        out["aerodynamics"] = aero
    if engine is not None:
        out["engine"] = engine
    if heli:
        out["helicopter"] = {"sourcePath": base, **heli}
    if not out:
        return None
    return {"aircraft": aircraft, "sourcePaths": [record_path], **out}


def build(
    units: dict[str, dict[str, Any]], paths: dict[str, str]
) -> dict[str, dict[str, Any]]:
    """The ``aircraft_flight`` series of the aircraft unit records ``units``
    (by type) read from ``paths``."""
    out = {
        uid: record
        for uid, rec in sorted(units.items())
        if uid in paths and (record := flight(uid, rec, paths[uid])) is not None
    }
    counts = {
        b: sum(1 for r in out.values() if b in r)
        for b in ("aerodynamics", "engine", "helicopter")
    }
    print(f"Aircraft flight records: {len(out)}; blocks: {counts}")
    return out
