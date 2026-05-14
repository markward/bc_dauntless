"""TorpedoTube.Fire — discrete shot. Decrements _num_ready, stamps
_last_fire_time, auto-stops _firing.  Gated on (parent on AND _num_ready > 0).
"""
from engine.appc.subsystems import TorpedoTube, TorpedoSystem


def _loaded_tube(num_ready=1, max_ready=1):
    tube = TorpedoTube("Forward Torpedo 1")
    parent = TorpedoSystem("Torpedoes")
    parent.TurnOn()
    parent.AddChildSubsystem(tube)
    tube._max_ready = max_ready
    tube._num_ready = num_ready
    tube._reload_delay = 40.0
    return tube


def test_can_fire_true_when_loaded_and_on():
    tube = _loaded_tube()
    assert tube.CanFire() == 1


def test_can_fire_false_when_empty():
    tube = _loaded_tube(num_ready=0)
    assert tube.CanFire() == 0


def test_can_fire_false_when_parent_off():
    tube = _loaded_tube()
    tube.GetParentSubsystem().TurnOff()
    assert tube.CanFire() == 0


def test_fire_decrements_num_ready():
    tube = _loaded_tube(num_ready=1)
    tube.Fire(target=None, offset=None)
    assert tube.GetNumReady() == 0


def test_fire_records_target():
    tube = _loaded_tube()
    tube.Fire(target="enemy_ship", offset="hit_point")
    assert tube._target == "enemy_ship"
    assert tube._target_offset == "hit_point"


def test_fire_with_none_target_succeeds():
    tube = _loaded_tube()
    tube.Fire(target=None, offset=None)
    assert tube.GetNumReady() == 0


def test_fire_auto_stops_firing():
    """Torpedoes are discrete-shot — _firing flips False immediately after
    the launch.  WeaponSystem.IsFiring() derives from _currently_firing
    which stays populated until StopFiring."""
    tube = _loaded_tube()
    tube.Fire(target=None, offset=None)
    assert tube.IsFiring() == 0


def test_fire_stamps_last_fire_time():
    import math
    tube = _loaded_tube()
    assert tube.GetLastFireTime() == -math.inf
    tube.Fire(target=None, offset=None)
    assert tube.GetLastFireTime() > -math.inf


def test_fire_no_ops_when_empty():
    tube = _loaded_tube(num_ready=0)
    import math
    tube.Fire(target=None, offset=None)
    assert tube.GetNumReady() == 0  # no underflow
    assert tube.GetLastFireTime() == -math.inf  # no fire-time update


def test_fire_no_sfx_in_pr2a():
    """Torpedo SFX deferred to PR 2b (needs TorpedoAmmoType.GetLaunchSound).
    PR 2a Fire must not crash even with no SFX path wired."""
    tube = _loaded_tube()
    tube.Fire(target=None, offset=None)  # must not raise
    assert tube.GetNumReady() == 0
