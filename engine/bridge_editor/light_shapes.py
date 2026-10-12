"""Lights with size (spec 2026-10-08-bridge-emitters §16.2): an object's
front rectangle, and the strip / panel rectangles cut from it. Pure Python;
the geometry comes from host_io.bridge_mesh_geometry. Nothing here is
stored: the file holds only parameters, so a light follows its object
through mesh fixes and shape-diff edits."""
import math
from dataclasses import dataclass, field
from typing import Optional, Tuple

Vec = Tuple[float, float, float]

ROOM_UP: Vec = (0.0, 0.0, 1.0)      # renderer::kBridgeUp
STRIP_WIDTH = 0.5                   # bridge units; an engine constant, not edited
NO_FACING = 0.05                    # normal sum below this x area: a closed shape
VERTICAL_DEG = 25.0                 # facing this close to +-Z: a ceiling / floor piece

# SPIKE (edge snap, 2026-10-12): a strip with an `anchor` (a clicked point)
# sits on the mesh's sharp edge nearest it instead of the front rectangle's.
# Tuned on DBridge's Map 3 walls: once their double-sided duplicate triangles
# are dropped, the alcove lips are crease runs of 7-10 vertices that follow
# the curved wall, so the run is kept as a polyline of a few segments.
CREASE_DEG = 30.0                   # faces meeting at more than this: a sharp edge
STRAIGHT_DEG = 20.0                 # a run continues while it turns less than this
SNAP_REACH = 20.0                   # bridge units: no sharp edge this near = no snap
SNAP_TIE = 2.0                      # edges this much further than the nearest still compete
SIMPLIFY_TOL = 0.5                  # a polyline vertex is kept if this far off the chord
MAX_SEGMENTS = 6                    # each segment is one area light
WASH_DEPTH = 10.0                   # a snapped strip aims this far in across the surface


def _add(a, b): return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def _sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def _mul(a, k): return (a[0] * k, a[1] * k, a[2] * k)
def _dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def _len(a): return math.sqrt(_dot(a, a))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(a) -> Optional[Vec]:
    n = _len(a)
    return _mul(a, 1.0 / n) if n > 1e-9 else None


def _horizontal(a) -> Optional[Vec]:
    return _unit((a[0], a[1], 0.0))


@dataclass(frozen=True)
class Frame:
    right: Vec
    up: Vec
    facing: Vec
    centre: Vec      # the object's box centre, world
    half: Vec        # half-extents along (right, up, facing)
    # SPIKE (edge snap): the triangles and eye the frame was built from, and
    # a per-frame memo (the snapped edges are recomputed per frame otherwise).
    vertices: tuple = field(default=(), compare=False, repr=False)
    eye: Vec = field(default=(0.0, 0.0, 0.0), compare=False, repr=False)
    cache: dict = field(default_factory=dict, compare=False, repr=False)


@dataclass(frozen=True)
class Rect:
    centre: Vec
    half_u: Vec
    half_v: Vec      # cross(half_u, half_v) points where it emits

    @property
    def normal(self) -> Vec:
        return _unit(_cross(self.half_u, self.half_v)) or (0.0, 0.0, 0.0)


def oriented_normal_sum(vertices, eye) -> Vec:
    """Sum of per-triangle normals, each oriented toward the eye (spec
    ruling, review item 2): DBridge's winding is mixed (measured: 3/145
    shapes fall to "no facing", 26 have raw normal sums < 0.8 of this sum),
    which is why bridge.frag's shading_normal() already flips per-pixel
    normals toward the viewer. `vertices` are consecutive triangles (a, b,
    c); for each, n = cross(b - a, c - a) / 2, negated toward the eye when
    it points away from it. A trailing partial triangle is ignored."""
    total = (0.0, 0.0, 0.0)
    for i in range(0, len(vertices) - 2, 3):
        a, b, c = vertices[i], vertices[i + 1], vertices[i + 2]
        n = _mul(_cross(_sub(b, a), _sub(c, a)), 0.5)
        centroid = _mul(_add(_add(a, b), c), 1.0 / 3.0)
        if _dot(n, _sub(eye, centroid)) < 0.0:
            n = _mul(n, -1.0)
        total = _add(total, n)
    return total


