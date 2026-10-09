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
