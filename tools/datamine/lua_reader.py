"""Reader for the DCS ``_G`` dump files, and the one Lua sandbox the datamine uses.

Each dump file is one assignment into the global table::

    _G["db"]["Units"]["Planes"]["Plane"]["#Index"] = { ... }

Each file runs in the sandbox (no libraries, instruction and memory limits) with
a capturing ``_G`` as its only global; the assigned value becomes plain Python
values. Shared records the dumper wrote as path strings
(``warhead = "_G/warheads/AN_M65.lua"``) are replaced by the referenced record
(unless the reader is made with ``link_refs=False``); the referenced files of a
batch are read together.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lupa import LuaRuntime

from .common import fail, pmap, read_text

_REF = re.compile(r"^_G/.+\.lua$")

INSTRUCTION_LIMIT = 50_000_000
MEMORY_LIMIT = 1 << 30

# exec(text, name, env, limit): run a text chunk with ``env`` as its only
# globals, aborting after ``limit`` instructions. capture(): an env whose ``_G``
# records the first assignment made anywhere under it (missing keys index as
# fresh nested tables), plus the state table holding that value and the count.
_LUA = """
local load, pcall, sethook, tostring, error = load, pcall, debug.sethook, tostring, error
local setmetatable, rawset = setmetatable, rawset
local function exec(text, name, env, limit)
    local fn, err = load(text, name, "t", env)
    if not fn then return false, err end
    sethook(function() error("instruction limit exceeded") end, "", limit)
    local ok, run_err = pcall(fn)
    sethook()
    if not ok then return false, tostring(run_err) end
    return true, env
end
local function capture()
    local state = {count = 0}
    local mt = {}
    mt.__index = function(t, k)
        local v = setmetatable({}, mt)
        rawset(t, k, v)
        return v
    end
    mt.__newindex = function(t, k, v)
        rawset(t, k, v)
        state.count = state.count + 1
        if state.count == 1 then state.value = v end
    end
    return {_G = setmetatable({}, mt)}, state
