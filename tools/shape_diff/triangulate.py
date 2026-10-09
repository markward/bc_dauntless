"""Ear clipping for added n-gon faces (spec §5.3). Ported from the parked
spike (spike/bridge-lighting-vfx: tools/bridge_meshgen/obj_import.py), with
one change: where the spike fell back to a fan on a polygon it couldn't clip,
this refuses -- a fan over a self-intersecting or degenerate polygon would
put triangles outside the face Mark drew."""
from tools.shape_diff import ShapeDiffError

_EPS = 1e-12


def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _inside(p, a, b, c):
    """p in triangle abc, boundary included."""
    d1, d2, d3 = _cross(a, b, p), _cross(b, c, p), _cross(c, a, p)
    neg = d1 < 0 or d2 < 0 or d3 < 0
    pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (neg and pos)


def ear_clip(pts):
    """Triangulate a simple planar polygon (3D points, any winding) by ear
    clipping in its dominant projection plane. Returns index triples that
    keep the polygon's winding. Raises ShapeDiffError when the polygon is
    degenerate or not simple (no ear, or ears that don't tile its area)."""
    n = len(pts)
    if n < 3:
        raise ShapeDiffError(f"a {n}-corner face can't be triangulated")
    if n == 3:
        return [(0, 1, 2)]
    # Newell normal -> drop the dominant axis
    nx = ny = nz = 0.0
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        nx += (a[1] - b[1]) * (a[2] + b[2])
        ny += (a[2] - b[2]) * (a[0] + b[0])
        nz += (a[0] - b[0]) * (a[1] + b[1])
    normal = (nx, ny, nz)
    ax = max(range(3), key=lambda k: abs(normal[k]))
    if abs(normal[ax]) <= _EPS:
        raise ShapeDiffError("a face with no area (self-intersecting or flat) can't be triangulated")
    keep = [k for k in range(3) if k != ax]
    sign = 1.0 if normal[ax] >= 0 else -1.0
    if ax == 1:
        sign = -sign  # dropping Y flips the handedness of (x, z)
    P = [(p[keep[0]], p[keep[1]]) for p in pts]
    idx = list(range(n))
    out = []
    while len(idx) > 3:
        for k in range(len(idx)):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            if sign * _cross(P[i0], P[i1], P[i2]) <= _EPS:
                continue  # reflex or degenerate corner
            if any(_inside(P[j], P[i0], P[i1], P[i2]) for j in idx if j not in (i0, i1, i2)):
                continue
            out.append((i0, i1, i2))
            idx.pop(k)
            break
        else:
            raise ShapeDiffError(
                f"a {n}-corner face can't be triangulated (no ear: self-intersecting?)")
    if sign * _cross(P[idx[0]], P[idx[1]], P[idx[2]]) <= _EPS:
        raise ShapeDiffError(f"a {n}-corner face can't be triangulated (degenerate last ear)")
    out.append((idx[0], idx[1], idx[2]))
    # The ears of a simple polygon tile it exactly; anything else overlaps.
    area = sum(abs(_cross(P[a], P[b], P[c])) for a, b, c in out) / 2
    if abs(area - abs(normal[ax]) / 2) > 1e-9 * max(1.0, area):
        raise ShapeDiffError(
            f"a {n}-corner face can't be triangulated (it overlaps itself)")
    return out
