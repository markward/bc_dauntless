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


def _cloak_scene(target_x):
    """Firing ship with a REAL 2000 GU SensorSubsystem — so its cloak bubble is
    a flat 5 GU plus 1% of that, 25 GU — plus a fully cloaked target at
    (target_x, 0, 0).

    Real engine objects, not fakes: _target_visible swallows every exception and
    returns True, so a fake missing a method would make these tests pass for the
    wrong reason. Mirrors tests/unit/test_cloak_detection_contest.py::_observer.
    """
    from engine.appc.ships import ShipClass, ShipClass_Create
    from engine.appc.subsystems import CloakingSubsystem, SensorSubsystem
    src = ShipClass_Create("Galaxy")
    src.SetTranslateXYZ(0.0, 0.0, 0.0)
    sensors = SensorSubsystem("Sensors")
    sensors._max_condition = 100.0
    sensors._condition = 100.0
    sensors.SetBaseSensorRange(2000.0)
    src.SetSensorSubsystem(sensors)
    tgt = ShipClass()
    tgt.SetTranslateXYZ(float(target_x), 0.0, 0.0)
    tgt.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
    tgt.GetCloakingSubsystem().InstantCloak()
    return src, tgt


def _torp_with_stale_cache(src, tgt):
    """Torpedo fired by *src* at *tgt*, flying +y at 10 GU/s, with its last-seen
    cache seeded to a sentinel BEHIND it on -x.

    That sentinel is the discriminator. Steering toward the live target (+x)
    versus toward the sentinel (-x) separates "still homing" from "coasting on
    the frozen last-seen position" by the SIGN of velocity.x, which a boolean on
    _target_visible alone could not do. (Note the cloak path is not literally
    ballistic — true ballistic is the dead-target case, covered by
    test_dead_target_goes_ballistic_no_cache, which returns before any steering.)
    """
    t = _torp(target=tgt)
    t._source_ship = src
    t._last_seen_target_pos = TGPoint3(-999.0, -999.0, -999.0)
    return t


def test_torpedo_keeps_homing_when_target_cloaks_inside_the_bubble():
    """INTENTIONAL stage-4 gameplay change (ENHANCED_SENSOR_CONTEST, default on).

    Torpedo guidance consults sensor_detection.can_detect via _target_visible,
    and cloak is now a flat 5 GU plus a percentage of effective sensor range
    rather than an absolute. At 15 GU the cloaked target is inside the firing
    ship's 25 GU bubble, so the torpedo keeps tracking it: cloaking to shake a
    torpedo no longer works at knife range. This is a deliberate divergence
    from BC — if it starts failing, ask "was the change reverted?", not "what
    broke?".
    """
    from engine.appc import projectiles
    src, tgt = _cloak_scene(15.0)
    t = _torp_with_stale_cache(src, tgt)

    assert projectiles._target_visible(t, tgt) is True
    projectiles._guide(t, 0.016)

    # Cache refreshed to the LIVE position, and steering +x toward it.
    assert (t._last_seen_target_pos.x,
            t._last_seen_target_pos.y,
            t._last_seen_target_pos.z) == (15.0, 0.0, 0.0)
    assert t._velocity.x > 0.0


def test_torpedo_coasts_on_last_seen_when_target_cloaks_outside_the_bubble():
    """The bubble boundary still holds: at 45 GU (well outside the 25 GU
    bubble) a cloaked target is invisible, the cache stays frozen, and the
    torpedo steers to the stale last-seen point on -x. Stock BC's
    shake-the-torpedo trick is intact at any real engagement distance."""
    from engine.appc import projectiles
    src, tgt = _cloak_scene(45.0)
    t = _torp_with_stale_cache(src, tgt)

    assert projectiles._target_visible(t, tgt) is False
    projectiles._guide(t, 0.016)

    assert (t._last_seen_target_pos.x,
            t._last_seen_target_pos.y,
            t._last_seen_target_pos.z) == (-999.0, -999.0, -999.0)
    assert t._velocity.x < 0.0


def test_torpedo_cloak_cache_is_absolute_with_the_contest_off(monkeypatch):
    """STOCK-BC BEHAVIOUR, held under ENHANCED_SENSOR_CONTEST = False: any
    cloak freezes the cache regardless of range, even at the 15 GU that the
    contest makes trackable."""
    import engine.appc.sensor_detection as sd
    monkeypatch.setattr(sd, "ENHANCED_SENSOR_CONTEST", False)
    from engine.appc import projectiles
    src, tgt = _cloak_scene(15.0)
    t = _torp_with_stale_cache(src, tgt)

    assert projectiles._target_visible(t, tgt) is False
    projectiles._guide(t, 0.016)

    assert (t._last_seen_target_pos.x,
            t._last_seen_target_pos.y,
            t._last_seen_target_pos.z) == (-999.0, -999.0, -999.0)
    assert t._velocity.x < 0.0


def test_speed_constant_under_guidance():
    target = FakeShip(pos=(100, 100, 0), vel=(50, 0, 0))
    t = _torp(target=target)
    from engine.appc import projectiles
    for _ in range(20):
        projectiles._guide(t, 0.05)
    assert abs(t._velocity.Length() - 10.0) < 1e-6
