"""Typed surface-unit fields (surface_config) added to the record blocks.

The fixtures are excerpts of this repo's own _G dump (DCS 2.9, dump format 3):
fixtures/object_config/_G/db/Units/Cars/Car/SA-11 Buk LN 9A310M1.lua (top-level
`snd`, `encyclopediaAnimation`, `animation_arguments`, `CanopyGeometry` cut) and
.../Ships/Ship/PERRY.lua (`DM`, `snd`, `encyclopediaAnimation`,
`animation_arguments`, `Categories` cut); the kept keys, `WS` included, are
verbatim, no value is hand-edited. Duplicate-type cases use inline records.
"""

from pathlib import Path
from typing import Any

import fastjsonschema
import pytest
from conftest import entity_schema, write

from tools.datamine.extract_units import RawUnits, build_surface, load_units
from tools.datamine.lua_reader import LuaReader

G = Path(__file__).parent / "fixtures" / "object_config" / "_G"
BUK = "SA-11 Buk LN 9A310M1"
Surface = dict[str, dict[str, dict[str, Any]]]


def _surface() -> Surface:
    raw = load_units(LuaReader(G, dump_format=3), G)
    return build_surface(raw, {"SA9M38M1"}, {})


@pytest.fixture(scope="module")
def surface() -> Surface:
    return _surface()


def _one(series_dir: str, rec: dict[str, Any]) -> dict[str, Any]:
    """The record ``build_surface`` makes of the single unit ``rec``."""
    raw = RawUnits()
    raw.by_category[series_dir] = {"X": {"type": "X", **rec}}
    series = {"Cars": "ground_vehicles", "Ships": "ships", "Cargos": "structures"}
    return build_surface(raw)[series[series_dir]]["X"]


def test_buk_blocks(surface: Surface) -> None:
    buk = surface["ground_vehicles"][BUK]
    assert buk["mobility"] == {
        "mobile": True,
        "maxSpeedKmh": 65.00016,
        "maxRoadSpeedMs": 18.0556,
        "maxSlopeRad": 0.27,
        "maxVertObstacleM": 1,
        "minTurnRadiusM": 2.62,
        "fordingDepthM": 1.3,
        "enginePower": 740,
        "rMaxM": 0.46,
        "maxAcceleration": 4.08497,
        "traceWidth": 0.446,
        "gearType": 2,
    }  # gear points (X_gear_1 ...) and r_track: no field
    assert buk["detection"]["sensorMountWs"] == 1
    assert buk["fireControl"] == {
        "fireOnMove": False,
        "maxTargetDetectionRangeM": 60000,
        "radarType": 103,
        "searchRadarFrequencies": [[6000000000, 10000000000]],
    }
    assert "configuration" not in buk


def test_buk_weapon_systems(surface: Surface) -> None:
    tel, *tracking = surface["ground_vehicles"][BUK]["weaponSystems"]
    # WS[1] mount keys, LN[1] keys and its sensor table join the public entry
    assert (tel["referenceAngleYRad"], tel["referenceAngleZRad"]) == (
        3.1415926535898,
        0.034906585039887,
    )
    assert tel["mountBeforeMove"] is True
    assert (tel["minLaunchAngleRad"], tel["barrelsReloadType"]) == (0.17453292519943, 3)
    assert tel["sensor"] == {
        "type": 0,
        "deviationErrorAzimuth": 0,
        "deviationErrorElevation": 0,
        "deviationErrorDistance": 0,
        "deviationErrorSpeedSensor": 0,
        "deviationErrorStability": 0,
    }  # zero stays zero
    # keys the public fields read are not repeated
    for key in ("distanceMin", "angles", "omegaY", "shellName", "identicalTo"):
        assert key not in tel
    assert tel["payloads"] == [
        {
            "weapon": "SA9M38M1",
            "ammoName": "9M38",
            "ammoCapacity": 4,
            "reloadTimeS": 780,
            "shotDelayS": 0.1,
        }
    ]
    assert [w["baseWs"] for w in tracking] == [1, 1, 1, 1]


