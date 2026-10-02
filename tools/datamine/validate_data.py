"""Validate ``dcs-world-reference/latest/``: every record against its
``Entity.*`` type and ``manifest.json`` against ``Entity.Provenance`` (JSON
Schema from ``tools/export_jsonschema.py``), cross-references (``check_refs``),
that every ``Entity.*`` type is reachable from a series type, that grouped
series files sit where ``series_files`` puts them, and that no other
directory sits beside ``latest/`` (older versions are in git history).
Exits non-zero on any failure; upstream gaps are warnings.

    uv run python -m tools.datamine.validate_data [--data-root DIR]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import fastjsonschema
from jsonschema import Draft7Validator

from tools.export_jsonschema import schema_for
from tools.package.entity_types import ref_name
from tools.spec_types import ENTITY_PREFIX

from . import overlays
from .check_refs import check_refs
from .common import (
    JSON_SCHEMA_PATH,
    LATEST,
    MANIFEST,
    MANIFEST_TYPE,
    REFERENCE_DATA_DIR,
    SERIES,
    UNEXTRACTED_TYPES,
    Series,
    fail,
    latest_version,
    load_json,
    read_tree,
    series_files,
    series_records,
)


class _Validator:
    """Validates records of one type: a compiled check, and ``jsonschema``'s
    messages for the records it rejects."""

    def __init__(self, document: dict[str, Any], type_name: str) -> None:
        schema = schema_for(document, type_name)
        self._check = fastjsonschema.compile(schema)
        self._explain = Draft7Validator(schema)

    def errors(self, record: Any, rel: str) -> list[str]:
        try:
            self._check(record)
            return []
        except fastjsonschema.JsonSchemaException:
            pass
        errs = sorted(
            self._explain.iter_errors(record), key=lambda e: list(e.absolute_path)
        )
        if not errs:
            return [f"  {rel} :: <root> -> rejected by the compiled schema"]
        return [
            f"  {rel} :: {'/'.join(str(p) for p in e.absolute_path) or '<root>'}"
            f" -> {e.message}"
            for e in errs
        ]


def _refs(node: Any, out: set[str]) -> None:
    if isinstance(node, dict):
        if isinstance(node.get("$ref"), str):
            out.add(ref_name(node))
        for v in node.values():
            _refs(v, out)
    elif isinstance(node, list):
        for v in node:
            _refs(v, out)


def orphan_types(document: dict[str, Any]) -> list[str]:
    """``Entity.*`` definitions no series, manifest or planned type reaches."""
    defs = document["definitions"]
    roots = [s.type_name for s in SERIES.values()] + [MANIFEST_TYPE, *UNEXTRACTED_TYPES]
    seen: set[str] = set()
    todo = [r for r in roots if r in defs]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        found: set[str] = set()
        _refs(defs[name], found)
        todo.extend(found - seen)
    return sorted(n for n in defs if n.startswith(ENTITY_PREFIX) and n not in seen)


def _misplaced(series: Series, records: dict[str, Any], actual: set[str]) -> list[str]:
    """Files of a grouped series (``actual``: every file under its dir) not at
    the path ``series_files`` gives them."""
    expected = series_files(
        series, {r[series.id_field]: r for r in records.values()}
    ).keys()
    return [
        *(
            f"  {series.name}/{rel} :: <file> -> not where series_files puts it"
            for rel in sorted(actual - expected)
        ),
        *(
            f"  {series.name}/{rel} :: <file> -> missing"
            for rel in sorted(expected - actual)
        ),
    ]


def strays(data_root: Path) -> list[str]:
    """Entries of ``data_root`` other than ``latest``."""
    return sorted(p.name for p in data_root.iterdir() if p.name != LATEST)


def validate(tree: dict[str, bytes], document: dict[str, Any], version: str) -> bool:
    """Print a report for the data dir ``tree`` (``{relative path:
    bytes}``, ``common.read_tree``); True when it passes."""
    violations: list[str] = []
    orphans = orphan_types(document)
    for name in orphans:
        print(f"  ERR  orphan type: {name} is not reachable from any series type")

    if MANIFEST not in tree:
        fail(f"missing {MANIFEST} in DCS {version}")
    errs = _Validator(document, MANIFEST_TYPE).errors(
        json.loads(tree[MANIFEST]), MANIFEST
    )
    violations += errs
    print(f"  [{'FAIL' if errs else 'PASS'}] {MANIFEST:<16} {MANIFEST_TYPE}")

    files_of: dict[str, set[str]] = {}
    for rel in tree:
        name, sep, sub = rel.partition("/")
        if sep:
            files_of.setdefault(name, set()).add(sub)
    by_series = series_records(tree)
    data: dict[str, dict[str, dict[str, Any]]] = {}
    for name in sorted(by_series):
        series = SERIES[name]
        validator = _Validator(document, series.type_name)
        data[name] = records = {
            stem: json.loads(b) for stem, b in by_series[name].items()
        }
        failed = 0
        for stem, record in records.items():
            errs = validator.errors(record, f"{name}/{stem}.json")
            failed += bool(errs)
            violations += errs
        if series.group_fields and not failed:
            violations += _misplaced(series, records, files_of[name])
        status = "FAIL" if failed else "PASS"
        print(
            f"  [{status}] {name:<16} {series.type_name:<24} {len(records) - failed} ok / {failed} fail"
        )

    facts = overlays.load(version)
    report = check_refs(
        data,
        document,
        {
            **facts.table("stores", "upstreamGaps"),
            **facts.table("stores", "loadoutRuleUpstreamGaps"),
        },
        facts.table("units", "upstreamGaps"),
    )
    print(f"\nCross-references: {report.resolved} resolved")
    by_gap: dict[tuple[str, Any], set[str]] = {}
    for ref in report.upstream:
        by_gap.setdefault((ref.target, ref.value), set()).add(
            f"{ref.series}/{ref.stem}"
        )
    for (target, value), sources in sorted(by_gap.items(), key=str):
        print(
            f"  WARN upstream gap: {target} {value!r} <- {', '.join(sorted(sources))}"
        )
    for value in report.stale_gaps:
        print(
            f"  ERR  upstream gap {value!r} now resolves; remove it from overlays.yaml"
        )
    for ref in sorted(report.dangling, key=str):
        print(f"  ERR  dangling: {ref}")

    if violations:
        print(f"\n{len(violations)} schema violation(s):")
        print("\n".join(violations))
    print(
        f"\nSchema violations: {len(violations)}; dangling refs: {len(report.dangling)}; "
        f"stale gaps: {len(report.stale_gaps)}; "
        f"orphan types: {len(orphans)}; upstream gaps: {len(report.upstream)}"
    )
    return not (violations or report.dangling or report.stale_gaps or orphans)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--schema", type=Path, default=JSON_SCHEMA_PATH, help="Entity JSON Schema."
    )
    parser.add_argument("--data-root", type=Path, default=REFERENCE_DATA_DIR)
    args = parser.parse_args()
    if not args.schema.is_file():
        fail(
            f"JSON Schema not found: {args.schema} (run `task build:jsonschema` first)"
        )
    version = latest_version(args.data_root)
    if version is None:
        fail(f"no {args.data_root / LATEST / MANIFEST}")
    latest = args.data_root / LATEST
    print(f"Validating {latest} (DCS {version}) against {args.schema.name}\n")
    ok = validate(read_tree(latest), load_json(args.schema), version)
    stray = strays(args.data_root)
    for name in stray:
        print(f"  ERR  {args.data_root / name}: only {LATEST}/ belongs here")
    return 0 if ok and not stray else 1


if __name__ == "__main__":
    sys.exit(main())
