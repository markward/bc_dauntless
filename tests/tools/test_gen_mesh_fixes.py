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
    # Patch vertex at x=1,y=2 continues the saucer mapping: u=0.1+0.4*|1|, v=0.2+0.5*2.
    idx = patch["vertices"].index((1.0, 2.0, 0.0))
    assert m["uvs"][idx] == pytest.approx([0.5, 1.2], abs=1e-6)
    # Mirror side: the x=-1 vertex gets the same u.
    idx_neg = patch["vertices"].index((-1.0, 2.0, 0.0))
    assert m["uvs"][idx_neg][0] == pytest.approx(0.5, abs=1e-6)
    # Shared y=1 edge: patch x∈{-1,-.5,0,.5,1} vs saucer x∈{-2,-1,0,1,2} → 3 coincide.
    assert len(m["weld"]) == 3
    assert m["normals"] is None


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
