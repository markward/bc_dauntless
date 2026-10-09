"""Identity and diff between Blender OBJ exports and the original NIF shapes.

Blender does not preserve vertex order across import, so identity goes by
position (POS_TOL), never by index. Between base.obj and edit.obj (both
written by Blender from the same mesh) surviving vertices keep their
relative order and new vertices are appended, so `correspond` finds the
order-preserving matching that best agrees on position and connectivity,
refusing when it is ambiguous.

diff_shape records moves, UV edits, removed faces (every NIF triangle on the
face's welded vertex set, duplicates and reversed twins included), added
triangles and new vertices. A value equal to an original's (a snapped
position, a shared UV) is stored as a reference to it (spec §6.2). A
changed albedo (by map_Kd basename, one per object, file present in the
overlay or stock texture dir) is recorded as the edit's "albedo" key."""
from pathlib import Path

from tools.shape_diff import ShapeDiffError, frames, obj_io, triangulate
from tools.shape_diff.payload import Ref

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


class NifIndex:
    """Every ORIGINAL vertex of every shape in the NIF, in model space, for
    reference detection (spec §6.2): a value Mark's edit shares with an
    original is stored as an index to it, never as BC's number."""

    def __init__(self, shapes):
        self.shapes = {s["block"]: s for s in shapes}
        self._keys, self._points = [], []
        for s in shapes:
            for v, p in enumerate(s["vertices"]):
                self._keys.append((s["block"], v))
                self._points.append(p)
        self._grid = _grid(self._points)

    def _at(self, p):
        return [self._keys[i] for i in _near(self._grid, self._points, p)]

    def position_ref(self, p, target):
        """Ref to an original within POS_TOL of model-space `p`: the target
        shape's own first, then the lowest block, then the lowest index."""
        found = self._at(p)
        if not found:
            return None
        block, v = min(found, key=lambda k: (k[0] != target, k[0], k[1]))
        return Ref(block, v)

    def uv_ref(self, uv, pos_ref, target, p):
        """Ref for UV0 `uv` of a vertex at model-space `p` whose position
        resolved to `pos_ref` (or None): that same original if its UV0
        matches; else the lowest target-shape original AT `p` with that UV0;
        else the lowest target-shape original anywhere with it (the value is
        identical, and it keeps BC's number out of the payload); else None."""
        if uv is None:
            return None
        if pos_ref is not None:
            src = self.shapes[pos_ref.block]["uvs"]
            if pos_ref.vertex < len(src) and _uv_equal(src[pos_ref.vertex], uv):
                return pos_ref
        tuvs = self.shapes[target]["uvs"]
        here = [v for b, v in self._at(p) if b == target and _uv_equal(tuvs[v], uv)]
        if here:
            return Ref(target, min(here))
        anywhere = next((v for v, t in enumerate(tuvs) if _uv_equal(t, uv)), None)
        return None if anywhere is None else Ref(target, anywhere)


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


def _same_pos(p, q):
    return max(abs(a - b) for a, b in zip(p, q)) <= POS_TOL


def _neighbours(mesh):
    """Vertex -> set of vertices sharing a face edge with it."""
    out = [set() for _ in mesh.positions]
    for f in mesh.faces:
        vs = [v for v, _ in f]
        for i, v in enumerate(vs):
            for w in (vs[i - 1], vs[(i + 1) % len(vs)]):
                if w != v:
                    out[v].add(w)
    return out


def _corner_uvs(mesh):
    out = [[] for _ in mesh.positions]
    for f in mesh.faces:
        for v, uv in f:
            if uv is not None and not any(_uv_equal(uv, u) for u in out[v]):
                out[v].append(uv)
    return out