end
return exec, capture
"""


@dataclass(frozen=True)
class _Lua:
    runtime: LuaRuntime
    exec: Callable[..., tuple[bool, Any]]
    capture: Any
    table_type: type[Any]


@functools.cache
def _lua() -> _Lua:
    """The shared runtime. Not thread-safe: run Lua on the main thread only."""
    runtime = LuaRuntime(encoding="utf-8", register_eval=False, max_memory=MEMORY_LIMIT)
    exec_fn, capture = runtime.execute(_LUA)
    return _Lua(runtime, exec_fn, capture, type(runtime.table()))


def lua_table_type() -> type[Any]:
    return _lua().table_type


def lua_execute(code: str) -> Any:
    """Run trusted helper ``code`` (not dump or install text) in the shared runtime."""
    return _lua().runtime.execute(code)


def sandbox_exec(text: str, name: str, env: Any = None) -> tuple[bool, Any]:
    """Run a Lua chunk with ``env`` (a Lua table; a fresh empty one when None)
    as its only globals. ``(True, env)`` on success, ``(False, error)`` when it
    fails to load, raises, or exceeds the instruction limit."""
    lua = _lua()
    return lua.exec(
        text, name, lua.runtime.table() if env is None else env, INSTRUCTION_LIMIT
    )


class _Ref(str):
    """A path-string ref awaiting its target record."""


_MISSING = object()


@dataclass
class ReadStats:
    failures: list[tuple[str, str]] = field(default_factory=list)
    unresolved_refs: list[tuple[str, str]] = field(default_factory=list)


def _to_py(value: Any, table: type[Any], refs: set[str] | None) -> Any:
    """``value`` as plain Python values; path-string refs become ``_Ref`` and
    are added to ``refs`` unless it is None."""
    if isinstance(value, table):
        items = list(value.items())
        if items and _is_consecutive_array([k for k, _ in items]):
            return [
                _to_py(v, table, refs) for _, v in sorted(items, key=lambda kv: kv[0])
            ]
        return {key_str(k): _to_py(v, table, refs) for k, v in items}
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if refs is not None and isinstance(value, str) and _REF.match(value):
        refs.add(value)
        return _Ref(value)
    return value


def lua_to_py(value: Any) -> Any:
    """A Lua value as plain Python values (a table with keys 1..n is a list,
    any other a dict with string keys; integral floats are ints)."""
    return _to_py(value, _lua().table_type, None)


class LuaReader:
    """Reads ``_G`` dump files into plain Python values. With ``link_refs``
    off, path-string refs stay strings and their targets are not read.
    ``texts``: file texts by path, shared by readers of one dump so a file
    is read from disk once."""

    def __init__(
        self,
        g_dir: Path | None = None,
        link_refs: bool = True,
        texts: dict[Path, str] | None = None,
    ) -> None:
        self.g_dir = g_dir
        self.link_refs = link_refs
        self.texts = texts
        self.stats = ReadStats()
        self._targets: dict[str, Any] = {}  # ref -> (value, has refs) or _MISSING
        self._table = lua_table_type()
        self._pending: set[str] = set()

    def read_file(self, path: Path) -> Any | None:
        """One file's value; None when it is absent (or fails, recorded in ``stats``)."""
        try:
            text = self._text(path)
        except FileNotFoundError:
            return None
        return self._finish([(path, *self._parse(path, text))])[0][1]

    def read_many(self, paths: list[Path]) -> list[tuple[Path, Any | None]]:
        """Read ``paths`` on the I/O pool, parsing each as it arrives."""
        parsed = [
            (p, *self._parse(p, t))
            for p, t in zip(paths, pmap(self._text, paths), strict=True)
        ]
        return self._finish(parsed)

    def _text(self, path: Path) -> str:
        if self.texts is None:
            return read_text(path)
        text = self.texts.get(path)
        if text is None:
            text = self.texts[path] = read_text(path)
        return text

    def _text_or_none(self, path: Path | None) -> str | None:
        if path is None:
            return None
        try:
            return self._text(path)
        except FileNotFoundError:
            return None

    def _finish(
        self, parsed: list[tuple[Path, Any, bool]]
    ) -> list[tuple[Path, Any | None]]:
        self._load_targets()
        return [
            (p, self._link(v, str(p), frozenset()) if has_ref else v)
            for p, v, has_ref in parsed
        ]

    def _parse(self, path: Path, text: str) -> tuple[Any | None, bool]:
        """(value assigned by one dump file or None, whether it holds refs)."""
        name = str(path)
        ok, value, count = self._run(text, name)
        if not ok:
            self.stats.failures.append((name, str(value)))
            return None, False
        if count != 1:
            self.stats.failures.append(
                (name, f"expected one _G assignment, found {count}")
            )
            return None, False
        refs: set[str] | None = set() if self.link_refs else None
        py = _to_py(value, self._table, refs)
        if refs:
            self._pending |= refs
        return py, bool(refs)

    @staticmethod
    def _run(text: str, name: str) -> tuple[bool, Any, int]:
        env, state = _lua().capture()
        ok, err = sandbox_exec(text, name, env)
        return ok, (state["value"] if ok else err), state["count"]

    def _load_targets(self) -> None:
        """Read every pending ref target (and the refs those hold) in batches."""
        while batch := sorted(self._pending - self._targets.keys()):
            self._pending.clear()
            paths = [
                self.g_dir / r[len("_G/") :] if self.g_dir else None for r in batch
            ]
            for ref, path, text in zip(
                batch, paths, pmap(self._text_or_none, paths), strict=True
            ):
                if text is None or path is None:
                    self._targets[ref] = _MISSING
                    continue
                value, has_ref = self._parse(path, text)
                self._targets[ref] = (value, has_ref)
        self._pending.clear()

    def _link(self, value: Any, source: str, stack: frozenset[str]) -> Any:
        """``value`` with every ``_Ref`` replaced by its target record (in place);
        missing and cyclic refs stay strings and are recorded as unresolved."""
        if isinstance(value, _Ref):
            target = self._targets.get(value, _MISSING)
            if target is _MISSING or value in stack:
                self.stats.unresolved_refs.append((source, str(value)))
                return str(value)
            record, has_ref = target
            if has_ref:
                record = self._link(record, value, stack | {value})
                self._targets[value] = (record, False)
            return record
        if isinstance(value, dict):
            for k, v in value.items():
                if isinstance(v, (dict, list, _Ref)):
                    value[k] = self._link(v, source, stack)
        elif isinstance(value, list):
            for i, v in enumerate(value):
                if isinstance(v, (dict, list, _Ref)):
                    value[i] = self._link(v, source, stack)
        return value


