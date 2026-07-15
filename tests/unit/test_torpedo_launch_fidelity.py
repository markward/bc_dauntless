"""BC-faithful torpedo launch: straight out the tube's authored direction at
GetLaunchSpeed(), plus the firing ship's own velocity — the aim point never
steers the launch.  Audited §2.4.1: "the game never computes a ballistic
firing solution for the launch."

Uses the shared ship+tube fixture (tests/helpers/torpedo_fixtures.py) so the
tube is a REAL TorpedoTube under a REAL TorpedoSystem under a REAL ShipClass
(GetDirection/GetRight/IsSkewFire/GetVelocityTG/GetWorldRotation/GetTarget
all resolve through production code, not doubles) — only the projectile
module (mod.GetLaunchSpeed) is faked, so the test can pin an exact speed
without depending on PhotonTorpedo.py's authored 19.0.
"""
import math

from engine.appc.math import TGPoint3
from engine.appc.weapon_subsystems import _spawn_projectile

from tests.helpers.torpedo_fixtures import system_with_tubes, LiveTarget


SKEW = 0.033   # audited .rdata constant, fixed sign, local frame


class _FakeTorpedoModule:
    """Stand-in for a Tactical.Projectiles.* module — only what
    _spawn_projectile touches."""
    def __init__(self, launch_speed):
        self._launch_speed = launch_speed

    def Create(self, torp):
        pass

    def GetLaunchSpeed(self):
        return self._launch_speed

    def GetLaunchSound(self):
        return ""


def _fire_and_capture(tube_direction, tube_right, ship_vel, skew=False,
                      launch_speed=10.0):
    """Build a ready tube on a ship (tests/helpers/torpedo_fixtures.py),
    author the tube's mount Direction/Right, set the ship's velocity, and
    spawn a projectile via _spawn_projectile directly (bypassing the real
    hardpoint script so launch_speed is test-controlled).  A live target far
    off to starboard proves the launch ignores target position.
    Returns the spawned Torpedo."""
    target = LiveTarget(1000.0, 0.0, 0.0)
    system, ship = system_with_tubes(1, target=target)
    tube = system.GetWeapon(0)
    tube.SetDirection(tube_direction)
    tube.SetRight(tube_right)
    tube.SetSkewFire(1 if skew else 0)
    ship.SetVelocity(ship_vel)

    mod = _FakeTorpedoModule(launch_speed)
    return _spawn_projectile(tube, mod)


def test_targeted_launch_ignores_target_position():
    # Target far off to starboard; tube points ship-forward.
    torp = _fire_and_capture(tube_direction=TGPoint3(0, 1, 0),
                             tube_right=TGPoint3(1, 0, 0),
                             ship_vel=TGPoint3(0, 0, 0))
    v = torp._velocity
    speed = v.Length()
    assert abs(v.y / speed - 1.0) < 1e-6      # straight out the tube
    assert abs(v.x) < 1e-6 and abs(v.z) < 1e-6


def test_velocity_inherits_ship_motion():
    torp = _fire_and_capture(tube_direction=TGPoint3(0, 1, 0),
                             tube_right=TGPoint3(1, 0, 0),
                             ship_vel=TGPoint3(3.0, 0, 0), launch_speed=10.0)
    assert abs(torp._velocity.x - 3.0) < 1e-6
    assert abs(torp._velocity.y - 10.0) < 1e-6


def test_skew_perturbs_local_direction_fixed_sign():
    straight = _fire_and_capture(TGPoint3(0, 1, 0), TGPoint3(1, 0, 0),
                                 TGPoint3(0, 0, 0), skew=False)
    skewed = _fire_and_capture(TGPoint3(0, 1, 0), TGPoint3(1, 0, 0),
                               TGPoint3(0, 0, 0), skew=True)
    # +0.033 x Right -> positive x component, same speed.
    assert skewed._velocity.x > 0
    expected = math.atan2(SKEW, 1.0)
    got = math.atan2(skewed._velocity.x, skewed._velocity.y)
    assert abs(got - expected) < 1e-6
    assert abs(skewed._velocity.Length() - straight._velocity.Length()) < 1e-6


def test_target_lock_still_stamped_but_not_used_for_velocity():
    """Guidance (Task 9) still needs the target lock stamped — this task
    only forbids USING it to steer the launch."""
    target = LiveTarget(1000.0, 0.0, 0.0)
    system, ship = system_with_tubes(1, target=target)
    tube = system.GetWeapon(0)
    tube.SetDirection(TGPoint3(0, 1, 0))
    tube.SetRight(TGPoint3(1, 0, 0))
    ship.SetVelocity(TGPoint3(0, 0, 0))

    torp = _spawn_projectile(tube, _FakeTorpedoModule(10.0))
    assert torp._target_ship is target
