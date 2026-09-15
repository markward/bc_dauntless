"""Manual Aim (BC "mouse pick fire", H key).

Spec: docs/superpowers/specs/2026-09-15-manual-aim-pick-fire-design.md
"""
import math

from engine.appc.math import TGPoint3


# ── Task 1: ShipClass target-offset state ────────────────────────────────────

def _ship_with_locked_subsystem():
    from engine.appc.ships import ShipClass
    from engine.appc.subsystems import ShipSubsystem
    ship = ShipClass()
    sub = ShipSubsystem("Warp Core")
    sub._position = TGPoint3(0.5, -2.0, 1.5)
    ship.SetTargetSubsystem(sub)
    return ship


def test_manual_offset_overrides_the_subsystem_offset_while_in_use():
    ship = _ship_with_locked_subsystem()
    ship.set_manual_target_offset(TGPoint3(3.0, 4.0, 5.0))

    assert ship.is_using_target_offset() is True
    o = ship.GetTargetOffsetTG()
    assert (o.x, o.y, o.z) == (3.0, 4.0, 5.0)


def test_get_target_offset_returns_a_copy_not_the_stored_point():
    from engine.appc.ships import ShipClass
    ship = ShipClass()
    ship.set_manual_target_offset(TGPoint3(1.0, 2.0, 3.0))
    o = ship.GetTargetOffsetTG()
    o.x = 99.0
    assert ship.GetTargetOffsetTG().x == 1.0


def test_use_target_offset_zero_reverts_to_the_locked_subsystem():
    """E3M1.FixTargeting: UseTargetOffsetTG(0) == 'fix the targeted
    location to match the targeted subsystem'."""
    ship = _ship_with_locked_subsystem()
    ship.set_manual_target_offset(TGPoint3(3.0, 4.0, 5.0))

    ship.UseTargetOffsetTG(0)

    assert ship.is_using_target_offset() is False
    o = ship.GetTargetOffsetTG()
    assert (o.x, o.y, o.z) == (0.5, -2.0, 1.5)


def test_use_target_offset_one_without_a_stored_offset_is_not_in_use():
    from engine.appc.ships import ShipClass
    ship = ShipClass()
    ship.UseTargetOffsetTG(1)
    assert ship.is_using_target_offset() is False
    o = ship.GetTargetOffsetTG()
    assert (o.x, o.y, o.z) == (0.0, 0.0, 0.0)


def test_changing_target_clears_the_manual_offset():
    """The offset is target-local; it cannot survive a retarget."""
    from engine.appc.ships import ShipClass
    ship = ShipClass()
    a = ShipClass()
    b = ShipClass()
    ship.SetTarget(a)
    ship.set_manual_target_offset(TGPoint3(1.0, 1.0, 1.0))

    ship.SetTarget(a)                       # same object: keeps it
    assert ship.is_using_target_offset() is True
    ship.SetTarget(b)                       # different object: clears
    assert ship.is_using_target_offset() is False
