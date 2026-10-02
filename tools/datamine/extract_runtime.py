"""Merge the per-terrain runtime dumps (``.datamine/terrains/<theatre>.lua``,
written by ``hook/terrain-dump.lua``) into the theatre and airbase records.

A dump whose ``dcsVersion`` is not the extracted version is ignored (warned);
a terrain without a dump gets no runtime fields.

Rules (DCS values; derived values say how):

* An airdrome is merged when the terrain config (``GetTerrainConfig('Airdromes')``,
  keyed by airdrome id) and ``world.getAirbases()`` (``getID()``) both list it;
  an airbase with runways or parking and no config airdrome fails, as does a
  config whose ``display_name`` (else ``names.en``, else ``id``) is not the
  airbase's name. ``name`` is ``getName()``; ``category``/``categoryName`` are
  ``getDesc().category`` and its ``Airbase.Category`` key; ``referencePoint`` is
  the config's ``reference_point`` with ``land.getHeight`` (the field
  elevation) and ``coord.LOtoLL``; ``magneticVariation`` is ``magvar.get_mag_decl`` there at
  the mission date (1 January of the build year).
* Runways: each ``Terrain.getRunwayList`` entry with edge points is paired with
  the ``getRunways()`` entry whose centre is nearest (mutually, within
  ``RUNWAY_MATCH_M``) on the same axis (within ``RUNWAY_AXIS_TOL_DEG``);
  anything unpaired fails. ``getRunways()`` ``course`` is minus the true
  bearing. Edge ``k`` is the threshold of ``edge<k>name``; its direction's true
  bearing is the great-circle bearing from that edge to the other one (from
  their ``coord.LOtoLL``; map x is grid north), the magnetic bearing that
  minus the variation. ``lengthM`` is the edge-to-edge distance; the edges are the
  runway spawn points, inside the drawn runway ends.
  ``getRunways()`` entry k reports the length, width and Name of runway k // 2
  (DCS bug), so only its position and course are used, for pairing; runways
  carry no width. Designators (``_designators``):
  DCS's two ``edge<k>name`` go on the ends whose magnetic bearing they match
  better (``name``, verbatim); an end keeps its name when the number is
  within ``NAME_TOL`` of round(magnetic / 10) (0 -> 36), else takes that
  number; DCS L/C/R suffixes are kept, and suffixless ends sharing a number
  within a parallel group get L/C/R by lateral position. Swaps and
  differences are reported. Threshold elevation is ``land.getHeight`` at the
  edge; TDZE is the highest ``land.getHeight`` sample
  (every <= 10 m along the edge-to-edge centreline) within ``TDZ_M`` of the
  threshold. ``getRunways()`` entries without a runway list fail.
* An ILS/PRMG navaid of the airbase serves the runway direction whose grid
  bearing (map x is grid north) is within ``NAVAID_TOL_DEG`` of its localizer
  ``direction`` + 180
  (a DCS localizer's ``direction`` points back along the approach); the navaid
  records ``runwayDirection`` and ``runwayBearingDeltaDeg``. Several fitting
  directions (parallel runways) resolve to the one whose far end is nearest
  the localizer by at least ``PARALLEL_MARGIN_M``; otherwise it is not linked.
* Stands are ``getParking()`` spots (``Term_Index``, ``Term_Type``,
  ``vTerminalPos``), joined to ``Terrain.getStandList`` stands by
  ``Term_Index == crossroad_index`` when every such pair lies within
  ``STAND_MATCH_M``; otherwise by mutual nearest position within it. The stand
  list gives the name (``name``) and limits (``params``). A spot that joins
  no listed stand must lie on a runway threshold (within ``STAND_MATCH_M``):
  DCS's runway take-off positions (``Term_Type`` 16 in DCS 2.9.29), which
  the stand list does not describe; it records ``runwayEnd``. A terrain whose
  ``standDescriptionVersion`` is neither nil (every terrain in DCS 2.9.29) nor
  2 fails: version 1 stands carry a ``flag`` instead of params.
* Projection: a terrain without beacons is fitted (``tmerc``) to the dump's
  ``coord.LOtoLL`` grid, with the same gates as the beacon fit.

Rounding: map metres to 3 decimals, latitude/longitude to 7, heights and
lengths to 2, bearings and variation to 4.
"""

