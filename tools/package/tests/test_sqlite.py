"""The SQLite database (``tools.package.sqlite``) and the SQL snippets of
docs/cookbook.md.

Builds the database from ``dcs-world-reference/latest`` into a temporary
directory; with ``DCS_REF_SQLITE`` set (``task package:test``) checks that
built file against ``dist/reference`` instead.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from tools.datamine.common import (
    JSON_SCHEMA_PATH,
    LATEST,
    MANIFEST,
    REFERENCE_DATA_DIR,
    REPO_ROOT,
    SERIES,
    UNIT_SERIES,
    load_json,
)
from tools.export_jsonschema import export
from tools.merge import merge_tree
from tools.package import bundles
from tools.package import sqlite as sqlite_db
from tools.package.cookbook import snippets


@dataclass
class Built:
    path: Path
    series: dict[str, dict[str, Any]]
    manifest: dict[str, Any]
    document: dict[str, Any]


def _build(
    tmp: Path,
    name: str,
    series: dict[str, Any],
    manifest: dict[str, Any],
    document: dict[str, Any],
) -> Path:
    out = tmp / name
    sqlite_db.build(series, manifest, document, "0.0.0", out)
    return out


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Built:
    given = os.environ.get("DCS_REF_SQLITE")
    if given:
        path = Path(given)
        if not path.is_absolute():
            path = REPO_ROOT / path
        data = bundles.BUNDLE_DIR
        series = {n: load_json(data / f"{n}.json") for n in SERIES}
        return Built(
            path, series, load_json(data / MANIFEST), load_json(JSON_SCHEMA_PATH)
        )
    tmp = tmp_path_factory.mktemp("sqlite")
    made = bundles.build(REFERENCE_DATA_DIR / LATEST, tmp / "bundles")
    merged, _ = merge_tree(str(REPO_ROOT / "dcs-world-schema"))
    document = export(merged["types"])
    path = _build(tmp, "a.sqlite", made.series, made.manifest, document)
    return Built(path, made.series, made.manifest, document)


@pytest.fixture(scope="module")
def db(built: Built) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(f"file:{built.path}?mode=ro", uri=True)
    yield conn
    conn.close()


def _tables(db: sqlite3.Connection) -> list[str]:
    rows = db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    return sorted(r[0] for r in rows)


def test_row_counts_equal_the_bundles(db: sqlite3.Connection, built: Built) -> None:
    for name, bundle in built.series.items():
        (count,) = db.execute(f'SELECT count(*) FROM "{name}"').fetchone()
        assert count == len(bundle), name
    recorded = dict(db.execute("SELECT name, records FROM series").fetchall())
    assert recorded == {n: len(b) for n, b in built.series.items()}
    units = {k for u in UNIT_SERIES for k in built.series[u]}
    assert db.execute("SELECT count(*) FROM units").fetchone()[0] == len(units)


def test_meta(db: sqlite3.Connection, built: Built) -> None:
    meta = dict(db.execute("SELECT key, value FROM meta").fetchall())
    assert meta["dcsVersion"] == built.manifest["dcsVersion"]
    assert meta["pkgVersion"]


def test_foreign_keys_are_clean(db: sqlite3.Connection) -> None:
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    links = [t for t in _tables(db) if "__" in t]
    assert "aircraft__stations_accepts_clsid" in links
    for table in links:
        fks = db.execute(f'PRAGMA foreign_key_list("{table}")').fetchall()
        assert len(fks) == 2, table
    fks = db.execute('PRAGMA foreign_key_list("weapons")').fetchall()
    assert [(f[2], f[3]) for f in fks] == [("warheads", "warhead")]


def test_columns_round_trip(db: sqlite3.Connection, built: Built) -> None:
    db.row_factory = sqlite3.Row
    try:
        row = db.execute("SELECT * FROM aircraft WHERE id = 'F-16C_50'").fetchone()
    finally:
        db.row_factory = None
    record = built.series["aircraft"]["F-16C_50"]
    assert row["displayName"] == record["displayName"]
    assert row["flyable"] == int(record["flyable"])
    assert json.loads(row["stations"]) == record["stations"]
    (country_id,) = db.execute(
        "SELECT id FROM countries WHERE shortName = 'USA'"
    ).fetchone()
    assert country_id == 2


def test_joins(db: sqlite3.Connection, built: Built) -> None:
    joined = db.execute(
        "SELECT count(*) FROM weapons w JOIN warheads h ON h.id = w.warhead"
    ).fetchone()[0]
    assert joined == sum(1 for w in built.series["weapons"].values() if "warhead" in w)
    stations = db.execute(
        "SELECT count(*) FROM aircraft__stations_accepts_clsid WHERE aircraft_id = 'F-16C_50'"
    ).fetchone()[0]
    unresolved = db.execute(
        "SELECT count(*) FROM unresolved_refs WHERE record = 'F-16C_50'"
    ).fetchone()[0]
    record = built.series["aircraft"]["F-16C_50"]
    assert stations + unresolved == sum(len(s["accepts"]) for s in record["stations"])
    path = db.execute(
        "SELECT path, stores_clsid FROM aircraft__stations_accepts_clsid"
        " WHERE aircraft_id = 'F-16C_50' AND ordinal = 0"
    ).fetchone()
    assert path == ("[0,0]", record["stations"][0]["accepts"][0]["clsid"])


def test_unresolved_refs_resolve_to_nothing(
    db: sqlite3.Connection, built: Built
) -> None:
    rows = db.execute("SELECT series, value, target FROM unresolved_refs").fetchall()
    assert rows, "the data has upstream gaps"
    for _, value, target in rows:
        tables = UNIT_SERIES if target == "units" else [target]
        assert all(value not in built.series[t] for t in tables)


def test_docs(db: sqlite3.Connection) -> None:
    (text,) = db.execute(
        "SELECT description FROM docs WHERE table_name = 'stores' AND column_name = 'clsid'"
    ).fetchone()
    assert text == "Unique store CLSID."


def test_deterministic(built: Built, tmp_path: Path) -> None:
    if os.environ.get("DCS_REF_SQLITE"):
        pytest.skip("checked when building")
    again = _build(tmp_path, "b.sqlite", built.series, built.manifest, built.document)
    assert again.read_bytes() == built.path.read_bytes()


# Recipe slug -> (minimum rows, text in the rows); every SQL snippet needs one.
EXPECTED = {
    "which-aircraft-can-carry-the-aim-120c": (5, "F-16C_50"),
    "runway-ends-and-magnetic-bearings-for-batumi": (
        2,
        "('13/31', '13', 124.5, 131.4)",
    ),
    "sam-threat-ranges-on-a-map": (10, "'SA-10', 120.0"),
    "find-stores-by-display-name": (10, "GBU-12"),
    "airbase-stands-that-fit-an-aircraft": (13, "67.1"),
    "navaids-for-a-runway": (2, "BEACON_TYPE_ILS_LOCALIZER"),
    "ai-tasks-for-a-cap-flight": (10, "'Orbit'"),
    "loadout-rules-of-a-store": (1, "C-101CC"),
}
SQL = {s.recipe: s.code for s in snippets() if s.lang == "sql"}


def test_every_sql_snippet_is_checked() -> None:
    assert sorted(SQL) == sorted(EXPECTED)


@pytest.mark.parametrize("recipe", sorted(SQL))
def test_sql_snippet(db: sqlite3.Connection, recipe: str) -> None:
    rows = db.execute(SQL[recipe]).fetchall()
    minimum, text = EXPECTED[recipe]
    assert len(rows) >= minimum, rows
    assert text in str(rows), rows
