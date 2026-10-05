"""Reorder the pages of a SQLite file so the pages every HTTP client reads
first sit together near the start of the file.

A client that reads the database over HTTP (the reference site) fetches it in
fixed-size parts. Each connection reads the whole schema, and every page
starts by reading a few small tables and the upper levels of a few b-trees.
After ``VACUUM`` those pages are spread over the first megabyte (each table's
root page is allocated when the table is created), so a cold start fetches
dozens of parts. Moving them together makes that a handful.

The content is untouched: every page keeps its bytes but for the page numbers
it holds (b-tree child pointers, overflow chains and the ``rootpage`` column
of ``sqlite_schema``). Only files without a freelist or pointer map (no
auto-vacuum), as ``VACUUM`` leaves them, are supported.

Hot pages are ``hot_pages``: page 1, every page of ``sqlite_schema`` and of the
``whole`` objects, and the interior pages (the root included) of the ``upper``
objects. Pages are laid out as: page 1, hot root pages numbered below 128
(their ``rootpage`` takes one byte, so they must stay there), the other root
pages below 128, every other hot page (group by group), then the rest in
their old order.
"""

from __future__ import annotations

import sqlite3
import struct
from collections.abc import Iterable, Sequence
from pathlib import Path

INTERIOR_INDEX, INTERIOR_TABLE, LEAF_INDEX, LEAF_TABLE = 2, 5, 10, 13


def _varint(buf: bytes, at: int) -> tuple[int, int]:
    """``(value, length)`` of the SQLite varint at ``at``."""
    value = 0
    for i in range(8):
        b = buf[at + i]
        value = (value << 7) | (b & 0x7F)
        if not b & 0x80:
            return value, i + 1
    return (value << 8) | buf[at + 8], 9


class _File:
    def __init__(self, data: bytearray) -> None:
        self.data = data
        size = struct.unpack_from(">H", data, 16)[0]
        self.size = 65536 if size == 1 else size
        self.usable = self.size - data[20]
        self.count = struct.unpack_from(">I", data, 28)[0]
        if (
            struct.unpack_from(">I", data, 32)[0]
            or struct.unpack_from(">I", data, 52)[0]
        ):
            raise ValueError("page_order: a freelist or auto-vacuum file")
        if self.count * self.size != len(data):
            raise ValueError("page_order: header page count disagrees with the size")

    def base(self, page: int) -> int:
        return (page - 1) * self.size

    def header(self, page: int) -> int:
        return self.base(page) + (100 if page == 1 else 0)

    def kind(self, page: int) -> int:
        return self.data[self.header(page)]

    def cells(self, page: int) -> list[int]:
        """Absolute offsets of the page's cells."""
        h = self.header(page)
        kind = self.data[h]
        n = struct.unpack_from(">H", self.data, h + 3)[0]
        ptrs = h + (12 if kind in (INTERIOR_INDEX, INTERIOR_TABLE) else 8)
        base = self.base(page)
        return [
            base + struct.unpack_from(">H", self.data, ptrs + 2 * i)[0]
            for i in range(n)
        ]

    def overflow_at(self, kind: int, cell: int) -> int | None:
        """Offset of a cell's first-overflow page number, if it overflows."""
        at = cell + (4 if kind == INTERIOR_INDEX else 0)
        if kind == INTERIOR_TABLE:
            return None
        payload, n = _varint(self.data, at)
        at += n
        if kind == LEAF_TABLE:
            at += _varint(self.data, at)[1]
            limit = self.usable - 35
        else:
            limit = (self.usable - 12) * 64 // 255 - 23
        if payload <= limit:
            return None
        least = (self.usable - 12) * 32 // 255 - 23
        local = least + (payload - least) % (self.usable - 4)
        if local > limit:
            local = least
        return at + local

    def children(self, page: int) -> list[int]:
        """Child pages and first overflow pages of a b-tree page."""
        kind = self.kind(page)
        out = []
        for cell in self.cells(page):
            if kind in (INTERIOR_INDEX, INTERIOR_TABLE):
                out.append(struct.unpack_from(">I", self.data, cell)[0])
            at = self.overflow_at(kind, cell)
            if at is not None:
                out.append(-struct.unpack_from(">I", self.data, at)[0])
        if kind in (INTERIOR_INDEX, INTERIOR_TABLE):
            out.append(struct.unpack_from(">I", self.data, self.header(page) + 8)[0])
        return out


def _walk(f: _File, root: int, interior_only: bool) -> list[int]:
    """Pages of the b-tree at ``root`` in page order; overflow pages included
    unless ``interior_only`` (then: interior pages only, the root always)."""
    out: list[int] = []
    stack = [root]
    while stack:
        page = stack.pop()
        if page < 0:  # an overflow chain
            p = -page
            while p:
                out.append(p)
                p = struct.unpack_from(">I", f.data, f.base(p))[0]
            continue
        kind = f.kind(page)
        interior = kind in (INTERIOR_INDEX, INTERIOR_TABLE)
        if not interior_only or interior or page == root:
            out.append(page)
        for child in f.children(page):
            if interior_only and (child < 0 or not interior):
                continue
            stack.append(child)
    return sorted(set(out))


