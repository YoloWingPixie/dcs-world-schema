"""Unit property blocks (model, life, detection, mobility, armour, crew, cargo,
facilities, aircraft performance) from ``db/Units`` records."""

from __future__ import annotations

from typing import Any

import pytest

from tools.datamine import unit_properties as props
from tools.datamine.extract_units import (
    RawUnits,
    _gun,
    _stations,
    build_aircraft,
    build_surface,
    check_gun_mixes,
)

T72: dict[str, Any] = {
    "type": "T-72B",
    "visual": {"shape": "t-72", "shape_dstr": "T-72_p_1"},
    "shape_table_data": [
        {
            "file": "t-72",
            "classname": "lLandVehicle",
            "positioning": "BYNORMAL",
            "life": 6,
            "desrt": "T-72_desrt",
        },
        {"file": "T-72_p_1", "name": "T-72_p_1"},
    ],
    "mapclasskey": "P0091000001",
    "chassis": {
        "life": 25,
        "length": 11.917,
        "width": 3.584,
        "mass": 40000,
        "max_road_velocity": 16.6667,
        "max_slope": 0.61,
        "max_vert_obstacle": 0.5,
        "min_turn_radius": 3,
        "fordingDepth": 1.2,
        "engine_power": 840,
        "armour_thickness": 0.1,
    },
    "MaxSpeed": 60.00012,
    "mobile": True,
    "Crew": 3,
    "crew_members": ["gunner", "loader"],
    "DetectionRange": 0,
    "ThreatRange": 4000,
    "airWeaponDist": 3500,
    "IR_emission_coeff": 0.1,
    "sensor": {
        "max_range_finding_target": 5000,
        "min_range_finding_target": 0,
        "max_alt_finding_target": 5000,
        "min_alt_finding_target": 0,
        "height": 2.723,
        "laser": False,
    },
    "armour_scheme": {"hull_azimuth": [[0, 10, 2.9], [10, 30, 1]]},
    "canTow": ["Saddle22"],
    "InternalCargo": {"nominalCapacity": 700, "maximalCapacity": 700},
    "Transportable": {"valide": True, "size": 100},
}

CARRIER: dict[str, Any] = {
    "type": "CVN",
    "visual": {"shape": "Nimitz", "shape_dstr": ""},
    "life": 7300,
    "Length": 332.9,
    "Width": 96,
    "Height": 57.8,
    "mass": 72916000,
    "MaxSpeed": 55.55988,
    "max_velocity": 15.4333,
    "R_min": 665.8,
    "draft": 13,
    "RCS": 2000000,
    "airFindDist": 50000,
    "chassis": {"armour_thickness": 0.005},
    "TACAN": True,
    "ICLS": True,
    "OLS": {"Type": 0, "MeatBallArg": 151, "GlideslopeBasicAngle": 3.5},
    "numParking": 4,
    "Plane_Num_": 72,
    "Helicopter_Num_": 6,
    "DeckLevel": 20.1494,
    "RunWays": {
        "1": [[-45, 20.1, -10.5], 350.9, 240, 25, 0, 2.5, 2.8, 3, 3, 3.2, 3.5],
        "RunwaysNumber": 1,
    },
}

F16: dict[str, Any] = {
    "type": "F-16C_50",
    "Shape": "f-16",
    "mapclasskey": "P0091000024",
    "RCS": 5,
    "IR_emission_coeff": 0.8,
    "detection_range_max": 70,
    "H_max": 15240,
    "Mach_max": 2,
    "V_max_sea_level": 403,
    "V_max_h": 588.9,
    "V_opt": 220,
    "range": 3200,
    "engines_count": 1,
    "Tasks": {
        "1": {"OldID": "CAP", "Name": "CAP", "WorldID": 11},
        "3": {"OldID": "CAS", "Name": "CAS", "WorldID": 31},
    },
    "DefaultTask": {"OldID": "CAP", "Name": "CAP", "WorldID": 11},
    "is_tanker": False,
    "tanker_type": 1,
    "air_refuel_receptacle_pos": [7.8, 0.4, 0],
    "passivCounterm": {
        "CMDS_Edit": True,
        "SingleChargeTotal": 120,
        "chaff": {"chargeSz": 1, "default": 60, "increment": 30},
        "flare": {"chargeSz": 1, "default": 60, "increment": 30},
    },
    "chaff_flare_dispenser": [{"dir": [0, -1, 0], "pos": [-4.3, -0.6, -0.5]}],
    "country_of_origin": "USA",
}


