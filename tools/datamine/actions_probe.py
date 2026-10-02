"""Plan, cache and document the live AI actions probe (``hook/actions-probe.lua``,
``hook/actions-probe-lib.lua``), which writes ``api/actions-probe.json`` into
the reference data and, joined by ``extract_actions``, each action's ``probe``.

It settles which task ids the engine takes, per context: every Mission Editor
action (``extract_actions``), called on the blue sample group of each group
category the action is offered for (``overlays.yaml`` ``probe/actions``
``samples``, objects of the ``probe/mission`` mission), in each context of its
kind:

* task, en-route task: ``setTask``, ``pushTask``, ``comboTask`` (setTask of a
  ``ComboTask`` holding it), ``route``
* command: ``setCommand``, ``wrappedAction`` (setTask of a ``WrappedAction``),
  ``comboTask`` (a ``ComboTask`` holding that ``WrappedAction``), ``route``
* option: ``setOption`` (the option number; label ``numeric``),
  ``wrappedAction``, ``comboTask``, ``route`` (the ``Option`` id)

``route``: a late-activated mission group (``probe_mission.Extra``, a copy of
the category's sample object) whose first waypoint's ``ComboTask`` holds the
action as the Mission Editor writes it (commands and options in a
``WrappedAction``); the step activates it, reads its controller and destroys it.

Each step calls the id in DCS casing (label ``dcs``). Params: the Mission
Editor's default params (an option's value: its default params' ``value``,
else the category's ``optionValues`` default). A ``control`` step per kind,
category and context uses the id ``ActionsProbeNoSuchId``: what an unknown id
does there.

Effects (``probe/actions`` ``effects``): for the listed ids and categories,
every step (and a control with the same params) also measures a behaviour
change over ``seconds``: ``turnToward`` (target ``distance`` m at ``bearing``
degrees from the lead unit's velocity; the end angle between velocity and
target bearing), ``stop`` (ground speed) and ``shoot`` (shots fired). Their
params may use the placeholders ``$target``, ``$target.x``, ``$target.y``,
``$alt``, ``$speed`` (actions-probe-lib.lua); API context steps first set a
straight ``Mission`` route (reset), route steps fly or drive north from their
spawn. ``deny``: ``kind:dcsId`` patterns (``*`` any text) never called.

``actions-probe.json`` (``document``): ``format`` ``dcs-actions-probe/1``,
``dcsVersion``, ``plan``, ``criteria``, ``setup``, ``steps`` (one row per
step: ``accepted``, ``error``, ``hasTaskBefore``/``Immediate``/``After``,
``effect`` (start/end values) with ``observed`` judged against its control,
``effectObserved`` (null with an ``effectNote`` when nothing is measured),
``logLines``: the dcs.log lines between the step's BEGIN and END markers,
prefix dropped),
``summary`` (per kind, context and label: steps, accepted, hasTaskAfter,
effectObserved, withLogLines (``event:`` lines of the probe's event handler
not counted); ``works``: per action and context the labels meeting
``criteria``; ``indistinguishable``: those that met it where an unknown id
does too) and ``stats``.

The follow-up (``followup_plan``, ``probe/actionsFollowup``) settles what the
main probe leaves open: point vs x/y params, option values, whether Bombing
and EngageTargetsInZone attack. Its API-context effect steps run on a fresh
late-activated copy of the sample each (``spawn``;
``hook/actions-probe-followup-lib.lua``, appended to the lib in the run dir),
so one step's task cannot confound the next. Its ``objects`` join the probe
mission's (a loaded bomber, a red target group); a case's ``target`` object
fixes the effect target (``$target``) at that group, whose hits by the
step's group the lib counts next to its shots. It writes
``api/actions-probe-followup.json`` (``dcs-actions-probe-followup/1``, rows
also carry ``variant``) and caches in ``.datamine/actions-probe-followup``.

``refresh.py --actions-probe`` caches a run in ``.datamine/actions-probe``
(``actions-probe.json``, ``inputs`` (the plan id), ``logs/``, then ``done`` or
``partial``); interrupted, it also installs the partial document.

    uv run python -m tools.datamine.actions_probe [--followup] [--data-dir DIR] [--plan-out FILE]

prints the plan made from ``dcs-world-reference/latest/actions`` without DCS.

    uv run python -m tools.datamine.actions_probe rescore [--followup]

re-scores the cached document (``summary``, ``criteria``) with this module's
rules, caches and installs it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from tools.package.lua_data import lua_inline

from . import overlays as overlays_mod
from . import probe_mission
from .common import (
    API_DIR,
    CACHE_DIR,
    HOOK_DIR,
    LATEST,
    PROBED_ON,
    REFERENCE_DATA_DIR,
    ProbeCache,
    fail,
    glob_re,
    hooks_hash,
    install_probe,
    json_text,
    load_json,
    load_plan_lua,
    load_series,
    progress_lines,
    read_progress,
    version_probe,
)

HOOK = HOOK_DIR / "actions-probe.lua"
LIB = HOOK_DIR / "actions-probe-lib.lua"
# The hooks' JSON encoder (probe-call.lua's), passed to the lib as its argument.
JSON_LIB = HOOK_DIR / "probe-call.lua"
PROBE_HOOKS = [HOOK, LIB, JSON_LIB]
FOLLOWUP_LIB = HOOK_DIR / "actions-probe-followup-lib.lua"
LIB_NAME = "actions-probe-lib.lua"
PLAN_NAME = "actions-probe-plan.lua"
PROGRESS = "progress.tsv"
DONE = "done"
LOGS = "logs"
FORMAT = "dcs-actions-probe/1"
SERIES, TABLE = "probe", "actions"
FOLLOWUP_TABLE = "actionsFollowup"
CONTROL_ID = "ActionsProbeNoSuchId"
CONTROL_OPTION = 99999
CATEGORIES = ("plane", "helicopter", "vehicle", "ship")
KINDS = ("task", "enrouteTask", "command", "option")
CONTEXTS = {
    "task": ("setTask", "pushTask", "comboTask", "route"),
    "enrouteTask": ("pushTask", "setTask", "comboTask", "route"),
    "command": ("setCommand", "wrappedAction", "comboTask", "route"),
    "option": ("setOption", "wrappedAction", "comboTask", "route"),
}
MEASURES = ("turnToward", "stop", "shoot")
# actions-probe.lua's pacing (model seconds); FRAME_SECONDS a frame at ~60 fps.
SETTLE_SECONDS, WARMUP_SECONDS, RESET_SECONDS, FRAME_SECONDS = 1, 10, 5, 1 / 60
ROUTE_PREFIX = "ACTIONS_PROBE_"
SPAWN_PREFIX = "ACTIONS_SPAWN_"
ROUTE_LEG = {"turnToward": 50000, "stop": 3000}
CRITERIA = (
    "An id works in a context when its step was accepted (no Lua error), "
    "logged no dcs.log line (the probe's own event: lines aside), and, where "
    "measured, its effect beat the control's; for setTask, pushTask and "
    "comboTask also when hasTaskAfter is true while the control's is false. "
    "Without a measured effect it is indistinguishable instead when the "
    "unknown-id control of its kind, category and context met the same "
    "checks, and always for a command or option in a comboTask and a task or "
    "en-route task in a route (unknown ids pass silently there)."
)
_EVENT_LINE = re.compile(r"^\w+\s+Scripting \(Main\): event:")
_MARKER = re.compile(r"ACTIONS PROBE (BEGIN|END) (\w+) (\d+)\s*$")
_LOG_PREFIX = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+\s+")
MAX_LOG_LINES = 20
# Why a step without an effect measure has no effectObserved, by kind.
NO_EFFECT = {
    "task": "no cheap observable measured for this task",
    "enrouteTask": "no cheap observable measured for en-route tasks",
    "command": "no observable measured (no getter for command state)",
    "option": "no getter for option values",
}
# An effect overlay entry and its index in probe/actions ``effects`` (None:
# a follow-up case's).
Effect = tuple[dict[str, Any], int | None]


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


def spec(version: str | None = None) -> dict[str, Any]:
    """The ``probe/actions`` overlay table, checked."""
    value = overlays_mod.load(version).table(SERIES, TABLE)
    where = f"overlays {SERIES}/{TABLE}"
    if not isinstance(value, dict):
        fail(f"{where}: a mapping")
    for key in ("samples", "route", "effects", "measures", "deny"):
        if key not in value:
            fail(f"{where}: missing {key}")
    if sorted(value["samples"]) != sorted(CATEGORIES):
        fail(f"{where}: samples must name one object per {', '.join(CATEGORIES)}")
    if sorted(value["route"]) != sorted(CATEGORIES):
        fail(f"{where}: route must place {', '.join(CATEGORIES)}")
    for e in value["effects"]:
        if e.get("measure") not in MEASURES:
            fail(
                f"{where} effect {e.get('dcsId')}: measure must be one of {', '.join(MEASURES)}"
            )
        if not set(e.get("categories") or []) <= set(CATEGORIES):
            fail(f"{where} effect {e.get('dcsId')}: unknown categories")
    if sorted(value["measures"]) != sorted(MEASURES):
        fail(f"{where}: measures must configure {', '.join(MEASURES)}")
    return value


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


def _wrapped(action: dict[str, Any]) -> dict[str, Any]:
    return {"id": "WrappedAction", "params": {"action": action}}


def _option_value(
    action: dict[str, Any], options: dict[str, Any], category: str
) -> Any:
    params = action.get("defaultParams") or {}
    if "value" in params:
        return params["value"]
    opt = options.get(action.get("option") or "")
    for s in (opt or {}).get("valueSets") or []:
        if (not s.get("categories") or category in s["categories"]) and "default" in s:
            return s["default"]
    return None


def _resolve(v: Any, ctx: dict[str, Any]) -> Any:
    """Placeholders resolved as actions-probe-lib.lua does (route steps)."""
    if isinstance(v, str) and v.startswith("$"):
        tx, tz = ctx["target"]
        table = {
            "$target": {"x": tx, "y": tz},
            "$target.x": tx,
            "$target.y": tz,
            "$alt": ctx.get("alt"),
            "$speed": ctx.get("speed"),
        }
        if v not in table or table[v] is None:
            fail(f"overlays {SERIES}/{TABLE}: placeholder {v} has no value here")
        return table[v]
    if isinstance(v, dict):
        return {k: _resolve(x, ctx) for k, x in v.items()}
    if isinstance(v, list):
        return [_resolve(x, ctx) for x in v]
    return v


class _Planner:
    def __init__(self, sp: dict[str, Any], mission_spec: dict[str, Any]) -> None:
        self.sp = sp
        self.ms = mission_spec
        self.objects: dict[str, dict[str, Any]] = {
            o["name"]: o for o in mission_spec["objects"]
        }
        for cat, name in sp["samples"].items():
            if name not in self.objects:
                fail(
                    f"overlays {SERIES}/{TABLE}: sample {cat} {name!r} is no probe/mission object"
                )
        for e in sp["effects"]:
            if e.get("object") and e["object"] not in self.objects:
                fail(
                    f"overlays {SERIES}/{TABLE}: effect object {e['object']!r} is no probe/mission object"
                )
        self.deny: list[tuple[re.Pattern[str], str]] = [
            (glob_re(d["pattern"]), d["reason"]) for d in sp["deny"]
        ]
        self.steps: list[dict[str, Any]] = []
        self.extra: list[tuple[str, probe_mission.Extra]] = []
        self.used_effects: set[int] = set()

    def effect(self, dcs_id: str, category: str) -> Effect | None:
        for i, e in enumerate(self.sp["effects"]):
            if e["dcsId"] == dcs_id and category in e["categories"]:
                return e, i
        return None

    def denied(self, kind: str, dcs_id: str) -> str | None:
        for pattern, reason in self.deny:
            if pattern.fullmatch(f"{kind}:{dcs_id}"):
                return reason
        return None

    def object_for(self, category: str, eff: dict[str, Any] | None) -> dict[str, Any]:
        return self.objects[(eff or {}).get("object") or self.sp["samples"][category]]

    def route_place(
        self, category: str, e: dict[str, Any] | None = None
    ) -> tuple[float, float]:
        """Where a category's route and spawned groups start (an effect's
        ``at`` instead, when it has one)."""
        r = (e or {}).get("at") or self.sp["route"][category]
        x, y = self.ms["sides"]["blue"][r["anchor"]]
        dx, dy = r["offset"]
        return x + dx, y + dy

    def route_speed(self, e: dict[str, Any] | None) -> float | None:
        """The route speed of a ``stop`` effect's group (``routeSpeed``)."""
        if e is None or e["measure"] != "stop":
            return None
        return cast(float | None, self.sp["measures"]["stop"].get("routeSpeed"))

    def target_of(self, e: dict[str, Any]) -> tuple[str, tuple[float, float]]:
        """An effect's ``target`` object: its group's name and place (its
        first side's)."""
        obj = self.objects.get(e["target"])
        if obj is None:
            fail(
                f"overlays {SERIES}/{FOLLOWUP_TABLE}: target {e['target']!r} is no "
                "probe mission object"
            )
        side = obj.get("sides", probe_mission.SIDES)[0]
        return f"{obj['name']}_{side.upper()}", probe_mission.anchored(
            self.ms, side, obj
        )

    def add(
        self,
        base: dict[str, Any],
        category: str,
        context: str,
        vid: str,
        labels: list[str],
        item: dict[str, Any] | None,
        eff: Effect | None,
        spawn: bool = False,
    ) -> None:
        """One step; ``spawn``: an API-context effect step runs on a fresh
        late-activated copy of its sample (``SPAWN_PREFIX``)."""
        n = len(self.steps) + 1
        e, effect_index = eff if eff else (None, None)
        obj = self.object_for(category, e)
        step: dict[str, Any] = {
            "n": n,
            **{k: v for k, v in base.items() if v is not None},
            "category": category,
            "context": context,
            "id": vid,
            "casings": labels,
            "sample": f"{obj['name']}_BLUE",
        }
        if e is not None:
            if effect_index is not None:
                self.used_effects.add(effect_index)
            m = self.sp["measures"][e["measure"]]
            step["effect"] = {
                "measure": e["measure"],
                "seconds": e["seconds"],
                **{k: m[k] for k in ("distance", "bearing", "routeSpeed") if k in m},
            }
            leg = _leg(e)
            if leg:
                step["effect"]["leg"] = leg
            if e.get("target"):
                group, place = self.target_of(e)
                step["effect"]["target"] = [place[0], place[1]]
                step["effect"]["targetGroup"] = group
            if spawn and context != "route":
                step["sample"] = f"{SPAWN_PREFIX}{n:05d}"
                step["spawn"] = True
                self.extra.append((obj["name"], self.spawn_group(step, obj, e)))
        kind = base["kind"]
        if e is None and context != "route" and _has_placeholder(item):
            at = probe_mission.anchored(self.ms, "blue", obj)
            item = _resolve(item, self.ctx(obj, at))
        if context == "setOption":
            step["optionName"] = base.get("optionName", CONTROL_OPTION)
            if base.get("optionValue") is not None:
                step["optionValue"] = base["optionValue"]
        elif item is None:
            fail(f"actions probe step {n}: {context} has no task")
        elif context in ("setTask", "pushTask", "setCommand"):
            step["task"] = item
        elif context == "wrappedAction":
            step["task"] = _wrapped(item)
        elif context == "comboTask":
            step["task"] = probe_mission.combo(
                [_wrapped(item) if kind in ("command", "option") else item]
            )
        elif context == "route":
            step["route"] = f"{ROUTE_PREFIX}{n:05d}"
            self.route_group(step, obj, item, e)
        self.steps.append(step)

    def route_group(
        self,
        step: dict[str, Any],
        obj: dict[str, Any],
        item: dict[str, Any],
        e: dict[str, Any] | None,
    ) -> None:
        """A route step's group: at the category's route place, its first
        waypoint holding the action (placeholders resolved), for an effect
        then the leg straight ahead."""
        x, y = self.route_place(step["category"], e)
        ctx: dict[str, Any] | None = None
        points: tuple[tuple[float, float], ...] = ()
        if e is not None:
            m = self.sp["measures"][e["measure"]]
            bearing = m.get("bearing", 0) * math.pi / 180
            dist = m.get("distance", 0)
            target = (x + dist * math.cos(bearing), y + dist * math.sin(bearing))
            if e.get("target"):
                target = self.target_of(e)[1]
            ctx = self.ctx(obj, target)
            step["effect"]["target"] = [target[0], target[1]]
            leg = _leg(e)
            if leg:
                points = ((x + leg, y),)
        elif _has_placeholder(item):
            ctx = self.ctx(obj, (x, y))
        resolved = _resolve(item, ctx) if ctx else item
        wrapped: dict[str, Any] = (
            _wrapped(resolved) if step["kind"] in ("command", "option") else resolved
        )
        self.extra.append(
            (
                obj["name"],
                probe_mission.Extra(
                    step["route"], (x, y), [wrapped], points, self.route_speed(e)
                ),
            )
        )

    def control(
        self,
        kind: str,
        category: str,
        context: str,
        params: dict[str, Any] | None = None,
        eff: Effect | None = None,
        control_for: str | None = None,
        spawn: bool = False,
    ) -> None:
        """A control step: the unknown id (option number) of ``kind`` with
        ``params``; ``control_for``: the action whose effect it judges."""
        base: dict[str, Any] = {"kind": kind, "dcsId": CONTROL_ID, "control": True}
        if control_for:
            base["controlFor"] = control_for
        vid = CONTROL_ID
        if context == "setOption":
            base.update(optionName=CONTROL_OPTION, optionValue=0)
            vid = str(CONTROL_OPTION)
        item = _task_item(kind, vid, {}, params or {})
        self.add(base, category, context, vid, ["control"], item, eff, spawn)

    def ctx(self, obj: dict[str, Any], target: tuple[float, float]) -> dict[str, Any]:
        """Placeholder values for ``obj``'s group and ``target``."""
        return {
            "target": target,
            "alt": obj.get("alt"),
            "speed": probe_mission.per_side(obj.get("speed"), "blue"),
        }

    def spawn_group(
        self, step: dict[str, Any], obj: dict[str, Any], e: dict[str, Any]
    ) -> probe_mission.Extra:
        """A spawn step's group: at the category's route place (the effect's
        ``at``), first waypoint like the sample's (``fire_tasks``, immortal,
        invisible), then the leg straight ahead."""
        x, y = self.route_place(step["category"], e)
        tasks = [
            *probe_mission.fire_tasks(self.ms, obj),
            probe_mission.IMMORTAL,
            probe_mission.INVISIBLE,
        ]
        leg = _leg(e)
        return probe_mission.Extra(
            step["sample"],
            (x, y),
            tasks,
            ((x + leg, y),) if leg else (),
            self.route_speed(e),
        )

    def finish(
        self,
        version: str,
        mission_spec: dict[str, Any],
        hooks: list[Path],
        **extra: Any,
    ) -> dict[str, Any]:
        """The plan: ``steps``, the ``samples`` they use (spawned groups
        aside), the mission's ``extra`` groups and ``extra``; its ``id``
        hashes the steps, the ``hooks`` and the mission."""
        samples = sorted({s["sample"] for s in self.steps if not s.get("spawn")})
        body = {"version": version, "samples": samples, "steps": self.steps}
        h = hashlib.sha256(json.dumps(body, sort_keys=True).encode())
        h.update(hooks_hash(hooks).encode())
        h.update(json.dumps(mission_spec, sort_keys=True).encode())
        return {"id": h.hexdigest()[:16], **body, "extra": self.extra, **extra}


