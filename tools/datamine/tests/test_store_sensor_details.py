"""Weapon cluster/arming, store guns/sensors/kind, sensor search fields, ship
facilities, model extras and country lists."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from conftest import NO_IDS, write
from test_extract import _constants

from tools.datamine import unit_properties as props
from tools.datamine.extract_countries import (
    build_countries,
    build_operators,
    load_countries,
)
from tools.datamine.extract_sensors import build_sensors, sensor_keys
from tools.datamine.extract_stores import (
    ProjectileIndex,
    add_weapon_details,
    build_stores_and_racks,
    build_weapons_and_warheads,
    collect_projectiles,
)
from tools.datamine.lua_reader import LuaReader

KEYS = {
    "HEMISPHERE_UPPER": 0,
    "HEMISPHERE_LOWER": 1,
    "ASPECT_HEAD_ON": 0,
    "ASPECT_TAIL_ON": 1,
    "ENGINE_MODE_FORSAGE": 0,
    "ENGINE_MODE_MAXIMAL": 1,
    "ENGINE_MODE_MINIMAL": 2,
}

CLUSTER_BOMB = """_G["bombs"]["#Index"] = {
    name = "CBU", M = 400,
    client = {
        arming_delay = { enabled = true, delay_time = 0.8 },
        arming_vane = { enabled = false, velK = 1 },
        launcher = { cluster = {
            name = "BLU", display_name = "BLU-X",
            client = {
                bomblets = { count = 202, mass = 1.5, model_name = "blu" },
                elem1 = { count = 3 },
                warhead = { mass = 1.5, expl_mass = 0.3, cumulative_factor = 1 },
            },
        } },
    },
}"""


def _weapons(
    tmp_path: Path, text: str
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    g = tmp_path / "_G"
    write(g / "bombs/CBU.lua", text)
    index = collect_projectiles(LuaReader(g), g)
    weapons, warheads = build_weapons_and_warheads(index, _constants())
    effective = add_weapon_details(weapons, warheads, index)
    return weapons, warheads, effective


def test_cluster_gives_submunition_warhead_and_arming(tmp_path: Path) -> None:
    weapons, warheads, effective = _weapons(tmp_path, CLUSTER_BOMB)
    cbu = weapons["CBU"]
    assert cbu["cluster"] == {
        "submunition": "BLU",
        "displayName": "BLU-X",
        "count": 202,
        "elements": [
            {"name": "bomblets", "count": 202, "model": "blu", "massKg": 1.5},
            {"name": "elem1", "count": 3},
        ],
        "warhead": "CBU.cluster",
    }
    assert (cbu["warhead"], cbu["_source"]["warhead"]) == ("CBU.cluster", "cluster")
    assert warheads["CBU.cluster"]["type"] == "shaped-charge"
    assert effective == ["CBU"]
    assert cbu["arming"] == {
        "delay": {"enabled": True, "timeS": 0.8},
        "vane": {"enabled": False, "velK": 1},
    }


def test_own_warhead_is_kept(tmp_path: Path) -> None:
    text = CLUSTER_BOMB.replace("M = 400,", "M = 400, warhead = { mass = 10 },")
    weapons, _, effective = _weapons(tmp_path, text)
    assert weapons["CBU"]["warhead"] == "CBU" and effective == []


def test_bad_arming_fails(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        _weapons(tmp_path, CLUSTER_BOMB.replace("enabled = true", "enabled = 1"))


def _stores(raws: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
    stores, _, _ = build_stores_and_racks(
        [(Path(f"{r['CLSID']}.lua"), r) for r in raws],
        ProjectileIndex(),
        _constants(),
        NO_IDS,
        **kw,
    )
    return stores


def test_count_zero_weapon_store_is_a_rack() -> None:
    stores = _stores(
        [
            {"CLSID": "ter", "attribute": [4, 5, 32, "Redacted"], "Count": 0},
            {"CLSID": "one", "attribute": [4, 5, 32, "Redacted"], "Count": 1},
        ]
    )
    assert (stores["ter"]["kind"], stores["one"]["kind"]) == ("rack", "single")


def test_gunpod_mounts_come_from_aircraft_gunpods() -> None:
    mount = {
        "display_name": "M134",
        "gun": {"rates": [4000, 2000]},
        "supply": {"count": 3200, "shells": [{"name": "S1"}]},
        "effective_fire_distance": 1500,
    }
    stores = _stores(
        [{"CLSID": "M134_L", "attribute": [4, 15, 46, "Redacted"], "Picture": "m.png"}],
        gunpods={"M134_L": {"mounts": [mount]}},
    )
    store = stores["M134_L"]
    assert store["gunAmmo"] == ["S1"]
    assert store["guns"] == [
        {
            "displayName": "M134",
            "rates": [4000, 2000],
            "rounds": 3200,
            "gunAmmo": ["S1"],
            "effectiveFireDistance": 1500,
        }
    ]
    assert store["_source"] == {
        "guns": "aircraft_gunpods",
        "gunAmmo": "aircraft_gunpods",
    }
    assert store["picture"] == "m.png"


def test_store_sensors_from_launcher_else_pod() -> None:
    stores = _stores(
        [
            {"CLSID": "a", "category": 6, "displayName": "Pod A",
             "Sensors": {"OPTIC": ["S1", "S2"]}},
            {"CLSID": "b", "category": 6, "displayName": "Pod A"},
        ],
        pod_sensors={"Pod A": ["S1", "S2"]},
    )  # fmt: skip
    assert stores["a"]["sensors"] == ["S1", "S2"] and "_source" not in stores["a"]
    assert (stores["b"]["sensors"], stores["b"]["_source"]) == (
        ["S1", "S2"],
        {"sensors": "pods"},
    )
    with pytest.raises(SystemExit):
        _stores(
            [{"CLSID": "c", "displayName": "P", "Sensors": {"OPTIC": "S3"}}],
            pod_sensors={"P": ["S1"]},
        )


def test_sensor_keys_read_from_install(tmp_path: Path) -> None:
    text = "\n".join(f"local {k} = {v}" for k, v in KEYS.items())
    write(tmp_path / "CoreMods/aircraft/AJS37/Entry/Sensors.lua", text)
    assert sensor_keys(tmp_path) == KEYS
    write(
        tmp_path / "CoreMods/aircraft/F-4E/Entry/Sensors.lua",
        "local HEMISPHERE_UPPER = 1",
    )
    with pytest.raises(SystemExit):
        sensor_keys(tmp_path)


def test_sensor_search_fields_and_irst_range(tmp_path: Path) -> None:
    g = tmp_path / "_G"
    write(
        g / "db/Sensors/Sensor/R.lua",
        """_G["db"]["Sensors"]["Sensor"]["#Index"] = {
            Name = "R", category = 1, type = 2, max_measuring_distance = 100000,
            scan_volume = { azimuth = { -60, 60 }, elevation = { -30, 30 } },
            detection_distance = { [0] = { [0] = 4, [1] = 3 }, [1] = { [0] = 2, [1] = 1 } },
            air_search = { TWS_max_targets = 4, lock_on_distance_coeff = 0.85 },
        }""",
    )
    write(
        g / "db/Sensors/Sensor/I.lua",
        """_G["db"]["Sensors"]["Sensor"]["#Index"] = {
            Name = "I", category = 2,
            detection_distance_for_tail_on_Su_27 = { [0] = 35000, [1] = 15000, [2] = 8000 },
        }""",
    )
    sensors, _ = build_sensors(
        LuaReader(g), g, _constants(), KEYS, {"Pod": ["R"], "Gap": ["X"]}
    )
    r, i = sensors["R"], sensors["I"]
    assert r["detectionDistance"] == {
        "upperHeadOnM": 4,
        "upperTailOnM": 3,
        "lowerHeadOnM": 2,
        "lowerTailOnM": 1,
    }
    assert r["scanVolume"] == {"azimuthDeg": [-60, 60], "elevationDeg": [-30, 30]}
    assert r["airSearch"] == {"twsMaxTargets": 4, "lockOnDistanceCoeff": 0.85}
    assert r["pods"] == ["Pod"]
    assert (i["detectionRangeKm"], i["detectionRangeField"]) == (
        35.0,
        "detection_distance_for_tail_on_Su_27",
    )
    assert i["irstDetectionDistance"] == {
        "afterburnerM": 35000,
        "maximalM": 15000,
        "minimalM": 8000,
    }


CARRIER: dict[str, Any] = {
    "TACAN_position": [-55, 55, 29],
    "ICLS_Localizer_position": [-153, 12, 9.4, 189],
    "Landing_Point": [-104, 19.6, -33],
    "ArrestingGears": {
        "1": {"Left": {"connector_name": "L1"}, "Right": {"connector_name": "R1"}},
        "ArrestingGearsNumber": 1,
    },
    "TaxiRoutes": {"1": [[[13, 20, -19], 5], [[10, 20, 5], 3, 180]], "RoutesNumber": 1},
    "HelicopterSpawnTerminal": {
        "1": {"Points": [[[147, 20, -0.18], 0]], "TerminalIdx": 1},
        "TerminalNumber": 1,
    },
}


def test_ship_facilities() -> None:
    f = props.facilities(CARRIER, "CVN")
    assert f is not None
    assert f["tacanPosition"] == [-55, 55, 29]
    assert f["iclsLocalizerPosition"] == [-153, 12, 9.4, 189]
    assert f["arrestingGears"] == [{"leftConnector": "L1", "rightConnector": "R1"}]
    assert f["taxiRoutes"] == [
        {
            "points": [
                {"position": [13, 20, -19], "values": [5]},
                {"position": [10, 20, 5], "values": [3, 180]},
            ]
        }
    ]
    assert f["helicopterSpawnTerminals"] == [
        {"terminal": 1, "points": [{"position": [147, 20, -0.18], "values": [0]}]}
    ]
    bad = {**CARRIER, "TaxiRoutes": {**CARRIER["TaxiRoutes"], "RoutesNumber": 2}}
    with pytest.raises(SystemExit):
        props.facilities(bad, "CVN")


def test_model_extras() -> None:
    model = props.model(
        {
            "Shape": "x",
            "encyclopediaAnimation": {
                "args": {"0": 0.25, "1": 0.4},
                "children": [{"connector": "P1", "model": "m", "args": [1, 0.5]}],
            },
            "Damage": {"3": {"args": [65], "critical_damage": 10}, "64": {}},
            "CanopyGeometry": [0.5, 0.5],
        },
        "X",
    )
    assert model is not None
    assert model["encyclopediaAnimation"] == {
        "args": [{"arg": 0, "value": 0.25}, {"arg": 1, "value": 0.4}],
        "children": [
            {
                "connector": "P1",
                "model": "m",
                "args": [{"arg": 1, "value": 1}, {"arg": 2, "value": 0.5}],
            }
        ],
    }
    assert model["damageArgs"] == [{"cell": 3, "args": [65]}]
    assert model["canopyGeometry"] == [0.5, 0.5]


def test_country_lists() -> None:
    raw: dict[str, Any] = {
        "WorldID": 2,
        "Name": "USA",
        "Awards": [
            {"countryID": 2, "name": "A", "nativeName": "A", "picture": "a.png",
             "threshold": 200},
        ],
        "Ranks": [],
        "Troops": [{"name": "T", "nativeName": "T", "picture": "t.png"}],
    }  # fmt: skip
    country = build_countries([raw], _constants())["USA"]
    assert country["awards"] == [
        {"name": "A", "nativeName": "A", "picture": "a.png", "threshold": 200}
    ]
    assert "ranks" not in country
    assert country["troops"] == [{"name": "T", "nativeName": "T", "picture": "t.png"}]
    raw["Awards"][0]["countryID"] = 3
    with pytest.raises(SystemExit):
        build_countries([raw], _constants())


def test_unit_operators_from_country_files(tmp_path: Path) -> None:
    def country(world: int, name: str, units: str) -> str:
        return (
            f'_G["db"]["Countries"]["#Index"] = {{ WorldID = {world}, Name = "{name}",'
            f' OldID = "{name}", Units = {{ {units} }} }}'
        )

    planes = 'Planes = { Plane = { { Name = "F-16C_50" }, { Name = "MiG-29S" } } }'
    write(tmp_path / "db/Countries/USA.lua", country(2, "USA", planes))
    write(
        tmp_path / "db/Countries/Russia.lua",
        country(0, "Russia", 'Planes = { Plane = { { Name = "MiG-29S" } } },'
                ' Cars = { Car = { { Name = "T-72B" } } }'),
    )  # fmt: skip
    write(
        tmp_path / "__years__.lua",
        '_G["__years__"] = { ["MiG-29S"] = { Russia = { from = 1983, to = 9999 },'
        " USA = { from = 0, to = 0 } } }",
    )
    reader = LuaReader(tmp_path)
    raw = load_countries(reader, tmp_path)
    operators = build_operators(reader, tmp_path, raw, _constants())
    assert operators == {
        "F-16C_50": [{"country": 2, "countryName": "USA"}],
        "MiG-29S": [
            {"country": 0, "years": {"from": 1983, "to": 9999}},
            {"country": 2, "countryName": "USA"},
        ],
        "T-72B": [{"country": 0}],
    }
    write(
        tmp_path / "db/Countries/Bad.lua",
        '_G["db"]["Countries"]["#Index"] = { Name = "X" }',
    )
    with pytest.raises(SystemExit):
        load_countries(LuaReader(tmp_path), tmp_path)
