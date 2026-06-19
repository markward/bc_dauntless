import os
from engine.appc import viewscreen_static as vss


def test_paths_for_view_screen_static():
    paths = vss.static_texture_paths("View Screen Static")
    assert len(paths) == 3
    assert [os.path.basename(p) for p in paths] == [
        "Noise1.tga", "Noise2.tga", "Noise3.tga"]
    for p in paths:
        assert os.path.isabs(p)
        assert os.path.normpath("data/Textures/Effects") in os.path.normpath(p)


def test_paths_for_unknown_group_empty():
    assert vss.static_texture_paths("Nonexistent Group") == []
    assert vss.static_texture_paths(None) == []


def test_intensity_lerps_and_clamps():
    # midpoint
    assert vss.static_intensity(0.0, 1.0, rng=lambda: 0.5) == 0.5
    # min when rng=0
    assert vss.static_intensity(0.2, 0.6, rng=lambda: 0.0) == 0.2
    # max when rng=1
    assert vss.static_intensity(0.2, 0.6, rng=lambda: 1.0) == 0.6
    # E5M4 (5,5) clamps to 1.0
    assert vss.static_intensity(5.0, 5.0, rng=lambda: 0.5) == 1.0
    # never negative
    assert vss.static_intensity(0.0, 0.0, rng=lambda: 0.5) == 0.0
