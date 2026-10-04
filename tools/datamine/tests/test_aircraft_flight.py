"""The aircraft flight model (aircraft_flight, Entity.AircraftFlight) and the
aircraft fields merged from the unit record (aircraft_config).

The fixtures are excerpts of this repo's own _G dump (DCS 2.9, dump format 3):
fixtures/object_config/_G/db/Units/Planes/Plane/Su-27.lua and
.../Helicopters/Helicopter/Mi-8MT.lua keep a subset of the records' top-level
keys (Damage, Failures, Guns, Pylons, Tasks, lights, crew... cut); the kept
keys are verbatim, no value is hand-edited. The redacted and list-valued
`Sensors` cases use inline records.
"""

from pathlib import Path
from typing import Any

import fastjsonschema
import pytest
from conftest import entity_schema, unresolved_paths

from tools.datamine import aircraft_flight
from tools.datamine.aircraft_config import merge, sensor_roles
from tools.datamine.extract_units import RawUnits, build_aircraft, load_units
from tools.datamine.lua_reader import LuaReader

G = Path(__file__).parent / "fixtures" / "object_config" / "_G"
SU27 = "_G/db/Units/Planes/Plane/Su-27"
MI8 = "_G/db/Units/Helicopters/Helicopter/Mi-8MT"

SU27_AERO: list[list[float]] = [
    [0, 0.0165, 0.077, 0.1, 0.032, 0.65, 25, 1.6],
    [0.2, 0.0165, 0.077, 0.1, 0.032, 1.95, 25, 1.6],
    [0.4, 0.0165, 0.077, 0.1, 0.032, 3.25, 25, 1.6],
    [0.6, 0.0165, 0.08, 0.094, 0.043, 4.55, 24, 1.5],
    [0.7, 0.017, 0.083, 0.094, 0.045, 4.55, 23, 1.45],
    [0.8, 0.0178, 0.087, 0.094, 0.048, 4.55, 21, 1.4],
    [0.9, 0.0215, 0.091, 0.11, 0.05, 4.55, 20, 1.3],
    [1, 0.031, 0.094, 0.15, 0.1, 4.55, 18, 1.2],
    [1.1, 0.0422, 0.094, 0.15, 0.1, 4.1, 16, 1.1],
    [1.2, 0.044, 0.091, 0.14, 0.1, 3.19, 17, 1.05],
    [1.3, 0.0432, 0.085, 0.17, 0.096, 2.28, 15, 1],
    [1.5, 0.0423, 0.068, 0.23, 0.09, 1.95, 13, 0.9],
    [1.8, 0.0416, 0.051, 0.23, 0.38, 1.17, 12, 0.7],
    [2, 0.0416, 0.043, 0.08, 2.5, 1.04, 10.5, 0.55],
    [2.2, 0.0416, 0.037, 0.16, 3.2, 0.91, 9, 0.4],
    [2.5, 0.041, 0.036, 0.25, 4.5, 0.91, 9, 0.4],
    [3.9, 0.0395, 0.033, 0.35, 6, 0.8, 9, 0.4],
]
SU27_ENGINE: list[list[float]] = [
    [0, 126000, 185024],
    [0.2, 126000, 198744],
    [0.4, 126000, 208250],
    [0.6, 126000, 220892],
    [0.7, 124000, 226870],
    [0.8, 124000, 232887],
    [0.9, 122000, 250210],
    [1, 117000, 256120],
    [1.1, 113000, 265400],
    [1.2, 110000, 280300],
    [1.3, 102000, 298900],
    [1.5, 85000, 326000],
    [1.8, 30000, 350000],
    [2, 19000, 363000],
    [2.2, 17000, 384000],
    [2.5, 12000, 415000],
    [3.9, 10000, 260476],
]


AERO_COLUMNS = aircraft_flight.AERO_ROW[8]
ENGINE_COLUMNS = aircraft_flight.ENGINE_ROW[3]


def _raw() -> RawUnits:
    return load_units(LuaReader(G, dump_format=3), G)


@pytest.fixture(scope="module")
def aircraft() -> dict[str, dict[str, Any]]:
    return build_aircraft(_raw(), set(), {}, {}, set())


@pytest.fixture(scope="module")
def flight() -> dict[str, dict[str, Any]]:
    raw = _raw()
    return aircraft_flight.build(raw.category("Planes", "Helicopters"), raw.paths)


def _keys(value: Any) -> set[str]:
    """Every dict key of ``value``, at any depth."""
    if isinstance(value, dict):
        return set(value).union(*map(_keys, value.values()))
    if isinstance(value, list):
        return set().union(*map(_keys, value))
    return set()


def test_su27_flight_model(flight: dict[str, dict[str, Any]]) -> None:
    rec = flight["Su-27"]
    assert rec["aircraft"] == "Su-27" and rec["sourcePaths"] == [SU27]
    assert (rec["emptyMassKg"], rec["nominalMassKg"]) == (17250, 20000)
    assert (rec["maxMassKg"], rec["maxFuelMassKg"]) == (28000, 9400)
    aero = rec["aerodynamics"]
    assert aero["sourcePath"] == f"{SU27}#/SFM_Data/aerodynamics"
    assert aero["table"] == [dict(zip(AERO_COLUMNS, r, strict=True)) for r in SU27_AERO]
    assert aero["cy0"] == 0  # zero stays zero
    assert aero["cxGear"] == 0.0268
    engine = rec["engine"]
    assert engine["table"] == [
        dict(zip(ENGINE_COLUMNS, r, strict=True)) for r in SU27_ENGINE
    ]
    assert engine["type"] == "TurboJet"
    assert engine["altitudeMaxKm"] == 19.5
    assert engine["thrustAltitudeCoeffMilitary"] == 8000
    assert engine["thrustAltitudeCoeffAfterburner"] == 17000
    assert "helicopter" not in rec


