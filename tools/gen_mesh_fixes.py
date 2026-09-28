"""Generate hull name-cut mesh-fix files (spec:
docs/superpowers/specs/2026-09-28-hull-name-cut-fix-design.md).

BC's Federation saucer hulls carry a small "ID" texture patch cut out of the
saucer mesh (see the design doc). This tool rebuilds UVs for that patch into
the saucer's own texture and emits a fix file describing how to merge the
patch back into the saucer at NIF load time (`native/src/assets/src/
mesh_fix.cc` applies it).

This module is the pure-Python core: fitting, region grouping, and the fix
JSON builder. All geometry comes from `_dauntless_host.nif_shapes(path)`, a
read-only binding over the C++ NIF parser -- no numpy, no new dependency.

The CLI (`main()`) walks `STOCK_MESHES`, calls `build_fix`, renders a review
PNG per mesh, and -- only with `--write` -- writes
`native/assets/mesh_fixes/<hash>.json`.
"""
import argparse
import json
import math
import struct
import tempfile
from pathlib import Path

# Stock Federation hulls with an ID cut: 5 hulls, High LOD only. The engine
# never loads Medium or Low meshes, so those are out of scope (Low LODs also
# have no ID patch at all -- see design doc S2.1).
STOCK_MESHES: tuple = (
    "data/Models/Ships/Galaxy/Galaxy.nif",
    "data/Models/Ships/Nebula/Nebula.nif",
    "data/Models/Ships/Sovereign/Sovereign.nif",
    "data/Models/Ships/Akira/Akira.nif",
    "data/Models/Ships/Ambassador/Ambassador.nif",
)

# Per-mesh target-shape overrides, keyed by the `rel` path in STOCK_MESHES.
# The automatic pick (highest twin count, then fit quality, then region
# size -- see build_fix) is right for all 5 stock High meshes; this exists
# for a future mesh whose ID patch borders more than one shape ambiguously.
TARGET_OVERRIDES: dict = {}

# Per-mesh overrides for build_fix's region-bounds UV clamp (see the clamp
# comment inside build_fix), keyed by the `rel` path in STOCK_MESHES. Each
# value merges over the computed region bounds via dict.get(key, default) --
# only keys present here move; everything else keeps the region's own bound.
#
# Ambassador: AmbassadorSaucer_glow.tga is 256x256. Its left half (columns
# <=127, u<=0.49609) is the saucer UNDERSIDE and has glow alpha 0 there; its
# right half (columns >=128, u>=0.5) is the TOP, with alpha 126-255 at the
# patch's rows. The patch's centreline vertices land at u=0.49947-0.50094
# (columns ~127.86-128.24) -- straddling the alpha-0/alpha>0 split -- so
# bilinear filtering blends in 26-36% of the alpha=0 texel per sample and
# dims the glow along the seam by about a third (measured; see design doc
# S10). Raising the floor to 129/256=0.50390625 -- one texel past the
# split -- keeps both mip 0 and mip 1 sampling wholly inside the alpha>0
# top half.
UV_CLAMP_OVERRIDES: dict = {
    "data/Models/Ships/Ambassador/Ambassador.nif": {"u_min": 129 / 256},
}

# FNV-1a 64-bit constants -- must match native/src/assets/src/mesh_fix.cc's
# fnv1a64_hex exactly, since fix files are keyed by this hash.
_FNV_OFFSET = 14695981039346656037
_FNV_PRIME = 1099511628211
_MASK64 = (1 << 64) - 1

# Position match tolerance (game units) shared by twin-finding and welding.
_POS_TOL = 1e-3


def fnv1a64_hex(data: bytes) -> str:
    """FNV-1a 64-bit hash of `data`, as 16 lowercase hex digits."""
    h = _FNV_OFFSET
    for byte in data:
        h ^= byte
        h = (h * _FNV_PRIME) & _MASK64
    return "%016x" % h


def to_f32(x: float) -> float:
    """Round-trip `x` through IEEE-754 float32 (the NIF's own precision)."""
    return struct.unpack("f", struct.pack("f", x))[0]


def _distance(a, b) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def regions(shape: dict) -> list:
    """Per-vertex region label: union-find over vertices sharing a
    (rounded position, rounded UV) key, plus every triangle's three
    vertices. Two adjoining, UV-continuous patches of a shape end up in one
    region; a UV seam (a duplicated vertex with a different UV) starts a
    new one unless a shared triangle re-joins it."""
    verts = shape["vertices"]
    uvs = shape["uvs"]
    n = len(verts)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    seen = {}
    for i in range(n):
        x, y, z = verts[i]
        u, v = uvs[i]
        key = (round(x, 4), round(y, 4), round(z, 4), round(u, 5), round(v, 5))
        if key in seen:
            union(i, seen[key])
        else:
            seen[key] = i

    for tri in shape["triangles"]:
        a, b, c = tri
        union(a, b)
        union(b, c)

    return [find(i) for i in range(n)]


def _solve_normal_equations(rows, targets):
    """Solve the least-squares normal equations (A^T A) x = A^T b for one
    right-hand side via Gauss-Jordan elimination with partial pivoting.
    Returns None if any pivot magnitude is below 1e-12 (rank-deficient --
    too few points, or a degenerate axis)."""
    n = len(rows[0])
    ata = [[sum(r[i] * r[j] for r in rows) for j in range(n)] for i in range(n)]
    atb = [sum(r[i] * t for r, t in zip(rows, targets)) for i in range(n)]

    aug = [ata[i] + [atb[i]] for i in range(n)]
    for col in range(n):
        pivot_row = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot_row][col]) < 1e-12:
            return None
        aug[col], aug[pivot_row] = aug[pivot_row], aug[col]
        pivot = aug[col][col]
        aug[col] = [v / pivot for v in aug[col]]
        for r in range(n):
            if r == col:
                continue
            factor = aug[r][col]
            if factor == 0.0:
                continue
            aug[r] = [v - factor * aug[col][j] for j, v in enumerate(aug[r])]
    return [aug[i][n] for i in range(n)]


