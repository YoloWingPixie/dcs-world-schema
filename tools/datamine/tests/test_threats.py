"""RWR table evaluation and exact joins, and threat systems from DCS data."""

from pathlib import Path
from typing import Any

import pytest
from conftest import entity_schema, write

from tools.datamine import rwr
from tools.datamine.check_refs import check_refs
from tools.datamine.extract_threats import build_threats, nato_names
from tools.datamine.extract_units import weapon_systems
from tools.datamine.overlays import Overlays
from tools.datamine.rwr import Entry, Key, RwrJoin, WsTypeIds

COCKPIT = "Scripts/Aircrafts/_Common/Cockpit"


def _install(tmp_path: Path, symbols: str, harm: str) -> Path:
    write(
        tmp_path / "Scripts/Database/wsTypes.lua",
        "wsType_Ground = 2\nwsType_SAM = 16\nwsType_Radar = 101\nTR_ = 7\nLN_ = 8\n",
    )
    write(
        tmp_path / COCKPIT / "wsTypes_SAM.lua",
        'dofile("Scripts/Database/wsTypes.lua")\n'
        "SAM_TR = {wsType_Ground, wsType_SAM, wsType_Radar, TR_}\n"
        "SAM_LN = {wsType_Ground, wsType_SAM, wsType_Radar, LN_}\n",
    )
    write(tmp_path / COCKPIT / "AN_ALR_SymbolsBase.lua", symbols)
    write(tmp_path / COCKPIT / "AN_ALR_HarmIDs.lua", harm)
    return tmp_path


_SYMBOLS = f"""dofile('{COCKPIT}/wsTypes_SAM.lua')
DefaultType = 100
DEFAULT_TYPE_ = {{DefaultType, DefaultType, DefaultType, DefaultType}}
symbols = {{
    {{SAM_TR, "10"}},
    {{TR_, "S"}},          -- a bare level-4 number
    {{NOT_DEFINED, "12"}}, -- an undefined global
}}
symbols_strings = {{ ['EWR unit'] = 'S', ['AIM_X'] = 'M' }}
"""
_HARM = f"""dofile('{COCKPIT}/wsTypes_SAM.lua')
symbolID = {{ {{110, SAM_TR}} }}
symbols_stringsID = {{ {{120, "A", "B"}} }}
"""


def test_tables_keep_the_global_each_key_was_written_as(tmp_path: Path) -> None:
    entries, ws_types = rwr.read_tables(_install(tmp_path, _SYMBOLS, _HARM))
    assert [(e.table, str(e.key), e.value) for e in entries] == [
        ("symbols", "SAM_TR {2, 16, 101, 7}", "10"),
        ("symbols", "TR_ (the number 7, not a wsType tuple)", "S"),
        ("symbols", "NOT_DEFINED (undefined)", "12"),
        ("symbols_strings", "'AIM_X'", "M"),
        ("symbols_strings", "'EWR unit'", "S"),
        ("symbolID", "SAM_TR {2, 16, 101, 7}", "110"),
        ("symbols_stringsID", "'A'", "120"),
        ("symbols_stringsID", "'B'", "120"),
    ]
    assert ws_types == {"wsType_Ground": 2, "wsType_SAM": 16, "wsType_Radar": 101}


def test_install_scripts_are_sandboxed(tmp_path: Path) -> None:
    outside = "dofile('../../etc/passwd')\nsymbols = {}\nsymbols_strings = {}\n"
    with pytest.raises(SystemExit):
        rwr.read_tables(_install(tmp_path, outside, _HARM))
    with pytest.raises(SystemExit):  # no libraries
        rwr.read_tables(_install(tmp_path, "os.exit(1)\n", _HARM))


def test_install_and_dump_wstype_levels_must_agree() -> None:
    rwr.check_ws_type_constants({"wsType_SAM": 16}, {"wsType_SAM": 16, "wsType_X": 1})
    with pytest.raises(SystemExit):
        rwr.check_ws_type_constants({"wsType_SAM": 16}, {"wsType_SAM": 17})


def _e(table: str, value: str, **key: Any) -> Entry:
    return Entry(table, Key(**key), value)


_IDS = WsTypeIds(
    units={
        "tr_a": [(2, 16, 101, 7)],
        "tr_b": [(2, 16, 101, 7)],  # one wsType, two unit types: both match
        "ln": [(2, 16, 102, 8)],
    },
    stores={},
    projectiles={"AIM_Y": [(4, 4, 7, 5)]},
    ammunition={},
)


