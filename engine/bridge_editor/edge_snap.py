"""Edge snap (spec 2026-10-08-bridge-emitters §16.8): a strip with an
`anchor` (the clicked point) sits on the mesh's sharp edge nearest it,
instead of the object's box edge -- compound meshes such as DBridge's Map 3
walls hold several alcoves in one shape, so no box edge reaches an alcove's
lip. Pure Python; the triangles and eye come from the object's
light_shapes.Frame, and every result is memoised on it."""
import math
from dataclasses import dataclass
from typing import List, Optional

from engine.bridge_editor.light_shapes import (
    ROOM_UP, STRIP_WIDTH, VERTICAL_DEG, Rect, Vec, _add, _cross, _dot, _horizontal, _len, _mul,
    _sub, _unit, light_rect)

CREASE_DEG = 30.0                   # faces meeting at more than this: a sharp edge
STRAIGHT_DEG = 20.0                 # a run continues while it turns less than this
SNAP_REACH = 20.0                   # bridge units: no sharp edge this near = no snap
SNAP_TIE = 2.0                      # edges this much further than the nearest still compete
SIMPLIFY_TOL = 0.5                  # a polyline vertex is kept if this far off the chord
MAX_SEGMENTS = 6                    # each segment is one area light
WASH_DEPTH = 10.0                   # a snapped strip aims this far in across the surface


@dataclass(frozen=True)
class Snap:
    polyline: List[Vec]             # left to right as seen from the clicked surface
    surface_normal: Vec             # the clicked surface, facing the eye


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
    triangle with the nearest centroid. The inside test is sign-agnostic
    (every edge term >= -eps, OR every term <= eps): `_welded` orients each
    triangle's STORED normal toward the eye but never touches its vertex
    order, so a kept triangle whose winding was the back-facing copy has a
    normal that points opposite its own winding -- a point truly inside it
    then gives every term NEGATIVE, not positive."""
    best, best_d = None, float("inf")
    for (a, b, c), n in zip(tris, normals):
        if n is None:
            continue
        d = abs(_dot(_sub(p, pts[a]), n))
        q = _sub(p, _mul(n, _dot(_sub(p, pts[a]), n)))
        terms = [_dot(_cross(_sub(pts[v], pts[u]), _sub(q, pts[u])), n)
                 for u, v in ((a, b), (b, c), (c, a))]
        inside = all(t >= -1e-6 for t in terms) or all(t <= 1e-6 for t in terms)
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


def snap(fr, anchor) -> Optional[Snap]:
    """The Snap of the sharp-edge run nearest `anchor` on the frame's mesh --
    its polyline ordered left to right as seen from the clicked surface
    (bottom to top for an upright edge) and simplified to at most
    MAX_SEGMENTS segments -- or None when no sharp edge is within
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
    # frame()'s own rule for ordering: a near-horizontal surface (ceiling or
    # floor) uses the horizontal direction from the eye to the run's
    # midpoint as its hint, not ROOM_UP -- ROOM_UP projected onto a flat
    # ceiling/floor is always degenerate regardless of where the eye is, so
    # using it directly (falling back to a FIXED (0, 1, 0) only in that
    # degenerate case) ignored the eye's side of the room entirely.
    if abs(_dot(ns, ROOM_UP)) > math.cos(math.radians(VERTICAL_DEG)):
        mid = _mul(_add(simple[0], simple[-1]), 0.5)
        hint = _horizontal(_sub(mid, fr.eye)) or (0.0, 1.0, 0.0)
    else:
        hint = ROOM_UP
    up = _unit(_sub(hint, _mul(ns, _dot(hint, ns)))) or (0.0, 1.0, 0.0)
    right = _cross(up, ns)
    run = _sub(simple[-1], simple[0])
    lean = _dot(run, right) if abs(_dot(_unit(run) or up, up)) < 0.7 else _dot(run, up)
    if lean < 0.0:
        simple.reverse()
    fr.cache[key] = Snap(simple, ns)
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


def strip_rects(fr, light) -> Optional[List[Rect]]:
    """The rectangles of a strip snapped to the edge nearest its `anchor`,
    one per polyline segment, or None when there is no edge to snap to. Each
    sits on its segment, moved out along the clicked surface by `offset`,
    and aims at the clicked surface WASH_DEPTH in from the edge."""
    s = snap(fr, light["anchor"])
    if s is None:
        return None
    poly, ns = s.polyline, s.surface_normal
    part = _cut(poly, float(light.get("start", 0.0)), float(light.get("end", 1.0)))
    anchor = tuple(float(c) for c in light["anchor"])
    nearest = min(range(len(poly) - 1), key=lambda i: _len(_sub(
        anchor, _closest_on_segment(anchor, poly[i], poly[i + 1]))))
    d0 = _unit(_sub(poly[nearest + 1], poly[nearest])) or (1.0, 0.0, 0.0)
    side = 1.0 if _dot(_cross(ns, d0), _sub(anchor, _closest_on_segment(
        anchor, poly[nearest], poly[nearest + 1]))) >= 0.0 else -1.0
    offset = float(light.get("offset", 0.0))
    rects = []
    segments = [(a, b) for a, b in zip(part, part[1:]) if _unit(_sub(b, a)) is not None]
    for k, (a, b) in enumerate(segments):
        d = _unit(_sub(b, a))
        if d is None:
            continue
        across = _unit(_mul(_cross(ns, d), side)) or ns
        mid = _mul(_add(a, b), 0.5)
        c = _add(mid, _mul(ns, offset))
        aim = _sub(_add(mid, _mul(across, WASH_DEPTH)), c)
        n = _unit(_sub(aim, _mul(d, _dot(aim, d)))) or across
        joins = (1 if k > 0 else 0) | (2 if k < len(segments) - 1 else 0)
        rects.append(Rect(c, _mul(d, _len(_sub(b, a)) / 2.0),
                          _mul(_cross(n, d), STRIP_WIDTH / 2.0), joins))
    return rects


def light_rects(light, fr):
    """Every rectangle a strip or panel light is drawn as: a snapped strip
    gives one per edge segment (or falls back to its edge chips when nothing
    is in reach), anything else exactly one."""
    if light.get("shape") == "strip" and light.get("anchor") and fr.vertices:
        rects = strip_rects(fr, light)
        if rects is not None:
            return rects
    return [light_rect(light, fr)]
