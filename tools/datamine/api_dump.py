"""The Lua API dumps of ``hook/api-dump.lua``: its cache, the files it adds to the
reference data and the member view ``tools/verify.py`` compares the schema with.

The reference data holds, under ``api/``:

* ``<env>.json`` for each of ``ENVS``, the hook's file normalised
  (``normalize``): ``paths`` header dropped, install and Saved Games prefixes
  in function sources as ``<install>/`` and ``<writedir>/``, members sorted.
* ``states.json``: the hook's probe of the ``net.dostring_in`` state names
  (which exist, which are the same Lua state), when the run wrote one.
* ``export.docs.json``: ``export_docs`` of the install's ``Scripts/Export.lua``.

``refresh.py`` caches a run's files in ``.datamine/api`` with ``done`` (the DCS
version) and ``hook`` (hash of the hooks) like the terrain dumps.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import export_docs
from .common import (
    API_DIR,
    CACHE_DIR,
    DONE,
    HOOK_DIR,
    ProbeCache,
    fail,
    hooks_hash,
    json_text,
    read_marker,
)

API_HOOKS = [HOOK_DIR / "api-dump.lua", HOOK_DIR / "api-walk.lua"]
API_REL = "DCS.Lua.Exporter/api"
CACHED_API_DIR = CACHE_DIR / "api"
FORMAT = "dcs-api-dump/2"
ENVS = ("scripting", "hooks", "server", "export")
# Envs the run must dump: the hook runs in one, terrain-dump.lua uses the other.
REQUIRED_ENVS = ("scripting", "hooks")
DOCS_FILE = "export.docs.json"
STATES_FILE = "states.json"
HOOK_STAMP = "hook"
CACHE = ProbeCache(CACHED_API_DIR, "scripting.json", "API dump", "API hook", HOOK_STAMP)
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# How deep the legacy view follows nested tables (the walk's maxDepth).
LEGACY_DEPTH = 8

# The namespaces `task verify` compares with the schema.
LEGACY_TARGETS = (
    "AI",
    "Airbase",
    "Beacons",
    "CoalitionObject",
    "Controller",
    "Disposition",
    "Formation",
    "Group",
    "Object",
    "SceneryObject",
    "Spot",
    "StaticObject",
    "Unit",
    "VoiceChat",
    "Warehouse",
    "Weapon",
    "atmosphere",
    "coalition",
    "coord",
    "dcs",
    "env",
    "land",
    "missionCommands",
    "net",
    "radio",
    "timer",
    "trigger",
    "world",
)


def hook_hash() -> str:
    """SHA-256 of the API hooks' names and contents."""
    return hooks_hash(API_HOOKS)


def _path_prefixes(paths: dict[str, Any]) -> list[tuple[str, str]]:
    out = []
    for key, label in (("installDir", "<install>/"), ("writeDir", "<writedir>/")):
        value = paths.get(key)
        if isinstance(value, str) and value.strip("/\\"):
            prefix = value.replace("\\", "/")
            out.append((prefix if prefix.endswith("/") else prefix + "/", label))
    # The longer prefix first: Saved Games may sit inside the install.
    return sorted(out, key=lambda p: -len(p[0]))


def _strip_source(source: str, prefixes: list[tuple[str, str]]) -> str:
    at = source.startswith("@")
    path = source[1:] if at else source
    if at:
        path = path.replace("\\", "/")
        for prefix, label in prefixes:
            if path.lower().startswith(prefix.lower()):
                path = label + path[len(prefix) :]
                break
        path = re.sub(r"^\./", "<install>/", path)
    return ("@" if at else "") + path


def _member_key(m: dict[str, Any]) -> tuple[int, float, str]:
    if m.get("keyType") == "number":
        k = m["key"]
        return (0, k if isinstance(k, (int, float)) else float(k), "")
    return (1, 0.0, str(m["key"]))


