from collections import Counter
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import NO_IDS, entity_schema, write

from tools.datamine import overlays
from tools.datamine.check_refs import check_refs, rules
from tools.datamine.dcs_constants import (
    Constants,
    load_constants,
    render_country_schema,
    render_schema,
)
from tools.datamine.extract_sensors import sensor_enums, sensor_kind
from tools.datamine.extract_stores import (
    ProjectileIndex,
    build_stores_and_racks,
    build_weapons_and_warheads,
    categories_from_launchers,
    collect_projectiles,
)
from tools.datamine.lua_reader import LuaReader
from tools.datamine.validate_data import orphan_types
from tools.export_jsonschema import export, schema_for


def _constants() -> Constants:
    return Constants(
        {
            "wsType": {
                "wsType_Air": 1,
                "wsType_Weapon": 4,
                "wsType_Free_Fall": 3,
                "wsType_Missile": 4,
                "wsType_Bomb": 5,
                "wsType_Shell": 6,
                "wsType_NURS": 7,
                "wsType_Torpedo": 8,
                "wsType_Moving": 8,
                "wsType_GContainer": 15,
                "wsType_FuelTank": 43,
            },
            "CAT": {
                "CAT_BOMBS": 1,
                "CAT_MISSILES": 2,
                "CAT_ROCKETS": 3,
                "CAT_AIR_TO_AIR": 4,
                "CAT_FUEL_TANKS": 5,
                "CAT_PODS": 6,
                "CAT_TORPEDOES": 11,
            },
            "SENSOR": {
                "SENSOR_OPTICAL": 0,
                "SENSOR_RADAR": 1,
                "SENSOR_IRST": 2,
                "SENSOR_RWR": 3,
            },
            "OPTIC_SENSOR": {
                "OPTIC_SENSOR_TV": 0,
                "OPTIC_SENSOR_LLTV": 1,
                "OPTIC_SENSOR_IR": 2,
            },
            "RADAR": {"RADAR_AS": 0, "RADAR_SS": 1, "RADAR_MULTIROLE": 2},
            "MODULATION": {
                "MODULATION_AM": 0,
                "MODULATION_FM": 1,
                "MODULATION_AM_AND_FM": 2,
            },
            "country": {"USA": 2},
        }
    )


def test_dump_without_constants_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        load_constants(LuaReader(tmp_path), tmp_path)
    assert "dump predates constant capture" in capsys.readouterr().err


def test_level2_name_is_scoped_to_weapons() -> None:
    c = _constants()
    # 8 is both wsType_Torpedo and wsType_Moving; only the former is a weapon.
    assert c.name("Entity.WsTypeWeaponLevel2", 8) == "wsType_Torpedo"
    assert c.name("Entity.WsTypeWeaponLevel2", 99) is None
    assert c.unresolved == {("Entity.WsTypeWeaponLevel2", 99): 1}


def test_country_schema_is_id_and_exact_inverse() -> None:
    c = _constants()
    c.values["country"] = {"RUSSIA": 0, "ISRAEL": 15, "NEW ZEALAND": 92}
    types = yaml.safe_load(render_country_schema(c))["types"]
    assert types["country.id"]["values"] == c.values["country"]
    assert types["country.name"]["values"] == {
        0: "RUSSIA",
        15: "ISRAEL",
        92: "NEW ZEALAND",
    }


def test_render_schema_is_generated_from_constants() -> None:
    text = render_schema(_constants())
    assert "#" not in text
    assert "      wsType_Missile: 4\n" in text
    assert "wsType_Moving" not in text
    assert "      CAT_TORPEDOES: 11\n" in text
    assert text == render_schema(_constants())


def test_rocket_with_only_top_level_M_is_a_weapon(tmp_path: Path) -> None:
    g = tmp_path / "_G"
    write(
        g / "rockets/SA5B55.lua",
        '_G["rockets"]["#Index"] = { name = "SA5B55", M = 1600, D_max = 40000 }',
    )
    write(
        g / "weapons_table/weapons/missiles/X.lua",
        '_G["weapons_table"]["weapons"]["missiles"]["X"] = { name = "X", mass = 0, client = { M = 5 } }',
    )
    index = collect_projectiles(LuaReader(g), g)
    weapons, _ = build_weapons_and_warheads(index, _constants())
    assert weapons["SA5B55"]["massKg"] == 1600
    assert "category" not in weapons["SA5B55"]
    assert "category" not in weapons["X"]
    assert weapons["X"]["massKg"] == 0  # a real 0 is not treated as missing


