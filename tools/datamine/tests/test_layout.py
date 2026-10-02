import json
from pathlib import Path
from typing import Any

import pytest
from conftest import entity_schema, write

from tools.datamine.check_refs import check_refs
from tools.datamine.common import (
    SERIES,
    latest_version,
    safe_name,
    sanitize_id,
    series_bytes,
    series_files,
    series_records,
    sync_tree,
    write_latest,
    yaml_key,
)
from tools.datamine.extract_units import index_attribute_units
from tools.datamine.validate_data import strays


def test_safe_name_keeps_what_file_systems_allow() -> None:
    assert safe_name("F-16C bl.52d") == "F-16C bl.52d"
    assert safe_name("F/A-18C") == "F_A-18C"
    assert safe_name('a:b*c?"<>|\\\x01') == "a_b_c_______"
    assert safe_name("Aux") == "_Aux"
    assert safe_name("con.x") == "_con.x"
    assert safe_name("Console") == "Console"
    assert safe_name("B.") == "B."
    assert safe_name("B. ", folder=True) == "B__"


def test_sanitize_id_hashes_only_on_collision() -> None:
    used: set[str] = set()
    assert sanitize_id("F/A-18C", used) == "F_A-18C"
    assert sanitize_id("F_A-18C", used).startswith("F_A-18C~")
    assert sanitize_id("", used).startswith("id~")


def test_series_files_claims_unsanitised_stems_first() -> None:
    records = {"F/A-18C": {"id": "F/A-18C"}, "F_A-18C": {"id": "F_A-18C"}}
    files = series_files(SERIES["aircraft"], records)
    assert files.pop("F_A-18C.json")["id"] == "F_A-18C"
    ((other, rec),) = files.items()
    assert other.startswith("F_A-18C~") and rec["id"] == "F/A-18C"


def test_airbases_grouped_by_theatre_and_named_by_name() -> None:
    records = {
        "Caucasus.1": {"id": "Caucasus.1", "theatre": "Caucasus", "name": "Batumi"},
        "Caucasus.2": {"id": "Caucasus.2", "theatre": "Caucasus", "name": "batumi"},
        "Caucasus.3": {"id": "Caucasus.3", "theatre": "Caucasus", "name": "Batumi"},
        "Syria.1": {"id": "Syria.1", "theatre": "Syria", "name": "Batumi"},
    }
    files = series_files(SERIES["airbases"], records)
    assert files["Caucasus/Batumi.json"]["id"] == "Caucasus.1"
    assert files["Syria/Batumi.json"]["id"] == "Syria.1"
    hashed = sorted(f for f in files if "~" in f)
    assert len(hashed) == 2 and len(set(files)) == 4


def test_beacons_grouped_by_theatre_and_type() -> None:
    rec = {
        "id": "Caucasus.airfield1_0",
        "theatre": "Caucasus",
        "typeName": "BEACON_TYPE_TACAN",
        "beaconId": "airfield1_0",
    }
    assert list(series_files(SERIES["beacons"], {rec["id"]: rec})) == [
        "Caucasus/BEACON_TYPE_TACAN/airfield1_0.json"
    ]


def test_sync_tree_removes_stale_files_and_dirs(tmp_path: Path) -> None:
    out = tmp_path / "airbases"
    write(out / "Caucasus.1.json", "{}")
    write(out / "Gone" / "X.json", "{}")
    rec = {"id": "Caucasus.1", "theatre": "Caucasus", "name": "Batumi"}
    files = series_bytes(SERIES["airbases"], {"Caucasus.1": rec})
    sync_tree(out, {out / rel: b for rel, b in files.items()})
    written = sorted(p.relative_to(out).as_posix() for p in out.rglob("*"))
    assert written == ["Caucasus", "Caucasus/Batumi.json"]


def manifest(version: str) -> bytes:
    return json.dumps({"dcsVersion": version}).encode()


def test_write_latest_replaces_the_previous_version(tmp_path: Path) -> None:
    write(tmp_path / "latest" / "weapons" / "stale.json", "{}")
    write(tmp_path / "latest" / "manifest.json", manifest("2.9.10.1").decode())
    assert latest_version(tmp_path) == "2.9.10.1"
    files = {"weapons/A.json": b"new", "manifest.json": manifest("2.9.11.1")}
    assert write_latest(tmp_path, files) == tmp_path / "latest"
    assert latest_version(tmp_path) == "2.9.11.1"
    assert sorted(p.name for p in (tmp_path / "latest" / "weapons").iterdir()) == [
        "A.json"
    ]
    assert strays(tmp_path) == []


def test_write_latest_refuses_an_older_version(tmp_path: Path) -> None:
    write(tmp_path / "latest" / "manifest.json", manifest("2.9.11.1").decode())
    with pytest.raises(SystemExit):
        write_latest(tmp_path, {"manifest.json": manifest("2.9.10.1")})
    with pytest.raises(SystemExit):
        write_latest(tmp_path, {"weapons/A.json": b"{}"})
    assert latest_version(tmp_path) == "2.9.11.1"


def test_only_latest_belongs_in_the_data_root(tmp_path: Path) -> None:
    write(tmp_path / "latest" / "manifest.json", "{}")
    write(tmp_path / "2.9.9.1" / "manifest.json", "{}")
    assert strays(tmp_path) == ["2.9.9.1"]


def test_series_records_take_files_at_the_series_depth() -> None:
    tree = {
        "manifest.json": 0,
        "weapons/A.json": 1,
        "weapons/sub/B.json": 2,
        "airbases/Caucasus/Batumi.json": 3,
        "airbases/Kutaisi.json": 4,
    }
    assert series_records(tree) == {
        "weapons": {"A": 1},
        "airbases": {"Caucasus/Batumi": 3},
    }


def test_yaml_keys_quote_what_yaml_would_misread() -> None:
    assert yaml_key("wsType_Bomb") == "wsType_Bomb"
    assert yaml_key("On") == '"On"'
    assert yaml_key("DcsDb.X") == '"DcsDb.X"'
    assert yaml_key("NEW ZEALAND") == '"NEW ZEALAND"'
    assert yaml_key("NEW ZEALAND", spaces=True) == "NEW ZEALAND"
    assert yaml_key(" X", spaces=True) == '" X"'


def test_attribute_units_index_and_refs() -> None:
    series: dict[str, dict[str, dict[str, Any]]] = {
        "aircraft": {"F-15C": {"id": "F-15C", "attributes": ["Air", "Fighters"]}},
        "ground_vehicles": {"Train": {"id": "Train", "attributes": ["Air"]}},
        "personnel": {},
        "ships": {},
        "structures": {"Train": {"id": "Train", "attributes": ["Air"]}},
        "attributes": {"Air": {"id": "Air"}, "Fighters": {"id": "Fighters"}},
    }
    index_attribute_units(series)
    assert series["attributes"]["Air"]["units"] == {
        "aircraft": ["F-15C"],
        "groundVehicles": ["Train"],
        "structures": ["Train"],
    }
    series["attributes"]["Fighters"]["units"]["ships"] = ["Gone"]
    report = check_refs(series, entity_schema(), {})
    assert [(r.stem, r.field, r.value) for r in report.dangling] == [
        ("Fighters", "units.ships[]", "Gone")
    ]
