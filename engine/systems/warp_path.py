"""In-system warp planner: path, speed policy and body drop-out (pure).

Spec: docs/superpowers/specs/2026-09-25-in-system-warp-design.md, section 1
("Path", "Speed policy", "Body drop-out") and "Tunables". Everything here is
plain math on ``(x, y, z)`` tuples in **system coordinates** (GU); no engine
imports, so the planner is testable on its own and the callers (the warp
flight, the dashes) own every engine-side decision.

The tunables are the spec's starting values and are each named once, here.

Path construction (a design choice; the spec fixes only the properties):

* Unobstructed -- the straight line keeps every body's COMFORT keep-out
  (``radius + comfort_gu(radius)``) -- the path is exactly that line.
* Otherwise, and without an arrival direction, it is ONE smooth curve for
  the whole trip (Mark, live 2026-09-28: the tangent-and-arc route hugged
  each body "like the planetary body has repelled us magnetically"; he asked
  to "set out on a heading which avoids the planet and then turn over the
  course of the entire warp"). A cubic Bezier whose inner control points
  are pushed off the chord -- a bow, or an S-bend for bodies either side --
  chosen as the LEAST-BEND candidate that clears every body by the comfort
  margin (``_smooth_curve`` documents the family and the choice); then by
  the hard ``clearance_gu`` margin. Walked by arc length (``SmoothPath``).
  A re-plan can pin the curve's first tangent (``start_dir``) so a flight
  in progress never snaps its nose.
* When no smooth curve clears, or an arrival direction is asked for, the
  routed planner below runs (the pre-2026-09-28 path, kept as the
  fallback):
* The whole path lies in **one plane** through the start and the end. With an
  arrival direction that plane also contains it; otherwise it is the plane
  holding the start->end line and the horizontal perpendicular to it (the
  maps are flat, so detours go sideways in the map, not over a pole).
* Each obstacle sphere, inflated to ``radius + clearance_gu(radius)``, cuts
  that plane in a disk. A path that stays outside every disk in the plane
  stays outside every sphere in 3D, because the out-of-plane offset only adds
  distance.
* In the plane the path is the shortest "tangents and arcs" route: straight
  tangent segments between oriented circles (every disk, both ways round)
  and arcs along the circles, found by Dijkstra. Every segment and arc is
  checked against every disk, so overlapping inflated disks (Vesuvi's Haven
  and Moon 1) are never cut between; pieces join with the same tangent by
  construction.
* With an arrival direction the route ends on a turning circle that leaves
  it at ``end - end_dir * L`` heading along ``end_dir``, then a final straight
  of length ``L = clearance_gu(largest obstacle radius)`` (or the remaining
  distance, if shorter) into the placement. When that turn or straight would
  cut a disk, shorter straights, tighter circles and the other side are
  tried, and the turn and straight are obstacle-checked like the rest.
* The finished path is re-measured in 3D against every keep-out sphere and
  rejected if it cuts one; ``plan_path`` documents the fallback order and
  the flags that report it. It never silently enters a body (ruling R6).
"""
from __future__ import annotations

import bisect
import heapq
import math
from typing import Callable, NamedTuple, Sequence

# --- Tunables (spec "Tunables"; each named in one place) --------------------
DASH_TRIP_S = 10.0          # Set Course: engage -> drop-out, seconds
DASH_MIN_GUPS = 2000.0      # Set Course speed clamp, low end
DASH_MAX_GUPS = 100000.0    # Set Course speed clamp, high end
HEADING_DASH_GUPS = 10000.0  # heading dash speed
DROP_LOOKAHEAD_S = 2.0      # body drop-out looks this much travel time ahead
CLEARANCE_FRACTION = 0.25   # routed gap to a body's surface, x its radius ...
CLEARANCE_MIN_GU = 2000.0   # ... but never less than this
# Comfort margin: the berth the whole-trip smooth curve gives a body's
# surface -- its radius, but never less than this (Mark, live 2026-09-28:
# the clearance-hugging route looked "repelled magnetically"). The hard
# ``clearance_gu`` stays the minimum the fallbacks keep.
COMFORT_MARGIN_MIN_GU = 4000.0

# Routing slack so float rounding never lands a tangent point a hair inside
# a clearance sphere (a thousandth of a GU, 0.175 m).
_ROUTE_EPS_GU = 1e-3
# Tightest turning circle tried for the arrival turn (keeps the path smooth).
_MIN_TURN_GU = 250.0
_EPS = 1e-9


def clearance_gu(radius_gu: float) -> float:
    """Gap a routed path keeps from a body's SURFACE, in GU (the hard
    minimum)."""
    return max(CLEARANCE_FRACTION * radius_gu, CLEARANCE_MIN_GU)


def comfort_gu(radius_gu: float) -> float:
    """Gap the smooth curve keeps from a body's SURFACE, in GU."""
    return max(radius_gu, COMFORT_MARGIN_MIN_GU)


def keep_out_gu(radius_gu: float, near_gu: float, comfort: bool = False):
    """Distance from a body's CENTRE a path between two endpoints must keep,
    where ``near_gu`` is the nearer endpoint's distance to that centre; None
    when an endpoint is inside the body (it is then no obstacle at all).

    Exemption (R5): when the margin sphere holds an endpoint the keep-out is
    only halfway from the surface to that endpoint. The comfort keep-out is
    never less than the hard one, so a comfortable plan also keeps the hard
    clearance."""
    r = float(radius_gu)
    if near_gu <= r:
        return None
    halfway = r + 0.5 * (near_gu - r)
    hard = r + clearance_gu(r)
    if near_gu < hard + _ROUTE_EPS_GU:
        hard = halfway
    if not comfort:
        return hard
    soft = r + comfort_gu(r)
    if near_gu < soft + _ROUTE_EPS_GU:
        soft = halfway
    return max(hard, soft)