def _pair_weights(base, edit):
    """Sparse agreement score per (edit, base) pair (spec §5.2): 4 for the
    same position, plus 2 per edit neighbour that sits where one of the base
    vertex's neighbours sits, plus 1 when the pair already scores and a
    corner UV of one equals a corner UV of the other (a moved survivor keeps
    its UVs; it only breaks ties, never creates a candidate).
    Matching-independent, so it can drive one DP."""
    grid = _grid(base.positions)
    bn, en = _neighbours(base), _neighbours(edit)
    buv, euv = _corner_uvs(base), _corner_uvs(edit)
    weights = {}
    for e, ep in enumerate(edit.positions):
        w = {}
        for b in _near(grid, base.positions, ep):
            w[b] = w.get(b, 0) + 4
        agree = {}
        for e2 in en[e]:
            for b2 in _near(grid, base.positions, edit.positions[e2]):
                for b in bn[b2]:
                    agree.setdefault(b, set()).add(e2)
        for b, es in agree.items():
            w[b] = w.get(b, 0) + 2 * len(es)
        for b in w:
            if any(_uv_equal(u, v) for u in euv[e] for v in buv[b]):
                w[b] += 1
        if w:
            weights[e] = w
    return weights


def _best_monotone_matching(weights, nb):
    """Max-weight order-preserving matching over the positive-weight pairs
    (a heaviest chain strictly increasing in both indices), with the number
    of distinct optimal matchings saturated at 2. Fenwick tree over base
    index holding (score, count, last pair)."""
    size = nb + 1
    t_val = [0] * size
    t_cnt = [0] * size
    t_arg = [None] * size
    pred = {}

    def query(i):                       # best chain ending at base index < i
        best, cnt, arg = 0, 1, None     # the empty chain
        while i > 0:
            v = t_val[i]
            if t_cnt[i]:
                if v > best:
                    best, cnt, arg = v, t_cnt[i], t_arg[i]
                elif v == best:
                    cnt = min(2, cnt + t_cnt[i])
            i -= i & -i
        return best, cnt, arg

    def update(i, v, c, a):
        i += 1
        while i < size:
            if not t_cnt[i] or v > t_val[i]:
                t_val[i], t_cnt[i], t_arg[i] = v, c, a
            elif v == t_val[i]:
                t_cnt[i] = min(2, t_cnt[i] + c)
            i += i & -i

    opt, opt_cnt, opt_arg = 0, 1, None
    for e in sorted(weights):
        row = []
        for b, w in sorted(weights[e].items()):
            v, c, a = query(b)
            row.append((b, v + w, c, a))
        for b, v, c, a in row:
            pred[(e, b)] = a
            update(b, v, c, (e, b))
            if v > opt:
                opt, opt_cnt, opt_arg = v, c, (e, b)
            elif v == opt:
                opt_cnt = min(2, opt_cnt + c)
    chain = []
    while opt_arg is not None:
        chain.append(opt_arg)
        opt_arg = pred[opt_arg]
    return dict(reversed(chain)), opt_cnt


def _window(corr, e, nb, anchors):
    """Open base-index interval an unmatched edit vertex `e` may take
    without breaking the order of the non-anchored matches (anchors are
    position-certain and may sit in any order)."""
    lo = max((b for k, b in enumerate(corr[:e]) if b is not None and k not in anchors),
             default=-1)
    hi = min((b for k, b in enumerate(corr[e + 1:], e + 1)
              if b is not None and k not in anchors), default=nb)
    return lo, hi


def _base_face_keys(base):
    return {frozenset(v for v, _ in f): _face_key(f) for f in base.faces}


def _flips(face_keys, mapped):
    """True if `mapped` (base indices, edit winding) is a base face's vertex
    set wound the other way."""
    key = face_keys.get(frozenset(mapped))
    if key is None or len(set(mapped)) != len(mapped):
        return False
    k = mapped.index(min(mapped))
    return tuple(mapped[k:] + mapped[:k]) != key


