"""Hand-authored facts from ``overlays.yaml`` (format documented there):
record patches applied after extraction, and lookup and rule tables
extractors read."""

from __future__ import annotations

import operator
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .common import CORRECTED, HAND_AUTHORED, fail

OVERLAYS_PATH = Path(__file__).resolve().with_name("overlays.yaml")
_SEGMENT = re.compile(r"^(\w+)(?:\[(\w+)=([^\]]+)\])?$")
OPS = ("negate",)
_COMPARE = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge}


@dataclass(frozen=True)
class Overlays:
    patches: list[dict[str, Any]]
    tables: dict[tuple[str, str], Any]

    def table(self, series: str, name: str) -> Any:
        """A table's value: a mapping, or a list of rules (``rule``)."""
        if (series, name) not in self.tables:
            fail(f"overlays: no table {series}/{name}")
        return self.tables[(series, name)]


def rule(
    rules: list[dict[str, Any]], facts: Mapping[str, float], where: str
) -> int | None:
    """The index of the first rule whose every ``when`` comparison holds for
    ``facts`` (``{fact: {op: bound}}``, ``op`` one of ``< <= > >=``; no
    ``when`` always holds), or None."""
    for i, r in enumerate(rules):
        ok = True
        for fact, tests in (r.get("when") or {}).items():
            if fact not in facts:
                fail(
                    f"{where} rule {i + 1}: unknown fact {fact!r} (known: {', '.join(facts)})"
                )
            for op, bound in tests.items():
                if op not in _COMPARE:
                    fail(f"{where} rule {i + 1}: unknown comparison {op!r}")
                ok = ok and _COMPARE[op](facts[fact], bound)
        if ok:
            return i
    return None


def unused_rules(rules: list[dict[str, Any]], used: set[int], where: str) -> None:
    """Fail on a rule no input matched: it is stale."""
    stale = [i + 1 for i in range(len(rules)) if i not in used]
    if stale:
        fail(f"{where}: rule(s) {stale} match nothing; remove or fix them")


def unused_keys(table: Iterable[str], used: set[str], where: str) -> None:
    """Fail on a table key no input used: it is stale."""
    stale = sorted(set(table) - used)
    if stale:
        fail(f"{where}: {stale} used by nothing; remove them")


def load(version: str | None, path: Path = OVERLAYS_PATH) -> Overlays:
    """The entries of ``path`` that apply to DCS ``version`` (all when None)."""
    entries = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get(
        "entries", []
    )
    patches: list[dict[str, Any]] = []
    tables: dict[tuple[str, str], Any] = {}
    for i, e in enumerate(entries):
        where = f"{path.name} entry {i + 1}"
        for key in ("series", "note", "evidence"):
            if not str(e.get(key) or "").strip():
                fail(f"{where}: missing {key}")
        if version is not None and "versions" in e and version not in e["versions"]:
            continue
        if "table" in e:
            if not isinstance(e.get("value"), (dict, list)):
                fail(f"{where}: table {e['table']} needs a mapping or list value")
            tables[(e["series"], e["table"])] = e["value"]
        elif "id" in e and "field" in e and "add" in e:
            if "value" in e or "op" in e or not isinstance(e["add"], dict):
                fail(f"{where}: `add` takes a mapping, without `value` or `op`")
            last = _SEGMENT.match(e["field"].split(".")[-1])
            if last is None or last.group(2) is None:
                fail(
                    f"{where}: `add` needs a field ending in a `name[key=value]` selector"
                )
            patches.extend({**e, "id": i} for i in _ids(e["id"], where))
        elif "id" in e and "field" in e and (("value" in e) != ("op" in e)):
            if "op" in e and e["op"] not in OPS:
                fail(f"{where}: unknown op {e['op']!r} (known: {', '.join(OPS)})")
            if e.get("op") == "negate" and e.get("raw_sign") not in (1, -1):
                fail(
                    f"{where}: negate needs raw_sign 1 or -1 (the wrong sign it corrects)"
                )
            patches.extend({**e, "id": i} for i in _ids(e["id"], where))
        else:
            fail(
                f"{where}: needs `table` + `value`, or `id` + `field` + one of "
                "`value`/`op`/`add`"
            )
    return Overlays(patches, tables)