class Obstacle(NamedTuple):
    name: str
    center: tuple
    radius_gu: float


# --- small vector helpers ----------------------------------------------------

def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _mul(a, k):
    return (a[0] * k, a[1] * k, a[2] * k)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _norm(a):
    return math.sqrt(_dot(a, a))


def _unit(a):
    n = _norm(a)
    return _mul(a, 1.0 / n) if n > _EPS else None


def _left2(u):
    """2D vector rotated +90 degrees."""
    return (-u[1], u[0])


# --- the path ------------------------------------------------------------------

class WarpPath:
    """A tangent-continuous chain of straight and circular pieces.

    Pieces are ``("line", p0, u, length)`` or ``("arc", c, a, b, r, length)``
    where an arc's point at arc-length ``s`` is ``c + r(cos(s/r) a + sin(s/r) b)``
    -- ``a`` points from the centre to the arc's start, ``b`` is the travel
    direction there.
    """

    def __init__(self, start: tuple, end: tuple, pieces: list,
                 fallback_dir: tuple, *, clearance_kept: bool = True,
                 end_dir_honoured: bool = True, enters_body: bool = False,
                 comfort_kept: bool = False, smooth: bool = False):
        self._start = tuple(float(v) for v in start)
        self._end = tuple(float(v) for v in end)
        self._pieces = pieces
        self._starts = []
        total = 0.0
        for piece in pieces:
            self._starts.append(total)
            total += piece[-1]
        self.length_gu = total
        self._fallback_dir = fallback_dir
        # How the plan came out (see plan_path's fallback order).
        self.clearance_kept = clearance_kept
        self.end_dir_honoured = end_dir_honoured
        self.enters_body = enters_body
        # The comfort margin (comfort_gu) was kept from every body; the
        # path is the whole-trip smooth curve (SmoothPath).
        self.comfort_kept = comfort_kept
        self.smooth = smooth

    @property
    def end(self) -> tuple:
        return self._end

    def _locate(self, s: float):
        s = min(max(float(s), 0.0), self.length_gu)
        if not self._pieces:
            return None, 0.0
        i = max(bisect.bisect_right(self._starts, s) - 1, 0)
        return self._pieces[i], s - self._starts[i]

    def point_at(self, s: float) -> tuple:
        if s >= self.length_gu:
            return self._end
        if s <= 0.0:
            return self._start
        piece, ds = self._locate(s)
        if piece is None:
            return self._start
        if piece[0] == "line":
            _, p0, u, _length = piece
            return _add(p0, _mul(u, ds))
        _, c, a, b, r, _length = piece
        phi = ds / r
        return _add(c, _add(_mul(a, r * math.cos(phi)), _mul(b, r * math.sin(phi))))

    def tangent_at(self, s: float) -> tuple:
        piece, ds = self._locate(s)
        if piece is None:
            return self._fallback_dir
        if piece[0] == "line":
            return piece[2]
        _, _c, a, b, r, _length = piece
        phi = ds / r
        return _add(_mul(a, -math.sin(phi)), _mul(b, math.cos(phi)))


# --- the whole-trip smooth curve ---------------------------------------------
# A cubic Bezier from start to end whose inner control points sit at a third
# and two thirds of the chord, pushed off it along one perpendicular ``n``:
#
#     P1 = S + (D/3) ex + h*alpha*n      P2 = S + (2D/3) ex + h*beta*n
#
# Its point at parameter t is then exactly ``S + D t ex + h Y(t) n`` with
# ``Y(t) = 3 t (1-t) ((1-t) alpha + t beta)``: progress along the chord is
# LINEAR in t (so the curve never doubles back and its tangent is never
# zero), and the sideways bulge is one scalar ``h`` times a fixed SHAPE.
# (alpha, beta) of one sign is a bow (skewed toward the start or the end when
# they differ); of opposite signs an S-bend, for bodies either side of the
# line. For a shape and a direction, the offsets ``h`` that bring a sampled
# point inside a keep-out sphere form one interval, solved in closed form, so
# the least offset that clears EVERY body is found exactly. Among the
# candidates the least bend wins: smallest maximum curvature, then shortest,
# then the table order below (deterministic). A candidate is accepted only
# after a conservative 3D check against every body (``_curve_clear``).

_CURVE_SHAPES = ((1.0, 1.0), (1.0, 0.6), (0.6, 1.0), (1.0, 0.3), (0.3, 1.0),
                 (1.0, 0.0), (0.0, 1.0), (1.0, -1.0), (1.0, -0.5),
                 (0.5, -1.0), (1.0, -0.25), (0.25, -1.0))
# Perpendicular directions, degrees from the horizontal perpendicular (h is
# signed, so each covers both sides). The maps are flat: the horizontal is
# tried alone first, so a detour goes sideways in the map rather than over a
# pole; the tilted ones only when it has no clear candidate.
_CURVE_TILTS_DEG = (30.0, 150.0, 60.0, 120.0, 90.0)
_CURVE_MAX_OFFSET = 1.0     # |h| cap, x chord length (bow peak <= 0.75 D)
_CURVE_WINDOW_SAMPLES = 16  # interval samples across each body's window
_CURVE_PAD = 0.004          # sampled keep-out inflation, x the keep-out ...
_CURVE_PAD_GU = 2.0         # ... plus this, so the exact check rarely rejects
_CURVE_CHECK_TOL_GU = 0.25  # conservative check: curve-vs-polyline slack
_CURVE_TABLE = 128          # arc-length table intervals
_CURVE_RANK_T = tuple(i / 16.0 for i in range(17))
# A re-plan pins its start heading only when that heading makes at least
# this cosine with the new chord; otherwise it plans afresh (and turns).
_PIN_MIN_COS = 0.25