def _drop_flipping_pairs(base, edit, corr, used, anchors):
    """A pairing under which an edit face lands on a base face wound the
    other way is not a survivor (b0395: a new vertex below a deleted one
    shares its neighbours). Unpair the non-anchored corners of such faces
    -- their faces are then re-derived as added -- until none remain. A
    flip among anchored corners alone is left for diff_shape to refuse."""
    face_keys = _base_face_keys(base)
    changed = True
    while changed:
        changed = False
        for f in edit.faces:
            vs = [v for v, _ in f]
            mapped = [corr[v] for v in vs]
            if None in mapped or not _flips(face_keys, mapped):
                continue
            for v in vs:
                if v not in anchors and corr[v] is not None:
                    used.discard(corr[v])
                    corr[v] = None
                    changed = True


def _propagate_by_faces(base, edit, corr, used, anchors):
    """Match an unmatched edit vertex through a face whose other corners are
    matched: if every such face maps onto base faces that add exactly one
    unmatched base vertex inside its order window, and only one, take it."""
    nb = len(base.positions)
    face_keys = _base_face_keys(base)
    base_faces_of = {}
    for f in base.faces:
        fs = frozenset(v for v, _ in f)
        for v in fs:
            base_faces_of.setdefault(v, set()).add(fs)
    changed = True
    while changed:
        changed = False
        for e in range(len(corr)):
            if corr[e] is not None:
                continue
            lo, hi = _window(corr, e, nb, anchors)
            cands = set()
            for f in edit.faces:
                vs = [v for v, _ in f]
                if e not in vs:
                    continue
                others = [corr[v] for v in vs if v != e]
                if None in others or len(set(others)) != len(vs) - 1:
                    continue
                img = frozenset(others)
                for bf in base_faces_of.get(others[0], ()):
                    if len(bf) == len(vs) and img < bf:
                        (b,) = bf - img
                        mapped = [b if v == e else corr[v] for v in vs]
                        if b not in used and lo < b < hi and not _flips(face_keys, mapped):
                            cands.add(b)
            if len(cands) == 1:
                b = cands.pop()
                corr[e] = b
                used.add(b)
                changed = True


def _fill_equal_gaps(base, edit, corr, used, anchors):
    """A run of unmatched edit vertices facing as many unmatched base
    vertices in its order window is taken in order -- but only if every edit
    face touching the run then maps onto a base face (a pure move, e.g. a
    whole island translated). Anything else stays new/deleted."""
    nb = len(base.positions)
    face_keys = _base_face_keys(base)
    e = 0
    while e < len(corr):
        if corr[e] is not None:
            e += 1
            continue
        run = [e]
        while run[-1] + 1 < len(corr) and corr[run[-1] + 1] is None:
            run.append(run[-1] + 1)
        lo, hi = _window(corr, e, nb, anchors)
        free = [b for b in range(lo + 1, hi) if b not in used]
        if len(free) == len(run):
            trial = list(corr)
            for k, b in zip(run, free):
                trial[k] = b
            touched = set(run)
            faces = [f for f in edit.faces if touched.intersection(v for v, _ in f)]
            if faces and all(None not in [trial[v] for v, _ in f]
                             and frozenset(trial[v] for v, _ in f) in face_keys
                             and not _flips(face_keys, [trial[v] for v, _ in f])
                             for f in faces):
                corr[:] = trial
                used.update(free)
        e = run[-1] + 1


def _anchors(base, edit):
    """edit -> base pairs whose positions coincide one-to-one in BOTH
    directions (the only base vertex at the edit vertex's position, and the
    only edit vertex at that base vertex's). Order-free: separate/join can
    return survivors in any order, and position alone settles these."""
    bgrid, egrid = _grid(base.positions), _grid(edit.positions)
    out = {}
    for e, ep in enumerate(edit.positions):
        bs = _near(bgrid, base.positions, ep)
        if len(bs) == 1 and _near(egrid, edit.positions, base.positions[bs[0]]) == [e]:
            out[e] = bs[0]
    return out