_CANDIDATES = (
    ("planar-mirrored", True, 3),
    ("planar-mirrored-xyz", True, 4),
    ("planar", False, 3),
    ("planar-xyz", False, 4),
)


# Local-fit's looser worst-vertex tolerance (design doc's "small smooth
# perturbation" case): the whole region isn't planar, but the immediate
# neighbourhood of the patch usually still is, closely enough for this.
_LOCAL_FIT_TOL = 5e-3


def _fit_candidates(points, uvs, tol):
    """Try each of `_CANDIDATES`, in order, on `points`/`uvs` pairs; return
    the first whose worst-vertex error is <= `tol` as (method,
    [u_coeffs, v_coeffs], max_err), or None if none of the four fit."""
    for method, mirrored, ndim in _CANDIDATES:
        rows = []
        for (x, y, z) in points:
            fx = abs(x) if mirrored else x
            rows.append([fx, y, 1.0] if ndim == 3 else [fx, y, z, 1.0])
        us = [uv[0] for uv in uvs]
        vs = [uv[1] for uv in uvs]
        cu = _solve_normal_equations(rows, us)
        if cu is None:
            continue
        cv = _solve_normal_equations(rows, vs)
        if cv is None:
            continue
        max_err = 0.0
        for row, (u, v) in zip(rows, uvs):
            pu = sum(r * c for r, c in zip(row, cu))
            pv = sum(r * c for r, c in zip(row, cv))
            max_err = max(max_err, abs(pu - u), abs(pv - v))
        if max_err <= tol:
            return method, [cu, cv], max_err
    return None


def fit_projection(points, uvs):
    """Fit a planar (u, v) = f(position) projection over `points`/`uvs`
    pairs. Tries, in order, mirrored-xy, mirrored-xyz, unmirrored-xy,
    unmirrored-xyz; returns the first candidate whose worst-vertex error is
    below 1e-4 as (method, [u_coeffs, v_coeffs], max_err), or None if none
    of the four fit."""
    return _fit_candidates(points, uvs, 1e-4)


# The local-fit window's radius, as a fraction of the patch's own world-bbox
# diagonal -- a ring around the patch's footprint, not its (potentially huge,
# e.g. Ambassador's ~207 GU) bounding box.
_LOCAL_FIT_RADIUS_FRAC = 0.05


def _fit_local_projection(patch: dict, target_shape: dict, region_idxs: list):
    """A local stand-in for `fit_projection`, used when the chosen region as
    a whole isn't planar enough. Restricts the fit to the region vertices
    whose distance to ANY patch vertex is under `_LOCAL_FIT_RADIUS_FRAC` of
    the patch's own world-bbox diagonal -- the patch's immediate
    neighbourhood -- and accepts a looser worst-vertex error
    (`_LOCAL_FIT_TOL`). Tries the same four candidates in the same order as
    `fit_projection`. Returns (method, coeffs, max_err) with `method`
    UNPREFIXED (the caller adds the "local-" prefix), or None if fewer than
    4 region vertices fall within the radius or none of the four candidates
    fits within tolerance."""
    patch_verts = patch["vertices"]
    mins = [min(v[k] for v in patch_verts) for k in range(3)]
    maxs = [max(v[k] for v in patch_verts) for k in range(3)]
    radius = _LOCAL_FIT_RADIUS_FRAC * _distance(mins, maxs)

    local_idxs = [
        i for i in region_idxs
        if any(_distance(target_shape["vertices"][i], pv) < radius
               for pv in patch_verts)
    ]
    if len(local_idxs) < 4:
        return None
    points = [target_shape["vertices"][i] for i in local_idxs]
    uvs = [target_shape["uvs"][i] for i in local_idxs]
    return _fit_candidates(points, uvs, _LOCAL_FIT_TOL)


def apply_projection(method: str, coeffs, point):
    """Evaluate a fitted projection (from `fit_projection`) at `point`."""
    mirrored = "mirrored" in method
    ndim = 4 if method.endswith("xyz") else 3
    x, y, z = point
    fx = abs(x) if mirrored else x
    row = [fx, y, 1.0] if ndim == 3 else [fx, y, z, 1.0]
    cu, cv = coeffs
    u = sum(r * c for r, c in zip(row, cu))
    v = sum(r * c for r, c in zip(row, cv))
    return u, v


def seam_copy(patch: dict, known: dict) -> list:
    """Fill in every patch vertex's UV: `known` vertices keep their given
    (u, v); every other vertex is solved by inverse-edge-length-weighted
    Laplace interpolation from its mesh neighbours, 2000 Gauss-Seidel
    sweeps. Isolated (unconnected, unknown) vertices stay at (0, 0)."""
    verts = patch["vertices"]
    n = len(verts)

    edges = set()
    for tri in patch["triangles"]:
        for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            edges.add((a, b) if a < b else (b, a))

    adj = [[] for _ in range(n)]
    for a, b in sorted(edges):
        d = _distance(verts[a], verts[b])
        if d < 1e-12:
            continue
        w = 1.0 / d
        adj[a].append((b, w))
        adj[b].append((a, w))

    u = [0.0] * n
    v = [0.0] * n
    for i, (uu, vv) in known.items():
        u[i] = uu
        v[i] = vv

    for _sweep in range(2000):
        for i in range(n):
            if i in known or not adj[i]:
                continue
            wsum = sum(w for _, w in adj[i])
            if wsum <= 0.0:
                continue
            u[i] = sum(w * u[j] for j, w in adj[i]) / wsum
            v[i] = sum(w * v[j] for j, w in adj[i]) / wsum

    return list(zip(u, v))


