"""The dump files the reference data points into, collected for the site
from the dump or its release asset (dump_lua)."""

import json
from pathlib import Path

import pytest
from conftest import write

from tools.datamine import dump_lua
from tools.datamine.common import LATEST, MANIFEST, VERSION_MARKER

VERSION = "2.9.30.28536"


def test_dump_file() -> None:
    assert dump_lua.dump_file("_G/db/Units/Planes/Plane/F-16C_50") == (
        "db/Units/Planes/Plane/F-16C_50.lua"
    )
    assert dump_lua.dump_file("_G/Pylons/LAU-115C+2_LAU127#/a/[1]") == (
        "Pylons/LAU-115C+2_LAU127.lua"
    )
    for bad in ("db/x", "_G/", "_G/a/../b", "_G/a//b"):
        with pytest.raises(ValueError):
            dump_lua.dump_file(bad)


def test_release_names() -> None:
    assert dump_lua.release_tag(VERSION) == "dcs-dump-2.9.30.28536"
    assert dump_lua.asset_name(VERSION) == "dcs-g-dump-2.9.30.28536.tar.gz"


def test_referenced_takes_record_and_block_paths() -> None:
    records = [
        {"sourcePaths": ["_G/b/y", "_G/a/x"], "flight": {"sourcePath": "_G/c/z#/fm"}},
        {"sourcePaths": ["_G/a/x"], "stages": [{"sourcePath": "_G/a/x#/[1]"}]},
    ]
    assert dump_lua.referenced(records) == ["a/x.lua", "b/y.lua", "c/z.lua"]


def _setup(tmp_path: Path) -> tuple[Path, Path]:
    g = tmp_path / "_G"
    write(g / VERSION_MARKER, VERSION)
    write(g / "a" / "x.lua", '_G["a"]["x"] = {\n\tk = 1\n}\n')
    write(g / "b" / "y (2)+.lua", '_G["b"]["y (2)+"] = "\xe9"\n')
    write(g / "unused.lua", "_G.unused = 1\n")
    root = tmp_path / "ref"
    latest = root / LATEST
    write(latest / MANIFEST, json.dumps({"dcsVersion": VERSION}))
    rec = {"id": "x", "sourcePaths": ["_G/a/x"], "b": {"sourcePath": "_G/b/y (2)+#/"}}
    write(latest / "weapons" / "x.json", json.dumps(rec))
    write(latest / "api" / "scripting.json", "{}")
    return g, root


@pytest.mark.parametrize("source", ["g_dir", "archive"])
def test_collect_copies_bytes_and_prunes(tmp_path: Path, source: str) -> None:
    g, root = _setup(tmp_path)
    out = tmp_path / "out"
    write(out / "stale" / "gone.lua", "old")
    if source == "g_dir":
        files = dump_lua.collect(root, out, g_dir=g)
    else:
        archive = tmp_path / "dump.tar.gz"
        assert dump_lua.pack(g, archive) == VERSION
        files = dump_lua.collect(root, out, archive=archive)
    assert sorted(files) == ["a/x.lua", "b/y (2)+.lua"]
    for rel in files:
        assert (out / rel).read_bytes() == (g / rel).read_bytes()
    assert not (out / "stale").exists()
    assert not (out / "unused.lua").exists()


def test_pack_is_deterministic(tmp_path: Path) -> None:
    g, _ = _setup(tmp_path)
    dump_lua.pack(g, tmp_path / "1.tar.gz")
    (g / "a" / "x.lua").touch()
    dump_lua.pack(g, tmp_path / "2.tar.gz")
    assert (tmp_path / "1.tar.gz").read_bytes() == (tmp_path / "2.tar.gz").read_bytes()


def test_collect_fails_on_other_version_or_missing_file(tmp_path: Path) -> None:
    g, root = _setup(tmp_path)
    archive = tmp_path / "dump.tar.gz"
    (g / "a" / "x.lua").unlink()
    dump_lua.pack(g, archive)
    for kw in ({"g_dir": g}, {"archive": archive}):
        with pytest.raises(SystemExit):
            dump_lua.collect(root, tmp_path / "out", **kw)
    write(g / VERSION_MARKER, "2.9.31.1")
    write(g / "a" / "x.lua", "x")
    dump_lua.pack(g, archive)
    for kw in ({"g_dir": g}, {"archive": archive}):
        with pytest.raises(SystemExit):
            dump_lua.collect(root, tmp_path / "out", **kw)
