"""Typed sensor and gun-shell fields set directly on Entity.Sensor
(extract_sensors) and Entity.GunAmmo (shell_config).

Fixtures (unedited copies of this repo's own _G dump, DCS 2.9, dump format 3)
under fixtures/object_config/_G:
- db/Sensors/Sensor/ANAPG-68.lua (radar with air/surface search blocks),
- db/Sensors/Sensor/OLS-27.lua (IRST),
- weapons_table/weapons/shells/M256_120_AP_L55.lua (120 mm APFSDS shell).
The untyped-key cases edit in-memory copies only.
"""

import copy
from pathlib import Path
from typing import Any

import fastjsonschema
from conftest import entity_schema
from test_extract import _constants

from tools.datamine.extract_sensors import build_sensors
from tools.datamine.lua_reader import LuaReader
from tools.datamine.shell_config import shell_fields

G = Path(__file__).parent / "fixtures" / "object_config" / "_G"
KEYS = {
    "HEMISPHERE_UPPER": 0,
    "HEMISPHERE_LOWER": 1,
    "ASPECT_HEAD_ON": 0,
    "ASPECT_TAIL_ON": 1,
    "ENGINE_MODE_FORSAGE": 0,
    "ENGINE_MODE_MAXIMAL": 1,
    "ENGINE_MODE_MINIMAL": 2,
}


def _sensors() -> dict[str, dict[str, Any]]:
    return build_sensors(LuaReader(G, dump_format=3), G, _constants(), KEYS)[0]


def _shell_raw() -> dict[str, Any]:
    path = G / "weapons_table/weapons/shells/M256_120_AP_L55.lua"
    value = LuaReader(G, dump_format=3).read_file(path)
    assert isinstance(value, dict)
    return value


def _validate(type_name: str, record: dict[str, Any]) -> None:
    schema = entity_schema()
    fastjsonschema.compile({**schema, "$ref": f"#/definitions/{type_name}"})(record)


def test_radar_fields() -> None:
    r = _sensors()["AN/APG-68"]
    assert r["scanPeriodS"] == 5
    air = r["airSearch"]
    assert air["velocityLimits"] == {
        "radialVelocityMinMs": 27.777777777778,
        "relativeRadialVelocityMinMs": 27.777777777778,
    }
    assert air["centeredScanVolume"] == {
        "azimuthSectorDeg": 30,
        "elevationSectorDeg": 30,
    }
    assert "configuration" not in r and "sensorType" not in r
    _validate("Entity.Sensor", r)


def test_irst_fields() -> None:
    i = _sensors()["OLS-27"]
    assert (i["backgroundFactor"], i["headOnDistanceCoeff"]) == (0.5, 0.333)
    assert i["laserRanger"] is True
    for absent in ("airSearch", "velocityLimits", "viewVolumeMax"):
        assert absent not in i
    _validate("Entity.Sensor", i)


def test_shell_fields_exact() -> None:
    out = shell_fields(_shell_raw())
    assert out["cx"] == [1, 1.4, 0.8, 0.172, 1.6]
    assert out["v0Ms"] == 1800
    assert (out["caliberMm"], out["apCapCaliber"], out["piercingMass"]) == (
        120,
        27,
        4.6,
    )
    # Zero stays zero, false stays false; round_mass is read by build_gun_ammo.
    assert out["explosiveKg"] == 0 and out["cartridgeMass"] == 0
    assert out["subcalibre"] is True and out["silentSelfDestruction"] is False
    for absent in ("massKg", "roundMass", "k1", "da1", "tracerOff", "projectile"):
        assert absent not in out
    assert out["reboundWater"] == {
        "angle0Deg": 65,
        "angle100Deg": 83,
        "cxFactor": 5,
        "deviationAngleDeg": 30,
        "velocityLossFactor": 0.5,
    }
    _validate("Entity.GunAmmo", {"id": "M256_120_AP_L55", **out})


def test_shell_untyped_keys_skipped() -> None:
    raw = copy.deepcopy(_shell_raw())
    raw["rebound_ground"]["extra"] = [1, 2]
    raw["caliber"] = "120 mm"  # not a number: not typed
    raw["rebound_object"] = {"extra": 1}  # no typed field: no block
    expected = shell_fields(_shell_raw())
    expected.pop("caliberMm")
    expected.pop("reboundObject")
    assert shell_fields(raw) == expected