def build_fix(shapes: list, rel: str, target_override, uv_clamp_override=None):
    """Build one fix file's contents from a NIF's shapes (as returned by
    `_dauntless_host.nif_shapes`). Returns (fix_json_dict, review_info).
    Raises ValueError if the mesh doesn't have exactly one ID-texture shape,
    no candidate target region borders it, or the target choice is
    ambiguous under mirroring (see the design doc's ambiguity rule).

    `uv_clamp_override`, if given, is a dict with any of "u_min", "u_max",
    "v_min", "v_max" that overrides the corresponding region-bounds clamp
    computed below (see UV_CLAMP_OVERRIDES)."""
    id_shapes = [s for s in shapes if any("ID" in t for t in s["textures"])]
    if len(id_shapes) != 1:
        raise ValueError(
            "expected exactly one shape with an 'ID' texture, found "
            f"{len(id_shapes)}")
    patch = id_shapes[0]
    other_shapes = [s for s in shapes if s is not patch]

    candidates = []
    for shape in other_shapes:
        if target_override is not None and shape["name"] != target_override:
            continue
        labels = regions(shape)
        by_region = {}
        for i, lbl in enumerate(labels):
            by_region.setdefault(lbl, []).append(i)
        for lbl, idxs in by_region.items():
            twinned = set()
            for i in idxs:
                sv = shape["vertices"][i]
                for pi, pv in enumerate(patch["vertices"]):
                    if _distance(sv, pv) < _POS_TOL:
                        twinned.add(pi)
            if not twinned:
                continue
            points = [shape["vertices"][i] for i in idxs]
            uvs = [shape["uvs"][i] for i in idxs]
            fit = fit_projection(points, uvs)
            candidates.append({
                "fit_ok": fit is not None,
                "num_twinned": len(twinned),
                "region_count": len(idxs),
                "shape": shape,
                "indices": idxs,
                "fit": fit,
            })

    if not candidates:
        raise ValueError("no candidate target region borders the ID patch")

    candidates.sort(
        key=lambda c: (c["num_twinned"], c["fit_ok"], c["region_count"]),
        reverse=True)
    chosen = candidates[0]
    target_shape = chosen["shape"]
    region_idxs = chosen["indices"]
    fit = chosen["fit"]

    region_xs = [target_shape["vertices"][i][0] for i in region_idxs]
    all_nonneg = all(x >= -_POS_TOL for x in region_xs)
    all_nonpos = all(x <= _POS_TOL for x in region_xs)
    if all_nonneg or all_nonpos:
        patch_xs = [v[0] for v in patch["vertices"]]
        opposite = (
            (all_nonneg and any(x < -_POS_TOL for x in patch_xs))
            or (all_nonpos and any(x > _POS_TOL for x in patch_xs)))
        if opposite:
            raise ValueError(
                "ambiguous mirroring: the chosen target region lies wholly "
                "on one side of x=0, but the patch reaches the other side, "
                "so mirrored vs. unmirrored cannot be resolved")

    if fit is not None:
        method, coeffs, max_fit_error = fit
        uvs_out = [
            [to_f32(c) for c in apply_projection(method, coeffs, v)]
            for v in patch["vertices"]
        ]
    else:
        local_fit = _fit_local_projection(patch, target_shape, region_idxs)
        if local_fit is not None:
            local_method, coeffs, max_fit_error = local_fit
            method = "local-" + local_method
            uvs_out = [
                [to_f32(c) for c in apply_projection(local_method, coeffs, v)]
                for v in patch["vertices"]
            ]
            # Snap every patch vertex with an exact twin in the chosen
            # region to the twin's own UV, so the shared seam is exact even
            # though the local fit is only approximate off the seam.
            for i in region_idxs:
                sv = target_shape["vertices"][i]
                tu, tv = target_shape["uvs"][i]
                for pi, pv in enumerate(patch["vertices"]):
                    if _distance(sv, pv) < _POS_TOL:
                        uvs_out[pi] = [to_f32(tu), to_f32(tv)]
        else:
            method = "seam-copy"
            max_fit_error = None
            known = {}
            for i in region_idxs:
                sv = target_shape["vertices"][i]
                for pi, pv in enumerate(patch["vertices"]):
                    if _distance(sv, pv) < _POS_TOL:
                        known[pi] = target_shape["uvs"][i]
            uvs_out = [[to_f32(u), to_f32(v)] for u, v in seam_copy(patch, known)]

    # Clamp every patch vertex's UV into the chosen region's own UV range.
    # A fit (exact or local) is only constrained AT the region's vertices --
    # nothing stops it extrapolating past them for a patch vertex that
    # reaches further than the region does, and BC's saucer textures pack
    # unrelated content on the other side of the region's UV footprint (see
    # design doc S10 -- a mirrored fit for the Ambassador put one hub-end
    # centreline vertex at u=0.48952, just below the saucer region's u=0.50
    # minimum, sampling the texture's other half and drawing a stray dark
    # line). Region bounds come from the same target-shape UVs the fit was
    # built from, so this is a no-op whenever the fit already stays inside
    # them (every exact-fit stock mesh). Snapped twins (local-fit's seam
    # vertices) already lie inside the range by construction.
    region_us = [target_shape["uvs"][i][0] for i in region_idxs]
    region_vs = [target_shape["uvs"][i][1] for i in region_idxs]
    u_min, u_max = min(region_us), max(region_us)
    v_min, v_max = min(region_vs), max(region_vs)
    if uv_clamp_override:
        u_min = uv_clamp_override.get("u_min", u_min)
        u_max = uv_clamp_override.get("u_max", u_max)
        v_min = uv_clamp_override.get("v_min", v_min)
        v_max = uv_clamp_override.get("v_max", v_max)
    uvs_out = [
        [to_f32(min(max(u, u_min), u_max)), to_f32(min(max(v, v_min), v_max))]
        for u, v in uvs_out
    ]

    weld = []
    for pi, pv in enumerate(patch["vertices"]):
        best = None
        pu, pv_ = uvs_out[pi]
        pn = patch["normals"][pi]
        for ti, tv in enumerate(target_shape["vertices"]):
            if _distance(pv, tv) >= _POS_TOL:
                continue
            tu, tv_ = target_shape["uvs"][ti]
            if abs(pu - to_f32(tu)) > 1e-6 or abs(pv_ - to_f32(tv_)) > 1e-6:
                continue
            tn = target_shape["normals"][ti]
            dot = pn[0] * tn[0] + pn[1] * tn[1] + pn[2] * tn[2]
            if dot <= 0.9999:
                continue
            if best is None or ti < best:
                best = ti
        if best is not None:
            weld.append([pi, best])

    fix = {
        "format": 1,
        "source": rel,
        "generator": "tools/gen_mesh_fixes.py",
        "merges": [{
            "patch": {"block": patch["block"], "name": patch["name"]},
            "target": {"block": target_shape["block"], "name": target_shape["name"]},
            "method": method,
            "max_fit_error": max_fit_error,
            "uvs": uvs_out,
            "weld": weld,
            "normals": None,
        }],
    }
    review = {
        "target_texture": target_shape["textures"][0] if target_shape["textures"] else "",
        "uvs": uvs_out,
        "patch_tris": patch["triangles"],
        "target_uvs": target_shape["uvs"],
        "target_tris": target_shape["triangles"],
    }
    return fix, review


