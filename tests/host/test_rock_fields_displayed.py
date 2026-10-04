"""Rock fields are VISIBLE on screen, band by band (rock-fields plan Task 14).

The displayed-value acceptance for the whole rock-fields stack: the REAL
`_dauntless_host`
draws real SDK content the production way -- Beol 4's sets built by its SDK
Initialize(), sources/catalogue/dials pushed by far_tier.reconcile_with,
lights from host_loop._aggregate_lights -- through the whole post chain, and
the DISPLAYED difference far-tier-on minus far-tier-off is measured.

Bands (spec docs/superpowers/specs/2026-10-02-rock-fields-design.md): near
streamed rocks (meshes, then billboards), mid collection sprites (nested
150/600/2400 GU tiles), and the puffs -- soft lit billboards placed by the
field density, fading in from puff_start_gu -- that carry a field's far look.

Rocks are discrete: inside a field the frame is mostly open space with
scattered rocks, so a frame MEAN would hide them. Those views count the
fraction of pixels the far tier changed by >= 10/255 instead, on a stride
grid (an unbiased estimate of the whole-frame fraction; read_pixel is one
glReadPixels per call).
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
STRIDE = 4                   # whole-frame grid step for the changed-pixel fraction
INSIDE_GU = 300.0            # engine/dev_missions/rock_fields_inside.py
OUTSIDE_GU = 6000.0          # the "Far Tier: Beol 4 field" view distance

CHANGED_LEVEL = 10           # /255, per channel max
CHANGED_FRAC = 0.005         # 0.5% of the frame


@pytest.fixture
def host():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    try:
        h.init(640, 600, "test_rock_fields_displayed")
    except RuntimeError as e:
        pytest.skip(f"no GL context: {e}")
    far_tier.reset()
    h.dust_set_enabled(False)
    # Rock-real Part 1 strip-back (2026-10-03): mid is off by default,
    # independent of far_set_enabled. This file's acceptance covers the
    # whole band-by-band stack, so it is on for its duration.
    h.rock_mid_set_enabled(True)
    try:
        yield h
    finally:
        far_tier.reset()
        h.far_clear()
        h.far_set_dials({})
        h.far_set_enabled(True)
        h.rock_mid_set_enabled(False)
        h.rock_puffs_set_enabled(True)
        h.dust_set_enabled(True)
        h.minors_set_player(None)
        h.shutdown()


# ── Scene ─────────────────────────────────────────────────────────────────────

def _unit(v):
    n = math.sqrt(sum(x * x for x in v))
    return tuple(x / n for x in v)


def _beol4():
    """Beol 4 through its SDK Initialize(), pushed through reconcile_with:
    (set, Player Start, field centre, field radius)."""
    _fresh_world()
    import Systems.Beol.Beol4 as beol4
    beol4.Initialize()
    pSet = beol4.GetSet()
    fields = [App.AsteroidField_Cast(o)
              for o in pSet.GetClassObjectList(App.CT_ASTEROID_FIELD)]
    far_tier.reconcile_with(h, pSet, {}, fields)
    field = pSet.GetObject("Asteroid Field 1")
    c = field.GetWorldLocation()
    start = pSet.GetObject("Player Start")
    return pSet, start, (c.x, c.y, c.z), float(field.GetFieldRadius())


def _start_loc(start):
    s = start.GetWorldLocation()
    return (s.x, s.y, s.z)


def _on_line(start, centre, dist):
    """The point `dist` GU from the field centre toward Player Start."""
    a = _unit(tuple(s - c for s, c in zip(_start_loc(start), centre)))
    return tuple(c + x * dist for c, x in zip(centre, a))


def _light_and_camera(pSet, player, eye, target):
    ambient, directionals = host_loop._aggregate_lights(pSet, player)
    h.set_lighting(tuple(ambient), [(tuple(d), tuple(c)) for d, c in directionals])
    h.set_camera(eye=tuple(eye), target=tuple(target), up=(0.0, 0.0, 1.0),
                 fov_y_rad=FOV_Y, near=1.0, far=1.0e7)


# ── Readback ──────────────────────────────────────────────────────────────────

def _centre_mean():
    fw, fh = h.framebuffer_size()
    cx, cy = fw // 2, fh // 2
    vals = []
    for dx in range(-PATCH, PATCH + 1, 2):
        for dy in range(-PATCH, PATCH + 1, 2):
            r, g, b, _ = h.read_pixel(cx + dx, cy + dy)
            vals.append((r + g + b) / 3.0)
    return sum(vals) / len(vals)


def _grid():
    fw, fh = h.framebuffer_size()
    return [h.read_pixel(x, y)[:3]
            for y in range(STRIDE // 2, fh, STRIDE)
            for x in range(STRIDE // 2, fw, STRIDE)]


def _frames(n=2):
    for _ in range(n):
        h.frame()


def _off_then_on(read):
    """read() with the far tier off, then on (stats taken with it on)."""
    h.far_set_enabled(False)
    _frames()
    off = read()
    h.far_set_enabled(True)
    _frames()
    on = read()
    return off, on, h.far_stats()


def _changed_fraction(off, on):
    changed = sum(1 for a, b in zip(off, on)
                  if max(abs(x - y) for x, y in zip(a, b)) >= CHANGED_LEVEL)
    return changed / float(len(off))


def _mean(px):
    return sum((r + g + b) / 3.0 for r, g, b in px) / float(len(px))


# ── Acceptance ────────────────────────────────────────────────────────────────

def test_field_visible_from_outside(host):
    """Beol 4 from 6,000 GU outside (the "Far Tier: Beol 4 field" view), on
    the Player Start -> centre line: the puffs carry the field. Rocks and
    puffs are discrete, so the bar is the changed-pixel share (>= 0.5% of
    the frame changed by >= 10/255), and the puffs drew. The mid band is
    off, so the puffs alone carry it."""
    h.rock_mid_set_enabled(False)
    h.rock_puffs_set_enabled(True)
    pSet, start, centre, _radius = _beol4()
    _light_and_camera(pSet, start, _on_line(start, centre, OUTSIDE_GU), centre)
    off, on, st = _off_then_on(_grid)
    frac = _changed_fraction(off, on)
    print(f"[rock fields] Beol 4 from {OUTSIDE_GU:.0f} GU: changed {100 * frac:.2f}% of "
          f"the frame, puffs {st['puffs']}")
    assert st["puffs"] > 0
    assert frac >= CHANGED_FRAC


def test_field_visible_from_player_start(host):
    """From Beol 4's Player Start (~2,079 GU from the centre of the 1,000 GU
    field) the MID band carries it."""
    pSet, start, centre, _radius = _beol4()
    _light_and_camera(pSet, start, _start_loc(start), centre)
    off, on, st = _off_then_on(_grid)
    frac = _changed_fraction(off, on)
    print(f"[rock fields] Beol 4 Player Start: changed {100 * frac:.2f}% of the frame "
          f"(>= {CHANGED_LEVEL}/255), mean off {_mean(off):.2f} on {_mean(on):.2f}, "
          f"mid_sprites {st['mid_sprites']} mid_tiles {st['mid_tiles']}")
    assert st["mid_sprites"] > 0
    assert frac >= CHANGED_FRAC


def _inside(pSet, start, centre, radius):
    """Task 13's mission pose: (radius - 300) GU from the centre toward
    Player Start, nose on the centre."""
    eye = _on_line(start, centre, radius - INSIDE_GU)
    _light_and_camera(pSet, start, eye, centre)
    return eye


def test_rocks_visible_from_inside(host):
    pSet, start, centre, radius = _beol4()
    _inside(pSet, start, centre, radius)
    off, on, st = _off_then_on(_grid)
    frac = _changed_fraction(off, on)
    print(f"[rock fields] Beol 4 inside ({INSIDE_GU:.0f} GU in): changed "
          f"{100 * frac:.2f}% of the frame, near_meshes {st['near_meshes']} "
          f"near_billboards {st['near_billboards']} mid_sprites {st['mid_sprites']}")
    assert st["near_meshes"] > 0
    assert st["near_billboards"] > 0
    assert frac >= CHANGED_FRAC


def test_no_mid_sprite_within_the_near_band(host):
    """The mid band never draws inside the near band's reach: the guard is
    decided at the drawn (jittered) sprite's distance, so no sprite centre
    is nearer than mid_in_lo_gu (final review 3)."""
    from engine.rocks import far_dials
    pSet, start, centre, radius = _beol4()
    eye = _inside(pSet, start, centre, radius)
    _frames()
    sprites = h.far_debug_mid_centres()
    assert sprites, "no mid sprites at the inside pose"
    # Render space IS view space here (no set_render_origin); the camera eye
    # is in it.
    nearest = min(math.dist(s["centre"], eye) for s in sprites)
    floor = far_dials.get("mid_in_lo_gu")
    print(f"[rock fields] inside: {len(sprites)} mid sprites, nearest {nearest:.1f} GU "
          f"(floor {floor:.1f})")
    assert nearest >= floor