def _same_name_bombs(g: Path, other_ws: str, third: str | None = None) -> None:
    write(
        g / "weapons_table/weapons/bombs/BDU_33.lua",
        '_G["weapons_table"]["weapons"]["bombs"]["BDU_33"] = { name = "BDU_33",'
        ' mass = 11.3, ws_type = { 4, 5, 9, "BDU_33" },'
        " client = { warhead = { caliber = 100 } } }",
    )
    write(
        g / "bombs/BDU_33.lua",
        '_G["bombs"]["BDU_33"] = { name = "BDU_33", mass = 11.3,'
        f' ws_type = {other_ws}, warhead = "_G/warheads/BDU.lua" }}',
    )
    if third is not None:
        write(g / "torpedoes/BDU_33.lua", third)
    write(
        g / "warheads/BDU.lua",
        '_G["warheads"]["BDU"] = { mass = 4.2, expl_mass = 4e-05 }',
    )


def test_warhead_ref_of_a_same_object_record(tmp_path: Path) -> None:
    g = tmp_path / "_G"
    _same_name_bombs(g, '{ 4, 5, 9, "BDU_33" }')
    weapons, warheads = build_weapons_and_warheads(
        collect_projectiles(LuaReader(g), g), _constants()
    )
    assert weapons["BDU_33"]["warhead"] == "BDU_33"
    assert weapons["BDU_33"]["_source"] == {"warhead": "bombs"}
    assert warheads["BDU_33"]["massKg"] == 4.2


def test_no_warhead_from_another_object_of_the_same_name(tmp_path: Path) -> None:
    g = tmp_path / "_G"
    _same_name_bombs(g, '{ 4, 5, 38, "BDU_33" }')
    weapons, warheads = build_weapons_and_warheads(
        collect_projectiles(LuaReader(g), g), _constants()
    )
    assert "warhead" not in weapons["BDU_33"]
    assert "BDU_33" not in warheads


def test_same_object_warheads_of_different_masses_fail(tmp_path: Path) -> None:
    g = tmp_path / "_G"
    _same_name_bombs(
        g,
        '{ 4, 5, 9, "BDU_33" }',
        '_G["torpedoes"]["BDU_33"] = { name = "BDU_33", mass = 11.3,'
        ' ws_type = { 4, 5, 9, "BDU_33" }, warhead = { mass = 5 } }',
    )
    with pytest.raises(SystemExit):
        build_weapons_and_warheads(collect_projectiles(LuaReader(g), g), _constants())


def test_hard_target_penetrator_flag(tmp_path: Path) -> None:
    g = tmp_path / "_G"
    write(
        g / "bombs/BLU_109.lua",
        '_G["bombs"]["BLU_109"] = { name = "BLU_109", mass = 874,'
        ' warhead = "_G/warheads/BLU_109.lua" }',
    )
    write(
        g / "warheads/BLU_109.lua",
        '_G["warheads"]["BLU_109"] = { mass = 874, expl_mass = 240, is_htp = true }',
    )
    write(
        g / "bombs/Mk_84.lua",
        '_G["bombs"]["Mk_84"] = { name = "Mk_84", mass = 894,'
        " warhead = { mass = 894, expl_mass = 429 } }",
    )
    _, warheads = build_weapons_and_warheads(
        collect_projectiles(LuaReader(g), g), _constants()
    )
    assert warheads["BLU_109"]["hardTargetPenetrator"] is True
    assert "hardTargetPenetrator" not in warheads["Mk_84"]


def test_non_boolean_htp_flag_fails(tmp_path: Path) -> None:
    g = tmp_path / "_G"
    write(
        g / "bombs/X.lua",
        '_G["bombs"]["X"] = { name = "X", mass = 1, warhead = { mass = 1, is_htp = 1 } }',
    )
    with pytest.raises(SystemExit):
        build_weapons_and_warheads(collect_projectiles(LuaReader(g), g), _constants())


def test_rockets_dir_missile_is_a_missile(tmp_path: Path) -> None:
    g = tmp_path / "_G"
    write(
        g / "rockets/AIM-9L.lua",
        '_G["rockets"]["#Index"] = { name = "AIM-9L", M = 85, category = 4,'
        ' wsTypeOfWeapon = { 4, 4, 7, "Redacted" } }',
    )
    write(
        g / "rockets/Y.lua",
        '_G["rockets"]["#Index"] = { name = "Y", M = 1, category = 2,'
        ' _unique_resource_name = "weapons.nurs.Y" }',
    )
    index = collect_projectiles(LuaReader(g), g)
    weapons, _ = build_weapons_and_warheads(index, _constants())
    aim9 = weapons["AIM-9L"]
    assert (aim9["category"], aim9["categoryName"]) == (4, "wsType_Missile")
    assert (aim9["launcherCategory"], aim9["launcherCategoryName"]) == (
        4,
        "CAT_AIR_TO_AIR",
    )
    assert weapons["Y"]["launcherCategoryName"] == "CAT_MISSILES"
    assert "category" not in weapons["Y"]


