"""Write the shared conformance vectors of the package helpers
(``tools/package/tests/vectors/helpers.json``) from the Python package, the
reference implementation, over the real data. The TypeScript, Python and Lua
package tests all run them.

A vector is ``{"fn": <camelCase name>, "args": [...], "expect": <result>}`` or,
for inputs the helper must reject, ``{"fn", "args", "throws": true}``. Numbers
match within ``TOLERANCE`` (absolute plus relative); object keys of a
``station -> clsid`` mapping are strings. Needs the built package
(``task package``):

    uv run python -m tools.package.vectors [--check]
"""

from __future__ import annotations

import argparse
import importlib
import itertools
import sys
from collections.abc import Callable
from typing import Any

from tools.datamine.common import REPO_ROOT, UNIT_SERIES, fail, json_text

VECTORS = REPO_ROOT / "tools" / "package" / "tests" / "vectors" / "helpers.json"
TOLERANCE = {"abs": 1e-6, "rel": 1e-9}
FIT_AIRCRAFT = (
    "F-16C_50",
    "FA-18C_hornet",
    "A-10C_2",
    "AH-64D_BLK_II",
    "Su-25T",
    "F-14B",
)


def _ref() -> Any:
    sys.path.insert(0, str(REPO_ROOT / "packages" / "python" / "src"))
    return importlib.import_module("dcs_world_reference")


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    return value


