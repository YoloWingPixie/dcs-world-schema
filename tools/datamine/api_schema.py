"""Generate schema globals for the hooks, server and export Lua environments
from the API dump (``api/<env>.json``), and build their dist outputs.

Mission scripting stays hand-written in ``dcs-world-schema/globals``. Each other
env gets ``globals/<env>/`` (outside the main spec, ``tools.merge.ENV_DIRS``)
with one ``<global>.generated.yaml`` per global table, a ``kind: singleton``
whose members are typed from the dumped values (tables one level deep).
Functions get their signature from a conclusive ``api/probe.json`` record of
the same DCS version (``api_probe``; without a probe of its own the previous
version's, ``probedOn``, for functions still dumped as the same kind),
otherwise "signature unknown" plus any crash or luaL argument types. Non-table globals go in ``_G.generated.yaml``.
Skipped and listed in its header: ``module()`` tables, non-identifier or
reserved names, and data tables (no function within the dump's ``apiDepth``).
Envs with no dump or ``sameAs`` another get no files. ``dist`` builds
``dist/dcs-world-api-<env>-schema.json`` plus ``.lua`` / ``.d.ts`` per env, kept
apart from the main spec (``net`` is in several envs).

    uv run python -m tools.datamine.api_schema [--api-dir DIR] [--out DIR] [--check]
    uv run python -m tools.datamine.api_schema dist [--dist DIR]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from tools.merge import merge_tree

from . import api_probe
from .api_dump import path_index, resolve
from .common import (
    API_DIR,
    LATEST,
    REFERENCE_DATA_DIR,
    REPO_ROOT,
    fail,
    generated_drift,
    probed_on,
    write_generated,
)

SCHEMA_DIR = REPO_ROOT / "dcs-world-schema"
SCHEMA_ENVS = ("hooks", "server", "export")
SUFFIX = ".generated.yaml"
VERSION_TAG = "DCS version: "
FREE_GLOBALS = "_G"
MODULE_KEYS = {"_M", "_NAME", "_PACKAGE"}
# Lua keywords and names the exporters cannot declare as a namespace.
RESERVED = {
    "and", "break", "do", "else", "elseif", "end", "false", "for", "function",
    "goto", "if", "in", "local", "nil", "not", "or", "repeat", "return", "then",
    "true", "until", "while", "class", "const", "default", "delete", "enum",
    "export", "extends", "import", "interface", "let", "new", "super", "switch",
    "this", "throw", "try", "typeof", "var", "void", "with", "yield",
}  # fmt: skip
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
VALUE_CHARS = 80


def env_dir(env: str, root: Path = SCHEMA_DIR) -> Path:
    return root / "globals" / env


def _members(node: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """String-keyed members of a table node."""
    return {
        m["key"]: m.get("value") or {}
        for m in node.get("members") or []
        if m.get("keyType") == "string"
    }


class Probe:
    """An env's argument probe records (``api/probe.json``) and the DCS
    version they were measured on; ``carried`` when that is an earlier
    version's probe (``probedOn``)."""

    def __init__(
        self, records: dict[str, dict[str, Any]], version: str, carried: bool = False
    ) -> None:
        self.records, self.version, self.carried = records, version, carried

    def record(
        self, path: str, node: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """``path``'s record; a carried one only when it probed the same kind
        of function (C or Lua) as the dumped ``node``."""
        rec = api_probe.probe_record(self.records, path)
        if (
            rec
            and self.carried
            and node is not None
            and rec.get("what") != node.get("what")
        ):
            return None
        return rec


def _where(node: dict[str, Any]) -> str:
    what = node.get("what")
    if what == "C":
        return "C function"
    if what in ("Lua", "main") and node.get("source"):
        return f"Lua function ({node['source'].lstrip('@')}:{node.get('linedefined')})"
    return "Function"


def _function_desc(
    node: dict[str, Any], rec: dict[str, Any] | None, version: str
) -> str:
    text = f"{_where(node)}; signature unknown (the API dump has none)."
    if rec and rec.get("status") == "crashed":
        text += " " + api_probe.CRASHED_NOTE.format(version)
    elif rec and (partial := api_probe.partial_text(rec, version)):
        text += " " + partial
    return text


def _function(
    node: dict[str, Any], path: str, probe: Probe | None, method: bool
) -> dict[str, Any]:
    """A dumped function: a ``methodDef`` from a conclusive probe record when
    ``method`` (it may be one there), else a ``function`` field."""
    rec = probe.record(path, node) if probe else None
    if rec and rec.get("conclusive") and method and probe:
        sig = api_probe.signature(rec)
        text = api_probe.probed_text(rec, probe.version)
        return {"description": f"{_where(node)}. {text}", **sig}
    version = probe.version if probe else ""
    return {"type": "function", "description": _function_desc(node, rec, version)}


def _value_text(node: dict[str, Any]) -> str:
    value = node.get("value")
    text = json.dumps(value, ensure_ascii=False)
    if len(text) > VALUE_CHARS:
        text = text[: VALUE_CHARS - 3] + "..."
    return text


def _field(
    node: dict[str, Any], path: str = "", probe: Probe | None = None
) -> dict[str, Any]:
    """A fieldDef for a dumped value."""
    t = node.get("type")
    if t == "function":
        return _function(node, path, probe, False)
    if t in ("number", "string", "boolean"):
        return {"type": t, "description": f"Dumped value: {_value_text(node)}."}
    if t == "table":
        return {"type": "table", "description": _table_desc(node)}
    return {"type": "any", "description": f"A {t} in the dump."}


def _table_desc(node: dict[str, Any]) -> str:
    if node.get("ref"):
        return f"The table at `{node['ref']}`."
    if node.get("summary"):
        return (
            f"A {node['summary']} table of {node.get('entries')} entries (not dumped)."
        )
    if node.get("truncated"):
        return f"A table (not dumped: {node['truncated']} limit)."
    members = node.get("members") or []
    numbers = sum(1 for m in members if m.get("keyType") == "number")
    text = f"A table of {len(members)} members in the dump"
    if numbers:
        text += f" ({numbers} with number keys, not listed)"
    return text + "."


def _member(node: dict[str, Any], path: str, probe: Probe | None) -> dict[str, Any]:
    """A static member: a nested table (one level of fields), a probed
    function's methodDef or a fieldDef."""
    if node.get("type") == "function":
        return _function(node, path, probe, True)
    if node.get("type") != "table" or not node.get("members"):
        return _field(node)
    fields = {
        k: _field(v, f"{path}.{k}", probe) for k, v in sorted(_members(node).items())
    }
    out: dict[str, Any] = {"kind": "table", "description": _table_desc(node)}
    if fields:
        out["fields"] = fields
    return out


def _is_module(node: dict[str, Any]) -> bool:
    return bool(MODULE_KEYS & _members(node).keys())


def _has_functions(
    node: dict[str, Any], depth: int, index: dict[str, dict[str, Any]]
) -> bool:
    """Whether a function is among the values of ``node`` or its metatable,
    or of the tables up to ``depth`` levels below (api-walk.lua's isApi, over
    what the dump holds: refs are followed, summarised tables have none)."""
    level, seen = [resolve(node, index)], set()
    for _ in range(depth + 1):
        below = []
        for t in level:
            for x in (t, resolve(t.get("metatable") or {}, index)):
                if id(x) in seen:
                    continue
                seen.add(id(x))
                for m in x.get("members") or []:
                    v = resolve(m.get("value") or {}, index)
                    if v.get("type") == "function":
                        return True
                    if v.get("type") == "table":
                        below.append(v)
        level = below
    return False


def _file(env: str, name: str, body: dict[str, Any], version: str, note: str) -> str:
    head = [
        f"# The {env} Lua environment's `{name}`, generated from api/{env}.json.",
        f"# {VERSION_TAG}{version}",
        "# Generated by tools/datamine/api_schema.py; do not edit.",
    ]
    if note:
        head.append(f"# {note}")
    doc = {"globals": {name: body}, "types": {}}
    text = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100)
    return "\n".join(head) + "\n" + text


