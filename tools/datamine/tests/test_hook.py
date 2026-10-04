"""Run the Lua tests for the DCS dump hook under Lua 5.1 or LuaJIT (the
runtimes DCS uses). Skipped when neither is installed."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tools.datamine.common import DUMP_FORMAT, read_dump_format
from tools.datamine.dcs_constants import load_constants
from tools.datamine.lua_reader import LuaReader
from tools.datamine.rwr import load_wstype_ids

TESTS_LUA = Path(__file__).parent / "lua"
# A small dump format 4 tree written by the hook (test_dump_format4.lua), for
# reader tests. DCS_UPDATE_FIXTURES=1 rewrites it from the hook's output.
FORMAT4_FIXTURE = Path(__file__).parent / "fixtures" / "dump_format4"
HOOK_DIR = Path(__file__).parents[1] / "hook"
LUA = shutil.which("lua5.1") or shutil.which("luajit")

pytestmark = pytest.mark.skipif(LUA is None, reason="lua5.1/luajit not installed")


def _run(*args: str) -> str:
    result = subprocess.run(
        [str(LUA), *args], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_serialize() -> None:
    assert "SERIALIZE TESTS PASSED" in _run(
        str(TESTS_LUA / "test_serialize.lua"), str(HOOK_DIR)
    )


def test_serialize_lossless() -> None:
    assert "SERIALIZE LOSSLESS TESTS PASSED" in _run(
        str(TESTS_LUA / "test_serialize_lossless.lua"), str(HOOK_DIR), str(TESTS_LUA)
    )


def test_serialize_proxy() -> None:
    assert "SERIALIZE PROXY TESTS PASSED" in _run(
        str(TESTS_LUA / "test_serialize_proxy.lua"), str(HOOK_DIR)
    )


def test_unwritable_array_elements_read_without_failures(tmp_path: Path) -> None:
    # Functions, NaN and cycles in an array are not dropped tables.
    body = _run(
        "-e",
        f"package.path = {str(HOOK_DIR / '?.lua')!r} .. ';' .. package.path\n"
        "local loop = { 'a' }; loop[2] = loop\n"
        "io.write(require('serialize')({ fns = { 1, print, 3 }, nans = { 0/0, 2 },"
        " tail = { 'x', print }, loop = loop }, { indent = '\\t' }))",
    )
    path = tmp_path / "_G/x/A.lua"
    path.parent.mkdir(parents=True)
    path.write_text('_G["x"]["A"] = ' + body, encoding="utf-8")
    reader = LuaReader(tmp_path / "_G")
    assert reader.read_file(path) == {
        "fns": {"1": 1, "3": 3},
        "nans": {"2": 2},
        "tail": ["x"],
        "loop": ["a"],
    }
    assert reader.stats.failures == []


def _install_hook(
    root: Path, names: tuple[str, ...] = ("dump-globals.lua", "serialize.lua")
) -> None:
    hooks = root / "Scripts" / "Hooks"
    hooks.mkdir(parents=True)
    for name in names:
        shutil.copy(HOOK_DIR / name, hooks / name)


def test_ref_names_written_file(tmp_path: Path) -> None:
    _install_hook(tmp_path)
    assert "REF CASE TEST PASSED" in _run(
        str(TESTS_LUA / "test_ref_case.lua"), str(TESTS_LUA), f"{tmp_path}/"
    )


def test_file_name_collisions_get_suffixes(tmp_path: Path) -> None:
    _install_hook(tmp_path)
    out = _run(
        str(TESTS_LUA / "test_file_collision.lua"), str(TESTS_LUA), f"{tmp_path}/"
    )
    assert "FILE COLLISION TEST PASSED" in out
    assert (
        "File name collision: _G/Pylons/b-20.lua [b-20] matches B-20.lua [B-20];"
        " written as b-20~3.lua"
    ) in out


def test_serialize_shared() -> None:
    assert "SERIALIZE SHARED TESTS PASSED" in _run(
        str(TESTS_LUA / "test_serialize_shared.lua"), str(HOOK_DIR)
    )


def test_shared_tables_written_in_full(tmp_path: Path) -> None:
    _install_hook(tmp_path)
    out = _run(
        str(TESTS_LUA / "test_shared_record.lua"), str(TESTS_LUA), f"{tmp_path}/"
    )
    assert "SHARED RECORD TEST PASSED" in out
    assert "Cycle written as ref: _G/db/Units/Planes/Plane/F-16C_50.lua [self]" in out


def test_whole_tables_and_format_marker(tmp_path: Path) -> None:
    _install_hook(tmp_path)
    out = _run(str(TESTS_LUA / "test_whole_tables.lua"), str(TESTS_LUA), f"{tmp_path}/")
    assert "WHOLE TABLES TEST PASSED" in out
    assert "No records (no `type`) under _G.db.Units.WWIIstructures" in out
    assert "Skipping absent table _G.IndividualFuzeGUISettings" in out
    g_dir = tmp_path / "DCS.Lua.Exporter" / "_G"
    assert read_dump_format(g_dir) == DUMP_FORMAT


def _tree(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_dump_format4(tmp_path: Path) -> None:
    _install_hook(tmp_path)
    out = _run(str(TESTS_LUA / "test_dump_format4.lua"), str(TESTS_LUA), f"{tmp_path}/")
    assert "DUMP FORMAT 4 TEST PASSED" in out
    assert (
        "Cycle written as ref: _G/weapons_table/weapons/missiles/TEST_AAM.lua"
        " [controller/owner]"
    ) in out
    assert "Matched whole tables: 2 (TEST_CLUSTER_DATA, Test_cells_properties)" in out
    assert (
        'Record keys withheld as "#Index" (level-4 ids): 1; keys not writable: 0;'
        " truncated tables: 0"
    ) in out
    g_dir = tmp_path / "DCS.Lua.Exporter" / "_G"
    assert read_dump_format(g_dir) == DUMP_FORMAT == 4
    fixture = FORMAT4_FIXTURE / "_G"
    if os.environ.get("DCS_UPDATE_FIXTURES") == "1":
        shutil.rmtree(fixture, ignore_errors=True)
        shutil.copytree(g_dir, fixture)
    assert _tree(g_dir) == _tree(fixture), (
        "fixtures/dump_format4 is stale; rerun with DCS_UPDATE_FIXTURES=1"
    )


def test_constants_written(tmp_path: Path) -> None:
    _install_hook(tmp_path)
    assert "CONSTANTS TEST PASSED" in _run(
        str(TESTS_LUA / "test_constants.lua"), str(TESTS_LUA), f"{tmp_path}/"
    )
    # The extractor reads the hook's file as the dump source.
    g_dir = tmp_path / "DCS.Lua.Exporter" / "_G"
    constants = load_constants(LuaReader(g_dir), g_dir)
    assert constants.values["country"] == {"RUSSIA": 0, "USA": 2}
    assert constants.name("Entity.LauncherCategory", 6) == "CAT_PODS"


def test_ws_type_slot4_translated(tmp_path: Path) -> None:
    _install_hook(tmp_path)
    assert "WS_TYPE TEST PASSED" in _run(
        str(TESTS_LUA / "test_ws_type.lua"), str(TESTS_LUA), f"{tmp_path}/"
    )


def test_constants_failure_blocks_marker(tmp_path: Path) -> None:
    _install_hook(tmp_path)
    assert "CONSTANTS FAILURE TEST PASSED" in _run(
        str(TESTS_LUA / "test_constants_failure.lua"), str(TESTS_LUA), f"{tmp_path}/"
    )


def test_ws_type_slot4_level3_fallback(tmp_path: Path) -> None:
    _install_hook(tmp_path)
    out = _run(
        str(TESTS_LUA / "test_ws_type_fallback.lua"), str(TESTS_LUA), f"{tmp_path}/"
    )
    assert "WS_TYPE FALLBACK TEST PASSED" in out
    assert (
        "wsType slot 4 fallback (l1,l2,l4): _G/db/Units/Cars/Car/2S6 Tunguska.lua"
        " [WS/1/LN/1/PL/1/type_ammunition] {4, 4, 11, 80} -> 9M311"
    ) in out
    # Projectile records' own ws_type count as exact matches.
    assert (
        "wsType slot 4: 10 exact, 2 fallback (l1,l2,l4), 2 unmapped, 1 ambiguous" in out
    )


def test_wstype_ids_companion(tmp_path: Path) -> None:
    _install_hook(tmp_path)
    assert "WSTYPE IDS TEST PASSED" in _run(
        str(TESTS_LUA / "test_wstype_ids.lua"), str(TESTS_LUA), f"{tmp_path}/"
    )
    # The extractor reads the hook's file.
    g_dir = tmp_path / "DCS.Lua.Exporter" / "_G"
    ids = load_wstype_ids(LuaReader(g_dir), g_dir)
    assert ids.units["2S6 Tunguska"] == [(2, 16, 103, 29)]
    assert ids.projectiles["9M311"] == [(4, 4, 34, 90), (4, 4, 35, 90)]


def test_dump_without_wstype_ids_fails(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        load_wstype_ids(LuaReader(tmp_path), tmp_path)


def test_type_ammunition_slot4_translated(tmp_path: Path) -> None:
    _install_hook(tmp_path)
    assert "TYPE_AMMUNITION TEST PASSED" in _run(
        str(TESTS_LUA / "test_type_ammunition.lua"), str(TESTS_LUA), f"{tmp_path}/"
    )


@pytest.mark.parametrize("mode", ["module", "global"])
def test_me_units_written_under_u(tmp_path: Path, mode: str) -> None:
    _install_hook(tmp_path)
    out = _run(
        str(TESTS_LUA / "test_me_units.lua"), str(TESTS_LUA), f"{tmp_path}/", mode
    )
    assert "ME UNITS TEST PASSED" in out
    source = "_G.U" if mode == "global" else "_G.U (from _G.me_utilities)"
    assert f"[DCS.Lua.Exporter][INFO] {source}: " in out
    g_dir = tmp_path / "DCS.Lua.Exporter" / "_G"
    reader = LuaReader(g_dir)
    assert reader.read_file(g_dir / "U/months/January.lua") == {
        "days": 31,
        "name": "January",
    }
    assert reader.stats.failures == []


@pytest.mark.parametrize(
    ("mode", "error"),
    [
        ("absent", "Required table _G.U is absent (looked in _G.U, _G.me_utilities)"),
        ("empty", "No records (no `name`) under _G.me_utilities"),
    ],
)
def test_me_units_missing_fails_dump(tmp_path: Path, mode: str, error: str) -> None:
    _install_hook(tmp_path)
    out = _run(
        str(TESTS_LUA / "test_me_units.lua"), str(TESTS_LUA), f"{tmp_path}/", mode
    )
    assert "ME UNITS FAILURE TEST PASSED" in out
    assert f"[ERROR] {error}" in out
    # refresh.py stops the DCS run on this line (its fail_log).
    assert "[ERROR] Export aborted: 1 failures; version marker not written." in out


TERRAIN_HOOKS = ("terrain-dump.lua", "serialize.lua")


def test_terrain_dump(tmp_path: Path) -> None:
    _install_hook(tmp_path, TERRAIN_HOOKS)
    assert "TERRAIN DUMP TEST PASSED" in _run(
        str(TESTS_LUA / "test_terrain_dump.lua"), str(TESTS_LUA), f"{tmp_path}/", "ok"
    )


@pytest.mark.parametrize("mode", ["mission_error", "wrong_terrain"])
def test_terrain_dump_failure_writes_no_marker(tmp_path: Path, mode: str) -> None:
    _install_hook(tmp_path, TERRAIN_HOOKS)
    out = _run(
        str(TESTS_LUA / "test_terrain_dump.lua"), str(TESTS_LUA), f"{tmp_path}/", mode
    )
    assert "TERRAIN DUMP FAILURE TEST PASSED" in out
    assert "Terrain dump failed: " in out