def test_perry(surface: Surface) -> None:
    perry = surface["ships"]["PERRY"]
    mob = perry["mobility"]
    assert (mob["maxSpeedMs"], mob["speedup"], mob["distFindObstacles"]) == (
        14.9189,
        0.269786,
        462.5,
    )
    assert "gammaMax" not in mob and "om" not in mob  # meaning not stated
    assert perry["dimensions"] == {
        "lengthM": 137.5,
        "widthM": 14,
        "heightM": 31.5,
        "massKg": 4100000,
        "shipLengthM": 124.3,
        "xNoseM": 59.1924,
        "xTailM": -64.9268,
        "tailWidth": 13.5,
    }
    det = perry["detection"]
    assert (det["radar1Period"], det["radar2Period"], det["radar3Period"]) == (
        5,
        2,
        3.75,
    )
    assert perry["fireControl"]["searchRadarMaxElevationRad"] == 0.69813170079773
    systems = perry["weaponSystems"]
    assert systems[0]["payloads"][0]["switchOnDelay"] == 12
    # a mount's keys are on each of its launchers
    ws10 = [w for w in systems if w["ws"] == 10]
    assert [w["ln"] for w in ws10] == [1, 2]
    assert (
        ws10[0]["anglesMechRad"]
        == ws10[1]["anglesMechRad"]
        == [[3.1415926535898, -3.1415926535898, -0.17453292519943, 1.5707963267949]]
    )


def test_missing_zero_false() -> None:
    rec = _one(
        "Cars",
        {
            "mobile": False,
            "chassis": {"canWade": False, "gear_type": 0},
            "WS": {"1": {"moveable": False, "LN": [{"PL": [{"switch_on_delay": 0}]}]}},
        },
    )
    assert rec["mobility"] == {"mobile": False, "canWade": False, "gearType": 0}
    (ws,) = rec["weaponSystems"]
    assert ws["moveable"] is False and "sensor" not in ws
    assert ws["payloads"] == [{"switchOnDelay": 0}]
    bare = _one("Cars", {})
    assert not {"mobility", "detection", "fireControl", "weaponSystems"} & set(bare)


def test_only_typed_fields() -> None:
    # unknown keys, opaque keys and values of another kind are not copied
    rec = _one(
        "Ships",
        {
            "Om": 0.05,
            "Gamma_max": 0.35,
            "speedup": "fast",
            "Sensors": {"RADAR": "R", "Mount_WS_ID": 2},
            "sensor": {"beamWidth": 0.5},
            "WS": [
                {
                    "angles_mech": [[1, -1, 0, 1]],
                    "LN": [{"sightMasterMode": 1, "PL": [{"virtualStwID": 1}]}],
                }
            ],
        },
    )
    assert "mobility" not in rec
    assert rec["detection"] == {"sensor": {"beamWidthRad": 0.5}, "sensorMountWs": 2}
    assert rec["weaponSystems"] == [
        {"ws": 1, "ln": 1, "payloads": [{}], "anglesMechRad": [[1, -1, 0, 1]]}
    ]


def test_schema(surface: Surface) -> None:
    schema = entity_schema()
    for entity, series, uid in (
        ("GroundVehicle", "ground_vehicles", BUK),
        ("Ship", "ships", "PERRY"),
    ):
        validate = fastjsonschema.compile(
            {**schema, "$ref": f"#/definitions/Entity.{entity}"}
        )
        validate(surface[series][uid])


def test_structure_mass() -> None:
    rec = _one("Cargos", {"Life": 3, "mass": 100, "minMass": 50, "maxMass": 200})
    assert (rec["mass"], rec["minMass"], rec["maxMass"]) == (100, 50, 200)
    fastjsonschema.compile(
        {**entity_schema(), "$ref": "#/definitions/Entity.Structure"}
    )(rec)


CAR = """_G["db"]["Units"]["Cars"]["Car"]["#Index"] = {{
\ttype = "Dup", Name = "{name}", DisplayName = "{name}", MaxSpeed = {speed}
}}
"""


@pytest.mark.parametrize("second_speed", [10, 20])
def test_duplicate_types_kept_first(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], second_speed: int
) -> None:
    g = tmp_path / "_G"
    write(g / "db/Units/Cars/Car/A.lua", CAR.format(name="first", speed=10))
    write(g / "db/Units/Cars/Car/B.lua", CAR.format(name="first", speed=second_speed))
    raw = load_units(LuaReader(g, dump_format=3), g)
    assert raw.duplicates == {
        "Dup": ["_G/db/Units/Cars/Car/A", "_G/db/Units/Cars/Car/B"]
    }
    assert raw.paths["Dup"] == "_G/db/Units/Cars/Car/A"
    assert raw.by_category["Cars"]["Dup"]["MaxSpeed"] == 10  # not overwritten
    err = capsys.readouterr()
    text = err.out + err.err
    assert "duplicate unit type 'Dup'" in text
    same = "identical" if second_speed == 10 else "AMBIGUOUS (differing)"
    assert same in text
    assert build_surface(raw)["ground_vehicles"]["Dup"]["mobility"] == {
        "maxSpeedKmh": 10
    }