def _leg(e: dict[str, Any]) -> int | None:
    """Metres a measured group flies or drives straight ahead: the effect's
    ``leg``, else its measure's."""
    return e.get("leg", ROUTE_LEG.get(e["measure"]))


def _has_placeholder(v: Any) -> bool:
    if isinstance(v, str):
        return v.startswith("$")
    if isinstance(v, dict):
        return any(_has_placeholder(x) for x in v.values())
    if isinstance(v, list):
        return any(_has_placeholder(x) for x in v)
    return False


def _task_item(
    kind: str, vid: str, action: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
    item: dict[str, Any] = {"id": vid, "params": params}
    if action.get("key") and kind in ("task", "enrouteTask"):
        item["key"] = action["key"]
    return item


def plan(
    actions: dict[str, dict[str, Any]],
    options: dict[str, dict[str, Any]],
    version: str,
    sp: dict[str, Any] | None = None,
    mission_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The probe plan: ``steps`` in run order, the ``samples`` it uses, the
    mission's ``extra`` route groups (not in the plan hook file)."""
    sp = spec(version) if sp is None else sp
    mission_spec = probe_mission.spec(version) if mission_spec is None else mission_spec
    p = _Planner(sp, mission_spec)
    by_kind: dict[str, list[dict[str, Any]]] = {k: [] for k in KINDS}
    for a in sorted(actions.values(), key=lambda a: (KINDS.index(a["kind"]), a["id"])):
        by_kind[a["kind"]].append(a)
    for category in CATEGORIES:
        for kind in KINDS:
            for context in CONTEXTS[kind]:
                p.control(kind, category, context)
            for a in by_kind[kind]:
                if category not in {e["category"] for e in a["availableFor"]}:
                    continue
                dcs_id = a["dcsId"]
                eff = p.effect(dcs_id, category)
                reason = p.denied(kind, dcs_id)
                params = dict(a.get("defaultParams") or {})
                if eff:
                    params.update(eff[0].get("params") or {})
                for context in CONTEXTS[kind]:
                    base = {"action": a["id"], "kind": kind, "dcsId": dcs_id}
                    if reason:
                        base["denied"] = reason
                    if kind != "option":
                        item = _task_item(kind, dcs_id, a, params)
                        p.add(base, category, context, dcs_id, ["dcs"], item, eff)
                        if eff:
                            p.control(kind, category, context, params, eff, a["id"])
                        continue
                    value = _option_value(a, options, category)
                    base["optionName"] = a["optionName"]
                    if value is not None:
                        base["optionValue"] = value
                    if context == "setOption":
                        vid = str(a["optionName"])
                        p.add(base, category, context, vid, ["numeric"], None, eff)
                        continue
                    oparams = {"name": a["optionName"]}
                    if value is not None:
                        oparams["value"] = value
                    item = {"id": dcs_id, "params": oparams}
                    p.add(base, category, context, dcs_id, ["dcs"], item, eff)
    unused = [
        e["dcsId"] for i, e in enumerate(sp["effects"]) if i not in p.used_effects
    ]
    if unused:
        fail(
            f"overlays {SERIES}/{TABLE}: effects {unused} match no action and category"
        )
    return p.finish(version, mission_spec, PROBE_HOOKS)


# ---------------------------------------------------------------------------
# Follow-up plan
# ---------------------------------------------------------------------------


def followup_spec(version: str | None = None) -> dict[str, Any]:
    """The ``probe/actionsFollowup`` overlay table, checked, its objects'
    aircraft values resolved (``probe_mission.resolve_objects``)."""
    value = overlays_mod.load(version).table(SERIES, FOLLOWUP_TABLE)
    return _check_followup(value, version)


def _check_followup(value: Any, version: str | None) -> dict[str, Any]:
    where = f"overlays {SERIES}/{FOLLOWUP_TABLE}"
    if not isinstance(value, dict) or not {"cases", "options"} <= set(value):
        fail(f"{where}: a mapping with cases and options")
    probe_mission.check_objects(value.get("objects") or [], f"{where} objects")
    for c in value["cases"]:
        what = f"{where} case {c.get('dcsId')}"
        if c.get("kind") not in ("task", "enrouteTask", "command"):
            fail(f"{what}: kind must be task, enrouteTask or command")
        if not c.get("categories") or not set(c["categories"]) <= set(CATEGORIES):
            fail(f"{what}: categories must be some of {', '.join(CATEGORIES)}")
        if not c.get("contexts") or not set(c["contexts"]) <= set(CONTEXTS[c["kind"]]):
            fail(f"{what}: contexts must be some of {', '.join(CONTEXTS[c['kind']])}")
        if "measure" in c and (c["measure"] not in MEASURES or "seconds" not in c):
            fail(f"{what}: measure must be one of {', '.join(MEASURES)}, with seconds")
        if {"target", "at", "leg"} & set(c) and "measure" not in c:
            fail(f"{what}: target, at and leg need a measure")
    objects = probe_mission.resolve_objects(
        value.get("objects") or [], f"{where} objects"
    )
    return {**value, "objects": objects}


def followup_mission_spec(
    mission_spec: dict[str, Any], fsp: dict[str, Any]
) -> dict[str, Any]:
    """The probe mission's table with the follow-up's ``objects`` added."""
    objects = fsp.get("objects") or []
    return {**mission_spec, "objects": [*mission_spec["objects"], *objects]}


def _option_values(opt: dict[str, Any], category: str, top: int) -> list[Any]:
    """An option's Mission Editor values for ``category``, then its ``top``
    most frequent install mission values; ``[None]`` when it has none."""
    values = [
        v["value"]
        for s in opt.get("valueSets") or []
        if category in (s.get("categories") or [category])
        for v in s.get("values") or []
        if "value" in v
    ]
    ranked = sorted(
        (m for m in opt.get("missionValues") or [] if "value" in m),
        key=lambda m: -m["count"],
    )
    values += [m["value"] for m in ranked[:top]]
    out: list[Any] = []
    for v in values:
        if not any(type(v) is type(o) and v == o for o in out):
            out.append(v)
    return out or [None]


def _value_variant(value: Any) -> str:
    return "no value" if value is None else f"value={json.dumps(value)}"


def followup_plan(
    actions: dict[str, dict[str, Any]],
    options: dict[str, dict[str, Any]],
    version: str,
    sp: dict[str, Any] | None = None,
    fsp: dict[str, Any] | None = None,
    mission_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The follow-up plan (``probe/actionsFollowup``), shaped as ``plan``'s;
    steps also carry ``variant`` and, on a fresh group, ``spawn``."""
    sp = spec(version) if sp is None else sp
    fsp = followup_spec(version) if fsp is None else _check_followup(fsp, version)
    mission_spec = probe_mission.spec(version) if mission_spec is None else mission_spec
    mission_spec = followup_mission_spec(mission_spec, fsp)
    p = _Planner(sp, mission_spec)
    by_dcs: dict[tuple[str, str], dict[str, Any]] = {}
    for a in sorted(actions.values(), key=lambda a: a["id"]):
        by_dcs.setdefault((a["kind"], a["dcsId"]), a)
    plain: set[tuple[str, str, str]] = set()

    def control(kind: str, category: str, context: str) -> None:
        if (kind, category, context) not in plain:
            plain.add((kind, category, context))
            p.control(kind, category, context)

    for c in fsp["cases"]:
        kind = c["kind"]
        a = by_dcs.get((kind, c["dcsId"])) or {}
        name = a.get("id") or c["dcsId"]
        variants = c.get("variants") or {}
        drop = {k for v in variants.values() for k in v}
        params = {
            k: v for k, v in (a.get("defaultParams") or {}).items() if k not in drop
        }
        params.update(c.get("params") or {})
        eff: Effect | None = None
        if c.get("measure"):
            keys = ("measure", "seconds", "object", "target", "at", "leg")
            e = {k: c[k] for k in keys if k in c}
            eff = ({**e, "dcsId": c["dcsId"], "categories": c["categories"]}, None)
        first = {**params, **next(iter(variants.values()), {})}
        for category in c["categories"]:
            for context in c["contexts"]:
                control(kind, category, context)
                rows = [
                    (v, c["dcsId"], ["dcs"], {**params, **vp})
                    for v, vp in variants.items()
                ] or [(None, c["dcsId"], ["dcs"], params)]
                rows += [
                    (x["label"], x["id"], [x["label"]], x.get("params") or {})
                    for x in c.get("compare") or []
                    if context in x["contexts"]
                ]
                for variant, vid, labels, prm in rows:
                    base = {
                        "action": name,
                        "kind": kind,
                        "dcsId": vid,
                        "variant": variant,
                    }
                    item = _task_item(kind, vid, a, prm)
                    p.add(base, category, context, vid, labels, item, eff, spawn=True)
                if eff:
                    p.control(kind, category, context, first, eff, name, spawn=True)
    by_option = {a["option"]: a for a in actions.values() if a["kind"] == "option"}
    for oid in fsp["options"]["ids"]:
        option = by_option.get(oid)
        if option is None or oid not in options:
            fail(f"overlays {SERIES}/{FOLLOWUP_TABLE}: no option {oid}")
        cats = {e["category"] for e in option["availableFor"]}
        for category in (c for c in CATEGORIES if c in cats):
            control("option", category, "setOption")
            top = fsp["options"].get("missionValues", 0)
            for value in _option_values(options[oid], category, top):
                base = {
                    "action": option["id"],
                    "kind": "option",
                    "dcsId": option["dcsId"],
                    "optionName": option["optionName"],
                    "optionValue": value,
                    "variant": _value_variant(value),
                }
                vid = str(option["optionName"])
                p.add(base, category, "setOption", vid, ["numeric"], None, None)
    return p.finish(
        version,
        mission_spec,
        [*PROBE_HOOKS, FOLLOWUP_LIB],
        objects=fsp.get("objects") or [],
    )


def plan_lua(p: dict[str, Any], out_rel: str) -> str:
    """The plan as the hook file ``actions-probe-plan.lua``; the hook writes
    its progress and done marker in ``<writedir>/<out_rel>``."""
    lines = [
        "-- The actions probe's plan (tools/datamine/actions_probe.py); read by actions-probe.lua.",
        "return {",
        f"  id = {lua_inline(p['id'])},",
        f"  version = {lua_inline(p['version'])},",
        f"  outDir = {lua_inline(out_rel)},",
        f"  samples = {lua_inline(p['samples'])},",
        "  steps = {",
        *(f"    {lua_inline(s)}," for s in p["steps"]),
        "  },",
        "}",
    ]
    return "\n".join(lines) + "\n"


def read_plan_lua(text: str) -> dict[str, Any]:
    """The plan of a hook file ``plan_lua`` wrote: ``id``, ``version``,
    ``samples`` and ``steps`` (no ``extra``)."""
    return load_plan_lua(text, PLAN_NAME, "actions probe", "steps")


def mission(
    p: dict[str, Any], mission_spec: dict[str, Any], defaults: dict[str, Any] | None
) -> probe_mission.Mission:
    """The probe mission with the plan's objects (the follow-up's) and route
    groups."""
    spec = followup_mission_spec(mission_spec, p)
    return probe_mission.build(spec, defaults, p["extra"])


def summary(p: dict[str, Any]) -> list[str]:
    steps = p["steps"]
    lines = [f"Actions probe plan {p['id']} (DCS {p['version']}): {len(steps)} steps"]
    by = Counter((s["kind"], s["context"]) for s in steps)
    for kind in KINDS:
        parts = ", ".join(f"{c} {by[(kind, c)]}" for c in CONTEXTS[kind])
        lines.append(f"  {kind:<12} {parts}")
    lines.append(
        f"  controls {sum(bool(s.get('control')) for s in steps)}, effect steps "
        f"{sum('effect' in s for s in steps)} ({sum(s['effect']['seconds'] for s in steps if 'effect' in s)} s), "
        f"route groups {sum(s['context'] == 'route' for s in steps)}, spawned groups "
        f"{sum(bool(s.get('spawn')) for s in steps)}, denied {sum('denied' in s for s in steps)}"
    )
    labels = Counter(label for s in steps for label in s["casings"])
    lines.append(f"  labels: {dict(sorted(labels.items()))}")
    lines.append(
        f"  estimated run: {run_seconds(p) / 60:.0f} min of model time after the "
        "mission loads (the first run went at about real time)"
    )
    return lines


def run_seconds(p: dict[str, Any]) -> float:
    """Model seconds the hook needs for ``p``: warm-up, each effect's seconds,
    a reset before each API-context effect step, a frame per call."""
    total = SETTLE_SECONDS + WARMUP_SECONDS + FRAME_SECONDS * 2 * len(p["steps"])
    for s in p["steps"]:
        if "effect" in s and not s.get("denied"):
            total += s["effect"]["seconds"]
            if s["context"] != "route":
                total += RESET_SECONDS
    return total


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


def parse_progress(text: str, plan_id: str) -> dict[int, dict[str, Any]]:
    """``{step n: record}`` of a progress file of plan ``plan_id``."""
    pid, lines = progress_lines(text)
    if pid != plan_id:
        return {}
    out: dict[int, dict[str, Any]] = {}
    for tag, rest in lines:
        if tag == "R":
            n, payload = rest.split("\t", 1)
            out[int(n)] = json.loads(payload)
    return out


def setup_record(text: str) -> dict[str, Any] | None:
    for tag, rest in progress_lines(text)[1]:
        if tag == "X":
            return cast(dict[str, Any], json.loads(rest))
    return None


def recorded(progress: Path, plan_id: str) -> int:
    return len(parse_progress(read_progress(progress), plan_id))


def attribute_log(texts: list[str], plan_id: str) -> dict[int, list[str]]:
    """dcs.log lines from each step's BEGIN marker to its END (or the next
    BEGIN), timestamps dropped; the markers themselves excluded."""
    out: dict[int, list[str]] = {}
    for text in texts:
        current: int | None = None
        for line in text.splitlines():
            m = _MARKER.search(line)
            if m:
                what, pid, n = m.groups()
                current = int(n) if what == "BEGIN" and pid == plan_id else None
                continue
            if current is not None and line.strip():
                out.setdefault(current, []).append(_LOG_PREFIX.sub("", line).rstrip())
    return out


def _judge(
    effect: dict[str, Any], control: dict[str, Any] | None, m: dict[str, float]
) -> bool | None:
    def end(e: dict[str, Any] | None, key: str) -> float | None:
        return cast(float | None, ((e or {}).get("end") or {}).get(key))

    measure = effect["measure"]
    if measure == "turnToward":
        mine, ctl = end(effect, "angle"), end(control, "angle")
        if mine is None or ctl is None:
            return None
        return mine <= m["maxEndAngle"] < ctl
    if measure == "stop":
        mine, ctl = end(effect, "speed"), end(control, "speed")
        if mine is None or ctl is None:
            return None
        return mine <= m["maxEndSpeed"] < ctl
    if measure == "shoot":
        mine, ctl = end(effect, "shots"), end(control, "shots")
        if mine is None or ctl is None:
            return None
        return mine >= m["minShots"] > ctl
    return None


def document(
    p: dict[str, Any],
    progress_text: str,
    logs: list[str],
    measures: dict[str, Any],
    fmt: str = FORMAT,
) -> dict[str, Any]:
    """``actions-probe.json`` (``fmt``) of plan ``p`` from a progress file's
    text and the run's dcs.log texts (partial runs too)."""
    records = parse_progress(progress_text, p["id"])
    lines = attribute_log(logs, p["id"])
    rows: list[dict[str, Any]] = []
    for s in p["steps"]:
        r = records.get(s["n"])
        row: dict[str, Any] = {
            k: s.get(k)
            for k in (
                "n",
                "action",
                "kind",
                "dcsId",
                "category",
                "context",
                "id",
                "casings",
            )
        }
        for flag in ("control", "controlFor", "variant", "spawn"):
            if s.get(flag):
                row[flag] = s[flag]
        if s.get("variant") and "optionValue" in s:
            row["optionValue"] = s["optionValue"]
        row["status"] = r["status"] if r else "notRun"
        if r and r.get("reason"):
            row["reason"] = r["reason"]
        if r and r["status"] == "done":
            apply, after = r.get("apply") or {}, r.get("after") or {}
            row["accepted"] = apply.get("accepted")
            if apply.get("error") is not None:
                row["error"] = apply["error"]
            for k in ("hasTaskBefore", "hasTaskImmediate"):
                if k in apply:
                    row[k] = apply[k]
            if "hasTaskAfter" in after:
                row["hasTaskAfter"] = after["hasTaskAfter"]
            for part in ("reset", "cleanup"):
                if (r.get(part) or {}).get("error"):
                    row[f"{part}Error"] = r[part]["error"]
            if "effect" in s:
                row["effect"] = {
                    "measure": s["effect"]["measure"],
                    "seconds": s["effect"]["seconds"],
                    "start": after.get("effectStart"),
                    "end": (r.get("measure") or {}).get("end"),
                }
                if apply.get("target"):
                    row["effect"]["target"] = apply["target"]
        log = lines.get(s["n"], [])
        row["logLines"] = log[:MAX_LOG_LINES]
        if len(log) > MAX_LOG_LINES:
            row["logLinesDropped"] = len(log) - MAX_LOG_LINES
        rows.append(row)
    _judge_rows(rows, measures)
    stats = Counter(r["status"] for r in rows)
    return {
        "format": fmt,
        "dcsVersion": p["version"],
        "plan": p["id"],
        "source": "probe",
        "criteria": CRITERIA,
        "setup": setup_record(progress_text),
        "summary": _summary(rows),
        "stats": {
            "complete": len(records) == len(p["steps"]),
            "status": dict(sorted(stats.items())),
        },
        "steps": rows,
    }


def _judge_rows(rows: list[dict[str, Any]], measures: dict[str, Any]) -> None:
    controls = {
        (r["controlFor"], r["category"], r["context"]): r
        for r in rows
        if r.get("controlFor") and r["status"] == "done"
    }
    for r in rows:
        if r["status"] != "done":
            continue
        eff = r.get("effect")
        if not eff:
            r["effectObserved"] = None
            r["effectNote"] = NO_EFFECT[r["kind"]]
            continue
        if r.get("control"):
            continue
        ctl = controls.get((r["action"], r["category"], r["context"]))
        eff["observed"] = _judge(
            eff, (ctl or {}).get("effect"), measures[eff["measure"]]
        )
        r["effectObserved"] = eff["observed"]


def significant(lines: list[str]) -> list[str]:
    """dcs.log lines but the probe's own event handler's (``event:``)."""
    return [line for line in lines if not _EVENT_LINE.match(line)]


def _passes(r: dict[str, Any], control: dict[str, Any] | None) -> bool:
    if r["status"] != "done" or not r.get("accepted") or significant(r["logLines"]):
        return False
    if "effect" in r:
        return r["effect"].get("observed") is True
    if (
        r["context"] in ("setTask", "pushTask", "comboTask")
        and control
        and control.get("hasTaskAfter") is False
    ):
        return r.get("hasTaskAfter") is True
    return True


def _works(r: dict[str, Any], control: dict[str, Any] | None) -> bool | str:
    """True, False or ``"indistinguishable"`` (see ``CRITERIA``)."""
    if not _passes(r, control):
        return False
    if "effect" in r:
        return True
    blind = (r["context"] == "comboTask" and r["kind"] in ("command", "option")) or (
        r["context"] == "route" and r["kind"] in ("task", "enrouteTask")
    )
    if blind or (control is not None and _control_passes(control)):
        return "indistinguishable"
    return True


def _control_passes(c: dict[str, Any]) -> bool:
    """Whether an unknown id met the checks a step without an effect gets."""
    if c["status"] != "done" or not c.get("accepted") or significant(c["logLines"]):
        return False
    return not (
        c["context"] in ("setTask", "pushTask", "comboTask")
        and c.get("hasTaskAfter") is False
    )


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    controls = {
        (r["kind"], r["category"], r["context"]): r
        for r in rows
        if r.get("control") and not r.get("controlFor") and r["status"] == "done"
    }
    by: dict[str, dict[str, dict[str, Counter[str]]]] = {}
    works: dict[str, dict[str, list[str]]] = {}
    blind: dict[str, dict[str, list[str]]] = {}
    for r in rows:
        if r["status"] != "done":
            continue
        for label in r["casings"]:
            c = (
                by.setdefault(r["kind"], {})
                .setdefault(r["context"], {})
                .setdefault(label, Counter())
            )
            c["steps"] += 1
            c["accepted"] += bool(r.get("accepted"))
            c["hasTaskAfter"] += bool(r.get("hasTaskAfter"))
            c["effectObserved"] += bool((r.get("effect") or {}).get("observed"))
            c["withLogLines"] += bool(significant(r["logLines"]))
        if r.get("control"):
            continue
        name = r["action"] or r["dcsId"]
        if r.get("variant"):
            name += f"[{r['variant']}]"
        key = f"{r['context']}/{r['category']}"
        labels = works.setdefault(name, {}).setdefault(key, [])
        verdict = _works(r, controls.get((r["kind"], r["category"], r["context"])))
        if verdict == "indistinguishable":
            labels = blind.setdefault(name, {}).setdefault(key, [])
        if verdict:
            labels += [lb for lb in r["casings"] if lb not in labels]
    return {
        "byContext": {
            k: {
                c: {lb: dict(sorted(v.items())) for lb, v in sorted(ls.items())}
                for c, ls in sorted(cs.items())
            }
            for k, cs in sorted(by.items())
        },
        "works": {a: dict(sorted(v.items())) for a, v in sorted(works.items())},
        "indistinguishable": {
            a: dict(sorted(v.items())) for a, v in sorted(blind.items())
        },
    }


def rescore(doc: dict[str, Any], measures: dict[str, Any]) -> dict[str, Any]:
    """``doc`` judged and summarised again with this module's rules."""
    rows = [dict(r) for r in doc["steps"]]
    for r in rows:
        if "effect" in r:
            r["effect"] = {k: v for k, v in r["effect"].items() if k != "observed"}
        r.pop("effectObserved", None)
        r.pop("effectNote", None)
    _judge_rows(rows, measures)
    return {**doc, "criteria": CRITERIA, "summary": _summary(rows), "steps": rows}


def join(doc: dict[str, Any], actions: dict[str, dict[str, Any]]) -> list[str]:
    """Put each action's probe rows on its record (``probe``, with
    ``probedOn`` when ``doc`` was carried forward from an earlier version);
    problems."""
    problems = []
    rows: dict[str, list[dict[str, Any]]] = {}
    for r in doc.get("steps") or []:
        if r.get("action") and not r.get("control"):
            rows.setdefault(r["action"], []).append(r)
    for name, rs in sorted(rows.items()):
        if name not in actions:
            problems.append(
                f"actions probe {doc.get('plan')}: action {name} is no longer extracted"
            )
            continue
        out = []
        for r in rs:
            e: dict[str, Any] = {
                "context": r["context"],
                "category": r["category"],
                "casings": r["casings"],
                "id": r["id"],
                "status": r["status"],
            }
            if r["status"] == "done":
                if r.get("accepted") is not None:
                    e["accepted"] = r["accepted"]
                if r.get("hasTaskAfter") is not None:
                    e["hasTaskAfter"] = r["hasTaskAfter"]
                observed = (r.get("effect") or {}).get("observed")
                if observed is not None:
                    e["effectObserved"] = observed
                e["logLines"] = len(r["logLines"]) + r.get("logLinesDropped", 0)
            out.append(e)
        actions[name]["probe"] = out
        if PROBED_ON in doc:
            actions[name][PROBED_ON] = doc[PROBED_ON]
    return problems


# ---------------------------------------------------------------------------
# Probes and cache
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Probe:
    """One probe plan and where its runs live: ``cache`` (document, logs,
    markers), the run dir beside it (plan and lib hook files), the reference
    data's ``file``, ``out_rel`` (the hook's progress and done marker under the
    profile) and the mission file, all named after ``stem``; ``make_plan``
    builds its plan from the actions and options records; ``libs`` are
    appended to the lib in the run dir."""

    name: str
    flag: str
    stem: str
    format: str
    make_plan: Callable[..., dict[str, Any]]
    cache: Path
    libs: tuple[Path, ...] = ()

    @property
    def run_dir(self) -> Path:
        return self.cache.with_name(f"{self.cache.name}-run")

    @property
    def file(self) -> str:
        return f"{self.stem}.json"

    @property
    def out_rel(self) -> str:
        return f"DCS.Lua.Exporter/{self.stem}"

    @property
    def store(self) -> ProbeCache:
        return ProbeCache(
            self.cache, self.file, self.name, "actions, overlays or probe hooks"
        )

    def plan(
        self,
        actions: dict[str, dict[str, Any]],
        options: dict[str, dict[str, Any]],
        version: str,
    ) -> dict[str, Any]:
        return self.make_plan(actions, options, version)

    def lib_lua(self) -> str:
        """The hook file ``actions-probe-lib.lua`` of a run: the lib, with
        ``libs`` appended (as ``local M = (function(...) <lib> end)(...)``)."""
        base = LIB.read_text(encoding="utf-8")
        if not self.libs:
            return base
        return (
            "local M = (function(...)\n"
            + base
            + "\nend)(...)\n"
            + "".join(p.read_text(encoding="utf-8") for p in self.libs)
        )

    def load(
        self, version: str, data_root: Path | None = None
    ) -> dict[str, Any] | None:
        """This version's document: the cached one, else ``api/<file>`` of
        ``<data_root>/latest``, carried forward when ``latest`` is older
        (``version_probe``)."""
        doc = self.store.load(version)
        if doc is None and data_root is not None:
            doc = version_probe(data_root, version, self.file)
        return doc


MAIN = Probe(
    "actions probe",
    "--actions-probe",
    "actions-probe",
    FORMAT,
    plan,
    cache=CACHE_DIR / "actions-probe",
)
FOLLOWUP = Probe(
    "actions probe follow-up",
    "--actions-probe-followup",
    "actions-probe-followup",
    "dcs-actions-probe-followup/1",
    followup_plan,
    cache=CACHE_DIR / "actions-probe-followup",
    libs=(FOLLOWUP_LIB,),
)


def probe_for(doc: dict[str, Any]) -> Probe:
    return FOLLOWUP if doc.get("format") == FOLLOWUP.format else MAIN


def cached_logs(cache: Path) -> list[str]:
    d = cache / LOGS
    if not d.is_dir():
        return []
    return [
        p.read_text(encoding="utf-8", errors="replace") for p in sorted(d.glob("*.log"))
    ]


def install(doc: dict[str, Any], data_root: Path = REFERENCE_DATA_DIR) -> Path | None:
    """Put ``doc`` in ``latest`` as its probe's ``api/<file>`` when ``latest``
    is its DCS version (``install_probe``)."""
    return install_probe(doc, probe_for(doc).file, data_root)


def rescore_cached(
    probe: Probe = MAIN, data_root: Path = REFERENCE_DATA_DIR
) -> dict[str, Any]:
    """Re-score ``probe``'s cached document (``rescore``), cache and install it."""
    store = probe.store
    version = store.cached_version()
    if version is None:
        fail(f"no cached {probe.name} in {store.dir}")
    old = load_json(store.dir / store.file)
    doc = rescore(old, spec(old["dcsVersion"])["measures"])
    store.write(doc, old["dcsVersion"], doc["plan"])
    print(f"Re-scored {store.dir / store.file}")
    latest = install(doc, data_root)
    if latest:
        print(f"Installed {latest / API_DIR / probe.file}")
    return doc


def print_stats(doc: dict[str, Any]) -> None:
    print(
        f"  {probe_for(doc).name} steps: {doc['stats']['status']} "
        f"(complete: {doc['stats']['complete']})"
    )
    for kind, contexts in doc["summary"]["byContext"].items():
        for context, labels in contexts.items():
            parts = "; ".join(
                f"{lb} {v.get('accepted', 0)}/{v.get('steps', 0)} accepted, "
                f"{v.get('hasTaskAfter', 0)} hasTask, {v.get('effectObserved', 0)} effect, "
                f"{v.get('withLogLines', 0)} logged"
                for lb, v in labels.items()
            )
            print(f"  {kind:<12} {context:<13} {parts}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main_rescore(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Re-score the cached actions probe document, cache and install it"
    )
    parser.add_argument("--followup", action="store_true", help="the follow-up's")
    args = parser.parse_args(argv)
    print_stats(rescore_cached(FOLLOWUP if args.followup else MAIN))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["rescore"]:
        return main_rescore(argv[1:])
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--followup", action="store_true", help="the follow-up plan")
    parser.add_argument("--data-dir", type=Path, default=REFERENCE_DATA_DIR / LATEST)
    parser.add_argument("--plan-out", type=Path, help="also write the plan hook file")
    parser.add_argument("--plan-json", type=Path, help="also write the plan as JSON")
    args = parser.parse_args(argv)
    version = load_json(args.data_dir / "manifest.json")["dcsVersion"]
    probe = FOLLOWUP if args.followup else MAIN
    p = probe.plan(
        load_series(args.data_dir, "actions", required=True),
        load_series(args.data_dir, "options", required=True),
        version,
    )
    for line in summary(p):
        print(line)
    if args.plan_out:
        args.plan_out.parent.mkdir(parents=True, exist_ok=True)
        args.plan_out.write_text(plan_lua(p, probe.out_rel), encoding="utf-8")
        print(f"Wrote {args.plan_out}")
    if args.plan_json:
        body = {k: v for k, v in p.items() if k not in ("extra", "objects")}
        args.plan_json.write_text(json_text(body), encoding="utf-8")
        print(f"Wrote {args.plan_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
