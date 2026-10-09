"""Identity and diff between Blender OBJ exports and the original NIF shapes.

Blender does not preserve vertex order across import, so identity goes by
position (POS_TOL), never by index. Between base.obj and edit.obj (both
written by Blender from the same mesh) surviving vertices keep their
relative order: by index when no vertex was deleted, else by an
order-preserving alignment on unmoved positions (`_correspondence`).

diff_shape records moves, UV edits, removed faces (every NIF triangle on the
face's welded vertex set, duplicates and reversed twins included) and added
triangles on existing original vertices/UVs. New vertices, new UVs on an
added face, a vertex split and a flipped existing face are refused."""
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


def _correspondence(block, base, edit):
    """edit vertex index -> base vertex index. Equal counts: by index.
    Fewer edit vertices: Blender deleted some and kept the survivors'
    relative order, so walk both in order, skipping base vertices until one
    sits at the edit vertex's position."""
    nb, ne = len(base.positions), len(edit.positions)
    if ne > nb:
        raise ShapeDiffError(
            f"block {block}: vertex count grew ({nb} -> {ne}); "
            "new vertices are iteration 3")
    if ne == nb:
        return list(range(nb))
    corr = []
    b = 0
    for ep in edit.positions:
        while b < nb and max(abs(x - y) for x, y in zip(base.positions[b], ep)) > POS_TOL:
            b += 1
        if b == nb:
            raise ShapeDiffError(
                f"block {block}: can't align vertices after deletion (a surviving "
                "vertex moved, or vertices were added) -- not supported yet")
        corr.append(b)
        b += 1
    return corr


def _by_vertex_set(faces):
    out = {}
    for f in faces:
        out.setdefault(frozenset(v for v, _ in f), []).append(f)
    return out


def _removed_triangles(block, shape, ids, removed_sets):
    """Every NIF triangle whose three vertices lie in three distinct corners'
    weld groups of a removed face. write_obj exports exactly those triangles
    onto that face (Blender then collapses duplicates and reversed twins into
    it), so all of them go -- whatever their winding or UVs."""
    tris_of = {}
    for t, tri in enumerate(shape["triangles"]):
        for v in tri:
            tris_of.setdefault(v, set()).add(t)
    out = set()
    for vset in removed_sets:
        corner_of = {}
        for c, bv in enumerate(sorted(vset)):
            for orig in ids[bv]:
                corner_of.setdefault(orig, set()).add(c)
        found = set()
        for orig in corner_of:
            for t in tris_of.get(orig, ()):
                tri = shape["triangles"][t]
                if all(v in corner_of for v in tri) and _distinct_corners(
                        [corner_of[v] for v in tri]):
                    found.add(t)
        if not found:
            raise ShapeDiffError(
                f"block {block}: removed face on OBJ vertices {sorted(vset)} "
                "matches no NIF triangle (base face doesn't match the NIF)")
        out |= found
    return sorted(out)


def _distinct_corners(options):
    """True if each triangle vertex can be assigned a different face corner."""
    a, b, c = options
    return any(x != y and y != z and x != z for x in a for y in b for z in c)


def _added_triangles(block, shape, ids, base, added_faces, final_local):
    """Added faces (already in base indices) -> original-index triangles in
    the edit face's winding. Each corner must be an existing original at
    that position whose NIF UV equals the corner's UV (lowest such index)."""
    nif_uvs = shape["uvs"]
    out = []
    for f in added_faces:
        if len(f) != 3:
            raise ShapeDiffError(
                f"block {block}: added face has {len(f)} corners; "
                "triangulate before export (Ctrl+T in Blender)")
        tri = []
        for bv, uv in f:
            cands = [o for o in ids[bv] if uv is not None and _uv_equal(nif_uvs[o], uv)]
            if not cands:
                raise ShapeDiffError(
                    f"block {block}: added face needs a new vertex/UV at "
                    f"{tuple(base.positions[bv])} (UV {uv}) -- iteration 3")
            tri.append(min(cands))
        if len(set(tri)) < 3:
            raise ShapeDiffError(
                f"block {block}: added triangle {tuple(tri)} repeats a vertex")
        p0, p1, p2 = (final_local[i] for i in tri)
        u = [p1[k] - p0[k] for k in range(3)]
        w = [p2[k] - p0[k] for k in range(3)]
        n = (u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0])
        if sum(c * c for c in n) ** 0.5 <= 1e-10:      # mesh_fix.cc's rule
            raise ShapeDiffError(
                f"block {block}: added triangle {tuple(tri)} has zero area")
        out.append(tuple(tri))
    return out


