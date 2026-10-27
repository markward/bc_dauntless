from tools.shape_diff import obj_io, smoothing

V = ["v 0 0 0", "v 1 0 0", "v 1 1 0", "v 0 1 0"]
VT = ["vt 0 0", "vt 1 0", "vt 1 1", "vt 0 1"]


def _load(tmp_path, lines):
    (tmp_path / "a.mtl").write_text("newmtl m\nKd 1 1 1\n")
    p = tmp_path / "a.obj"
    p.write_text("mtllib a.mtl\no b0001_x\n" + "\n".join(lines) + "\n")
    return obj_io.read_objects(p)["b0001_x"]


def _quad(tmp_path, n1, n2):
    """Quad as two triangles (1,2,3) and (1,3,4); shared edge is verts 0-2."""
    vn = ["vn 0 0 1", "vn 0 1 0", "vn 1 0 0", "vn 0 0 -1"]
    f1 = " ".join(f"{v}/{v}/{n}" for v, n in zip((1, 2, 3), n1))
    f2 = " ".join(f"{v}/{v}/{n}" for v, n in zip((1, 3, 4), n2))
    return _load(tmp_path, V + VT + vn + [f"f {f1}", f"f {f2}"])


def test_reader_keeps_corner_normals(tmp_path):
    m = _quad(tmp_path, (1, 1, 1), (1, 1, 1))
    assert len(m.face_normals) == 2
    assert all(len(f) == 3 for f in m.face_normals)
    assert all(n is not None for f in m.face_normals for n in f)
    m2 = _load(tmp_path, V + VT + ["f 1/1 2/2 3/3"])
    assert m2.face_normals == [[None, None, None]]


def test_shared_normals_make_a_soft_edge(tmp_path):
    m = _quad(tmp_path, (1, 1, 1), (1, 1, 1))
    flags = smoothing.edge_flags(m)
    assert list(flags) == [(0, 2)]
    f = flags[(0, 2)]
    assert (f.hard, f.same_a, f.same_b) == (False, True, True)


def test_split_normals_make_a_hard_edge(tmp_path):
    m = _quad(tmp_path, (1, 1, 1), (2, 2, 2))
    f = smoothing.edge_flags(m)[(0, 2)]
    assert (f.hard, f.same_a, f.same_b) == (True, False, False)


def test_hard_edge_ending_in_a_smooth_fan(tmp_path):
    # edge (0,1): faces differ at vertex 1 only
    vn = ["vn 0 0 1", "vn 0 1 0"]
    lines = V + ["v 0 -1 0"] + VT + ["vt 0 0"] + vn + [
        "f 1/1/1 2/2/1 3/3/1",
        "f 1/1/1 2/2/2 5/5/1",
    ]
    m = _load(tmp_path, lines)
    f = smoothing.edge_flags(m)[(0, 1)]
    assert f.hard is True
    assert (f.same_a, f.same_b) == (True, False)


def test_no_vn_means_not_authored(tmp_path):
    m = _load(tmp_path, V + VT + ["f 1/1 2/2 3/3", "f 1/1 3/3 4/4"])
    assert smoothing.edge_flags(m) is None


def test_open_and_three_face_edges_are_not_flagged(tmp_path):
    lines = V + ["v 0 0 1"] + VT + ["vt 0 0", "vn 0 0 1",
        "f 1/1/1 2/2/1 3/3/1", "f 1/1/1 2/2/1 4/4/1", "f 1/1/1 2/2/1 5/5/1"]
    m = _load(tmp_path, lines)
    assert smoothing.edge_flags(m) == {}


import pytest

from tools.shape_diff import ShapeDiffError, payload
from tools.shape_diff.obj_io import ObjMesh


def test_smoothing_payload_matches_cpp_golden():
    recs = [
        {"block": 7, "vertex_count": 4, "hard": [(0, 1)], "soft": [(0, 2), (1, 2)]},
        {"block": 12, "vertex_count": 3, "hard": [], "soft": []},
    ]
    assert payload.encode_smoothing_b64(recs) == (
        "QlNNMQIABwAAAAQAAQACAAAAAQAAAAIAAQACAAwAAAADAAAAAAA=")
    assert len(payload.encode_smoothing(recs)) == 38