def test_category_from_agreeing_exact_launchers() -> None:
    weapons: dict[str, dict[str, Any]] = {n: {"id": n} for n in ("A", "B", "C", "D")}
    weapons["D"].update(category=4, categoryName="wsType_Missile")
    launchers = [
        (Path(f"{i}.lua"), {"CLSID": str(i), "wsTypeOfWeapon": ws})
        for i, ws in enumerate(
            [
                [4, 5, 36, "A"],
                [4, 5, 37, "A"],
                [4, 5, 36, "B"],
                [4, 4, 36, "B"],  # launchers disagree: no category
                [4, 5, 36, "D"],  # has its own: untouched
                [4, 5, 36, "Redacted"],
            ]
        )
    ]
    categories_from_launchers(weapons, launchers, _constants())
    assert weapons["A"] == {
        "id": "A",
        "category": 5,
        "categoryName": "wsType_Bomb",
        "_source": {"category": "launcher"},
    }
    assert all("category" not in weapons[n] for n in ("B", "C"))
    assert weapons["D"]["category"] == 4 and "_source" not in weapons["D"]


def test_projectile_without_mass_fails(tmp_path: Path) -> None:
    g = tmp_path / "_G"
    write(g / "bombs/B.lua", '_G["bombs"]["#Index"] = { name = "B" }')
    with pytest.raises(SystemExit):
        build_weapons_and_warheads(collect_projectiles(LuaReader(g), g), _constants())


@pytest.mark.parametrize(
    ("record", "kind"),
    [
        ({"category": 0, "type": 0}, "tv"),
        ({"category": 0, "type": 1}, "lltv"),
        ({"category": 0, "type": 2}, "ir"),
        ({"category": 1, "type": 2}, "radar"),
        ({"category": 2}, "irst"),
        ({"category": 3}, "rwr"),
        ({}, None),
    ],
)
def test_sensor_kind_from_category(record: dict[str, Any], kind: str | None) -> None:
    assert sensor_kind(sensor_enums(record, _constants())) == kind


def test_sensor_type_name_follows_category() -> None:
    c = _constants()
    assert sensor_enums({"category": 1, "type": 2}, c) == {
        "category": 1,
        "categoryName": "SENSOR_RADAR",
        "type": 2,
        "typeName": "RADAR_MULTIROLE",
    }
    assert sensor_enums({"category": 0, "type": 2}, c)["typeName"] == "OPTIC_SENSOR_IR"


def _store(raw: dict[str, Any]) -> dict[str, Any]:
    stores, _, _ = build_stores_and_racks(
        [(Path("x.lua"), raw)], ProjectileIndex(), _constants(), NO_IDS
    )
    return stores[raw["CLSID"]]


@pytest.mark.parametrize(
    ("raw", "kind"),
    [
        ({"CLSID": "a", "category": 5}, "fuel-tank"),
        ({"CLSID": "b", "category": 6, "Count": 3}, "pod"),
        ({"CLSID": "c", "category": 1, "Count": 3}, "rack"),
        ({"CLSID": "d", "category": 4, "Count": 1}, "single"),
        ({"CLSID": "e", "attribute": [1, 3, 43, "Redacted"]}, "fuel-tank"),
        ({"CLSID": "f", "attribute": [4, 15, 46, "Redacted"]}, "pod"),
        ({"CLSID": "g"}, "unknown"),
    ],
)
def test_store_kind_from_category(raw: dict[str, Any], kind: str) -> None:
    assert _store(raw)["kind"] == kind


def test_store_keeps_category_number_and_name() -> None:
    store = _store({"CLSID": "p", "category": 6})
    assert (store["category"], store["categoryName"]) == (6, "CAT_PODS")
    assert "category" not in _store({"CLSID": "q", "category": 99})


def test_store_delivering_two_weapons_lists_both(tmp_path: Path) -> None:
    g = tmp_path / "_G"
    write(
        g / "rockets/A.lua",
        '_G["rockets"]["#Index"] = { name = "A", M = 1, model = "a" }',
    )
    write(
        g / "rockets/B.lua",
        '_G["rockets"]["#Index"] = { name = "B", M = 1, model = "b" }',
    )
    index = collect_projectiles(LuaReader(g), g)
    raw = {
        "CLSID": "{MIX}",
        "category": 4,
        "Count": 3,
        "Elements": [{"ShapeName": "a"}, {"ShapeName": "b"}, {"ShapeName": "b"}],
    }
    stores, _, stats = build_stores_and_racks(
        [(Path("x.lua"), raw)], index, _constants(), NO_IDS
    )
    assert stores["{MIX}"]["delivers"] == [
        {"weapon": "A", "count": 1},
        {"weapon": "B", "count": 2},
    ]
    assert stats.basis == {"shape": 1}


