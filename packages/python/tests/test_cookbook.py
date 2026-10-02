"""Run the Python snippets of docs/cookbook.md against the installed package."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

COOKBOOK = Path(__file__).resolve().parents[3] / "docs" / "cookbook.md"

# Recipe slug -> text its output must contain; every Python snippet needs one.
EXPECTED = {
    "load-an-aircraft-and-list-its-stations-and-stores": "station 1:",
    "which-aircraft-can-carry-the-aim-120c": "F-16C_50",
    "runway-ends-and-magnetic-bearings-for-batumi": "13/31 end 13: 124.5 M",
    "a-unit-s-weapon-systems-and-missile-channels": "2 missile channels",
    "airbase-stands-that-fit-an-aircraft": "fits 13 of",
    "map-coordinates-to-latitude-and-longitude": "NTTR is Nevada",
    "a-sam-ring-with-its-dead-zone-as-geojson": "ring of 65 points, hole of 65",
    "fit-a-loadout-weigh-it-and-check-a-radio-preset": "stations [2, 3, 5, 7]",
    "the-runway-into-the-wind-and-its-approach-aids": "TACAN 16X BTM: interrogate 1040 MHz, reply 977 MHz",
    "paste-a-mission-editor-coordinate": "DMS: N 29°32.059'   E 52°35.930' | 39 R XN 54929 68251",
    "a-weapon-who-launches-it-and-what-they-see": "PIOTR: detects 250 km, threat 190 km",
    "divert-airfields-that-can-park-an-aircraft": "Kutaisi: 38 nm at 096 T, 13 stands for a C-130J",
    "ai-tasks-for-a-cap-flight": "setTask   orbit: rejected",
    "loadout-rules-of-a-store": "on 2: station 6 holds ['BR_250']",
}


def _snippets() -> dict[str, str]:
    text = COOKBOOK.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    recipe = ""
    for m in re.finditer(r"^## ([^\n]+)$|^```(\w*)\n(.*?)^```$", text, re.M | re.S):
        if m.group(1):
            recipe = re.sub(r"[^a-z0-9]+", "-", m.group(1).lower()).strip("-")
        elif m.group(2) == "python":
            out[recipe] = m.group(3)
    return out


SNIPPETS = _snippets()


def test_every_snippet_is_checked() -> None:
    assert sorted(SNIPPETS) == sorted(EXPECTED)


@pytest.mark.parametrize("recipe", sorted(SNIPPETS))
def test_snippet_runs(recipe: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", SNIPPETS[recipe]],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    assert EXPECTED[recipe] in result.stdout, result.stdout
