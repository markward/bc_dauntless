"""Tests for engine.appc.backdrops.aggregate_for_renderer."""
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).parent.parent.parent
GAME_DATA = PROJECT_ROOT / "game" / "data"


def test_aggregate_returns_empty_for_none():
    from engine.appc.backdrops import aggregate_for_renderer
    assert aggregate_for_renderer(None, PROJECT_ROOT) == []


def test_aggregate_returns_empty_for_set_with_no_backdrops():
    import App
    from engine.appc.backdrops import aggregate_for_renderer
    pSet = App.SetClass_Create()
    assert aggregate_for_renderer(pSet, PROJECT_ROOT) == []


def test_aggregate_resolves_texture_path_against_game_dir():
    """data/stars.tga must resolve to project_root/game/data/stars.tga."""
    if not (GAME_DATA / "stars.tga").is_file():
        pytest.skip("BC assets not available")
    import App
    from engine.appc.backdrops import aggregate_for_renderer
    pSet = App.SetClass_Create()
    s = App.StarSphere_Create()
    s.SetTextureFileName("data/stars.tga")
    pSet.AddBackdropToSet(s, "stars")

    result = aggregate_for_renderer(pSet, PROJECT_ROOT)
    assert len(result) == 1
    expected_abs = str((GAME_DATA / "stars.tga").resolve())
    assert result[0]["texture_path"] == expected_abs


def test_aggregate_preserves_draw_order():
    if not (GAME_DATA / "stars.tga").is_file():
        pytest.skip("BC assets not available")
    import App
    from engine.appc.backdrops import aggregate_for_renderer
    pSet = App.SetClass_Create()
    star = App.StarSphere_Create();         star.SetTextureFileName("data/stars.tga")
    cloud1 = App.BackdropSphere_Create();   cloud1.SetTextureFileName("data/stars.tga")
    cloud2 = App.BackdropSphere_Create();   cloud2.SetTextureFileName("data/stars.tga")
    pSet.AddBackdropToSet(star, "stars")
    pSet.AddBackdropToSet(cloud1, "n1")
    pSet.AddBackdropToSet(cloud2, "n2")

    result = aggregate_for_renderer(pSet, PROJECT_ROOT)
    assert [r["kind"] for r in result] == ["star", "backdrop", "backdrop"]


def test_aggregate_extracts_world_rotation_from_align_to_vectors():
    if not (GAME_DATA / "stars.tga").is_file():
        pytest.skip("BC assets not available")
    import App
    from engine.appc.backdrops import aggregate_for_renderer
    from engine.appc.math import TGPoint3

    pSet = App.SetClass_Create()
    s = App.StarSphere_Create()
    s.SetTextureFileName("data/stars.tga")
    fwd = TGPoint3(); fwd.SetXYZ(0.185766, 0.947862, -0.258938)
    up  = TGPoint3(); up.SetXYZ(0.049825, 0.254099, 0.965894)
    s.AlignToVectors(fwd, up)
    pSet.AddBackdropToSet(s, "stars")

    result = aggregate_for_renderer(pSet, PROJECT_ROOT)
    m9 = result[0]["world_rotation"]
    assert len(m9) == 9
    # Row 1 (forward axis) must equal the AlignToVectors-normalized fwd.
    # AlignToVectors normalises; (0.186, 0.948, -0.259) is already
    # near-unit-length so we can compare directly with tolerance.
    assert m9[3] == pytest.approx(0.185766, abs=1e-4)
    assert m9[4] == pytest.approx(0.947862, abs=1e-4)
    assert m9[5] == pytest.approx(-0.258938, abs=1e-4)


def test_aggregate_drops_backdrops_with_unresolvable_texture(capsys):
    import App
    from engine.appc.backdrops import aggregate_for_renderer
    pSet = App.SetClass_Create()
    pSet.SetName("MissingTextureSet")
    s = App.StarSphere_Create()
    s.SetTextureFileName("data/does_not_exist.tga")
    pSet.AddBackdropToSet(s, "stars")

    result = aggregate_for_renderer(pSet, PROJECT_ROOT)
    assert result == []
    out = capsys.readouterr().out
    assert "MissingTextureSet" in out
    assert "data/does_not_exist.tga" in out


def test_aggregate_unresolvable_warning_fires_once_per_set(capsys):
    import App
    from engine.appc.backdrops import aggregate_for_renderer
    pSet = App.SetClass_Create()
    pSet.SetName("RepeatSet")
    s = App.StarSphere_Create()
    s.SetTextureFileName("data/missing.tga")
    pSet.AddBackdropToSet(s, "stars")

    aggregate_for_renderer(pSet, PROJECT_ROOT)
    capsys.readouterr()  # drain first warning
    aggregate_for_renderer(pSet, PROJECT_ROOT)
    assert capsys.readouterr().out == ""


def test_aggregate_drops_empty_texture_path_silently(capsys):
    import App
    from engine.appc.backdrops import aggregate_for_renderer
    pSet = App.SetClass_Create()
    s = App.StarSphere_Create()
    # No SetTextureFileName called.
    pSet.AddBackdropToSet(s, "stars")

    result = aggregate_for_renderer(pSet, PROJECT_ROOT)
    assert result == []
    assert capsys.readouterr().out == ""


def test_aggregate_snaps_target_poly_count_to_minimum():
    if not (GAME_DATA / "stars.tga").is_file():
        pytest.skip("BC assets not available")
    import App
    from engine.appc.backdrops import aggregate_for_renderer
    pSet = App.SetClass_Create()
    s = App.StarSphere_Create()
    s.SetTextureFileName("data/stars.tga")
    s.SetTargetPolyCount(0)
    pSet.AddBackdropToSet(s, "stars")
    result = aggregate_for_renderer(pSet, PROJECT_ROOT)
    assert result[0]["target_poly_count"] == 64


def test_aggregate_passes_through_tile_and_span():
    if not (GAME_DATA / "stars.tga").is_file():
        pytest.skip("BC assets not available")
    import App
    from engine.appc.backdrops import aggregate_for_renderer
    pSet = App.SetClass_Create()
    s = App.StarSphere_Create()
    s.SetTextureFileName("data/stars.tga")
    s.SetTextureHTile(22.0)
    s.SetTextureVTile(11.0)
    s.SetHorizontalSpan(0.3025)
    s.SetVerticalSpan(0.605)
    pSet.AddBackdropToSet(s, "stars")
    result = aggregate_for_renderer(pSet, PROJECT_ROOT)
    assert result[0]["h_tile"] == 22.0
    assert result[0]["v_tile"] == 11.0
    assert result[0]["h_span"] == 0.3025
    assert result[0]["v_span"] == 0.605