def _index(tmp_path: Path) -> ProjectileIndex:
    g = tmp_path / "_G"
    write(
        g / "rockets/A.lua",
        '_G["rockets"]["#Index"] = { name = "A", M = 1, model = "a" }',
    )
    write(
        g / "rockets/B.lua",
        '_G["rockets"]["#Index"] = { name = "B", M = 1, model = "b" }',
    )
    return collect_projectiles(LuaReader(g), g)


def test_slot4_name_is_an_exact_join(tmp_path: Path) -> None:
    # Slot 4 names B although the element shapes match A: the name wins.
    launchers = [
        {"CLSID": "exact", "category": 4, "wsTypeOfWeapon": [4, 4, 7, "B"],
         "Elements": [{"ShapeName": "a"}, {"ShapeName": "a"}]},
        {"CLSID": "exact-count", "category": 4, "Count": 3, "wsTypeOfWeapon": [4, 4, 7, "B"]},
        {"CLSID": "shape", "category": 4, "wsTypeOfWeapon": [4, 4, 7, "Redacted"],
         "Elements": [{"ShapeName": "a"}]},
        {"CLSID": "gone", "category": 4, "wsTypeOfWeapon": [4, 4, 7, "NOPE"],
         "Elements": [{"ShapeName": "a"}]},
        {"CLSID": "tank", "category": 5},
    ]  # fmt: skip
    stores, _, stats = build_stores_and_racks(
        [(Path(f"{r['CLSID']}.lua"), r) for r in launchers],
        _index(tmp_path),
        _constants(),
        NO_IDS,
    )
    assert stores["exact"]["delivers"] == [{"weapon": "B", "count": 2}]
    assert stores["exact-count"]["delivers"] == [{"weapon": "B", "count": 3}]
    assert stores["shape"]["delivers"] == [{"weapon": "A", "count": 1}]
    assert stores["gone"]["delivers"] == []
    assert stats.basis == {"exact": 2, "shape": 1, "none": 2}
    assert stats.unknown_weapon == {"NOPE": 1}
    assert stats.no_delivers == {"single": 1, "fuel-tank": 1}


def _overlays(tmp_path: Path, entries: str) -> overlays.Overlays:
    return overlays.load("1.0.0", write(tmp_path / "o.yaml", f"entries:\n{entries}"))


_META = "    note: n\n    evidence: e\n"


def test_overlay_patch_sets_and_stamps(tmp_path: Path) -> None:
    facts = _overlays(
        tmp_path,
        "  - series: datalink\n    id: X\n    field: cross\n    value: true\n" + _META
        + "  - series: datalink\n    id: X\n    field: other\n    value: 1\n"
        "    versions: [9.9.9]\n" + _META,
    )  # fmt: skip
    series = {"datalink": {"X": {"cross": False, "_source": {"cross": "default"}}}}
    overlays.apply(facts, series)
    assert series["datalink"]["X"] == {
        "cross": True,
        "_source": {"cross": "hand-authored"},
    }


def test_overlay_negate_asserts_the_wrong_sign(tmp_path: Path) -> None:
    facts = _overlays(
        tmp_path,
        "  - series: aircraft\n    id: F\n    field: stations[station=10].position.lateral\n"
        "    op: negate\n    raw_sign: 1\n" + _META,
    )
    station = {"station": 10, "position": {"lateral": 0.5}}
    series = {"aircraft": {"F": {"stations": [station]}}}
    overlays.apply(facts, series)
    assert station == {
        "station": 10,
        "position": {"lateral": -0.5},
        "_source": {"position.lateral": "corrected"},
    }
    with pytest.raises(SystemExit):  # ED fixed the sign: the correction is stale
        overlays.apply(
            facts,
            {
                "aircraft": {
                    "F": {"stations": [{"station": 10, "position": {"lateral": -0.5}}]}
                }
            },
        )


@pytest.mark.parametrize(
    "series",
    [
        {"datalink": {}},  # record gone
        {"datalink": {"X": {}}},  # field gone
        {"datalink": {"X": {"cross": True}}},  # no longer changes anything
    ],
)
def test_stale_overlay_patch_fails(tmp_path: Path, series: dict[str, Any]) -> None:
    facts = _overlays(
        tmp_path,
        "  - series: datalink\n    id: X\n    field: cross\n    value: true\n" + _META,
    )
    with pytest.raises(SystemExit):
        overlays.apply(facts, series)


