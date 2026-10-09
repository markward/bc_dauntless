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


def test_affine_inverse_raises_shape_diff_error_on_singular_matrix():
    singular = [0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 1]
    with pytest.raises(ShapeDiffError, match="singular"):
        frames.affine_inverse(singular)


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
    with pytest.raises(ShapeDiffError, match="EMPTY scene"):
        obj_io.block_of("Cube")


def test_mat_name_strips_directory_part():
    assert obj_io._mat_name({"textures": ["data/Models/Sets/DBridge/High/Map 1.tga"]}) == "Map_1.tga"
    assert obj_io._mat_name({"textures": [r"High\Map 1.tga"]}) == "Map_1.tga"
    assert obj_io._mat_name({"textures": ["Map 1.tga"]}) == "Map_1.tga"
    assert obj_io._mat_name({"textures": []}) == "none"


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


def test_read_objects_refuses_out_of_range_vertex_index(tmp_path):
    p = tmp_path / "bad.obj"
    p.write_text("o b0001_x\nv 0 0 0\nv 1 0 0\nv 1 1 0\nf 1 2 9\n")
    with pytest.raises(ShapeDiffError, match="line 5"):
        obj_io.read_objects(p)


def test_read_objects_refuses_out_of_range_uv_index(tmp_path):
    p = tmp_path / "bad.obj"
    p.write_text("o b0001_x\nv 0 0 0\nv 1 0 0\nv 1 1 0\nvt 0 0\nf 1/1 2/2 3/9\n")
    with pytest.raises(ShapeDiffError, match="line 6"):
        obj_io.read_objects(p)


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


from tools.shape_diff import match


def _permute(mesh, perm):
    """Simulate Blender reordering: new index k holds old vertex perm[k]."""
    inv = {old: new for new, old in enumerate(perm)}
    out = obj_io.ObjMesh()
    out.positions = [mesh.positions[o] for o in perm]
    out.faces = [[(inv[v], uv) for v, uv in f] for f in mesh.faces]
    return out


def _export_read(tmp_path, shapes):
    obj, mtl = tmp_path / "x.obj", tmp_path / "x.mtl"
    obj_io.write_obj(shapes, obj, mtl, lambda n: None)
    return obj_io.read_objects(obj)


def test_identify_maps_every_vertex_including_seam_duplicates(tmp_path):
    s = _shape(offset=(10.0, -4.0, 2.0))
    m = _export_read(tmp_path, [s])["b0011_wall_side_pnls_01"]
    m = _permute(m, [3, 1, 0, 2])
    ids = match.identify(s, m)
    assert ids == [[3], [1, 4], [0], [2]]


def test_identify_refuses_unknown_vertex(tmp_path):
    s = _shape()
    m = _export_read(tmp_path, [s])["b0011_wall_side_pnls_01"]
    m.positions[2] = (7.0, 7.0, 7.0)
    with pytest.raises(ShapeDiffError, match="vertex 2"):
        match.identify(s, m)


def test_identify_tolerates_missing_duplicate_faces(tmp_path):
    s = _shape()
    s["triangles"] = s["triangles"] + [(0, 1, 2)]      # exact duplicate triangle
    m = _export_read(tmp_path, [s])["b0011_wall_side_pnls_01"]
    m.faces = m.faces[:1]                               # Blender dropped faces
    assert len(match.identify(s, m)) == 4


def _moved(mesh, k, p):
    out = obj_io.ObjMesh()
    out.positions = list(mesh.positions)
    out.positions[k] = p
    out.faces = [list(f) for f in mesh.faces]
    return out


def _retex(mesh, changes):
    """changes: {(face_index, local_vertex): new_uv} -- mutate only those
    corners, leaving every other corner's UV untouched."""
    out = obj_io.ObjMesh()
    out.positions = list(mesh.positions)
    out.faces = []
    for fi, face in enumerate(mesh.faces):
        out.faces.append([(v, changes.get((fi, v), uv)) for v, uv in face])
    return out


