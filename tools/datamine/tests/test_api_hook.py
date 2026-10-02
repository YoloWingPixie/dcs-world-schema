"""The API dump hook (hook/api-dump.lua, api-walk.lua) under Lua 5.1 or LuaJIT
against stubbed Lua states (tests/lua/test_api_dump.lua). Skipped when neither
is installed."""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest

TESTS_LUA = Path(__file__).parent / "lua"
HOOK_DIR = Path(__file__).parents[1] / "hook"
LUA = shutil.which("lua5.1") or shutil.which("luajit")
API_HOOKS = ("api-dump.lua", "api-walk.lua")
ENVS = ("scripting", "hooks", "server", "export")

pytestmark = pytest.mark.skipif(LUA is None, reason="lua5.1/luajit not installed")


def _run(*args: str) -> str:
    result = subprocess.run(
        [str(LUA), *args], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def api_dump(root: Path, mode: str = "ok") -> Path:
    """Run the hook in ``root`` (its writedir); the api output dir."""
    hooks = root / "Scripts" / "Hooks"
    hooks.mkdir(parents=True)
    for name in API_HOOKS:
        shutil.copy(HOOK_DIR / name, hooks / name)
    out = _run(str(TESTS_LUA / "test_api_dump.lua"), str(TESTS_LUA), f"{root}/", mode)
    assert "API DUMP TEST DONE" in out
    api = root / "DCS.Lua.Exporter" / "api"
    assert (api / "done").read_text() == "9.9.9.7"
    return api


def _dumps(tmp_path: Path, mode: str = "ok") -> dict[str, dict[str, Any]]:
    api = api_dump(tmp_path, mode)
    return {
        env: json.loads((api / f"{env}.json").read_text(encoding="utf-8"))
        for env in ENVS
    }


def _member(node: dict[str, Any], key: str | int) -> dict[str, Any]:
    (value,) = [m["value"] for m in node["members"] if m["key"] == key]
    return cast(dict[str, Any], value)


def test_environments(tmp_path: Path) -> None:
    dumps = _dumps(tmp_path)
    s = dumps["scripting"]
    assert s["format"] == "dcs-api-dump/2" and s["status"] == "ok"
    assert (s["env"], s["state"], s["dcsVersion"]) == (
        "scripting",
        "scripting",
        "9.9.9.7",
    )
    assert s["paths"] == {"installDir": "C:/DCS World/", "writeDir": f"{tmp_path}/"}
    # The standard library is listed, not walked; the sanitized io is absent.
    assert "string" in s["excluded"] and "io" not in s["excluded"]
    assert sorted(s["globals"]) == ["CoalitionObject", "Object", "Unit", "env", "misc"]
    hooks = dumps["hooks"]
    assert "state" not in hooks and {"guiTable", "Export"} <= hooks["globals"].keys()
    assert "io" in hooks["excluded"]
    assert sorted(dumps["server"]["globals"]) == ["net"]
    assert sorted(dumps["export"]["globals"]) == ["LoGetModelTime", "LoGetSelfData"]
    assert dumps["export"]["globals"]["LoGetModelTime"]["what"] == "Lua"


def test_classes_and_metatables(tmp_path: Path) -> None:
    unit = _dumps(tmp_path)["scripting"]["globals"]["Unit"]
    assert unit["className"] == "Unit" and unit["parentClass"] == "CoalitionObject"
    # A global's table is written at the global; elsewhere it is a ref.
    assert _member(unit, "parentClass_") == {"ref": "CoalitionObject", "type": "table"}
    assert _member(unit["metatable"], "__index") == {
        "ref": "CoalitionObject",
        "type": "table",
    }
    assert _member(unit, "Category")["members"][0]["key"] == "AIRPLANE"
    fn = _member(unit, "getByName")
    assert fn["what"] == "Lua" and fn["source"].endswith("test_api_dump.lua")
    assert fn["linedefined"] > 0


def test_api_only_walk(tmp_path: Path) -> None:
    misc = _dumps(tmp_path)["scripting"]["globals"]["misc"]
    # Data (no reachable function) is summarised unless a small constant table.
    assert _member(misc, "data") == {"entries": 600, "summary": "data", "type": "table"}
    assert _member(misc, "records") == {
        "entries": 2,
        "summary": "data",
        "type": "table",
    }
    assert _member(misc, "records2") == {
        "entries": 1,
        "summary": "data",
        "type": "table",
    }
    assert _member(misc, "tooDeep") == {
        "entries": 1,
        "summary": "data",
        "type": "table",
    }
    enum = _member(misc, "enum")
    node = _member(_member(_member(_member(enum, "B"), "D"), "E"), "F")
    assert _member(node, "G") == {"type": "number", "value": 1}
    # A table whose metatable reaches a function is API and walked.
    obj = _member(misc, "obj")
    assert _member(obj, "x")["value"] == 1
    assert _member(obj["metatable"], "__index")["members"][0]["key"] == "get"
    # A standard-library global is a ref to its name.
    assert _member(misc, "str") == {"ref": "string", "type": "table"}


def test_server_same_state(tmp_path: Path) -> None:
    api = api_dump(tmp_path, "server_is_scripting")
    server = json.loads((api / "server.json").read_text(encoding="utf-8"))
    assert server["status"] == "sameAs" and server["sameAs"] == "scripting"
    assert server["state"] == "server" and "globals" not in server


def test_states_probe(tmp_path: Path) -> None:
    api = api_dump(tmp_path)
    states = json.loads((api / "states.json").read_text(encoding="utf-8"))
    assert states["format"] == "dcs-api-dump/2" and states["dcsVersion"] == "9.9.9.7"
    s = states["states"]
    assert s["scripting"] == {"env": "scripting", "status": "ok"}
    assert s["gui"] == {"env": "hooks", "status": "ok"}
    assert s["mission"] == {
        "globals": {"a_do_script": "function", "mission": "table"},
        "status": "ok",
    }
    assert s["config"]["status"] == "unavailable"


def test_values(tmp_path: Path) -> None:
    misc = _dumps(tmp_path)["scripting"]["globals"]["misc"]
    keys = [(m["keyType"], m["key"]) for m in misc["members"]]
    # Number keys first, and 1 and "1" stay apart.
    assert keys[:3] == [("number", 1), ("number", 2.5), ("string", "1")]
    assert keys[2:] == sorted(keys[2:])
    assert misc["skippedKeys"] == {"boolean": 1}
    assert _member(misc, "inf") == {"nonFinite": True, "type": "number", "value": "inf"}
    assert _member(misc, "ninf")["value"] == "-inf"
    assert _member(misc, "nan")["value"] == "nan"
    assert _member(misc, "big")["value"] == 2**40
    assert _member(misc, "frac")["value"] == 0.1
    assert _member(misc, "bad") == {
        "invalidUtf8": True,
        "type": "string",
        "value": "caf\u00e9",
    }
    assert _member(misc, "utf") == {"type": "string", "value": "café"}
    assert _member(misc, "ctl")["value"] == "a\x00b\n"
    long = _member(misc, "long")
    assert (long["truncated"], long["length"], len(long["value"])) == (
        "length",
        5000,
        4096,
    )
    # A shared table is written once, later places are refs; so is a cycle.
    assert _member(misc, "shared1")["members"][0]["key"] == "a"
    assert _member(misc, "shared2") == {"ref": "misc.shared1", "type": "table"}
    loop = _member(misc, "loop")
    assert _member(loop, "self") == {"ref": "misc.loop", "type": "table"}
    node = _member(misc, "deep")
    for level in ("l1", "l2", "l3", "l4", "l5", "l6", "l7"):
        node = _member(node, level)
    assert node == {"size": 2, "truncated": "depth", "type": "table"}


def test_without_debug_library(tmp_path: Path) -> None:
    unit = _dumps(tmp_path, "no_debug")["scripting"]["globals"]["Unit"]
    assert _member(unit, "getByName") == {"type": "function", "what": "unknown"}
    assert "metatable" in unit  # from getmetatable


@pytest.mark.parametrize(
    ("mode", "error"),
    [
        ("export_unavailable", 'net.dostring_in failed: Lua state "export" not found'),
        ("export_raises", "net.dostring_in raised: "),
    ],
)
def test_export_unavailable(tmp_path: Path, mode: str, error: str) -> None:
    dumps = _dumps(tmp_path, mode)
    export = dumps["export"]
    assert export["status"] == "unavailable" and export["error"].startswith(error)
    assert "globals" not in export and export["state"] == "export"
    # The other states are still dumped, and the run completes.
    assert all(dumps[e]["status"] == "ok" for e in ("scripting", "hooks", "server"))


def test_numbers_under_dcs_c_runtime() -> None:
    # Decimal-comma locale and a 32-bit C long, as DCS on Windows may run.
    walk, encoded = _run(
        str(TESTS_LUA / "test_number_locale.lua"), str(HOOK_DIR)
    ).splitlines()
    expected = {"half": 0.5, "big": 2**40, "neg": -(2**33), "tiny": 1.25e-7}
    globals_ = json.loads(walk)["globals"]
    assert {k: v["value"] for k, v in globals_.items()} == expected
    assert json.loads(encoded) == expected


def test_walk_budget() -> None:
    data = json.loads(_run(str(TESTS_LUA / "test_api_walk.lua"), str(HOOK_DIR)))
    assert data["limits"] == {
        "apiDepth": 1,
        "enumDepth": 4,
        "enumEntries": 500,
        "maxDepth": 8,
        "maxString": 4096,
        "maxTables": 2,
        "scanBudget": 200000,
    }
    # The budget is per global: a's third table is cut, b is walked.
    assert data["stats"] == {
        "refs": 0,
        "summarised": 0,
        "tables": 3,
        "truncatedBudget": 1,
        "truncatedDepth": 0,
    }
    a = data["globals"]["a"]
    assert a["members"][1]["value"] == {"truncated": "budget", "type": "table"}
    assert data["globals"]["b"] == {"members": [], "type": "table"}
    assert data["skippedKeys"] == {"number": 1}
    assert data["excluded"] == ["pairs"]
