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


def _view_dirs():
    # The bake's view layout (rock-blend: 64 octahedral views). The native
    # side derives the blend from the layout, so a lone direction is no
    # usable layout and draws no impostors.
    from engine.rocks import catalogue
    return [tuple(d) for d in catalogue.impostor_view_dirs()]


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
    assert set(h.far_stats()) == {"sources", "rocks", "impostors", "specks", "draw_calls",
                                  "near_cells", "near_small", "near_large",
                                  "near_ghosted", "near_meshes", "near_billboards",
                                  "near_fading", "mid_sprites", "mid_fading",
                                  "mid_tiles", "mid_cache_evictions",
                                  "speck_cells", "band_specks", "puffs"}


def test_far_set_dials_p_min_and_omitted_keys_reset():
    h.far_set_dials({"p_min": 0.5})
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


def test_an_active_belt_generates_no_rocks(host):
    """Rock-fields (2026-10-02): the belt generator is gone; a belt is a
    density source only."""
    h.far_set_sources([_source(table=[(0.0, 1.0), (226000.0, 1.0)])])
    h.far_set_frame("Vesuvi", (100000.0, 0.0, 0.0))
    _look_down_minus_z()
    h.frame()
    s = h.far_stats()
    assert s["sources"] == 1
    assert s["specks"] == 0 and s["impostors"] == 0


def test_a_catalogue_pushed_before_init_still_draws_impostors():
    """FarField keeps its catalogue across sessions, but each init() makes a
    fresh FarPass: the atlas paths must reach it too, or every impostor of a
    catalogue pushed with the host down silently never draws."""
    from engine.rocks import catalogue
    major = catalogue.pick("x", kind="major", family="silicate")
    h.far_set_catalogue(
        [{"albedo": major.impostor_albedo, "normal": major.impostor_normal,
          "avg_albedo": (0.4, 0.4, 0.4)}], _view_dirs())
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    try:
        h.init(64, 64, "test_far_catalogue")
    except RuntimeError as e:
        pytest.skip(f"no GL context: {e}")
    try:
        # A wide impostor band so the DPI-dependent framebuffer (64 or 128 px)
        # cannot push the rock out of it: r=1 at d=4 is ~14-28 px.
        h.far_set_dials({"imp_hi": 1000.0, "imp_lo": 1.0, "speck_hi": 0.9,
                         "speck_lo": 0.5})
        rock = h.create_instance(_rock_model())
        h.set_world_transform(rock, _row_major(0.0, 0.0, -4.0))
        h.far_set_rocks([{"instance": rock, "index": 0, "radius_mu": 1.0}])
        _look_down_minus_z()
        h.frame()
        s = h.far_stats()
        assert s["impostors"] >= 1 and s["draw_calls"] >= 1
    finally:
        h.shutdown()
        h.far_set_catalogue([], [])


def test_a_rock_whose_atlas_fails_to_load_keeps_its_mesh(host):
    """A flagged rock whose impostor atlas cannot be read must not vanish in
    the impostor band: the host learns of the failure that frame and the rock
    is treated as having no impostor -- whole mesh (fade 0), no impostor."""
    try:
        h.far_set_catalogue(
            [{"albedo": "/nonexistent/far_host_test/a0.png",
              "normal": "/nonexistent/far_host_test/n0.png",
              "avg_albedo": (0.4, 0.4, 0.4)}], _view_dirs())
        # The wide impostor band of the catalogue-before-init test: r=1 at
        # d=4 is ~14-28 px, inside it at either framebuffer height.
        h.far_set_dials({"imp_hi": 1000.0, "imp_lo": 1.0, "speck_hi": 0.9,
                         "speck_lo": 0.5})
        rock = h.create_instance(_rock_model())
        h.set_world_transform(rock, _row_major(0.0, 0.0, -4.0))
        h.far_set_rocks([{"instance": rock, "index": 0, "radius_mu": 1.0}])
        _look_down_minus_z()
        h.frame()
        assert h.far_debug_fade(rock) == 0.0
        assert h.far_stats()["impostors"] == 0
    finally:
        h.far_set_dials({})
        h.far_set_catalogue([], [])


def test_a_hidden_flagged_rock_draws_no_speck_and_keeps_fade_zero(host):
    rock = h.create_instance(_rock_model())
    # The speck-band placement of test_a_speck_band_rock_draws_a_speck.
    h.set_world_transform(rock, _row_major(0.0, 0.0, -60.0))
    h.far_set_rocks([{"instance": rock, "index": -1, "radius_mu": 1.0}])
    h.set_visible(rock, False)
    _look_down_minus_z()
    h.frame()
    assert h.far_stats()["specks"] == 0
    assert h.far_debug_fade(rock) == 0.0


# ── Tile-field sphere sources (added 2026-10-02) ─────────────────────────────


def test_a_source_without_the_sphere_keys_parses_as_today():
    h.far_clear()
    h.far_set_sources([_source()])
    h.far_set_frame("Vesuvi", (0.0, 0.0, 0.0))
    (s,) = h.far_debug_active_sources()
    assert s["shape"] == "disc"
    assert s["procedural"] is True and s["view_space"] is False
    h.far_clear()


