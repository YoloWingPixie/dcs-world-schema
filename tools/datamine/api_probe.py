"""Plan, cache and document the Lua API argument probe (``hook/api-probe.lua``,
``hook/probe-call.lua``), which writes ``api/probe.json`` into the reference data.

Plan: every function of the ``scripting``, ``hooks`` and ``export`` API dumps
with its ``_G`` keys, ``what`` (C/Lua), owner ``className`` and name;
``documented`` when the hand-written mission scripting schema gives it a
signature (description without "signature not documented", inherited too);
``context``: ``{position: {kind: value}}`` sample arguments from
``overlays.yaml`` ``probe/contextSamples`` over the probe mission's pools. It
carries ``probe/doNotCall`` (``deny_list``), the mission id and samples, and
``carried``: functions that crashed or hung DCS earlier for this DCS version
(``crashed.json``, reset per version), which are denied too. Order: ``Weapon``
methods first (the hook waits for a shell in flight), undocumented, documented,
then ``destroy*``/``remove*`` (they may remove a sample). Written as
``api-probe-plan.lua``; its ``id`` hashes the plan (not ``carried``) and the
hooks, so progress of another plan is restarted and of this one resumed.

``probe.json`` (``document``, also for partial runs):

* ``format`` ``dcs-api-probe/1``, ``dcsVersion``, ``plan`` id, ``source:
  "probe"`` (observed, kept apart from documented signatures).
* ``samples``: sample setup steps and which samples resolved.
* ``envs``: ``{env: {path: record}}``, the probe-call.lua record or
  ``denied``/``sameAs``/``missing``/``crashed``/``unavailable``/``notRun``,
  plus ``what``, ``owner``, ``documented``, ``source`` and ``conclusive``: the
  call succeeded and every parameter type came from a luaL type error or is a
  ``self`` satisfied by the owner's sample. Carried crashes have
  ``carriedFrom`` (plan id).
* ``stats``: ``complete`` (every entry recorded; a call in flight when DCS died
  is ``crashed`` but not recorded) and ``{env: {status: count}}``.
* ``errorFormats``: each error message template (``'…'``, ``N``, ``(T
  expected, got X)``) with its count.

``refresh.py --probe`` caches a run in ``.datamine/probe`` (``probe.json``,
``inputs``, ``crashed.json``, then ``done`` or ``partial`` holding the DCS
version).

    uv run python -m tools.datamine.api_probe [--api-dir DIR] [--plan-out FILE]

prints what a probe run would call and the unsure do-not-call entries, without DCS.

    uv run python -m tools.datamine.api_probe document --from-progress FILE [--plan FILE]

builds ``probe.json`` offline from a progress file and its plan hook file
(default ``.datamine/probe-run/api-probe-plan.lua``), records its crashes,
caches it and installs it in ``dcs-world-reference/latest/api/`` when
``latest`` is the probe's DCS version.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from tools.merge import merge_tree
from tools.package.lua_data import lua_inline

from . import overlays as overlays_mod
from . import probe_mission
from .api_dump import _key_text
from .api_dump import load as load_dump
from .common import (
    API_DIR,
    CACHE_DIR,
    HOOK_DIR,
    LATEST,
    REFERENCE_DATA_DIR,
    REPO_ROOT,
    ProbeCache,
    fail,
    glob_re,
    hooks_hash,
    install_probe,
    json_text,
    load_plan_lua,
    progress_lines,
    read_progress,
    warn,
)

PROBE_HOOKS = [HOOK_DIR / "api-probe.lua", HOOK_DIR / "probe-call.lua"]
PLAN_NAME = "api-probe-plan.lua"
PLAN_FILE = CACHE_DIR / "probe-run" / PLAN_NAME
PROBE_REL = "DCS.Lua.Exporter/probe"
PROGRESS = "progress.tsv"
DONE = "done"
PROBE_FILE = "probe.json"
CRASHED = "crashed.json"
CACHED_PROBE_DIR = CACHE_DIR / "probe"
CACHE = ProbeCache(
    CACHED_PROBE_DIR,
    PROBE_FILE,
    "probe",
    "probe hooks, overlays or API dump hook",
)
FORMAT = "dcs-api-probe/1"
ENVS = ("scripting", "hooks", "export")
SERIES, TABLE, CONTEXT = "probe", "doNotCall", "contextSamples"
SCHEMA_DIR = REPO_ROOT / "dcs-world-schema"
UNDOCUMENTED = "signature not documented"
POOL_KINDS = {"sides": "number", "countries": "number"}
_LAST = re.compile(r"^(destroy|remove)")
_PLAN_ID = re.compile(r'^\s*id = "(\w+)",$', re.M)
_PLAN_VERSION = re.compile(r'^\s*version = "([^"]+)",$', re.M)
_TEMPLATES = (
    (re.compile(r"\((?:[^()]*) expected, got [^()]*\)"), "(T expected, got X)"),
    (re.compile(r"\((?:[^()]*) expected\)"), "(T expected)"),
    (re.compile(r"'[^']*'"), "'…'"),
    (re.compile(r"\d+(?:\.\d+)?"), "N"),
)


@dataclass(frozen=True)
class Deny:
    pattern: str
    reason: str
    unsure: bool
    envs: tuple[str, ...] | None

    def matches(self, env: str, path: str) -> bool:
        if self.envs is not None and env not in self.envs:
            return False
        return glob_re(self.pattern).fullmatch(path) is not None


def deny_list(version: str | None = None) -> list[Deny]:
    """``overlays.yaml`` ``probe/doNotCall``: ``{pattern: {reason, unsure?,
    envs?}}``, sorted by pattern."""
    table = overlays_mod.load(version).table(SERIES, TABLE)
    if not isinstance(table, dict):
        fail(f"overlays {SERIES}/{TABLE}: a mapping of pattern -> entry")
    out = []
    for pattern, entry in sorted(table.items()):
        where = f"overlays {SERIES}/{TABLE} {pattern!r}"
        if not isinstance(entry, dict) or not str(entry.get("reason") or "").strip():
            fail(f"{where}: needs a reason")
        unknown = set(entry) - {"reason", "unsure", "envs"}
        if unknown:
            fail(f"{where}: unknown keys {sorted(unknown)}")
        envs = entry.get("envs")
        if envs is not None and (
            not isinstance(envs, list) or not set(envs) <= set(ENVS)
        ):
            fail(f"{where}: envs must be a list of {', '.join(ENVS)}")
        if "\t" in pattern or "\n" in pattern:
            fail(f"{where}: a pattern has no tab or newline")
        out.append(
            Deny(
                pattern,
                entry["reason"].strip(),
                bool(entry.get("unsure")),
                tuple(envs) if envs is not None else None,
            )
        )
    return out


@dataclass(frozen=True)
class ContextRule:
    paths: tuple[str, ...]
    pool: str
    position: int
    envs: tuple[str, ...] | None

    def matches(self, env: str, path: str) -> bool:
        if self.envs is not None and env not in self.envs:
            return False
        return any(glob_re(p).fullmatch(path) for p in self.paths)


def context_rules(version: str | None = None) -> list[ContextRule]:
    """``overlays.yaml`` ``probe/contextSamples``: a list of ``{paths, pool,
    position?, envs?}``, in order."""
    table = overlays_mod.load(version).table(SERIES, CONTEXT)
    if not isinstance(table, list):
        fail(f"overlays {SERIES}/{CONTEXT}: a list of rules")
    out = []
    for i, rule in enumerate(table, 1):
        where = f"overlays {SERIES}/{CONTEXT} rule {i}"
        if not isinstance(rule, dict):
            fail(f"{where}: a mapping")
        unknown = set(rule) - {"paths", "pool", "position", "envs"}
        if unknown:
            fail(f"{where}: unknown keys {sorted(unknown)}")
        paths = rule.get("paths")
        if not isinstance(paths, list) or not paths:
            fail(f"{where}: needs a list of paths")
        if rule.get("pool") not in probe_mission.POOLS:
            fail(f"{where}: pool must be one of {', '.join(probe_mission.POOLS)}")
        position = rule.get("position", 1)
        if not isinstance(position, int) or position < 1:
            fail(f"{where}: position is a number from 1")
        envs = rule.get("envs")
        if envs is not None and (
            not isinstance(envs, list) or not set(envs) <= set(ENVS)
        ):
            fail(f"{where}: envs must be a list of {', '.join(ENVS)}")
        out.append(
            ContextRule(
                tuple(paths),
                rule["pool"],
                position,
                tuple(envs) if envs is not None else None,
            )
        )
    return out


def context(
    env: str, path: str, rules: list[ContextRule], pools: dict[str, list[Any]]
) -> dict[int, dict[str, Any]]:
    """``{position: {kind: value}}`` for a function: per position, the first
    value of the pool of the first rule matching it (an empty pool gives
    nothing)."""
    out: dict[int, dict[str, Any]] = {}
    for r in rules:
        if r.position in out or not r.matches(env, path) or not pools.get(r.pool):
            continue
        out[r.position] = {POOL_KINDS.get(r.pool, "string"): pools[r.pool][0]}
    return out


def unused_context(p: dict[str, Any], rules: list[ContextRule]) -> list[str]:
    """Context rule paths that match no function of the plan."""
    return [
        path
        for r in rules
        for path in r.paths
        if not any(
            ContextRule((path,), r.pool, r.position, r.envs).matches(
                e["env"], e["path"]
            )
            for e in p["entries"]
        )
    ]


def _schema_members(node: dict[str, Any], prefix: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for section in ("static", "instance"):
        for name, member in (node.get(section) or {}).items():
            if isinstance(member, dict):
                out[f"{prefix}.{name}"] = member
    for name, member in (node.get("properties") or {}).items():
        if isinstance(member, dict):
            out.update(_schema_members(member, f"{prefix}.{name}"))
    return out


def documented_paths(schema_dir: Path = SCHEMA_DIR) -> set[str]:
    """Mission scripting function paths the hand-written schema documents: a
    member with a description other than "signature not documented", under
    its global and every class that inherits it."""
    merged, _ = merge_tree(str(schema_dir.resolve()))
    globals_ = merged.get("globals") or {}
    own: dict[str, set[str]] = {}
    for name, node in globals_.items():
        if not isinstance(node, dict):
            continue
        own[name] = {
            path[len(name) + 1 :]
            for path, m in _schema_members(node, name).items()
            if UNDOCUMENTED not in str(m.get("description") or "")
        }

    def ancestors(name: str, seen: frozenset[str] = frozenset()) -> list[str]:
        node = globals_.get(name)
        parents = node.get("inherits") if isinstance(node, dict) else None
        out = []
        for parent in parents or []:
            if parent not in seen:
                out += [parent, *ancestors(parent, seen | {name})]
        return out

    paths = set()
    for name in own:
        for source in (name, *ancestors(name)):
            paths |= {f"{name}.{m}" for m in own.get(source, ())}
    return paths


def functions(dump: dict[str, Any]) -> list[dict[str, Any]]:
    """Every function written in a dump's globals (refs are not followed), in
    dump order: ``{env, path, keys, what, owner?, name}``. A key is a string or
    number, or ``{"m": true}`` for a metatable."""
    env = dump["env"]
    out: list[dict[str, Any]] = []

    def visit(node: Any, path: str, keys: list[Any], owner: str | None) -> None:
        if not isinstance(node, dict) or "ref" in node:
            return
        if node.get("type") == "function":
            if "\t" in path or "\n" in path:
                return
            entry = {
                "env": env,
                "path": path,
                "keys": keys,
                "what": node.get("what"),
                "name": str(keys[-1])
                if keys and not isinstance(keys[-1], dict)
                else path,
            }
            if owner:
                entry["owner"] = owner
            out.append(entry)
            return
        cls = node.get("className")
        for m in node.get("members") or []:
            visit(m.get("value"), path + _key_text(m), [*keys, m["key"]], cls)
        visit(node.get("metatable"), path + "<metatable>", [*keys, {"m": True}], None)

    for name, node in sorted((dump.get("globals") or {}).items()):
        visit(node, name, [name], None)
    return out


def _order(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(ie: tuple[int, dict[str, Any]]) -> tuple[int, int]:
        i, e = ie
        if e.get("owner") == "Weapon":
            return (0, i)
        if _LAST.match(e["name"]):
            return (3, i)
        return (2 if e.get("documented") else 1, i)

    return [e for _, e in sorted(enumerate(entries), key=key)]


def inputs_hash(
    deny: list[Deny],
    api_hook_hash: str,
    rules: list[ContextRule] | None = None,
    mission_spec: dict[str, Any] | None = None,
) -> str:
    """What a cached probe was made from: the probe hooks, the deny list, the
    API dump hook (with the DCS version, the dump the plan is built from),
    the context rules and the probe mission's overlay."""
    h = hashlib.sha256()
    h.update(hooks_hash(PROBE_HOOKS).encode())
    h.update(json.dumps([d.__dict__ for d in deny], sort_keys=True).encode())
    h.update(api_hook_hash.encode())
    h.update(json.dumps([r.__dict__ for r in rules or []], sort_keys=True).encode())
    h.update(json.dumps(mission_spec, sort_keys=True).encode())
    return h.hexdigest()