def _proximity(base, edit, weights):
    """+4 on a scoring pair when each is the other's strictly nearest
    candidate: a survivor that moved a little beats a new vertex that merely
    shares more neighbours with the original (b0688). Ties earn nothing."""
    def d2(e, b):
        return sum((x - y) ** 2 for x, y in zip(edit.positions[e], base.positions[b]))
    best_b, best_e = {}, {}
    for e, w in weights.items():
        for b in w:
            d = d2(e, b)
            for key, other, table in ((e, b, best_b), (b, e, best_e)):
                cur = table.get(key)
                if cur is None or d < cur[0]:
                    table[key] = (d, other, False)
                elif d == cur[0] and other != cur[1]:
                    table[key] = (d, cur[1], True)          # tied: no nearest
    for e, w in weights.items():
        for b in w:
            nb_, ne_ = best_b[e], best_e[b]
            if nb_[1] == b and ne_[1] == e and not nb_[2] and not ne_[2]:
                w[b] += 4


def correspond(block, base, edit):
    """edit vertex index -> base vertex index, or None for a NEW vertex
    (spec §5.2). Pairs whose positions coincide one-to-one are anchored in
    any order (`_anchors`). The rest (moved survivors, new and deleted
    vertices, non-unique position claims) are paired by the order-preserving
    matching that maximises agreement -- Blender keeps survivors in relative
    order and appends new vertices -- then extended through faces and
    equal-size gaps. Refuses ("ambiguous correspondence") when that best
    matching is not unique. Never guesses."""
    nb, ne = len(base.positions), len(edit.positions)
    if ne == nb and all(_same_pos(p, q) for p, q in zip(base.positions, edit.positions)):
        return list(range(nb))
    anchored = _anchors(base, edit)
    taken = set(anchored.values())
    weights = {}
    for e, w in _pair_weights(base, edit).items():
        if e in anchored:
            continue
        w = {b: v for b, v in w.items() if b not in taken}
        if w:
            weights[e] = w
    _proximity(base, edit, weights)
    matched, count = _best_monotone_matching(weights, nb)
    if count > 1:
        matched = _certain_pairs(block, base, edit, weights, matched)
    corr = [anchored.get(e, matched.get(e)) for e in range(ne)]
    used = taken | set(matched.values())
    anchors = set(anchored)
    _drop_flipping_pairs(base, edit, corr, used, anchors)
    _propagate_by_faces(base, edit, corr, used, anchors)
    _fill_equal_gaps(base, edit, corr, used, anchors)
    _refuse_unsettled_originals(block, base, edit, corr, used, anchors)
    return corr


def _ambiguous(block, why):
    return ShapeDiffError(f"block {block}: ambiguous correspondence -- {why}; "
                          "refused rather than guessed")


def _certain_pairs(block, base, edit, weights, matched):
    """The best matching is not unique: keep only the pairs every optimal
    matching shares (dropping one lowers the optimum). The others stay
    unpaired -- new/deleted -- which re-derives their faces exactly; but a
    contested pair that sits on the same position is a claim nothing else
    can settle, so that is refused."""
    def total(m):
        return sum(weights[e][b] for e, b in m.items())
    opt = total(matched)
    keep = {}
    for e, b in matched.items():
        trial = {k: ({c: v for c, v in w.items() if c != b} if k == e else w)
                 for k, w in weights.items()}
        if total(_best_monotone_matching(trial, len(base.positions))[0]) < opt:
            keep[e] = b
        elif _same_pos(edit.positions[e], base.positions[b]):
            raise _ambiguous(block, f"edit vertex {e} at {tuple(edit.positions[e])} "
                                    "sits on more than one original that could have survived")
    return keep