def _shape_y(t, al, be):
    u = 1.0 - t
    return 3.0 * t * u * (u * al + t * be)


def _shape_dy(t, al, be):
    u = 1.0 - t
    return 3.0 * al * (u * u - 2.0 * t * u) + 3.0 * be * (2.0 * t * u - t * t)


def _shape_ddy(t, al, be):
    u = 1.0 - t
    return 3.0 * al * (2.0 * t - 4.0 * u) + 3.0 * be * (2.0 * u - 4.0 * t)


def _first_free(intervals, sign, cap):
    """Least ``|h|`` on the ``sign`` side outside every open interval, or
    None beyond ``cap``."""
    spans = sorted((lo, hi) if sign > 0 else (-hi, -lo) for lo, hi in intervals)
    cur = 0.0
    for lo, hi in spans:
        if hi <= cur:
            continue
        if lo >= cur:
            break
        cur = hi
    return sign * cur if cur <= cap else None


def _rank(al, be, h, dist):
    """(max curvature, length) of a candidate, from 17 stations."""
    kappa, speeds = 0.0, []
    for t in _CURVE_RANK_T:
        dy = h * _shape_dy(t, al, be) / dist
        ddy = h * _shape_ddy(t, al, be) / (dist * dist)
        g = 1.0 + dy * dy
        kappa = max(kappa, abs(ddy) / (g * math.sqrt(g)))
        speeds.append(math.sqrt(g))
    n = len(speeds) - 1                                # Simpson
    length = speeds[0] + speeds[-1] + sum(
        (4.0 if i % 2 else 2.0) * speeds[i] for i in range(1, n))
    return kappa, dist * length / (3.0 * n)


def _curve_clear(dist, lateral, sag, bodies):
    """Conservative exact check, in chord coordinates: every point of the
    curve ``(D t, lateral(t))`` keeps each body's keep-out. Outside a body's
    window ``|D t - x_c| >= need`` already. Inside it the curve is compared
    as a polyline, less the most any chord of that step can sag from the
    curve (``dt^2 / 8 * sag``, ``sag`` >= max|B''| -- B'' is linear in t, so
    its max is at an end)."""
    step = math.sqrt(8.0 * _CURVE_CHECK_TOL_GU / sag) if sag > _EPS else 1.0

    def at(t):
        ly, lz = lateral(t)
        return (dist * t, ly, lz)

    for x_c, wy, wz, need in bodies:
        t0 = max((x_c - need) / dist, 0.0)
        t1 = min((x_c + need) / dist, 1.0)
        if t1 <= t0:
            continue
        q = (x_c, wy, wz)
        count = max(1, int(math.ceil((t1 - t0) / step)))
        a = at(t0)
        for i in range(1, count + 1):
            b = at(t0 + (t1 - t0) * i / count)
            seg = _sub(b, a)
            l2 = _dot(seg, seg)
            k = 0.0 if l2 <= _EPS else min(max(_dot(_sub(q, a), seg) / l2, 0.0), 1.0)
            if _norm(_sub(q, _add(a, _mul(seg, k)))) - _CURVE_CHECK_TOL_GU < need:
                return False
            a = b
    return True


def _rank_pinned(dist, pin, b, n2):
    """(max curvature, length) of a pinned candidate, lateral
    ``A(t) pin + B(t) b n2``, from 17 stations (3D curvature)."""
    kappa, speeds = 0.0, []
    for t in _CURVE_RANK_T:
        da, db = _shape_dy(t, 1.0, 0.0), _shape_dy(t, 0.0, 1.0)
        dda, ddb = _shape_ddy(t, 1.0, 0.0), _shape_ddy(t, 0.0, 1.0)
        l1 = (da * pin[0] + db * b * n2[0], da * pin[1] + db * b * n2[1])
        m1 = (dda * pin[0] + ddb * b * n2[0], dda * pin[1] + ddb * b * n2[1])
        cross = (l1[0] * m1[1] - l1[1] * m1[0], -dist * m1[1], dist * m1[0])
        speed = math.sqrt(dist * dist + l1[0] * l1[0] + l1[1] * l1[1])
        kappa = max(kappa, _norm(cross) / speed ** 3)
        speeds.append(speed)
    n = len(speeds) - 1
    length = speeds[0] + speeds[-1] + sum(
        (4.0 if i % 2 else 2.0) * speeds[i] for i in range(1, n))
    return kappa, length / (3.0 * n)


