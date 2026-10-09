import base64

import pytest

from tools.shape_diff import ShapeDiffError, frames, payload

# BSD2 (spec §6.1) as the encoder writes it: positions by reference (kind 1)
# and by reference + delta (kind 2) -- never literal --, literal and
# reference UVs, added vertices of both position kinds with attr_src, a
# removed and an added triangle. Hand-assembled with struct, NOT produced by
# the encoder; pinned byte-identical in native/tests/assets/cpu/
# mesh_fix_parse_test.cc (kGoldenBsd2B64).
GOLDEN_B64 = (
    "QlNEMgEABwAAAAQAAgACAAIAAgABAAEAAQABCQAAAAMAAgACBwAAAAIAAAAAPwAAgL4AAIA/AAAAAACA"
    "PgAAQD8DAAEHAAAAAQACBwAAAAAAAAAAPgAAAAAAAABAAAAAAD4AAAA/AgABCQAAAAAAAQkAAAAAAAMAAQAAAAQABQA="
)

GOLDEN_EDIT = {
    "block": 7, "orig_vertex_count": 4, "orig_triangle_count": 2,
    "moves": [(1, payload.Ref(9, 3)), (2, payload.Ref(7, 2, (0.5, -0.25, 1.0)))],
    "uvs": [(0, (0.25, 0.75)), (3, payload.Ref(7, 1))],
    "add_vertices": [{"pos": payload.Ref(7, 0, (0.125, 0.0, 2.0)), "uv0": (0.125, 0.5),
                      "attr_src": 2},
                     {"pos": payload.Ref(9, 0), "uv0": payload.Ref(9, 0), "attr_src": 3}],
    "remove_triangles": [1],
    "add_triangles": [(0, 4, 5)],
}


def test_payload_matches_cpp_golden():
    assert payload.encode_b64([GOLDEN_EDIT]) == GOLDEN_B64
    assert len(base64.b64decode(GOLDEN_B64)) == 128


def test_payload_missing_lists_are_empty():
    raw = payload.encode([{"block": 1, "orig_vertex_count": 3, "orig_triangle_count": 1}])
    assert raw == b"BSD2" + bytes([1, 0, 1, 0, 0, 0, 3, 0, 1, 0]) + bytes(10)


def test_payload_refuses_index_overflow():
    with pytest.raises(ShapeDiffError):
        payload.encode([{"block": 1, "orig_vertex_count": 70000, "orig_triangle_count": 1}])


def test_payload_refuses_reference_vertex_overflow():
    e = {"block": 1, "orig_vertex_count": 3, "orig_triangle_count": 1,
         "moves": [(0, payload.Ref(2, 70000))]}
    with pytest.raises(ShapeDiffError, match="16 bits"):
        payload.encode([e])


def test_payload_refuses_an_added_vertex_without_attr_src():
    # BSD1's literal uv1/colour fields were BC data (spec §6.2): never written.
    e = {"block": 1, "orig_vertex_count": 3, "orig_triangle_count": 1,
         "add_vertices": [{"pos": (0, 0, 0), "uv0": (0, 0),
                           "uv1": (0, 0), "color": (1, 1, 1, 1)}]}
    with pytest.raises(ShapeDiffError, match="attr_src"):
        payload.encode([e])


def test_payload_never_writes_a_literal_position():
    # spec §6.2: every position is relative to an original (kind 1 or 2).
    e = {"block": 1, "orig_vertex_count": 3, "orig_triangle_count": 1,
         "moves": [(0, (1.0, 2.0, 3.0))]}
    with pytest.raises(ShapeDiffError, match="literal position"):
        payload.encode([e])


def test_payload_refuses_a_non_finite_delta():
    e = {"block": 1, "orig_vertex_count": 3, "orig_triangle_count": 1,
         "moves": [(0, payload.Ref(1, 0, (float("nan"), 0.0, 0.0)))]}
    with pytest.raises(ShapeDiffError, match="finite"):
        payload.encode([e])


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
    (tmp_path / "b.mtl").write_text("newmtl m\n")
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


def _resolve(shape, p):
    """A same-shape position record as the loader resolves it: the
    referenced original's shape-local position plus the delta."""
    assert isinstance(p, payload.Ref) and p.block == shape["block"], p
    o = frames.apply(frames.affine_inverse(shape["world"]), shape["vertices"][p.vertex])
    return tuple(a + b for a, b in zip(o, p.delta or (0.0, 0.0, 0.0)))


def _moves(shape, e):
    return [(i, _resolve(shape, p)) for i, p in e["moves"]]


def _added_pos(shape, e):
    return [_resolve(shape, v["pos"]) for v in e["add_vertices"]]


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
    assert _moves(s, e)[0][1] == pytest.approx((1.25, 0.0, 0.5))
    assert not e.get("add_vertices") and not e.get("add_triangles")


def test_move_is_stored_in_shape_local_frame(tmp_path):
    s = _shape(offset=(100.0, 50.0, 10.0))
    base = _export_read(tmp_path, [s])["b0011_wall_side_pnls_01"]
    edit = _moved(base, 2, (101.0, 51.0, 10.75))        # model space
    e = match.diff_shape(s, base, edit)
    assert _moves(s, e) == [(2, pytest.approx((1.0, 1.0, 0.75)))]


def test_move_and_uv_edit_together_are_both_recorded(tmp_path):
    s = _shape()
    base = _export_read(tmp_path, [s])["b0011_wall_side_pnls_01"]
    edit = _moved(base, 1, (1.25, 0.0, 0.5))           # move the seam vertex
    # vertex 1's only corner is face 0 (vertex 4's degenerate triangle was
    # dropped by the weld) -- touch its UV there too.
    edit = _retex(edit, {(0, 1): (0.6, 0.0)})
    e = match.diff_shape(s, base, edit)
    assert [i for i, _ in e["moves"]] == [1, 4]
    assert _moves(s, e)[0][1] == pytest.approx((1.25, 0.0, 0.5))
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


def test_a_loose_new_vertex_on_no_face_records_nothing(tmp_path):
    s = _shape()
    base = _export_read(tmp_path, [s])["b0011_wall_side_pnls_01"]
    edit = _moved(base, 0, base.positions[0])
    edit.positions.append((9.0, 9.0, 9.0))
    assert match.diff_shape(s, base, edit) is None


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
    broken = _copy(base[face_name])
    broken.faces[0] = list(reversed(broken.faces[0]))        # flipped: unsupported
    edit[face_name] = broken

    with pytest.raises(ShapeDiffError, match="winding"):
        match.diff(shapes, base, edit)

    edits, skipped = match.diff(shapes, base, edit, partial=True)
    assert [e["block"] for e in edits] == [11]
    assert len(skipped) == 1
    name, reason = skipped[0]
    assert name == face_name
    assert "winding" in reason


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
    for orig, local in _moves(s, edits[0]):
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


def test_deletion_where_a_survivor_also_moved_is_aligned_by_connectivity(tmp_path):
    s, base = _sliver_base(tmp_path)
    sliver = {_local(base, (5, 0, 0)), _local(base, (6, 0, 0)), _local(base, (5, 1, 0))}
    edit = _blender_delete(base, _face_on(base, sliver))
    k = next(i for i, p in enumerate(edit.positions) if p == pytest.approx((2, 1, 0)))
    edit.positions[k] = (2.0, 1.5, 0.0)
    e = match.diff_shape(s, base, edit)
    assert e["remove_triangles"] == [2, 5, 6]
    assert _moves(s, e) == [(8, pytest.approx((2.0, 1.5, 0.0)))]
    assert e["add_triangles"] == [] and e["uvs"] == []


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


def test_added_face_corner_with_a_new_uv_splits_the_vertex_by_reference(tmp_path):
    s, base = _sliver_base(tmp_path)
    edit = _copy(base)
    edit.faces.append([_corner(base, (2, 0, 0), (0.2, 0.0)),
                       _corner(base, (5, 0, 0), (0.33, 0.33)),     # no original has it
                       _corner(base, (2, 1, 0), (0.2, 1.0))])
    e = match.diff_shape(s, base, edit)
    # originals 2 and 9 sit at (5,0,0): position by reference to the lowest,
    # colour/UV1 from the nearest (a tie at distance 0 -> lowest index)
    assert e["add_vertices"] == [{"pos": Ref(175, 2), "uv0": pytest.approx((0.33, 0.33)),
                                  "attr_src": 2}]
    assert e["add_triangles"] == [(7, 10, 8)]


