"""Rock mid band dev toggle (rock-real Part 1 strip-back, 2026-10-03).

Independent of far_set_enabled (the master switch, which still disables
everything when off): rock_mid_set_enabled gates the mid band's build and
every draw of it (solid and fading). Default OFF. The assertions reuse
test_rock_mid_host.py's synthetic sphere source (no SDK mission needed).
"""
import os

import pytest

h = pytest.importorskip("_dauntless_host")

from engine.rocks import far_tier


def _sphere_source(radius=1000.0):
    """One full-density view-space sphere around the origin, no noise."""
    return {
        "id": 43, "frame": "", "centre": (0.0, 0.0, 0.0), "normal": (0.0, 0.0, 1.0),
        "table": [], "outer_fade_gu": 0.0, "scale_height_frac": 0.03,
        "scale_height_min_gu": 1000.0, "seed": 7, "explicit_regions": [],
        "populations": [], "shape": "sphere", "procedural": False,
        "view_space": True, "sphere_radius_gu": radius, "sphere_edge_frac": 0.0}


def _look_from(host, eye):
    host.set_camera(eye=eye, target=(0.0, 0.0, 0.0), up=(0.0, 1.0, 0.0),
                    fov_y_rad=1.0472, near=0.1, far=1.0e7)


def _push_real_catalogue():
    from engine import renderer
    far_tier.reset()
    far_tier._push_catalogue(renderer)


def _mid_field(host):
    _push_real_catalogue()
    host.far_set_dials({})
    host.far_set_sources([_sphere_source(radius=1000.0)])
    host.far_set_frame(None, (0.0, 0.0, 0.0))


@pytest.fixture
def host():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    try:
        h.init(640, 600, "test_rock_mid_haze_toggles")
    except RuntimeError as e:
        pytest.skip(f"no GL context: {e}")
    far_tier.reset()
    h.dust_set_enabled(False)
    try:
        yield h
    finally:
        far_tier.reset()
        h.far_clear()
        h.far_set_dials({})
        h.far_set_enabled(True)
        h.rock_mid_set_enabled(False)
        h.dust_set_enabled(True)
        h.minors_set_player(None)
        h.shutdown()


def test_mid_defaults_off(host):
    assert h.rock_mid_enabled() is False


# ── Mid band ──────────────────────────────────────────────────────────────

def test_mid_off_draws_no_sprites_and_no_scope_work(host):
    _mid_field(host)
    _look_from(host, (0.0, 0.0, 1500.0))
    host.profiler_set_enabled(True)
    try:
        host.frame()
        st = host.far_stats()
        assert st["mid_sprites"] == 0 and st["mid_tiles"] == 0
        order = [s["name"] for s in host.profiler_scopes()]
        assert "rock.mid.draw" not in order, order
    finally:
        host.profiler_set_enabled(False)


def test_mid_on_restores_the_build_and_draw(host):
    _mid_field(host)
    _look_from(host, (0.0, 0.0, 1500.0))
    host.profiler_set_enabled(True)
    try:
        host.rock_mid_set_enabled(True)
        for _ in range(6):       # profiler scopes resolve a few frames late
            host.frame()
        st = host.far_stats()
        assert st["mid_sprites"] > 0 and st["mid_tiles"] > 0
        order = [s["name"] for s in host.profiler_scopes()]
        assert "rock.mid.draw" in order, order
    finally:
        host.profiler_set_enabled(False)
