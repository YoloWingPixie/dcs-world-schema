from pathlib import Path
from typing import Any

import pytest
from conftest import entity_schema, write
from jsonschema import Draft7Validator

from tools.datamine import extract_db_tables as dbt
from tools.datamine.common import SERIES, WRITE_WHOLE
from tools.datamine.dcs_constants import Constants
from tools.datamine.extract_radios import default_radio
from tools.datamine.lua_reader import LuaReader
from tools.export_jsonschema import schema_for

CONSTANTS = Constants(
    {
        "country": {"RUSSIA": 0, "UKRAINE": 1, "USA": 2, "UK": 4},
        "MODULATION": {"MODULATION_AM": 0, "MODULATION_FM": 1},
    }
)
COUNTRIES = [
    {"Name": "Russia", "WorldID": 0},
    {"Name": "Ukraine", "WorldID": 1},
    {"Name": "USA", "WorldID": 2},
    {"Name": "UK", "WorldID": 4},
]
UNITS: dict[str, dict[str, Any]] = {
    "A-10C": {
        "Tasks": [
            {"Name": "CAS", "WorldID": 31},
            {"Name": "Ground Attack", "WorldID": 32},
        ],
        "DefaultTask": {"Name": "CAS", "WorldID": 31},
    },
    "E-3A": {"Tasks": [{"Name": "AWACS", "WorldID": 14}]},
    "S-3B": {
        "Tasks": [
            {"Name": "Anti-ship Strike", "WorldID": 30, "OldID": "Antiship Strike"}
        ]
    },
}


def _dump(g: Path) -> Path:
    write(
        g / "db/Callnames.lua",
        '_G["db"]["Callnames"] = {\n'
        '  [0] = { Air = { { Name = "101", WorldID = 1 } } },\n'
        '  [2] = { Air = { { Name = "Springfield", WorldID = 2 }, { Name = "Enfield", WorldID = 1 } },\n'
        '          AWACS = { { Name = "Overlord", WorldID = 1 } } },\n'
        '  [4] = { AWACS = { { Name = "Magic", WorldID = 1 } } },\n'
        "}",
    )
    write(
        g / "db/callnamesRussia.lua",
        '_G["db"]["callnamesRussia"] = { "Russia", "Ukraine" }',
    )
    write(g / "db/DefaultCountry.lua", '_G["db"]["DefaultCountry"] = { [1] = 0 }')
    write(
        g / "db/FormationID.lua",
        '_G["db"]["FormationID"] = { NO_FORMATION = 0, FINGER_FOUR = 6, HEL_WEDGE = 8,'
        " COMBAT_BOX = 15, TRAIL = 2, MAX = 19 }",
    )
    write(
        g / "db/Units/Skills.lua",
        '_G["db"]["Units"]["Skills"] = { { Name = "Average", WorldID = 0 }, { Name = "Good", WorldID = 1 } }',
    )
    write(
        g / "db/Targets.lua",
        '_G["db"]["Targets"] = { Tasks = { [31] = { Planes = true, Point = false }, [35] = {} } }',
    )
    write(
        g / "FuzeDescriptions.lua",
        '_G["FuzeDescriptions"] = { M905 = "Mechanical, impact", Mk339Mod1 = "Mechanical, time" }',
    )
    write(
        g / "SchemeFuzeParameters.lua",
        '_G["SchemeFuzeParameters"] = {\n'
        "  Mk339Mod1 = { ED = { is_multidelay = true, default_delays = { 1, 2 } } },\n"
        "  Z3 = { default_arm_delays = { 0.5 } },\n"
        "}",
    )
    list_ = '_G["db"]["Formations"]["{0}"]["list"]["#Index"] = {1}'
    write(
        g / "db/Formations/plane/list/Finger Four.lua",
        list_.format(
            "plane",
            '{ CLSID = "{F4}", Name = "Finger Four", WorldID = 6, defaultVariantIndex = 2,'
            ' zInverse = false, variants = { { name = "Close", positions = {'
            " { x = -48, y = 0, z = 58 } } } } }",
        ),
    )
    write(
        g / "db/Formations/helicopter/list/Wedge.lua",
        list_.format(
            "helicopter",
            '{ Name = "Wedge", WorldID = 8, positions = { { x = -49, y = 5, z = -49 } } }',
        ),
    )
    write(
        g / "db/Formations/big_formations/list/Combat Box.lua",
        list_.format(
            "big_formations",
            '{ Name = "Combat Box", WorldID = 15, positions = { { name = "Position in Box",'
            ' positions = { { name = "Right", positions = { x = -80, y = 50, z = 120 } } } } } }',
        ),
    )
    return g


def _build(g: Path) -> dict[str, Any]:
    reader = LuaReader(g)
    return dbt.build(
        reader, g, dbt.read_formations(reader, g), COUNTRIES, UNITS, CONSTANTS
    )