def _refuse_unsettled_originals(block, base, edit, corr, used, anchors):
    """An original left unpaired at the position of a non-anchored pair's
    edit vertex: which of the coincident originals survived is not settled."""
    grid = _grid(base.positions)
    for e, b in enumerate(corr):
        if b is None or e in anchors:
            continue
        loose = [c for c in _near(grid, base.positions, edit.positions[e]) if c not in used]
        if loose:
            raise _ambiguous(block, f"edit vertex {e} at {tuple(edit.positions[e])} could be "
                                    f"original {b} or {loose[0]} (coincident)")


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


def _refuse_overlapping_groups(block, ids, removed_sets, added_faces):
    """Two distinct OBJ vertices within POS_TOL of each other (straddling a
    1/1024 weld boundary) share originals in `identify`, so a removal or an
    added corner on either could hit the other's triangles. Harmless for
    moves/UVs, so refuse only when a topology edit touches one of them."""
    touched = set().union(*removed_sets, *({v for v, _ in f if v >= 0} for f in added_faces))
    owners = {}
    for bv, group in enumerate(ids):
        for orig in group:
            owners.setdefault(orig, []).append(bv)
    for orig, bvs in owners.items():
        if len(bvs) > 1 and touched.intersection(bvs):
            raise ShapeDiffError(
                f"block {block}: OBJ vertices {bvs} lie within POS_TOL of each other "
                f"(both match original {orig}); a face removed or added on them "
                "can't be resolved to NIF triangles unambiguously")


def _distinct_corners(options):
    """True if each triangle vertex can be assigned a different face corner."""
    a, b, c = options
    return any(x != y and y != z and x != z for x in a for y in b for z in c)


class _AddedVertices:
    """Vertices appended to the shape (spec §5.3), one per distinct UV of a
    new edit vertex or of a survivor an added face shows with a UV no
    original carries (a split). Values equal to an original's become
    references; colour/UV1 come from `attr_src`, the target shape's original
    nearest in model space (ties -> lowest index)."""

    def __init__(self, shape, index, inv):
        self.shape, self.index, self.inv = shape, index, inv
        self.items = []        # (model position, uv)
        self._by_source = {}   # source key -> [(uv, item index)]

    def index_of(self, source, model, uv):
        for u, i in self._by_source.get(source, ()):
            if _uv_equal(u, uv):
                return i
        self.items.append((model, uv))
        self._by_source.setdefault(source, []).append((uv, len(self.items) - 1))
        return len(self.items) - 1

    def local(self, i):
        return frames.apply(self.inv, self.items[i][0])

    def records(self):
        block, pts = self.shape["block"], self.shape["vertices"]
        out = []
        for model, uv in self.items:
            pos_ref = self.index.position_ref(model, block)
            attr = min(range(len(pts)), key=lambda o: (
                sum((a - b) ** 2 for a, b in zip(pts[o], model)), o))
            pos = pos_ref or _delta_ref(block, attr, self.inv, pts[attr], model)
            out.append({"pos": pos,
                        "uv0": self.index.uv_ref(uv, pos_ref, block, model) or uv,
                        "attr_src": attr})
        return out


def _delta_ref(block, orig, inv, orig_model, model):
    """Kind-2 position (spec §6.1): original `orig` of this shape plus the
    shape-local offset that takes it to model-space `model`."""
    a, b = frames.apply(inv, orig_model), frames.apply(inv, model)
    return Ref(block, orig, tuple(y - x for x, y in zip(a, b)))


def _ear_clipped(block, faces, pos_of):
    """Each face as triangles of its corners: an n-gon is ear-clipped on the
    edit positions of its corners, keeping its winding."""
    for f in faces:
        try:
            tris = triangulate.ear_clip([pos_of[k] for k, _ in f])
        except ShapeDiffError as exc:
            raise ShapeDiffError(f"block {block}: added {exc}") from None
        for a, b, c in tris:
            yield [f[a], f[b], f[c]]


