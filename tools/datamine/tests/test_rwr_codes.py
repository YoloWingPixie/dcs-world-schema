from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from conftest import write

from tools.datamine import extract_rwr_codes as rc
from tools.datamine.rwr import Key, WsTypeIds

COCKPIT = "Scripts/Aircrafts/_Common/Cockpit"
SAM = f"dofile('{COCKPIT}/wsTypes_SAM.lua')\n"


def _install(tmp_path: Path, modules: bool = True) -> Path:
    write(
        tmp_path / COCKPIT / "wsTypes_SAM.lua",
        "SAM_TR = {2, 16, 101, 7}\nSAM_SR = {2, 16, 101, 8}\n",
    )
    write(
        tmp_path / COCKPIT / "AN_ALR_SymbolsBase.lua",
        SAM + 'symbols = { {SAM_TR, "HK"} }\nsymbols_strings = { ["sr"] = "S" }\n',
    )
    write(
        tmp_path / COCKPIT / "AN_ALR_HarmIDs.lua",
        SAM
        + 'symbolID = { {203, SAM_TR} }\nsymbols_stringsID = { {204, "sr", "gone"} }\n',
    )
    write(
        tmp_path / COCKPIT / "RU_ELINT_Symbols.lua",
        SAM + "local DNL = true\n"
        'symbols = { {SAM_TR, "S", DNL} }\nsymbols_strings = { {"sr", "S"} }\n',
    )
    write(
        tmp_path / COCKPIT / "SPO_15_symbols.lua",
        SAM + "local SPO_15_types = { P = 1, H = 3 }\n"
        "local M = { M1 = tonumber('001000', 2) }\n"
        "spo_15_symbols = { {type = SAM_TR, symbol = SPO_15_types.H},\n"
        '  {name = "sr", symbol = SPO_15_types.P, modes = {M.M1}} }\n',
    )
    if modules:
        write(
            tmp_path / rc.C130J,
            SAM + 'f_ = {}\nf_["H+hat"] = "5"\nf_["S"] = "L"\n'
            'symbols = { {SAM_TR, f_["H+hat"]} }\n'
            'symbols_strings = { ["sr"] = f_["S"] }\n',
        )
        write(
            tmp_path / rc.F15E,
            'rwr_codes = {}\nrwr_codes["sr"] = { code = "SR", coal = 2, desc = "Search" }\n',
        )
        write(
            tmp_path / rc.M2000C,
            "local DOT = '.'\nrwr_codes = {}\n"
            'rwr_codes["sr"] = { symb = DOT, coal = 2, desc = "Search" }\n',
        )
    return tmp_path


_IDS = WsTypeIds(
    units={"tr": [(2, 16, 101, 7)], "sr": [(2, 16, 101, 8)]},
    stores={},
    projectiles={},
    ammunition={},
)
_THREATS: dict[str, dict[str, Any]] = {
    "MIM": {"id": "MIM", "components": [{"unit": "tr"}, {"unit": "sr"}]},
}


def _records(tmp_path: Path) -> dict[str, dict[str, Any]]:
    rows = rc.read_rows(_install(tmp_path))
    return rc.build_rwr_codes(rows, {"tr", "sr"}, set(), _IDS, _THREATS)


def test_every_family_table_entry_is_a_row(tmp_path: Path) -> None:
    out = _records(tmp_path)
    assert {
        (r["family"], r["sourceTable"], r["key"], r["value"]) for r in out.values()
    } == {
        ("AN/ALR", "symbols", "SAM_TR", "HK"),
        ("AN/ALR", "symbols_strings", "sr", "S"),
        ("AN/ALR", "symbolID", "SAM_TR", "203"),
        ("AN/ALR", "symbols_stringsID", "sr", "204"),
        ("AN/ALR", "symbols_stringsID", "gone", "204"),
        ("RU ELINT", "symbols", "SAM_TR", "S"),
        ("RU ELINT", "symbols_strings", "sr", "S"),
        ("SPO-15", "spo_15_symbols", "SAM_TR", "H"),
        ("SPO-15", "spo_15_symbols", "sr", "P"),
        ("C-130J CDMS", "symbols", "SAM_TR", "H+hat"),
        ("C-130J CDMS", "symbols_strings", "sr", "S"),
        ("F-15E ALR-56C", "rwr_codes", "sr", "SR"),
        ("M-2000C SERVAL", "rwr_codes", "sr", "."),
    }


