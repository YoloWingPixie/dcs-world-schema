"""The argument probe: probe-call.lua against stand-ins for DCS's C functions
(tests/lua/test_probe_call.lua), the hook against stubbed Lua states with a
crash and a resume (tests/lua/test_api_probe.lua), and api_probe.py's plan,
deny list and probe.json. The Lua tests are skipped without lua5.1/luajit."""

import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from conftest import hold, write

from tools.datamine import api_probe, probe_mission
from tools.datamine.api_probe import ContextRule, Deny
from tools.datamine.common import (
    HOOK_DIR,
    LATEST,
    REFERENCE_DATA_DIR,
    CacheState,
    json_text,
)

TESTS_LUA = Path(__file__).parent / "lua"
LUA = shutil.which("lua5.1") or shutil.which("luajit")
VERSION = "9.9.9.7"
needs_lua = pytest.mark.skipif(LUA is None, reason="lua5.1/luajit not installed")


def _fn(what: str = "C") -> dict[str, Any]:
    return {"type": "function", "what": what}


def _table(members: dict[str, Any], class_name: str | None = None) -> dict[str, Any]:
    node = {
        "type": "table",
        "members": [
            {"key": k, "keyType": "string", "value": v} for k, v in members.items()
        ],
    }
    if class_name:
        node["className"] = class_name
    return node


def _dump(env: str, globals_: dict[str, Any]) -> dict[str, Any]:
    return {
        "format": "dcs-api-dump/2",
        "env": env,
        "dcsVersion": VERSION,
        "status": "ok",
        "globals": globals_,
    }


DUMPS = {
    "scripting": {
        "Group": _table({"getByName": _fn()}, "Group"),
        "Unit": _table({"getName": _fn(), "destroy": _fn()}, "Unit"),
        "Weapon": _table({"getLauncher": _fn()}, "Weapon"),
        "alias": _fn(),
        "boom": _fn(),
        "env": _table({"crash": _fn(), "info": _fn()}),
        "gone": _table({"fn": _fn()}),
        "trigger": _table({"action": _table({"outText": _fn()})}),
        "writer": _fn("Lua"),
    },
    "hooks": {"hooksFn": _fn(), "net": _table({"stop_game": _fn()})},
    "export": {"LoGetModelTime": _fn()},
}
DENY = [
    Deny("env.crash", "Crashes the mission environment.", False, None),
    Deny("net.stop_*", "Stops the game.", True, ("hooks",)),
]
MISSION = probe_mission.Mission({}, {"groups": ["probe-air"]}, {"airbase": "Batumi"})
RULES = [ContextRule(("Group.getByName",), "groups", 1, None)]


def _api_dir(root: Path) -> Path:
    api = root / "api"
    for env, globals_ in DUMPS.items():
        write(api / f"{env}.json", json.dumps(_dump(env, globals_)))
    write(api / "server.json", json.dumps({**_dump("server", {}), "status": "sameAs"}))
    return api


def _plan(tmp_path: Path, **kw: Any) -> dict[str, Any]:
    return api_probe.plan(
        _api_dir(tmp_path),
        DENY,
        VERSION,
        mission=MISSION,
        rules=RULES,
        documented={"Unit.getName"},
        **kw,
    )