def _added_triangles(block, shape, ids, edit, added_faces, final_local, uv_edits,
                     moved, added, pos_of):
    """Added faces (corners in base indices, or -1-e for new edit vertex e;
    n-gons ear-clipped) -> triangles in the edit face's winding over final
    vertex indices. A survivor corner is the original at that position whose
    FINAL UV (NIF UV0 with this diff's `uv_edits`) equals the corner's
    (lowest such index); failing that, and for every new vertex, an added
    vertex (`added`)."""
    nif_uvs = shape["uvs"]
    n_orig = len(shape["vertices"])
    out = []
    for f in _ear_clipped(block, added_faces, pos_of):
        tri = []
        for k, uv in f:
            where = edit.positions[-1 - k] if k < 0 else None
            if uv is None:
                at = where if k < 0 else shape["vertices"][min(ids[k])]
                raise ShapeDiffError(
                    f"block {block}: added face corner at {tuple(at)} has no UV")
            if k >= 0:
                cands = [o for o in ids[k] if _uv_equal(uv_edits.get(o, nif_uvs[o]), uv)]
                if cands:
                    tri.append(min(cands))
                    continue
                rep = min(ids[k])        # split: the survivor, with this corner's UV
                tri.append(n_orig + added.index_of(
                    ("split", k), moved.get(rep, shape["vertices"][rep]), uv))
            else:
                tri.append(n_orig + added.index_of(("new", k), where, uv))
        if len(set(tri)) < 3:
            raise ShapeDiffError(
                f"block {block}: added triangle {tuple(tri)} repeats a vertex")
        p0, p1, p2 = (final_local[i] if i < n_orig else added.local(i - n_orig) for i in tri)
        u = [p1[k] - p0[k] for k in range(3)]
        w = [p2[k] - p0[k] for k in range(3)]
        n = (u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0])
        if sum(c * c for c in n) ** 0.5 <= 1e-10:      # mesh_fix.cc's rule
            raise ShapeDiffError(
                f"block {block}: added triangle {tuple(tri)} has zero area")
        out.append(tuple(tri))
    return out


# model_build.cc's filename_is_glow / _specular / _normal, on the
# extension-less stem, case-insensitive (mesh_fix.cc mirrors the same list).
_RESERVED_SUFFIXES = (("_glow", "glow"), ("_specular", "specular"), ("_spec", "specular"),
                      ("_normal", "a normal map"), ("_norm", "a normal map"))


def _object_albedo(mesh):
    """The one map_Kd basename every face of `mesh` uses, or None (no
    texture info, or no map_Kd). A face set split across two albedos -- or a
    texture and none -- is a sentinel tuple of the sorted names."""
    names = set(mesh.face_albedos)
    if len(names) > 1:
        return tuple(sorted(n or "<none>" for n in names))
    return next(iter(names), None)


def _find_texture(name, texture_dirs):
    want = name.casefold()
    for d in texture_dirs:
        d = Path(d)
        if d.is_dir() and any(p.name.casefold() == want for p in d.iterdir() if p.is_file()):
            return True
    return False


def _albedo_op(block, base, edit, texture_dirs):
    """Spec §5.3: the edit's single albedo, when it differs from the base's
    and the file exists in one of `texture_dirs` (overlay, then stock). None
    when there is nothing to record."""
    new = _object_albedo(edit)
    if isinstance(new, tuple):
        raise ShapeDiffError(
            f"block {block}: faces use {len(new)} different textures {list(new)}; "
            "per-face material split isn't supported -- one texture per object")
    old = _object_albedo(base)
    if isinstance(old, tuple):
        raise ShapeDiffError(
            f"block {block}: base faces use {len(old)} different textures {list(old)}; "
            "base.obj must be the unaltered export (one texture per object)")
    if new is None or (isinstance(old, str) and old.casefold() == new.casefold()):
        return None
    if not new.lower().endswith(".tga"):
        raise ShapeDiffError(
            f"block {block}: texture {new!r} is not a .tga (the NIF loader reads TGA only)")
    stem = new[:new.rfind(".")].lower()
    for suffix, slot in _RESERVED_SUFFIXES:
        if stem.endswith(suffix):
            raise ShapeDiffError(
                f"block {block}: texture {new!r} would bind as {slot}; an albedo op "
                f"takes a plain diffuse (use {new[:len(stem) - len(suffix)]}"
                f"{new[new.rfind('.'):]})")
    if not _find_texture(new, texture_dirs or ()):
        searched = ", ".join(str(d) for d in texture_dirs or ()) or "(none)"
        raise ShapeDiffError(
            f"block {block}: texture {new!r} not found; searched {searched}")
    return new


