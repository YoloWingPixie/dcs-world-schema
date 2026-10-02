"""Extract ``Entity.Theatre``, ``Entity.Beacon``, ``Entity.Navaid`` and
``Entity.Airbase`` records from every installed terrain's plain-Lua files
(``Mods/terrains/<dir>/entry.lua``, ``Beacons.lua``, ``Radio.lua``; see
``terrain_lua``). ``terrain.cfg.lua`` is encrypted and not read.

Rules (from DCS's own data unless they name an overlay table):

* Theatre id is ``entry.lua``'s plugin ``id`` (the mission's ``theatre``).
  The map projection is a Transverse Mercator fitted (``tmerc``) to every
  beacon's map ``position`` (x north, z east) against its ``positionGeo``; the
  fit fails the extraction unless it has at least ``MIN_POINTS`` points
  spanning ``MIN_SPAN_KM`` with a max residual under ``MAX_RESIDUAL_M``. A
  terrain that ships no beacons is fitted, under the same gates, to its
  runtime dump's ``coord.LOtoLL`` grid (``runtime_projections``); without
  one it gets no projection (warned). Its ``aliases`` come from the
  ``theatres/aliases`` overlay table (``apply_aliases``).
* Beacon/navaid-equipment ids are ``<theatre>.<beaconId>``: ``beaconId`` is
  unique only within a terrain (checked). A ``beaconId``/``radioId`` of the
  form ``airfield<N>_<k>`` belongs to airbase ``N``, the DCS airdrome id
  (``Airbase:getID()``, a mission's ``airdromeId``); every such beacon group
  must lie within ``MAX_AIRBASE_SPREAD_KM``.
* An airbase exists for every ``N`` either file names; its id is
  ``<theatre>.<N>``. ``Radio.lua`` entries become its services; each DCS
  ``role`` maps to a communication type code through the
  ``airbases/serviceTypes`` overlay table (``hand-authored``). A role the
  table lacks, or a table role no service has, stops the extraction.
* A navaid groups equipment only where DCS pairs it: exactly one
  ILS localizer and one ILS glideslope of one airbase on the same
  ``frequency`` (DCS keys the glideslope by the localizer frequency), or one
  PRMG localizer and glideslope of one airbase on the same ``channel``
  (``grouping`` is that key). When one airbase has n > 1 of each on one
  frequency/channel (both ends of a runway), each localizer pairs with the
  glideslope whose ``direction`` is closest, accepted only when that is mutual
  one-to-one and every pair is within ``DIRECTION_TOLERANCE_DEG``
  (``grouping: direction``); otherwise they stay standalone (warned).
  Everything else stays standalone equipment.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from . import tmerc
from .common import HAND_AUTHORED, fail, warn
from .dcs_constants import Constants
from .lua_reader import as_dict, lua_to_py
from .overlays import Overlays, unused_keys
from .terrain_lua import (
    BANDS_SCRIPT,
    BEACON_SITES_SCRIPT,
    BEACON_TYPES_SCRIPT,
    MODULATION_SCRIPT,
    TerrainFiles,
    TerrainLua,
)

TERRAINS_DIR = "Mods/terrains"
MIN_POINTS = 10
MIN_SPAN_KM = 50.0
MAX_RESIDUAL_M = 1.0
MAX_AIRBASE_SPREAD_KM = 50.0
# Localizer/glideslope `direction` agreement for direction pairing. In 2.9.29
# same-end pairs differ by at most 4.1 deg; opposite runway ends by ~180 deg.
DIRECTION_TOLERANCE_DEG = 10.0

BEACON_TYPE = "Entity.BeaconType"
MODULATION_TYPE = "Entity.RadioModulationType"
FREQUENCY_BAND = "Entity.FrequencyBand"

_AIRFIELD = re.compile(r"^airfield(\d+)_(\d+)$")
_PAIRS = (
    # (navaid type, localizer, glideslope, pairing key)
    ("ILS", "BEACON_TYPE_ILS_LOCALIZER", "BEACON_TYPE_ILS_GLIDESLOPE", "frequency"),
    ("PRMG", "BEACON_TYPE_PRMG_LOCALIZER", "BEACON_TYPE_PRMG_GLIDESLOPE", "channel"),
)


def _airfield(dcs_id: str) -> int | None:
    m = _AIRFIELD.match(dcs_id)
    return int(m.group(1)) if m else None


def _hz(value: float) -> int | float:
    """A DCS frequency (a float in the files) as an int when whole."""
    return int(value) if value == int(value) else value


def _fit(t: TerrainFiles, theatre: str) -> dict[str, Any] | None:
    points = [
        (b["position"][0], b["position"][2], b["_geo"][0], b["_geo"][1])
        for b in t.beacons
    ]
    if not points:
        return None
    return _fit_points(points, theatre, "beacon")


def _fit_points(points: list[tmerc.Point], theatre: str, what: str) -> dict[str, Any]:
    span = max(math.dist(p[:2], q[:2]) for p in points for q in points) / 1000
    if len(points) < MIN_POINTS or span < MIN_SPAN_KM:
        fail(
            f"theatre {theatre}: {len(points)} {what} points spanning {span:.1f} km; "
            f"need {MIN_POINTS} spanning {MIN_SPAN_KM:g} km for a projection fit"
        )
    f = tmerc.fit(points)
    if f.max_m > MAX_RESIDUAL_M:
        fail(
            f"theatre {theatre}: projection fit max residual {f.max_m:.3f} m "
            f"(rms {f.rms_m:.3f} m) exceeds {MAX_RESIDUAL_M} m"
        )
    p = f.projection
    # Rounded to what 6-decimal positionGeo resolves (~0.1 m).
    proj = tmerc.Projection(
        round(p.central_meridian, 6),
        round(p.scale_factor, 8),
        round(p.false_easting, 2),
        round(p.false_northing, 2),
    )
    lat, lon = proj.to_geo(0.0, 0.0)
    return {
        "projection": {
            "method": "TransverseMercator",
            "ellipsoid": "WGS84",
            "latitudeOfOrigin": 0,
            "centralMeridian": proj.central_meridian,
            "scaleFactor": proj.scale_factor,
            "falseEasting": proj.false_easting,
            "falseNorthing": proj.false_northing,
            "fit": {
                "points": f.points,
                "spanKm": round(span, 1),
                "rmsResidualM": round(f.rms_m, 3),
                "maxResidualM": round(f.max_m, 3),
            },
        },
        "datum": {"latitude": round(lat, 7), "longitude": round(lon, 7)},
    }


def _grid_points(dump: dict[str, Any], theatre: str) -> list[tmerc.Point]:
    grid = dump.get("grid") or []
    if not isinstance(grid, list):
        fail(f"theatre {theatre}: runtime dump grid is not a list")
    points = []
    for g in grid:
        try:
            points.append(
                (float(g["x"]), float(g["z"]), float(g["lat"]), float(g["lon"]))
            )
        except (KeyError, TypeError, ValueError):
            fail(f"theatre {theatre}: runtime dump grid point {g!r}")
    return points


def runtime_projections(
    theatres: dict[str, dict[str, Any]], dumps: dict[str, dict[str, Any]]
) -> list[str]:
    """Fit a projection to the runtime ``coord.LOtoLL`` grid of every theatre
    without a beacon fit; for beacon-fitted theatres, report the largest
    distance between the beacon projection and the grid. Report lines."""
    report = []
    for theatre, rec in sorted(theatres.items()):
        dump = dumps.get(theatre)
        if dump is None:
            if "projection" not in rec:
                warn(
                    f"theatre {theatre}: no beacons and no runtime dump, so no projection"
                )
            continue
        points = _grid_points(dump, theatre)
        if "projection" in rec:
            p = rec["projection"]
            proj = tmerc.Projection(
                p["centralMeridian"],
                p["scaleFactor"],
                p["falseEasting"],
                p["falseNorthing"],
            )
            worst = max(
                (math.dist(proj.to_map(lat, lon), (x, z)) for x, z, lat, lon in points),
                default=math.nan,
            )
            report.append(
                f"{theatre:18s} beacon fit vs coord.LOtoLL grid (n={len(points)}): "
                f"max {worst:.3f} m"
            )
            continue
        fitted = _fit_points(points, theatre, "coord.LOtoLL grid")
        fitted["projection"]["fit"]["source"] = "coord.LOtoLL"
        rec.update(fitted)
        fit = fitted["projection"]["fit"]
        report.append(
            f"{theatre:18s} grid fit n={fit['points']} rms={fit['rmsResidualM']} m "
            f"max={fit['maxResidualM']} m; datum {fitted['datum']}"
        )
    return report


def _beacon(
    raw: dict[str, Any], theatre: str, constants: Constants
) -> dict[str, Any] | None:
    bid = raw["beaconId"]
    rec: dict[str, Any] = {
        "id": f"{theatre}.{bid}",
        "beaconId": bid,
        "theatre": theatre,
    }
    if not constants.set_pair(rec, "type", BEACON_TYPE, raw.get("type")):
        warn(
            f"{theatre} beacon {bid}: DCS gives no known type ({raw.get('type')!r}); skipped"
        )
        return None
    pos = raw["position"]
    lat, lon = raw["_geo"]
    rec.update(
        position={"x": pos[0], "y": pos[1], "z": pos[2]},
        latitude=lat,
        longitude=lon,
        direction=raw["direction"],
    )
    if raw.get("display_name"):
        rec["displayName"] = raw["display_name"]
    if raw.get("callsign"):
        rec["callsign"] = raw["callsign"]
    if raw.get("frequency") is not None:
        rec["frequencyHz"] = _hz(raw["frequency"])
    if raw.get("channel") is not None:
        rec["channel"] = raw["channel"]
    if (n := _airfield(bid)) is not None:
        rec["airbase"] = f"{theatre}.{n}"
    return rec


def _check_geo(t: TerrainFiles, theatre: str) -> None:
    for b in t.beacons:
        geo, pos = b.get("positionGeo"), b.get("position")
        if not (isinstance(geo, dict) and isinstance(pos, list) and len(pos) == 3):
            fail(f"{theatre} beacon {b.get('beaconId')}: no position/positionGeo")
        b["_geo"] = (geo["latitude"], geo["longitude"])
    ids = Counter(b["beaconId"] for b in t.beacons)
    if dup := sorted(i for i, c in ids.items() if c > 1):
        fail(f"{theatre}: duplicate beaconIds {dup}")


def _by_direction(
    locs: list[dict[str, Any]], gss: list[dict[str, Any]]
) -> list[tuple[dict[str, Any], dict[str, Any]]] | None:
    """Mutual-nearest ``direction`` pairs, or None unless one-to-one and all
    within ``DIRECTION_TOLERANCE_DEG``."""
    if len(locs) != len(gss):
        return None

    def nearest(b: dict[str, Any], pool: list[dict[str, Any]]) -> dict[str, Any]:
        return min(
            pool,
            key=lambda o: (tmerc.angle_diff(b["direction"], o["direction"]), o["id"]),
        )

    pairs = [(loc, nearest(loc, gss)) for loc in locs]
    if len({gs["id"] for _, gs in pairs}) != len(gss):
        return None
    for loc, gs in pairs:
        if nearest(gs, locs) is not loc:
            return None
        if (
            tmerc.angle_diff(loc["direction"], gs["direction"])
            > DIRECTION_TOLERANCE_DEG
        ):
            return None
    return pairs


def _navaids(beacons: list[dict[str, Any]], theatre: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for kind, loc_t, gs_t, key in _PAIRS:
        groups: dict[tuple[str, Any], dict[str, list[dict[str, Any]]]] = {}
        field = "frequencyHz" if key == "frequency" else key
        for b in beacons:
            if b["typeName"] in (loc_t, gs_t) and "airbase" in b and field in b:
                group = groups.setdefault(
                    (b["airbase"], b[field]), {loc_t: [], gs_t: []}
                )
                group[b["typeName"]].append(b)
        for (airbase, value), parts in sorted(groups.items(), key=str):
            locs, gss = parts[loc_t], parts[gs_t]
            if not locs or not gss:
                continue
            pairs: list[tuple[dict[str, Any], dict[str, Any]]] | None
            if len(locs) == 1 and len(gss) == 1:
                pairs, grouping = [(locs[0], gss[0])], key
            else:
                pairs, grouping = _by_direction(locs, gss), "direction"
                if pairs is None:
                    warn(
                        f"{airbase} {kind} {field}={value}: {len(locs)} localizer(s) "
                        f"and {len(gss)} glideslope(s) do not pair one-to-one by "
                        f"direction within {DIRECTION_TOLERANCE_DEG:g} deg; left standalone"
                    )
                    continue
            for loc, gs in pairs:
                nid = f"{theatre}.{kind}.{loc['beaconId']}"
                rec = {
                    "id": nid,
                    "theatre": theatre,
                    "airbase": airbase,
                    "type": kind,
                    "equipment": [loc["id"], gs["id"]],
                    "grouping": grouping,
                    "directionDeltaDeg": round(
                        tmerc.angle_diff(loc["direction"], gs["direction"]), 6
                    ),
                    field: value,
                }
                if "callsign" in loc:
                    rec["callsign"] = loc["callsign"]
                out[nid] = rec
    return out


def _service(
    raw: dict[str, Any], constants: Constants, service_types: dict[str, str], where: str
) -> dict[str, Any]:
    """``service_types``: the ``airbases/serviceTypes`` overlay table."""
    roles = [r for r in raw.get("role") or [] if isinstance(r, str)]
    unknown = sorted(set(roles) - service_types.keys())
    if unknown:
        fail(
            f"{where}: unknown radio role(s) {unknown}; "
            "extend overlays.yaml airbases/serviceTypes"
        )
    rec: dict[str, Any] = {
        "radioId": raw["radioId"],
        "roles": roles,
        "serviceTypes": [service_types[r] for r in roles],
        "_source": {"serviceTypes": HAND_AUTHORED},
    }
    callsigns = []
    for entry in raw.get("callsign") or []:
        for faction, names in sorted((entry or {}).items()):
            name = names[-1] if isinstance(names, list) and names else names
            if not isinstance(name, str):
                fail(f"{where}: callsign {faction!r} is not a string")
            callsigns.append({"faction": faction, "callsign": name})
    if callsigns:
        rec["callsigns"] = callsigns
    channels = []
    for ch in raw["frequency"]:
        c: dict[str, Any] = {}
        if not (
            constants.set_pair(c, "band", FREQUENCY_BAND, ch.get("band"))
            and constants.set_pair(
                c, "modulation", MODULATION_TYPE, ch.get("modulation")
            )
        ) or not isinstance(ch.get("hz"), (int, float)):
            fail(f"{where}: unresolvable radio frequency entry {ch}")
        c["frequencyHz"] = _hz(ch["hz"])
        channels.append(c)
    if channels:
        rec["channels"] = channels
    return rec


def _terrain_dirs(install_dir: Path) -> list[Path]:
    root = install_dir / TERRAINS_DIR
    dirs = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name)
    if not dirs:
        fail(f"no terrains under {root}")
    return dirs


def _theatre_id(plugin: dict[str, Any], d: Path) -> str:
    theatre = plugin.get("id")
    if not isinstance(theatre, str) or not theatre:
        fail(f"{d}/entry.lua declares no plugin id")
    return theatre


def installed_theatres(install_dir: Path) -> list[str]:
    """Theatre ids of the installed terrains, in directory order."""
    lua = TerrainLua(install_dir)
    return [_theatre_id(lua.plugin(d), d) for d in _terrain_dirs(install_dir)]


def build(
    install_dir: Path, constants: Constants, overlays: Overlays
) -> tuple[dict[str, dict[str, dict[str, Any]]], list[str]]:
    """(``{series: records}`` for theatres/beacons/navaids/airbases, report lines)."""
    service_types = overlays.table("airbases", "serviceTypes")
    lua = TerrainLua(install_dir)
    dirs = _terrain_dirs(install_dir)
    theatres: dict[str, Any] = {}
    beacons: dict[str, Any] = {}
    navaids: dict[str, Any] = {}
    airbases: dict[str, Any] = {}
    report: list[str] = []
    for d in dirs:
        t = lua.terrain(d)
        theatre = _theatre_id(t.plugin, d)
        if theatre in theatres:
            fail(f"theatre id {theatre} declared by two terrains")
        _check_geo(t, theatre)
        rec: dict[str, Any] = {"id": theatre, "directory": d.name}
        if isinstance(t.plugin.get("localizedName"), str):
            rec["displayName"] = t.plugin["localizedName"]
        fitted = _fit(t, theatre)
        if fitted:
            rec.update(fitted)
            fit = fitted["projection"]["fit"]
            report.append(
                f"{theatre:18s} fit n={fit['points']} rms={fit['rmsResidualM']} m "
                f"max={fit['maxResidualM']} m; datum {fitted['datum']}"
            )
        theatres[theatre] = rec

        mine = [b for raw in t.beacons if (b := _beacon(raw, theatre, constants))]
        by_base: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for b in mine:
            beacons[b["id"]] = b
            if "airbase" in b:
                by_base[b["airbase"]].append(b)
        for base, bs in by_base.items():
            spread = max(
                math.dist(
                    (p["position"]["x"], p["position"]["z"]),
                    (q["position"]["x"], q["position"]["z"]),
                )
                for p in bs
                for q in bs
            )
            if spread > MAX_AIRBASE_SPREAD_KM * 1000:
                fail(f"airbase {base}: its beacons spread {spread / 1000:.1f} km")
        mine_navaids = _navaids(mine, theatre)
        navaids.update(mine_navaids)

        services: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for raw in t.radio:
            rid = raw.get("radioId")
            n = _airfield(rid) if isinstance(rid, str) else None
            if n is None:
                warn(f"{theatre} radio {rid!r}: not an airfield<N>_<k> id; skipped")
                continue
            base = f"{theatre}.{n}"
            services[base].append(
                _service(raw, constants, service_types, f"{theatre} radio {rid}")
            )
        for base in sorted(set(services) | set(by_base)):
            ab: dict[str, Any] = {
                "id": base,
                "theatre": theatre,
                "airdromeId": int(base.rsplit(".", 1)[1]),
            }
            if services.get(base):
                ab["services"] = sorted(services[base], key=lambda s: s["radioId"])
            if by_base.get(base):
                ab["beacons"] = sorted(b["id"] for b in by_base[base])
            linked = sorted(k for k, v in mine_navaids.items() if v["airbase"] == base)
            if linked:
                ab["navaids"] = linked
            airbases[base] = ab
    unused_keys(
        service_types,
        {
            r
            for ab in airbases.values()
            for s in ab.get("services", [])
            for r in s["roles"]
        },
        "overlays airbases/serviceTypes",
    )
    apply_aliases(theatres, overlays.table("theatres", "aliases"))
    return (
        {
            "theatres": theatres,
            "beacons": beacons,
            "navaids": navaids,
            "airbases": airbases,
        },
        report,
    )


def _name_key(name: str) -> str:
    """The package helpers' name key: trimmed, ASCII letters lowercased."""
    return name.strip(" \t\n\r\f\v").translate(
        str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
    )


