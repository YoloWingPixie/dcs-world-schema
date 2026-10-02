"""The classification rules (tools/package/rules.py): checked against the data,
stale or unknown entries fail."""

from __future__ import annotations

from typing import Any

import pytest

from tools.datamine import overlays
from tools.package import rules

SERIES: dict[str, dict[str, Any]] = {
    "attributes": {"Tanks": {}, "Tankers": {}, "SAM SR": {}},
    "aircraft": {
        "KC": {"id": "KC", "kind": "fixedwing", "attributes": ["Tankers"]},
        "H": {"id": "H", "kind": "rotary", "refuelling": {"isTanker": 1}},
    },
    "ground_vehicles": {
        "T": {"id": "T", "attributes": ["Tanks"]},
        "R": {"id": "R", "attributes": ["SAM SR"]},
        "X": {"id": "X"},
    },
}


def _build(
    monkeypatch: pytest.MonkeyPatch, classes: Any, roles: Any
) -> tuple[dict[str, Any], list[str]]:
    tables = {("units", "classes"): classes, ("aircraft", "roles"): roles}
    monkeypatch.setattr(overlays, "load", lambda _v: overlays.Overlays([], tables))
    return rules.build(SERIES, "test")


CLASSES = [
    {"class": "sam", "when": {"attributes": {"any": ["SAM SR"]}}},
    {"class": "armor", "when": {"attributes": {"all": ["Tanks"]}}},
    {
        "class": "helicopter",
        "when": {"series": {"any": ["aircraft"]}, "kind": {"any": ["rotary"]}},
    },
    {"class": "airplane", "when": {"series": {"any": ["aircraft"]}}},
]
ROLES = [
    {"role": "tanker", "when": {"isTanker": {"any": ["true"]}}},
    {"role": "tanker", "when": {"attributes": {"any": ["Tankers"]}}},
    {
        "role": "rotary",
        "when": {"kind": {"any": ["rotary"]}, "attributes": {"none": ["Tanks"]}},
    },
]


def test_build_and_report(monkeypatch: pytest.MonkeyPatch) -> None:
    payload, report = _build(monkeypatch, CLASSES, ROLES)
    assert payload == {"unitClasses": CLASSES, "aircraftRoles": ROLES}
    assert (
        report[0] == "unit classes: airplane 1, helicopter 1, armor 1, sam 1, other 1"
    )
    assert report[1] == "aircraft roles: tanker 2, rotary 1"


def test_rule_semantics() -> None:
    facts = {"attributes": ["A", "B"], "series": ["ships"]}
    assert rules.matches({}, facts)
    assert rules.matches({"attributes": {"all": ["A", "B"], "none": ["C"]}}, facts)
    assert not rules.matches({"attributes": {"any": ["C"]}}, facts)
    assert not rules.matches({"attributes": {"none": ["B"]}}, facts)
    assert not rules.matches({"kind": {"any": ["rotary"]}}, facts)
    tanker = rules.aircraft_facts({"kind": "fixedwing", "refuelling": {"isTanker": 0}})
    assert tanker["isTanker"] == []


@pytest.mark.parametrize(
    ("classes", "message"),
    [
        (
            [*CLASSES, {"class": "ship", "when": {"series": {"any": ["ships"]}}}],
            "match nothing",
        ),
        (
            [{"class": "x", "when": {"attributes": {"any": ["Nope"]}}}],
            "no value ['Nope']",
        ),
        (
            [{"class": "x", "when": {"colour": {"any": ["red"]}}}],
            "unknown fact 'colour'",
        ),
        (
            [{"class": "x", "when": {"attributes": {"some": ["Tanks"]}}}],
            "needs tests among",
        ),
        ([{"klass": "x"}], "needs `class`"),
    ],
)
def test_bad_rules_fail(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    classes: Any,
    message: str,
) -> None:
    with pytest.raises(SystemExit):
        _build(monkeypatch, classes, ROLES)
    assert message in capsys.readouterr().err
