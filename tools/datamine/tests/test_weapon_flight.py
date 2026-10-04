"""The weapon_flight series (weapon_flight, Entity.WeaponFlight).

The fixtures are small excerpts of this repo's own _G dump (DCS 2.9, dump
format 3, numbers as the dump wrote them); the client/server difference and
the 0/false/missing cases are hand-edited where noted.
"""

from pathlib import Path
from typing import Any

import fastjsonschema
from conftest import entity_schema, write

from tools.datamine.extract_stores import (
    build_weapon_flight,
    client_server_differences,
    collect_projectiles,
)
from tools.datamine.lua_reader import LuaReader
from tools.datamine.weapon_flight import SPECS

# AIM-120C: _G/weapons_table/weapons/missiles/AIM_120C.lua (excerpt).
AIM_120C_CX0 = "0.468, 0.468, 0.468, 0.468, 0.479, 0.751, 0.88, 0.8572, 0.8132, 0.7645, 0.7205, 0.6808, 0.6447, 0.6119, 0.582, 0.5545, 0.5292, 0.5057, 0.4838, 0.4633, 0.4439, 0.4256, 0.4083, 0.3921, 0.377, 0.364"
AIM_120C_CXB = "0.021, 0.021, 0.021, 0.021, 0.021, 0.138, 0.153, 0.146, 0.1382, 0.1272, 0.1167, 0.1073, 0.0987, 0.0909, 0.0837, 0.077, 0.0708, 0.065, 0.0595, 0.0544, 0.0495, 0.0449, 0.0406, 0.0364, 0.0324, 0.0286"
AIM_120C_K1 = "0.0025, 0.0025, 0.0025, 0.0025, 0.0025, 0.0024, 0.002, 0.00172, 0.00151, 0.00135, 0.00123, 0.00114, 0.00106, 0.00099, 0.00094, 0.00088, 0.00084, 0.00079, 0.00074, 0.0007, 0.00066, 0.00062, 0.00058, 0.00055, 0.00052, 0.0005"
AIM_120C_K2 = "-0.0024, -0.0024, -0.0024, -0.0024, -0.0024, -0.0024, -0.00206, -0.00186, -0.00168, -0.0015, -0.00134, -0.00118, -0.00104, -0.0009, -0.00078, -0.00066, -0.00056, -0.00046, -0.00038, -0.0003, -0.00024, -0.00018, -0.00014, -0.0001, -8e-05, -6e-05"
AIM_120C_BLOCK = f"""
    D_max = 16000, D_min = 700, Range_max = 61000, Head_Type = 2, KillDistance = 15, Life_Time = 90,
    M = 161.48, Mach_max = 4, PN_gain = 4, X_back = -1.98, v_min = 140, t_b = 0.4,
    boost = {{ fuel_mass = 0, impulse = 0, nozzle_exit_area = 0.0132, work_time = 0.1,
               nozzle_position = {{ {{ -1.9, 0, 0 }} }}, smoke_color = {{ 0.8, 0.8, 0.8 }} }},
    march = {{ fuel_mass = 51.26, impulse = 234, nozzle_exit_area = 0.0132, work_time = 6.5,
               smoke_transparency = 0.03 }},
    controller = {{ boost_start = 0, march_start = 0.4 }},
    autopilot = {{ Knav = 4, delay = 0.2, op_time = 100, fins_limit = 0.31415926535898,
                   gload_limit = 30, loft_sin = 0.49996660034157,
                   accel_coeffs = {{ 0, 11.5, -1.2, -0.25, 24, 0.00016926 }}, Kd = 180 }},
    sensor = {{ FOV = 0.26179938779915, delay = 1.5, max_w_LOS = 0.5235987755983, op_time = 100,
                sens_far_dist = 30000, sens_near_dist = 100 }},
    gimbal = {{ op_time = 100, pitch_max = 1.0471975511966, yaw_max = 1.0471975511966 }},
    proximity_fuze = {{ arm_delay = 1.6, radius = 15 }},
    fm = {{ Cx0 = {{ {AIM_120C_CX0} }}, CxB = {{ {AIM_120C_CXB} }},
            K1 = {{ {AIM_120C_K1} }}, K2 = {{ {AIM_120C_K2} }},
            L = 0.178, S = 0.0248, caliber = 0.178, mass = 161.48, delta_max = 0.34906585039887,
            table_degree_values = 1, table_scale = 0.2, wind_sigma = 0 }},
    warhead = {{ mass = 18.7, expl_mass = 18.7, fantom = {{fantom}} }},
    exhaust = {{ 0.8, 0.8, 0.8, 0.05 }}
"""