def build() -> dict[str, Any]:
    ref = _ref()
    cases: list[dict[str, Any]] = []

    def case(fn: str, call: Callable[..., Any], *args: Any) -> None:
        try:
            result = call(*args)
        except (KeyError, ValueError):
            cases.append({"fn": fn, "args": _jsonable(list(args)), "throws": True})
            return
        cases.append(
            {"fn": fn, "args": _jsonable(list(args)), "expect": _jsonable(result)}
        )

    def theatre_id(name: str) -> str | None:
        t = ref.theatre_by_name(name)
        return None if t is None else t["id"]

    theatres = ref.theatres()
    for t in theatres.values():
        for name in [
            t["id"],
            t.get("displayName"),
            t["directory"],
            *t.get("aliases", []),
        ]:
            if isinstance(name, str):
                case("theatreByName", theatre_id, name)
                case("theatreByName", theatre_id, f"  {name.upper()} ")
    case("theatreByName", theatre_id, "Atlantis")

    airbases = ref.airbases()
    for tid in sorted(theatres):
        points = [
            ab["referencePoint"]
            for _, ab in sorted(airbases.items())
            if ab["theatre"] == tid and "referencePoint" in ab
        ][:3]
        for p in points:
            case("toMapXZ", ref.to_map_xz, tid, p["latitude"], p["longitude"])
            case("toLatLon", ref.to_lat_lon, tid, p["x"], p["z"])
    case("toLatLon", ref.to_lat_lon, "Atlantis", 0, 0)
    case("toLatLon", ref.to_lat_lon, "NTTR", 0, 0)

    threats = ref.threats()
    for tid in sorted(threats):
        case("threatRange", ref.threat_range, tid)
    case("threatRange", ref.threat_range, "no such threat")
    units = sorted(
        {c["unit"] for t in threats.values() for c in t.get("components", [])}
        | {t["unit"] for t in threats.values() if "unit" in t}
    )
    for u in [*units, "M 818", "Hummer", "no such unit"]:
        case("threatForUnitType", ref.threat_for_unit_type, u)
    for tid in ("SA5B55", "ZSU-23-4 Shilka", "Gepard", "1L13 EWR"):
        if tid in threats:
            case("threatRingGeoJSON", ref.threat_ring_geojson, tid, 41.6, 41.6, 8)
    case("threatRingGeoJSON", ref.threat_ring_geojson, "SA5B55", 89.9, 179.9, 3)
    case("threatRingGeoJSON", ref.threat_ring_geojson, "SA5B55", 0, 0, 2)

    aircraft = ref.aircraft()
    for aid in sorted(aircraft):
        case("aircraftRoles", ref.aircraft_roles, aid)
    case("aircraftRoles", ref.aircraft_roles, "no such aircraft")
    for s in UNIT_SERIES:
        for uid in sorted(getattr(ref, s)()):
            case("unitClass", ref.unit_class, uid)
    case("unitClass", ref.unit_class, "no such unit")

    stores = ref.stores()
    for aid in sorted(aircraft):
        stations = sorted(aircraft[aid].get("stations", []), key=lambda s: s["station"])
        if not stations:
            continue
        for st in (stations[0], stations[-1]):
            clsid = next(
                (a["clsid"] for a in st["accepts"] if a["clsid"] in stores), None
            )
            if clsid is not None:
                case("stationsAccepting", ref.stations_accepting, aid, clsid)
                case("canMount", ref.can_mount, aid, st["station"], clsid)
    case("stationsAccepting", ref.stations_accepting, "F-16C_50", "no such store")
    case(
        "stationsAccepting",
        ref.stations_accepting,
        "no such aircraft",
        "{5335D97A-35A5-4643-9D9B-026C75961E52}",
    )
    case(
        "canMount",
        ref.can_mount,
        "F-16C_50",
        1,
        "{5335D97A-35A5-4643-9D9B-026C75961E52}",
    )
    case(
        "canMount",
        ref.can_mount,
        "F-16C_50",
        999,
        "{5335D97A-35A5-4643-9D9B-026C75961E52}",
    )
    # B-52H station 2 lists this launcher in `obsoleteAccepts`: the mission editor
    # hides it, so no helper offers it.
    obsolete = "{46ACDCF8-5451-4E26-BDDB-E78D5830E93C}"
    case("stationsAccepting", ref.stations_accepting, "B-52H", obsolete)
    case("canMount", ref.can_mount, "B-52H", 2, obsolete)
    case("fitStores", ref.fit_stores, "B-52H", [obsolete])
    # Nor is B-52H an AGM-84A carrier: that launcher is its only AGM-84A store.
    case("launchPlatforms", ref.launch_platforms, "AGM_84A")

    for aid in FIT_AIRCRAFT:
        stations = sorted(aircraft[aid].get("stations", []), key=lambda s: s["station"])
        firsts = [
            a["clsid"]
            for st in stations
            for a in st["accepts"][:1]
            if a["clsid"] in stores
        ]
        # Every station's first store, last station first: the fit must
        # reshuffle to the lowest stations that keep the rest placeable.
        request = list(reversed(firsts))
        case("fitStores", ref.fit_stores, aid, request)
        common = max(
            (
                c
                for c in {a["clsid"] for st in stations for a in st["accepts"]}
                if stores.get(c, {}).get("aero", {}).get("massKg", 0) > 0
            ),
            key=lambda c: (len(ref.stations_accepting(aid, c)), c),
        )
        n = len(ref.stations_accepting(aid, common))
        case("fitStores", ref.fit_stores, aid, [common] * n)
        case("fitStores", ref.fit_stores, aid, [common] * (n + 1))
        other = next(c for c in sorted(stores) if not ref.stations_accepting(aid, c))
        case("fitStores", ref.fit_stores, aid, [common, other])
        # The first store of each rule kind with a store it names: alone, with
        # that store, and that store first.
        for kind in ("forbidden", "required"):
            found = next(
                (
                    (a["clsid"], c)
                    for st in stations
                    for a in st["accepts"]
                    if a["clsid"] in stores
                    for r in a.get(kind, [])
                    for c in r.get("clsids", [])
                    if c in stores
                ),
                None,
            )
            if found is not None:
                store, named = found
                case("fitStores", ref.fit_stores, aid, [store])
                case("fitStores", ref.fit_stores, aid, [store, named])
                case("fitStores", ref.fit_stores, aid, [named, store])
        fit = ref.fit_stores(aid, [common] * n)
        loadout = fit.get("assignment", {})
        case("loadoutMass", ref.loadout_mass, aid, loadout, None)
        case("loadoutMass", ref.loadout_mass, aid, loadout, 1000)
        case("loadoutMass", ref.loadout_mass, aid, {}, 0)
    # Symmetric required pairs (station 2 needs the store on 6 and 6 on 2):
    # a lone store or an odd one out lacks its partner, pairs fit even
    # interleaved.
    for n in range(1, 5):
        case("fitStores", ref.fit_stores, "C-101CC", ["BR_250"] * n)
    pairs = ["BR_250", "BR_500", "BR_250", "BR_500"]
    case("fitStores", ref.fit_stores, "C-101CC", pairs[:3])
    case("fitStores", ref.fit_stores, "C-101CC", pairs)
    case("loadoutMass", ref.loadout_mass, "F-15C", {}, None)
    case("loadoutMass", ref.loadout_mass, "F-16C_50", {}, -1)
    case(
        "loadoutMass",
        ref.loadout_mass,
        "F-16C_50",
        {1: "{5335D97A-35A5-4643-9D9B-026C75961E52}"},
        0,
    )

    for aid in sorted(aircraft):
        if not aircraft[aid].get("radios"):
            continue
        case("radioBands", ref.radio_bands, aid)
        for r in ref.radio_bands(aid):
            ranges = r["ranges"]
            lo = min(g["minMHz"] for g in ranges)
            hi = max(g["maxMHz"] for g in ranges)
            gaps = [
                round((a["maxMHz"] + b["minMHz"]) / 2, 3)
                for a, b in itertools.pairwise(ranges)
                if b["minMHz"] > a["maxMHz"]
            ]
            for mhz in (
                lo,
                hi,
                round((lo + hi) / 2, 1),
                lo - 1,
                hi + 1,
                lo + 0.0125,
                *gaps,
            ):
                case("isValidFrequency", ref.is_valid_frequency, aid, r["index"], mhz)
    case("isValidFrequency", ref.is_valid_frequency, "F-16C_50", 7, 251.0)
    for cases_of in (
        _weapon_cases,
        _navaid_cases,
        _airfield_cases,
        _country_cases,
        _geo_cases,
    ):
        cases_of(ref, case)
    return {
        "note": "Generated by tools/package/vectors.py from the Python package; do not edit.",
        "dcsVersion": ref.DCS_VERSION,
        "tolerance": TOLERANCE,
        "cases": cases,
    }


