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


def main(argv=None) -> None:
    """CLI entry point. For each mesh in `STOCK_MESHES` (or `--only`):
    resolve it under the stock game root, hash it, call `nif_shapes` and
    `build_fix`, print one summary line, and render a review PNG. A mesh
    that fails prints its error and does not abort the run. With `--write`,
    also writes `native/assets/mesh_fixes/<hash>.json`."""
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
    args = parser.parse_args(argv)

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
            fix, review = build_fix(shapes, rel, targets.get(rel))
        except Exception as exc:  # noqa: BLE001 -- one bad mesh must not abort the run
            print(f"{rel}  ERROR: {exc}")
            continue

        print(_summary_line(rel, file_hash, fix))
        _render_review_png(rel, review, review_dir / (Path(rel).stem + ".png"))

        if args.write:
            (out_dir / f"{file_hash}.json").write_text(dumps(fix))


if __name__ == "__main__":
    main()