def test_model_and_life() -> None:
    assert props.model(T72) == {
        "shape": "t-72",
        "shapeDestroyed": "T-72_p_1",
        "file": "t-72",
        "className": "lLandVehicle",
        "positioning": "BYNORMAL",
        "mapClassKey": "P0091000001",
    }
    assert props.life(T72) == [
        {"source": "chassis.life", "value": 25},
        {"source": "shape_table_data[1].life", "value": 6},
    ]
    # An empty visual.shape_dstr is no model: the next source is used.
    structure = {
        "ShapeName": "hangar",
        "ShapeNameDestr": "",
        "shape_table_data": [{"desrt": "ruin"}],
    }
    assert props.model(structure) == {"shape": "hangar", "shapeDestroyed": "ruin"}
    assert props.model({"type": "bare"}) is None
    assert props.life({"Life": 250}) == [{"source": "Life", "value": 250}]


def test_vehicle_blocks() -> None:
    assert props.vehicle_mobility(T72, "T-72B") == {
        "mobile": True,
        "maxSpeedKmh": 60.00012,
        "maxRoadSpeedMs": 16.6667,
        "maxSlopeRad": 0.61,
        "maxVertObstacleM": 0.5,
        "minTurnRadiusM": 3,
        "fordingDepthM": 1.2,
        "enginePower": 840,
    }
    assert props.vehicle_dimensions(T72) == {
        "lengthM": 11.917,
        "widthM": 3.584,
        "massKg": 40000,
    }
    assert props.surface_crew(T72) == {"count": 3, "members": ["gunner", "loader"]}
    assert props.detection(T72, "T-72B") == {
        "detectionRangeM": 0,
        "threatRangeM": 4000,
        "airWeaponDistM": 3500,
        "irEmissionCoeff": 0.1,
        "sensor": {
            "minRangeM": 0,
            "maxRangeM": 5000,
            "minAltM": 0,
            "maxAltM": 5000,
            "heightM": 2.723,
            "laser": False,
        },
    }
    assert props.armour(T72, "T-72B") == {
        "thickness": 0.1,
        "scheme": {"hullAzimuth": [[0, 10, 2.9], [10, 30, 1]]},
    }
    assert props.cargo(T72, "T-72B") == {
        "nominalCapacity": 700,
        "maximalCapacity": 700,
        "transportable": {"valid": True, "size": 100},
        "canTow": ["Saddle22"],
    }


def test_ship_blocks() -> None:
    assert props.ship_mobility(CARRIER, "CVN") == {
        "maxSpeedKmh": 55.55988,
        "maxSpeedMs": 15.4333,
        "minTurnRadiusM": 665.8,
        "draftM": 13,
    }
    assert props.ship_dimensions(CARRIER) == {
        "lengthM": 332.9,
        "widthM": 96,
        "heightM": 57.8,
        "massKg": 72916000,
    }
    assert props.facilities(CARRIER, "CVN") == {
        "tacan": True,
        "icls": True,
        "ols": {"type": 0, "meatBallArg": 151, "glideslopeBasicAngleDeg": 3.5},
        "numParking": 4,
        "planeNum": 72,
        "helicopterNum": 6,
        "runways": [
            {
                "start": [-45, 20.1, -10.5],
                "azimuthDeg": 350.9,
                "lengthM": 240,
                "widthM": 25,
                "alsArgument": 0,
                "glidePath": {
                    "low": 2.5,
                    "slightlyLow": 2.8,
                    "onLower": 3,
                    "onUpper": 3,
                    "slightlyHigh": 3.2,
                    "high": 3.5,
                },
            }
        ],
        "deckLevelM": 20.1494,
    }


@pytest.mark.parametrize(
    "rec",
    [
        {"draft": 7, "Draft": 9.6},
        {"armour_scheme": {"hull_side": [[0, 90, 1]]}},
        {"RunWays": {"1": [[0, 0, 0], 350, 240]}},
        {"TACAN": 1},
        {"OLS": {"MeatBallArg": 1}},
    ],
)
def test_unreadable_fields_fail(rec: dict[str, Any]) -> None:
    with pytest.raises(SystemExit):
        props.ship_mobility(rec, "X")
        props.armour(rec, "X")
        props.facilities(rec, "X")


