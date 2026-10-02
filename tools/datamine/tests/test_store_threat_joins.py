"""Store deliveries (nested payloads, resource names, loaders, gun pods, raw
wsType ids)."""

from pathlib import Path
from typing import Any

import pytest
from conftest import NO_IDS, write
from test_extract import _constants

from tools.datamine.extract_stores import (
    ProjectileIndex,
    StoreStats,
    build_stores_and_racks,
    collect_projectiles,
)
from tools.datamine.lua_reader import LuaReader
from tools.datamine.rwr import WsTypeIds


def _index(tmp_path: Path) -> ProjectileIndex:
    g = tmp_path / "_G"
    for name in ("A", "B"):
        write(
            g / f"weapons_table/weapons/missiles/{name}.lua",
            f'_G["weapons_table"]["weapons"]["missiles"]["{name}"] = '
            f'{{ name = "{name}", M = 1, model = "{name.lower()}", '
            f'_unique_resource_name = "weapons.missiles.{name}" }}',
        )
    # No _unique_resource_name: its weapons_table path is the resource name.
    write(
        g / "weapons_table/weapons/bombs/C.lua",
        '_G["weapons_table"]["weapons"]["bombs"]["C"] = { name = "C", M = 1 }',
    )
    return collect_projectiles(LuaReader(g), g)


def _stores(
    tmp_path: Path, launchers: list[dict[str, Any]]
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], StoreStats]:
    return build_stores_and_racks(
        [(Path(f"{i}.lua"), r) for i, r in enumerate(launchers)],
        _index(tmp_path),
        _constants(),
        NO_IDS,
    )


def test_resource_names_join_exactly(tmp_path: Path) -> None:
    stores, _, stats = _stores(
        tmp_path,
        [
            {"CLSID": "ws", "category": 4, "Count": 2,
             "wsTypeOfWeapon": "weapons.missiles.A", "Elements": [{"ShapeName": "b"}]},
            {"CLSID": "attr", "category": 4, "attribute": "weapons.missiles.B",
             "Elements": [{"ShapeName": "x"}]},
            {"CLSID": "path", "category": 1, "wsTypeOfWeapon": "weapons.bombs.C",
             "Elements": [{"ShapeName": "x"}]},
            {"CLSID": "gone", "category": 4, "wsTypeOfWeapon": "weapons.missiles.Z",
             "Elements": [{"ShapeName": "a"}]},
        ],
    )  # fmt: skip
    assert stores["ws"]["delivers"] == [{"weapon": "A", "count": 2}]
    assert stores["attr"]["delivers"] == [{"weapon": "B", "count": 1}]
    assert stores["path"]["delivers"] == [{"weapon": "C", "count": 1}]
    assert stores["gone"]["delivers"] == []
    assert stats.unknown_weapon == {"weapons.missiles.Z": 1}


def test_nested_payloads_sum_and_loaders_name_leaves(tmp_path: Path) -> None:
    stores, _, stats = _stores(
        tmp_path,
        [
            # Pod of 7 A; a rack of two pods and a mixed rack.
            {"CLSID": "pod", "category": 3, "Count": 7,
             "wsTypeOfWeapon": "weapons.missiles.A", "Elements": [{"ShapeName": "a"}]},
            {"CLSID": "rack", "category": 3, "Count": 2,
             "wsTypeOfWeapon": "weapons.missiles.B",  # nested wins over the name
             "Elements": [{"IsAdapter": True, "ShapeName": "ter"},
                          {"payload_CLSID": "pod"}, {"payload_CLSID": "pod"}]},
            {"CLSID": "mixed", "category": 4, "Count": 2,
             "wsTypeOfWeapon": "weapons.missiles.A",
             "Elements": [{"payload_CLSID": "leaf"}, {"payload_CLSID": "leaf2"}]},
            # Leaves without a name: `leaf` shape-matches B but its sole
            # loader names A; `leaf2` is loaded only by the mixed rack.
            {"CLSID": "leaf", "category": 4, "wsTypeOfWeapon": [4, 4, 7, "Redacted"],
             "Elements": [{"ShapeName": "b"}]},
            {"CLSID": "solo", "category": 4, "wsTypeOfWeapon": "weapons.missiles.A",
             "Elements": [{"payload_CLSID": "leaf"}]},
            {"CLSID": "leaf2", "category": 4, "Elements": [{"ShapeName": "x"}]},
        ],
    )  # fmt: skip
    assert stores["rack"]["delivers"] == [{"weapon": "A", "count": 14}]
    assert stores["leaf"]["delivers"] == [{"weapon": "A", "count": 1}]
    assert stores["leaf2"]["delivers"] == []
    assert stores["mixed"]["delivers"] == [{"weapon": "A", "count": 1}]
    assert stats.loader_overrides == {"leaf": (["B"], "A")}
    assert stats.basis["nested"] == 3