def frame(vertices, normal_sum, area, eye) -> Optional[Frame]:
    """The object's frame: facing = its area-weighted normal; up = room up
    without its facing part; right = up x facing (the viewer's right, seen
    from the front). A closed shape (normals cancel) faces the eye; a piece
    within VERTICAL_DEG of +-Z tops on its edge farther from the eye."""
    if not vertices:
        return None
    lo = [min(v[i] for v in vertices) for i in range(3)]
    hi = [max(v[i] for v in vertices) for i in range(3)]
    mid = tuple((lo[i] + hi[i]) / 2.0 for i in range(3))
    n = tuple(float(c) for c in normal_sum)
    if area > 0.0 and _len(n) >= NO_FACING * area:
        facing = _unit(n)
    else:
        facing = _horizontal(_sub(eye, mid)) or (0.0, -1.0, 0.0)
    if abs(_dot(facing, ROOM_UP)) > math.cos(math.radians(VERTICAL_DEG)):
        hint = _horizontal(_sub(mid, eye)) or (0.0, 1.0, 0.0)
    else:
        hint = ROOM_UP
    up = _unit(_sub(hint, _mul(facing, _dot(hint, facing))))
    if up is None:          # cannot happen for the hints above; keep a frame anyway
        up = _unit(_cross(facing, (1.0, 0.0, 0.0))) or (0.0, 1.0, 0.0)
    right = _cross(up, facing)
    axes = (right, up, facing)
    proj = [[_dot(v, a) for a in axes] for v in vertices]
    plo = [min(p[i] for p in proj) for i in range(3)]
    phi = [max(p[i] for p in proj) for i in range(3)]
    centre = (0.0, 0.0, 0.0)
    for i in range(3):
        centre = _add(centre, _mul(axes[i], (plo[i] + phi[i]) / 2.0))
    half = tuple((phi[i] - plo[i]) / 2.0 for i in range(3))
    return Frame(right, up, facing, centre, half,
                 vertices=tuple(tuple(v) for v in vertices), eye=tuple(eye))


def _front(fr) -> Vec:
    return _add(fr.centre, _mul(fr.facing, fr.half[2]))


def strip_rect(fr, edge, start=0.0, end=1.0, offset=0.0) -> Rect:
    """That edge of the front rectangle, cut to [start, end] (0 = the left /
    bottom end), moved out along facing by `offset`, STRIP_WIDTH wide. It
    faces the box centre with its along-edge part removed: perpendicular to
    the edge, toward the centre on average."""
    hr, hu, _hf = fr.half
    if edge in ("top", "bottom"):
        axis, span = fr.right, hr
        across = _mul(fr.up, hu if edge == "top" else -hu)
    else:
        axis, span = fr.up, hu
        across = _mul(fr.right, hr if edge == "right" else -hr)
    mid = (start + end) / 2.0
    c = _add(_add(_front(fr), across), _mul(axis, span * (2.0 * mid - 1.0)))
    c = _add(c, _mul(fr.facing, offset))
    to_centre = _sub(fr.centre, c)
    n = _unit(_sub(to_centre, _mul(axis, _dot(to_centre, axis)))) or fr.facing
    width = _cross(n, axis)
    return Rect(c, _mul(axis, span * (end - start)), _mul(width, STRIP_WIDTH / 2.0))


def panel_rect(fr, x=(0.0, 1.0), y=(0.0, 1.0), offset=0.0) -> Rect:
    """The x by y span of the front rectangle (0 = left / bottom), moved out
    along facing by `offset`, facing out."""
    hr, hu, hf = fr.half
    c = _add(fr.centre, _mul(fr.facing, hf + offset))
    c = _add(c, _mul(fr.right, hr * (x[0] + x[1] - 1.0)))
    c = _add(c, _mul(fr.up, hu * (y[0] + y[1] - 1.0)))
    return Rect(c, _mul(fr.right, hr * (x[1] - x[0])), _mul(fr.up, hu * (y[1] - y[0])))


def light_rect(light, fr) -> Rect:
    off = float(light.get("offset", 0.0))
    if light.get("shape") == "strip":
        return strip_rect(fr, light["edge"], float(light.get("start", 0.0)),
                          float(light.get("end", 1.0)), off)
    x = light.get("x", (0.0, 1.0))
    y = light.get("y", (0.0, 1.0))
    return panel_rect(fr, (float(x[0]), float(x[1])), (float(y[0]), float(y[1])), off)


# ── SPIKE: snap a strip to the sharp edge nearest a clicked point ───────────

def _welded(vertices, eye):
    """(points, triangles, normals): vertices welded at 0.01 units, degenerate
    and duplicate triangles dropped (DBridge walls carry a back-facing copy of
    every face), each normal oriented toward the eye."""
    index, pts, tris, seen = {}, [], [], set()
    for i in range(0, len(vertices) - 2, 3):
        t = []
        for p in vertices[i:i + 3]:
            k = (round(p[0], 2), round(p[1], 2), round(p[2], 2))
            if k not in index:
                index[k] = len(pts)
                pts.append(tuple(p))
            t.append(index[k])
        if len(set(t)) == 3 and frozenset(t) not in seen:
            seen.add(frozenset(t))
            tris.append(tuple(t))
    normals = []
    for a, b, c in tris:
        n = _unit(_cross(_sub(pts[b], pts[a]), _sub(pts[c], pts[a])))
        if n is not None:
            centroid = _mul(_add(_add(pts[a], pts[b]), pts[c]), 1.0 / 3.0)
            if _dot(n, _sub(eye, centroid)) < 0.0:
                n = _mul(n, -1.0)
        normals.append(n)
    return pts, tris, normals


