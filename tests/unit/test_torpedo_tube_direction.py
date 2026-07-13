"""CalculateRoughDirection is WORLD space; GetDirection stays MODEL space.

Evidence that CalculateRoughDirection is world-space:
  AI/Preprocessors.py:447-456          dots it against a world-space target delta
  AI/PlainAI/IntelligentCircleObject.py:204,234
                                       converts the result world->model explicitly
                                       ("Change it to model space")

Evidence that GetDirection is model-space:
  Conditions/ConditionTorpsReady.py:128  dots it against a model-space vector
"""
import math

from engine.appc.math import TGPoint3, TGMatrix3
from engine.appc.ships import ShipClass
from engine.appc.subsystems import TorpedoSystem, TorpedoTube


def _tube_on_ship(local_dir: TGPoint3, yaw_rad: float) -> tuple:
    """A tube pointing `local_dir` in body space, on a ship yawed by `yaw_rad`."""
    ship = ShipClass()
    rot = TGMatrix3()
    rot.MakeZRotation(yaw_rad)          # yaw about body-up (col 2)
    ship.SetMatrixRotation(rot)

    system = TorpedoSystem("Torpedoes")
    tube = TorpedoTube("Aft Torpedo 1")
    tube.SetDirection(local_dir)
    system.AddChildSubsystem(tube)
    ship._attach_subsystem(system)      # sets _parent_ship on the SYSTEM only
    return ship, tube


def test_aft_tube_points_backwards_in_world_space_when_ship_is_unrotated():
    """The core dumb-fire bug: an AFT tube must NOT read as ship-forward."""
    _ship, tube = _tube_on_ship(TGPoint3(0.0, -1.0, 0.0), 0.0)
    world = tube.CalculateRoughDirection()
    assert world.y < -0.99          # points aft, i.e. -Y in world

    # AI/Preprocessors.py:456 gates dumb-fire on this dot being > 0.
    target_ahead = TGPoint3(0.0, 1.0, 0.0)
    dot = world.x * target_ahead.x + world.y * target_ahead.y + world.z * target_ahead.z
    assert dot < 0.0, "aft tube must not dumb-fire at a target dead ahead"


def test_forward_tube_rotates_with_the_ship():
    """World space means the ship's rotation is applied."""
    _ship, tube = _tube_on_ship(TGPoint3(0.0, 1.0, 0.0), math.radians(90.0))
    world = tube.CalculateRoughDirection()
    # Body +Y yawed 90 deg about body-up lands on world -X (column-vector,
    # right-handed; see CLAUDE.md).
    assert abs(world.x - (-1.0)) < 1e-6
    assert abs(world.y) < 1e-6


def test_get_direction_stays_model_space():
    """GetDirection must NOT be rotated -- ConditionTorpsReady.py:128 dots it
    against a model-space restriction vector."""
    _ship, tube = _tube_on_ship(TGPoint3(0.0, -1.0, 0.0), math.radians(90.0))
    local = tube.GetDirection()
    assert abs(local.y - (-1.0)) < 1e-6   # unchanged by the ship's rotation
    assert abs(local.x) < 1e-6


def test_orphaned_tube_falls_back_to_its_body_direction():
    """No parent ship -- return the un-rotated mount direction, not a crash."""
    tube = TorpedoTube("Orphan")
    tube.SetDirection(TGPoint3(0.0, 1.0, 0.0))
    world = tube.CalculateRoughDirection()
    assert abs(world.y - 1.0) < 1e-6