Case = Callable[..., None]
# Aircraft of every size class the stand limits separate.
STAND_AIRCRAFT = ("F-16C_50", "C-130J-30", "KC-135", "UH-1H", "CH-47Fbl1")
# Mission editor copies of one point (user-confirmed clipboard strings).
DCS_COPIES = (
    "Metric: X+00380826 Z-00352108",
    "Lat Long Standard: N 29°32'03\"   E 52°35'55\"",
    "Lat Long Precise: N 29°32'03.53\"   E 52°35'55.82\"",
    "Lat Long Decimal Minutes: N 29°32.296'   E 52°35.179'",
    "MGRS GRID: 39 R XN 54929 68251",
)


def _weapon_cases(ref: Any, case: Case) -> None:
    weapons = ref.weapons()
    for wid in sorted(weapons):
        case("weaponInfo", ref.weapon_info, wid)
    for clsid in sorted(ref.stores())[:60]:
        case("weaponInfo", ref.weapon_info, clsid)
    case("weaponInfo", ref.weapon_info, "no such weapon")
    surface = sorted(
        {
            w
            for s in ("ground_vehicles", "ships")
            for u in getattr(ref, s)().values()
            for ws in u.get("weaponSystems", [])
            for w in ws.get("weapons", [])
        }
    )
    for wid in [*surface, *sorted(weapons)[::10]]:
        case("launchPlatforms", ref.launch_platforms, wid)
    case("launchPlatforms", ref.launch_platforms, "no such weapon")
    shapes = sorted(
        {
            u["model"]["shape"]
            for s in UNIT_SERIES
            for u in getattr(ref, s)().values()
            if "shape" in u.get("model", {})
        }
    )
    for shape in shapes:
        case("modelToUnits", ref.model_to_units, shape)
    for shape in shapes[::25]:
        case("modelToUnits", ref.model_to_units, f" {shape.upper()} ")
    case("modelToUnits", ref.model_to_units, "no such model")
    for s in ("ground_vehicles", "ships"):
        for uid in sorted(getattr(ref, s)()):
            case("unitDetection", ref.unit_detection, uid)
    for s in ("aircraft", "structures", "personnel"):
        for uid in sorted(getattr(ref, s)())[::10]:
            case("unitDetection", ref.unit_detection, uid)
    case("unitDetection", ref.unit_detection, "no such unit")


