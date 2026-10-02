"""The Lua series files load in Lua 5.1 through ``init.lua`` and hold exactly the
JSON bundles (Lua has no empty-array/empty-object distinction: both compare as
empty)."""

from __future__ import annotations

import json
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import pytest

from tools.datamine.common import SERIES
from tools.package.build import lua_zip_name
from tools.package.bundles import BUNDLE_DIR

LUA_DIR = Path(__file__).resolve().parents[1]
LUA = shutil.which("lua5.1") or shutil.which("luajit")
ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")

pytestmark = pytest.mark.skipif(LUA is None, reason="lua5.1 or luajit not installed")


def _lua(*args: str, cwd: Path = LUA_DIR) -> str:
    assert LUA is not None
    result = subprocess.run(
        [LUA, *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8"
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _normalise(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _normalise(x) for k, x in v.items()} if v else None
    if isinstance(v, list):
        return [_normalise(x) for x in v] if v else None
    return v


@pytest.fixture(scope="module")
def dumped() -> dict[str, Any]:
    return json.loads(_lua("tests/dump.lua", str(LUA_DIR), *SERIES))


@pytest.mark.parametrize("name", list(SERIES))
def test_series_round_trips(dumped: dict[str, Any], name: str) -> None:
    bundle = json.loads((BUNDLE_DIR / f"{name}.json").read_text(encoding="utf-8"))
    assert len(dumped[name]) == len(bundle)
    assert _normalise(dumped[name]) == _normalise(bundle)


def test_dcs_version(dumped: dict[str, Any]) -> None:
    manifest = json.loads((BUNDLE_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert dumped["dcsVersion"] == manifest["dcsVersion"]


def test_require_and_unknown_series(tmp_path: Path) -> None:
    script = (
        'package.path = "./?.lua;./?/init.lua;" .. package.path\n'
        'local ref = require("dcs_world_reference")\n'
        'assert(ref.countries["2"].shortName == "USA")\n'
        "ref.setDir(nil)\n"
        "assert(next(ref.theatres) ~= nil)\n"
        "assert(not pcall(function() return ref.nope end))\n"
        'assert(not pcall(function() return ref["../init"] end))\n'
        'print("ok")\n'
    )
    path = tmp_path / "require.lua"
    path.write_text(script, encoding="utf-8")
    assert _lua(str(path)).strip() == "ok"


def test_zip_holds_the_package() -> None:
    version = (LUA_DIR.parents[1] / "VERSION").read_text(encoding="utf-8").strip()
    manifest = json.loads((BUNDLE_DIR / "manifest.json").read_text(encoding="utf-8"))
    archive = (
        LUA_DIR.parents[1] / "dist" / lua_zip_name(version, manifest["dcsVersion"])
    )
    with zipfile.ZipFile(archive) as zf:
        for name in zf.namelist():
            assert zf.read(name) == (LUA_DIR / name).read_bytes(), name
        names = set(zf.namelist())
    files = {
        p.relative_to(LUA_DIR).as_posix()
        for p in LUA_DIR.glob("dcs_world_reference/*.lua")
    }
    assert names == files | {"README.md"}
