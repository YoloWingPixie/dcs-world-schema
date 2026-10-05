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
from tools.package import api_docs, bundles, page_order
from tools.package import sqlite as sqlite_db
from tools.package.cookbook import snippets


@dataclass
class Built:
    path: Path
    series: dict[str, dict[str, Any]]
    manifest: dict[str, Any]
    document: dict[str, Any]
    api: api_docs.ApiRows | None = None


def _api_rows() -> api_docs.ApiRows:
    """The API docs rows from the schema sources, merged as ``task merge:json``
    and ``task build:envs`` merge them."""
    root = str(REPO_ROOT / "dcs-world-schema")
    mission, _ = merge_tree(root)
    envs = {}
    for env in ("hooks", "export", "server"):
        merged, count = merge_tree(root, subdirs=[f"globals/{env}"])
        if count:
            envs[env] = merged
    return api_docs.build_rows(mission, envs)


def _build(
    tmp: Path,
    name: str,
    series: dict[str, Any],
    manifest: dict[str, Any],
    document: dict[str, Any],
    api: api_docs.ApiRows | None = None,
) -> Path:
    out = tmp / name
    sqlite_db.build(series, manifest, document, "0.0.0", out, api)
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
    api = _api_rows()
    path = _build(tmp, "a.sqlite", made.series, made.manifest, document, api)
    return Built(path, made.series, made.manifest, document, api)


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
    again = _build(
        tmp_path, "b.sqlite", built.series, built.manifest, built.document, _api_rows()
    )
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


def test_self_description(db: sqlite3.Connection, built: Built) -> None:
    """Range-request clients render from ``schema_types`` and ``ref_paths``."""
    kinds = dict(db.execute("SELECT name, kind FROM schema_types").fetchall())
    assert set(kinds) == set(built.document["definitions"])
    assert kinds["Entity.Aircraft"] == "record"
    assert kinds["Entity.AircraftKind"] == "enum"
    (definition,) = db.execute(
        "SELECT definition FROM schema_types WHERE name = 'Entity.Station'"
    ).fetchone()
    assert "accepts" in json.loads(definition)["properties"]
    paths = {
        (s, p): (t, table)
        for s, p, t, table in db.execute(
            "SELECT series, path, target, table_name FROM ref_paths"
        )
    }
    assert paths[("aircraft", "stations[].accepts[].clsid")] == (
        "stores",
        "aircraft__stations_accepts_clsid",
    )
    assert paths[("weapons", "warhead")] == ("warheads", "weapons")
    # Every link table is described, so reverse references need no schema walk.
    links = {t for t in _tables(db) if "__" in t}
    assert links <= {table for _, table in paths.values()}


def test_reverse_reference_queries(db: sqlite3.Connection) -> None:
    rows = db.execute(
        "SELECT table_name, source_column, target_column FROM ref_paths"
        " WHERE target = 'stores' AND series = 'aircraft'"
    ).fetchall()
    found = set()
    for table, src, dst in rows:
        found |= {
            r[0]
            for r in db.execute(
                f'SELECT "{src}" FROM "{table}" WHERE "{dst}" = ?',
                ("{5CE2FF2A-645A-4197-B48D-8720AC69394F}",),
            )
        }
    assert "F-16C_50" in found
    plan = " ".join(
        str(r)
        for r in db.execute(
            "EXPLAIN QUERY PLAN SELECT id FROM weapons WHERE warhead = 'AIM_120C'"
        )
    )
    assert "INDEX" in plan


def test_search(db: sqlite3.Connection, built: Built) -> None:
    count = db.execute(
        "SELECT count(*) FROM search WHERE series != ?", (api_docs.API_SERIES,)
    ).fetchone()[0]
    assert count == sum(
        len(b)
        for n, b in built.series.items()
        if n not in ("weapon_flight", "aircraft_flight")
    )
    hits = db.execute(
        "SELECT s.series, s.id, s.name FROM search_fts f"
        " JOIN search s ON s.rowid = f.rowid"
        " WHERE search_fts MATCH ? ORDER BY rank LIMIT 20",
        ('"aim120c"*',),
    ).fetchall()
    assert ("weapons", "AIM_120C", "AIM-120C") in hits
    (name,) = db.execute(
        "SELECT name FROM search WHERE series = 'aircraft' AND id = 'F-16C_50'"
    ).fetchone()
    assert name == built.series["aircraft"]["F-16C_50"]["displayName"]


