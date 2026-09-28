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

Task 5 adds the CLI (`main()`) that walks `STOCK_MESHES`, calls `build_fix`,
writes `native/assets/mesh_fixes/<hash>.json`, and renders review PNGs.
"""
import json
import math
import struct

# Stock Federation hulls with an ID cut: 5 hulls x {High, Medium} LOD. Low
# LODs have no ID patch (see design doc S2.1) and are out of scope.
STOCK_MESHES: tuple = (
    "data/Models/Ships/Galaxy/Galaxy.nif",
    "data/Models/Ships/Galaxy/GalaxyMed.nif",
    "data/Models/Ships/Nebula/Nebula.nif",
    "data/Models/Ships/Nebula/NebulaMed.nif",
    "data/Models/Ships/Sovereign/Sovereign.nif",
    "data/Models/Ships/Sovereign/SovereignMed.nif",
    "data/Models/Ships/Akira/Akira.nif",
    "data/Models/Ships/Akira/AkiraMed.nif",
    "data/Models/Ships/Ambassador/Ambassador.nif",
    "data/Models/Ships/Ambassador/AmbassadorMed.nif",
)

# Per-mesh target-shape overrides, keyed by the `rel` path in STOCK_MESHES.
# Needed where a Medium LOD's ID patch borders more than one shape (e.g.
# Galaxy Med borders 3). Filled in by Task 5 from the review PNGs.
TARGET_OVERRIDES: dict = {}

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


def fit_projection(points, uvs):
    """Fit a planar (u, v) = f(position) projection over `points`/`uvs`
    pairs. Tries, in order, mirrored-xy, mirrored-xyz, unmirrored-xy,
    unmirrored-xyz; returns the first candidate whose worst-vertex error is
    below 1e-4 as (method, [u_coeffs, v_coeffs], max_err), or None if none
    of the four fit."""
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
        if max_err < 1e-4:
            return method, [cu, cv], max_err
    return None


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
    for a, b in edges:
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


def build_fix(shapes: list, rel: str, target_override):
    """Build one fix file's contents from a NIF's shapes (as returned by
    `_dauntless_host.nif_shapes`). Returns (fix_json_dict, review_info).
    Raises ValueError if the mesh doesn't have exactly one ID-texture shape,
    no candidate target region borders it, or the target choice is
    ambiguous under mirroring (see the design doc's ambiguity rule)."""
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
        key=lambda c: (c["fit_ok"], c["num_twinned"], c["region_count"]),
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
        method = "seam-copy"
        max_fit_error = None
        known = {}
        for i in region_idxs:
            sv = target_shape["vertices"][i]
            for pi, pv in enumerate(patch["vertices"]):
                if _distance(sv, pv) < _POS_TOL:
                    known[pi] = target_shape["uvs"][i]
        uvs_out = [[to_f32(u), to_f32(v)] for u, v in seam_copy(patch, known)]

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


def main():
    """CLI entry point -- filled in by Task 5 (walks STOCK_MESHES, writes
    native/assets/mesh_fixes/<hash>.json, renders review PNGs)."""
    raise NotImplementedError("tools/gen_mesh_fixes.py CLI lands in Task 5")


if __name__ == "__main__":
    main()