def test_draft_spellings_merge() -> None:
    assert props.ship_mobility({"Draft": 9.6}, "X") == {"draftM": 9.6}
    assert props.ship_mobility({"draft": 9.6, "Draft": 9.6}, "X") == {"draftM": 9.6}


def test_aircraft_blocks(capsys: pytest.CaptureFixture[str]) -> None:
    assert props.detection(F16, "F-16C_50") == {
        "detectionRangeMax": 70,
        "irEmissionCoeff": 0.8,
        "rcsM2": 5,
    }
    assert props.performance(F16) == {
        "hMaxM": 15240,
        "machMax": 2,
        "vMaxSeaLevelMs": 403,
        "vMaxHMs": 588.9,
        "vOptMs": 220,
        "rangeKm": 3200,
        "enginesCount": 1,
    }
    assert props.tasks(F16, "F-16C_50") == {
        "tasks": [{"id": 11, "name": "CAP"}, {"id": 31, "name": "CAS"}],
        "defaultTask": {"id": 11, "name": "CAP"},
    }
    assert props.tasks({"Tasks": {}}, "X") == {"tasks": []}
    assert props.refuelling(F16, "F-16C_50") == {
        "isTanker": False,
        "tankerType": 1,
        "receptaclePosition": [7.8, 0.4, 0],
    }
    assert props.refuelling({"is_tanker": 2}, "X") == {"isTanker": 2}
    assert props.countermeasures(F16, "F-16C_50") == {
        "cmdsEdit": True,
        "singleChargeTotal": 120,
        "chaff": {"chargeSize": 1, "default": 60, "increment": 30},
        "flare": {"chargeSize": 1, "default": 60, "increment": 30},
        "dispensers": [{"position": [-4.3, -0.6, -0.5], "direction": [0, -1, 0]}],
    }
    assert (
        props.countermeasures({"chaff_flare_dispenser": {"CMDS_Edit": True}}, "X")
        is None
    )
    assert "chaff_flare_dispenser entries without dir/pos" in capsys.readouterr().err
    assert props.country_of_origin({"country_of_orgin": "USA"}, "X") == "USA"
    with pytest.raises(SystemExit):
        props.country_of_origin(
            {"country_of_origin": "USA", "country_of_orgin": "RUS"}, "X"
        )


def test_builders_attach_blocks() -> None:
    raw = RawUnits(
        by_category={
            "Planes": {"F-16C_50": F16},
            "Cars": {"T-72B": T72},
            "Ships": {"CVN": CARRIER},
            "Personnel": {"P": {"type": "P", "ShapeName": "soldier", "Life": 1}},
            "Heliports": {"FARP": {"type": "FARP", "numParking": 4}},
        }
    )
    aircraft = build_aircraft(raw, set(), {}, {}, set())["F-16C_50"]
    assert {"model", "detection", "performance", "tasks", "defaultTask"} <= set(
        aircraft
    )
    assert aircraft["countryOfOrigin"] == "USA"
    surface = build_surface(raw)
    assert set(surface["ground_vehicles"]["T-72B"]) == {
        "id",
        "displayName",
        "attributes",
        "model",
        "life",
        "dimensions",
        "mobility",
        "crew",
        "detection",
        "armour",
        "cargo",
    }
    assert "facilities" in surface["ships"]["CVN"]
    assert surface["personnel"]["P"]["model"] == {"shape": "soldier"}
    assert surface["structures"]["FARP"]["facilities"] == {"numParking": 4}


