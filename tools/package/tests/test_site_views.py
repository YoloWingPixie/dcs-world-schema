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