def _normalize_node(node: Any, prefixes: list[tuple[str, str]]) -> None:
    if not isinstance(node, dict):
        return
    if node.get("type") == "function" and isinstance(node.get("source"), str):
        node["source"] = _strip_source(node["source"], prefixes)
    if isinstance(node.get("members"), list):
        node["members"].sort(key=_member_key)
        for m in node["members"]:
            _normalize_node(m.get("value"), prefixes)
    _normalize_node(node.get("metatable"), prefixes)


def normalize(dump: dict[str, Any]) -> dict[str, Any]:
    """``dump`` (one hook file) as stored in the reference data, in place."""
    if dump.get("format") != FORMAT:
        fail(
            f"API dump {dump.get('env')!r}: format {dump.get('format')!r}, want {FORMAT}"
        )
    prefixes = _path_prefixes(dump.pop("paths", None) or {})
    for node in (dump.get("globals") or {}).values():
        _normalize_node(node, prefixes)
    return dump


def load(path: Path) -> dict[str, Any]:
    """A hook file, parsed (``inf``/``nan`` are strings there, never bare)."""
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        fail(f"unreadable API dump {path}: {exc}")
    if not isinstance(data, dict):
        fail(f"API dump {path} is not a JSON object")
    return data


def cached_files(
    api_dir: Path, version: str, install_dir: Path | None
) -> dict[str, bytes]:
    """``{"api/<name>": bytes}`` for the reference data from the cached run in
    ``api_dir``; every env file must be there and of ``version``."""
    out: dict[str, bytes] = {}
    for env in ENVS:
        path = api_dir / f"{env}.json"
        if not path.is_file():
            fail(f"no {env}.json in {api_dir}")
        dump = normalize(load(path))
        if dump.get("env") != env or dump.get("dcsVersion") != version:
            fail(
                f"{path} is env {dump.get('env')!r} of DCS {dump.get('dcsVersion')}, "
                f"want {env!r} of {version}"
            )
        out[f"{API_DIR}/{env}.json"] = json_text(dump).encode("utf-8")
    states_path = api_dir / STATES_FILE
    if states_path.is_file():
        states = load(states_path)
        if states.get("dcsVersion") != version:
            fail(f"{states_path} is of DCS {states.get('dcsVersion')}, want {version}")
        out[f"{API_DIR}/{STATES_FILE}"] = json_text(states).encode("utf-8")
    docs = export_docs.document(install_dir) if install_dir else None
    if docs is not None:
        out[f"{API_DIR}/{DOCS_FILE}"] = json_text(docs).encode("utf-8")
    return out


def version_files(
    api_dir: Path, version: str, install_dir: Path | None, ver_dir: Path | None
) -> dict[str, bytes]:
    """The ``api/`` files of DCS ``version``: from the cache when it holds
    this version, else the ones in ``ver_dir`` (the data already extracted for
    it, if any), so a re-extraction keeps them."""
    if read_marker(api_dir / DONE) == version:
        return cached_files(api_dir, version, install_dir)
    existing = ver_dir / API_DIR if ver_dir else None
    if existing is None or not existing.is_dir():
        return {}
    return {
        f"{API_DIR}/{p.name}": p.read_bytes()
        for p in sorted(existing.iterdir())
        if p.is_file()
    }


def status(dump: dict[str, Any]) -> str:
    """``"ok"``, ``"sameAs <env>"`` or ``"<status>: <error>"`` of one env file."""
    if dump.get("status") == "ok":
        return "ok"
    if dump.get("status") == "sameAs":
        return f"sameAs {dump.get('sameAs')}"
    return f"{dump.get('status')}: {dump.get('error')}"


def statuses(files: dict[str, bytes]) -> dict[str, str]:
    """``{env: status(...)}`` of a data dir's api files."""
    out = {}
    for env in ENVS:
        raw = files.get(f"{API_DIR}/{env}.json")
        if raw is None:
            out[env] = "missing"
            continue
        out[env] = status(json.loads(raw))
    return out