def test_plan_entries_and_order(tmp_path: Path) -> None:
    p = _plan(tmp_path)
    assert p["envs"] == ["scripting", "hooks", "export"]
    # Weapon methods first (they wait for a shell), then the undocumented
    # functions of every env, the documented ones, destroy/remove last.
    assert [(e["env"], e["path"]) for e in p["entries"]] == [
        ("scripting", "Weapon.getLauncher"),
        ("scripting", "Group.getByName"),
        ("scripting", "alias"),
        ("scripting", "boom"),
        ("scripting", "env.crash"),
        ("scripting", "env.info"),
        ("scripting", "gone.fn"),
        ("scripting", "trigger.action.outText"),
        ("scripting", "writer"),
        ("hooks", "hooksFn"),
        ("hooks", "net.stop_game"),
        ("export", "LoGetModelTime"),
        ("scripting", "Unit.getName"),
        ("scripting", "Unit.destroy"),
    ]
    (get_name,) = [e for e in p["entries"] if e["path"] == "Unit.getName"]
    assert get_name == {
        "env": "scripting",
        "path": "Unit.getName",
        "keys": ["Unit", "getName"],
        "what": "C",
        "name": "getName",
        "owner": "Unit",
        "documented": True,
    }
    (by_name,) = [e for e in p["entries"] if e["path"] == "Group.getByName"]
    assert by_name["context"] == {1: {"string": "probe-air"}}
    assert p["deny"][1] == {
        "pattern": "net.stop_*",
        "reason": "Stops the game.",
        "envs": ["hooks"],
    }
    assert p["samples"] == {"airbase": "Batumi"} and p["mission"] == MISSION.id
    assert _plan(tmp_path)["id"] == p["id"]
    # Carried crashes are denied but keep the plan (and its progress file).
    carried = [{"env": "scripting", "path": "boom", "plan": "old"}]
    assert _plan(tmp_path, carried=carried)["id"] == p["id"]
    assert api_probe.plan(tmp_path / "api", DENY[:1], VERSION)["id"] != p["id"]
    other = probe_mission.Mission({"mission": "x"}, {}, {})
    assert (
        _plan(tmp_path)["id"]
        != api_probe.plan(
            tmp_path / "api", DENY, VERSION, mission=other, documented=set()
        )["id"]
    )
    text = api_probe.plan_lua(_plan(tmp_path, carried=carried))
    assert text.startswith("-- The API probe's plan") and f'id = "{p["id"]}"' in text
    assert '["pattern"] = "boom"' in text and "plan old" in text
    assert '["context"] = {[1] = {["string"] = "probe-air"}}' in text


def test_context_rules() -> None:
    rules = [
        ContextRule(("Group.getByName",), "groups", 1, None),
        ContextRule(("coalition.get*",), "sides", 1, None),
        ContextRule(("coalition.getGroups",), "countries", 2, ("hooks",)),
    ]
    pools: dict[str, list[Any]] = {
        "groups": ["G1", "G2"],
        "sides": [2, 1],
        "countries": [2, 0],
    }
    ctx = api_probe.context
    assert ctx("scripting", "Group.getByName", rules, pools) == {1: {"string": "G1"}}
    assert ctx("scripting", "coalition.getGroups", rules, pools) == {1: {"number": 2}}
    assert ctx("hooks", "coalition.getGroups", rules, pools) == {
        1: {"number": 2},
        2: {"number": 2},
    }
    assert ctx("scripting", "Group.getByName", rules, {"groups": []}) == {}
    assert ctx("scripting", "Unit.getByName", rules, pools) == {}


def test_overlay_context_rules_match_the_committed_dumps() -> None:
    api = REFERENCE_DATA_DIR / LATEST / "api"
    if not (api / "scripting.json").is_file():
        pytest.skip("no committed API dump")
    version = json.loads((api / "scripting.json").read_text())["dcsVersion"]
    rules = api_probe.context_rules(version)
    mission = probe_mission.build(probe_mission.spec(version), None)
    p = api_probe.plan(api, [], version, mission=mission, rules=rules)
    assert api_probe.unused_context(p, rules) == []
    by_path = {(e["env"], e["path"]): e for e in p["entries"]}
    assert by_path[("scripting", "Group.getByName")]["context"] == {
        1: {"string": "PROBE_PLANE_BLUE"}
    }
    assert by_path[("scripting", "trigger.misc.getZone")]["context"] == {
        1: {"string": "PROBE_ZONE_C"}
    }
    assert by_path[("scripting", "coalition.getGroups")]["context"] == {
        1: {"number": 2}
    }
    # Undocumented functions come before documented ones.
    documented = [
        bool(e.get("documented"))
        for e in p["entries"]
        if e.get("owner") != "Weapon" and not api_probe._LAST.match(e["name"])
    ]
    assert documented == sorted(documented) and True in documented


