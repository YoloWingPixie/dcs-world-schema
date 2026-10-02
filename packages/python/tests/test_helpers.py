"""The reference helpers: the shared conformance vectors
(tools/package/tests/vectors/helpers.json, also run by the TypeScript and Lua
packages) and checks against the data itself."""

from __future__ import annotations

import itertools
import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import dcs_world_reference as ref
import pytest

VECTORS = json.loads(
    (
        Path(__file__).resolve().parents[3] / "tools/package/tests/vectors/helpers.json"
    ).read_text(encoding="utf-8")
)
TOL = VECTORS["tolerance"]


# Vector function name -> Python helper.
NAMES = {
    "theatreByName": "theatre_by_name",
    "toLatLon": "to_lat_lon",
    "toMapXZ": "to_map_xz",
    "threatRange": "threat_range",
    "threatForUnitType": "threat_for_unit_type",
    "threatRingGeoJSON": "threat_ring_geojson",
    "aircraftRoles": "aircraft_roles",
    "unitClass": "unit_class",
    "stationsAccepting": "stations_accepting",
    "canMount": "can_mount",
    "fitStores": "fit_stores",
    "loadoutMass": "loadout_mass",
    "radioBands": "radio_bands",
    "isValidFrequency": "is_valid_frequency",
    "weaponInfo": "weapon_info",
    "launchPlatforms": "launch_platforms",
    "modelToUnits": "model_to_units",
    "unitDetection": "unit_detection",
    "tacanFrequency": "tacan_frequency",
    "tacanChannel": "tacan_channel",
    "isValidTacan": "is_valid_tacan",
    "navaidsFor": "navaids_for",
    "runwayEnds": "runway_ends",
    "bestRunway": "best_runway",
    "nearestAirbases": "nearest_airbases",
    "standsFor": "stands_for",
    "countryId": "country_id",
    "countryName": "country_name",
    "liveriesFor": "liveries_for",
    "datalinkCapability": "datalink_capability",
    "distanceBearing": "distance_bearing",
    "destination": "destination",
    "formatCoord": "format_coord",
    "parseCoord": "parse_coord",
}


def _args(fn: str, args: list[Any]) -> list[Any]:
    if fn == "loadoutMass":
        return [args[0], {int(k): v for k, v in args[1].items()}, args[2]]
    return args


def _close(got: Any, want: Any, path: str = "") -> None:
    if isinstance(want, bool) or want is None or isinstance(want, str):
        assert got == want, path
    elif isinstance(want, int | float):
        assert isinstance(got, int | float) and not isinstance(got, bool), path
        assert abs(got - want) <= TOL["abs"] + TOL["rel"] * abs(want), (path, got, want)
    elif isinstance(want, list):
        assert isinstance(got, list) and len(got) == len(want), path
        for i, (g, w) in enumerate(zip(got, want, strict=True)):
            _close(g, w, f"{path}[{i}]")
    else:
        assert isinstance(got, dict) and sorted(map(str, got)) == sorted(want), path
        for k, w in want.items():
            _close({str(a): b for a, b in got.items()}[k], w, f"{path}.{k}")


def _call(fn: str, args: list[Any]) -> Any:
    if fn == "theatreByName":
        t = ref.theatre_by_name(args[0])
        return None if t is None else t["id"]
    if fn == "nearestAirbases":
        theatre, lat, lon, options = args
        return ref.nearest_airbases(
            theatre,
            lat,
            lon,
            min_runway_m=options.get("minRunwayM"),
            n=options.get("n", 5),
            category=options.get("category"),
        )
    helper: Callable[..., Any] = getattr(ref, NAMES[fn])
    return helper(*_args(fn, args))


@pytest.mark.parametrize(
    "case", VECTORS["cases"], ids=lambda c: f"{c['fn']}{json.dumps(c['args'])[:60]}"
)
def test_vector(case: dict[str, Any]) -> None:
    if case.get("throws"):
        with pytest.raises((KeyError, ValueError)):
            _call(case["fn"], case["args"])
    else:
        _close(_call(case["fn"], case["args"]), case["expect"])


