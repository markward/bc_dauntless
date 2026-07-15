from engine.appc.projectiles import Torpedo
from engine.appc.math import TGPoint3


class FakeShip:
    def __init__(self, pos, vel=(0, 0, 0), dead=False, detectable=True):
        self._pos = TGPoint3(*pos); self._vel = TGPoint3(*vel)
        self._dead = dead; self.detectable = detectable
    def GetWorldLocation(self): return self._pos
    def GetVelocityTG(self): return self._vel
    def IsDead(self): return self._dead


def _torp(pos=(0, 0, 0), vel=(0, 10, 0), target=None):
    t = Torpedo()
    t._position = TGPoint3(*pos); t._velocity = TGPoint3(*vel)
    t._target_ship = target
    t.SetGuidanceLifetime(4.0); t.SetMaxAngularAccel(0.125)
    return t


def test_defaults_match_bc_ctor():
    t = Torpedo()
    assert t._ttl == 60.0
    assert t._guidance_lifetime == 4.0 and t._guidance_initial == 4.0
    assert t._max_angular_accel == 0.125


def test_lead_pursuit_steers_ahead_of_crossing_target():
    target = FakeShip(pos=(100, 100, 0), vel=(50, 0, 0))   # crossing +x
    t = _torp(target=target)
    from engine.appc import projectiles
    projectiles._guide(t, 0.016)
    # Pure pursuit would rotate toward (100,100); lead must rotate FURTHER
    # toward +x than the pure-pursuit bearing.
    import math
    pure = math.atan2(100, 100)
    got = math.atan2(t._velocity.x, t._velocity.y)
    assert got > 0                       # turned toward the target at all
    # With max_step = 0.125*0.016 the turn is budget-clamped; assert the
    # DESIRED direction by widening the budget:
    t2 = _torp(target=target); t2.SetMaxAngularAccel(1000.0)
    projectiles._guide(t2, 0.016)
    got2 = math.atan2(t2._velocity.x, t2._velocity.y)
    assert got2 > pure - 1e-6            # at least as far starboard as pure


def test_turn_budget_decays_linearly_to_zero():
    target = FakeShip(pos=(1000, 0, 0))
    early = _torp(target=target); early._age = 0.0
    late = _torp(target=target); late._age = 3.9
    from engine.appc import projectiles
    projectiles._guide(early, 0.1); projectiles._guide(late, 0.1)
    import math
    turn_early = abs(math.atan2(early._velocity.x, early._velocity.y))
    turn_late = abs(math.atan2(late._velocity.x, late._velocity.y))
    assert turn_early > turn_late > 0.0
    expected_late = (0.1 / 4.0) * 0.125 * 0.1      # remaining/initial × accel × dt
    assert abs(turn_late - expected_late) < 1e-6


def test_dead_target_goes_ballistic_no_cache():
    target = FakeShip(pos=(100, 0, 0), dead=True)
    t = _torp(target=target)
    before = (t._velocity.x, t._velocity.y, t._velocity.z)
    from engine.appc import projectiles
    projectiles._guide(t, 0.1)
    assert (t._velocity.x, t._velocity.y, t._velocity.z) == before


def test_cloaked_target_steers_to_frozen_last_seen(monkeypatch):
    from engine.appc import projectiles
    target = FakeShip(pos=(100, 100, 0))
    t = _torp(target=target)
    monkeypatch.setattr(projectiles, "_target_visible", lambda torp, tgt: True)
    projectiles._guide(t, 0.016)                    # caches (100,100,0)
    assert t._last_seen_target_pos is not None
    target._pos = TGPoint3(-500, 100, 0)            # moves while cloaked
    monkeypatch.setattr(projectiles, "_target_visible", lambda torp, tgt: False)
    t2_vel_before_x = t._velocity.x
    projectiles._guide(t, 0.016)
    assert t._velocity.x >= t2_vel_before_x         # still steering +x-ward


def test_speed_constant_under_guidance():
    target = FakeShip(pos=(100, 100, 0), vel=(50, 0, 0))
    t = _torp(target=target)
    from engine.appc import projectiles
    for _ in range(20):
        projectiles._guide(t, 0.05)
    assert abs(t._velocity.Length() - 10.0) < 1e-6
