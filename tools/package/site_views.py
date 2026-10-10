"""What the reference site's page views precompute from the site's own
configuration (``tools.package.sqlite`` ``views``).

The site keeps two specs as JSON so this package reads the same lists the
site renders from:

* ``site/src/lib/series-display.json`` (``lib/series-display.ts``): per series
  the default browse ``columns``, ``facets`` and ``groupBy``. Every configured
  path outside a series' scalar columns goes into its series view
  (``browse_paths``), as does each row's group-by target;
* ``site/src/lib/api/scripting.json`` (``lib/api/scripting.ts``): per series the
  Lua class, member and enum pages naming its records. Each record view holds
  the record's Scripting rows (``scripting_rows``), checked against the Lua API
  rows: an enum row only when the enum lists the record, a member only when it
  exists;
* ``site/src/lib/compare-fields.json`` (``site/scripts/build-compare-fields.ts``):
  per series every comparable field of its catalog (``compareAs`` set) and how
  to read it. The site's catalog decides what is comparable; this package only
  reads the values each entry names (``field_value``, ``keyed_paths``), as the
  site's ``valuesAt`` and ``keyedFieldPaths`` (lib/catalog.ts,
  lib/db/reference.ts) read them.

The views are stored deflate-compressed (``compress``): raw deflate, no zlib
header, as ``DecompressionStream("deflate-raw")`` reads it.
"""

from __future__ import annotations

import json
import re
import zlib
from collections.abc import Iterable
from typing import Any
from urllib.parse import quote

from tools.datamine.common import REPO_ROOT, load_json

SITE_LIB = REPO_ROOT / "site" / "src" / "lib"
SERIES_DISPLAY_PATH = SITE_LIB / "series-display.json"
SCRIPTING_PATH = SITE_LIB / "api" / "scripting.json"
COMPARE_PATH = SITE_LIB / "compare-fields.json"
# A path under this prefix reads the companion's record (site lib/catalog.ts).
COMPANION_PREFIX = "flight"
LUA_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

Json = dict[str, Any]


def load_display() -> dict[str, Json]:
    return load_json(SERIES_DISPLAY_PATH)


def load_scripting() -> dict[str, Json]:
    return load_json(SCRIPTING_PATH)


def load_compare() -> dict[str, Json]:
    return load_json(COMPARE_PATH)


def compress(text: str) -> bytes:
    """``text`` as UTF-8, raw-deflated (no header) at the highest level."""
    packer = zlib.compressobj(9, zlib.DEFLATED, -15)
    return packer.compress(text.encode("utf-8")) + packer.flush()


def decompress(blob: bytes) -> str:
    return zlib.decompress(blob, -15).decode("utf-8")


def browse_paths(display: Json) -> list[str]:
    """Every path a series' browse page shows by default: its columns, facets,
    grouped columns and group fallback, in that order."""
    group = display.get("groupBy") or {}
    paths = [
        *display.get("columns", []),
        *display.get("facets", []),
        *group.get("columns", []),
        *([group["fallback"]] if group.get("fallback") else []),
    ]
    return list(dict.fromkeys(paths))


def split_companion(path: str) -> tuple[bool, str]:
    """``(in the companion, rest)``: ``flight.machMax`` -> ``(True, "machMax")``."""
    if path.startswith(f"{COMPANION_PREFIX}."):
        return True, path[len(COMPANION_PREFIX) + 1 :]
    return False, path


def value_at(record: Any, path: str) -> Any:
    """The value at a dotted path of a record, None when a step is missing."""
    node = record
    for step in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(step)
    return node


def present(value: Any) -> bool:
    """As the site's ``present``: neither null nor an empty list."""
    return value is not None and value != []


def is_number(value: Any) -> bool:
    """JavaScript's ``typeof value === "number"`` for a JSON value."""
    return isinstance(value, int | float) and not isinstance(value, bool)


# Compare fields ---------------------------------------------------------------