def _assert_valid(series: dict[str, Any]) -> None:
    doc = entity_schema()
    for name, records in series.items():
        v = Draft7Validator(schema_for(doc, SERIES[name].type_name))
        for rec in records.values():
            errors = [e.message for e in v.iter_errors(rec)]
            assert not errors, (name, rec, errors)


def test_series_from_dump(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    series = _build(_dump(tmp_path / "_G"))
    assert set(series) == set(dbt.SERIES_NAMES)
    _assert_valid(series)

    cs = series["callsigns"]
    assert cs["USA"]["categories"] == [
        {
            "category": "AWACS",
            "country": 2,
            "callsigns": [{"id": 1, "name": "Overlord"}],
        },
        {
            "category": "Air",
            "country": 2,
            "callsigns": [
                {"id": 2, "name": "Springfield"},
                {"id": 1, "name": "Enfield"},
            ],
        },
    ]
    # Ukraine falls back to Russia (DefaultCountry), the UK to USA per category.
    assert cs["Ukraine"]["fallbackCountry"] == 0 and cs["Ukraine"]["numeric"] is True
    assert [c["category"] for c in cs["Ukraine"]["categories"]] == ["Air"]
    uk = {c["category"]: c["country"] for c in cs["UK"]["categories"]}
    assert uk == {"AWACS": 4, "Air": 2} and cs["UK"]["numeric"] is False
    assert cs["UK"]["countryName"] == "UK"

    fm = series["formations"]
    assert set(fm) == {"FINGER_FOUR", "HEL_WEDGE", "COMBAT_BOX"}
    assert fm["FINGER_FOUR"]["variants"][0] == {
        "name": "Close",
        "positions": [{"x": -48, "y": 0, "z": 58}],
    }
    assert fm["FINGER_FOUR"]["defaultVariantIndex"] == 2
    assert fm["FINGER_FOUR"]["zInverse"] is False
    assert fm["HEL_WEDGE"]["group"] == "helicopter"
    assert fm["HEL_WEDGE"]["variants"] == [
        {"positions": [{"x": -49, "y": 5, "z": -49}]}
    ]
    assert fm["COMBAT_BOX"]["variants"] == [
        {
            "name": "Position in Box",
            "positions": [{"name": "Right", "x": -80, "y": 50, "z": 120}],
        }
    ]
    assert "['TRAIL']" in capsys.readouterr().err

    tasks = series["tasks"]
    assert tasks["CAS"] == {
        "id": "CAS",
        "worldId": 31,
        "targets": [
            {"category": "Planes", "default": True},
            {"category": "Point", "default": False},
        ],
    }
    assert tasks["AWACS"] == {"id": "AWACS", "worldId": 14}
    assert tasks["Anti-ship Strike"]["oldId"] == "Antiship Strike"
    assert series["skills"]["Good"] == {"id": "Good", "worldId": 1}

    fz = series["fuzes"]
    assert fz["M905"] == {"id": "M905", "description": "Mechanical, impact"}
    assert fz["Mk339Mod1"]["parameters"] == [
        {"mode": "ED", "name": "default_delays", "numbers": [1, 2]},
        {"mode": "ED", "name": "is_multidelay", "flag": True},
    ]
    assert fz["Z3"]["parameters"] == [{"name": "default_arm_delays", "numbers": [0.5]}]


def test_dump_missing_a_table_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    g = _dump(tmp_path / "_G")
    (g / "db/FormationID.lua").unlink()
    with pytest.raises(SystemExit):
        _build(g)
    assert "lacks db/FormationID.lua" in capsys.readouterr().err


def test_required_tables_are_written_whole() -> None:
    assert dbt.table_file(dbt.REQUIRED["skills"]) == "db/Units/Skills.lua"
    assert set(dbt.REQUIRED.values()) <= set(WRITE_WHOLE)


def test_formation_without_formation_id_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    g = _dump(tmp_path / "_G")
    write(g / "db/FormationID.lua", '_G["db"]["FormationID"] = { FINGER_FOUR = 6 }')
    with pytest.raises(SystemExit):
        _build(g)
    assert "has no db.FormationID name" in capsys.readouterr().err


def test_default_radio_from_human_radio() -> None:
    unit = {
        "HumanRadio": {
            "frequency": 251,
            "modulation": 0,
            "minFrequency": 100,
            "maxFrequency": 399.975,
            "editable": True,
        }
    }
    radio = default_radio("A-10C", unit, CONSTANTS)
    assert radio == {
        "frequencyMHz": 251,
        "modulation": 0,
        "modulationName": "MODULATION_AM",
        "minMHz": 100,
        "maxMHz": 399.975,
        "editable": True,
    }
    doc = entity_schema()
    assert not list(
        Draft7Validator(schema_for(doc, "Entity.DefaultRadio")).iter_errors(radio)
    )
    assert default_radio("X", {}, CONSTANTS) is None
    with pytest.raises(SystemExit):
        default_radio("X", {"HumanRadio": {"frequency": 251}}, CONSTANTS)