def generate_env(
    dump: dict[str, Any], probe: dict[str, Any] | None = None
) -> dict[str, str]:
    """``{file name: YAML}`` of one env's dump (none unless its status is ok),
    its functions typed from the env's records of ``probe`` (a ``probe.json``
    of the dump's DCS version, perhaps carried forward from an earlier one:
    its records then only for functions of the same kind, described with the
    version probed): a conclusive one's signature, a crash, the argument
    types an inconclusive one's errors name."""
    if dump.get("status") != "ok":
        return {}
    env, version = dump["env"], dump.get("dcsVersion", "unknown")
    records = (probe or {}).get("envs", {}).get(env)
    pr = None
    if probe is not None and records is not None:
        on = probed_on(probe)
        pr = Probe(records, on, carried=on != version)
    source = f"From the {env} environment's API dump (DCS {version})."
    files: dict[str, str] = {}
    used: set[str] = set()
    free: dict[str, Any] = {}
    skipped: list[str] = []
    dropped: list[str] = []
    globals_ = dump.get("globals") or {}
    index = path_index(globals_)
    depth = (dump.get("limits") or {}).get("apiDepth", 1)
    for name, node in sorted(globals_.items()):
        if not _IDENT.match(name) or name in RESERVED:
            skipped.append(name)
            continue
        if node.get("type") != "table":
            free[name] = _member(node, name, pr)
            continue
        alias = node.get("ref")
        if alias in globals_:
            node = globals_[alias]
        else:
            alias = None
        if _is_module(node):
            skipped.append(name)
            continue
        if not _has_functions(node, depth, index):
            dropped.append(name)
            continue
        owner = alias or name
        static = {
            k: _member(v, f"{owner}.{k}", pr) for k, v in sorted(_members(node).items())
        }
        desc = source
        if alias:
            desc = f"The same table as `{alias}`. {source}"
        elif node.get("summary") or node.get("ref"):
            desc = f"{_table_desc(node)} {source}"
        body: dict[str, Any] = {"kind": "singleton", "description": desc}
        if static:
            body["static"] = static
        stem = name
        while stem.lower() in used:
            stem += "_"
        used.add(stem.lower())
        files[f"{stem}{SUFFIX}"] = _file(env, name, body, version, "")
    if free or skipped or dropped:
        body = {
            "kind": "singleton",
            "description": f"Global functions and non-table values. {source}",
        }
        if free:
            body["static"] = free
        notes = []
        if skipped:
            notes.append(
                f"Skipped (module() tables, non-identifiers): {', '.join(skipped)}"
            )
        if dropped:
            notes.append(f"Skipped (data tables, no functions): {', '.join(dropped)}")
        note = "\n# ".join(notes)
        files[f"{FREE_GLOBALS}{SUFFIX}"] = _file(env, FREE_GLOBALS, body, version, note)
    return dict(sorted(files.items()))


