"""id_types: the DcsId.* types from a small data dir."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.datamine import id_types
from tools.datamine.common import generated_drift

RECORDS: dict[str, Any] = {
    "manifest.json": {"dcsVersion": "9.9.9.1"},
    "aircraft/F-16C_50.json": {
        "id": "F-16C_50",
        "kind": "fixedwing",
        "displayName": "F-16CM bl.50",
    },
    "aircraft/F-14A.json": {"id": "F-14A", "kind": "fixedwing", "displayName": "F-14A"},
    "aircraft/F-14A-95.json": {
        "id": "F-14A-95",
        "kind": "fixedwing",
        "displayName": "F-14A",
    },
    "aircraft/UH-1H.json": {"id": "UH-1H", "kind": "rotary", "displayName": "UH-1H"},
    "ground_vehicles/M-1.json": {"id": "M-1", "displayName": "MBT M1A2 Abrams"},
    "ships/CVN_71.json": {"id": "CVN_71", "displayName": "CVN-71"},
    "structures/FARP.json": {"id": "FARP", "displayName": "FARP"},
    "personnel/Airboss.json": {"id": "Airboss", "displayName": "Carrier Airboss"},
    "weapons/AIM_120C.json": {"id": "AIM_120C", "displayName": "AIM-120C"},
    "gun_ammo/M61_20_HE.json": {"id": "M61_20_HE"},
    "airbases/Caucasus/Anapa.json": {
        "theatre": "Caucasus",
        "name": "Anapa-Vityazevo",
        "airdromeId": 12,
    },
    "airbases/Nevada/Nellis.json": {
        "theatre": "Nevada",
        "name": "Nellis",
        "airdromeId": 4,
    },
    "attributes/Planes.json": {"id": "Planes"},
    "sensors/AN_APG-68.json": {"id": "AN/APG-68"},
    "tasks/Anti-ship Strike.json": {
        "id": "Anti-ship Strike",
        "worldId": 30,
        "oldId": "Antiship Strike",
    },
    "tasks/CAP.json": {"id": "CAP", "worldId": 11},
    "skills/Random.json": {"id": "Random", "worldId": 4},
    "formations/TRAIL.json": {"id": "TRAIL", "worldId": 2},
    "options/FORMATION.json": {
        "id": "FORMATION",
        "valueSets": [{"categories": ["plane"]}, {"categories": ["helicopter"]}],
    },
}


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    for rel, rec in RECORDS.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(json.dumps(rec), encoding="utf-8")
    return tmp_path


def _types(files: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for text in files.values():
        out.update(yaml.safe_load(text)["types"])
    return out


def test_generated_types(data_dir: Path, tmp_path: Path) -> None:
    files = id_types.generate(data_dir)
    assert sorted(files) == [
        "Airbases.generated.yaml",
        "Misc.generated.yaml",
        "Units.generated.yaml",
        "Weapons.generated.yaml",
    ]
    types = _types(files)
    # Keyed by display name; by id where records share one.
    assert types["DcsId.AircraftType"]["values"] == {
        "F-14A": "F-14A",
        "F-14A-95": "F-14A-95",
        "F-16CM bl.50": "F-16C_50",
    }
    assert types["DcsId.UnitType"]["anyOf"] == [
        "DcsId.AircraftType",
        "DcsId.HelicopterType",
        "DcsId.GroundUnitType",
        "DcsId.ShipType",
    ]
    assert "DcsId.StructureType" in types["DcsId.StaticType"]["anyOf"]
    assert types["DcsId.WeaponType"]["values"] == {
        "AIM-120C": "AIM_120C",
        "M61_20_HE": "M61_20_HE",
    }
    assert types["DcsId.Theatre.Caucasus.AirdromeId"]["values"] == {
        "Anapa-Vityazevo": 12
    }
    assert types["DcsId.AirbaseName"]["anyOf"] == [
        "DcsId.Theatre.Caucasus.AirbaseName",
        "DcsId.Theatre.Nevada.AirbaseName",
    ]
    assert types["DcsId.MainTask"]["values"] == {
        "CAP": "CAP",
        "Anti-ship Strike": "Antiship Strike",
    }
    attributes = types["DcsId.Attribute"]["values"]
    assert attributes["Planes"] == "Planes"
    assert attributes["AA Missiles (weapons)"] == "AA Missiles"
    assert types["DcsId.FormationValue"]["anyOf"] == [
        "DcsTask.OptionValue.FORMATION_helicopter",
        "DcsTask.OptionValue.FORMATION_plane",
    ]
    assert types["DcsId.FormationId"]["values"] == {"TRAIL": 2}
    out = tmp_path / "ids"
    id_types.write(files, out)
    assert generated_drift(out, files, id_types.SUFFIX) == []


def test_member_cap_and_key_clash_fail(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(id_types, "MAX_MEMBERS", 2)
    with pytest.raises(SystemExit):
        id_types.generate(data_dir)
    with pytest.raises(SystemExit):  # a display name that is another's id
        id_types.keyed([("A", "B"), ("B", None)])


def test_extra_attribute_in_the_series_fails(data_dir: Path) -> None:
    (data_dir / "attributes" / "AA Missiles.json").write_text(
        json.dumps({"id": "AA Missiles"}), encoding="utf-8"
    )
    with pytest.raises(SystemExit):
        id_types.generate(data_dir)