def walk(
    root: Any, path: str, key_fields: dict[str, str]
) -> list[tuple[str, Any, Json]]:
    """Every ``(concrete path, value, holder)`` a catalog path reaches in its
    root (the record, or its companion's for ``flight.`` paths), as the site's
    ``walkPath``: ``x[]`` steps into each item of the list ``x``, ``*`` into
    each item of a keyed array, named by its ``key_fields`` field. Absent, null
    and empty values are skipped."""
    in_companion, rest = split_companion(path)
    segments = rest.split(".")
    out: list[tuple[str, Any, Json]] = []

    def join(a: str, b: str) -> str:
        return f"{a}.{b}" if a else b

    def step(node: Any, i: int, keyed: str, concrete: str) -> None:
        segment = segments[i]
        if segment == "*":
            if not isinstance(node, list):
                return
            key_field = key_fields.get(keyed, "key")
            for item in node:
                if isinstance(item, dict):
                    key = (
                        js_string(item[key_field]) if key_field in item else "undefined"
                    )
                    step(item, i + 1, join(keyed, "*"), join(concrete, key))
            return
        if not isinstance(node, dict):
            return
        field = segment.removesuffix("[]")
        value = node.get(field)
        if i == len(segments) - 1:
            if present(value):
                out.append((join(concrete, field), value, node))
        elif field == segment:
            step(value, i + 1, join(keyed, segment), join(concrete, field))
        elif isinstance(value, list):
            for j, item in enumerate(value):
                step(item, i + 1, join(keyed, segment), f"{join(concrete, field)}[{j}]")

    start = COMPANION_PREFIX if in_companion else ""
    step(root, 0, start, start)
    return out


def curve_of(rows: Any, x: str, y: str) -> Json | None:
    """The site's ``curveOf``: a table's ``y`` column over its ``x`` column."""
    xs: list[Any] = []
    ys: list[Any] = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and is_number(row.get(x)) and is_number(row.get(y)):
            xs.append(row[x])
            ys.append(row[y])
    return {"x": xs, "y": ys} if xs else None


def surfaces_of(items: Any, rows: str, cols: str, z: str) -> list[Json]:
    """The site's ``surfacesOf``: the grid ``z`` of each item holding it, with
    the item's axes (a missing axis left out, as ``JSON.stringify`` drops it)."""
    out = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and isinstance(item.get(z), list):
            surface = {
                k: item[f] for k, f in (("rows", rows), ("cols", cols)) if f in item
            }
            surface["z"] = item[z]
            out.append(surface)
    return out


def samples_of(holder: Json, list_field: str, step_field: str) -> Json | None:
    """A Mach-sampled list as its record holds it: the list and its step (when
    a number), the fields the site's ``samplesOf`` reads; None when the list
    holds no number (the site has no curve for it)."""
    values = holder.get(list_field)
    if not isinstance(values, list) or not any(is_number(v) for v in values):
        return None
    out: Json = {list_field: values}
    if is_number(holder.get(step_field)):
        out[step_field] = holder[step_field]
    return out


def field_value(field: Json, root: Any, wanted: str, key_fields: dict[str, str]) -> Any:
    """A record's value of a comparable ``field`` (a ``compare-fields.json``
    entry) at the concrete path ``wanted`` (the field's own path, or one of its
    keyed paths), as the site compares it; None when it has none. ``root`` is
    the record, or its companion's for ``flight.`` paths; ``key_fields`` the
    series' keyed arrays."""
    table = field.get("curve") or field.get("surfaces")
    if table is not None:
        rows = value_at(root, split_companion(table["table"])[1])
        if "curve" in field:
            return curve_of(rows, table["x"], table["y"])
        return surfaces_of(rows, table["rows"], table["cols"], table["z"]) or None
    samples = field.get("samples")
    for path, value, holder in walk(root, field["path"], key_fields):
        if path != wanted:
            continue
        if samples is None:
            return value
        if (found := samples_of(holder, samples["list"], samples["step"])) is not None:
            return found
    return None