def _smooth_curve(start, end, spheres, comfort, start_dir=None):
    """The least-bend smooth curve from ``start`` to ``end`` keeping every
    keep-out sphere ``(centre, need, _)``: its two inner control points, or
    None when no candidate within ``_CURVE_MAX_OFFSET`` clears them all.
    ``comfort`` says which margin the spheres carry (reporting only).

    With a unit ``start_dir`` (a re-plan: the heading already flown) the
    first control point is PINNED on it, ``P1 = S + (D/3) (ex + lat/c)`` for
    ``start_dir = c ex + lat``, so the curve sets off exactly along it; only
    ``P2``'s offset is searched. The caller keeps ``c`` well above zero."""
    chord = _sub(end, start)
    dist = _norm(chord)
    if dist <= _EPS:
        return None
    ex = _mul(chord, 1.0 / dist)
    ey = _unit(_cross((0.0, 0.0, 1.0), ex)) or _unit(_cross((1.0, 0.0, 0.0), ex))
    ez = _cross(ex, ey)
    bodies = []                        # (x_c, wy, wz, need) in chord axes
    for centre, need, _reach in spheres:
        d = _sub(centre, start)
        x_c = _dot(d, ex)
        if x_c + need <= 0.0 or x_c - need >= dist:
            continue                   # no curve point can come that close
        bodies.append((x_c, _dot(d, ey), _dot(d, ez), need))
    pin = None
    if start_dir is not None:
        c = _dot(start_dir, ex)
        k = dist / (3.0 * c)
        pin = (k * _dot(start_dir, ey), k * _dot(start_dir, ez))
    elif not bodies:
        return None
    windows = []                       # (t, dx^2, wy, wz, need') per sample
    for x_c, wy, wz, need in bodies:
        t0 = max((x_c - need) / dist, 0.0)
        t1 = min((x_c + need) / dist, 1.0)
        padded = need * (1.0 + _CURVE_PAD) + _CURVE_PAD_GU
        for i in range(_CURVE_WINDOW_SAMPLES + 1):
            t = t0 + (t1 - t0) * i / _CURVE_WINDOW_SAMPLES
            if pin is not None:        # the pinned part of the bulge
                a = _shape_y(t, 1.0, 0.0)
                wy_t, wz_t = wy - a * pin[0], wz - a * pin[1]
            else:
                wy_t, wz_t = wy, wz
            windows.append((t, (dist * t - x_c) ** 2, wy_t, wz_t, padded))
    cap = _CURVE_MAX_OFFSET * dist
    shapes = ((0.0, 1.0),) if pin is not None else _CURVE_SHAPES

    def search(tilts):
        found = []
        for ti, tilt in enumerate(tilts):
            n2 = (math.cos(math.radians(tilt)), math.sin(math.radians(tilt)))
            bands = []                 # (t, y_lo, y_hi): bulges inside a body
            for t, dx2, wy, wz, padded in windows:
                c_n = wy * n2[0] + wz * n2[1]
                perp2 = wy * wy + wz * wz - c_n * c_n
                disc = padded * padded - dx2 - perp2
                if disc > 0.0:
                    r = math.sqrt(disc)
                    bands.append((t, c_n - r, c_n + r))
            for si, (al, be) in enumerate(shapes):
                spans = []
                for t, lo, hi in bands:
                    y = _shape_y(t, al, be)
                    if abs(y) < 1e-12:
                        if lo < 0.0 < hi:
                            break      # a fixed point of the shape is inside
                        continue
                    spans.append((lo / y, hi / y) if y > 0.0 else (hi / y, lo / y))
                else:
                    hs = [_first_free(spans, sign, cap) for sign in (1.0, -1.0)]
                    if pin is not None:
                        # b's curvature is not monotone in |b|: also offer a
                        # few free offsets scaled to the pinned one.
                        size = math.hypot(*pin)
                        hs += [f * size for f in (0.0, 0.5, -0.5, 1.0, -1.0)
                               if not any(lo < f * size < hi for lo, hi in spans)]
                    for gi, h in enumerate(hs):
                        if h is None:
                            continue
                        if pin is not None:
                            kappa, length = _rank_pinned(dist, pin, h, n2)
                        else:
                            kappa, length = _rank(al, be, h, dist)
                        found.append((kappa, length, ti, si, gi, n2, h))
        found.sort(key=lambda c: c[:5])
        for _k, _l, _ti, si, _gi, n2, h in found:
            al, be = shapes[si]
            if pin is None:
                def lateral(t, al=al, be=be, h=h, n2=n2):
                    y = h * _shape_y(t, al, be)
                    return (y * n2[0], y * n2[1])
                sag = abs(h) * max(abs(_shape_ddy(0.0, al, be)),
                                   abs(_shape_ddy(1.0, al, be)))
                a_lat = (h * al * n2[0], h * al * n2[1])
            else:
                def lateral(t, h=h, n2=n2):
                    a, b = _shape_y(t, 1.0, 0.0), _shape_y(t, 0.0, 1.0) * h
                    return (a * pin[0] + b * n2[0], a * pin[1] + b * n2[1])
                sag = max(abs(_shape_ddy(e, 1.0, 0.0)) * math.hypot(*pin)
                          + abs(_shape_ddy(e, 0.0, 1.0) * h) for e in (0.0, 1.0))
                a_lat = pin
            if _curve_clear(dist, lateral, sag, bodies):
                p1 = _add(_mul(ey, a_lat[0]), _mul(ez, a_lat[1]))
                p2 = _add(_mul(ey, h * be * n2[0]), _mul(ez, h * be * n2[1]))
                return (_add(start, _add(_mul(ex, dist / 3.0), p1)),
                        _add(start, _add(_mul(ex, 2.0 * dist / 3.0), p2)))
        return None

    return search((0.0,)) or search(_CURVE_TILTS_DEG)


