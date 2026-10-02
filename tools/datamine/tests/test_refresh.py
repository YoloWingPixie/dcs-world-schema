"""refresh.py's flow with dcs_headless, extraction and validation mocked."""

import dataclasses
import importlib
import json
import re
import sys
import types
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest
from conftest import hold, write

from tools.datamine import api_schema
from tools.datamine.common import DUMP_FORMAT, latest_version

VERSION = "2.9.99.1"
DEFAULTS = {
    "version": 23,
    "weather": {"qnh": 760},
    "coalitions": {"blue": [2], "red": [0], "neutrals": []},
    "year": 2026,
}
API_ENVS = ("scripting", "hooks", "server", "export")
PREVIOUS = "2.9.26.1"


def manifest(version: str) -> str:
    return json.dumps({"dcsVersion": version})


def api_file(env: str, status: str) -> str:
    """A hook output file of ``env`` (``status``: ok, sameAs or unavailable)."""
    d = {
        "format": "dcs-api-dump/2",
        "env": env,
        "dcsVersion": VERSION,
        "paths": {"installDir": "C:/DCS/", "writeDir": "C:/SG/"},
        "status": status,
    }
    if status == "ok":
        d.update(excluded=[], globals={}, limits={}, skippedKeys={}, stats={})
    elif status == "sameAs":
        d["sameAs"] = "scripting"
    else:
        d["error"] = f"{env} state not found"
    return json.dumps(d)


class Interrupted(Exception):
    pass


class HeadlessError(Exception):
    pass


@dataclass
class Paths:
    install: Path
    auth_profile: Path
    profile: Path


@dataclass
class RunResult:
    ok: bool
    reason: str
    log: str | None = None
    cleanup_errors: tuple[str, ...] = ()
    elapsed_seconds: float = 1.0