def sqlite_key(item: Any, key_field: str) -> Any:
    """SQLite's ``json_extract(item, '$.<key_field>')``: a boolean as 0 or 1,
    an object or array as its JSON text."""
    if not isinstance(item, dict):
        return None
    value = item.get(key_field)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, dict | list):
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    return value


def keyed_paths(spec: Json, columns: dict[str, list[Any]]) -> list[list[str]]:
    """``[concrete path, catalog path]`` of a series' keyed fields, as the
    site's ``keyedFieldPaths``: per keyed array (``spec["keyed"]``), each key
    its items hold, most common first, then every comparable field under it.
    ``columns`` holds each array's column value of every record."""
    out: list[list[str]] = []
    for array in spec.get("keyed", []):
        key_field = spec["keyFields"][array]
        counts: dict[Any, int] = {}
        for value in columns[array]:
            # json_each: an array's items, an object's member values.
            if isinstance(value, dict):
                items = list(value.values())
            else:
                items = value if isinstance(value, list) else []
            for item in items:
                key = sqlite_key(item, key_field)
                if key is not None:
                    counts[key] = counts.get(key, 0) + 1
        # SQLite's GROUP BY order (numbers before text), then by count.
        keys = sorted(counts, key=lambda k: (isinstance(k, str), k))
        keys.sort(key=lambda k: -counts[k])
        prefix = f"{array}.*."
        for key in keys:
            for field in spec["fields"]:
                if field["path"].startswith(prefix):
                    concrete = field["path"].replace(
                        prefix, f"{array}.{js_string(key)}.", 1
                    )
                    out.append([concrete, field["path"]])
    return out


# Scripting rows ---------------------------------------------------------------


def encode_uri_component(text: str) -> str:
    """JavaScript's ``encodeURIComponent``."""
    return quote(text, safe="-_.!~*'()")


def api_href(section: str, name: str) -> str:
    """The site's ``apiHref`` (lib/api/routes.ts)."""
    path = "/".join(encode_uri_component(p) for p in name.split("."))
    return f"/api/{path}/" if section == "mission" else f"/api/{section}/{path}/"