def test_documented_paths(tmp_path: Path) -> None:
    paths = api_probe.documented_paths()
    assert "Group.getByName" in paths
    assert "trigger.action.outText" in paths
    # Inherited: Object's methods are documented on its subclasses too.
    assert "Object.getName" in paths and "Unit.getName" in paths
    schema = tmp_path / "schema" / "globals"
    write(
        schema / "Thing.class.yaml",
        "globals:\n  Thing:\n    kind: class\n    instance:\n"
        "      known: {description: Known., params: [], returns: void}\n"
        '      odd: {description: "Present in DCS 1.0; signature not documented.",'
        " returns: any}\n"
        "types: {}\n",
    )
    # "signature not documented" members are not.
    assert api_probe.documented_paths(schema.parent) == {"Thing.known"}


def test_metatable_and_number_keys() -> None:
    dump = _dump(
        "hooks",
        {
            "net": {
                "type": "table",
                "members": [{"key": 1, "keyType": "number", "value": _fn("Lua")}],
                "metatable": _table({"__index": _fn()}),
            }
        },
    )
    entries = api_probe.functions(dump)
    assert [(e["path"], e["keys"], e["name"]) for e in entries] == [
        ("net[1]", ["net", 1], "1"),
        ("net<metatable>.__index", ["net", {"m": True}, "__index"], "__index"),
    ]


def test_deny_matching() -> None:
    d = Deny("dxgui.*", "GUI", True, None)
    assert d.matches("scripting", "dxgui.Button.new")
    assert not d.matches("scripting", "dxguiWin.new")
    assert Deny("*LoSetCommand", "x", True, None).matches(
        "hooks", "Export.LoSetCommand"
    )
    only = Deny("RPC.*", "x", True, ("hooks",))
    assert only.matches("hooks", "RPC.call") and not only.matches(
        "scripting", "RPC.call"
    )


def test_overlay_deny_list_covers_run_ending_functions() -> None:
    deny = api_probe.deny_list()
    patterns = {d.pattern for d in deny}
    for name in (
        "DCS.exitProcess",
        "DCS.stopMission",
        "DCS.setUserCallbacks",
        "DCS.reloadUserScripts",
        "net.stop_game",
        "net.stop_network",
        "net.load_mission",
        "net.kick",
        "env.crash",
        "env.exit",
        "lfs.mkdir",
        "lfs.rmdir",
        "lfs.chdir",
        "log.set_output",
        "world.addEventHandler",
    ):
        assert name in patterns, name
    assert all(d.reason for d in deny)


def test_overlay_deny_list_matches_the_committed_dumps() -> None:
    api = REFERENCE_DATA_DIR / LATEST / "api"
    if not (api / "scripting.json").is_file():
        pytest.skip("no committed API dump")
    version = json.loads((api / "scripting.json").read_text())["dcsVersion"]
    deny = api_probe.deny_list(version)
    p = api_probe.plan(api, deny, version)
    assert api_probe.unused(p, deny) == []
    hits = api_probe.denied(p, deny)
    for env in ("scripting", "hooks"):
        assert (env, "DCS.exitProcess") in hits
    assert ("hooks", "net.stop_game") in hits
    assert ("export", "lfs.mkdir") in hits
    assert ("scripting", "Unit.getName") not in hits