def dumps(fix: dict) -> str:
    """Deterministic JSON rendering of a fix dict: 2-space indent, trailing
    newline. Every `uvs` value going in is already float32-round-tripped by
    `build_fix`, so re-parsing this text and calling `to_f32` again is a
    no-op."""
    return json.dumps(fix, indent=2) + "\n"


# ---------------------------------------------------------------------------
# Hull name decals (spec: docs/superpowers/specs/2026-09-28-hull-name-decals-
# design.md). Generates each class's Masks/decals.json: where BC's merged-
# back ID-patch lettering sat on the hull, and where Mark's mask artwork
# should be placed to land in the same spot at the same scale.
# ---------------------------------------------------------------------------

# Per stock class with masks authored (Masks/<Registry>/<placement>.png):
# the NIF to read shapes from, the blank ID texture and a reference
# registry texture (to diff for BC's own lettering box), the reference mask
# artwork (to diff for Mark's own lettering box), which merged shape carries
# the decal, and which placement this entry generates.
DECAL_CLASSES: dict = {
    "Ambassador": {
        "nif": "data/Models/Ships/Ambassador/Ambassador.nif",
        "id_texture": "data/Models/Ships/Ambassador/High/AmbassadorSaucerID_glow.tga",
        "reference_registry": "data/Models/Ships/Ambassador/High/Zhukov.tga",
        "reference_mask": "data/Models/Ships/Ambassador/Masks/Zhukov/top.png",
        "target_shape": "amb saucer:0",
        "placement": "top",
    },
}


def fit_plane_st(points, sts, normals=None) -> dict:
    """Fit an affine map from a patch's own (s, t) UVs to its ship-body
    positions: `p = a0 + s * s_axis + t * t_axis`, one least-squares solve
    per position coordinate (reusing `_solve_normal_equations`) over rows
    `[1, s, t]`.

    `normal` is `normalise(s_axis x t_axis)`, flipped to agree with the mean
    of `normals` when given (undefined orientation otherwise -- the raw
    cross product's sign, whatever that happens to be).

    The returned `origin` is NOT `a0` (p at s=0, t=0): it is the point on
    the fitted plane nearest the ship-body origin -- a stable anchor that
    does not depend on the arbitrary zero of the patch's own UV space.
    `st_origin` is the (s, t) coordinate of that same point, solved from
    `s_axis`/`t_axis`'s Gram matrix, so that for any (s, t):

        p(s, t) == origin + (s - st_origin[0]) * s_axis + (t - st_origin[1]) * t_axis

    is exactly the original affine map (`build_decal` relies on this).
    """
    if len(points) < 3:
        raise ValueError("fit_plane_st needs at least 3 points")
    rows = [[1.0, s, t] for s, t in sts]
    coeffs = []
    for k in range(3):
        target = [p[k] for p in points]
        c = _solve_normal_equations(rows, target)
        if c is None:
            raise ValueError("fit_plane_st: degenerate (s, t) sample")
        coeffs.append(c)
    a0 = [coeffs[k][0] for k in range(3)]
    s_axis = [coeffs[k][1] for k in range(3)]
    t_axis = [coeffs[k][2] for k in range(3)]

    cross = (
        s_axis[1] * t_axis[2] - s_axis[2] * t_axis[1],
        s_axis[2] * t_axis[0] - s_axis[0] * t_axis[2],
        s_axis[0] * t_axis[1] - s_axis[1] * t_axis[0],
    )
    mag = math.sqrt(sum(c * c for c in cross))
    if mag < 1e-12:
        raise ValueError("fit_plane_st: s_axis and t_axis are parallel")
    normal = [c / mag for c in cross]
    if normals:
        mean_n = [sum(nv[k] for nv in normals) / len(normals) for k in range(3)]
        if sum(normal[k] * mean_n[k] for k in range(3)) < 0.0:
            normal = [-c for c in normal]

    # origin: the point on the plane nearest the ship-body origin, i.e. the
    # projection of (0, 0, 0) onto the plane through a0 with this normal.
    d = sum(a0[k] * normal[k] for k in range(3))
    origin = [d * normal[k] for k in range(3)]

    # st_origin: solve origin - a0 == s * s_axis + t * t_axis via the 2x2
    # Gram-matrix normal equations (exact -- origin lies in the plane
    # spanned by s_axis/t_axis by construction).
    delta = [origin[k] - a0[k] for k in range(3)]
    ss = sum(c * c for c in s_axis)
    st = sum(s_axis[k] * t_axis[k] for k in range(3))
    tt = sum(c * c for c in t_axis)
    bs = sum(s_axis[k] * delta[k] for k in range(3))
    bt = sum(t_axis[k] * delta[k] for k in range(3))
    det = ss * tt - st * st
    if abs(det) < 1e-12:
        raise ValueError("fit_plane_st: s_axis and t_axis are not independent")
    st_origin = [(bs * tt - bt * st) / det, (ss * bt - st * bs) / det]

    return {"origin": origin, "s_axis": s_axis, "t_axis": t_axis,
            "normal": normal, "st_origin": st_origin}