def load_dumps(api_dir: Path) -> dict[str, dict[str, Any]]:
    """``{env: dump}`` of ``SCHEMA_ENVS`` in ``api_dir`` (absent envs left out)."""
    out = {}
    for env in SCHEMA_ENVS:
        path = api_dir / f"{env}.json"
        if path.is_file():
            out[env] = json.loads(path.read_text(encoding="utf-8"))
    return out


def generate(api_dir: Path) -> dict[str, dict[str, str]]:
    """``{env: {file name: YAML}}`` for every ``SCHEMA_ENVS`` env."""
    dumps = load_dumps(api_dir)
    return {
        env: generate_env(
            dumps[env], api_probe.load_probe(api_dir, dumps[env].get("dcsVersion"))
        )
        if env in dumps
        else {}
        for env in SCHEMA_ENVS
    }


def write(files: dict[str, dict[str, str]], root: Path = SCHEMA_DIR) -> None:
    """Make each env's generated files under ``root`` exactly ``files``."""
    for env, env_files in files.items():
        out = env_dir(env, root)
        write_generated(out, env_files, SUFFIX)
        if out.is_dir() and not any(out.iterdir()):
            out.rmdir()


def drift(files: dict[str, dict[str, str]], root: Path = SCHEMA_DIR) -> list[str]:
    """Generated files under ``root`` that differ from ``files``."""
    return [
        f"globals/{env}/{n}"
        for env, env_files in files.items()
        for n in generated_drift(env_dir(env, root), env_files, SUFFIX)
    ]


def build_dist(dist: Path, root: Path = SCHEMA_DIR) -> list[str]:
    """Per env with schema files: the merged spec and its Lua and TypeScript
    outputs in ``dist``; the envs built."""
    built = []
    for env in SCHEMA_ENVS:
        merged, count = merge_tree(str(root), subdirs=[f"globals/{env}"])
        if not count:
            print(f"No schema files for the {env} environment: skipped")
            continue
        spec = dist / f"dcs-world-api-{env}-schema.json"
        dist.mkdir(parents=True, exist_ok=True)
        spec.write_text(
            json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        for module, suffix in (
            ("tools.export_lua", ".lua"),
            ("tools.export_typescript", ".d.ts"),
        ):
            target = dist / f"dcs-world-api-{env}{suffix}"
            cmd = [sys.executable, "-m", module, str(spec), "--output", str(target)]
            if subprocess.run(cmd, cwd=REPO_ROOT, check=False).returncode:
                fail(f"{module} failed for the {env} environment")
        built.append(env)
    return built


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["dist"]:
        parser = argparse.ArgumentParser(description="Build the per-env dist outputs")
        parser.add_argument("--dist", type=Path, default=REPO_ROOT / "dist")
        args = parser.parse_args(argv[1:])
        built = build_dist(args.dist)
        print(f"Built dist outputs for: {', '.join(built) or 'no environment'}")
        return 0
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--api-dir",
        type=Path,
        default=REFERENCE_DATA_DIR / LATEST / API_DIR,
        help="API dump files (default: dcs-world-reference/latest/api).",
    )
    parser.add_argument("--out", type=Path, default=SCHEMA_DIR, help="Schema root.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if the generated files differ from what the dumps produce.",
    )
    args = parser.parse_args(argv)
    if not load_dumps(args.api_dir):
        print(f"No API dumps in {args.api_dir}: nothing to generate")
        return 0
    files = generate(args.api_dir)
    if args.check:
        stale = drift(files, args.out)
        if stale:
            fail(
                f"API env schemas out of date ({', '.join(stale)}); "
                "run `task datamine:api-schema`"
            )
        print(f"API env schemas match {args.api_dir}")
        return 0
    write(files, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