def test_added_quad_is_ear_clipped_into_two_triangles_keeping_its_winding(tmp_path):
    s, base = _sliver_base(tmp_path)
    edit = _copy(base)
    edit.faces.append([_corner(base, (2, 0, 0), (0.2, 0.0)),        # 7
                       _corner(base, (5, 0, 0), (0.5, 0.0)),        # 2
                       _corner(base, (5, 1, 0), (0.5, 1.0)),        # 6
                       _corner(base, (2, 1, 0), (0.2, 1.0))])       # 8
    e = match.diff_shape(s, base, edit)
    assert e["add_triangles"] == [(8, 7, 2), (2, 6, 8)]
    pts = s["vertices"]
    for a, b, c in e["add_triangles"]:          # counter-clockwise seen from +z, like the quad
        (x0, y0, _), (x1, y1, _), (x2, y2, _) = pts[a], pts[b], pts[c]
        assert (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0) > 0


def test_added_self_intersecting_n_gon_is_refused(tmp_path):
    s, base = _sliver_base(tmp_path)
    edit = _copy(base)
    edit.faces.append([_corner(base, (2, 0, 0), (0.2, 0.0)),        # a bow-tie
                       _corner(base, (5, 1, 0), (0.5, 1.0)),
                       _corner(base, (5, 0, 0), (0.5, 0.0)),
                       _corner(base, (2, 1, 0), (0.2, 1.0))])
    with pytest.raises(ShapeDiffError, match="can't be triangulated"):
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
    assert _moves(s, e) == [(0, pytest.approx((0.0, -0.25, 0.0)))]
    assert e["remove_triangles"] == [2, 5, 6]
    assert e["add_triangles"] == [(7, 3, 8)]
    payload.encode([e])  # must not raise


def test_main_summary_line_counts_triangles(monkeypatch, tmp_path, capsys):
    cli, _ = _patched_cli(monkeypatch, tmp_path)
    assert cli.main(["diff", "b.obj", "e.obj"]) == 0
    out = capsys.readouterr().out
    assert ("block 7: 2 vertices moved (1 by reference), 2 UVs changed, "
            "1 triangles removed, 1 added, 2 vertices added (1 by reference)") in out


def _retex_vertex(mesh, v, uv):
    out = _copy(mesh)
    out.faces = [[(w, uv if w == v else wuv) for w, wuv in f] for f in out.faces]
    return out


def test_added_face_corner_resolves_against_this_diffs_uv_edits(tmp_path):
    s, base = _sliver_base(tmp_path)
    edit = _retex_vertex(base, _local(base, (2, 0, 0)), (0.3, 0.3))   # original 7 re-mapped
    edit.faces.append([_corner(base, (2, 0, 0), (0.3, 0.3)),            # the NEW uv
                       _corner(base, (5, 0, 0), (0.5, 0.0)),
                       _corner(base, (2, 1, 0), (0.2, 1.0))])
    e = match.diff_shape(s, base, edit)
    assert e["uvs"] == [(7, pytest.approx((0.3, 0.3)))]
    assert e["add_triangles"] == [(7, 2, 8)]


def test_added_face_corner_with_the_pre_edit_uv_of_a_remapped_original_splits_it(tmp_path):
    # Original 7 now renders the NEW uv (0.3,0.3); the added face shows its
    # OLD one, so that corner becomes a split vertex -- both by reference.
    s, base = _sliver_base(tmp_path)
    edit = _retex_vertex(base, _local(base, (2, 0, 0)), (0.3, 0.3))
    edit.faces.append([_corner(base, (2, 0, 0), (0.2, 0.0)),            # the OLD uv
                       _corner(base, (5, 0, 0), (0.5, 0.0)),
                       _corner(base, (2, 1, 0), (0.2, 1.0))])
    e = match.diff_shape(s, base, edit)
    assert e["uvs"] == [(7, pytest.approx((0.3, 0.3)))]
    assert e["add_vertices"] == [{"pos": Ref(175, 7), "uv0": Ref(175, 7), "attr_src": 7}]
    assert e["add_triangles"] == [(10, 2, 8)]


def _straddle_shape():
    """Originals 2 and 3 are 6e-5 apart (inside POS_TOL) but straddle a
    1/1024 weld boundary, so they export as two OBJ vertices whose identify
    groups overlap."""
    y0 = 1.5 / 1024
    return {"block": 175, "parent": "console", "hidden": False,
            "vertices": [(0, 0, 0), (1, 0, 0), (0.5, y0 - 3e-5, 1.0), (0.5, y0 + 3e-5, 1.0)],
            "uvs": [(0, 0), (1, 0), (0.5, 1), (0.6, 1)], "colors": [(1, 1, 1, 1)] * 4,
            "uvs1": [], "triangles": [(0, 1, 2), (0, 1, 3)], "textures": ["Map 1.tga"],
            "world": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]}


def test_topology_edit_on_overlapping_identity_groups_is_refused(tmp_path):
    s, base = _sliver_base(tmp_path, _straddle_shape())
    assert len(base.positions) == 4
    edit = _copy(base)
    del edit.faces[0]
    with pytest.raises(ShapeDiffError, match="within POS_TOL"):
        match.diff_shape(s, base, edit)


def test_overlapping_identity_groups_do_not_block_an_untouched_object(tmp_path):
    s, base = _sliver_base(tmp_path, _straddle_shape())
    assert match.diff_shape(s, base, _copy(base)) is None


# --- Task 14: per-shape albedo texture op ---

def test_read_mtl_maps_material_to_map_kd_basename(tmp_path):
    p = tmp_path / "m.mtl"
    p.write_text(
        "# Blender MTL\nnewmtl Map_1.tga\nKd 1 1 1\nmap_Kd /stock/High/Map 1.tga\n\n"
        "newmtl Map_1.tga.001\nmap_Kd -bm 1.0 C:\\overlay\\High\\g_imp_connops.tga\n"
        "newmtl plain\nKd 0.5 0.5 0.5\n")
    assert obj_io.read_mtl(p) == {"Map_1.tga": "Map 1.tga",
                                  "Map_1.tga.001": "g_imp_connops.tga",
                                  "plain": None}


def test_read_objects_records_each_faces_albedo_from_the_mtllib(tmp_path):
    (tmp_path / "e.mtl").write_text(
        "newmtl a\nmap_Kd /x/Map 1.tga\nnewmtl b\nmap_Kd /y/new.tga\nnewmtl c\n")
    p = tmp_path / "e.obj"
    p.write_text("mtllib e.mtl\no b0003_x\nv 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\n"
                 "f 1 2 3\nusemtl a\nf 1 3 4\nusemtl b\nf 1 2 4\nusemtl c\nf 2 3 4\n")
    m = obj_io.read_objects(p)["b0003_x"]
    assert m.face_albedos == [None, "Map 1.tga", "new.tga", None]


def test_read_objects_refuses_a_named_mtllib_that_is_missing(tmp_path):
    p = tmp_path / "e.obj"
    p.write_text("mtllib missing.mtl\no b0003_x\nv 0 0 0\nv 1 0 0\nv 1 1 0\n"
                 "usemtl a\nf 1 2 3\n")
    with pytest.raises(ShapeDiffError, match="missing.mtl"):
        obj_io.read_objects(p)


def test_read_objects_without_an_mtllib_line_has_no_albedos(tmp_path):
    p = tmp_path / "e.obj"
    p.write_text("o b0003_x\nv 0 0 0\nv 1 0 0\nv 1 1 0\nusemtl a\nf 1 2 3\n")
    assert obj_io.read_objects(p)["b0003_x"].face_albedos == [None]


def _write_pair_then_drop(tmp_path, which):
    s = _shape()
    base, edit = _tex_pair(tmp_path, [s], "newmtl m\nmap_Kd /b/new.tga\n")
    (tmp_path / f"{which}.mtl").unlink()
    return tmp_path / "base.obj", tmp_path / "edit.obj"


@pytest.mark.parametrize("which", ["base", "edit"])
@pytest.mark.parametrize("partial", [False, True])
def test_build_fix_aborts_when_either_mtl_is_missing(tmp_path, which, partial):
    from tools import bridge_shape_diff as cli
    base_obj, edit_obj = _write_pair_then_drop(tmp_path, which)
    with pytest.raises(ShapeDiffError, match=f"{which}.mtl"):
        cli.build_fix(DBRIDGE, base_obj, edit_obj, partial=partial)


def _tex_dirs(tmp_path, overlay_files=(), stock_files=()):
    overlay, stock = tmp_path / "overlay" / "High", tmp_path / "stock" / "High"
    for d, names in ((overlay, overlay_files), (stock, stock_files)):
        d.mkdir(parents=True, exist_ok=True)
        for n in names:
            (d / n).write_bytes(b"tga")
    return [overlay, stock]