from __future__ import annotations

import itertools
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .common import fail, read_text, warn
from .lua_reader import lua_to_py, sandbox_exec
from .tmerc import angle_diff

RUNWAY_MATCH_M = 100.0
RUNWAY_AXIS_TOL_DEG = 5.0
# Parallel runways laterally this close are one lane (collinear segments).
LANE_M = 50.0
NAVAID_TOL_DEG = 10.0
STAND_MATCH_M = 2.0
# Parallel runway directions: the localizer must be this much nearer one's far end.
PARALLEL_MARGIN_M = 50.0
# A DCS end name within this many numbers of the geometry is kept (chart lag).
NAME_TOL = 3
TDZ_M = 914.4  # 3000 ft
MAGVAR_SOURCE = "magvar.get_mag_decl"

_NAME = re.compile(r"^0*(\d{1,2})([LCR]?)$")


@dataclass
class Report:
    """Report lines, plus per-theatre tallies summarised by ``summary``."""

    lines: list[str] = field(default_factory=list)
    counts: Counter[str] = field(default_factory=Counter)

    def add(self, line: str) -> None:
        self.lines.append(line)

    def summary(self, theatre: str) -> None:
        c = self.counts
        self.add(
            f"{theatre}: {c['airbases']} airbases, {c['runways']} runways "
            f"({c['swapped']} with DCS end names swapped, {c['mismatches']} ends "
            f"designated otherwise than DCS), {c['stands']} stands ({c['joined']} joined to the stand list, "
            f"join basis {dict(sorted((k[6:], v) for k, v in c.items() if k.startswith('basis:')))}, "
            f"{c['runway_ends']} runway-end spots, "
            f"{c['unlisted']} listed stands with no parking spot), "
            f"{c['navaid_links']} navaid-runway links"
        )
        self.counts = Counter()


def load(terrains_dir: Path | None, version: str) -> dict[str, dict[str, Any]]:
    """``{theatre: dump}`` of the dumps for ``version`` in ``terrains_dir``."""
    out: dict[str, dict[str, Any]] = {}
    if terrains_dir is None or not terrains_dir.is_dir():
        return out
    for path in sorted(terrains_dir.glob("*.lua")):
        ok, env = sandbox_exec(read_text(path), str(path))
        if not ok:
            fail(f"{path}: {env}")
        dump = lua_to_py(env["terrain"])
        if not isinstance(dump, dict):
            fail(f"{path}: no `terrain` table")
        if dump.get("theatre") != path.stem:
            fail(f"{path}: dump is for theatre {dump.get('theatre')!r}")
        if dump.get("dcsVersion") != version:
            warn(
                f"{path}: runtime dump of DCS {dump.get('dcsVersion')}, extracting "
                f"{version}; ignored (task datamine re-runs it)"
            )
            continue
        out[path.stem] = dump
    return out


# --- small helpers -----------------------------------------------------------


def _norm(deg: float) -> float:
    return deg % 360.0


def _bearing(x1: float, z1: float, x2: float, z2: float) -> float:
    """True bearing (degrees) from map point 1 to 2 (x north, z east)."""
    return _norm(math.degrees(math.atan2(z2 - z1, x2 - x1)))


def _true_bearing(p: dict[str, Any], q: dict[str, Any]) -> float:
    """Initial great-circle bearing from sample p to q. Map x is grid north,
    not true north (TM convergence reaches several degrees)."""
    f1, f2 = math.radians(p["lat"]), math.radians(q["lat"])
    dl = math.radians(q["lon"] - p["lon"])
    y = math.sin(dl) * math.cos(f2)
    x = math.cos(f1) * math.sin(f2) - math.sin(f1) * math.cos(f2) * math.cos(dl)
    return _norm(math.degrees(math.atan2(y, x)))


def _entries(value: Any) -> list[Any]:
    """A dumped Lua array (list, or dict with numeric string keys when holes)."""
    if value is None or value == {}:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict) and all(k.isdigit() for k in value):
        top = max(int(k) for k in value)
        return [value.get(str(i)) for i in range(1, top + 1)]
    fail(f"runtime dump: expected an array, got {type(value).__name__}")