def test_a_view_space_sphere_source_is_active_without_a_frame():
    h.far_clear()
    h.far_set_sources([_source(
        id=7, frame="", centre=(10.0, 20.0, 30.0), table=[], shape="sphere",
        procedural=False, view_space=True, sphere_radius_gu=1000.0,
        sphere_edge_frac=0.25)])
    h.far_set_frame(None, (0.0, 0.0, 0.0))
    (s,) = h.far_debug_active_sources()
    assert s["id"] == 7 and s["shape"] == "sphere"
    assert s["procedural"] is False and s["view_space"] is True
    assert s["centre"] == pytest.approx((10.0, 20.0, 30.0))
    assert s["sphere_radius_gu"] == 1000.0
    assert s["sphere_edge_frac"] == 0.25
    h.far_set_frame("Beol", (1.0, 2.0, 3.0))
    (s,) = h.far_debug_active_sources()
    assert s["centre"] == pytest.approx((11.0, 22.0, 33.0))
    h.far_clear()


def test_an_unknown_shape_is_rejected():
    with pytest.raises(ValueError):
        h.far_set_sources([_source(shape="cube")])


# ── Field noise (added 2026-10-02) ──────────────────────────────────────────


def test_a_source_without_the_noise_keys_has_no_noise():
    h.far_clear()
    h.far_set_sources([_source()])
    h.far_set_frame("Vesuvi", (0.0, 0.0, 0.0))
    (s,) = h.far_debug_active_sources()
    assert s["noise_scale_gu"] == 0.0 and s["noise_contrast"] == 0.0
    assert s["noise_octaves"] == 0
    h.far_clear()


def test_the_noise_keys_round_trip():
    h.far_clear()
    h.far_set_sources([_source(
        id=8, frame="", centre=(0.0, 0.0, 0.0), table=[], shape="sphere",
        procedural=False, view_space=True, sphere_radius_gu=1000.0,
        noise_scale_gu=250.0, noise_contrast=0.8, noise_octaves=3)])
    h.far_set_frame(None, (0.0, 0.0, 0.0))
    (s,) = h.far_debug_active_sources()
    assert s["noise_scale_gu"] == 250.0
    assert s["noise_contrast"] == pytest.approx(0.8)
    assert s["noise_octaves"] == 3
    h.far_clear()


def test_noise_contrast_is_clamped_to_zero_one_on_parse():
    """Rock-fields R1 (2026-10-02): m's contrast lives in [0, 1]."""
    for sent, kept in ((3.0, 1.0), (-0.5, 0.0), (0.4, 0.4)):
        h.far_clear()
        h.far_set_sources([_source(noise_scale_gu=4000.0, noise_contrast=sent,
                                   noise_octaves=3)])
        h.far_set_frame("Vesuvi", (0.0, 0.0, 0.0))
        (s,) = h.far_debug_active_sources()
        assert s["noise_contrast"] == pytest.approx(kept)
    h.far_clear()


# ── Rock fields near band dials (rock-fields plan Task 7) ────────────────────


def _near_sphere():
    return _source(id=12, frame="", centre=(0.0, 0.0, 0.0), table=[], shape="sphere",
                   procedural=False, view_space=True, sphere_radius_gu=2000.0,
                   sphere_edge_frac=0.0, populations=[])


def test_near_density_dials_reach_the_near_band(host):
    from engine import renderer
    from engine.rocks import far_tier
    far_tier.reset()
    far_tier._push_catalogue(renderer)   # the real catalogue, with LOD handles
    h.far_set_sources([_near_sphere()])
    h.far_set_frame(None, (0.0, 0.0, 0.0))
    _look_down_minus_z()
    h.far_set_dials({"near_small_density": 0.0})
    h.frame()
    s = h.far_stats()
    assert s["near_cells"] > 0 and s["near_small"] == 0 and s["near_large"] > 0
    h.far_set_dials({})   # omitted keys reset: small rocks come back
    h.frame()
    assert h.far_stats()["near_small"] > 0
    h.far_clear()
    h.far_set_catalogue([], [])
    far_tier.reset()


def test_a_tiny_near_cell_is_floored_and_the_span_capped(host):
    """Task 4 review: cell_gu is floored at 1 GU on parse and a class spans
    at most 33 cells per axis, so a huge range over tiny cells stays bounded."""
    import time
    h.far_set_sources([_near_sphere()])
    h.far_set_frame(None, (0.0, 0.0, 0.0))
    _look_down_minus_z()
    h.far_set_dials({"near_small_cell_gu": 1.0e-4, "near_small_billboard_gu": 1.0e6,
                     "near_large_cell_gu": 1.0e-4, "near_large_billboard_gu": 1.0e6,
                     "near_small_density": 1.0e-9, "near_large_density": 1.0e-9})
    t0 = time.monotonic()
    h.frame()
    assert time.monotonic() - t0 < 10.0
    assert 0 < h.far_stats()["near_cells"] <= 2 * 33 ** 3
    h.far_set_dials({})
    h.far_clear()
