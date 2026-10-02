"""Build the reference data as one SQLite database from the series bundles.

Layout, derived from the entity JSON Schema:

* one table per series (``common.SERIES``), primary key its id field; a
  top-level field whose type is a scalar (string, number, boolean or a scalar
  enum, nullable or not) is a typed column, anything else (records, arrays,
  unions of shapes, ``_source``) a TEXT column holding compact JSON (query it
  with ``json_extract``/``json_each``); booleans are 0/1;
* ``units``: every unit type (``id``, ``series`` as a JSON list: one type id
  can name units of two series), the target of references to
  any unit series;
* a scalar top-level ``x-ref`` field is a column with a foreign key to its
  target table (an unresolved one fails the build);
* every other ``x-ref`` (inside arrays or records) is a link table
  ``<series>__<field>_<subfield>...`` of (``<series>_<id>``, ``ordinal``,
  ``path``, ``<target>_<id>``), the two id columns foreign keys: ``ordinal``
  counts the record's references of that field, ``path`` holds the array
  indices leading to one as JSON (e.g. ``[3,1]`` for
  ``stations[3].accepts[1]``); references that resolve to no record (upstream
  gaps) go to ``unresolved_refs`` instead, leaving a gap in ``ordinal``;
* ``meta`` (``dcsVersion``, ``pkgVersion``, ``extractedAt``), ``series``
  (table, type, key, record count) and ``docs`` (the schema's table and column
  descriptions).

Rows are inserted in key order and the file is written afresh, so the bytes
depend only on the data (and the SQLite library version).

    uv run python -m tools.package.sqlite [--bundles DIR] [--output FILE]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from tools.datamine.check_refs import ARRAY, UNITS, Rule, rules
from tools.datamine.common import (
    DIST_DIR,
    JSON_SCHEMA_PATH,
    MANIFEST,
    REPO_ROOT,
    SERIES,
    UNIT_SERIES,
    fail,
    load_json,
)
from tools.package.bundles import BUNDLE_DIR

JSON = "JSON"  # column kind: TEXT holding JSON
SQL_TYPES = {"string": "TEXT", "number": "NUMERIC", "integer": "INTEGER"}


def sqlite_name(version: str, dcs_version: str) -> str:
    return f"dcs-world-reference-{version}-dcs{dcs_version}.sqlite"


def q(name: str) -> str:
    """``name`` as a quoted SQL identifier."""
    return '"' + name.replace('"', '""') + '"'


def _deref(document: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in node:
        node = document["definitions"][node["$ref"].rsplit("/", 1)[-1]]
    return node


def column_kind(document: dict[str, Any], node: dict[str, Any]) -> str:
    """The SQL type of a scalar schema (``BOOLEAN`` for booleans), else JSON."""
    node = _deref(document, node)
    if "anyOf" in node:
        kinds = {
            column_kind(document, n)
            for n in node["anyOf"]
            if _deref(document, n).get("type") != "null"
        }
        return kinds.pop() if len(kinds) == 1 else JSON
    if "enum" in node:
        values = node["enum"]
        if all(isinstance(v, str) for v in values):
            return "TEXT"
        if all(isinstance(v, int) and not isinstance(v, bool) for v in values):
            return "INTEGER"
        if all(isinstance(v, int | float) and not isinstance(v, bool) for v in values):
            return "NUMERIC"
        return JSON
    t = node.get("type")
    if t == "boolean":
        return "BOOLEAN"
    return SQL_TYPES.get(t, JSON) if isinstance(t, str) else JSON


def json_value(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def link_table(rule: Rule) -> str:
    return f"{rule.series}__" + "_".join(p for p in rule.path if p != ARRAY)


def key_column(table: str) -> str:
    """The primary key column of a series table or ``units``."""
    return "id" if table == UNITS else SERIES[table].id_field


def ref_column(table: str) -> str:
    return f"{table}_{key_column(table)}"


def _walk(
    node: Any, path: tuple[str, ...], index: tuple[int, ...]
) -> Iterator[tuple[tuple[int, ...], Any]]:
    """``(array indices, value)`` of every non-null value at ``path``."""
    if not path:
        if node is not None:
            yield index, node
        return
    step, rest = path[0], path[1:]
    if step == ARRAY:
        if isinstance(node, list):
            for i, item in enumerate(node):
                yield from _walk(item, rest, (*index, i))
    elif isinstance(node, dict) and step in node:
        yield from _walk(node[step], rest, index)


def _descriptions(document: dict[str, Any], type_name: str) -> dict[str, str]:
    node = document["definitions"][type_name]
    out = {"": node.get("description", "")}
    for field, sub in node["properties"].items():
        out[field] = sub.get("description", "")
    return out


def build(
    series: dict[str, dict[str, Any]],
    manifest: dict[str, Any],
    document: dict[str, Any],
    version: str,
    output: Path,
) -> dict[str, int]:
    """Write the database to ``output`` (replacing it); ``{table: rows}``."""
    all_rules = rules(document)
    scalar_refs = {
        (r.series, r.path[0]): r.target for r in all_rules if len(r.path) == 1
    }
    link_rules = [r for r in all_rules if len(r.path) > 1]
    keys: dict[str, set[Any]] = {
        name: set(series[name]) for name in SERIES
    }  # bundle keys are strings; ids compare as text
    keys[UNITS] = set().union(*(keys[u] for u in UNIT_SERIES))

    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.name + ".tmp")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    # Tables reference tables created after them: enforce by one check at the end.
    db.execute("PRAGMA foreign_keys = OFF")
    counts: dict[str, int] = {}

    def create(table: str, columns: list[str], rows: list[tuple[Any, ...]]) -> None:
        db.execute(f"CREATE TABLE {q(table)} (\n  " + ",\n  ".join(columns) + "\n)")
        if rows:
            marks = ", ".join("?" * len(rows[0]))
            db.executemany(f"INSERT INTO {q(table)} VALUES ({marks})", rows)
        counts[table] = len(rows)

    create(
        "meta",
        ["key TEXT PRIMARY KEY", "value TEXT NOT NULL"],
        [
            ("dcsVersion", manifest["dcsVersion"]),
            ("extractedAt", str(manifest.get("extractedAt", ""))),
            ("pkgVersion", version),
        ],
    )
    create(
        "series",
        [
            "name TEXT PRIMARY KEY",
            "type_name TEXT NOT NULL",
            "key_column TEXT NOT NULL",
            "records INTEGER NOT NULL",
        ],
        [
            (s.name, s.type_name, s.id_field, len(series[s.name]))
            for s in SERIES.values()
        ],
    )
    unit_series: dict[str, list[str]] = {}
    for u in UNIT_SERIES:
        for key in series[u]:
            unit_series.setdefault(key, []).append(u)
    create(
        "units",
        ["id TEXT PRIMARY KEY", "series TEXT NOT NULL"],
        sorted((k, json_value(v)) for k, v in unit_series.items()),
    )

    docs: list[tuple[str, str, str]] = []
    key_sql = {UNITS: "TEXT"}
    for s in SERIES.values():
        props = document["definitions"][s.type_name]["properties"]
        kinds = {f: column_kind(document, sub) for f, sub in props.items()}
        key_sql[s.name] = kinds[s.id_field]
        if key_sql[s.name] not in ("TEXT", "INTEGER"):
            fail(f"{s.name}: key {s.id_field} is no text or integer")
        columns = []
        for field, kind in kinds.items():
            sql = "TEXT" if kind == JSON else ("INTEGER" if kind == "BOOLEAN" else kind)
            col = f"{q(field)} {sql}"
            if field == s.id_field:
                col += " PRIMARY KEY NOT NULL"
            if (target := scalar_refs.get((s.name, field))) is not None:
                col += f" REFERENCES {q(target)}({q(key_column(target))})"
            columns.append(col)
        rows = []
        for key, record in series[s.name].items():
            row = []
            for field, kind in kinds.items():
                value = record.get(field)
                if value is not None and kind == JSON:
                    value = json_value(value)
                elif isinstance(value, dict | list):
                    fail(f"{s.name}/{key}.{field}: nested value in a scalar column")
                elif isinstance(value, bool):
                    value = int(value)
                target = scalar_refs.get((s.name, field))
                if target and value is not None and str(value) not in keys[target]:
                    fail(f"{s.name}/{key}.{field}: {value!r} is no {target} record")
                row.append(value)
            rows.append(tuple(row))
        create(s.name, columns, rows)
        docs.extend(
            (s.name, field, text)
            for field, text in _descriptions(document, s.type_name).items()
            if text
        )

    unresolved: list[tuple[Any, ...]] = []
    for rule in link_rules:
        table, src, dst = (
            link_table(rule),
            ref_column(rule.series),
            ref_column(rule.target),
        )
        if src == dst:
            fail(f"{table}: a reference from {rule.series} to itself")
        rows = []
        for key, record in series[rule.series].items():
            for ordinal, (index, value) in enumerate(_walk(record, rule.path, ())):
                path = json_value(list(index))
                if str(value) in keys[rule.target]:
                    rows.append((key, ordinal, path, value))
                else:
                    unresolved.append(
                        (rule.series, key, rule.label, path, str(value), rule.target)
                    )
        create(
            table,
            [
                f"{q(src)} {key_sql[rule.series]} NOT NULL"
                f" REFERENCES {q(rule.series)}({q(key_column(rule.series))})",
                "ordinal INTEGER NOT NULL",
                "path TEXT NOT NULL",
                f"{q(dst)} {key_sql[rule.target]} NOT NULL"
                f" REFERENCES {q(rule.target)}({q(key_column(rule.target))})",
                f"PRIMARY KEY ({q(src)}, ordinal)",
            ],
            rows,
        )
        db.execute(f"CREATE INDEX {q(table + '__' + dst)} ON {q(table)} ({q(dst)})")
        docs.append(
            (table, "", f"References of {rule.series}.{rule.label} to {rule.target}.")
        )

    create(
        "unresolved_refs",
        [
            "series TEXT NOT NULL",
            "record TEXT NOT NULL",
            "field TEXT NOT NULL",
            "path TEXT NOT NULL",
            "value TEXT NOT NULL",
            "target TEXT NOT NULL",
            "PRIMARY KEY (series, record, field, path)",
        ],
        sorted(unresolved),
    )
    create(
        "docs",
        [
            "table_name TEXT NOT NULL",
            "column_name TEXT NOT NULL",
            "description TEXT NOT NULL",
            "PRIMARY KEY (table_name, column_name)",
        ],
        sorted(docs),
    )
    db.commit()
    problems = db.execute("PRAGMA foreign_key_check").fetchall()
    if problems:
        fail(f"foreign key violations: {problems[:5]}")
    db.execute("VACUUM")
    db.close()
    tmp.replace(output)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bundles", type=Path, default=BUNDLE_DIR)
    parser.add_argument("--schema", type=Path, default=JSON_SCHEMA_PATH)
    parser.add_argument("--output", type=Path, help="Default: dist/<versioned name>.")
    args = parser.parse_args()
    manifest = load_json(args.bundles / MANIFEST)
    series = {name: load_json(args.bundles / f"{name}.json") for name in SERIES}
    version = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    output = args.output or DIST_DIR / sqlite_name(version, manifest["dcsVersion"])
    counts = build(series, manifest, load_json(args.schema), version, output)
    size = output.stat().st_size
    print(f"Wrote {len(counts)} tables ({size / 1e6:.1f} MB) to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