def _numbers(text: str) -> list[float]:
    return [float(x) if "." in x or "e" in x else int(x) for x in text.split(", ")]


def _wt_missile(
    g: Path, name: str, client: str, server: str | None = None, top: str = ""
) -> None:
    write(
        g / f"weapons_table/weapons/missiles/{name}.lua",
        f'_G["weapons_table"]["weapons"]["missiles"]["{name}"] = {{ name = "{name}", mass = 100, '
        f'ws_type = {{ 4, 4, 7, "{name}" }}, {top} client = {{ {client} }}, '
        f"server = {{ {server if server is not None else client} }} }}",
    )


def _legacy(g: Path, table: str, file: str, body: str) -> None:
    write(g / f"{table}/{file}.lua", f'_G["{table}"]["#Index"] = {{ {body} }}')


def _flight(g: Path) -> dict[str, Any]:
    records = build_weapon_flight(collect_projectiles(LuaReader(g), g))
    schema = entity_schema()
    validate = fastjsonschema.compile(
        {**schema, "$ref": "#/definitions/Entity.WeaponFlight"}
    )
    for record in records.values():
        validate(record)
    return records


def _aim_120c(g: Path, server_extra: str = "") -> None:
    client = AIM_120C_BLOCK.replace("{fantom}", "1")
    server = AIM_120C_BLOCK.replace("{fantom}", "0") + server_extra
    _wt_missile(
        g, "AIM_120C", client, server, top="caliber = 0.178, Reflection = 0.07,"
    )


WT = "_G/weapons_table/weapons/missiles/AIM_120C"


def test_aim_120c_record(tmp_path: Path) -> None:
    g = tmp_path / "_G"
    _aim_120c(g, server_extra=", Life_Time = 60")
    rec = _flight(g)["AIM_120C"]
    path = WT + "#/client"
    assert (rec["weapon"], rec["sourcePaths"], rec["sourcePath"]) == (
        "AIM_120C",
        [WT],
        path,
    )
    # One record: the client block (server's Life_Time 60 is source-only).
    assert (rec["batteryLifeS"], rec["killDistanceM"]) == (90, 15)
    assert (rec["rangeMaxM"], rec["machMax"]) == (61000, 4)
    aero = rec["aerodynamics"]
    assert aero["sourcePath"] == path + "/fm"
    assert aero["cx0"] == _numbers(AIM_120C_CX0)
    assert aero["cxB"] == _numbers(AIM_120C_CXB)
    assert aero["k1"] == _numbers(AIM_120C_K1)
    assert aero["k2"] == _numbers(AIM_120C_K2)
    assert (aero["machStep"], aero["referenceArea"], aero["lengthM"]) == (
        0.2,
        0.0248,
        0.178,
    )
    assert (aero["caliberM"], aero["massKg"]) == (0.178, 161.48)
    assert aero["finDeflectionMaxRad"] == 0.34906585039887  # not rounded
    boost, march = rec["motorStages"]
    assert boost == {
        "stage": "boost",
        "sourcePath": path + "/boost",
        "impulseS": 0,  # zero kept
        "fuelMassKg": 0,
        "workTimeS": 0.1,
        "startTime": 0,
    }
    assert (march["impulseS"], march["fuelMassKg"], march["workTimeS"]) == (
        234,
        51.26,
        6.5,
    )
    assert march["startTime"] == 0.4
    assert rec["autopilot"] == {
        "sourcePath": path + "/autopilot",
        "navigationGain": 4,
        "gLoadLimit": 30,
        "finsLimitRad": 0.31415926535898,
        "operatingTime": 100,
    }
    assert rec["seeker"] == {
        "sourcePath": path + "/sensor",
        "fovRad": 0.26179938779915,
        "nearDistance": 100,
        "farDistance": 30000,
        "operatingTime": 100,
    }
    assert rec["gimbal"]["yawMaxRad"] == 1.0471975511966
    assert rec["proximityFuze"] == {
        "sourcePath": path + "/proximity_fuze",
        "radius": 15,
        "armDelay": 1.6,
    }
    # Only named fields: nothing raw.
    assert set(rec) <= {
        "weapon", "sourcePaths", "sourcePath", "batteryLifeS", "killDistanceM",
        "rangeMaxM", "machMax", "pnCoefficients", "launchTables", "aerodynamics",
        "motorStages", "autopilot", "seeker", "gimbal", "proximityFuze",
    }  # fmt: skip
    # The public fields read client and report the server difference.
    (line,) = client_server_differences(collect_projectiles(LuaReader(g), g))
    assert "AIM_120C" in line and "['Life_Time']" in line