def _tex_pair(tmp_path, shapes, edit_mtl_text, edit_obj_text=None):
    """base.obj/base.mtl as the exporter writes them (map_Kd -> stock file),
    and an edit.obj (same geometry unless given) whose mtllib is edit.mtl and
    whose exported material is renamed to edit.mtl's FIRST material, the way
    Blender re-exports a material it renamed ('.001')."""
    base_obj, base_mtl = tmp_path / "base.obj", tmp_path / "base.mtl"
    obj_io.write_obj(shapes, base_obj, base_mtl, lambda n: Path("/stock/High") / n)
    text = edit_obj_text if edit_obj_text is not None else base_obj.read_text()
    first = edit_mtl_text.split("newmtl ", 1)[1].splitlines()[0]
    text = text.replace("usemtl Map_1.tga\n", f"usemtl {first}\n")
    edit_obj = tmp_path / "edit.obj"
    edit_obj.write_text(text.replace("mtllib base.mtl", "mtllib edit.mtl"))
    (tmp_path / "edit.mtl").write_text(edit_mtl_text)
    return obj_io.read_objects(base_obj), obj_io.read_objects(edit_obj)


def test_retextured_object_records_a_texture_op(tmp_path):
    s = _shape()
    base, edit = _tex_pair(tmp_path, [s],
                           "newmtl Map_1.tga.001\nmap_Kd /blender/new panel.tga\n")
    dirs = _tex_dirs(tmp_path, overlay_files=["new panel.tga"])
    edits = match.diff([s], base, edit, texture_dirs=dirs)
    assert edits == [{"block": 11, "orig_vertex_count": 5, "orig_triangle_count": 3,
                      "moves": [], "uvs": [], "remove_triangles": [],
                      "add_triangles": [], "albedo": "new panel.tga"}]


def test_same_texture_under_a_renamed_material_is_no_op(tmp_path):
    s = _shape()
    base, edit = _tex_pair(tmp_path, [s],
                           "newmtl Map_1.tga.001\nmap_Kd D:\\other\\tree\\Map 1.tga\n")
    assert match.diff([s], base, edit, texture_dirs=_tex_dirs(tmp_path)) == []


def test_object_without_map_kd_records_no_texture_op(tmp_path):
    s = _shape()
    base, edit = _tex_pair(tmp_path, [s], "newmtl Map_1.tga\nKd 1 1 1\n")
    assert match.diff([s], base, edit, texture_dirs=_tex_dirs(tmp_path)) == []


def test_two_albedos_on_one_object_is_refused(tmp_path):
    s = _seam_shape()
    base_obj = tmp_path / "base.obj"
    obj_io.write_obj([s], base_obj, tmp_path / "base.mtl", lambda n: Path("/s") / n)
    lines = base_obj.read_text().splitlines()
    f_at = [i for i, line in enumerate(lines) if line.startswith("f ")]
    lines.insert(f_at[2], "usemtl second")      # quad B's faces take another texture
    mtl = "newmtl Map_1.tga\nmap_Kd /s/a.tga\nnewmtl second\nmap_Kd /s/b.tga\n"
    base, edit = _tex_pair(tmp_path, [s], mtl, "\n".join(lines) + "\n")
    dirs = _tex_dirs(tmp_path, overlay_files=["a.tga", "b.tga"])
    with pytest.raises(ShapeDiffError, match="one texture per object"):
        match.diff([s], base, edit, texture_dirs=dirs)


def test_missing_texture_file_is_refused_naming_file_and_dirs(tmp_path):
    s = _shape()
    base, edit = _tex_pair(tmp_path, [s], "newmtl m\nmap_Kd /blender/gone.tga\n")
    dirs = _tex_dirs(tmp_path)
    with pytest.raises(ShapeDiffError, match="gone.tga") as exc:
        match.diff([s], base, edit, texture_dirs=dirs)
    assert str(dirs[0]) in str(exc.value) and str(dirs[1]) in str(exc.value)


def test_texture_found_in_the_stock_dir_case_insensitively(tmp_path):
    s = _shape()
    base, edit = _tex_pair(tmp_path, [s], "newmtl m\nmap_Kd /blender/MAP 7.TGA\n")
    dirs = _tex_dirs(tmp_path, stock_files=["Map 7.tga"])
    [e] = match.diff([s], base, edit, texture_dirs=dirs)
    assert e["albedo"] == "MAP 7.TGA"


def test_non_tga_texture_is_refused(tmp_path):
    s = _shape()
    base, edit = _tex_pair(tmp_path, [s], "newmtl m\nmap_Kd /blender/new.png\n")
    dirs = _tex_dirs(tmp_path, overlay_files=["new.png"])
    with pytest.raises(ShapeDiffError, match=r"\.tga"):
        match.diff([s], base, edit, texture_dirs=dirs)


def test_texture_op_coexists_with_a_move_on_the_same_object(tmp_path):
    s = _shape()
    base_obj = tmp_path / "base.obj"
    obj_io.write_obj([s], base_obj, tmp_path / "base.mtl", lambda n: Path("/s") / n)
    lines = base_obj.read_text().splitlines()
    i = next(k for k, line in enumerate(lines) if line.startswith("v "))
    lines[i] = "v 0.000000 0.500000 0.000000 1.000000 1.000000 1.000000"
    base, edit = _tex_pair(tmp_path, [s], "newmtl m\nmap_Kd /b/new.tga\n",
                           "\n".join(lines) + "\n")
    [e] = match.diff([s], base, edit,
                     texture_dirs=_tex_dirs(tmp_path, overlay_files=["new.tga"]))
    assert e["albedo"] == "new.tga" and [i for i, _ in e["moves"]] == [0]


def test_partial_skips_an_object_with_a_refused_texture_entirely(tmp_path):
    a, b = _shape(block=11), _shape(block=12, parent="console top", offset=(5, 0, 0))
    base_obj = tmp_path / "base.obj"
    obj_io.write_obj([a, b], base_obj, tmp_path / "base.mtl", lambda n: Path("/s") / n)
    lines = base_obj.read_text().splitlines()
    o12 = lines.index("o b0012_console_top")
    i = next(k for k in range(o12, len(lines)) if lines[k].startswith("v "))
    lines[i] = "v 5.000000 0.500000 0.000000 1.000000 1.000000 1.000000"   # a move...
    u = next(k for k in range(o12, len(lines)) if lines[k].startswith("usemtl"))
    lines[u] = "usemtl gone"                                               # ...plus a bad texture
    mtl = "newmtl Map_1.tga\nmap_Kd /s/Map 1.tga\nnewmtl gone\nmap_Kd /b/gone.tga\n"
    base, edit = _tex_pair(tmp_path, [a, b], mtl, "\n".join(lines) + "\n")
    edits, skipped = match.diff([a, b], base, edit, partial=True,
                                texture_dirs=_tex_dirs(tmp_path))
    assert edits == []
    assert [n for n, _ in skipped] == ["b0012_console_top"]


def test_make_fix_dict_emits_sorted_textures_only_when_present():
    from tools import bridge_shape_diff as cli
    tex_only = [{"block": 59, "orig_vertex_count": 4, "orig_triangle_count": 2,
                 "albedo": "g.tga"},
                {"block": 29, "orig_vertex_count": 4, "orig_triangle_count": 2,
                 "moves": [], "albedo": "g.tga"}]
    fix = cli.make_fix_dict(DBRIDGE, tex_only)
    assert fix["textures"] == [{"block": 29, "albedo": "g.tga"},
                               {"block": 59, "albedo": "g.tga"}]
    assert "shape_edits" not in fix
    both = cli.make_fix_dict(DBRIDGE, [dict(GOLDEN_EDIT, albedo="g.tga")])
    assert both["shape_edits"] == GOLDEN_B64      # the albedo key never reaches the payload
    assert both["textures"] == [{"block": 7, "albedo": "g.tga"}]
    assert "textures" not in cli.make_fix_dict(DBRIDGE, [GOLDEN_EDIT])


def test_texture_dirs_are_overlay_then_stock_beside_the_nif(monkeypatch, tmp_path):
    from engine import mods
    from tools import bridge_shape_diff as cli
    monkeypatch.setattr(paths, "project_asset_root", lambda: tmp_path / "assets")
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "install")
    assert cli._texture_dirs(DBRIDGE) == [
        mods.replacements_root() / "data/Models/Sets/DBridge/High",
        tmp_path / "install" / "data/Models/Sets/DBridge/High"]


def test_main_summary_names_the_texture_and_lists_texture_only_blocks(
        monkeypatch, tmp_path, capsys):
    cli, _ = _patched_cli(monkeypatch, tmp_path)
    tex_only = {"block": 59, "orig_vertex_count": 4, "orig_triangle_count": 2,
                "moves": [], "uvs": [], "remove_triangles": [], "add_triangles": [],
                "albedo": "g_imp_connops.tga"}
    edits = [dict(GOLDEN_EDIT, albedo="g_imp_connops.tga"), tex_only]
    monkeypatch.setattr(cli, "build_fix", lambda rel, base, edit:
                        (cli.make_fix_dict(rel, edits), edits))
    assert cli.main(["diff", "b.obj", "e.obj"]) == 0
    out = capsys.readouterr().out
    assert ("block 7: 2 vertices moved (1 by reference), 2 UVs changed, "
            "1 triangles removed, 1 added, 2 vertices added (1 by reference), "
            "texture -> g_imp_connops.tga") in out
    assert "block 59: texture -> g_imp_connops.tga" in out