def test_parse_progress_marks_the_call_in_flight_crashed() -> None:
    text = (
        "P\tabc\n"
        "V\t9.9.9.7\n"
        'X\t{"setup":{"air":"ok"}}\n'
        "S\tscripting\ta\n"
        'R\tscripting\ta\t{"status":"ok","minArgs":0}\n'
        "S\tscripting\tb\n"
        'X\t{"weapon":true}\n'
    )
    pid, samples, results = api_probe.parse_progress(text)
    assert pid == "abc"
    assert samples == {"setup": {"air": "ok"}, "weapon": True}
    assert results[("scripting", "b")] == {"status": "crashed"}
    assert results[("scripting", "a")]["minArgs"] == 0
    assert api_probe.progress_version(text) == "9.9.9.7"


def test_progress_version_from_the_plan_file() -> None:
    text = "P\tabc\nS\tscripting\tb\n"
    plan_text = 'return {\n  id = "abc",\n  version = "9.9.9.7",\n}\n'
    assert api_probe.progress_version(text) is None
    assert api_probe.progress_version(text, plan_text) == "9.9.9.7"
    assert api_probe.progress_version(text, plan_text.replace("abc", "xyz")) is None


def test_harvest_carries_crashes_per_dcs_version(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    text = (
        "P\tabc\nV\t9.9.9.7\n"
        'S\tscripting\ta\nR\tscripting\ta\t{"status":"ok"}\n'
        'S\tscripting\tb\nR\tscripting\tb\t{"status":"crashed"}\n'
        "S\thooks\tc\n"
    )
    added = api_probe.harvest(cache, text, VERSION)
    assert added == [
        {"env": "hooks", "path": "c", "plan": "abc"},
        {"env": "scripting", "path": "b", "plan": "abc"},
    ]
    assert api_probe.harvest(cache, text, VERSION) == []
    assert len(api_probe.carried_crashes(cache, VERSION)) == 2
    # Another DCS version: its progress adds nothing, its crashes start over.
    assert api_probe.carried_crashes(cache, "1.0") == []
    assert api_probe.harvest(cache, text, "1.0") == []
    other = text.replace("9.9.9.7", "1.0")
    assert [c["path"] for c in api_probe.harvest(cache, other, "1.0")] == ["c", "b"]
    assert api_probe.carried_crashes(cache, VERSION) == []


def test_document_of_a_partial_run_with_carried_crashes(tmp_path: Path) -> None:
    carried = [{"env": "scripting", "path": "boom", "plan": "old"}]
    p = _plan(tmp_path, carried=carried)
    text = (
        f"P\t{p['id']}\nV\t{VERSION}\n"
        'R\tscripting\tWeapon.getLauncher\t{"status":"ok","minArgs":1}\n'
        'R\tscripting\tboom\t{"status":"denied","reason":"x"}\n'
    )
    doc = api_probe.document(p, text)
    s = doc["envs"]["scripting"]
    assert doc["stats"]["complete"] is False and doc["plan"] == p["id"]
    assert s["boom"]["status"] == "crashed" and s["boom"]["carriedFrom"] == "old"
    assert s["Unit.getName"]["status"] == "notRun" and s["Unit.getName"]["documented"]
    assert doc["stats"]["scripting"]["notRun"] == 9
    other = api_probe.document(p, "P\tother\n")
    assert other["stats"]["complete"] is False
    assert other["envs"]["scripting"]["Weapon.getLauncher"]["status"] == "notRun"


def test_template() -> None:
    t = api_probe.template
    assert (
        t("bad argument #2 to 'outText' (number expected, got no value)")
        == "bad argument #N to '…' (T expected, got X)"
    )
    assert t("Parameter #1 (unit name) missed") == "Parameter #N (unit name) missed"


def test_version_files(tmp_path: Path) -> None:
    cache = replace(api_probe.CACHE, dir=tmp_path / "cache")
    assert cache.version_files(VERSION, tmp_path) == {}
    hold(tmp_path, VERSION)
    old = json_text({"dcsVersion": VERSION, "envs": {}})
    write(tmp_path / LATEST / "api" / "probe.json", old)
    own = {"api/probe.json": old.encode("utf-8")}
    assert cache.version_files(VERSION, tmp_path) == own
    partial = {"stats": {"complete": False}}
    cache.write(partial, VERSION, "inputs")
    assert cache.version_files(VERSION, tmp_path) == {
        "api/probe.json": b'{\n  "stats": {\n    "complete": false\n  }\n}\n'
    }
    assert cache.status(VERSION, "inputs") == (
        CacheState.PARTIAL,
        "cached probe is partial",
    )
    cache.write({"stats": {"complete": True}}, VERSION, "inputs")
    assert not (cache.dir / "partial").exists()
    assert cache.stale(VERSION, "inputs") is None
    assert cache.status(VERSION, "other")[0] is CacheState.INPUTS_CHANGED
    assert cache.stale("1.0", "inputs") == f"cached probe is DCS {VERSION}"
    # Not cached and older than latest: nothing.
    assert cache.version_files("1.0", tmp_path) == {}


def test_version_without_a_probe_carries_latest_forward(tmp_path: Path) -> None:
    cache = replace(api_probe.CACHE, dir=tmp_path / "cache")
    probe = tmp_path / LATEST / "api" / "probe.json"
    hold(tmp_path, "9.9.9.1")
    doc: dict[str, Any] = {"dcsVersion": "9.9.9.1", "envs": {"hooks": {}}}
    write(probe, json_text(doc))
    # latest's own probe wins; a newer version gets it carried forward.
    assert "probedOn" not in json.loads(
        cache.version_files("9.9.9.1", tmp_path)["api/probe.json"]
    )
    carried = json.loads(cache.version_files("9.9.9.2", tmp_path)["api/probe.json"])
    assert carried == {
        "dcsVersion": "9.9.9.2",
        "probedOn": "9.9.9.1",
        "envs": {"hooks": {}},
    }
    # Carried on again it keeps the version it was probed on.
    hold(tmp_path, "9.9.9.2")
    write(probe, json_text(carried))
    assert json.loads(cache.version_files("9.9.9.2", tmp_path)["api/probe.json"]) == (
        carried
    )
    later = json.loads(cache.version_files("9.9.10.1", tmp_path)["api/probe.json"])
    assert (later["dcsVersion"], later["probedOn"]) == ("9.9.10.1", "9.9.9.1")
    # A newer latest is never carried back.
    assert cache.version_files("9.9.7.1", tmp_path) == {}


@needs_lua
def test_probe_call() -> None:
    out = subprocess.run(
        [str(LUA), str(TESTS_LUA / "test_probe_call.lua"), str(HOOK_DIR)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 0, out.stdout + out.stderr
    assert "PROBE CALL TEST DONE" in out.stdout


def _hook_run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(LUA), str(TESTS_LUA / "test_api_probe.lua"), str(TESTS_LUA), f"{root}/"],
        capture_output=True,
        text=True,
        check=False,
    )


def _install(root: Path, p: dict[str, Any]) -> Path:
    hooks = root / "Scripts" / "Hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    for path in api_probe.PROBE_HOOKS:
        shutil.copy(path, hooks / path.name)
    write(hooks / api_probe.PLAN_NAME, api_probe.plan_lua(p))
    return root / "DCS.Lua.Exporter" / "probe" / api_probe.PROGRESS


@needs_lua
def test_hook_crash_resume_and_deny(tmp_path: Path) -> None:
    p = _plan(tmp_path)
    root = tmp_path / "sg"
    progress = _install(root, p)

    first = _hook_run(root)
    assert first.returncode == 3, first.stdout + first.stderr
    lines = progress.read_text().splitlines()
    assert lines[:2] == [f"P\t{p['id']}", f"V\t{VERSION}"]
    assert lines[-1] == "S\tscripting\tboom"
    # Heartbeats while waiting for the warm-up and the Weapon sample.
    assert any(line.startswith("H\t") for line in lines)

    second = _hook_run(root)
    assert second.returncode == 0, second.stdout + second.stderr
    assert "API PROBE TEST DONE" in second.stdout
    assert "boom crashed in an earlier run" in second.stdout
    text = progress.read_text()
    # Entries recorded before the crash are not called again.
    assert text.count("S\tscripting\tGroup.getByName\n") == 1

    # Denied functions never ran, under any of their names.
    assert not list(root.glob("called-*"))
    doc = api_probe.document(p, text)
    s, hooks = doc["envs"]["scripting"], doc["envs"]["hooks"]
    assert s["env.crash"]["status"] == "denied"
    assert s["alias"] == {
        "conclusive": False,
        "reason": "same function as env.crash: Crashes the mission environment.",
        "source": "probe",
        "status": "denied",
        "what": "C",
    }
    assert hooks["net.stop_game"]["reason"] == "Stops the game."
    assert s["boom"]["status"] == "crashed"

    # Signatures.
    out_text = s["trigger.action.outText"]
    assert (out_text["status"], out_text["minArgs"], out_text["conclusive"]) == (
        "ok",
        2,
        True,
    )
    assert [q["expected"] for q in out_text["params"]] == ["string", "number"]
    get_name = s["Unit.getName"]
    assert get_name["status"] == "ok" and get_name["owner"] == "Unit"
    # Its self is the owner class's sample: still conclusive.
    assert get_name["params"][0]["from"] == "self" and get_name["conclusive"]
    assert get_name["params"][0]["sample"] == "Unit"
    assert get_name["returns"] == [{"type": "string"}]
    assert s["Weapon.getLauncher"]["returns"] == [
        {"className": "Unit", "type": "table"}
    ]
    assert s["writer"]["status"] == "blocked" and s["writer"]["blocked"] == "os.remove"
    assert s["gone.fn"]["status"] == "missing"
    assert s["env.info"]["params"][0]["expected"] == "string"
    assert hooks["hooksFn"]["params"][0]["expected"] == "number"
    assert doc["envs"]["export"]["LoGetModelTime"]["returns"] == [{"type": "number"}]
    # The plan names the airbase; the aircraft is not in the mission: spawned.
    assert doc["samples"]["setup"]["airbase"] == "mission"
    assert doc["samples"]["setup"]["air"] == "spawned"
    by_name = s["Group.getByName"]
    assert by_name["returns"] == [{"className": "Group", "type": "table"}]
    assert by_name["params"][0]["value"] == "probe-air"
    assert doc["stats"]["complete"] is True
    assert doc["samples"]["setup"]["static"] != "ok"
    assert doc["samples"]["available"]["Unit"] is True
    assert doc["samples"]["weapon"] is True
    assert doc["stats"]["scripting"]["denied"] == 2
    assert {
        "template": "bad argument #N to '…' (T expected, got X)",
        "count": 5,
    } in doc["errorFormats"]
    assert json_text(api_probe.document(p, text)) == json_text(doc)


@needs_lua
def test_hook_restarts_a_progress_file_of_another_plan(tmp_path: Path) -> None:
    p = _plan(tmp_path)
    root = tmp_path / "sg"
    progress = _install(root, p)
    write(root / "boom-once", "")
    write(progress, 'P\tother\nR\tscripting\tboom\t{"status":"ok"}\n')
    out = _hook_run(root)
    assert out.returncode == 0, out.stdout + out.stderr
    doc = api_probe.document(p, progress.read_text())
    assert doc["envs"]["scripting"]["boom"]["status"] == "ok"
    assert "notRun" not in doc["stats"]["scripting"]


def test_read_plan_lua_round_trips_the_plan(tmp_path: Path) -> None:
    carried = [{"env": "scripting", "path": "boom", "plan": "old"}]
    p = _plan(tmp_path, carried=carried)
    back = api_probe.read_plan_lua(api_probe.plan_lua(p))
    assert (back["id"], back["version"], back["envs"]) == (
        p["id"],
        p["version"],
        p["envs"],
    )
    assert back["carried"] == carried and back["deny"] == p["deny"]
    strip = [{k: v for k, v in e.items() if k != "context"} for e in p["entries"]]
    assert [
        {k: v for k, v in e.items() if k != "context"} for e in back["entries"]
    ] == strip


def test_document_offline_caches_and_installs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api_probe, "current_inputs", lambda version: "inputs")
    p = _plan(tmp_path)
    plan_file = tmp_path / "api-probe-plan.lua"
    plan_file.write_text(api_probe.plan_lua(p), encoding="utf-8")
    progress = tmp_path / "progress.tsv"
    progress.write_text(
        f"P\t{p['id']}\nV\t{VERSION}\n"
        'R\tscripting\tWeapon.getLauncher\t{"status":"ok","minArgs":0}\n'
        "S\tscripting\tboom\n",
        encoding="utf-8",
    )
    data, cache = tmp_path / "data", tmp_path / "cache"
    hold(data, VERSION)
    write(data / LATEST / "weapons" / "A.json", "{}")
    doc = api_probe.document_offline(progress, plan_file, cache, data)
    assert doc["stats"]["complete"] is False
    assert doc["envs"]["scripting"]["boom"]["status"] == "crashed"
    assert json.loads((data / LATEST / "api" / "probe.json").read_text()) == doc
    assert (data / LATEST / "weapons" / "A.json").is_file()
    assert (cache / "partial").read_text() == VERSION
    crashed = json.loads((cache / api_probe.CRASHED).read_text())["crashed"]
    assert crashed == [{"env": "scripting", "path": "boom", "plan": p["id"]}]
    progress.write_text("P\tother\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        api_probe.document_offline(progress, plan_file, cache, data)


def test_signature_of_conclusive_records() -> None:
    rec = {
        "status": "ok",
        "what": "C",
        "minArgs": 2,
        "params": [
            {"position": 1, "from": "error", "expected": "string"},
            {"position": 2, "from": "error", "expected": "number"},
        ],
        "returns": [{"type": "table", "className": "Unit"}, {"type": "nil"}],
        "extraArgs": False,
    }
    assert api_probe.signature(rec, classes=frozenset({"Unit"})) == {
        "params": [
            {"name": "param1", "type": "string"},
            {"name": "param2", "type": "number"},
        ],
        "returns": ["Unit", "any"],
    }
    assert api_probe.signature(rec)["returns"] == ["table", "any"]
    assert api_probe.probed_text(rec, "1.0") == (
        "Signature probed (DCS 1.0): 2 required argument types from DCS errors; "
        "returns from one call; rejects an extra argument."
    )
    method = {
        "status": "ok",
        "what": "Lua",
        "minArgs": 1,
        "paramNames": ["self", "name", "new"],
        "params": [{"position": 1, "from": "self", "sample": "Unit"}],
    }
    assert api_probe.signature(method, method=True) == {
        "params": [
            {"name": "name", "type": "any", "optional": True},
            {"name": "new_", "type": "any", "optional": True},
        ],
        "returns": "any",
    }
    assert api_probe.signature({"status": "ok", "minArgs": 0})["returns"] == "void"
    partial = {"params": [{"position": 2, "from": "error", "expected": "unzFile"}]}
    assert api_probe.partial_text(partial, "1.0") == (
        "Probe (DCS 1.0): argument 2 must be a unzFile."
    )
    assert api_probe.partial_text({"params": [{"from": "usage"}]}, "1.0") is None


def test_probe_record_follows_same_as() -> None:
    records = {
        "a": {"status": "sameAs", "sameAs": "b"},
        "b": {"status": "ok"},
        "c": {"status": "sameAs", "sameAs": "c"},
    }
    assert api_probe.probe_record(records, "a") == {"status": "ok"}
    assert (api_probe.probe_record(records, "c") or {})["status"] == "sameAs"
    assert api_probe.probe_record(records, "x") is None
