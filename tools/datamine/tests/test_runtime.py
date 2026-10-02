"""The per-terrain runtime dump merge: runways, TDZE, stands, navaid links,
projections from the coord.LOtoLL grid, and the hook's own output end to end."""

import math
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
from conftest import write

from tools.datamine import extract_runtime as rt
from tools.datamine import extract_theatres, tmerc

VERSION = "9.9.9.7"
TRUE = tmerc.Projection(33.0, 0.9996, -99517.0, -4998115.0)
VAR_RAD = math.radians(6)


def _sample(x: float, z: float, h: float = 10.0) -> dict[str, Any]:
    lat, lon = TRUE.to_geo(x, z)
    return {"x": x, "z": z, "h": h, "lat": lat, "lon": lon}


def _line(
    x1: float,
    z1: float,
    x2: float,
    z2: float,
    height: Callable[[float], float] = lambda d: 10.0,
) -> dict[str, Any]:
    length = math.dist((x1, z1), (x2, z2))
    n = math.ceil(length / 10)
    return {
        "from": _sample(x1, z1, height(0)),
        "to": _sample(x2, z2, height(length)),
        "spacingM": length / n,
        "heights": [height(k * length / n) for k in range(n + 1)],
    }


def _dump(**over: Any) -> dict[str, Any]:
    """Airdrome 12: runway 04/22 from (-6000, 239000) to (-4000, 241000), true 45."""
    ref = _sample(-5000, 240000, 12.5)
    ref["magDeclRad"] = VAR_RAD
    dump = {
        "theatre": "TestMap",
        "dcsVersion": VERSION,
        "standDescriptionVersion": 2,
        "magvar": {"year": 2026, "month": 1, "source": "magvar.get_mag_decl"},
        "airbaseCategories": {"AIRDROME": 0, "HELIPAD": 1, "SHIP": 2},
        "airdromes": {
            "12": {
                "config": {"display_name": "Anapa-Vityazevo"},
                "reference": ref,
                "runwayList": [
                    {
                        "edge1name": "04",
                        "edge2name": "22",
                        "edge1x": -6000,
                        "edge1y": 239000,
                    }
                ],
                "edges": [_line(-6000, 239000, -4000, 241000, lambda d: 10 + d / 100)],
                "stands": [
                    {
                        "crossroad_index": 7,
                        "name": "01",
                        "x": -5100,
                        "y": 240100,
                        "params": {
                            "WIDTH": "20",
                            "LENGTH": "22",
                            "SHELTER": "0",
                            "FOR_HELICOPTERS": "0",
                            "FOR_AIRPLANES": "1",
                            "HEIGHT": "",  # DCS's "no limit"
                        },
                    },
                    {
                        "crossroad_index": 8,
                        "name": "02",
                        "x": -5200,
                        "y": 240200,
                        "params": {
                            "WIDTH": "40",
                            "LENGTH": "40",
                            "SHELTER": "1",
                            "FOR_HELICOPTERS": "1",
                            "FOR_AIRPLANES": "1",
                            "HEIGHT": "12",
                        },
                    },
                ],
            }
        },
        "airbases": [
            {
                "id": 12,
                "name": "Anapa-Vityazevo",
                "desc": {"category": 0},
                "runways": [
                    {
                        "Name": 4,
                        "course": -math.radians(45),
                        "length": 3000,  # DCS's; lengthM comes from the edges
                        "width": 50,
                        "position": {"x": -5000, "y": 10, "z": 240000},
                    }
                ],
                "parking": [
                    {
                        "Term_Index": 8,
                        "Term_Type": 104,
                        "vTerminalPos": {"x": -5200, "y": 10, "z": 240200},
                    },
                    {
                        "Term_Index": 7,
                        "Term_Type": 72,
                        "vTerminalPos": {"x": -5100, "y": 10, "z": 240100},
                    },
                    {
                        "Term_Index": 30,
                        "Term_Type": 16,
                        "vTerminalPos": {"x": -6000, "y": 10, "z": 239000},
                    },
                ],
                "parkingGeo": [
                    {"lat": 1.0, "lon": 2.0},
                    {"lat": 1.5, "lon": 2.5},
                    {"lat": 3.0, "lon": 4.0},
                ],
            }
        ],
        "grid": [],
    }
    dump.update(over)
    return dump


