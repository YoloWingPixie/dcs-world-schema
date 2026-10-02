"""Weapon ``category`` sources: own wsType, exact launchers, ``_G/bombs`` table."""

from pathlib import Path
from typing import Any

import pytest
from conftest import write

from tools.datamine.dcs_constants import Constants
from tools.datamine.extract_stores import (
    build_weapons_and_warheads,
    categories_from_bombs_table,
    categories_from_launchers,
    collect_projectiles,
)
from tools.datamine.lua_reader import LuaReader


def _constants() -> Constants:
    return Constants(
        {
            "wsType": {
                "wsType_Weapon": 4,
                "wsType_Missile": 4,
                "wsType_Bomb": 5,
                "wsType_NURS": 7,
            }
        }
    )


def _bomb(g: Path, name: str, extra: str = "") -> None:
    write(
        g / f"bombs/{name}.lua",
        f'_G["bombs"]["#Index"] = {{ name = "{name}", M = 100{extra} }}',
    )


def _categorise(g: Path, launchers: list[Any]) -> tuple[dict[str, Any], list[str]]:
    constants = _constants()
    index = collect_projectiles(LuaReader(g), g)
    weapons, _ = build_weapons_and_warheads(index, constants)
    categories_from_launchers(weapons, launchers, constants)
    return weapons, categories_from_bombs_table(weapons, index, constants)


def test_bombs_table_member_without_wstype_is_a_bomb(tmp_path: Path) -> None:
    g = tmp_path / "_G"
    _bomb(g, "MK_82", ", ws_type = { 4, 5, 9, 31 }")
    _bomb(g, "GBU_11")
    write(g / "rockets/R.lua", '_G["rockets"]["#Index"] = { name = "R", M = 1 }')
    weapons, left = _categorise(g, [])
    assert weapons["GBU_11"]["category"] == 5
    assert weapons["GBU_11"]["categoryName"] == "wsType_Bomb"
    assert weapons["GBU_11"]["_source"] == {"category": "table"}
    assert "_source" not in weapons["MK_82"]  # its own ws_type
    assert left == ["R"]  # outside _G/bombs: untouched


def test_non_bomb_wstype_in_bombs_table_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    g = tmp_path / "_G"
    _bomb(g, "GBU_11")
    _bomb(g, "ODD", ", ws_type = { 4, 7, 33, 1 }")
    with pytest.raises(SystemExit):
        _categorise(g, [])
    assert "ODD" in capsys.readouterr().err


def test_bombs_table_fails_even_when_nothing_needs_it(tmp_path: Path) -> None:
    g = tmp_path / "_G"
    _bomb(g, "ODD", ", wsTypeOfWeapon = { 4, 4, 7, 1 }")
    with pytest.raises(SystemExit):
        _categorise(g, [])


def test_bombs_table_is_lowest_precedence(tmp_path: Path) -> None:
    g = tmp_path / "_G"
    _bomb(g, "MK_82", ", ws_type = { 4, 5, 9, 31 }")
    _bomb(g, "OWN")
    _bomb(g, "VIA_LAUNCHER")
    # A higher-precedence dir defines OWN with its own wsType.
    write(
        g / "weapons_table/weapons/missiles/OWN.lua",
        '_G["weapons_table"]["weapons"]["missiles"]["OWN"] = '
        '{ name = "OWN", M = 5, ws_type = { 4, 4, 7, 1 } }',
    )
    launchers = [
        (Path("l.lua"), {"CLSID": "L", "wsTypeOfWeapon": [4, 7, 33, "VIA_LAUNCHER"]})
    ]
    weapons, left = _categorise(g, launchers)
    assert (weapons["OWN"]["categoryName"], "_source" in weapons["OWN"]) == (
        "wsType_Missile",
        False,
    )
    assert weapons["VIA_LAUNCHER"]["categoryName"] == "wsType_NURS"
    assert weapons["VIA_LAUNCHER"]["_source"] == {
        "category": "launcher",
        "subcategory": "launcher",
    }
    assert weapons["VIA_LAUNCHER"]["subcategory"] == 33
    assert left == []
