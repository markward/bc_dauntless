"""Identity and diff between Blender OBJ exports and the original NIF shapes.

Blender does not preserve vertex order across import, so identity goes by
position (POS_TOL), never by index. Between base.obj and edit.obj (both
written by Blender from the same mesh) the vertex index IS stable for
surviving vertices; diff_shape relies on that and checks it.

diff_shape records moves and UV edits; topology changes (added/removed
vertices or faces) are refused as iteration 2+."""
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


def _rotate_face(face):
    """Rotate a face's corners the same way `_face_key` rotates its vertex
    indices, so a base/edit pair sharing a key line up corner-for-corner."""
    vs = [v for v, _ in face]
    k = vs.index(min(vs))
    return face[k:] + face[:k]


UV_TOL = 1e-5


def _uv_equal(a, b):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a[0] - b[0]) <= UV_TOL and abs(a[1] - b[1]) <= UV_TOL


def _paired_faces(base_faces, edit_faces):
    """Pair each base face with its edit counterpart by the same
    rotation-invariant face-key match the topology check above already
    requires, with corners rotation-aligned so the k-th base corner lines up
    with the k-th edit corner."""
    base_sorted = sorted(((_face_key(f), _rotate_face(f)) for f in base_faces),
                         key=lambda x: x[0])
    edit_sorted = sorted(((_face_key(f), _rotate_face(f)) for f in edit_faces),
                         key=lambda x: x[0])
    return [(bf, ef) for (_, bf), (_, ef) in zip(base_sorted, edit_sorted)]


def _resolve_uv_edits(block, shape, ids, base_faces, edit_faces):
    """Record per-original-vertex UV edits (spec §5.3). obj_io.write_obj welds
    positions, so a corner's OBJ vertex may map to several original vertices
    at a seam; its UV (written per-corner, never per weld group) picks out
    which original(s) it actually is, by matching the NIF's own UV0 for that
    vertex. Refuses only a genuine vertex split: one original vertex whose
    corners disagree on the new UV (spec: "needs a vertex split")."""
    nif_uvs = shape["uvs"]
    touched = {}
    for bf, ef in _paired_faces(base_faces, edit_faces):
        for (bv, buv), (_, euv) in zip(bf, ef):
            if buv is None:
                continue
            candidates = [orig for orig in ids[bv] if _uv_equal(nif_uvs[orig], buv)]
            if not candidates:
                raise ShapeDiffError(
                    f"block {block}: OBJ vertex {bv} UV {buv} matches no original "
                    f"vertex's UV (base.obj doesn't match the NIF)")
            if euv is None:
                raise ShapeDiffError(
                    f"block {block}: OBJ vertex {bv} lost its UV in edit.obj")
            for orig in candidates:
                touched.setdefault(orig, []).append(euv)
    uvs = {}
    for orig, vals in touched.items():
        first = vals[0]
        for v in vals[1:]:
            if not _uv_equal(v, first):
                raise ShapeDiffError(
                    f"block {block}: original vertex {orig} would need two "
                    "different UVs -- that needs a vertex split (iteration 2)")
        if not _uv_equal(first, nif_uvs[orig]):
            uvs[orig] = first
    return uvs


def diff_shape(shape: dict, base, edit):
    """Diff one shape's base/edit OBJ pair: records vertex moves and UV0
    edits; refuses topology changes (added/removed vertices or faces) and a
    UV edit that would need a vertex split (both iteration 2+)."""
    block = shape["block"]
    if len(edit.positions) != len(base.positions):
        raise ShapeDiffError(
            f"block {block}: vertex count changed ({len(base.positions)} -> "
            f"{len(edit.positions)}); adding/deleting vertices is iteration 2+")
    if sorted(map(_face_key, edit.faces)) != sorted(map(_face_key, base.faces)):
        raise ShapeDiffError(
            f"block {block}: faces changed; topology edits are iteration 2 "
            f"(this iteration is moves and UV edits only)")
    ids = identify(shape, base)
    uvs = _resolve_uv_edits(block, shape, ids, base.faces, edit.faces)
    inv = frames.affine_inverse(shape["world"])
    moves = {}
    for k, (bp, ep) in enumerate(zip(base.positions, edit.positions)):
        if max(abs(a - b) for a, b in zip(bp, ep)) <= POS_TOL:
            continue
        local = frames.apply(inv, ep)
        for orig in ids[k]:
            moves[orig] = local
    if not moves and not uvs:
        return None
    return {
        "block": block,
        "orig_vertex_count": len(shape["vertices"]),
        "orig_triangle_count": len(shape["triangles"]),
        "moves": sorted(moves.items()),
        "uvs": sorted(uvs.items()),
    }


def diff(shapes: list, base_objs: dict, edit_objs: dict) -> list:
    if set(base_objs) != set(edit_objs):
        missing = sorted(set(base_objs) ^ set(edit_objs))
        raise ShapeDiffError(f"objects differ between base and edit: {missing[:5]} "
                             f"(don't join, split or rename objects)")
    block_to_names = {}
    for name in base_objs:
        block_to_names.setdefault(obj_io.block_of(name), []).append(name)
    for block, names in block_to_names.items():
        if len(names) > 1:
            raise ShapeDiffError(
                f"block {block}: two objects map to it ({sorted(names)}); "
                "importing the same OBJ twice duplicates its objects as "
                "'<name>.001' -- delete the duplicate before diffing")
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