def test_overlay_entry_needs_evidence(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        _overlays(
            tmp_path, "  - series: radios\n    table: t\n    value: {}\n    note: n\n"
        )


def test_repo_overlays_load() -> None:
    facts = overlays.load(None)
    assert facts.table("radios", "guardMHz")["UHF"] == [243.0]
    by_series = Counter(p["series"] for p in facts.patches)
    assert by_series == {"aircraft": 2, "actions": 42}  # one per record id
    assert all("add" in p for p in facts.patches if p["series"] == "actions")


def test_overlay_rule_first_match_and_unused() -> None:
    rules_: list[dict[str, Any]] = [
        {"band": "HF", "when": {"maxMHz": {"<=": 30}}},
        {"band": "UHF", "when": {"minMHz": {">=": 225}, "maxMHz": {"<": 400}}},
        {"band": "VHF"},
    ]
    at = [
        overlays.rule(rules_, {"minMHz": lo, "maxMHz": hi}, "t")
        for lo, hi in ((2, 30), (225, 399), (225, 400), (30, 88))
    ]
    assert at == [0, 1, 2, 2]
    overlays.unused_rules(rules_, {i for i in at if i is not None}, "t")
    with pytest.raises(SystemExit):
        overlays.unused_rules(rules_, {0, 2}, "t")
    with pytest.raises(SystemExit):
        overlays.rule([{"when": {"hz": {"<": 1}}}], {"minMHz": 1}, "t")
    with pytest.raises(SystemExit):
        overlays.rule([{"when": {"minMHz": {"~": 1}}}], {"minMHz": 1}, "t")


def test_radio_modulation_band_and_hand_facts() -> None:
    from tools.datamine.extract_radios import build_radios

    channels: list[dict[str, Any]] = [{"name": "1", "default": 40, "modulation": "FM"}]
    units: dict[str, dict[str, Any]] = {
        "F": {
            "panelRadio": [
                {
                    "name": "UHF/VHF: X",
                    "range": [
                        {"min": 30, "max": 87.975, "modulation": 2, "modulationDef": 1},
                        {"min": 225, "max": 399.975},
                    ],
                    "channels": [],
                }
            ]
        },
        "G": {
            "panelRadio": [
                {
                    "name": "R-1",
                    "range": {"min": 30, "max": 87.975},
                    "channels": channels,
                }
            ]
        },
    }
    facts = overlays.Overlays(
        [],
        {
            ("radios", "bandRules"): [{"band": "VHF"}],
            ("radios", "guardMHz"): {"V/UHF": [243.0], "VHF": [121.5]},
            ("radios", "stepKHz"): {"V/UHF": 25},
        },
    )
    constants = Constants(
        {
            "MODULATION": {
                "MODULATION_AM": 0,
                "MODULATION_FM": 1,
                "MODULATION_AM_AND_FM": 2,
            }
        }
    )
    radios, _ = build_radios(units, {"F", "G"}, constants, facts)
    f, g = radios["F__radio0"], radios["G__radio0"]
    # Named band; DCS segment modulation, else the editor's AM fallback.
    assert (f["name"], f["band"], f["guard"], f["stepKHz"]) == (
        "UHF/VHF: X",
        "V/UHF",
        True,
        25,
    )
    assert f["segments"] == [
        {
            "minMHz": 30, "maxMHz": 87.975, "modulation": 2,
            "modulationName": "MODULATION_AM_AND_FM",
            "defaultModulation": 1, "defaultModulationName": "MODULATION_FM",
        },
        {"minMHz": 225, "maxMHz": 399.975, "modulation": 0, "modulationName": "MODULATION_AM"},
    ]  # fmt: skip
    assert f["modulationName"] == ["MODULATION_AM", "MODULATION_AM_AND_FM"]
    assert f["_source"] == {"guard": "hand-authored", "stepKHz": "hand-authored"}
    # Unnamed band from the rules; modulation from the preset channel label.
    assert (g["band"], g["guard"], g["modulationName"]) == (
        "VHF",
        False,
        ["MODULATION_FM"],
    )
    assert g["_source"] == {"band": "hand-authored", "guard": "hand-authored"}
    del units["G"]  # the band rule and the VHF guard key are now unused
    with pytest.raises(SystemExit):
        build_radios(units, {"F"}, constants, facts)
    channels.append({"name": "2", "default": 50, "modulation": "AM"})  # two labels
    with pytest.raises(SystemExit):
        build_radios({"G": {"panelRadio": [{"range": {"min": 30, "max": 88}, "channels": channels}]}},
                     {"G"}, constants, facts)  # fmt: skip


def test_radio_guard_is_per_segment() -> None:
    from tools.datamine.extract_radios import build_radios

    def radio(*segments: tuple[float, float]) -> dict[str, Any]:
        rng = [{"min": lo, "max": hi} for lo, hi in segments]
        return {"panelRadio": [{"name": "UHF/VHF", "range": rng, "channels": []}]}

    facts = overlays.Overlays(
        [],
        {
            ("radios", "bandRules"): [],
            ("radios", "guardMHz"): {"V/UHF": [121.5]},
            ("radios", "stepKHz"): {},
        },
    )
    constants = Constants({"MODULATION": {"MODULATION_AM": 0}})
    units = {
        "Gap": radio((30, 87.975), (225, 399.975)),  # 121.5 between the segments
        "Air": radio((30, 87.975), (108, 151.975), (225, 399.975)),
    }
    radios, _ = build_radios(units, set(units), constants, facts)
    assert radios["Gap__radio0"]["range"] == {"minMHz": 30, "maxMHz": 399.975}
    assert radios["Gap__radio0"]["guard"] is False
    assert radios["Air__radio0"]["guard"] is True


def test_radio_from_human_radio_without_panel() -> None:
    from tools.datamine.extract_radios import build_radios

    facts = overlays.Overlays(
        [],
        {
            ("radios", "bandRules"): [{"band": "V/UHF"}],
            ("radios", "guardMHz"): {"V/UHF": [243.0]},
            ("radios", "stepKHz"): {},
        },
    )
    constants = Constants({"MODULATION": {"MODULATION_AM": 0, "MODULATION_FM": 1}})
    units: dict[str, dict[str, Any]] = {
        "Range": {"HumanRadio": {"rangeFrequency": [{"min": 225, "max": 399.975}]}},
        "MinMax": {
            "HumanRadio": {"minFrequency": 30, "maxFrequency": 88, "modulation": 1}
        },
        "Fixed": {"HumanRadio": {"frequency": 251, "modulation": 0}},
        "Panel": {
            "panelRadio": [{"range": {"min": 30, "max": 88}, "channels": []}],
            "HumanRadio": {"frequency": 251},
        },
        "Empty": {"HumanRadio": {"editable": True}},
    }
    radios, by_aircraft = build_radios(units, set(units), constants, facts)
    ranges = {
        rid: (r["range"], r["modulationName"], r["presets"])
        for rid, r in radios.items()
    }
    assert ranges == {
        "Fixed__radio0": ({"minMHz": 251, "maxMHz": 251}, ["MODULATION_AM"], 0),
        "MinMax__radio0": ({"minMHz": 30, "maxMHz": 88}, ["MODULATION_FM"], 0),
        "Panel__radio0": ({"minMHz": 30, "maxMHz": 88}, ["MODULATION_AM"], 0),
        "Range__radio0": ({"minMHz": 225, "maxMHz": 399.975}, ["MODULATION_AM"], 0),
    }
    assert "Empty" not in by_aircraft


# A mission-editor datalink descriptor in the shape of CoreMods/aircraft/*/Datalinks/*.lua.
_DESCRIPTOR = """
local cur, pool
local function nextUnit(list)
    for _, units in pairs(pool) do
        for _, id in ipairs(units) do
            local taken = false
            for _, m in ipairs(cur.network.teamMembers) do taken = taken or m.missionUnitId == id end
            for _, m in ipairs(cur.network.donors) do taken = taken or m.missionUnitId == id end
            if not taken then return id end
        end
    end
end
function addMember(self, dl)
    if #dl.network.teamMembers < TEAM then table.insert(dl.network.teamMembers, {missionUnitId = nextUnit()}) end
end
function addDonor(self, dl)
    if #dl.network.DONORS < 3 then table.insert(dl.network.DONORS, {missionUnitId = nextUnit()}) end
end
function getDefault(data)
    return {settings = {}, network = {teamMembers = {{missionUnitId = data.unit.unitId}}, DONORS = {}, donors = {}}}
end
function init(dl, index, unitId)
    cur = dl
    pool = getUnitsGroupsWithAddPropName("KEY")
    onAction("b_AddUnit_Members", "add_callback", {"onChange", addMember})
    onAction("b_AddUnit_Donors", "add_callback", {"onChange", addDonor})
end
"""


def test_datalink_limits_come_from_the_editor_descriptor(tmp_path: Path) -> None:
    from tools.datamine.extract_datalink import build_datalinks

    def run(
        team: str = "4", donors: str = "donors", key: str = "STN_L16"
    ) -> dict[str, Any]:
        text = _DESCRIPTOR.replace("TEAM", team).replace("DONORS", donors)
        write(tmp_path / "mod" / "Datalinks" / "Link16.lua", text.replace("KEY", key))
        prop = [{"id": "STN_L16"}]
        units: dict[str, dict[str, Any]] = {
            "A": {"_file": "./mod/a.lua", "datalinks": {"Link16": "Datalinks\\Link16.lua"},
                  "AddPropAircraft": prop},
            "B": {"_file": "./mod/b.lua", "datalinks": {"Link16": "Datalinks\\Link16.lua"}},
        }  # fmt: skip
        return build_datalinks(units, {"A", "B"}, tmp_path)

    out = run()
    assert out["A"] == {
        "id": "A",
        "datalinkType": "Link16",
        "canBeLink16Donor": True,
        "supportsTeamMembers": True,
        "supportsCrossFlightTeam": True,
        "maxTeamMembers": 4,
        "maxDonors": 3,
    }
    assert out["B"]["canBeLink16Donor"] is False
    for bad in ({"team": "1e9"}, {"donors": "teamMembers"}, {"donors": "other"}):
        with pytest.raises(
            SystemExit
        ):  # no limit / two buttons, one list / unknown list
            run(**bad)
    with pytest.raises(SystemExit):  # a datalink type outside Entity.DatalinkType
        build_datalinks({"C": {"datalinks": {"Link4": "x.lua"}}}, {"C"}, tmp_path)


def test_check_refs_reports_dangling_and_gaps() -> None:
    data: dict[str, dict[str, dict[str, Any]]] = {
        "weapons": {"W": {"id": "W"}},
        "stores": {
            "s": {"clsid": "s", "delivers": [{"weapon": "W"}, {"weapon": "NOPE"}]}
        },
        "aircraft": {
            "a": {
                "id": "a",
                "stations": [{"accepts": [{"clsid": "{GONE}"}, {"clsid": "s"}]}],
            }
        },
    }
    report = check_refs(data, entity_schema(), {"{GONE}": "note", "s": "now defined"})
    assert report.resolved == 2
    assert [(r.field, r.value) for r in report.dangling] == [
        ("delivers[].weapon", "NOPE")
    ]
    assert [r.value for r in report.upstream] == ["{GONE}"]
    assert report.stale_gaps == ["s"]


def test_ref_rules_come_from_the_schema() -> None:
    found = {(r.series, r.label, r.target) for r in rules(entity_schema())}
    assert {
        ("aircraft", "stations[].accepts[].clsid", "stores"),
        ("ships", "weaponSystems[].dependsOn[][].unit", "units"),
        ("attributes", "units.groundVehicles[]", "ground_vehicles"),
        ("liveries", "unitTypes[]", "units"),
    } <= found


def test_ref_must_name_an_entity_type_on_a_string_field() -> None:
    types: dict[str, dict[str, Any]] = {
        "Entity.Thing": {"kind": "record", "fields": {"id": {"type": "string"}}},
        "Entity.Holder": {
            "kind": "record",
            "fields": {"n": {"type": "number", "ref": "Entity.Thing"}},
        },
    }
    with pytest.raises(ValueError, match="holding no string"):
        export(types)
    types["Entity.Holder"]["fields"]["n"] = {"type": "string[]", "ref": "Thing"}
    with pytest.raises(KeyError, match="no entity type"):
        export(types)
    types["Entity.Holder"]["fields"]["n"]["ref"] = "Entity.Thing"
    holder = export(types)["definitions"]["Entity.Holder"]
    assert holder["properties"]["n"]["items"]["x-ref"] == ["Entity.Thing"]


SPEC_TYPES = {
    "country.id": {"kind": "enum", "values": {"USA": 2}},
    "Entity.Thing": {
        "kind": "record",
        "fields": {
            "id": {"type": "string"},
            "n": {"type": "number | nil"},
            "c": {"type": "country.id[]"},
        },
        "required": ["id"],
    },
}


def test_json_schema_export_validates_and_is_fail_closed() -> None:
    from jsonschema import Draft7Validator

    doc = export(SPEC_TYPES)
    assert doc["definitions"]["country.id"] == {
        "title": "country.id",
        "enum": [2],
        "x-values": {"USA": 2},
    }
    v = Draft7Validator(schema_for(doc, "Entity.Thing"))
    assert v.is_valid({"id": "x", "n": None, "c": [2], "_source": {"n": "default"}})
    assert not v.is_valid({"id": "x", "c": [3]})
    assert not v.is_valid({"id": "x", "extra": 1})
    with pytest.raises(KeyError):
        export(
            {
                **SPEC_TYPES,
                "Entity.Bad": {
                    "kind": "record",
                    "fields": {"x": {"type": "Entity.Missing"}},
                },
            }
        )
    with pytest.raises(ValueError):
        export({"Entity.Alias": {"kind": "alias"}})


def test_orphan_entity_types_are_reported() -> None:
    types = {
        "Entity.Aircraft": {"kind": "record", "fields": {"g": {"type": "Entity.Gun"}}},
        "Entity.Gun": {"kind": "record", "fields": {}},
        "Entity.Lonely": {"kind": "record", "fields": {}},
    }
    assert orphan_types(export(types)) == ["Entity.Lonely"]


def test_years_zero_zero_means_no_service_period() -> None:
    from tools.datamine.extract_countries import _years_for

    years = {
        "F-16C_50": {
            "2": {"from": 1991, "to": 9999},
            "0": {"from": 0, "to": 0},
        }
    }
    assert _years_for(years, "F-16C_50", "2") == {"from": 1991, "to": 9999}
    assert _years_for(years, "F-16C_50", "0") is None
    assert _years_for(years, "F-16C_50", "99") is None


def test_sanitize_id_case_insensitive_collision() -> None:
    from tools.datamine.common import sanitize_id

    used: set[str] = set()
    first = sanitize_id("Zell", used)
    second = sanitize_id("zell", used)
    assert first == "Zell"
    assert second.startswith("zell~") and second.lower() != first.lower()


def test_unit_gun_ammo_and_sensors_from_dump(tmp_path: Path) -> None:
    from tools.datamine.extract_units import _sensor_names, build_gun_ammo, load_units

    write(
        tmp_path / "db/Units/Cars/Car/ZSU.lua",
        """_G["db"]["Units"]["Cars"]["Car"]["#Index"] = {
            type = "ZSU", attribute = { "AAA", "Vehicles" },
            WS = { { LN = { { PL = { { shell_name = { "23mm_HE", "23mm_AP" } } } } },
                     extra = { shell_name = { "ignored" } } } },
            Sensors = { RADAR = "RPK-2", OPTIC = { "TV", "Redacted" } },
        }""",
    )
    write(
        tmp_path / "weapons_table/weapons/shells/23mm_HE.lua",
        '_G["shells"]["#Index"] = { round_mass = 0.19, mass = 0.1, type_name = "shell",'
        ' display_name = "23mm HE" }',
    )
    reader = LuaReader(tmp_path)
    raw = load_units(reader, tmp_path)
    assert set(raw.category("Cars")) == {"ZSU"}
    assert raw.attributes >= {"AAA", "Vehicles"}
    assert raw.gun_ammo == {"23mm_HE", "23mm_AP"}
    assert build_gun_ammo(raw, reader, tmp_path) == {
        "23mm_AP": {"id": "23mm_AP"},
        "23mm_HE": {"id": "23mm_HE", "massKg": 0.19, "type": "shell", "displayName": "23mm HE"},
    }  # fmt: skip
    assert _sensor_names(raw.category("Cars")["ZSU"]) == ["RPK-2", "TV"]
    write(tmp_path / "db/Units/Planes/Plane/X.lua", '_G["x"] = { Name = "X" }')
    with pytest.raises(SystemExit):
        load_units(LuaReader(tmp_path), tmp_path)


def test_aircraft_dimensions_from_unit_fields() -> None:
    from tools.datamine.extract_units import _dimensions

    plane = {"wing_span": 17.53, "length": 16.26, "height": 4.47, "WingSpan": 1}
    assert _dimensions(plane) == {"wingSpanM": 17.53, "lengthM": 16.26, "heightM": 4.47}
    heli = {"rotor_diameter": 21.33, "length": 18.2, "height": 4.9}
    assert _dimensions(heli) == {
        "rotorDiameterM": 21.33,
        "lengthM": 18.2,
        "heightM": 4.9,
    }
    assert _dimensions({}) is None


def test_validate_explains_rejected_records(capsys: pytest.CaptureFixture[str]) -> None:
    from tools.datamine.common import REFERENCE_DATA_DIR, REPO_ROOT
    from tools.datamine.validate_data import validate
    from tools.merge import merge_tree

    merged, _ = merge_tree(str(REPO_ROOT / "dcs-world-schema"))
    manifest = (REFERENCE_DATA_DIR / "latest" / "manifest.json").read_bytes()
    tree = {"manifest.json": manifest, "racks/R.json": b'{"id": "R", "ejectors": 2}'}
    assert validate(tree, export(merged["types"]), "2.9.1.1")
    tree["racks/R.json"] = b'{"id": "R", "ejectors": "two"}'
    assert not validate(tree, export(merged["types"]), "2.9.1.1")
    assert "racks/R.json :: ejectors -> 'two' is not of type 'number'" in (
        capsys.readouterr().out
    )
