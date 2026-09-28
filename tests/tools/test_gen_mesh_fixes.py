import json
import math

import pytest

from tools import gen_mesh_fixes as g


def _grid_shape(block, name, x0, x1, mirrored, tex="Hull_glow.tga", n=4, y0=0.0, y1=1.0):
    """A flat n×n grid over x∈[x0,x1], y∈[y0,y1] whose UVs are an exact
    projection: u = 0.1 + 0.4*f(x), v = 0.2 + 0.5*y, f = |x| if mirrored."""
    verts, uvs, tris = [], [], []
    for j in range(n + 1):
        for i in range(n + 1):
            x = x0 + (x1 - x0) * i / n
            y = y0 + (y1 - y0) * j / n
            verts.append((x, y, 0.0))
            fx = abs(x) if mirrored else x
            uvs.append((0.1 + 0.4 * fx, 0.2 + 0.5 * y))
    for j in range(n):
        for i in range(n):
            a = j * (n + 1) + i
            tris += [(a, a + 1, a + n + 2), (a, a + n + 2, a + n + 1)]
    return {"block": block, "name": name, "textures": [tex], "vertices": verts,
            "normals": [(0.0, 0.0, 1.0)] * len(verts), "uvs": uvs,
            "triangles": tris, "hidden": False}


def _shape(block, name, tex, vertices, uvs, triangles):
    return {"block": block, "name": name, "textures": [tex], "vertices": vertices,
            "normals": [(0.0, 0.0, 1.0)] * len(vertices), "uvs": uvs,
            "triangles": triangles, "hidden": False}


def test_fnv_known_vectors():
    assert g.fnv1a64_hex(b"") == "cbf29ce484222325"
    assert g.fnv1a64_hex(b"foobar") == "85944171f73967e8"


@pytest.mark.parametrize("mirrored", [True, False])
def test_fit_projection_recovers_exact_mapping(mirrored):
    s = _grid_shape(1, "saucer", -1.0, 1.0, mirrored)
    method, coeffs, err = g.fit_projection(s["vertices"], s["uvs"])
    assert err < 1e-6
    assert ("mirrored" in method) == mirrored
    u, v = g.apply_projection(method, coeffs, (-0.5, 0.5, 0.0))
    assert math.isclose(u, 0.1 + 0.4 * (0.5 if mirrored else -0.5), abs_tol=1e-6)


def test_fit_projection_rejects_non_planar():
    s = _grid_shape(1, "saucer", -1.0, 1.0, False)
    s["uvs"] = [(u + 0.3 * y * y, v) for (u, v), (_, y, _) in zip(s["uvs"], s["vertices"])]
    assert g.fit_projection(s["vertices"], s["uvs"]) is None


def test_regions_split_on_uv_seams_and_join_flat_shading():
    s = _grid_shape(1, "saucer", 0.0, 1.0, False, n=2)
    labels = g.regions(s)
    assert len(set(labels)) == 1
    # Duplicate one vertex with a different UV: a seam, still one region per side.
    s2 = dict(s, vertices=s["vertices"] + [s["vertices"][0]],
              uvs=s["uvs"] + [(0.9, 0.9)], normals=s["normals"] + [(0, 0, 1)])
    assert len(set(g.regions(s2))) == 2


def _saucer_and_patch():
    # Saucer spans both sides of x=0 (as real mirrored saucers do); the patch
    # sits above it (y∈[1,2]) sharing the y=1 edge, crossing the centreline.
    target = _grid_shape(1, "saucer", -2.0, 2.0, True)
    patch = _grid_shape(2, "idpatch", -1.0, 1.0, True, tex="Hull_ID_glow.tga", y0=1.0, y1=2.0)
    patch["uvs"] = [(0.0, 0.0)] * len(patch["uvs"])   # the ID texture's own UVs
    return target, patch