def diff_shape(shape: dict, base, edit, texture_dirs=None, index=None):
    """Diff one shape's base/edit OBJ pair (spec §5.3): vertex moves, UV0
    edits, removed faces, added triangles and new vertices, with values
    shared with an original stored as references (`index`, all shapes of the
    NIF; this shape alone when omitted). Refuses (all-or-nothing for the
    object) an ambiguous vertex correspondence, an added n-gon or degenerate
    triangle, a flipped existing face, a corner without a UV, and a UV edit
    on a kept face that would need a vertex split."""
    block = shape["block"]
    index = index or NifIndex([shape])
    corr = correspond(block, base, edit)
    ids = identify(shape, base)
    # base vertex index for a survivor, -1 - e for new edit vertex e
    keys = [b if b is not None else -1 - e for e, b in enumerate(corr)]
    edit_faces = [[(keys[v], uv) for v, uv in f] for f in edit.faces]
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
    moved = {}          # original -> new MODEL-space position
    for k, ep in enumerate(edit.positions):
        if corr[k] is None:
            continue
        if _same_pos(base.positions[corr[k]], ep):
            continue
        for orig in ids[corr[k]]:
            moved[orig] = ep
    removed_sets = base_sets.keys() - edit_sets.keys()
    added_faces = [f for f in edit_faces if frozenset(v for v, _ in f) not in base_sets]
    _refuse_overlapping_groups(block, ids, removed_sets, added_faces)
    remove = _removed_triangles(block, shape, ids, removed_sets)
    final_local = [frames.apply(inv, p) for p in shape["vertices"]]
    for orig, p in moved.items():
        final_local[orig] = frames.apply(inv, p)
    added = _AddedVertices(shape, index, inv)
    pos_of = {keys[e]: p for e, p in enumerate(edit.positions)}
    add = _added_triangles(block, shape, ids, edit, added_faces, final_local, uvs,
                           moved, added, pos_of)
    albedo = _albedo_op(block, base, edit, texture_dirs)
    # A move or UV edit on an original no surviving or added triangle uses
    # renders nothing: a dead record (e.g. a survivor every face of which was
    # re-added with new UVs, as split vertices).
    gone = set(remove)
    live = {v for t, tri in enumerate(shape["triangles"]) if t not in gone for v in tri}
    live |= {i for tri in add for i in tri}
    moved = {o: p for o, p in moved.items() if o in live}
    uvs = {o: uv for o, uv in uvs.items() if o in live}
    if not moved and not uvs and not remove and not add and albedo is None:
        return None
    moves, uv_out = {}, {}
    for orig, p in moved.items():
        moves[orig] = (index.position_ref(p, block)
                       or _delta_ref(block, orig, inv, shape["vertices"][orig], p))
    for orig, uv in uvs.items():
        p = moved.get(orig, shape["vertices"][orig])
        uv_out[orig] = index.uv_ref(uv, index.position_ref(p, block), block, p) or uv
    out = {
        "block": block,
        "orig_vertex_count": len(shape["vertices"]),
        "orig_triangle_count": len(shape["triangles"]),
        "moves": sorted(moves.items()),
        "uvs": sorted(uv_out.items()),
        "remove_triangles": remove,
        "add_triangles": add,
    }
    if added.items:
        out["add_vertices"] = added.records()
    survivors = [(k, b) for k, b in enumerate(corr)
                 if b is not None and not _same_pos(base.positions[b], edit.positions[k])]
    if survivors:
        out["moved_survivors"] = survivors      # for the CLI's warning, never encoded
    if albedo is not None:
        out["albedo"] = albedo
    return out


