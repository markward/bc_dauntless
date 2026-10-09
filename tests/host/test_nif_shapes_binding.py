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