def _sharp_edges(pts, tris, normals):
    """{(i, j): None} for every open edge and every edge whose faces meet at
    more than CREASE_DEG; plus the vertex adjacency over those edges."""
    faces = {}
    for f, (a, b, c) in enumerate(tris):
        for u, w in ((a, b), (b, c), (c, a)):
            faces.setdefault((min(u, w), max(u, w)), []).append(f)
    cos_crease = math.cos(math.radians(CREASE_DEG))
    sharp = set()
    for e, fs in faces.items():
        ns = [normals[f] for f in fs if normals[f] is not None]
        if len(fs) == 1 or any(_dot(x, y) < cos_crease for x in ns for y in ns):
            sharp.add(e)
    adj = {}
    for u, w in sharp:
        adj.setdefault(u, []).append(w)
        adj.setdefault(w, []).append(u)
    return sharp, adj


def _closest_on_segment(p, a, b):
    ab = _sub(b, a)
    t = _dot(_sub(p, a), ab) / max(_dot(ab, ab), 1e-12)
    return _add(a, _mul(ab, min(1.0, max(0.0, t))))


def _surface_normal(p, pts, tris, normals):
    """The oriented normal of the triangle under `p` (the clicked one): the
    triangle whose plane is nearest among those `p` projects inside; else the
    triangle with the nearest centroid."""
    best, best_d = None, float("inf")
    for (a, b, c), n in zip(tris, normals):
        if n is None:
            continue
        d = abs(_dot(_sub(p, pts[a]), n))
        q = _sub(p, _mul(n, _dot(_sub(p, pts[a]), n)))
        inside = all(_dot(_cross(_sub(pts[v], pts[u]), _sub(q, pts[u])), n) >= -1e-6
                     for u, v in ((a, b), (b, c), (c, a)))
        if inside and d < best_d:
            best, best_d = n, d
    if best is not None:
        return best
    cen = lambda t: _mul(_add(_add(pts[t[0]], pts[t[1]]), pts[t[2]]), 1.0 / 3.0)
    pairs = [(n, _len(_sub(p, cen(t)))) for t, n in zip(tris, normals) if n is not None]
    return min(pairs, key=lambda x: x[1])[0] if pairs else None


def _walk(pts, adj, sharp, seed):
    """The run of sharp edges through `seed`, extended at each end while it
    turns less than STRAIGHT_DEG: a list of point indices."""
    chain, used = [seed[0], seed[1]], {seed}
    cos_straight = math.cos(math.radians(STRAIGHT_DEG))
    for at_end in (True, False):
        while True:
            tip, prev = (chain[-1], chain[-2]) if at_end else (chain[0], chain[1])
            heading = _unit(_sub(pts[tip], pts[prev]))
            best, best_c = None, cos_straight
            for nb in adj.get(tip, ()):
                e = (min(tip, nb), max(tip, nb))
                d = _unit(_sub(pts[nb], pts[tip]))
                if e in used or d is None or heading is None:
                    continue
                c = _dot(d, heading)
                if c > best_c:
                    best, best_c = nb, c
            if best is None:
                break
            used.add((min(tip, best), max(tip, best)))
            if at_end:
                chain.append(best)
            else:
                chain.insert(0, best)
    return chain


def _simplify(points, tol):
    """Douglas-Peucker: the polyline's vertices further than `tol` from the
    chord between their neighbours."""
    if len(points) < 3:
        return list(points)
    a, b = points[0], points[-1]
    far, far_d = 0, -1.0
    for i in range(1, len(points) - 1):
        d = _len(_sub(points[i], _closest_on_segment(points[i], a, b)))
        if d > far_d:
            far, far_d = i, d
    if far_d <= tol:
        return [a, b]
    return _simplify(points[:far + 1], tol)[:-1] + _simplify(points[far:], tol)


