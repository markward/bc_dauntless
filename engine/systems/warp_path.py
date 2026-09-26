"""In-system warp planner: path, speed policy and body drop-out (pure).

Spec: docs/superpowers/specs/2026-09-25-in-system-warp-design.md, section 1
("Path", "Speed policy", "Body drop-out") and "Tunables". Everything here is
plain math on ``(x, y, z)`` tuples in **system coordinates** (GU); no engine
imports, so the planner is testable on its own and the callers (the warp
flight, the dashes) own every engine-side decision.

The tunables are the spec's starting values and are each named once, here.

Path construction (a design choice; the spec fixes only the properties):

* The whole path lies in **one plane** through the start and the end. With an
  arrival direction that plane also contains it; otherwise it is the plane
  holding the start->end line and the horizontal perpendicular to it (the
  maps are flat, so detours go sideways in the map, not over a pole).
* Each obstacle sphere, inflated to ``radius + clearance_gu(radius)``, cuts
  that plane in a disk. A path that stays outside every disk in the plane
  stays outside every sphere in 3D, because the out-of-plane offset only adds
  distance.
* In the plane the path is the classic "tangents and arcs" route: straight
  tangent segments between oriented circles, and arcs along the circles.
  Blocking disks are wrapped greedily -- the first disk a segment hits is
  inserted as a node and the tangents recomputed -- so each piece joins the
  next with the same tangent by construction.
* With an arrival direction the route ends on a turning circle that leaves
  it at ``end - end_dir * L`` heading along ``end_dir``, then a final straight
  of length ``L = clearance_gu(largest obstacle radius)`` (or the remaining
  distance, if shorter) into the placement.
"""
from __future__ import annotations

import bisect
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

# Routing slack so float rounding never lands a tangent point a hair inside
# a clearance sphere (a thousandth of a GU, 0.175 m).
_ROUTE_EPS_GU = 1e-3
_EPS = 1e-9


def clearance_gu(radius_gu: float) -> float:
    """Gap a routed path keeps from a body's SURFACE, in GU."""
    return max(CLEARANCE_FRACTION * radius_gu, CLEARANCE_MIN_GU)


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
                 fallback_dir: tuple):
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


# --- planar routing ----------------------------------------------------------
# A node is (centre2, radius, orient): orient +1 travels counter-clockwise
# (centre on the left), -1 clockwise. A point is a node of radius 0.

def _touch(node, u):
    """Where a travel direction ``u`` touches ``node``."""
    (cx, cy), r, s = node
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


def _seg_hit(p, q, centre, radius):
    """Param along p->q of the closest approach if the segment enters the disk."""
    ux, uy = q[0] - p[0], q[1] - p[1]
    l2 = ux * ux + uy * uy
    wx, wy = centre[0] - p[0], centre[1] - p[1]
    t = 0.0 if l2 <= _EPS else min(max((wx * ux + wy * uy) / l2, 0.0), 1.0)
    cx, cy = p[0] + t * ux - centre[0], p[1] + t * uy - centre[1]
    return t if cx * cx + cy * cy < radius * radius else None


def _route(nodes, disks):
    """Greedily wrap every disk a tangent segment crosses. ``nodes`` is
    ``[start, ..., goal]``; returns the node list and each leg's direction."""
    nodes = list(nodes)
    wrapped = set()
    for _ in range(len(disks) + 1):
        dirs = [_tangent(nodes[i], nodes[i + 1]) for i in range(len(nodes) - 1)]
        if any(u is None for u in dirs):
            return None
        inserted = False
        for i, u in enumerate(dirs):
            p, q = _touch(nodes[i], u), _touch(nodes[i + 1], u)
            hits = []
            for j, (centre, radius) in enumerate(disks):
                if j in wrapped:
                    continue
                t = _seg_hit(p, q, centre, radius)
                if t is not None:
                    hits.append((t, j))
            if not hits:
                continue
            _t, j = min(hits)
            centre, radius = disks[j]
            side = (centre[0] - p[0]) * -u[1] + (centre[1] - p[1]) * u[0]
            orient = 1 if side >= 0.0 else -1   # centre on the left -> ccw
            trial = nodes[:i + 1] + [(centre, radius, orient)] + nodes[i + 1:]
            trial_dirs = [_tangent(trial[k], trial[k + 1])
                          for k in range(len(trial) - 1)]
            wrapped.add(j)
            if any(d is None for d in trial_dirs):
                continue  # disks overlap; cannot wrap this one -- leave it
            nodes = trial
            inserted = True
            break
        if not inserted:
            return nodes, dirs
    dirs = [_tangent(nodes[i], nodes[i + 1]) for i in range(len(nodes) - 1)]
    if any(u is None for u in dirs):
        return None
    return nodes, dirs


