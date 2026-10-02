"""The API dump's cache, version-dir files, legacy verify view, the Export.lua
comment parser and the generated env schemas."""

import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import write
from jsonschema import Draft7Validator

from tools import verify
from tools.datamine import api_dump, api_schema, export_docs
from tools.datamine.common import REPO_ROOT, CacheState, series_records
from tools.merge import merge_tree

VERSION = "9.9.9.7"


def fn(what: str = "C", **kw: Any) -> dict[str, Any]:
    return {"type": "function", "what": what, **kw}


def num(v: float) -> dict[str, Any]:
    return {"type": "number", "value": v}


def table(members: dict[str | int, Any], **kw: Any) -> dict[str, Any]:
    return {
        "type": "table",
        "members": [
            {
                "key": k,
                "keyType": "number" if isinstance(k, int) else "string",
                "value": v,
            }
            for k, v in members.items()
        ],
        **kw,
    }


def dump(
    env: str, globals_: dict[str, Any], status: str = "ok", **kw: Any
) -> dict[str, Any]:
    d: dict[str, Any] = {
        "format": api_dump.FORMAT,
        "env": env,
        "dcsVersion": VERSION,
        "paths": {
            "installDir": "C:\\DCS World\\",
            "writeDir": "C:/Users/me/Saved Games/DCS.datamine/",
        },
        "status": status,
        **kw,
    }
    if status == "ok":
        d.update(
            excluded=["string"], globals=globals_, limits={}, skippedKeys={}, stats={}
        )
    return d


def write_cache(
    api_dir: Path, dumps: dict[str, dict[str, Any]], version: str = VERSION
) -> None:
    for env, d in dumps.items():
        write(api_dir / f"{env}.json", json.dumps(d))
    write(api_dir / "done", version)


def all_envs(**over: dict[str, Any]) -> dict[str, dict[str, Any]]:
    base = {
        "scripting": dump(
            "scripting", {"timer": table({"getTime": fn()})}, state="scripting"
        ),
        "hooks": dump("hooks", {"DCS": table({"getModelTime": fn()})}),
        "server": dump("server", {"net": table({"log": fn()})}, state="server"),
        "export": dump(
            "export", {}, status="unavailable", error="no state", state="export"
        ),
    }
    return {**base, **over}


def test_normalize_strips_paths_and_sorts_members() -> None:
    d = dump(
        "hooks",
        {
            "x": table(
                {
                    "b": fn(
                        "Lua", source="@C:\\DCS World\\Scripts\\a.lua", linedefined=3
                    ),
                    "a": fn(
                        "Lua",
                        source="@c:/users/me/saved games/DCS.datamine/Scripts/Hooks/h.lua",
                    ),
                    2: fn("Lua", source="@./Scripts/b.lua"),
                    1: fn("main", source="=[C]"),
                },
                metatable=table({"__index": fn("Lua", source="@C:/DCS World/c.lua")}),
            )
        },
    )
    out = api_dump.normalize(d)
    assert "paths" not in out
    x = out["globals"]["x"]
    assert [m["key"] for m in x["members"]] == [1, 2, "a", "b"]
    sources = [m["value"].get("source") for m in x["members"]]
    assert sources == [
        "=[C]",
        "@<install>/Scripts/b.lua",
        "@<writedir>/Scripts/Hooks/h.lua",
        "@<install>/Scripts/a.lua",
    ]
    assert x["metatable"]["members"][0]["value"]["source"] == "@<install>/c.lua"


def test_stale_and_hook_hash(tmp_path: Path) -> None:
    h = api_dump.hook_hash()
    cache = replace(api_dump.CACHE, dir=tmp_path)
    assert cache.status(VERSION, h) == (CacheState.MISSING, "no cached API dump")
    write(tmp_path / "done", "1.2.3.4")
    assert cache.stale(VERSION, h) == "cached API dump is DCS 1.2.3.4"
    write(tmp_path / "done", VERSION)
    assert cache.status(VERSION, h) == (
        CacheState.INPUTS_CHANGED,
        "API hook changed since it ran",
    )
    write(tmp_path / "hook", h)
    assert cache.stale(VERSION, h) is None