def _series(
    navaids: dict[str, Any] | None = None, beacons: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "theatres": {"TestMap": {"id": "TestMap", "directory": "Test"}},
        "airbases": {},
        "navaids": navaids or {},
        "beacons": beacons or {},
    }


def test_airbase_header_and_runway() -> None:
    series = _series()
    rt.merge(series, {"TestMap": _dump()})
    ab = series["airbases"]["TestMap.12"]
    assert ab["name"] == "Anapa-Vityazevo"
    assert (ab["category"], ab["categoryName"]) == (0, "AIRDROME")
    assert ab["referencePoint"]["elevationM"] == 12.5
    assert ab["magneticVariation"] == {
        "degrees": 6,
        "date": "2026-01",
        "source": "magvar.get_mag_decl",
    }
    (rw,) = ab["runways"]
    assert rw["designator"] == "04/22"
    assert (rw["lengthM"], ab["longestRunwayM"]) == (
        2828.43,
        2828.43,
    ) and "widthM" not in rw
    d04, d22 = rw["directions"]
    assert (d04["designator"], d04["name"]) == ("04", "04")
    assert "designatorMismatch" not in d04
    # Grid 45; true from the ends' lat/lon (TM convergence here is ~3 deg).
    assert d04["trueBearingDeg"] == pytest.approx(47.9448, abs=1e-4)
    assert d04["magneticBearingDeg"] == pytest.approx(41.9448, abs=1e-4)
    assert d22["trueBearingDeg"] == pytest.approx(227.9636, abs=1e-4)
    assert (d04["threshold"]["x"], d04["threshold"]["z"]) == (-6000, 239000)
    assert d04["threshold"]["elevationM"] == 10
    lat, _ = TRUE.to_geo(-6000, 239000)
    assert d04["threshold"]["latitude"] == round(lat, 7)
    # Height rises 1 m per 100 m from the 04 threshold: TDZE at 914.4 m in (or
    # the last sample before it), and the 22 end's own zone is its highest part.
    spacing = 2828.4271 / 283
    assert d04["tdzeM"] == round(10 + math.floor(914.4 / spacing) * spacing / 100, 2)
    assert d22["tdzeM"] == round(10 + 2828.4271 / 100, 2)


def test_tdze_windows() -> None:
    hs: list[float] = [0, 5, 1, 1, 9]
    assert rt.tdze(hs, 400, True) == 5  # samples at 0, 400, 800 m
    assert rt.tdze(hs, 400, False) == 9
    assert rt.tdze(hs, 1000, True) == 0
    assert rt.tdze([3.0, 4.0], 10, False) == 4  # shorter than the zone: whole runway


def test_designator_number_rounding() -> None:
    assert [rt._number(m) for m in (0, 4.9, 5, 44.9, 355, 359.9)] == [
        36,
        36,
        1,
        4,
        36,
        36,
    ]
    assert rt._normalise_name("7") == "07" and rt._normalise_name("3r") == "03R"


def _end(series: dict[str, Any], runway: int = 0, end: int = 0) -> dict[str, Any]:
    runways = series["airbases"]["TestMap.12"]["runways"]
    return cast(dict[str, Any], runways[runway]["directions"][end])


def _named(a: str, b: str) -> tuple[dict[str, Any], list[str]]:
    """Merge the 04/22 runway (magnetic 41.9) with DCS end names a (edge1), b."""
    dump = _dump()
    dump["airdromes"]["12"]["runwayList"][0].update(edge1name=a, edge2name=b)
    series = _series()
    lines = rt.merge(series, {"TestMap": dump})
    return series, lines