def _sweep(orient, u_in, u_out):
    """Angle turned on a circle of orientation ``orient`` from u_in to u_out."""
    ang = math.atan2(u_out[1], u_out[0]) - math.atan2(u_in[1], u_in[0])
    ang *= orient
    ang %= 2.0 * math.pi
    return 0.0 if ang > 2.0 * math.pi - 1e-12 else ang


def plan_path(start, end, obstacles: Sequence[Obstacle], end_dir=None) -> WarpPath:
    """Plan a warp from ``start`` to ``end`` clearing every obstacle by
    ``radius + clearance_gu(radius)``; straight when nothing is in the way.
    With ``end_dir`` the path arrives travelling along it. Deterministic."""
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

    # Obstacle spheres -> disks in the plane. A sphere holding the start or
    # the end cannot be cleared; it is left out rather than failing the warp.
    disks = []
    largest = 0.0
    for o in sorted(obstacles, key=lambda o: (o.name, tuple(o.center))):
        centre = tuple(float(v) for v in o.center)
        reach = o.radius_gu + clearance_gu(o.radius_gu) + _ROUTE_EPS_GU
        largest = max(largest, o.radius_gu)
        if _norm(_sub(s3, centre)) < reach or _norm(_sub(e3, centre)) < reach:
            continue
        h = _dot(_sub(centre, s3), ez)
        if abs(h) >= reach:
            continue
        disks.append((to2(centre), math.sqrt(reach * reach - h * h)))

    s2, e2 = (0.0, 0.0), to2(e3)
    start_node = (s2, 0.0, 1)
    if ed is None:
        goal = (e2, 0.0, 1)
        exit_point = None
    else:
        e_dir2 = (_dot(ed, ex), _dot(ed, ey))
        final_len = min(clearance_gu(largest), dist)
        a2 = (e2[0] - e_dir2[0] * final_len, e2[1] - e_dir2[1] * final_len)
        lft = _left2(e_dir2)
        rel = (s2[0] - a2[0], s2[1] - a2[1])
        lateral = rel[0] * lft[0] + rel[1] * lft[1]
        orient = 1 if lateral >= 0.0 else -1
        rho = final_len
        toward = orient * lateral
        if toward > _EPS:   # keep the start outside the turning circle
            rho = min(rho, 0.25 * (rel[0] ** 2 + rel[1] ** 2) / toward)
        goal = ((a2[0] + orient * rho * lft[0], a2[1] + orient * rho * lft[1]),
                rho, orient)
        exit_point = (a2, e_dir2)

    routed = _route([start_node, goal], disks)
    if routed is None:   # no tangent at all (degenerate): straight line
        routed = ([start_node, (e2, 0.0, 1)], [_tangent(start_node, (e2, 0.0, 1))])
        exit_point = None
    nodes, dirs = routed

    pieces = []

    def add_line(p, q):
        seg = (q[0] - p[0], q[1] - p[1])
        length = math.hypot(*seg)
        if length > _EPS:
            pieces.append(("line", to3(p), dir3((seg[0] / length, seg[1] / length)),
                           length))

    def add_arc(node, u_in, u_out):
        centre, r, orient = node
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

    fallback = ed or ex
    return WarpPath(s3, e3, pieces, fallback)


# --- speed policy and drop-out -----------------------------------------------

def set_course_speed(length_gu: float) -> float:
    """Set Course dash speed: the path in ``DASH_TRIP_S``, clamped."""
    return min(max(length_gu / DASH_TRIP_S, DASH_MIN_GUPS), DASH_MAX_GUPS)


def drop_out(pos, direction, speed_gups: float, obstacles: Sequence[Obstacle],
             standoff_of: Callable[[Obstacle], float]):
    """Where a straight-line warp must end short of a body, or None.

    A body counts when the ray from ``pos`` along ``direction`` enters it
    within ``speed_gups * DROP_LOOKAHEAD_S`` of travel. The drop point is the
    point on the ray ``standoff_of(body)`` from the body's centre, before the
    centre, and never behind ``pos``. The nearest such point wins."""
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
        if along - half > reach:
            continue                       # beyond the lookahead
        sd = float(standoff_of(o))
        t = max(along - math.sqrt(max(sd * sd - lat2, 0.0)), 0.0)
        if best is None or t < best:
            best = t
    return None if best is None else _add(p, _mul(d, best))
