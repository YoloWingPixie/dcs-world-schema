"""Run the Lua snippets of docs/cookbook.md in Lua 5.1 against the generated
series files (``require`` from ``packages/lua``)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tools.package.cookbook import snippets

LUA_DIR = Path(__file__).resolve().parents[1]
LUA = shutil.which("lua5.1") or shutil.which("luajit")

pytestmark = pytest.mark.skipif(LUA is None, reason="lua5.1 or luajit not installed")

# Recipe slug -> text its output must contain; every Lua snippet needs one.
EXPECTED = {
    "load-an-aircraft-and-list-its-stations-and-stores": "station 1:",
    "a-unit-s-weapon-systems-and-missile-channels": "2 missile channels",
    "find-stores-by-display-name": "stores match GBU-12",
    "navaids-for-a-runway": "runway 13: ILS ILU 110.30 MHz",
    "map-coordinates-to-latitude-and-longitude": "round trip under 1 mm",
    "fit-a-loadout-weigh-it-and-check-a-radio-preset": "251.01 MHz on radio 0: offStep",
    "the-runway-into-the-wind-and-its-approach-aids": "TACAN 16X: interrogate 1040 MHz, reply 977 MHz",
    "paste-a-mission-editor-coordinate": "MGRS -> N 29°32'03.54\"   E 52°35'55.82\"",
    "divert-airfields-that-can-park-an-aircraft": "Kutaisi: 38 nm, 13 stands for a C-130J",
}
SNIPPETS = {s.recipe: s.code for s in snippets() if s.lang == "lua"}


def test_every_snippet_is_checked() -> None:
    assert sorted(SNIPPETS) == sorted(EXPECTED)


@pytest.mark.parametrize("recipe", sorted(SNIPPETS))
def test_snippet_runs(recipe: str, tmp_path: Path) -> None:
    assert LUA is not None
    script = tmp_path / f"{recipe}.lua"
    script.write_text(SNIPPETS[recipe], encoding="utf-8")
    result = subprocess.run(
        [LUA, str(script)],
        cwd=LUA_DIR,
        env={**os.environ, "LUA_PATH": "./?.lua;./?/init.lua;;"},
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    assert EXPECTED[recipe] in result.stdout, result.stdout