def test_rows_join_units_and_threats(tmp_path: Path) -> None:
    out = _records(tmp_path)
    alic = out["an-alr:symbolID:SAM_TR:203"]
    assert alic == {
        "id": "an-alr:symbolID:SAM_TR:203",
        "family": "AN/ALR",
        "kind": "alic",
        "value": "203",
        "sourceFile": f"{COCKPIT}/AN_ALR_HarmIDs.lua",
        "sourceTable": "symbolID",
        "key": "SAM_TR",
        "keyType": "global",
        "wsType": [2, 16, 101, 7],
        "units": ["tr"],
        "threats": ["MIM"],
    }
    gone = out["an-alr:symbols_stringsID:gone:204"]
    assert "units" not in gone and "threats" not in gone
    assert out["f-15e-alr-56c:rwr_codes:sr:SR"]["description"] == "Search"


def test_repeated_entries_get_distinct_ids() -> None:
    row = rc.Row("RU ELINT", "symbols", Path("x.lua"), Key(name="sr"), "S")
    out = rc.build_rwr_codes([row, row], {"sr"}, set(), _IDS, {})
    assert list(out) == ["ru-elint:symbols:sr:S", "ru-elint:symbols:sr:S#2"]


def test_missing_module_tables_are_skipped(tmp_path: Path) -> None:
    rows = rc.read_rows(_install(tmp_path, modules=False))
    assert {r.family for r in rows} == {"AN/ALR", "RU ELINT", "SPO-15"}


def test_missing_common_table_fails(tmp_path: Path) -> None:
    (_install(tmp_path) / COCKPIT / "SPO_15_symbols.lua").unlink()
    with pytest.raises(SystemExit):
        rc.read_rows(tmp_path)


def test_hts_classes_apply_to_an_alr_rows_and_threats(tmp_path: Path) -> None:
    out = _records(tmp_path)
    table = [{"class": 7, "had": "HK", "name": "Hawk", "units": ["tr"]}]
    classes = rc.hts_classes(table, {"tr", "sr"}, out)
    threats: dict[str, dict[str, Any]] = {
        "MIM": {"id": "MIM", "components": [{"unit": "tr"}, {"unit": "sr"}]}
    }
    assert rc.apply_hts_classes(classes, out, threats) == []
    assert out["an-alr:symbols:SAM_TR:HK"]["htsClass"] == 7
    assert out["an-alr:symbols:SAM_TR:HK"]["_source"] == {"htsClass": "hand-authored"}
    assert out["an-alr:symbolID:SAM_TR:203"]["htsClass"] == 7
    assert "htsClass" not in out["ru-elint:symbols:SAM_TR:S"]
    assert threats["MIM"]["components"][0]["htsClass"] == 7
    assert "htsClass" not in threats["MIM"]["components"][1]


@pytest.mark.parametrize(
    "row",
    [
        {"class": 7, "had": "S", "name": "wrong code", "units": ["tr"]},
        {"class": 7, "had": "HK", "name": "no unit", "units": ["nope"]},
        {"class": 7, "had": "HK", "name": "empty", "units": []},
    ],
)
def test_hts_class_overlay_is_checked(tmp_path: Path, row: dict[str, Any]) -> None:
    out = _records(tmp_path)
    with pytest.raises(SystemExit):
        rc.hts_classes([row], {"tr", "sr"}, out)


def test_hts_dcs_symbol_overrides_the_manual_code(tmp_path: Path) -> None:
    out = _records(tmp_path)
    row = {"class": 5, "had": "HP", "dcsSymbol": "HK", "name": "x", "units": ["tr"]}
    assert rc.hts_classes([row], {"tr", "sr"}, out) == {"tr": 5}


def test_hts_unit_in_two_classes_fails(tmp_path: Path) -> None:
    out = _records(tmp_path)
    rows = [
        {"class": 1, "had": "HK", "name": "a", "units": ["tr"]},
        {"class": 2, "had": "HK", "name": "b", "units": ["tr"]},
    ]
    with pytest.raises(SystemExit):
        rc.hts_classes(rows, {"tr", "sr"}, out)
