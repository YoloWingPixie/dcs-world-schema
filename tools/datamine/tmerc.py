"""Transverse Mercator on WGS84 and a least-squares fit of its parameters.

DCS map coordinates are metres with ``x`` north and ``z`` east of the map
origin. A terrain's projection is recovered from points DCS gives in both map
and geographic coordinates: ``z = falseEasting + E``, ``x = falseNorthing + N``
with ``(E, N)`` the Transverse Mercator (latitude of origin 0) of the point.
The latitude of origin is fixed at 0 because it trades exactly against
``falseNorthing``.

Forward: Krueger series to order n^6 (Karney 2011, "Transverse Mercator with
an accuracy of a few nanometers"), sub-millimetre within 3900 km of the central
meridian. For a fixed central meridian the scale factor and false offsets are
linear least squares; the central meridian is a 1-D minimisation (grid then
golden section) of the RMS residual.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

A = 6378137.0
F = 1 / 298.257223563
_N = F / (2 - F)
_E = math.sqrt(F * (2 - F))
_A_RECT = A / (1 + _N) * (1 + _N**2 / 4 + _N**4 / 64 + _N**6 / 256)
_n = _N
_ALPHA = (
    _n / 2
    - 2 / 3 * _n**2
    + 5 / 16 * _n**3
    + 41 / 180 * _n**4
    - 127 / 288 * _n**5
    + 7891 / 37800 * _n**6,
    13 / 48 * _n**2
    - 3 / 5 * _n**3
    + 557 / 1440 * _n**4
    + 281 / 630 * _n**5
    - 1983433 / 1935360 * _n**6,
    61 / 240 * _n**3
    - 103 / 140 * _n**4
    + 15061 / 26880 * _n**5
    + 167603 / 181440 * _n**6,
    49561 / 161280 * _n**4 - 179 / 168 * _n**5 + 6601661 / 7257600 * _n**6,
    34729 / 80640 * _n**5 - 3418889 / 1995840 * _n**6,
    212378941 / 319334400 * _n**6,
)


def angle_diff(a: float, b: float) -> float:
    """Smallest difference between two bearings, degrees."""
    d = abs(a - b) % 360
    return min(d, 360 - d)


@dataclass(frozen=True)
class Projection:
    central_meridian: float  # degrees
    scale_factor: float
    false_easting: float  # metres, added to E to give map z
    false_northing: float  # metres, added to N to give map x

    def to_map(self, lat: float, lon: float) -> tuple[float, float]:
        """(x, z) map metres of a WGS84 latitude/longitude in degrees."""
        e, n = tm_unscaled(lat, lon - self.central_meridian)
        k = self.scale_factor
        return self.false_northing + k * n, self.false_easting + k * e

    def to_geo(self, x: float, z: float) -> tuple[float, float]:
        """(latitude, longitude) degrees of map (x, z), by Newton iteration on
        ``to_map`` (converges to well under a millimetre)."""
        k = self.scale_factor
        lat, lon = 0.0, self.central_meridian
        for _ in range(50):
            px, pz = self.to_map(lat, lon)
            dx, dz = x - px, z - pz
            if abs(dx) < 1e-6 and abs(dz) < 1e-6:
                break
            h = 1e-6
            x1, z1 = self.to_map(lat + h, lon)
            x2, z2 = self.to_map(lat, lon + h)
            a, b = (x1 - px) / h, (x2 - px) / h
            c, d = (z1 - pz) / h, (z2 - pz) / h
            det = a * d - b * c
            lat += (d * dx - b * dz) / det
            lon += (a * dz - c * dx) / det
        else:
            raise ArithmeticError(f"to_geo did not converge for ({x}, {z}) k={k}")
        return lat, lon


def tm_unscaled(lat: float, dlon: float) -> tuple[float, float]:
    """(E, N) metres at unit scale, latitude of origin 0, ``dlon`` degrees
    from the central meridian."""
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


@dataclass(frozen=True)
class Fit:
    projection: Projection
    points: int
    rms_m: float
    max_m: float


# (x, z, latitude, longitude)
Point = tuple[float, float, float, float]


def _solve(points: Sequence[Point], lon0: float) -> tuple[Projection, list[float]]:
    """Least-squares scale and offsets for a fixed central meridian, and the
    per-point horizontal residuals in metres."""
    en = [tm_unscaled(lat, lon - lon0) for _, _, lat, lon in points]
    m = len(points)
    me = sum(e for e, _ in en) / m
    mn = sum(n for _, n in en) / m
    mz = sum(p[1] for p in points) / m
    mx = sum(p[0] for p in points) / m
    num = sum(
        (e - me) * (p[1] - mz) + (n - mn) * (p[0] - mx)
        for (e, n), p in zip(en, points, strict=True)
    )
    den = sum((e - me) ** 2 + (n - mn) ** 2 for e, n in en)
    k = num / den
    proj = Projection(lon0, k, mz - k * me, mx - k * mn)
    res = [
        math.hypot(
            p[0] - proj.false_northing - k * n, p[1] - proj.false_easting - k * e
        )
        for (e, n), p in zip(en, points, strict=True)
    ]
    return proj, res


def _rms(res: list[float]) -> float:
    return math.sqrt(sum(r * r for r in res) / len(res))


def fit(points: Sequence[Point]) -> Fit:
    """Fit a Transverse Mercator to ``points``; needs at least 3 distinct."""
    if len(points) < 3:
        raise ValueError(f"need at least 3 points, got {len(points)}")
    mean_lon = sum(p[3] for p in points) / len(points)

    def cost(lon0: float) -> float:
        return _rms(_solve(points, lon0)[1])

    grid = [mean_lon + d / 4 for d in range(-80, 81)]  # +-20 deg, 0.25 deg steps
    best = min(grid, key=cost)
    lo, hi = best - 0.25, best + 0.25
    g = (math.sqrt(5) - 1) / 2
    c, d = hi - g * (hi - lo), lo + g * (hi - lo)
    fc, fd = cost(c), cost(d)
    while hi - lo > 1e-10:
        if fc < fd:
            hi, d, fd = d, c, fc
            c = hi - g * (hi - lo)
            fc = cost(c)
        else:
            lo, c, fc = c, d, fd
            d = lo + g * (hi - lo)
            fd = cost(d)
    proj, res = _solve(points, (lo + hi) / 2)
    return Fit(proj, len(points), _rms(res), max(res))
