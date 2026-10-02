"""The far-tier haze is VISIBLE on screen (ruling R16, 2026-10-02).

The acceptance test that was missing: the haze was once calibrated on alpha
with light 1 and showed as ~1-4/255 in game. Here the REAL `_dauntless_host`
draws the real SDK content the production way -- the system's sets built by
the SDK, sources pushed by far_tier.reconcile_with, lights from
host_loop._aggregate_lights (the key re-aimed from the star) -- through the
whole post chain (resolve, filmic on by default), and the displayed
difference far-tier-on minus far-tier-off, mean of the channels over a patch
at the view centre, must be at least 20/255 (calibrated target 25/255 over
black; here the clear colour sits behind it, so the expected difference is
~25 - alpha x background ~= 22).
"""
import math
import os

import pytest

h = pytest.importorskip("_dauntless_host")

import App
from engine import host_loop
from engine.rocks import far_tier
from tests.helpers.fresh_world import _fresh_world

FOV_Y = math.radians(30.0)   # settings.json fov_deg 30, vertical
PATCH = 10                   # +-10 px around the centre, step 2 (averages the grain)


@pytest.fixture
def host():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    try:
        h.init(640, 600, "test_far_haze_displayed")
    except RuntimeError as e:
        pytest.skip(f"no GL context: {e}")
    far_tier.reset()
    h.dust_set_enabled(False)
    try:
        yield h
    finally:
        far_tier.reset()
        h.far_clear()
        h.far_set_enabled(True)
        h.dust_set_enabled(True)
        h.shutdown()


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
    h.far_set_enabled(False)
    h.frame()
    h.frame()
    off = _centre_mean()
    h.far_set_enabled(True)
    h.frame()
    h.frame()
    on = _centre_mean()
    return on, off


def _light_and_camera(pSet, player, eye, target):
    ambient, directionals = host_loop._aggregate_lights(pSet, player)
    h.set_lighting(tuple(ambient), [(tuple(d), tuple(c)) for d, c in directionals])
    h.set_camera(eye=tuple(eye), target=tuple(target), up=(0.0, 0.0, 1.0),
                 fov_y_rad=FOV_Y, near=1.0, far=1.0e7)


def test_beol4_tile_field_haze_shows_from_player_start(host):
    _fresh_world()
    import Systems.Beol.Beol4 as beol4
    beol4.Initialize()
    pSet = beol4.GetSet()
    far_tier.reconcile_with(h, pSet, {}, _fields(pSet))
    (src,) = h.far_debug_active_sources()
    assert src["shape"] == "sphere" and src["brightness"] > 1.0
    assert src["noise_contrast"] > 0.0 and src["noise_octaves"] > 0   # measured WITH noise
    start = pSet.GetObject("Player Start")
    loc = start.GetWorldLocation()
    _light_and_camera(pSet, start, (loc.x, loc.y, loc.z),
                      (797.714355, 977.248474, 1268.854858))
    on, off = _on_minus_off()
    print(f"[far haze] Beol 4 Player Start: off {off:.1f} on {on:.1f} "
          f"diff {on - off:.1f}/255")
    assert on - off >= 20.0


def test_vesuvi_belt_haze_shows_from_mid_band(host):
    """Vesuvi mid-band (system rho 278,000 GU, z 0) looking tangentially
    along the plane, lit as a player there in Vesuvi6 (E1M2's region)."""
    _fresh_world()
    import Systems.Vesuvi.Vesuvi6 as v6
    v6.Initialize()
    pSet = v6.GetSet()
    from engine.systems import resolve
    ax, ay, az = resolve.anchor_of("Vesuvi6")
    eye = (278000.0 - ax, 0.0 - ay, 0.0 - az)
    probe = App.PlacementObject_Create("far haze probe", pSet.GetName(), None)
    probe.SetTranslateXYZ(*eye)
    probe.UpdateNodeOnly()
    far_tier.reconcile_with(h, pSet, {}, _fields(pSet))
    belts = [s for s in h.far_debug_active_sources() if s["shape"] == "disc"]
    assert len(belts) == 1 and belts[0]["brightness"] > 1.0
    _light_and_camera(pSet, probe, eye, (eye[0], eye[1] + 1000.0, eye[2]))
    on, off = _on_minus_off()
    print(f"[far haze] Vesuvi mid-band: off {off:.1f} on {on:.1f} "
          f"diff {on - off:.1f}/255")
    assert on - off >= 20.0