def test_real_dbridge_texture_op_resolves_against_the_stock_dir(tmp_path):
    pytest.importorskip("_dauntless_host")
    nif = paths.game_root() / DBRIDGE
    if not nif.exists():
        pytest.skip("BC content not configured")
    from tools import bridge_shape_diff as cli
    cli.export(DBRIDGE, tmp_path)
    base = tmp_path / "Dbridge.obj"
    lines = base.read_text().splitlines()
    o = lines.index(next(line for line in lines if line.startswith("o b0029")))
    u = next(k for k in range(o, len(lines)) if lines[k].startswith("usemtl"))
    lines[u] = "usemtl swapped"
    edit = tmp_path / "edit.obj"
    edit.write_text("\n".join(lines).replace("mtllib Dbridge.mtl", "mtllib edit.mtl") + "\n")
    (tmp_path / "edit.mtl").write_text(
        (tmp_path / "Dbridge.mtl").read_text() + "newmtl swapped\nmap_Kd /elsewhere/Map 7.tga\n")
    fix, edits = cli.build_fix(DBRIDGE, base, edit)
    assert fix["textures"] == [{"block": 29, "albedo": "Map 7.tga"}]
    assert "shape_edits" not in fix


@pytest.mark.parametrize("name", ["panel_glow.tga", "panel_GLOW.TGA", "panel_specular.tga",
                                  "panel_spec.tga", "panel_normal.tga", "panel_norm.tga"])
def test_reserved_suffix_albedo_is_refused(tmp_path, name):
    s = _shape()
    base, edit = _tex_pair(tmp_path, [s], f"newmtl m\nmap_Kd /b/{name}\n")
    dirs = _tex_dirs(tmp_path, overlay_files=[name])
    with pytest.raises(ShapeDiffError, match="plain diffuse") as exc:
        match.diff([s], base, edit, texture_dirs=dirs)
    assert name in str(exc.value)


def test_base_object_spanning_two_albedos_is_refused(tmp_path):
    s = _seam_shape()
    base_obj = tmp_path / "base.obj"
    obj_io.write_obj([s], base_obj, tmp_path / "base.mtl", lambda n: Path("/s") / n)
    lines = base_obj.read_text().splitlines()
    f_at = [i for i, line in enumerate(lines) if line.startswith("f ")]
    lines.insert(f_at[2], "usemtl second")
    base_obj.write_text("\n".join(lines) + "\n")
    (tmp_path / "base.mtl").write_text(
        "newmtl Map_1.tga\nmap_Kd /s/a.tga\nnewmtl second\nmap_Kd /s/b.tga\n")
    edit_obj = tmp_path / "edit.obj"
    edit_obj.write_text(base_obj.read_text().replace("mtllib base.mtl", "mtllib edit.mtl")
                        .replace("usemtl second\n", "usemtl Map_1.tga\n"))
    (tmp_path / "edit.mtl").write_text("newmtl Map_1.tga\nmap_Kd /s/a.tga\n")
    base, edit = obj_io.read_objects(base_obj), obj_io.read_objects(edit_obj)
    with pytest.raises(ShapeDiffError, match="base"):
        match.diff([s], base, edit, texture_dirs=_tex_dirs(tmp_path, overlay_files=["a.tga"]))


# --- Task 15: references (spec §6.2) ---

Ref = payload.Ref


def _two_shapes(tmp_path):
    """A = _shape() at block 11 (identity frame); B = _shape() at block 12,
    offset (3, 0, 0) -- so B's vertex k sits at A's vertex k + (3, 0, 0)."""
    a = _shape(block=11, parent="wall side pnls 01")
    b = _shape(block=12, parent="console top", offset=(3.0, 0.0, 0.0))
    objs = _export_read(tmp_path, [a, b])
    return a, b, objs


def test_move_snapped_onto_another_shapes_vertex_is_a_position_reference(tmp_path):
    a, b, objs = _two_shapes(tmp_path)
    base = objs[obj_io.object_name(a)]
    k = _local(base, (0, 1, 0))                          # original 3
    edit = _moved(base, k, (3.0, 1.0, 0.0))              # onto B's original 3
    [e] = match.diff([a, b], objs, dict(objs, **{obj_io.object_name(a): edit}))
    assert e["block"] == 11
    assert e["moves"] == [(3, Ref(12, 3))]


def test_snapped_move_prefers_the_target_shape_then_lowest_block_and_index(tmp_path):
    a = _shape(block=11)
    b = _shape(block=12, parent="console top", offset=(1.0, 0.0, 0.0))
    c = _shape(block=13, parent="console side", offset=(1.0, 0.0, 0.0))
    objs = _export_read(tmp_path, [a, b, c])
    base = objs[obj_io.object_name(a)]
    # (2, 0, 0) is B's and C's original 1 AND 4 (seam twins): lowest block, lowest index
    edit = _moved(base, _local(base, (0, 0, 0)), (2.0, 0.0, 0.0))
    [e] = match.diff([a, b, c], objs, dict(objs, **{obj_io.object_name(a): edit}))
    assert e["moves"] == [(0, Ref(12, 1))]
    # (1, 0, 0) is A's own 1/4 AND B/C's 0: the target shape wins
    edit = _moved(base, _local(base, (0, 1, 0)), (1.0, 0.0, 0.0))
    [e] = match.diff([a, b, c], objs, dict(objs, **{obj_io.object_name(a): edit}))
    assert e["moves"] == [(3, Ref(11, 1))]


def test_move_to_a_fresh_position_stays_literal(tmp_path):
    a, b, objs = _two_shapes(tmp_path)
    base = objs[obj_io.object_name(a)]
    edit = _moved(base, _local(base, (0, 1, 0)), (0.5, 1.5, 0.25))
    [e] = match.diff([a, b], objs, dict(objs, **{obj_io.object_name(a): edit}))
    assert _moves(a, e) == [(3, pytest.approx((0.5, 1.5, 0.25)))]


def test_uv_equal_to_the_position_references_uv_is_a_uv_reference(tmp_path):
    a, b, objs = _two_shapes(tmp_path)
    b["uvs"] = [(0.7, 0.7), (0.8, 0.1), (0.9, 0.9), (0.6, 0.4), (0.3, 0.3)]
    objs = _export_read(tmp_path, [a, b])
    base = objs[obj_io.object_name(a)]
    k = _local(base, (0, 1, 0))                          # original 3, UV (0, 1)
    edit = _moved(base, k, (3.0, 1.0, 0.0))              # onto B's 3...
    edit = _retex(edit, {(1, k): (0.6, 0.4)})            # ...taking B's 3's UV
    [e] = match.diff([a, b], objs, dict(objs, **{obj_io.object_name(a): edit}))
    assert e["moves"] == [(3, Ref(12, 3))]
    assert e["uvs"] == [(3, Ref(12, 3))]


def test_uv_equal_to_a_seam_copy_at_that_position_references_the_copy(tmp_path):
    s = _seam_shape()
    base = _export_read(tmp_path, [s])[obj_io.object_name(s)]
    k = _local(base, (1, 0, 0))     # quad A's original 1 (UV 0.5,0) + quad B's 4 (UV 0,0)
    # quad A's corner at k takes quad B's seam UV (0, 0); original 0 has it
    # too, elsewhere -- the copy AT THIS POSITION wins.
    edit = _retex(base, {(0, k): (0.0, 0.0)})
    e = match.diff_shape(s, base, edit)
    assert e["uvs"] == [(1, Ref(11, 4))]


def test_uv_equal_to_some_target_original_elsewhere_is_still_a_reference(tmp_path):
    s = _seam_shape()
    base = _export_read(tmp_path, [s])[obj_io.object_name(s)]
    k = _local(base, (0, 1, 0))                          # original 3, UV (0, 1)
    edit = _retex(base, {(1, k): (1.0, 1.0)})            # original 6's UV (quad B)
    e = match.diff_shape(s, base, edit)
    assert e["uvs"] == [(3, Ref(11, 6))]


def test_authored_uv_stays_literal(tmp_path):
    s = _seam_shape()
    base = _export_read(tmp_path, [s])[obj_io.object_name(s)]
    k = _local(base, (0, 1, 0))
    edit = _retex(base, {(1, k): (0.123, 0.456)})
    e = match.diff_shape(s, base, edit)
    assert e["uvs"] == [(3, pytest.approx((0.123, 0.456)))]


# --- Task 15: correspondence (spec §5.2) ---

def _with(positions, faces):
    out = obj_io.ObjMesh()
    out.positions = list(positions)
    out.faces = [list(f) for f in faces]
    return out


def test_correspondence_is_identity_for_equal_counts_and_unmoved_vertices(tmp_path):
    s, base = _sliver_base(tmp_path)
    assert match.correspond(175, base, _copy(base)) == list(range(len(base.positions)))


