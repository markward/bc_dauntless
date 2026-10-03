"""Rock fields mid band, host wiring (rock-fields plan Task 11).

far_set_catalogue's optional third argument hands the baked collection
impostors to the native MidField (atlas slots after the catalogue's);
render_space_geometry builds and draws its sprites per drawn camera
(scope rock.mid.draw); far_stats() reports mid_sprites / mid_tiles. Gated on
the far tier being enabled.
"""
import os

import pytest

h = pytest.importorskip("_dauntless_host")

from engine.rocks import far_tier  # noqa: E402


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


def _field(host):
    _push_real_catalogue()
    host.far_set_dials({})
    host.far_set_sources([_sphere_source(radius=1000.0)])
    host.far_set_frame(None, (0.0, 0.0, 0.0))


@pytest.fixture
def host():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    try:
        h.init(64, 64, "test_rock_mid")
    except RuntimeError as e:
        pytest.skip(f"no GL context: {e}")
    try:
        yield h
    finally:
        h.far_clear()
        h.far_set_dials({})
        h.far_set_enabled(True)
        h.minors_set_player(None)
        h.shutdown()
        far_tier.reset()


def test_outside_a_field_looking_at_it_draws_mid_sprites_only(host):
    _field(host)
    _look_from(host, (0.0, 0.0, 1500.0))
    host.frame()
    st = host.far_stats()
    assert st["mid_sprites"] > 0
    assert st["mid_tiles"] > 0
    assert st["near_meshes"] == 0


def test_inside_a_field_draws_mid_sprites_and_near_rocks(host):
    """At the centre the near band streams and draws, and the mid band
    still draws its (>= 80 GU) sprites around it."""
    _field(host)
    host.set_camera(eye=(0.0, 0.0, 0.0), target=(0.0, 0.0, -1.0),
                    up=(0.0, 1.0, 0.0), fov_y_rad=1.0472, near=0.1, far=1.0e7)
    host.frame()
    st = host.far_stats()
    assert st["mid_sprites"] > 0
    assert st["near_cells"] > 0 and st["near_meshes"] > 0


def test_disabled_far_tier_draws_no_mid_sprites(host):
    _field(host)
    _look_from(host, (0.0, 0.0, 1500.0))
    host.frame()
    assert host.far_stats()["mid_sprites"] > 0
    host.far_set_enabled(False)
    st = host.far_stats()
    assert st["mid_sprites"] == 0 and st["mid_tiles"] == 0
    host.frame()
    st = host.far_stats()
    assert st["mid_sprites"] == 0 and st["mid_tiles"] == 0


def test_far_clear_leaves_no_mid_output(host):
    _field(host)
    _look_from(host, (0.0, 0.0, 1500.0))
    host.frame()
    assert host.far_stats()["mid_sprites"] > 0
    host.far_clear()
    st = host.far_stats()
    assert st["mid_sprites"] == 0 and st["mid_tiles"] == 0
    host.frame()
    st = host.far_stats()
    assert st["mid_sprites"] == 0 and st["mid_tiles"] == 0


def test_without_collections_nothing_draws_in_the_mid_band(host):
    """A two-argument far_set_catalogue (no collections) leaves the mid band
    empty: there is nothing to place in a tile."""
    from engine import renderer
    from engine.rocks import catalogue
    far_tier.reset()
    entries = [far_tier._catalogue_entry(renderer, r) for r in catalogue.load()]
    host.far_set_catalogue(entries, [tuple(d) for d in catalogue.impostor_view_dirs()])
    host.far_set_dials({})
    host.far_set_sources([_sphere_source(radius=1000.0)])
    host.far_set_frame(None, (0.0, 0.0, 0.0))
    _look_from(host, (0.0, 0.0, 1500.0))
    host.frame()
    assert host.far_stats()["mid_sprites"] == 0


def test_mid_dials_reach_the_native_field(host):
    """mid_fill 0 empties every tile (chance = density x fill)."""
    _field(host)
    host.far_set_dials({"mid_fill": 0.0})
    _look_from(host, (0.0, 0.0, 1500.0))
    host.frame()
    assert host.far_stats()["mid_sprites"] == 0
    host.far_set_dials({})
    host.frame()
    assert host.far_stats()["mid_sprites"] > 0


def test_mid_fades_draw_translucent_in_their_own_scope(host):
    """Rock fade (2026-10-03): from 1,500 GU the r 1,000 field spans the
    L0/L1 (450-600 GU) and L1/L2 (1,800-2,400 GU) crossfades, so some drawn
    sprites are fading -- counted in mid_fading (a part of mid_sprites) and
    drawn by the blended draw, profiled as rock.fade.draw."""
    _field(host)
    _look_from(host, (0.0, 0.0, 1500.0))
    host.profiler_set_enabled(True)
    try:
        for _ in range(6):
            host.frame()
        st = host.far_stats()
        assert 0 < st["mid_fading"] < st["mid_sprites"], st
        names = {s["name"] for s in host.profiler_scopes()}
        assert "rock.fade.draw" in names, sorted(names)
    finally:
        host.profiler_set_enabled(False)
