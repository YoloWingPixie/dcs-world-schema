"""The coverage/diff command (``tools.datamine.coverage``) on small synthetic
trees. The Quaggles-style snippets are hand-written in inspect.lua's syntax
(``<1>{...}``, ``<table 1>``, ``<function 2>``), not copied from Quaggles."""

import json
import math
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from conftest import write

from tools.datamine import aircraft_flight, coverage, weapon_flight
from tools.datamine.coverage import (
    CYCLE,
    EMPTY,
    FileRef,
    Mark,
    diff_paths,
    flatten,
    load_rules,
    open_tree,
    parse_dump,
    run_diff,
    run_typed,
)
from tools.datamine.extract_units import load_units
from tools.datamine.lua_reader import LuaReader, lua_to_py

FIXTURES = Path(__file__).parent / "fixtures"


def _paths(text: str) -> dict[str, Any]:
    _, value = parse_dump(text)
    return flatten(value, coverage.anchors_of(value), None)


def _g(root: Path, rel: str, text: str) -> Path:
    return write(root / "_G" / f"{rel}.lua", text)


# --- parser -------------------------------------------------------------------


def test_parse_inspect_placeholders() -> None:
    keys, _ = parse_dump('_G["rockets"]["#Index"] = {}')
    assert keys == ["rockets", "#Index"]
    paths = _paths(
        '_G["x"]["A"] = <1>{\n'
        '\tname = "A",\n'
        "\twarhead = <2>{ mass = 5, caliber = 0.2 },\n"
        "\twarhead_air = <table 2>,\n"
        "\tself_ref = <table 1>,\n"
        "\tgetter = <function 3>,\n"
        '\t["key with space"] = { 1, 2.5, "s" },\n'
        "\t[true] = false,\n"
        "\tempty = {},\n"
        "}"
    )
    assert paths == {
        '["key with space"][1]': 1.0,
        '["key with space"][2]': 2.5,
        '["key with space"][3]': "s",
        ".empty": EMPTY,
        ".getter": Mark("function"),
        ".name": "A",
        ".self_ref": CYCLE,
        ".warhead.caliber": 0.2,
        ".warhead.mass": 5.0,
        ".warhead_air.caliber": 0.2,
        ".warhead_air.mass": 5.0,
        "[true]": False,
    }


def test_parse_format4_markers_and_format3_nil() -> None:
    paths = _paths(
        '_G["x"]["A"] = {\n'
        '\tf = __dcs{kind="function"},\n'
        '\tnz = __dcs{kind="number", value="-0"},\n'
        '\tinf = __dcs{kind="number", value="inf"},\n'
        '\tshared = __dcs{kind="anchor", id=1, value={ a = 1 }},\n'
        '\tagain = __dcs{kind="ref", id=1},\n'
        '\tws = { 4, 4, 7, __dcs{kind="redacted", reason="patch-volatile", lua_type="number"} },\n'
        "\told = nil,\n"
        '\twh = "_G/warheads/X.lua",\n'
        "\tbig = 1e309,\n"
        "}"
    )
    assert paths[".f"] == Mark("function")
    assert math.copysign(1, paths[".nz"]) < 0
    assert paths[".inf"] == math.inf
    assert paths[".big"] == math.inf
    assert paths[".shared.a"] == 1 and paths[".again.a"] == 1
    assert paths[".ws[4]"] == Mark("redacted", "patch-volatile")
    assert paths[".old"] == Mark("unsupported", "format3-nil")
    assert paths[".wh"] == FileRef("_G/warheads/X")


def test_parse_errors_are_reported(tmp_path: Path) -> None:
    _g(tmp_path, "rockets/BAD", '_G["rockets"]["#Index"] = { a = <table 9 }')
    tree = open_tree(tmp_path / "_G")
    assert tree.paths("rockets/BAD") is None
    assert tree.failures and tree.failures[0][0] == "rockets/BAD"


# --- diff ---------------------------------------------------------------------


def test_diff_classes() -> None:
    s = {
        ".a": 1,
        ".b": 2.0,
        ".c": "x",
        ".n": 0.0,
        ".f": Mark("unsupported", "format3-nil"),
    }
    t = {".a": 1.0, ".b": 3, ".d": True, ".n": -0.0, ".f": Mark("function")}
    t[".r"] = Mark("unresolved-ref", "_G/Pylons/B-20")
    got = {(e.cls, e.path) for e in diff_paths(s, t, "rockets/X", "rockets", "", False)}
    assert got == {
        ("changed", ".b"),
        ("added", ".c"),
        ("missing", ".d"),
        ("changed", ".n"),  # -0 is not 0
        ("unresolved", ".f"),
        ("unresolved", ".r"),
    }
    # Booleans are not numbers.
    assert {
        e.cls for e in diff_paths({".a": True}, {".a": 1}, "f", "r", "", False)
    } == {"changed"}