def test_join_tuples_and_names_exactly() -> None:
    entries = [
        _e("symbols", "10", ident="SAM_TR", tuple=(2, 16, 101, 7)),
        _e("symbols", "M", ident="AIM_Y_", tuple=(4, 4, 7, 5)),
        _e("symbols", "X", ident="GONE", tuple=(2, 16, 101, 99)),
        _e("symbols", "S", ident="TR_", number=7),
        _e("symbols_strings", "10", name="tr_a"),  # same value again: fine
        _e("symbols_strings", "F", name="no such unit"),
        _e("symbolID", "110", ident="SAM_TR", tuple=(2, 16, 101, 7)),
    ]
    out = rwr.join(entries, {"tr_a", "tr_b", "ln"}, {"AIM_Y"}, _IDS)
    assert out.units == {
        "tr_a": {"rwrSymbol": "10", "alic": ["110"]},
        "tr_b": {"rwrSymbol": "10", "alic": ["110"]},
    }
    assert out.projectiles == {"AIM_Y": {"rwrSymbol": "M"}}
    assert out.unmatched == [
        "symbols GONE {2, 16, 101, 99}",
        "symbols_strings 'no such unit'",
    ]
    assert out.unkeyed == ["symbols TR_ (the number 7, not a wsType tuple)"]


def test_joined_projectile_codes_go_on_the_weapon() -> None:
    weapons = {"AIM_Y": {"id": "AIM_Y"}, "AIM_Z": {"id": "AIM_Z"}}
    joined = RwrJoin(projectiles={"AIM_Y": {"rwrSymbol": "M", "alic": ["120"]}})
    rwr.apply_to_weapons(joined, weapons)
    assert weapons == {
        "AIM_Y": {"id": "AIM_Y", "rwrSymbol": "M", "alic": ["120"]},
        "AIM_Z": {"id": "AIM_Z"},
    }


def test_join_conflicting_values_fail() -> None:
    entries = [
        _e("symbols", "10", ident="SAM_TR", tuple=(2, 16, 101, 7)),
        _e("symbols_strings", "11", name="tr_b"),
    ]
    with pytest.raises(SystemExit):
        rwr.join(entries, {"tr_a", "tr_b"}, set(), _IDS)


def test_join_collects_several_alic_codes() -> None:
    entries = [
        _e("symbolID", "315", ident="SAM_TR", tuple=(2, 16, 101, 7)),
        _e("symbols_stringsID", "412", name="tr_b"),
        _e("symbols_stringsID", "90", name="tr_b"),
        _e("symbols_stringsID", "315", name="tr_b"),
    ]
    out = rwr.join(entries, {"tr_a", "tr_b"}, set(), _IDS)
    assert out.units == {
        "tr_a": {"alic": ["315"]},
        "tr_b": {"alic": ["90", "315", "412"]},
    }


def test_ammunition_report_rechecks_level3_mismatch() -> None:
    ids = WsTypeIds(
        units={},
        stores={},
        projectiles={"SA9M311": [(4, 4, 34, 90)], "R": [(4, 4, 7, 1)]},
        ammunition={"2S6 Tunguska": [(4, 4, 11, 90)], "ok": [(4, 4, 7, 1)]},
    )
    assert rwr.ammunition_report(ids) == [
        "2S6 Tunguska: type_ammunition {4, 4, 11, 90} exactly matches no projectile;"
        " by levels 1, 2, 4: ['SA9M311']"
    ]


def _ad(
    attrs: list[str],
    missile: str | None = None,
    deps: list[Any] | None = None,
    guns: bool = False,
) -> dict[str, Any]:
    ln: dict[str, Any] = {"distanceMax": 40000}
    if deps is not None:
        ln["depends_on_unit"] = deps
    pl: list[dict[str, Any]] = []
    if missile:
        pl.append({"type_ammunition": f"weapons.missiles.{missile}"})
    if guns:
        pl.append({"shell_name": ["23mm"]})
    if pl:
        ln["PL"] = pl
    return {"category": "Air Defence", "attribute": attrs, "WS": [{"LN": [ln]}]}


def _dep(*names: str) -> list[Any]:
    return [[[n]] for n in names]


