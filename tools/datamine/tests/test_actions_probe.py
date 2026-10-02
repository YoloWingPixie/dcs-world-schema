"""The actions probe: plan, plan hook file, mission groups, document, join,
and the hook itself against a stubbed scripting state (skipped without
lua5.1)."""

from __future__ import annotations

import copy
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from conftest import hold, write
from lupa import LuaRuntime

from tools.datamine import actions_probe as ap
from tools.datamine import probe_mission
from tools.datamine.common import CacheState, json_text

TESTS_LUA = Path(__file__).parent / "lua"
LUA = shutil.which("lua5.1")
needs_lua = pytest.mark.skipif(LUA is None, reason="lua5.1 not installed")
VERSION = "9.9.9.7"

SPEC: dict[str, Any] = {
    "samples": {
        "plane": "PROBE_PLANE",
        "helicopter": "PROBE_HELO",
        "vehicle": "PROBE_GROUND",
        "ship": "PROBE_SHIP",
    },
    "route": {
        "plane": {"anchor": "land", "offset": [30000, 0]},
        "helicopter": {"anchor": "land", "offset": [10000, -10000]},
        "vehicle": {"anchor": "land", "offset": [4000, 4000]},
        "ship": {"anchor": "sea", "offset": [0, 20000]},
    },
    "effects": [
        {
            "dcsId": "Orbit",
            "categories": ["plane"],
            "measure": "turnToward",
            "seconds": 2,
            "params": {
                "pattern": "Circle",
                "point": "$target",
                "altitude": "$alt",
                "speed": "$speed",
            },
        }
    ],
    "measures": {
        "turnToward": {"distance": 10000, "bearing": -90, "maxEndAngle": 45},
        "stop": {"maxEndSpeed": 0.5, "routeSpeed": 10},
        "shoot": {"distance": 2000, "bearing": 0, "minShots": 1},
    },
    "deny": [{"pattern": "task:NoTask", "reason": "test deny"}],
}