def _navaid_cases(ref: Any, case: Case) -> None:
    for n in range(1, 127):
        for band in ("X", "Y"):
            for role in ("air", "ground"):
                case("tacanFrequency", ref.tacan_frequency, n, band, role)
    for ch, band, role in (
        (0, "X", "air"),
        (127, "Y", "air"),
        (1.5, "X", "air"),
        (16, "Z", "air"),
        (16, "X", "sea"),
    ):
        case("tacanFrequency", ref.tacan_frequency, ch, band, role)
    for c in (-1, 0, 1, 1.5, 17, 59, 60, 63, 64, 69, 70, 126, 127):
        for band in ("X", "Y", "x", "Z"):
            case("isValidTacan", ref.is_valid_tacan, c, band)
    for b in sorted(ref.beacons().values(), key=lambda b: b["id"]):
        if b.get("channel", 0) >= 1 and "frequencyHz" in b:
            mhz = b["frequencyHz"] / 1e6
            case(
                "tacanChannel", ref.tacan_channel, mhz, "ground" if mhz > 900 else "vhf"
            )
    for mhz, role in (
        (1025, "air"),
        (1150, "air"),
        (1151, "air"),
        (962, "ground"),
        (1213, "ground"),
        (108.05, "vhf"),
        (112.2, "vhf"),
        (1040, "sea"),
    ):
        case("tacanChannel", ref.tacan_channel, mhz, role)
    for aid, ab in sorted(ref.airbases().items()):
        if not ab.get("navaids"):
            continue
        case("navaidsFor", ref.navaids_for, aid, None)
        for rwy in ab.get("runways", []):
            for d in rwy["directions"]:
                case("navaidsFor", ref.navaids_for, aid, d["designator"].lower())
    case("navaidsFor", ref.navaids_for, "Caucasus.22", "99")
    case("navaidsFor", ref.navaids_for, "no such airbase", None)


