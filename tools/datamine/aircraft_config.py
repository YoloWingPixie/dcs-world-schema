"""Aircraft fields read from selected keys of the unit record that the other
``Entity.Aircraft`` fields do not read: merged into ``aero``, ``dimensions``,
``detection`` and ``countermeasures``, plus ``sensorRoles`` and
``connectDatalinks``. Values are copied exactly (no rounding, no
conversion). The flight model is the ``aircraft_flight`` series
(``aircraft_flight``).
"""

from __future__ import annotations

from typing import Any

from .typed_fields import F, typed_block

# The sensor name DCS writes for a classified sensor; no Entity.Sensor.
REDACTED = "Redacted"

# Block field -> keys merged into it.
MERGED: dict[str, tuple[F, ...]] = {
    "aero": (
        F("M_fuel_per_tank", "fuelPerTankKg", "numbers", unit="kg"),
        F("AmmoWeight", "ammoMass"),
        F("defFuelRatio", "defaultFuelFraction", unit="1"),
    ),
    "dimensions": (
        F("wing_area", "wingAreaM2", unit="m2"),
        F("main_gear_pos", "mainGearPosition", "numbers"),
        F("nose_gear_pos", "noseGearPosition", "numbers"),
    ),
    "detection": (F("IR_emission_coeff_ab", "irEmissionCoeffAfterburner", unit="1"),),
    "countermeasures": (
        F("ChaffDefault", "chaffDefault"),
        F("ChaffChargeSize", "chaffChargeSize"),
        F("FlareDefault", "flareDefault"),
        F("FlareChargeSize", "flareChargeSize"),
    ),
}
CONNECT_DATALINKS = F("connectDatalinks", "connectDatalinks", kind="strings")


def sensor_roles(rec: dict[str, Any]) -> list[dict[str, Any]] | None:
    """One entry per sensor name of ``Sensors``, sorted by role (a list role
    keeps its order); a redacted name has no ``sensor``."""
    block = rec.get("Sensors")
    if not isinstance(block, dict):
        return None
    out: list[dict[str, Any]] = []
    for role, value in sorted(block.items()):
        names = value if isinstance(value, list) else [value]
        for name in names:
            if isinstance(name, str):
                out.append(
                    {"role": role, **({} if name == REDACTED else {"sensor": name})}
                )
    return out or None


def merge(record: dict[str, Any], rec: dict[str, Any]) -> None:
    """Add the fields of the unit record ``rec`` to the ``Entity.Aircraft``
    ``record``."""
    for name, specs in MERGED.items():
        if fields := typed_block(rec, specs):
            record[name] = {**record.get(name, {}), **fields}
    if roles := sensor_roles(rec):
        record["sensorRoles"] = roles
    if links := typed_block(rec, (CONNECT_DATALINKS,)):
        record.update(links)