def _ids(value: Any, where: str) -> list[str]:
    """A patch's record ids: one, or a list."""
    ids = value if isinstance(value, list) else [value]
    if not ids or not all(isinstance(i, str) and i for i in ids):
        fail(f"{where}: `id` is a record id or a list of them")
    return ids


def _locate(
    record: dict[str, Any], field: str
) -> tuple[dict[str, Any], str, dict[str, Any], str]:
    """(holder, key, stamp holder, stamp path) of a dotted ``field`` path. The
    ``_source`` stamp goes on the innermost selected list element (else the
    record), keyed by the path below it."""
    node = stamp = record
    rel: list[str] = []
    segments = field.split(".")
    for i, seg in enumerate(segments):
        m = _SEGMENT.match(seg)
        if m is None:
            raise KeyError(f"bad path segment {seg!r}")
        name, sel_key, sel_value = m.groups()
        if i == len(segments) - 1:
            if sel_key is not None or name not in node:
                raise KeyError(f"no field {seg!r}")
            return node, name, stamp, ".".join([*rel, name])
        child = node.get(name)
        if sel_key is None:
            if not isinstance(child, dict):
                raise KeyError(f"no object {name!r}")
            node = child
            rel.append(name)
            continue
        hits = [
            e
            for e in child or []
            if isinstance(e, dict) and str(e.get(sel_key)) == sel_value
        ]
        if len(hits) != 1:
            raise KeyError(f"{seg!r} selects {len(hits)} elements")
        node = stamp = hits[0]
        rel = []
    raise KeyError("empty path")


def _add(record: dict[str, Any], field: str, add: dict[str, Any], where: str) -> None:
    """Add the list element ``field``'s last ``name[key=value]`` segment
    selects, ``{key: value, **add}``; stamped hand-authored on the stamp
    holder of its list (as ``_locate``'s), keyed by its path. An element
    already there is an error: DCS has it now."""
    *parents, last = field.split(".")
    m = _SEGMENT.match(last)
    if m is None:
        fail(f"{where}: bad `add` field {field!r}")
    name, sel_key, sel_value = m.groups()
    holder, stamp, stamp_path = record, record, last
    if parents:
        try:
            holder, key, stamp, rel = _locate(record, ".".join(parents))
        except KeyError as exc:
            fail(f"{where}: {exc.args[0]}")
        holder = holder[key]
        if not isinstance(holder, dict):
            fail(f"{where}: {'.'.join(parents)} is no object")
        stamp_path = f"{rel}.{last}"
    items = holder.get(name)
    if not isinstance(items, list):
        fail(f"{where}: no list {name!r}")
    if any(isinstance(e, dict) and str(e.get(sel_key)) == sel_value for e in items):
        fail(f"{where}: already extracted without the overlay; remove it")
    keys = [str(e.get(sel_key)) for e in items if isinstance(e, dict)]
    items.append({sel_key: sel_value, **add})
    if len(keys) == len(items) - 1 and keys == sorted(keys):  # keep it sorted
        items.sort(key=lambda e: str(e.get(sel_key)))
    stamp.setdefault("_source", {})[stamp_path] = HAND_AUTHORED


def apply(overlays: Overlays, series: dict[str, dict[str, dict[str, Any]]]) -> None:
    """Apply every record patch in place; any stale patch is an error."""
    for p in overlays.patches:
        where = f"overlay {p['series']}/{p['id']} {p['field']}"
        record = series.get(p["series"], {}).get(p["id"])
        if record is None:
            fail(f"{where}: no such record")
        if "add" in p:
            _add(record, p["field"], p["add"], where)
            continue
        try:
            holder, key, stamp, stamp_path = _locate(record, p["field"])
        except KeyError as exc:
            fail(f"{where}: {exc.args[0]}")
        raw = holder[key]
        if "op" in p:  # negate
            sign = (raw > 0) - (raw < 0)
            if sign != p.get("raw_sign"):
                fail(
                    f"{where}: raw value {raw!r} no longer has the sign this correction expects; remove it"
                )
            new, source = -raw, CORRECTED
        else:
            new, source = p["value"], HAND_AUTHORED
        if new == raw:
            fail(f"{where}: already {raw!r} without the overlay; remove it")
        holder[key] = new
        stamp.setdefault("_source", {})[stamp_path] = source