def _deny_entry(d: Deny) -> dict[str, Any]:
    return {"pattern": d.pattern, "reason": d.reason} | (
        {"envs": list(d.envs)} if d.envs is not None else {}
    )


def plan(
    api_dir: Path,
    deny: list[Deny],
    version: str,
    *,
    mission: probe_mission.Mission | None = None,
    rules: list[ContextRule] | None = None,
    documented: set[str] | None = None,
    carried: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """The probe plan of the dumps in ``api_dir`` (hook files or a version
    dir's ``api/``) for the probe ``mission`` (its context ``rules``);
    ``documented``: the scripting paths the schema documents (default
    ``documented_paths()``); ``carried``: ``[{env, path, plan}]`` of
    ``carried_crashes``."""
    if documented is None:
        documented = documented_paths()
    pools = mission.pools if mission else {}
    envs, entries = [], []
    for env in ENVS:
        path = api_dir / f"{env}.json"
        if not path.is_file():
            continue
        dump = load_dump(path)
        if dump.get("status") != "ok":
            continue
        if dump.get("dcsVersion") != version:
            fail(f"{path} is DCS {dump.get('dcsVersion')}, want {version}")
        envs.append(env)
        for e in functions(dump):
            if env == "scripting" and e["path"] in documented:
                e["documented"] = True
            ctx = context(env, e["path"], rules or [], pools)
            if ctx:
                e["context"] = ctx
            entries.append(e)
    if "scripting" not in envs:
        fail(f"no scripting env dump in {api_dir}")
    body = {
        "version": version,
        "envs": envs,
        "deny": [_deny_entry(d) for d in deny],
        "mission": mission.id if mission else None,
        "samples": mission.samples if mission else {},
        "entries": _order(entries),
    }
    h = hashlib.sha256(json.dumps(body, sort_keys=True).encode())
    h.update(hooks_hash(PROBE_HOOKS).encode())
    return {"id": h.hexdigest()[:16], **body, "carried": list(carried or [])}


_CARRIED = "crashed or hung DCS in an earlier probe run (plan {})"
_CARRIED_RE = re.compile(
    re.escape(_CARRIED).replace(re.escape("{}"), r"([^()\s]+)") + "$"
)


def carried_deny(p: dict[str, Any]) -> list[Deny]:
    """The plan's carried functions as deny entries (exact paths)."""
    return [
        Deny(c["path"], _CARRIED.format(c["plan"]), False, (c["env"],))
        for c in p.get("carried") or []
    ]


def plan_lua(p: dict[str, Any]) -> str:
    """The plan as the hook file ``api-probe-plan.lua`` (``return { ... }``;
    DCS running it as a hook does nothing)."""
    lines = [
        "-- The API probe's plan (tools/datamine/api_probe.py); read by api-probe.lua.",
        "return {",
        f"  id = {lua_inline(p['id'])},",
        f"  version = {lua_inline(p['version'])},",
        f"  envs = {lua_inline(p['envs'])},",
        f"  samples = {lua_inline(p.get('samples') or {})},",
        "  deny = {",
        *(f"    {lua_inline(d)}," for d in p["deny"]),
        *(f"    {lua_inline(_deny_entry(d))}," for d in carried_deny(p)),
        "  },",
        "  entries = {",
        *(f"    {lua_inline(e)}," for e in p["entries"]),
        "  },",
        "}",
    ]
    return "\n".join(lines) + "\n"


def read_plan_lua(text: str) -> dict[str, Any]:
    """The plan of a hook file ``plan_lua`` wrote: ``id``, ``version``,
    ``envs``, ``samples``, ``deny`` and ``entries`` as written (a context's
    positions become a list), ``carried`` from the carried deny entries."""
    p = load_plan_lua(text, PLAN_NAME, "probe", "entries")
    deny, carried = [], []
    for d in p.get("deny") or []:
        m = _CARRIED_RE.match(d.get("reason") or "")
        if m and len(d.get("envs") or []) == 1:
            carried.append({"env": d["envs"][0], "path": d["pattern"], "plan": m[1]})
        else:
            deny.append(d)
    p["samples"] = p.get("samples") or {}
    return {**p, "deny": deny, "carried": carried}


def denied(p: dict[str, Any], deny: list[Deny]) -> dict[tuple[str, str], Deny]:
    """``{(env, path): the first matching Deny}`` of a plan's entries (the
    hook also denies every other path of a denied function)."""
    out = {}
    for e in p["entries"]:
        for d in deny:
            if d.matches(e["env"], e["path"]):
                out[(e["env"], e["path"])] = d
                break
    return out


def unused(p: dict[str, Any], deny: list[Deny]) -> list[str]:
    """Deny patterns that match no function of the plan."""
    return [
        d.pattern
        for d in deny
        if not any(d.matches(e["env"], e["path"]) for e in p["entries"])
    ]


def parse_progress(
    text: str,
) -> tuple[str | None, dict[str, Any], dict[tuple[str, str], dict[str, Any]]]:
    """(plan id, merged ``X`` sample lines, ``{(env, path): record}``) of a
    progress file; an ``S`` with no ``R`` after it is ``crashed``."""
    plan_id, lines = progress_lines(text)
    samples: dict[str, Any] = {}
    results: dict[tuple[str, str], dict[str, Any]] = {}
    started: list[tuple[str, str]] = []
    for kind, rest in lines:
        if kind == "X":
            samples.update(json.loads(rest))
        elif kind == "S":
            env, _, path = rest.partition("\t")
            started.append((env, path))
        elif kind == "R":
            env, path, record = rest.split("\t", 2)
            results[(env, path)] = json.loads(record)
    for key in started:
        results.setdefault(key, {"status": "crashed"})
    return plan_id, samples, results


def recorded(progress: Path, plan_id: str) -> int:
    """How many entries ``progress`` has a record of for ``plan_id`` (0 when
    it is missing or of another plan)."""
    pid, _, results = parse_progress(read_progress(progress))
    return len(results) if pid == plan_id else 0


def progress_version(text: str, plan_text: str | None = None) -> str | None:
    """The DCS version a progress file is of: its ``V`` line, else the
    version of ``plan_text`` (a plan hook file) when that plan has its id."""
    pid, lines = progress_lines(text)
    for tag, rest in lines[:2]:
        if tag == "V":
            return rest
    if plan_text and pid:
        m_id, m_ver = _PLAN_ID.search(plan_text), _PLAN_VERSION.search(plan_text)
        if m_id and m_ver and m_id.group(1) == pid:
            return m_ver.group(1)
    return None


def carried_crashes(cache: Path, version: str) -> list[dict[str, str]]:
    """``[{env, path, plan}]`` of ``cache``'s ``crashed.json`` when it is of
    DCS ``version``, else none."""
    try:
        known = json.loads((cache / CRASHED).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    return (
        list(known.get("crashed") or []) if known.get("dcsVersion") == version else []
    )


def harvest(
    cache: Path, progress_text: str, version: str, plan_text: str | None = None
) -> list[dict[str, str]]:
    """Add the ``crashed`` entries of a progress file of DCS ``version``
    (``progress_version``) to ``cache``'s ``crashed.json`` (one of another
    version is started over); returns the ones it added."""
    if progress_version(progress_text, plan_text) != version:
        return []
    pid, _, results = parse_progress(progress_text)
    known = carried_crashes(cache, version)
    have = {(c["env"], c["path"]) for c in known}
    added = [
        {"env": env, "path": path, "plan": pid or "?"}
        for (env, path), rec in sorted(results.items())
        if rec.get("status") == "crashed" and (env, path) not in have
    ]
    if added or not (cache / CRASHED).is_file():
        cache.mkdir(parents=True, exist_ok=True)
        crashed = sorted(known + added, key=lambda c: (c["env"], c["path"]))
        (cache / CRASHED).write_text(
            json_text({"dcsVersion": version, "crashed": crashed}), encoding="utf-8"
        )
    return added


def template(message: str) -> str:
    for pattern, repl in _TEMPLATES:
        message = pattern.sub(repl, message)
    return message


def _messages(record: dict[str, Any]) -> list[str]:
    out = [p["message"] for p in record.get("params") or [] if p.get("message")]
    out += [record[k] for k in ("error", "extraError") if record.get(k)]
    return out


def document(p: dict[str, Any], progress_text: str) -> dict[str, Any]:
    """``probe.json`` of a run of plan ``p``, finished or not (a progress
    file of another plan gives no records)."""
    pid, samples, results = parse_progress(progress_text)
    if pid != p["id"]:
        samples, results = {}, {}
    carried = {(c["env"], c["path"]): c["plan"] for c in p.get("carried") or []}
    envs: dict[str, dict[str, Any]] = {env: {} for env in p["envs"]}
    stats: dict[str, Counter[str]] = {env: Counter() for env in p["envs"]}
    formats: Counter[str] = Counter()
    for e in p["entries"]:
        key = (e["env"], e["path"])
        rec = dict(results.get(key) or {"status": "notRun"})
        if key in carried and rec["status"] in ("denied", "notRun"):
            rec = {"status": "crashed", "carriedFrom": carried[key]}
        rec["what"] = e["what"]
        rec["source"] = "probe"
        if e.get("owner"):
            rec["owner"] = e["owner"]
        if e.get("documented"):
            rec["documented"] = True
        rec["conclusive"] = rec["status"] == "ok" and all(
            q.get("from") == "error"
            or (q.get("from") == "self" and q.get("sample") == e.get("owner"))
            for q in rec.get("params") or []
        )
        envs[e["env"]][e["path"]] = rec
        stats[e["env"]][rec["status"]] += 1
        for m in _messages(rec):
            formats[template(m)] += 1
    finished = {
        tuple(rest.split("\t", 2)[:2])
        for tag, rest in progress_lines(progress_text)[1]
        if tag == "R"
    }
    complete = pid == p["id"] and all(
        (e["env"], e["path"]) in finished for e in p["entries"]
    )
    return {
        "dcsVersion": p["version"],
        "format": FORMAT,
        "plan": p["id"],
        "source": "probe",
        "samples": samples,
        "stats": {
            "complete": complete,
            **{env: dict(sorted(c.items())) for env, c in stats.items()},
        },
        "errorFormats": [
            {"template": t, "count": n} for t, n in sorted(formats.items())
        ],
        "envs": envs,
    }


PROBED = "Signature probed (DCS {})"
CRASHED_NOTE = "Crashed or hung DCS on invalid arguments (DCS {})."
_LUA_TYPES = {"string", "number", "boolean", "table", "function"}
# Parameter names the exporters cannot use as such (TypeScript reserved words).
_BAD_NAMES = {
    "class", "const", "default", "delete", "enum", "export", "extends",
    "import", "interface", "let", "new", "super", "switch", "this", "throw",
    "try", "typeof", "var", "void", "with", "yield", "arguments", "eval",
}  # fmt: skip


def load_probe(api_dir: Path, version: str | None) -> dict[str, Any] | None:
    """``api_dir``'s ``probe.json`` when it is of DCS ``version``, else None."""
    path = api_dir / PROBE_FILE
    if not path.is_file():
        return None
    doc = json.loads(path.read_text(encoding="utf-8"))
    return doc if doc.get("dcsVersion") == version else None


def probe_record(
    records: dict[str, dict[str, Any]], path: str
) -> dict[str, Any] | None:
    """The record of ``path`` in an env's records, a ``sameAs`` followed to
    the record of the function it is."""
    seen = set()
    rec = records.get(path)
    while rec and rec.get("status") == "sameAs" and rec.get("sameAs") not in seen:
        seen.add(rec["sameAs"])
        rec = records.get(rec["sameAs"])
    return rec


def _type(t: str | None) -> str:
    return t if t in _LUA_TYPES else "any"


def _param_name(name: str, pos: int) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        return f"param{pos}"
    return f"{name}_" if name in _BAD_NAMES else name


def signature(
    rec: dict[str, Any], *, method: bool = False, classes: frozenset[str] = frozenset()
) -> dict[str, Any]:
    """``{params, returns}`` (schema ``methodDef`` shapes) of a conclusive
    record: the arguments the call needed, typed from their luaL type errors
    (a Lua function's own parameter names, else ``param<N>``; one supplied
    only to reach a later position is optional ``any``), then a Lua
    function's further parameters as optional ``any``; a ``method``'s self
    is left out. Returns as observed: a table of a class in ``classes`` is
    that class, nil is ``any``; none is ``void`` for a call without
    arguments, else ``any``."""
    by_pos = {q["position"]: q for q in rec.get("params") or []}
    names = rec.get("paramNames") or []
    params = []
    n = rec.get("minArgs") or 0
    for pos in range(1, max(n, len(names)) + 1):
        q = by_pos.get(pos)
        if (
            pos == 1
            and method
            and ((q and q.get("from") == "self") or names[:1] == ["self"])
        ):
            continue
        name = names[pos - 1] if pos <= len(names) else f"param{pos}"
        param: dict[str, Any] = {"name": _param_name(name, pos)}
        if q and q.get("from") == "self":
            owner = q.get("sample")
            param["type"] = owner if owner in classes else "table"
        elif q and pos <= n:
            param["type"] = _type(q.get("expected"))
        else:
            param["type"] = "any"
            param["optional"] = True
        params.append(param)
    returns = []
    for r in rec.get("returns") or []:
        if r.get("className") in classes:
            returns.append(r["className"])
        else:
            returns.append("any" if r.get("type") == "nil" else _type(r.get("type")))
    if not returns:
        # Nothing back from sample arguments says little about real ones.
        returns = ["any" if n else "void"]
    return {"params": params, "returns": returns[0] if len(returns) == 1 else returns}


def probed_text(rec: dict[str, Any], version: str) -> str:
    """What a conclusive record's signature is based on, for its description."""
    params = rec.get("params") or []
    typed = sum(q.get("from") == "error" for q in params)
    if typed:
        plural = "s" if typed > 1 else ""
        parts = [f"{typed} required argument type{plural} from DCS errors"]
    elif any(q.get("from") == "self" for q in params):
        parts = ["no arguments besides self"]
    else:
        parts = ["no arguments"]
    if rec.get("returns"):
        parts.append("returns from one call")
    elif rec.get("minArgs"):
        parts.append("returned nothing for sample arguments")
    else:
        parts.append("returned nothing")
    if rec.get("what") == "C":
        if rec.get("extraArgs") is True:
            parts.append("accepts an extra argument")
        elif rec.get("extraArgs") is False:
            parts.append("rejects an extra argument")
        else:
            parts.append("extra arguments not probed")
    return f"{PROBED.format(version)}: {'; '.join(parts)}."


def partial_text(rec: dict[str, Any], version: str) -> str | None:
    """The argument types an inconclusive record's luaL type errors name."""
    known = [
        f"argument {q['position']} must be a {q['expected']}"
        for q in rec.get("params") or []
        if q.get("from") == "error" and q.get("expected")
    ]
    if not known:
        return None
    return f"Probe (DCS {version}): {', '.join(known)}."


def current_inputs(version: str) -> str:
    """``inputs_hash`` of the probe inputs in the repo now."""
    from .api_dump import hook_hash

    return inputs_hash(
        deny_list(version),
        hook_hash(),
        context_rules(version),
        probe_mission.spec(version),
    )


def document_offline(
    progress_file: Path,
    plan_file: Path,
    cache: Path = CACHED_PROBE_DIR,
    data_root: Path = REFERENCE_DATA_DIR,
) -> dict[str, Any]:
    """``probe.json`` of a progress file and its plan hook file, cached in
    ``cache`` (its crashes added to ``crashed.json``) and installed in
    ``data_root``."""
    progress_text = progress_file.read_text(encoding="utf-8")
    plan_text = plan_file.read_text(encoding="utf-8")
    p = read_plan_lua(plan_text)
    pid, _, _ = parse_progress(progress_text)
    if pid != p["id"]:
        fail(f"{progress_file} is of plan {pid}, {plan_file} is plan {p['id']}")
    version = p["version"]
    for c in harvest(cache, progress_text, version, plan_text):
        print(f"  carrying forward {c['env']} {c['path']}: crashed in plan {c['plan']}")
    doc = document(p, progress_text)
    replace(CACHE, dir=cache).write(doc, version, current_inputs(version))
    print(f"Cached the argument probe in {cache}")
    latest = install_probe(doc, PROBE_FILE, data_root)
    if latest:
        print(f"Installed {latest / API_DIR / PROBE_FILE}")
    else:
        warn(f"{data_root / LATEST} is not DCS {version}: probe.json only cached")
    return doc


def print_stats(doc: dict[str, Any]) -> None:
    for env, counts in doc["stats"].items():
        if env != "complete":
            print(f"  probe {env:<9} {counts}")
    conclusive = Counter(
        env
        for env, recs in doc["envs"].items()
        for r in recs.values()
        if r.get("conclusive")
    )
    print(f"  conclusive: {dict(sorted(conclusive.items()))}")
    print(f"  complete: {doc['stats']['complete']}")


def summary(p: dict[str, Any], deny: list[Deny]) -> list[str]:
    """What a run of plan ``p`` would call, as text lines."""
    hits = denied(p, deny + carried_deny(p))
    lines = [f"Probe plan {p['id']} (DCS {p['version']}, mission {p['mission']})"]
    for env in p["envs"]:
        entries = [e for e in p["entries"] if e["env"] == env]
        what = Counter(e["what"] for e in entries)
        n_denied = sum((env, e["path"]) in hits for e in entries)
        n_doc = sum(bool(e.get("documented")) for e in entries)
        n_ctx = sum(bool(e.get("context")) for e in entries)
        lines.append(
            f"  {env:<9} {len(entries):5d} functions (C {what.get('C', 0)}, "
            f"Lua {what.get('Lua', 0)}; {n_doc} documented, {n_ctx} with context "
            f"samples), {n_denied} denied, {len(entries) - n_denied} to call"
        )
    unsure = [d for d in deny if d.unsure]
    lines.append(f"  deny list: {len(deny)} patterns, {len(unsure)} unsure:")
    lines += [f"    {d.pattern}: {d.reason}" for d in unsure]
    carried = p.get("carried") or []
    lines.append(f"  carried forward (crashed or hung before): {len(carried)}")
    lines += [f"    {c['env']} {c['path']} (plan {c['plan']})" for c in carried]
    stale_patterns = unused(p, deny)
    if stale_patterns:
        lines.append(f"  patterns matching nothing: {', '.join(stale_patterns)}")
    return lines


def main_document(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Build probe.json from a progress file, cache and install it"
    )
    parser.add_argument("--from-progress", type=Path, required=True)
    parser.add_argument(
        "--plan",
        type=Path,
        default=PLAN_FILE,
        help=f"the plan hook file of the run (default {PLAN_FILE})",
    )
    args = parser.parse_args(argv)
    print_stats(document_offline(args.from_progress, args.plan))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["document"]:
        return main_document(argv[1:])
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--api-dir",
        type=Path,
        default=REFERENCE_DATA_DIR / LATEST / API_DIR,
        help="API dump dir (default: dcs-world-reference/latest/api)",
    )
    parser.add_argument("--plan-out", type=Path, help="also write the plan hook file")
    args = parser.parse_args(argv)
    scripting = args.api_dir / "scripting.json"
    if not scripting.is_file():
        fail(f"no scripting.json in {args.api_dir}")
    version = load_dump(scripting).get("dcsVersion")
    if not isinstance(version, str):
        fail(f"{scripting}: no dcsVersion")
    deny = deny_list(version)
    rules = context_rules(version)
    mission = probe_mission.build(probe_mission.spec(version), None)
    p = plan(
        args.api_dir,
        deny,
        version,
        mission=mission,
        rules=rules,
        carried=carried_crashes(CACHED_PROBE_DIR, version),
    )
    for line in summary(p, deny):
        print(line)
    for pattern in unused(p, deny):
        warn(f"overlays {SERIES}/{TABLE} {pattern!r} matches no dumped function")
    for path in unused_context(p, rules):
        warn(f"overlays {SERIES}/{CONTEXT} {path!r} matches no dumped function")
    if args.plan_out:
        args.plan_out.parent.mkdir(parents=True, exist_ok=True)
        args.plan_out.write_text(plan_lua(p), encoding="utf-8")
        print(f"Wrote {args.plan_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
