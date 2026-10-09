"""Identity and diff between Blender OBJ exports and the original NIF shapes.

Blender does not preserve vertex order across import, so identity goes by
position (POS_TOL), never by index. Between base.obj and edit.obj (both
written by Blender from the same mesh) the vertex index IS stable for
surviving vertices; diff_shape relies on that and checks it."""
from tools.shape_diff import ShapeDiffError, frames, obj_io

POS_TOL = 1e-4
_CELL = 1e-3   # spatial hash cell; > POS_TOL so a 3x3x3 probe suffices


def _grid(points):
    g = {}
    for i, p in enumerate(points):
        g.setdefault(tuple(int(c // _CELL) for c in p), []).append(i)
    return g


def _near(grid, points, p):
    cx, cy, cz = (int(c // _CELL) for c in p)
    out = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                for i in grid.get((cx + dx, cy + dy, cz + dz), ()):
                    q = points[i]
                    if max(abs(q[0] - p[0]), abs(q[1] - p[1]), abs(q[2] - p[2])) <= POS_TOL:
                        out.append(i)
    return sorted(out)


def identify(shape: dict, mesh) -> list:
    pts = shape["vertices"]
    grid = _grid(pts)
    ids = []
    for k, p in enumerate(mesh.positions):
        found = _near(grid, pts, p)
        if not found:
            raise ShapeDiffError(
                f"block {shape['block']}: OBJ vertex {k} at {p} matches no original "
                f"vertex (was base.obj exported unaltered with default axes?)")
        ids.append(found)
    return ids


def _face_key(face):
    """Rotation-invariant, winding-preserving key over vertex indices."""
    vs = [v for v, _ in face]
    k = vs.index(min(vs))
    return tuple(vs[k:] + vs[:k])


def diff_shape(shape: dict, base, edit):
    block = shape["block"]
    if len(edit.positions) != len(base.positions):
        raise ShapeDiffError(
            f"block {block}: vertex count changed ({len(base.positions)} -> "
            f"{len(edit.positions)}); adding/deleting vertices is iteration 2+")
    if sorted(map(_face_key, edit.faces)) != sorted(map(_face_key, base.faces)):
        raise ShapeDiffError(
            f"block {block}: faces changed; topology edits are iteration 2 "
            f"(this iteration is move-only)")
    ids = identify(shape, base)
    inv = frames.affine_inverse(shape["world"])
    moves = {}
    for k, (bp, ep) in enumerate(zip(base.positions, edit.positions)):
        if max(abs(a - b) for a, b in zip(bp, ep)) <= POS_TOL:
            continue
        local = frames.apply(inv, ep)
        for orig in ids[k]:
            moves[orig] = local
    if not moves:
        return None
    return {
        "block": block,
        "orig_vertex_count": len(shape["vertices"]),
        "orig_triangle_count": len(shape["triangles"]),
        "moves": sorted(moves.items()),
    }


def diff(shapes: list, base_objs: dict, edit_objs: dict) -> list:
    if set(base_objs) != set(edit_objs):
        missing = sorted(set(base_objs) ^ set(edit_objs))
        raise ShapeDiffError(f"objects differ between base and edit: {missing[:5]} "
                             f"(don't join, split or rename objects)")
    by_block = {s["block"]: s for s in shapes}
    edits = []
    for name in sorted(base_objs, key=obj_io.block_of):
        block = obj_io.block_of(name)
        if block not in by_block:
            raise ShapeDiffError(f"object {name}: block {block} is not a shape in this NIF")
        e = diff_shape(by_block[block], base_objs[name], edit_objs[name])
        if e is not None:
            edits.append(e)
    return edits