def _seam_shape(block=11, parent="wall side pnls 01"):
    """Two quads sharing an edge. The shared edge's two vertices are each
    duplicated -- one original copy per quad, same position, different
    authored UV -- a real UV seam (unlike _shape()'s lone seam vertex, which
    sits only in a triangle degenerate after welding)."""
    verts = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
             (1, 0, 0), (2, 0, 0), (2, 1, 0), (1, 1, 0)]
    uvs = [(0, 0), (0.5, 0), (0.5, 1), (0, 1),
           (0, 0), (1, 0), (1, 1), (0, 1)]
    return {
        "block": block, "parent": parent, "hidden": False,
        "vertices": verts,
        "uvs": uvs,
        "colors": [(1, 1, 1, 1)] * 8, "uvs1": [],
        "triangles": [(0, 1, 2), (0, 2, 3), (4, 5, 6), (4, 6, 7)],
        "textures": ["Map 1.tga"],
        "world": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
    }


def test_unchanged_edit_produces_no_edits(tmp_path):
    s = _shape()
    objs = _export_read(tmp_path, [s])
    assert match.diff([s], objs, objs) == []


def test_move_moves_every_welded_duplicate(tmp_path):
    s = _shape()
    base = _export_read(tmp_path, [s])["b0011_wall_side_pnls_01"]
    edit = _moved(base, 1, (1.25, 0.0, 0.5))           # the seam vertex
    e = match.diff_shape(s, base, edit)
    assert e["block"] == 11 and e["orig_vertex_count"] == 5 and e["orig_triangle_count"] == 3
    assert [i for i, _ in e["moves"]] == [1, 4]
    assert e["moves"][0][1] == pytest.approx((1.25, 0.0, 0.5))
    assert not e.get("add_vertices") and not e.get("add_triangles")


def test_move_is_stored_in_shape_local_frame(tmp_path):
    s = _shape(offset=(100.0, 50.0, 10.0))
    base = _export_read(tmp_path, [s])["b0011_wall_side_pnls_01"]
    edit = _moved(base, 2, (101.0, 51.0, 10.75))        # model space
    e = match.diff_shape(s, base, edit)
    assert e["moves"] == [(2, pytest.approx((1.0, 1.0, 0.75)))]


def test_move_and_uv_edit_together_are_both_recorded(tmp_path):
    s = _shape()
    base = _export_read(tmp_path, [s])["b0011_wall_side_pnls_01"]
    edit = _moved(base, 1, (1.25, 0.0, 0.5))           # move the seam vertex
    # vertex 1's only corner is face 0 (vertex 4's degenerate triangle was
    # dropped by the weld) -- touch its UV there too.
    edit = _retex(edit, {(0, 1): (0.6, 0.0)})
    e = match.diff_shape(s, base, edit)
    assert [i for i, _ in e["moves"]] == [1, 4]
    assert e["moves"][0][1] == pytest.approx((1.25, 0.0, 0.5))
    assert e["uvs"] == [(1, pytest.approx((0.6, 0.0)))]


def test_uv_only_edit_on_one_quad_records_only_that_quads_originals(tmp_path):
    s = _seam_shape()
    name = obj_io.object_name(s)
    base = _export_read(tmp_path, [s])[name]
    # faces 0, 1 are quad A (originals 0, 1, 2, 3); faces 2, 3 are quad B
    # (originals 4, 5, 6, 7), sharing local vertices 1 and 2 at the seam.
    changes = {}
    for fi in (0, 1):
        for v, uv in base.faces[fi]:
            changes[(fi, v)] = (uv[0] + 0.1, uv[1] + 0.1)
    edit = _retex(base, changes)
    e = match.diff_shape(s, base, edit)
    assert e["moves"] == []
    assert sorted(i for i, _ in e["uvs"]) == [0, 1, 2, 3]
    by_orig = dict(e["uvs"])
    for orig in (0, 1, 2, 3):
        bu, bv = s["uvs"][orig]
        assert by_orig[orig] == pytest.approx((bu + 0.1, bv + 0.1))