def test_build_fix_merges_patch_with_exact_uvs_and_welds():
    target, patch = _saucer_and_patch()
    fix, review = g.build_fix([target, patch], "data/Models/Ships/X/X.nif", None)
    m = fix["merges"][0]
    assert m["patch"] == {"block": 2, "name": "idpatch"}
    assert m["target"] == {"block": 1, "name": "saucer"}
    assert "mirrored" in m["method"]
    assert len(m["uvs"]) == len(patch["vertices"])
    # Patch vertex at x=1,y=2 continues the saucer mapping: u=0.1+0.4*|1|,
    # v=0.2+0.5*2=1.2 -- but the saucer region's own v only spans [0.2, 0.7]
    # (y in [0, 1]), so the extrapolated v is clamped to that region's max.
    idx = patch["vertices"].index((1.0, 2.0, 0.0))
    assert m["uvs"][idx] == pytest.approx([0.5, 0.7], abs=1e-6)
    # Mirror side: the x=-1 vertex gets the same u.
    idx_neg = patch["vertices"].index((-1.0, 2.0, 0.0))
    assert m["uvs"][idx_neg][0] == pytest.approx(0.5, abs=1e-6)
    # Shared y=1 edge: patch x∈{-1,-.5,0,.5,1} vs saucer x∈{-2,-1,0,1,2} → 3 coincide.
    assert len(m["weld"]) == 3
    assert m["normals"] is None


def test_build_fix_clamps_extrapolated_uv_into_region_bounds():
    # Target region UV bounds: u in [0.1, 0.9] (x in [-2, 2], mirrored),
    # v in [0.2, 0.7] (y in [0, 1]).
    target = _grid_shape(1, "saucer", -2.0, 2.0, True)
    # The patch shares the y=1 edge with the target (x in [-1, 1]) but
    # extends far past it to y=5 -- a linear extrapolation whose v value at
    # y=5 (0.2 + 0.5*5 = 2.7) lands far outside the region's own v range,
    # and is NOT a twin of any region vertex (the region only reaches y=1),
    # so the seam-snap in the local-fit path can't save it -- and this case
    # doesn't even take that path, since the whole-region fit is exact here.
    patch = _grid_shape(2, "idpatch", -1.0, 1.0, True, tex="Hull_ID_glow.tga",
                         y0=1.0, y1=5.0)
    patch["uvs"] = [(0.0, 0.0)] * len(patch["uvs"])   # the ID texture's own UVs

    fix, _review = g.build_fix([target, patch], "r", None)
    m = fix["merges"][0]
    # Confirm the premise: this is the exact global fit, not local-fit --
    # the clamp must work on that path too, not just the local-fit one.
    assert not m["method"].startswith("local-")

    region_us = [u for u, _v in target["uvs"]]
    region_vs = [v for _u, v in target["uvs"]]
    u_min, u_max = min(region_us), max(region_us)
    v_min, v_max = min(region_vs), max(region_vs)

    far_idx = patch["vertices"].index((1.0, 5.0, 0.0))
    u_far, v_far = m["uvs"][far_idx]
    assert v_far == pytest.approx(v_max, abs=1e-6)
    assert u_min - 1e-6 <= u_far <= u_max + 1e-6

    # The shared y=1 seam vertex is a twin and must stay exact, unaffected
    # by the clamp.
    seam_idx = patch["vertices"].index((1.0, 1.0, 0.0))
    assert m["uvs"][seam_idx] == pytest.approx([0.5, 0.7], abs=1e-6)


def test_build_fix_refuses_ambiguous_mirroring():
    # Saucer region wholly on x<=0 fits BOTH projections; a patch reaching x>0
    # cannot be resolved without guessing.
    target = _grid_shape(1, "saucer", -2.0, 0.0, True)
    patch = _grid_shape(2, "idpatch", -1.0, 1.0, True, tex="Hull_ID_glow.tga", y0=1.0, y1=2.0)
    with pytest.raises(ValueError, match="ambiguous"):
        g.build_fix([target, patch], "r", None)


def test_seam_copy_interpolates_interior():
    patch = _grid_shape(2, "idpatch", 0.0, 1.0, False, n=2)
    known = {i: uv for i, uv in enumerate(patch["uvs"]) if i != 4}  # 4 = centre
    out = g.seam_copy(patch, known)
    assert out[4] == pytest.approx(patch["uvs"][4], abs=1e-4)