class SmoothPath(WarpPath):
    """A cubic Bezier ``start, p1, p2, end``, walked by ARC LENGTH through a
    table: ``point_at`` / ``tangent_at`` look up the parameter for ``s`` and
    evaluate the curve itself, so every point is on the curve and the
    tangent is its continuous derivative."""

    def __init__(self, start, end, p1, p2, **flags):
        start = tuple(float(v) for v in start)
        end = tuple(float(v) for v in end)
        super().__init__(start, end, [], _unit(_sub(end, start)) or (0.0, 1.0, 0.0),
                         smooth=True, **flags)
        self._ctrl = (start, tuple(p1), tuple(p2), end)
        self._t_tab = [i / _CURVE_TABLE for i in range(_CURVE_TABLE + 1)]
        self._s_tab = [0.0]
        self._rate = [1.0 / _norm(self._velocity(0.0))]   # dt/ds at each node
        prev = start
        for t in self._t_tab[1:]:
            q = self._bezier(t)
            self._s_tab.append(self._s_tab[-1] + _norm(_sub(q, prev)))
            self._rate.append(1.0 / _norm(self._velocity(t)))
            prev = q
        self.length_gu = self._s_tab[-1]

    def _bezier(self, t):
        p0, p1, p2, p3 = self._ctrl
        u = 1.0 - t
        a, b, c, d = u * u * u, 3.0 * u * u * t, 3.0 * u * t * t, t * t * t
        return tuple(a * p0[i] + b * p1[i] + c * p2[i] + d * p3[i] for i in range(3))

    def _velocity(self, t):
        p0, p1, p2, p3 = self._ctrl
        u = 1.0 - t
        a, b, c = 3.0 * u * u, 6.0 * u * t, 3.0 * t * t
        return tuple(a * (p1[i] - p0[i]) + b * (p2[i] - p1[i]) + c * (p3[i] - p2[i])
                     for i in range(3))

    def _param(self, s):
        """The curve parameter at arc length ``s``: cubic Hermite through the
        table nodes with slopes dt/ds, so the speed change across a cell
        does not skew the walk."""
        s = min(max(float(s), 0.0), self.length_gu)
        i = min(max(bisect.bisect_right(self._s_tab, s) - 1, 0), _CURVE_TABLE - 1)
        s0, s1 = self._s_tab[i], self._s_tab[i + 1]
        h = s1 - s0
        if h <= 0.0:
            return self._t_tab[i]
        u = (s - s0) / h
        u2, u3 = u * u, u * u * u
        return ((2.0 * u3 - 3.0 * u2 + 1.0) * self._t_tab[i]
                + (u3 - 2.0 * u2 + u) * h * self._rate[i]
                + (-2.0 * u3 + 3.0 * u2) * self._t_tab[i + 1]
                + (u3 - u2) * h * self._rate[i + 1])

    def point_at(self, s: float) -> tuple:
        if s >= self.length_gu:
            return self._end
        if s <= 0.0:
            return self._start
        return self._bezier(self._param(s))

    def tangent_at(self, s: float) -> tuple:
        return _unit(self._velocity(self._param(s))) or self._fallback_dir


# --- planar routing ----------------------------------------------------------
# A circle is (centre2, radius, orient, disk_id): orient +1 travels
# counter-clockwise (centre on the left), -1 clockwise. A point is a circle of
# radius 0 with disk_id None. A disk is (centre2, radius) in the plane.

def _touch(node, u):
    """Where a travel direction ``u`` touches ``node``."""
    (cx, cy), r, s = node[0], node[1], node[2]
    lx, ly = _left2(u)
    return (cx - s * r * lx, cy - s * r * ly)


def _tangent(n1, n2):
    """Unit direction of the tangent segment leaving n1 and arriving on n2,
    honouring both orientations; None when it does not exist."""
    dx, dy = n2[0][0] - n1[0][0], n2[0][1] - n1[0][1]
    d2 = dx * dx + dy * dy
    k = n2[2] * n2[1] - n1[2] * n1[1]
    if d2 <= k * k + _EPS:
        return None
    t = math.sqrt(d2 - k * k)
    lx, ly = -dy, dx
    return ((t * dx - k * lx) / d2, (t * dy - k * ly) / d2)


def _sweep(orient, u_in, u_out):
    """Angle turned on a circle of orientation ``orient`` from u_in to u_out."""
    ang = math.atan2(u_out[1], u_out[0]) - math.atan2(u_in[1], u_in[0])
    ang *= orient
    ang %= 2.0 * math.pi
    return 0.0 if ang > 2.0 * math.pi - 1e-12 else ang


def _tol(r):
    return 1e-9 * max(1.0, r)


def _seg_clear(p, q, disks, skip=()):
    """True when segment p->q stays outside every disk not in ``skip``."""
    ux, uy = q[0] - p[0], q[1] - p[1]
    l2 = ux * ux + uy * uy
    for j, (centre, radius) in enumerate(disks):
        if j in skip:
            continue
        wx, wy = centre[0] - p[0], centre[1] - p[1]
        t = 0.0 if l2 <= _EPS else min(max((wx * ux + wy * uy) / l2, 0.0), 1.0)
        cx, cy = p[0] + t * ux - centre[0], p[1] + t * uy - centre[1]
        if math.hypot(cx, cy) < radius - _tol(radius):
            return False
    return True