def test_correspondence_survives_deletion_a_moved_survivor_and_appended_vertices(tmp_path):
    # Equal vertex counts (3 deleted, 3 added) -- the old by-index rule would
    # have read every survivor after the deletion as moved.
    s, base = _sliver_base(tmp_path)
    sliver = {_local(base, (5, 0, 0)), _local(base, (6, 0, 0)), _local(base, (5, 1, 0))}
    edit = _blender_delete(base, _face_on(base, sliver))
    l7 = _local(edit, (2, 0, 0))
    l8 = _local(edit, (2, 1, 0))
    edit.positions[l8] = (2.0, 1.5, 0.0)                        # moved survivor
    n = len(edit.positions)
    edit.positions += [(3.0, 0.0, 0.0), (3.0, 1.0, 0.0), (4.0, 0.5, 0.0)]
    edit.faces += [[(l7, (0, 0)), (n, (0, 0)), (n + 1, (0, 0))],
                   [(l7, (0, 0)), (n + 1, (0, 0)), (l8, (0, 0))],
                   [(n, (0, 0)), (n + 2, (0, 0)), (n + 1, (0, 0))]]
    assert len(edit.positions) == len(base.positions)
    survivors = [_local(base, p) for p in [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
                                           (2, 0, 0), (2, 1, 0)]]
    assert match.correspond(175, base, edit) == sorted(survivors) + [None, None, None]


def test_correspondence_of_a_wholly_translated_island_is_identity(tmp_path):
    s = _shape()
    base = _export_read(tmp_path, [s])[obj_io.object_name(s)]
    edit = _with([(x, y, z + 1.0) for x, y, z in base.positions], base.faces)
    assert match.correspond(11, base, edit) == [0, 1, 2, 3]
    e = match.diff_shape(s, base, edit)
    assert [i for i, _ in e["moves"]] == [0, 1, 2, 3, 4]


def test_correspondence_appends_new_vertices_as_none(tmp_path):
    s = _shape()
    base = _export_read(tmp_path, [s])[obj_io.object_name(s)]
    edit = _copy(base)
    edit.positions.append((0.5, 0.5, 1.0))
    edit.faces.append([(0, (0, 0)), (1, (0.5, 0)), (4, (0.2, 0.2))])
    assert match.correspond(11, base, edit) == [0, 1, 2, 3, None]


def test_correspondence_follows_survivors_reordered_by_separate_and_join(tmp_path):
    # Separate + join moved original L0 to the end. Every vertex still sits
    # on exactly one base vertex (and vice versa): those pairs are anchored
    # whatever their order, so the reorder is read as no change at all.
    s = _seam_shape()
    base = _export_read(tmp_path, [s])[obj_io.object_name(s)]
    perm = list(range(1, len(base.positions))) + [0]
    edit = _permute(base, perm)
    assert match.correspond(11, base, edit) == perm
    assert match.diff_shape(s, base, edit) is None


def _cove_like():
    """b0395 (cove_graphic) in miniature: two columns of three vertices, A at
    x=1 (base 1, 0, 5 bottom to top), B at x=0 (base 2, 3, 4). Mark deleted
    the middle row (base 0 and 3), extended both columns down and up with new
    vertices, and joined the strip back -- so the survivors return in a
    swapped order: B-bottom, A-bottom, ..., A-top, B-top."""
    base = _with([(1, 0, 2), (1, 0, 1), (0, 0, 1), (0, 0, 2), (0, 0, 3), (1, 0, 3)],
                 [[(0, (0, .5)), (1, (0, 1)), (2, (1, 1))], [(0, (0, .5)), (2, (1, 1)), (3, (1, .5))],
                  [(4, (1, 0)), (5, (0, 0)), (0, (0, .5))], [(4, (1, 0)), (0, (0, .5)), (3, (1, .5))]])
    edit = _with([(0, 0, 1), (1, 0, 1), (1, 0, 0), (0, 0, 0),
                  (1, 0, 4), (1, 0, 3), (0, 0, 3), (0, 0, 4)],
                 [[(0, (1, 1)), (1, (0, 1)), (2, (0, 1.5))], [(0, (1, 1)), (2, (0, 1.5)), (3, (1, 1.5))],
                  [(4, (0, -.5)), (5, (0, 0)), (6, (1, 0))], [(4, (0, -.5)), (6, (1, 0)), (7, (1, -.5))],
                  [(0, (1, 1)), (6, (1, 0)), (5, (0, 0)), (1, (0, 1))]])
    return base, edit


def test_correspondence_anchors_coincident_survivors_in_any_order():
    base, edit = _cove_like()
    assert match.correspond(395, base, edit) == [2, 1, None, None, None, 5, 4, None]


def test_cove_like_rework_diffs_to_removals_and_ear_clipped_additions():
    base, edit = _cove_like()
    s = {"block": 395, "parent": "cove graphic", "hidden": False,
         "vertices": list(base.positions),
         "uvs": [(0, .5), (0, 1), (1, 1), (1, .5), (1, 0), (0, 0)],
         "colors": [(1, 1, 1, 1)] * 6, "uvs1": [],
         "triangles": [(0, 1, 2), (0, 2, 3), (4, 5, 0), (4, 0, 3)],
         "textures": ["Map 1.tga"], "world": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]}
    e = match.diff_shape(s, base, edit)
    assert e["remove_triangles"] == [0, 1, 2, 3]
    assert len(e["add_triangles"]) == 6                      # 4 triangles + a quad clipped in 2
    assert len(e["add_vertices"]) == 4                       # the four new corners
    assert e["moves"] == [] and e["uvs"] == []


def test_correspondence_prefers_the_nearer_candidate_over_connectivity_alone():
    # b0688 (Lcar_02) in miniature: the top edge (base 2, 3) moved down, and
    # a new column through the middle split the quad. The new bottom
    # midpoint shares more neighbours with base 2 than moved base 2 does,
    # but moved base 2 is far nearer to where it was.
    base = _with([(1, 0, 0), (-1, 0, 0), (-1, 0, 2), (1, 0, 2)],
                 [[(0, (1, 1)), (1, (0, 1)), (2, (0, 0))], [(0, (1, 1)), (2, (0, 0)), (3, (1, 0))]])
    edit = _with([(1, 0, 0), (-1, 0, 0), (0, 0, 0), (-1, 0, 1.2), (1, 0, 1.2), (0, 0, 1.2)],
                 [[(3, (0, 0)), (5, (.5, 0)), (2, (.5, 1)), (1, (0, 1))],
                  [(5, (.5, 0)), (4, (1, 0)), (0, (1, 1)), (2, (.5, 1))]])
    assert match.correspond(688, base, edit) == [0, 1, None, 2, 3, None]


def test_moves_and_uvs_on_originals_no_triangle_uses_are_dropped(tmp_path):
    s, base = _sliver_base(tmp_path)
    sliver = {_local(base, (5, 0, 0)), _local(base, (6, 0, 0)), _local(base, (5, 1, 0))}
    edit = _copy(base)
    del edit.faces[_face_on(base, sliver)]
    k = _local(base, (6, 0, 0))                     # original 3: in sliver triangles only
    edit.positions[k] = (6.0, 0.5, 0.0)             # moved, and re-used ONLY with a new UV
    edit.faces.append([_corner(base, (5, 0, 0), (0.5, 0.0)), (k, (0.77, 0.77)),
                       _corner(base, (2, 0, 0), (0.2, 0.0))])
    assert match.correspond(175, base, edit)[k] == k
    e = match.diff_shape(s, base, edit)
    assert e["remove_triangles"] == [2, 5, 6]
    assert e["moves"] == []                         # nothing renders original 3 any more
    assert _added_pos(s, e) == [pytest.approx((6.0, 0.5, 0.0))]
    assert e["add_triangles"] == [(2, 10, 7)]


def test_correspondence_leaves_a_tie_between_two_candidate_survivors_unpaired():
    # Two triangles on edge X-Y wound the same way (a fold); one apex was
    # deleted and the other moved to a point equally far from both: either
    # could be the survivor, so neither is -- the vertex is new and both
    # apexes deleted (the faces are re-derived either way; nothing guessed).
    base = _with([(0, 0, 0), (1, 0, 0), (0.5, 1, 0), (0.5, -1, 0)],
                 [[(0, None), (1, None), (2, None)], [(0, None), (1, None), (3, None)]])
    edit = _with([(0, 0, 0), (1, 0, 0), (0.5, 0, 1)],
                 [[(0, None), (1, None), (2, None)]])
    assert match.correspond(5, base, edit) == [0, 1, None]


def test_correspondence_tie_is_broken_by_face_winding():
    # Same, but the deleted apex's face was wound the other way: only the
    # first apex keeps the kept face's winding, so it is the survivor.
    base = _with([(0, 0, 0), (1, 0, 0), (0.5, 1, 0), (0.5, -1, 0)],
                 [[(0, None), (1, None), (2, None)], [(1, None), (0, None), (3, None)]])
    edit = _with([(0, 0, 0), (1, 0, 0), (0.5, 0, 1)],
                 [[(0, None), (1, None), (2, None)]])
    assert match.correspond(5, base, edit) == [0, 1, 2]