def test_dumps_is_deterministic_and_float32():
    target, patch = _saucer_and_patch()
    a = g.dumps(g.build_fix([target, patch], "r", None)[0])
    b = g.dumps(g.build_fix([target, patch], "r", None)[0])
    assert a == b and a.endswith("\n")
    for u, v in json.loads(a)["merges"][0]["uvs"]:
        assert g.to_f32(u) == u and g.to_f32(v) == v


def test_build_fix_refuses_mesh_without_id_shape():
    with pytest.raises(ValueError):
        g.build_fix([_grid_shape(1, "saucer", 0, 1, False)], "r", None)


def test_build_fix_uses_local_fit_ring_when_whole_region_fails_but_snaps_twins():
    # The patch is a single 5-vertex border row at y=10 (its own world-bbox
    # diagonal is therefore exactly 2.0, x=-1..1 -- so the ring radius is a
    # known 0.05*2.0=0.1 GU). The target region has 8 rows: y=10, 9.97,
    # 9.94, 9.91 (0, 0.03, 0.06, 0.09 GU from the patch -- all INSIDE the
    # 0.1 ring, and crucially FOUR distinct distances, not two: a fit
    # linear in y can pass through two rows exactly, so an earlier version
    # of this test used only two and the seam came out exact even with the
    # snap deleted -- see the design doc's fix-round-1 note); plus y=9.5,
    # 9.0, 8.5, 8.0 (0.5-2.0 GU away -- outside the ring but still inside a
    # one-diagonal-expanded bounding box, so this also still distinguishes
    # the ring rule from the old bbox-expansion rule). UVs are the usual
    # planar-mirrored map plus k*(distance from the patch edge)^2, k=0.05:
    # small but genuinely UNFITTABLE-exactly within the ring (four distinct
    # curvature values), and large over the whole region.
    k = 0.05

    def uv(x, y):
        fx = abs(x)
        d = 10.0 - y
        return (0.1 + 0.4 * fx + k * d * d, 0.2 + 0.5 * y)

    xs = (-1.0, -0.5, 0.0, 0.5, 1.0)
    ys = (10.0, 9.97, 9.94, 9.91, 9.5, 9.0, 8.5, 8.0)
    verts = [(x, y, 0.0) for y in ys for x in xs]
    uvs = [uv(x, y) for (x, y, _z) in verts]
    # A chain of overlapping triangles sharing consecutive vertices --
    # enough for regions() to union everything into one connected component.
    triangles = [(i, i + 1, i + 2) for i in range(len(verts) - 2)]
    target = _shape(1, "saucer", "Hull_glow.tga", verts, uvs, triangles)

    patch_verts = [(x, 10.0, 0.0) for x in xs]
    patch = _shape(2, "idpatch", "Hull_ID_glow.tga", patch_verts,
                    [(0.0, 0.0)] * len(patch_verts), [])

    # Confirm the premise: the whole region fails even the LOOSER 5e-3
    # tolerance (not just the strict 1e-4 exact-fit one), so this genuinely
    # exercises the ring window and not a lucky whole-region fit.
    assert g.fit_projection(verts, uvs) is None
    assert g._fit_candidates(verts, uvs, 5e-3) is None

    fix, _review = g.build_fix([target, patch], "data/Models/Ships/X/X.nif", None)
    m = fix["merges"][0]
    assert m["method"].startswith("local-")
    assert m["max_fit_error"] is not None
    assert m["max_fit_error"] <= 5e-3

    # Every patch vertex is an exact twin (the border row) and must come out
    # with EXACTLY the twin's own UV (the snap). Without the snap, the
    # local fit's own (merely close, ~4.5e-5 off here) projected value
    # would land here instead, and this equality would fail.
    for i, (x, y, _z) in enumerate(patch_verts):
        twin = verts.index((x, y, 0.0))
        expected = [g.to_f32(c) for c in uvs[twin]]
        assert m["uvs"][i] == expected


