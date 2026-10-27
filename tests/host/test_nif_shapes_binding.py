import pytest

from engine import paths


def _host():
    return pytest.importorskip("_dauntless_host")


def test_galaxy_has_one_id_shape_with_consistent_arrays():
    nif = paths.game_root() / "data/Models/Ships/Galaxy/Galaxy.nif"
    if not nif.exists():
        pytest.skip("BC content not configured")
    shapes = _host().nif_shapes(str(nif))
    ids = [s for s in shapes if any("ID" in t for t in s["textures"])]
    assert len(ids) == 1
    s = ids[0]
    assert s["name"] == "Ent-D Saucer Section:9"
    assert len(s["vertices"]) == len(s["normals"]) == len(s["uvs"]) == 25
    assert len(s["triangles"]) == 30
    assert not s["hidden"]


def test_missing_file_returns_none():
    assert _host().nif_shapes("/nonexistent/x.nif") is None


def test_dbridge_shapes_carry_frame_parent_colours_and_uv1():
    nif = paths.game_root() / "data/Models/Sets/DBridge/Dbridge.NIF"
    if not nif.exists():
        pytest.skip("BC content not configured")
    shapes = _host().nif_shapes(str(nif))
    assert len(shapes) == 145
    by_block = {s["block"]: s for s in shapes}
    walls = by_block[468]
    assert walls["parent"] == "Material: D walls 1"
    assert walls["data_block"] >= 0
    w = walls["world"]
    assert len(w) == 16 and w[15] == 1.0
    assert sum(1 for s in shapes if s["colors"]) == 123
    assert sum(1 for s in shapes if s["uvs1"]) == 17
    for s in shapes:
        n = len(s["vertices"])
        assert len(s["colors"]) in (0, n)
        assert len(s["uvs1"]) in (0, n)
        assert all(len(c) == 4 for c in s["colors"])


def test_dbridge_shapes_resolve_textures_through_ancestor_nodes():
    # F1: DBridge's NiTextureProperty sits on ancestor NiNodes, not the
    # shape's own property_links. Every visible shape must still report a
    # texture (walked up the parent chain, nearest ancestor wins).
    nif = paths.game_root() / "data/Models/Sets/DBridge/Dbridge.NIF"
    if not nif.exists():
        pytest.skip("BC content not configured")
    shapes = _host().nif_shapes(str(nif))
    visible = [s for s in shapes if not s["hidden"]]
    untextured = [s["block"] for s in visible if not s["textures"]]
    assert untextured == [], f"shapes with no resolved texture: {untextured}"


def _dbridge():
    nif = paths.game_root() / "data/Models/Sets/DBridge/Dbridge.NIF"
    if not nif.exists():
        pytest.skip("BC content not configured")
    return nif


def test_nif_shapes_applies_a_given_fix_in_memory():
    import base64
    import json
    import struct
    nif = _dbridge()
    stock = {s["block"]: s for s in _host().nif_shapes(str(nif))}
    s = stock[468]
    # BSD2: move original 0 of block 468 to its own position + (0, 0, 1) local
    blob = (b"BSD2" + struct.pack("<H", 1)
            + struct.pack("<IHH", 468, len(s["vertices"]), len(s["triangles"]))
            + struct.pack("<5H", 1, 0, 0, 0, 0)
            + struct.pack("<HBIH3f", 0, 2, 468, 0, 0.0, 0.0, 1.0))
    fix = json.dumps({"format": 1, "shape_edits": base64.b64encode(blob).decode()})
    fixed = {d["block"]: d for d in _host().nif_shapes(str(nif), fix)}
    w = s["world"]
    dz = (w[8], w[9], w[10])                 # local +z in model space
    moved = fixed[468]["vertices"][0]
    assert moved == pytest.approx(tuple(a + b for a, b in zip(s["vertices"][0], dz)), abs=1e-4)
    assert fixed[468]["vertices"][1:] == pytest.approx(s["vertices"][1:])
    assert fixed[29]["vertices"] == stock[29]["vertices"]
    assert _host().nif_shapes(str(nif), None) == list(stock.values())


def test_nif_shapes_raises_the_loaders_refusal():
    nif = _dbridge()
    bad = '{"format": 1, "textures": [{"block": 0, "albedo": "x.tga"}]}'
    with pytest.raises(RuntimeError, match="not a NiTriShape"):
        _host().nif_shapes(str(nif), bad)
    with pytest.raises(RuntimeError, match="parse"):
        _host().nif_shapes(str(nif), "{ nope")


def test_nif_shapes_reports_a_flipbooks_frame_0_as_the_shapes_texture():
    # A flipbook property has image_link 0 (as BC's stock EBridge one does);
    # the renderer draws source 0 as its static Base, so nif_shapes must too.
    import json
    nif = _dbridge()
    fix = json.dumps({"format": 1, "textures": [{
        "block": 688, "albedo": "Map 7.tga",
        "flipbook": {"frames": ["Map 7.tga", "Map 8.tga"], "fps": 5.0}}]})
    fixed = {d["block"]: d for d in _host().nif_shapes(str(nif), fix)}
    assert fixed[688]["textures"] == ["Map 7.tga"]


def _two_triangle_edge(shape):
    # An edge of this block shared by EXACTLY two triangles (welded by
    # position), as vertex indices a < b -- derived from the file, not hard-coded.
    verts = shape["vertices"]
    key = lambda i: tuple(round(c, 4) for c in verts[i])
    seen = {}
    for tri in shape["triangles"]:
        for u, v in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            if key(u) == key(v):
                continue
            e = tuple(sorted((key(u), key(v))))
            seen.setdefault(e, []).append((min(u, v), max(u, v)))
    for pairs in seen.values():
        if len(pairs) == 2 and pairs[0][0] != pairs[0][1]:
            return pairs[0]
    pytest.skip("no two-triangle edge in the chosen block")


def _smoothing_fix(block, vertex_count, hard):
    import json
    from tools.shape_diff.payload import encode_smoothing_b64
    rec = {"block": block, "vertex_count": vertex_count, "hard": hard, "soft": []}
    return json.dumps({"format": 1, "smoothing": encode_smoothing_b64([rec])})


def test_set_smoothing_report_on_dbridge():
    nif = _dbridge()
    shape = {s["block"]: s for s in _host().nif_shapes(str(nif))}[468]
    a, b = _two_triangle_edge(shape)
    fix = _smoothing_fix(468, len(shape["vertices"]), [(a, b)])
    rows = _host().set_smoothing_report(str(nif), fix)
    assert rows == [{"block": 468, "a": a, "b": b, "found": True,
                     "joined_a": False, "joined_b": False}]


def test_set_smoothing_report_refused_fix_raises():
    nif = _dbridge()
    shape = {s["block"]: s for s in _host().nif_shapes(str(nif))}[468]
    fix = _smoothing_fix(468, len(shape["vertices"]) + 1, [(0, 1)])
    with pytest.raises(RuntimeError, match="refused"):
        _host().set_smoothing_report(str(nif), fix)


def test_set_smoothing_report_missing_file_returns_none():
    assert _host().set_smoothing_report("/nonexistent/x.nif", "{}") is None