def _ends(series: dict[str, Any], runway: int = 0) -> list[tuple[str, str, bool]]:
    return [
        (d["designator"], d["name"], d.get("designatorMismatch", False))
        for d in series["airbases"]["TestMap.12"]["runways"][runway]["directions"]
    ]


def test_chart_lag_names_kept() -> None:
    # Geometry says 04/22; DCS names within three numbers are kept.
    for a, b in (("05", "23"), ("03", "21"), ("5", "23"), ("07", "25"), ("01", "19")):
        series, lines = _named(a, b)
        assert _ends(series) == [(f"{int(a):02d}", a, False), (b, b, False)]
        assert "0 ends designated otherwise" in lines[-1]
    # 36 <-> 01 wraps: a runway running grid north is magnetic ~357 here.
    series = _series()
    rt.merge(series, {"TestMap": _multi([("01", "19", -6000, 240000, -3000, 240000)])})
    assert _ends(series) == [("01", "01", False), ("19", "19", False)]
    assert rt._num_delta(36, 1) == 1 and rt._num_delta(34, 1) == 3


def test_swapped_dcs_names_placed_on_their_ends() -> None:
    # Barth-style: DCS names edge1 (magnetic 42) "22" and edge2 "04".
    series, lines = _named("22", "04")
    assert _ends(series) == [("04", "04", False), ("22", "22", False)]
    assert series["airbases"]["TestMap.12"]["runways"][0]["designator"] == "04/22"
    assert any(
        "DCS runway 22/04 names each other's end; placed as 04/22" in ln for ln in lines
    )
    assert "1 with DCS end names swapped, 0 ends" in lines[-1]


def test_wrong_dcs_number_replaced() -> None:
    # Gelendzhik: DCS 01/19 on a runway that runs 036 magnetic; here 08/26 on 042.
    series, lines = _named("08", "26")
    assert _ends(series) == [("04", "08", True), ("22", "26", True)]
    assert any("runway end 08 designated 04 (magnetic 41.9)" in ln for ln in lines)
    assert "2 ends designated otherwise" in lines[-1]
    # 36 <-> 01 wraps: 36 is four from 04.
    series, _ = _named("36", "18")
    assert _ends(series) == [("04", "36", True), ("22", "18", True)]
    # Only the far-off end is replaced; its suffix stays.
    series, _ = _named("04", "26L")
    assert _ends(series) == [("04", "04", False), ("22L", "26L", True)]


def test_duplicated_or_missing_end_name() -> None:
    # Puerto Santa Cruz: "07" at both ends.
    series, _ = _named("04", "04")
    assert _ends(series) == [("04", "04", False), ("22", "04", True)]
    series, _ = _named("22", "22")
    assert _ends(series) == [("04", "22", True), ("22", "22", False)]
    series, _ = _named("", "04")
    assert _ends(series) == [("04", "04", False), ("22", "", True)]


def test_dcs_suffix_kept_without_modelled_parallel() -> None:
    series, _ = _named("4L", "22R")
    assert _ends(series) == [("04L", "4L", False), ("22R", "22R", False)]
    assert series["airbases"]["TestMap.12"]["runways"][0]["designator"] == "04L/22R"