def _airfield_cases(ref: Any, case: Case) -> None:
    airbases = ref.airbases()
    by_theatre: dict[str, list[str]] = {}
    for aid, ab in sorted(airbases.items()):
        by_theatre.setdefault(ab["theatre"], []).append(aid)
    sample = [
        aid
        for ids in by_theatre.values()
        for aid in [i for i in ids if airbases[i].get("runways")][:3]
    ]
    bare = next(aid for aid, ab in sorted(airbases.items()) if not ab.get("runways"))
    for aid in [*sample, bare]:
        case("runwayEnds", ref.runway_ends, aid)
        for wind in ((0, 0), (90, 10), (271.5, 25), (135, 7.5)):
            case("bestRunway", ref.best_runway, aid, *wind)
    case("bestRunway", ref.best_runway, sample[0], 90, -1)
    case("runwayEnds", ref.runway_ends, "no such airbase")

    def nearest(theatre: str, lat: float, lon: float, options: dict[str, Any]) -> Any:
        return ref.nearest_airbases(
            theatre,
            lat,
            lon,
            min_runway_m=options.get("minRunwayM"),
            n=options.get("n", 5),
            category=options.get("category"),
        )

    for theatre, ids in sorted(by_theatre.items()):
        p = airbases[ids[0]]["referencePoint"]
        lat, lon = p["latitude"] + 0.1, p["longitude"] - 0.1
        for options in (
            {},
            {"n": 1},
            {"n": 8, "minRunwayM": 2500},
            {"category": "airdrome", "n": 3},
            {"category": "HELIPAD"},
        ):
            case("nearestAirbases", nearest, theatre, lat, lon, options)
    case("nearestAirbases", nearest, "NTTR", 36.2, -115.0, {"n": 0})
    case("nearestAirbases", nearest, "Atlantis", 0, 0, {})
    for aid in [
        i
        for ids in by_theatre.values()
        for i in [j for j in ids if airbases[j].get("stands")][:2]
    ]:
        for craft in STAND_AIRCRAFT:
            case("standsFor", ref.stands_for, aid, craft)
    case("standsFor", ref.stands_for, "Caucasus.22", "no such aircraft")


def _country_cases(ref: Any, case: Case) -> None:
    countries = ref.countries()
    for c in sorted(countries.values(), key=lambda c: c["id"]):
        for f in ("name", "shortName", "internationalName", "idName", "oldId"):
            if f in c:
                case("countryId", ref.country_id, c[f])
        case("countryId", ref.country_id, f"  {c['name'].lower()} ")
        case("countryName", ref.country_name, c["id"])
    for name in (
        "United States",
        "UNITED STATES OF AMERICA",
        "united kingdom",
        "Great Britain",
        "Netherlands",
        "Czechia",
        "New Zealand",
        "NEW ZEALAND",
        "Atlantis",
    ):
        case("countryId", ref.country_id, name)
    case("countryName", ref.country_name, 9999)
    liveries = ref.liveries()
    types = sorted({u for lv in liveries.values() for u in lv["unitTypes"]})
    for unit in types[::8]:
        for country in (None, 2, 0, 16):
            case("liveriesFor", ref.liveries_for, unit, country)
    shapes: dict[str, Callable[[dict[str, Any]], bool]] = {
        "every country": lambda lv: "countries" not in lv,
        "filtered": lambda lv: bool(lv.get("countries")),
        "unmapped": lambda lv: "unmappedCountries" in lv,
        "empty": lambda lv: lv.get("countries") == [] and "unmappedCountries" not in lv,
    }
    for shape, test in shapes.items():
        hits = [
            lv for _, lv in sorted(liveries.items()) if lv["unitTypes"] and test(lv)
        ]
        if not hits:
            if shape in ("every country", "filtered"):
                fail(f"vectors: no unit's livery is {shape}")
            continue
        lv = hits[0]
        listed = lv.get("countries", [])
        others = [c for c in sorted(int(k) for k in countries) if c not in listed]
        for country in (None, *listed[:1], *others[:1]):
            case("liveriesFor", ref.liveries_for, lv["unitTypes"][0], country)
    # The Combined Joint Task Forces get every livery, filtered ones included.
    cjtf = [
        c["id"] for c in countries.values() if c.get("shortName") in ("BLUE", "RED")
    ]
    filtered = sorted(
        {u for lv in liveries.values() if lv.get("countries") for u in lv["unitTypes"]}
    )
    for unit in ["F-16C_50", "F-15C", *filtered[::40]]:
        for country in sorted(cjtf):
            case("liveriesFor", ref.liveries_for, unit, country)
    case("liveriesFor", ref.liveries_for, "F-15C", 9999)
    case("liveriesFor", ref.liveries_for, "no such unit", None)
    for aid in sorted(ref.aircraft()):
        case("datalinkCapability", ref.datalink_capability, aid)
    case("datalinkCapability", ref.datalink_capability, "no such aircraft")


