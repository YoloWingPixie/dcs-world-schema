"""Paths into the ``_G`` dump, and their check against it.

A record's ``sourcePaths`` are dump paths: ``_G/<dump file path without
.lua>`` (``_G/weapons_table/weapons/missiles/AIM_120C``). A typed block's
``sourcePath`` is ``<dump path>#<pointer>``: the pointer is ``""`` (the
file's whole value) or ``/``-separated segments, one per Lua key from the
file's value down: a string key with RFC 6901 escaping (``~`` -> ``~0``,
``/`` -> ``~1``) plus ``~2`` for a leading ``[``; any other key as its Lua
literal in brackets (``[1]``, ``[true]``, ``[0.5]``, ``[inf]``).

``DumpPaths`` resolves both against the dump as ``LuaReader.read_source``
reads it (losslessly: key types kept, anchors and same-file refs followed,
cross-file refs read from their file). The extraction fails when an emitted
path does not resolve (``check``).
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .lua_reader import LuaReader, LuaTable, Marker, SourceRef

# Integral doubles at or above this magnitude are written as floats.
_EXACT_INT = 2**53


def pointer_segment(key: Any) -> str:
    """One pointer segment of the Lua key ``key`` (``str``, ``bool``, ``int``
    or ``float``)."""
    if isinstance(key, str):
        seg = key.replace("~", "~0").replace("/", "~1")
        return "~2" + seg[1:] if seg.startswith("[") else seg
    if isinstance(key, bool):
        return "[true]" if key else "[false]"
    if isinstance(key, int):
        return f"[{key}]"
    if isinstance(key, float):
        if math.isnan(key):
            raise ValueError("NaN is not a Lua table key")
        if math.isinf(key):
            return "[inf]" if key > 0 else "[-inf]"
        if key.is_integer() and abs(key) < _EXACT_INT:
            return f"[{int(key)}]"
        return f"[{key!r}]"
    raise TypeError(f"not a pointer key: {key!r}")


def pointer(*keys: Any) -> str:
    """The pointer (``/a/[1]/b``) of a key path from a file's value."""
    return "".join("/" + pointer_segment(k) for k in keys)


def _parse_segment(seg: str) -> Any:
    if seg.startswith("[") and seg.endswith("]") and len(seg) > 2:
        lit = seg[1:-1]
        if lit in ("true", "false"):
            return lit == "true"
        if lit in ("inf", "-inf"):
            return math.inf if lit == "inf" else -math.inf
        try:
            return int(lit)
        except ValueError:
            pass
        try:
            return float(lit)
        except ValueError:
            raise ValueError(f"bad pointer segment {seg!r}") from None
    if seg.startswith("["):
        raise ValueError(f"bad pointer segment {seg!r} (escape a leading [ as ~2)")
    out: list[str] = []
    i = 0
    while i < len(seg):
        c = seg[i]
        if c == "~":
            nxt = seg[i + 1 : i + 2]
            if nxt not in ("0", "1", "2"):
                raise ValueError(f"bad pointer escape in {seg!r}")
            out.append({"0": "~", "1": "/", "2": "["}[nxt])
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def parse_pointer(text: str) -> list[Any]:
    """The Lua keys of a pointer (``pointer``'s inverse)."""
    if text == "":
        return []
    if not text.startswith("/"):
        raise ValueError(f"pointer does not start with /: {text!r}")
    return [_parse_segment(s) for s in text[1:].split("/")]


def split_source_path(source_path: str) -> tuple[str, list[Any]]:
    """``(dump path, Lua keys)`` of ``<dump path>[#<pointer>]``."""
    path, _, ptr = source_path.partition("#")
    return path, parse_pointer(ptr)


def _same_key(a: Any, b: Any) -> bool:
    return isinstance(a, bool) == isinstance(b, bool) and a == b


def _anchors(node: Any, out: dict[Any, Any]) -> dict[Any, Any]:
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, Marker):
            if n.kind == "anchor":
                out[n.fields.get("id")] = n.fields.get("value")
            stack.extend(v for _, v in n.fields.entries)
        elif isinstance(n, LuaTable):
            stack.extend(v for _, v in n.entries)
    return out


class DumpPaths:
    """Resolves dump paths and ``sourcePath`` pointers against the ``_G``
    dump in ``g_dir`` (files read losslessly once, cached)."""

    def __init__(self, g_dir: Path, reader: LuaReader | None = None) -> None:
        self.g_dir = g_dir
        self.reader = reader or LuaReader(g_dir, link_refs=False)
        self._files: dict[str, Any] = {}

    def file(self, path: str) -> Any:
        """The lossless value of the dump file of ``path`` (``_G/...``);
        ``KeyError`` when absent or unreadable."""
        if path not in self._files:
            if not path.startswith("_G/"):
                raise KeyError(f"not a _G dump path: {path!r}")
            file = self.g_dir / f"{path[len('_G/') :]}.lua"
            parsed = None
            if file.is_file():
                text = file.read_text(encoding="utf-8", errors="replace")
                parsed = self.reader.read_source(file, text)
            self._files[path] = None if parsed is None else parsed.value
        value = self._files[path]
        if value is None:
            raise KeyError(f"no dump file {path}")
        return value

    def resolve(self, source_path: str) -> Any:
        """The lossless value at ``<dump path>#<pointer>``; ``KeyError`` when
        the file or a key is missing."""
        path, keys = split_source_path(source_path)
        root = self.file(path)
        node = root
        anchors: dict[Any, Any] | None = None
        for depth, key in enumerate([*keys, None]):
            while isinstance(node, (Marker, SourceRef)):
                if isinstance(node, SourceRef):
                    node = root = self.file(node.path)
                    anchors = None
                elif node.kind == "anchor":
                    node = node.fields.get("value")
                elif node.kind == "ref":
                    if anchors is None:
                        anchors = _anchors(root, {})
                    ident = node.fields.get("id")
                    if ident not in anchors:
                        raise KeyError(f"unknown anchor {ident!r} in {path}")
                    node = anchors[ident]
                else:
                    break
            if depth == len(keys):
                return node
            if not isinstance(node, LuaTable):
                raise KeyError(f"{key!r}: not a table at {keys[:depth]} in {path}")
            for k, v in node.entries:
                if _same_key(k, key):
                    node = v
                    break
            else:
                raise KeyError(f"{key!r} not at {keys[:depth]} in {path}")
        raise AssertionError("unreachable")


def emitted_paths(node: Any, where: str = "") -> Iterator[tuple[str, str]]:
    """``(where, path)`` of every ``sourcePaths`` entry and ``sourcePath``
    string in a record tree."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "sourcePaths" and isinstance(v, list):
                yield from ((f"{where}.{k}", p) for p in v if isinstance(p, str))
            elif k == "sourcePath" and isinstance(v, str):
                yield f"{where}.{k}", v
            elif isinstance(v, (dict, list)):
                yield from emitted_paths(v, f"{where}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from emitted_paths(v, f"{where}[{i}]")


def check(dump: DumpPaths, series: dict[str, dict[str, Any]]) -> list[str]:
    """One problem line per emitted path of ``series`` that does not resolve
    in the dump."""
    problems: list[str] = []
    for name, records in sorted(series.items()):
        for rid, record in sorted(records.items()):
            for where, path in emitted_paths(record, f"{name}/{rid}"):
                try:
                    dump.resolve(path)
                except (KeyError, ValueError) as e:
                    problems.append(f"{where} = {path!r}: {e}")
    return problems