def _texel_bounds(texels: set) -> tuple:
    """Integer inclusive `(min_x, min_y, max_x, max_y)` over a texel set.
    Raises ValueError if `texels` is empty."""
    if not texels:
        raise ValueError("no matching texels")
    xs = [x for x, _ in texels]
    ys = [y for _, y in texels]
    return min(xs), min(ys), max(xs), max(ys)


def _bbox_from_texels(texels: set, w: int, h: int) -> tuple:
    """Normalised bounding box, over pixel edges, of a texel set in a
    `w` x `h` grid. Raises ValueError if `texels` is empty."""
    min_x, min_y, max_x, max_y = _texel_bounds(texels)
    return (min_x / w, min_y / h, (max_x + 1) / w, (max_y + 1) / h)


def drop_isolated_texels(texels: set) -> set:
    """Drop any texel with fewer than 2 differing 8-neighbours also present
    in `texels` (spec S3.3 step 4: an isolated stray differing texel --
    e.g. compression/export noise -- is not lettering). A solid block or a
    stroke at least 2 texels wide survives untouched; a lone texel, or a
    diagonal pair (which only gives each other 1 neighbour), does not."""
    kept = set()
    for x, y in texels:
        neighbours = sum(
            1 for dx in (-1, 0, 1) for dy in (-1, 0, 1)
            if (dx, dy) != (0, 0) and (x + dx, y + dy) in texels)
        if neighbours >= 2:
            kept.add((x, y))
    return kept


def _footprint_contains(footprint, x: int, y: int) -> bool:
    """`footprint` is either a set/frozenset of (x, y) texel coordinates, or
    a 2D boolean grid indexable as `footprint[y][x]`."""
    if isinstance(footprint, (set, frozenset)):
        return (x, y) in footprint
    return bool(footprint[y][x])


def uv_footprint(patch: dict, width: int, height: int) -> set:
    """Rasterise `patch`'s triangles, through its own `uvs`, into a
    `width` x `height` texel grid: for each triangle, every texel whose
    CENTRE lies inside it (barycentric test, either winding) is covered.
    The covered set is then dilated by one texel (8-neighbourhood) so a
    texel straddling a triangle edge -- including BC's own lettering sitting
    right up against the ID patch's own UV edge -- still counts. UV v maps
    directly to row (not flipped), matching `_render_review_png`'s
    convention. Returns a set of (x, y) texel coordinates; degenerate
    (zero-area) triangles contribute nothing."""
    uvs = patch["uvs"]
    covered = set()
    for tri in patch["triangles"]:
        (x0, y0), (x1, y1), (x2, y2) = (
            (uvs[i][0] * width, uvs[i][1] * height) for i in tri)
        area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        if abs(area) < 1e-12:
            continue
        min_x = max(0, int(math.floor(min(x0, x1, x2))))
        max_x = min(width - 1, int(math.ceil(max(x0, x1, x2))))
        min_y = max(0, int(math.floor(min(y0, y1, y2))))
        max_y = min(height - 1, int(math.ceil(max(y0, y1, y2))))
        for y in range(min_y, max_y + 1):
            for x in range(min_x, max_x + 1):
                px, py = x + 0.5, y + 0.5
                w0 = ((x1 - px) * (y2 - py) - (x2 - px) * (y1 - py)) / area
                w1 = ((x2 - px) * (y0 - py) - (x0 - px) * (y2 - py)) / area
                w2 = 1.0 - w0 - w1
                if w0 >= 0.0 and w1 >= 0.0 and w2 >= 0.0:
                    covered.add((x, y))

    dilated = set(covered)
    for x, y in covered:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                nx, ny = x + dx, y + dy
                if 0 <= nx < width and 0 <= ny < height:
                    dilated.add((nx, ny))
    return dilated


def _diff_texels(ref_rgba, base_rgba, footprint=None) -> set:
    """The set of (x, y) texels where `ref_rgba` differs from `base_rgba`
    by more than 24 in any RGB channel or in alpha (the literal brief rule
    -- no alpha-visibility gate: in BC's "_glow" textures alpha is the GLOW
    MASK, not opacity, and alpha 0 is still drawn as unlit hull, so a real
    letter can sit over alpha-0 pixels).

    `footprint`, if given (see `uv_footprint`), restricts the search to
    texels inside it -- this is how real BC content excludes leftover/
    export RGB noise in fully-unrelated regions of the texture without
    silently dropping real lettering over alpha-0 pixels."""
    ref = ref_rgba.convert("RGBA")
    base = base_rgba.convert("RGBA")
    w, h = ref.size
    rp, bp = ref.load(), base.load()
    texels = set()
    for y in range(h):
        for x in range(w):
            if footprint is not None and not _footprint_contains(footprint, x, y):
                continue
            r1, g1, b1, a1 = rp[x, y]
            r2, g2, b2, a2 = bp[x, y]
            if (max(abs(r1 - r2), abs(g1 - g2), abs(b1 - b2)) > 24
                    or abs(a1 - a2) > 24):
                texels.add((x, y))
    return texels