def test_correspondence_refuses_a_vertex_on_two_coincident_originals():
    # Base 2 and 3 sit within POS_TOL of each other (a weld-boundary straddle)
    # and one of them was deleted: which one survived is a position claim
    # nothing can settle.
    base = _with([(0, 0, 0), (1, 0, 0), (0.5, 1, 0), (0.5, 1.00005, 0)],
                 [[(0, None), (1, None), (2, None)], [(1, None), (0, None), (3, None)]])
    edit = _with([(0, 0, 0), (1, 0, 0), (0.5, 1, 0)], [[(0, None), (1, None), (2, None)]])
    with pytest.raises(ShapeDiffError, match="ambiguous correspondence"):
        match.correspond(5, base, edit)


# --- Task 15: new vertices (spec §5.3) ---

def _add_vertex(mesh, pos):
    mesh.positions.append(pos)
    return len(mesh.positions) - 1


def test_new_literal_vertex_with_attr_src_from_the_nearest_original(tmp_path):
    s = _shape()                                   # originals 1 and 4 at (1,0,0)
    base = _export_read(tmp_path, [s])[obj_io.object_name(s)]
    edit = _copy(base)
    n = _add_vertex(edit, (0.9, 0.1, 0.25))
    edit.faces.append([_corner(base, (0, 0, 0), (0.0, 0.0)),
                       _corner(base, (1, 0, 0), (0.5, 0.0)),
                       (n, (0.45, 0.05))])
    e = match.diff_shape(s, base, edit)
    [v] = e["add_vertices"]
    assert v["pos"].vertex == 1 and v["pos"].delta is not None   # nearest original + delta
    assert _added_pos(s, e) == [pytest.approx((0.9, 0.1, 0.25))]
    assert v["uv0"] == pytest.approx((0.45, 0.05)) and v["attr_src"] == 1
    assert e["add_triangles"] == [(0, 1, 5)]
    assert e["moves"] == [] and e["remove_triangles"] == []


def test_new_vertex_position_is_stored_shape_local(tmp_path):
    s = _shape(offset=(100.0, 50.0, 10.0))
    base = _export_read(tmp_path, [s])[obj_io.object_name(s)]
    edit = _copy(base)
    n = _add_vertex(edit, (100.5, 50.5, 11.0))
    edit.faces.append([_corner(base, (100, 50, 10), (0.0, 0.0)),
                       _corner(base, (101, 50, 10), (0.5, 0.0)), (n, (0.2, 0.2))])
    e = match.diff_shape(s, base, edit)
    assert _added_pos(s, e)[0] == pytest.approx((0.5, 0.5, 1.0))


def test_new_vertex_on_another_shapes_vertex_references_that_shape(tmp_path):
    a, b, objs = _two_shapes(tmp_path)
    b["uvs"] = [(0.7, 0.7), (0.8, 0.1), (0.9, 0.9), (0.6, 0.4), (0.3, 0.3)]
    objs = _export_read(tmp_path, [a, b])
    base = objs[obj_io.object_name(a)]
    edit = _copy(base)
    n = _add_vertex(edit, (4.0, 1.0, 0.0))                 # B's original 2
    edit.faces.append([_corner(base, (1, 0, 0), (0.5, 0.0)), (n, (0.9, 0.9)),
                       _corner(base, (1, 1, 0), (0.5, 1.0))])
    [e] = match.diff([a, b], objs, dict(objs, **{obj_io.object_name(a): edit}))
    assert e["add_vertices"] == [{"pos": Ref(12, 2), "uv0": Ref(12, 2), "attr_src": 2}]
    assert e["add_triangles"] == [(1, 5, 2)]


def test_new_vertex_used_with_two_uvs_becomes_two_added_vertices(tmp_path):
    s = _shape()
    base = _export_read(tmp_path, [s])[obj_io.object_name(s)]
    edit = _copy(base)
    n = _add_vertex(edit, (0.5, -1.0, 0.0))
    edit.faces.append([_corner(base, (0, 0, 0), (0.0, 0.0)), (n, (0.1, 0.9)),
                       _corner(base, (1, 0, 0), (0.5, 0.0))])
    edit.faces.append([_corner(base, (1, 0, 0), (0.5, 0.0)), (n, (0.2, 0.8)),
                       _corner(base, (0, 0, 0), (0.0, 0.0))])
    # second face would be the first's reverse: give it a distinct third corner
    edit.faces[-1][2] = _corner(base, (1, 1, 0), (0.5, 1.0))
    e = match.diff_shape(s, base, edit)
    assert [v["uv0"] for v in e["add_vertices"]] == [pytest.approx((0.1, 0.9)),
                                                    pytest.approx((0.2, 0.8))]
    assert _added_pos(s, e) == [pytest.approx((0.5, -1.0, 0.0))] * 2
    assert e["add_triangles"] == [(0, 5, 1), (1, 6, 2)]


def test_new_vertex_corner_without_a_uv_is_refused(tmp_path):
    s = _shape()
    base = _export_read(tmp_path, [s])[obj_io.object_name(s)]
    edit = _copy(base)
    n = _add_vertex(edit, (0.5, -1.0, 0.0))
    edit.faces.append([_corner(base, (0, 0, 0), (0.0, 0.0)), (n, None),
                       _corner(base, (1, 0, 0), (0.5, 0.0))])
    with pytest.raises(ShapeDiffError, match="no UV"):
        match.diff_shape(s, base, edit)


def test_deletion_move_and_new_vertices_round_trip_through_the_payload(tmp_path):
    s, base = _sliver_base(tmp_path)
    sliver = {_local(base, (5, 0, 0)), _local(base, (6, 0, 0)), _local(base, (5, 1, 0))}
    edit = _blender_delete(base, _face_on(base, sliver))
    l7, l8 = _local(edit, (2, 0, 0)), _local(edit, (2, 1, 0))
    edit.positions[l8] = (2.0, 1.5, 0.0)
    n1 = _add_vertex(edit, (3.0, 0.0, 0.0))
    n2 = _add_vertex(edit, (3.0, 1.0, 0.0))
    edit.faces.append([(l7, (0.2, 0.0)), (n1, (0.3, 0.0)), (n2, (0.3, 1.0))])
    e = match.diff_shape(s, base, edit)
    assert e["remove_triangles"] == [2, 5, 6]
    assert _moves(s, e) == [(8, pytest.approx((2.0, 1.5, 0.0)))]
    assert _added_pos(s, e) == [pytest.approx((3, 0, 0)),
                                                    pytest.approx((3, 1, 0))]
    # nearest ORIGINAL position: (2,0,0) is 7; (2,1,0) is 8 (it moved, but
    # attr_src is chosen against the unedited originals)
    assert [v["attr_src"] for v in e["add_vertices"]] == [7, 8]
    assert e["add_triangles"] == [(7, 10, 11)]
    raw = payload.encode([e])
    assert raw[:4] == b"BSD2"


# --- Task 15: ear clipping (ported from spike/bridge-lighting-vfx) ---

from tools.shape_diff import triangulate


def _area2(pts, tris, ax=(0, 1)):
    i, j = ax
    return sum(abs((pts[b][i] - pts[a][i]) * (pts[c][j] - pts[a][j])
                   - (pts[c][i] - pts[a][i]) * (pts[b][j] - pts[a][j])) / 2
               for a, b, c in tris)


def test_ear_clip_handles_a_concave_ngon():
    # An L-shaped hexagon in the XY plane: a fan from vertex 0 would put a
    # triangle outside the shape.
    pts = [(0, 0, 0), (4, 0, 0), (4, 1, 0), (1, 1, 0), (1, 4, 0), (0, 4, 0)]
    tris = triangulate.ear_clip(pts)
    assert len(tris) == 4
    assert _area2(pts, tris) == pytest.approx(7.0)   # 4x1 + 1x3, no triangle outside


@pytest.mark.parametrize("plane", ["xy", "xz", "yz"])
@pytest.mark.parametrize("flip", [False, True])
def test_ear_clip_keeps_the_polygon_winding_in_every_plane(plane, flip):
    square = [(0, 0), (2, 0), (2, 1), (1, 3), (0, 1)]
    if flip:
        square = square[::-1]
    lift = {"xy": lambda a, b: (a, b, 5.0), "xz": lambda a, b: (a, 5.0, b),
            "yz": lambda a, b: (5.0, a, b)}[plane]
    pts = [lift(a, b) for a, b in square]

    def normal(poly):
        n = [0.0, 0.0, 0.0]
        for k in range(len(poly)):
            p, q = poly[k], poly[(k + 1) % len(poly)]
            n[0] += (p[1] - q[1]) * (p[2] + q[2])
            n[1] += (p[2] - q[2]) * (p[0] + q[0])
            n[2] += (p[0] - q[0]) * (p[1] + q[1])
        return n

    want = normal(pts)
    tris = triangulate.ear_clip(pts)
    assert len(tris) == 3
    for t in tris:
        got = normal([pts[i] for i in t])
        assert sum(a * b for a, b in zip(got, want)) > 0


