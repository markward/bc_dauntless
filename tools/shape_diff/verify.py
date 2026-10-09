"""Verify a shape-diff fix by applying it (spec §5.4): the loader's own
parse + apply (`_dauntless_host.nif_shapes(path, fix_json)`) must turn the
stock NIF into exactly what edit.obj shows, and touch nothing else.

Triangles compare as corner tuples: model-space position snapped to the
1/1024 weld grid and UV0 to 1e-5, rotated to start at the smallest corner,
degenerate ones dropped. Blender keeps one face per vertex set (it collapses
NIF duplicates, reversed twins and seam twins), so triangles are grouped by
their position set: every edit triangle must be one of the applied
triangles of its set, and the sets must agree both ways. A corner a grid
step or UV step away (rounding across a cell boundary) still matches."""
from tools.shape_diff import ShapeDiffError, triangulate

_GRID = 1024.0
_UVQ = 1e5


def _host():
    try:
        import _dauntless_host
    except ImportError:
        return None
    return _dauntless_host


def _corner(p, uv):
    q = tuple(round(c * _GRID) for c in p)
    return (q, None if uv is None else (round(uv[0] * _UVQ), round(uv[1] * _UVQ)))


def _canon(corners):
    if len({c[0] for c in corners}) < 3:
        return None
    k = min(range(3), key=lambda i: corners[i][0])
    return tuple(corners[k:] + corners[:k])


def _shape_triangles(shape):
    pts, uvs = shape["vertices"], shape["uvs"]
    for tri in shape["triangles"]:
        t = _canon([_corner(pts[i], uvs[i] if i < len(uvs) else None) for i in tri])
        if t is not None:
            yield t


def _mesh_triangles(mesh):
    for f in mesh.faces:
        pts = [mesh.positions[v] for v, _ in f]
        for a, b, c in triangulate.ear_clip(pts):
            t = _canon([_corner(mesh.positions[f[i][0]], f[i][1]) for i in (a, b, c)])
            if t is not None:
                yield t


def _groups(tris):
    out = {}
    for t in tris:
        out.setdefault(frozenset(c[0] for c in t), set()).add(t)
    return out


def _close(t, u):
    """Same triangle up to one grid/UV step per coordinate, same winding."""
    for r in range(3):
        v = u[r:] + u[:r]
        if all(max(abs(a - b) for a, b in zip(c[0], d[0])) <= 1
               and (c[1] is None) == (d[1] is None)
               and (c[1] is None or max(abs(a - b) for a, b in zip(c[1], d[1])) <= 1)
               for c, d in zip(t, v)):
            return True
    return False


def _show(t):
    return "(" + ", ".join(
        f"{tuple(round(x / _GRID, 4) for x in c[0])} uv "
        f"{None if c[1] is None else tuple(x / _UVQ for x in c[1])}" for c in t) + ")"


def _compare(name, applied, edit_mesh):
    a, e = _groups(_shape_triangles(applied)), _groups(_mesh_triangles(edit_mesh))
    missing = [t for k, ts in e.items() for t in sorted(ts) if k not in a or t not in a[k]]
    extra_keys = [k for k in a if k not in e]
    spare = [t for k in extra_keys for t in a[k]]
    for t in missing:
        near = [k for k in a if any(_close(t, u) for u in a[k])]
        if not near:
            raise ShapeDiffError(
                f"verify: {name}: the applied fix lacks edit triangle {_show(t)}")
        for k in near:
            if k in extra_keys:
                extra_keys.remove(k)
    spare = [t for k in extra_keys for t in sorted(a[k])]
    for t in spare:
        if not any(_close(t, u) for ts in e.values() for u in ts):
            raise ShapeDiffError(
                f"verify: {name}: the applied fix keeps triangle {_show(t)}, "
                "which edit.obj doesn't have")


def check(stock_shapes, applied_shapes, edited, albedos=None):
    """`edited`: block -> (object name, edit ObjMesh) for every block the
    fix touches; `albedos`: block -> texture name its texture op sets.
    Raises ShapeDiffError on the first difference; returns len(edited)."""
    stock = {s["block"]: s for s in stock_shapes}
    applied = {s["block"]: s for s in applied_shapes}
    if set(stock) != set(applied):
        raise ShapeDiffError("verify: the applied fix changed the set of shapes")
    for block, s in stock.items():
        if block not in edited and applied[block] != s:
            raise ShapeDiffError(f"verify: block {block} changed but is not in the fix")
    for block, (name, mesh) in sorted(edited.items()):
        _compare(name, applied[block], mesh)
        want = (albedos or {}).get(block)
        if want is not None and want not in applied[block]["textures"]:
            raise ShapeDiffError(f"verify: {name}: texture {want} did not bind")
    return len(edited)


def run(nif_path, fix_json, stock_shapes, edited, albedos=None):
    """Apply `fix_json` to `nif_path` with the loader and `check` it."""
    host = _host()
    if host is None:
        raise ShapeDiffError(
            "can't verify the fix: _dauntless_host is not importable -- build it "
            "(cmake --build build -j); verification is never skipped on the CLI")
    try:
        applied = host.nif_shapes(str(nif_path), fix_json)
    except RuntimeError as exc:
        raise ShapeDiffError(f"verify: the loader refuses this fix: {exc}") from None
    if applied is None:
        raise ShapeDiffError(f"verify: cannot read {nif_path}")
    return check(stock_shapes, applied, edited, albedos)
