"""Warp-in dewarp drive (warp-in spec 6.1, "Dewarp drive" / "During the slide"
/ "Timing").

TransitionToState(WES_DEWARP_INITIATED) with a placement set slides the ship
from its warp exit point onto the placement over 2.0 s of GAME time: velocity
held at zero, heading held at the placement's, and every weapon on it held
silent until it lands. Advanced by warp_state.tick_warp_states, which
GameLoop.tick runs, so the host and the headless harness drive it alike.
"""
import math

import App
import pytest

from engine.appc import ship_motion, warp_state
from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.objects import PhysicsObjectClass
from engine.appc.placement import PlacementObject
from engine.appc.sets import SetClass_Create
from engine.appc.ships import ShipClass
from engine.appc.subsystems import PhaserBank, PhaserSystem, WarpEngineSubsystem

W = WarpEngineSubsystem
DT = 1.0 / 60.0


@pytest.fixture(autouse=True)
def _isolate():
    App.g_kSetManager._sets.clear()
    warp_state.reset()
    yield
    App.g_kSetManager._sets.clear()
    warp_state.reset()


def _bank(name):
    b = PhaserBank(name)
    b._max_charge = 5.0
    b._charge_level = 5.0
    b._min_firing_charge = 3.0
    b._max_damage = 1.0
    b._max_damage_distance = 1000.0
    b._max_condition = 100.0
    b._condition = 100.0
    b._disabled_percentage = 0.25
    return b


def _phasers():
    sys_ = PhaserSystem("Phasers")
    sys_._max_condition = 100.0
    sys_._condition = 100.0
    sys_._disabled_percentage = 0.75
    sys_.TurnOn()
    for i in range(4):
        sys_.AddChildSubsystem(_bank("Bank%d" % i))
    return sys_


def _tilted():
    m = TGMatrix3()
    m.MakeZRotation(0.7)
    return m


def _arrival():
    """A ship in a set, radius 2, phasers fitted, facing somewhere other than
    the placement; placement at (100, 0, 0) with identity rotation."""
    pSet = SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "S")
    s = ShipClass()
    sub = WarpEngineSubsystem("Warp Engines")
    s.SetWarpEngineSubsystem(sub)
    s.SetPhaserSystem(_phasers())
    s.SetRadius(2.0)
    pSet.AddObjectToSet(s, "npc")
    s.SetTranslateXYZ(-500.0, 40.0, 7.0)
    s.SetMatrixRotation(_tilted())
    p = PlacementObject()
    p.SetTranslateXYZ(100.0, 0.0, 0.0)
    return pSet, s, sub, p


def _start(s, sub, p):
    sub.SetPlacement(p)
    sub.SetWarpState(W.WES_WARPING)
    sub.TransitionToState(W.WES_DEWARP_INITIATED)


def _loc(s):
    l = s.GetWorldLocation()
    return (l.x, l.y, l.z)


def _assert_rot(rot, expected):
    for i in range(3):
        c, e = rot.GetCol(i), expected.GetCol(i)
        assert (c.x, c.y, c.z) == pytest.approx((e.x, e.y, e.z), abs=1e-5)


def _target(pSet):
    class _T:
        def GetWorldLocation(self):
            return TGPoint3(100.0, 100.0, 0.0)

        def IsDead(self):
            return False

        def GetContainingSet(self):
            return pSet
    return _T()


def test_initiate_with_placement_starts_drive_at_exit_point():
    _, s, sub, p = _arrival()
    s.SetVelocity(TGPoint3(3.0, 4.0, 5.0))
    _start(s, sub, p)
    assert _loc(s) == pytest.approx((100.0, -20.0, 0.0), abs=1e-5)
    _assert_rot(s.GetWorldRotation(), p.GetWorldRotation())
    v = s.GetVelocityTG()
    assert (v.x, v.y, v.z) == (0.0, 0.0, 0.0)
    assert sub.is_dewarp_driving() is True
    assert warp_state.is_arriving(s) is True


def test_drive_lands_exactly_on_placement_after_2s():
    _, s, sub, p = _arrival()
    _start(s, sub, p)
    for _ in range(120):
        warp_state.tick_warp_states(DT)
    assert _loc(s) == pytest.approx((100.0, 0.0, 0.0), abs=1e-4)
    v = s.GetVelocityTG()
    assert (v.x, v.y, v.z) == (0.0, 0.0, 0.0)
    _assert_rot(s.GetWorldRotation(), p.GetWorldRotation())
    assert sub.is_dewarp_driving() is False
    assert warp_state.is_arriving(s) is False
    assert sub.GetPlacement() is None


def test_drive_is_monotonic():
    _, s, sub, p = _arrival()
    _start(s, sub, p)

    def dist():
        x, y, z = _loc(s)
        return math.sqrt((x - 100.0) ** 2 + y * y + z * z)

    last = dist()
    moved = False
    for _ in range(130):
        warp_state.tick_warp_states(DT)
        d = dist()
        assert d <= last + 1e-9
        moved = moved or d < last
        last = d
    assert moved