def test_ear_clip_refuses_a_self_intersecting_polygon():
    with pytest.raises(ShapeDiffError, match="can't be triangulated"):
        triangulate.ear_clip([(0, 0, 0), (1, 1, 0), (1, 0, 0), (0, 1, 0)])


# --- Task 15: --exclude ---

def test_diff_excludes_listed_blocks_even_when_they_would_be_refused(tmp_path):
    a = _shape(block=11)
    b = _shape(block=12, parent="console top", offset=(5.0, 0.0, 0.0))
    base = _export_read(tmp_path, [a, b])
    edit = dict(base)
    edit[obj_io.object_name(a)] = _moved(base[obj_io.object_name(a)], 1, (1.25, 0.0, 0.5))
    flipped = _copy(base[obj_io.object_name(b)])
    flipped.faces[0] = list(reversed(flipped.faces[0]))
    edit[obj_io.object_name(b)] = flipped
    with pytest.raises(ShapeDiffError, match="winding"):
        match.diff([a, b], base, edit)
    assert [e["block"] for e in match.diff([a, b], base, edit, exclude=[12])] == [11]
    edits, skipped = match.diff([a, b], base, edit, partial=True, exclude=[12])
    assert [e["block"] for e in edits] == [11] and skipped == []


def test_excluding_a_block_with_no_object_is_refused(tmp_path):
    a = _shape(block=11)
    base = _export_read(tmp_path, [a])
    with pytest.raises(ShapeDiffError, match="--exclude 99"):
        match.diff([a], base, base, exclude=[99])


def test_main_passes_exclude_and_reports_it(monkeypatch, tmp_path, capsys):
    cli, _ = _patched_cli(monkeypatch, tmp_path)
    seen = {}

    def fake(rel, base, edit, exclude=()):
        seen["exclude"] = list(exclude)
        return cli.make_fix_dict(rel, [GOLDEN_EDIT]), [GOLDEN_EDIT]
    monkeypatch.setattr(cli, "build_fix", fake)
    assert cli.main(["diff", "b.obj", "e.obj", "--exclude", "392", "--exclude", "395"]) == 0
    assert seen["exclude"] == [392, 395]
    assert "excluded: blocks 392, 395" in capsys.readouterr().out


def test_correspondence_breaks_a_connectivity_tie_on_kept_corner_uvs():
    # The two-apex tie above, but the kept face still shows apex 2's UV: a
    # moved survivor keeps its corner UVs, so apex 2 (base 2) survived.
    base = _with([(0, 0, 0), (1, 0, 0), (0.5, 1, 0), (0.5, -1, 0)],
                 [[(0, (0, 0)), (1, (1, 0)), (2, (0.1, 0.9))],
                  [(1, (1, 0)), (0, (0, 0)), (3, (0.2, 0.2))]])
    edit = _with([(0, 0, 0), (1, 0, 0), (0.5, 2, 0)],
                 [[(0, (0, 0)), (1, (1, 0)), (2, (0.1, 0.9))]])
    assert match.correspond(5, base, edit) == [0, 1, 2]


def test_real_dbridge_new_vertex_snapped_onto_another_shape_is_a_reference(tmp_path):
    host = pytest.importorskip("_dauntless_host")
    nif = paths.game_root() / DBRIDGE
    if not nif.exists():
        pytest.skip("BC content not configured")
    from tools import bridge_shape_diff as cli
    cli.export(DBRIDGE, tmp_path)
    base = tmp_path / "Dbridge.obj"
    shapes = {s["block"]: s for s in host.nif_shapes(str(nif))}
    target = shapes[24]["vertices"][0]                      # block 24: a rotated frame
    assert match.NifIndex([shapes[468]]).position_ref(target, 468) is None
    text = base.read_text()
    lines = text.splitlines()
    o = lines.index("o b0468_Material_D_walls_1")
    first_face = next(line for line in lines[o:] if line.startswith("f "))
    (a, ta), (b, tb) = [tuple(map(int, c.split("/")[:2])) for c in first_face.split()[1:3]]
    n_v = sum(1 for line in lines if line.startswith("v "))
    n_vt = sum(1 for line in lines if line.startswith("vt "))
    usemtl = next(line for line in lines[o:] if line.startswith("usemtl "))
    x, y, z = frames.bc_to_obj(target)
    edit = tmp_path / "edit.obj"
    edit.write_text(text + f"o b0468_Material_D_walls_1\nv {x:.6f} {y:.6f} {z:.6f}\n"
                    f"vt 0.25 0.75\n{usemtl}\nf {a}/{ta} {b}/{tb} {n_v + 1}/{n_vt + 1}\n")
    _, edits = cli.build_fix(DBRIDGE, base, edit)
    [e] = edits
    assert e["block"] == 468
    [v] = e["add_vertices"]
    assert v["pos"] == payload.Ref(24, 0)
    assert v["uv0"] == pytest.approx((0.25, 0.25))          # OBJ v is flipped
    assert 0 <= v["attr_src"] < len(shapes[468]["vertices"])
    assert e["add_triangles"][0][2] == len(shapes[468]["vertices"])
    assert payload.encode([e])[:4] == b"BSD2"



def test_every_unsnapped_move_is_its_own_original_plus_a_delta(tmp_path):
    s = _shape(offset=(100.0, 50.0, 10.0))
    base = _export_read(tmp_path, [s])[obj_io.object_name(s)]
    e = match.diff_shape(s, base, _moved(base, 1, (101.25, 50.0, 10.5)))
    assert [(i, p.block, p.vertex) for i, p in e["moves"]] == [(1, 11, 1), (4, 11, 4)]
    assert e["moves"][0][1].delta == pytest.approx((0.25, 0.0, 0.5))


# --- Task 15 fix round: a removal must not land without its replacement ---

def _removal_and_dependent(tmp_path, offset):
    """A (block 175) loses its sliver face (corners (5,0,0) (6,0,0) (5,1,0));
    B (block 180, a quad at `offset`) moves its vertex at offset + (0,1,0) to
    offset + (-1, 0, 0) and has an unsupported edit (a flipped face) -- so
    --partial skips B. With offset (7,0,0) B's moved vertex lands on A's
    removed corner (6,0,0): B was A's replacement."""
    a = _sliver_shape(175)
    b = _shape(block=180, parent="cove graphic", offset=offset)
    base = _export_read(tmp_path, [a, b])
    na, nb = obj_io.object_name(a), obj_io.object_name(b)
    base[na] = _blenderize(base[na])
    edit = dict(base)
    ea = _copy(base[na])
    sliver = {_local(ea, (5, 0, 0)), _local(ea, (6, 0, 0)), _local(ea, (5, 1, 0))}
    del ea.faces[_face_on(ea, sliver)]
    edit[na] = ea
    eb = _copy(base[nb])
    ox, oy, oz = offset
    eb.positions[_local(eb, (ox, oy + 1, oz))] = (ox - 1, oy, oz)
    eb.faces[0] = list(reversed(eb.faces[0]))
    edit[nb] = eb
    return [a, b], base, edit, na, nb


def test_partial_skips_a_removal_whose_replacement_was_skipped(tmp_path):
    shapes, base, edit, na, nb = _removal_and_dependent(tmp_path, (7.0, 0.0, 0.0))
    edits, skipped = match.diff(shapes, base, edit, partial=True)
    assert edits == []
    reasons = dict(skipped)
    assert set(reasons) == {na, nb}
    assert f"depends on skipped {nb}" in reasons[na]


def test_partial_keeps_a_removal_no_skipped_edit_touches(tmp_path):
    shapes, base, edit, na, nb = _removal_and_dependent(tmp_path, (50.0, 0.0, 0.0))
    edits, skipped = match.diff(shapes, base, edit, partial=True)
    assert [e["block"] for e in edits] == [175]
    assert [n for n, _ in skipped] == [nb]


def test_excluding_a_removals_replacement_refuses_unless_both_are_excluded(tmp_path):
    shapes, base, edit, na, nb = _removal_and_dependent(tmp_path, (7.0, 0.0, 0.0))
    with pytest.raises(ShapeDiffError, match=f"depends on excluded {nb}"):
        match.diff(shapes, base, edit, exclude=[180])
    assert match.diff(shapes, base, edit, exclude=[175, 180]) == []
    edits, skipped = match.diff(shapes, base, edit, partial=True, exclude=[180])
    assert edits == [] and [n for n, _ in skipped] == [na]


# --- Task 15 fix round: verify the fix by applying it (spec §5.4) ---

