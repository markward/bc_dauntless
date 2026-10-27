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