# (refresh module, calls log, outcome knobs, reference data dir)
Env = tuple[Any, dict[str, list[Any]], dict[str, Any], Path]


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    """(refresh module, calls log, tmp root) with every side effect redirected."""
    calls: dict[str, list[Any]] = {"run": [], "schema": []}
    paths = Paths(
        tmp_path / "install", tmp_path / "SG" / "DCS", tmp_path / "SG" / "DCS.datamine"
    )
    write(paths.install / "autoupdate.cfg", f'{{"version": "{VERSION}"}}')
    outcome: dict[str, Any] = {
        "run": RunResult(True, "ready"),
        "valid": True,
        "theatres": [],
        "terrain_fail": set(),
        "api": dict.fromkeys(API_ENVS, "ok"),
        "probe": None,
        "actions_probe": None,
    }

    def run(**kwargs: Any) -> Any:
        calls["run"].append(kwargs)
        if any(h.name == "api-probe.lua" for h in kwargs["hooks"]):
            return outcome["probe"](paths.profile, kwargs)
        if any(h.name == "actions-probe.lua" for h in kwargs["hooks"]):
            return outcome["actions_probe"](paths.profile, kwargs)
        if any(h.name == "api-dump.lua" for h in kwargs["hooks"]):
            assert kwargs["mission"].is_file()
            api = paths.profile / "DCS.Lua.Exporter" / "api"
            for env, status in outcome["api"].items():
                write(api / f"{env}.json", api_file(env, status))
            states = {"scripting": {"env": "scripting", "status": "ok"}}
            write(
                api / "states.json",
                json.dumps(
                    {
                        "format": "dcs-api-dump/2",
                        "dcsVersion": VERSION,
                        "states": states,
                    }
                ),
            )
            write(api / "done", VERSION)
            return RunResult(True, "ready")
        if kwargs.get("mission") is not None:
            theatre = kwargs["mission"].stem
            assert kwargs["mission"].is_file()
            if theatre in outcome["terrain_fail"]:
                return RunResult(False, "fail_log matched: Terrain dump failed")
            t = paths.profile / "DCS.Lua.Exporter" / "terrains"
            write(t / f"{theatre}.lua", f"terrain = {{ theatre = '{theatre}' }}")
            write(t / f"{theatre}.done", VERSION)
            return RunResult(True, "ready")
        g = paths.profile / "DCS.Lua.Exporter" / "_G"
        write(g / "__DCS_VERSION__.lua", VERSION)
        write(g / "__DUMP_FORMAT__.lua", str(DUMP_FORMAT))
        write(g / "db" / "x.lua", "x")
        return outcome["run"]

    headless = types.ModuleType("dcs_headless")
    vars(headless).update(
        run=run,
        HeadlessError=HeadlessError,
        RunResult=RunResult,
        Interrupted=Interrupted,
    )
    headless_paths = types.ModuleType("dcs_headless.paths")
    vars(headless_paths).update(resolve=lambda **kw: paths, Paths=Paths)
    monkeypatch.setitem(sys.modules, "dcs_headless", headless)
    monkeypatch.setitem(sys.modules, "dcs_headless.paths", headless_paths)
    sys.modules.pop("tools.datamine.refresh", None)
    refresh = importlib.import_module("tools.datamine.refresh")

    data = tmp_path / "dcs-world-reference"
    hold(data, PREVIOUS)
    write(data / "latest" / "weapons" / "A.json", "{}")
    monkeypatch.setattr(refresh, "REFERENCE_DATA_DIR", data)
    monkeypatch.setattr(refresh, "CACHE_DIR", tmp_path / ".datamine")
    monkeypatch.setattr(refresh, "CACHED_G_DIR", tmp_path / ".datamine" / "_G")
    monkeypatch.setattr(refresh, "RUN_OUT", tmp_path / ".datamine" / "run")
    monkeypatch.setattr(refresh, "TERRAINS_CACHE", tmp_path / ".datamine" / "terrains")
    monkeypatch.setattr(refresh, "MISSIONS_DIR", tmp_path / ".datamine" / "missions")
    api_cache = tmp_path / ".datamine" / "api"
    monkeypatch.setattr(refresh, "API_CACHE", api_cache)
    monkeypatch.setattr(refresh, "PROBE_CACHE", tmp_path / ".datamine" / "probe")
    monkeypatch.setattr(refresh, "PROBE_RUN", tmp_path / ".datamine" / "probe-run")
    for name, probe in (
        ("ACTIONS_PROBE", refresh.ACTIONS_PROBE),
        ("ACTIONS_PROBE_FOLLOWUP", refresh.ACTIONS_PROBE_FOLLOWUP),
    ):
        monkeypatch.setattr(
            refresh,
            name,
            dataclasses.replace(probe, cache=tmp_path / ".datamine" / probe.cache.name),
        )
    monkeypatch.setattr(
        refresh, "action_records", lambda install: ({"actions": {}, "options": {}}, [])
    )
    # A current API dump is cached unless a test removes it.
    for env in API_ENVS:
        write(api_cache / f"{env}.json", api_file(env, "ok"))
    write(api_cache / "hook", refresh.api_dump.hook_hash())
    write(api_cache / "done", VERSION)

    def publish(ver_dir: Path, extraction: Any, g_dir: Path) -> None:
        calls["schema"].append(extraction.constants)
        calls.setdefault("db_types", []).append(g_dir)
        api = api_schema.generate(ver_dir / "api")
        calls.setdefault("api_schema", []).append(api)

    monkeypatch.setattr(refresh, "publish_latest", publish)
    monkeypatch.setattr(
        refresh, "installed_theatres", lambda install: list(outcome["theatres"])
    )
    monkeypatch.setattr(refresh, "install_defaults", lambda install: DEFAULTS)
    monkeypatch.setattr(refresh, "entity_schema", lambda constants: {})

    def extract(
        g_dir: Path,
        install_dir: Path,
        terrains_dir: Path,
        actions_probe_doc: Any = None,
        actions: Any = None,
    ) -> types.SimpleNamespace:
        calls.setdefault("actions_probe_doc", []).append(actions_probe_doc)
        assert install_dir == paths.install  # HARM ids, flyables, liveries
        assert terrains_dir == tmp_path / ".datamine" / "terrains"
        calls.setdefault("terrains", []).append(
            sorted(p.name for p in terrains_dir.glob("*"))
            if terrains_dir.is_dir()
            else []
        )
        assert (g_dir / "db" / "x.lua").read_text() == "x"  # the cached dump
        files = {f"weapons/{name}.json": b"{}" for name in ("A", "B")}
        files["manifest.json"] = manifest(VERSION).encode()
        return types.SimpleNamespace(
            version=VERSION,
            constants="constants",
            series={"weapons": {"A": {}, "B": {}}},
            files=lambda: files,
        )

    def validate(files: dict[str, bytes], doc: Any, version: str) -> bool:
        assert version == VERSION
        assert set(files) == {"manifest.json", "weapons/A.json", "weapons/B.json"}
        return cast(bool, outcome["valid"])

    monkeypatch.setattr(refresh, "extract", extract)
    monkeypatch.setattr(refresh, "validate", validate)
    return refresh, calls, outcome, data


ARGS: list[str] = []


def test_up_to_date_does_not_launch(env: Env) -> None:
    refresh, calls, _, data = env
    hold(data, VERSION)
    assert refresh.main(ARGS) == 0
    assert calls["run"] == []


