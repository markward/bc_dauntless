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

import pytest

from engine.appc import projectiles
from engine.appc import weapon_subsystems as ws
from engine.appc.math import TGPoint3

from tests.helpers.torpedo_fixtures import system_with_tubes, LiveTarget


SKEW = 0.033   # audited .rdata constant, fixed sign, local frame


@pytest.fixture
def spawned(monkeypatch):
    """Every torpedo the launches register (at their SPAWN delivery)."""
    out = []
    real = projectiles.register

    def spy(torp, *a, **kw):
        out.append(torp)
        return real(torp, *a, **kw)
    monkeypatch.setattr(projectiles, "register", spy)
    return out


def _launch_speed():
    """The stock photon's launch speed (the fixture tubes' slot-0 script),
    as the launch cache holds it."""
    mod = ws._resolve_projectile_module("Tactical.Projectiles.PhotonTorpedo")
    return ws.tube_launch_params(mod)[1]


def _fire_and_capture(spawned, tube_direction, tube_right, ship_vel,
                      skew=False, target_at=(60.0, 400.0, 0.0)):
    """Build a ready tube on a ship (tests/helpers/torpedo_fixtures.py),
    author the tube's mount Direction/Right, set the ship's velocity, and
    fire it natively (fire control native only, M3: the kernel's launch,
    spawned at its session's end). A live target off to starboard, inside
    the +/-30 degree cone, proves the launch ignores target position.
    Returns the spawned Torpedo."""
    target = LiveTarget(*target_at)
    system, ship = system_with_tubes(1, target=target)
    tube = system.GetWeapon(0)
    tube.SetDirection(tube_direction)
    tube.SetRight(tube_right)
    tube.SetSkewFire(1 if skew else 0)
    ship.SetVelocity(ship_vel)
    before = len(spawned)
    assert tube.Fire(target) is True
    assert len(spawned) == before + 1
    return spawned[-1]


def test_targeted_launch_ignores_target_position(spawned):
    # Target off to starboard; tube points ship-forward.
    torp = _fire_and_capture(spawned, tube_direction=TGPoint3(0, 1, 0),
                             tube_right=TGPoint3(1, 0, 0),
                             ship_vel=TGPoint3(0, 0, 0))
    v = torp._velocity
    speed = v.Length()
    assert abs(v.y / speed - 1.0) < 1e-6      # straight out the tube
    assert abs(v.x) < 1e-6 and abs(v.z) < 1e-6


def test_velocity_inherits_ship_motion(spawned):
    torp = _fire_and_capture(spawned, tube_direction=TGPoint3(0, 1, 0),
                             tube_right=TGPoint3(1, 0, 0),
                             ship_vel=TGPoint3(3.0, 0, 0))
    assert abs(torp._velocity.x - 3.0) < 1e-6
    assert abs(torp._velocity.y - _launch_speed()) < 1e-6


def test_skew_perturbs_local_direction_fixed_sign(spawned):
    straight = _fire_and_capture(spawned, TGPoint3(0, 1, 0),
                                 TGPoint3(1, 0, 0), TGPoint3(0, 0, 0),
                                 skew=False)
    skewed = _fire_and_capture(spawned, TGPoint3(0, 1, 0), TGPoint3(1, 0, 0),
                               TGPoint3(0, 0, 0), skew=True)
    # +0.033 x Right -> positive x component, same speed.
    assert skewed._velocity.x > 0
    expected = math.atan2(SKEW, 1.0)
    got = math.atan2(skewed._velocity.x, skewed._velocity.y)
    assert abs(got - expected) < 1e-6
    assert abs(skewed._velocity.Length() - straight._velocity.Length()) < 1e-6


def test_target_lock_still_stamped_but_not_used_for_velocity(spawned):
    """Guidance (Task 9) still needs the target lock stamped -- this task
    only forbids USING it to steer the launch. Task 7 audited: "Fire stamps
    the homing state": the launch reads the tube's own `_target`, stamped
    by its targeted Fire."""
    torp = _fire_and_capture(spawned, tube_direction=TGPoint3(0, 1, 0),
                             tube_right=TGPoint3(1, 0, 0),
                             ship_vel=TGPoint3(0, 0, 0))
    target = torp._target_ship
    assert target is not None and target.GetName() == "Target"
    v = torp._velocity
    assert abs(v.x) < 1e-6 and abs(v.z) < 1e-6   # straight out regardless