def test_loaders_naming_different_weapons_leave_the_shape_match(
    tmp_path: Path,
) -> None:
    stores, _, stats = _stores(
        tmp_path,
        [
            {"CLSID": "leaf", "category": 4, "Elements": [{"ShapeName": "b"}]},
            {"CLSID": "p1", "category": 4, "wsTypeOfWeapon": "weapons.missiles.A",
             "Elements": [{"payload_CLSID": "leaf"}]},
            {"CLSID": "p2", "category": 4, "wsTypeOfWeapon": "weapons.missiles.B",
             "Elements": [{"payload_CLSID": "leaf"}]},
        ],
    )  # fmt: skip
    assert stores["leaf"]["delivers"] == [{"weapon": "B", "count": 1}]
    assert stats.loader_conflicts == {"leaf": ["A", "B"]}


def test_gun_pod_ammo_from_gun_mounts(tmp_path: Path) -> None:
    mounts = [{"supply": {"shells": [{"name": "S_T"}, {"name": "S"}]}}]
    stores, _, stats = _stores(
        tmp_path,
        [
            {"CLSID": "gun", "category": 6, "gun_mounts": mounts,
             "Elements": [{"ShapeName": "x"}]},
            {"CLSID": "on_rack", "category": 6,
             "Elements": [{"IsAdapter": True, "ShapeName": "ad"},
                          {"payload_CLSID": "gun"}]},
            {"CLSID": "ecm", "category": 6, "Elements": [{"ShapeName": "x"}]},
        ],
    )  # fmt: skip
    assert stores["gun"]["gunAmmo"] == ["S", "S_T"]
    assert stores["on_rack"]["gunAmmo"] == ["S", "S_T"]
    assert "gunAmmo" not in stores["ecm"]
    assert stats.no_delivers == {"pod": 1}


@pytest.mark.parametrize(
    "launchers",
    [
        [{"CLSID": "a", "Elements": [{"payload_CLSID": "b"}]},
         {"CLSID": "b", "Elements": [{"payload_CLSID": "a"}]}],
        [{"CLSID": "a", "Elements": [{"payload_CLSID": "nope"}]}],
        [{"CLSID": "a", "Elements": [{"payload_CLSID": "b"}, {"ShapeName": "a"}]},
         {"CLSID": "b"}],
    ],
)  # fmt: skip
def test_bad_payload_references_fail(
    tmp_path: Path, launchers: list[dict[str, Any]]
) -> None:
    with pytest.raises(SystemExit):
        _stores(tmp_path, launchers)


def test_weapons_table_resource_name_mismatch_fails(tmp_path: Path) -> None:
    g = tmp_path / "_G"
    write(
        g / "weapons_table/weapons/missiles/A.lua",
        '_G["weapons_table"]["weapons"]["missiles"]["A"] = '
        '{ name = "A", M = 1, _unique_resource_name = "weapons.missiles.Other" }',
    )
    with pytest.raises(SystemExit):
        collect_projectiles(LuaReader(g), g)


def test_raw_attribute_ids_join_exactly(tmp_path: Path) -> None:
    ids = WsTypeIds(
        units={},
        stores={"one": [(4, 4, 7, 1)], "two": [(4, 4, 7, 2)], "none": [(4, 4, 7, 9)]},
        projectiles={"A": [(4, 4, 7, 1)], "B": [(4, 4, 7, 2)], "C": [(4, 4, 7, 2)]},
        ammunition={},
    )
    redacted = [4, 4, 7, "Redacted"]
    stores, _, stats = build_stores_and_racks(
        [
            (Path(f"{c}.lua"), {"CLSID": c, "attribute": redacted, "Elements": [{}]})
            for c in ("one", "two", "none")
        ],
        _index(tmp_path),
        _constants(),
        ids,
    )
    assert stores["one"]["delivers"] == [{"weapon": "A", "count": 1}]
    assert stores["two"]["delivers"] == []  # B and C share the tuple
    assert stats.ids_ambiguous == {"two": ["B", "C"]}
    assert stores["none"]["delivers"] == []