def _is_consecutive_array(keys: list[Any]) -> bool:
    n = len(keys)
    seen: set[int] = set()
    for k in keys:
        if isinstance(k, bool) or not isinstance(k, (int, float)) or k != int(k):
            return False
        if not 1 <= k <= n:
            return False
        seen.add(int(k))
    return len(seen) == n


def key_str(key: Any) -> str:
    """A Lua table key as the reader writes it: ``true``/``false``, an
    integral float as an integer."""
    if isinstance(key, bool):
        return "true" if key else "false"
    if isinstance(key, float) and key.is_integer():
        return str(int(key))
    return str(key)


def as_number(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


_NUMERIC_STRING = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def as_numeric(value: Any) -> float | int | None:
    """``as_number``, also reading a decimal numeric string (``"6103"``).

    Only for fields DCS is known to write either way (the mission editor's
    ``MaxFuelWeight`` and friends); ``as_number`` stays strict elsewhere.
    """
    if isinstance(value, str):
        text = value.strip()
        if not _NUMERIC_STRING.fullmatch(text):
            return None
        return int(text) if text.lstrip("+-").isdigit() else float(text)
    return as_number(value)


def first_number(*values: Any) -> float | int | None:
    """The first argument that is a number (a real 0 counts)."""
    for v in values:
        n = as_number(v)
        if n is not None:
            return n
    return None


def km(metres: Any) -> float | None:
    """A number of metres in kilometres, to the metre; None for a non-number."""
    n = as_number(metres)
    return round(n / 1000, 3) if n is not None else None


def as_string(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def first_string(*values: Any) -> str | None:
    """The first argument that is a non-empty string."""
    for v in values:
        if isinstance(v, str) and v:
            return v
    return None


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_flag(value: Any, where: str) -> bool | None:
    """A DCS boolean flag as set; None when DCS does not set it. Any other
    value fails (``where`` names it)."""
    if value is not None and not isinstance(value, bool):
        fail(f"{where} is not a boolean: {value!r}")
    return value


def array_entries(value: Any, mixed: bool = False) -> list[Any]:
    """View a Lua value as an array ([] when it is not one).

    A table with holes parses as an object with numeric string keys; its
    entries are returned in numeric order. ``mixed``: a table with named keys
    too (a ``WS`` table) yields its numeric-keyed entries instead of [].
    """
    if isinstance(value, list):
        return value
    if not isinstance(value, dict):
        return []
    if mixed:
        keys = [k for k in value if k.isdigit()]
    elif value and all(k.isdigit() for k in value):
        keys = list(value)
    else:
        return []
    return [value[k] for k in sorted(keys, key=int)]


def number_tuple(value: Any, n: int) -> list[Any] | None:
    """An array of exactly ``n`` numbers, else None."""
    items = array_entries(value)
    if len(items) == n and all(as_number(v) is not None for v in items):
        return list(items)
    return None


def strings_of(value: Any) -> list[str]:
    """String entries of an array-ish value, without ``Redacted`` markers."""
    return [v for v in array_entries(value) if isinstance(v, str) and v != "Redacted"]
