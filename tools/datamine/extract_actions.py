"""The ``actions`` and ``options`` series: every AI task, en-route task,
command and option the Mission Editor defines, from the install's
``MissionEditor/modules``.

``me-action-db.lua`` loads ``me_action_db.lua`` and ``me_staticAction_db.lua``
under ``lua5.1`` with minimal stubs (documented there; ``db.Formations`` comes
from the ``_G`` dump) and prints their tables as data. ``action_sources``
reads what loading cannot show from the source text, and the task and
command tables DCS's own scripts (``Scripts/``, ``CoreMods/``, ``Mods/``)
pass to a controller (``script_sources``), and ``mission_corpus`` what DCS's own missions use.

``actions`` (``Entity.Action``), one record per Mission Editor ``ActionId``,
plus one per command only DCS's scripts send (id its DCS id, no
``displayName`` or ``defaultParams``, ``modules`` and ``availableFor``
empty, ``wrapped`` false):

* ``id`` the ``ActionId`` name; ``kind`` task, enrouteTask, command or option
  (``ActionType``); ``module`` the Mission Editor file that defines it.
* ``dcsId`` the task id DCS takes (a command's or option's
  ``WrappedAction`` inner id, as the Mission Editor writes it); ``key`` the
  Mission Editor's variant key of a shared ``dcsId`` (``CAP`` ...);
  ``wrapped`` whether the Mission Editor stores it in a ``WrappedAction``;
  ``option`` / ``optionName`` an option's ``OptionName`` and number.
* ``displayName``, ``description``: the Mission Editor's untranslated text.
* ``defaultParams``: the params of the default task the Mission Editor
  creates (keys it declares ``nil`` are absent there).
* ``params``: every parameter name seen, with ``seenIn`` (``default``,
  ``declared``: a ``key = nil`` in its ``actionsData`` entry, ``makeParams``:
  keys its ``makeParams`` returns, ``panel``: ``actionParams.<key>`` in its
  parameter panels, ``scripts``: a DCS script's table, ``missions``: install
  missions; empty for one ``overlays.yaml`` adds, stamped ``_source``
  hand-authored), ``types`` (Lua types of the default, script literal and
  mission values), ``missionCount`` and ``missionStrings``
  (its string values in install missions, when at most
  ``MAX_MISSION_STRINGS`` distinct).
* ``capability``: its Mission Editor capability check (``rule``: the
  function's name when it has one; ``attributes`` and ``messages`` in it);
  ``makeParams``: the name of its ``makeParams`` function.
* ``scripts``: the DCS scripts sending it (``file``, ``call``: setCommand,
  setTask or pushTask, ``function``: the named function calling).
* ``availableFor``: ``{category, groupTask}`` pairs of ``availableActions``
  (``static`` for ``me_staticAction_db``); ``edPublicHidden`` marks a pair
  the file drops when ``ED_PUBLIC_AVAILABLE`` is set.
* ``missions``: ``count``, ``categories`` and ``contexts`` in install missions.
* ``maneuvers`` (aerobatics): ``AerobaticsManeuversData``.
* ``probe`` (``actions_probe``): what the live actions probe of this DCS
  version recorded per context and id casing; ``probedOn``: the earlier DCS
  version it ran on when this version has no probe of its own.

``options`` (``Entity.ActionOption``), one record per ``OptionName``: ``id``,
``value`` (the number ``setOption`` takes), ``actions``, ``categories``,
``valueSets`` (``optionValues``: per set of categories the allowed ``values``
with their display names, ``default``, ``min``/``max`` and ``units``) and
``missionValues``.

    uv run python -m tools.datamine.extract_actions [--install-dir DIR] [--g-dir DIR] [--json]

prints the counts and problems of an extraction without writing anything
(``--json``: the records).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast

from tools.package.lua_data import lua_inline

from . import mission_corpus
from .action_sources import (
    ModuleSource,
    ScriptAction,
    declared,
    function_ranges,
    panel_params,
    script_actions,
)
from .common import (
    CACHE_DIR,
    CACHED_G_DIR,
    fail,
    install_version,
    json_text,
    read_text,
    to_wsl_path,
    walk_lua,
    warn,
)
from .extract_db_tables import read_formations
from .lua_reader import (
    LuaReader,
    as_dict,
    as_number,
    as_string,
    key_str,
    lua_to_py,
    sandbox_exec,
)

HERE = Path(__file__).resolve().parent
LOADER = HERE / "me-action-db.lua"
HOOK_DIR = HERE / "hook"
ME_DIR = Path("MissionEditor") / "modules"
ACTION_DB = "me_action_db.lua"
STATIC_DB = "me_staticAction_db.lua"
EDIT_PANEL = "me_action_edit_panel.lua"
PARAM_PANELS = "me_action_param_panels.lua"
# The install dirs whose Lua files ``script_sources`` scans, in this order.
SCRIPT_DIRS = ("Scripts", "CoreMods", "Mods")
# The action kinds a script's controller call can send.
SCRIPT_CALL_KINDS = {
    "setCommand": ("command",),
    "setTask": ("task", "enrouteTask"),
    "pushTask": ("task", "enrouteTask"),
}
KINDS = {
    "TASK": "task",
    "ENROUTE_TASK": "enrouteTask",
    "COMMAND": "command",
    "OPTION": "option",
}
CATEGORIES = ("plane", "helicopter", "vehicle", "ship", "static")
STATIC = "static"
CORPUS_CACHE = CACHE_DIR / "mission-corpus.json"
SERIES_NAMES = ("actions", "options")
# A parameter's install mission string values are listed up to this many
# distinct ones (more: free text such as names).
MAX_MISSION_STRINGS = 12


def lua51() -> str:
    lua = shutil.which("lua5.1")
    if lua is None:
        fail(
            "lua5.1 not found: the actions extraction loads the Mission Editor's tables with it"
        )
    return lua


def formations_chunk(formations: list[tuple[Path, Any]], g_dir: Path) -> str:
    """``db.Formations`` of the ``_G`` dump (``read_formations``) as the
    loader's stdin: per table its list of ``{WorldID, Name}`` in ``WorldID``
    order."""
    root = g_dir / "db" / "Formations"
    groups: dict[str, list[dict[str, Any]]] = {}
    for path, raw in formations:
        rec = raw if isinstance(raw, dict) else {}
        wid, name = as_number(rec.get("WorldID")), as_string(rec.get("Name"))
        if wid is None or name is None:
            fail(f"formation {path} without WorldID/Name")
        groups.setdefault(path.relative_to(root).parts[0], []).append(
            {"WorldID": int(wid), "Name": name}
        )
    table = {
        g: {"list": sorted(items, key=lambda f: f["WorldID"])}
        for g, items in groups.items()
    }
    return "return " + lua_inline(table) + "\n"


def load_db(modules_dir: Path, formations: str) -> dict[str, Any]:
    """The loader's tables for the Mission Editor modules in ``modules_dir``."""
    for name in (ACTION_DB, STATIC_DB):
        if not (modules_dir / name).is_file():
            fail(f"no {name} in {modules_dir}")
    proc = subprocess.run(
        [lua51(), str(LOADER), str(modules_dir), str(HOOK_DIR)],
        input=formations,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if proc.returncode:
        fail(f"me-action-db.lua failed: {proc.stderr.strip()}")
    ok, env = sandbox_exec(proc.stdout, "me-action-db")
    if not ok:
        fail(f"me-action-db.lua output does not load: {env}")
    result = lua_to_py(env["result"])
    if not isinstance(result, dict):
        fail("me-action-db.lua printed no result table")
    return result


def _corpus_fingerprint(install_dir: Path) -> str:
    """The corpus cache key: the scanner, the install's DCS version and its
    module folders (``Mods/<kind>/<module>``, ``CoreMods/<module>``): listing
    every mission file takes minutes on a Windows drive under WSL."""
    h = hashlib.sha256(f"{mission_corpus.FORMAT}\0{mission_corpus.WALKER}".encode())
    h.update(f"{install_version(install_dir)}\0".encode())
    for top, depth in (("Mods", 2), ("CoreMods", 1)):
        level = [install_dir / top]
        for _ in range(depth):
            level = sorted(
                (p for d in level if d.is_dir() for p in d.iterdir() if p.is_dir()),
                key=lambda p: str(p).lower(),
            )
        for p in level:
            h.update(f"{p.relative_to(install_dir).as_posix()}\0".encode())
    return h.hexdigest()


def _corpus_json(c: mission_corpus.Corpus) -> dict[str, Any]:
    return {
        "files": c.files,
        "failed": [list(f) for f in c.failed],
        "actions": {
            k: {
                "count": a["count"],
                "categories": dict(sorted(a["categories"].items())),
                "contexts": dict(sorted(a["contexts"].items())),
                "params": {
                    n: dict(sorted(t.items())) for n, t in sorted(a["params"].items())
                },
                "strings": {
                    n: dict(sorted(t.items())) for n, t in sorted(a["strings"].items())
                },
            }
            for k, a in sorted(c.actions.items())
        },
        "optionValues": {
            k: dict(sorted(v.items())) for k, v in sorted(c.option_values.items())
        },
        "keyed": dict(sorted(c.keyed.items())),
    }


def _corpus_from_json(d: dict[str, Any]) -> mission_corpus.Corpus:
    c = mission_corpus.Corpus(files=d["files"], failed=[tuple(f) for f in d["failed"]])
    c.add(
        {
            "actions": d["actions"],
            "optionValues": d["optionValues"],
            "keyed": d["keyed"],
        }
    )
    return c


def corpus(
    install_dir: Path, cache: Path | None = CORPUS_CACHE
) -> mission_corpus.Corpus:
    """The install missions' counts; reused from ``cache`` while the
    scanner, the DCS version and the installed modules are the same."""
    fingerprint = _corpus_fingerprint(install_dir)
    if cache is not None and cache.is_file():
        cached = json.loads(read_text(cache))
        if cached.get("fingerprint") == fingerprint:
            return _corpus_from_json(cached["corpus"])
    print("Scanning the install missions for AI actions ...", file=sys.stderr)
    c = mission_corpus.scan(install_dir)
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(
            json_text({"fingerprint": fingerprint, "corpus": _corpus_json(c)}),
            encoding="utf-8",
        )
    return c


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


def _lua_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    return "table"


def _category_order(c: str) -> tuple[int, str]:
    return (CATEGORIES.index(c) if c in CATEGORIES else len(CATEGORIES), c)


def action_key(rec: dict[str, Any]) -> str:
    """The Mission Editor's ``getActionKey`` of an action record, as
    ``mission_corpus`` keys it."""
    if rec["kind"] == "option":
        return f"Option:{key_str(rec['optionName'])}"
    return cast(str, rec.get("key") or rec["dcsId"])


def _available(db: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """``{ActionId name: [{category, groupTask, edPublicHidden?}]}``."""

    def pairs(table: dict[str, Any]) -> set[tuple[str, str, str]]:
        out: set[tuple[str, str, str]] = set()
        for cat, by_kind in as_dict(table).items():
            for by_task in as_dict(by_kind).values():
                for task, entry in as_dict(by_task).items():
                    for name in as_dict(entry).get("names") or []:
                        out.add((name, cat, task))
        return out

    private, public = (
        pairs(db["availableActions"]),
        pairs(db["availableActionsEdPublic"]),
    )
    if public - private:
        fail(f"entries only with ED_PUBLIC_AVAILABLE: {sorted(public - private)}")
    out: dict[str, list[dict[str, Any]]] = {}
    for name, cat, task in sorted(
        private, key=lambda t: (t[0], _category_order(t[1]), t[2])
    ):
        entry: dict[str, Any] = {"category": cat, "groupTask": task}
        if (name, cat, task) not in public:
            entry["edPublicHidden"] = True
        out.setdefault(name, []).append(entry)
    return out


def _holes(db: dict[str, Any], text: str) -> list[str]:
    undefined = sorted(
        set(re.findall(r"\bActionId\.(\w+)", text)) - set(db["actionIds"])
    )
    out = []
    for cat, by_kind in as_dict(db["availableActions"]).items():
        for kind, by_task in as_dict(by_kind).items():
            for task, entry in as_dict(by_task).items():
                if as_dict(entry).get("holes"):
                    out.append(
                        f"availableActions {cat}/{kind}/{task} lists {entry['holes']} "
                        "ActionId(s) me_action_db.lua does not define (nil; the file "
                        f"references undefined {', '.join(undefined) or '(none found)'})"
                    )
    return out


def _function(fn: Any) -> tuple[str | None, int, int] | None:
    f = as_dict(fn)
    if "line" not in f:
        return None
    return as_string(f.get("name")), int(f["line"]), int(f["lastLine"])


def _params(
    defaults: dict[str, Any],
    extra: dict[str, list[str]],
    missions: dict[str, Any] | None,
    scripts: dict[str, set[str]] | None = None,
) -> list[dict[str, Any]]:
    names: dict[str, dict[str, Any]] = {}

    def entry(name: str) -> dict[str, Any]:
        return names.setdefault(name, {"name": name, "seenIn": [], "types": set()})

    for k, v in defaults.items():
        e = entry(k)
        e["seenIn"].append("default")
        e["types"].add(_lua_type(v))
    for source in ("declared", "makeParams", "panel"):
        for k in extra.get(source, []):
            entry(k)["seenIn"].append(source)
    for k, types in sorted((scripts or {}).items()):
        e = entry(k)
        e["seenIn"].append("scripts")
        e["types"] |= types
    strings = as_dict(missions and missions.get("strings"))
    for k, types in sorted(as_dict(missions and missions.get("params")).items()):
        e = entry(k)
        e["seenIn"].append("missions")
        e["types"] |= set(types)
        e["missionCount"] = sum(types.values())
        values = strings.get(k) or {}
        if 0 < len(values) <= MAX_MISSION_STRINGS:
            e["missionStrings"] = [
                {"value": v, "count": n}
                for v, n in sorted(values.items(), key=lambda kv: (-kv[1], kv[0]))
            ]
    out = []
    for name in sorted(names):
        e = names[name]
        e["types"] = sorted(e["types"])
        out.append(e)
    return out


def _missions(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    if not entry:
        return None
    return {
        "count": entry["count"],
        "categories": sorted(entry["categories"], key=_category_order),
        "contexts": dict(sorted(entry["contexts"].items())),
    }


def _maneuvers(raw: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for mid, m in sorted(as_dict(raw).items()):
        params = [
            {"name": n, **dict(sorted(as_dict(p).items()))}
            for n, p in sorted(as_dict(m.get("param")).items())
        ]
        rec: dict[str, Any] = {"id": mid, "displayName": m.get("displayName")}
        if m.get("desc"):
            rec["description"] = m["desc"]
        rec["params"] = params
        out.append(rec)
    return out


def _join_scripts(
    records: dict[str, dict[str, Any]], scripts: dict[str, list[ScriptAction]]
) -> dict[str, dict[str, set[str]]]:
    """Put each script use (``script_sources``) on the records of its
    ``dcsId`` and kind (``SCRIPT_CALL_KINDS``) as ``scripts``; a command no
    Mission Editor action has becomes a record of its own (id the DCS id),
    a task none has is an error (its kind is unknown). ``{record id: {param
    name: Lua types}}`` of the scripts' params."""
    params: dict[str, dict[str, set[str]]] = {}
    for file, uses in sorted(scripts.items()):
        for u in uses:
            kinds = SCRIPT_CALL_KINDS[u.call]
            hits = [
                r
                for r in records.values()
                if r["dcsId"] == u.dcs_id and r["kind"] in kinds
            ]
            if not hits:
                if "command" not in kinds:
                    fail(
                        f"{file}: {u.call} of {u.dcs_id!r}, which no Mission Editor "
                        "task or en-route task has (its kind is unknown)"
                    )
                if u.dcs_id in records:
                    fail(f"{file}: command {u.dcs_id!r} is a Mission Editor ActionId")
                records[u.dcs_id] = {
                    "id": u.dcs_id,
                    "kind": "command",
                    "modules": [],
                    "dcsId": u.dcs_id,
                    "wrapped": False,
                    "availableFor": [],
                    "_extra": {},
                }
                hits = [records[u.dcs_id]]
            use = {"file": file, "call": u.call}
            if u.function:
                use["function"] = u.function
            for r in hits:
                if use not in r.setdefault("scripts", []):
                    r["scripts"].append(use)
                p = params.setdefault(r["id"], {})
                for name, types in u.params.items():
                    p.setdefault(name, set()).update(types)
    return params


def build_actions(
    db: dict[str, Any],
    texts: dict[str, str],
    panels: dict[str, list[str]],
    corpus: mission_corpus.Corpus | None,
    scripts: dict[str, list[ScriptAction]] | None = None,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """The ``actions`` records and problems; ``scripts``: the install's
    script uses (``script_sources``)."""
    problems = _holes(db, texts[ACTION_DB])
    kind_of = {n: KINDS[name] for name, n in db["actionTypes"].items()}
    option_names = {int(v): k for k, v in db["optionNames"].items()}
    main_src = ModuleSource(
        texts[ACTION_DB],
        {
            k: (int(v["line"]), int(v["lastLine"]))
            for k, v in as_dict(db.get("functions")).items()
        },
    )
    static_src = ModuleSource(texts[STATIC_DB])
    nil_keys = declared(texts[ACTION_DB])
    available = _available(db)
    records: dict[str, dict[str, Any]] = {}

    def one(
        name: str, a: dict[str, Any], module: str, src: ModuleSource
    ) -> dict[str, Any]:
        task = as_dict(a.get("task"))
        wrapped = task.get("id") == "WrappedAction"
        inner = as_dict(as_dict(task.get("params")).get("action")) if wrapped else task
        dcs_id = as_string(inner.get("id"))
        if dcs_id is None:
            fail(f"{module} action {name} has no task id")
        params = as_dict(inner.get("params"))
        rec: dict[str, Any] = {
            "id": name,
            "kind": kind_of[a["type"]],
            "modules": [module.removesuffix(".lua")],
            "dcsId": dcs_id,
            "wrapped": wrapped,
            "displayName": a.get("displayName"),
        }
        if task.get("key") is not None:
            rec["key"] = task["key"]
        if a.get("desc"):
            rec["description"] = a["desc"]
        if rec["kind"] == "option":
            number = as_number(params.get("name"))
            if number is None:
                fail(f"option action {name} has no numeric params.name")
            rec["optionName"] = int(number)
            if int(number) in option_names:
                rec["option"] = option_names[int(number)]
            elif int(number) != -1:
                problems.append(
                    f"option action {name}: OptionName {number} has no name"
                )
        rec["defaultParams"] = params
        extra: dict[str, list[str]] = {}
        if module == ACTION_DB:
            extra["declared"] = nil_keys.get(name, [])
            extra["panel"] = panels.get(name, [])
        cap_fn = a.get("verifyGroupCapability") or a.get("verifyUnitCapability")
        if (f := _function(cap_fn)) is not None:
            rule, first, last = f
            attributes, messages = src.capability(first, last)
            cap: dict[str, Any] = {"rule": rule} if rule else {}
            if attributes:
                cap["attributes"] = attributes
            if messages:
                cap["messages"] = messages
            rec["capability"] = cap
        if (f := _function(a.get("makeParams"))) is not None:
            rule, first, last = f
            extra["makeParams"] = src.returned(first, last)
            rec["makeParams"] = {"rule": rule} if rule else {}
        rec["_extra"] = extra
        return rec

    for name, a in sorted(as_dict(db["actions"]).items()):
        rec = one(name, a, ACTION_DB, main_src)
        rec["availableFor"] = available.get(name, [])
        records[name] = rec
    static = as_dict(db.get("static"))
    for name, a in sorted(as_dict(static.get("actions")).items()):
        rec = one(name, a, STATIC_DB, static_src)
        in_static = [
            {"category": STATIC, "groupTask": task}
            for task, entry in sorted(as_dict(static.get("availableActions")).items())
            if name in (as_dict(entry).get("names") or [])
        ]
        if name in records:
            same = records[name]
            if (same["dcsId"], same["defaultParams"]) != (
                rec["dcsId"],
                rec["defaultParams"],
            ):
                fail(f"{name} differs between {ACTION_DB} and {STATIC_DB}")
            same["availableFor"] += in_static
            same["modules"] += rec["modules"]
            continue
        rec["availableFor"] = in_static
        records[name] = rec

    script_params = _join_scripts(records, scripts or {})
    counts = corpus.actions if corpus else {}
    seen_keys: set[str] = set()
    for name, rec in records.items():
        key = action_key(rec)
        seen_keys.add(key)
        m = counts.get(key)
        extra = rec.pop("_extra")
        rec["params"] = _params(
            rec.get("defaultParams") or {}, extra, m, script_params.get(name)
        )
        if (missions := _missions(m)) is not None:
            rec["missions"] = missions
        if name == "AEROBATICS":
            rec["maneuvers"] = _maneuvers(db.get("aerobatics") or {})
        if rec["modules"] and not rec["availableFor"]:
            problems.append(f"action {name} is in no availableActions list")
    for key in sorted(set(counts) - seen_keys):
        problems.append(
            f"install missions use action key {key!r} ({counts[key]['count']}x) "
            "that no Mission Editor action has"
        )
    return {k: _order(v) for k, v in sorted(records.items())}, problems


_FIELD_ORDER = (
    "id", "kind", "modules", "dcsId", "key", "wrapped", "option", "optionName",
    "displayName", "description", "defaultParams", "params", "capability",
    "makeParams", "scripts", "availableFor", "missions", "maneuvers", "probe",
    "probedOn",
)  # fmt: skip


def _order(rec: dict[str, Any]) -> dict[str, Any]:
    unknown = set(rec) - set(_FIELD_ORDER)
    if unknown:
        fail(f"action record fields without an order: {sorted(unknown)}")
    return {k: rec[k] for k in _FIELD_ORDER if k in rec}


def _value_set(raw: dict[str, Any], names: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(raw.get("list"), list) and raw["list"]:
        out["values"] = [
            {
                "value": v,
                **({"name": names[key_str(v)]} if key_str(v) in names else {}),
            }
            for v in raw["list"]
        ]
    for k in ("default", "min", "max"):
        if k in raw:
            out[k] = raw[k]
    units = as_dict(raw.get("units")).get("unitsTable")
    if units:
        out["units"] = units
    if raw.get("DisplayNameValue"):
        out["displayName"] = raw["DisplayNameValue"]
    return out


_SET_KEYS = {"list", "default", "min", "max", "units", "DisplayNameValue"}


def build_options(
    db: dict[str, Any],
    actions: dict[str, dict[str, Any]],
    corpus: mission_corpus.Corpus | None,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    problems: list[str] = []
    values = as_dict(db.get("optionValues"))
    display = as_dict(db.get("optionValueDisplayName"))
    out: dict[str, dict[str, Any]] = {}
    for name, number in sorted(db["optionNames"].items(), key=lambda kv: kv[1]):
        key = key_str(number)
        raw = as_dict(values.get(key))
        names = as_dict(display.get(key))
        rec: dict[str, Any] = {"id": name, "value": number}
        acts = sorted(
            a["id"] for a in actions.values() if a.get("optionName") == number
        )
        rec["actions"] = acts
        cats = {e["category"] for a in acts for e in actions[a]["availableFor"]}
        rec["categories"] = sorted(cats, key=_category_order)
        sets: list[dict[str, Any]] = []
        if raw and set(raw) <= _SET_KEYS:
            sets.append(_value_set(raw, names))
        elif raw:
            by_content: dict[str, list[str]] = {}
            rendered: dict[str, dict[str, Any]] = {}
            for cat, sub in sorted(raw.items(), key=lambda kv: _category_order(kv[0])):
                vs = _value_set(as_dict(sub), names)
                text = json.dumps(vs, sort_keys=True)
                by_content.setdefault(text, []).append(cat)
                rendered[text] = vs
            for text, cs in by_content.items():
                sets.append({"categories": cs, **rendered[text]})
        if sets:
            rec["valueSets"] = sets
        if name == "FORMATION":
            for s in sets:
                if "default" not in s:
                    problems.append(
                        f"option FORMATION {'/'.join(s.get('categories', []))}: no "
                        "default (db.Formations.<table>.default is not in the _G dump)"
                    )
        used = (corpus.option_values if corpus else {}).get(f"Option:{key}")
        if used:
            rec["missionValues"] = [
                {**({} if _typed(v) is None else {"value": _typed(v)}), "count": n}
                for v, n in sorted(used.items(), key=lambda kv: (-kv[1], kv[0]))
            ]
        if not acts:
            problems.append(f"option {name} ({number}) has no Mission Editor action")
        out[name] = rec
    return out, problems


def _typed(text: str) -> Any:
    kind, _, value = text.partition(":")
    if kind == "number":
        n = float(value)
        return int(n) if n.is_integer() else n
    if kind == "boolean":
        return value == "true"
    if kind == "nil":
        return None
    return value


def _null(v: Any, path: str = "") -> str | None:
    """The path of the first None in ``v``, or None."""
    if v is None:
        return path
    items = (
        v.items()
        if isinstance(v, dict)
        else enumerate(v)
        if isinstance(v, list)
        else ()
    )
    for k, x in items:
        if (found := _null(x, f"{path}.{k}" if path else str(k))) is not None:
            return found
    return None


def sources(install_dir: Path) -> tuple[dict[str, str], dict[str, list[str]]]:
    """The module texts and the parameter panels' params."""
    d = install_dir / ME_DIR
    texts = {
        n: read_text(d / n) for n in (ACTION_DB, STATIC_DB, EDIT_PANEL, PARAM_PANELS)
    }
    panels = panel_params(
        texts[EDIT_PANEL],
        function_ranges(d / EDIT_PANEL),
        texts[PARAM_PANELS],
        function_ranges(d / PARAM_PANELS),
    )
    return texts, panels


def script_sources(install_dir: Path) -> dict[str, list[ScriptAction]]:
    """``{file: script uses}`` of the install's Lua files (``SCRIPT_DIRS``)
    that pass task or command tables to a controller (``script_actions``),
    by path relative to the install."""
    roots = [install_dir / d for d in SCRIPT_DIRS]
    if missing := [r.name for r in roots if not r.is_dir()]:
        fail(f"no {', '.join(missing)} in {install_dir}")
    out: dict[str, list[ScriptAction]] = {}
    for path in (p for root in roots for p in walk_lua(root)):
        text = read_text(path)
        if not any(call in text for call in SCRIPT_CALL_KINDS):
            continue
        uses = script_actions(text, function_ranges(path))
        if uses:
            out[path.relative_to(install_dir).as_posix()] = uses
    return out


def build(
    install_dir: Path,
    g_dir: Path,
    reader: LuaReader | None = None,
    corpus_cache: Path | None = CORPUS_CACHE,
    formations: list[tuple[Path, Any]] | None = None,
) -> tuple[dict[str, dict[str, dict[str, Any]]], list[str]]:
    """``({"actions": records, "options": records}, report lines)``;
    ``formations``: ``read_formations`` of ``g_dir``, when already read."""
    if formations is None:
        formations = read_formations(reader or LuaReader(g_dir), g_dir)
    chunk = formations_chunk(formations, g_dir)
    with ThreadPoolExecutor(max_workers=4) as pool:
        db_job = pool.submit(load_db, install_dir / ME_DIR, chunk)
        sources_job = pool.submit(sources, install_dir)
        scripts_job = pool.submit(script_sources, install_dir)
        missions_job = pool.submit(corpus, install_dir, corpus_cache)
        db, (texts, panels) = db_job.result(), sources_job.result()
        scripts, missions = scripts_job.result(), missions_job.result()
    actions, problems = build_actions(db, texts, panels, missions, scripts)
    options, option_problems = build_options(db, actions, missions)
    problems += option_problems
    for name, records in (("actions", actions), ("options", options)):
        for rid, rec in records.items():
            if (where := _null(rec)) is not None:
                fail(
                    f"{name}/{rid}: null at {where or '(record)'} (Lua cannot hold it)"
                )
    for p, why in missions.failed:
        problems.append(f"install mission {p} not scanned: {why}")
    kinds = Counter(a["kind"] for a in actions.values())
    report = [
        f"Mission Editor actions: {dict(sorted(kinds.items()))}; options: {len(options)}; "
        f"install missions scanned: {missions.files}",
        *(f"problem: {p}" for p in problems),
    ]
    return {"actions": actions, "options": options}, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--install-dir", default=os.environ.get("DCS_INSTALL_DIR"))
    parser.add_argument("--g-dir", type=Path, default=CACHED_G_DIR)
    parser.add_argument("--json", action="store_true", help="print the records")
    args = parser.parse_args(argv)
    if not args.install_dir:
        parser.error("--install-dir (or DCS_INSTALL_DIR) is required")
    series, report = build(to_wsl_path(args.install_dir), args.g_dir)
    for line in report:
        if line.startswith("problem:"):
            warn(line.removeprefix("problem: "))
        else:
            print(line, file=sys.stderr if args.json else sys.stdout)
    if args.json:
        sys.stdout.write(json_text(series))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
