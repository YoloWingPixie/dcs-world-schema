"""The hand tables of tools/package/tables.py: the TACAN plan must reproduce
the beacons, country aliases must not collide; stale entries fail."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from tools.datamine import overlays
from tools.package import tables

PLAN: dict[str, Any] = {
    "channels": {"first": 1, "last": 126},
    "bands": ["X", "Y"],
    "interrogationMHz": {"base": 1025},
    "replyOffsetMHz": {
        "X": [
            {"from": 1, "to": 63, "offset": -63},
            {"from": 64, "to": 126, "offset": 63},
        ],
        "Y": [
            {"from": 1, "to": 63, "offset": 63},
            {"from": 64, "to": 126, "offset": -63},
        ],
    },
    "vhfPairing": {
        "ranges": [
            {"from": 17, "to": 59, "baseKHz": 108000},
            {"from": 70, "to": 126, "baseKHz": 112300},
        ],
        "stepKHz": 100,
        "bandOffsetKHz": {"X": 0, "Y": 50},
    },
    "beaconTypes": ["BEACON_TYPE_TACAN", "BEACON_TYPE_VORTAC"],
}
BEACONS: dict[str, dict[str, Any]] = {
    "C.batumi": {"typeName": "BEACON_TYPE_TACAN", "channel": 16, "frequencyHz": 977e6},
    "C.kobuleti": {
        "typeName": "BEACON_TYPE_TACAN",
        "channel": 67,
        "frequencyHz": 1154e6,
    },
    "N.las": {"typeName": "BEACON_TYPE_VORTAC", "channel": 116, "frequencyHz": 116.9e6},
    "G.wrb": {
        "typeName": "BEACON_TYPE_VORTAC",
        "channel": 104,
        "frequencyHz": 115.75e6,
    },
    "N.lsv": {"typeName": "BEACON_TYPE_TACAN", "channel": 12},
    "S.ndb": {"typeName": "BEACON_TYPE_HOMER", "channel": 0, "frequencyHz": 310e3},
}
COUNTRIES = {
    "2": {"id": 2, "name": "USA", "idName": "USA", "shortName": "USA"},
    "4": {"id": 4, "name": "UK", "idName": "UK", "shortName": "UK"},
    "80": {"id": 80, "name": "CJTF Blue", "idName": "CJTF_BLUE", "shortName": "BLUE"},
}


def _build(
    monkeypatch: pytest.MonkeyPatch, **overrides: Any
) -> tuple[dict[str, Any], list[str]]:
    """``overrides``: ``exceptions``, ``plan``, ``aliases`` or ``every``
    tables."""
    base: dict[tuple[str, str], Any] = {
        ("beacons", "tacanPlan"): overrides.get("plan", PLAN),
        ("beacons", "tacanPlanExceptions"): overrides.get("exceptions", {}),
        ("countries", "aliases"): overrides.get("aliases", {"USA": ["United States"]}),
        ("countries", "allLiveries"): overrides.get("every", ["BLUE"]),
    }
    monkeypatch.setattr(overlays, "load", lambda _v: overlays.Overlays([], base))
    return tables.build({"beacons": BEACONS, "countries": COUNTRIES}, "test")


def test_build_and_report(monkeypatch: pytest.MonkeyPatch) -> None:
    payload, report = _build(monkeypatch)
    assert payload == {
        "tacan": PLAN,
        "countryAliases": {"united states": 2},
        "allLiveryCountries": {"80": "BLUE"},
    }
    assert report == [
        "tacan plan: VHF pairing X 1, VHF pairing Y 1, channel only 1, reply X 2, listed exceptions 0",
        "country aliases: 1",
        "all-livery countries: 1",
    ]


@pytest.mark.parametrize("every", [["RED"], [], "BLUE"])
def test_all_livery_countries_need_known_short_names(
    monkeypatch: pytest.MonkeyPatch, every: Any
) -> None:
    with pytest.raises(SystemExit):
        _build(monkeypatch, every=every)


def test_plan_arithmetic() -> None:
    assert tables.reply_mhz(PLAN, 1, "X") == 962
    assert tables.reply_mhz(PLAN, 126, "X") == 1213
    assert tables.reply_mhz(PLAN, 1, "Y") == 1088
    assert tables.reply_mhz(PLAN, 64, "Y") == 1025
    assert tables.vhf_khz(PLAN, 17, "X") == 108000
    assert tables.vhf_khz(PLAN, 59, "Y") == 112250
    assert tables.vhf_khz(PLAN, 126, "Y") == 117950
    assert tables.vhf_khz(PLAN, 65, "X") is None


def test_unlisted_mismatch_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(
        BEACONS,
        "F.bad",
        {"typeName": "BEACON_TYPE_TACAN", "channel": 31, "frequencyHz": 1e6},
    )
    with pytest.raises(SystemExit):
        _build(monkeypatch)
    assert "cannot reproduce 1 beacon" in capsys.readouterr().err


def test_listed_mismatch_passes_and_stale_exception_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        BEACONS,
        "F.bad",
        {"typeName": "BEACON_TYPE_TACAN", "channel": 31, "frequencyHz": 1e6},
    )
    _, report = _build(monkeypatch, exceptions={"F.bad": "1 MHz"})
    assert report[0].endswith("listed exceptions 1")
    with pytest.raises(SystemExit):
        _build(monkeypatch, exceptions={"F.bad": "1 MHz", "C.batumi": "matches"})
    with pytest.raises(SystemExit):
        _build(monkeypatch, exceptions={"F.bad": "1 MHz", "Z.gone": "no beacon"})


def test_channel_outside_plan_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        BEACONS, "F.far", {"typeName": "BEACON_TYPE_TACAN", "channel": 127}
    )
    with pytest.raises(SystemExit):
        _build(monkeypatch)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p["replyOffsetMHz"]["X"].pop(),
        lambda p: p["vhfPairing"]["bandOffsetKHz"].pop("Y"),
        lambda p: p.update(beaconTypes=["BEACON_TYPE_NOPE"]),
        lambda p: p["vhfPairing"]["ranges"].append(
            {"from": 120, "to": 130, "baseKHz": 1}
        ),
        lambda p: p["replyOffsetMHz"]["Y"].append({"from": 5, "to": 5, "offset": 0}),
        lambda p: p["replyOffsetMHz"]["X"][0].update(offset=-63.5),
        lambda p: p["replyOffsetMHz"]["X"][0].update(to=0),
        lambda p: p["channels"].update(last="126"),
        lambda p: p.update(bands="XY"),
        lambda p: p["interrogationMHz"].update(base=1025.0),
        lambda p: p["vhfPairing"].pop("stepKHz"),
        lambda p: p.update(beaconTypes=[]),
    ],
)
def test_bad_plan_fails(monkeypatch: pytest.MonkeyPatch, mutate: Any) -> None:
    plan = copy.deepcopy(PLAN)
    mutate(plan)
    with pytest.raises(SystemExit):
        _build(monkeypatch, plan=plan)


@pytest.mark.parametrize(
    "aliases",
    [
        {"USA": ["uk"]},
        {"USA": ["Freedonia"], "UK": ["freedonia"]},
        {"NOPE": ["Nowhere"]},
        {"USA": []},
    ],
)
def test_bad_aliases_fail(monkeypatch: pytest.MonkeyPatch, aliases: Any) -> None:
    with pytest.raises(SystemExit):
        _build(monkeypatch, aliases=aliases)