def test_encoder_refuses_overflow_and_bad_pairs():
    ok = {"block": 1, "vertex_count": 4, "hard": [], "soft": []}
    for bad in (
        dict(ok, vertex_count=70000),
        dict(ok, hard=[(2, 1)]),
        dict(ok, soft=[(1, 1)]),
        dict(ok, hard=[(0, 4)]),
        dict(ok, soft=[(0, 70000)], vertex_count=65535),
    ):
        with pytest.raises(ShapeDiffError):
            payload.encode_smoothing([bad])


def _mesh(positions, faces, normals):
    return ObjMesh(positions=positions,
                   faces=[[(v, 0) for v in f] for f in faces],
                   face_normals=normals)


N1, N2 = (0.0, 0.0, 1.0), (0.0, 1.0, 0.0)


def _tri_pair(n_second):
    pos = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
    return _mesh(pos, [(0, 1, 2), (0, 2, 3)],
                 [[N1] * 3, [n_second] * 3])


def test_records_map_edges_to_final_indices():
    mesh = _tri_pair(N2)
    d = 1.0 / 1024
    applied = [{"block": 3, "vertices": [
        (0, 0, 0), (1, 0, 0), (1 + d, 1 - d, 0), (0, 1, 0), (9, 9, 9),
        (1, 1, 0)]}]
    recs = smoothing.records(applied, {3: mesh})
    assert len(recs) == 1
    r = recs[0]
    assert (r["block"], r["vertex_count"]) == (3, 6)
    assert r["hard"] == [(0, 2)]
    assert r["soft"] == []
    assert r["ends"][(0, 2)] == (False, False)


def test_records_swap_ends_when_final_order_flips():
    # OBJ vertex 0 lands on final 3, vertex 2 on final 1: edge (0,2) -> (1,3)
    applied = [{"block": 3, "vertices": [
        (9, 9, 9), (1, 1, 0), (8, 8, 8), (0, 0, 0), (1, 0, 0), (0, 1, 0)]}]
    mesh2 = _mesh([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
                  [(0, 1, 2), (0, 2, 3)],
                  [[N1, N1, N2], [N1, N1, N1]])
    r = smoothing.records(applied, {3: mesh2})[0]
    a, b = 1, 3
    assert (a, b) in r["ends"]
    flag = smoothing.edge_flags(mesh2)[(0, 2)]
    assert (flag.same_a, flag.same_b) == (True, False)
    assert r["ends"][(a, b)] == (False, True)


def test_records_refuse_an_unmatched_vertex():
    applied = [{"block": 3, "vertices": [(0, 0, 0), (1, 0, 0), (0, 1, 0)]}]
    with pytest.raises(ShapeDiffError, match="3"):
        smoothing.records(applied, {3: _tri_pair(N2)})


def test_records_refuse_a_block_not_in_the_applied_shapes():
    with pytest.raises(ShapeDiffError, match="9"):
        smoothing.records([{"block": 3, "vertices": []}], {9: _tri_pair(N2)})


def test_records_refuse_conflicting_flags():
    # Two OBJ edges (0,2) and (1,3) collapse onto final pair (0,1).
    pos = [(0, 0, 0), (0, 0, 0), (1, 0, 0), (1, 0, 0)]
    # edge A (0,2): hard; edge B (1,3): soft
    mesh = _mesh(pos, [(0, 2, 1), (0, 3, 1), (0, 2, 1)], [])
    mesh.faces = [[(0, 0), (2, 0), (3, 0)], [(0, 0), (2, 0), (1, 0)],
                  [(1, 0), (3, 0), (2, 0)], [(1, 0), (3, 0), (0, 0)]]
    mesh.face_normals = [[N1] * 3, [N2] * 3, [N1] * 3, [N1] * 3]
    applied = [{"block": 3, "vertices": [(0, 0, 0), (1, 0, 0)]}]
    with pytest.raises(ShapeDiffError, match="conflict"):
        smoothing.records(applied, {3: mesh})


def test_object_without_normals_gets_no_record():
    mesh = _mesh([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)], [[None] * 3])
    applied = [{"block": 3, "vertices": [(0, 0, 0), (1, 0, 0), (0, 1, 0)]}]
    assert smoothing.records(applied, {3: mesh}) == []
