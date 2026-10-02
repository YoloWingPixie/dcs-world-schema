from pathlib import Path

from conftest import write

from tools.datamine.lua_reader import (
    LuaReader,
    array_entries,
    as_number,
    as_numeric,
    lua_to_py,
    number_tuple,
    sandbox_exec,
)


def test_returns_exactly_the_assigned_value(tmp_path: Path) -> None:
    # A record whose only field is a table must not be unwrapped further.
    f = write(
        tmp_path / "_G/__years__.lua",
        '_G["__years__"] = { ["F-16C_50"] = { USA = { from = 1990 } } }',
    )
    assert LuaReader(tmp_path / "_G").read_file(f) == {
        "F-16C_50": {"USA": {"from": 1990}}
    }


def test_nested_assignment_path(tmp_path: Path) -> None:
    f = write(
        tmp_path / "_G/db/Units/Planes/Plane/A.lua",
        '_G["db"]["Units"]["Planes"]["Plane"]["#Index"] = { type = "A", Pylons = { { X = 0 } } }',
    )
    rec = LuaReader(tmp_path / "_G").read_file(f)
    assert rec == {"type": "A", "Pylons": [{"X": 0}]}


def test_path_string_refs_are_resolved(tmp_path: Path) -> None:
    g = tmp_path / "_G"
    write(
        g / "warheads/AN_M65.lua",
        '_G["warheads"]["AN_M65"] = { mass = 500.8, expl_mass = 269.9 }',
    )
    f = write(
        g / "bombs/M65.lua",
        '_G["bombs"]["#Index"] = { name = "M65", warhead = "_G/warheads/AN_M65.lua" }',
    )
    reader = LuaReader(g)
    record = reader.read_file(f)
    assert record is not None
    assert record["warhead"] == {"mass": 500.8, "expl_mass": 269.9}
    assert reader.stats.unresolved_refs == []


def test_nested_and_cyclic_refs(tmp_path: Path) -> None:
    g = tmp_path / "_G"
    write(g / "a.lua", '_G["a"] = { b = "_G/b.lua" }')
    write(g / "b.lua", '_G["b"] = { n = 1, c = "_G/c.lua" }')
    write(g / "c.lua", '_G["c"] = { back = "_G/b.lua" }')
    f = write(g / "top.lua", '_G["top"] = { a = "_G/a.lua", again = "_G/b.lua" }')
    reader = LuaReader(g)
    top = reader.read_file(f)
    assert top is not None
    assert top["a"]["b"]["n"] == 1
    assert top["a"]["b"]["c"] == {"back": "_G/b.lua"}  # the cycle stays a string
    assert top["again"] is top["a"]["b"]
    assert [r for _, r in reader.stats.unresolved_refs] == ["_G/b.lua"]


def test_missing_ref_is_recorded(tmp_path: Path) -> None:
    g = tmp_path / "_G"
    f = write(
        g / "bombs/X.lua",
        '_G["bombs"]["#Index"] = { warhead = "_G/warheads/NOPE.lua" }',
    )
    reader = LuaReader(g)
    reader.read_file(f)
    assert reader.stats.unresolved_refs == [(str(f), "_G/warheads/NOPE.lua")]


def test_parse_failures_are_recorded(tmp_path: Path) -> None:
    g = tmp_path / "_G"
    serpent = write(g / "a.lua", '_G["a"]["b"] = <1>{ f = <function 2>, n = 1 }')
    broken = write(g / "b.lua", '_G["a"]["c"] = { ')
    reader = LuaReader(g)
    assert reader.read_file(serpent) is None
    assert reader.read_file(broken) is None
    assert [p for p, _ in reader.stats.failures] == [str(serpent), str(broken)]


def test_dump_files_have_no_library_access(tmp_path: Path) -> None:
    f = write(tmp_path / "_G/a.lua", '_G["a"] = { v = os.time() }')
    loop = write(tmp_path / "_G/b.lua", "while true do end")
    reader = LuaReader(tmp_path / "_G")
    assert reader.read_many([f, loop]) == [(f, None), (loop, None)]
    assert "instruction limit" in reader.stats.failures[-1][1]


def test_sandbox_exec_returns_env() -> None:
    ok, env = sandbox_exec("x = 1 + 2", "t")
    assert ok and env["x"] == 3
    assert sandbox_exec("error('boom')", "t")[0] is False


def test_unlinked_refs_stay_strings(tmp_path: Path) -> None:
    f = write(tmp_path / "_G/x/A.lua", '_G["x"]["A"] = { w = "_G/w/Gone.lua" }')
    reader = LuaReader(tmp_path / "_G", link_refs=False)
    assert reader.read_file(f) == {"w": "_G/w/Gone.lua"}
    assert reader.stats.unresolved_refs == []


def test_lua_to_py() -> None:
    ok, env = sandbox_exec('t = { 1, 2.0, { a = "_G/x.lua" }, [5] = 5 }', "t")
    assert ok
    assert lua_to_py(env["t"]) == {"1": 1, "2": 2, "3": {"a": "_G/x.lua"}, "5": 5}


def test_array_views() -> None:
    mixed = {"2": "b", "1": "a", "name": "x"}
    assert array_entries(mixed) == []
    assert array_entries(mixed, mixed=True) == ["a", "b"]
    assert array_entries({"3": "c", "1": "a"}) == ["a", "c"]
    assert number_tuple([1, 2.5], 2) == [1, 2.5]
    assert number_tuple([1, "x"], 2) is None
    assert number_tuple([1, 2, 3], 2) is None


def test_as_numeric_reads_numeric_strings_as_number_does_not() -> None:
    assert as_number("6103") is None
    assert as_numeric("6103") == 6103 and isinstance(as_numeric("6103"), int)
    assert as_numeric(" 12.5 ") == 12.5
    assert as_numeric("-3") == -3
    assert as_numeric(7.5) == 7.5
    assert as_numeric("6103 kg") is None
    assert as_numeric("") is None
    assert as_numeric(True) is None