def _num(value: Any, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail(f"runtime dump: {what} is not a number ({value!r})")
    return value


def _r(value: float, digits: int) -> float | int:
    v = round(value, digits)
    return int(v) if v == int(v) else v


def _map_point(sample: dict[str, Any], elevation: bool = True) -> dict[str, Any]:
    p = {
        "x": _r(_num(sample.get("x"), "sample x"), 3),
        "z": _r(_num(sample.get("z"), "sample z"), 3),
        "latitude": _r(_num(sample.get("lat"), "sample lat"), 7),
        "longitude": _r(_num(sample.get("lon"), "sample lon"), 7),
    }
    if elevation:
        p["elevationM"] = _r(_num(sample.get("h"), "sample h"), 2)
    return p


def _parse(name: str) -> tuple[int, str] | None:
    """(number, suffix) of a DCS end name, None unless 1-36 with L/C/R or none."""
    m = _NAME.match(name.strip().upper())
    return (int(m.group(1)), m.group(2)) if m and 1 <= int(m.group(1)) <= 36 else None


def _normalise_name(name: str) -> str:
    """DCS end name in designator form ("7" -> "07", "3r" -> "03R")."""
    p = _parse(name)
    return f"{p[0]:02d}{p[1]}" if p else name.strip().upper()


def _number(mag: float) -> int:
    n = math.floor(_norm(mag) / 10 + 0.5) % 36
    return n or 36


def _circular_mean(degs: list[float]) -> float:
    s = sum(math.sin(math.radians(d)) for d in degs)
    c = sum(math.cos(math.radians(d)) for d in degs)
    return _norm(math.degrees(math.atan2(s, c)))


def tdze(heights: list[float], spacing: float, from_start: bool) -> float:
    """Highest sample within ``TDZ_M`` of the line's start (or end)."""
    n = len(heights)
    if n == 0 or spacing <= 0:
        fail("runtime dump: empty runway profile")
    last = min(n - 1, math.floor(TDZ_M / spacing + 1e-9))
    window = heights[: last + 1] if from_start else heights[n - 1 - last :]
    return max(window)


# --- runways ------------------------------------------------------------------


def _direction(
    designator: str,
    dcs_name: str,
    threshold: dict[str, Any],
    true_deg: float,
    var: float,
    tdze_m: float,
) -> dict[str, Any]:
    d: dict[str, Any] = {
        "designator": designator,
        "name": dcs_name,
        "trueBearingDeg": _r(true_deg, 4),
        "magneticBearingDeg": _r(_norm(true_deg - var), 4),
        "threshold": _map_point(threshold),
        "tdzeM": _r(tdze_m, 2),
    }
    if _normalise_name(dcs_name) != designator:
        d["designatorMismatch"] = True
    return d


def _pair_designator(a: str, b: str) -> str:
    return f"{a}/{b}" if a[:2] <= b[:2] else f"{b}/{a}"


def _mission_axis(r: dict[str, Any]) -> float:
    return _norm(-math.degrees(_num(r.get("course"), "runway course")))


def _line_axis(line: dict[str, Any]) -> float:
    return _bearing(
        line["from"]["x"], line["from"]["z"], line["to"]["x"], line["to"]["z"]
    )


def _centre(line: dict[str, Any]) -> tuple[float, float]:
    return (
        (line["from"]["x"] + line["to"]["x"]) / 2,
        (line["from"]["z"] + line["to"]["z"]) / 2,
    )


def _parallel(a: float, b: float) -> bool:
    d = angle_diff(a, b)
    return min(d, 180 - d) <= RUNWAY_AXIS_TOL_DEG


def _lateral(t: float, line: dict[str, Any]) -> float:
    """The line centre's offset to the right of travel along bearing ``t`` (rad)."""
    x, z = _centre(line)
    return -math.sin(t) * x + math.cos(t) * z


def _check_runway_pairs(
    where: str,
    listed: list[tuple[dict[str, Any], dict[str, Any]]],
    mission: list[dict[str, Any]],
) -> None:
    """Fail unless the listed runways and the ``getRunways()`` entries pair
    one-to-one by mutually nearest centre on the same axis."""

    def centre_b(r: dict[str, Any]) -> tuple[float, float]:
        p = r.get("position") or {}
        return _num(p.get("x"), "runway x"), _num(p.get("z"), "runway z")

    def axis_ok(line: dict[str, Any], r: dict[str, Any]) -> bool:
        return _parallel(_line_axis(line), _mission_axis(r))

    def dist(line: dict[str, Any], r: dict[str, Any]) -> float:
        return math.dist(_centre(line), centre_b(r))

    used: set[int] = set()
    for entry, line in listed:
        cands = [(dist(line, r), j) for j, r in enumerate(mission) if axis_ok(line, r)]
        if not cands:
            fail(
                f"{where}: runway {entry.get('edge1name')}/{entry.get('edge2name')} "
                f"(edge axis {_line_axis(line):.1f}) has no getRunways() entry on its axis; "
                f"getRunways() axes (-course): {[round(_mission_axis(r), 1) for r in mission]}"
            )
        d, j = min(cands)
        back = min(
            (dist(ln, mission[j]), i)
            for i, (_, ln) in enumerate(listed)
            if axis_ok(ln, mission[j])
        )
        if d > RUNWAY_MATCH_M or listed[back[1]][1] is not line or j in used:
            fail(
                f"{where}: runway {entry.get('edge1name')}/{entry.get('edge2name')} does not pair "
                f"one-to-one with a getRunways() entry within {RUNWAY_MATCH_M:g} m (nearest {d:.1f} m)"
            )
        used.add(j)
    if len(used) != len(mission):
        fail(
            f"{where}: {len(mission) - len(used)} getRunways() entries pair with no runway list entry"
        )


def _chunks(n: int) -> list[int]:
    """Sizes of the L/R and L/C/R sets ``n`` parallel runways split into."""
    k = math.ceil(n / 3)
    return [n // k + (i < n % k) for i in range(k)]


def _groups(axes: list[float]) -> list[list[int]]:
    """Parallel groups: runways whose axes are within ``RUNWAY_AXIS_TOL_DEG``."""
    groups: list[list[int]] = []
    for i, a in enumerate(axes):
        hit = [g for g in groups if any(_parallel(a, axes[k]) for k in g)]
        merged = [i] + [k for g in hit for k in g]
        groups = [g for g in groups if g not in hit] + [sorted(merged)]
    return groups


def _geometry_designators(
    lines: list[dict[str, Any]], groups: list[list[int]], var: float
) -> list[tuple[str, str]]:
    """Geometry designators (edge1 end, edge2 end) of each runway line.

    A parallel group is numbered by its mean magnetic bearing. Seen travelling
    along the group's end with magnetic bearing below 180, its runways ordered
    left to right by lateral offset get L/R or L/C/R; more than three split
    into consecutive sets of two or three (larger first) numbered N, N+1, ...
    (FAA practice, for example 08L/08R/09L/09R). The reciprocal end is the same
    runway's number + 18 with the suffix mirrored."""
    axes = [_line_axis(ln) for ln in lines]
    trues = [_true_bearing(ln["from"], ln["to"]) for ln in lines]
    out: list[list[str]] = [["", ""] for _ in lines]
    mirror = {"": "", "L": "R", "C": "C", "R": "L"}
    for g in groups:
        ref = axes[g[0]]
        flip = {k: angle_diff(axes[k], ref) > 90 for k in g}
        fwd = _circular_mean([_norm(axes[k] + 180 * flip[k]) for k in g])
        mag = _norm(_circular_mean([_norm(trues[k] + 180 * flip[k]) for k in g]) - var)
        if mag >= 180:
            fwd, mag = _norm(fwd + 180), mag - 180
            flip = {k: not f for k, f in flip.items()}
        base = _number(mag)
        t = math.radians(fwd)
        ordered = sorted(g, key=lambda k: _lateral(t, lines[k]))
        pos = 0
        for n, size in enumerate(_chunks(len(g))):
            number = (base + n - 1) % 36 + 1
            suffixes = {1: [""], 2: ["L", "R"], 3: ["L", "C", "R"]}[size]
            for k, suffix in zip(ordered[pos : pos + size], suffixes, strict=True):
                # edge1 -> edge2 runs along fwd unless flipped.
                ends = (
                    f"{number:02d}{suffix}",
                    f"{(number + 17) % 36 + 1:02d}{mirror[suffix]}",
                )
                out[k] = list(ends[::-1] if flip[k] else ends)
            pos += size
    return [(a, b) for a, b in out]


def _num_delta(a: int, b: int) -> int:
    d = abs(a - b) % 36
    return min(d, 36 - d)


@dataclass
class Designation:
    """A runway's end designators and DCS names, edge1 end first."""

    designators: tuple[str, str]
    dcs_names: tuple[str, str]
    swapped: bool


def _designators(
    lines: list[dict[str, Any]], names: list[tuple[str, str]], var: float
) -> list[Designation]:
    """DCS's end names placed on the ends they match, kept where plausible.

    Each name goes on the end whose magnetic bearing it matches better. An end
    keeps its name's number within ``NAME_TOL`` of round(magnetic / 10)
    (charts lag the drifting variation), else takes that geometric number; a
    DCS L/C/R suffix is kept either way. A suffixless end sharing its number
    with another runway of its parallel group gets L/R or L/C/R by lateral
    position among those runways, collinear ones (within ``LANE_M``) sharing a
    letter; in groups of more than three it takes the whole geometric
    designator."""
    axes = [_line_axis(ln) for ln in lines]
    groups = _groups(axes)
    geo = _geometry_designators(lines, groups, var)
    group_of = {k: g for g in groups for k in g}
    mags = [
        (
            _norm(_true_bearing(ln["from"], ln["to"]) - var),
            _norm(_true_bearing(ln["to"], ln["from"]) - var),
        )
        for ln in lines
    ]

    def cost(name: str, mag: float) -> float:
        p = _parse(name)
        return angle_diff(p[0] * 10, mag) if p else 0.0

    placed: list[tuple[str, str]] = []
    swapped: list[bool] = []
    ends: list[list[tuple[int, str]]] = []
    for (n1, n2), (m1, m2) in zip(names, mags, strict=True):
        swap = cost(n2, m1) + cost(n1, m2) < cost(n1, m1) + cost(n2, m2)
        pair = (n2, n1) if swap else (n1, n2)
        placed.append(pair)
        swapped.append(swap)
        row = []
        for name, mag in zip(pair, (m1, m2), strict=True):
            p, g = _parse(name), _number(mag)
            row.append(
                (p[0], p[1])
                if p and _num_delta(p[0], g) <= NAME_TOL
                else (g, p[1] if p else "")
            )
        ends.append(row)
    out = []
    for k, row in enumerate(ends):
        des = []
        for e, (number, suffix) in enumerate(row):
            same = [j for j in group_of[k] if any(n == number for n, _ in ends[j])]
            if not suffix and len(same) > 1:
                if len(group_of[k]) > 3:
                    des.append(geo[k][e])
                    continue
                # Left to right along this end's direction of travel; collinear
                # segments (Abu Dhabi's 13/31 is two) share a lane.
                t = math.radians(axes[k] + 180 * e)
                offs = sorted((_lateral(t, lines[j]), j) for j in same)
                lane, lanes = {offs[0][1]: 0}, 0
                for (prev, _), (off, j) in itertools.pairwise(offs):
                    lanes += off - prev > LANE_M
                    lane[j] = lanes
                suffix = ("", "LR", "LCR")[lanes][lane[k]] if lanes else ""
            des.append(f"{number:02d}{suffix}")
        out.append(Designation((des[0], des[1]), placed[k], swapped[k]))
    return out


def _runway(
    line: dict[str, Any],
    des: Designation,
    var: float,
) -> dict[str, Any]:
    designators, names = des.designators, des.dcs_names
    a, b = line["from"], line["to"]
    heights = [_num(h, "profile height") for h in _entries(line.get("heights"))]
    spacing = _num(line.get("spacingM"), "profile spacing")
    dirs = [
        _direction(
            designators[k],
            names[k],
            thr,
            true_deg,
            var,
            tdze(heights, spacing, k == 0),
        )
        for k, (thr, true_deg) in enumerate(
            ((a, _true_bearing(a, b)), (b, _true_bearing(b, a)))
        )
    ]
    rw: dict[str, Any] = {
        "designator": _pair_designator(*designators),
        "lengthM": _r(math.dist((a["x"], a["z"]), (b["x"], b["z"])), 2),
    }
    rw["directions"] = dirs
    return rw


# --- stands -------------------------------------------------------------------


def _stand_limits(stand: dict[str, Any]) -> dict[str, Any] | None:
    """``StandLimits`` from a ``getStandList`` entry's ``params``."""
    params = stand.get("params")
    if not isinstance(params, dict):
        return None
    num = {}
    for k, v in params.items():
        if k == "HEIGHT" and v == "":  # no height limit (Caucasus, PersianGulf)
            continue
        try:
            num[k] = float(v)
        except (TypeError, ValueError):
            fail(f"stand {stand.get('name')}: param {k}={v!r} is not a number")
    if (
        not {"WIDTH", "LENGTH", "SHELTER", "FOR_HELICOPTERS", "FOR_AIRPLANES"}
        <= num.keys()
    ):
        fail(f"stand {stand.get('name')}: params {sorted(num)} lack a size or use flag")
    limits: dict[str, Any] = {
        "maxWidthM": _r(num["WIDTH"], 2),
        "maxLengthM": _r(num["LENGTH"], 2),
        "shelter": num["SHELTER"] != 0,
        "helicopters": num["FOR_HELICOPTERS"] != 0,
        "airplanes": num["FOR_AIRPLANES"] != 0,
    }
    if "HEIGHT" in num:
        limits["maxHeightM"] = _r(num["HEIGHT"], 2)
    return limits


def join_stands(
    stands: list[dict[str, Any]], parking: list[dict[str, Any]]
) -> tuple[dict[int, dict[str, Any]], str]:
    """``{parking index: stand}`` and the join basis (``index`` or ``position``)."""

    def spos(s: dict[str, Any]) -> tuple[float, float]:
        return _num(s.get("x"), "stand x"), _num(s.get("y"), "stand y")

    def ppos(p: dict[str, Any]) -> tuple[float, float]:
        v = p.get("vTerminalPos") or {}
        return _num(v.get("x"), "parking x"), _num(v.get("z"), "parking z")

    by_index = {s.get("crossroad_index"): s for s in stands}
    joined = {
        i: by_index[p.get("Term_Index")]
        for i, p in enumerate(parking)
        if p.get("Term_Index") in by_index
    }
    if joined and all(
        math.dist(spos(s), ppos(parking[i])) <= STAND_MATCH_M for i, s in joined.items()
    ):
        return joined, "index"
    joined = {}
    for i, p in enumerate(parking):
        d, j = min(
            ((math.dist(spos(s), ppos(p)), j) for j, s in enumerate(stands)),
            default=(math.inf, -1),
        )
        if d > STAND_MATCH_M:
            continue
        back = min(math.dist(spos(stands[j]), ppos(q)) for q in parking)
        if back == d:
            joined[i] = stands[j]
    return joined, "position"


def _runway_end(
    where: str, pos: tuple[float, float], runways: list[dict[str, Any]]
) -> str | None:
    """Designator of the runway threshold ``pos`` lies on (within ``STAND_MATCH_M``)."""
    ends = {
        d["designator"]
        for r in runways
        for d in r["directions"]
        if math.dist(pos, (d["threshold"]["x"], d["threshold"]["z"])) <= STAND_MATCH_M
    }
    if len(ends) > 1:
        fail(f"{where}: parking spot at {pos} lies on runway ends {sorted(ends)}")
    return next(iter(ends), None)


def _stands(
    where: str,
    dump_ab: dict[str, Any],
    cfg: dict[str, Any],
    runways: list[dict[str, Any]],
    report: Report,
) -> list[dict[str, Any]]:
    parking = [p for p in _entries(dump_ab.get("parking")) if isinstance(p, dict)]
    geo = _entries(dump_ab.get("parkingGeo"))
    stands = [s for s in _entries(cfg.get("stands")) if isinstance(s, dict)]
    joined, basis = join_stands(stands, parking)
    out = []
    for i, p in enumerate(parking):
        v = p.get("vTerminalPos") or {}
        g = geo[i] if i < len(geo) else None
        if not isinstance(g, dict):
            fail(f"{where}: parking {p.get('Term_Index')} has no coord.LOtoLL sample")
        rec: dict[str, Any] = {
            "termIndex": int(_num(p.get("Term_Index"), "Term_Index")),
            "termType": int(_num(p.get("Term_Type"), "Term_Type")),
            "position": _map_point(
                {
                    "x": v.get("x"),
                    "z": v.get("z"),
                    "lat": g.get("lat"),
                    "lon": g.get("lon"),
                },
                elevation=False,
            ),
        }
        stand = joined.get(i)
        if stand is not None:
            if isinstance(stand.get("name"), (str, int, float)):
                rec["name"] = str(stand["name"])
            limits = _stand_limits(stand)
            if limits is None:
                fail(f"{where}: stand {stand.get('name')} has no params")
            rec["limits"] = limits
        else:
            end = _runway_end(
                where, (rec["position"]["x"], rec["position"]["z"]), runways
            )
            if end is None:
                fail(
                    f"{where}: parking {rec['termIndex']} (Term_Type {rec['termType']}) "
                    "joins no listed stand and lies on no runway end"
                )
            rec["runwayEnd"] = end
            report.counts["runway_ends"] += 1
        out.append(rec)
    out.sort(key=lambda r: r["termIndex"])
    report.counts["stands"] += len(out)
    report.counts["joined"] += len(joined)
    report.counts[f"basis:{basis}"] += 1
    report.counts["unlisted"] += len(stands) - len(joined)
    return out


# --- merge --------------------------------------------------------------------


def _link_navaids(
    base_id: str,
    runways: list[dict[str, Any]],
    navaids: dict[str, dict[str, Any]],
    beacons: dict[str, dict[str, Any]],
    report: Report,
) -> None:
    for nid, nav in sorted(navaids.items()):
        if nav["airbase"] != base_id:
            continue
        loc = beacons[nav["equipment"][0]]
        course = _norm(loc["direction"] + 180)
        pos = (loc["position"]["x"], loc["position"]["z"])
        fits = []
        for r in runways:
            for k, d in enumerate(r["directions"]):
                near, far = d["threshold"], r["directions"][1 - k]["threshold"]
                # A localizer's direction is in the map grid, like the edges.
                delta = angle_diff(
                    course, _bearing(near["x"], near["z"], far["x"], far["z"])
                )
                if delta <= NAVAID_TOL_DEG:
                    fits.append((math.dist((far["x"], far["z"]), pos), delta, d))
        fits.sort(key=lambda f: f[0])
        if not fits or (len(fits) > 1 and fits[1][0] - fits[0][0] < PARALLEL_MARGIN_M):
            report.add(
                f"{nid}: {len(fits)} runway directions within {NAVAID_TOL_DEG:g} deg "
                f"of {course:.1f}; not linked"
            )
            continue
        _, delta, direction = fits[0]
        direction.setdefault("navaids", []).append(nid)
        report.counts["navaid_links"] += 1
        nav["runwayDirection"] = direction["designator"]
        nav["runwayBearingDeltaDeg"] = _r(delta, 4)


def _config_name(config: dict[str, Any]) -> Any:
    """The airdrome's name in its terrain config: display_name, else names.en, else id."""
    return (
        config.get("display_name")
        or (config.get("names") or {}).get("en")
        or config.get("id")
    )


def merge(
    series: dict[str, dict[str, dict[str, Any]]],
    dumps: dict[str, dict[str, Any]],
) -> list[str]:
    """Merge ``dumps`` into ``series`` (theatres/airbases/navaids); report lines."""
    report = Report()
    airbases = series["airbases"]
    for theatre, dump in sorted(dumps.items()):
        if theatre not in series["theatres"]:
            fail(f"runtime dump for unknown theatre {theatre}")
        mv = dump.get("magvar") or {}
        if mv.get("source") != MAGVAR_SOURCE:
            fail(f"{theatre}: runtime dump magvar source {mv.get('source')!r}")
        date = f"{int(_num(mv.get('year'), 'magvar year')):04d}-{int(_num(mv.get('month'), 'magvar month')):02d}"
        categories = {v: k for k, v in (dump.get("airbaseCategories") or {}).items()}
        configs = dump.get("airdromes") or {}
        if isinstance(configs, list):  # ids 1..n read back as an array
            configs = {str(i): c for i, c in enumerate(configs, 1)}
        sdv = dump.get("standDescriptionVersion")
        if sdv not in (None, 2):
            fail(f"{theatre}: standDescriptionVersion {sdv!r}; only nil and 2 are read")
        unmatched = []
        for ab in _entries(dump.get("airbases")):
            aid = int(_num(ab.get("id"), "airbase id"))
            cfg = configs.get(str(aid))
            if cfg is None:
                if _entries(ab.get("runways")) or _entries(ab.get("parking")):
                    fail(
                        f"{theatre}: getAirbases() entry {ab.get('name')} ({aid}) has "
                        "runways or parking but no terrain config airdrome"
                    )
                unmatched.append(f"{ab.get('name')} ({aid})")
                continue
            base_id = f"{theatre}.{aid}"
            where = f"{base_id} {ab.get('name')}"
            config_name = _config_name(cfg.get("config") or {})
            if config_name != ab.get("name"):
                fail(f"{where}: terrain config airdrome {aid} is {config_name!r}")
            rec = airbases.setdefault(
                base_id, {"id": base_id, "theatre": theatre, "airdromeId": aid}
            )
            rec["name"] = str(ab.get("name"))
            cat = (ab.get("desc") or {}).get("category")
            if isinstance(cat, (int, float)):
                rec["category"] = int(cat)
                if int(cat) not in categories:
                    fail(
                        f"{where}: category {cat} is not in Airbase.Category {categories}"
                    )
                rec["categoryName"] = categories[int(cat)]
            var = None
            ref = cfg.get("reference")
            if isinstance(ref, dict):
                rec["referencePoint"] = _map_point(ref)
                var = math.degrees(_num(ref.get("magDeclRad"), "magDeclRad"))
                rec["magneticVariation"] = {
                    "degrees": _r(var, 4),
                    "date": date,
                    "source": MAGVAR_SOURCE,
                }
            runways = _runways(where, ab, cfg, var, report)
            if runways:
                rec["runways"] = runways
                rec["longestRunwayM"] = max(r["lengthM"] for r in runways)
                report.counts["runways"] += len(runways)
                _link_navaids(
                    base_id, runways, series["navaids"], series["beacons"], report
                )
            stands = _stands(where, ab, cfg, runways, report)
            if stands:
                rec["stands"] = stands
            report.counts["airbases"] += 1
        if unmatched:
            report.add(
                f"{theatre}: getAirbases() entries with no terrain config airdrome: {unmatched}"
            )
        report.summary(theatre)
    return report.lines


def _runways(
    where: str,
    ab: dict[str, Any],
    cfg: dict[str, Any],
    var: float | None,
    report: Report,
) -> list[dict[str, Any]]:
    mission = [r for r in _entries(ab.get("runways")) if isinstance(r, dict)]
    listed_raw = _entries(cfg.get("runwayList"))
    if not listed_raw:
        if mission:
            fail(f"{where}: getRunways() entries but no Terrain.getRunwayList")
        return []
    if var is None:
        fail(f"{where}: runways without a reference point to take variation at")
    listed = []
    for entry, line in zip(listed_raw, _entries(cfg.get("edges")), strict=True):
        if not isinstance(line, dict) or line.get("missing"):
            fail(f"{where}: runway list entry without edge points: {entry}")
        listed.append((entry, line))
    _check_runway_pairs(where, listed, mission)
    designations = _designators(
        [ln for _, ln in listed],
        [(str(e.get("edge1name")), str(e.get("edge2name"))) for e, _ in listed],
        var,
    )
    out = []
    for (entry, line), des in zip(listed, designations, strict=True):
        rw = _runway(line, des, var)
        if des.swapped:
            report.add(
                f"{where}: DCS runway {entry.get('edge1name')}/{entry.get('edge2name')} "
                f"names each other's end; placed as {rw['designator']}"
            )
            report.counts["swapped"] += 1
        for d in rw["directions"]:
            if d.get("designatorMismatch"):
                report.add(
                    f"{where}: runway end {d['name']} designated {d['designator']} "
                    f"(magnetic {d['magneticBearingDeg']:.1f})"
                )
                report.counts["mismatches"] += 1
        out.append(rw)
    out.sort(key=lambda r: r["designator"])
    return out
