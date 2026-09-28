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