def _geo_cases(ref: Any, case: Case) -> None:
    points = [
        (0, 0),
        (29.534313888888892, 52.59883888888889),
        (41.6096, 41.6002),
        (-51.8228, -58.4478),
        (36.2359, -115.0343),
        (59.9999, 5.3),
        (78.2, 15.6),
        (-79.99, 179.99),
        (84, -180),
        (-33.8568, 151.2153),
        (0.000001, -0.000001),
        (47.99999999, 7.99999999),
    ]
    for (lat1, lon1), (lat2, lon2) in zip(points, points[1:] + points[:1], strict=True):
        case("distanceBearing", ref.distance_bearing, lat1, lon1, lat2, lon2)
    case("distanceBearing", ref.distance_bearing, 41.6, 41.6, 41.6, 41.6)
    case("distanceBearing", ref.distance_bearing, 91, 0, 0, 0)
    for lat, lon in points:
        for bearing, dist in ((0, 0), (45, 10000), (271.25, 250000)):
            case("destination", ref.destination, lat, lon, bearing, dist)
    case("destination", ref.destination, 0, 181, 0, 0)
    for lat, lon in points:
        for fmt, precisions in (
            ("DD", (None, 0, 8)),
            ("DMS", (None, 2, 4)),
            ("DDM", (None, 0, 6)),
            ("MGRS", (None, 0, 1, 3)),
        ):
            for p in precisions:
                case("formatCoord", ref.format_coord, lat, lon, fmt, p)
    for fmt, p in (("DMS", 5), ("MGRS", 6), ("UTM", None), ("DD", -1)):
        case("formatCoord", ref.format_coord, 1, 1, fmt, p)
    case("formatCoord", ref.format_coord, 85, 0, "MGRS", None)
    case("formatCoord", ref.format_coord, 0, 190, "DMS", None)
    texts = [
        *DCS_COPIES,
        *(t.split(": ", 1)[1] for t in DCS_COPIES),
        "39RXN5492968251",
        "39 r xn 5492 6825",
        "39R XN",
        "31N AA 66021 00000",
        "s 51°49'22.08\" w 58°26'52.08\"",
        "S 51 49.368 W 58 26.868",
        "N 41.6096°   E 41.6002°",
        "-51.8228, -58.4478",
        "x-00000001 z+00000002",
        "N 29°32'03.53\"",
        "N 29°32'60\"   E 52°35'55\"",
        "N 29.5°32'   E 52°35'",
        "E 29°32'03\"   N 52°35'55\"",
        "N 91°00'00\"   E 52°35'55\"",
        "39 R XA 54929 68251",
        "39 R XN 5492 682",
        "61 R XN 54929 68251",
        "Metric: X+003808.26",
        "N 29°32'03\"   E 52°35'55\" extra",
        "N 29°32'03\"   E 52°35'55\" ß",
        "",
    ]
    for text in texts:
        case("parseCoord", ref.parse_coord, text)
    for lat, lon in points:
        for fmt in ("DD", "DMS", "DDM", "MGRS"):
            try:
                text = ref.format_coord(lat, lon, fmt, None)
            except ValueError:
                continue
            case("parseCoord", ref.parse_coord, text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="fail if the file differs")
    args = parser.parse_args()
    text = json_text(build())
    if args.check:
        if not VECTORS.is_file() or VECTORS.read_text(encoding="utf-8") != text:
            fail(f"{VECTORS} is stale; run `uv run python -m tools.package.vectors`")
        print(f"{VECTORS.relative_to(REPO_ROOT)} is current")
        return 0
    VECTORS.parent.mkdir(parents=True, exist_ok=True)
    VECTORS.write_text(text, encoding="utf-8", newline="\n")
    print(f"Wrote {VECTORS.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