def _multi(
    runways: list[tuple[str, str, float, float, float, float]],
) -> dict[str, Any]:
    """Airdrome 12 with the given (edge1name, edge2name, x1, z1, x2, z2) runways;
    getRunways() entry k has runway k's position/course but runway k // 2's
    length/width/Name (the DCS bug)."""
    dump = _dump()
    ad = dump["airdromes"]["12"]
    ad["runwayList"] = [{"edge1name": a, "edge2name": b} for a, b, *_ in runways]
    ad["edges"] = [_line(x1, z1, x2, z2) for _, _, x1, z1, x2, z2 in runways]
    mission = []
    for k, (_, _, x1, z1, x2, z2) in enumerate(runways):
        src = runways[k // 2]
        mission.append(
            {
                "Name": src[0],
                "course": -math.atan2(z2 - z1, x2 - x1),
                "length": math.dist(src[2:4], src[4:6]),
                "width": 40 + k // 2,
                "position": {"x": (x1 + x2) / 2, "y": 0, "z": (z1 + z2) / 2},
            }
        )
    dump["airbases"][0]["runways"] = mission
    x1, z1 = runways[0][2:4]
    dump["airbases"][0]["parking"][2]["vTerminalPos"] = {"x": x1, "y": 10, "z": z1}
    return dump


def test_unlabelled_parallels_get_suffixes() -> None:
    # Two runways running grid north: z 240000 is left of z 240300 heading N.
    # DCS names both 36/18 (one reversed): ambiguous, so L/R from geometry.
    dump = _multi(
        [
            ("36", "18", -6000, 240300, -3000, 240300),  # right heading 36
            ("18", "36", -4000, 240000, -6000, 240000),  # left heading 36, reversed
        ]
    )
    series = _series()
    rt.merge(series, {"TestMap": dump})
    runways = series["airbases"]["TestMap.12"]["runways"]
    assert [r["designator"] for r in runways] == ["18L/36R", "18R/36L"]
    right, left = runways  # sorted by designator
    assert [d["designator"] for d in right["directions"]] == ["36R", "18L"]
    assert [d["designator"] for d in left["directions"]] == ["18R", "36L"]
    assert [d["name"] for r in runways for d in r["directions"]] == [
        "36",
        "18",
        "18",
        "36",
    ]
    assert all(d["designatorMismatch"] for r in runways for d in r["directions"])
    # Length from the edges, not from the shifted getRunways() entries.
    assert (right["lengthM"], left["lengthM"]) == (3000, 2000)
    assert not any("widthM" in r for r in runways)


def test_parallel_suffixes_partly_labelled() -> None:
    # Al-Taquddum: 12L/30R and 12R/"30"; distinct numbers need no suffix.
    dump = _multi(
        [
            ("36L", "18R", -6000, 240000, -3000, 240000),
            ("36R", "18", -6000, 240300, -3000, 240300),
            ("35", "17", -6000, 240600, -3000, 240600),
        ]
    )
    series = _series()
    rt.merge(series, {"TestMap": dump})
    got = {
        r["directions"][0]["name"]: _ends(series, k)
        for k, r in enumerate(series["airbases"]["TestMap.12"]["runways"])
    }
    assert got["36L"] == [("36L", "36L", False), ("18R", "18R", False)]
    assert got["36R"] == [("36R", "36R", False), ("18L", "18", True)]
    assert got["35"] == [("35", "35", False), ("17", "17", False)]


def test_collinear_segments_share_a_lane() -> None:
    # Abu Dhabi: 13/31 modelled as two collinear segments beside a parallel.
    dump = _multi(
        [
            ("36", "18", -6000, 240000, -3000, 240000),
            ("36", "18", -3000, 240000, -2000, 240000),
            ("36", "18", -6000, 240300, -3000, 240300),
        ]
    )
    series = _series()
    rt.merge(series, {"TestMap": dump})
    runways = series["airbases"]["TestMap.12"]["runways"]
    assert sorted(r["designator"] for r in runways) == ["18L/36R", "18R/36L", "18R/36L"]


def test_three_and_four_parallel_runways() -> None:
    three: list[tuple[str, str, float, float, float, float]] = [
        ("x", "y", -6000, 240000 + 300 * i, -3000, 240000 + 300 * i) for i in range(3)
    ]
    series = _series()
    rt.merge(series, {"TestMap": _multi(three)})
    got = {
        r["directions"][0]["threshold"]["z"]: r["designator"]
        for r in series["airbases"]["TestMap.12"]["runways"]
    }
    assert got == {240000: "18R/36L", 240300: "18C/36C", 240600: "18L/36R"}
    series = _series()
    rt.merge(
        series, {"TestMap": _multi([*three, ("x", "y", -6000, 240900, -3000, 240900)])}
    )
    got = {
        r["directions"][0]["threshold"]["z"]: r["directions"][0]["designator"]
        for r in series["airbases"]["TestMap.12"]["runways"]
    }
    # Numbered along 18 (the end below 180 magnetic): east is left there, so
    # the eastern pair is 18L/18R -> 36R/36L and the western 19L/19R -> 01R/01L.
    assert got == {240000: "01L", 240300: "01R", 240600: "36L", 240900: "36R"}


def test_runway_without_mission_pair_fails() -> None:
    dump = _dump()
    dump["airbases"][0]["runways"][0]["position"] = {"x": -3000, "y": 0, "z": 240000}
    with pytest.raises(SystemExit):
        rt.merge(_series(), {"TestMap": dump})


def test_mission_runways_without_runway_list_fail() -> None:
    dump = _dump()
    del dump["airdromes"]["12"]["runwayList"]
    with pytest.raises(SystemExit):
        rt.merge(_series(), {"TestMap": dump})


def test_airbase_without_config_fails_with_runways_or_parking() -> None:
    for drop in ("parking", "runways"):
        dump = _dump()
        dump["airbases"][0]["id"] = 13
        del dump["airbases"][0][drop]
        with pytest.raises(SystemExit):
            rt.merge(_series(), {"TestMap": dump})
    dump = _dump()
    dump["airbases"][0].update(id=13, runways=[], parking=[])
    lines = rt.merge(_series(), {"TestMap": dump})
    assert any(
        "no terrain config airdrome: ['Anapa-Vityazevo (13)']" in ln for ln in lines
    )


def test_config_name_must_match_airbase_name() -> None:
    dump = _dump()
    dump["airdromes"]["12"]["config"] = {"display_name": "Anapa"}
    with pytest.raises(SystemExit):
        rt.merge(_series(), {"TestMap": dump})
    # Without a display_name, names.en, then the config id.
    for config in (
        {"display_name": "", "names": {"en": "Anapa-Vityazevo"}, "id": "Anapa"},
        {"display_name": "", "id": "Anapa-Vityazevo"},
    ):
        dump = _dump()
        dump["airdromes"]["12"]["config"] = config
        rt.merge(_series(), {"TestMap": dump})


def test_stands_join_by_index_with_limits() -> None:
    series = _series()
    rt.merge(series, {"TestMap": _dump()})
    stands = series["airbases"]["TestMap.12"]["stands"]
    assert [s["termIndex"] for s in stands] == [7, 8, 30]
    s7, s8, s30 = stands
    assert s7["name"] == "01" and s7["termType"] == 72
    assert s7["limits"] == {
        "maxWidthM": 20,
        "maxLengthM": 22,
        "shelter": False,
        "helicopters": False,
        "airplanes": True,
    }
    assert s7["position"] == {
        "x": -5100,
        "z": 240100,
        "latitude": 1.5,
        "longitude": 2.5,
    }
    assert s8["name"] == "02" and s8["limits"]["maxHeightM"] == 12
    assert s8["limits"]["shelter"] and s8["limits"]["helicopters"]
    assert "name" not in s30 and "limits" not in s30
    assert s30["runwayEnd"] == "04" and "runwayEnd" not in s7


def test_stand_without_params_fails() -> None:
    dump = _dump()
    del dump["airdromes"]["12"]["stands"][1]["params"]
    with pytest.raises(SystemExit):
        rt.merge(_series(), {"TestMap": dump})


def test_unlisted_spot_off_runway_end_fails() -> None:
    dump = _dump()
    dump["airbases"][0]["parking"][2]["vTerminalPos"] = {
        "x": -5900,
        "y": 10,
        "z": 239100,
    }
    with pytest.raises(SystemExit):
        rt.merge(_series(), {"TestMap": dump})


def test_stand_join_falls_back_to_position() -> None:
    stands = [
        {"crossroad_index": 1, "x": 0, "y": 0},
        {"crossroad_index": 2, "x": 50, "y": 0},
    ]
    parking = [
        {"Term_Index": 2, "vTerminalPos": {"x": 0.5, "z": 0}},
        {"Term_Index": 1, "vTerminalPos": {"x": 50, "z": 0.5}},
    ]
    joined, basis = rt.join_stands(stands, parking)
    assert basis == "position"
    assert joined == {0: stands[0], 1: stands[1]}
    parking[0]["Term_Index"], parking[1]["Term_Index"] = 1, 2
    assert rt.join_stands(stands, parking)[1] == "index"


def test_stand_description_version_1_fails() -> None:
    rt.merge(_series(), {"TestMap": _dump(standDescriptionVersion=2)})
    with pytest.raises(SystemExit):
        rt.merge(_series(), {"TestMap": _dump(standDescriptionVersion=1)})


def _ils(
    localizer_xz: tuple[float, float], direction: float
) -> tuple[dict[str, Any], dict[str, Any]]:
    beacons = {
        "TestMap.airfield12_0": {
            "position": {"x": localizer_xz[0], "y": 0, "z": localizer_xz[1]},
            "direction": direction,
        }
    }
    navaids = {
        "TestMap.ILS.airfield12_0": {
            "airbase": "TestMap.12",
            "equipment": ["TestMap.airfield12_0", "TestMap.airfield12_1"],
        }
    }
    return navaids, beacons


def test_localizer_serves_direction_opposite_its_direction() -> None:
    # Localizer beyond the 22 end (NE) radiating back along the 04 approach.
    navaids, beacons = _ils((-3800, 241200), -133.0)
    series = _series(navaids, beacons)
    rt.merge(series, {"TestMap": _dump()})
    d04, d22 = series["airbases"]["TestMap.12"]["runways"][0]["directions"]
    assert d04["navaids"] == ["TestMap.ILS.airfield12_0"] and "navaids" not in d22
    nav = series["navaids"]["TestMap.ILS.airfield12_0"]
    assert nav["runwayDirection"] == "04" and nav["runwayBearingDeltaDeg"] == 2


def test_localizer_off_every_direction_is_not_linked() -> None:
    navaids, beacons = _ils((-3800, 241200), 0.0)
    series = _series(navaids, beacons)
    lines = rt.merge(series, {"TestMap": _dump()})
    assert "runwayDirection" not in series["navaids"]["TestMap.ILS.airfield12_0"]
    assert any("not linked" in line for line in lines)


def test_load_ignores_other_versions_and_checks_theatre(tmp_path: Path) -> None:
    write(
        tmp_path / "A.lua", f'terrain = {{ theatre = "A", dcsVersion = "{VERSION}" }}'
    )
    write(tmp_path / "B.lua", 'terrain = { theatre = "B", dcsVersion = "1.0.0.1" }')
    assert list(rt.load(tmp_path, VERSION)) == ["A"]
    assert rt.load(tmp_path / "missing", VERSION) == {}
    assert rt.load(None, VERSION) == {}
    write(
        tmp_path / "C.lua", f'terrain = {{ theatre = "X", dcsVersion = "{VERSION}" }}'
    )
    with pytest.raises(SystemExit):
        rt.load(tmp_path, VERSION)


def _grid() -> list[dict[str, Any]]:
    out = []
    for i in range(9):
        for k in range(9):
            x, z = -300000 + i * 40000, 200000 + k * 40000
            lat, lon = TRUE.to_geo(x, z)
            out.append({"x": x, "z": z, "lat": lat, "lon": lon})
    return out


def test_projection_from_grid_for_beaconless_theatre() -> None:
    theatres: dict[str, dict[str, Any]] = {
        "TestMap": {"id": "TestMap", "directory": "Test"}
    }
    lines = extract_theatres.runtime_projections(
        theatres, {"TestMap": {"grid": _grid()}}
    )
    p = theatres["TestMap"]["projection"]
    assert p["fit"]["source"] == "coord.LOtoLL" and p["fit"]["points"] == 81
    assert p["centralMeridian"] == pytest.approx(33.0, abs=1e-6)
    assert "grid fit n=81" in lines[0]


def test_beacon_projection_is_cross_checked_not_replaced() -> None:
    proj = {
        "centralMeridian": 33.0,
        "scaleFactor": 0.9996,
        "falseEasting": -99517.0,
        "falseNorthing": -4998115.0,
        "fit": {"points": 20},
    }
    theatres = {"TestMap": {"id": "TestMap", "projection": dict(proj)}}
    lines = extract_theatres.runtime_projections(
        theatres, {"TestMap": {"grid": _grid()}}
    )
    assert theatres["TestMap"]["projection"] == proj
    assert "beacon fit vs coord.LOtoLL grid (n=81): max 0.000 m" in lines[0]


def test_grid_too_small_fails() -> None:
    theatres = {"TestMap": {"id": "TestMap"}}
    with pytest.raises(SystemExit):
        extract_theatres.runtime_projections(
            theatres, {"TestMap": {"grid": _grid()[:3]}}
        )


LUA = shutil.which("lua5.1") or shutil.which("luajit")


@pytest.mark.skipif(LUA is None, reason="lua5.1/luajit not installed")
def test_hook_output_merges(tmp_path: Path) -> None:
    """The stubbed hook run's file is what the extractor reads."""
    tests_lua = Path(__file__).parent / "lua"
    hooks = tmp_path / "Scripts" / "Hooks"
    hooks.mkdir(parents=True)
    for name in ("terrain-dump.lua", "serialize.lua"):
        shutil.copy(Path(__file__).parents[1] / "hook" / name, hooks / name)
    subprocess.run(
        [
            str(LUA),
            str(tests_lua / "test_terrain_dump.lua"),
            str(tests_lua),
            f"{tmp_path}/",
            "ok",
        ],
        check=True,
        capture_output=True,
    )
    dumps = rt.load(tmp_path / "DCS.Lua.Exporter" / "terrains", VERSION)
    series = _series()
    rt.merge(series, dumps)
    ab = series["airbases"]["TestMap.12"]
    (rw,) = ab["runways"]
    assert rw["designator"] == "04/22"
    assert [d["designator"] for d in rw["directions"]] == ["04", "22"]
    assert ab["stands"][0]["name"] == "01"
    assert ab["stands"][0]["limits"]["maxWidthM"] == 20
    assert ab["magneticVariation"]["date"] == "2026-01"


def test_merged_records_match_the_entity_schema() -> None:
    from jsonschema import Draft7Validator

    from tools.datamine.common import REPO_ROOT
    from tools.export_jsonschema import export, schema_for
    from tools.merge import merge_tree

    merged, _ = merge_tree(str(REPO_ROOT / "dcs-world-schema"))
    doc = export(merged["types"])
    navaids, beacons = _ils((-3800, 241200), -133.0)
    navaids["TestMap.ILS.airfield12_0"].update(
        id="TestMap.ILS.airfield12_0",
        theatre="TestMap",
        type="ILS",
        grouping="frequency",
        directionDeltaDeg=0,
    )
    series = _series(navaids, beacons)
    rt.merge(series, {"TestMap": _dump()})
    for type_name, rec in (
        ("Entity.Airbase", series["airbases"]["TestMap.12"]),
        ("Entity.Navaid", series["navaids"]["TestMap.ILS.airfield12_0"]),
    ):
        errors = list(Draft7Validator(schema_for(doc, type_name)).iter_errors(rec))
        assert not errors, [e.message for e in errors]


def test_airdrome_ids_from_one_read_as_array() -> None:
    dump = _dump()
    dump["airdromes"] = [{"config": {}}] * 11 + [dump["airdromes"]["12"]]
    series = _series()
    rt.merge(series, {"TestMap": dump})
    assert series["airbases"]["TestMap.12"]["runways"][0]["designator"] == "04/22"
