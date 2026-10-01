"""Minor rocks host wiring (minor-rocks plan Task 8).

The native MinorField is reachable two ways: the global ``minors_*`` bindings
that ``frame()`` steps and draws, and a standalone ``MinorField`` class that
headless probes drive directly (no GL, no init()).
"""
import os
import math


def _identity16():
    return [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]


def _persp16(fovy=math.radians(60), aspect=16 / 9, n=0.1, f=1e6):
    t = 1.0 / math.tan(fovy / 2)
    return [t / aspect, 0, 0, 0, 0, t, 0, 0, 0, 0, (f + n) / (n - f), -1,
            0, 0, 2 * f * n / (n - f), 0]


def _desc(**kw):
    d = dict(id=1, anchor="point", instance=None, point=(0.0, 0.0, -20.0),
             velocity=(0.0, 0.0, 0.0), t0=0.0, shell_inner=0.0, shell_outer=2.0,
             falloff=0.0, count=50, r_min=0.3, r_max=0.3, size_exponent=2.5,
             family=0, seed=1, orbit_rate=0.0, fade_in=False, debris=[])
    d.update(kw)
    return d


def test_standalone_minorfield_steps_without_init():
    import _dauntless_host as h
    f = h.MinorField()
    f.set_fragments(0, [(1, 2, 57.142857)])
    f.add_cloud(_desc(), 0.0)
    f.step(0.0, _identity16(), _persp16(), 1080.0)
    s = f.stats()
    assert s["clouds"] == 1 and s["minors"] == 50 and s["drawn"] == 50


def test_set_fragments_takes_an_optional_albedo_fourth_element():
    # Far tier: (lod0, lod1, bound_mu, (r, g, b)) carries the speck albedo;
    # the 3-tuple form keeps working, mixed in one list.
    import _dauntless_host as h
    f = h.MinorField()
    f.set_fragments(0, [(1, 2, 57.142857, (0.3, 0.25, 0.2)), (3, 4, 57.142857)])
    f.add_cloud(_desc(), 0.0)
    f.step(0.0, _identity16(), _persp16(), 1080.0)
    assert f.stats()["drawn"] == 50


def test_dials_defaults_match_python_defaults():
    import _dauntless_host as h
    from engine.rocks import minor_dials as md
    native = h.MinorField().dials()
    for k in md.NATIVE_KEYS:
        assert native[k] == md.DEFAULTS[k], k


def test_set_dials_round_trips_and_omitted_keys_reset():
    import _dauntless_host as h
    f = h.MinorField()
    f.set_dials({"shove_min_gups": 0.7, "max_shoves_per_frame": 3})
    d = f.dials()
    assert d["shove_min_gups"] == 0.7 and d["max_shoves_per_frame"] == 3
    f.set_dials({})
    assert f.dials()["shove_min_gups"] == 0.3


def test_contacts_come_back_as_dicts():
    import _dauntless_host as h
    f = h.MinorField()
    f.set_fragments(0, [(1, 2, 57.142857)])
    f.add_cloud(_desc(count=1, shell_outer=0.0, r_min=0.2, r_max=0.2), 0.0)
    def player(y):
        w = [0.01, 0, 0, 0, 0, 0.01, 0, 0, 0, 0, 0.01, 0, 0.0, y, -20.0, 1.0]
        return {"world": w, "center": (0, 0, 0), "half": (50, 100, 30)}
    f.step(0.0, _identity16(), _persp16(), 1080.0, player=player(-5.0))
    f.step(0.1, _identity16(), _persp16(), 1080.0, player=player(0.0))
    c = f.drain_contacts()
    assert len(c) == 1 and set(c[0]) == {"point", "radius", "rel_speed"}


def test_instance_anchor_reads_the_anchors_dict():
    import _dauntless_host as h
    f = h.MinorField()
    f.set_fragments(0, [(1, 2, 57.142857)])
    iid = h.InstanceId()
    f.add_cloud(_desc(anchor="instance", instance=iid), 0.0)
    f.step(0.0, _identity16(), _persp16(), 1080.0)
    assert f.stats()["drawn"] == 0          # no anchor supplied: skipped
    f.step(0.1, _identity16(), _persp16(), 1080.0, anchors={0: (0.0, 0.0, -20.0)})
    assert f.stats()["drawn"] == 50


def test_global_minors_bindings_before_init_are_silent():
    import _dauntless_host as h
    h.minors_clear()
    h.minors_set_enabled(True)
    assert h.minors_drain_contacts() == []


def _load_fragment(h):
    from engine.rocks import catalogue
    rock = catalogue.pick("x", kind="fragment", family="silicate")
    h0 = h.load_model(rock.lod_paths[0], [], None, decals=None, scale=1.0)
    h1 = h.load_model(rock.lod_paths[1], [], None, decals=None, scale=1.0)
    return h0, h1, rock.bound_radius_m / 1.75


def _look_down_minus_z(h):
    h.set_camera(eye=(0.0, 0.0, 0.0), target=(0.0, 0.0, -1.0),
                 up=(0.0, 1.0, 0.0), fov_y_rad=1.0472, near=0.1, far=1.0e6)