def test_vectors_cover_every_helper() -> None:
    assert {c["fn"] for c in VECTORS["cases"]} == set(NAMES)
    assert VECTORS["dcsVersion"] == ref.DCS_VERSION


def _geo_points() -> list[tuple[float, str, float, float, float, float]]:
    """(allowed residual m, theatre, x, z, lat, lon) of every airbase
    reference point (``coord.LOtoLL``) and beacon (6-decimal ``positionGeo``,
    ~0.11 m resolution, and single-precision map positions)."""
    out = [
        (0.1, ab["theatre"], p["x"], p["z"], p["latitude"], p["longitude"])
        for ab in ref.airbases().values()
        if (p := ab.get("referencePoint"))
    ]
    out += [
        (
            0.15,
            b["id"].split(".", 1)[0],
            b["position"]["x"],
            b["position"]["z"],
            b["latitude"],
            b["longitude"],
        )
        for b in ref.beacons().values()
    ]
    return out


def test_projection_residuals_and_round_trip() -> None:
    points = _geo_points()
    assert len(points) > 2000
    squares = 0.0
    for allowed, theatre, x, z, lat, lon in points:
        xz = ref.to_map_xz(theatre, lat, lon)
        residual = math.hypot(xz["x"] - x, xz["z"] - z)
        assert residual < allowed, (theatre, x, z, residual)
        squares += residual * residual
        ll = ref.to_lat_lon(theatre, x, z)
        back = ref.to_map_xz(theatre, ll["lat"], ll["lon"])
        assert math.hypot(back["x"] - x, back["z"] - z) < 1e-3, (theatre, x, z)
    assert math.sqrt(squares / len(points)) < 0.05


def test_theatre_names_are_unambiguous() -> None:
    owners: dict[str, str] = {}
    for t in ref.theatres().values():
        names = [t["id"], t.get("displayName"), t["directory"], *t.get("aliases", [])]
        for n in names:
            if isinstance(n, str):
                assert owners.setdefault(ref.name_key(n), t["id"]) == t["id"], n
                found = ref.theatre_by_name(n)
                assert found is not None and found["id"] == t["id"]
    nttr = ref.theatre_by_name(" nttr ")
    assert nttr is not None and nttr["id"] == "Nevada"


def test_ring_points_lie_at_the_range() -> None:
    fc = ref.threat_ring_geojson("SA5B55", 42.0, 41.0)
    (feature,) = fc["features"]
    outer, hole = feature["geometry"]["coordinates"]
    assert len(outer) == len(hole) == 65 and outer[0] == outer[-1]
    lat0, lon0 = math.radians(42.0), math.radians(41.0)
    for ring, km in ((outer, 120.0), (hole, 5.0)):
        for lon, lat in ring:
            phi, lam = math.radians(lat), math.radians(lon)
            a = (
                math.sin((phi - lat0) / 2) ** 2
                + math.cos(phi) * math.cos(lat0) * math.sin((lam - lon0) / 2) ** 2
            )
            d = 2 * ref.EARTH_RADIUS_M * math.asin(math.sqrt(a))
            assert d == pytest.approx(km * 1000, rel=1e-9)

    # Exterior counterclockwise, hole clockwise (shoelace sign in lon/lat).
    def area(r: list[list[float]]) -> float:
        return sum(a[0] * b[1] - b[0] * a[1] for a, b in itertools.pairwise(r))

    assert area(outer) > 0 > area(hole)


def test_fit_assignment_is_valid() -> None:
    fit = ref.fit_stores("F-16C_50", ["{5335D97A-35A5-4643-9D9B-026C75961E52}"] * 4)
    assignment = fit.get("assignment")
    assert assignment is not None and len(assignment) == 4
    for station, clsid in assignment.items():
        assert ref.can_mount("F-16C_50", station, clsid)