def apply_aliases(theatres: dict[str, dict[str, Any]], table: dict[str, Any]) -> None:
    """Set each theatre's ``aliases`` from the ``theatres/aliases`` overlay
    table (stamped hand-authored). Fails on an alias naming a theatre's id,
    displayName or directory, or shared by two theatres; skips (warns) entries
    for theatres not extracted."""
    owner: dict[str, str] = {}
    for tid, rec in theatres.items():
        for name in (rec["id"], rec.get("displayName"), rec["directory"]):
            if isinstance(name, str):
                owner.setdefault(_name_key(name), tid)
    for tid, aliases in sorted(table.items()):
        if tid not in theatres:
            warn(f"overlays theatres/aliases: no theatre {tid!r}; skipped")
            continue
        if not isinstance(aliases, list) or not all(
            isinstance(a, str) and _name_key(a) for a in aliases
        ):
            fail(f"overlays theatres/aliases {tid}: needs a list of names")
        for alias in aliases:
            key = _name_key(alias)
            if key in owner:
                fail(
                    f"overlays theatres/aliases {tid}: {alias!r} already names "
                    f"theatre {owner[key]}"
                )
            owner[key] = tid
        rec = theatres[tid]
        rec["aliases"] = list(aliases)
        rec.setdefault("_source", {})["aliases"] = HAND_AUTHORED


def install_constants(install_dir: Path) -> dict[str, dict[str, int]]:
    """The beacon-type, beacon-system, modulation-type and band constants of
    the install scripts."""
    lua = TerrainLua(install_dir)
    beacon = {
        k: v
        for k, v in lua.constants(BEACON_TYPES_SCRIPT).items()
        if k.startswith("BEACON_TYPE_")
    }
    modulation = {
        k: v
        for k, v in lua.constants(MODULATION_SCRIPT).items()
        if k.startswith("MODULATIONTYPE_")
    }
    bands = lua.constants(BANDS_SCRIPT)
    systems = {
        str(k): int(v)
        for k, v in as_dict(
            lua_to_py(lua.run(lua.install_dir / BEACON_SITES_SCRIPT)["SystemName"])
        ).items()
    }
    for name, fam in (
        ("BEACON_TYPE_", beacon),
        ("MODULATIONTYPE_", modulation),
        ("SystemName.", systems),
    ):
        if not fam:
            fail(f"install defines no {name}* constants")
    return {
        "BEACON_TYPE": beacon,
        "SystemName": systems,
        "MODULATIONTYPE": modulation,
        "FrequencyBand": bands,
    }