def test_uv_seam_edit_in_one_quad_leaves_the_other_quads_copy_untouched(tmp_path):
    s = _seam_shape()
    name = obj_io.object_name(s)
    base = _export_read(tmp_path, [s])[name]
    # Re-map the shared edge (local 1, local 2) only where quad A uses it:
    # local 1 in face 0, local 2 in faces 0 and 1 (consistently).
    edit = _retex(base, {(0, 1): (0.55, 0.05), (0, 2): (0.55, 0.95), (1, 2): (0.55, 0.95)})
    e = match.diff_shape(s, base, edit)
    assert sorted(i for i, _ in e["uvs"]) == [1, 2]
    by_orig = dict(e["uvs"])
    assert by_orig[1] == pytest.approx((0.55, 0.05))
    assert by_orig[2] == pytest.approx((0.55, 0.95))


def test_uv_conflict_on_a_non_seam_vertex_is_refused(tmp_path):
    s = _seam_shape()
    name = obj_io.object_name(s)
    base = _export_read(tmp_path, [s])[name]
    # local 0 (original 0, non-seam) is shared by faces 0 and 1 (quad A's own
    # diagonal split) -- give it two different new UVs.
    edit = _retex(base, {(0, 0): (0.2, 0.2), (1, 0): (0.3, 0.3)})
    with pytest.raises(ShapeDiffError, match="vertex split"):
        match.diff_shape(s, base, edit)


def test_recorded_uv_edit_round_trips_through_payload_encode(tmp_path):
    from tools.shape_diff import payload
    s = _seam_shape()
    name = obj_io.object_name(s)
    base = _export_read(tmp_path, [s])[name]
    # vertex 0 is shared by faces 0 and 1 (quad A's diagonal) -- change both
    # consistently, else it's the "two different UVs" conflict case.
    edit = _retex(base, {(0, 0): (0.9, 0.9), (1, 0): (0.9, 0.9)})
    e = match.diff_shape(s, base, edit)
    payload.encode([e])  # must not raise


def test_move_without_uv_change_still_accepted(tmp_path):
    s = _shape()
    base = _export_read(tmp_path, [s])["b0011_wall_side_pnls_01"]
    edit = _moved(base, 1, (1.25, 0.0, 0.5))
    e = match.diff_shape(s, base, edit)
    assert [i for i, _ in e["moves"]] == [1, 4]


def test_added_vertex_is_refused_as_iteration_3(tmp_path):
    s = _shape()
    base = _export_read(tmp_path, [s])["b0011_wall_side_pnls_01"]
    edit = _moved(base, 0, base.positions[0])
    edit.positions.append((9.0, 9.0, 9.0))
    with pytest.raises(ShapeDiffError, match="new vertices are iteration 3"):
        match.diff_shape(s, base, edit)


def test_diff_refuses_renamed_or_missing_objects(tmp_path):
    s = _shape()
    objs = _export_read(tmp_path, [s])
    with pytest.raises(ShapeDiffError, match="objects differ"):
        match.diff([s], objs, {"b0011_renamed": objs["b0011_wall_side_pnls_01"]})


def test_diff_refuses_two_objects_mapping_to_the_same_block(tmp_path):
    s = _shape()
    objs = _export_read(tmp_path, [s])
    base_name = "b0011_wall_side_pnls_01"
    dup_name = base_name + ".001"
    both_base = dict(objs)
    both_base[dup_name] = objs[base_name]
    both_edit = dict(both_base)
    with pytest.raises(ShapeDiffError, match="block 11") as exc:
        match.diff([s], both_base, both_edit)
    assert base_name in str(exc.value) and dup_name in str(exc.value)


