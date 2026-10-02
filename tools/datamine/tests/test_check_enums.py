"""check_enums: each check on a small spec, data dir and API dump."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools.datamine import check_enums


def _enum(values: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "enum", "description": "x.", "values": values}


def _dump(globals_: dict[str, Any]) -> dict[str, Any]:
    def node(v: Any) -> dict[str, Any]:
        if isinstance(v, dict):
            members = [
                {"key": k, "keyType": "string", "value": node(x)} for k, x in v.items()
            ]
            return {"type": "table", "members": members}
        return {"type": "number" if isinstance(v, int) else "string", "value": v}

    return {
        "format": "dcs-api-dump/2",
        "env": "scripting",
        "status": "ok",
        "globals": {k: node(v) for k, v in globals_.items()},
    }


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    files: dict[str, Any] = {
        "api/scripting.json": _dump(
            {
                "AI": {
                    "Skill": {"GOOD": "Good"},
                    "Task": {"WeaponExpend": {"ONE": "One"}},
                    "Option": {"Ground": {"val": {"ROE": {"OPEN_FIRE": 2}}}},
                }
            }
        ),
        "skills/Good.json": {"id": "Good", "worldId": 1},
        "skills/Random.json": {"id": "Random", "worldId": 4},
        "actions/BOMBING.json": {
            "kind": "task",
            "dcsId": "Bombing",
            "params": [
                {
                    "name": "expend",
                    "missionStrings": [
                        {"value": "Auto", "count": 3},
                        {"value": "One", "count": 1},
                    ],
                }
            ],
        },
        "options/ROE.json": {
            "id": "ROE",
            "categories": ["vehicle"],
            "valueSets": [{"values": [{"value": 0}, {"value": 2}]}],
        },
    }
    for rel, doc in files.items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(json.dumps(doc), encoding="utf-8")
    return d


def _types(**changes: Any) -> dict[str, Any]:
    types = {
        "AI.Skill": _enum({"GOOD": "Good"}),
        "AI.Task.WeaponExpend": _enum({"ONE": "One"}),
        "DcsTask.Task.BombingParams": {
            "kind": "record",
            "fields": {"expend": {"type": 'AI.Task.WeaponExpend | "Auto"'}},
        },
        "DcsTask.OptionValue.ROE": _enum({"WEAPON_FREE": 0, "OPEN_FIRE": 2}),
        "BeaconType": _enum({"BEACON_TYPE_TACAN": 4}),
        "Entity.BeaconType": _enum({"BEACON_TYPE_TACAN": 4}),
        "RadioModulation": _enum({"AM": 0}),
        "Entity.RadioModulation": _enum({"MODULATION_AM": 0}),
        "Unit.RadarType": _enum({"AS": 0}),
        "Entity.RadarType": _enum({"RADAR_AS": 0, "RADAR_SS": 1}),
    }
    return {**types, **changes}


ALLOWED = {
    "c skills: 'Random' not admitted by AI.Skill": "ME only.",
    "d DcsTask.OptionValue.ROE: 0 (WEAPON_FREE) not in AI.Option.Ground.val.ROE": (
        "ME only."
    ),
}


def _check(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, Any] | None = None,
    me_values: dict[str, str] | None = None,
) -> list[str]:
    monkeypatch.setattr(check_enums, "ALLOWED", ALLOWED)
    monkeypatch.setattr(
        check_enums,
        "ME_VALUES",
        {"skills": "AI.Skill"} if me_values is None else me_values,
    )
    return check_enums.check({"types": _types(**(changes or {}))}, data_dir)


def test_agreeing_enums_pass(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _check(data_dir, monkeypatch) == []


@pytest.mark.parametrize(
    ("changes", "finding"),
    [
        (
            {"AI.Skill": _enum({"GOOD": "Good", "BEST": "Best"})},
            "a AI.Skill.BEST: schema 'Best', DCS 'missing'",
        ),
        (
            {"BeaconType": _enum({"BEACON_TYPE_TACAN": 5})},
            "b BeaconType.BEACON_TYPE_TACAN: 5, Entity.BeaconType 4",
        ),
        (
            {"RadioModulation": _enum({})},
            "b RadioModulation.AM: 'missing', Entity.RadioModulation 0",
        ),
        (
            {
                "DcsTask.Task.BombingParams": {
                    "kind": "record",
                    "fields": {"expend": {"type": "AI.Task.WeaponExpend"}},
                }
            },
            "c DcsTask.Task.BombingParams.expend: 'Auto' (3 uses) not admitted by "
            "AI.Task.WeaponExpend",
        ),
        (
            {"DcsTask.OptionValue.ROE": _enum({"WEAPON_FREE": 0})},
            "d DcsTask.OptionValue.ROE: lacks AI.Option.Ground.val.ROE 2 (OPEN_FIRE)",
        ),
    ],
)
def test_disagreements_fail(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, Any],
    finding: str,
) -> None:
    assert finding in _check(data_dir, monkeypatch, changes)


def test_subset_family_and_open_types_pass(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    params = {
        "kind": "record",
        "fields": {"expend": {"type": "AI.Task.WeaponExpend | string"}},
    }
    assert _check(data_dir, monkeypatch, {"DcsTask.Task.BombingParams": params}) == []


def test_stale_allowance_fails(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _check(data_dir, monkeypatch, me_values={}) == [
        "stale ALLOWED entry: c skills: 'Random' not admitted by AI.Skill"
    ]


def test_record_field_target(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    unit = {"kind": "record", "fields": {"skill": {"type": 'AI.Skill | "Random"'}}}
    found = _check(data_dir, monkeypatch, {"Unit": unit}, {"skills": "Unit.skill"})
    assert found == ["stale ALLOWED entry: c skills: 'Random' not admitted by AI.Skill"]
