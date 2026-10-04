"""Coverage of DCS object configuration in Lua ``_G`` dumps.

``diff SUBJECT [TARGET | --quaggles DIR | --quaggles-ref REF]``
    Flattens every object file (``ROOTS``) of two dumps into ``path = leaf``
    pairs and classifies each difference, per file, root and category:

    * ``missing``    - a target path the subject lacks;
    * ``added``      - a subject path the target lacks;
    * ``changed``    - both have the path with different plain values;
    * ``unresolved`` - a cross-file ref with no target file, or a path where
      either side holds a marker (function, cycle, ``format3-nil``, redacted,
      truncated ...) and the two differ.

    A dump is ours (formats 3 and 4, e.g. a previous one) or a Quaggles
    ``dcs-lua-datamine`` checkout (``--quaggles``, or ``--quaggles-ref``
    cloned into ``.datamine/quaggles``), parsed by the pure-Python
    ``parse_dump``. Against Quaggles every difference is matched against
    ``coverage-explanations.yaml``; a target path the subject lacks that no
    rule explains fails the command (exit 1) unless ``--advisory``.

``typed [DATA_DIR] [--g-dir G]``
    Checks the ``weapon_flight`` and ``aircraft_flight`` records of
    ``DATA_DIR`` against the dump: every typed value must equal the dump
    value at its block's ``sourcePath`` plus its DCS key (``dump_paths``).
    The keys of the dump blocks are reported as typed or dump-only (not a
    failure). A path that does not resolve, or a differing value, fails
    unless ``--advisory``.

Diff paths are ``<file>`` (dump path below ``_G`` without ``.lua``) plus a
Lua-style key path (``.client.fm.Cx0[3]``, ``["key with space"]``, ``[true]``).
Cross-file refs (``"_G/warheads/X.lua"``) are inlined by default, so the two
sides compare by content. Output is deterministic.
"""

from __future__ import annotations

import argparse
import bisect
import fnmatch
import json
import math
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import yaml

from . import aircraft_flight, weapon_flight
from .common import CACHE_DIR, CACHED_G_DIR, LATEST, REFERENCE_DATA_DIR, REPO_ROOT, fail
from .dump_paths import DumpPaths, pointer, split_source_path
from .lua_reader import LuaTable, Marker, SourceRef, key_str
from .typed_fields import F, fits

EXPLANATIONS = Path(__file__).with_name("coverage-explanations.yaml")
QUAGGLES_URL = "https://github.com/Quaggles/dcs-lua-datamine.git"
# Tag 2.9.30.28536 (the DCS version of the committed reference data).
QUAGGLES_REF = "fdd11ed960d5402909a876558b7bec3b2653b268"
QUAGGLES_DIR = CACHE_DIR / "quaggles"

CLASSES = ("missing", "added", "changed", "unresolved")
# Side files of the dump that are not object configuration.
_META = re.compile(r"^__(?:DCS_VERSION|DUMP_FORMAT|constants|wstype_ids|years)__$")


# --- tree model ---------------------------------------------------------------


class Num(float):
    """A dump number that remembers its literal."""

    raw: str

    def __new__(cls, raw: str) -> Num:
        low = raw.lower()
        if low in ("1e309", "math.huge", "1.#inf"):
            v = math.inf
        elif low in ("-1e309", "-math.huge", "-1.#inf"):
            v = -math.inf
        elif "nan" in low or "#ind" in low:
            v = math.nan
        elif low.startswith(("0x", "-0x")):
            v = float(int(low, 16))
        else:
            v = float(raw)
        obj = super().__new__(cls, v)
        obj.raw = raw
        return obj


@dataclass(frozen=True)
class Mark:
    """A leaf that is no plain Lua value: a dump marker (``function``,
    ``unsupported``, ``redacted``, ...), ``empty`` (a table without keys),
    ``cycle`` or ``unresolved-ref``."""

    kind: str
    detail: str = ""

    def json(self) -> Any:
        if self.kind == "empty":
            return {}
        out: dict[str, Any] = {"$type": self.kind}
        if self.detail:
            out["detail"] = self.detail
        return out


EMPTY = Mark("empty")
CYCLE = Mark("cycle")


@dataclass(frozen=True)
class Anchor:
    """A table referenced more than once in its file (format 4 ``anchor``,
    inspect's ``<N>{...}``)."""

    id: str
    value: Any


@dataclass(frozen=True)
class LocalRef:
    """A later occurrence of an anchor (format 4 ``ref``, ``<table N>``)."""

    id: str


@dataclass(frozen=True)
class FileRef:
    """A cross-file ref: ``path`` is the target's ``_G/...`` path without
    ``.lua``."""

    path: str


def is_marker(leaf: Any) -> bool:
    return isinstance(leaf, Mark) and leaf.kind != "empty"