def test_fantom_only_difference_is_not_reported(tmp_path: Path) -> None:
    g = tmp_path / "_G"
    _aim_120c(g)
    assert client_server_differences(collect_projectiles(LuaReader(g), g)) == []


# R-27ER: _G/weapons_table/weapons/missiles/P_27PE.lua (excerpt); its `ap`
# block carries `tail_control = false` and gain lists.
P_27PE_CLIENT = """
    Head_Type = 6, Life_Time = 1000000000, radar_synced = true, Nr_max = 24, t_acc = 4,
    ap = { Kav = { 0.04, 0.03, 0.03, 0.02 }, Kdv = { 0.2, 0.4, 0.4, 0.6 }, Kra = 2, Krd = 0.1,
           Ksv = { 0, 0, 0, 0 }, altitude_bands = 4, delay = 0.8, fins_limit = 0.26179938779915,
           gload_limit = 25, omega_limit = 2.0943951023932, op_time = 60, tail_control = false },
    WCSE = { energy_mod = 1 },
    boost = { fuel_mass = 57, impulse = 245, nozzle_exit_area = 0.032, work_time = 2.5 },
    march = { fuel_mass = 81.5, impulse = 236, nozzle_exit_area = 0.032, work_time = 5.5 },
    controller = { boost_start = 0.2, march_start = 2.7 },
    gimbal = { az_max = 0.95993108859688, el_max = 0.95993108859688, op_time = 60, roll_max = 2.0943951023932 },
    proximity_fuze = { arm_delay = 1.8, min_cls_vel = 150, radius = 12 },
    fm = { Ix = 3.5, Iy = 316, Iz = 316, tail_first = 1, model_roll = -0.78539816339745,
           draw_fins_conv = { 0, 1, 1 } }
"""


def test_r27er_ap_block_and_legacy_record_not_read(tmp_path: Path) -> None:
    g = tmp_path / "_G"
    _wt_missile(g, "P_27PE", P_27PE_CLIENT)
    _legacy(
        g,
        "rockets",
        "P_27PE",
        'name = "P_27PE", M = 350, _unique_resource_name = "weapons.missiles.P_27PE", '
        "Life_Time = 5, t_acc = 4, t_b = 0, Damage = 33",
    )
    rec = _flight(g)["P_27PE"]
    assert rec["sourcePaths"] == ["_G/weapons_table/weapons/missiles/P_27PE"]
    assert rec["batteryLifeS"] == 1000000000
    assert rec["autopilot"]["sourcePath"].endswith("#/client/ap")
    assert (rec["autopilot"]["gLoadLimit"], rec["autopilot"]["operatingTime"]) == (
        25,
        60,
    )
    assert (rec["aerodynamics"]["ix"], rec["aerodynamics"]["iy"]) == (3.5, 316)
    assert [s["stage"] for s in rec["motorStages"]] == ["boost", "march"]
    assert rec["motorStages"][1]["startTime"] == 2.7
    assert "seeker" not in rec
    assert rec["gimbal"] == {
        "sourcePath": rec["sourcePath"] + "/gimbal",
        "operatingTime": 60,
    }


def test_sd_10_pn_coefficients(tmp_path: Path) -> None:
    g = tmp_path / "_G"
    # SD-10: _G/weapons_table/weapons/missiles/SD-10.lua (excerpt).
    _wt_missile(
        g,
        "SD-10",
        "Life_Time = 120, PN_coeffs = { 4, 12000, 1, 18000, 0.75, 30000, 0.5, 48000, 0.2 }, "
        "march = { fuel_mass = 40, impulse = 240, work_time = 8 }",
    )
    rec = _flight(g)["SD-10"]
    assert rec["pnCoefficients"] == [
        {"distanceM": 12000, "gain": 1},
        {"distanceM": 18000, "gain": 0.75},
        {"distanceM": 30000, "gain": 0.5},
        {"distanceM": 48000, "gain": 0.2},
    ]
    (march,) = rec["motorStages"]
    assert (
        march["sourcePath"] == "_G/weapons_table/weapons/missiles/SD-10#/client/march"
    )


