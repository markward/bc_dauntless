"""Far tier host wiring (far-tier plan Task 8).

The global ``far_*`` bindings feed the native FarField that ``frame()`` builds
per drawn camera; the build's fades are written onto each flagged rock's
``Instance::far_fade`` (0 = mesh, 1 = skip), read back here through the
test-only ``far_debug_fade``.
"""
import os

import pytest

h = pytest.importorskip("_dauntless_host")


def _source(**kw):
    d = {
        "id": 1, "frame": "Vesuvi", "centre": (0.0, 0.0, 0.0), "normal": (0.0, 0.0, 1.0),
        "table": [(0.0, 0.05), (226000.0, 0.5)], "outer_fade_gu": 20000.0,
        "scale_height_frac": 0.03, "scale_height_min_gu": 1000.0, "seed": 9,
        "explicit_regions": [], "populations": [{
            "kind": 0, "density_at_1": 9.67e-8, "a_lo": 0.0, "a_hi": 1.0,
            "r_min": 0.05, "r_max": 0.7, "exponent": 2.5, "rocks": [5], "weights": [1.0],
            "albedo": (0.4, 0.4, 0.4)}]}
    d.update(kw)
    return d


def test_far_bindings_are_on_the_facade():
    from engine import renderer
    for name in ("far_set_catalogue", "far_set_rocks", "far_set_sources",
                 "far_set_frame", "far_set_dials", "far_set_enabled",
                 "far_enabled", "far_stats", "far_clear"):
        assert callable(getattr(renderer, name))


def test_far_enabled_round_trip():
    h.far_set_enabled(False)
    assert h.far_enabled() is False
    h.far_set_enabled(True)
    assert h.far_enabled() is True


def test_far_sources_round_trip_into_stats():
    h.far_clear()
    h.far_set_sources([_source()])
    assert h.far_stats()["sources"] == 1
    h.far_clear()
    assert h.far_stats()["sources"] == 0


def test_far_stats_keys():
    assert set(h.far_stats()) == {"sources", "rocks", "cached_cells", "generated",
                                  "cells", "impostors", "specks", "draw_calls"}


def test_far_set_dials_p_min_and_omitted_keys_reset():
    h.far_set_dials({"p_min": 0.5, "max_cells_per_axis": 9})
    assert h.frame_state_debug()["far_p_min"] == 0.5
    h.far_set_dials({})
    assert h.frame_state_debug()["far_p_min"] == 0.25


def test_far_set_catalogue_and_frame_accept_their_shapes():
    h.far_set_catalogue(
        [{"albedo": "a.png", "normal": "n.png", "avg_albedo": (0.3, 0.3, 0.3)},
         {"albedo": "", "normal": "", "avg_albedo": (0.5, 0.4, 0.3)}],
        [(0.0, 0.0, 1.0), (1.0, 0.0, 0.0)])
    h.far_set_frame("Vesuvi", (1.0, 2.0, 3.0))
    h.far_set_frame(None, (0.0, 0.0, 0.0))
    h.far_clear()


# ── Frame wiring (GL) ──────────────────────────────────────────────────────


def _row_major(x, y, z, s=1.0):
    return [s, 0, 0, x, 0, s, 0, y, 0, 0, s, z, 0, 0, 0, 1.0]


def _look_down_minus_z():
    h.set_camera(eye=(0.0, 0.0, 0.0), target=(0.0, 0.0, -1.0),
                 up=(0.0, 1.0, 0.0), fov_y_rad=1.0472, near=0.1, far=1.0e7)


def _rock_model():
    from engine.rocks import catalogue
    rock = catalogue.pick("x", kind="fragment", family="silicate")
    return h.load_model(rock.lod_paths[0], [], None, decals=None, scale=1.0)


@pytest.fixture
def host():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    try:
        h.init(64, 64, "test_far")
    except RuntimeError as e:
        pytest.skip(f"no GL context: {e}")
    try:
        yield h
    finally:
        h.shutdown()


def test_a_far_flagged_rock_fades_its_mesh_out_and_back(host):
    rock = h.create_instance(_rock_model())
    # radius 1 GU at 10000 GU: ~0.01 px -- far below speck_lo, mesh weight 0.
    h.set_world_transform(rock, _row_major(0.0, 0.0, -10000.0))
    h.far_set_rocks([{"instance": rock, "index": -1, "radius_mu": 1.0}])
    _look_down_minus_z()
    h.frame()
    assert h.far_debug_fade(rock) == 1.0
    # Unflagged: the fade is written back to mesh-only at once.
    h.far_set_rocks([])
    assert h.far_debug_fade(rock) == 0.0


def test_a_near_flagged_rock_stays_mesh(host):
    rock = h.create_instance(_rock_model())
    h.set_world_transform(rock, _row_major(0.0, 0.0, -5.0))
    h.far_set_rocks([{"instance": rock, "index": -1, "radius_mu": 1.0}])
    _look_down_minus_z()
    h.frame()
    assert h.far_debug_fade(rock) == 0.0


def test_disabling_far_zeroes_fades_and_skips_the_build(host):
    rock = h.create_instance(_rock_model())
    h.set_world_transform(rock, _row_major(0.0, 0.0, -10000.0))
    h.far_set_rocks([{"instance": rock, "index": -1, "radius_mu": 1.0}])
    _look_down_minus_z()
    h.frame()
    assert h.far_debug_fade(rock) == 1.0
    h.far_set_enabled(False)
    assert h.far_debug_fade(rock) == 0.0
    h.frame()
    assert h.far_debug_fade(rock) == 0.0
    s = h.far_stats()
    assert s["specks"] == 0 and s["draw_calls"] == 0


def test_far_clear_zeroes_flagged_fades(host):
    rock = h.create_instance(_rock_model())
    h.set_world_transform(rock, _row_major(0.0, 0.0, -10000.0))
    h.far_set_rocks([{"instance": rock, "index": -1, "radius_mu": 1.0}])
    _look_down_minus_z()
    h.frame()
    assert h.far_debug_fade(rock) == 1.0
    h.far_clear()
    assert h.far_debug_fade(rock) == 0.0
    assert h.far_stats()["rocks"] == 0


def test_a_speck_band_rock_draws_a_speck(host):
    rock = h.create_instance(_rock_model())
    # Inside the speck band at any DPI: p = r*k/d with k = 0.866*H (H 64 or
    # 128); r=1, d=60 -> p ~0.9 or ~1.8 px, between p_min (0.25) and speck_hi.
    h.set_world_transform(rock, _row_major(0.0, 0.0, -60.0))
    h.far_set_rocks([{"instance": rock, "index": -1, "radius_mu": 1.0}])
    _look_down_minus_z()
    h.frame()
    s = h.far_stats()
    assert s["specks"] >= 1 and s["draw_calls"] >= 1
    assert s["rocks"] == 1


def test_an_active_source_walks_cells(host):
    h.far_set_sources([_source(table=[(0.0, 1.0), (226000.0, 1.0)])])
    h.far_set_frame("Vesuvi", (100000.0, 0.0, 0.0))
    _look_down_minus_z()
    h.frame()
    s = h.far_stats()
    assert s["sources"] == 1 and s["cells"] > 0
    assert s["cached_cells"] > 0