def js_string(value: Any) -> str:
    """JavaScript's ``String(value)`` of a JSON scalar."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _literal(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return js_string(value)


def names_key(constant: str, key: str) -> bool:
    """Whether a DCS constant name (``SENSOR_OPTICAL``) names an enum key (``OPTIC``)."""
    last = constant.split("_")[-1]
    return bool(last) and last.startswith(key)


def enum_value_id(key: str) -> str:
    return f"v-{encode_uri_component(key)}"


def enum_member_text(page: str, key: str) -> str:
    """``Enum.KEY``, or ``Enum["Key with spaces"]`` when the key is no Lua name."""
    if LUA_NAME.fullmatch(key):
        return f"{page}.{key}"
    return f"{page}[{json.dumps(key, ensure_ascii=False)}]"


class ApiIndex:
    """The mission classes and members by path, and the type enums by page,
    from ``api_symbols`` rows (``tools.package.api_docs``)."""

    def __init__(self, symbols: Iterable[tuple[Any, ...]]) -> None:
        self.calls: dict[str, tuple[str, str]] = {}
        self.enums: dict[str, Json] = {}
        for section, page, name, path, _kind, _parent, _summary, _n, entry in symbols:
            if section == "mission":
                base = api_href("mission", page)
                if name == "":
                    self.calls[path] = (base, page)
                    continue
                m = json.loads(entry)
                href = m.get("href") or f"{base}#{m.get('anchor')}"
                self.calls[path] = (href, f"{m.get('qualified') or path}()")
            elif section == "types" and name == "":
                e = json.loads(entry)
                if e.get("kind") == "enum" and e.get("values") is not None:
                    self.enums[page] = {
                        "values": e["values"],
                        "series": e.get("valuesSeries"),
                    }


def _text(text: str, href: str | None = None, code: bool = False) -> Json:
    out: Json = {"text": text}
    if href is not None:
        out["href"] = href
    if code:
        out["code"] = True
    return out


def _enum_link(page: str, key: str) -> Json:
    anchor = encode_uri_component(enum_value_id(key))
    return _text(
        enum_member_text(page, key), f"{api_href('types', page)}#{anchor}", True
    )


def scripting_rows(
    spec: Json | None, series: str, key: str, data: Json, api: ApiIndex
) -> list[Json]:
    """A record's Scripting rows (the site's ``ScriptingRow``): its Lua class,
    the member and enum values naming it, each kept only when ``api`` confirms
    it. ``data`` is the record as its view holds it."""
    if not spec:
        return []
    theatre = data.get("theatre") if isinstance(data.get("theatre"), str) else ""
    enum_names = [
        e.replace("{theatre}", theatre) if "{theatre}" in e else e
        for e in spec.get("enums", [])
        if "{theatre}" not in e or theatre
    ]
    rows: list[Json] = []
    cls = spec.get("class")
    if cls and (hit := api.calls.get(cls)):
        rows.append(
            {
                "id": "class",
                "label": _text("Lua class"),
                "value": _text(cls, hit[0], True),
            }
        )

    # The record in its enums (the enum must list this series' records and this one).
    listed: list[tuple[str, Json]] = []
    for page in enum_names:
        e = api.enums.get(page)
        if e is None or e["series"] != series:
            continue
        v = next((x for x in e["values"] if x.get("ref") == key), None)
        if v is not None:
            listed.append((page, v))
    member = api.calls.get(spec["member"]) if spec.get("member") else None
    if member and listed:
        rows.append(
            {
                "id": "member",
                "label": _text(member[1], member[0], True),
                "verb": "takes" if spec.get("memberRole") == "takes" else "returns",
                "value": _text(_literal(listed[0][1].get("value")), code=True),
            }
        )
    for f in spec.get("fields", []):
        call = api.calls.get(f["member"])
        v = data.get(f["path"])
        if not call or not (isinstance(v, str) or _number(v)):
            continue
        rows.append(
            {
                "id": f"field-{f['path']}",
                "label": _text(call[1], call[0], True),
                "verb": "returns",
                "value": _text(_literal(v), code=True),
            }
        )
    for field in spec.get("values", []):
        raw, name = data.get(field["path"]), data.get(field["name"])
        if not _number(raw) or not isinstance(name, str):
            continue
        for page in field["enums"]:
            values = (api.enums.get(page) or {}).get("values") or []
            hit = next(
                (
                    x
                    for x in values
                    if _number(x.get("value"))
                    and x["value"] == raw
                    and names_key(name, str(x.get("key")))
                ),
                None,
            )
            if hit is None:
                continue
            rows.append(
                {
                    "id": f"value-{field['path']}",
                    "label": _text(field["label"]),
                    "value": _enum_link(page, str(hit["key"])),
                    "note": f"{name} = {js_string(raw)}",
                }
            )
            break
    for i, (page, value) in enumerate(listed):
        row: Json = {
            "id": f"enum-{page}",
            "label": _text("Listed in"),
            "value": _enum_link(page, str(value["key"])),
        }
        # The value, when the key is not it and no member row above already gives it.
        if str(value["key"]) != js_string(value.get("value")) and not (
            member and i == 0
        ):
            row["note"] = f"= {_literal(value.get('value'))}"
        rows.append(row)
    attrs = data.get("attributes")
    count = len(attrs) if isinstance(attrs, list) else 0
    has = api.calls.get("Object.hasAttribute")
    if spec.get("attributes") and has and count and "DcsId.Attribute" in api.enums:
        rows.append(
            {
                "id": "attributes",
                "label": _text(has[1], has[0], True),
                "value": _text(
                    "DcsId.Attribute", api_href("types", "DcsId.Attribute"), True
                ),
                "note": f"true for this type's {count} "
                + ("attribute" if count == 1 else "attributes"),
            }
        )
    return rows
