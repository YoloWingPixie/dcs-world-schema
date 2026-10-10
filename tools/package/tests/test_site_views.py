"""The site view helpers (``tools.package.site_views``)."""

from __future__ import annotations

import json
import zlib
from typing import Any

import pytest

from tools.package import site_views
from tools.package.site_views import ApiIndex, scripting_rows


@pytest.mark.parametrize("text", ["", "{}", '{"name":"Sochi-Adler","é":"ü"}' * 50])
def test_compress_round_trips_as_raw_deflate(text: str) -> None:
    blob = site_views.compress(text)
    assert site_views.decompress(blob) == text
    # Raw deflate: no zlib header, which DecompressionStream("deflate-raw") refuses.
    assert zlib.decompressobj(-15).decompress(blob).decode("utf-8") == text
    with pytest.raises(zlib.error):
        zlib.decompress(blob)


def test_specs_load() -> None:
    display = site_views.load_display()
    assert display["liveries"]["groupBy"]["path"] == "unitTypes"
    assert "Unit" in {s.get("class") for s in site_views.load_scripting().values()}


def test_browse_paths() -> None:
    shown = {
        "readouts": ["x"],
        "columns": ["a", "b"],
        "facets": ["b", "c"],
        "groupBy": {"path": "g", "fallback": "f", "columns": ["d"]},
    }
    assert site_views.browse_paths(shown) == ["a", "b", "c", "d", "f"]
    assert site_views.browse_paths({}) == []


def test_paths() -> None:
    assert site_views.split_companion("flight.machMax") == (True, "machMax")
    assert site_views.split_companion("flightLevel") == (False, "flightLevel")
    record = {"aero": {"massKg": 3}, "kind": "x"}
    assert site_views.value_at(record, "aero.massKg") == 3
    assert site_views.value_at(record, "kind.name") is None
    assert site_views.value_at(record, "nope.x") is None
    assert not site_views.present([]) and site_views.present(0)


def test_javascript_mirrors() -> None:
    assert site_views.encode_uri_component("AN/APG-68 (x)") == "AN%2FAPG-68%20(x)"
    assert site_views.api_href("mission", "trigger.action") == "/api/trigger/action/"
    assert site_views.api_href("types", "DcsId.Skill") == "/api/types/DcsId/Skill/"
    assert site_views.js_string(18.0) == "18"
    assert site_views.js_string(0.5) == "0.5"
    assert site_views.js_string(True) == "true"
    assert site_views.names_key("SENSOR_OPTICAL", "OPTIC")
    assert not site_views.names_key("RADAR_AS", "TV")
    assert site_views.enum_member_text("E", "KEY_1") == "E.KEY_1"
    assert site_views.enum_member_text("E", "F-16CM bl.50") == 'E["F-16CM bl.50"]'


def _symbol(
    section: str, page: str, name: str, path: str, entry: dict[str, Any]
) -> tuple[Any, ...]:
    return (section, page, name, path, "", "", "", 0, json.dumps(entry))


API = ApiIndex(
    [
        _symbol("mission", "Unit", "", "Unit", {"kind": "class"}),
        _symbol(
            "mission",
            "Unit",
            "getTypeName",
            "Unit.getTypeName",
            {"anchor": "getTypeName", "qualified": "Unit:getTypeName"},
        ),
        _symbol(
            "mission",
            "Object",
            "hasAttribute",
            "Object.hasAttribute",
            {"anchor": "hasAttribute", "qualified": "Object:hasAttribute"},
        ),
        _symbol(
            "types",
            "DcsId.AircraftType",
            "",
            "DcsId.AircraftType",
            {
                "kind": "enum",
                "valuesSeries": "aircraft",
                "values": [
                    {"key": "F-16CM bl.50", "value": "F-16C_50", "ref": "F-16C_50"}
                ],
            },
        ),
        _symbol(
            "types",
            "DcsId.Attribute",
            "",
            "DcsId.Attribute",
            {"kind": "enum", "valuesSeries": "attributes", "values": []},
        ),
        _symbol(
            "types",
            "Unit.SensorType",
            "",
            "Unit.SensorType",
            {"kind": "enum", "values": [{"key": "OPTIC", "value": 0}]},
        ),
    ]
)
SPEC = {
    "class": "Unit",
    "member": "Unit.getTypeName",
    "enums": ["DcsId.AircraftType", "DcsId.HelicopterType"],
    "attributes": True,
}


def test_scripting_rows_keep_what_the_api_confirms() -> None:
    rows = scripting_rows(SPEC, "aircraft", "F-16C_50", {"attributes": ["A"]}, API)
    assert [r["id"] for r in rows] == [
        "class",
        "member",
        "enum-DcsId.AircraftType",
        "attributes",
    ]
    assert rows[1] == {
        "id": "member",
        "label": {
            "text": "Unit:getTypeName()",
            "href": "/api/Unit/#getTypeName",
            "code": True,
        },
        "verb": "returns",
        "value": {"text": '"F-16C_50"', "code": True},
    }
    assert rows[2]["value"]["href"] == (
        "/api/types/DcsId/AircraftType/#v-F-16CM%2520bl.50"
    )
    assert "note" not in rows[2]  # the member row gives the value
    assert rows[3]["note"] == "true for this type's 1 attribute"

    # No enum lists the record: no member row; another series' enum is not read.
    assert [r["id"] for r in scripting_rows(SPEC, "aircraft", "X", {}, API)] == [
        "class"
    ]
    assert scripting_rows(SPEC, "ships", "F-16C_50", {}, API)[1:] == []
    assert scripting_rows(None, "aircraft", "F-16C_50", {}, API) == []