def test_diff_partial_skips_unsupported_objects_but_keeps_supported(tmp_path):
    move_shape = _shape(block=11, parent="wall side pnls 01")
    face_shape = _shape(block=12, parent="console top")
    shapes = [move_shape, face_shape]
    base = _export_read(tmp_path, shapes)
    move_name = obj_io.object_name(move_shape)
    face_name = obj_io.object_name(face_shape)

    edit = dict(base)
    edit[move_name] = _moved(base[move_name], 1, (1.25, 0.0, 0.5))
    broken = obj_io.ObjMesh()
    broken.positions = list(base[face_name].positions) + [(9.0, 9.0, 9.0)]  # new vertex
    broken.faces = [list(f) for f in base[face_name].faces]
    edit[face_name] = broken

    with pytest.raises(ShapeDiffError, match="iteration 3"):
        match.diff(shapes, base, edit)

    edits, skipped = match.diff(shapes, base, edit, partial=True)
    assert [e["block"] for e in edits] == [11]
    assert len(skipped) == 1
    name, reason = skipped[0]
    assert name == face_name
    assert "new vertices" in reason


def test_diff_partial_still_raises_on_file_level_errors(tmp_path):
    s = _shape()
    objs = _export_read(tmp_path, [s])
    with pytest.raises(ShapeDiffError, match="objects differ"):
        match.diff([s], objs, {"b0011_renamed": objs["b0011_wall_side_pnls_01"]}, partial=True)


from engine import paths

DBRIDGE = "data/Models/Sets/DBridge/Dbridge.NIF"


def test_fix_text_is_opaque_and_well_formed():
    from tools import bridge_shape_diff as cli
    fix = cli.make_fix_dict(DBRIDGE, [GOLDEN_EDIT])
    text = cli.fix_text(fix)
    assert '"generator": "tools/bridge_shape_diff.py"' in text
    assert '"shape_edits": "' + GOLDEN_B64 + '"' in text
    assert "merges" not in text


def test_real_dbridge_export_round_trips_with_no_edits(tmp_path):
    host = pytest.importorskip("_dauntless_host")
    nif = paths.game_root() / DBRIDGE
    if not nif.exists():
        pytest.skip("BC content not configured")
    from tools import bridge_shape_diff as cli
    cli.export(DBRIDGE, tmp_path)
    obj = tmp_path / "Dbridge.obj"
    objs = obj_io.read_objects(obj)
    assert len(objs) == 145
    shapes = host.nif_shapes(str(nif))
    for s in shapes:
        match.identify(s, objs[obj_io.object_name(s)])      # every vertex identified
    fix, edits = cli.build_fix(DBRIDGE, obj, obj)
    assert edits == []


def test_real_dbridge_export_mtl_has_textures_on_disk(tmp_path):
    # F1: every DBridge shape resolves a texture through its ancestor NiNode;
    # the exported .mtl must carry map_Kd lines pointing at real files.
    pytest.importorskip("_dauntless_host")
    nif = paths.game_root() / DBRIDGE
    if not nif.exists():
        pytest.skip("BC content not configured")
    from tools import bridge_shape_diff as cli
    cli.export(DBRIDGE, tmp_path)
    mtl_text = (tmp_path / "Dbridge.mtl").read_text()
    map_kd_lines = [line for line in mtl_text.splitlines() if line.startswith("map_Kd ")]
    assert len(map_kd_lines) >= 1
    for line in map_kd_lines:
        path = Path(line.split(" ", 1)[1])
        assert path.exists(), path


def test_real_dbridge_move_lands_in_local_frame(tmp_path):
    host = pytest.importorskip("_dauntless_host")
    nif = paths.game_root() / DBRIDGE
    if not nif.exists():
        pytest.skip("BC content not configured")
    from tools import bridge_shape_diff as cli
    cli.export(DBRIDGE, tmp_path)
    base = tmp_path / "Dbridge.obj"
    edit = tmp_path / "edit.obj"
    lines = base.read_text().splitlines()
    i = lines.index("o b0468_Material_D_walls_1") + 1
    x, y, z = map(float, lines[i].split()[1:4])
    lines[i] = f"v {x:.6f} {y + 0.5:.6f} {z:.6f}" + "".join(
        " " + c for c in lines[i].split()[4:])
    edit.write_text("\n".join(lines) + "\n")
    _, edits = cli.build_fix(DBRIDGE, base, edit)
    assert [e["block"] for e in edits] == [468]
    s = {d["block"]: d for d in host.nif_shapes(str(nif))}[468]
    for orig, local in edits[0]["moves"]:
        model = frames.apply(s["world"], local)
        assert model[2] == pytest.approx(s["vertices"][orig][2] + 0.5, abs=1e-4)  # OBJ +y is BC +z