def test_mi8_helicopter(flight: dict[str, dict[str, Any]]) -> None:
    rec = flight["Mi-8MT"]
    assert "aerodynamics" not in rec
    assert "table" not in rec["engine"]
    heli = rec["helicopter"]
    assert heli["sourcePath"] == f"{MI8}#"
    assert (heli["rotorRpm"], heli["speedMaxKmh"], heli["thrustCorrection"]) == (
        -192,
        250,
        0.8,
    )
    engine = heli["engine"]
    assert engine["sourcePath"] == f"{MI8}#/engine_data"
    assert engine["powerAltitudeCoeffs"] == [
        [0, -230.8, 2245.6],
        [0, -230.8, 2245.6],
        [0, -325.4, 2628.9],
        [0, -235.6, 1931.9],
    ]
    assert engine["fuelConsumptionCoeffs"] == [2.045e-07, -0.0006328, 0.803]


def test_su27_merged_fields(aircraft: dict[str, dict[str, Any]]) -> None:
    su27 = aircraft["Su-27"]
    assert "configuration" not in su27
    assert "nominalMassKg" not in su27["aero"]  # aircraft_flight
    assert su27["dimensions"]["wingAreaM2"] == 62
    assert su27["dimensions"]["mainGearPosition"] == [-0.537, -2.237, 2.168]
    assert su27["detection"]["irEmissionCoeffAfterburner"] == 5
    assert su27["sensorRoles"] == [
        {"role": "IRST", "sensor": "OLS-27"},
        {"role": "RADAR", "sensor": "N-001"},
        {"role": "RWR", "sensor": "Abstract RWR"},
    ]


def test_mi8_absent_and_zero(aircraft: dict[str, dict[str, Any]]) -> None:
    mi8 = aircraft["Mi-8MT"]
    assert "irEmissionCoeffAfterburner" not in mi8.get("detection", {})
    assert "sensorRoles" not in mi8


def test_only_field_names(flight: dict[str, dict[str, Any]]) -> None:
    for uid in ("Su-27", "Mi-8MT"):
        keys = _keys(flight[uid])
        # DCS keys never leak: every key is a camelCase field name.
        assert all(k[0].islower() and "_" not in k for k in keys), uid


def test_paths_resolve(flight: dict[str, dict[str, Any]]) -> None:
    for uid in ("Su-27", "Mi-8MT"):
        assert unresolved_paths(flight[uid], G) == []


def test_schema(
    aircraft: dict[str, dict[str, Any]], flight: dict[str, dict[str, Any]]
) -> None:
    schema = entity_schema()
    validate = fastjsonschema.compile(
        {**schema, "$ref": "#/definitions/Entity.Aircraft"}
    )
    check_flight = fastjsonschema.compile(
        {**schema, "$ref": "#/definitions/Entity.AircraftFlight"}
    )
    for uid in ("Su-27", "Mi-8MT"):
        validate({**aircraft[uid], "operators": []})  # joined later by extract
        check_flight(flight[uid])


def test_sensor_roles() -> None:
    rec = {"Sensors": {"RADAR": "Redacted", "OPTIC": ["A", "B"]}}
    assert sensor_roles(rec) == [
        {"role": "OPTIC", "sensor": "A"},
        {"role": "OPTIC", "sensor": "B"},
        {"role": "RADAR"},
    ]


def test_merge_keeps_existing_block_fields() -> None:
    record: dict[str, Any] = {"dimensions": {"lengthM": 10}}
    merge(record, {"wing_area": 20, "connectDatalinks": ["Link16"], "M_nominal": "x"})
    assert record == {
        "dimensions": {"lengthM": 10, "wingAreaM2": 20},
        "connectDatalinks": ["Link16"],
    }


def test_undecoded_tables_dropped() -> None:
    rows = [[0, 1, 2, 3, 4, 5, 6, 7], [1, 1, 2, 3, 4, 5, 6, 7, 8]]
    rec = {
        "SFM_Data": {
            "aerodynamics": {"table_data": rows, "Cy0": 0.1},
            "engine": {"table_data": [[0, 1, 2, 3]]},
        }
    }
    out = aircraft_flight.flight("x", rec, "_G/x")
    assert out is not None
    # Rows of irregular or undocumented length are not copied; an engine
    # block left without a typed field is absent.
    assert out["aerodynamics"] == {
        "sourcePath": "_G/x#/SFM_Data/aerodynamics",
        "cy0": 0.1,
    }
    assert "engine" not in out


def test_no_flight_without_typed_keys() -> None:
    rec = {"SFM_Data": {"extra": 1}, "EmptyWeight": "17250", "type": "x"}
    assert aircraft_flight.flight("x", rec, "_G/x") is None