def _arc_clear(node, u_in, ang, disks, skip=()):
    """True when the arc on ``node`` from direction u_in, turning ``ang``,
    stays outside every disk not in ``skip``."""
    (cx, cy), r, orient = node[0], node[1], node[2]
    if r <= _EPS or ang <= 0.0:
        return True
    p0 = _touch(node, u_in)
    a0 = math.atan2(p0[1] - cy, p0[0] - cx)
    a1 = a0 + orient * ang
    p1 = (cx + r * math.cos(a1), cy + r * math.sin(a1))
    for j, (centre, radius) in enumerate(disks):
        if j in skip:
            continue
        qx, qy = centre[0] - cx, centre[1] - cy
        dq = math.hypot(qx, qy)
        within = ((orient * (math.atan2(qy, qx) - a0)) % (2.0 * math.pi)) <= ang
        if within or dq <= _EPS:
            nearest = abs(dq - r)
        else:
            nearest = min(math.hypot(centre[0] - p0[0], centre[1] - p0[1]),
                          math.hypot(centre[0] - p1[0], centre[1] - p1[1]))
        if nearest < radius - _tol(radius):
            return False
    return True


def _shortest(start2, goal, exit_dir, final_len, disks):
    """Shortest tangent-continuous route in the plane from the point
    ``start2`` to ``goal`` that enters no disk.

    ``goal`` is a point (radius 0) or, with ``exit_dir``, a turning circle
    the route leaves travelling along ``exit_dir`` (then ``final_len`` more
    of straight). Dijkstra over tangent segments between oriented circles --
    every disk twice (both orientations) -- with arcs along the circles;
    every segment and arc is checked against every other disk, so a route
    through the overlap of two inflated disks cannot be produced. Returns
    ``(nodes, dirs)`` -- the circles visited and each leg's direction -- or
    None."""
    circles = [(start2, 0.0, 1, None)]
    for j, (centre, radius) in enumerate(disks):
        if radius <= _EPS:
            continue                   # sphere misses the plane
        circles.append((centre, radius, 1, j))
        circles.append((centre, radius, -1, j))
    circles.append((goal[0], goal[1], goal[2], None))
    gi = len(circles) - 1

    segs = []                      # (from, to, u, length)
    out = {}
    for a in range(gi):
        for b in range(1, gi + 1):
            if a == b or (circles[a][3] is not None and circles[a][3] == circles[b][3]):
                continue
            u = _tangent(circles[a], circles[b])
            if u is None:
                continue
            p, q = _touch(circles[a], u), _touch(circles[b], u)
            skip = {circles[a][3], circles[b][3]} - {None}
            if not _seg_clear(p, q, disks, skip):
                continue
            out.setdefault(a, []).append(len(segs))
            segs.append((a, b, u, math.hypot(q[0] - p[0], q[1] - p[1])))

    heap = []
    counter = 0
    for k in out.get(0, []):
        heapq.heappush(heap, (segs[k][3], counter, k))
        counter += 1
    done = set()
    prev = {}
    while heap:
        cost, _seq, k = heapq.heappop(heap)
        if k == "goal":
            break
        if k in done:
            continue
        done.add(k)
        c = segs[k][1]
        node, u_in = circles[c], segs[k][2]
        if c == gi:
            if exit_dir is None:
                heapq.heappush(heap, (cost, counter, "goal"))
                prev.setdefault("goal", []).append((cost, counter, k))
            else:
                ang = _sweep(node[2], u_in, exit_dir)
                if _arc_clear(node, u_in, ang, disks):
                    total = cost + node[1] * ang + final_len
                    heapq.heappush(heap, (total, counter, "goal"))
                    prev.setdefault("goal", []).append((total, counter, k))
            counter += 1
            continue
        own = {node[3]}
        for k2 in out.get(c, []):
            if k2 in done:
                continue
            ang = _sweep(node[2], u_in, segs[k2][2])
            if not _arc_clear(node, u_in, ang, disks, own):
                continue
            total = cost + node[1] * ang + segs[k2][3]
            heapq.heappush(heap, (total, counter, k2))
            prev.setdefault(k2, []).append((total, counter, k))
            counter += 1
    else:
        return None

    def best_prev(k):
        return min(prev[k])[2]

    chain = []
    k = best_prev("goal")
    while True:
        chain.append(k)
        if segs[k][0] == 0:
            break
        k = best_prev(k)
    chain.reverse()
    nodes = [circles[segs[chain[0]][0]]] + [circles[segs[k][1]] for k in chain]
    return nodes, [segs[k][2] for k in chain]


def _piece_min_dist(piece, q):
    """Exact minimum distance from point ``q`` to a line or arc piece (3D)."""
    if piece[0] == "line":
        _, p0, u, length = piece
        t = min(max(_dot(_sub(q, p0), u), 0.0), length)
        return _norm(_sub(q, _add(p0, _mul(u, t))))
    _, c, a, b, r, length = piece
    w = _sub(q, c)
    x, y = _dot(w, a), _dot(w, b)
    h2 = max(_dot(w, w) - x * x - y * y, 0.0)
    sweep = length / r
    rho = math.hypot(x, y)
    if rho <= _EPS or (math.atan2(y, x) % (2.0 * math.pi)) <= sweep:
        return math.sqrt(h2 + (rho - r) ** 2)
    end = _add(c, _add(_mul(a, r * math.cos(sweep)), _mul(b, r * math.sin(sweep))))
    return min(_norm(_sub(q, _add(c, _mul(a, r)))), _norm(_sub(q, end)))


def _min_dist(pieces, q):
    return min((_piece_min_dist(pc, q) for pc in pieces), default=math.inf)


