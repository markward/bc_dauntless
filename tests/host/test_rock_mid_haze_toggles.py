"""Rock mid band / haze dev toggles (rock-real Part 1 strip-back, 2026-10-03).

Mark, live 2026-10-03: "strip this back to the near field / real asteroids
only for a moment; we will build it up from there." Two toggles independent
of far_set_enabled (the master switch, which still disables everything when
off): rock_mid_set_enabled gates the mid band's build and every draw of it
(solid and fading); rock_haze_set_enabled gates the belt haze draw. Both
default OFF.

The mid assertions reuse test_rock_mid_host.py's synthetic sphere source (no
SDK mission needed); the haze assertions reuse test_far_haze_displayed.py's
real Beol 4 pose, because the haze's displayed contribution needs a strong,
already-calibrated source to measure against noise.
"""
import math
import os

import pytest

h = pytest.importorskip("_dauntless_host")

import App
from engine import host_loop
from engine.rocks import far_dials, far_tier
from tests.helpers.fresh_world import _fresh_world

FOV_Y = math.radians(30.0)
PATCH = 10


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


def _fields(pSet):
    return [App.AsteroidField_Cast(o)
            for o in pSet.GetClassObjectList(App.CT_ASTEROID_FIELD)]


def _centre_mean():
    fw, fh = h.framebuffer_size()
    cx, cy = fw // 2, fh // 2
    vals = []
    for dx in range(-PATCH, PATCH + 1, 2):
        for dy in range(-PATCH, PATCH + 1, 2):
            r, g, b, _ = h.read_pixel(cx + dx, cy + dy)
            vals.append((r + g + b) / 3.0)
    return sum(vals) / len(vals)


def _on_minus_off():
    """far-tier-on minus far-tier-off, as test_far_haze_displayed.py does it
    -- at a haze-only view the only source of a difference is the haze."""
    h.far_set_enabled(False)
    h.frame()
    h.frame()
    off = _centre_mean()
    h.far_set_enabled(True)
    h.frame()
    h.frame()
    on = _centre_mean()
    return on, off


def _beol4_haze_pose():
    """The Player-Start -> field-centre line at the haze hand-off (as
    test_beol4_tile_field_haze_shows_from_the_handoff does it): the haze
    owns the whole field from here."""
    _fresh_world()
    import Systems.Beol.Beol4 as beol4
    beol4.Initialize()
    pSet = beol4.GetSet()
    far_tier.reconcile_with(h, pSet, {}, _fields(pSet))
    (src,) = h.far_debug_active_sources()
    start = pSet.GetObject("Player Start")
    loc = start.GetWorldLocation()
    centre = (797.714355, 977.248474, 1268.854858)
    dist = far_dials.get("haze_handoff_gu") + src["sphere_radius_gu"]
    v = (loc.x - centre[0], loc.y - centre[1], loc.z - centre[2])
    n = math.sqrt(sum(x * x for x in v))
    eye = tuple(centre[i] + v[i] / n * dist for i in range(3))
    ambient, directionals = host_loop._aggregate_lights(pSet, start)
    h.set_lighting(tuple(ambient), [(tuple(d), tuple(c)) for d, c in directionals])
    h.set_camera(eye=eye, target=centre, up=(0.0, 0.0, 1.0),
                 fov_y_rad=FOV_Y, near=1.0, far=1.0e7)


@pytest.fixture
def host():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    try:
        h.init(640, 600, "test_rock_mid_haze_toggles")
    except RuntimeError as e:
        pytest.skip(f"no GL context: {e}")
    far_tier.reset()
    h.dust_set_enabled(False)
    h.rock_puffs_set_enabled(False)   # spike/rock-specks: these measure the haze alone
    try:
        yield h
    finally:
        far_tier.reset()
        h.far_clear()
        h.far_set_dials({})
        h.far_set_enabled(True)
        h.rock_mid_set_enabled(False)
        h.rock_haze_set_enabled(False)
        h.dust_set_enabled(True)
        h.minors_set_player(None)
        h.shutdown()


def test_mid_and_haze_default_off(host):
    assert h.rock_mid_enabled() is False
    assert h.rock_haze_enabled() is False   # spike/rock-specks: puffs replace it


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


# ── Haze ──────────────────────────────────────────────────────────────────

def test_haze_off_contributes_nothing_at_a_haze_only_view(host):
    """rock_haze off: toggling far_set_enabled on/off makes no displayed
    difference at a view where the haze would otherwise be the only
    contributor (as test_far_haze_displayed.py measures it on)."""
    _beol4_haze_pose()
    h.rock_haze_set_enabled(False)
    on, off = _on_minus_off()
    print(f"[rock haze off] on {on:.1f} off {off:.1f} diff {on - off:.1f}/255")
    assert abs(on - off) < 2.0


def test_haze_on_restores_the_contribution(host):
    _beol4_haze_pose()
    h.rock_haze_set_enabled(True)
    on, off = _on_minus_off()
    print(f"[rock haze on] on {on:.1f} off {off:.1f} diff {on - off:.1f}/255")
    assert on - off >= 20.0
