"""Dump paths and pointers (``<dump path>#<pointer>``, dump_paths) and the
check that every emitted path resolves in the dump."""

import math
from pathlib import Path

import pytest
from conftest import unresolved_paths, write
from test_weapon_flight import _aim_120c, _flight, _legacy

from tools.datamine import dump_paths
from tools.datamine.dump_paths import DumpPaths
from tools.datamine.lua_reader import LuaReader


@pytest.mark.parametrize(
    ("keys", "text"),
    [
        ([], ""),
        (["client", "fm", "Cx0"], "/client/fm/Cx0"),
        (["a/b", "~x"], "/a~1b/~0x"),
        (["[1]", "[x", "x[1]"], "/~21]/~2x/x[1]"),
        ([1, 2], "/[1]/[2]"),
        ([True, False], "/[true]/[false]"),
        ([0.5, -3, 1e20], "/[0.5]/[-3]/[1e+20]"),
        ([math.inf, -math.inf], "/[inf]/[-inf]"),
        (["1", "true", ""], "/1/true/"),
        (["$type"], "/$type"),
    ],
)
def test_pointer_round_trip(keys: list[object], text: str) -> None:
    assert dump_paths.pointer(*keys) == text
    assert dump_paths.parse_pointer(text) == keys
    for a, b in zip(dump_paths.parse_pointer(text), keys, strict=True):
        assert type(a) is type(b)


@pytest.mark.parametrize("bad", ["x", "/[", "/[]", "/~3", "/a~", "/[1", "/[abc]"])
def test_bad_pointers(bad: str) -> None:
    with pytest.raises(ValueError):
        dump_paths.parse_pointer(bad)


def test_split_source_path() -> None:
    assert dump_paths.split_source_path("_G/rockets/X#") == ("_G/rockets/X", [])
    assert dump_paths.split_source_path("_G/rockets/X") == ("_G/rockets/X", [])
    assert dump_paths.split_source_path("_G/a#/b/[2]") == ("_G/a", ["b", 2])


def _dump(tmp_path: Path, body: str) -> DumpPaths:
    write(tmp_path / "_G" / "x" / "y.lua", f'_G["x"]["y"] = {body}')
    g = tmp_path / "_G"
    return DumpPaths(g, LuaReader(g, link_refs=False, dump_format=4))


def test_resolve_key_types(tmp_path: Path) -> None:
    dump = _dump(
        tmp_path,
        '{ [1] = "int", ["1"] = "str", [true] = "bool", [0.5] = "half",'
        ' ["$type"] = "dollar", ["[1]"] = "bracket", ["a/b"] = { 10, 20, { c = 3 } } }',
    )
    r = dump.resolve
    assert r("_G/x/y#/[1]") == "int"
    assert r("_G/x/y#/1") == "str"
    assert r("_G/x/y#/[true]") == "bool"
    assert r("_G/x/y#/[0.5]") == "half"
    assert r("_G/x/y#/$type") == "dollar"
    assert r("_G/x/y#/~21]") == "bracket"
    assert r("_G/x/y#/a~1b/[2]") == 20
    assert r("_G/x/y#/a~1b/[3]/c") == 3
    assert r("_G/x/y") is not None
    for missing in ("/[2]", "/2", "/[false]", "/a~1b/[0]", "/a~1b/[4]", "/a~1b/1"):
        with pytest.raises(KeyError):
            r(f"_G/x/y#{missing}")
    with pytest.raises(KeyError):
        r("_G/x/none#")


def test_resolve_through_markers(tmp_path: Path) -> None:
    dump = _dump(
        tmp_path,
        '{ a = __dcs{kind="anchor", id=1, value={ b = 7 }}, c = __dcs{kind="ref", id=1},'
        ' w = "_G/warheads/W.lua", v = "_G/warheads/V.lua" }',
    )
    write(tmp_path / "_G" / "warheads" / "W.lua", '_G["warheads"]["W"] = { mass = 5 }')
    assert dump.resolve("_G/x/y#/a/b") == 7
    assert dump.resolve("_G/x/y#/c/b") == 7
    assert dump.resolve("_G/x/y#/w/mass") == 5
    with pytest.raises(KeyError):
        dump.resolve("_G/x/y#/v/mass")


def test_weapon_flight_pointers_resolve(tmp_path: Path) -> None:
    g = tmp_path / "_G"
    _aim_120c(g)
    _legacy(
        g,
        "rockets",
        "AIM_120C",
        'name = "AIM_120C", _unique_resource_name = "weapons.missiles.AIM_120C",'
        " Life_Time = 90, ModelData = { 58, 0.2 }, fm = { Cx0 = { 0.4, 0.5 } },"
        " LaunchDistData = { 1, 1, 100, 0, 5 }",
    )
    record = _flight(g)["AIM_120C"]
    assert unresolved_paths(record, g, dump_format=4) == []
    assert record["sourcePath"] == "_G/weapons_table/weapons/missiles/AIM_120C#/client"
    assert record["seeker"]["sourcePath"] == record["sourcePath"] + "/sensor"


def test_check_reports(tmp_path: Path) -> None:
    dump = _dump(tmp_path, "{ b = { 1, 2 }, c = 3 }")
    record = {
        "sourcePaths": ["_G/x/y", "_G/x/missing"],
        "block": {
            "sourcePath": "_G/x/y#/b",
            "rows": [{"sourcePath": "_G/x/y#/b/[3]"}],
        },
    }
    problems = dump_paths.check(dump, {"s": {"r": record}})
    assert [p.split(" = ")[0] for p in problems] == [
        "s/r.sourcePaths",
        "s/r.block.rows[0].sourcePath",
    ]