def plan_path(start, end, obstacles: Sequence[Obstacle], end_dir=None,
              start_dir=None) -> WarpPath:
    """Plan a warp from ``start`` to ``end``; straight when the line keeps
    every body's comfort keep-out. Deterministic.

    Never enters a body the endpoints are outside of (spec section 1, ruling
    R6). Order, each outcome reported on the returned path's flags:

    Without ``end_dir`` (every current caller -- Set Course dashes arrive
    facing their travel and turn afterwards, AI flights have no arrival
    direction):

    1. comfort margin (``comfort_gu``): the straight line, else the smooth
       curve (``smooth``, ``comfort_kept``); with ``start_dir`` the curve is
       first pinned to leave along it (the line only if it is already
       along it), then planned afresh;
    2. the hard ``clearance_gu`` margin: the line, else the smooth curve
       (``comfort_kept`` False);
    3. the routed planner below.

    With ``end_dir`` the routed planner runs directly (still supported and
    tested; no caller passes it since 1eb145a5). Routed fallback order:

    1. full clearance, arriving along ``end_dir``;
    2. full clearance, ``end_dir`` dropped (``end_dir_honoured`` False) --
       the caller turns the ship at the placement itself;
    3. bodies only, with then without ``end_dir`` (``clearance_kept`` False);
    4. the straight line (``enters_body`` True when it crosses a body) --
       only when even (3) has no route, which needs bodies enclosing an
       endpoint in the plane.

    Clearance exemption (R5, ``keep_out_gu``): a body whose margin sphere
    holds the start or the end is kept out of only halfway from its surface
    to that endpoint; a body holding an endpoint is not an obstacle at all.

    ``start_dir`` is honoured only while it makes a cosine of at least
    ``_PIN_MIN_COS`` with the chord; facing further away, it plans afresh."""
    s3 = tuple(float(v) for v in start)
    e3 = tuple(float(v) for v in end)
    ed = _unit(tuple(float(v) for v in end_dir)) if end_dir is not None else None
    chord = _sub(e3, s3)
    dist = _norm(chord)
    if dist <= _EPS:
        return WarpPath(s3, e3, [], ed or (0.0, 1.0, 0.0))

    # The plane: x along the chord, y along end_dir's perpendicular part (so
    # the arrival direction lies in it) or else the horizontal perpendicular.
    ex = _mul(chord, 1.0 / dist)
    ey = None
    if ed is not None:
        ey = _unit(_sub(ed, _mul(ex, _dot(ed, ex))))
    if ey is None:
        ey = _unit(_cross((0.0, 0.0, 1.0), ex)) or _unit(_cross((1.0, 0.0, 0.0), ex))
    ez = _cross(ex, ey)

    def to2(p):
        d = _sub(p, s3)
        return (_dot(d, ex), _dot(d, ey))

    def to3(p):
        return _add(s3, _add(_mul(ex, p[0]), _mul(ey, p[1])))

    def dir3(u):
        return _add(_mul(ex, u[0]), _mul(ey, u[1]))

    # Keep-out spheres per level: (centre3, required distance, routing radius).
    ordered = sorted(obstacles, key=lambda o: (o.name, tuple(o.center), o.radius_gu))
    largest = max((o.radius_gu for o in ordered), default=0.0)

    def valid(pieces, spheres):
        return all(_min_dist(pieces, c) >= need - _tol(need)
                   for c, need, _reach in spheres)

    def keep_outs(full_clearance, comfort=False):
        spheres = []
        for o in ordered:
            centre = tuple(float(v) for v in o.center)
            near = min(_norm(_sub(s3, centre)), _norm(_sub(e3, centre)))
            if near <= o.radius_gu:
                continue                     # an endpoint is inside the body
            if full_clearance:
                need = keep_out_gu(o.radius_gu, near, comfort)
            else:
                need = o.radius_gu
                if near < need + _ROUTE_EPS_GU:  # R5: halfway to the endpoint
                    need = o.radius_gu + 0.5 * (near - o.radius_gu)
            if near < need + _ROUTE_EPS_GU:
                spheres.append((centre, need, need))
            else:
                spheres.append((centre, need, need + _ROUTE_EPS_GU))
        return spheres

    sd = _unit(tuple(float(v) for v in start_dir)) if start_dir is not None else None
    if sd is not None and _dot(sd, ex) < _PIN_MIN_COS:
        sd = None                            # facing away: plan afresh
    if ed is None:
        # The whole-trip smooth curve: comfort margin, then the hard one;
        # pinned to start_dir first when there is one, then afresh.
        line = [("line", s3, ex, dist)]
        for pin in ((None,) if sd is None else (sd, None)):
            for comfort in (True, False):
                spheres = keep_outs(True, comfort)
                if (pin is None or _dot(pin, ex) >= 1.0 - 1e-12) and valid(line, spheres):
                    return WarpPath(s3, e3, line, ex, comfort_kept=comfort)
                ctrl = _smooth_curve(s3, e3, spheres, comfort, start_dir=pin)
                if ctrl is not None:
                    return SmoothPath(s3, e3, *ctrl, comfort_kept=comfort)

    def disks_of(spheres):
        disks = []
        for centre, _need, reach in spheres:
            h = _dot(_sub(centre, s3), ez)
            disks.append((to2(centre), math.sqrt(reach * reach - h * h))
                         if abs(h) < reach else ((0.0, 0.0), 0.0))
        return disks

    s2, e2 = (0.0, 0.0), to2(e3)

    def build(nodes, dirs, exit_point):
        pieces = []

        def add_line(p, q):
            seg = (q[0] - p[0], q[1] - p[1])
            length = math.hypot(*seg)
            if length > _EPS:
                pieces.append(("line", to3(p),
                               dir3((seg[0] / length, seg[1] / length)), length))

        def add_arc(node, u_in, u_out):
            centre, r, orient = node[0], node[1], node[2]
            ang = _sweep(orient, u_in, u_out)
            if r <= _EPS or ang <= 0.0:
                return
            p = _touch(node, u_in)
            a = ((p[0] - centre[0]) / r, (p[1] - centre[1]) / r)
            pieces.append(("arc", to3(centre), dir3(a), dir3(u_in), r, r * ang))

        for i, u in enumerate(dirs):
            if i > 0:
                add_arc(nodes[i], dirs[i - 1], u)
            add_line(_touch(nodes[i], u), _touch(nodes[i + 1], u))
        if exit_point is not None:
            a2, e_dir2 = exit_point
            add_arc(nodes[-1], dirs[-1], e_dir2)
            add_line(a2, e2)
        return pieces

    def route_to_point(spheres, disks):
        routed = _shortest(s2, (e2, 0.0, 1), None, 0.0, disks)
        if routed is None:
            return None
        pieces = build(*routed, None)
        return pieces if valid(pieces, spheres) else None

    def route_along_end_dir(spheres, disks):
        e_dir2 = (_dot(ed, ex), _dot(ed, ey))
        lft = _left2(e_dir2)
        l0 = min(clearance_gu(largest), dist)
        tried = set()
        for final_len in (l0, 0.5 * l0, 0.25 * l0, 0.0):
            a2 = (e2[0] - e_dir2[0] * final_len, e2[1] - e_dir2[1] * final_len)
            if not _seg_clear(a2, e2, disks):
                continue
            lateral = (s2[0] - a2[0]) * lft[0] + (s2[1] - a2[1]) * lft[1]
            first = 1 if lateral >= 0.0 else -1
            for scale in (1.0, 0.5, 0.25, 0.125):
                rho = max(l0 * scale, _MIN_TURN_GU)
                if (final_len, rho) in tried:
                    continue
                tried.add((final_len, rho))
                best = None
                for orient in (first, -first):
                    goal = ((a2[0] + orient * rho * lft[0], a2[1] + orient * rho * lft[1]),
                            rho, orient)
                    routed = _shortest(s2, goal, e_dir2, final_len, disks)
                    if routed is None:
                        continue
                    pieces = build(*routed, (a2, e_dir2))
                    if not valid(pieces, spheres):
                        continue
                    length = sum(pc[-1] for pc in pieces)
                    if best is None or length < best[0]:
                        best = (length, pieces)
                if best is not None:
                    return best[1]
        return None

    fallback = ed or ex
    for full_clearance in (True, False):
        spheres = keep_outs(full_clearance)
        disks = disks_of(spheres)
        if ed is None and _seg_clear(s2, e2, disks):
            return WarpPath(s3, e3, [("line", s3, ex, dist)], fallback,
                            clearance_kept=full_clearance)
        attempts = ((route_along_end_dir, True),) if ed is not None else ()
        attempts += ((route_to_point, False),)
        for attempt, honours in attempts:
            pieces = attempt(spheres, disks)
            if pieces is not None:
                return WarpPath(s3, e3, pieces, fallback,
                                clearance_kept=full_clearance,
                                end_dir_honoured=honours or ed is None)
    line = [("line", s3, ex, dist)]
    return WarpPath(s3, e3, line, fallback, clearance_kept=False,
                    end_dir_honoured=ed is None,
                    enters_body=not valid(line, keep_outs(False)))