def is_number(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def same(a: Any, b: Any) -> bool:
    """Leaf equality: booleans are not numbers, ``-0`` is not ``0``, NaN
    equals NaN."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if is_number(a) and is_number(b):
        fa, fb = float(a), float(b)
        if math.isnan(fa) or math.isnan(fb):
            return math.isnan(fa) and math.isnan(fb)
        return fa == fb and math.copysign(1, fa) == math.copysign(1, fb)
    if is_number(a) or is_number(b):
        return False
    return bool(type(a) is type(b) and a == b)


def leaf_json(v: Any) -> Any:
    """A leaf as JSON (numbers that JSON cannot hold as markers)."""
    if isinstance(v, Mark):
        return v.json()
    if isinstance(v, FileRef):
        return {"$type": "ref", "path": v.path}
    if is_number(v):
        f = float(v)
        if math.isnan(f) or math.isinf(f) or (f == 0 and math.copysign(1, f) < 0):
            text = "nan" if math.isnan(f) else "-0" if f == 0 else repr(f)
            return {"$type": "number", "value": text}
        if isinstance(v, int):
            return v
        return int(f) if f.is_integer() and abs(f) < 2**53 else f
    return v


# --- dump parser --------------------------------------------------------------

_WS = re.compile(r"(?:\s+|--\[(=*)\[.*?\]\1\]|--[^\n]*)+", re.S)
_NUM = re.compile(
    r"-?(?:1\.#(?:INF|IND|QNAN)|0[xX][0-9a-fA-F]+|"
    r"(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)"
)
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ANGLE = re.compile(r"<(?:(table|function|userdata|thread)\s*)?(\d*)>")
_DIGITS = re.compile(r"\d{1,3}")
_LONG_OPEN = re.compile(r"\[(=*)\[")
_ESC = {
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
    "\\": "\\",
    '"': '"',
    "'": "'",
    "\n": "\n",
}
_REF = re.compile(r"^_G/.+\.lua$")
_HEADER = re.compile(r'\s*_G((?:\[(?:"(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?)\])*)\s*=\s*')
_HKEY = re.compile(r'\[(?:"((?:[^"\\]|\\.)*)"|(-?\d+(?:\.\d+)?))\]')


class ParseError(Exception):
    pass


class _Parser:
    """Recursive descent over the table-constructor subset both dumpers
    write, plus inspect's ``<N>{}``/``<table N>``/``<function N>``
    placeholders (Quaggles) and format 4's ``__dcs{...}`` markers. A
    ``key = nil`` entry (format 3's unwritable value) is the ``unsupported``
    marker ``format3-nil``, as ``lua_reader.read_source`` keeps it."""

    def __init__(self, text: str, name: str) -> None:
        self.s = text
        self.i = 0
        self.name = name

    def ws(self) -> None:
        m = _WS.match(self.s, self.i)
        if m:
            self.i = m.end()

    def peek(self) -> str:
        self.ws()
        return self.s[self.i : self.i + 1]

    def expect(self, ch: str) -> None:
        if self.peek() != ch:
            self.fail(f"expected {ch!r}")
        self.i += 1

    def fail(self, msg: str) -> None:
        line = self.s.count("\n", 0, self.i) + 1
        ctx = self.s[self.i : self.i + 40].replace("\n", "\\n")
        raise ParseError(f"{self.name}:{line}: {msg} at {ctx!r}")

    def string(self) -> str:
        s = self.s
        q = s[self.i]
        if q == "[":
            m = _LONG_OPEN.match(s, self.i)
            if not m:
                self.fail("bad long string")
                raise AssertionError
            close = "]" + m.group(1) + "]"
            end = s.find(close, m.end())
            if end < 0:
                self.fail("unterminated long string")
            body = s[m.end() : end]
            self.i = end + len(close)
            return body[1:] if body.startswith("\n") else body
        self.i += 1
        out: list[str] = []
        while True:
            j = self.i
            n = len(s)
            while j < n and s[j] != q and s[j] != "\\":
                j += 1
            if j >= n:
                self.fail("unterminated string")
            out.append(s[self.i : j])
            if s[j] == q:
                self.i = j + 1
                return "".join(out)
            c = s[j + 1]
            if c.isdigit():
                m = _DIGITS.match(s, j + 1)
                assert m is not None
                out.append(chr(int(m.group())))
                self.i = m.end()
            else:
                out.append(_ESC.get(c, c))
                self.i = j + 2

    def value(self) -> Any:
        c = self.peek()
        s = self.s
        if c == "{":
            return self.table()
        if c in "\"'" or s.startswith(("[[", "[="), self.i):
            v = self.string()
            return FileRef(v[: -len(".lua")]) if _REF.match(v) else v
        if c == "<":
            m = _ANGLE.match(s, self.i)
            if not m:
                self.fail("bad <...> token")
                raise AssertionError
            self.i = m.end()
            kind, num = m.group(1), m.group(2)
            if kind is None:
                if self.peek() != "{":
                    self.fail("anchor not followed by a table")
                return Anchor(num, self.table())
            if kind == "table":
                return LocalRef(num)
            return Mark(kind)
        m = _NUM.match(s, self.i)
        if m and m.end() > self.i:
            self.i = m.end()
            return Num(m.group())
        m = _IDENT.match(s, self.i)
        if m:
            w = m.group()
            self.i = m.end()
            if w == "true":
                return True
            if w == "false":
                return False
            if w == "nil":
                return Mark("unsupported", "format3-nil")
            if w == "math" and s.startswith(".huge", self.i):
                self.i += len(".huge")
                return math.inf
            if w == "__dcs":
                paren = self.peek() == "("
                if paren:
                    self.i += 1
                fields = self.table()
                if paren:
                    self.expect(")")
                return _marker(fields)
            self.fail(f"unexpected identifier {w}")
        self.fail("unexpected token")
        raise AssertionError

    def key(self) -> tuple[bool, Any]:
        s = self.s
        if s[self.i] == "[" and not s.startswith(("[[", "[="), self.i):
            self.i += 1
            k = self.value()
            self.expect("]")
            self.expect("=")
            if isinstance(k, FileRef):  # a key is never a ref
                k = k.path + ".lua"
            return True, _norm_key(k)
        m = _IDENT.match(s, self.i)
        if m and m.group() not in ("true", "false", "nil"):
            j = _WS.match(s, m.end())
            jj = j.end() if j else m.end()
            if s[jj : jj + 1] == "=" and s[jj + 1 : jj + 2] != "=":
                self.i = jj + 1
                return True, m.group()
        return False, None

    def table(self) -> dict[Any, Any]:
        self.expect("{")
        t: dict[Any, Any] = {}
        n = 0
        while True:
            if self.peek() == "}":
                self.i += 1
                return t
            has_key, k = self.key()
            v = self.value()
            if not has_key:
                n += 1
                k = n
            t[k] = v
            c = self.peek()
            if c in ",;":
                self.i += 1
            elif c != "}":
                self.fail("expected , or }")


@dataclass(frozen=True)
class BoolKey:
    """A boolean table key (a bare ``True`` would collide with ``1``)."""

    value: bool


def _norm_key(k: Any) -> Any:
    if isinstance(k, bool):
        return BoolKey(k)
    if isinstance(k, str | Mark):
        return k
    if is_number(k):
        f = float(k)
        return int(f) if f.is_integer() and not math.isinf(f) else f
    return Mark("key", type(k).__name__)


def _marker(fields: dict[Any, Any]) -> Any:
    """A format 4 ``__dcs{...}`` marker as a tree node."""
    kind = fields.get("kind")
    if not isinstance(kind, str):
        raise ParseError(f"__dcs marker without a kind: {fields!r}")
    if kind == "number":
        special = {"nan": math.nan, "inf": math.inf, "-inf": -math.inf, "-0": -0.0}
        return special.get(str(fields.get("value")), math.nan)
    ident: Any = fields.get("id")
    ident_s = str(int(ident)) if is_number(ident) else str(ident)
    if kind == "anchor":
        return Anchor(ident_s, fields.get("value"))
    if kind == "ref" and "id" in fields:
        return LocalRef(ident_s)
    reason = fields.get("reason")
    return Mark(kind, reason if isinstance(reason, str) else "")


def parse_dump(text: str, name: str = "<text>") -> tuple[list[Any], Any]:
    """``(assignment keys below _G, value)`` of one dump file. A file without
    a ``_G[...] =`` header (Quaggles' ``prbCoeff.lua``) is a bare value."""
    m = _HEADER.match(text)
    p = _Parser(text, name)
    keys: list[Any] = []
    if m:
        for sk, nk in _HKEY.findall(m.group(1)):
            keys.append(sk if nk == "" else _norm_key(float(nk)))
        p.i = m.end()
    if p.peek() == "":
        return keys, None
    v = p.value()
    if p.peek() not in ("", ";"):
        p.fail("trailing data")
    return keys, v


# --- flattening ---------------------------------------------------------------


def _seg(k: Any) -> str:
    if isinstance(k, BoolKey):
        return f"[{str(k.value).lower()}]"
    if isinstance(k, int):
        return f"[{k}]"
    if isinstance(k, float):
        return f"[{k!r}]"
    if isinstance(k, Mark):
        return f"[<{k.kind}>]"
    text = str(k)
    if _IDENT.fullmatch(text):
        return f".{text}"
    return '["' + text.replace("\\", "\\\\").replace('"', '\\"') + '"]'


def _key_order(k: Any) -> tuple[int, Any]:
    if isinstance(k, BoolKey):
        return (0, k.value)
    if isinstance(k, int | float):
        return (1, float(k))
    return (2, str(k))


def anchors_of(value: Any, out: dict[str, Any] | None = None) -> dict[str, Any]:
    """Every anchor of a file tree by id."""
    out = {} if out is None else out
    stack = [value]
    while stack:
        v = stack.pop()
        if isinstance(v, Anchor):
            out.setdefault(v.id, v.value)
            stack.append(v.value)
        elif isinstance(v, dict):
            stack.extend(v.values())
    return out


Resolver = Callable[[str], tuple[Any, dict[str, Any]] | None]


def flatten(
    value: Any,
    anchors: dict[str, Any],
    resolve: Resolver | None,
    prefix: str = "",
    out: dict[str, Any] | None = None,
    stack: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """``{path: leaf}`` of a file tree. Anchors and same-file refs are
    inlined (a back-reference into an enclosing table is ``cycle``); a
    cross-file ref is inlined from ``resolve`` (``unresolved-ref`` when the
    target is absent), or kept as a ``FileRef`` leaf without ``resolve``."""
    out = {} if out is None else out
    while True:
        if isinstance(value, Anchor):
            stack = stack | {f"a:{value.id}"}
            value = value.value
        elif isinstance(value, LocalRef):
            tag = f"a:{value.id}"
            if tag in stack:
                out[prefix] = CYCLE
                return out
            if value.id not in anchors:
                out[prefix] = Mark("unresolved-ref", f"#{value.id}")
                return out
            stack = stack | {tag}
            value = anchors[value.id]
        elif isinstance(value, FileRef) and resolve is not None:
            tag = f"f:{value.path}"
            if tag in stack:
                out[prefix] = CYCLE
                return out
            target = resolve(value.path)
            if target is None:
                out[prefix] = Mark("unresolved-ref", value.path)
                return out
            stack = stack | {tag}
            value, anchors = target
        else:
            break
    if isinstance(value, dict):
        if not value:
            out[prefix] = EMPTY
            return out
        for k in sorted(value, key=_key_order):
            flatten(value[k], anchors, resolve, prefix + _seg(k), out, stack)
        return out
    out[prefix] = value
    return out


# --- trees --------------------------------------------------------------------


@dataclass
class Tree:
    """A dump (``_G`` dir of ``.lua`` files); ``files`` maps the dump path
    below ``_G`` without ``.lua`` to the file."""

    root: Path  # the _G dir
    files: dict[str, Path]
    quaggles: bool = False
    dcs_version: str | None = None
    dump_format: int | None = None
    commit: str | None = None
    failures: list[tuple[str, str]] = field(default_factory=list)
    _cache: dict[str, tuple[Any, dict[str, Any]] | None] = field(default_factory=dict)

    def read(self, rel: str) -> tuple[Any, dict[str, Any]] | None:
        """``(value, anchors)`` of one file; None when absent or unreadable."""
        path = self.files.get(rel)
        if path is None:
            return None
        try:
            text = path.read_text(encoding="utf-8", errors="surrogateescape")
            value = parse_dump(text, rel)[1]
        except (ParseError, ValueError, KeyError, IndexError, RecursionError) as e:
            self.failures.append((rel, str(e)))
            return None
        return value, anchors_of(value)

    def resolve(self, ref: str) -> tuple[Any, dict[str, Any]] | None:
        """A cross-file ref target (exact case: a case-insensitive file
        system must not change the result), cached."""
        rel = ref.removeprefix("_G/")
        if rel not in self._cache:
            self._cache[rel] = self.read(rel)
        return self._cache[rel]

    def paths(self, rel: str, resolve_refs: bool = True) -> dict[str, Any] | None:
        got = self.read(rel)
        if got is None:
            return None
        value, anchors = got
        return flatten(value, anchors, self.resolve if resolve_refs else None)


def _version_text(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except FileNotFoundError:
        return None
    m = re.search(r"\d+(?:\.\d+){2,}", text)
    return m.group() if m else None


def _git_head(path: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


def _walk(directory: Path, suffix: str) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for root, dirs, files in os.walk(directory):
        dirs.sort()
        for f in files:
            if f.endswith(suffix):
                p = Path(root, f)
                rel = p.relative_to(directory).as_posix()[: -len(suffix)]
                out[rel] = p
    return dict(sorted(out.items()))


def open_tree(path: Path, quaggles: bool = False) -> Tree:
    """The dump at ``path``: a ``_G`` dir or a dir holding ``_G`` (a
    Quaggles checkout, ``.datamine``)."""
    path = path.resolve()
    if path.name != "_G" and (path / "_G").is_dir():
        g = path / "_G"
    elif path.name == "_G" and path.is_dir():
        g = path
    else:
        fail(f"no _G dump at {path}")
    if not quaggles and (g.parent / "Hooks" / "DCS-LuaExporter-hook.lua").is_file():
        quaggles = True
    files = {
        rel: p
        for rel, p in _walk(g, ".lua").items()
        if not _META.match(rel) and rel != "__DCS_VERSION__"
    }
    try:
        fmt: str | None = (
            (g / "__DUMP_FORMAT__.lua").read_text(encoding="utf-8").strip()
        )
    except FileNotFoundError:
        fmt = None
    return Tree(
        g,
        files,
        quaggles=quaggles,
        dcs_version=_version_text(g / "__DCS_VERSION__.lua"),
        dump_format=int(fmt) if fmt and fmt.isdigit() else None,
        commit=_git_head(g.parent) if quaggles else None,
    )


def fetch_quaggles(
    ref: str, dest: Path = QUAGGLES_DIR, url: str = QUAGGLES_URL
) -> Path:
    """Clone (blobless) or update Quaggles' dcs-lua-datamine at ``ref`` into
    ``dest`` (gitignored ``.datamine/quaggles``). It has no licence: it is a
    local comparison input only, never vendored or committed."""

    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], capture_output=True, text=True)

    if not (dest / ".git").exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        r = git("clone", "--filter=blob:none", "--no-checkout", url, str(dest))
        if r.returncode:
            fail(f"git clone {url}: {r.stderr.strip()}")
    if git(
        "-C", str(dest), "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"
    ).returncode:
        r = git("-C", str(dest), "fetch", "--tags", "origin")
        if r.returncode:
            fail(f"git fetch in {dest}: {r.stderr.strip()}")
    r = git("-C", str(dest), "checkout", "--detach", "--force", ref)
    if r.returncode:
        fail(f"git checkout {ref} in {dest}: {r.stderr.strip()}")
    return dest


# --- scope --------------------------------------------------------------------

# The object roots compared (dump paths below ``_G``): the longest root a file
# is under, else a top-level name matching a pattern.
ROOTS = (
    "weapons_table",
    "rockets",
    "bombs",
    "torpedoes",
    "warheads",
    "launcher",
    "Pylons",
    "db/Units",
    "db/Sensors",
    "db/Pods",
    "SchemeFMParameters",
    "SchemeEngineParameters",
    "gun_mount_templates",
    "guns_by_wstype",
    "jato_conts",
    "Weapon_containers",
    "damage_cells",
    "planes_dmg_parts",
    "planes_dmg_properties",
    "resource_by_unique_name",
    "__inheritance__",
)
ROOT_PATTERNS = ("*_DATA", "*_cells_properties")
EXCLUDED = ("db/Units/Skills",)


def _under(rel: str, root: str) -> bool:
    return rel == root or rel.startswith(root + "/")


def root_of(rel: str) -> str | None:
    """The object root of the dump file ``rel`` (below ``_G``, no ``.lua``);
    None when it is not object configuration."""
    if any(_under(rel, x) for x in EXCLUDED):
        return None
    roots = [r for r in ROOTS if _under(rel, r)]
    if roots:
        return max(roots, key=len)
    top = rel.partition("/")[0]
    return top if any(fnmatch.fnmatchcase(top, p) for p in ROOT_PATTERNS) else None


def scope_of(rel: str, all_roots: bool) -> tuple[str, str] | None:
    """``(root, category)`` of a file, None when out of scope."""
    root = root_of(rel)
    if root is None:
        if not all_roots:
            return None
        root = rel.partition("/")[0] if "/" in rel else "(top)"
    category = rel[len(root) + 1 :].rpartition("/")[0] if rel.startswith(root) else ""
    return root, category


_TWIN = re.compile(r"~\d+$")


def collision_key(rel: str) -> str:
    """Files a case-insensitive file system cannot tell apart share a key;
    our dumper's ``~N`` disambiguation suffix is dropped."""
    return _TWIN.sub("", rel).lower()


# --- explanations -------------------------------------------------------------


@dataclass
class Entry:
    cls: str
    file: str
    root: str
    category: str
    path: str
    subject: Any  # leaf, or ABSENT
    target: Any
    collision: bool
    subject_children: bool = False
    target_children: bool = False
    subject_empty_ancestor: bool = False
    target_empty_ancestor: bool = False
    rule: str | None = None

    def json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "class": self.cls,
            "file": self.file,
            "path": self.path,
        }
        if self.subject is not ABSENT:
            out["subject"] = leaf_json(self.subject)
        if self.target is not ABSENT:
            out["target"] = leaf_json(self.target)
        if self.collision:
            out["collision"] = True
        for name, flag in (
            ("subjectChildren", self.subject_children),
            ("targetChildren", self.target_children),
            ("subjectEmptyAncestor", self.subject_empty_ancestor),
            ("targetEmptyAncestor", self.target_empty_ancestor),
        ):
            if flag:
                out[name] = True
        if self.rule:
            out["rule"] = self.rule
        return out


class _Absent:
    def __repr__(self) -> str:
        return "ABSENT"


ABSENT: Any = _Absent()


def _match_side(
    m: dict[str, Any], leaf: Any, children: bool, empty_ancestor: bool
) -> bool:
    for key, want in m.items():
        if key == "absent":
            ok = (leaf is ABSENT) == bool(want)
        elif key == "present":
            ok = (leaf is not ABSENT) == bool(want)
        elif key == "value":
            ok = leaf is not ABSENT and same(leaf, want)
        elif key == "marker":
            kinds = [want] if isinstance(want, str) else list(want)
            ok = isinstance(leaf, Mark) and leaf.kind in kinds
        elif key == "detail":
            ok = isinstance(leaf, Mark) and re.search(want, leaf.detail) is not None
        elif key == "empty":
            ok = (leaf == EMPTY) == bool(want)
        elif key == "children":
            ok = children == bool(want)
        elif key == "emptyAncestor":
            ok = empty_ancestor == bool(want)
        elif key == "number":
            ok = is_number(leaf) == bool(want)
        elif key == "string":
            ok = isinstance(leaf, str) == bool(want)
        elif key == "regex":
            ok = isinstance(leaf, str) and re.search(want, leaf) is not None
        elif key == "negativeZero":
            ok = (
                is_number(leaf)
                and float(leaf) == 0
                and (math.copysign(1, float(leaf)) < 0) == bool(want)
            )
        else:
            raise ValueError(f"unknown matcher {key!r}")
        if not ok:
            return False
    return True


def _rounded14(subject: Any, target: Any) -> bool:
    """The target number is the subject's written with ``%.14g``."""
    if not (is_number(subject) and is_number(target)):
        return False
    return same(float(f"{float(subject):.14g}"), target) and not same(subject, target)


@dataclass
class Rule:
    id: str
    title: str
    reasoning: str
    classes: tuple[str, ...]
    compare: tuple[str, ...]
    file: re.Pattern[str] | None
    path: re.Pattern[str] | None
    collision: bool | None
    subject: dict[str, Any]
    target: dict[str, Any]
    rounded14g: bool
    case_only: bool

    def matches(self, e: Entry) -> bool:
        if e.cls not in self.classes:
            return False
        if self.collision is not None and e.collision != self.collision:
            return False
        if self.file is not None and not self.file.search(e.file):
            return False
        if self.path is not None and not self.path.search(e.path):
            return False
        if self.rounded14g and not _rounded14(e.subject, e.target):
            return False
        if self.case_only and not (
            isinstance(e.subject, str)
            and isinstance(e.target, str)
            and e.subject.lower() == e.target.lower()
        ):
            return False
        return _match_side(
            self.subject, e.subject, e.subject_children, e.subject_empty_ancestor
        ) and _match_side(
            self.target, e.target, e.target_children, e.target_empty_ancestor
        )


def load_rules(path: Path, compare: str) -> list[Rule]:
    """The rules of an explanations file that apply to ``compare``
    (``quaggles`` or ``dump``: the target's kind)."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rules = []
    seen: set[str] = set()
    for raw in doc.get("rules", []):
        rid = raw["id"]
        if rid in seen:
            raise ValueError(f"duplicate rule id {rid}")
        seen.add(rid)
        for required in ("title", "reasoning", "classes"):
            if required not in raw:
                raise ValueError(f"rule {rid}: no {required}")
        classes = tuple(raw["classes"])
        if bad := set(classes) - set(CLASSES):
            raise ValueError(f"rule {rid}: unknown classes {sorted(bad)}")
        applies = tuple(raw.get("compare", ("quaggles", "dump")))
        if compare not in applies:
            continue
        rules.append(
            Rule(
                rid,
                raw["title"],
                " ".join(str(raw["reasoning"]).split()),
                classes,
                applies,
                re.compile(raw["file"]) if "file" in raw else None,
                re.compile(raw["path"]) if "path" in raw else None,
                raw.get("collision"),
                raw.get("subject", {}) or {},
                raw.get("target", {}) or {},
                bool(raw.get("rounded14g", False)),
                bool(raw.get("caseOnly", False)),
            )
        )
    return rules


# --- diff ---------------------------------------------------------------------


def _has_children(sorted_paths: list[str], path: str) -> bool:
    for sep in (".", "["):
        i = bisect.bisect_left(sorted_paths, path + sep)
        if i < len(sorted_paths) and sorted_paths[i].startswith(path + sep):
            return True
    return False


def _empty_ancestor(paths: dict[str, Any], path: str) -> bool:
    """Whether a prefix of ``path`` is an empty table on that side."""
    for i in range(len(path) - 1, 0, -1):
        if path[i] in ".[" and paths.get(path[:i]) == EMPTY:
            return True
    return False


def diff_paths(
    s: dict[str, Any] | None,
    t: dict[str, Any] | None,
    file: str,
    root: str,
    category: str,
    collision: bool,
) -> list[Entry]:
    """The classified differences of one file pair (either side may be
    None: the file is absent there)."""
    s = s or {}
    t = t or {}
    out: list[Entry] = []
    s_sorted = sorted(s)
    t_sorted = sorted(t)
    for p in sorted(set(s) | set(t)):
        a = s.get(p, ABSENT)
        b = t.get(p, ABSENT)
        if a is ABSENT:
            cls = (
                "unresolved"
                if isinstance(b, Mark) and b.kind == "unresolved-ref"
                else "missing"
            )
        elif b is ABSENT:
            cls = (
                "unresolved"
                if isinstance(a, Mark) and a.kind == "unresolved-ref"
                else "added"
            )
        elif same(a, b):
            continue
        elif is_marker(a) or is_marker(b):
            cls = "unresolved"
        else:
            cls = "changed"
        e = Entry(cls, file, root, category, p, a, b, collision)
        if a is ABSENT:
            e.subject_children = _has_children(s_sorted, p)
            e.subject_empty_ancestor = _empty_ancestor(s, p)
        if b is ABSENT:
            e.target_children = _has_children(t_sorted, p)
            e.target_empty_ancestor = _empty_ancestor(t, p)
        out.append(e)
    return out


@dataclass
class Totals:
    paths_subject: int = 0
    paths_target: int = 0
    files_subject: int = 0
    files_target: int = 0
    counts: Counter[str] = field(default_factory=Counter)
    unexplained: Counter[str] = field(default_factory=Counter)

    def json(self) -> dict[str, Any]:
        return {
            "files": {"subject": self.files_subject, "target": self.files_target},
            "paths": {"subject": self.paths_subject, "target": self.paths_target},
            **{c: self.counts[c] for c in CLASSES},
            "unexplained": {c: self.unexplained[c] for c in CLASSES},
        }


@dataclass
class DiffReport:
    subject: Tree
    target: Tree
    compare: str
    rules: list[Rule]
    resolve_refs: bool
    all_roots: bool
    totals: Totals = field(default_factory=Totals)
    by_root: dict[str, Totals] = field(default_factory=lambda: defaultdict(Totals))
    by_category: dict[str, Totals] = field(default_factory=lambda: defaultdict(Totals))
    rule_counts: dict[str, Counter[str]] = field(
        default_factory=lambda: defaultdict(Counter)
    )
    rule_examples: dict[str, list[Entry]] = field(
        default_factory=lambda: defaultdict(list)
    )
    unexplained: list[Entry] = field(default_factory=list)
    unexplained_top: Counter[tuple[str, str, str]] = field(default_factory=Counter)
    added_top: Counter[tuple[str, str]] = field(default_factory=Counter)
    files_only_subject: list[str] = field(default_factory=list)
    files_only_target: list[str] = field(default_factory=list)
    collision_pairs: list[tuple[str, str]] = field(default_factory=list)
    out_of_scope: dict[str, Counter[str]] = field(default_factory=dict)
    markers: dict[str, Counter[str]] = field(default_factory=dict)
    details: list[Entry] | None = None
    examples: int = 5

    def add(self, e: Entry) -> None:
        for t in (
            self.totals,
            self.by_root[e.root],
            self.by_category[f"{e.root}|{e.category}"],
        ):
            t.counts[e.cls] += 1
        for rule in self.rules:
            if rule.matches(e):
                e.rule = rule.id
                self.rule_counts[rule.id][e.cls] += 1
                if len(self.rule_examples[rule.id]) < self.examples:
                    self.rule_examples[rule.id].append(e)
                break
        if e.rule is None and e.cls != "added":
            for t in (
                self.totals,
                self.by_root[e.root],
                self.by_category[f"{e.root}|{e.category}"],
            ):
                t.unexplained[e.cls] += 1
            self.unexplained.append(e)
            self.unexplained_top[e.cls, e.file.rpartition("/")[0], _top(e.path)] += 1
        if e.cls == "added" and e.rule is None:
            self.added_top[e.root, _top(e.path)] += 1
        if self.details is not None:
            self.details.append(e)

    def failed(self) -> bool:
        return self.totals.unexplained["missing"] > 0


def _top(path: str) -> str:
    m = re.match(r"^(\.[A-Za-z_][A-Za-z0-9_]*|\[[^\]]*\])", path)
    return m.group() if m else path


def _count_markers(paths: dict[str, Any], c: Counter[str]) -> None:
    for v in paths.values():
        if is_marker(v):
            c[f"{v.kind}:{v.detail}" if v.detail else v.kind] += 1


def _out_of_scope(
    subject: Tree, target: Tree, all_roots: bool
) -> dict[str, Counter[str]]:
    """Files outside the compared roots, by top-level dir, per side."""
    out: dict[str, Counter[str]] = {"subject": Counter(), "target": Counter()}
    for side, tree in (("subject", subject), ("target", target)):
        for rel in tree.files:
            if scope_of(rel, all_roots) is None:
                out[side][rel.split("/")[0]] += 1
    return out


def run_diff(
    subject: Tree,
    target: Tree,
    rules: list[Rule],
    compare: str,
    resolve_refs: bool = True,
    all_roots: bool = False,
    keep_details: bool = False,
) -> DiffReport:
    rep = DiffReport(subject, target, compare, rules, resolve_refs, all_roots)
    if keep_details:
        rep.details = []
    groups: dict[str, tuple[list[str], list[str]]] = defaultdict(lambda: ([], []))
    for n, tree in ((0, subject), (1, target)):
        for rel in tree.files:
            if scope_of(rel, all_roots) is not None:
                groups[collision_key(rel)][n].append(rel)
    rep.out_of_scope = _out_of_scope(subject, target, all_roots)
    rep.markers = {"subject": Counter(), "target": Counter()}
    cache_s: dict[str, dict[str, Any] | None] = {}
    cache_t: dict[str, dict[str, Any] | None] = {}

    def sp(rel: str) -> dict[str, Any] | None:
        if rel not in cache_s:
            cache_s[rel] = subject.paths(rel, resolve_refs)
        return cache_s[rel]

    def tp(rel: str) -> dict[str, Any] | None:
        if rel not in cache_t:
            cache_t[rel] = target.paths(rel, resolve_refs)
        return cache_t[rel]

    for key in sorted(groups):
        s_files, t_files = groups[key]
        collision = len(s_files) > 1 or len(t_files) > 1
        pairs: list[tuple[str | None, str | None]] = []
        if not collision:
            pairs.append(
                (s_files[0] if s_files else None, t_files[0] if t_files else None)
            )
            if s_files and t_files and s_files[0] != t_files[0]:
                collision = True
        else:
            # Pair by least difference; ties by name.
            costs = []
            for sa in s_files:
                for tb in t_files:
                    d = diff_paths(sp(sa), tp(tb), sa, "", "", True)
                    costs.append((len(d), sa, tb))
            used_s: set[str] = set()
            used_t: set[str] = set()
            for _, sa, tb in sorted(costs):
                if sa not in used_s and tb not in used_t:
                    pairs.append((sa, tb))
                    used_s.add(sa)
                    used_t.add(tb)
            pairs += [(sa, None) for sa in s_files if sa not in used_s]
            pairs += [(None, tb) for tb in t_files if tb not in used_t]
        for a, b in sorted(pairs, key=lambda p: (p[0] or "", p[1] or "")):
            rel = a or b or ""
            root, category = cast(tuple[str, str], scope_of(rel, all_roots))
            s_paths = sp(a) if a else None
            t_paths = tp(b) if b else None
            if a and b and a != b:
                rep.collision_pairs.append((a, b))
            if a is None:
                rep.files_only_target.append(rel)
            if b is None:
                rep.files_only_subject.append(rel)
            for paths, side, tot in (
                (s_paths, "subject", "paths_subject"),
                (t_paths, "target", "paths_target"),
            ):
                if paths is None:
                    continue
                _count_markers(paths, rep.markers[side])
                for tt in (
                    rep.totals,
                    rep.by_root[root],
                    rep.by_category[f"{root}|{category}"],
                ):
                    setattr(tt, tot, getattr(tt, tot) + len(paths))
                    if side == "subject":
                        tt.files_subject += 1
                    else:
                        tt.files_target += 1
            for e in diff_paths(s_paths, t_paths, rel, root, category, collision):
                rep.add(e)
            cache_s.pop(a or "", None)
            cache_t.pop(b or "", None)
    return rep


# --- typed coverage -----------------------------------------------------------

# Weapon solver keys at the top of a ``weapon_flight`` variant: blocks (every
# key below is reported) and plain values.
PRIORITY_BLOCKS = (
    "fm",
    "boost",
    "march",
    "march2",
    "booster",
    "engine",
    "autopilot",
    "ap",
    "controller",
    "actuator",
    "sensor",
    "seeker",
    "gimbal",
    "proximity_fuze",
)
PRIORITY_VALUES = (
    "Life_Time",
    "op_time",
    "KillDistance",
    "ModelData",
    "LaunchDistData",
    "PN_coeffs",
)
SERIES = ("weapon_flight", "aircraft_flight")
# Record fields that are not typed DCS values.
_STRUCTURAL = frozenset({"sourcePath", "sourcePaths", "weapon", "aircraft", "stage"})
_DROP: Any = object()  # a value the default reading leaves out


def _anchors(node: Any) -> dict[Any, Any]:
    """Every anchor of a lossless file value by id."""
    out: dict[Any, Any] = {}
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, Marker):
            if n.kind == "anchor":
                out.setdefault(n.fields.get("id"), n.fields.get("value"))
            stack.extend(v for _, v in n.fields.entries)
        elif isinstance(n, LuaTable):
            stack.extend(v for _, v in n.entries)
    return out


def plain(
    node: Any,
    dumps: DumpPaths,
    anchors: dict[Any, Any] | None = None,
    stack: frozenset[Any] = frozenset(),
) -> Any:
    """A lossless dump node as the default reading gives it (the reading
    typed values are copied from): keys ``1..n`` a list, other keys strings,
    integral floats ints, markers left out, cross-file refs inlined."""
    if isinstance(node, SourceRef):
        try:
            target = dumps.file(node.path)
        except KeyError:
            return node.path + ".lua"  # an unresolved ref stays a string
        if node.path in stack:
            return _DROP
        return plain(target, dumps, _anchors(target), stack | {node.path})
    if isinstance(node, Marker):
        ident = node.fields.get("id")
        if node.kind == "anchor":
            return plain(node.fields.get("value"), dumps, anchors, stack | {ident})
        if node.kind == "ref" and anchors and ident in anchors and ident not in stack:
            return plain(anchors[ident], dumps, anchors, stack | {ident})
        return _DROP
    if isinstance(node, LuaTable):
        items = [
            (k, c)
            for k, v in node.entries
            if not isinstance(k, Marker)
            and (c := plain(v, dumps, anchors, stack)) is not _DROP
        ]
        keys = [k for k, _ in items]
        if (
            keys
            and all(is_number(k) and float(k).is_integer() for k in keys)
            and sorted(int(k) for k in keys) == list(range(1, len(keys) + 1))
        ):
            return [v for _, v in sorted(items, key=lambda kv: float(kv[0]))]
        return {key_str(k): v for k, v in items}
    if isinstance(node, float) and node.is_integer():
        return int(node)
    return node


def _equal(a: Any, b: Any) -> bool:
    """Typed value equality (JSON numbers: ``1 == 1.0``; NaN equals NaN)."""
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(map(_equal, a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_equal(a[k], b[k]) for k in a)
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if is_number(a) and is_number(b) and math.isnan(a) and math.isnan(b):
        return True
    return bool(a == b)


def _short(v: Any) -> str:
    text = json.dumps(v, default=repr)
    return text if len(text) <= 80 else text[:77] + "..."


@dataclass
class Failure:
    series: str
    record: str
    source_path: str
    kind: str  # unresolved | differs | unmapped-field
    detail: str = ""

    def json(self) -> dict[str, Any]:
        out = {
            "series": self.series,
            "record": self.record,
            "sourcePath": self.source_path,
            "kind": self.kind,
        }
        if self.detail:
            out["detail"] = self.detail
        return out


@dataclass
class TypedReport:
    data_dir: Path
    g_dir: Path
    records: Counter[str] = field(default_factory=Counter)
    values: Counter[str] = field(default_factory=Counter)
    # Dump keys of the checked blocks: group -> typed / dump-only counts.
    typed: Counter[str] = field(default_factory=Counter)
    dump_only: Counter[str] = field(default_factory=Counter)
    examples: dict[str, str] = field(default_factory=dict)
    markers: Counter[str] = field(default_factory=Counter)
    failures: list[Failure] = field(default_factory=list)

    def failed(self) -> bool:
        return bool(self.failures)


class _Checker:
    """Checks one record against the dump."""

    def __init__(self, rep: TypedReport, dumps: DumpPaths, series: str, rid: str):
        self.rep = rep
        self.dumps = dumps
        self.series = series
        self.rid = rid

    def fail(self, sp: str, kind: str, detail: str = "") -> None:
        self.rep.failures.append(Failure(self.series, self.rid, sp, kind, detail))

    def table(self, sp: str) -> tuple[LuaTable, dict[Any, Any]] | None:
        """The dump table at ``sp`` and its file's anchors (a failure when
        it does not resolve to a table)."""
        try:
            node = self.dumps.resolve(sp)
            root = self.dumps.file(split_source_path(sp)[0])
        except (KeyError, ValueError) as e:
            self.fail(sp, "unresolved", str(e))
            return None
        if not isinstance(node, LuaTable):
            self.fail(sp, "unresolved", "not a table")
            return None
        return node, _anchors(root)

    def lookup(
        self, tables: list[tuple[str, LuaTable, dict[Any, Any]]], key: str
    ) -> tuple[str, Any] | None:
        """``(sourcePath, plain value)`` of ``key`` in the first table that
        has it (a later table, the record top of a ``client`` variant, only
        with a non-table value)."""
        for i, (sp, t, anchors) in enumerate(tables):
            raw = t.get(key, _DROP)
            if raw is _DROP:
                continue
            v = plain(raw, self.dumps, anchors)
            if v is _DROP or (i and isinstance(v, dict)):
                continue
            return sp + pointer(key), v
        return None

    def same(self, sp: str, typed: Any, dump: Any) -> None:
        self.rep.values[self.series] += 1
        if not _equal(typed, dump):
            self.fail(sp, "differs", f"typed {_short(typed)}, dump {_short(dump)}")

    def keys(
        self, label: str, t: LuaTable, sp: str, covered: set[str], only: Iterable[str]
    ) -> None:
        """Report the string keys of ``t`` (``only`` them when given) as
        typed or dump-only."""
        wanted = set(only)
        for k, v in t.entries:
            if not isinstance(k, str) or (wanted and k not in wanted):
                continue
            group = f"{self.series} {label}/{k}"
            if k in covered:
                self.rep.typed[group] += 1
            elif isinstance(v, Marker) and v.kind not in ("anchor", "ref"):
                self.rep.markers[v.kind] += 1
            else:
                self.rep.dump_only[group] += 1
                self.rep.examples.setdefault(group, f"{sp}{pointer(k)}")

    def untyped_block(self, label: str, sp: str) -> None:
        group = f"{self.series} {label} (block not typed)"
        self.rep.dump_only[group] += 1
        self.rep.examples.setdefault(group, sp)

    def block(
        self,
        label: str,
        block: dict[str, Any],
        specs: tuple[F, ...],
        sources: list[str],
        all_keys: bool,
        skip: Iterable[str] = (),
    ) -> set[str] | None:
        """Check the typed fields of ``block`` read from the dump tables at
        ``sources`` (first match wins); report the keys of the first table
        (all of them, or only the spec keys). The covered DCS keys."""
        tables = []
        for sp in sources:
            got = self.table(sp)
            if got is None:
                return None
            tables.append((sp, *got))
        covered: set[str] = set()
        skipped = _STRUCTURAL | set(skip)
        for name, value in block.items():
            if name in skipped:
                continue
            if name == aircraft_flight.TABLE.name:
                found = self.lookup(tables, aircraft_flight.TABLE.key)
                if found is None:
                    self.fail(sources[0], "unresolved", aircraft_flight.TABLE.key)
                else:
                    covered.add(aircraft_flight.TABLE.key)
                    self.same(found[0], [_row_values(r) for r in value], found[1])
                continue
            cands = [f for f in specs if f.name == name]
            if not cands:
                self.fail(sources[0], "unmapped-field", f"{label}.{name}")
                continue
            # The last spec whose key fits wins (``typed_block``).
            for f in reversed(cands):
                found = self.lookup(tables, f.key)
                if found is not None and fits(f.kind, found[1]):
                    covered.add(f.key)
                    self.same(found[0], value, found[1])
                    break
            else:
                keys = ",".join(f.key for f in cands)
                self.fail(sources[0], "unresolved", f"{label}.{name} ({keys})")
        spec_keys = () if all_keys else [f.key for f in specs]
        self.keys(label, tables[0][1], sources[0], covered, spec_keys)
        return covered

    def weapon(self, rec: dict[str, Any]) -> None:
        sp = rec["sourcePath"]
        path, keys = split_source_path(sp)
        sources = [sp, f"{path}#"] if keys else [sp]
        skip = {*weapon_flight.BLOCKS, "pnCoefficients", "launchEnvelopes"}
        covered = self.block("top", rec, weapon_flight.TOP, sources, False, skip)
        if covered is None:
            return
        tables = [(s, *got) for s in sources if (got := self.table(s))]
        if "pnCoefficients" in rec:
            found = self.lookup(tables, "PN_coeffs")
            if found is None:
                self.fail(sp, "unresolved", "PN_coeffs")
            else:
                covered.add("PN_coeffs")
                pn = rec["pnCoefficients"]
                flat = [len(pn), *(x for e in pn for x in (e["distanceM"], e["gain"]))]
                self.same(found[0], flat, found[1])
        for env in rec.get("launchEnvelopes", []):
            alts, speeds = env["altitudesM"], env["speedsMs"]
            for key, grid in weapon_flight.LAUNCH_TABLES:
                if grid not in env:
                    continue
                covered.add(key)
                at = env["sourcePath"] + pointer(key)
                try:
                    node = self.dumps.resolve(at)
                    anchors = _anchors(self.dumps.file(split_source_path(at)[0]))
                except (KeyError, ValueError) as e:
                    self.fail(at, "unresolved", str(e))
                    continue
                flat = [len(alts), len(speeds), *speeds]
                for alt, row in zip(alts, env[grid], strict=True):
                    flat += [alt, *row]
                self.same(at, flat, plain(node, self.dumps, anchors))
        typed_blocks: set[str] = set()
        variant, anchors = tables[0][1], tables[0][2]
        for name in weapon_flight.BLOCKS:
            value = rec.get(name)
            for b in value if isinstance(value, list) else [value] if value else []:
                typed_blocks.add(b["sourcePath"])
                specs = weapon_flight.SPECS[name]
                self.block(name, b, specs, [b["sourcePath"]], True, {"startTime"})
                if "startTime" in b:
                    self.start_time(b, variant, anchors)
        # Solver keys of the variant (and plain values of the record top).
        for k, v in variant.entries:
            if not isinstance(k, str):
                continue
            where = f"{sp}{pointer(k)}"
            if (
                k in PRIORITY_BLOCKS
                and where not in typed_blocks
                and isinstance(plain(v, self.dumps, anchors), dict)
            ):
                self.untyped_block(k, where)
        top_keys = {k for t in tables for k, _ in t[1].entries if isinstance(k, str)}
        for k in sorted(top_keys & set(PRIORITY_VALUES)):
            group = f"{self.series} top/{k}"
            if k in covered:
                self.rep.typed[group] += 1
            else:
                self.rep.dump_only[group] += 1
                self.rep.examples.setdefault(group, f"{sp}{pointer(k)}")

    def start_time(
        self, stage: dict[str, Any], variant: LuaTable, anchors: dict[Any, Any]
    ) -> None:
        """A stage's ``startTime`` is a ``<stage>_start`` of a variant block."""
        key = f"{stage['stage']}_start"
        values = [
            v
            for _, b in variant.entries
            if isinstance(pb := plain(b, self.dumps, anchors), dict)
            and is_number(v := pb.get(key))
        ]
        self.rep.values[self.series] += 1
        if not any(_equal(stage["startTime"], v) for v in values):
            self.fail(
                stage["sourcePath"],
                "differs" if values else "unresolved",
                f"startTime {_short(stage['startTime'])}, dump {key} {_short(values)}",
            )

    def aircraft(self, rec: dict[str, Any]) -> None:
        typed: set[str] = set()
        top_skip = {
            "aircraft",
            "sourcePaths",
            *(n for n, _, _ in aircraft_flight.BLOCKS),
        }
        top = f"{rec['sourcePaths'][0]}#"
        self.block("top", rec, aircraft_flight.MASSES, [top], False, top_skip)
        for name, keys, specs in aircraft_flight.BLOCKS:
            b: Any = rec
            for part in name.split("."):
                b = b.get(part) if isinstance(b, dict) else None
            if not isinstance(b, dict):
                continue
            typed.add(name)
            skip = ("engine",) if name == "helicopter" else ()
            self.block(name, b, specs, [b["sourcePath"]], bool(keys), skip)
        # Flight blocks of the unit record without a typed block.
        path = rec["sourcePaths"][0]
        for name, keys, _ in aircraft_flight.BLOCKS:
            if keys and name not in typed and self.is_table(path, keys):
                self.untyped_block("/".join(keys), f"{path}#{pointer(*keys)}")
        sfm = self.resolve(path, ("SFM_Data",))
        known = {k[1] for _, k, _ in aircraft_flight.BLOCKS if k[:1] == ("SFM_Data",)}
        if isinstance(sfm, LuaTable):
            for k, _ in sfm.entries:
                if (
                    isinstance(k, str)
                    and k not in known
                    and self.is_table(path, ("SFM_Data", k))
                ):
                    self.untyped_block(
                        f"SFM_Data/{k}", f"{path}#{pointer('SFM_Data', k)}"
                    )

    def resolve(self, path: str, keys: tuple[str, ...]) -> Any:
        try:
            return self.dumps.resolve(f"{path}#{pointer(*keys)}")
        except (KeyError, ValueError):
            return None

    def is_table(self, path: str, keys: tuple[str, ...]) -> bool:
        return isinstance(self.resolve(path, keys), LuaTable)


def _row_values(row: dict[str, Any]) -> list[Any]:
    """A named ``table_data`` row's values in DCS column order (records
    are written with sorted keys)."""
    for columns in (
        *aircraft_flight.AERO_ROW.values(),
        *aircraft_flight.ENGINE_ROW.values(),
    ):
        if set(columns) == set(row):
            return [row[c] for c in columns]
    return list(row.values())


def run_typed(data_dir: Path, g_dir: Path) -> TypedReport:
    """Check the flight records of ``data_dir`` against the dump ``g_dir``."""
    data_dir = data_dir.resolve()
    g_dir = open_tree(g_dir).root
    dirs = {s: data_dir / s for s in SERIES if (data_dir / s).is_dir()}
    if not dirs:
        fail(f"{data_dir}: no {' or '.join(SERIES)} records")
    rep = TypedReport(data_dir, g_dir)
    dumps = DumpPaths(g_dir)
    for series, d in dirs.items():
        for f in sorted(d.glob("*.json")):
            rec = json.loads(f.read_text(encoding="utf-8"))
            rep.records[series] += 1
            check = _Checker(rep, dumps, series, f.stem)
            if series == "weapon_flight":
                check.weapon(rec)
            else:
                check.aircraft(rec)
    return rep


# --- output -------------------------------------------------------------------


def _tree_json(t: Tree) -> dict[str, Any]:
    out: dict[str, Any] = {
        "path": _display(t.root),
        "kind": "quaggles" if t.quaggles else "dump",
        "files": len(t.files),
    }
    for k, v in (
        ("dcsVersion", t.dcs_version),
        ("dumpFormat", t.dump_format),
        ("commit", t.commit),
    ):
        if v is not None:
            out[k] = v
    if t.failures:
        out["failures"] = [{"file": f, "error": e} for f, e in sorted(t.failures)]
    return out


def _display(p: Path) -> str:
    try:
        return p.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def diff_json(rep: DiffReport) -> dict[str, Any]:
    rules = []
    for r in rep.rules:
        c = rep.rule_counts.get(r.id, Counter())
        rules.append(
            {
                "id": r.id,
                "title": r.title,
                **{cls: c[cls] for cls in CLASSES},
                "examples": [e.json() for e in rep.rule_examples.get(r.id, [])],
            }
        )
    return {
        "command": "diff",
        "subject": _tree_json(rep.subject),
        "target": _tree_json(rep.target),
        "compare": rep.compare,
        "resolveRefs": rep.resolve_refs,
        "scope": "all" if rep.all_roots else "object-roots",
        "outOfScopeFiles": {
            k: dict(sorted(v.items())) for k, v in rep.out_of_scope.items()
        },
        "totals": rep.totals.json(),
        "failed": rep.failed(),
        "byRoot": {k: v.json() for k, v in sorted(rep.by_root.items())},
        "byCategory": {k: v.json() for k, v in sorted(rep.by_category.items())},
        "files": {
            "onlySubject": sorted(rep.files_only_subject),
            "onlyTarget": sorted(rep.files_only_target),
            "collisionPairs": [list(p) for p in sorted(rep.collision_pairs)],
        },
        "markers": {k: dict(sorted(v.items())) for k, v in sorted(rep.markers.items())},
        "rules": rules,
        "unexplainedByTopKey": [
            {"class": c, "dir": d, "key": k, "count": n}
            for (c, d, k), n in sorted(
                rep.unexplained_top.items(), key=lambda x: (-x[1], x[0])
            )
        ],
        "addedByTopKey": [
            {"root": r, "key": k, "count": n}
            for (r, k), n in sorted(rep.added_top.items(), key=lambda x: (-x[1], x[0]))
        ],
        "unexplained": [e.json() for e in rep.unexplained],
    }


def _row(cells: Iterable[Any]) -> str:
    return "| " + " | ".join(str(c) for c in cells) + " |"


def _totals_rows(items: Iterable[tuple[str, Totals]]) -> list[str]:
    lines = [
        _row(
            [
                "",
                "files S/T",
                "paths S/T",
                "missing",
                "added",
                "changed",
                "unresolved",
                "unexplained missing",
            ]
        ),
        _row(["---"] * 8),
    ]
    for name, t in items:
        lines.append(
            _row(
                [
                    f"`{name}`",
                    f"{t.files_subject}/{t.files_target}",
                    f"{t.paths_subject:,}/{t.paths_target:,}",
                    f"{t.counts['missing']:,}",
                    f"{t.counts['added']:,}",
                    f"{t.counts['changed']:,}",
                    f"{t.counts['unresolved']:,}",
                    f"{t.unexplained['missing']:,}",
                ]
            )
        )
    return lines


def diff_markdown(rep: DiffReport, limit: int = 40) -> str:
    j = _tree_json
    s, t = j(rep.subject), j(rep.target)
    lines = [
        "# Coverage diff",
        "",
        f"- Subject: `{s['path']}` ({s['kind']}, DCS {s.get('dcsVersion', '?')}, "
        f"format {s.get('dumpFormat', '?')}, {s['files']} files)",
        f"- Target: `{t['path']}` ({t['kind']}, DCS {t.get('dcsVersion', '?')}"
        + (f", commit {t['commit'][:12]}" if "commit" in t else "")
        + f", {t['files']} files)",
        f"- Scope: {'all roots' if rep.all_roots else 'object roots'}; "
        f"cross-file refs {'inlined' if rep.resolve_refs else 'compared as refs'}",
        f"- Result: **{'FAIL' if rep.failed() else 'ok'}** "
        f"({rep.totals.unexplained['missing']:,} unexplained missing paths)",
        "",
        "## Totals",
        "",
        *_totals_rows([("all", rep.totals)]),
        "",
        "## By root",
        "",
        *_totals_rows(sorted(rep.by_root.items())),
        "",
        "## By category",
        "",
        *_totals_rows(
            (k.replace("|", "/").rstrip("/"), v)
            for k, v in sorted(rep.by_category.items())
            if any(v.counts.values())
        ),
        "",
    ]
    if rep.rules:
        lines += [
            "## Explanation rules",
            "",
            _row(["rule", "missing", "added", "changed", "unresolved", "title"]),
            _row(["---"] * 6),
        ]
        for r in rep.rules:
            c = rep.rule_counts.get(r.id, Counter())
            lines.append(_row([f"`{r.id}`", *(f"{c[x]:,}" for x in CLASSES), r.title]))
        lines.append("")
    files = rep.files_only_subject, rep.files_only_target
    lines += [
        "## Files",
        "",
        f"- Paired by case-insensitive name: {len(rep.collision_pairs)} "
        + ", ".join(f"`{a}`~`{b}`" for a, b in sorted(rep.collision_pairs)[:limit]),
        f"- Only in subject: {len(files[0])} "
        + ", ".join(f"`{f}`" for f in sorted(files[0])[:limit]),
        f"- Only in target: {len(files[1])} "
        + ", ".join(f"`{f}`" for f in sorted(files[1])[:limit]),
        "",
        "## Markers",
        "",
    ]
    for side, c in sorted(rep.markers.items()):
        lines.append(
            f"- {side}: "
            + (", ".join(f"`{k}` {n:,}" for k, n in sorted(c.items())) or "none")
        )
    lines.append("")
    if rep.unexplained:
        lines += [
            "## Unexplained",
            "",
            _row(["class", "dir", "top key", "paths"]),
            _row(["---"] * 4),
        ]
        for (cls, d, k), n in sorted(
            rep.unexplained_top.items(), key=lambda x: (-x[1], x[0])
        )[:limit]:
            lines.append(_row([cls, f"`{d}`", f"`{k}`", f"{n:,}"]))
        lines += ["", "First entries:", ""]
        for e in rep.unexplained[:limit]:
            lines.append(
                f"- {e.cls} `{e.file}{e.path}`: subject "
                f"`{json.dumps(leaf_json(e.subject)) if e.subject is not ABSENT else '-'}`, target "
                f"`{json.dumps(leaf_json(e.target)) if e.target is not ABSENT else '-'}`"
            )
        lines.append("")
    return "\n".join(lines)


def typed_json(rep: TypedReport) -> dict[str, Any]:
    groups = sorted({*rep.typed, *rep.dump_only})
    return {
        "command": "typed",
        "data": _display(rep.data_dir),
        "dump": _display(rep.g_dir),
        "records": dict(sorted(rep.records.items())),
        "valuesChecked": dict(sorted(rep.values.items())),
        "keys": {
            g: {
                "typed": rep.typed[g],
                "dumpOnly": rep.dump_only[g],
                **({"example": rep.examples[g]} if g in rep.examples else {}),
            }
            for g in groups
        },
        "markers": dict(sorted(rep.markers.items())),
        "failureKinds": dict(sorted(Counter(f.kind for f in rep.failures).items())),
        "failures": [f.json() for f in rep.failures],
        "failed": rep.failed(),
    }


def typed_markdown(rep: TypedReport, limit: int = 80) -> str:
    records = ", ".join(
        f"{s} {rep.records[s]} records, {rep.values[s]:,} typed values"
        for s in SERIES
        if rep.records[s]
    )
    lines = [
        "# Typed coverage of flight records",
        "",
        f"- Data: `{_display(rep.data_dir)}`; dump: `{_display(rep.g_dir)}`",
        f"- Checked: {records}",
        f"- Result: **{'FAIL' if rep.failed() else 'ok'}** ({len(rep.failures)} "
        "failures: paths that do not resolve, typed values differing from the dump)",
        f"- Dump keys of the checked blocks: {sum(rep.typed.values()):,} typed, "
        f"{sum(rep.dump_only.values()):,} only in the dump (not a failure)"
        + (
            "; markers (no value to type): "
            + ", ".join(f"`{k}` {n}" for k, n in sorted(rep.markers.items()))
            if rep.markers
            else ""
        ),
        "",
    ]
    if rep.failures:
        lines += ["## Failures", ""]
        for f in rep.failures[:limit]:
            detail = f": {f.detail}" if f.detail else ""
            lines.append(
                f"- {f.kind} `{f.series}/{f.record}` `{f.source_path}`{detail}"
            )
        lines.append("")
    groups = sorted({*rep.typed, *rep.dump_only}, key=lambda g: (-rep.dump_only[g], g))
    if groups:
        lines += [
            "## Dump keys by block",
            "",
            _row(["block/key", "typed", "dump only", "example"]),
            _row(["---"] * 4),
        ]
        for g in groups[:limit]:
            example = f"`{rep.examples[g]}`" if g in rep.examples else ""
            lines.append(_row([f"`{g}`", rep.typed[g], rep.dump_only[g], example]))
        if len(groups) > limit:
            lines.append(f"\n{len(groups) - limit} more in the JSON report.")
        lines.append("")
    return "\n".join(lines)


def _write(path: Path | None, text: str) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser(
        "diff",
        help="Diff object paths of SUBJECT against a target tree or Quaggles.",
    )
    d.add_argument(
        "subject", type=Path, help="Our dump (a _G dir or a dir holding _G)."
    )
    d.add_argument(
        "target", type=Path, nargs="?", help="Another dump (e.g. a previous one)."
    )
    d.add_argument(
        "--quaggles", type=Path, help="A Quaggles dcs-lua-datamine checkout as target."
    )
    d.add_argument(
        "--quaggles-ref",
        help=f"Clone/update Quaggles into {_display(QUAGGLES_DIR)} at this tag or "
        f"sha and use it as target (pinned: {QUAGGLES_REF[:7]}).",
    )
    d.add_argument("--quaggles-url", default=QUAGGLES_URL, help=argparse.SUPPRESS)
    d.add_argument(
        "--explanations",
        type=Path,
        help="Explanation rules (default: coverage-explanations.yaml for Quaggles, none otherwise).",
    )
    d.add_argument(
        "--no-resolve-refs",
        action="store_true",
        help="Compare cross-file refs as values.",
    )
    d.add_argument(
        "--all-roots",
        action="store_true",
        help="Compare every file, not only object roots.",
    )
    d.add_argument("--details", type=Path, help="Write every difference as JSON lines.")
    for p in (
        d,
        sub.add_parser(
            "typed", help="Check flight records' typed values against the dump."
        ),
    ):
        p.add_argument("--json", type=Path, help="Write the JSON report here.")
        p.add_argument("--markdown", type=Path, help="Write the Markdown summary here.")
        p.add_argument(
            "--advisory", action="store_true", help="Exit 0 even when the check fails."
        )
    t = sub.choices["typed"]
    t.add_argument(
        "data",
        type=Path,
        nargs="?",
        default=REFERENCE_DATA_DIR / LATEST,
        help="A data dir with weapon_flight/ and/or aircraft_flight/ "
        f"(default {_display(REFERENCE_DATA_DIR / LATEST)}).",
    )
    t.add_argument(
        "--g-dir",
        type=Path,
        default=CACHED_G_DIR,
        help=f"The _G dump (default {_display(CACHED_G_DIR)}).",
    )
    args = parser.parse_args(argv)
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 10000))
    if args.command == "typed":
        trep = run_typed(args.data, args.g_dir)
        _write(args.json, json.dumps(typed_json(trep), indent=2, sort_keys=True) + "\n")
        md = typed_markdown(trep)
        _write(args.markdown, md + "\n")
        if args.markdown is None:
            print(md)
        failed = trep.failed()
    else:
        sources = [
            x for x in (args.target, args.quaggles, args.quaggles_ref) if x is not None
        ]
        if len(sources) != 1:
            parser.error("give exactly one of TARGET, --quaggles, --quaggles-ref")
        subject = open_tree(args.subject)
        if args.quaggles_ref:
            target = open_tree(
                fetch_quaggles(args.quaggles_ref, url=args.quaggles_url), quaggles=True
            )
        elif args.quaggles:
            target = open_tree(args.quaggles, quaggles=True)
        else:
            target = open_tree(args.target)
        compare = "quaggles" if target.quaggles else "dump"
        expl = args.explanations or (EXPLANATIONS if compare == "quaggles" else None)
        rules = load_rules(expl, compare) if expl else []
        rep = run_diff(
            subject,
            target,
            rules,
            compare,
            resolve_refs=not args.no_resolve_refs,
            all_roots=args.all_roots,
            keep_details=args.details is not None,
        )
        _write(args.json, json.dumps(diff_json(rep), indent=2, sort_keys=True) + "\n")
        md = diff_markdown(rep)
        _write(args.markdown, md + "\n")
        if args.details is not None:
            _write(
                args.details,
                "".join(
                    json.dumps(e.json(), sort_keys=True) + "\n"
                    for e in rep.details or []
                ),
            )
        if args.markdown is None:
            print(md)
        for f, e in sorted({*subject.failures, *target.failures}):
            print(f"WARNING: unreadable {f}: {e}", file=sys.stderr)
        failed = rep.failed()
    if failed:
        print(
            "coverage: check failed" + (" (advisory)" if args.advisory else ""),
            file=sys.stderr,
        )
    return 1 if failed and not args.advisory else 0


if __name__ == "__main__":
    raise SystemExit(main())