def test_version_files_from_cache_with_docs(tmp_path: Path) -> None:
    cache, install = tmp_path / "api", tmp_path / "install"
    write_cache(cache, all_envs())
    write(
        install / "Scripts" / "Export.lua",
        "--[[\nOutput:\nLoGetModelTime() -- (args - 0, results - 1 (sec))\n--]]\n",
    )
    files = api_dump.version_files(cache, VERSION, install, tmp_path / "ver")
    assert sorted(files) == [
        "api/export.docs.json",
        "api/export.json",
        "api/hooks.json",
        "api/scripting.json",
        "api/server.json",
    ]
    docs = json.loads(files["api/export.docs.json"])
    assert docs["source"] == "Scripts/Export.lua comments"
    assert docs["functions"]["LoGetModelTime"][0]["results"] == "1 (sec)"
    assert api_dump.statuses(files) == {
        "scripting": "ok",
        "hooks": "ok",
        "server": "ok",
        "export": "unavailable: no state",
    }
    # Deterministic: formatted like every other record, no local paths.
    text = files["api/hooks.json"].decode()
    assert (
        text
        == json.dumps(json.loads(text), indent=2, sort_keys=True, ensure_ascii=False)
        + "\n"
    )
    assert "Users" not in text
    # The api/ dir is no series.
    assert series_records({**files, "weapons/A.json": b"{}"}) == {
        "weapons": {"A": b"{}"}
    }


def test_version_files_keep_existing_without_cache(tmp_path: Path) -> None:
    ver = tmp_path / "ver"
    write(ver / "api" / "scripting.json", "{}")
    assert api_dump.version_files(tmp_path / "none", VERSION, None, ver) == {
        "api/scripting.json": b"{}"
    }
    assert (
        api_dump.version_files(tmp_path / "none", VERSION, None, tmp_path / "x") == {}
    )


def test_cached_states_probe_and_same_state(tmp_path: Path) -> None:
    same = dump("server", {}, status="sameAs", sameAs="scripting", state="server")
    write_cache(tmp_path, all_envs(server=same))
    states = {"format": api_dump.FORMAT, "dcsVersion": VERSION, "states": {}}
    write(tmp_path / "states.json", json.dumps(states))
    files = api_dump.cached_files(tmp_path, VERSION, None)
    assert json.loads(files["api/states.json"]) == states
    assert api_dump.statuses(files)["server"] == "sameAs scripting"
    write(tmp_path / "states.json", json.dumps({**states, "dcsVersion": "1.1.1.1"}))
    with pytest.raises(SystemExit):
        api_dump.cached_files(tmp_path, VERSION, None)


def test_cached_files_reject_other_version(tmp_path: Path) -> None:
    write_cache(
        tmp_path, all_envs(hooks={**all_envs()["hooks"], "dcsVersion": "1.1.1.1"})
    )
    with pytest.raises(SystemExit):
        api_dump.cached_files(tmp_path, VERSION, None)


def test_legacy_view_feeds_verify() -> None:
    base = table({"className_": {"type": "string", "value": "Object"}, "isExist": fn()})
    unit = table(
        {
            "className_": {"type": "string", "value": "Unit"},
            "getName": fn(),
            "parentClass_": base,
            "Category": table({"AIRPLANE": num(0)}),
        }
    )
    d = dump("scripting", {"Unit": unit, "Object": base, "notATarget": table({})})
    legacy = api_dump.legacy(d)
    assert sorted(legacy) == ["Object", "Unit"]
    members = {m["name"]: m for m in legacy["Unit"]["members"]}
    assert members["Category"]["sub"]["members"] == [
        {"name": "AIRPLANE", "type": "number", "value": 0}
    ]
    got = verify.extract_dcs(legacy)
    assert got["Unit"] == {"Category", "Category.AIRPLANE", "getName", "isExist"}
    # Refs are followed: to a global, to a path, to an ancestor (no sub).
    ref_unit = table(
        {
            "className_": {"type": "string", "value": "Unit"},
            "getName": fn(),
            "parentClass_": {"type": "table", "ref": "Object"},
            "Category": table(
                {"AIRPLANE": num(0), "self": {"type": "table", "ref": "Unit"}}
            ),
            "Kind": {"type": "table", "ref": "Unit.Category"},
            "data": {"type": "table", "summary": "data", "entries": 9},
        }
    )
    legacy = api_dump.legacy(
        dump(
            "scripting",
            {
                "Unit": ref_unit,
                "Object": base,
                "World": {"type": "table", "ref": "Unit"},
            },
        ),
        targets=("Object", "Unit", "World"),
    )
    assert verify.extract_dcs(legacy)["Unit"] == {
        "Category",
        "Category.AIRPLANE",
        "Category.self",
        "Kind",
        "Kind.AIRPLANE",
        "Kind.self",
        "data",
        "getName",
        "isExist",
    }
    assert legacy["World"] == legacy["Unit"]
    with pytest.raises(SystemExit):
        api_dump.legacy(dump("scripting", {}, status="unavailable", error="x"))


