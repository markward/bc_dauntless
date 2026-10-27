import pytest

from engine import paths
from tools.shape_diff import ShapeDiffError, obj_io, payload, smoothing, verify
from tools.shape_diff.obj_io import ObjMesh

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
    assert r["hard"] == [(0, 5)]
    assert r["soft"] == []
    assert r["ends"][(0, 5)] == (False, False)


def test_records_tie_goes_to_the_lowest_index():
    applied = [{"block": 3, "vertices": [
        (0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (1, 1, 0)]}]
    r = smoothing.records(applied, {3: _tri_pair(N2)})[0]
    assert r["hard"] == [(0, 2)]


def test_records_match_across_a_grid_cell_boundary():
    d = 1.0 / 1024
    edge = 3 * d
    applied = [{"block": 3, "vertices": [
        (0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]}]
    mesh = _tri_pair(N2)
    mesh.positions[1] = (1 - 0.4 * d, 0, 0)
    applied[0]["vertices"][1] = (1 + 0.4 * d, 0, 0)
    assert smoothing.records(applied, {3: mesh})[0]["hard"] == [(0, 2)]
    assert edge


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


def test_records_refuse_conflicting_ends():
    # Edges (0,2) and (1,3) land on final pair (0,1), both hard, but the
    # normals agree at different ends. The other edges are open.
    pos = [(0, 0, 0), (0, 0, 0), (1, 0, 0), (1, 0, 0),
           (2, 0, 0), (3, 0, 0), (4, 0, 0), (5, 0, 0)]
    faces = [(0, 2, 4), (0, 2, 5), (1, 3, 6), (1, 3, 7)]
    normals = [[N1, N1, N1], [N1, N2, N1], [N1, N1, N1], [N2, N1, N1]]
    mesh = _mesh(pos, faces, normals)
    flags = smoothing.edge_flags(mesh)
    assert (flags[(0, 2)].hard, flags[(0, 2)].same_a, flags[(0, 2)].same_b) == (True, True, False)
    assert (flags[(1, 3)].hard, flags[(1, 3)].same_a, flags[(1, 3)].same_b) == (True, False, True)
    applied = [{"block": 3, "vertices": [
        (0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0), (4, 0, 0), (5, 0, 0)]}]
    with pytest.raises(ShapeDiffError, match="conflicting ends"):
        smoothing.records(applied, {3: mesh})


def test_object_without_normals_gets_no_record():
    mesh = _mesh([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)], [[None] * 3])
    applied = [{"block": 3, "vertices": [(0, 0, 0), (1, 0, 0), (0, 1, 0)]}]
    assert smoothing.records(applied, {3: mesh}) == []


def test_encoder_refuses_unordered_duplicate_and_shared_pairs():
    ok = {"block": 1, "vertex_count": 6, "hard": [], "soft": []}
    for bad in (
        dict(ok, hard=[(2, 3), (0, 1)]),
        dict(ok, soft=[(0, 1), (0, 1)]),
        dict(ok, hard=[(0, 1)], soft=[(0, 1)]),
    ):
        with pytest.raises(ShapeDiffError):
            payload.encode_smoothing([bad])


def test_encoder_refuses_more_than_65535_edges():
    n = 65535
    pairs = [(0, i) for i in range(1, 65535)] + [(1, 2), (1, 3)]
    rec = {"block": 1, "vertex_count": n, "hard": pairs, "soft": []}
    with pytest.raises(ShapeDiffError):
        payload.encode_smoothing([rec])


def test_smoothing_payload_decodes_what_it_encodes():
    recs = [
        {"block": 7, "vertex_count": 4, "hard": [(0, 1)], "soft": [(0, 2), (1, 2)]},
        {"block": 12, "vertex_count": 3, "hard": [], "soft": []},
    ]
    assert payload.decode_smoothing_b64(payload.encode_smoothing_b64(recs)) == recs


# --- verifier -----------------------------------------------------------

REC = {"block": 5, "vertex_count": 4, "hard": [(0, 2)], "soft": [(1, 3)],
       "ends": {(0, 2): (False, True), (1, 3): (True, True)}}


def _row(a, b, joined_a, joined_b, found=True, block=5):
    return {"block": block, "a": a, "b": b, "found": found,
            "joined_a": joined_a, "joined_b": joined_b}


def test_check_smoothing_passes_matching_rows():
    rows = [_row(0, 2, False, True), _row(1, 3, True, True)]
    assert verify.check_smoothing([REC], rows) == 2


def test_check_smoothing_refuses_soft_where_blender_hard():
    rows = [_row(0, 2, True, True), _row(1, 3, True, True)]
    with pytest.raises(ShapeDiffError,
                       match=r"block 5: edge 0-2 renders soft at vertex 0 where Blender shows hard"):
        verify.check_smoothing([REC], rows)


def test_check_smoothing_refuses_hard_where_blender_soft():
    rows = [_row(0, 2, False, True), _row(1, 3, True, False)]
    with pytest.raises(ShapeDiffError,
                       match=r"block 5: edge 1-3 renders hard at vertex 3 where Blender shows soft"):
        verify.check_smoothing([REC], rows)


def test_check_smoothing_refuses_missing_row():
    rows = [_row(0, 2, False, True), _row(1, 3, True, True, block=6)]
    with pytest.raises(ShapeDiffError, match=r"block 5: edge 1-3"):
        verify.check_smoothing([REC], rows)


def test_check_smoothing_refuses_an_edge_not_found():
    rows = [_row(0, 2, False, True, found=False), _row(1, 3, True, True)]
    with pytest.raises(ShapeDiffError, match=r"block 5: edge 0-2"):
        verify.check_smoothing([REC], rows)


# --- CLI ----------------------------------------------------------------

DBRIDGE = "data/Models/Sets/DBridge/Dbridge.NIF"


def test_make_fix_dict_smoothing_only_has_no_shape_edits():
    from tools import bridge_shape_diff as cli
    fix = cli.make_fix_dict(DBRIDGE, [], smoothing="QlNNMQAA")
    assert fix["smoothing"] == "QlNNMQAA"
    assert "shape_edits" not in fix
    assert "shape_edits" in cli.make_fix_dict(DBRIDGE, [])


def test_main_treats_a_smoothing_only_diff_as_a_change(monkeypatch, tmp_path, capsys):
    from tools import bridge_shape_diff as cli
    nif_file = tmp_path / "fake.nif"
    nif_file.write_bytes(b"fake nif")
    monkeypatch.setattr(cli, "_fix_dir", lambda: tmp_path)
    monkeypatch.setattr(cli, "_nif_path", lambda rel: nif_file)
    rec = {"block": 7, "vertex_count": 4, "hard": [(0, 1)], "soft": [(0, 2), (1, 2)]}
    fix = cli.make_fix_dict(DBRIDGE, [], smoothing=payload.encode_smoothing_b64([rec]))
    monkeypatch.setattr(cli, "build_fix", lambda rel, base, edit: (fix, []))
    assert cli.main(["diff", "a.obj", "b.obj"]) == 0
    out = capsys.readouterr().out
    assert "no changes" not in out
    assert "smoothing: 1 shapes, 1 hard / 2 soft edges" in out
    assert "dry run" in out


def _real_cli(tmp_path):
    pytest.importorskip("_dauntless_host")
    if not (paths.game_root() / DBRIDGE).exists():
        pytest.skip("BC content not configured")
    from tools import bridge_shape_diff as cli
    return cli, cli.export(DBRIDGE, tmp_path)


def _objects(lines):
    """Exported OBJ lines -> ({name: (o line, [f line indices])}, OBJ-frame
    positions by global index)."""
    objs, pos, name = {}, [], None
    for i, line in enumerate(lines):
        if line.startswith("o "):
            name = line[2:]
            objs[name] = (i, [])
        elif line.startswith("v "):
            pos.append(tuple(float(c) for c in line.split()[1:4]))
        elif line.startswith("f "):
            objs[name][1].append(i)
    return objs, pos


def _face_verts(line):
    return [int(t.split("/")[0]) - 1 for t in line.split()[1:]]


def _flat_normal(pts):
    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = pts[:3]
    u, v = (bx - ax, by - ay, bz - az), (cx - ax, cy - ay, cz - az)
    n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    length = sum(c * c for c in n) ** 0.5
    return None if length < 1e-9 else tuple(c / length for c in n)


def _with_flat_normals(lines, names):
    """`lines` with flat per-face `vn` on every face of the objects in
    `names`, computed from the export's own faces (no NIF value)."""
    objs, pos = _objects(lines)
    out = list(lines)
    vn, insert_at = [], {}
    for name in names:
        o_line, faces = objs[name]
        insert_at[o_line] = []
        for fi in faces:
            verts = _face_verts(lines[fi])
            n = _flat_normal([pos[v] for v in verts])
            vn.append(n)
            insert_at[o_line].append(f"vn {n[0]:.6f} {n[1]:.6f} {n[2]:.6f}")
            out[fi] = "f " + " ".join(f"{t}/{len(vn)}" for t in lines[fi].split()[1:])
    for o_line in sorted(insert_at, reverse=True):
        out[o_line + 1:o_line + 1] = insert_at[o_line]
    return out


def _candidates(lines):
    """Objects, fewest faces first, whose faces are non-degenerate, each on a
    distinct position set, with at least one two-face edge."""
    from collections import Counter
    objs, pos = _objects(lines)
    out = []
    for name, (_, faces) in objs.items():
        vs = [_face_verts(lines[fi]) for fi in faces]
        if len(vs) < 2 or len({frozenset(v) for v in vs}) != len(vs):
            continue
        if any(_flat_normal([pos[v] for v in f]) is None for f in vs):
            continue
        uses = Counter(frozenset((f[i], f[(i + 1) % len(f)])) for f in vs for i in range(len(f)))
        if any(n == 2 for n in uses.values()):
            out.append((len(vs), obj_io.block_of(name), name))
    return [name for _, _, name in sorted(out)]


def _without_object(lines, name):
    """`lines` with object `name` deleted, as Blender exports it: every later
    v / vt / vn index shifts down by the lines it owned."""
    objs, _ = _objects(lines)
    start = objs[name][0]
    end = min((o for o, _ in objs.values() if o > start), default=len(lines))
    tags = ("v ", "vt ", "vn ")
    first = [sum(1 for ln in lines[:start] if ln.startswith(t)) for t in tags]
    gone = [sum(1 for ln in lines[start:end] if ln.startswith(t)) for t in tags]
    out = []
    for ln in lines[:start] + lines[end:]:
        if ln.startswith("f "):
            toks = []
            for tok in ln.split()[1:]:
                f = tok.split("/")
                for k, idx in enumerate(f):
                    if idx and int(idx) > first[k]:
                        f[k] = str(int(idx) - gone[k])
                toks.append("/".join(f))
            ln = "f " + " ".join(toks)
        out.append(ln)
    return out


def _decoded(fix):
    return payload.decode_smoothing_b64(fix["smoothing"])


def _authored_block(cli, tmp_path, base, extra=lambda lines, name: (lines, {})):
    """First candidate object whose flat-normal edit builds and verifies;
    `extra(lines, name) -> (lines, build_fix kwargs)` adds to the edit."""
    lines = base.read_text(encoding="utf-8").splitlines()
    edit = tmp_path / "edit.obj"
    refused = []
    for name in _candidates(lines)[:12]:
        edit_lines, kw = extra(_with_flat_normals(lines, [name]), name)
        edit.write_text("\n".join(edit_lines) + "\n", encoding="utf-8")
        try:
            return name, cli.build_fix(DBRIDGE, base, edit, **kw)
        except ShapeDiffError as exc:
            refused.append(f"{name}: {exc}")
    pytest.fail("no candidate verified:\n" + "\n".join(refused))


def test_build_fix_writes_smoothing_for_an_authored_object(tmp_path, capsys):
    cli, base = _real_cli(tmp_path)
    name, (fix, edits) = _authored_block(cli, tmp_path, base)
    assert edits == []
    assert "shape_edits" not in fix
    recs = _decoded(fix)
    assert [r["block"] for r in recs] == [obj_io.block_of(name)]
    assert recs[0]["hard"]
    out = capsys.readouterr().out
    assert "verified smoothing on " in out


def test_no_record_for_skipped_or_deleted_blocks(tmp_path):
    cli, base = _real_cli(tmp_path)
    lines = base.read_text(encoding="utf-8").splitlines()
    cands = _candidates(lines)

    def extra(edit_lines, name):
        deleted, excluded = [n for n in cands if n != name][:2]
        edit_lines = _without_object(_with_flat_normals(edit_lines, [deleted, excluded]), deleted)
        return edit_lines, {"delete": [obj_io.block_of(deleted)],
                            "exclude": [obj_io.block_of(excluded)]}

    name, (fix, edits) = _authored_block(cli, tmp_path, base, extra)
    assert [r["block"] for r in _decoded(fix)] == [obj_io.block_of(name)]


def test_partial_skipped_block_gets_no_record(tmp_path):
    cli, base = _real_cli(tmp_path)
    lines = base.read_text(encoding="utf-8").splitlines()
    cands = _candidates(lines)

    def extra(edit_lines, name):
        other = [n for n in cands if n != name][0]
        edit_lines = _with_flat_normals(edit_lines, [other])
        o, _ = _objects(edit_lines)
        fi = o[other][1][0]
        toks = edit_lines[fi].split()[1:]
        edit_lines[fi] = "f " + " ".join(reversed(toks))   # flipped winding: refused
        return edit_lines, {"partial": True}

    name, (fix, edits, skipped) = _authored_block(cli, tmp_path, base, extra)
    assert len(skipped) == 1
    assert [r["block"] for r in _decoded(fix)] == [obj_io.block_of(name)]


def test_export_without_normals_writes_no_smoothing(tmp_path):
    cli, base = _real_cli(tmp_path)
    fix, edits = cli.build_fix(DBRIDGE, base, base)
    assert edits == []
    assert "smoothing" not in fix