def test_page_size(db: sqlite3.Connection) -> None:
    assert db.execute("PRAGMA page_size").fetchone()[0] == sqlite_db.PAGE_SIZE


def _symbol(db: sqlite3.Connection, section: str, page: str, name: str = "") -> Any:
    row = db.execute(
        "SELECT entry FROM api_symbols WHERE section = ? AND page = ? AND name = ?",
        (section, page, name),
    ).fetchone()
    assert row, (section, page, name)
    return json.loads(row[0])


def test_api_symbols(db: sqlite3.Connection) -> None:
    sections = dict(
        db.execute(
            "SELECT section, count(*) FROM api_symbols WHERE name = '' GROUP BY section"
        )
    )
    assert (
        sections["mission"] >= 25
        and sections["hooks"] >= 20
        and sections["export"] >= 3
    )
    assert sections["types"] > 300
    classes = db.execute(
        "SELECT count(*) FROM api_symbols WHERE kind = 'class'"
    ).fetchone()[0]
    assert classes == 10
    # Reference-data types are not part of the Lua API.
    assert not db.execute(
        "SELECT 1 FROM api_symbols WHERE page LIKE 'Entity.%' OR page LIKE 'DcsDb.%'"
    ).fetchone()
    get_by_name = _symbol(db, "mission", "Unit", "getByName")
    assert (
        api_docs.tokens_text(get_by_name["sig"])
        == "Unit.getByName(name: string): Unit?"
    )
    assert {"r": "Unit"} in get_by_name["sig"]
    out_text = _symbol(db, "mission", "trigger.action", "outText")
    assert api_docs.tokens_text(out_text["sig"]) == (
        "trigger.action.outText(text: string, displayTime: number, clearview?: boolean)"
    )
    (path,) = db.execute(
        "SELECT path FROM api_symbols WHERE section = 'mission' AND page = 'Controller'"
        " AND name = 'setTask'"
    ).fetchone()
    assert path == "Controller.setTask"
    # A page's rows are stored together, page row first (one range read).
    rows = db.execute(
        "SELECT name FROM api_symbols WHERE section = 'mission' AND page = 'Unit' ORDER BY rowid"
    ).fetchall()
    assert rows[0] == ("",) and len(rows) > 40


def test_api_inheritance_and_links(db: sqlite3.Connection) -> None:
    unit = _symbol(db, "mission", "Unit")
    origin = {g["from"]: g for g in unit["inherited"]}
    assert origin["Object"]["href"] == "/api/Object/"
    assert any(m["qualified"] == "Unit:isExist" for m in origin["Object"]["members"])
    # Unit declares getCoalition itself: not listed again as inherited.
    assert "CoalitionObject" not in origin
    assert {"name": "CoalitionObject", "href": "/api/types/CoalitionObject/"} in unit[
        "inherits"
    ]
    assert unit["links"]["Unit.Category"] == "/api/types/Unit/Category/"
    obj = _symbol(db, "mission", "Object")
    assert "Unit" in {s["name"] for s in obj["subclasses"]}
    uses = db.execute(
        "SELECT label, href FROM api_type_uses WHERE section = 'types' AND type = 'Vec3'"
    ).fetchall()
    assert ("Unit:getPoint", "/api/Object/#getPoint") not in uses
    assert ("Object:getPoint", "/api/Object/#getPoint") in uses


def test_api_enum_values_name_records(db: sqlite3.Connection) -> None:
    weapons = _symbol(db, "types", "DcsId.WeaponType")
    assert weapons["valuesSeries"] == "weapons"
    refs = [v["ref"] for v in weapons["values"]]
    found = db.execute(
        f"SELECT count(*) FROM weapons WHERE id IN ({','.join('?' * len(refs))})", refs
    ).fetchone()[0]
    assert found > 400
    batumi = next(
        v
        for v in _symbol(db, "types", "DcsId.Theatre.Caucasus.AirbaseName")["values"]
        if v["key"] == "Batumi"
    )
    assert db.execute(
        "SELECT name FROM airbases WHERE id = ?", (batumi["ref"],)
    ).fetchone()


def test_api_search(db: sqlite3.Connection, built: Built) -> None:
    def hits(match: str) -> list[str]:
        return [
            r[0]
            for r in db.execute(
                "SELECT s.name FROM search_fts f JOIN search s ON s.rowid = f.rowid"
                " WHERE search_fts MATCH ? AND s.series = 'api'"
                " ORDER BY bm25(search_fts, 8.0, 2.0, 1.0) LIMIT 10",
                (match,),
            )
        ]

    assert hits('"outtext"*')[0] == "trigger.action.outText"
    assert "Unit.getByName" in hits('"getbyname"*')
    assert hits('"controller"* "settask"*')[0] == "Controller:setTask"
    if built.api:
        api = db.execute("SELECT count(*) FROM search WHERE series = 'api'").fetchone()[
            0
        ]
        assert api == len(built.api.search)