def test_stations_keep_every_pylon_with_rules() -> None:
    rec = {
        "type": "B",
        "Pylons": [
            {
                "Number": 2,
                "Type": 2,
                "DisplayName": "BAY",
                "Order": 1,
                "connector": "disable",
                "Launchers": [
                    {"CLSID": "b", "forbidden": [{"station": 1}]},
                    {"CLSID": "a", "required": {}},
                    {"CLSID": "b", "forbidden": [{"station": 1, "loadout": ["x"]}]},
                    {"CLSID": ""},
                ],
            },
            {
                "Number": 1,
                "Type": 0,
                "Launchers": [
                    {"CLSID": "x", "required": [{"station": 2, "loadout": [""]}]}
                ],
            },
        ],
    }
    assert _stations(rec, {"a"}, "B") == [
        {
            "station": 1,
            "type": 0,
            "wet": False,
            "accepts": [
                {
                    "clsid": "x",
                    "required": [{"station": 2, "clsids": [], "allowEmpty": True}],
                }
            ],
        },
        {
            "station": 2,
            "type": 2,
            "displayName": "BAY",
            "order": 1,
            "wet": True,
            "accepts": [
                {"clsid": "a"},
                {
                    "clsid": "b",
                    "forbidden": [
                        {"station": 1, "anyStore": True},
                        {"station": 1, "clsids": ["x"]},
                    ],
                },
            ],
        },
    ]
    either = {"CLSID": "a", "required": [{"station": 2, "loadout": ["y", ""]}]}
    assert _stations({"Pylons": [{"Number": 1, "Launchers": [either]}]}, set(), "X")[0][
        "accepts"
    ] == [
        {
            "clsid": "a",
            "required": [{"station": 2, "clsids": ["y"], "allowEmpty": True}],
        }
    ]
    for bad in (
        {"CLSID": "a", "required": [{"station": 2}]},
        {"CLSID": "a", "forbidden": [{"station": 2, "loadout": [""]}]},
    ):
        with pytest.raises(SystemExit):
            _stations({"Pylons": [{"Number": 1, "Launchers": [bad]}]}, set(), "X")


def test_obsolete_launchers_are_split_out() -> None:
    launchers = [
        {"CLSID": "old", "obsolete": True},
        {"CLSID": "both", "obsolete": True},
        {"CLSID": "both"},
        {"CLSID": "new", "obsolete": False},
    ]
    (station,) = _stations(
        {"Pylons": [{"Number": 1, "Launchers": launchers}]}, set(), "X"
    )
    assert station["accepts"] == [{"clsid": "both"}, {"clsid": "new"}]
    assert station["obsoleteAccepts"] == [{"clsid": "old"}]
    (station,) = _stations(
        {"Pylons": [{"Number": 1, "Launchers": [{"CLSID": "new"}]}]}, set(), "X"
    )
    assert "obsoleteAccepts" not in station
    bad = {"CLSID": "a", "obsolete": 1}
    with pytest.raises(SystemExit):
        _stations({"Pylons": [{"Number": 1, "Launchers": [bad]}]}, set(), "X")


def test_mission_options() -> None:
    rec = {
        "AddPropAircraft": [
            {"id": "h", "control": "label", "label": "HEAD", "xLbl": 150},
            {
                "id": "HMD",
                "control": "comboList",
                "label": "Helmet",
                "defValue": 1,
                "wCtrl": 150,
                "arg": 509,
                "playerOnly": True,
                "values": [
                    {"id": 0, "dispName": "None", "value": 0.5},
                    {"dispName": "Livery Default"},
                ],
            },
            {"id": "W", "control": "checkbox", "defValue": True, "weightWhenOn": 2.5},
        ]
    }
    assert props.mission_options(rec, "AddPropAircraft", "X") == [
        {"id": "h", "control": "label", "label": "HEAD"},
        {
            "id": "HMD",
            "control": "comboList",
            "label": "Helmet",
            "default": 1,
            "arg": 509,
            "playerOnly": True,
            "values": [
                {"id": 0, "label": "None", "value": 0.5},
                {"label": "Livery Default"},
            ],
        },
        {"id": "W", "control": "checkbox", "default": True, "weightWhenOnKg": 2.5},
    ]
    assert props.mission_options({}, "AddPropVehicle", "X") is None
    with pytest.raises(SystemExit):
        props.mission_options(
            {"AddPropVehicle": [{"id": "a", "control": "x", "onChange": 1}]},
            "AddPropVehicle",
            "X",
        )