def _quaggles_pair(tmp_path: Path) -> tuple[Path, Path]:
    """Our format-3 dump and a hand-written Quaggles-style checkout."""
    ours = tmp_path / "ours"
    q = tmp_path / "q"
    write(ours / "_G" / "__DCS_VERSION__.lua", "2.9.30.1")
    write(ours / "_G" / "__DUMP_FORMAT__.lua", "3")
    write(q / "_G" / "__DCS_VERSION__.lua", "2.9.30.1")
    write(q / "Hooks" / "DCS-LuaExporter-hook.lua", "-- exporter")
    _g(
        ours,
        "rockets/R1",
        '_G["rockets"]["#Index"] = {\n\tname = "R1",\n\tws_type = { 4, 4, 7, "R1" },\n'
        '\twarhead = "_G/warheads/W1.lua",\n\tget_mass = nil,\n\tfm = { Cx0 = { 0.4, 0.5 } }\n}',
    )
    _g(
        q,
        "rockets/R1",
        '_G["rockets"]["#Index"] = {\n\tname = "R1",\n\tws_type = { 4, 4, 7, "Redacted" },\n'
        '\twarhead = "_G/warheads/W1.lua",\n\tget_mass = <function 1>,\n'
        "\tfm = { Cx0 = { 0.4, 0.5 } }\n}",
    )
    for root in (ours, q):
        _g(root, "warheads/W1", '_G["warheads"]["W1"] = { mass = 2 }')
    # A proxy table: Quaggles writes {}, we write the inherited fields.
    _g(
        ours,
        "db/Units/Cars/Car/T1",
        '_G["db"]["Units"]["Cars"]["Car"]["#Index"] = { type = "T1", chassis = { mass = 9 } }',
    )
    _g(
        q,
        "db/Units/Cars/Car/T1",
        '_G["db"]["Units"]["Cars"]["Car"]["#Index"] = { type = "T1", chassis = {} }',
    )
    # A case collision: Quaggles kept one spelling, we kept both.
    _g(ours, "Pylons/B-20", '_G["Pylons"]["#Index"] = { name = "B-20", x = 1 }')
    _g(ours, "Pylons/b-20~2", '_G["Pylons"]["#Index"] = { name = "b-20", x = 2 }')
    _g(q, "Pylons/b-20", '_G["Pylons"]["#Index"] = { name = "b-20", x = 2 }')
    # Out of scope (not an object root).
    _g(q, "U/u", '_G["U"]["u"] = { a = 1 }')
    return ours, q


def test_quaggles_diff_explained(tmp_path: Path) -> None:
    ours, q = _quaggles_pair(tmp_path)
    subject = open_tree(ours)
    target = open_tree(q)
    assert target.quaggles and subject.dump_format == 3
    rep = run_diff(
        subject, target, load_rules(coverage.EXPLANATIONS, "quaggles"), "quaggles"
    )
    assert rep.totals.unexplained["missing"] == 0, [e.json() for e in rep.unexplained]
    assert not rep.unexplained
    rules = {r: dict(c) for r, c in rep.rule_counts.items()}
    assert rules["quaggles-redacted"] == {"changed": 1}
    assert rules["function-values"] == {"unresolved": 1}
    assert rules["quaggles-proxy-empty"] == {"missing": 1}
    assert rules["quaggles-proxy-empty-added"] == {"added": 1}
    assert rules["case-collision"]["added"] == 2  # our B-20 twin
    assert rep.collision_pairs == [("Pylons/b-20~2", "Pylons/b-20")]
    assert rep.files_only_subject == ["Pylons/B-20"]
    assert rep.out_of_scope["target"] == {"U": 1}
    assert rep.totals.counts["missing"] == 1  # the {} leaf
    assert not rep.failed()