def diff_shape(shape: dict, base, edit):
    """Diff one shape's base/edit OBJ pair (spec §5.3): vertex moves, UV0
    edits, removed faces and added triangles on existing originals. Refuses
    (all-or-nothing for the object) new vertices, a survivor that moved
    while vertices were deleted, an added face needing a new vertex/UV, an
    added n-gon or degenerate triangle, a flipped existing face, and a UV
    edit that would need a vertex split."""
    block = shape["block"]
    corr = _correspondence(block, base, edit)
    ids = identify(shape, base)
    edit_faces = [[(corr[v], uv) for v, uv in f] for f in edit.faces]
    base_sets = _by_vertex_set(base.faces)
    edit_sets = _by_vertex_set(edit_faces)
    common_base, common_edit = [], []
    for vset in base_sets.keys() & edit_sets.keys():
        bfs, efs = base_sets[vset], edit_sets[vset]
        if sorted(map(_face_key, bfs)) != sorted(map(_face_key, efs)):
            raise ShapeDiffError(
                f"block {block}: face on OBJ vertices {sorted(vset)} changed "
                "winding (flipped normal?) -- not supported yet")
        common_base += bfs
        common_edit += efs
    uvs = _resolve_uv_edits(block, shape, ids, common_base, common_edit)
    inv = frames.affine_inverse(shape["world"])
    moves = {}
    for k, ep in enumerate(edit.positions):
        bp = base.positions[corr[k]]
        if max(abs(a - b) for a, b in zip(bp, ep)) <= POS_TOL:
            continue
        local = frames.apply(inv, ep)
        for orig in ids[corr[k]]:
            moves[orig] = local
    remove = _removed_triangles(block, shape, ids, base_sets.keys() - edit_sets.keys())
    final_local = [frames.apply(inv, p) for p in shape["vertices"]]
    for orig, p in moves.items():
        final_local[orig] = p
    added = [f for f in edit_faces if frozenset(v for v, _ in f) not in base_sets]
    add = _added_triangles(block, shape, ids, base, added, final_local)
    if not moves and not uvs and not remove and not add:
        return None
    return {
        "block": block,
        "orig_vertex_count": len(shape["vertices"]),
        "orig_triangle_count": len(shape["triangles"]),
        "moves": sorted(moves.items()),
        "uvs": sorted(uvs.items()),
        "remove_triangles": remove,
        "add_triangles": add,
    }


def diff(shapes: list, base_objs: dict, edit_objs: dict, partial: bool = False):
    """Diff every object. With partial=False (default, unchanged), the first
    object whose diff_shape raises ShapeDiffError aborts the whole call, and
    the return is just the edit list. With partial=True, an object-level
    ShapeDiffError (new vertices, unalignable deletion, an added face needing
    a new vertex/UV, flipped face, UV vertex-split conflict, identity failure) is caught and recorded instead of raising, so
    the supported objects still get written; the return becomes
    (edits, skipped), skipped being a list of (object_name, reason_str) in
    block order. File-level problems (object-set mismatch, two objects
    mapping to one block, an object name that isn't a shape export, a block
    not in the NIF) always raise, in both modes -- they mean the export
    itself is broken, not that one object's edit is unsupported."""
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
    skipped = []
    for name in sorted(base_objs, key=obj_io.block_of):
        block = obj_io.block_of(name)
        if block not in by_block:
            raise ShapeDiffError(f"object {name}: block {block} is not a shape in this NIF")
        try:
            e = diff_shape(by_block[block], base_objs[name], edit_objs[name])
        except ShapeDiffError as exc:
            if not partial:
                raise
            skipped.append((name, str(exc)))
            continue
        if e is not None:
            edits.append(e)
    if partial:
        return edits, skipped
    return edits