def test_frame_with_a_cloud_draws_it():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host as h
    h.init(64, 64, "test_minors_frame")
    try:
        h0, h1, bound_mu = _load_fragment(h)
        h.minors_set_fragments(0, [(h0, h1, bound_mu)])
        # DPI-independent geometry: h.init(64, 64) asks for a 64x64 WINDOW,
        # but the actual FRAMEBUFFER (what minors_step's pixel-radius cull
        # uses) is DPI-scaled -- 64px on a non-Retina display, 128px on a
        # Retina one. The _desc() default (point z=-20, r=0.3) sits at
        # ~0.83 px on a 64px framebuffer, under min_pixel_radius (1.5), so
        # the cloud was invisible whenever the OS happened to hand back an
        # unscaled framebuffer. A near, large cloud (z=-5, r=1.0, tight
        # shell so no minor's individual z offset can undo the margin)
        # reads ~9-14 px even at 64px -- comfortably above the 1.5px floor
        # at HALF that framebuffer size too, so the assertion still fails
        # if drawing is genuinely broken, independent of display DPI.
        h.minors_add_cloud(_desc(point=(0.0, 0.0, -5.0), shell_outer=1.0,
                                 r_min=1.0, r_max=1.0))
        _look_down_minus_z(h)
        h.damage_decals_tick(1.0)
        h.frame()
        s = h.minors_stats()
        assert s["drawn"] > 0 and s["draw_calls"] >= 1
    finally:
        h.shutdown()


def test_disabled_minors_neither_step_nor_draw():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host as h
    h.init(64, 64, "test_minors_disabled")
    try:
        h0, h1, bound_mu = _load_fragment(h)
        h.minors_set_fragments(0, [(h0, h1, bound_mu)])
        h.minors_add_cloud(_desc())
        h.minors_set_enabled(False)
        assert h.minors_enabled() is False
        _look_down_minus_z(h)
        h.frame()
        s = h.minors_stats()
        assert s["drawn"] == 0 and s["draw_calls"] == 0
    finally:
        h.shutdown()


def _translate_row_major(x, y, z, s=1.0):
    return [s, 0, 0, x, 0, s, 0, y, 0, 0, s, z, 0, 0, 0, 1.0]


def test_frame_player_sweeping_through_a_minor_makes_a_contact():
    """The global path builds the player's box from its model AABB."""
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host as h
    h.init(64, 64, "test_minors_contact")
    try:
        h0, h1, bound_mu = _load_fragment(h)
        h.minors_set_fragments(0, [(h0, h1, bound_mu)])
        h.minors_add_cloud(_desc(count=1, shell_outer=0.0, r_min=0.2, r_max=0.2))
        ship = h.create_instance(h0)           # any model: its AABB is the box
        h.minors_set_player(ship)
        _look_down_minus_z(h)
        h.set_world_transform(ship, _translate_row_major(0.0, -6.0, -20.0, 0.01))
        h.damage_decals_tick(0.0)
        h.frame()
        h.set_world_transform(ship, _translate_row_major(0.0, 0.0, -20.0, 0.01))
        h.damage_decals_tick(0.1)
        h.frame()
        c = h.minors_drain_contacts()
        assert len(c) == 1 and set(c[0]) == {"point", "radius", "rel_speed"}
    finally:
        h.shutdown()


def test_set_player_none_forgets_the_previous_pose():
    """A new player must not be swept from the old player's pose."""
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host as h
    h.init(64, 64, "test_minors_player_reset")
    try:
        h0, h1, bound_mu = _load_fragment(h)
        h.minors_set_fragments(0, [(h0, h1, bound_mu)])
        h.minors_add_cloud(_desc(count=1, shell_outer=0.0, r_min=0.2, r_max=0.2))
        ship = h.create_instance(h0)
        h.minors_set_player(ship)
        _look_down_minus_z(h)
        h.set_world_transform(ship, _translate_row_major(0.0, -6.0, -20.0, 0.01))
        h.damage_decals_tick(0.0)
        h.frame()
        h.minors_set_player(None)
        h.minors_set_player(ship)
        h.set_world_transform(ship, _translate_row_major(0.0, 6.0, -20.0, 0.01))
        h.damage_decals_tick(0.1)
        h.frame()
        assert h.minors_drain_contacts() == []
    finally:
        h.shutdown()


def test_bridge_view_draws_minors_into_the_viewscreen():
    """In bridge view the only space render is the viewscreen RTT: minors must
    be binned against THAT camera and drawn there."""
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host as h
    h.init(64, 64, "test_minors_viewscreen")
    try:
        h0, h1, bound_mu = _load_fragment(h)
        h.minors_set_fragments(0, [(h0, h1, bound_mu)])
        h.minors_add_cloud(_desc(point=(0.0, 0.0, 20.0)))   # behind g_camera
        _look_down_minus_z(h)
        h.set_viewscreen_scene_source(eye=(0.0, 0.0, 0.0), target=(0.0, 0.0, 1.0),
                                      up=(0.0, 1.0, 0.0), fov_y_rad=1.0472,
                                      near=0.1, far=1.0e6)
        h.bridge_pass_set_enabled(True)
        h.set_viewscreen_enabled(True)
        h.damage_decals_tick(1.0)
        h.frame()
        s = h.minors_stats()
        assert s["draw_calls"] >= 1 and s["drawn"] > 0
    finally:
        h.clear_viewscreen_scene_source()
        h.shutdown()


def test_detach_accepts_none_debris():
    import _dauntless_host as h
    f = h.MinorField()
    f.add_cloud(_desc(anchor="instance", instance=h.InstanceId()), 0.0)
    f.detach(1, (0.0, 0.0, -20.0), (0.0, 0.0, 0.0), 0.0, None)
    h.minors_add_cloud(_desc(anchor="instance", instance=h.InstanceId()))
    h.minors_detach(1, (0.0, 0.0, -20.0), (0.0, 0.0, 0.0), 0.0, None)
    h.minors_clear()
