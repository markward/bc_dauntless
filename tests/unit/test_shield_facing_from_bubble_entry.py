"""Which shield facing a hit drains is decided from the BUBBLE ENTRY point.

BC's chooser is ``ShipClass::TestHit`` (0x005AE730, stbc_reference
``spec/ShieldFacingDamage.md`` §2.3). It runs at collision-detection time and
takes the dominant axis of the point where the shot's SEGMENT ENTERS the shield
ellipsoid — not of where the shot lands on the hull.

We already computed that entry point: ``combat.shield_bubble_entry`` is a real
segment/ellipsoid intersection mirroring §2.3 steps 4-6, and both weapon
families pass it into ``apply_hit`` as ``shield_point`` (host_loop.py:876 for
torpedoes, :997 for beams). It was being used only as the VFX anchor, while the
facing kept reading the hull impact.

The two points are ~2 GU apart on a Galaxy, because the bubble is sqrt(3)x the
hull. A shot crossing that gap obliquely can cross a facing boundary on the
way in. Sampling 400k shots at a Galaxy, the two inputs picked DIFFERENT
facings on 6.0% of them.

The rule itself was already correct and is unchanged — the axis->index table,
the y->z->x tie order and the normalisation all match the binary. Only the
input moves.
"""
import math

import pytest

from engine.appc.combat import apply_hit, _shield_face_from_hit_point
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass, ShipClass_Create
from engine.appc.subsystems import HullSubsystem, ShieldSubsystem

FRONT, REAR, TOP, BOTTOM, LEFT, RIGHT = 0, 1, 2, 3, 4, 5

# Real Galaxy hull AABB half-extents in the units combat works in — world
# units at GetScale() == 1, i.e. NIF x BC_MODEL_SCALE. Bubble semi-axes are
# these x sqrt(3): 4.02 / 5.58 / 1.22 GU.
GALAXY_HALF = (2.32, 3.22, 0.70)


def _galaxy_with_powered_shields(face_max=1000.0):
    ship = ShipClass_Create("Target")
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(20000.0)
    ship._hull = hull
    ss = ShieldSubsystem("Shield Generator")
    ss.SetMaxCondition(100.0)
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        ss.SetMaxShields(f, face_max)
    ship.SetShieldSubsystem(ss)
    ship._radius = 4.0
    # The cached hull box host_loop._cache_shield_hull_box installs at spawn.
    # Without it the chooser falls back to a raw-component compare and the
    # geometry below stops meaning anything.
    ship._shield_hull_box = ((0.0, 0.0, 0.0), GALAXY_HALF)
    ship.SetAlertLevel(ShipClass.YELLOW_ALERT)
    return ship


# A shot whose bubble entry and hull impact land on DIFFERENT facings, taken
# from the 6% divergent population. Verified against the chooser itself below,
# so the fixture cannot silently stop being divergent.
ENTRY_POINT = TGPoint3(0.65, -3.63, 0.90)     # -> TOP
IMPACT_POINT = TGPoint3(-0.74, -3.22, 0.22)   # -> REAR


def _drained(gen):
    """The set of facings that lost charge."""
    return {f for f in range(ShieldSubsystem.NUM_SHIELDS)
            if gen.GetCurrentShields(f) < 1000.0}


def test_the_fixture_really_is_a_divergent_shot():
    """Guard the guard: if these two points ever agree, every assertion below
    passes vacuously and proves nothing."""
    ship = _galaxy_with_powered_shields()
    assert _shield_face_from_hit_point(ship, ENTRY_POINT) == TOP
    assert _shield_face_from_hit_point(ship, IMPACT_POINT) == REAR


def test_the_facing_comes_from_the_bubble_entry_not_the_hull_impact():
    ship = _galaxy_with_powered_shields()
    gen = ship.GetShields()

    apply_hit(ship, 400.0, IMPACT_POINT, source=None, shield_point=ENTRY_POINT)

    assert _drained(gen) == {TOP}, (
        "expected the entry facing (TOP) to drain; drained "
        f"{_drained(gen)} instead"
    )
    assert gen.GetCurrentShields(TOP) == 600.0
    assert gen.GetCurrentShields(REAR) == 1000.0


def test_a_caller_with_no_ray_still_falls_back_to_the_hull_impact():
    """Collisions and splash damage carry no segment, so shield_point is None.
    BC runs the hull test first in that case (spec 2.3 step 5), and the hull
    point is all we have."""
    ship = _galaxy_with_powered_shields()
    gen = ship.GetShields()

    apply_hit(ship, 400.0, IMPACT_POINT, source=None, shield_point=None)

    assert _drained(gen) == {REAR}
    assert gen.GetCurrentShields(REAR) == 600.0


def test_a_head_on_shot_is_unaffected_because_both_points_agree():
    """The common case must not move. When the segment runs straight down a
    principal axis, entry and impact pick the same facing and the change is a
    no-op."""
    ship = _galaxy_with_powered_shields()
    gen = ship.GetShields()
    bow_entry = TGPoint3(0.0, 5.58, 0.0)    # on the bubble
    bow_impact = TGPoint3(0.0, 3.22, 0.0)   # on the hull, same direction

    apply_hit(ship, 400.0, bow_impact, source=None, shield_point=bow_entry)

    assert _drained(gen) == {FRONT}


def test_the_damage_still_lands_where_the_shot_hit_the_hull():
    """Only the FACING moves. Overflow to hull, subsystem attribution and the
    hit point itself are all still driven by the hull impact."""
    ship = _galaxy_with_powered_shields(face_max=100.0)
    gen = ship.GetShields()

    apply_hit(ship, 400.0, IMPACT_POINT, source=None, shield_point=ENTRY_POINT)

    assert gen.GetCurrentShields(TOP) == 0.0                 # entry facing emptied
    assert ship.GetHull().GetCondition() == 20000.0 - 300.0  # overflow reached hull
