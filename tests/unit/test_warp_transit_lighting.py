"""Tests for the in-warp transit lighting rig (_warp_transit_lighting)."""

import math


def test_key_light_points_along_travel():
    from engine import host_loop
    travel = (0.0, 0.0, 1.0)
    amb, dirs = host_loop._warp_transit_lighting(travel, 1.0)
    # Two directionals: key from ahead (along travel), fill from behind.
    assert len(dirs) == 2
    key_dir, key_col = dirs[0]
    fill_dir, _fill_col = dirs[1]
    assert key_dir == (0.0, 0.0, 1.0)         # toward travel direction
    assert fill_dir == (0.0, 0.0, -1.0)       # opposite
    # Key is the bright cool one; fill is dimmer.
    assert key_col == host_loop._WARP_LIGHT_KEY
    assert sum(key_col) > sum(_fill_col)


def test_travel_is_normalized():
    from engine import host_loop
    _amb, dirs = host_loop._warp_transit_lighting((0.0, 5.0, 0.0), 1.0)
    key_dir, _ = dirs[0]
    assert math.isclose(key_dir[1], 1.0, abs_tol=1e-6)
    assert key_dir[0] == 0.0 and key_dir[2] == 0.0


def test_streak_scales_intensity_in_and_out():
    from engine import host_loop
    # streak 0 => fully off (warp look faded out)
    amb0, dirs0 = host_loop._warp_transit_lighting((0.0, 1.0, 0.0), 0.0)
    assert amb0 == (0.0, 0.0, 0.0)
    assert dirs0[0][1] == (0.0, 0.0, 0.0)
    # streak 0.5 => half intensity
    _a, dirs_half = host_loop._warp_transit_lighting((0.0, 1.0, 0.0), 0.5)
    assert math.isclose(dirs_half[0][1][2], host_loop._WARP_LIGHT_KEY[2] * 0.5)
    # streak 1 => full key
    _a, dirs_full = host_loop._warp_transit_lighting((0.0, 1.0, 0.0), 1.0)
    assert dirs_full[0][1] == host_loop._WARP_LIGHT_KEY


def test_zero_travel_falls_back_to_forward():
    from engine import host_loop
    _amb, dirs = host_loop._warp_transit_lighting((0.0, 0.0, 0.0), 1.0)
    assert dirs[0][0] == (0.0, 1.0, 0.0)  # degenerate travel => model-forward