def test_scripting_value_rows_match_constant_names() -> None:
    spec = {
        "enums": [],
        "values": [
            {
                "path": "category",
                "label": "Category",
                "name": "categoryName",
                "enums": ["Unit.SensorType"],
            }
        ],
    }
    data = {"category": 0, "categoryName": "SENSOR_OPTICAL"}
    [row] = scripting_rows(spec, "sensors", "s", data, API)
    assert row["value"]["text"] == "Unit.SensorType.OPTIC"
    assert row["note"] == "SENSOR_OPTICAL = 0"
    data["categoryName"] = "SENSOR_RADAR"
    assert scripting_rows(spec, "sensors", "s", data, API) == []


def test_walk_mirrors_walk_path() -> None:
    record = {
        "a": {"b": 1, "empty": [], "none": None},
        "stages": [{"stage": "boost", "t": 2}, {"stage": "march", "t": 5}, {"t": 7}],
        "list": [{"x": 1}, {"x": None}, {"x": 3}],
    }
    keys = {"flight.stages": "stage"}
    assert site_views.walk(record, "a.b", {}) == [("a.b", 1, record["a"])]
    assert site_views.walk(record, "a.empty", {}) == []
    assert site_views.walk(record, "a.none", {}) == []
    assert [p for p, _, _ in site_views.walk(record, "flight.stages.*.t", keys)] == [
        "flight.stages.boost.t",
        "flight.stages.march.t",
        "flight.stages.undefined.t",
    ]
    assert [(p, v) for p, v, _ in site_views.walk(record, "list[].x", {})] == [
        ("list[0].x", 1),
        ("list[2].x", 3),
    ]


def test_table_shapes() -> None:
    rows = [{"mach": 0, "cx": 0.2}, {"mach": 1, "cx": True}, {"mach": 2, "cx": 0.4}, 3]
    assert site_views.curve_of(rows, "mach", "cx") == {"x": [0, 2], "y": [0.2, 0.4]}
    assert site_views.curve_of(None, "mach", "cx") is None
    items = [{"r": [1], "c": [2], "z": [[3]]}, {"r": [1], "z": None}, {"z": [[4]]}]
    assert site_views.surfaces_of(items, "r", "c", "z") == [
        {"rows": [1], "cols": [2], "z": [[3]]},
        {"z": [[4]]},
    ]
    holder = {"cx0": [0.1, "x"], "machStep": 0.1, "other": 1}
    assert site_views.samples_of(holder, "cx0", "machStep") == {
        "cx0": [0.1, "x"],
        "machStep": 0.1,
    }
    assert site_views.samples_of({"cx0": [0.1]}, "cx0", "machStep") == {"cx0": [0.1]}
    assert site_views.samples_of({"cx0": ["x"]}, "cx0", "machStep") is None


def test_field_value() -> None:
    record = {
        "aero": {"cx0": [1, 2], "machStep": 0.1},
        "table": [{"m": 0, "y": 1}],
        "stages": [{"stage": "a", "t": 1}, {"stage": "a", "t": 2}],
    }
    keys = {"stages": "stage"}
    sampled = {"path": "aero.cx0", "samples": {"list": "cx0", "step": "machStep"}}
    assert site_views.field_value(sampled, record, "aero.cx0", keys) == record["aero"]
    curve = {"path": "table[].y", "curve": {"table": "table", "x": "m", "y": "y"}}
    assert site_views.field_value(curve, record, "table[].y", keys) == {
        "x": [0],
        "y": [1],
    }
    # A keyed path: the first item with the key.
    keyed = {"path": "stages.*.t"}
    assert site_views.field_value(keyed, record, "stages.a.t", keys) == 1
    assert site_views.field_value(keyed, record, "stages.b.t", keys) is None


def test_keyed_paths_count_keys_as_sqlite_groups_them() -> None:
    spec = {
        "fields": [{"path": "s.*.t"}, {"path": "s.*.u"}, {"path": "other"}],
        "keyFields": {"s": "stage"},
        "keyed": ["s"],
    }
    columns = {
        "s": [
            [{"stage": "b"}, {"stage": "a"}, {"stage": 2}, {"x": 1}, 5],
            [{"stage": "a"}, {"stage": True}],
            None,
        ]
    }
    paths = site_views.keyed_paths(spec, columns)
    # `a` twice; then by SQLite's order: numbers (1 for true, 2) before text.
    assert [p for p, _ in paths][::2] == ["s.a.t", "s.1.t", "s.2.t", "s.b.t"]
    assert paths[:2] == [["s.a.t", "s.*.t"], ["s.a.u", "s.*.u"]]
    assert site_views.keyed_paths({"fields": []}, {}) == []
