"""SPV-only fill light (_spv_frame_lighting): while the Ship Property Viewer
is open, a soft fill from the anti-key direction lights the side of the hull
the sun leaves black. Closed, the lighting passes through untouched."""
import inspect
import math


def _dirs():
    return [((0.0, 2.0, 0.0), (1.0, 0.9, 0.8)),
            ((1.0, 0.0, 0.0), (0.2, 0.2, 0.2))]


def test_open_adds_a_fill_opposite_the_brightest_key():
    from engine import host_loop
    amb = (0.1, 0.1, 0.1)
    out_amb, out_dirs = host_loop._spv_frame_lighting(amb, _dirs(), True)
    assert out_amb == amb
    assert out_dirs[:2] == _dirs()
    fill_dir, fill_col = out_dirs[2]
    assert fill_dir == (-0.0, -1.0, -0.0)
    k = host_loop.SPV_FILL_STRENGTH
    assert all(math.isclose(c, k * kc) for c, kc in zip(fill_col, (1.0, 0.9, 0.8)))
    assert 0.0 < k < 1.0


def test_closed_is_the_in_game_lighting_unchanged():
    from engine import host_loop
    amb, dirs = (0.1, 0.1, 0.1), _dirs()
    out_amb, out_dirs = host_loop._spv_frame_lighting(amb, dirs, False)
    assert out_amb is amb and out_dirs is dirs


def test_open_then_closed_restores():
    from engine import host_loop
    amb, dirs = (0.1, 0.1, 0.1), _dirs()
    host_loop._spv_frame_lighting(amb, dirs, True)
    assert dirs == _dirs(), "the input list is never mutated"
    assert host_loop._spv_frame_lighting(amb, dirs, False)[1] is dirs


def test_the_fill_respects_the_four_light_cap():
    from engine import host_loop
    dirs = _dirs() * 2
    _a, out = host_loop._spv_frame_lighting((0.1,) * 3, dirs, True)
    assert len(out) == 4
    assert out[-1][0] == (-0.0, -1.0, -0.0)


def test_no_key_light_means_no_fill():
    from engine import host_loop
    assert host_loop._spv_frame_lighting((0.1,) * 3, [], True)[1] == []


def test_the_render_loop_applies_it_only_under_the_spv():
    from engine import host_loop
    src = inspect.getsource(host_loop)
    i = src.index("ambient, directionals = _aggregate_lights(active_set, player)")
    j = src.index("r.set_lighting(ambient, directionals)", i)
    assert ("ambient, directionals = _spv_frame_lighting(\n"
            "                ambient, directionals, _spv_open)") in src[i:j]
