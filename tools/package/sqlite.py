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

For clients that read the file over HTTP range requests (the reference site),
the database also describes itself and indexes what such a client queries:

* ``schema_types``: every JSON Schema definition (``name``, ``kind``: record,
  enum, array or other, and the ``definition`` as JSON: fields, descriptions,
  enum values and ``x-values`` constant names, ``x-ref`` targets);
* ``ref_paths``: every reference path, one row per link table or scalar ref
  column (``series``, ``path`` like ``stations[].accepts[].clsid``,
  ``target``, the ``table_name`` and its source and target id columns), so
  reverse references are plain ``SELECT``s;
* ``search`` (``series``, ``id``, display ``name``, ``subtitle``,
  ``keywords``) and its FTS5 index ``search_fts``;
* the Lua API docs (``tools.package.api_docs``): ``api_symbols`` (every page
  and member, render-ready JSON), ``api_type_uses`` (used-by) and ``search``
  rows of ``series = 'api'`` (``id`` the site path), from the merged API
  schema and the per-environment schemas (``task merge:json build:envs``);
* ``record_views``: one row per record (``series``, ``id``, ``view``), the
  whole record page as compact JSON: the record, its
  companion's record (``weapon_flight`` on a weapon), display names of every
  record it references, the records referencing it (at most ``REF_CAP``
  per group, with the full count) and its Lua scripting rows;
  ``series_views``: one row per browsable series, its browse table with the
  columns, facets and groups the site shows by default
  (``tools.package.site_views``); ``field_values``: one row per comparable
  field of a series (``series``, ``path``, ``view``), its value in every
  record (``field_views``), and ``field_paths``: each series' keyed field
  paths. Each ``view`` is a BLOB: the UTF-8 JSON,
  raw-deflate compressed (``zlib.decompress(view, -15)``). Rows are stored in
  key order, so a page is one index lookup and one contiguous read;
* an index on every scalar ref column and one covering each series' scalar
  columns (browse tables read it instead of whole rows);
* the pages a client reads first (``BOOT_GROUPS``: the upper levels of the
  per-page views and of the API docs) moved together near the start
  (``tools.package.page_order``);
* pages of ``PAGE_SIZE`` bytes, small enough that one range request fetches
  little beyond what a lookup needs.

Rows are inserted in key order and the file is written afresh, so the bytes
depend only on the data (and the SQLite library version).

    uv run python -m tools.package.sqlite [--bundles DIR] [--output FILE]
