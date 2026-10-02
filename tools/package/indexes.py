"""Reverse and name indexes over the series bundles, written to
``dist/reference/_index/`` beside them.

The relations are the fields the entity JSON Schema marks with ``x-ref``
(``tools.datamine.check_refs.rules``); only ``DERIVED`` names one. Files:

* ``references_<series>.json``: ``{id: [{series, id, path}, ...]}``, every
  record referencing a record of ``<series>`` and the field (``path``, arrays as
  ``[]``) holding the reference. Only resolved references are indexed; a
  reference to any unit series lands in the series holding the id.
* one file per ``DERIVED`` chain, e.g. ``carriers.json``: ``{weapon id:
  [aircraft id, ...]}``, aircraft with a station accepting a store that delivers
  the weapon.
* ``names_<series>.json``: ``{name key: [id, ...]}`` of each record's
  ``NAME_FIELDS``; ``name_key`` (trimmed, ASCII-lowercased) is the key every
  package helper computes the same way.
* ``airbases_by_name.json``: ``{theatre: {name key: [id, ...]}}``.
* ``meta.json``: the relations and which files exist.

Lists are sorted and deduplicated and keys sorted, so the output depends only on
the data.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from tools.datamine.check_refs import UNITS, rules
from tools.datamine.common import SERIES, UNIT_SERIES, json_text

INDEX_DIR = "_index"
NAME_FIELDS = ("displayName", "name")
# name -> (target series, (series, path) hopped through back to front): the
# records of the last series reaching the target through the others, by
# references at that path (None: any). Carriers take a store's own station
# entries, not the loadout rules naming it.
DERIVED: dict[str, tuple[str, tuple[tuple[str, str | None], ...]]] = {
    "carriers": (
        "weapons",
        (("stores", None), ("aircraft", "stations[].accepts[].clsid")),
    ),
}
AIRBASES = ("airbases", "name", "theatre")  # series, name field, group field

_ASCII_UPPER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
_ASCII_SPACE = " \t\n\r\f\v"


def name_key(name: str) -> str:
    """Trimmed of ASCII whitespace, ASCII letters lowercased (as Lua's
    ``string.lower``, so every package computes the same key)."""
    return name.strip(_ASCII_SPACE).translate(_ASCII_UPPER)


def _sorted_lists(index: dict[str, set[str]]) -> dict[str, list[str]]:
    return {k: sorted(v) for k, v in sorted(index.items())}


def references(
    bundles: dict[str, dict[str, Any]], document: dict[str, Any]
) -> dict[str, dict[str, list[dict[str, str]]]]:
    """``{target series: {target id: [{series, id, path}]}}`` for every
    ``x-ref`` rule; target series without inbound references are left out."""
    ids = {name: set(bundle) for name, bundle in bundles.items()}
    found: dict[str, dict[str, set[tuple[str, str, str]]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for rule in rules(document):
        targets = UNIT_SERIES if rule.target == UNITS else (rule.target,)
        for key, record in bundles.get(rule.series, {}).items():
            for value in rule.values(record):
                value = str(value)
                for target in targets:
                    if value in ids.get(target, ()):
                        found[target][value].add((rule.series, key, rule.label))
    return {
        target: {
            k: [{"series": s, "id": i, "path": p} for s, i, p in sorted(v)]
            for k, v in sorted(by_id.items())
        }
        for target, by_id in sorted(found.items())
    }


def referrers(
    refs: dict[str, dict[str, list[dict[str, str]]]],
    target: str,
    key: str,
    series: str,
    path: str | None = None,
) -> list[str]:
    """Ids of the ``series`` records referencing ``target`` record ``key``
    (at ``path`` only, if given)."""
    return sorted(
        {
            r["id"]
            for r in refs.get(target, {}).get(key, [])
            if r["series"] == series and path in (None, r["path"])
        }
    )


def derived(
    refs: dict[str, dict[str, list[dict[str, str]]]],
    target: str,
    via: tuple[tuple[str, str | None], ...],
) -> dict[str, list[str]]:
    """``{target id: [ids of via[-1]]}`` following the references back from
    ``target`` through each ``(series, path)`` of ``via`` in turn."""
    out: dict[str, set[str]] = {}
    for key in refs.get(target, {}):
        series, frontier = target, {key}
        for hop, path in via:
            frontier = {
                i for k in frontier for i in referrers(refs, series, k, hop, path)
            }
            series = hop
        if frontier:
            out[key] = frontier
    return _sorted_lists(out)


def _names(record: dict[str, Any]) -> Iterable[str]:
    for field in NAME_FIELDS:
        value = record.get(field)
        if isinstance(value, str) and name_key(value):
            yield name_key(value)


def names(bundle: dict[str, Any]) -> dict[str, list[str]]:
    """``{name key: [id]}`` of a series' records."""
    out: dict[str, set[str]] = defaultdict(set)
    for key, record in bundle.items():
        for name in _names(record):
            out[name].add(key)
    return _sorted_lists(out)


def grouped_names(
    bundle: dict[str, Any], name_field: str, group_field: str
) -> dict[str, dict[str, list[str]]]:
    """``{group: {name key: [id]}}`` of a series' records."""
    out: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for key, record in bundle.items():
        value, group = record.get(name_field), record.get(group_field)
        if isinstance(value, str) and name_key(value) and group is not None:
            out[str(group)][name_key(value)].add(key)
    return {g: _sorted_lists(v) for g, v in sorted(out.items())}


def build(
    bundles: dict[str, dict[str, Any]], document: dict[str, Any]
) -> dict[str, Any]:
    """Every index file's payload by its name (without ``.json``)."""
    refs = references(bundles, document)
    named = {s: idx for s in SERIES if s in bundles and (idx := names(bundles[s]))}
    out: dict[str, Any] = {f"references_{t}": v for t, v in refs.items()}
    for name, (target, via) in DERIVED.items():
        out[name] = derived(refs, target, via)
    out.update({f"names_{s}": v for s, v in named.items()})
    series, name_field, group_field = AIRBASES
    out["airbases_by_name"] = grouped_names(
        bundles.get(series, {}), name_field, group_field
    )
    out["meta"] = {
        "relations": [
            {"series": r.series, "path": r.label, "target": r.target}
            for r in rules(document)
        ],
        "unitSeries": list(UNIT_SERIES),
        "references": sorted(refs),
        "names": sorted(named),
        "derived": {
            name: {
                "target": target,
                "via": [hop for hop, _ in via],
                "paths": [path for _, path in via],
            }
            for name, (target, via) in sorted(DERIVED.items())
        },
    }
    return dict(sorted(out.items()))


def files(indexes: dict[str, Any]) -> dict[str, str]:
    """``{"_index/<name>.json": text}``, compact deterministic JSON."""
    return {
        f"{INDEX_DIR}/{name}.json": json_text(payload, compact=True)
        for name, payload in indexes.items()
    }
