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