from tools.shape_diff import verify


def _applied(shape, moves=None):
    """`shape` as nif_shapes(path, fix) would report it after moving
    original i to model-space p for each i, p in `moves`."""
    out = dict(shape)
    out["vertices"] = list(shape["vertices"])
    for i, p in (moves or {}).items():
        out["vertices"][i] = p
    return out


def test_verify_accepts_an_applied_fix_that_reproduces_the_edit(tmp_path):
    s = _shape()
    base = _export_read(tmp_path, [s])[obj_io.object_name(s)]
    edit = _moved(base, 1, (1.25, 0.0, 0.5))               # originals 1 and 4
    applied = _applied(s, {1: (1.25, 0.0, 0.5), 4: (1.25, 0.0, 0.5)})
    n = verify.check([s], [applied], {11: (obj_io.object_name(s), edit)})
    assert n == 1


def test_verify_refuses_a_fix_that_does_not_reproduce_the_edit(tmp_path):
    s = _shape()
    base = _export_read(tmp_path, [s])[obj_io.object_name(s)]
    edit = _moved(base, 1, (1.25, 0.0, 0.5))
    applied = _applied(s, {1: (1.25, 0.0, 0.5)})            # seam copy 4 left behind
    with pytest.raises(ShapeDiffError, match=r"b0011_wall_side_pnls_01.*triangle"):
        verify.check([s], [applied], {11: (obj_io.object_name(s), edit)})


def test_verify_refuses_a_change_to_a_block_outside_the_fix(tmp_path):
    a, b = _shape(block=11), _shape(block=12, parent="console top", offset=(5, 0, 0))
    objs = _export_read(tmp_path, [a, b])
    with pytest.raises(ShapeDiffError, match="block 12.*not in the fix"):
        verify.check([a, b], [a, _applied(b, {0: (9.0, 9.0, 9.0)})],
                     {11: (obj_io.object_name(a), objs[obj_io.object_name(a)])})


def test_verify_tolerates_collapsed_reversed_twins_and_seam_uvs(tmp_path):
    # the sliver is stored three times in the NIF (twice, once reversed);
    # Blender shows one face. An unchanged object must verify.
    s, base = _sliver_base(tmp_path)
    assert verify.check([s], [s], {175: (obj_io.object_name(s), base)}) == 1


def test_verify_compares_ear_clipped_n_gons(tmp_path):
    s, base = _sliver_base(tmp_path)
    edit = _copy(base)
    edit.faces.append([_corner(base, (2, 0, 0), (0.2, 0.0)), _corner(base, (5, 0, 0), (0.5, 0.0)),
                       _corner(base, (5, 1, 0), (0.5, 1.0)), _corner(base, (2, 1, 0), (0.2, 1.0))])
    applied = dict(s)
    applied["triangles"] = list(s["triangles"]) + [(8, 7, 2), (2, 6, 8)]
    assert verify.check([s], [applied], {175: (obj_io.object_name(s), edit)}) == 1
    applied["triangles"] = list(s["triangles"]) + [(8, 7, 2)]
    with pytest.raises(ShapeDiffError, match="triangle"):
        verify.check([s], [applied], {175: (obj_io.object_name(s), edit)})


def test_build_fix_refuses_to_proceed_without_the_host_module(monkeypatch, tmp_path):
    from tools import bridge_shape_diff as cli
    s = _shape()
    obj = tmp_path / "x.obj"
    obj_io.write_obj([s], obj, tmp_path / "x.mtl", lambda n: None)
    monkeypatch.setattr(cli, "_shapes", lambda rel: [s])
    monkeypatch.setattr(verify, "_host", lambda: None)
    with pytest.raises(ShapeDiffError, match="can't verify"):
        cli.build_fix(DBRIDGE, obj, obj)
    fix, edits = cli.build_fix(DBRIDGE, obj, obj, verify=False)    # explicit opt-out
    assert edits == []


def test_real_dbridge_build_fix_verifies_and_catches_a_corrupted_edit(tmp_path, monkeypatch, capsys):
    pytest.importorskip("_dauntless_host")
    nif = paths.game_root() / DBRIDGE
    if not nif.exists():
        pytest.skip("BC content not configured")
    from tools import bridge_shape_diff as cli
    cli.export(DBRIDGE, tmp_path)
    base = tmp_path / "Dbridge.obj"
    lines = base.read_text().splitlines()
    i = lines.index("o b0468_Material_D_walls_1") + 1
    x, y, z = map(float, lines[i].split()[1:4])
    lines[i] = f"v {x:.6f} {y + 0.5:.6f} {z:.6f}" + "".join(" " + c for c in lines[i].split()[4:])
    edit = tmp_path / "edit.obj"
    edit.write_text("\n".join(lines) + "\n")
    cli.build_fix(DBRIDGE, base, edit)
    assert "verified 1 objects" in capsys.readouterr().out
    real = match.diff

    def corrupt(*a, **k):
        edits = real(*a, **k)
        i, p = edits[0]["moves"][0]
        edits[0]["moves"][0] = (i, payload.Ref(p.block, p.vertex, (0.0, 0.0, 0.0)))
        return edits
    monkeypatch.setattr(match, "diff", corrupt)
    with pytest.raises(ShapeDiffError, match="b0468_Material_D_walls_1"):
        cli.build_fix(DBRIDGE, base, edit)


def test_mark_round_regenerates_and_verifies():
    # Mark's own Blender round (read only; skipped where absent).
    pytest.importorskip("_dauntless_host")
    folder = Path("/Users/mward/Documents/dauntless-blender")   # paths-guard: Mark's local Blender folder, read only
    base, edit = (folder / f"Dbridge_{k}_rexport.obj" for k in ("unmodified", "modified"))
    if not (base.exists() and edit.exists() and (paths.game_root() / DBRIDGE).exists()):
        pytest.skip("Mark's Blender export not present")
    from tools import bridge_shape_diff as cli
    fix, edits, skipped = cli.build_fix(DBRIDGE, base, edit, partial=True)
    blocks = {e["block"] for e in edits}
    assert {392, 395, 471, 688, 697} <= blocks
    assert skipped == []


# --- Task 15 fix round 2 ---

def test_a_moved_corner_whose_face_was_flipped_is_still_refused(tmp_path):
    # Reviewer's probe: vertex 1 is only in face 0; move it and reverse face 0.
    # It is a survivor (nearest to where it was) -- the flip must be refused,
    # never re-derived as a new back-face.
    s = _shape()
    base = _export_read(tmp_path, [s])[obj_io.object_name(s)]
    edit = _moved(base, 1, (1.25, 0.0, 0.5))
    edit.faces[0] = list(reversed(edit.faces[0]))
    with pytest.raises(ShapeDiffError, match="winding"):
        match.diff_shape(s, base, edit)


def test_verify_catches_a_leftover_twin_under_an_added_face(tmp_path):
    # The fix adds (8,7,2) but an original triangle on the same three
    # positions (reversed) survives: a back-face twin edit.obj doesn't show.
    s, base = _sliver_base(tmp_path)
    edit = _copy(base)
    edit.faces.append([_corner(base, (2, 0, 0), (0.2, 0.0)), _corner(base, (5, 0, 0), (0.5, 0.0)),
                       _corner(base, (2, 1, 0), (0.2, 1.0))])
    stock = dict(s)
    stock["triangles"] = list(s["triangles"]) + [(8, 2, 7)]        # a reversed original
    applied = dict(stock)
    applied["triangles"] = list(stock["triangles"]) + [(7, 2, 8)]  # the fix's addition
    with pytest.raises(ShapeDiffError, match="keeps triangle"):
        verify.check([stock], [applied], {175: (obj_io.object_name(s), edit)},
                     added={175: 1})
    applied["triangles"] = list(s["triangles"]) + [(7, 2, 8)]      # twin removed: fine
    stock["triangles"] = list(s["triangles"])
    assert verify.check([stock], [applied], {175: (obj_io.object_name(s), edit)},
                        added={175: 1}) == 1


def test_survivor_warning_lists_only_pairs_that_produce_a_move(tmp_path):
    s = _shape()
    base = _export_read(tmp_path, [s])[obj_io.object_name(s)]
    e = match.diff_shape(s, base, _moved(base, 1, (1.25, 0.0, 0.5)))
    assert "moved_survivors" not in e                  # identity pair, no deletions
    s2, base2 = _sliver_base(tmp_path)
    sliver = {_local(base2, (5, 0, 0)), _local(base2, (6, 0, 0)), _local(base2, (5, 1, 0))}
    edit2 = _blender_delete(base2, _face_on(base2, sliver))
    k = _local(edit2, (2, 1, 0))
    edit2.positions[k] = (2.0, 1.5, 0.0)
    e2 = match.diff_shape(s2, base2, edit2)
    assert e2["moved_survivors"] == [(k, _local(base2, (2, 1, 0)))]