def _key_text(m: dict[str, Any]) -> str:
    """A member's step in a dump path (api-walk.lua's childPath)."""
    k = m["key"]
    if m.get("keyType") == "number":
        if isinstance(k, float) and k.is_integer() and abs(k) < 2**53:
            k = int(k)
        return f"[{k if isinstance(k, (int, str)) else format(k, '.17g')}]"
    if _IDENT.match(k):
        return f".{k}"
    return f"[{json.dumps(k, ensure_ascii=False)}]"


def path_index(globals_: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """``{path: node}`` of every table written in full in a dump's globals:
    what a ``{"ref": path}`` node stands for."""
    out: dict[str, dict[str, Any]] = {}

    def visit(node: Any, path: str) -> None:
        if not isinstance(node, dict) or "ref" in node:
            return
        if node.get("type") == "table":
            out[path] = node
        for m in node.get("members") or []:
            visit(m.get("value"), path + _key_text(m))
        visit(node.get("metatable"), path + "<metatable>")

    for name, node in globals_.items():
        visit(node, name)
    return out


def resolve(node: dict[str, Any], index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The node a ref stands for (itself when it is no ref or points nowhere)."""
    seen = set()
    while isinstance(node.get("ref"), str) and node["ref"] not in seen:
        seen.add(node["ref"])
        target = index.get(node["ref"])
        if target is None:
            break
        node = target
    return node


def _legacy_node(
    node: dict[str, Any],
    index: dict[str, dict[str, Any]],
    stack: tuple[int, ...] = (),
) -> dict[str, Any]:
    """A table node in the ``tools/verify.py`` shape: ``{kind, members}`` with ``{name, type, value?, sub?}`` per member (direct members only); refs
    are followed, a cycle or a table LEGACY_DEPTH deep is left without ``sub``."""
    stack = (*stack, id(node))
    members = []
    for m in node.get("members") or []:
        value = resolve(m.get("value") or {}, index)
        entry: dict[str, Any] = {"name": str(m["key"]), "type": value.get("type")}
        if value.get("type") in ("number", "string", "boolean"):
            entry["value"] = value.get("value")
        if (
            value.get("type") == "table"
            and id(value) not in stack
            and len(stack) < LEGACY_DEPTH
        ):
            entry["sub"] = _legacy_node(value, index, stack)
        members.append(entry)
    return {"kind": "table", "members": members}


def legacy(
    dump: dict[str, Any], targets: tuple[str, ...] = LEGACY_TARGETS
) -> dict[str, Any]:
    """The mission scripting dump in the ``tools/verify.py`` shape, limited to
    ``targets``."""
    if dump.get("env") != "scripting":
        fail(f"verify needs the scripting env dump, got {dump.get('env')!r}")
    if dump.get("status") != "ok":
        fail(f"the scripting env dump is {dump.get('status')}: {dump.get('error')}")
    out: dict[str, Any] = {}
    globals_ = dump.get("globals") or {}
    index = path_index(globals_)
    for name, node in sorted(globals_.items()):
        if name not in targets:
            continue
        node = resolve(node, index)
        out[name] = (
            _legacy_node(node, index)
            if node.get("type") == "table"
            else {"kind": node.get("type")}
        )
    return out


def table_at(api: dict[str, Any], path: str) -> dict[str, Any] | None:
    """The ``legacy`` view's table at a dotted path (``AI.Option.Air.id``), or None."""
    ns, *rest = path.split(".")
    node = api.get(ns)
    for key in rest:
        if not isinstance(node, dict):
            return None
        node = next(
            (m.get("sub") for m in node.get("members", []) if m.get("name") == key),
            None,
        )
    return node if isinstance(node, dict) else None


def scalars_at(api: dict[str, Any], path: str) -> dict[str, Any] | None:
    """``{key: value}`` of the scalar members of ``table_at(api, path)``."""
    table = table_at(api, path)
    if table is None:
        return None
    return {m["name"]: m["value"] for m in table.get("members", []) if "value" in m}