def test_verify_reads_the_first_existing_dump(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    new = write(
        tmp_path / "scripting.json",
        json.dumps(dump("scripting", {"timer": table({"getTime": fn()})})),
    )
    old = write(
        tmp_path / "old.json", json.dumps({"env": {"kind": "table", "members": []}})
    )
    assert verify.load_api([str(tmp_path / "missing.json"), str(new), str(old)]) == {
        "timer": {"kind": "table", "members": [{"name": "getTime", "type": "function"}]}
    }
    with pytest.raises(SystemExit):  # a legacy dump is no longer read
        verify.load_api([str(old)])
    with pytest.raises(SystemExit):
        verify.load_api([str(tmp_path / "missing.json")])


EXPORT_LUA = """\
-- LoSetCommand(3, 0.25) -- rudder 0.25 right
--	local t = LoGetModelTime()
--[[ You can use registered functions
Output:
LoGetModelTime() -- returns current model time (args - 0, results - 1 (sec))
LoGetWorldObjects() -- (args - 0- 1, results - 1 (table of object tables))  arg can be
    "units" (default)
LoGetEngineInfo() -- (args - 0 ,results = table)
engineinfo =
{
	RPM = {left, right},(%)
	fuel_internal      -- fuel quantity internal tanks	kg
}
LoGetCameraPosition() -- (args - 0, results - 1 : table:
	{
		x = {x = ...},
		y = (x = ...},
		p = {x = ...}
    }

Coordinates convertion :
{x,y,z}				  = LoGeoCoordinatesToLoCoordinates(longitude_degrees,latitude_degrees)
LoGetSnares               =   {chaff,flare}
Input:
LoSetCommand(command, value) -- (args - 2, results - 0)
-1.0 <= value <= 1.0

Some commands:
command = 2001 - joystick pitch
	LoForceCamera(request)
--]]
--LoGetLocalPlayer()	-- returns player table { host_id, name }
--LoGetHelicopterFMData()
-- return table with fm data
--{
--G_factor = {x,y,z }    in cockpit
--}

--        LoSetSharedTexture(name)          -- register texture
"""


def test_export_docs_parse() -> None:
    f = export_docs.parse(EXPORT_LUA)
    assert sorted(f) == [
        "LoGeoCoordinatesToLoCoordinates",
        "LoGetCameraPosition",
        "LoGetEngineInfo",
        "LoGetHelicopterFMData",
        "LoGetLocalPlayer",
        "LoGetModelTime",
        "LoGetSnares",
        "LoGetWorldObjects",
        "LoSetCommand",
        "LoSetSharedTexture",
    ]
    (t,) = f["LoGetModelTime"]
    assert t == {
        "name": "LoGetModelTime",
        "params": [],
        "text": "-- returns current model time (args - 0, results - 1 (sec))",
        "argsCount": 0,
        "results": "1 (sec)",
        "section": "Output:",
        "line": 5,
    }
    (w,) = f["LoGetWorldObjects"]
    assert "argsCount" not in w and w["results"] == "1 (table of object tables)"
    assert w["detail"] == ['    "units" (default)']
    (e,) = f["LoGetEngineInfo"]
    assert e["fields"] == ["RPM", "fuel_internal"]
    assert "fields" not in f["LoGetCameraPosition"][0]  # ED's `y = (` typo
    (g,) = f["LoGeoCoordinatesToLoCoordinates"]
    assert g["assigns"] == "{x,y,z}" and g["section"] == "Coordinates convertion :"
    assert g["params"] == ["longitude_degrees", "latitude_degrees"]
    assert f["LoGetSnares"][0]["text"] == "=   {chaff,flare}"
    (c,) = f["LoSetCommand"]
    assert (c["section"], c["params"], c["argsCount"]) == (
        "Input:",
        ["command", "value"],
        2,
    )
    assert "command = 2001 - joystick pitch" in c["detail"]
    heli = f["LoGetHelicopterFMData"][0]
    assert heli["fields"] == ["G_factor"] and "section" not in heli
    assert f["LoSetSharedTexture"][0]["params"] == ["name"]


def env_dumps() -> dict[str, dict[str, Any]]:
    hooks = dump(
        "hooks",
        {
            "DCS": table(
                {
                    "getModelTime": fn(),
                    "helper": fn(
                        "Lua", source="@<install>/Scripts/x.lua", linedefined=4
                    ),
                    "limits": table({"max": num(3), 1: num(1), "cb": fn()}),
                    "version": {"type": "string", "value": "2.9"},
                }
            ),
            "me_module": table({"_M": table({}), "f": fn()}),
            "DCSAlias": {"type": "table", "ref": "DCS"},
            "db": {"type": "table", "summary": "data", "entries": 12},
            "Shared": table({"dcs": {"type": "table", "ref": "DCS"}}),
            "Pylons": table({"a": table({"n": num(1)}), "b": num(2)}),
            "Mt": table({"x": table({}, metatable=table({"__eq": fn()}))}),
            "Deep": table({"a": table({"b": table({"f": fn()})})}),
            "free": fn(),
            "count": num(3),
            "end": table({}),
        },
    )
    export = dump("export", {"LoGetModelTime": fn()}, state="export")
    server = dump("server", {}, status="unavailable", error="nope", state="server")
    return {"hooks": hooks, "export": export, "server": server}


def test_generate_env_schema(tmp_path: Path) -> None:
    for env, d in env_dumps().items():
        write(tmp_path / f"{env}.json", json.dumps(d))
    files = api_schema.generate(tmp_path)
    assert sorted(files["hooks"]) == [
        "DCS.generated.yaml",
        "DCSAlias.generated.yaml",
        "Mt.generated.yaml",
        "Shared.generated.yaml",
        "_G.generated.yaml",
    ]
    alias = yaml.safe_load(files["hooks"]["DCSAlias.generated.yaml"])["globals"]
    assert alias["DCSAlias"]["description"].startswith("The same table as `DCS`.")
    assert alias["DCSAlias"]["static"].keys() == {
        "getModelTime",
        "helper",
        "limits",
        "version",
    }
    shared = yaml.safe_load(files["hooks"]["Shared.generated.yaml"])["globals"]
    assert shared["Shared"]["static"]["dcs"] == {
        "type": "table",
        "description": "The table at `DCS`.",
    }
    assert files["server"] == {}
    assert sorted(files["export"]) == ["_G.generated.yaml"]
    dcs = yaml.safe_load(files["hooks"]["DCS.generated.yaml"])["globals"]["DCS"]
    assert dcs["kind"] == "singleton"
    s = dcs["static"]
    assert s["getModelTime"]["type"] == "function"
    assert "signature unknown" in s["getModelTime"]["description"]
    assert s["helper"]["description"].startswith(
        "Lua function (<install>/Scripts/x.lua:4)"
    )
    assert s["limits"]["kind"] == "table"
    assert s["limits"]["fields"] == {
        "cb": {"type": "function", "description": s["getModelTime"]["description"]},
        "max": {"type": "number", "description": "Dumped value: 3."},
    }
    assert s["version"] == {"type": "string", "description": 'Dumped value: "2.9".'}
    g_text = files["hooks"]["_G.generated.yaml"]
    assert "# Skipped (module() tables, non-identifiers): end, me_module" in g_text
    assert "# Skipped (data tables, no functions): Deep, Pylons, db" in g_text
    free = yaml.safe_load(g_text)["globals"]["_G"]["static"]
    assert sorted(free) == ["count", "free"]
    assert "# DCS version: 9.9.9.7" in g_text


def test_generated_env_schema_is_valid_and_builds(tmp_path: Path) -> None:
    for env, d in env_dumps().items():
        write(tmp_path / "api" / f"{env}.json", json.dumps(d))
    root = tmp_path / "schema"
    write(
        root / "globals" / "timer.singleton.yaml",
        "globals:\n  timer:\n    kind: singleton\ntypes: {}\n",
    )
    files = api_schema.generate(tmp_path / "api")
    api_schema.write(files, root)
    assert api_schema.drift(files, root) == []
    meta = yaml.safe_load(
        (REPO_ROOT / "dcs_yaml_schema.yaml").read_text(encoding="utf-8")
    )
    validator = Draft7Validator(meta)
    for path in sorted((root / "globals").rglob("*.generated.yaml")):
        errors = list(
            validator.iter_errors(yaml.safe_load(path.read_text(encoding="utf-8")))
        )
        assert not errors, (path, errors[0].message)
    # The main spec leaves the env folders out; each env merges on its own.
    assert sorted(merge_tree(str(root))[0]["globals"]) == ["timer"]
    assert sorted(merge_tree(str(root), subdirs=["globals/hooks"])[0]["globals"]) == [
        "DCS",
        "DCSAlias",
        "Mt",
        "Shared",
        "_G",
    ]
    dist = tmp_path / "dist"
    assert api_schema.build_dist(dist, root) == ["hooks", "export"]
    lua = (dist / "dcs-world-api-hooks.lua").read_text(encoding="utf-8")
    assert "---@field getModelTime function" in lua
    ts = (dist / "dcs-world-api-export.d.ts").read_text(encoding="utf-8")
    assert "LoGetModelTime: (...args: any[]) => any;" in ts
    # Drift: a changed, a stale and a missing file are reported.
    (root / "globals" / "hooks" / "DCS.generated.yaml").write_text(
        "x", encoding="utf-8"
    )
    write(root / "globals" / "server" / "old.generated.yaml", "x")
    (root / "globals" / "export" / "_G.generated.yaml").unlink()
    assert api_schema.drift(files, root) == [
        "globals/hooks/DCS.generated.yaml",
        "globals/server/old.generated.yaml",
        "globals/export/_G.generated.yaml",
    ]
    api_schema.write(files, root)
    assert api_schema.drift(files, root) == []


def test_check_cli_skips_without_dumps(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert api_schema.main(["--api-dir", str(tmp_path), "--check"]) == 0
    assert "No API dumps" in capsys.readouterr().out


def test_check_cli_fails_on_drift(tmp_path: Path) -> None:
    for env, d in env_dumps().items():
        write(tmp_path / "api" / f"{env}.json", json.dumps(d))
    args = ["--api-dir", str(tmp_path / "api"), "--out", str(tmp_path / "schema")]
    with pytest.raises(SystemExit):
        api_schema.main([*args, "--check"])
    assert api_schema.main(args) == 0
    assert api_schema.main([*args, "--check"]) == 0


@pytest.mark.skipif(sys.platform == "win32", reason="lua stubs use a POSIX shell")
def test_hook_output_through_the_pipeline(tmp_path: Path) -> None:
    from test_api_hook import LUA
    from test_api_hook import api_dump as run_hook

    if LUA is None:
        pytest.skip("lua5.1/luajit not installed")
    api = run_hook(tmp_path / "writedir")
    files = api_dump.version_files(api, VERSION, None, tmp_path / "ver")
    assert api_dump.statuses(files) == dict.fromkeys(api_dump.ENVS, "ok")
    scripting = json.loads(files["api/scripting.json"])
    unit = scripting["globals"]["Unit"]
    (fn_node,) = [m["value"] for m in unit["members"] if m["key"] == "getByName"]
    assert fn_node["source"].startswith("@") and "paths" not in scripting
    legacy = api_dump.legacy(scripting)
    assert verify.extract_dcs(legacy)["Unit"] >= {
        "getByName",
        "isExist",
        "getCoalition",
    }
    for env in api_schema.SCHEMA_ENVS:
        write(tmp_path / "ref" / f"{env}.json", files[f"api/{env}.json"].decode())
    generated = api_schema.generate(tmp_path / "ref")
    assert sorted(generated["export"]) == ["_G.generated.yaml"]
    assert "net.generated.yaml" in generated["server"]