def lettering_bbox(ref_rgba, base_rgba, footprint=None) -> tuple:
    """Normalised (s0, t0, s1, t1) bounding box, over pixel edges, of
    `_diff_texels(ref_rgba, base_rgba, footprint)`. No isolated-texel
    filtering here -- that's `drop_isolated_texels`, applied by `build_decal`
    on top of this same texel set where BC's own lettering box is derived
    (spec S3.3 step 2), not baked into this general-purpose function."""
    w, h = ref_rgba.size
    return _bbox_from_texels(_diff_texels(ref_rgba, base_rgba, footprint), w, h)


def _alpha_texels(mask_rgba) -> set:
    """The set of (x, y) texels of `mask_rgba` whose alpha is greater than
    8."""
    mask = mask_rgba.convert("RGBA")
    w, h = mask.size
    mp = mask.load()
    return {(x, y) for y in range(h) for x in range(w) if mp[x, y][3] > 8}


def alpha_bbox(mask_rgba) -> tuple:
    """Normalised (u0, v0, u1, v1) bounding box, over pixel edges, of the
    pixels of `mask_rgba` whose alpha is greater than 8."""
    w, h = mask_rgba.size
    return _bbox_from_texels(_alpha_texels(mask_rgba), w, h)


# The 4 aspect-preserving orientations a mask can be authored in relative to
# BC's own lettering (spec S3.3 step 4). Order matters: ties in
# `choose_orientation` resolve to the first (= "identity") of a tie.
_ORIENTATIONS = ("identity", "rot180", "flip_u", "flip_v")


def _orient_fraction(orientation: str, fu: float, fv: float) -> tuple:
    """Map a fractional (fu, fv) in [0, 1]x[0, 1] through one of the 4
    orientations. Every orientation here is its own inverse, so this same
    function both "applies" an orientation to sample-space coordinates and
    "un-applies" it."""
    if orientation == "identity":
        return fu, fv
    if orientation == "rot180":
        return 1.0 - fu, 1.0 - fv
    if orientation == "flip_u":
        return 1.0 - fu, fv
    if orientation == "flip_v":
        return fu, 1.0 - fv
    raise ValueError(f"unknown orientation {orientation!r}")


def _iou(a: set, b: set) -> float:
    """Intersection-over-union of two texel sets; 1.0 if both are empty."""
    if not a and not b:
        return 1.0
    union = len(a | b)
    return (len(a & b) / union) if union else 0.0


def choose_orientation(bc_texels: set, bc_bounds: tuple,
                        mask_texels: set, mask_bounds: tuple) -> tuple:
    """Pick the orientation (see `_ORIENTATIONS`) under which `mask_texels`
    (e.g. a mask's own alpha>8 lettering, in the mask's full-image texel
    coordinates) best overlaps `bc_texels` (BC's own cleaned lettering, in
    the ID texture's full-image texel coordinates), both restricted to
    their own bounds (`_texel_bounds`-shaped 4-tuples) and resampled
    (nearest-neighbour, by fractional position within each bbox) into a
    common grid the size of `bc_bounds`. Returns `(name, scores)` where
    `scores` maps every orientation name to its IoU; ties -- including a
    lettering shape symmetric under all 4 -- go to `"identity"`."""
    bx0, by0, bx1, by1 = bc_bounds
    mx0, my0, mx1, my1 = mask_bounds
    bw, bh = bx1 - bx0 + 1, by1 - by0 + 1
    mw, mh = mx1 - mx0 + 1, my1 - my0 + 1
    bc_local = {(x - bx0, y - by0) for x, y in bc_texels
                if bx0 <= x <= bx1 and by0 <= y <= by1}

    scores = {}
    for orientation in _ORIENTATIONS:
        resampled = set()
        for j in range(bh):
            for i in range(bw):
                fu, fv = (i + 0.5) / bw, (j + 0.5) / bh
                su, sv = _orient_fraction(orientation, fu, fv)
                sx = mx0 + min(mw - 1, int(su * mw))
                sy = my0 + min(mh - 1, int(sv * mh))
                if (sx, sy) in mask_texels:
                    resampled.add((i, j))
        scores[orientation] = _iou(bc_local, resampled)

    best = max(_ORIENTATIONS, key=lambda o: scores[o])
    return best, scores