def _roots(path: Path) -> dict[str, int]:
    db = sqlite3.connect(path)
    try:
        rows = db.execute(
            "SELECT name, rootpage FROM sqlite_schema WHERE rootpage > 0"
        ).fetchall()
    finally:
        db.close()
    return {str(n): int(r) for n, r in rows}


def hot_pages(path: Path, whole: Iterable[str], upper: Iterable[str]) -> list[int]:
    """Page 1, all of ``sqlite_schema`` and ``whole``, the interior pages of
    ``upper`` (tables or indexes by name; missing names are skipped)."""
    f = _File(bytearray(path.read_bytes()))
    roots = _roots(path)
    hot = set(_walk(f, 1, False))
    for name in whole:
        if name in roots:
            hot.update(_walk(f, roots[name], False))
    for name in upper:
        if name in roots:
            hot.update(_walk(f, roots[name], True))
    return sorted(hot)


Group = tuple[Iterable[str], Iterable[str]]


def reorder(path: Path, groups: Sequence[Group]) -> None:
    """Rewrite ``path`` with its hot pages first (see the module docs): the
    ``hot_pages`` of each ``(whole, upper)`` group in turn."""
    ranked: list[int] = []
    for whole, upper in groups:
        ranked += [p for p in hot_pages(path, whole, upper) if p not in ranked]
    hot = set(ranked)
    data = bytearray(path.read_bytes())
    f = _File(data)
    roots = _roots(path)
    root_pages = set(roots.values())
    small = {p for p in root_pages if p < 128}
    schema_leaves = [p for p in _walk(f, 1, False) if f.kind(p) == LEAF_TABLE]

    order = [1]
    order += [p for p in range(2, f.count + 1) if p in small and p in hot]
    order += [p for p in range(2, f.count + 1) if p in small and p not in hot]
    order += [p for p in ranked if p != 1 and p not in small]
    order += [p for p in range(2, f.count + 1) if p not in hot and p not in small]
    new = {old: i + 1 for i, old in enumerate(order)}

    # Every b-tree page and overflow page reachable from a root.
    btree: set[int] = set()
    overflow: set[int] = set()
    for root in [1, *sorted(root_pages)]:
        stack = [root]
        while stack:
            page = stack.pop()
            if page in btree:
                continue
            btree.add(page)
            for child in f.children(page):
                if child > 0:
                    stack.append(child)
                else:
                    p = -child
                    while p:
                        overflow.add(p)
                        p = struct.unpack_from(">I", data, f.base(p))[0]
    if len(btree) + len(overflow) != f.count:
        raise ValueError("page_order: pages not reachable from the schema")

    def remap(at: int) -> None:
        old = struct.unpack_from(">I", data, at)[0]
        if old:
            struct.pack_into(">I", data, at, new[old])

    for page in btree:
        kind = f.kind(page)
        for cell in f.cells(page):
            if kind in (INTERIOR_INDEX, INTERIOR_TABLE):
                remap(cell)
            at = f.overflow_at(kind, cell)
            if at is not None:
                remap(at)
        if kind in (INTERIOR_INDEX, INTERIOR_TABLE):
            remap(f.header(page) + 8)
    for page in overflow:
        remap(f.base(page))

    # sqlite_schema rows: (type, name, tbl_name, rootpage, sql).
    for page in schema_leaves:
        if page in overflow:
            continue
        for cell in f.cells(page):
            at = cell + _varint(data, cell)[1]
            at += _varint(data, at)[1]
            head, n = _varint(data, at)
            types, i = [], at + n
            while i < at + head:
                t, n = _varint(data, i)
                types.append(t)
                i += n
            offset = at + head
            for t in types[:3]:
                offset += (
                    (t - 12) // 2 if t >= 12 else (0, 1, 2, 3, 4, 6, 8, 8, 0, 0)[t]
                )
            t = types[3]
            width = {1: 1, 2: 2, 3: 3, 4: 4}.get(t)
            if width is None:
                continue  # 0 (a view or virtual table)
            old = int.from_bytes(data[offset : offset + width], "big", signed=True)
            value = new[old]
            if value >= 1 << (8 * width - 1):
                raise ValueError(
                    f"page_order: root {old} -> {value} needs a wider field"
                )
            data[offset : offset + width] = value.to_bytes(width, "big", signed=True)

    out = bytearray(len(data))
    for old, n in new.items():
        out[(n - 1) * f.size : n * f.size] = data[f.base(old) : f.base(old) + f.size]
    path.write_bytes(bytes(out))
