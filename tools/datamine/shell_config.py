"""Typed fields of a DCS gun shell, set directly on its ``Entity.GunAmmo``.

Read from ``_G/weapons_table/weapons/shells/<name>`` (the default reading of
``lua_reader``): the ballistic, geometry and terminal-effect keys of the flat
shell record and its ``rebound_*`` blocks, copied exactly (never rounded or
converted; ``cx`` in DCS order). ``round_mass``, ``type_name`` and
``display_name`` are read by ``build_gun_ammo`` itself. Other keys are only
in the ``_G`` dump.
"""

from __future__ import annotations

from typing import Any

from .typed_fields import F, typed_block

SHELL: tuple[F, ...] = (
    F("v0", "v0Ms", unit="m/s"),
    F("Dv0", "dv0"),
    F("Da0", "da0"),
    F("cx", "cx", "numbers"),
    F("life_time", "lifeTime"),
    F("silent_self_destruction", "silentSelfDestruction", "boolean"),
    F("caliber", "caliberMm", unit="mm"),
    F("AP_cap_caliber", "apCapCaliber"),
    F("subcalibre", "subcalibre", "boolean"),
    F("cartridge_mass", "cartridgeMass"),
    F("projectile", "projectile", "string"),
    F("mass", "projectileMassKg", unit="kg"),
    F("explosive", "explosiveKg", unit="kg"),
    F("piercing_mass", "piercingMass"),
    F("cumulative_mass", "cumulativeMass"),
    F("payload", "payload"),
    F("payloadEffect", "payloadEffect", "string"),
    F("payloadMaterial", "payloadMaterial", "string"),
    F("smoke_tail_life_time", "smokeTailLifeTime"),
)
REBOUND: tuple[F, ...] = (
    F("angle0", "angle0Deg", unit="deg"),
    F("angle100", "angle100Deg", unit="deg"),
    F("cx_factor", "cxFactor"),
    F("deviation_angle", "deviationAngleDeg", unit="deg"),
    F("velocity_loss_factor", "velocityLossFactor"),
)
# rebound_<surface> -> field.
REBOUNDS = {
    "rebound_concrete": "reboundConcrete",
    "rebound_ground": "reboundGround",
    "rebound_object": "reboundObject",
    "rebound_water": "reboundWater",
}


def shell_fields(raw: dict[str, Any]) -> dict[str, Any]:
    """The typed ``Entity.GunAmmo`` fields of the shell record ``raw``."""
    out = typed_block(raw, SHELL)
    for key, name in REBOUNDS.items():
        if isinstance(block := raw.get(key), dict) and (
            typed := typed_block(block, REBOUND)
        ):
            out[name] = typed
    return out