def test_success_installs_validated_data(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    refresh, calls, _, data = env
    assert refresh.main(ARGS) == 0
    run = calls["run"][0]
    assert run["profile"] == "DCS.datamine"
    assert run["wait_file"] == "DCS.Lua.Exporter/_G/__DCS_VERSION__.lua"
    assert [h.name for h in run["hooks"]] == ["dump-globals.lua", "serialize.lua"]
    assert sorted(p.name for p in (data / "latest" / "weapons").iterdir()) == [
        "A.json",
        "B.json",
    ]
    assert calls["schema"] == ["constants"]
    g_dir = data.parent / ".datamine" / "_G"
    assert calls["db_types"] == [g_dir]
    assert latest_version(data) == VERSION
    assert (
        "weapons                       1              2  (+1)"
        in capsys.readouterr().out
    )


@pytest.mark.parametrize("failure", ["run", "validation"])
def test_failure_writes_nothing(env: Env, failure: str) -> None:
    refresh, calls, outcome, data = env
    if failure == "run":
        outcome["run"] = RunResult(False, "fail_log matched: Export aborted")
    else:
        outcome["valid"] = False
    with pytest.raises(SystemExit):
        refresh.main(ARGS)
    assert latest_version(data) == PREVIOUS
    assert calls["schema"] == []
    assert "db_types" not in calls
    assert sorted(p.name for p in data.iterdir()) == ["latest"]


def test_force_replaces_an_existing_version(env: Env) -> None:
    refresh, _, _, data = env
    hold(data, VERSION)
    write(data / "latest" / "weapons" / "stale.json", "{}")
    assert refresh.main([*ARGS, "--force"]) == 0
    assert sorted(p.name for p in (data / "latest" / "weapons").iterdir()) == [
        "A.json",
        "B.json",
    ]


def test_terrains_run_once_per_uncached_theatre(env: Env) -> None:
    refresh, calls, outcome, _ = env
    outcome["theatres"] = ["Caucasus", "Normandy"]
    cache = refresh.TERRAINS_CACHE
    write(cache / "Caucasus.lua", "terrain = {}")
    write(cache / "Caucasus.hook", refresh.terrain_hook_hash())
    write(cache / "Caucasus.done", VERSION)
    assert refresh.main(ARGS) == 0
    g_run, terrain_run = calls["run"]
    assert "mission" not in g_run
    assert terrain_run["mission"].name == "Normandy.miz"
    assert terrain_run["wait_file"] == "DCS.Lua.Exporter/terrains/Normandy.done"
    assert [h.name for h in terrain_run["hooks"]] == [
        "terrain-dump.lua",
        "serialize.lua",
    ]
    assert terrain_run["fail_log"] == "Terrain dump failed"
    assert (terrain_run["timeout"], terrain_run["stall_timeout"]) == (900, 300)
    assert (cache / "Normandy.done").read_text() == VERSION
    assert (cache / "Normandy.hook").read_text() == refresh.terrain_hook_hash()
    assert calls["terrains"] == [
        [
            "Caucasus.done",
            "Caucasus.hook",
            "Caucasus.lua",
            "Normandy.done",
            "Normandy.hook",
            "Normandy.lua",
        ]
    ]


def test_missing_terrain_reruns_extraction_with_cached_dump(env: Env) -> None:
    refresh, calls, outcome, data = env
    hold(data, VERSION)
    write(refresh.CACHED_G_DIR / "__DCS_VERSION__.lua", VERSION)
    write(refresh.CACHED_G_DIR / "__DUMP_FORMAT__.lua", str(DUMP_FORMAT))
    write(refresh.CACHED_G_DIR / "db" / "x.lua", "x")
    outcome["theatres"] = ["Caucasus"]
    assert refresh.main(ARGS) == 0
    assert [r["mission"].name for r in calls["run"]] == ["Caucasus.miz"]
    assert (data / "latest" / "weapons" / "B.json").exists()


def test_old_dump_format_redumps_with_version_present(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    refresh, calls, _, data = env
    hold(data, VERSION)
    write(refresh.CACHED_G_DIR / "__DCS_VERSION__.lua", VERSION)
    write(refresh.CACHED_G_DIR / "db" / "x.lua", "x")
    assert refresh.main(ARGS) == 0
    assert [r["wait_file"] for r in calls["run"]] == [
        "DCS.Lua.Exporter/_G/__DCS_VERSION__.lua"
    ]
    assert f"cached dump has no format marker, the hook writes {DUMP_FORMAT}" in (
        capsys.readouterr().out
    )
    assert (refresh.CACHED_G_DIR / "__DUMP_FORMAT__.lua").read_text() == str(
        DUMP_FORMAT
    )


def test_stale_terrain_cache_reruns(env: Env) -> None:
    refresh, calls, outcome, data = env
    hold(data, VERSION)
    write(refresh.CACHED_G_DIR / "__DCS_VERSION__.lua", VERSION)
    write(refresh.CACHED_G_DIR / "__DUMP_FORMAT__.lua", str(DUMP_FORMAT))
    write(refresh.CACHED_G_DIR / "db" / "x.lua", "x")
    outcome["theatres"] = ["Caucasus"]
    write(refresh.TERRAINS_CACHE / "Caucasus.done", "2.9.1.1")
    assert refresh.main(ARGS) == 0
    assert len(calls["run"]) == 1


def test_terrain_hook_change_reruns(
    env: Env,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    refresh, calls, outcome, data = env
    hold(data, VERSION)
    write(refresh.CACHED_G_DIR / "__DCS_VERSION__.lua", VERSION)
    write(refresh.CACHED_G_DIR / "__DUMP_FORMAT__.lua", str(DUMP_FORMAT))
    write(refresh.CACHED_G_DIR / "db" / "x.lua", "x")
    outcome["theatres"] = ["Caucasus"]
    write(refresh.TERRAINS_CACHE / "Caucasus.lua", "terrain = {}")
    write(refresh.TERRAINS_CACHE / "Caucasus.hook", refresh.terrain_hook_hash())
    write(refresh.TERRAINS_CACHE / "Caucasus.done", VERSION)
    assert refresh.main(ARGS) == 0
    assert calls["run"] == []
    # A changed hook (serialize.lua counts too) invalidates the cached dump.
    hooks = [tmp_path / "hooks" / p.name for p in refresh.TERRAIN_HOOKS]
    for src, dest in zip(refresh.TERRAIN_HOOKS, hooks, strict=True):
        write(dest, src.read_text(encoding="utf-8"))
    write(hooks[1], hooks[1].read_text(encoding="utf-8") + "\n-- changed\n")
    monkeypatch.setattr(refresh, "TERRAIN_HOOKS", hooks)
    assert refresh.main(ARGS) == 0
    assert [r["mission"].name for r in calls["run"]] == ["Caucasus.miz"]
    assert "Terrain Caucasus: dumping (terrain hook changed" in capsys.readouterr().out
    assert (
        refresh.TERRAINS_CACHE / "Caucasus.hook"
    ).read_text() == refresh.terrain_hook_hash()


def test_terrain_failure_stops_before_extraction(env: Env) -> None:
    refresh, calls, outcome, data = env
    outcome["theatres"] = ["Caucasus", "Kola", "Syria"]
    outcome["terrain_fail"] = {"Kola"}
    with pytest.raises(SystemExit):
        refresh.main(ARGS)
    assert [r.get("mission") and r["mission"].stem for r in calls["run"]] == [
        None,
        "Caucasus",
        "Kola",
    ]
    assert "terrains" not in calls
    assert latest_version(data) == PREVIOUS
    # The terrain that succeeded stays cached, so a rerun resumes.
    assert (refresh.TERRAINS_CACHE / "Caucasus.done").read_text() == VERSION
    assert not (refresh.TERRAINS_CACHE / "Kola.done").exists()


def test_force_reruns_cached_terrains(env: Env) -> None:
    refresh, calls, outcome, _ = env
    outcome["theatres"] = ["Caucasus"]
    write(refresh.TERRAINS_CACHE / "Caucasus.done", VERSION)
    write(refresh.CACHED_G_DIR / "__DCS_VERSION__.lua", VERSION)
    write(refresh.CACHED_G_DIR / "__DUMP_FORMAT__.lua", str(DUMP_FORMAT))
    assert refresh.main([*ARGS, "--force"]) == 0
    assert len(calls["run"]) == 3  # _G, API, the terrain


def _uncache_api(refresh: Any) -> None:
    (refresh.API_CACHE / "done").unlink()


def test_api_dump_runs_and_lands_in_latest(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    refresh, calls, outcome, data = env
    _uncache_api(refresh)
    outcome["theatres"] = ["Syria", "Caucasus"]
    write(refresh.TERRAINS_CACHE / "Syria.done", VERSION)
    write(refresh.TERRAINS_CACHE / "Syria.hook", refresh.terrain_hook_hash())
    write(refresh.TERRAINS_CACHE / "Caucasus.done", VERSION)
    write(refresh.TERRAINS_CACHE / "Caucasus.hook", refresh.terrain_hook_hash())
    outcome["api"]["export"] = "unavailable"
    outcome["api"]["server"] = "sameAs"
    assert refresh.main(ARGS) == 0
    _, api_run = calls["run"]
    assert [h.name for h in api_run["hooks"]] == ["api-dump.lua", "api-walk.lua"]
    assert api_run["mission"].name == "api-Caucasus.miz"
    assert api_run["wait_file"] == "DCS.Lua.Exporter/api/done"
    assert api_run["fail_log"] == "API dump failed"
    out = capsys.readouterr().out
    assert "API dump: dumping (no cached API dump)" in out
    assert "API env export    unavailable: export state not found" in out
    assert "API env server    sameAs scripting" in out
    cache = refresh.API_CACHE
    assert (cache / "done").read_text() == VERSION
    assert (cache / "hook").read_text() == refresh.api_dump.hook_hash()
    api = data / "latest" / "api"
    assert sorted(p.name for p in api.iterdir()) == [
        "export.json",
        "hooks.json",
        "scripting.json",
        "server.json",
        "states.json",
    ]
    scripting = json.loads((api / "scripting.json").read_text())
    assert "paths" not in scripting and scripting["status"] == "ok"
    exported = json.loads((data / "latest" / "api" / "export.json").read_text())
    assert exported["status"] == "unavailable"
    server = json.loads((data / "latest" / "api" / "server.json").read_text())
    assert server["sameAs"] == "scripting"
    # The stub dumps have no globals; export is unavailable.
    assert calls["api_schema"] == [{"hooks": {}, "server": {}, "export": {}}]


def test_api_dump_reruns_on_hook_change_with_version_present(env: Env) -> None:
    refresh, calls, _, data = env
    hold(data, VERSION)
    write(refresh.CACHED_G_DIR / "__DCS_VERSION__.lua", VERSION)
    write(refresh.CACHED_G_DIR / "__DUMP_FORMAT__.lua", str(DUMP_FORMAT))
    write(refresh.CACHED_G_DIR / "db" / "x.lua", "x")
    write(refresh.API_CACHE / "hook", "old")
    assert refresh.main(ARGS) == 0
    assert [r["hooks"][0].name for r in calls["run"]] == ["api-dump.lua"]
    assert (data / "latest" / "api" / "hooks.json").is_file()


@pytest.mark.parametrize("env_name", ["scripting", "hooks"])
def test_required_api_env_unavailable_writes_nothing(env: Env, env_name: str) -> None:
    refresh, calls, outcome, data = env
    _uncache_api(refresh)
    outcome["api"][env_name] = "unavailable"
    with pytest.raises(SystemExit):
        refresh.main(ARGS)
    assert latest_version(data) == PREVIOUS
    assert not (refresh.API_CACHE / "done").exists()
    assert "terrains" not in calls


def _probe_api_cache(refresh: Any) -> None:
    """A cached scripting dump with two functions to probe."""
    fn = {"type": "function", "what": "C"}
    d = json.loads(api_file("scripting", "ok"))
    d["globals"] = {"f": fn, "g": fn}
    write(refresh.API_CACHE / "scripting.json", json.dumps(d))


ProbeStep = Callable[[Path, dict[str, Any]], RunResult]


def _match(pattern: str, text: str) -> str:
    """Group 1 of ``pattern`` in ``text``, which must match."""
    m = re.search(pattern, text)
    assert m, pattern
    return m.group(1)


def _probe_runs(*steps: tuple[list[str], bool]) -> ProbeStep:
    """A fake probe run per step: the progress lines it appends (the plan id
    filled in) and whether it finishes."""
    it = iter(steps)

    def run(profile: Path, kwargs: dict[str, Any]) -> RunResult:
        lines, finishes = next(it)
        plan_text = kwargs["hooks"][-1].read_text()
        plan_id = _match(r'id = "(\w+)"', plan_text)
        out = profile / "DCS.Lua.Exporter" / "probe"
        out.mkdir(parents=True, exist_ok=True)
        progress = out / "progress.tsv"
        if not progress.is_file():
            progress.write_text(f"P\t{plan_id}\n")
        with progress.open("a") as fh:
            fh.writelines(line + "\n" for line in lines)
        if not finishes:
            return RunResult(False, "DCS exited")
        (out / "done").write_text(VERSION)
        return RunResult(True, "ready")

    return run


def test_probe_is_off_by_default(env: Env) -> None:
    refresh, calls, _, _ = env
    assert refresh.main(ARGS) == 0
    assert not any(h.name == "api-probe.lua" for r in calls["run"] for h in r["hooks"])


def test_probe_restarts_after_a_crash_and_lands_in_latest(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    refresh, calls, outcome, data = env
    _probe_api_cache(refresh)
    ok = '{"status":"ok","minArgs":0}'
    outcome["probe"] = _probe_runs(
        (["S\tscripting\tf", f"R\tscripting\tf\t{ok}", "S\tscripting\tg"], False),
        (['R\tscripting\tg\t{"status":"crashed"}'], True),
    )
    assert refresh.main(["--probe"]) == 0
    probe_runs = [r for r in calls["run"] if r["hooks"][0].name == "api-probe.lua"]
    assert len(probe_runs) == 2
    run = probe_runs[0]
    assert [h.name for h in run["hooks"]] == [
        "api-probe.lua",
        "probe-call.lua",
        "api-probe-plan.lua",
    ]
    assert run["mission"].name == "probe-Caucasus.miz"
    assert (
        "PROBE_PLANE_BLUE" in zipfile.ZipFile(run["mission"]).read("mission").decode()
    )
    assert run["wait_file"] == "DCS.Lua.Exporter/probe/done"
    assert run["fail_log"] == "API probe failed"
    assert "restarting (1/60)" in capsys.readouterr().out
    doc = json.loads((data / "latest" / "api" / "probe.json").read_text())
    assert doc["source"] == "probe"
    assert doc["envs"]["scripting"]["f"]["conclusive"] is True
    assert doc["envs"]["scripting"]["g"]["status"] == "crashed"
    assert doc["stats"]["complete"] is True
    assert (refresh.PROBE_CACHE / "done").read_text() == VERSION
    # Cached: a second refresh with --probe does not run DCS.
    calls["run"].clear()
    assert refresh.main(["--probe"]) == 0
    assert calls["run"] == []
    # Without --probe a re-extraction keeps latest's probe.json.
    assert refresh.main(["--force"]) == 0
    assert (data / "latest" / "api" / "probe.json").is_file()


def test_probe_without_progress_writes_nothing(env: Env) -> None:
    refresh, _, outcome, data = env
    _probe_api_cache(refresh)
    outcome["probe"] = _probe_runs(([], False))
    with pytest.raises(SystemExit):
        refresh.main(["--probe"])
    assert latest_version(data) == PREVIOUS
    assert not (refresh.PROBE_CACHE / "done").exists()


def test_probe_interrupted_keeps_and_installs_a_partial_probe(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    refresh, _, outcome, data = env
    assert refresh.main(ARGS) == 0  # the data the probe lands in
    _probe_api_cache(refresh)
    ok = '{"status":"ok","minArgs":0}'
    step = _probe_runs((["S\tscripting\tf", f"R\tscripting\tf\t{ok}"], False))

    def interrupted(profile: Path, kwargs: dict[str, Any]) -> RunResult:
        step(profile, kwargs)
        raise Interrupted(2)

    outcome["probe"] = interrupted
    with pytest.raises(SystemExit) as exc:
        refresh.main(["--probe"])
    assert exc.value.code == 130
    assert "argument probe interrupted at 1 of 2" in capsys.readouterr().err
    doc = json.loads((data / "latest" / "api" / "probe.json").read_text())
    assert doc["stats"]["complete"] is False
    assert doc["envs"]["scripting"]["f"]["conclusive"] is True
    assert doc["envs"]["scripting"]["g"]["status"] == "notRun"
    assert (refresh.PROBE_CACHE / "partial").read_text() == VERSION


def test_probe_out_of_restarts_keeps_a_partial_probe(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    refresh, calls, outcome, data = env
    _probe_api_cache(refresh)
    ok = '{"status":"ok","minArgs":0}'
    outcome["probe"] = _probe_runs(
        (["S\tscripting\tf", f"R\tscripting\tf\t{ok}", "S\tscripting\tg"], False),
    )
    assert refresh.main(["--probe", "--probe-restarts", "0"]) == 0
    assert "keeping the partial probe" in capsys.readouterr().err
    doc = json.loads((data / "latest" / "api" / "probe.json").read_text())
    assert doc["stats"]["complete"] is False
    assert doc["envs"]["scripting"]["g"]["status"] == "crashed"
    assert (refresh.PROBE_CACHE / "partial").read_text() == VERSION
    assert not (refresh.PROBE_CACHE / "done").exists()

    # The next --probe resumes it: a new mission or plan would start over,
    # but this one is the same plan; g crashed, so it is carried forward.
    calls["run"].clear()
    outcome["probe"] = _probe_runs((['R\tscripting\tg\t{"status":"crashed"}'], True))
    assert refresh.main(["--probe"]) == 0
    assert len(calls["run"]) == 1
    crashed = json.loads((refresh.PROBE_CACHE / "crashed.json").read_text())
    assert crashed == {
        "dcsVersion": VERSION,
        "crashed": [
            {"env": "scripting", "path": "g", "plan": crashed["crashed"][0]["plan"]}
        ],
    }
    plan_text = (refresh.PROBE_RUN / "api-probe-plan.lua").read_text()
    assert '["pattern"] = "g"' in plan_text
    assert (refresh.PROBE_CACHE / "done").read_text() == VERSION


def test_probe_without_progress_keeps_its_partial_probe(env: Env) -> None:
    refresh, _, outcome, _ = env
    _probe_api_cache(refresh)
    outcome["probe"] = _probe_runs(([], False))
    with pytest.raises(SystemExit):
        refresh.main(["--probe"])
    doc = json.loads((refresh.PROBE_CACHE / "probe.json").read_text())
    assert doc["stats"]["complete"] is False


def test_progress_watch(env: Env, tmp_path: Path) -> None:
    refresh = env[0]
    progress = tmp_path / "progress.tsv"
    now = [0.0]
    check = refresh.progress_watch(progress, 60, clock=lambda: now[0])
    now[0] = 500
    assert check() is None  # not started: the map may still be loading
    progress.write_text("P\tx\n")
    now[0] = 510
    assert check() is None
    now[0] = 569
    assert check() is None
    with progress.open("a") as fh:
        fh.write("S\tscripting\tf\n")
    now[0] = 600
    assert check() is None
    now[0] = 660
    assert check() == "progress.tsv stalled: unchanged for 60s"


def test_watching_adds_the_check_to_the_run_watch(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    refresh = env[0]
    seen: list[str | None] = []

    def wait_for(*, watch: Any = None, **kw: Any) -> dict[str, Any]:
        seen.append(watch())
        return kw

    runner = types.SimpleNamespace(wait_for=wait_for)
    monkeypatch.setattr(sys.modules["dcs_headless"], "runner", runner, raising=False)
    with refresh.watching(lambda: "stalled"):
        assert runner.wait_for(watch=lambda: None, poll=1) == {"poll": 1}
        runner.wait_for(watch=lambda: "DCS exited")
    assert runner.wait_for is wait_for
    assert seen == ["stalled", "DCS exited"]


def _actions_plan(version: str) -> dict[str, Any]:
    from test_actions_probe import ACTIONS, OPTIONS, SPEC

    from tools.datamine import actions_probe, probe_mission

    return actions_probe.plan(
        ACTIONS,
        OPTIONS,
        version,
        sp=SPEC,
        mission_spec=probe_mission.spec(None),
    )


def _use_plans(
    monkeypatch: pytest.MonkeyPatch,
    refresh: Any,
    main: Callable[[str], dict[str, Any]],
    followup: Callable[[str], dict[str, Any]] | None = None,
) -> None:
    """Make the actions probes plan ``main(version)`` / ``followup(version)``."""
    for name, make in (("ACTIONS_PROBE", main), ("ACTIONS_PROBE_FOLLOWUP", followup)):
        if make is not None:
            probe = dataclasses.replace(
                getattr(refresh, name), make_plan=lambda a, o, v, make=make: make(v)
            )
            monkeypatch.setattr(refresh, name, probe)


def _actions_runs(*finishes: bool) -> ProbeStep:
    """A fake actions probe run per entry: records every step (a crash at the
    first step when False) in the plan's outDir and writes a dcs.log with a
    marker."""
    it = iter(finishes)

    def run(profile: Path, kwargs: dict[str, Any]) -> RunResult:
        finished = next(it)
        plan_text = kwargs["hooks"][-1].read_text()
        plan_id = _match(r'id = "(\w+)"', plan_text)
        total = len(re.findall(r"\[\"n\"\] = ", plan_text))
        out = profile / _match(r'outDir = "([^"]+)"', plan_text)
        out.mkdir(parents=True, exist_ok=True)
        progress = out / "progress.tsv"
        lines = [] if progress.is_file() else [f"P\t{plan_id}", "V\t" + VERSION]
        if finished:
            lines += [
                f'R\t{n}\t{{"status":"done","apply":{{"accepted":true}}}}'
                for n in range(2, total + 1)
            ]
        else:
            lines += ["S\t1", 'R\t1\t{"status":"crashed"}']
        with progress.open("a") as fh:
            fh.writelines(line + "\n" for line in lines)
        n = 2 if finished else 1
        write(
            kwargs["out"] / "dcs.log",
            f"[X][INFO] ACTIONS PROBE BEGIN {plan_id} {n}\nlogged {n}\n",
        )
        if not finished:
            return RunResult(False, "DCS exited")
        (out / "done").write_text(VERSION)
        return RunResult(True, "ready")

    return run


def test_actions_probe_runs_caches_and_joins(
    env: Env, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    refresh, calls, outcome, data = env
    _use_plans(monkeypatch, refresh, _actions_plan)
    outcome["actions_probe"] = _actions_runs(False, True)
    assert refresh.main(["--actions-probe"]) == 0
    runs = [r for r in calls["run"] if r["hooks"][0].name == "actions-probe.lua"]
    assert len(runs) == 2
    assert [h.name for h in runs[0]["hooks"]] == [
        "actions-probe.lua",
        "probe-call.lua",
        "actions-probe-lib.lua",
        "actions-probe-plan.lua",
    ]
    assert runs[0]["wait_file"] == "DCS.Lua.Exporter/actions-probe/done"
    assert runs[0]["fail_log"] == "Actions probe failed"
    mission = zipfile.ZipFile(runs[0]["mission"]).read("mission").decode()
    assert "ACTIONS_PROBE_" in mission and "lateActivation" in mission
    assert "restarting (1/60)" in capsys.readouterr().out
    cache = refresh.ACTIONS_PROBE.cache
    assert (cache / "done").read_text() == VERSION
    assert sorted(p.name for p in (cache / "logs").glob("*.log")) == [
        "run-001.log",
        "run-002.log",
    ]
    doc = json.loads((data / "latest" / "api" / "actions-probe.json").read_text())
    assert doc["stats"]["complete"] is True
    rows = {r["n"]: r for r in doc["steps"]}
    assert rows[1]["status"] == "crashed" and rows[1]["logLines"] == ["logged 1"]
    assert rows[2]["logLines"] == ["logged 2"]
    assert calls["actions_probe_doc"][-1]["plan"] == doc["plan"]
    # Cached: the same plan does not run DCS again.
    calls["run"].clear()
    assert refresh.main(["--actions-probe"]) == 0
    assert calls["run"] == []


def test_actions_probe_interrupted_installs_a_partial_probe(
    env: Env, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    refresh, _, outcome, data = env
    assert refresh.main(ARGS) == 0  # the data the probe lands in
    _use_plans(monkeypatch, refresh, _actions_plan)
    step = _actions_runs(False)

    def interrupted(profile: Path, kwargs: dict[str, Any]) -> RunResult:
        step(profile, kwargs)
        raise Interrupted(2)

    outcome["actions_probe"] = interrupted
    with pytest.raises(SystemExit) as exc:
        refresh.main(["--actions-probe"])
    assert exc.value.code == 130
    assert "actions probe interrupted at 1 of" in capsys.readouterr().err
    doc = json.loads((data / "latest" / "api" / "actions-probe.json").read_text())
    assert doc["stats"]["complete"] is False
    assert doc["steps"][0]["status"] == "crashed"
    assert (refresh.ACTIONS_PROBE.cache / "partial").read_text() == VERSION


def test_actions_probe_is_off_by_default(env: Env) -> None:
    refresh, calls, _, _ = env
    assert refresh.main(ARGS) == 0
    assert not any(
        h.name == "actions-probe.lua" for r in calls["run"] for h in r["hooks"]
    )
    assert calls["actions_probe_doc"] == [None]


def test_actions_probe_followup_runs_with_its_lib_and_file(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_actions_probe import ACTIONS, FOPTIONS, FSPEC, SPEC

    from tools.datamine import actions_probe, probe_mission

    def _followup() -> dict[str, Any]:
        return actions_probe.followup_plan(
            ACTIONS,
            FOPTIONS,
            VERSION,
            sp=SPEC,
            fsp=FSPEC,
            mission_spec=probe_mission.spec(None),
        )

    refresh, calls, outcome, data = env
    assert refresh.main(ARGS) == 0
    _use_plans(monkeypatch, refresh, _actions_plan, lambda v: _followup())
    outcome["actions_probe"] = _actions_runs(False, True)
    assert refresh.main(["--actions-probe-followup"]) == 0
    runs = [r for r in calls["run"] if r["hooks"][0].name == "actions-probe.lua"]
    assert len(runs) == 2
    lib = runs[0]["hooks"][2]
    assert lib.name == "actions-probe-lib.lua" and "spawnStep" in lib.read_text()
    assert "actions-probe-followup" in runs[0]["mission"].name
    assert runs[0]["wait_file"] == "DCS.Lua.Exporter/actions-probe-followup/done"
    doc = json.loads(
        (data / "latest" / "api" / "actions-probe-followup.json").read_text()
    )
    assert doc["format"] == "dcs-actions-probe-followup/1"
    assert not (data / "latest" / "api" / "actions-probe.json").exists()
    assert (refresh.ACTIONS_PROBE_FOLLOWUP.cache / "done").read_text() == VERSION


def test_actions_probes_keep_their_own_progress(
    env: Env, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from test_actions_probe import ACTIONS, FOPTIONS, FSPEC, SPEC

    from tools.datamine import actions_probe, probe_mission

    refresh, _, outcome, data = env
    assert refresh.main(ARGS) == 0
    _use_plans(
        monkeypatch,
        refresh,
        _actions_plan,
        lambda v: actions_probe.followup_plan(
            ACTIONS,
            FOPTIONS,
            VERSION,
            sp=SPEC,
            fsp=FSPEC,
            mission_spec=probe_mission.spec(None),
        ),
    )
    step = _actions_runs(False)

    def interrupted(profile: Path, kwargs: dict[str, Any]) -> RunResult:
        step(profile, kwargs)
        raise Interrupted(2)

    outcome["actions_probe"] = interrupted
    with pytest.raises(SystemExit):
        refresh.main(["--actions-probe"])
    profile = data.parent / "SG" / "DCS.datamine"
    main_progress = profile / refresh.ACTIONS_PROBE.out_rel / "progress.tsv"
    kept = main_progress.read_text()
    assert kept.splitlines()[-1] == 'R\t1\t{"status":"crashed"}'

    # The follow-up runs to the end in its own dir, leaving the main partial.
    outcome["actions_probe"] = _actions_runs(True)
    assert refresh.main(["--actions-probe-followup"]) == 0
    followup = profile / refresh.ACTIONS_PROBE_FOLLOWUP.out_rel / "progress.tsv"
    assert followup.is_file() and main_progress.read_text() == kept

    # The main probe resumes after its recorded step.
    capsys.readouterr()
    outcome["actions_probe"] = _actions_runs(True)
    assert refresh.main(["--actions-probe"]) == 0
    assert "(1 of" in capsys.readouterr().out
    doc = json.loads((data / "latest" / "api" / "actions-probe.json").read_text())
    assert doc["stats"]["complete"] is True
    assert {r["n"]: r for r in doc["steps"]}[1]["status"] == "crashed"
    assert (data / "latest" / "api" / "actions-probe-followup.json").is_file()


def test_extract_main_keeps_every_api_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.datamine import extract

    api, out = tmp_path / "api", tmp_path / "data"
    for env in API_ENVS:
        write(api / f"{env}.json", api_file(env, "ok"))
    write(api / "done", VERSION)
    probes = ("probe.json", "actions-probe.json", "actions-probe-followup.json")
    hold(out, VERSION)
    for name in probes:
        write(out / "latest" / "api" / name, manifest(VERSION))
    (tmp_path / "_G").mkdir()
    monkeypatch.setattr(extract, "read_version", lambda g_dir: VERSION)
    monkeypatch.setattr(
        extract,
        "extract",
        lambda *args: types.SimpleNamespace(
            version=VERSION,
            files=lambda: {
                "weapons/A.json": b"{}",
                "manifest.json": manifest(VERSION).encode(),
            },
        ),
    )
    caches = ("probe", "actions-probe", "actions-probe-followup")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "extract",
            str(tmp_path / "_G"),
            *("--out", str(out), "--install-dir", str(tmp_path / "install")),
            *("--api-dir", str(api)),
            *(
                arg
                for flag, name in zip(
                    (
                        "--probe-dir",
                        "--actions-probe-dir",
                        "--actions-probe-followup-dir",
                    ),
                    caches,
                    strict=True,
                )
                for arg in (flag, str(tmp_path / name))
            ),
        ],
    )
    assert extract.main() == 0
    names = {p.name for p in (out / "latest" / "api").iterdir()}
    assert names == {f"{env}.json" for env in API_ENVS} | set(probes)


def test_install_older_than_latest_fails(env: Env) -> None:
    refresh, calls, _, data = env
    hold(data, "2.9.100.1")
    with pytest.raises(SystemExit):
        refresh.main(ARGS)
    assert calls["run"] == []
    assert latest_version(data) == "2.9.100.1"