def test_unexplained_missing_fails(tmp_path: Path) -> None:
    ours, q = _quaggles_pair(tmp_path)
    _g(q, "rockets/R2", '_G["rockets"]["#Index"] = { name = "R2", Life_Time = 30 }')
    args = ["diff", str(ours), "--quaggles", str(q), "--json", str(tmp_path / "c.json")]
    assert coverage.main([*args, "--markdown", str(tmp_path / "c.md")]) == 1
    report = json.loads((tmp_path / "c.json").read_text(encoding="utf-8"))
    assert report["failed"] is True
    assert report["totals"]["unexplained"]["missing"] == 2
    assert {e["path"] for e in report["unexplained"]} == {".Life_Time", ".name"}
    assert report["files"]["onlyTarget"] == ["rockets/R2"]
    assert "rockets/R2" in (tmp_path / "c.md").read_text(encoding="utf-8")
    assert coverage.main([*args, "--advisory"]) == 0
    # Deterministic output.
    first = (tmp_path / "c.json").read_bytes()
    coverage.main([*args, "--advisory"])
    assert (tmp_path / "c.json").read_bytes() == first


def test_no_rules_against_a_dump(tmp_path: Path) -> None:
    ours, q = _quaggles_pair(tmp_path)
    shutil.rmtree(q / "Hooks")  # now a plain dump: no explanations apply
    target = open_tree(q)
    assert not target.quaggles
    rep = run_diff(open_tree(ours), target, [], "dump")
    assert rep.failed()
    assert rep.totals.unexplained["missing"] == rep.totals.counts["missing"] == 1


def test_unresolved_ref(tmp_path: Path) -> None:
    _g(
        tmp_path,
        "launcher/L",
        '_G["launcher"]["#Index"] = { CLSID = "L", Elements = { "_G/Pylons/X.lua" } }',
    )
    tree = open_tree(tmp_path / "_G")
    assert tree.paths("launcher/L") == {
        ".CLSID": "L",
        ".Elements[1]": Mark("unresolved-ref", "_G/Pylons/X"),
    }
    assert tree.paths("launcher/L", resolve_refs=False) == {
        ".CLSID": "L",
        ".Elements[1]": FileRef("_G/Pylons/X"),
    }


def test_rules_file_is_valid() -> None:
    rules = load_rules(coverage.EXPLANATIONS, "quaggles")
    assert len({r.id for r in rules}) == len(rules) >= 10
    assert all(len(r.reasoning) > 80 for r in rules)
    assert load_rules(coverage.EXPLANATIONS, "dump") == []


def test_bad_rules(tmp_path: Path) -> None:
    f = write(
        tmp_path / "r.yaml",
        "rules:\n- {id: a, title: t, reasoning: r, classes: [gone]}\n",
    )
    with pytest.raises(ValueError, match="unknown classes"):
        load_rules(f, "quaggles")


# --- dump vs dump -------------------------------------------------------------


def test_dump_against_itself() -> None:
    """The format 4 fixture parses without failures and equals itself."""
    g = FIXTURES / "dump_format4" / "_G"
    subject, target = open_tree(g), open_tree(g.parent)
    assert subject.dump_format == 4 and not target.quaggles
    rep = run_diff(subject, target, [], "dump")
    assert not subject.failures and not target.failures
    assert sum(rep.totals.counts.values()) == 0
    assert rep.totals.paths_subject == rep.totals.paths_target > 0
    assert "U" in rep.out_of_scope["subject"]  # not an object root


def test_root_of() -> None:
    assert coverage.root_of("db/Units/Planes/Plane/Su-27") == "db/Units"
    assert coverage.root_of("db/Units/Skills/X") is None
    assert coverage.root_of("weapons_table/weapons/missiles/M") == "weapons_table"
    assert coverage.root_of("TEST_CLUSTER_DATA") == "TEST_CLUSTER_DATA"
    assert coverage.root_of("Test_cells_properties") == "Test_cells_properties"
    assert coverage.root_of("U/u") is None


# --- typed coverage -----------------------------------------------------------

M1 = "_G/weapons_table/weapons/missiles/M1"