_UNITS = {
    # SA-10-like: launchers need either TR, TRs need the CP, the CP needs SRs.
    "5P85C ln": _ad(["SAM LL"], "SA5B55", _dep("40B6M tr", "30H6 tr")),
    "5P85D ln": _ad(["SAM LL"], "SA5B55", _dep("40B6M tr", "30H6 tr")),
    "40B6M tr": _ad(["SAM TR"], deps=_dep("54K6 cp")),
    "30H6 tr": _ad(["SAM TR"], deps=_dep("54K6 cp")),
    "54K6 cp": _ad(["SAM CC"], deps=_dep("64H6E sr")),
    "64H6E sr": _ad(["SAM SR"]),
    # NASAMS-like: two missiles, one command post.
    "LN_B": _ad(["SAM LL"], "AIM_120", _dep("CP")),
    "LN_C": _ad(["SAM LL"], "AIM_120C", _dep("CP")),
    "CP": _ad(["SAM CC"], deps=_dep("MPQ64")),
    "MPQ64": _ad(["SAM SR"]),
    # IR, no radar, no role attribute.
    "Soldier stinger": _ad(["MANPADS", "IR Guided SAM"], "FIM_92C"),
    # Avenger-like: the same missile plus guns, no role attribute.
    "Avenger": _ad(["IR Guided SAM"], "FIM_92C", guns=True),
    # SA-2/SA-3-like: a shared SR does not merge them; RD is a peer TR.
    "S75 ln": _ad(["SAM LL"], "SA2V755", _dep("SNR")),
    "SNR": _ad(["SAM TR"], deps=[[["self", 2]], [["P19"]]]),
    "RD": _ad(["SAM TR"], deps=_dep("P19", "SNR")),
    "S125 ln": _ad(["SAM LL"], "SA5B27", _dep("S125 tr")),
    "S125 tr": _ad(["SAM TR"], deps=_dep("P19")),
    "P19": _ad(["SAM SR"]),
    # Tor-like self-contained: SR/TR attributes, fires a missile.
    "Tor": _ad(["SAM SR", "SAM TR"], "SA9M330"),
    # Radar-directed guns vs plain guns.
    "Shilka": _ad(["SAM TR", "AAA"], guns=True),
    "ZU-23": _ad(["AAA"], guns=True),
    # A standalone SR on the RWR and an EWR.
    "Dog Ear": _ad(["SAM SR"]),
    "1L13": _ad(["EWR"]),
    "Truck": {"category": "Unarmed", "attribute": []},
    "CVN": {"category": "Ships", "attribute": []},
    "F-16C_50": {"category": "Planes", "attribute": []},
}
_DIRS = dict.fromkeys(_UNITS, "Cars") | {"CVN": "Ships", "F-16C_50": "Planes"}
_MISSILES = ["SA5B55", "AIM_120", "AIM_120C", "FIM_92C", "SA2V755", "SA5B27", "SA9M330"]
_WEAPONS = {m: {"id": m, "categoryName": "wsType_Missile"} for m in _MISSILES}
_ROCKETS = {m: {"D_max": 20000, "D_min": 1000, "H_max": 9000} for m in _MISSILES}
_EMITTERS = RwrJoin(
    units={
        "30H6 tr": {"rwrSymbol": "10", "alic": ["110"]},
        "Tor": {"rwrSymbol": "15"},
        "Shilka": {"rwrSymbol": "A"},
        "Dog Ear": {"rwrSymbol": "DE"},
        "1L13": {"rwrSymbol": "S"},
        "CVN": {"rwrSymbol": "SS", "alic": ["403"]},
        "F-16C_50": {"rwrSymbol": "16"},
    }
)


# NATO.lua-like names: SA-10 by its track radar, the shared P19 (an SR, which
# names nothing), both FIM_92C launchers differently.
_NATO = {
    "40B6M tr": "SA-10",
    "P19": "SA-2",
    "SNR": "SA-2",
    "S125 tr": "SA-3",
    "Soldier stinger": "MANPADS",
    "Avenger": "Avenger",
}


