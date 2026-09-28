import pytest

from tools import gen_mesh_fixes as g


def _plane_patch():
    # flat patch in z=5, s = 0.1 + x/200, t = 0.2 + y/100 (x in [-50,50], y in [0,60])
    pts, sts = [], []
    for x in (-50, 0, 50):
        for y in (0, 30, 60):
            pts.append((float(x), float(y), 5.0))
            sts.append((0.1 + x / 200.0, 0.2 + y / 100.0))
    return pts, sts


def test_fit_plane_st_inverts_exactly():
    pts, sts = _plane_patch()
    f = g.fit_plane_st(pts, sts)
    # the point at (s,t)=(0.1,0.2) is x=0,y=0,z=5
    p = [f["origin"][k] + 0.0 for k in range(3)]
    assert p == pytest.approx([0.0, 0.0, 5.0], abs=1e-6)
    assert f["s_axis"] == pytest.approx([200.0, 0.0, 0.0], abs=1e-4)   # d p / d s
    assert f["t_axis"] == pytest.approx([0.0, 100.0, 0.0], abs=1e-4)
    assert abs(f["normal"][2]) == pytest.approx(1.0, abs=1e-6)


def test_lettering_and_alpha_bboxes():
    from PIL import Image
    base = Image.new("RGBA", (10, 10), (100, 100, 100, 255))
    ref = base.copy(); ref.putpixel((2, 3), (0, 0, 0, 255)); ref.putpixel((7, 5), (0, 0, 0, 255))
    assert g.lettering_bbox(ref, base) == pytest.approx((0.2, 0.3, 0.8, 0.6))
    m = Image.new("RGBA", (20, 10), (0, 0, 0, 0)); m.putpixel((4, 2), (0, 0, 0, 255)); m.putpixel((15, 7), (0, 0, 0, 255))
    assert g.alpha_bbox(m) == pytest.approx((0.2, 0.2, 0.8, 0.8))


def test_lettering_bbox_footprint_gate_ignores_outside_texels():
    # Ruling C: a differing texel outside the footprint is ignored; one
    # inside still counts.
    from PIL import Image
    base = Image.new("RGBA", (10, 10), (100, 100, 100, 255))
    ref = base.copy()
    ref.putpixel((2, 3), (0, 0, 0, 255))   # inside the footprint below
    ref.putpixel((8, 8), (0, 0, 0, 255))   # outside it
    footprint = {(x, y) for x in range(0, 5) for y in range(0, 5)}
    assert g.lettering_bbox(ref, base, footprint=footprint) == pytest.approx(
        (0.2, 0.3, 0.3, 0.4))
    # without a footprint both differing texels are picked up
    assert g.lettering_bbox(ref, base) == pytest.approx((0.2, 0.3, 0.9, 0.9))


def test_lettering_bbox_counts_change_under_zero_alpha():
    # Ruling C: alpha in BC's "_glow" textures is a glow MASK, not opacity --
    # a=0 is drawn (unlit hull), so a changed pixel there must still count.
    # This is exactly the case an alpha-visibility gate gets wrong.
    from PIL import Image
    base = Image.new("RGBA", (10, 10), (100, 100, 100, 0))
    ref = base.copy()
    ref.putpixel((4, 4), (0, 0, 0, 0))     # RGB differs, alpha stays 0 both sides
    assert g.lettering_bbox(ref, base) == pytest.approx((0.4, 0.4, 0.5, 0.5))


def test_uv_footprint_covers_triangle_interior_and_dilated_edge():
    patch = {"uvs": [(0.1, 0.1), (0.6, 0.1), (0.1, 0.6)], "triangles": [(0, 1, 2)]}
    fp = g.uv_footprint(patch, 10, 10)
    assert (3, 3) in fp        # well inside the triangle
    assert (9, 9) not in fp    # far outside it