def _weapon_data(
    tmp_path: Path, mutate: Callable[[dict[str, Any]], None] | None = None
) -> tuple[Path, Path]:
    """A format 3 dump with one missile and its weapon_flight record."""
    g = tmp_path / "dump" / "_G"
    write(g / "__DUMP_FORMAT__.lua", "3")
    _g(
        tmp_path / "dump",
        "weapons_table/weapons/missiles/M1",
        '_G["weapons_table"]["weapons"]["missiles"]["M1"] = {\n'
        '\tname = "M1", _unique_resource_name = "weapons.missiles.M1",\n'
        "\tKillDistance = 7,\n"
        "\tclient = {\n"
        "\t\tLife_Time = 60, ModelData = { 1, 2, 3 },\n"
        "\t\tPN_coeffs = { 2, 5000, 1, 10000, 0.5 },\n"
        "\t\tLaunchDistData = { 2, 2, 100, 165, 50, 8400, 11000, 2000, 14000, 15500 },\n"
        "\t\tMinLaunchDistData = { 2, 2, 100, 165, 50, 2000, 2300, 2000, 1000, 1200 },\n"
        "\t\tfm = {\n\t\t\tCx0 = { 0.4, 0.5 },\n\t\t\tgetter = nil,\n\t\t\tmystery = 3\n\t\t},\n"
        "\t\tboost = { impulse = 200, fuel_mass = 10, work_time = 2 },\n"
        "\t\tcontroller = { boost_start = 0.5 },\n"
        "\t},\n"
        "}",
    )
    raw = lua_to_py(LuaReader(g).read_file(g / "weapons_table/weapons/missiles/M1.lua"))
    flight = weapon_flight.flight("M1", [weapon_flight.Source(M1, True, raw)])
    assert flight is not None
    if mutate:
        mutate(flight)
    data = tmp_path / "latest"
    write(data / "weapon_flight" / "M1.json", json.dumps(flight))
    return data, g


def test_typed_weapon_complete(tmp_path: Path) -> None:
    rep = run_typed(*_weapon_data(tmp_path))
    assert rep.failures == [], [f.json() for f in rep.failures]
    assert rep.records == {"weapon_flight": 1}
    # Life_Time, KillDistance (record top), PN_coeffs, Cx0, 3 stage values,
    # startTime, LaunchDistData, MinLaunchDistData.
    assert rep.values == {"weapon_flight": 10}
    assert rep.typed["weapon_flight aerodynamics/Cx0"] == 1
    assert rep.typed["weapon_flight top/KillDistance"] == 1
    assert rep.typed["weapon_flight top/PN_coeffs"] == 1
    # Keys without a typed field are reported, not failures.
    assert dict(rep.dump_only) == {
        "weapon_flight aerodynamics/mystery": 1,
        "weapon_flight top/ModelData": 1,
        "weapon_flight controller (block not typed)": 1,
    }
    assert (
        rep.examples["weapon_flight aerodynamics/mystery"] == f"{M1}#/client/fm/mystery"
    )
    assert rep.markers == {"unsupported": 1}  # fm.getter
    assert not rep.failed()


def _wrong_value(flight: dict[str, Any]) -> None:
    flight["aerodynamics"]["cx0"] = [9, 9]


def _wrong_envelope(flight: dict[str, Any]) -> None:
    flight["launchEnvelopes"][0]["minRangeM"][1][0] = 9


def _bad_path(flight: dict[str, Any]) -> None:
    flight["motorStages"][0]["sourcePath"] = f"{M1}#/client/gone"


def _unmapped(flight: dict[str, Any]) -> None:
    flight["gimbal"] = {"sourcePath": f"{M1}#/client/fm", "newField": 1}


def test_typed_value_differing_from_dump_fails(tmp_path: Path) -> None:
    rep = run_typed(*_weapon_data(tmp_path, _wrong_value))
    assert [(f.kind, f.source_path) for f in rep.failures] == [
        ("differs", f"{M1}#/client/fm/Cx0")
    ]
    assert rep.failed()


def test_typed_launch_envelope_checked_per_table(tmp_path: Path) -> None:
    rep = run_typed(*_weapon_data(tmp_path))
    assert rep.typed["weapon_flight top/LaunchDistData"] == 1
    assert rep.failures == []
    rep = run_typed(*_weapon_data(tmp_path, _wrong_envelope))
    assert [(f.kind, f.source_path) for f in rep.failures] == [
        ("differs", f"{M1}#/client/MinLaunchDistData")
    ]


def test_typed_unresolved_and_unmapped_fail(tmp_path: Path) -> None:
    rep = run_typed(*_weapon_data(tmp_path, _bad_path))
    assert [(f.kind, f.source_path) for f in rep.failures] == [
        ("unresolved", f"{M1}#/client/gone")
    ]
    rep = run_typed(*_weapon_data(tmp_path, _unmapped))
    assert [(f.kind, f.detail) for f in rep.failures] == [
        ("unmapped-field", "gimbal.newField")
    ]