def _threats(
    names: dict[str, Any] | None = None,
    nato: dict[str, Any] | None = None,
    gaps: dict[str, Any] | None = None,
) -> dict[str, Any]:
    by_resource = {f"weapons.missiles.{m}": m for m in _MISSILES}
    return build_threats(
        _UNITS,
        _DIRS,
        {"F-16C_50": ["APG-68", "RWR"], "1L13": ["1L13"], "Tor": ["Tor radar"]},
        {"APG-68": "radar", "RWR": "rwr"},
        {u: weapon_systems(r, set(_WEAPONS), by_resource) for u, r in _UNITS.items()},
        _WEAPONS,
        _ROCKETS,
        _EMITTERS,
        _NATO if nato is None else nato,
        Overlays(
            [],
            {
                ("threats", "natoDesignation"): {"Dog Ear": "Dog Ear"}
                if names is None
                else names,
                ("threats", "natoDesignationUpstreamGaps"): gaps or {},
            },
        ),
    )


def _roles(threat: dict[str, Any]) -> list[tuple[str, list[str]]]:
    return [(c["unit"], c["roles"]) for c in threat["components"]]


def test_threat_kinds_and_ids() -> None:
    threats = _threats()
    assert {t: r["kind"] for t, r in threats.items()} == {
        "SA5B55": "sam",
        "AIM_120": "sam",
        "FIM_92C": "sam",
        "SA2V755": "sam",
        "SA5B27": "sam",
        "SA9M330": "sam",
        "Shilka": "aaa",
        "Dog Ear": "sam",
        "1L13": "ewr",
        "CVN": "ship",
        "F-16C_50": "aircraft",
    }


def test_sam_components_carry_requires_weapons_and_emitter_codes() -> None:
    sa10 = _threats()["SA5B55"]
    assert sa10["natoDesignation"] == "SA-10" and "_source" not in sa10
    by_unit = {c["unit"]: c for c in sa10["components"]}
    assert set(by_unit) == {
        "5P85C ln",
        "5P85D ln",
        "40B6M tr",
        "30H6 tr",
        "54K6 cp",
        "64H6E sr",
    }
    assert by_unit["5P85C ln"] == {
        "unit": "5P85C ln",
        "roles": ["SAM LL"],
        "requires": [[["40B6M tr"]], [["30H6 tr"]]],
        "weapons": ["SA5B55"],
        "envelope": {"rMaxKm": 40.0, "rMinKm": 1.0, "hMaxM": 9000},
    }
    assert by_unit["30H6 tr"] == {
        "unit": "30H6 tr",
        "roles": ["SAM TR"],
        "requires": [[["54K6 cp"]]],
        "rwrSymbol": "10",
        "alic": ["110"],
    }


def test_launchers_sharing_a_command_post_are_one_system() -> None:
    nasams = _threats()["AIM_120"]
    assert _roles(nasams) == [
        ("CP", ["SAM CC"]),
        ("LN_B", ["SAM LL"]),
        ("LN_C", ["SAM LL"]),
        ("MPQ64", ["SAM SR"]),
    ]
    assert [c.get("weapons") for c in nasams["components"]] == [
        None,
        ["AIM_120"],
        ["AIM_120C"],
        None,
    ]


def test_shared_search_radar_does_not_merge_systems() -> None:
    threats = _threats()
    assert _roles(threats["SA2V755"]) == [
        ("P19", ["SAM SR"]),
        ("RD", ["SAM TR"]),
        ("S75 ln", ["SAM LL"]),
        ("SNR", ["SAM TR"]),
    ]
    assert _roles(threats["SA5B27"]) == [
        ("P19", ["SAM SR"]),
        ("S125 ln", ["SAM LL"]),
        ("S125 tr", ["SAM TR"]),
    ]


def test_one_component_per_unit_with_dcs_roles_only() -> None:
    threats = _threats()
    # No role attribute: `weapons` alone says it is a launcher.
    assert threats["FIM_92C"]["components"] == [
        {
            "unit": "Avenger",
            "roles": [],
            "weapons": ["FIM_92C"],
            "envelope": {"rMaxKm": 40.0, "rMinKm": 1.0, "hMaxM": 9000},
            "gunAmmo": ["23mm"],
            "gunEnvelope": {"rMaxKm": 40.0},
        },
        {
            "unit": "Soldier stinger",
            "roles": [],
            "weapons": ["FIM_92C"],
            "envelope": {"rMaxKm": 40.0, "rMinKm": 1.0, "hMaxM": 9000},
        },
    ]
    tor = threats["SA9M330"]
    assert tor["components"] == [
        {
            "unit": "Tor",
            "roles": ["SAM SR", "SAM TR"],
            "rwrSymbol": "15",
            "weapons": ["SA9M330"],
            "envelope": {"rMaxKm": 40.0, "rMinKm": 1.0, "hMaxM": 9000},
        }
    ]
    assert tor["sensors"] == ["Tor radar"]
    assert threats["Shilka"]["components"] == [
        {
            "unit": "Shilka",
            "roles": ["SAM TR", "AAA"],
            "rwrSymbol": "A",
            "gunAmmo": ["23mm"],
            "gunEnvelope": {"rMaxKm": 40.0},
        }
    ]
    assert "ZU-23" not in threats  # guns without a radar


