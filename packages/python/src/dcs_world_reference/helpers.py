"""Reference helpers: pure functions of the published data (map projection,
threat rings, unit classification, loadout fit and mass, radio tuning, weapons
and detection, TACAN channels, runways and stands, countries, liveries and
datalinks) and pure geo maths (distances, coordinate formats, MGRS).

The TypeScript and Lua packages implement the same functions; the shared test
vectors in ``tools/package/tests/vectors/`` hold every package to the results
of this one. Unknown ids and impossible inputs raise ``KeyError`` or
``ValueError``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any, Final, Literal, NotRequired, TypedDict, cast

from . import Theatre, _load
from .lookup import _index, _meta, aircraft_carrying, name_key, threats_for_unit

Record = Mapping[str, Any]


def _series(name: str) -> Mapping[str, Record]:
    return cast(Mapping[str, Record], _load(name))


def _record(series: str, id: str) -> Record:
    record = _series(series).get(id)
    if record is None:
        raise KeyError(f"no {series} record {id!r}")
    return record


# Theatre projection ---------------------------------------------------------


class LatLon(TypedDict):
    lat: float
    lon: float


class MapXZ(TypedDict):
    x: float
    z: float


# WGS84 and the Krueger series to order n^6 (Karney 2011), as
# tools/datamine/tmerc.py fitted the projections with.
_A: Final = 6378137.0
_F: Final = 1 / 298.257223563
_N: Final = _F / (2 - _F)
_E: Final = math.sqrt(_F * (2 - _F))
_A_RECT: Final = _A / (1 + _N) * (1 + _N**2 / 4 + _N**4 / 64 + _N**6 / 256)
_ALPHA: Final = (
    _N / 2
    - 2 / 3 * _N**2
    + 5 / 16 * _N**3
    + 41 / 180 * _N**4
    - 127 / 288 * _N**5
    + 7891 / 37800 * _N**6,
    13 / 48 * _N**2
    - 3 / 5 * _N**3
    + 557 / 1440 * _N**4
    + 281 / 630 * _N**5
    - 1983433 / 1935360 * _N**6,
    61 / 240 * _N**3
    - 103 / 140 * _N**4
    + 15061 / 26880 * _N**5
    + 167603 / 181440 * _N**6,
    49561 / 161280 * _N**4 - 179 / 168 * _N**5 + 6601661 / 7257600 * _N**6,
    34729 / 80640 * _N**5 - 3418889 / 1995840 * _N**6,
    212378941 / 319334400 * _N**6,
)


def _tm(lat: float, dlon: float) -> tuple[float, float]:
    """(E, N) metres at unit scale, latitude of origin 0."""
    phi, lam = math.radians(lat), math.radians(dlon)
    s = math.sin(phi)
    t = math.sinh(math.atanh(s) - _E * math.atanh(_E * s))
    xi_p = math.atan2(t, math.cos(lam))
    eta_p = math.atanh(math.sin(lam) / math.sqrt(1 + t * t))
    xi, eta = xi_p, eta_p
    for j, a in enumerate(_ALPHA, start=1):
        xi += a * math.sin(2 * j * xi_p) * math.cosh(2 * j * eta_p)
        eta += a * math.cos(2 * j * xi_p) * math.sinh(2 * j * eta_p)
    return _A_RECT * eta, _A_RECT * xi


def _to_map(p: Record, lat: float, lon: float) -> tuple[float, float]:
    e, n = _tm(lat, lon - p["centralMeridian"])
    k = p["scaleFactor"]
    return p["falseNorthing"] + k * n, p["falseEasting"] + k * e


def _projection(theatre: str) -> Record:
    record = theatre_by_name(theatre)
    if record is None:
        raise KeyError(f"no theatre {theatre!r}")
    if "projection" not in record:
        raise ValueError(f"theatre {record['id']} has no map projection")
    return cast(Record, record["projection"])


def theatre_by_name(name: str) -> Theatre | None:
    """The theatre whose id, displayName, directory or one of its
    ``aliases`` is ``name`` (trimmed, ASCII case-insensitive), or None."""
    key = name_key(name)
    for record in cast(Mapping[str, Theatre], _load("theatres")).values():
        names = [record["id"], record.get("displayName"), record["directory"]]
        if any(isinstance(n, str) and name_key(n) == key for n in names) or any(
            name_key(a) == key for a in record.get("aliases", [])
        ):
            return record
    return None


def to_map_xz(theatre: str, lat: float, lon: float) -> MapXZ:
    """DCS map metres (``x`` north, ``z`` east) of a WGS84 latitude/longitude
    on ``theatre`` (anything :func:`theatre_by_name` accepts), through its
    Transverse Mercator ``projection``."""
    x, z = _to_map(_projection(theatre), lat, lon)
    return {"x": x, "z": z}


def to_lat_lon(theatre: str, x: float, z: float) -> LatLon:
    """WGS84 latitude/longitude of map metres (``x``, ``z``) on ``theatre``:
    Newton iteration on :func:`to_map_xz` from (0, central meridian) until
    both residuals are under a micrometre (at most 50 steps)."""
    return _inverse(_projection(theatre), x, z)


def _inverse(p: Record, x: float, z: float) -> LatLon:
    lat, lon = 0.0, float(p["centralMeridian"])
    h = 1e-6
    for _ in range(50):
        px, pz = _to_map(p, lat, lon)
        dx, dz = x - px, z - pz
        if abs(dx) < 1e-6 and abs(dz) < 1e-6:
            return {"lat": lat, "lon": lon}
        x1, z1 = _to_map(p, lat + h, lon)
        x2, z2 = _to_map(p, lat, lon + h)
        a, b = (x1 - px) / h, (x2 - px) / h
        c, d = (z1 - pz) / h, (z2 - pz) / h
        det = a * d - b * c
        lat += (d * dx - b * dz) / det
        lon += (a * dz - c * dx) / det
    raise ArithmeticError(f"to_lat_lon did not converge for ({x}, {z})")


# Threats ----------------------------------------------------------------------


class ThreatRange(TypedDict):
    """The union of a threat's engagement envelopes and its sensors' reach.
    A limit is present only when every envelope gives it."""

    rMinKm: NotRequired[float]
    rMaxKm: NotRequired[float]
    hMinM: NotRequired[float]
    hMaxM: NotRequired[float]
    detectionKm: NotRequired[float]


def threat_range(threat_id: str) -> ThreatRange:
    """Over every component ``envelope`` and ``gunEnvelope`` of threat
    ``threat_id``: ``rMaxKm``/``hMaxM`` the largest, ``rMinKm``/``hMinM`` the
    smallest, each only when every envelope gives it (no envelopes: none).
    ``detectionKm`` is the largest ``detectionRangeKm`` of its ``sensors``
    (absent when none gives one)."""
    threat = _record("threats", threat_id)
    envelopes = [
        c[key]
        for c in threat.get("components", [])
        for key in ("envelope", "gunEnvelope")
        if key in c
    ]
    out: dict[str, float] = {}
    for key, pick in (("rMinKm", min), ("rMaxKm", max), ("hMinM", min), ("hMaxM", max)):
        values = [e[key] for e in envelopes if key in e]
        if envelopes and len(values) == len(envelopes):
            out[key] = pick(values)
    sensors = _series("sensors")
    reach = [
        sensors[s]["detectionRangeKm"]
        for s in threat.get("sensors", [])
        if s in sensors and "detectionRangeKm" in sensors[s]
    ]
    if reach:
        out["detectionKm"] = max(reach)
    return cast(ThreatRange, out)


def _unit_series(unit_id: str) -> str | None:
    for s in cast(list[str], _meta()["unitSeries"]):
        if unit_id in _series(s):
            return s
    return None


def threat_for_unit_type(unit_type: str) -> list[str]:
    """Threat systems (``threats`` ids, sorted) unit type ``unit_type`` is a
    component or the emitter of; raises ``KeyError`` for an id no unit series
    holds (:func:`threats_for_unit` returns ``[]`` for it)."""
    if _unit_series(unit_type) is None:
        raise KeyError(f"no unit type {unit_type!r}")
    return threats_for_unit(unit_type)


EARTH_RADIUS_M: Final = 6371008.8
"""Mean Earth radius (IUGG) of the spherical ring geometry."""


def _destination(lat: float, lon: float, bearing: float, dist_m: float) -> list[float]:
    """[lon, lat] ``dist_m`` from (lat, lon) on ``bearing`` degrees, on a
    sphere of radius ``EARTH_RADIUS_M``; longitude in [-180, 180)."""
    phi, lam = math.radians(lat), math.radians(lon)
    theta, delta = math.radians(bearing), dist_m / EARTH_RADIUS_M
    phi2 = math.asin(
        math.sin(phi) * math.cos(delta)
        + math.cos(phi) * math.sin(delta) * math.cos(theta)
    )
    lam2 = lam + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(phi),
        math.cos(delta) - math.sin(phi) * math.sin(phi2),
    )
    lon2 = math.degrees(lam2)
    lon2 = (lon2 + 180) % 360 - 180
    return [lon2, math.degrees(phi2)]


def _ring(
    lat: float, lon: float, km: float, segments: int, clockwise: bool
) -> list[list[float]]:
    """Closed ring of ``segments`` points; bearing 0 first, then clockwise
    (increasing bearing) or counterclockwise."""
    points = []
    for i in range(segments + 1):
        step = i % segments
        bearing = (
            360 * step / segments
            if clockwise
            else (360 * (segments - step) / segments) % 360
        )
        points.append(_destination(lat, lon, bearing, km * 1000))
    return points


def threat_ring_geojson(
    threat_id: str, lat: float, lon: float, segments: int = 64
) -> dict[str, Any]:
    """A GeoJSON FeatureCollection of one Polygon feature: the threat's
    ``rMaxKm`` ring around (``lat``, ``lon``) (counterclockwise, as RFC 7946
    wants an exterior ring) with its ``rMinKm`` ring as a clockwise hole when
    ``rMinKm > 0``; ``segments`` points per ring plus the closing one.
    Properties: ``threat`` and the :func:`threat_range` fields. Raises
    ``ValueError`` for a threat without ``rMaxKm`` or ``segments < 3``."""
    if segments < 3:
        raise ValueError(f"segments must be at least 3, got {segments}")
    rng = threat_range(threat_id)
    if "rMaxKm" not in rng:
        raise ValueError(f"threat {threat_id} has no engagement range")
    rings = [_ring(lat, lon, rng["rMaxKm"], segments, clockwise=False)]
    if rng.get("rMinKm", 0) > 0:
        rings.append(_ring(lat, lon, rng["rMinKm"], segments, clockwise=True))
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"threat": threat_id, **rng},
                "geometry": {"type": "Polygon", "coordinates": rings},
            }
        ],
    }


# Classification ----------------------------------------------------------------

Facts = Mapping[str, Sequence[str]]


def _matches(when: Mapping[str, Mapping[str, Sequence[str]]], facts: Facts) -> bool:
    for fact, tests in when.items():
        have = set(facts.get(fact, ()))
        if "any" in tests and not have.intersection(tests["any"]):
            return False
        if "all" in tests and not have.issuperset(tests["all"]):
            return False
        if "none" in tests and have.intersection(tests["none"]):
            return False
    return True


def _rules(name: str) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], _index("classification")[name])


def aircraft_roles(aircraft_id: str) -> list[str]:
    """Sorted roles of aircraft ``aircraft_id``: those of every matching
    ``aircraft/roles`` rule of the ``classification`` index (facts
    ``attributes``, ``kind``, ``tasks``, ``defaultTask``, ``isTanker``)."""
    a = _record("aircraft", aircraft_id)
    tanker = a.get("refuelling", {}).get("isTanker")
    default = a.get("defaultTask")
    facts = {
        "attributes": a.get("attributes", []),
        "kind": [a["kind"]],
        "tasks": [t["name"] for t in a.get("tasks", [])],
        "defaultTask": [default["name"]] if default else [],
        "isTanker": ["true"]
        if tanker is not None and tanker is not False and tanker != 0
        else [],
    }
    return sorted(
        {r["role"] for r in _rules("aircraftRoles") if _matches(r["when"], facts)}
    )


def unit_class(unit_id: str) -> str:
    """Class of unit ``unit_id`` (any unit series): that of the first matching
    ``units/classes`` rule of the ``classification`` index (facts ``series``,
    ``attributes``, ``kind``), else ``"other"``."""
    series = _unit_series(unit_id)
    if series is None:
        raise KeyError(f"no unit type {unit_id!r}")
    u = _series(series)[unit_id]
    facts = {
        "series": [series],
        "attributes": u.get("attributes", []),
        "kind": [u["kind"]] if series == "aircraft" else [],
    }
    for r in _rules("unitClasses"):
        if _matches(r["when"], facts):
            return cast(str, r["class"])
    return "other"


# Loadouts ------------------------------------------------------------------------


class FitConflict(TypedDict):
    index: int
    """Position in the requested list."""
    clsid: str
    reason: Literal["unsupported", "noFreeStation", "loadoutRules"]
    """``unsupported``: no station accepts the store; ``noFreeStation``: the
    stations accepting it are all needed by the stores listed before it;
    ``loadoutRules``: every placement with them breaks a station's
    ``forbidden``/``required`` rule."""


class FitResult(TypedDict):
    assignment: NotRequired[dict[int, str]]
    conflicts: NotRequired[list[FitConflict]]


class LoadoutMass(TypedDict):
    totalKg: float
    emptyKg: float
    storesKg: float
    fuelKg: float
    maxTakeoffKg: NotRequired[float]
    overMtow: NotRequired[bool]


def _stations(aircraft_id: str) -> list[Record]:
    a = _record("aircraft", aircraft_id)
    return sorted(a.get("stations", []), key=lambda s: s["station"])


def _store(clsid: str) -> Record:
    return _record("stores", clsid)


def _accepted(station: Record, clsid: str) -> Record | None:
    return next((a for a in station["accepts"] if a["clsid"] == clsid), None)


def stations_accepting(aircraft_id: str, clsid: str) -> list[int]:
    """Station numbers (ascending) of aircraft ``aircraft_id`` accepting store
    ``clsid``."""
    _store(clsid)
    return [int(s["station"]) for s in _stations(aircraft_id) if _accepted(s, clsid)]


def can_mount(aircraft_id: str, station: int, clsid: str) -> bool:
    """Whether station ``station`` of aircraft ``aircraft_id`` accepts store
    ``clsid``; raises ``KeyError`` for a station the aircraft lacks."""
    _store(clsid)
    for s in _stations(aircraft_id):
        if s["station"] == station:
            return _accepted(s, clsid) is not None
    raise KeyError(f"aircraft {aircraft_id} has no station {station}")


def _matching(options: list[list[int]]) -> int:
    """Size of a maximum matching of stores (each a list of candidate
    stations) to distinct stations (Kuhn's augmenting paths)."""
    owner: dict[int, int] = {}

    def augment(i: int, seen: set[int]) -> bool:
        for s in options[i]:
            if s not in seen:
                seen.add(s)
                if s not in owner or augment(owner[s], seen):
                    owner[s] = i
                    return True
        return False

    return sum(1 for i in range(len(options)) if augment(i, set()))


Rules = dict[tuple[int, str], Record]


def _breaks(rule: Record, occupant: str | None, required: bool) -> bool:
    """Whether ``occupant`` (None: empty) of the rule's station breaks it: a
    ``required`` rule wants one of ``clsids`` (or nothing with ``allowEmpty``),
    a ``forbidden`` rule none of ``clsids`` (no store with ``anyStore``)."""
    if required:
        return (
            not rule["allowEmpty"]
            if occupant is None
            else occupant not in rule["clsids"]
        )
    return occupant is not None and (
        rule.get("anyStore", False) or occupant in rule["clsids"]
    )


def _allowed(a: dict[int, str], rules: Rules, s: int, c: str) -> bool:
    """Whether store ``c`` can join ``a`` (station -> CLSID) on station ``s``
    without breaking a rule of either side; a ``required`` rule on a station
    still empty is left to the complete assignment."""
    for kind, required in (("forbidden", False), ("required", True)):
        for r in rules[(s, c)].get(kind, []):
            t = r["station"]
            occupant = c if t == s else a.get(t)
            if occupant is not None and _breaks(r, occupant, required):
                return False
        for t, o in a.items():
            for r in rules[(t, o)].get(kind, []):
                if r["station"] == s and _breaks(r, c, required):
                    return False
    return True


def _complete(
    a: dict[int, str],
    rules: Rules,
    clsids: Sequence[str],
    options: list[list[int]],
    pool: list[int],
) -> bool:
    """Whether stores of ``pool`` (each used once) can fill every station a
    ``required`` rule of ``a`` needs, keeping every rule; ``a`` is restored."""
    need = next(
        (
            r
            for t, o in a.items()
            for r in rules[(t, o)].get("required", [])
            if _breaks(r, a.get(r["station"]), True)
        ),
        None,
    )
    if need is None:
        return True
    s = need["station"]
    if s in a:
        return False
    tried: set[str] = set()
    for j in pool:
        c = clsids[j]
        if c in tried or c not in need["clsids"] or s not in options[j]:
            continue
        tried.add(c)
        if not _allowed(a, rules, s, c):
            continue
        a[s] = c
        done = _complete(a, rules, clsids, options, [k for k in pool if k != j])
        del a[s]
        if done:
            return True
    return False


def _place(
    clsids: Sequence[str],
    options: list[list[int]],
    idx: list[int],
    rules: Rules,
    pool: list[int] | None = None,
) -> dict[int, str] | None:
    """The first assignment of stores ``idx`` (in order, each on its lowest
    station that leaves the rest placeable) keeping every rule, stations
    ``required`` rules need left empty only where stores of ``pool`` can fill
    them; None if none."""
    a: dict[int, str] = {}
    at: dict[int, int] = {}

    def step(k: int) -> bool:
        if k == len(idx):
            return _complete(a, rules, clsids, options, pool or [])
        i = idx[k]
        # A store equal to an earlier one goes above it (same fits, fewer tries).
        low = max((at[j] for j in idx[:k] if clsids[j] == clsids[i]), default=None)
        for s in options[i]:
            if (
                s in a
                or (low is not None and s <= low)
                or not _allowed(a, rules, s, clsids[i])
            ):
                continue
            a[s], at[i] = clsids[i], s
            rest = [[t for t in options[j] if t not in a] for j in idx[k + 1 :]]
            if _matching(rest) == len(rest) and step(k + 1):
                return True
            del a[s], at[i]
        return False

    return dict(sorted(a.items())) if step(0) else None


def fit_stores(aircraft_id: str, clsids: Sequence[str]) -> FitResult:
    """Put each store of ``clsids`` on its own station of ``aircraft_id``.

    Rule: a store no station accepts is ``unsupported``; the others are taken
    in list order, each kept while all kept stores still fit on distinct
    stations (else ``noFreeStation``) and some such placement, with stores
    later in the list filling the stations its ``required`` rules need, keeps
    every station's ``forbidden``/``required`` rules (else ``loadoutRules``; a
    ``required`` station must hold a listed store, or be empty where it
    ``allowEmpty``). Every station accepting a store is a candidate, whatever
    its ``type``, as in the mission editor. With no conflicts, each store in
    list order gets the lowest-numbered station that leaves the rest
    placeable: ``{"assignment": {station: clsid}}``; otherwise
    ``{"conflicts": [...]}``."""
    # Same lookup order, hence same error, as stations_accepting per store.
    for c in clsids[:1]:
        _store(c)
    stations = _stations(aircraft_id)
    for c in clsids[1:]:
        _store(c)
    rules: Rules = {}
    accepting: dict[str, list[int]] = {c: [] for c in clsids}
    for s in stations:
        n = int(s["station"])
        here: set[str] = set()
        for a in s["accepts"]:
            c = a["clsid"]
            if c in accepting:
                rules[(n, c)] = a
                if c not in here:
                    here.add(c)
                    accepting[c].append(n)
    options = [accepting[c] for c in clsids]
    # Without rules every placement that fits keeps them.
    ruled = any(
        rules[(s, c)].get("forbidden") or rules[(s, c)].get("required")
        for c, opts in zip(clsids, options, strict=True)
        for s in opts
    )
    conflicts: list[FitConflict] = []
    kept: list[int] = []
    placed: dict[int, str] | None = None

    def later(i: int) -> list[int]:
        return [k for k in range(i + 1, len(clsids)) if options[k]]

    for i, opts in enumerate(options):
        reason: Literal["unsupported", "noFreeStation", "loadoutRules"] | None = None
        if not opts:
            reason = "unsupported"
        elif _matching([options[k] for k in [*kept, i]]) != len(kept) + 1:
            reason = "noFreeStation"
        elif ruled:
            placed = _place(clsids, options, [*kept, i], rules, later(i))
            if placed is None:
                reason = "loadoutRules"
        if reason is None:
            kept.append(i)
        else:
            conflicts.append({"index": i, "clsid": clsids[i], "reason": reason})
    if conflicts:
        return {"conflicts": conflicts}
    # With no conflicts the last store's placement is that of every store.
    if placed is None:
        placed = _place(clsids, options, kept, rules)
    return {"assignment": placed or {}}


def loadout_mass(
    aircraft_id: str, loadout: Mapping[int, str], fuel_kg: float | None = None
) -> LoadoutMass:
    """Mass of aircraft ``aircraft_id`` with ``loadout`` (station -> store
    CLSID) and ``fuel_kg`` of internal fuel (default: ``aero.internalFuelKg``,
    full): ``emptyKg`` (``aero.emptyMassKg``) + ``storesKg`` (each store's
    ``aero.massKg``, DCS's launcher ``Weight``: rack and contents included) +
    ``fuelKg``; with ``aero.maxTakeoffKg``, ``maxTakeoffKg`` and ``overMtow``.
    Raises for a station that does not accept its store, a store without a
    mass, a missing empty mass, fuel not given where the aircraft has no
    ``internalFuelKg``, or fuel outside 0..``internalFuelKg``."""
    a = _record("aircraft", aircraft_id)
    aero = a.get("aero", {})
    if "emptyMassKg" not in aero:
        raise ValueError(f"aircraft {aircraft_id} has no aero.emptyMassKg")
    capacity = aero.get("internalFuelKg")
    if fuel_kg is None:
        if capacity is None:
            raise ValueError(
                f"aircraft {aircraft_id} has no aero.internalFuelKg; pass fuel_kg"
            )
        fuel_kg = capacity
    if fuel_kg < 0 or (capacity is not None and fuel_kg > capacity):
        raise ValueError(
            f"fuel {fuel_kg} kg outside 0..{capacity} kg for {aircraft_id}"
        )
    stores_kg = 0.0
    for station, clsid in sorted(loadout.items()):
        if not can_mount(aircraft_id, station, clsid):
            raise ValueError(
                f"station {station} of {aircraft_id} does not accept {clsid}"
            )
        mass = _store(clsid).get("aero", {}).get("massKg")
        if mass is None:
            raise ValueError(f"store {clsid} has no aero.massKg")
        stores_kg += mass
    empty = aero["emptyMassKg"]
    total = empty + stores_kg + fuel_kg
    out: LoadoutMass = {
        "totalKg": total,
        "emptyKg": empty,
        "storesKg": stores_kg,
        "fuelKg": fuel_kg,
    }
    if "maxTakeoffKg" in aero:
        out["maxTakeoffKg"] = aero["maxTakeoffKg"]
        out["overMtow"] = total > aero["maxTakeoffKg"]
    return out


# Radios --------------------------------------------------------------------------


class FrequencyRange(TypedDict):
    minMHz: float
    maxMHz: float
    modulations: list[str]
    """DCS ``MODULATION_*`` names."""


class RadioBands(TypedDict):
    index: int
    """``<index>`` of the radio id ``<aircraft>__radio<index>`` (DCS
    ``panelRadio`` order, from 0)."""
    id: str
    band: str
    ranges: list[FrequencyRange]
    presets: int
    guard: bool
    stepKHz: NotRequired[float]


class FrequencyCheck(TypedDict):
    ok: bool
    reason: NotRequired[Literal["outOfRange", "offStep"]]


_RADIO_SEP: Final = "__radio"


def radio_bands(aircraft_id: str) -> list[RadioBands]:
    """The radios of aircraft ``aircraft_id`` by index: band, tunable ranges
    (the DCS range segments) with their modulations, preset count, guard
    coverage and ``stepKHz`` where the data gives one."""
    out: list[RadioBands] = []
    radios = _series("radios")
    for rid in _record("aircraft", aircraft_id).get("radios", []):
        r = radios.get(rid)
        if r is None:
            raise KeyError(f"no radios record {rid!r}")
        head, sep, index = rid.rpartition(_RADIO_SEP)
        if not sep or head != aircraft_id or not index.isdigit():
            raise ValueError(
                f"radio id {rid!r} is not {aircraft_id}{_RADIO_SEP}<index>"
            )
        entry: RadioBands = {
            "index": int(index),
            "id": rid,
            "band": r["band"],
            "ranges": [
                {
                    "minMHz": s["minMHz"],
                    "maxMHz": s["maxMHz"],
                    "modulations": [s["modulationName"]],
                }
                for s in r["segments"]
            ],
            "presets": r["presets"],
            "guard": r["guard"],
        }
        if "stepKHz" in r:
            entry["stepKHz"] = r["stepKHz"]
        out.append(entry)
    return sorted(out, key=lambda e: e["index"])


STEP_TOLERANCE: Final = 1e-6
"""Largest distance from a tuning step, in steps, still on the step grid."""


def is_valid_frequency(
    aircraft_id: str, radio_index: int, mhz: float
) -> FrequencyCheck:
    """Whether radio ``radio_index`` of ``aircraft_id`` tunes ``mhz``: within
    a range (else ``outOfRange``) and, with ``stepKHz``, on the step
    grid counted from 0 Hz (``offStep``). Raises ``KeyError`` for a radio the
    aircraft lacks."""
    for r in radio_bands(aircraft_id):
        if r["index"] != radio_index:
            continue
        if not any(g["minMHz"] <= mhz <= g["maxMHz"] for g in r["ranges"]):
            return {"ok": False, "reason": "outOfRange"}
        if "stepKHz" in r:
            steps = mhz * 1000 / r["stepKHz"]
            if abs(steps - round(steps)) > STEP_TOLERANCE:
                return {"ok": False, "reason": "offStep"}
        return {"ok": True}
    raise KeyError(f"aircraft {aircraft_id} has no radio {radio_index}")


# Weapons -------------------------------------------------------------------------


class WarheadInfo(TypedDict):
    id: str
    massKg: float
    type: NotRequired[str]
    explosiveMassKg: NotRequired[float]
    fragmentation: NotRequired[bool]
    hardTargetPenetrator: NotRequired[bool]


class WeaponInfo(TypedDict):
    """A weapon record's fields as the data gives them (no ``_source``), its
    ``warhead`` resolved to the warhead record."""

    id: str
    displayName: str
    massKg: float
    attributes: list[str]
    category: NotRequired[int]
    categoryName: NotRequired[str]
    launcherCategory: NotRequired[int]
    launcherCategoryName: NotRequired[str]
    subcategory: NotRequired[int]
    subcategoryName: NotRequired[str]
    className: NotRequired[str]
    scheme: NotRequired[str]
    seekerType: NotRequired[int]
    seekerTypeName: NotRequired[str]
    seeker: NotRequired[dict[str, Any]]
    rangeKm: NotRequired[float]
    rangeField: NotRequired[str]
    rangeMinKm: NotRequired[float]
    rangeMinField: NotRequired[str]
    launchRangeMaxKm: NotRequired[float]
    rwrSymbol: NotRequired[str]
    alic: NotRequired[list[str]]
    warhead: NotRequired[WarheadInfo]


class LaunchPlatforms(TypedDict):
    aircraft: list[str]
    groundVehicles: list[str]
    ships: list[str]


def _weapon_id(id_or_clsid: str) -> str:
    if id_or_clsid in _series("weapons"):
        return id_or_clsid
    store = _series("stores").get(id_or_clsid)
    if store is None:
        raise KeyError(f"no weapon or store {id_or_clsid!r}")
    delivered = sorted({str(d["weapon"]) for d in store.get("delivers", [])})
    if len(delivered) != 1:
        raise ValueError(
            f"store {id_or_clsid} delivers {len(delivered)} weapon types, not one"
        )
    return delivered[0]


def weapon_info(id_or_clsid: str) -> WeaponInfo:
    """The weapon ``id_or_clsid`` names: a weapon id, else the CLSID of a store
    delivering exactly one weapon type (``ValueError`` for a store delivering
    several or none). Fields are the weapon record's (``_source`` dropped),
    with ``warhead`` the warhead record; a field the data lacks is absent."""
    weapon = _record("weapons", _weapon_id(id_or_clsid))
    out = {k: v for k, v in weapon.items() if k != "_source"}
    if "warhead" in weapon:
        out["warhead"] = dict(_record("warheads", weapon["warhead"]))
    return cast(WeaponInfo, out)


def _surface_launchers(series: str, weapon_id: str) -> list[str]:
    return sorted(
        uid
        for uid, u in _series(series).items()
        if any(weapon_id in ws.get("weapons", []) for ws in u.get("weaponSystems", []))
    )


def launch_platforms(weapon_id: str) -> LaunchPlatforms:
    """Unit types launching weapon ``weapon_id``, sorted: ``aircraft`` with a
    station accepting a store that delivers it (the ``carriers`` index),
    ``groundVehicles`` and ``ships`` with a launcher (``weaponSystems[]``)
    whose ``weapons`` hold it."""
    _record("weapons", weapon_id)
    return {
        "aircraft": aircraft_carrying(weapon_id),
        "groundVehicles": _surface_launchers("ground_vehicles", weapon_id),
        "ships": _surface_launchers("ships", weapon_id),
    }


def model_to_units(shape: str) -> list[str]:
    """Unit ids of every unit series whose ``model.shape`` is ``shape``,
    sorted. Names compare as :func:`name_key` does (trimmed, ASCII
    case-insensitive): DCS finds models by file name, and Windows file names
    ignore case."""
    key = name_key(shape)
    return sorted(
        uid
        for s in cast(list[str], _meta()["unitSeries"])
        for uid, u in _series(s).items()
        if isinstance(u.get("model", {}).get("shape"), str)
        and name_key(u["model"]["shape"]) == key
    )


class SensorSummary(TypedDict):
    id: str
    kind: str
    detectionRangeKm: NotRequired[float]


class UnitDetectionInfo(TypedDict):
    """A unit's ``detection`` fields as the data gives them, and its sensors."""

    sensors: list[SensorSummary]
    detectionRangeM: NotRequired[float]
    detectionRangeMax: NotRequired[float]
    threatRangeM: NotRequired[float]
    threatRangeMinM: NotRequired[float]
    airWeaponDistM: NotRequired[float]
    airFindDistM: NotRequired[float]
    irEmissionCoeff: NotRequired[float]
    rcsM2: NotRequired[float]
    sensor: NotRequired[dict[str, Any]]


def unit_detection(unit_id: str) -> UnitDetectionInfo:
    """Detection values of unit ``unit_id`` (any unit series): its
    ``detection`` fields, and ``sensors``, its sensor ids in record order with
    each sensor's ``kind`` and ``detectionRangeKm`` (when given)."""
    series = _unit_series(unit_id)
    if series is None:
        raise KeyError(f"no unit type {unit_id!r}")
    u = _series(series)[unit_id]
    out: dict[str, Any] = dict(u.get("detection", {}))
    sensors = []
    for sid in u.get("sensors", []):
        s = _record("sensors", sid)
        entry: dict[str, Any] = {"id": sid, "kind": s["kind"]}
        if "detectionRangeKm" in s:
            entry["detectionRangeKm"] = s["detectionRangeKm"]
        sensors.append(entry)
    out["sensors"] = sensors
    return cast(UnitDetectionInfo, out)


# TACAN and navaids ------------------------------------------------------------------

TacanBand = Literal["X", "Y"]


class TacanFrequency(TypedDict):
    txMHz: float
    """Transmit frequency of the side ``role`` names."""
    rxMHz: float
    """Receive frequency of that side."""
    pairedVhfMHz: NotRequired[float]
    """The VOR/ILS frequency the channel pairs with, when it pairs."""


class TacanChannel(TypedDict):
    channel: int
    band: TacanBand


def _plan() -> Record:
    return cast(Record, _index("tacan"))


def is_valid_tacan(channel: float, band: str) -> bool:
    """Whether ``channel`` (an integer) and ``band`` name a channel of the
    ``tacan`` plan (1-126, X or Y)."""
    plan = _plan()
    return (
        not isinstance(channel, bool)
        and isinstance(channel, int | float)
        and channel == math.floor(channel)
        and plan["channels"]["first"] <= channel <= plan["channels"]["last"]
        and band in plan["bands"]
    )


def _tacan(channel: int, band: str) -> tuple[float, float, float | None]:
    """(interrogation MHz, reply MHz, paired VHF MHz or None)."""
    plan = _plan()
    air = plan["interrogationMHz"]["base"] + channel - plan["channels"]["first"]
    reply = next(
        r for r in plan["replyOffsetMHz"][band] if r["from"] <= channel <= r["to"]
    )
    pairing = plan["vhfPairing"]
    hit = next((r for r in pairing["ranges"] if r["from"] <= channel <= r["to"]), None)
    vhf = None
    if hit is not None:
        khz = hit["baseKHz"] + (channel - hit["from"]) * pairing["stepKHz"]
        vhf = (khz + pairing["bandOffsetKHz"][band]) / 1000
    return float(air), float(air + reply["offset"]), vhf


def tacan_frequency(
    channel: int, band: TacanBand, role: Literal["air", "ground"]
) -> TacanFrequency:
    """Frequencies of TACAN/DME channel ``channel`` ``band`` for the airborne
    interrogator (``role`` ``air``: transmits the interrogation, receives the
    reply) or the ground beacon (``ground``: the other way round), from the
    ``tacan`` index (ICAO Annex 10 Table A; tools/datamine/overlays.yaml).
    Raises ``ValueError`` for a channel :func:`is_valid_tacan` rejects."""
    if not is_valid_tacan(channel, band):
        raise ValueError(f"no TACAN channel {channel}{band}")
    if role not in ("air", "ground"):
        raise ValueError(f"role must be air or ground, got {role!r}")
    air, reply, vhf = _tacan(int(channel), band)
    out: dict[str, float] = (
        {"txMHz": air, "rxMHz": reply}
        if role == "air"
        else {"txMHz": reply, "rxMHz": air}
    )
    if vhf is not None:
        out["pairedVhfMHz"] = vhf
    return cast(TacanFrequency, out)


FREQUENCY_TOLERANCE_MHZ: Final = 1e-6
"""Largest difference, MHz, at which :func:`tacan_channel` counts a match."""


def tacan_channel(
    mhz: float, role: Literal["air", "ground", "vhf"]
) -> list[TacanChannel]:
    """Every channel (sorted by channel, then band) whose ``role`` side
    transmits on ``mhz`` (``air``: the interrogation, which X and Y channels
    share; ``ground``: the reply) or, for ``vhf``, that pairs with VOR/ILS
    frequency ``mhz``. Empty when none does."""
    if role not in ("air", "ground", "vhf"):
        raise ValueError(f"role must be air, ground or vhf, got {role!r}")
    plan = _plan()
    out: list[TacanChannel] = []
    for ch in range(plan["channels"]["first"], plan["channels"]["last"] + 1):
        for band in plan["bands"]:
            air, reply, vhf = _tacan(ch, band)
            value = {"air": air, "ground": reply, "vhf": vhf}[role]
            if value is not None and abs(value - mhz) <= FREQUENCY_TOLERANCE_MHZ:
                out.append({"channel": ch, "band": band})
    return out


def _airbase(airbase_id: str) -> Record:
    return _record("airbases", airbase_id)


def _direction(airbase_id: str, designator: str) -> Record:
    """The runway direction whose ``designator`` is ``designator`` (as
    :func:`name_key`)."""
    key = name_key(designator)
    for rwy in _airbase(airbase_id).get("runways", []):
        for d in rwy["directions"]:
            if name_key(d["designator"]) == key:
                return cast(Record, d)
    raise KeyError(f"airbase {airbase_id} has no runway end {designator!r}")


def navaids_for(airbase_id: str, runway: str | None = None) -> list[str]:
    """``navaids`` ids (ILS/PRMG) of airbase ``airbase_id``, or of its runway
    end ``runway`` (a direction ``designator``, case-insensitive), sorted.
    Raises ``KeyError`` for an end the airbase lacks."""
    if runway is None:
        return sorted(_airbase(airbase_id).get("navaids", []))
    return sorted(_direction(airbase_id, runway).get("navaids", []))


# Runways and stands -----------------------------------------------------------------


class RunwayThreshold(TypedDict):
    lat: float
    lon: float
    elevationM: float


class RunwayEnd(TypedDict):
    runway: str
    """Designator pair of the runway (``13/31``)."""
    designator: str
    name: str
    """DCS's own name of the end."""
    trueDeg: float
    magDeg: float
    threshold: RunwayThreshold
    lengthM: float


class BestRunway(TypedDict):
    end: RunwayEnd
    headwindKt: float
    """Negative for a tailwind."""
    crosswindKt: float
    """Magnitude, from either side."""


class NearbyAirbase(TypedDict):
    id: str
    distNm: float
    bearingDeg: float
    """Initial true bearing from the given point to the reference point."""


def runway_ends(airbase_id: str) -> list[RunwayEnd]:
    """Every runway end (``runways[].directions[]``, in data order) of
    ``airbase_id``: bearings from its threshold along the runway, the
    threshold (the runway spawn point at that end) and the runway length.
    Empty for an airbase without runway data."""
    out: list[RunwayEnd] = []
    for rwy in _airbase(airbase_id).get("runways", []):
        for d in rwy["directions"]:
            t = d["threshold"]
            out.append(
                {
                    "runway": rwy["designator"],
                    "designator": d["designator"],
                    "name": d["name"],
                    "trueDeg": d["trueBearingDeg"],
                    "magDeg": d["magneticBearingDeg"],
                    "threshold": {
                        "lat": t["latitude"],
                        "lon": t["longitude"],
                        "elevationM": t["elevationM"],
                    },
                    "lengthM": rwy["lengthM"],
                }
            )
    return out


WIND_TOLERANCE_KT: Final = 1e-9
"""Wind components closer than this compare equal in :func:`best_runway`."""


def _better(a: BestRunway, b: BestRunway) -> bool:
    if abs(a["headwindKt"] - b["headwindKt"]) > WIND_TOLERANCE_KT:
        return a["headwindKt"] > b["headwindKt"]
    if abs(a["crosswindKt"] - b["crosswindKt"]) > WIND_TOLERANCE_KT:
        return a["crosswindKt"] < b["crosswindKt"]
    if a["end"]["lengthM"] != b["end"]["lengthM"]:
        return a["end"]["lengthM"] > b["end"]["lengthM"]
    return a["end"]["designator"] < b["end"]["designator"]


def best_runway(
    airbase_id: str, wind_from_deg_true: float, wind_kt: float
) -> BestRunway:
    """The runway end of ``airbase_id`` facing the wind (blowing from
    ``wind_from_deg_true`` at ``wind_kt``): headwind ``wind_kt * cos(from -
    trueDeg)``, crosswind ``|wind_kt * sin(from - trueDeg)|``. Most headwind
    wins; ties (within ``WIND_TOLERANCE_KT``, as in calm air) go to the least
    crosswind, then the longer runway, then the lower designator (string
    order). Raises ``ValueError`` for a negative wind or an airbase without
    runway data."""
    if not wind_kt >= 0:
        raise ValueError(f"wind speed must be >= 0 kt, got {wind_kt}")
    best: BestRunway | None = None
    for end in runway_ends(airbase_id):
        a = math.radians(wind_from_deg_true - end["trueDeg"])
        cand: BestRunway = {
            "end": end,
            "headwindKt": wind_kt * math.cos(a),
            "crosswindKt": abs(wind_kt * math.sin(a)),
        }
        if best is None or _better(cand, best):
            best = cand
    if best is None:
        raise ValueError(f"airbase {airbase_id} has no runway data")
    return best


NM_M: Final = 1852.0
"""Metres per international nautical mile."""


def nearest_airbases(
    theatre: str,
    lat: float,
    lon: float,
    *,
    min_runway_m: float | None = None,
    n: int = 5,
    category: str | None = None,
) -> list[NearbyAirbase]:
    """The ``n`` airbases of ``theatre`` (anything :func:`theatre_by_name`
    accepts) whose reference points lie nearest (lat, lon) by
    :func:`distance_bearing`, nearest first (ties by id). ``min_runway_m``
    keeps airbases whose ``longestRunwayM`` reaches it (those without runway
    data drop out); ``category`` keeps those of that ``categoryName``
    (case-insensitive, e.g. ``AIRDROME``)."""
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ValueError(f"n must be an integer of at least 1, got {n!r}")
    t = theatre_by_name(theatre)
    if t is None:
        raise KeyError(f"no theatre {theatre!r}")
    want = None if category is None else name_key(category)
    found = []
    for aid, ab in _series("airbases").items():
        p = ab.get("referencePoint")
        if ab["theatre"] != t["id"] or p is None:
            continue
        longest = ab.get("longestRunwayM", -1)
        if min_runway_m is not None and not longest >= min_runway_m:
            continue
        if want is not None and name_key(ab.get("categoryName", "")) != want:
            continue
        db = distance_bearing(lat, lon, p["latitude"], p["longitude"])
        found.append((db["distM"], aid, db["bearingDeg"]))
    found.sort()
    return [{"id": aid, "distNm": d / NM_M, "bearingDeg": b} for d, aid, b in found[:n]]


def stands_for(airbase_id: str, aircraft_id: str) -> list[int]:
    """``termIndex`` of every stand of ``airbase_id`` taking ``aircraft_id``,
    ascending, by the mission editor's rule (``Entity.StandLimits``): wing
    span (else rotor diameter) < ``maxWidthM``, length < ``maxLengthM``,
    height < ``maxHeightM`` (1000 when absent), and ``helicopters`` (rotary)
    or ``airplanes`` (fixed wing) true. Stands without ``limits`` are left
    out. Raises ``ValueError`` for an aircraft without those dimensions."""
    a = _record("aircraft", aircraft_id)
    dims = a.get("dimensions", {})
    width = dims.get("wingSpanM", dims.get("rotorDiameterM"))
    if width is None or "lengthM" not in dims or "heightM" not in dims:
        raise ValueError(f"aircraft {aircraft_id} lacks the dimensions stands check")
    use = "helicopters" if a["kind"] == "rotary" else "airplanes"
    return sorted(
        int(s["termIndex"])
        for s in _airbase(airbase_id).get("stands", [])
        if (lim := s.get("limits")) is not None
        and width < lim["maxWidthM"]
        and dims["lengthM"] < lim["maxLengthM"]
        and dims["heightM"] < lim.get("maxHeightM", 1000)
        and lim[use]
    )


# Countries, liveries and datalinks --------------------------------------------------

_COUNTRY_NAMES: Final = ("name", "shortName", "internationalName", "idName", "oldId")


def country_id(name_or_alias: str) -> int | None:
    """The id of the country whose name, shortName, internationalName, idName
    or oldId is ``name_or_alias`` (as :func:`name_key`), else of the
    ``countryAliases`` index entry (tools/datamine/overlays.yaml), else
    None."""
    key = name_key(name_or_alias)
    for c in _series("countries").values():
        if any(
            isinstance(c.get(f), str) and name_key(c[f]) == key for f in _COUNTRY_NAMES
        ):
            return int(c["id"])
    alias = cast(Mapping[str, int], _index("countryAliases")).get(key)
    return None if alias is None else int(alias)


def country_name(country_id: int) -> str:
    """DCS ``Name`` of country ``country_id``."""
    return cast(str, _record("countries", str(country_id))["name"])


def liveries_for(unit_type: str, country_id: int | None = None) -> list[str]:
    """Ids of the liveries of unit type ``unit_type`` (in their
    ``unitTypes``), sorted; with ``country_id``, those without ``countries``
    (offered to every country) or whose ``countries`` hold it. A country of
    the ``allLiveryCountries`` index (the Combined Joint Task Forces, as the
    mission editor's loadLiveries.lua treats them; tools/datamine/overlays.yaml)
    gets every livery of the unit type."""
    if _unit_series(unit_type) is None:
        raise KeyError(f"no unit type {unit_type!r}")
    if country_id is not None:
        _record("countries", str(country_id))
        if str(country_id) in cast(Mapping[str, str], _index("allLiveryCountries")):
            country_id = None
    return sorted(
        lid
        for lid, lv in _series("liveries").items()
        if unit_type in lv["unitTypes"]
        and (
            country_id is None or "countries" not in lv or country_id in lv["countries"]
        )
    )


class DatalinkCapability(TypedDict):
    datalinkType: str
    canBeLink16Donor: bool
    supportsTeamMembers: bool
    supportsCrossFlightTeam: bool
    maxDonors: float
    maxTeamMembers: float
    notes: NotRequired[str]


def datalink_capability(aircraft_id: str) -> DatalinkCapability | None:
    """The datalink record of aircraft ``aircraft_id`` (without ``id``), or
    None when it has none."""
    dl = _record("aircraft", aircraft_id).get("datalink")
    if dl is None:
        return None
    return cast(
        DatalinkCapability,
        {k: v for k, v in _record("datalink", dl).items() if k != "id"},
    )


# Geo ----------------------------------------------------------------------------------


class DistanceBearing(TypedDict):
    distM: float
    bearingDeg: float
    """Initial true bearing, [0, 360)."""


def _check_lat_lon(lat: float, lon: float) -> None:
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError(f"latitude {lat} / longitude {lon} out of range")


def _bearing(deg: float) -> float:
    if deg < 0:
        deg += 360
    if deg >= 360:
        deg -= 360
    return deg


def distance_bearing(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> DistanceBearing:
    """Great-circle distance (haversine) and initial bearing from point 1 to
    point 2 on a sphere of radius ``EARTH_RADIUS_M`` (within about 0.5 % of
    the WGS84 geodesic); bearing 0 for coincident points."""
    _check_lat_lon(lat1, lon1)
    _check_lat_lon(lat2, lon2)
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    dist = 2 * EARTH_RADIUS_M * math.asin(math.sqrt(min(1.0, a)))
    theta = math.atan2(
        math.sin(dl) * math.cos(p2),
        math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl),
    )
    return {"distM": dist, "bearingDeg": _bearing(math.degrees(theta))}


def destination(lat: float, lon: float, bearing_deg: float, dist_m: float) -> LatLon:
    """The point ``dist_m`` from (lat, lon) along initial true bearing
    ``bearing_deg`` on the sphere of :func:`distance_bearing`; longitude in
    [-180, 180)."""
    _check_lat_lon(lat, lon)
    lon2, lat2 = _destination(lat, lon, bearing_deg, dist_m)
    return {"lat": lat2, "lon": lon2}


CoordFormat = Literal["DD", "DMS", "DDM", "MGRS"]

_PRECISION: Final = {"DD": (6, 8), "DMS": (0, 4), "DDM": (3, 6), "MGRS": (5, 5)}
"""Format -> (default, largest) precision: decimals of the degrees, seconds
or minutes; MGRS digits per easting/northing."""


def _pad(n: int, width: int) -> str:
    return str(n).rjust(width, "0")


def _angle(value: float, fmt: str, precision: int, hemis: str) -> str:
    unit = 10**precision
    scale = {"DD": 1, "DDM": 60, "DMS": 3600}[fmt] * unit
    total = math.floor(abs(value) * scale + 0.5)
    hemi = hemis[1] if value < 0 and total > 0 else hemis[0]
    whole, frac = total // unit, total % unit
    tail = "." + _pad(frac, precision) if precision > 0 else ""
    if fmt == "DD":
        return f"{hemi} {whole}{tail}°"
    if fmt == "DDM":
        return f"{hemi} {whole // 60}°{_pad(whole % 60, 2)}{tail}'"
    return f"{hemi} {whole // 3600}°{_pad(whole // 60 % 60, 2)}'{_pad(whole % 60, 2)}{tail}\""


# UTM/MGRS (WGS84): the Transverse Mercator above with k0 0.9996, false
# easting 500 km and false northing 10000 km south of the equator.
_UTM_K0: Final = 0.9996
_BANDS: Final = "CDEFGHJKLMNPQRSTUVWX"
_COLUMNS: Final = ("ABCDEFGH", "JKLMNPQR", "STUVWXYZ")
_ROWS: Final = "ABCDEFGHJKLMNPQRSTUV"


def _utm(zone: int, south: bool) -> dict[str, float]:
    return {
        "centralMeridian": zone * 6 - 183,
        "scaleFactor": _UTM_K0,
        "falseEasting": 500000.0,
        "falseNorthing": 10000000.0 if south else 0.0,
    }


def _band_lat(band: str) -> tuple[float, float]:
    south = -80 + 8 * _BANDS.index(band)
    return south, 84.0 if band == "X" else south + 8


def _mgrs(lat: float, lon: float, precision: int) -> str:
    if not -80 <= lat <= 84:
        raise ValueError(f"MGRS covers latitudes -80 to 84 (UTM), got {lat}")
    zone = min(math.floor((lon + 180) / 6) + 1, 60)
    band = _BANDS[min(math.floor((lat + 80) / 8), 19)]
    if band == "V" and zone == 31 and lon >= 3:
        zone = 32
    elif band == "X" and 0 <= lon < 42:
        zone = 31 if lon < 9 else 33 if lon < 21 else 35 if lon < 33 else 37
    n, e = _to_map(_utm(zone, lat < 0), lat, lon)
    col = math.floor(e / 100000)
    row = (math.floor(n / 100000) + (5 if zone % 2 == 0 else 0)) % 20
    letters = f"{zone} {band} {_COLUMNS[(zone - 1) % 3][col - 1]}{_ROWS[row]}"
    if precision == 0:
        return letters
    div = 10 ** (5 - precision)
    de = math.floor(e) % 100000 // div
    dn = math.floor(n) % 100000 // div
    return f"{letters} {_pad(de, precision)} {_pad(dn, precision)}"


def format_coord(
    lat: float, lon: float, fmt: CoordFormat, precision: int | None = None
) -> str:
    """(lat, lon) as the DCS mission editor writes it, without the ``Label:``
    prefix it copies: ``DMS`` ``N 29°32'03"   E 52°35'55"`` (``precision``
    decimals of the seconds, default 0; 2 is its "Lat Long Precise"),
    ``DDM`` ``N 29°32.296'   E 52°35.179'`` (minutes' decimals, default 3),
    ``DD`` ``N 29.534312°   E 52.598839°`` (degrees' decimals, default 6;
    not an editor format) and ``MGRS`` ``39 R XN 54929 68251`` (digits per
    easting/northing, 0-5, default 5, truncated as MGRS is). Values round
    half up; degrees are not padded."""
    if fmt not in _PRECISION:
        raise ValueError(f"format must be one of {', '.join(_PRECISION)}, got {fmt!r}")
    default, most = _PRECISION[fmt]
    p = default if precision is None else precision
    if isinstance(p, bool) or not isinstance(p, int) or not 0 <= p <= most:
        raise ValueError(f"{fmt} precision must be an integer 0-{most}, got {p!r}")
    _check_lat_lon(lat, lon)
    if fmt == "MGRS":
        return _mgrs(lat, lon, p)
    return f"{_angle(lat, fmt, p, 'NS')}   {_angle(lon, fmt, p, 'EW')}"


class ParsedCoord(TypedDict):
    format: Literal["DD", "DMS", "DDM", "MGRS", "METRIC"]
    lat: NotRequired[float]
    lon: NotRequired[float]
    x: NotRequired[float]
    """``METRIC``: DCS map metres north."""
    z: NotRequired[float]
    """``METRIC``: DCS map metres east."""


def _tokens(text: str) -> list[tuple[str, str]]:
    """(kind, text) tokens: ``num`` (sign, digits, optional decimals),
    ``word`` (letters), ``mark`` (``*`` for the degree sign, ``'``, ``"``);
    blanks and commas separate. Upper-cased, after the first colon."""
    s = text.split(":", 1)[1] if ":" in text else text
    s = s.replace("°", "*")
    if not s.isascii():
        raise ValueError(f"unexpected non-ASCII text in {text!r}")
    s = s.upper()
    out: list[tuple[str, str]] = []
    i = 0
    while i < len(s):
        c = s[i]
        if c in " \t,":
            i += 1
        elif c in "*'\"":
            out.append(("mark", c))
            i += 1
        elif "A" <= c <= "Z":
            j = i
            while j < len(s) and "A" <= s[j] <= "Z":
                j += 1
            out.append(("word", s[i:j]))
            i = j
        elif c in "+-" or "0" <= c <= "9":
            j = i + 1 if c in "+-" else i
            k = j
            while k < len(s) and "0" <= s[k] <= "9":
                k += 1
            if k == j:
                raise ValueError(f"bad number in {text!r}")
            if k < len(s) and s[k] == ".":
                m = k + 1
                while m < len(s) and "0" <= s[m] <= "9":
                    m += 1
                if m == k + 1:
                    raise ValueError(f"bad number in {text!r}")
                k = m
            out.append(("num", s[i:k]))
            i = k
        else:
            raise ValueError(f"unexpected {c!r} in {text!r}")
    return out


def _unsigned(token: tuple[str, str]) -> bool:
    return token[0] == "num" and all("0" <= c <= "9" for c in token[1])


def _parse_mgrs(tokens: list[tuple[str, str]], text: str) -> ParsedCoord:
    zone = int(tokens[0][1])
    i, letters = 1, ""
    while i < len(tokens) and tokens[i][0] == "word":
        letters += tokens[i][1]
        i += 1
    rest = tokens[i:]
    if len(letters) != 3 or len(rest) > 2 or not all(_unsigned(t) for t in rest):
        raise ValueError(f"not an MGRS reference: {text!r}")
    if len(rest) == 2:
        es, ns = rest[0][1], rest[1][1]
    elif len(rest) == 1:
        half = len(rest[0][1]) // 2
        es, ns = rest[0][1][:half], rest[0][1][half:]
    else:
        es = ns = ""
    if len(es) != len(ns) or len(es) > 5:
        raise ValueError(f"MGRS easting and northing need 0-5 digits each: {text!r}")
    band, col, row = letters[0], letters[1], letters[2]
    columns = _COLUMNS[(zone - 1) % 3]
    if band not in _BANDS or col not in columns or row not in _ROWS:
        raise ValueError(f"bad MGRS letters {letters} for zone {zone}: {text!r}")
    size = 10 ** (5 - len(es))
    e = (columns.index(col) + 1) * 100000 + (int(es or "0") + 0.5) * size
    n = ((_ROWS.index(row) - (5 if zone % 2 == 0 else 0)) % 20) * 100000 + (
        int(ns or "0") + 0.5
    ) * size
    lo, hi = _band_lat(band)
    p = _utm(zone, lo < 0)
    mid, _ = _to_map(p, (lo + hi) / 2, p["centralMeridian"])
    n += math.floor((mid - n) / 2000000 + 0.5) * 2000000
    ll = _inverse(p, n, e)
    if not lo - 0.5 <= ll["lat"] <= hi + 0.5:
        raise ValueError(f"MGRS square {col}{row} is not in band {band}: {text!r}")
    return {"format": "MGRS", "lat": ll["lat"], "lon": ll["lon"]}


def _parse_half(
    tokens: list[tuple[str, str]], i: int, hemis: str, text: str
) -> tuple[float, int, int]:
    """(signed degrees, component count, next index) of ``H d [m [s]]``."""
    if (
        i >= len(tokens)
        or tokens[i][0] != "word"
        or tokens[i][1] not in (hemis[0], hemis[1])
    ):
        raise ValueError(f"expected {hemis[0]} or {hemis[1]} in {text!r}")
    sign = -1 if tokens[i][1] == hemis[1] else 1
    i += 1
    parts: list[str] = []
    while i < len(tokens) and tokens[i][0] == "num" and len(parts) < 3:
        if not all(c == "." or "0" <= c <= "9" for c in tokens[i][1]):
            raise ValueError(f"signed angle component in {text!r}")
        parts.append(tokens[i][1])
        i += 1
        if i < len(tokens) and tokens[i][0] == "mark":
            if tokens[i][1] != "*'\""[len(parts) - 1]:
                raise ValueError(f"misplaced {tokens[i][1]} in {text!r}")
            i += 1
    if not parts:
        raise ValueError(f"no angle after {hemis[0]}/{hemis[1]} in {text!r}")
    if any("." in p for p in parts[:-1]):
        raise ValueError(f"only the last component may have decimals: {text!r}")
    values = [float(p) for p in parts]
    if any(v >= 60 for v in values[1:]):
        raise ValueError(f"minutes and seconds must be below 60: {text!r}")
    deg = values[0]
    if len(values) > 1:
        deg += values[1] / 60
    if len(values) > 2:
        deg += values[2] / 3600
    return sign * deg, len(parts), i


def parse_coord(text: str) -> ParsedCoord:
    """A coordinate in any DCS mission editor copy format, with or without
    its ``Label:`` prefix (the text up to the first colon is dropped):
    ``Metric: X+00380826 Z-00352108`` (``METRIC``, map metres ``x``/``z``),
    ``N 29°32'03"   E 52°35'55"`` and ``N 29°32'03.53"   E 52°35'55.82"``
    (``DMS``), ``N 29°32.296'   E 52°35.179'`` (``DDM``), ``39 R XN 54929
    68251`` (``MGRS``: the centre of the square, so formatting it again at
    the same precision gives the same text), and ``N 29.5343°   E 52.5988°``
    or a signed ``29.5343, 52.5988`` (``DD``). Case, spacing and the ``°``
    ``'`` ``"`` marks are loose; anything else raises ``ValueError``."""
    tokens = _tokens(text)
    kinds = [k for k, _ in tokens]
    words = [v for k, v in tokens if k == "word"]
    if kinds == ["word", "num", "word", "num"] and words == ["X", "Z"]:
        return {"format": "METRIC", "x": float(tokens[1][1]), "z": float(tokens[3][1])}
    if (
        kinds[:2] == ["num", "word"]
        and _unsigned(tokens[0])
        and len(tokens[0][1]) <= 2
        and 1 <= int(tokens[0][1]) <= 60
    ):
        return _parse_mgrs(tokens, text)
    fmt: Literal["DD", "DMS", "DDM"]
    if kinds == ["num", "num"]:
        lat, lon, fmt = float(tokens[0][1]), float(tokens[1][1]), "DD"
    else:
        lat, n_lat, i = _parse_half(tokens, 0, "NS", text)
        lon, n_lon, i = _parse_half(tokens, i, "EW", text)
        if i != len(tokens) or n_lat != n_lon:
            raise ValueError(f"latitude and longitude need the same form: {text!r}")
        fmt = "DD" if n_lat == 1 else "DDM" if n_lat == 2 else "DMS"
    _check_lat_lon(lat, lon)
    return {"format": fmt, "lat": lat, "lon": lon}
