import base64

import pytest

from tools.shape_diff import ShapeDiffError, frames, payload

GOLDEN_B64 = (
    "QlNEMQEABwAAAAQAAgABAAEAAQABAAEAAgAAAIA/AAAAQAAAQEAAAAAAgD4AAEA/AAAAPwAAAD8"
    "AAAAAzczMPc3MTD6amZk+zczMPgAAgD8AAAA/AACAPgAAgD8BAAAAAgAEAA=="
)

GOLDEN_EDIT = {
    "block": 7, "orig_vertex_count": 4, "orig_triangle_count": 2,
    "moves": [(2, (1.0, 2.0, 3.0))],
    "uvs": [(0, (0.25, 0.75))],
    "add_vertices": [{"pos": (0.5, 0.5, 0.0), "uv0": (0.1, 0.2),
                      "uv1": (0.3, 0.4), "color": (1.0, 0.5, 0.25, 1.0)}],
    "remove_triangles": [1],
    "add_triangles": [(0, 2, 4)],
}


def test_payload_matches_cpp_golden():
    assert payload.encode_b64([GOLDEN_EDIT]) == GOLDEN_B64
    assert len(base64.b64decode(GOLDEN_B64)) == 100


def test_payload_missing_lists_are_empty():
    raw = payload.encode([{"block": 1, "orig_vertex_count": 3, "orig_triangle_count": 1}])
    assert raw == b"BSD1" + bytes([1, 0, 1, 0, 0, 0, 3, 0, 1, 0]) + bytes(10)


def test_payload_refuses_index_overflow():
    with pytest.raises(ShapeDiffError):
        payload.encode([{"block": 1, "orig_vertex_count": 70000, "orig_triangle_count": 1}])


def test_axis_swap_round_trips():
    p = (1.5, -2.25, 3.125)
    assert frames.bc_to_obj(p) == (1.5, 3.125, 2.25)
    assert frames.obj_to_bc(frames.bc_to_obj(p)) == p


def test_affine_inverse_undoes_translation_rotation_scale():
    # column-major: rotate 90 deg about z, scale 2, translate (10, 20, 30)
    m = [0, 2, 0, 0,  -2, 0, 0, 0,  0, 0, 2, 0,  10, 20, 30, 1]
    p = (1.0, 2.0, 3.0)
    q = frames.apply(m, p)
    assert q == pytest.approx((10 - 4.0, 20 + 2.0, 36.0))
    back = frames.apply(frames.affine_inverse(m), q)
    assert back == pytest.approx(p, abs=1e-12)


from pathlib import Path

from tools.shape_diff import obj_io


def _shape(block=11, parent="wall side pnls 01", offset=(0.0, 0.0, 0.0)):
    """A unit quad with a UV seam: vertices 1 and 4 share a position but not a UV."""
    ox, oy, oz = offset
    verts = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (1, 0, 0)]
    return {
        "block": block, "parent": parent, "hidden": False,
        "vertices": [(x + ox, y + oy, z + oz) for x, y, z in verts],
        "uvs": [(0, 0), (0.5, 0), (0.5, 1), (0, 1), (1.0, 0)],
        "colors": [(1, 1, 1, 1)] * 5, "uvs1": [],
        "triangles": [(0, 1, 2), (0, 2, 3), (4, 2, 1)],
        "textures": ["Map 1.tga"],
        "world": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, ox, oy, oz, 1],
    }


def test_object_name_and_block_round_trip():
    assert obj_io.object_name(_shape(468, "Material: D walls 1")) == "b0468_Material_D_walls_1"
    assert obj_io.block_of("b0468_Material_D_walls_1") == 468
    with pytest.raises(ShapeDiffError):
        obj_io.block_of("Cube")


def test_write_then_read_welds_by_position_and_keeps_uvs(tmp_path):
    obj, mtl = tmp_path / "s.obj", tmp_path / "s.mtl"
    obj_io.write_obj([_shape()], obj, mtl, lambda name: None)
    objs = obj_io.read_objects(obj)
    m = objs["b0011_wall_side_pnls_01"]
    assert len(m.positions) == 4                 # seam duplicate welded
    assert m.positions[1] == pytest.approx((1, 0, 0))
    assert len(m.faces) == 2                     # (4,2,1) is degenerate after welding
    uvs = sorted(uv for f in m.faces for _, uv in f)
    assert (0.5, 1.0) in [tuple(round(c, 6) for c in uv) for uv in uvs]
    assert "usemtl Map_1.tga" in obj.read_text()


def test_read_objects_ignores_colours_normals_and_groups(tmp_path):
    p = tmp_path / "b.obj"
    p.write_text(
        "# Blender\nmtllib b.mtl\no b0003_x\n"
        "v 0 0 0 1 0 0\nv 1 0 0 1 0 0\nv 1 1 0 1 0 0\n"
        "vn 0 1 0\nvt 0 1\nvt 1 1\nvt 1 0\ns 0\nusemtl m\n"
        "f 1/1/1 2/2/1 3/3/1\n"
        "o b0004_y\nv 5 5 5\nv 6 5 5\nv 6 6 5\nf 4 5 6\n")
    objs = obj_io.read_objects(p)
    a, b = objs["b0003_x"], objs["b0004_y"]
    assert a.positions[1] == pytest.approx((1, 0, 0))     # OBJ (1,0,0) -> BC (1,-0,0)
    assert a.faces == [[(0, (0.0, 0.0)), (1, (1.0, 0.0)), (2, (1.0, 1.0))]]
    assert b.faces == [[(0, None), (1, None), (2, None)]]  # global -> local indices
    assert b.positions[0] == pytest.approx((5, -5, 5))


def test_hidden_shapes_are_written_and_read_correctly(tmp_path):
    obj, mtl = tmp_path / "hidden.obj", tmp_path / "hidden.mtl"
    visible = _shape(block=10, parent="visible panel")
    hidden = _shape(block=20, parent="hidden panel", offset=(5.0, 0.0, 0.0))
    hidden["hidden"] = True

    obj_io.write_obj([visible, hidden], obj, mtl, lambda name: None)
    objs = obj_io.read_objects(obj)

    assert "b0010_visible_panel" in objs
    vis = objs["b0010_visible_panel"]
    assert len(vis.positions) > 0
    assert len(vis.faces) > 0

    assert "b0020_hidden_panel_hidden" in objs
    hid = objs["b0020_hidden_panel_hidden"]
    assert len(hid.positions) > 0
    assert len(hid.faces) > 0

    assert obj_io.block_of("b0020_hidden_panel_hidden") == 20


def test_read_objects_preserves_n_gon_face_order(tmp_path):
    p = tmp_path / "quad.obj"
    p.write_text(
        "o b0001_quad\n"
        "v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\n"
        "vt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\n"
        "f 1/1 2/2 3/3 4/4\n")
    objs = obj_io.read_objects(p)
    quad = objs["b0001_quad"]
    assert len(quad.faces) == 1
    face = quad.faces[0]
    assert len(face) == 4
    assert face[0] == (0, (0.0, 1.0))
    assert face[1] == (1, (1.0, 1.0))
    assert face[2] == (2, (1.0, 0.0))
    assert face[3] == (3, (0.0, 0.0))
