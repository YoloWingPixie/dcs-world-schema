"""The classification rules the package helpers apply (``unitClass``,
``aircraftRoles``), from the ``units/classes`` and ``aircraft/roles`` tables of
``tools/datamine/overlays.yaml``, checked against the data and shipped as the
``classification`` index.

A rule's ``when`` maps a fact to ``any``/``all``/``none`` lists of values; it
matches when every test holds (a fact a record lacks is the empty list). A
unit's class is that of the first matching ``units/classes`` rule, else
``other``; an aircraft's roles are those of every matching ``aircraft/roles``
rule. Facts, as every package computes them:

* ``series``: ``[the unit's series]``
* ``attributes``: its DCS attributes
* ``kind``: ``[kind]`` of an aircraft
* ``tasks``: an aircraft's task names; ``defaultTask``: ``[its name]``
* ``isTanker``: ``["true"]`` when ``refuelling.isTanker`` is true or non-zero

A rule matching nothing, a value the data lacks (an unknown attribute, series,
kind or task name) or an unknown fact or test fails the build.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

from tools.datamine import overlays
from tools.datamine.common import UNIT_SERIES, fail

TESTS = ("any", "all", "none")
UNIT_FACTS = ("series", "attributes", "kind")
AIRCRAFT_FACTS = ("attributes", "kind", "tasks", "defaultTask", "isTanker")


def unit_facts(series: str, record: Mapping[str, Any]) -> dict[str, list[str]]:
    return {
        "series": [series],
        "attributes": list(record.get("attributes", [])),
        "kind": [record["kind"]] if series == "aircraft" else [],
    }


def aircraft_facts(record: Mapping[str, Any]) -> dict[str, list[str]]:
    tanker = record.get("refuelling", {}).get("isTanker")
    default = record.get("defaultTask")
    return {
        "attributes": list(record.get("attributes", [])),
        "kind": [record["kind"]],
        "tasks": [t["name"] for t in record.get("tasks", [])],
        "defaultTask": [default["name"]] if default else [],
        "isTanker": ["true"]
        if tanker is not None and tanker is not False and tanker != 0
        else [],
    }


def matches(
    when: Mapping[str, Mapping[str, list[str]]], facts: Mapping[str, list[str]]
) -> bool:
    for fact, tests in when.items():
        have = set(facts.get(fact, ()))
        if "any" in tests and not have.intersection(tests["any"]):
            return False
        if "all" in tests and not have.issuperset(tests["all"]):
            return False
        if "none" in tests and have.intersection(tests["none"]):
            return False
    return True


def _check(
    rules: Any,
    label: str,
    where: str,
    allowed: tuple[str, ...],
    known: Mapping[str, set[str]],
) -> list[dict[str, Any]]:
    if not isinstance(rules, list) or not rules:
        fail(f"{where}: needs a list of rules")
    out = []
    for i, r in enumerate(rules, start=1):
        at = f"{where} rule {i}"
        if (
            not isinstance(r, dict)
            or set(r) - {label, "when"}
            or not isinstance(r.get(label), str)
        ):
            fail(f"{at}: needs `{label}` (a string) and optionally `when`")
        when = r.get("when") or {}
        if not isinstance(when, dict):
            fail(f"{at}: `when` must be a mapping")
        for fact, tests in when.items():
            if fact not in allowed:
                fail(f"{at}: unknown fact {fact!r} (known: {', '.join(allowed)})")
            if not isinstance(tests, dict) or not tests or set(tests) - set(TESTS):
                fail(f"{at}: {fact} needs tests among {', '.join(TESTS)}")
            for test, values in tests.items():
                if not isinstance(values, list) or not values:
                    fail(f"{at}: {fact}.{test} needs a list of values")
                if unknown := sorted(str(v) for v in values if v not in known[fact]):
                    fail(f"{at}: {fact} has no value {unknown}")
        out.append({label: r[label], "when": when})
    return out


def build(
    series: Mapping[str, Mapping[str, Any]], dcs_version: str
) -> tuple[dict[str, Any], list[str]]:
    """(the ``classification`` index payload, report lines)."""
    tables = overlays.load(dcs_version)
    units = [(s, r) for s in UNIT_SERIES for r in series.get(s, {}).values()]
    aircraft = list(series.get("aircraft", {}).values())
    unit_known: dict[str, set[str]] = {
        "series": set(UNIT_SERIES),
        "attributes": set(series.get("attributes", {})),
        "kind": {r["kind"] for r in aircraft},
    }
    air_facts = [aircraft_facts(r) for r in aircraft]
    air_known: dict[str, set[str]] = {
        f: {v for facts in air_facts for v in facts[f]} for f in AIRCRAFT_FACTS
    }
    air_known["attributes"] = unit_known["attributes"]
    classes = _check(
        tables.table("units", "classes"),
        "class",
        "overlays units/classes",
        UNIT_FACTS,
        unit_known,
    )
    roles = _check(
        tables.table("aircraft", "roles"),
        "role",
        "overlays aircraft/roles",
        AIRCRAFT_FACTS,
        air_known,
    )
    used: set[int] = set()
    counts: Counter[str] = Counter()
    for s, r in units:
        facts = unit_facts(s, r)
        hit = next(
            (i for i, c in enumerate(classes) if matches(c["when"], facts)), None
        )
        if hit is not None:
            used.add(hit)
        counts[classes[hit]["class"] if hit is not None else "other"] += 1
    overlays.unused_rules(classes, used, "overlays units/classes")
    used = set()
    role_counts: Counter[str] = Counter()
    for facts in air_facts:
        mine = set()
        for i, r in enumerate(roles):
            if matches(r["when"], facts):
                used.add(i)
                mine.add(r["role"])
        role_counts.update(mine or {"(none)"})
    overlays.unused_rules(roles, used, "overlays aircraft/roles")
    report = [
        "unit classes: " + ", ".join(f"{c} {n}" for c, n in counts.most_common()),
        "aircraft roles: "
        + ", ".join(f"{c} {n}" for c, n in role_counts.most_common()),
    ]
    return {"unitClasses": classes, "aircraftRoles": roles}, report