def test_build_decal_centres_and_scales_on_bc_lettering(monkeypatch):
    # A wider x domain than _plane_patch()'s (still z=5, s = 0.1 + x/200,
    # t = 0.2 + y/100) so the patch's own UVs -- and so its uv_footprint --
    # fully contain BC's lettering box (s in [0.2, 0.6]) once Ruling C gates
    # lettering_bbox by that footprint; _plane_patch()'s own s only reaches
    # 0.35, which would clip the letters short of x=60.
    pts, sts = [], []
    for x in (-50, 50, 150):
        for y in (0, 30, 60):
            pts.append((float(x), float(y), 5.0))
            sts.append((0.1 + x / 200.0, 0.2 + y / 100.0))
    # Full triangulation of the 3x3 (x, y) grid -- uv_footprint needs the
    # patch's triangles to actually cover the lettering region, not just a
    # single corner triangle.
    grid_tris = [(0, 3, 4), (0, 4, 1), (1, 4, 5), (1, 5, 2),
                 (3, 6, 7), (3, 7, 4), (4, 7, 8), (4, 8, 5)]
    patch = {"block": 2, "name": "idpatch", "textures": ["X_ID_glow.tga"], "vertices": pts,
             "normals": [(0.0, 0.0, 1.0)] * len(pts), "uvs": sts, "triangles": grid_tris, "hidden": False}
    target = {"block": 1, "name": "saucer", "textures": ["X_glow.tga"], "vertices": [(0.0, 0.0, 5.0)],
              "normals": [(0.0, 0.0, 1.0)], "uvs": [(0.0, 0.0)], "triangles": [], "hidden": False}
    from PIL import Image
    base = Image.new("RGBA", (100, 100), (100, 100, 100, 255))
    ref = base.copy()
    for x in range(20, 61):          # BC lettering box s 0.2..0.6, t 0.3..0.5 (normalised to pixel edges)
        for y in range(30, 51):
            ref.putpixel((x, y), (0, 0, 0, 255))
    mask = Image.new("RGBA", (128, 64), (0, 0, 0, 0))
    for x in range(32, 97):          # mask lettering box u 0.25..0.75, v 0.25..0.75
        for y in range(16, 49):
            mask.putpixel((x, y), (0, 0, 0, 255))
    cfg = {"target_shape": "saucer", "placement": "top"}
    d = g.build_decal([target, patch], cfg, ref, base, mask)
    assert d["shape"] == "saucer"
    s0, t0, s1, t1 = g.lettering_bbox(ref, base)
    u0, v0, u1, v1 = g.alpha_bbox(mask)
    O, U, V = d["origin"], d["u_axis"], d["v_axis"]
    def at(a, b):
        return [O[k] + a * U[k] + b * V[k] for k in range(3)]
    # Mask lettering centre lands on BC lettering centre (plane: x=(s-0.1)*200, y=(t-0.2)*100, z=5)
    sc, tc = (s0 + s1) / 2, (t0 + t1) / 2
    assert at((u0 + u1) / 2, (v0 + v1) / 2) == pytest.approx(
        [(sc - 0.1) * 200.0, (tc - 0.2) * 100.0, 5.0], abs=1e-3)
    # Uniform scale: mask lettering width == BC lettering width on the hull
    ulen = sum(x * x for x in U) ** 0.5
    vlen = sum(x * x for x in V) ** 0.5
    assert ulen * (u1 - u0) == pytest.approx((s1 - s0) * 200.0, rel=1e-4)
    # 128x64 mask keeps square pixels: |U| / |V| == 2
    assert ulen / vlen == pytest.approx(2.0, rel=1e-6)
    # V runs down the image = +t direction here; normal faces +z like the patch normals
    assert V[1] > 0 and d["normal"] == pytest.approx([0.0, 0.0, 1.0], abs=1e-6)


def test_decals_json_is_deterministic():
    e = {"top": {"shape": "s", "origin": [0.0, 0.0, 0.0], "u_axis": [1.0, 0.0, 0.0],
                 "v_axis": [0.0, 1.0, 0.0], "normal": [0.0, 0.0, 1.0], "depth": 2.0}}
    assert g.decals_json(e) == g.decals_json(e) and g.decals_json(e).endswith("\n")


def test_build_decal_refuses_missing_target_shape():
    pts, sts = _plane_patch()
    patch = {"block": 2, "name": "idpatch", "textures": ["X_ID_glow.tga"], "vertices": pts,
             "normals": [(0.0, 0.0, 1.0)] * len(pts), "uvs": sts, "triangles": [], "hidden": False}
    from PIL import Image
    img = Image.new("RGBA", (4, 4))
    with pytest.raises(ValueError):
        g.build_decal([patch], {"target_shape": "nope", "placement": "top"}, img, img, img)
