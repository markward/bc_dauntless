"""WarpEngineSubsystem FSM: SetWarpState is the SDK setter; TransitionToState
is the engine-driven one that must run a dewarp to completion (the SDK's
EffectScriptActions.WarpEnterSet fires it and never clears the state itself)."""
import pytest
from engine.appc.subsystems import WarpEngineSubsystem


def _warp():
    return WarpEngineSubsystem("Warp Engines")


def test_fresh_subsystem_is_not_warping():
    w = _warp()
    assert w.GetWarpState() == WarpEngineSubsystem.WES_NOT_WARPING
    assert w.IsWarping() is False


def test_set_warp_state_marks_warping():
    w = _warp()
    w.SetWarpState(WarpEngineSubsystem.WES_WARPING)
    assert w.GetWarpState() == WarpEngineSubsystem.WES_WARPING
    assert w.IsWarping() is True


def test_transition_to_dewarp_auto_completes_to_not_warping():
    # The SDK's WarpEnterSet path: SetWarpState(WARPING) then
    # TransitionToState(DEWARP_INITIATED) and nothing else. The engine must
    # land it back on NOT_WARPING, or the ship is stranded mid-warp forever.
    w = _warp()
    w.SetWarpEffectTime(3.0)
    w.SetWarpState(WarpEngineSubsystem.WES_WARPING)
    w.TransitionToState(WarpEngineSubsystem.WES_DEWARP_INITIATED)
    assert w.GetWarpState() == WarpEngineSubsystem.WES_DEWARP_INITIATED

    w.tick_transition(1.0)
    assert w.IsWarping() is True          # 2.0 s still to run

    w.tick_transition(2.5)                # past the 3.0 s effect time
    assert w.GetWarpState() == WarpEngineSubsystem.WES_NOT_WARPING
    assert w.IsWarping() is False


def test_transition_uses_default_when_effect_time_unset():
    w = _warp()                            # GetWarpEffectTime() == 0.0
    w.TransitionToState(WarpEngineSubsystem.WES_DEWARP_ENDING)
    w.tick_transition(WarpEngineSubsystem.DEFAULT_DEWARP_SECONDS - 0.1)
    assert w.IsWarping() is True
    w.tick_transition(0.2)
    assert w.GetWarpState() == WarpEngineSubsystem.WES_NOT_WARPING


def test_transition_to_outbound_state_does_not_auto_complete():
    # Outbound warp states are held until the engine explicitly clears them —
    # only the DEWARP_* states have a completion deadline.
    w = _warp()
    w.TransitionToState(WarpEngineSubsystem.WES_WARPING)
    w.tick_transition(1000.0)
    assert w.GetWarpState() == WarpEngineSubsystem.WES_WARPING


def test_tick_transition_is_a_noop_when_not_warping():
    w = _warp()
    w.tick_transition(5.0)
    assert w.GetWarpState() == WarpEngineSubsystem.WES_NOT_WARPING


def test_set_warp_state_not_warping_cancels_a_pending_transition():
    w = _warp()
    w.TransitionToState(WarpEngineSubsystem.WES_DEWARP_INITIATED)
    w.SetWarpState(WarpEngineSubsystem.WES_NOT_WARPING)
    w.tick_transition(0.0)
    assert w.GetWarpState() == WarpEngineSubsystem.WES_NOT_WARPING
    assert w.__dict__.get("_transition_remaining") is None


# --- warp-in placement + exit point -------------------------------------

def _ship_with_radius(radius):
    from engine.appc.ships import ShipClass
    s = ShipClass()
    sub = WarpEngineSubsystem("Warp Engines")
    s.SetWarpEngineSubsystem(sub)
    s.SetRadius(radius)
    return s, sub


def _placement(x, y, z):
    from engine.appc.placement import PlacementObject
    p = PlacementObject()
    p.SetTranslateXYZ(x, y, z)
    return p


def test_placement_round_trip():
    w = _warp()
    assert w.GetPlacement() is None
    p = _placement(1, 2, 3)
    w.SetPlacement(p)
    assert w.GetPlacement() is p
    w.SetPlacement(None)
    assert w.GetPlacement() is None


def test_exit_point_is_behind_the_placement():
    s, sub = _ship_with_radius(2.0)
    p = _placement(100, 0, 0)
    sub.SetPlacement(p)
    loc = sub.GetWarpExitLocation()
    assert (loc.x, loc.y, loc.z) == pytest.approx((100.0, -20.0, 0.0), abs=1e-5)
    rot, prot = sub.GetWarpExitRotation(), p.GetWorldRotation()
    for i in range(3):
        c, pc = rot.GetCol(i), prot.GetCol(i)
        assert (c.x, c.y, c.z) == pytest.approx((pc.x, pc.y, pc.z), abs=1e-5)


def test_exit_point_without_placement_is_the_ship():
    s, sub = _ship_with_radius(2.0)
    s.SetTranslateXYZ(5, 6, 7)
    loc = sub.GetWarpExitLocation()
    assert (loc.x, loc.y, loc.z) == pytest.approx((5.0, 6.0, 7.0), abs=1e-5)
    rot, srot = sub.GetWarpExitRotation(), s.GetWorldRotation()
    for i in range(3):
        c, sc = rot.GetCol(i), srot.GetCol(i)
        assert (c.x, c.y, c.z) == pytest.approx((sc.x, sc.y, sc.z), abs=1e-5)


def test_exit_methods_are_real_surface():
    from engine.core.ids import implements
    w = _warp()
    for n in ("SetPlacement", "GetPlacement", "GetWarpExitLocation",
              "GetWarpExitRotation"):
        assert implements(w, n)


def test_warp_in_radius_uses_seeder_when_zero():
    from engine.appc import warp_state
    s, _ = _ship_with_radius(0.0)
    warp_state.set_radius_seeder(lambda ship: ship.SetRadius(3.5))
    assert warp_state.warp_in_radius(s) == 3.5


def test_warp_in_radius_falls_back_to_dial():
    from engine.appc import warp_state
    s, _ = _ship_with_radius(0.0)
    assert warp_state.warp_in_radius(s) == 2.0
    warp_state.set_radius_seeder(lambda ship: 1 / 0)   # logged, not raised
    assert warp_state.warp_in_radius(s) == 2.0
