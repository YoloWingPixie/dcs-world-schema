from __future__ import annotations

import json
import random
from typing import Any

from tools.datamine.common import SERIES, UNIT_SERIES
from tools.package import indexes


def _obj(**props: Any) -> dict[str, Any]:
    return {"type": "object", "properties": props}


def _ref(*types: str) -> dict[str, Any]:
    return {"type": "string", "x-ref": list(types)}


def _list(item: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": item}


UNIT_TYPES = [SERIES[s].type_name for s in UNIT_SERIES]
DEFS: dict[str, Any] = {
    s.type_name: _obj(id={"type": "string"}) for s in SERIES.values()
}
DEFS.update(
    {
        "Entity.Weapon": _obj(id={"type": "string"}, displayName={"type": "string"}),
        "Entity.Store": _obj(
            clsid={"type": "string"},
            displayName={"type": "string"},
            delivers=_list(_obj(weapon=_ref("Entity.Weapon"))),
        ),
        "Entity.Aircraft": _obj(
            id={"type": "string"},
            displayName={"type": "string"},
            stations=_list({"$ref": "#/definitions/Station"}),
        ),
        "Station": _obj(
            accepts=_list({"$ref": "#/definitions/StationStore"}),
            obsoleteAccepts=_list({"$ref": "#/definitions/StationStore"}),
        ),
        "StationStore": _obj(
            clsid=_ref("Entity.Store"),
            required=_list(_obj(clsids=_list(_ref("Entity.Store")))),
        ),
        "Entity.ThreatSystem": _obj(
            id={"type": "string"},
            unit=_ref(*UNIT_TYPES),
            components=_list(_obj(unit=_ref(*UNIT_TYPES))),
        ),
        "Entity.Airbase": _obj(
            id={"type": "string"},
            name={"type": "string"},
            theatre=_ref("Entity.Theatre"),
        ),
    }
)
DOCUMENT = {"definitions": DEFS}

BUNDLES: dict[str, dict[str, Any]] = {name: {} for name in SERIES}
BUNDLES.update(
    {
        "weapons": {
            "AIM_120C": {"id": "AIM_120C", "displayName": "AIM-120C"},
            "AIM_9": {"id": "AIM_9", "displayName": " aim-9 "},
            "Mk_82": {"id": "Mk_82", "displayName": "Mk-82"},
        },
        "stores": {
            "S1": {
                "clsid": "S1",
                "displayName": "AIM-120C",
                "delivers": [{"weapon": "AIM_120C"}],
            },
            "S2": {
                "clsid": "S2",
                "displayName": "2 x AIM-120C",
                "delivers": [{"weapon": "AIM_120C"}, {"weapon": "AIM_120C"}],
            },
            "S3": {"clsid": "S3", "delivers": [{"weapon": "Missing"}]},
        },
        "aircraft": {
            "F-16C": {
                "id": "F-16C",
                "displayName": "F-16C",
                "stations": [
                    {"accepts": [{"clsid": "S1"}]},
                    {"accepts": [{"clsid": "S1"}, {"clsid": "S2"}]},
                ],
            },
            # S1 only on an obsolete launcher: referenced, not a carrier
            "B-52H": {
                "id": "B-52H",
                "stations": [{"accepts": [], "obsoleteAccepts": [{"clsid": "S1"}]}],
            },
            "F-15C": {
                "id": "F-15C",
                "displayName": "f-16c",
                "stations": [{"accepts": [{"clsid": "S2"}]}],
            },
            # names S1 only in a loadout rule: not a carrier of its weapon
            "A-10C": {
                "id": "A-10C",
                "stations": [
                    {
                        "accepts": [
                            {"clsid": "S3", "required": [{"clsids": ["S1"]}]},
                            {"clsid": "Gap"},
                        ]
                    }
                ],
            },
        },
        "ground_vehicles": {"SA-11 LN": {"id": "SA-11 LN"}, "SR": {"id": "SR"}},
        "threats": {
            "SA-11": {
                "id": "SA-11",
                "unit": "SA-11 LN",
                "components": [{"unit": "SR"}, {"unit": "SA-11 LN"}],
            },
            "Ghost": {"id": "Ghost", "unit": "Nowhere"},
        },
        "theatres": {"Caucasus": {"id": "Caucasus"}, "Syria": {"id": "Syria"}},
        "airbases": {
            "C.1": {"id": "C.1", "name": "Batumi", "theatre": "Caucasus"},
            "S.1": {"id": "S.1", "name": "BATUMI", "theatre": "Syria"},
        },
    }
)


def _build(bundles: dict[str, dict[str, Any]] = BUNDLES) -> dict[str, Any]:
    return indexes.build(bundles, DOCUMENT)


def test_references() -> None:
    built = _build()
    assert built["references_weapons"]["AIM_120C"] == [
        {"series": "stores", "id": "S1", "path": "delivers[].weapon"},
        {"series": "stores", "id": "S2", "path": "delivers[].weapon"},
    ]
    assert built["references_stores"]["S1"] == [
        {
            "series": "aircraft",
            "id": "A-10C",
            "path": "stations[].accepts[].required[].clsids[]",
        },
        {
            "series": "aircraft",
            "id": "B-52H",
            "path": "stations[].obsoleteAccepts[].clsid",
        },
        {"series": "aircraft", "id": "F-16C", "path": "stations[].accepts[].clsid"},
    ]
    # unresolved references are not indexed
    assert "Missing" not in built["references_weapons"]
    assert "Gap" not in built["references_stores"]
    assert "Mk_82" not in built["references_weapons"]
    # a reference to any unit series lands in the series holding the id
    assert built["references_ground_vehicles"]["SA-11 LN"] == [
        {"series": "threats", "id": "SA-11", "path": "components[].unit"},
        {"series": "threats", "id": "SA-11", "path": "unit"},
    ]
    assert "references_aircraft" not in built


def test_references_match_a_scan() -> None:
    built = _build()
    expected: dict[str, dict[str, set[tuple[str, str, str]]]] = {}
    for key, rec in BUNDLES["stores"].items():
        for d in rec["delivers"]:
            if d["weapon"] in BUNDLES["weapons"]:
                expected.setdefault("weapons", {}).setdefault(d["weapon"], set()).add(
                    ("stores", key, "delivers[].weapon")
                )
    got = {
        k: {(r["series"], r["id"], r["path"]) for r in v}
        for k, v in built["references_weapons"].items()
    }
    assert got == expected["weapons"]


def test_carriers_follow_stores_to_aircraft() -> None:
    built = _build()
    assert built["carriers"] == {"AIM_120C": ["F-15C", "F-16C"]}


def test_names() -> None:
    built = _build()
    assert built["names_weapons"]["aim-9"] == ["AIM_9"]
    assert built["names_aircraft"]["f-16c"] == ["F-15C", "F-16C"]
    assert built["names_stores"]["aim-120c"] == ["S1"]
    assert "names_racks" not in built
    assert built["airbases_by_name"] == {
        "Caucasus": {"batumi": ["C.1"]},
        "Syria": {"batumi": ["S.1"]},
    }


def test_name_key() -> None:
    assert indexes.name_key("  F-16C Viper\t") == "f-16c viper"
    assert indexes.name_key("ÄB") == "Äb"  # ASCII only, as Lua's string.lower


def test_meta() -> None:
    meta = _build()["meta"]
    assert meta["unitSeries"] == list(UNIT_SERIES)
    assert {"series": "threats", "path": "unit", "target": "units"} in meta["relations"]
    assert meta["derived"] == {
        "carriers": {
            "target": "weapons",
            "via": ["stores", "aircraft"],
            "paths": [None, "stations[].accepts[].clsid"],
        }
    }
    assert "weapons" in meta["references"] and "aircraft" in meta["names"]


def test_deterministic() -> None:
    first = indexes.files(_build())
    shuffled: dict[str, dict[str, Any]] = {}
    rng = random.Random(7)
    for name, bundle in BUNDLES.items():
        items = list(bundle.items())
        rng.shuffle(items)
        shuffled[name] = dict(items)
    assert indexes.files(_build(shuffled)) == first
    assert all(name.startswith("_index/") for name in first)
    for text in first.values():
        assert (
            text
            == json.dumps(
                json.loads(text),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            + "\n"
        )