# --- speed policy and drop-out -----------------------------------------------

def set_course_speed(length_gu: float) -> float:
    """Set Course dash speed: the path in ``DASH_TRIP_S``, clamped."""
    return min(max(length_gu / DASH_TRIP_S, DASH_MIN_GUPS), DASH_MAX_GUPS)


def drop_out(pos, direction, speed_gups: float, obstacles: Sequence[Obstacle],
             standoff_of: Callable[[Obstacle], float]):
    """Where a straight-line warp must end short of a body, or None.

    A body counts when the ray from ``pos`` along ``direction`` passes
    through it and its DROP POINT lies within ``speed_gups *
    DROP_LOOKAHEAD_S`` of travel. The drop point is the point on the ray
    ``standoff_of(body)`` from the body's centre, before the centre -- but
    never past where the ray enters the body, and never behind ``pos``. The
    nearest such point wins.

    Reach is measured to the drop point, not the surface: a region-arrival
    standoff can sit tens of thousands of GU above a small moon (Prendel's
    Moon 2: 43,249 GU for a 1,800 GU radius), further than the reach, and a
    surface-reach test then clamped the drop to ``pos`` short of it."""
    p = tuple(float(v) for v in pos)
    d = _unit(tuple(float(v) for v in direction))
    if d is None:
        return None
    reach = speed_gups * DROP_LOOKAHEAD_S
    best = None
    for o in obstacles:
        v = _sub(tuple(float(c) for c in o.center), p)
        along = _dot(v, d)
        lat2 = max(_dot(v, v) - along * along, 0.0)
        r2 = o.radius_gu * o.radius_gu
        if lat2 >= r2:
            continue                       # off the line
        half = math.sqrt(r2 - lat2)
        if along + half < 0.0:
            continue                       # behind
        sd = float(standoff_of(o))
        t = min(along - math.sqrt(max(sd * sd - lat2, 0.0)), along - half)
        t = max(t, 0.0)
        if t > reach:
            continue                       # beyond the lookahead
        if best is None or t < best:
            best = t
    return None if best is None else _add(p, _mul(d, best))