from tools.gen_mesh_fixes import fnv1a64_hex


def _patched_cli(monkeypatch, tmp_path):
    """Isolate main()'s --write path from real BC content and real mesh fixes:
    a fake NIF (known bytes -> known fnv1a64_hex target name), a scratch fix
    dir, and build_fix() stubbed to return a fixed single-edit fix."""
    from tools import bridge_shape_diff as cli
    nif_bytes = b"fake nif bytes for main() --write tests"
    nif_file = tmp_path / "fake.nif"
    nif_file.write_bytes(nif_bytes)
    fix_dir = tmp_path / "fixes"
    fix_dir.mkdir()
    monkeypatch.setattr(cli, "_fix_dir", lambda: fix_dir)
    monkeypatch.setattr(cli, "_nif_path", lambda rel: nif_file)
    monkeypatch.setattr(cli, "build_fix", lambda rel, base, edit:
                         (cli.make_fix_dict(rel, [GOLDEN_EDIT]), [GOLDEN_EDIT]))
    target = fix_dir / (fnv1a64_hex(nif_bytes) + ".json")
    return cli, target


def test_main_write_refuses_fix_owned_by_another_generator(monkeypatch, tmp_path):
    cli, target = _patched_cli(monkeypatch, tmp_path)
    target.write_text('{"generator": "tools/gen_mesh_fixes.py"}')
    before = target.read_text()
    rc = cli.main(["diff", "b.obj", "e.obj", "--write"])
    assert rc == 2
    assert target.read_text() == before


def test_main_write_creates_new_fix_when_none_exists(monkeypatch, tmp_path):
    cli, target = _patched_cli(monkeypatch, tmp_path)
    assert not target.exists()
    rc = cli.main(["diff", "b.obj", "e.obj", "--write"])
    assert rc == 0
    assert target.read_text() == cli.fix_text(cli.make_fix_dict(cli.DEFAULT_NIF, [GOLDEN_EDIT]))


def test_main_write_overwrites_fix_owned_by_this_generator(monkeypatch, tmp_path):
    cli, target = _patched_cli(monkeypatch, tmp_path)
    target.write_text('{"generator": "tools/bridge_shape_diff.py"}')
    rc = cli.main(["diff", "b.obj", "e.obj", "--write"])
    assert rc == 0
    assert target.read_text() == cli.fix_text(cli.make_fix_dict(cli.DEFAULT_NIF, [GOLDEN_EDIT]))


def test_main_without_write_flag_writes_nothing(monkeypatch, tmp_path):
    cli, target = _patched_cli(monkeypatch, tmp_path)
    rc = cli.main(["diff", "b.obj", "e.obj"])
    assert rc == 0
    assert not target.exists()


def _patched_cli_partial(monkeypatch, tmp_path, skipped):
    """Like _patched_cli, but build_fix is stubbed for the --partial 3-tuple
    return shape (fix, edits, skipped)."""
    from tools import bridge_shape_diff as cli
    nif_bytes = b"fake nif bytes for main() --partial tests"
    nif_file = tmp_path / "fake.nif"
    nif_file.write_bytes(nif_bytes)
    fix_dir = tmp_path / "fixes"
    fix_dir.mkdir()
    monkeypatch.setattr(cli, "_fix_dir", lambda: fix_dir)
    monkeypatch.setattr(cli, "_nif_path", lambda rel: nif_file)
    monkeypatch.setattr(cli, "build_fix", lambda rel, base, edit, partial=False:
                         (cli.make_fix_dict(rel, [GOLDEN_EDIT]), [GOLDEN_EDIT], skipped))
    target = fix_dir / (fnv1a64_hex(nif_bytes) + ".json")
    return cli, target