def test_typed_cli(tmp_path: Path) -> None:
    data, g = _weapon_data(tmp_path, _wrong_value)
    args = [
        "typed",
        str(data),
        "--g-dir",
        str(g.parent),
        "--json",
        str(tmp_path / "t.json"),
    ]
    assert coverage.main([*args, "--markdown", str(tmp_path / "t.md")]) == 1
    report = json.loads((tmp_path / "t.json").read_text(encoding="utf-8"))
    assert report["failureKinds"] == {"differs": 1}
    assert "differs" in (tmp_path / "t.md").read_text(encoding="utf-8")
    assert coverage.main([*args, "--advisory"]) == 0


def test_typed_format4_weapons(tmp_path: Path) -> None:
    """weapon_flight records of the format 4 fixture match its dump."""
    g = FIXTURES / "dump_format4" / "_G"
    reader = LuaReader(g)
    for rel in ("weapons_table/weapons/missiles/TEST_AAM", "rockets/TEST_ROCKET"):
        raw = lua_to_py(reader.read_file(g / f"{rel}.lua"))
        source = weapon_flight.Source(f"_G/{rel}", rel.startswith("weapons"), raw)
        flight = weapon_flight.flight(rel.rpartition("/")[2], [source])
        assert flight is not None
        write(
            tmp_path / "weapon_flight" / f"{flight['weapon']}.json", json.dumps(flight)
        )
    rep = run_typed(tmp_path, g)
    assert rep.failures == [], [f.json() for f in rep.failures]
    assert rep.records == {"weapon_flight": 2} and rep.values["weapon_flight"] > 0


def test_typed_aircraft(tmp_path: Path) -> None:
    g = FIXTURES / "object_config" / "_G"
    raw = load_units(LuaReader(g, dump_format=3), g)
    records = aircraft_flight.build(raw.category("Planes", "Helicopters"), raw.paths)
    assert records
    for uid, rec in records.items():
        write(tmp_path / "aircraft_flight" / f"{uid}.json", json.dumps(rec))
    rep = run_typed(tmp_path, g)
    assert rep.failures == [], [f.json() for f in rep.failures]
    assert rep.records == {"aircraft_flight": len(records)}
    assert rep.typed["aircraft_flight aerodynamics/table_data"] >= 1
    assert rep.typed["aircraft_flight engine/table_data"] >= 1
    assert any(g.startswith("aircraft_flight helicopter/") for g in rep.typed)
    # A changed table cell fails.
    rec = records["Su-27"]
    rec["aerodynamics"]["table"][0]["cx0"] = 1
    write(tmp_path / "aircraft_flight" / "Su-27.json", json.dumps(rec))
    rep = run_typed(tmp_path, g)
    assert [f.source_path for f in rep.failures] == [
        "_G/db/Units/Planes/Plane/Su-27#/SFM_Data/aerodynamics/table_data"
    ]


# --- Quaggles fetch -----------------------------------------------------------


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_fetch_quaggles(tmp_path: Path) -> None:
    upstream = tmp_path / "upstream"
    write(
        upstream / "_G" / "rockets" / "R.lua",
        '_G["rockets"]["#Index"] = { name = "R" }',
    )

    def git(*args: str, cwd: Path = upstream) -> None:
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
        )

    git("init", "-q")
    git("add", ".")
    git("commit", "-qm", "v1")
    git("tag", "v1")
    write(
        upstream / "_G" / "rockets" / "R.lua",
        '_G["rockets"]["#Index"] = { name = "R2" }',
    )
    git("commit", "-qam", "v2")
    dest = coverage.fetch_quaggles("v1", tmp_path / "q", str(upstream))
    assert '"R"' in (dest / "_G" / "rockets" / "R.lua").read_text(encoding="utf-8")
    git("tag", "v2")  # not in the clone yet: fetched
    coverage.fetch_quaggles("v2", dest, str(upstream))
    assert '"R2"' in (dest / "_G" / "rockets" / "R.lua").read_text(encoding="utf-8")


def test_row_values_follow_dcs_columns() -> None:
    from tools.datamine.coverage import _row_values

    row = {
        "mach": 0.2,
        "thrustAfterburner": 3,
        "thrustMilitary": 2,
    }  # sorted, as on disk
    assert _row_values(row) == [0.2, 2, 3]