def build_decal(shapes: list, cls_cfg: dict, ref_img, base_img, mask_img,
                 diagnostics: dict = None) -> dict:
    """Build one `decals.json` "decals" entry (spec S3.3):

    1. The patch is the only shape with a texture basename containing 'ID'.
       Raise ValueError if there isn't exactly one, or if `cls_cfg
       ["target_shape"]` names no shape among `shapes`.
    2. Fit on the patch's `vertices`/`uvs` with its `normals`:
       `P(s, t) = fit["origin"] + (s - st0) * s_axis + (t - t0) * t_axis`
       (`fit_plane_st`'s own affine map -- see its docstring for why the
       intercept isn't simply `fit["origin"]` at s=0, t=0).
    3. BC's box `(s0, t0, s1, t1)` comes from the footprint-gated
       (`uv_footprint(patch, ...)`) differing texels between (`ref_img`,
       `base_img`), with `drop_isolated_texels` removing any stray texel
       with fewer than 2 differing 8-neighbours (Ruling D) before taking the
       bbox -- so a lone compression-noise texel can't widen the box. The
       mask box `(u0, v0, u1, v1)` comes from `alpha_bbox` on `mask_img`.
       Centres: `sc, tc` and `uc, vc`.
    4. `U = s_axis * (s1 - s0) / (u1 - u0)`, the ship-body vector for one
       full mask width. Uniform scale: the mask lettering width equals BC's
       lettering width.
    5. `V = normalise(t_axis - (t_axis . U^) U^) * |U| * (mask_h / mask_w)`.
       It's perpendicular to U, in the same sense as `t_axis`, and keeps the
       mask's pixels square.
    6. **Orientation is derived, not assumed (Ruling D).**
       `choose_orientation` scores the mask's own alpha>8 lettering against
       BC's cleaned lettering (from step 3) in the 4 aspect-preserving
       orientations (identity, rot180, flip_u, flip_v) and picks the best
       (ties -> identity). rot180 negates both `U` and `V`; flip_u negates
       only `U`; flip_v negates only `V` -- applied AFTER step 5, so `U`/`V`
       keep the same magnitude either way.
    7. `origin = P(sc, tc) - uc * U - vc * V` (`U`, `V` now oriented), which
       puts the mask lettering centre on BC's -- `uc`, `vc` are unchanged by
       the orientation: they're a property of the mask's OWN full-image
       pixel space, and this same closed form re-derives the one unknown
       (`origin`) correctly for any `U`, `V` by construction (verified
       against ground truth in
       `test_build_decal_derives_orientation_from_asymmetric_lettering`).
    8. Return `{"shape", "origin", "u_axis", "v_axis", "normal", "depth"}`,
       all floats passed through `to_f32`. If `diagnostics` is given (a
       dict), it's filled in-place with `"orientation"` and `"scores"` for
       CLI logging -- never part of the written JSON.
    """
    id_shapes = [s for s in shapes if any("ID" in t for t in s["textures"])]
    if len(id_shapes) != 1:
        raise ValueError(
            "expected exactly one shape with an 'ID' texture, found "
            f"{len(id_shapes)}")
    patch = id_shapes[0]

    target_name = cls_cfg["target_shape"]
    target = next((s for s in shapes if s["name"] == target_name), None)
    if target is None:
        raise ValueError(f"no shape named {target_name!r}")

    fit = fit_plane_st(patch["vertices"], patch["uvs"], patch["normals"])
    origin0, s_axis, t_axis = fit["origin"], fit["s_axis"], fit["t_axis"]
    st0, tt0 = fit["st_origin"]

    def eval_plane(s, t):
        return [origin0[k] + (s - st0) * s_axis[k] + (t - tt0) * t_axis[k]
                for k in range(3)]

    ref_w, ref_h = ref_img.size
    footprint = uv_footprint(patch, base_img.size[0], base_img.size[1])
    bc_texels = drop_isolated_texels(_diff_texels(ref_img, base_img, footprint))
    bc_bounds = _texel_bounds(bc_texels)
    s0, t0, s1, t1 = _bbox_from_texels(bc_texels, ref_w, ref_h)

    mask_texels = _alpha_texels(mask_img)
    mask_bounds = _texel_bounds(mask_texels)
    u0, v0, u1, v1 = _bbox_from_texels(mask_texels, *mask_img.size)

    sc, tc = (s0 + s1) / 2.0, (t0 + t1) / 2.0
    uc, vc = (u0 + u1) / 2.0, (v0 + v1) / 2.0

    s_scale = (s1 - s0) / (u1 - u0)
    u_vec = [c * s_scale for c in s_axis]
    u_len = math.sqrt(sum(c * c for c in u_vec))
    if u_len < 1e-12:
        raise ValueError("build_decal: degenerate u_axis")
    u_hat = [c / u_len for c in u_vec]

    t_dot_u = sum(t_axis[k] * u_hat[k] for k in range(3))
    t_perp = [t_axis[k] - t_dot_u * u_hat[k] for k in range(3)]
    t_perp_len = math.sqrt(sum(c * c for c in t_perp))
    if t_perp_len < 1e-12:
        raise ValueError("build_decal: s_axis and t_axis are not independent")
    mask_w, mask_h = mask_img.size
    v_len = u_len * (mask_h / mask_w)
    v_vec = [c / t_perp_len * v_len for c in t_perp]

    orientation, scores = choose_orientation(bc_texels, bc_bounds, mask_texels, mask_bounds)
    if diagnostics is not None:
        diagnostics["orientation"] = orientation
        diagnostics["scores"] = scores
    if orientation in ("rot180", "flip_u"):
        u_vec = [-c for c in u_vec]
    if orientation in ("rot180", "flip_v"):
        v_vec = [-c for c in v_vec]

    p_centre = eval_plane(sc, tc)
    origin = [p_centre[k] - uc * u_vec[k] - vc * v_vec[k] for k in range(3)]

    return {
        "shape": target_name,
        "origin": [to_f32(c) for c in origin],
        "u_axis": [to_f32(c) for c in u_vec],
        "v_axis": [to_f32(c) for c in v_vec],
        "normal": [to_f32(c) for c in fit["normal"]],
        "depth": to_f32(cls_cfg.get("depth", 2.0)),
    }


def decals_json(entries: dict) -> str:
    """Deterministic `decals.json` rendering: 2-space indent, trailing
    newline."""
    return json.dumps({"format": 1, "decals": entries}, indent=2) + "\n"


def _nif_shapes(abs_path: str):
    """Thin, lazily-imported wrapper around `_dauntless_host.nif_shapes`, so
    importing this module never requires the compiled extension."""
    import _dauntless_host
    return _dauntless_host.nif_shapes(abs_path)


def _ship_name(rel: str) -> str:
    """The `<Ship>` segment of a `data/Models/Ships/<Ship>/...` rel path."""
    return rel.split("/")[3]


def _find_texture(rel: str, texture_name: str):
    """Resolve a target shape's texture basename to an on-disk path, mod
    replacement first. Tries the ship's own High/ folder, then the shared Fed
    High/ folder; returns None if neither exists."""
    from engine import paths

    ship = _ship_name(rel)
    for candidate in (
            f"data/Models/Ships/{ship}/High/{texture_name}",
            f"data/Models/SharedTextures/FedShips/High/{texture_name}",
    ):
        path = paths.game_asset(candidate)
        if path.exists():
            return path
    return None