def test_aircraft_operations_and_equipment() -> None:
    rec = {
        "type": "A",
        "V_take_off": 62,
        "V_land": 68,
        "CAS_min": 58,
        "Ny_max": 5.9,
        "bank_angle_max": 60,
        "average_fuel_consumption": 0.302,
        "TakeOffRWCategories": [{"Name": "AircraftCarrier With Catapult"}],
        "LandRWCategories": {},
        "bigParkingRamp": True,
        "laserEquipment": {"laserDesignator": True},
        "EPLRS": True,
        "date_of_introduction": 1943.5,
        "Failures": [{"id": "asc", "label": "ASC", "enable": False, "prob": 100}],
        "Countermeasures": {"ECM": "AN/ALQ-161", "IRCM": ["A", "B"]},
    }
    assert props.performance(rec) == {
        "vTakeOffMs": 62,
        "vLandMs": 68,
        "casMin": 58,
        "nyMax": 5.9,
        "bankAngleMaxDeg": 60,
        "averageFuelConsumptionKgS": 0.302,
    }
    assert props.operations(rec, "A") == {
        "takeOffRunwayCategories": ["AircraftCarrier With Catapult"],
        "landRunwayCategories": [],
        "bigParkingRamp": True,
        "laserDesignator": True,
        "eplrs": True,
        "dateOfIntroduction": 1943.5,
    }
    assert props.failures(rec, "A") == [{"id": "asc", "label": "ASC"}]
    assert props.failures({"Failures": {}}, "A") == []
    assert props.countermeasures(rec, "A") == {
        "ecm": ["AN/ALQ-161"],
        "ircm": ["A", "B"],
    }
    with pytest.raises(SystemExit):
        props.countermeasures({"Countermeasures": {"RWR": "x"}}, "A")


def test_gun_mixes() -> None:
    supply = {
        "count": 510,
        "shells": [{"name": "HE"}, {"name": "AP"}],
        "mixes": [[1], [1, 2, 2]],
    }
    gun = {"short_name": "M_61", "supply": supply}
    rec = {
        "type": "F",
        "Guns": [gun, {**gun, "supply": {**supply, "mixes": [[2], [2, 1]]}}],
        "ammo_type": ["HEI", "CM"],
        "ammo_type_default": 2,
    }
    problems: list[str] = []
    mount = {"ammo": ["HE", "AP"], "rounds": 510, "type": "M_61"}
    assert _gun(rec, problems) == {
        "ammo": ["AP", "HE"],
        "rounds": 1020,
        "type": "M_61",
        "mixes": [{"label": "HEI"}, {"label": "CM"}],
        "defaultMix": 2,
        "mounts": [
            {**mount, "mixes": [{"ammo": ["HE"]}, {"ammo": ["HE", "AP", "AP"]}]},
            {**mount, "mixes": [{"ammo": ["AP"]}, {"ammo": ["AP", "HE"]}]},
        ],
    }
    assert problems == []
    bad = {"type": "F", "Guns": [{**gun, "supply": {**supply, "mixes": [[3], [1]]}}]}
    assert "mixes" not in (_gun(bad, problems) or {})["mounts"][0]
    assert problems == ["Guns[1]: supply.mixes entry [3] names no shell"]
    problems.clear()
    _gun({**rec, "ammo_type": ["A"]}, problems)
    assert problems == [
        "Guns[1]: 2 supply.mixes for 1 ammo_type labels",
        "Guns[2]: 2 supply.mixes for 1 ammo_type labels",
    ]
    dual = {
        "count1": 240,
        "count2": 220,
        "shell1": {"name": "HE"},
        "shell2": {"name": "AP"},
    }
    assert _gun(
        {"type": "K", "Guns": [{"short_name": "2A42", "supply": dual}]}, []
    ) == {
        "ammo": ["AP", "HE"],
        "rounds": 460,
        "type": "2A42",
        "mounts": [{"ammo": ["HE", "AP"], "rounds": 460, "type": "2A42"}],
    }
    with pytest.raises(SystemExit):
        _gun({"type": "N", "Guns": [{"supply": {"shells": [{"name": "HE"}]}}]}, [])


def test_check_gun_mixes() -> None:
    raw = RawUnits(
        by_category={"Planes": {"A": {}, "B": {}}, "Cars": {"T": {}}},
        gun_problems={"A": ["x"], "T": ["y"]},
    )
    check_gun_mixes(raw, {"A": "why"})
    with pytest.raises(SystemExit):
        check_gun_mixes(raw, {})
    with pytest.raises(SystemExit):
        check_gun_mixes(raw, {"A": "why", "B": "stale"})
