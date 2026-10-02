"""The far dials Mark turns with / L O actually change the picture.

Mark, 2026-10-02: "ARE YOU SURE the numbers I am playing with are actually
changing the render?" This drives the dials through the SAME path the keys
use (dev_dial_groups.push on the active "far" group -> far_dials._step ->
far_tier.on_dials_changed), runs the per-frame reconcile the host loop runs,
renders with the real `_dauntless_host`, and measures the displayed pixels.
"""
import math
import os

import pytest

h = pytest.importorskip("_dauntless_host")

import App
from engine import dev_dial_groups, host_loop
from engine.rocks import far_dials, far_tier
from tests.helpers.fresh_world import _fresh_world

FOV_Y = math.radians(30.0)
PATCH = 10
CENTRE = (797.714355, 977.248474, 1268.854858)   # Beol 4 Asteroid Field 1
FIELD_RADIUS_GU = 1000.0                          # its sphere source's radius


@pytest.fixture
def host():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    try:
        h.init(640, 600, "test_far_dials_reach_the_render")
    except RuntimeError as e:
        pytest.skip(f"no GL context: {e}")
    far_tier.reset()
    far_dials.reset()
    dev_dial_groups.reset()
    h.dust_set_enabled(False)
    try:
        yield h
    finally:
        far_tier.reset()
        far_dials.reset()
        dev_dial_groups.reset()
        h.far_clear()
        h.far_set_enabled(True)
        h.dust_set_enabled(True)
        h.shutdown()


def _centre_mean():
    fw, fh = h.framebuffer_size()
    cx, cy = fw // 2, fh // 2
    vals = []
    for dx in range(-PATCH, PATCH + 1, 2):
        for dy in range(-PATCH, PATCH + 1, 2):
            r, g, b, _ = h.read_pixel(cx + dx, cy + dy)
            vals.append((r + g + b) / 3.0)
    return sum(vals) / len(vals)


def _beol4():
    _fresh_world()
    import Systems.Beol.Beol4 as beol4
    beol4.Initialize()
    pSet = beol4.GetSet()
    fields = [App.AsteroidField_Cast(o)
              for o in pSet.GetClassObjectList(App.CT_ASTEROID_FIELD)]
    start = pSet.GetObject("Player Start")
    loc = start.GetWorldLocation()
    ambient, directionals = host_loop._aggregate_lights(pSet, start)
    h.set_lighting(tuple(ambient), [(tuple(d), tuple(c)) for d, c in directionals])
    # Rock-fields Task 12: the haze starts at the mid band's hand-off, so from
    # Player Start (2,079 GU from the 1,000 GU field) it is correctly ~0. View
    # the field from its Player Start line with its near surface at
    # haze_handoff_gu, where the haze owns all of it (as
    # test_far_haze_displayed.py does).
    dist = far_dials.get("haze_handoff_gu") + FIELD_RADIUS_GU
    v = (loc.x - CENTRE[0], loc.y - CENTRE[1], loc.z - CENTRE[2])
    n = math.sqrt(sum(x * x for x in v))
    eye = tuple(CENTRE[i] + v[i] / n * dist for i in range(3))
    h.set_camera(eye=eye, target=CENTRE, up=(0.0, 0.0, 1.0),
                 fov_y_rad=FOV_Y, near=1.0, far=1.0e7)
    return pSet, fields


def _render(pSet, fields):
    far_tier.reconcile_with(h, pSet, {}, fields)   # what the host loop runs each frame
    h.frame()
    h.frame()
    return _centre_mean()


def _press(dial, direction, times):
    """Exactly what / and L / O do once the far group is active."""
    while dev_dial_groups.active() != "far":
        dev_dial_groups.cycle_active()
    while dev_dial_groups.selected() != dial:
        dev_dial_groups.cycle_dial()
    for _ in range(times):
        dev_dial_groups.push(direction)


def _haze(pSet, fields):
    h.far_set_enabled(False)
    off = _render(pSet, fields)
    h.far_set_enabled(True)
    return _render(pSet, fields) - off


def test_tile_haze_brightness_keys_change_the_displayed_haze(host):
    pSet, fields = _beol4()
    far_dials.register()
    base = _haze(pSet, fields)
    _press("tile_haze_brightness", +1, 4)          # x1.25^4 = x2.44
    brighter = _haze(pSet, fields)
    src = h.far_debug_active_sources()[0]
    print(f"[far dials] brightness {far_dials.get('tile_haze_brightness'):.2f} "
          f"(native {src['brightness']:.2f}): haze {base:.1f} -> {brighter:.1f}/255")
    assert src["brightness"] == pytest.approx(far_dials.get("tile_haze_brightness"), rel=1e-5)
    assert base > 10.0, "a real haze to scale"
    assert brighter > base * 1.8


def test_tile_haze_gain_keys_change_the_displayed_haze(host):
    pSet, fields = _beol4()
    far_dials.register()
    base = _haze(pSet, fields)
    _press("tile_haze_gain", -1, 6)                # x1.25^-6 = x0.26
    thinner = _haze(pSet, fields)
    print(f"[far dials] gain {far_dials.get('tile_haze_gain'):.0f}: "
          f"haze {base:.1f} -> {thinner:.1f}/255")
    assert base > 10.0, "a real haze to thin"
    assert thinner < base * 0.5
