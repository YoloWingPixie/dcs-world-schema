"""Weapon subcategory, seeker and range fields (extract_stores)."""

from pathlib import Path
from typing import Any

import pytest
from conftest import write

from tools.datamine.dcs_constants import Constants
from tools.datamine.extract_stores import (
    build_weapons_and_warheads,
    categories_from_launchers,
    collect_projectiles,
    launch_table_max,
    name_seeker_types,
)
from tools.datamine.lua_reader import LuaReader
from tools.datamine.overlays import Overlays


def _constants() -> Constants:
    return Constants(
        {
            "wsType": {
                "wsType_Weapon": 4,
                "wsType_Missile": 4,
                "wsType_Bomb": 5,
                "wsType_NURS": 7,
                "wsType_AA_Missile": 7,
                "wsType_Bomb_Guided": 36,
                "wsType_Rocket": 33,
                "wsType_Container": 32,
            }
        }
    )


def _missile(g: Path, name: str, body: str) -> None:
    write(
        g / f"weapons_table/weapons/missiles/{name}.lua",
        f'_G["weapons_table"]["weapons"]["missiles"]["{name}"] = '
        f'{{ name = "{name}", mass = 100, ws_type = {{ 4, 4, 7, 1 }}, client = {{ {body} }} }}',
    )


def _rocket(g: Path, name: str, body: str, resource: str | None = None) -> None:
    res = f'_unique_resource_name = "{resource or f"weapons.missiles.{name}"}", '
    write(
        g / f"rockets/{name}.lua",
        f'_G["rockets"]["#Index"] = {{ name = "{name}", M = 100, {res}{body} }}',
    )


def _build(g: Path, constants: Constants | None = None) -> dict[str, Any]:
    index = collect_projectiles(LuaReader(g), g)
    weapons, _ = build_weapons_and_warheads(index, constants or _constants())
    return weapons


def test_rockets_table_fills_missing_fields_and_is_stamped(tmp_path: Path) -> None:
    g = tmp_path / "_G"
    _missile(g, "OWN", "Head_Type = 2, Range_max = 61000, D_max = 16000, D_min = 700")
    _rocket(g, "OWN", "Head_Type = 2, Range_max = 61000")
    _missile(
        g, "NEW", 'scheme = "schemes/missiles/x.sch", class_name = "wAmmunitionAntiRad"'
    )
    _rocket(
        g,
        "NEW",
        "Head_Type = 3, Range_max = 134000, D_max = 151000, D_min = 3500, SeekerGen = 3",
    )
    weapons = _build(g)
    own, new = weapons["OWN"], weapons["NEW"]
    assert (own["seekerType"], own["rangeKm"], own["rangeField"]) == (
        2,
        61.0,
        "Range_max",
    )
    assert (own["rangeMinKm"], own["launchRangeMaxKm"]) == (0.7, 16.0)
    assert "_source" not in own
    assert (own["subcategory"], own["subcategoryName"]) == (7, "wsType_AA_Missile")
    assert (new["seekerType"], new["rangeKm"], new["rangeMinKm"]) == (3, 134.0, 3.5)
    assert new["seeker"] == {"generation": 3}
    assert new["className"] == "wAmmunitionAntiRad"
    assert new["scheme"] == "schemes/missiles/x.sch"
    assert new["_source"] == {
        "seekerType": "rockets",
        "rangeKm": "rockets",
        "rangeMinKm": "rockets",
        "launchRangeMaxKm": "rockets",
        "seeker": "rockets",
    }


def test_rockets_table_disagreeing_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    g = tmp_path / "_G"
    _missile(g, "M", "Head_Type = 2")
    _rocket(g, "M", "Head_Type = 6")
    with pytest.raises(SystemExit):
        _build(g)
    assert "Head_Type" in capsys.readouterr().err


def test_rockets_table_of_another_object_is_not_joined(tmp_path: Path) -> None:
    g = tmp_path / "_G"
    _missile(g, "M", "Head_Type = 2")
    _rocket(g, "M", "Head_Type = 6, Range_max = 9000", resource="weapons.missiles.N")
    write(
        g / "rockets/W.lua",
        '_G["rockets"]["#Index"] = { name = "M", M = 1, ws_type = { 4, 4, 7, 1 }, '
        "D_max = 7000 }",
    )
    m = _build(g)["M"]
    assert m["seekerType"] == 2
    assert (m["rangeKm"], m["rangeField"]) == (7.0, "D_max")
    assert m["_source"] == {"rangeKm": "rockets", "launchRangeMaxKm": "rockets"}


