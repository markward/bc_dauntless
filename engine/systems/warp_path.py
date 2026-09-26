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

# Routing slack so float rounding never lands a tangent point a hair inside
# a clearance sphere (a thousandth of a GU, 0.175 m).
_ROUTE_EPS_GU = 1e-3
# Tightest turning circle tried for the arrival turn (keeps the path smooth).
_MIN_TURN_GU = 250.0
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
                 fallback_dir: tuple, *, clearance_kept: bool = True,
                 end_dir_honoured: bool = True, enters_body: bool = False):
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


def plan_path(start, end, obstacles: Sequence[Obstacle], end_dir=None) -> WarpPath:
    """Plan a warp from ``start`` to ``end`` clearing every obstacle by
    ``radius + clearance_gu(radius)``; straight when nothing is in the way.
    With ``end_dir`` the path arrives travelling along it. Deterministic.

    Never enters a body the endpoints are outside of (spec section 1, ruling
    R6). Fallback order when the ideal route cannot be built -- each one
    reported on the returned path's flags:

    1. full clearance, arriving along ``end_dir``;
    2. full clearance, ``end_dir`` dropped (``end_dir_honoured`` False) --
       the caller turns the ship at the placement itself;
    3. bodies only, with then without ``end_dir`` (``clearance_kept`` False);
    4. the straight line (``enters_body`` True when it crosses a body) --
       only when even (3) has no route, which needs bodies enclosing an
       endpoint in the plane.

    Clearance exemption (R5): a body whose clearance sphere holds the start
    or the end is kept out of only halfway from its surface to that
    endpoint; a body holding an endpoint is not an obstacle at all."""
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

    def keep_outs(full_clearance):
        spheres = []
        for o in ordered:
            centre = tuple(float(v) for v in o.center)
            near = min(_norm(_sub(s3, centre)), _norm(_sub(e3, centre)))
            if near <= o.radius_gu:
                continue                     # an endpoint is inside the body
            need = o.radius_gu + (clearance_gu(o.radius_gu) if full_clearance else 0.0)
            if near < need + _ROUTE_EPS_GU:  # R5: halfway to the endpoint
                need = o.radius_gu + 0.5 * (near - o.radius_gu)
                spheres.append((centre, need, need))
            else:
                spheres.append((centre, need, need + _ROUTE_EPS_GU))
        return spheres

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

    def valid(pieces, spheres):
        return all(_min_dist(pieces, c) >= need - _tol(need)
                   for c, need, _reach in spheres)

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