def test_build_fix_ranks_by_twin_count_before_fit_quality():
    # Patch: 5 vertices twin the big region; 1 twins a tiny 3-vertex island
    # that fits EXACTLY (any 3 non-degenerate points always do -- 3
    # unknowns, 3 equations). The big region's x=z=0 for every vertex makes
    # its design matrix rank-deficient in fx and z, so no candidate can fit
    # it at all, regardless of the (arbitrary) UVs chosen -- guaranteeing
    # "big region, no exact fit" without depending on any float tolerance.
    patch_verts = [(0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 2.0, 0.0),
                   (0.0, 3.0, 0.0), (0.0, 4.0, 0.0), (0.0, 10.0, 0.0)]
    patch = _shape(9, "idpatch", "Hull_ID_glow.tga", patch_verts,
                   [(0.0, 0.0)] * len(patch_verts), [])

    big_verts = [(0.0, float(y), 0.0) for y in range(7)]
    big = _shape(1, "big", "Hull_glow.tga", big_verts,
                 [(0.5, 0.5)] * len(big_verts),
                 [(0, 1, 2), (2, 3, 4), (4, 5, 6)])

    small_verts = [(0.0, 10.0, 0.0), (2.0, 11.0, 0.0), (1.0, 9.0, 0.0)]
    small = _shape(2, "small", "Hull_glow.tga", small_verts,
                   [(0.1, 0.1), (0.2, 0.3), (0.4, 0.1)], [(0, 1, 2)])

    # Confirm the premise underlying the construction above.
    assert g.fit_projection(big_verts, [(0.5, 0.5)] * len(big_verts)) is None
    assert g.fit_projection(
        small_verts, [(0.1, 0.1), (0.2, 0.3), (0.4, 0.1)]) is not None

    fix, _review = g.build_fix([patch, big, small], "r", None)
    assert fix["merges"][0]["target"]["name"] == "big"


def _fake_fix(rel):
    return {
        "format": 1,
        "source": rel,
        "generator": "test",
        "merges": [{
            "patch": {"block": 1, "name": "idpatch"},
            "target": {"block": 0, "name": "saucer"},
            "method": "planar",
            "max_fit_error": 1e-6,
            "uvs": [[0.1, 0.2], [0.3, 0.4]],
            "weld": [[0, 0]],
            "normals": None,
        }],
    }, {
        "target_texture": "",
        "uvs": [[0.1, 0.2], [0.3, 0.4]],
        "patch_tris": [[0, 1, 0]],
        "target_uvs": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]],
        "target_tris": [[0, 1, 2]],
    }


def test_main_survives_one_bad_mesh_and_only_writes_with_flag(
        tmp_path, monkeypatch, capsys):
    mesh_ok = "data/Models/Ships/Ok/Ok.nif"
    mesh_bad = "data/Models/Ships/Bad/Bad.nif"

    game_root = tmp_path / "game"
    (game_root / "data/Models/Ships/Ok").mkdir(parents=True)
    (game_root / "data/Models/Ships/Bad").mkdir(parents=True)
    (game_root / mesh_ok).write_bytes(b"ok-bytes")
    (game_root / mesh_bad).write_bytes(b"bad-bytes")

    review_dir = tmp_path / "review"
    fix_dir = tmp_path / "native_assets"

    def fake_build_fix(shapes, rel, target_override):
        if rel == mesh_bad:
            raise ValueError("no candidate target region borders the ID patch")
        return _fake_fix(rel)

    monkeypatch.setattr(g, "STOCK_MESHES", (mesh_bad, mesh_ok))
    monkeypatch.setattr(g, "_nif_shapes", lambda path: "shapes")
    monkeypatch.setattr(g, "build_fix", fake_build_fix)

    from engine import paths
    monkeypatch.setattr(paths, "game_root", lambda: game_root)
    monkeypatch.setattr(paths, "project_asset_root", lambda: fix_dir)

    # Dry run: no --write.
    g.main(["--review-dir", str(review_dir)])
    out = capsys.readouterr().out
    assert f"{mesh_bad}  ERROR: no candidate target region borders the ID patch" in out
    assert mesh_ok in out and "planar" in out
    assert (review_dir / "Ok.png").exists()
    assert not (review_dir / "Bad.png").exists()
    assert not fix_dir.exists()

    # --write: only the surviving mesh gets a fix file.
    g.main(["--review-dir", str(review_dir), "--write"])
    written = list((fix_dir / "mesh_fixes").glob("*.json"))
    assert len(written) == 1
    assert written[0].name == g.fnv1a64_hex(b"ok-bytes") + ".json"