def snap_edge(fr, anchor):
    """(polyline, surface_normal) of the sharp-edge run nearest `anchor` on
    the frame's mesh -- the polyline ordered left to right as seen from the
    clicked surface (bottom to top for an upright edge) and simplified to at
    most MAX_SEGMENTS segments -- or None when no sharp edge is within
    SNAP_REACH. Memoised on the frame."""
    key = ("snap", tuple(anchor))
    if key in fr.cache:
        return fr.cache[key]
    if "mesh" not in fr.cache:
        pts, tris, normals = _welded(fr.vertices, fr.eye)
        fr.cache["mesh"] = (pts, tris, normals) + _sharp_edges(pts, tris, normals)
    pts, tris, normals, sharp, adj = fr.cache["mesh"]
    anchor = tuple(float(c) for c in anchor)
    dist = {e: _len(_sub(anchor, _closest_on_segment(anchor, pts[e[0]], pts[e[1]])))
            for e in sharp}
    near = min(dist.values(), default=SNAP_REACH)
    # Among the edges about as near as the nearest, the longest run wins: a
    # click by an alcove's top lip must not snap to the short fillet at its
    # corner, which is often a hair nearer.
    best = None
    for e, d in dist.items():
        if d <= min(near + SNAP_TIE, SNAP_REACH):
            chain = _walk(pts, adj, sharp, e)
            length = sum(_len(_sub(pts[chain[i + 1]], pts[chain[i]]))
                         for i in range(len(chain) - 1))
            if best is None or length > best[0]:
                best = (length, chain)
    ns = _surface_normal(anchor, pts, tris, normals) if best else None
    if best is None or ns is None:
        fr.cache[key] = None
        return None
    poly = [pts[i] for i in best[1]]
    tol = SIMPLIFY_TOL
    simple = _simplify(poly, tol)
    while len(simple) - 1 > MAX_SEGMENTS:
        tol *= 2.0
        simple = _simplify(poly, tol)
    up = _unit(_sub(ROOM_UP, _mul(ns, _dot(ROOM_UP, ns)))) or (0.0, 1.0, 0.0)
    right = _cross(up, ns)
    run = _sub(simple[-1], simple[0])
    lean = _dot(run, right) if abs(_dot(_unit(run) or up, up)) < 0.7 else _dot(run, up)
    if lean < 0.0:
        simple.reverse()
    fr.cache[key] = (simple, ns)
    return fr.cache[key]


def _cut(poly, start, end):
    """The part of the polyline between fractions `start` and `end` of its
    length."""
    lengths = [_len(_sub(poly[i + 1], poly[i])) for i in range(len(poly) - 1)]
    total = sum(lengths)
    if total <= 0.0:
        return []

    def at(s):
        s *= total
        for i, L in enumerate(lengths):
            if s <= L or i == len(lengths) - 1:
                return i, _add(poly[i], _mul(_sub(poly[i + 1], poly[i]), min(1.0, s / max(L, 1e-12))))
            s -= L
    i0, p0 = at(start)
    i1, p1 = at(end)
    return [p0] + list(poly[i0 + 1:i1 + 1]) + [p1]


def snapped_strip_rects(fr, light):
    """The rectangles of a strip snapped to the edge nearest its `anchor`,
    one per polyline segment, or None when there is no edge to snap to. Each
    sits on its segment, moved out along the clicked surface by `offset`,
    and aims at the clicked surface WASH_DEPTH in from the edge."""
    snap = snap_edge(fr, light["anchor"])
    if snap is None:
        return None
    poly, ns = snap
    part = _cut(poly, float(light.get("start", 0.0)), float(light.get("end", 1.0)))
    anchor = tuple(float(c) for c in light["anchor"])
    nearest = min(range(len(poly) - 1), key=lambda i: _len(_sub(
        anchor, _closest_on_segment(anchor, poly[i], poly[i + 1]))))
    d0 = _unit(_sub(poly[nearest + 1], poly[nearest])) or (1.0, 0.0, 0.0)
    side = 1.0 if _dot(_cross(ns, d0), _sub(anchor, _closest_on_segment(
        anchor, poly[nearest], poly[nearest + 1]))) >= 0.0 else -1.0
    offset = float(light.get("offset", 0.0))
    rects = []
    for a, b in zip(part, part[1:]):
        d = _unit(_sub(b, a))
        if d is None:
            continue
        across = _unit(_mul(_cross(ns, d), side)) or ns
        mid = _mul(_add(a, b), 0.5)
        c = _add(mid, _mul(ns, offset))
        aim = _sub(_add(mid, _mul(across, WASH_DEPTH)), c)
        n = _unit(_sub(aim, _mul(d, _dot(aim, d)))) or across
        rects.append(Rect(c, _mul(d, _len(_sub(b, a)) / 2.0),
                          _mul(_cross(n, d), STRIP_WIDTH / 2.0)))
    return rects


def light_rects(light, fr):
    """Every rectangle a strip or panel light is drawn as: a snapped strip
    gives one per edge segment (or falls back to its edge chips when nothing
    is in reach), anything else exactly one."""
    if light.get("shape") == "strip" and light.get("anchor") and fr.vertices:
        rects = snapped_strip_rects(fr, light)
        if rects is not None:
            return rects
    return [light_rect(light, fr)]