def test_range_precedence_and_zero_is_unset(tmp_path: Path) -> None:
    g = tmp_path / "_G"
    _rocket(g, "ZERO", "Range_max = 0, D_max = 0")
    _rocket(g, "DMAX", "Range_max = 0, D_max = 8000")
    table = "{ 2, 2, 100, 200, 1000, 0, 5000, 2000, 7000, 9000 }"
    _missile(g, "TABLE", f"LaunchDistData = {table}")
    write(
        g / "weapons_table/weapons/nurs/R.lua",
        '_G["weapons_table"]["weapons"]["nurs"]["R"] = { name = "R", mass = 10, '
        "dist_min = 500, dist_max = 4000, client = {} }",
    )
    write(
        g / "weapons_table/weapons/nurs/MLRS.lua",
        '_G["weapons_table"]["weapons"]["nurs"]["MLRS"] = { name = "MLRS", mass = 10, '
        "dist_min = 0, dist_max = 0, client = {} }",
    )
    weapons = _build(g)
    assert "rangeKm" not in weapons["ZERO"]
    assert (weapons["DMAX"]["rangeKm"], weapons["DMAX"]["rangeField"]) == (8.0, "D_max")
    assert (weapons["TABLE"]["rangeKm"], weapons["TABLE"]["rangeField"]) == (
        9.0,
        "LaunchDistData",
    )
    assert (weapons["R"]["rangeKm"], weapons["R"]["rangeMinKm"]) == (4.0, 0.5)
    assert weapons["R"]["rangeMinField"] == "dist_min"
    assert "rangeKm" not in weapons["MLRS"] and "rangeMinKm" not in weapons["MLRS"]


def test_malformed_launch_table_fails_only_when_read(tmp_path: Path) -> None:
    bad = [2, 2, 100, 200, 1000, 0, 5000]
    with pytest.raises(SystemExit):
        launch_table_max(bad, "W")
    g = tmp_path / "_G"
    _missile(g, "SHADOWED", "Range_max = 8000, LaunchDistData = { 2, 2, 100 }")
    assert _build(g)["SHADOWED"]["rangeKm"] == 8.0


def test_seeker_parameters(tmp_path: Path) -> None:
    g = tmp_path / "_G"
    _missile(
        g,
        "S",
        "SeekerCooled = true, SeekerSensivityDistance = 25000, "
        "sensor = { cooled = true, max_seeker_range = 16000 }, "
        "seeker = { max_lock_dist = 40000, max_seeker_range = 16000 }, "
        "gimbal = { az_max = 1.0471975511966, el_max = 0.5235987755983 }",
    )
    _missile(
        g, "BAD", "seeker = { max_seeker_range = 1 }, sensor = { max_seeker_range = 2 }"
    )
    with pytest.raises(SystemExit):
        _build(g)
    (g / "weapons_table/weapons/missiles/BAD.lua").unlink()
    assert _build(g)["S"]["seeker"] == {
        "cooled": True,
        "irSensitivityRangeKm": 25.0,
        "maxLockRangeKm": 40.0,
        "maxSeekerRangeKm": 16.0,
        "gimbalAzimuthMaxDeg": 60.0,
        "gimbalElevationMaxDeg": 30.0,
    }


def test_unnamed_level3_keeps_the_number(tmp_path: Path) -> None:
    g = tmp_path / "_G"
    write(
        g / "weapons_table/weapons/bombs/B.lua",
        '_G["weapons_table"]["weapons"]["bombs"]["B"] = '
        '{ name = "B", mass = 2, ws_type = { 4, 5, 32, 1 } }',
    )
    constants = _constants()
    weapons = _build(g, constants)
    assert weapons["B"]["subcategory"] == 32 and "subcategoryName" not in weapons["B"]
    assert constants.unresolved == {("wsType level 3 under wsType_Bomb", 32): 1}


def test_subcategory_from_agreeing_launchers(tmp_path: Path) -> None:
    g = tmp_path / "_G"
    write(g / "bombs/GBU.lua", '_G["bombs"]["#Index"] = { name = "GBU", M = 500 }')
    constants = _constants()
    weapons = _build(g, constants)
    launchers = [(Path("l.lua"), {"CLSID": "L", "wsTypeOfWeapon": [4, 5, 36, "GBU"]})]
    categories_from_launchers(weapons, launchers, constants)
    assert weapons["GBU"]["subcategoryName"] == "wsType_Bomb_Guided"
    assert weapons["GBU"]["_source"] == {
        "category": "launcher",
        "subcategory": "launcher",
    }


def _overlays(names: dict[int, str], gaps: dict[int, str]) -> Overlays:
    return Overlays(
        [],
        {
            ("weapons", "seekerTypes"): names,
            ("weapons", "seekerTypeUpstreamGaps"): gaps,
        },
    )


def test_seeker_type_names() -> None:
    weapons: dict[str, dict[str, Any]] = {
        "A": {"seekerType": 1},
        "T": {"seekerType": 0},
        "B": {},
    }
    name_seeker_types(weapons, _overlays({1: "InfraredSeeker"}, {0: "torpedoes"}))
    assert weapons["A"]["seekerTypeName"] == "InfraredSeeker"
    assert weapons["A"]["_source"] == {"seekerTypeName": "hand-authored"}
    assert weapons["T"] == {"seekerType": 0}


@pytest.mark.parametrize(
    ("names", "gaps"),
    [
        ({1: "InfraredSeeker"}, {}),  # 0 unnamed and not a gap
        ({1: "InfraredSeeker", 2: "ActiveRadar"}, {0: "t"}),  # 2 unused
        ({1: "InfraredSeeker"}, {0: "t", 8: "x"}),  # gap 8 unused
    ],
)
def test_seeker_type_names_fail(names: dict[int, str], gaps: dict[int, str]) -> None:
    weapons: dict[str, dict[str, Any]] = {
        "A": {"seekerType": 1},
        "T": {"seekerType": 0},
    }
    with pytest.raises(SystemExit):
        name_seeker_types(weapons, _overlays(names, gaps))