def test_thin_emitter_entries() -> None:
    threats = _threats()
    assert threats["1L13"] == {
        "id": "1L13",
        "kind": "ewr",
        "unit": "1L13",
        "rwrSymbol": "S",
        "sensors": ["1L13"],
    }
    assert threats["CVN"] == {
        "id": "CVN",
        "kind": "ship",
        "unit": "CVN",
        "rwrSymbol": "SS",
        "alic": ["403"],
    }
    assert threats["F-16C_50"]["sensors"] == ["APG-68"]


def test_nato_names_come_from_launchers_and_track_radars(
    capsys: pytest.CaptureFixture[str],
) -> None:
    threats = _threats()
    assert threats["SA2V755"]["natoDesignation"] == "SA-2"
    assert threats["SA5B27"]["natoDesignation"] == "SA-3"  # not its shared SR's SA-2
    assert threats["Dog Ear"]["natoDesignation"] == "Dog Ear"
    assert threats["Dog Ear"]["_source"] == {"natoDesignation": "hand-authored"}
    assert "natoDesignation" not in threats["FIM_92C"]
    err = capsys.readouterr().err
    assert "different NATO names" in err and "FIM_92C" in err
    assert "without a natoDesignation" in err and "'AIM_120'" in err


def test_overlay_overrides_nato_callouts() -> None:
    threats = _threats({"Soldier stinger": "Stinger", "Avenger": "Stinger"})
    assert threats["FIM_92C"]["natoDesignation"] == "Stinger"
    assert threats["FIM_92C"]["_source"] == {"natoDesignation": "hand-authored"}
    # One launcher still named by NATO.lua: the name is datamined.
    threats = _threats({"Soldier stinger": "Avenger"})
    assert threats["FIM_92C"]["natoDesignation"] == "Avenger"
    assert "_source" not in threats["FIM_92C"]


@pytest.mark.parametrize(
    ("names", "nato", "gaps", "why"),
    [
        ({"SNR": "SA-2"}, None, None, "NATO.lua already names it 'SA-2'"),
        ({"P19": "Flat Face"}, None, None, "no threat takes its name"),
        ({"64H6E sr": "Big Bird"}, None, None, "no threat takes its name"),
        ({}, {"Gone ln": "SA-99"}, None, "no db/Units record"),
        ({}, None, {"Truck": "x"}, "is now a unit type"),
        ({}, None, {"Gone ln": "x"}, "is not in NATO.lua"),
    ],
)
def test_stale_nato_name_entries_fail(
    names: dict[str, Any],
    nato: dict[str, Any] | None,
    gaps: dict[str, Any] | None,
    why: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        _threats(names, nato, gaps)
    assert why in capsys.readouterr().err


def test_nato_names_read_from_the_speech_protocol(tmp_path: Path) -> None:
    write(
        tmp_path / "Scripts/Speech/NATO.lua",
        "GroupThreats = {\n"
        "  displayTypeIds = { ['Tor 9A331'] = 2, ['SNR'] = 1, -- {\n"
        "    ['A \\'}\\' b'] = 1 },\n"
        "  sub = { displayTypeName = Phrases:new( {{_('SA-2'), 'SA-2'},\n"
        "                                          {_('SA-15'), 'SA-15'}}, 'AirDefence') }\n"
        "}\n",
    )
    assert nato_names(tmp_path) == {
        "A '}' b": "SA-2",
        "SNR": "SA-2",
        "Tor 9A331": "SA-15",
    }


def test_component_refs_are_checked() -> None:
    threats = _threats()
    data = {"threats": threats, "weapons": {m: {"id": m} for m in _MISSILES}}
    report = check_refs(data, entity_schema(), {})
    dangling = {(r.field, r.value) for r in report.dangling}
    assert ("components[].weapons[]", "SA5B55") not in dangling
    assert ("components[].gunAmmo[]", "23mm") in dangling  # no gun_ammo series
    assert ("unit", "CVN") in dangling  # no ships series
