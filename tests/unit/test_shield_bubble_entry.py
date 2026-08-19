"""The shield bubble is what a shot meets first, not the hull.

BC resolves a weapon impact against the shield ELLIPSOID before the hull:
``ShipClass::TestHit`` intersects the shot's segment with the bubble in
unit-sphere space and hands back a point on the ellipsoid whenever the struck
facing is live (stbc_reference ``spec/ShieldFacingDamage.md`` §2.3 steps 6-10).
``PhaserBank``'s tick then "sets the current length to the distance to that
point" (§12.2 step 4) — so the drawn beam stops at the bubble.

We only ever mesh-traced the HULL. Two visible consequences on a Galaxy, whose
bubble stands 236 NIF units (~1.34 GU, 37% of the ship's half-length) off the
hull on the long axis:

  * the beam was drawn punching through the bubble to the hull, with the shield
    flash floating behind its tip, and
  * the flash was centred on the direction of the HULL point rather than of the
    bubble ENTRY point. Those agree only for a shot arriving perpendicular to
    the surface and diverge for an oblique one.

Facing SELECTION still reads the hull point; moving it to the entry point is a
gameplay change and lands separately.
"""
import math

import pytest

from engine.appc import combat
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import HullSubsystem, ShieldSubsystem


SQRT3 = math.sqrt(3.0)


def _ship(half=(232.0, 322.0, 70.0), centre=(0.0, 0.0, 0.0), at=(0.0, 0.0, 0.0)):
    """A ship with a cached hull box, as host_loop._cache_shield_hull_box
    leaves it at spawn (world units at GetScale() == 1)."""
    s = ShipClass_Create("Target")
    s._hull = HullSubsystem("Hull")
    s._hull.SetMaxCondition(1000.0)
    ss = ShieldSubsystem("Shield Generator")
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        ss.SetMaxShields(f, 1000.0)
    s.SetShieldSubsystem(ss)
    s.SetTranslateXYZ(*at)
    s._shield_hull_box = (tuple(centre), tuple(half))
    return s


def _on_unit_sphere(ship, point):
    """|point| in the bubble's unit-sphere space — 1.0 exactly on the bubble."""
    (cx, cy, cz), (hx, hy, hz) = combat._hull_box_for(ship)
    bx, by, bz = combat._body_frame_delta(ship, point)
    return math.sqrt(((bx - cx) / (hx * SQRT3)) ** 2
                     + ((by - cy) / (hy * SQRT3)) ** 2
                     + ((bz - cz) / (hz * SQRT3)) ** 2)


def test_entry_point_lands_on_the_bubble_surface():
    ship = _ship()
    origin = TGPoint3(0.0, 5000.0, 0.0)          # dead ahead, firing aft
    entry = combat.shield_bubble_entry(ship, origin, TGPoint3(0, -1, 0), 10000.0)
    assert entry is not None
    assert _on_unit_sphere(ship, entry) == pytest.approx(1.0, abs=1e-3)


def test_entry_point_is_on_every_axis():
    ship = _ship()
    for axis in range(3):
        d = [0.0, 0.0, 0.0]
        d[axis] = -1.0
        o = [0.0, 0.0, 0.0]
        o[axis] = 5000.0
        entry = combat.shield_bubble_entry(
            ship, TGPoint3(*o), TGPoint3(*d), 10000.0)
        assert entry is not None, f"axis {axis}"
        assert _on_unit_sphere(ship, entry) == pytest.approx(1.0, abs=1e-3)


def test_entry_point_is_nearer_the_shooter_than_the_hull():
    """The whole point: the beam must stop short of the hull."""
    ship = _ship()
    origin = TGPoint3(0.0, 5000.0, 0.0)
    entry = combat.shield_bubble_entry(ship, origin, TGPoint3(0, -1, 0), 10000.0)
    hull_nose = TGPoint3(0.0, 322.0, 0.0)
    assert (origin.y - entry.y) < (origin.y - hull_nose.y)
    # ...and by the full sqrt(3) stand-off, not a rounding difference.
    assert entry.y == pytest.approx(322.0 * SQRT3, abs=1.0)


def test_oblique_shot_enters_somewhere_the_hull_point_does_not_predict():
    """An oblique shot's bubble entry and its hull impact sit in different
    directions from the bubble centre — which is why centring the splash on
    the hull point misaligns it."""
    ship = _ship()
    # Shallow shot passing low along the hull, well off the nose axis.
    origin = TGPoint3(600.0, 5000.0, -60.0)
    direction = TGPoint3(-0.15, -0.98, 0.02)
    n = math.sqrt(sum(c * c for c in (direction.x, direction.y, direction.z)))
    direction = TGPoint3(direction.x / n, direction.y / n, direction.z / n)

    entry = combat.shield_bubble_entry(ship, origin, direction, 10000.0)
    assert entry is not None

    def unit_dir(p):
        (cx, cy, cz), (hx, hy, hz) = combat._hull_box_for(ship)
        b = combat._body_frame_delta(ship, p)
        v = ((b[0] - cx) / (hx * SQRT3), (b[1] - cy) / (hy * SQRT3),
             (b[2] - cz) / (hz * SQRT3))
        m = math.sqrt(sum(c * c for c in v))
        return tuple(c / m for c in v)

    # A plausible hull impact for that shot, on the saucer's port edge.
    hull_point = TGPoint3(-232.0, 40.0, 0.0)
    a, b = unit_dir(entry), unit_dir(hull_point)
    cos = sum(a[i] * b[i] for i in range(3))
    assert math.degrees(math.acos(max(-1.0, min(1.0, cos)))) > 20.0


def test_ray_that_misses_returns_none():
    ship = _ship()
    entry = combat.shield_bubble_entry(
        ship, TGPoint3(0.0, 5000.0, 9000.0), TGPoint3(0, -1, 0), 10000.0)
    assert entry is None


def test_segment_too_short_to_reach_returns_none():
    ship = _ship()
    entry = combat.shield_bubble_entry(
        ship, TGPoint3(0.0, 5000.0, 0.0), TGPoint3(0, -1, 0), 100.0)
    assert entry is None


def test_origin_already_inside_the_bubble_returns_none():
    """BC runs the hull test first when the shooter is inside the bubble
    (§2.3 step 5), so there is no entry point to report."""
    ship = _ship()
    entry = combat.shield_bubble_entry(
        ship, TGPoint3(0.0, 10.0, 0.0), TGPoint3(0, -1, 0), 10000.0)
    assert entry is None


def test_no_cached_hull_box_returns_none():
    """Headless / not-yet-realized ships degrade to the hull path."""
    ship = _ship()
    del ship._shield_hull_box
    entry = combat.shield_bubble_entry(
        ship, TGPoint3(0.0, 5000.0, 0.0), TGPoint3(0, -1, 0), 10000.0)
    assert entry is None


def test_entry_point_tracks_the_ship_position():
    """The bubble rides the ship — an offset ship's entry point offsets with
    it, so nothing here is anchored in absolute world space."""
    ship = _ship(at=(1000.0, 2000.0, -500.0))
    entry = combat.shield_bubble_entry(
        ship, TGPoint3(1000.0, 7000.0, -500.0), TGPoint3(0, -1, 0), 10000.0)
    assert entry is not None
    assert entry.y == pytest.approx(2000.0 + 322.0 * SQRT3, abs=1.0)
    assert _on_unit_sphere(ship, entry) == pytest.approx(1.0, abs=1e-3)