def test_main_partial_write_writes_only_supported_edit_and_lists_skipped(monkeypatch, tmp_path, capsys):
    skipped = [("b0099_broken_part", "block 99: faces changed; topology edits are "
                                      "iteration 2 (this iteration is moves and UV edits only)")]
    cli, target = _patched_cli_partial(monkeypatch, tmp_path, skipped)
    rc = cli.main(["diff", "b.obj", "e.obj", "--partial", "--write"])
    out = capsys.readouterr().out
    assert rc == 0
    assert target.read_text() == cli.fix_text(cli.make_fix_dict(cli.DEFAULT_NIF, [GOLDEN_EDIT]))
    assert "skipped (not yet supported):" in out
    assert "b0099_broken_part" in out
    assert "faces changed" in out


def test_main_partial_without_skips_omits_skipped_section(monkeypatch, tmp_path, capsys):
    cli, target = _patched_cli_partial(monkeypatch, tmp_path, [])
    rc = cli.main(["diff", "b.obj", "e.obj", "--partial", "--write"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "skipped" not in out


def test_main_partial_without_write_flag_writes_nothing(monkeypatch, tmp_path):
    skipped = [("b0099_broken_part", "block 99: faces changed")]
    cli, target = _patched_cli_partial(monkeypatch, tmp_path, skipped)
    rc = cli.main(["diff", "b.obj", "e.obj", "--partial"])
    assert rc == 0
    assert not target.exists()


# --- Task 13: triangle add/remove on existing vertices, vertex deletion ---

def _sliver_shape(block=175, parent="console"):
    """A quad (originals 0,1,4,5), a second quad (1,7,8,4) and a lone sliver
    triangle (2,3,6) whose vertices sit in the MIDDLE of the vertex list, so
    deleting them renumbers the survivors. The sliver is stored three times
    in the NIF: twice exactly (tris 2, 5) and once reversed (tri 6) -- the
    duplicate-triangle shape DBridge has 7,628 of. Vertex 9 is a UV-seam copy
    of vertex 2 (same position, different UV) used by no triangle."""
    verts = [(0, 0, 0), (1, 0, 0), (5, 0, 0), (6, 0, 0), (1, 1, 0),
             (0, 1, 0), (5, 1, 0), (2, 0, 0), (2, 1, 0), (5, 0, 0)]
    uvs = [(0.0, 0.0), (0.1, 0.0), (0.5, 0.0), (0.6, 0.0), (0.1, 1.0),
           (0.0, 1.0), (0.5, 1.0), (0.2, 0.0), (0.2, 1.0), (0.9, 0.9)]
    return {
        "block": block, "parent": parent, "hidden": False,
        "vertices": verts, "uvs": uvs,
        "colors": [(1, 1, 1, 1)] * len(verts), "uvs1": [],
        "triangles": [(0, 1, 4), (0, 4, 5), (2, 3, 6), (1, 7, 8),
                      (1, 8, 4), (2, 3, 6), (6, 3, 2)],
        "textures": ["Map 1.tga"],
        "world": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
    }


def _blenderize(mesh):
    """Blender keeps ONE face per vertex set (it also collapses a reversed
    twin); our writer emits every NIF triangle. Keep the first per set."""
    out = obj_io.ObjMesh()
    out.positions = list(mesh.positions)
    seen = set()
    for f in mesh.faces:
        key = frozenset(v for v, _ in f)
        if key not in seen:
            seen.add(key)
            out.faces.append(list(f))
    return out


def _copy(mesh):
    out = obj_io.ObjMesh()
    out.positions = list(mesh.positions)
    out.faces = [list(f) for f in mesh.faces]
    return out


def _face_on(mesh, vertex_set):
    return next(i for i, f in enumerate(mesh.faces)
                if frozenset(v for v, _ in f) == frozenset(vertex_set))


def _blender_delete(mesh, face_index):
    """Delete a face and the vertices it leaves unused; Blender renumbers the
    survivors preserving their relative order."""
    faces = [f for i, f in enumerate(mesh.faces) if i != face_index]
    used = sorted({v for f in faces for v, _ in f})
    new_of = {old: new for new, old in enumerate(used)}
    out = obj_io.ObjMesh()
    out.positions = [mesh.positions[o] for o in used]
    out.faces = [[(new_of[v], uv) for v, uv in f] for f in faces]
    return out


def _sliver_base(tmp_path, s=None):
    s = s or _sliver_shape()
    return s, _blenderize(_export_read(tmp_path, [s])[obj_io.object_name(s)])


def _local(base, pos):
    return next(i for i, p in enumerate(base.positions) if p == pytest.approx(pos))


def test_removing_a_face_removes_every_duplicate_and_reversed_nif_copy(tmp_path):
    s, base = _sliver_base(tmp_path)
    sliver = {_local(base, (5, 0, 0)), _local(base, (6, 0, 0)), _local(base, (5, 1, 0))}
    edit = _copy(base)
    del edit.faces[_face_on(base, sliver)]
    e = match.diff_shape(s, base, edit)
    assert e["remove_triangles"] == [2, 5, 6]
    assert e["add_triangles"] == [] and e["moves"] == [] and e["uvs"] == []


def test_removing_a_face_also_removes_a_reversed_twin_with_different_uvs(tmp_path):
    # Blender collapses a reversed twin onto the same face even when the twin
    # uses a seam copy with different UVs -- deleting the face must not leave
    # the twin rendering.
    s = _sliver_shape()
    s["triangles"] = s["triangles"] + [(9, 6, 3)]          # tri 7: seam copy 9 for 2
    s, base = _sliver_base(tmp_path, s)
    sliver = {_local(base, (5, 0, 0)), _local(base, (6, 0, 0)), _local(base, (5, 1, 0))}
    edit = _copy(base)
    del edit.faces[_face_on(base, sliver)]
    e = match.diff_shape(s, base, edit)
    assert e["remove_triangles"] == [2, 5, 6, 7]


def test_deleting_a_face_and_its_vertices_removes_its_triangles_without_moves(tmp_path):
    s, base = _sliver_base(tmp_path)
    sliver = {_local(base, (5, 0, 0)), _local(base, (6, 0, 0)), _local(base, (5, 1, 0))}
    edit = _blender_delete(base, _face_on(base, sliver))
    assert len(edit.positions) == len(base.positions) - 3
    e = match.diff_shape(s, base, edit)
    assert e["remove_triangles"] == [2, 5, 6]
    assert e["moves"] == [] and e["uvs"] == [] and e["add_triangles"] == []


def test_deletion_where_a_survivor_also_moved_is_refused(tmp_path):
    s, base = _sliver_base(tmp_path)
    sliver = {_local(base, (5, 0, 0)), _local(base, (6, 0, 0)), _local(base, (5, 1, 0))}
    edit = _blender_delete(base, _face_on(base, sliver))
    k = next(i for i, p in enumerate(edit.positions) if p == pytest.approx((2, 1, 0)))
    edit.positions[k] = (2.0, 1.5, 0.0)
    with pytest.raises(ShapeDiffError, match="can't align vertices after deletion"):
        match.diff_shape(s, base, edit)


def _corner(base, pos, uv):
    return (_local(base, pos), uv)


def test_adding_a_face_on_existing_vertices_emits_original_indices_in_edit_winding(tmp_path):
    s, base = _sliver_base(tmp_path)
    edit = _copy(base)
    # (2,0,0)=orig 7, (5,0,0) with orig 2's UV, (2,1,0)=orig 8 -- in this winding
    edit.faces.append([_corner(base, (2, 0, 0), (0.2, 0.0)),
                       _corner(base, (5, 0, 0), (0.5, 0.0)),
                       _corner(base, (2, 1, 0), (0.2, 1.0))])
    e = match.diff_shape(s, base, edit)
    assert e["add_triangles"] == [(7, 2, 8)]
    assert e["remove_triangles"] == [] and e["moves"] == [] and e["uvs"] == []


def test_added_face_corner_uv_picks_the_matching_seam_original(tmp_path):
    s, base = _sliver_base(tmp_path)
    edit = _copy(base)
    edit.faces.append([_corner(base, (2, 1, 0), (0.2, 1.0)),
                       _corner(base, (2, 0, 0), (0.2, 0.0)),
                       _corner(base, (5, 0, 0), (0.9, 0.9))])     # seam copy 9's UV
    e = match.diff_shape(s, base, edit)
    assert e["add_triangles"] == [(8, 7, 9)]


def test_added_face_needing_a_new_uv_is_refused_as_iteration_3(tmp_path):
    s, base = _sliver_base(tmp_path)
    edit = _copy(base)
    edit.faces.append([_corner(base, (2, 0, 0), (0.2, 0.0)),
                       _corner(base, (5, 0, 0), (0.33, 0.33)),     # no original has it
                       _corner(base, (2, 1, 0), (0.2, 1.0))])
    with pytest.raises(ShapeDiffError, match="needs a new vertex/UV.*iteration 3"):
        match.diff_shape(s, base, edit)


def test_added_n_gon_is_refused_triangulate_before_export(tmp_path):
    s, base = _sliver_base(tmp_path)
    edit = _copy(base)
    edit.faces.append([_corner(base, (2, 0, 0), (0.2, 0.0)),
                       _corner(base, (5, 0, 0), (0.5, 0.0)),
                       _corner(base, (5, 1, 0), (0.5, 1.0)),
                       _corner(base, (2, 1, 0), (0.2, 1.0))])
    with pytest.raises(ShapeDiffError, match="triangulate before export"):
        match.diff_shape(s, base, edit)


def test_added_zero_area_triangle_is_refused(tmp_path):
    s, base = _sliver_base(tmp_path)
    edit = _copy(base)
    edit.faces.append([_corner(base, (0, 0, 0), (0.0, 0.0)),        # collinear
                       _corner(base, (1, 0, 0), (0.1, 0.0)),
                       _corner(base, (2, 0, 0), (0.2, 0.0))])
    with pytest.raises(ShapeDiffError, match="zero area"):
        match.diff_shape(s, base, edit)


def test_flipped_winding_on_an_existing_face_is_refused(tmp_path):
    s, base = _sliver_base(tmp_path)
    edit = _copy(base)
    edit.faces[0] = list(reversed(edit.faces[0]))
    with pytest.raises(ShapeDiffError, match="winding"):
        match.diff_shape(s, base, edit)


def test_move_remove_and_add_in_one_object_are_all_recorded(tmp_path):
    from tools.shape_diff import payload
    s, base = _sliver_base(tmp_path)
    sliver = {_local(base, (5, 0, 0)), _local(base, (6, 0, 0)), _local(base, (5, 1, 0))}
    edit = _copy(base)
    del edit.faces[_face_on(base, sliver)]
    edit.positions[_local(base, (0, 0, 0))] = (0.0, -0.25, 0.0)
    edit.faces.append([_corner(base, (2, 0, 0), (0.2, 0.0)),
                       _corner(base, (6, 0, 0), (0.6, 0.0)),
                       _corner(base, (2, 1, 0), (0.2, 1.0))])
    e = match.diff_shape(s, base, edit)
    assert e["moves"] == [(0, pytest.approx((0.0, -0.25, 0.0)))]
    assert e["remove_triangles"] == [2, 5, 6]
    assert e["add_triangles"] == [(7, 3, 8)]
    payload.encode([e])  # must not raise


def test_main_summary_line_counts_triangles(monkeypatch, tmp_path, capsys):
    cli, _ = _patched_cli(monkeypatch, tmp_path)
    assert cli.main(["diff", "b.obj", "e.obj"]) == 0
    out = capsys.readouterr().out
    assert "block 7: 1 vertices moved, 1 UVs changed, 1 triangles removed, 1 added" in out