def test_fit_keeps_symmetric_required_pairs() -> None:
    # C-101CC station 2 requires its store on 6 and 6 requires it on 2.
    assert ref.fit_stores("C-101CC", ["BR_250"] * 2) == {
        "assignment": {2: "BR_250", 6: "BR_250"}
    }
    assert ref.fit_stores("C-101CC", ["BR_250"]) == {
        "conflicts": [{"index": 0, "clsid": "BR_250", "reason": "loadoutRules"}]
    }
    assert ref.fit_stores("C-101CC", ["BR_250", "BR_500", "BR_250"]) == {
        "conflicts": [{"index": 1, "clsid": "BR_500", "reason": "loadoutRules"}]
    }


def test_tacan_plan_reproduces_dcs_frequencies() -> None:
    # Caucasus TACANs give the X reply, VORTACs the paired VHF frequency.
    assert ref.tacan_frequency(16, "X", "ground")["txMHz"] == 977  # Batumi
    assert ref.tacan_frequency(67, "X", "ground")["txMHz"] == 1154  # Kobuleti
    assert ref.tacan_frequency(116, "X", "air")["pairedVhfMHz"] == 116.9  # LAS
    assert ref.tacan_channel(115.75, "vhf") == [{"channel": 104, "band": "Y"}]
    for ch in range(1, 127):
        for band in ("X", "Y"):
            f = ref.tacan_frequency(ch, band, "air")
            assert {"channel": ch, "band": band} in ref.tacan_channel(
                f["rxMHz"], "ground"
            )
            assert f["txMHz"] == 1024 + ch


def test_mgrs_reference_points() -> None:
    # NGA/GEOTRANS: the origin; the mission editor's own copies of one point.
    assert ref.format_coord(0, 0, "MGRS") == "31 N AA 66021 00000"
    precise = ref.parse_coord("Lat Long Precise: N 29°32'03.53\"   E 52°35'55.82\"")
    assert (
        ref.format_coord(precise["lat"], precise["lon"], "MGRS")
        == "39 R XN 54929 68251"
    )
    assert (
        ref.format_coord(precise["lat"], precise["lon"], "DMS", 2)
        == "N 29°32'03.53\"   E 52°35'55.82\""
    )
    ddm = ref.parse_coord("Lat Long Decimal Minutes: N 29°32.296'   E 52°35.179'")
    metric = ref.parse_coord("Metric: X+00380826 Z-00352108")
    xz = ref.to_map_xz("PersianGulf", ddm["lat"], ddm["lon"])
    assert math.hypot(xz["x"] - metric["x"], xz["z"] - metric["z"]) < 2
    # Zone exceptions: Norway 32V, Svalbard 33X.
    assert ref.format_coord(60.5, 5.5, "MGRS", 0).startswith("32 V ")
    assert ref.format_coord(78.2, 15.6, "MGRS", 0).startswith("33 X ")


def test_coordinates_round_trip() -> None:
    for ab in list(ref.airbases().values())[::7]:
        p = ab["referencePoint"]
        formats: tuple[tuple[ref.CoordFormat, int], ...] = (
            ("DMS", 2),
            ("DDM", 3),
            ("DD", 6),
            ("MGRS", 5),
            ("MGRS", 2),
        )
        for fmt, precision in formats:
            text = ref.format_coord(p["latitude"], p["longitude"], fmt, precision)
            back = ref.parse_coord(f"Label: {text}")
            assert ref.format_coord(back["lat"], back["lon"], fmt, precision) == text


def test_destination_inverts_distance_bearing() -> None:
    for lat, lon, bearing, dist in (
        (41.6, 41.6, 30, 50000),
        (-51.8, -58.4, 250, 400000),
    ):
        to = ref.destination(lat, lon, bearing, dist)
        db = ref.distance_bearing(lat, lon, to["lat"], to["lon"])
        assert db["distM"] == pytest.approx(dist, rel=1e-9)
        assert db["bearingDeg"] == pytest.approx(bearing, abs=1e-9)