def _action(
    aid: str,
    kind: str,
    dcs_id: str,
    params: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    rec = {
        "id": aid,
        "kind": kind,
        "dcsId": dcs_id,
        "defaultParams": params or {},
        "availableFor": [{"category": "plane", "groupTask": "Default"}],
    }
    rec.update(extra)
    return rec


ACTIONS: dict[str, dict[str, Any]] = {
    "ORBIT": _action("ORBIT", "task", "Orbit", {"altitude": 2000}),
    "BOOM": _action("BOOM", "task", "Boom"),
    "NO_TASK": _action("NO_TASK", "task", "NoTask"),
    "INVISIBLE": _action("INVISIBLE", "command", "SetInvisible", {"value": True}),
    "ROE": _action("ROE", "option", "Option", {"name": 0}, option="ROE", optionName=0),
}
OPTIONS: dict[str, dict[str, Any]] = {
    "ROE": {
        "id": "ROE",
        "value": 0,
        "valueSets": [{"categories": ["plane"], "values": [], "default": 2}],
    }
}


def _plan() -> dict[str, Any]:
    return ap.plan(
        copy.deepcopy(ACTIONS),
        OPTIONS,
        VERSION,
        sp=copy.deepcopy(SPEC),
        mission_spec=probe_mission.spec(None),
    )


def test_plan_steps() -> None:
    p = _plan()
    steps = p["steps"]
    assert [s["n"] for s in steps] == list(range(1, len(steps) + 1))
    controls = [s for s in steps if s.get("control") and not s.get("controlFor")]
    assert len(controls) == 4 * 16  # categories x contexts of every kind
    orbit = [s for s in steps if s.get("action") == "ORBIT"]
    assert {(s["context"], s["id"], tuple(s["casings"])) for s in orbit} == {
        (c, "Orbit", ("dcs",)) for c in ("setTask", "pushTask", "comboTask", "route")
    }
    assert all(
        s["effect"]["measure"] == "turnToward" and s["effect"]["leg"] == 50000
        for s in orbit
    )
    set_task = next(
        s for s in orbit if s["context"] == "setTask" and s["id"] == "Orbit"
    )
    assert set_task["task"] == {
        "id": "Orbit",
        "params": {
            "altitude": "$alt",
            "pattern": "Circle",
            "point": "$target",
            "speed": "$speed",
        },
    }
    effect_controls = [s for s in steps if s.get("controlFor") == "ORBIT"]
    assert len(effect_controls) == 4 and all(
        s["id"] == ap.CONTROL_ID for s in effect_controls
    )
    route = next(s for s in orbit if s["context"] == "route" and s["id"] == "Orbit")
    assert "task" not in route and route["route"].startswith(ap.ROUTE_PREFIX)
    ms = probe_mission.spec(None)
    x, y = ms["sides"]["blue"]["land"]
    assert route["effect"]["target"] == [x + 30000, y - 10000]
    extra = {e.name: (obj, e) for obj, e in p["extra"]}
    obj, e = extra[route["route"]]
    assert (
        obj == "PROBE_PLANE"
        and e.at == (x + 30000, y)
        and e.points == ((x + 80000, y),)
    )
    assert e.tasks == [
        {
            "id": "Orbit",
            "params": {
                "altitude": 3000,
                "pattern": "Circle",
                "point": {"x": x + 30000, "y": y - 10000},
                "speed": ms["objects"][0]["speed"]["blue"],  # F-15C vOptMs
            },
        }
    ]
    inv = [s for s in steps if s.get("action") == "INVISIBLE"]
    wrapped = next(
        s for s in inv if s["context"] == "wrappedAction" and s["id"] == "SetInvisible"
    )
    assert wrapped["task"] == {
        "id": "WrappedAction",
        "params": {"action": {"id": "SetInvisible", "params": {"value": True}}},
    }
    combo = next(s for s in inv if s["context"] == "comboTask")
    assert combo["task"]["params"]["tasks"][0]["id"] == "WrappedAction"
    roe = [s for s in steps if s.get("action") == "ROE"]
    set_option = next(s for s in roe if s["context"] == "setOption")
    assert (
        set_option["optionName"],
        set_option["optionValue"],
        set_option["casings"],
    ) == (0, 2, ["numeric"])
    assert {s["id"] for s in roe if s["context"] == "route"} == {"Option"}
    assert all(
        s["denied"] == "test deny" for s in steps if s.get("action") == "NO_TASK"
    )
    assert _plan()["id"] == p["id"]


def test_plan_rejects_unmatched_effects() -> None:
    sp = copy.deepcopy(SPEC)
    sp["effects"][0]["dcsId"] = "Nothing"
    with pytest.raises(SystemExit):
        ap.plan(
            ACTIONS,
            OPTIONS,
            VERSION,
            sp=sp,
            mission_spec=probe_mission.spec(None),
        )


def test_plan_lua_and_mission_groups() -> None:
    p = _plan()
    text = ap.plan_lua(p, ap.MAIN.out_rel)
    assert ap.read_plan_lua(text)["steps"][0]["n"] == 1
    loaded = LuaRuntime().execute(text)
    assert loaded["id"] == p["id"] and len(loaded["steps"]) == len(p["steps"])
    step = loaded["steps"][1]
    assert step["context"] == p["steps"][0]["context"]
    m = probe_mission.build(probe_mission.spec(None), None, p["extra"])
    assert "groups" in m.pools


def test_attribute_log() -> None:
    logs = [
        "\n".join(
            [
                "2026-01-01 00:00:00.000 INFO    X: before",
                "2026-01-01 00:00:00.000 INFO    DCS.Lua.Exporter (Main): ACTIONS PROBE BEGIN abc 2",
                "2026-01-01 00:00:00.000 ERROR   SCRIPTING: unknown task orbit",
                "2026-01-01 00:00:00.000 INFO    DCS.Lua.Exporter (Main): ACTIONS PROBE END abc 2",
                "2026-01-01 00:00:00.000 INFO    X: between",
                "[DCS.Lua.Exporter][INFO] ACTIONS PROBE BEGIN other 3",
                "noise of another plan",
            ]
        )
    ]
    assert ap.attribute_log(logs, "abc") == {
        2: ["ERROR   SCRIPTING: unknown task orbit"]
    }


def _record(
    apply: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    measure: dict[str, Any] | None = None,
) -> str:
    import json

    parts: dict[str, Any] = {
        "status": "done",
        "apply": apply or {"accepted": True},
        "after": after or {"hasTaskAfter": True},
    }
    if measure is not None:
        parts["measure"] = measure
    return json.dumps(parts)


def test_document_judges_effects_and_controls() -> None:
    p = _plan()
    by = {
        (s.get("action"), s.get("controlFor"), s["category"], s["context"], s["id"]): s[
            "n"
        ]
        for s in p["steps"]
    }
    ctl = by[(None, None, "plane", "setTask", ap.CONTROL_ID)]
    good = by[("ORBIT", None, "plane", "setTask", "Orbit")]
    bad = by[("ORBIT", None, "plane", "pushTask", "Orbit")]
    orbit_ctl = by[(None, "ORBIT", "plane", "setTask", ap.CONTROL_ID)]
    inv = by[("INVISIBLE", None, "plane", "setCommand", "SetInvisible")]
    lines = [f"P\t{p['id']}", f"V\t{VERSION}", 'X\t{"eventHandler":true}']
    lines.append(f"R\t{ctl}\t" + _record(after={"hasTaskAfter": False}))
    lines.append(
        f"R\t{good}\t"
        + _record(
            after={"hasTaskAfter": True, "effectStart": {"angle": 90}},
            measure={"end": {"angle": 5}},
        )
    )
    lines.append(
        f"R\t{bad}\t"
        + _record(
            after={"hasTaskAfter": False, "effectStart": {"angle": 90}},
            measure={"end": {"angle": 100}},
        )
    )
    lines.append(
        f"R\t{orbit_ctl}\t"
        + _record(after={"hasTaskAfter": False}, measure={"end": {"angle": 110}})
    )
    push_ctl = by[(None, "ORBIT", "plane", "pushTask", ap.CONTROL_ID)]
    lines.append(
        f"R\t{push_ctl}\t"
        + _record(after={"hasTaskAfter": False}, measure={"end": {"angle": 110}})
    )
    lines.append(
        f"R\t{inv}\t" + _record(apply={"accepted": False, "error": "unknown command"})
    )
    log = f"[X][INFO] ACTIONS PROBE BEGIN {p['id']} {bad}\nERROR unknown task orbit\n[X][INFO] ACTIONS PROBE END {p['id']} {bad}\n"
    doc = ap.document(p, "\n".join(lines) + "\n", [log], SPEC["measures"])
    rows = {r["n"]: r for r in doc["steps"]}
    assert rows[good]["effect"]["observed"] is True
    assert rows[bad]["effect"]["observed"] is False
    assert rows[bad]["logLines"] == ["ERROR unknown task orbit"]
    assert rows[inv]["error"] == "unknown command"
    assert rows[good]["effectObserved"] is True
    assert rows[inv]["effectObserved"] is None and "getter" in rows[inv]["effectNote"]
    assert doc["summary"]["works"]["ORBIT"]["setTask/plane"] == ["dcs"]
    assert doc["summary"]["works"]["INVISIBLE"]["setCommand/plane"] == []
    assert doc["stats"]["complete"] is False
    assert doc["setup"] == {"eventHandler": True}
    actions = copy.deepcopy(ACTIONS)
    assert ap.join(doc, actions) == []
    orbit = {(e["context"], e["id"]): e for e in actions["ORBIT"]["probe"]}
    assert orbit[("setTask", "Orbit")] == {
        "context": "setTask",
        "category": "plane",
        "casings": ["dcs"],
        "id": "Orbit",
        "status": "done",
        "accepted": True,
        "hasTaskAfter": True,
        "effectObserved": True,
        "logLines": 0,
    }
    assert orbit[("route", "Orbit")]["status"] == "notRun"


def test_cache_round_trip(tmp_path: Path) -> None:
    p = _plan()
    doc = ap.document(p, f"P\t{p['id']}\n", [], SPEC["measures"])
    probe = replace(ap.MAIN, cache=tmp_path / "cache")
    store = probe.store
    assert store.status(VERSION, p["id"])[0] is CacheState.MISSING
    store.write(doc, VERSION, doc["plan"])
    assert store.status(VERSION, p["id"])[0] is CacheState.PARTIAL
    assert store.status(VERSION, "other")[0] is CacheState.INPUTS_CHANGED
    loaded = probe.load(VERSION)
    assert loaded is not None and loaded["plan"] == p["id"]
    assert set(store.version_files(VERSION, tmp_path)) == {"api/actions-probe.json"}
    assert probe.load("1.0") is None


def test_carried_actions_probe_is_marked(tmp_path: Path) -> None:
    p = _plan()
    doc = ap.document(p, f"P\t{p['id']}\n", [], SPEC["measures"])
    hold(tmp_path, VERSION)
    write(tmp_path / "latest" / "api" / ap.MAIN.file, json_text(doc))
    probe, newer = replace(ap.MAIN, cache=tmp_path / "cache"), "9.9.10.1"
    carried = probe.load(newer, tmp_path)
    assert carried is not None
    assert (carried["dcsVersion"], carried["probedOn"]) == (newer, VERSION)
    assert carried["steps"] == doc["steps"]
    actions = copy.deepcopy(ACTIONS)
    assert ap.join(carried, actions) == []
    assert actions["ORBIT"]["probedOn"] == VERSION
    own = copy.deepcopy(ACTIONS)
    ap.join(doc, own)
    assert "probedOn" not in own["ORBIT"] and own["ORBIT"]["probe"]


def _install(root: Path, p: dict[str, Any], followup: bool = False) -> Path:
    hooks = root / "Scripts" / "Hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    for hook in (ap.HOOK, ap.JSON_LIB):
        shutil.copy(hook, hooks / hook.name)
    probe = ap.FOLLOWUP if followup else ap.MAIN
    write(hooks / ap.LIB_NAME, probe.lib_lua())
    write(hooks / ap.PLAN_NAME, ap.plan_lua(p, probe.out_rel))
    return root / probe.out_rel / ap.PROGRESS


def _hook_run(root: Path, followup: bool = False) -> subprocess.CompletedProcess[str]:
    assert LUA is not None
    out_rel = (ap.FOLLOWUP if followup else ap.MAIN).out_rel
    return subprocess.run(
        [
            LUA,
            str(TESTS_LUA / "test_actions_probe.lua"),
            str(TESTS_LUA),
            f"{root}/",
            out_rel,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


@needs_lua
def test_hook_crash_resume(tmp_path: Path) -> None:
    p = _plan()
    root = tmp_path / "sg"
    progress = _install(root, p)

    first = _hook_run(root)
    assert first.returncode == 3, first.stdout + first.stderr
    boom = next(s["n"] for s in p["steps"] if s.get("action") == "BOOM")
    lines = progress.read_text().splitlines()
    assert lines[0] == f"P\t{p['id']}" and lines[-1] == f"S\t{boom}"

    second = _hook_run(root)
    assert second.returncode == 0, second.stdout + second.stderr
    assert "ACTIONS PROBE TEST DONE" in second.stdout
    text = progress.read_text()
    doc = ap.document(p, text, [first.stdout, second.stdout], SPEC["measures"])
    rows = {r["n"]: r for r in doc["steps"]}
    assert doc["stats"]["complete"] is True
    assert rows[boom]["status"] == "crashed"
    assert all(
        r["status"] == "denied" for r in doc["steps"] if r["action"] == "NO_TASK"
    )
    works = doc["summary"]["works"]
    assert works["ORBIT"]["setTask/plane"] == ["dcs"]
    assert works["ORBIT"]["pushTask/plane"] == ["dcs"]
    assert works["ORBIT"]["comboTask/plane"] == ["dcs"]
    assert works["INVISIBLE"]["setCommand/plane"] == ["dcs"]
    # The stub takes any option number, so the control passes too.
    assert works["ROE"]["setOption/plane"] == []
    blind = doc["summary"]["indistinguishable"]
    assert blind["ROE"]["setOption/plane"] == ["numeric"]
    assert blind["INVISIBLE"]["comboTask/plane"] == ["dcs"]
    route = next(
        r
        for r in doc["steps"]
        if r["action"] == "ORBIT" and r["context"] == "route" and r["id"] == "Orbit"
    )
    assert route["status"] == "done" and route["accepted"] is True
    setup = doc["setup"]
    assert (
        setup["eventHandler"] is True and setup["samples"]["PROBE_PLANE_BLUE"] is True
    )


def test_spec_and_lib() -> None:
    assert ap.spec(None)["samples"]["plane"] == "PROBE_PLANE"
    assert ap.MAIN.lib_lua() == ap.LIB.read_text(encoding="utf-8")
    assert ap.FOLLOWUP.lib_lua().startswith("local M = (function(...)\n")


def _row(
    n: int,
    kind: str,
    context: str,
    casings: list[str],
    *,
    action: str | None = "A",
    accepted: bool = True,
    lines: list[str] | tuple[str, ...] = (),
    **extra: Any,
) -> dict[str, Any]:
    return {
        "n": n,
        "action": action,
        "kind": kind,
        "dcsId": "X",
        "category": "plane",
        "context": context,
        "id": "X",
        "casings": casings,
        "status": "done",
        "accepted": accepted,
        "logLines": list(lines),
        **extra,
    }


def test_works_ignores_event_lines_and_reports_indistinguishable() -> None:
    event = "INFO    Scripting (Main): event:type=engine startup,t=1"
    rows = [
        _row(
            1, "task", "setTask", ["control"], action=None, accepted=False, control=True
        ),
        _row(2, "task", "setTask", ["dcs"], lines=[event], hasTaskAfter=True),
        _row(3, "task", "setTask", ["lower"], lines=["ERROR   unknown task"]),
        _row(4, "task", "route", ["control"], action=None, control=True),
        _row(5, "task", "route", ["dcs"], lines=[event]),
        _row(6, "command", "comboTask", ["dcs"]),
        _row(7, "command", "setCommand", ["control"], action=None, control=True),
        _row(8, "command", "setCommand", ["dcs"], variant="v"),
    ]
    s = ap._summary(rows)
    assert s["works"]["A"]["setTask/plane"] == ["dcs"]
    assert s["works"]["A"]["route/plane"] == []
    assert s["indistinguishable"]["A"]["route/plane"] == ["dcs"]
    assert s["indistinguishable"]["A"]["comboTask/plane"] == ["dcs"]
    assert s["indistinguishable"]["A[v]"]["setCommand/plane"] == ["dcs"]
    assert s["byContext"]["task"]["setTask"]["dcs"]["withLogLines"] == 0
    assert s["byContext"]["task"]["setTask"]["lower"]["withLogLines"] == 1


def test_rescore_keeps_rows_and_judges_again() -> None:
    p = _plan()
    doc = ap.document(p, f"P\t{p['id']}\n", [], SPEC["measures"])
    doc["criteria"], doc["summary"] = "old", {}
    again = ap.rescore(doc, SPEC["measures"])
    assert again["criteria"] == ap.CRITERIA and "indistinguishable" in again["summary"]
    assert [r["n"] for r in again["steps"]] == [r["n"] for r in doc["steps"]]


FSPEC: dict[str, Any] = {
    "cases": [
        {
            "kind": "task",
            "dcsId": "Orbit",
            "categories": ["plane"],
            "contexts": ["setTask", "route"],
            "measure": "turnToward",
            "seconds": 2,
            "params": {"pattern": "Circle"},
            "variants": {
                "point": {"point": "$target"},
                "xy": {"x": "$target.x", "y": "$target.y"},
            },
        },
        {
            "kind": "command",
            "dcsId": "StopRoute",
            "categories": ["plane"],
            "contexts": ["setCommand", "wrappedAction"],
            "measure": "stop",
            "seconds": 2,
            "params": {"value": True},
            "compare": [
                {
                    "id": "SetInvisible",
                    "label": "inert",
                    "params": {"value": True},
                    "contexts": ["wrappedAction"],
                }
            ],
        },
        {
            "kind": "task",
            "dcsId": "Boom",
            "categories": ["plane"],
            "contexts": ["setTask"],
            "variants": {"here": {"point": "$target"}},
        },
        {
            "kind": "task",
            "dcsId": "Bombing",
            "categories": ["plane"],
            "object": "PROBE_BOMBER",
            "contexts": ["setTask", "route"],
            "measure": "shoot",
            "seconds": 2,
            "target": "PROBE_TARGET",
            "at": {"anchor": "land", "offset": [-5000, 0]},
            "leg": 20000,
            "variants": {"point": {"point": "$target"}},
        },
    ],
    "objects": [
        {
            "name": "PROBE_BOMBER",
            "kind": "plane",
            "sides": ["blue"],
            "anchor": "land",
            "offset": [0, 5000],
            "alt": 3000,
            "type": "F-15E",
            "fuel": 10246,
            "speed": 220,
            "fires": True,
            "pylons": {4: "{Mk82AIR}"},
        },
        {
            "name": "PROBE_TARGET",
            "kind": "vehicle",
            "sides": ["red"],
            "anchorSide": "blue",
            "anchor": "land",
            "offset": [5000, 0],
            "type": "T-72B",
            "immortal": True,
        },
    ],
    "options": {"ids": ["ROE"], "missionValues": 1},
}
FOPTIONS: dict[str, dict[str, Any]] = {
    "ROE": {
        "id": "ROE",
        "value": 0,
        "valueSets": [{"categories": ["plane"], "values": [{"value": 2}]}],
        "missionValues": [{"count": 1, "value": 4}, {"count": 9, "value": 2}],
    }
}


def _followup() -> dict[str, Any]:
    return ap.followup_plan(
        copy.deepcopy(ACTIONS),
        FOPTIONS,
        VERSION,
        sp=copy.deepcopy(SPEC),
        fsp=copy.deepcopy(FSPEC),
        mission_spec=probe_mission.spec(None),
    )


def test_followup_plan() -> None:
    p = _followup()
    steps = p["steps"]
    assert p["id"] != _plan()["id"] and _followup()["id"] == p["id"]
    orbit = [s for s in steps if s.get("action") == "ORBIT"]
    assert {(s["context"], s["variant"]) for s in orbit} == {
        (c, v) for c in ("setTask", "route") for v in ("point", "xy")
    }
    xy = next(s for s in orbit if s["context"] == "setTask" and s["variant"] == "xy")
    assert xy["task"]["params"] == {
        "altitude": 2000,
        "pattern": "Circle",
        "x": "$target.x",
        "y": "$target.y",
    }
    assert xy["spawn"] is True and xy["sample"] == f"{ap.SPAWN_PREFIX}{xy['n']:05d}"
    groups = {e.name: (obj, e) for obj, e in p["extra"]}
    obj, g = groups[xy["sample"]]
    ms = probe_mission.spec(None)
    x, y = ms["sides"]["blue"]["land"]
    assert obj == "PROBE_PLANE" and g.at == (x + 30000, y)
    assert g.points == ((x + 80000, y),)
    assert g.tasks == [
        ms["roe"]["Air"]["hold"],
        probe_mission.IMMORTAL,
        probe_mission.INVISIBLE,
    ]
    assert not any(s.startswith(ap.SPAWN_PREFIX) for s in p["samples"])
    ctl = [s for s in steps if s.get("controlFor") == "ORBIT"]
    assert len(ctl) == 2 and all(s.get("spawn") or s["context"] == "route" for s in ctl)
    stop = [s for s in steps if s.get("action") == "StopRoute"]
    assert {(s["context"], s["id"], tuple(s["casings"])) for s in stop} == {
        ("setCommand", "StopRoute", ("dcs",)),
        ("wrappedAction", "StopRoute", ("dcs",)),
        ("wrappedAction", "SetInvisible", ("inert",)),
    }
    speed = groups[stop[0]["sample"]][1].speed
    assert speed == SPEC["measures"]["stop"]["routeSpeed"]
    boom = next(s for s in steps if s.get("action") == "BOOM")
    assert "spawn" not in boom and "effect" not in boom
    assert isinstance(boom["task"]["params"]["point"]["x"], float | int)
    roe = [s for s in steps if s.get("action") == "ROE"]
    assert [(s["optionValue"], s["variant"]) for s in roe] == [(2, "value=2")]
    controls = {
        (s["kind"], s["context"])
        for s in steps
        if s.get("control") and not s.get("controlFor")
    }
    assert ("option", "setOption") in controls and ("task", "setTask") in controls
    assert ap.run_seconds(p) > sum(
        s["effect"]["seconds"] for s in steps if "effect" in s
    )
    assert "spawned groups" in "\n".join(ap.summary(p))


def test_followup_plan_targets() -> None:
    p = _followup()
    ms = probe_mission.spec(None)
    x, y = ms["sides"]["blue"]["land"]
    bombing = [s for s in p["steps"] if s.get("action") == "Bombing"]
    ctl = [s for s in p["steps"] if s.get("controlFor") == "Bombing"]
    assert len(bombing) == 2 and len(ctl) == 2
    for s in bombing + ctl:
        assert s["effect"]["target"] == [x + 5000, y]
        assert s["effect"]["targetGroup"] == "PROBE_TARGET_RED"
        assert s["effect"]["leg"] == 20000
    groups = {e.name: (obj, e) for obj, e in p["extra"]}
    spawn = next(s for s in bombing if s["context"] == "setTask")
    obj, g = groups[spawn["sample"]]
    assert obj == "PROBE_BOMBER" and g.at == (x - 5000, y)
    assert g.points == ((x + 15000, y),)
    assert (
        g.tasks[0] == ms["roe"]["Air"]["fires"]
    )  # attacks only what it is tasked with
    route = next(s for s in bombing if s["context"] == "route")
    assert route["sample"] == "PROBE_BOMBER_BLUE"
    _, r = groups[route["route"]]
    assert r.tasks[0]["params"]["point"] == {"x": x + 5000, "y": y}
    pools = ap.mission(p, ms, None).pools["groups"]
    assert {"PROBE_BOMBER_BLUE", "PROBE_TARGET_RED"} <= set(pools)
    assert not {"PROBE_BOMBER_RED", "PROBE_TARGET_BLUE"} & set(pools)
    main = _plan()
    assert "PROBE_BOMBER_BLUE" not in ap.mission(main, ms, None).pools["groups"]
    bad = copy.deepcopy(FSPEC)
    bad["cases"][-1]["target"] = "PROBE_NOTHING"
    with pytest.raises(SystemExit):
        ap.followup_plan(ACTIONS, FOPTIONS, VERSION, sp=SPEC, fsp=bad, mission_spec=ms)


def test_followup_spec_is_checked() -> None:
    fsp = ap.followup_spec(None)
    assert {c["dcsId"] for c in fsp["cases"]} >= {"Orbit", "StopRoute"}
    bad = copy.deepcopy(FSPEC)
    bad["cases"][0]["contexts"] = ["setCommand"]
    with pytest.raises(SystemExit):
        ap.followup_plan(
            ACTIONS,
            FOPTIONS,
            VERSION,
            sp=SPEC,
            fsp=bad,
            mission_spec=probe_mission.spec(None),
        )


@needs_lua
def test_followup_hook_spawns_and_scores(tmp_path: Path) -> None:
    p = _followup()
    root = tmp_path / "sg"
    progress = _install(root, p, followup=True)
    assert "actions-probe-followup" in str(progress)  # its own progress file
    run = _hook_run(root, followup=True)
    assert run.returncode == 3, run.stdout + run.stderr  # Boom
    run = _hook_run(root, followup=True)
    assert run.returncode == 0, run.stdout + run.stderr
    doc = ap.document(
        p,
        progress.read_text(),
        [run.stdout],
        SPEC["measures"],
        ap.FOLLOWUP.format,
    )
    assert doc["format"] == ap.FOLLOWUP.format and doc["stats"]["complete"] is True
    works = doc["summary"]["works"]
    assert works["ORBIT[point]"]["setTask/plane"] == ["dcs"]
    assert works["ORBIT[xy]"]["setTask/plane"] == []
    assert works["StopRoute"]["setCommand/plane"] == ["dcs"]
    rows = [r for r in doc["steps"] if r.get("spawn")]
    assert rows and all(r["status"] == "done" for r in rows)
    bombing = [r for r in doc["steps"] if r["action"] == "Bombing"]
    assert bombing and all(
        r["effect"]["end"] == {"shots": 0, "hits": 0} for r in bombing
    )
    assert all(r.get("variant") for r in doc["steps"] if r["action"] == "ORBIT")