def _view(db: sqlite3.Connection, series: str, key: str) -> dict[str, Any]:
    row = db.execute(
        "SELECT view FROM record_views WHERE series = ? AND id = ?", (series, key)
    ).fetchone()
    assert row, f"{series}/{key}"
    return json.loads(row[0])


def test_record_views(db: sqlite3.Connection, built: Built) -> None:
    companions = {"weapon_flight", "aircraft_flight"}
    counts = dict(
        db.execute("SELECT series, count(*) FROM record_views GROUP BY series")
    )
    for name, bundle in built.series.items():
        assert counts.get(name, 0) == (0 if name in companions else len(bundle)), name

    weapon = _view(db, "weapons", "AIM_120C")
    assert weapon["name"] == "AIM-120C"
    record = built.series["weapons"]["AIM_120C"]
    assert weapon["record"] == {k: v for k, v in record.items() if v is not None}
    assert weapon["companion"]["weapon"] == "AIM_120C"
    groups = {(g["series"], g["path"]): g for g in weapon["referencedBy"]}
    stores = groups[("stores", "delivers[].weapon")]
    assert stores["total"] == len(stores["records"]) >= 1
    via = groups[("aircraft", "via:stores")]
    assert via["via"] == "stores"
    assert "F-16C_50" in {r[0] for r in via["records"]}

    jet = _view(db, "aircraft", "F-16C_50")
    clsid = "{5CE2FF2A-645A-4197-B48D-8720AC69394F}"
    assert jet["links"]["stores"][clsid] == "AIM-9X Sidewinder IR AAM"
    assert jet["subtitle"]
    assert "companion" in jet

    store = _view(db, "stores", clsid)
    by = {(g["series"], g["path"]) for g in store["referencedBy"]}
    assert any(s == "aircraft" for s, _ in by)
    for (view,) in db.execute("SELECT view FROM record_views"):
        for g in json.loads(view)["referencedBy"]:
            assert len(g["records"]) == min(g["total"], sqlite_db.REF_CAP)


def test_record_view_is_one_index_lookup(db: sqlite3.Connection) -> None:
    plan = " ".join(
        str(r)
        for r in db.execute(
            "EXPLAIN QUERY PLAN SELECT view FROM record_views WHERE series = ? AND id = ?",
            ("weapons", "AIM_120C"),
        )
    )
    assert "sqlite_autoindex_record_views_1" in plan
    # Key order: rowids follow (series, id).
    keys = [
        r[0:2]
        for r in db.execute("SELECT series, id, rowid FROM record_views ORDER BY rowid")
    ]
    assert keys == sorted(keys)


def test_series_views(db: sqlite3.Connection, built: Built) -> None:
    view = json.loads(
        db.execute("SELECT view FROM series_views WHERE series = 'weapons'").fetchone()[
            0
        ]
    )
    assert len(view["rows"]) == len(built.series["weapons"])
    columns = [r[2] for r in db.execute("PRAGMA index_info('weapons__scalars')")][1:]
    assert view["columns"] == columns
    row = next(r for r in view["rows"] if r[0] == "AIM_120C")
    assert row[1] == "AIM-120C"
    record = built.series["weapons"]["AIM_120C"]
    assert row[2:] == [record.get(c) for c in columns]
    if "warhead" in columns:
        assert view["labels"]["warhead"]


def test_boot_pages_are_together(built: Built) -> None:
    db = sqlite3.connect(f"file:{built.path}?mode=ro", uri=True)
    try:
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        roots = {r[0] for r in db.execute("SELECT rootpage FROM sqlite_schema")}
    finally:
        db.close()
    for whole, upper in sqlite_db.BOOT_GROUPS:
        pages = page_order.hot_pages(built.path, whole, upper)
        rest = [p for p in pages if p != 1 and not (p in roots and p < 128)]
        assert rest, (whole, upper)
        # Every hot page beyond the one-byte root pages sits in one run (other groups'
        # pages may sit between, never cold ones).
        span = rest[-1] - rest[0] + 1
        assert span <= sum(
            len(page_order.hot_pages(built.path, w, u))
            for w, u in sqlite_db.BOOT_GROUPS
        )