def _render_review_png(rel: str, review: dict, out_path: Path) -> None:
    """Render the target's own triangles in blue and the patch's rebuilt-UV
    triangles in red, over the target texture (or a blank canvas if the
    texture can't be found), scaled to 512x512. UV v is not flipped."""
    from PIL import Image, ImageDraw

    texture_name = review["target_texture"]
    img = None
    if texture_name:
        texture_path = _find_texture(rel, texture_name)
        if texture_path is not None:
            img = Image.open(texture_path).convert("RGB")
    if img is None:
        img = Image.new("RGB", (512, 512), "white")
    img = img.resize((512, 512))
    draw = ImageDraw.Draw(img)
    w, h = img.size

    def draw_tris(uvs, tris, color):
        for tri in tris:
            pts = [(uvs[i][0] * w, uvs[i][1] * h) for i in tri]
            draw.line([pts[0], pts[1], pts[2], pts[0]], fill=color, width=1)

    draw_tris(review["target_uvs"], review["target_tris"], "blue")
    draw_tris(review["uvs"], review["patch_tris"], "red")
    img.save(out_path)


def _summary_line(rel: str, file_hash: str, fix: dict) -> str:
    m = fix["merges"][0]
    max_err = m["max_fit_error"]
    max_err_str = "n/a" if max_err is None else f"{max_err:.2e}"
    return (f"{rel}  {file_hash}  {m['patch']['name']}→{m['target']['name']}  "
            f"{m['method']}  max_err={max_err_str}  uvs={len(m['uvs'])} "
            f"welds={len(m['weld'])}")


def _run_decals() -> None:
    """For each `DECAL_CLASSES` entry: load its NIF's shapes, its two BC
    textures (stock root) and its reference mask (project replacement, mod-
    overlaid), build one decal, and write that class's
    `Masks/decals.json` under the project replacements tree. A class that
    fails prints its error and does not abort the run."""
    from PIL import Image
    from engine import paths

    for cls_name, cfg in DECAL_CLASSES.items():
        try:
            nif_path = paths.game_root() / cfg["nif"]
            shapes = _nif_shapes(str(nif_path))
            if shapes is None:
                raise ValueError(f"could not parse {nif_path}")
            ref_img = Image.open(paths.game_root() / cfg["reference_registry"])
            base_img = Image.open(paths.game_root() / cfg["id_texture"])
            mask_img = Image.open(paths.game_asset(cfg["reference_mask"]))
            diagnostics = {}
            decal = build_decal(shapes, cfg, ref_img, base_img, mask_img,
                                 diagnostics=diagnostics)
        except Exception as exc:  # noqa: BLE001 -- one bad class must not abort the run
            print(f"{cls_name}  ERROR: {exc}")
            continue

        entries = {cfg["placement"]: decal}
        masks_dir = Path(cfg["nif"]).parent / "Masks"
        out_path = paths.project_asset_root() / "replacements" / masks_dir / "decals.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(decals_json(entries))
        scores_str = " ".join(f"{o}={s:.3f}" for o, s in diagnostics["scores"].items())
        print(f"{cls_name}  {cfg['placement']}  orientation={diagnostics['orientation']} "
              f"scores=[{scores_str}]  -> {out_path}")


def main(argv=None) -> None:
    """CLI entry point. For each mesh in `STOCK_MESHES` (or `--only`):
    resolve it under the stock game root, hash it, call `nif_shapes` and
    `build_fix`, print one summary line, and render a review PNG. A mesh
    that fails prints its error and does not abort the run. With `--write`,
    also writes `native/assets/mesh_fixes/<hash>.json`. With `--decals`
    (independent of `--write`), also generates every `DECAL_CLASSES`
    entry's `Masks/decals.json` (see `_run_decals`)."""
    from engine import paths

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", action="append", default=None,
                         help="restrict to this mesh's rel path (repeatable)")
    parser.add_argument("--target", action="append", default=[],
                         metavar="REL=SHAPE",
                         help="override the merge target shape for REL "
                              "(repeatable)")
    parser.add_argument("--review-dir", default=None,
                         help="where to write review PNGs (default: a "
                              "mesh_fix_review folder under the system temp "
                              "dir)")
    parser.add_argument("--write", action="store_true",
                         help="write native/assets/mesh_fixes/<hash>.json")
    parser.add_argument("--decals", action="store_true",
                         help="generate each DECAL_CLASSES entry's "
                              "Masks/decals.json (independent of --write)")
    args = parser.parse_args(argv)

    if args.decals:
        _run_decals()

    targets = dict(TARGET_OVERRIDES)
    for spec in args.target:
        rel, _, shape_name = spec.partition("=")
        targets[rel] = shape_name

    review_dir = (Path(args.review_dir) if args.review_dir is not None
                  else Path(tempfile.gettempdir()) / "mesh_fix_review")
    review_dir.mkdir(parents=True, exist_ok=True)

    meshes = STOCK_MESHES
    if args.only is not None:
        meshes = [rel for rel in STOCK_MESHES if rel in args.only]

    out_dir = None
    if args.write:
        out_dir = paths.project_asset_root() / "mesh_fixes"
        out_dir.mkdir(parents=True, exist_ok=True)

    for rel in meshes:
        try:
            mesh_path = paths.game_root() / rel
            file_hash = fnv1a64_hex(mesh_path.read_bytes())
            shapes = _nif_shapes(str(mesh_path))
            if shapes is None:
                raise ValueError(f"could not parse {mesh_path}")
            fix, review = build_fix(
                shapes, rel, targets.get(rel), UV_CLAMP_OVERRIDES.get(rel))
        except Exception as exc:  # noqa: BLE001 -- one bad mesh must not abort the run
            print(f"{rel}  ERROR: {exc}")
            continue

        print(_summary_line(rel, file_hash, fix))
        _render_review_png(rel, review, review_dir / (Path(rel).stem + ".png"))

        if args.write:
            (out_dir / f"{file_hash}.json").write_text(dumps(fix))


if __name__ == "__main__":
    main()
