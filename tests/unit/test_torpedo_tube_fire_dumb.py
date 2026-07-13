"""TorpedoTube.FireDumb + CalculateRoughDirection + WeaponSystem.StopFiringAtTarget.

SDK Preprocessors.py:454-458 — dumb-fire path picks torp tubes facing
the target by dot-product with CalculateRoughDirection() > 0."""
import pytest

from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass
from engine.appc.subsystems import TorpedoTube, PhaserSystem, TorpedoSystem


def test_fire_dumb_calls_fire():
    """FireDumb routes through the regular Fire path in Phase 1."""
    tube = TorpedoTube("Tube")
    tube.SetMaxCondition(100.0)  # not destroyed
    fired = []
    tube.Fire = lambda *a, **kw: fired.append((a, kw))
    tube.FireDumb(0, 1)
    assert len(fired) == 1


def test_calculate_rough_direction_is_world_space_when_attached():
    """Was: asserted model-forward for every tube. That WAS the dumb-fire bug --
    see tests/unit/test_torpedo_tube_direction.py for the real coverage."""
    ship = ShipClass()
    system = TorpedoSystem("Torpedoes")
    tube = TorpedoTube("Forward Torpedo 1")
    tube.SetDirection(TGPoint3(0.0, 1.0, 0.0))
    system.AddChildSubsystem(tube)
    ship._attach_subsystem(system)

    world = tube.CalculateRoughDirection()
    assert abs(world.y - 1.0) < 1e-6      # identity rotation -> body == world


def test_calculate_rough_direction_falls_back_to_y_axis_when_orphaned():
    """No parent ship → return a non-zero forward vector (don't crash)."""
    tube = TorpedoTube("Tube")
    direction = tube.CalculateRoughDirection()
    # Just don't crash and return a non-zero vector.
    assert direction is not None
    sqr = (direction.GetX() ** 2 + direction.GetY() ** 2 + direction.GetZ() ** 2)
    assert sqr > 0.0


def test_stop_firing_at_target_aliases_stop_firing():
    """SDK Preprocessors.py:274/469 — StopFiringAtTarget(pTarget) is a no-op
    in headless; aliases StopFiring().

    PhaserSystem.StopFiring resets _fire_held (the trigger-held flag) — we
    assert that path runs, confirming the alias is wired through."""
    p = PhaserSystem("P")
    p._fire_held = True  # simulate firing
    p.StopFiringAtTarget(None)
    assert p._fire_held is False