def test_rockets_only_missile_and_launch_table(tmp_path: Path) -> None:
    g = tmp_path / "_G"
    # AIM-9M exists only in _G/rockets (excerpt of _G/rockets/AIM_9.lua).
    _legacy(
        g,
        "rockets",
        "AIM_9",
        'name = "AIM_9", M = 85.73, _unique_resource_name = "weapons.missiles.AIM_9", '
        "Life_Time = 60, KillDistance = 8, SeekerCooled = true, "
        'ModelData = { 58, 0.35, 0.049, 0.082 }, ws_type = { 4, 4, 7, "AIM_9" }',
    )
    # AGM-86 MinLaunchDistData: _G/rockets/AGM_86.lua (excerpt).
    _legacy(
        g,
        "rockets",
        "AGM_86",
        'name = "AGM_86", M = 1450, MinLaunchDistData = { 4, 4, 100, 125, 175, 250, 500, 0, 19500, '
        "20500, 22000, 2000, 23500, 25000, 27500, 30500, 7000, 53000, 53500, 58500, 63500, 13000, "
        "93000, 93000, 102000, 105000 }, AspectDistData = { 2, 2, 1, 2, 3 }",
    )
    records = _flight(g)
    # ModelData (positions without assigned meanings) is source-only.
    assert records["AIM_9"] == {
        "weapon": "AIM_9",
        "sourcePaths": ["_G/rockets/AIM_9"],
        "sourcePath": "_G/rockets/AIM_9#",
        "batteryLifeS": 60,
        "killDistanceM": 8,
    }
    # AspectDistData has no {rows, cols, ...} layout: only in the dump.
    (table,) = records["AGM_86"]["launchTables"]
    assert table["key"] == "MinLaunchDistData"
    assert table["columnHeaders"] == [100, 125, 175, 250]
    assert table["rows"][0] == {"header": 500, "cells": [0, 19500, 20500, 22000]}
    assert table["rows"][3] == {
        "header": 13000,
        "cells": [93000, 93000, 102000, 105000],
    }


def test_bomb_reads_client_fm(tmp_path: Path) -> None:
    g = tmp_path / "_G"
    client = (
        "fm = { I = 94.425933, L = 2.21, Ma = 2.746331, caliber = 0.273, "
        "cx_coeff = { 1, 0.29, 0.71, 0.14, 1.28 }, mass = 228, release_rnd = 0.3 }"
    )
    write(
        g / "weapons_table/weapons/bombs/Mk_82.lua",
        '_G["weapons_table"]["weapons"]["bombs"]["Mk_82"] = { name = "Mk_82", mass = 228, '
        f'ws_type = {{ 4, 5, 9, "Mk_82" }}, client = {{ {client} }}, server = {{ {client} }} }}',
    )
    rec = _flight(g)["Mk_82"]
    assert rec["aerodynamics"] == {
        "sourcePath": "_G/weapons_table/weapons/bombs/Mk_82#/client/fm",
        "massKg": 228,
        "caliberM": 0.273,
        "lengthM": 2.21,
        "cxCoeff": [1, 0.29, 0.71, 0.14, 1.28],
    }


def test_torpedo_engine_is_a_motor_stage(tmp_path: Path) -> None:
    g = tmp_path / "_G"
    _legacy(
        g,
        "torpedoes",
        "Mark_46",
        'name = "Mark_46", M = 230, Life_Time = 1000, engine = { thrust = 4080 }, '
        'ws_type = { 4, 7, 11, "Mark_46" }',
    )
    _legacy(
        g,
        "torpedoes",
        "YU-6",
        'name = "YU-6", M = 1700, engine = { data_table = { 9000, 1300, 10000, 1100 }, '
        'default_thrust = 9500, rail_thrust = 3500 }, ws_type = { 4, 7, 11, "YU-6" }',
    )
    records = _flight(g)
    assert records["Mark_46"]["motorStages"] == [
        {
            "stage": "engine",
            "sourcePath": "_G/torpedoes/Mark_46#/engine",
            "thrust": 4080,
        }
    ]
    assert records["YU-6"]["motorStages"][0]["thrust"] == 9500


def test_smoke_only_march_is_not_a_stage(tmp_path: Path) -> None:
    g = tmp_path / "_G"
    _wt_missile(
        g,
        "AGM_65D",
        "Life_Time = 90, march = { smoke_color = { 0.8, 0.8, 0.8 }, smoke_transparency = 0.7 }",
    )
    assert "motorStages" not in _flight(g)["AGM_65D"]


def test_schema_fields_match_specs() -> None:
    """Every typed field of the spec tables is a field of its schema type."""
    defs = entity_schema()["definitions"]
    types = {
        "": "Entity.WeaponFlight",
        "aerodynamics": "Entity.WeaponAerodynamics",
        "motorStages": "Entity.WeaponMotorStage",
        "autopilot": "Entity.WeaponAutopilot",
        "seeker": "Entity.WeaponSeeker",
        "gimbal": "Entity.WeaponGimbal",
        "proximityFuze": "Entity.WeaponProximityFuze",
    }
    for block, specs in SPECS.items():
        props = defs[types[block]]["properties"]
        for f in specs:
            assert f.name in props, (block, f.name)
            assert f"`{f.key}`" in props[f.name]["description"], (block, f.name)