def test_later_stage_calls_do_not_restart_drive():
    _, s, sub, p = _arrival()
    _start(s, sub, p)
    for _ in range(90):                       # 1.5 s
        warp_state.tick_warp_states(DT)
    before = _loc(s)
    sub.TransitionToState(W.WES_DEWARP_ENDING)
    assert _loc(s) == before                  # no snap back to the exit point
    assert sub.is_dewarp_driving() is True
    for _ in range(30):                       # to 2.0 s
        warp_state.tick_warp_states(DT)
    assert _loc(s) == pytest.approx((100.0, 0.0, 0.0), abs=1e-4)
    assert sub.is_dewarp_driving() is False


def test_ai_setpoints_cannot_turn_or_move_during_drive():
    _, s, sub, p = _arrival()
    _start(s, sub, p)
    for _ in range(30):
        warp_state.tick_warp_states(DT)
    s.SetTargetAngularVelocityDirect(TGPoint3(0.0, 0.0, 2.0))
    s._current_angular_velocity = TGPoint3(0.0, 0.0, 2.0)
    s.SetSpeed(5.0, TGPoint3(0.0, 1.0, 0.0), PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    before = _loc(s)
    for _ in range(5):
        ship_motion.tick_all_ship_motion(DT)
    assert _loc(s) == before
    _assert_rot(s.GetWorldRotation(), p.GetWorldRotation())
    x, y, z = _loc(s)
    assert x == pytest.approx(100.0) and z == pytest.approx(0.0)
    assert -20.0 < y < 0.0
    # The drive itself also holds the heading against a stale spin.
    warp_state.tick_warp_states(DT)
    _assert_rot(s.GetWorldRotation(), p.GetWorldRotation())
    w = s._current_angular_velocity
    assert (w.x, w.y, w.z) == (0.0, 0.0, 0.0)


def test_fire_held_during_drive_then_released():
    pSet, s, sub, p = _arrival()
    target = _target(pSet)
    sys_ = s.GetPhaserSystem()
    _start(s, sub, p)
    sys_.StartFiring(target=target)
    assert sys_._fire_held is False
    assert all(sys_.GetWeapon(i).IsFiring() == 0 for i in range(4))

    for _ in range(120):
        warp_state.tick_warp_states(DT)
    sys_.StartFiring(target=target)
    assert any(sys_.GetWeapon(i).IsFiring() == 1 for i in range(4))


def test_fire_dumb_is_a_noop_during_drive():
    from engine.appc.weapon_subsystems import Weapon

    calls = []

    class _Rec(Weapon):
        def Fire(self, target=None, offset=None):
            calls.append(1)

    _, s, sub, p = _arrival()
    w = _Rec("Rec")
    s.GetPhaserSystem().AddChildSubsystem(w)
    _start(s, sub, p)
    w.FireDumb(0, 1)
    assert calls == []
    for _ in range(120):
        warp_state.tick_warp_states(DT)
    w.FireDumb(0, 1)
    assert calls == [1]


def test_drive_start_silences_weapons():
    pSet, s, sub, p = _arrival()
    s.SetTranslateXYZ(100.0, -20.0, 0.0)
    sys_ = s.GetPhaserSystem()
    sys_.StartFiring(target=_target(pSet))
    assert any(sys_.GetWeapon(i).IsFiring() == 1 for i in range(4))
    _start(s, sub, p)
    assert sys_._fire_held is False
    assert all(sys_.GetWeapon(i).IsFiring() == 0 for i in range(4))


def test_dewarp_drive_releases_a_dead_ship():
    _, s, sub, p = _arrival()
    _start(s, sub, p)
    for _ in range(30):
        warp_state.tick_warp_states(DT)
    s.SetDead(True)
    before = _loc(s)
    warp_state.tick_warp_states(DT)
    assert _loc(s) == before
    assert sub.is_dewarp_driving() is False
    assert warp_state.is_arriving(s) is False


def test_dewarp_drive_frozen_by_zero_dt():
    _, s, sub, p = _arrival()
    _start(s, sub, p)
    for _ in range(30):
        warp_state.tick_warp_states(DT)
    before = _loc(s)
    for _ in range(10):
        warp_state.tick_warp_states(0.0)
    assert _loc(s) == before
    assert sub.is_dewarp_driving() is True


def test_no_placement_keeps_old_behaviour():
    _, s, sub, _p = _arrival()
    sub.SetWarpState(W.WES_WARPING)
    sub.TransitionToState(W.WES_DEWARP_INITIATED)
    assert _loc(s) == (-500.0, 40.0, 7.0)
    assert sub.is_dewarp_driving() is False
    assert warp_state.is_arriving(s) is False
    warp_state.tick_warp_states(1.0)
    assert sub.GetWarpState() == W.WES_DEWARP_INITIATED
    warp_state.tick_warp_states(1.0)
    assert sub.GetWarpState() == W.WES_NOT_WARPING
    assert _loc(s) == (-500.0, 40.0, 7.0)


def test_gameloop_ticks_warp_states():
    from engine.core.loop import GameLoop
    _, s, sub, p = _arrival()
    _start(s, sub, p)
    loop = GameLoop()
    for _ in range(120):
        loop.tick()
    assert _loc(s) == pytest.approx((100.0, 0.0, 0.0), abs=1e-4)
    assert sub.is_dewarp_driving() is False
    assert sub.GetWarpState() == W.WES_NOT_WARPING
