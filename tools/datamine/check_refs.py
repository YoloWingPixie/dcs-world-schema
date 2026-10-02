"""Cross-reference integrity of extracted ``dcs-world-reference``.

The references are the fields the entity JSON Schema marks with ``x-ref``
(a field's ``ref`` in the spec), found by walking each series' record type.
Every one must resolve to the id of a record of one of its entity types. An
unresolved reference is:

* dangling - an error;
* an upstream gap - a store CLSID in the ``overlays.yaml`` ``stores``
  ``upstreamGaps`` or ``loadoutRuleUpstreamGaps`` table because DCS itself
  does not define it in ``_G/launcher``, or a unit type in the ``units``
  ``upstreamGaps`` table because no ``db/Units`` record defines it; a
  warning. A gap that now resolves is an error (remove the entry).

Country fields are schema enums (``country.id`` is generated from the same dump).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from tools.export_jsonschema import X_REF
from tools.package.entity_types import ref_name

from .common import SERIES, UNIT_SERIES, fail

ARRAY = "[]"
UNITS = "units"  # the target of a reference to any unit series


@dataclass(frozen=True)
class Rule:
    series: str
    path: tuple[str, ...]  # field names and ARRAY steps from the record
    target: str  # a series, or UNITS

    @property
    def label(self) -> str:
        return ".".join(self.path).replace(f".{ARRAY}", ARRAY)

    def values(self, record: Any) -> Iterator[Any]:
        nodes = [record]
        for step in self.path:
            if step == ARRAY:
                nodes = [e for n in nodes if isinstance(n, list) for e in n]
            else:
                nodes = [n[step] for n in nodes if isinstance(n, dict) and step in n]
        return (n for n in nodes if n is not None)


def _target(types: list[str]) -> str:
    by_type = {s.type_name: s.name for s in SERIES.values()}
    missing = [t for t in types if t not in by_type]
    if missing:
        fail(f"{X_REF} {missing}: no series holds records of that type")
    names = sorted(by_type[t] for t in types)
    if names == sorted(UNIT_SERIES):
        return UNITS
    if len(names) != 1:
        fail(f"{X_REF} {types}: a reference is to one series or to every unit series")
    return names[0]


def rules(document: dict[str, Any]) -> list[Rule]:
    """One rule per ``x-ref`` a series' record type reaches."""
    defs = document["definitions"]
    out: list[Rule] = []

    def walk(
        series: str, node: Any, path: tuple[str, ...], seen: tuple[str, ...]
    ) -> None:
        if not isinstance(node, dict):
            return
        if X_REF in node:
            out.append(Rule(series, path, _target(node[X_REF])))
        if "$ref" in node and (name := ref_name(node)) not in seen:
            walk(series, defs[name], path, (*seen, name))
        for sub in node.get("anyOf", []):
            walk(series, sub, path, seen)
        if "items" in node:
            walk(series, node["items"], (*path, ARRAY), seen)
        for key, sub in node.get("properties", {}).items():
            walk(series, sub, (*path, key), seen)

    for s in SERIES.values():
        walk(s.name, {"$ref": f"#/definitions/{s.type_name}"}, (), ())
    return list(dict.fromkeys(out))


@dataclass(frozen=True)
class Ref:
    series: str
    stem: str
    field: str
    value: Any
    target: str

    def __str__(self) -> str:
        return f"{self.series}/{self.stem}.json :: {self.field} -> {self.value!r} [{self.target}]"


@dataclass
class RefReport:
    resolved: int = 0
    dangling: list[Ref] = field(default_factory=list)
    upstream: list[Ref] = field(default_factory=list)
    stale_gaps: list[str] = field(default_factory=list)


def check_refs(
    data: dict[str, dict[str, dict[str, Any]]],
    document: dict[str, Any],
    gaps: dict[str, str],
    unit_gaps: dict[str, str] | None = None,
) -> RefReport:
    """``data`` is ``{series: {file stem: record}}``, ``document`` the entity
    JSON Schema; ``gaps`` the upstream-gap store CLSIDs, ``unit_gaps`` the
    upstream-gap unit types."""
    targets: dict[str, set[Any]] = {
        name: {r[s.id_field] for r in data.get(name, {}).values()}
        for name, s in SERIES.items()
    }
    targets[UNITS] = set().union(*(targets[u] for u in UNIT_SERIES))

    gaps_of = {"stores": set(gaps), UNITS: set(unit_gaps or {})}
    report = RefReport(
        stale_gaps=sorted(
            v for target, known in gaps_of.items() for v in known & targets[target]
        )
    )
    for rule in rules(document):
        for stem, record in data.get(rule.series, {}).items():
            for value in rule.values(record):
                if value in targets[rule.target]:
                    report.resolved += 1
                    continue
                ref = Ref(rule.series, stem, rule.label, value, rule.target)
                (
                    report.upstream
                    if value in gaps_of.get(rule.target, ())
                    else report.dangling
                ).append(ref)

    return report