def diff(shapes: list, base_objs: dict, edit_objs: dict, partial: bool = False,
         texture_dirs=None, exclude=()):
    """Diff every object. With partial=False (default), the first object
    whose diff_shape raises ShapeDiffError aborts the whole call, and the
    return is just the edit list. With partial=True, an object-level
    ShapeDiffError (ambiguous correspondence, flipped face, UV vertex-split
    conflict, untriangulable face, identity failure, refused texture) is
    caught and recorded instead of raising, so the supported objects still
    get written; the return becomes (edits, skipped), skipped being a list of
    (object_name, reason_str) in block order. Blocks in `exclude` are left
    out entirely, before any diffing (so even a refused object can be
    excluded); excluding a block with no object is refused. File-level
    problems (object-set mismatch, two objects mapping to one block, an
    object name that isn't a shape export, a block not in the NIF) always
    raise, in both modes -- they mean the export itself is broken, not that
    one object's edit is unsupported."""
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
    for block in exclude:
        if block not in block_to_names:
            raise ShapeDiffError(f"--exclude {block}: no object for block {block} in the export")
    by_block = {s["block"]: s for s in shapes}
    index = NifIndex(shapes)
    edits = []
    skipped = []
    for name in sorted(base_objs, key=obj_io.block_of):
        block = obj_io.block_of(name)
        if block in exclude:
            continue
        if block not in by_block:
            raise ShapeDiffError(f"object {name}: block {block} is not a shape in this NIF")
        try:
            e = diff_shape(by_block[block], base_objs[name], edit_objs[name],
                           texture_dirs, index)
        except ShapeDiffError as exc:
            if not partial:
                raise
            skipped.append((name, str(exc)))
            continue
        if e is not None:
            edits.append(e)
    edits, dependents = _without_orphaned_removals(
        by_block, base_objs, edit_objs, edits,
        [(n, "skipped") for n, _ in skipped]
        + [(n, "excluded") for n in base_objs if obj_io.block_of(n) in exclude])
    if dependents and not partial:
        name, reason = dependents[0]
        raise ShapeDiffError(f"object {name}: {reason}; exclude it too")
    skipped += dependents
    if partial:
        return edits, skipped
    return edits


def _without_orphaned_removals(by_block, base_objs, edit_objs, edits, left_out):
    """An object left out of the fix (skipped or excluded) whose edit puts a
    vertex where a triangle REMOVED by an included block had a corner was
    that removal's replacement (b0392's faces, re-made by b0395): landing
    the removal alone would open a hole. Such blocks are left out too, with
    the reason, until nothing changes. Returns (kept edits, [(name, why)])."""
    name_of = {obj_io.block_of(n): n for n in base_objs}
    pending = list(left_out)
    out = []
    while pending:
        other, how = pending.pop()
        base_pts = base_objs[other].positions
        grid = _grid(base_pts)
        touch = [p for p in edit_objs[other].positions if not _near(grid, base_pts, p)]
        if not touch:
            continue
        tgrid = _grid(touch)
        keep = []
        for e in edits:
            shape = by_block[e["block"]]
            corners = {v for t in e.get("remove_triangles", ()) for v in shape["triangles"][t]}
            if any(_near(tgrid, touch, shape["vertices"][v]) for v in corners):
                name = name_of[e["block"]]
                out.append((name, f"block {e['block']}: depends on {how} {other} -- its "
                                  "edit meets triangles this block removes"))
                pending.append((name, "skipped"))
            else:
                keep.append(e)
        edits = keep
    return edits, out