"""

from __future__ import annotations

import argparse
import json
import re
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
from tools.package import page_order, site_views
from tools.package.api_docs import ApiRows, build_rows
from tools.package.bundles import BUNDLE_DIR

JSON = "JSON"  # column kind: TEXT holding JSON
PAGE_SIZE = 4096  # range-request clients fetch whole pages
# Display-name fields, first present wins (else the key).
NAME_FIELDS = ("displayName", "name", "natoDesignation", "callsign", "countryName")
KEYWORD_MAX = 48  # longest scalar text kept as a search keyword
API_ENVS = ("hooks", "export", "server")  # env schemas besides the mission one
SQL_TYPES = {"string": "TEXT", "number": "NUMERIC", "integer": "INTEGER"}
# Pages a client reads first, laid out together in this order
# (tools.package.page_order; site/scripts/split-sqlite.ts lists the same):
# ``(whole tables, tables or indexes whose interior pages)`` for every page (the
# per-page views: the site reads its model and search names from static files,
# not from ``meta``, ``series``, ``ref_paths``, ``schema_types`` or the search
# index), then for the API docs. Page 1 and ``sqlite_schema`` always lead.
BOOT_GROUPS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (
        (),
        (
            "record_views",
            "sqlite_autoindex_record_views_1",
            "series_views",
            "sqlite_autoindex_series_views_1",
            "field_values",
            "sqlite_autoindex_field_values_1",
        ),
    ),
    (
        (),
        (
            "api_symbols",
            "sqlite_autoindex_api_symbols_1",
            "api_symbols__path",
            "api_symbols__pages",
            "api_type_uses",
            "sqlite_autoindex_api_type_uses_1",
        ),
    ),
)
REF_CAP = 200  # referencing records stored per group in a record view
HOP_MAX = 400  # second-hop reverse references only from groups this small


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


def schema_kind(node: dict[str, Any]) -> str:
    if node.get("type") == "object" or "properties" in node:
        return "record"
    if "enum" in node:
        return "enum"
    if node.get("type") == "array":
        return "array"
    return "other"


def name_variants(*names: str) -> list[str]:
    """``AIM-120C`` -> ``aim120c``, ``aim 120c``, ``aim 120 c``: searches for
    "aim120", "aim 120" and "120" all meet a token."""
    out: dict[str, None] = {}
    for name in names:
        lower = name.lower()
        squashed = "".join(c for c in lower if c.isalnum())
        spaced = " ".join("".join(c if c.isalnum() else " " for c in lower).split())
        split = ""
        for i, c in enumerate(spaced):
            prev = spaced[i - 1] if i else " "
            if (c.isdigit() and prev.isalpha()) or (c.isalpha() and prev.isdigit()):
                split += " "
            split += c
        for v in (squashed, spaced, split):
            if v:
                out[v] = None
    return list(out)


def search_rows(
    series: dict[str, dict[str, Any]],
    document: dict[str, Any],
    companions: set[str],
) -> list[tuple[str, str, str, str, str]]:
    """``(series, id, name, subtitle, keywords)`` of every record, except those
    of companion series (keyed by a reference to another series' record, like
    ``weapon_flight``: found through that record)."""
    rows = []
    for s in SERIES.values():
        if s.name in companions:
            continue
        props = document["definitions"][s.type_name]["properties"]
        kinds = {f: column_kind(document, sub) for f, sub in props.items()}
        enums = [
            f
            for f, sub in props.items()
            if kinds[f] == "TEXT" and "enum" in _deref(document, sub)
        ] + [f for f in props if f.endswith("Name") and f[:-4] in props]
        for key, record in series[s.name].items():
            name = next(
                (
                    str(record[f])
                    for f in NAME_FIELDS
                    if isinstance(record.get(f), str) and record[f]
                ),
                key,
            )
            subtitle = " · ".join(
                dict.fromkeys(
                    str(record[f])
                    for f in enums
                    if isinstance(record.get(f), str | int)
                )
            )
            words = [
                str(v)
                for f, v in record.items()
                if kinds.get(f) == "TEXT"
                and isinstance(v, str)
                and len(v) <= KEYWORD_MAX
                and f != s.id_field
            ]
            variants = name_variants(name) if name == key else name_variants(name, key)
            keywords = " ".join(dict.fromkeys([key, *variants, *words]))
            rows.append((s.name, key, name, subtitle, keywords))
    return rows


def _natural(text: str) -> tuple[Any, ...]:
    """Sort key: case-insensitive, digit runs by value (``F-15`` before ``F-117``)."""
    out: list[Any] = []
    for part in re.split(r"(\d+)", text.casefold()):
        if part:
            out.append((0, int(part), "") if part.isdigit() else (1, 0, part))
    return tuple(out)


def _strip_nulls(record: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in record.items() if v is not None}


def _schema_has(document: dict[str, Any], type_name: str, path: str) -> bool:
    """Whether a dotted path names a field of a record type (through refs,
    nullable unions, records and arrays: ``x[]`` and ``x.*`` step into the
    items of the list ``x``)."""
    node: dict[str, Any] = {"$ref": f"#/definitions/{type_name}"}

    def step(key: str) -> bool:
        nonlocal node
        node = _deref(document, node)
        options = [_deref(document, n) for n in node.get("anyOf", [node])]
        found = [
            o["items"] if key == "[]" else o["properties"][key]
            for o in options
            if ("items" in o if key == "[]" else key in o.get("properties", {}))
        ]
        if found:
            node = found[0]
        return bool(found)

    for segment in path.split("."):
        name = segment.removesuffix("[]")
        if name == "*":
            if not step("[]"):
                return False
            continue
        if not step(name) or (name != segment and not step("[]")):
            return False
    return True


class References:
    """Which records the ids of a reference name, over every series: the
    companion series (``weapon_flight``) and their parents, each series' ids,
    and the display ``names`` of records (``titles``: ``(series, id) ->
    (name, subtitle)``)."""

    def __init__(
        self,
        series: dict[str, dict[str, Any]],
        all_rules: list[Rule],
        titles: dict[tuple[str, str], tuple[str, str]],
    ) -> None:
        self.names = {k: v[0] for k, v in titles.items()}
        self.scalar_refs = {
            (r.series, r.path[0]): r.target for r in all_rules if len(r.path) == 1
        }
        self.parent = {
            n: self.scalar_refs[(n, s.id_field)]
            for n, s in SERIES.items()
            if (n, s.id_field) in self.scalar_refs
            and self.scalar_refs[(n, s.id_field)] != UNITS
        }
        self.companion = {p: c for c, p in self.parent.items()}
        self.keys = {n: {str(k) for k in series[n]} for n in SERIES}
        self.rules_at = {(r.series, r.label): r for r in all_rules}

    def owner(self, name: str) -> str:
        return self.parent.get(name, name)

    def resolve(self, target: str, value: Any) -> tuple[str, str] | None:
        """``(owner series, name)`` of a referenced id, else None."""
        key = str(value)
        for t in UNIT_SERIES if target == UNITS else [target]:
            if key in self.keys[t]:
                o = self.owner(t)
                return o, self.names.get((o, key), key)
        return None

    def path_ref(self, table: str, rel: str) -> Rule | None:
        """The reference rule of a path (a list of references: its items')."""
        return self.rules_at.get((table, rel)) or self.rules_at.get((table, f"{rel}[]"))

    def as_joined(self, table: str, rel: str, value: Any) -> Any:
        """A column's value as the site reads it: a whole column listing
        references as its join table holds them (the resolved ones), any other
        value as is."""
        rule = self.path_ref(table, rel)
        if rule is None or rule.label != f"{rel}[]" or "." in rel:
            return value
        return [
            v
            for v in (value if isinstance(value, list) else [])
            if v is not None and self.resolve(rule.target, v)
        ]


def field_views(
    series: dict[str, dict[str, Any]],
    refs: References,
    compare: dict[str, dict[str, Any]],
    document: dict[str, Any] | None = None,
) -> tuple[list[tuple[str, str, str]], list[tuple[str, str]]]:
    """``field_values`` rows ``(series, path, view)`` and ``field_paths`` rows
    ``(series, paths)``, as compact JSON in key order (``build`` stores the
    views compressed), from the site's comparable fields (``compare``:
    ``site_views.load_compare``).

    A field view holds one comparable path across a series (the site's
    ``getFieldValues`` and ``loadLinkedField``): ``values``, ``{id: value}``
    of every record holding one (``site_views.field_value``: a whole column of
    references as its join table holds them), and for a reference field
    ``links``, ``{series: {id: name}}`` per series it names, for the ids it
    holds. A keyed field (``flight.motorStages.*.impulseS``) has a view per
    key (``flight.motorStages.march.impulseS``). The ``paths`` of a series
    with keyed arrays list those keyed paths as ``[path, catalog path]``
    (``site_views.keyed_paths``).

    Every path ``compare`` names (a field's, its table's, a keyed array's)
    must name a field of its series' type in ``document``: the build fails
    on one that does not (regenerate the list: ``pnpm gen:compare-fields``
    in ``site/``)."""
    value_rows: list[tuple[str, str, str]] = []
    path_rows: list[tuple[str, str]] = []
    for name in sorted(compare):
        if name not in SERIES or name in refs.parent:
            fail(f"site compare fields: no browsable series {name}")
        spec = compare[name]
        key_fields: dict[str, str] = spec.get("keyFields", {})
        comp = refs.companion.get(name)

        def table_of(path: str, name: str = name, comp: str | None = comp) -> str:
            in_comp, _ = site_views.split_companion(path)
            if in_comp and comp is None:
                fail(f"site compare fields: {name} has no companion for {path}")
            return comp if in_comp and comp else name

        if document is not None:
            for path in [
                *(f["path"] for f in spec["fields"]),
                *(
                    (f.get("curve") or f["surfaces"])["table"]
                    for f in spec["fields"]
                    if "curve" in f or "surfaces" in f
                ),
                *spec.get("keyed", []),
            ]:
                rel = site_views.split_companion(path)[1]
                if not _schema_has(document, SERIES[table_of(path)].type_name, rel):
                    fail(
                        f"site compare fields: {name} has no field {path}; run"
                        " `pnpm gen:compare-fields` in site/ against a fresh database"
                    )
        keyed = site_views.keyed_paths(
            spec,
            {
                a: [
                    r.get(site_views.split_companion(a)[1])
                    for r in series[table_of(a)].values()
                ]
                for a in spec.get("keyed", [])
            },
        )
        if keyed:
            path_rows.append((name, json_value(keyed)))
        for field in spec["fields"]:
            path = field["path"]
            table = table_of(path)
            rel = site_views.split_companion(path)[1]
            plain = not ({"curve", "surfaces", "samples"} & field.keys())
            concrete = [c for c, k in keyed if k == path] if "*" in path else [path]
            for wanted in concrete:
                values: dict[str, Any] = {}
                for key, record in series[table].items():
                    value = site_views.field_value(field, record, wanted, key_fields)
                    if plain:
                        value = refs.as_joined(table, rel, value)
                    if site_views.present(value):
                        values[str(key)] = value
                view: dict[str, Any] = {"values": values}
                ids = {
                    site_views.js_string(x)
                    for v in values.values()
                    for x in (v if isinstance(v, list) else [v])
                    if isinstance(x, str) or site_views.is_number(x)
                }
                if field.get("ref") and ids:
                    view["links"] = {
                        t: {
                            i: refs.names[(refs.owner(t), i)]
                            for i in ids
                            if (refs.owner(t), i) in refs.names
                        }
                        for t in field["ref"]
                    }
                value_rows.append((name, wanted, json_value(view)))
    return sorted(value_rows), path_rows


def views(
    series: dict[str, dict[str, Any]],
    all_rules: list[Rule],
    titles: dict[tuple[str, str], tuple[str, str]],
    scalars: dict[str, list[str]],
    document: dict[str, Any] | None = None,
    display: dict[str, dict[str, Any]] | None = None,
    scripting: dict[str, dict[str, Any]] | None = None,
    api: site_views.ApiIndex | None = None,
) -> tuple[list[tuple[str, str, str]], list[tuple[str, str]]]:
    """``record_views`` rows ``(series, id, view)`` and ``series_views`` rows
    ``(series, view)``, both as compact JSON in key order (``build`` stores
    them compressed).

    ``titles`` are the ``(name, subtitle)`` of each ``(series, id)``; ``display``
    and ``scripting`` the site's specs (``tools.package.site_views``), checked
    against ``document``; ``api`` the Lua API the Scripting rows are checked
    against (none: no Scripting rows).

    A record view: ``name``, ``subtitle``, ``record`` (null fields dropped),
    ``companion`` (the companion series' record, if any), ``links`` (``{series:
    {id: name}}`` of every reference it holds, its companion's included) and
    ``referencedBy``: groups ``{series, path, total, records: [[id, name]]}``
    (``path`` of a companion's reference prefixed ``flight.``; ``via`` set on
    unit series reaching the record through a non-unit series' records), at
    most ``REF_CAP`` records each, and ``scripting``: the record's Scripting rows
    (``site_views.scripting_rows``), when it has any.

    A series view: ``columns`` (scalar fields but the key, schema order),
    ``rows`` (``[id, name, *values]``) and ``labels`` (``{column: {id: name}}``
    of reference columns); ``fields``, every other path the site's browse shows
    by default (``site_views.browse_paths``): ``{path: {values, links}}``,
    ``values`` one per row (null for none, a list of references only those that
    resolve), ``links`` (``{series: {id: name}}``) naming the records they
    reference; ``groups``, for the site's group-by reference: ``{path: {id:
    [series, id, name]}}``, the first record each row's reference names."""
    display = display or {}
    scripting = scripting or {}
    refs = References(series, all_rules, titles)
    names, parent, companion, keys = refs.names, refs.parent, refs.companion, refs.keys
    scalar_refs = refs.scalar_refs
    owner, resolve, path_ref = refs.owner, refs.resolve, refs.path_ref

    # Reverse references: target series -> id -> (series, path) -> source ids.
    reverse: dict[str, dict[str, dict[tuple[str, str], set[str]]]] = {}
    for rule in all_rules:
        if parent.get(rule.series) == rule.target:
            continue  # a companion's key: its own record
        for key, record in series[rule.series].items():
            for value in rule.values(record):
                hit = resolve(rule.target, value)
                if hit is None:
                    continue
                targets = (
                    [t for t in UNIT_SERIES if str(value) in keys[t]]
                    if rule.target == UNITS
                    else [rule.target]
                )
                o = owner(rule.series)
                path = rule.label if o == rule.series else f"flight.{rule.label}"
                for t in targets:
                    reverse.setdefault(t, {}).setdefault(str(value), {}).setdefault(
                        (o, path), set()
                    ).add(str(key))

    def listed(ser: str, ids: set[str]) -> dict[str, Any]:
        records = sorted(
            ([i, names.get((ser, i), i)] for i in ids),
            key=lambda r: (_natural(r[1]), r[0]),
        )
        return {"total": len(records), "records": records[:REF_CAP]}

    def referenced_by(ser: str, key: str) -> list[dict[str, Any]]:
        groups = reverse.get(ser, {}).get(key, {})
        out = [
            {"series": o, "path": path, **listed(o, ids)}
            for (o, path), ids in sorted(groups.items())
        ]
        hops: dict[tuple[str, str], set[str]] = {}
        for (o, _), ids in sorted(groups.items()):
            if SERIES[o].unit or len(ids) > HOP_MAX:
                continue
            for i in ids:
                for (src_series, path), srcs in reverse.get(o, {}).get(i, {}).items():
                    if SERIES[src_series].unit and not path.startswith("flight."):
                        hops.setdefault((src_series, o), set()).update(srcs)
        out += [
            {"series": u, "path": f"via:{o}", "via": o, **listed(u, ids)}
            for (u, o), ids in sorted(hops.items())
        ]
        return out

    record_rows: list[tuple[str, str, str]] = []
    for name in sorted(SERIES):
        if name in parent:
            continue
        comp = companion.get(name)
        for key, record in series[name].items():
            k = str(key)
            links: dict[str, dict[str, str]] = {}
            parts = [(name, record)]
            extra = series[comp].get(key) if comp else None
            if extra is not None and comp:
                parts.append((comp, extra))
            for ser, rec in parts:
                for rule in all_rules:
                    if rule.series != ser:
                        continue
                    for value in rule.values(rec):
                        hit = resolve(rule.target, value)
                        if hit:
                            links.setdefault(hit[0], {})[str(value)] = hit[1]
            title, subtitle = titles.get((name, k), (k, ""))
            view: dict[str, Any] = {
                "name": title,
                "subtitle": subtitle,
                "record": _strip_nulls(record),
            }
            if extra is not None:
                view["companion"] = _strip_nulls(extra)
            view["links"] = {
                o: dict(sorted(m.items())) for o, m in sorted(links.items())
            }
            view["referencedBy"] = referenced_by(name, k)
            if api is not None and (
                script := site_views.scripting_rows(
                    scripting.get(name), name, k, view["record"], api
                )
            ):
                view["scripting"] = script
            record_rows.append((name, k, json_value(view)))

    def field_view(name: str, path: str) -> dict[str, Any]:
        """A path's values over a series' records and the names of the records
        they reference (the site's ``getFieldValues`` and ``loadLinkedField``)."""
        in_comp, rel = site_views.split_companion(path)
        comp = companion.get(name) if in_comp else None
        table = comp or name
        if document is not None and not _schema_has(
            document, SERIES[table].type_name, rel
        ):
            fail(f"site series display: {name} has no field {path}")
        rule = path_ref(table, rel)
        values: list[Any] = []
        links: dict[str, dict[str, str]] = {}
        for key, record in series[name].items():
            source = series[comp].get(key) if comp else record
            value = site_views.value_at(source, rel) if source is not None else None
            value = refs.as_joined(table, rel, value)
            if not site_views.present(value):
                values.append(None)
                continue
            values.append(value)
            if rule is None:
                continue
            for v in value if isinstance(value, list) else [value]:
                if isinstance(v, str | int) and (hit := resolve(rule.target, v)):
                    links.setdefault(hit[0], {})[str(v)] = hit[1]
        return {"values": values, "links": links}

    def group_targets(name: str, path: str) -> dict[str, list[str]]:
        """The first record a reference field names per record id, as
        ``[series, id, name]`` (the site's ``getGroupTargets``)."""
        rule = path_ref(name, path)
        if rule is None or "." in path:
            return {}
        out: dict[str, list[str]] = {}
        for key, record in series[name].items():
            value = record.get(path)
            if isinstance(value, list):
                # Its join table's ordinal 0: the first reference, if it resolves.
                value = next((v for v in value if v is not None), None)
            if value is None:
                continue
            k = str(value)
            if rule.target == UNITS:
                ser = next((u for u in UNIT_SERIES if k in keys[u]), None)
            else:
                ser = owner(rule.target) if k in keys[rule.target] else None
            if ser is not None:
                out[str(key)] = [ser, k, names.get((ser, k), k)]
        return out

    series_rows: list[tuple[str, str]] = []
    for name in sorted(SERIES):
        if name in parent:
            continue
        records = series[name]
        columns = scalars[name]
        labels: dict[str, dict[str, str]] = {}
        for c in columns:
            target = scalar_refs.get((name, c))
            if target is None:
                continue
            for r in records.values():
                if r.get(c) is not None and (hit := resolve(target, r[c])):
                    labels.setdefault(c, {})[str(r[c])] = hit[1]
        rows = [
            [str(k), names.get((name, str(k)), str(k)), *(r.get(c) for c in columns)]
            for k, r in records.items()
        ]
        view = {
            "columns": columns,
            "rows": rows,
            "labels": {c: dict(sorted(m.items())) for c, m in sorted(labels.items())},
        }
        shown = display.get(name, {})
        fields = {
            p: field_view(name, p)
            for p in site_views.browse_paths(shown)
            if p not in columns and p != SERIES[name].id_field
        }
        if fields:
            view["fields"] = fields
        group = (shown.get("groupBy") or {}).get("path")
        if group and (grouped := group_targets(name, group)):
            view["groups"] = {group: grouped}
        series_rows.append((name, json_value(view)))
    return sorted(record_rows), series_rows


def build(
    series: dict[str, dict[str, Any]],
    manifest: dict[str, Any],
    document: dict[str, Any],
    version: str,
    output: Path,
    api: ApiRows | None = None,
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
    db.execute(f"PRAGMA page_size = {PAGE_SIZE}")
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
    scalars: dict[str, list[str]] = {}
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
        for field in kinds:
            if (s.name, field) in scalar_refs:
                db.execute(
                    f"CREATE INDEX {q(s.name + '__' + field)} ON {q(s.name)} ({q(field)})"
                )
        scalar = [f for f, k in kinds.items() if k != JSON and f != s.id_field]
        scalars[s.name] = scalar
        if scalar:
            cols = ", ".join(q(f) for f in [s.id_field, *scalar])
            db.execute(
                f"CREATE INDEX {q(s.name + '__scalars')} ON {q(s.name)} ({cols})"
            )
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

    ref_paths = [
        (
            link_table(rule),
            rule.series,
            rule.label,
            rule.target,
            ref_column(rule.series),
            ref_column(rule.target),
        )
        for rule in link_rules
    ] + [
        (series_name, series_name, field, target, key_column(series_name), field)
        for (series_name, field), target in scalar_refs.items()
    ]
    create(
        "ref_paths",
        [
            "table_name TEXT NOT NULL",
            "series TEXT NOT NULL",
            "path TEXT NOT NULL",
            "target TEXT NOT NULL",
            "source_column TEXT NOT NULL",
            "target_column TEXT NOT NULL",
            "PRIMARY KEY (series, path)",
        ],
        sorted(ref_paths, key=lambda r: (r[1], r[2])),
    )
    create(
        "schema_types",
        ["name TEXT PRIMARY KEY", "kind TEXT NOT NULL", "definition TEXT NOT NULL"],
        sorted(
            # Field order as the schema declares it (renderers list fields in it).
            (
                name,
                schema_kind(node),
                json.dumps(node, ensure_ascii=False, separators=(",", ":")),
            )
            for name, node in document["definitions"].items()
        ),
    )
    records_search = search_rows(
        series, document, {n for n, f in scalar_refs if f == SERIES[n].id_field}
    )
    create(
        "search",
        [
            "series TEXT NOT NULL",
            "id TEXT NOT NULL",
            "name TEXT NOT NULL",
            "subtitle TEXT NOT NULL",
            "keywords TEXT NOT NULL",
            "PRIMARY KEY (series, id)",
        ],
        sorted(records_search + (api.search if api else [])),
    )
    # Names by series without the keywords: link labels read this index only.
    db.execute("CREATE INDEX search__names ON search (series, id, name)")
    db.execute(
        "CREATE VIRTUAL TABLE search_fts USING fts5("
        "name, keywords, subtitle, content='search', content_rowid='rowid',"
        " tokenize='unicode61 remove_diacritics 2')"
    )
    db.execute("INSERT INTO search_fts(search_fts) VALUES ('rebuild')")
    db.execute("INSERT INTO search_fts(search_fts) VALUES ('optimize')")

    if api is not None:
        create(
            "api_symbols",
            [
                "section TEXT NOT NULL",
                "page TEXT NOT NULL",
                "name TEXT NOT NULL",
                "path TEXT NOT NULL",
                "kind TEXT NOT NULL",
                "parent TEXT NOT NULL",
                "summary TEXT NOT NULL",
                "members INTEGER NOT NULL",
                "entry TEXT NOT NULL",
                "PRIMARY KEY (section, page, name)",
            ],
            api.symbols,  # display order: a page row, then its members
        )
        db.execute("CREATE INDEX api_symbols__path ON api_symbols (path)")
        # The page listing (API home) reads this index only.
        db.execute(
            "CREATE INDEX api_symbols__pages ON api_symbols"
            " (name, section, page, kind, parent, members, summary) WHERE name = ''"
        )
        create(
            "api_type_uses",
            [
                "section TEXT NOT NULL",
                "type TEXT NOT NULL",
                "label TEXT NOT NULL",
                "href TEXT NOT NULL",
                "PRIMARY KEY (section, type, label)",
            ],
            api.uses,
        )
        docs.extend(
            [
                (
                    "api_symbols",
                    "",
                    "Lua API pages and their members (tools/package/api_docs.py).",
                ),
                (
                    "api_type_uses",
                    "",
                    "Lua API functions taking or returning each type.",
                ),
            ]
        )
    titles = {(r[0], r[1]): (r[2], r[3]) for r in records_search}
    record_views, series_views = views(
        series,
        all_rules,
        titles,
        scalars,
        document,
        site_views.load_display(),
        site_views.load_scripting(),
        site_views.ApiIndex(api.symbols) if api else None,
    )
    create(
        "record_views",
        [
            "series TEXT NOT NULL",
            "id TEXT NOT NULL",
            "view BLOB NOT NULL",
            "PRIMARY KEY (series, id)",
        ],
        [(s, i, site_views.compress(v)) for s, i, v in record_views],
    )
    create(
        "series_views",
        ["series TEXT PRIMARY KEY", "view BLOB NOT NULL"],
        [(s, site_views.compress(v)) for s, v in series_views],
    )
    field_values, field_paths = field_views(
        series,
        References(series, all_rules, titles),
        site_views.load_compare(),
        document,
    )
    create(
        "field_values",
        [
            "series TEXT NOT NULL",
            "path TEXT NOT NULL",
            "view BLOB NOT NULL",
            "PRIMARY KEY (series, path)",
        ],
        [(s, p, site_views.compress(v)) for s, p, v in field_values],
    )
    create(
        "field_paths",
        ["series TEXT PRIMARY KEY", "paths TEXT NOT NULL"],
        sorted(field_paths),
    )
    docs.extend(
        [
            (
                "record_views",
                "",
                "Each record page as one JSON document, raw-deflate compressed.",
            ),
            (
                "series_views",
                "",
                "Each series' browse table as one JSON document, raw-deflate compressed.",
            ),
            (
                "field_values",
                "",
                "Each comparable field of a series across its records as one JSON"
                " document ({values: {id: value}, links}), raw-deflate compressed.",
            ),
            (
                "field_paths",
                "",
                "The keyed field paths of a series (motor stages by stage) as JSON"
                " [[path, catalog path], ...].",
            ),
        ]
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
    page_order.reorder(tmp, BOOT_GROUPS)
    tmp.replace(output)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bundles", type=Path, default=BUNDLE_DIR)
    parser.add_argument("--schema", type=Path, default=JSON_SCHEMA_PATH)
    parser.add_argument("--output", type=Path, help="Default: dist/<versioned name>.")
    parser.add_argument(
        "--api-schema",
        type=Path,
        default=DIST_DIR / "dcs-world-api-schema.json",
        help="Merged API schema; dcs-world-api-<env>-schema.json beside it.",
    )
    parser.add_argument(
        "--no-api", action="store_true", help="Leave out the Lua API docs."
    )
    args = parser.parse_args()
    manifest = load_json(args.bundles / MANIFEST)
    series = {name: load_json(args.bundles / f"{name}.json") for name in SERIES}
    version = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    output = args.output or DIST_DIR / sqlite_name(version, manifest["dcsVersion"])
    api = None
    if not args.no_api:
        if not args.api_schema.exists():
            fail(f"{args.api_schema} missing: run `task merge:json build:envs`")
        envs = {}
        for env in API_ENVS:
            path = args.api_schema.with_name(f"dcs-world-api-{env}-schema.json")
            if path.exists():
                envs[env] = load_json(path)
            elif env != "server":
                fail(f"{path} missing: run `task build:envs`")
        api = build_rows(load_json(args.api_schema), envs)
    counts = build(series, manifest, load_json(args.schema), version, output, api)
    size = output.stat().st_size
    print(f"Wrote {len(counts)} tables ({size / 1e6:.1f} MB) to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
