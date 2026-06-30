"""Unit tests for FloatRangeWatcher — the missing watcher abstraction that
several SDK Condition classes depend on (Conditions/ConditionPowerBelow.py,
ConditionPulseReady.py, ConditionSingleShieldBelow.py).

Contract (from the SDK conditions):
    pEvent = App.TGFloatEvent_Create()
    pEvent.SetEventType(ET); pEvent.SetSource(pSys); pEvent.SetDestination(handler)
    idCheck = pWatcher.AddRangeCheck(threshold, App.FloatRangeWatcher.FRW_BOTH, pEvent)
    ...
    pWatcher.RemoveRangeCheck(idCheck)
    fNow = pWatcher.GetWatchedVariable()

When the watched value crosses a registered threshold in the watched
direction, the watcher broadcasts pEvent (carrying the new value via
SetFloat) through g_kEventManager to pEvent's destination, which is a
TGPythonInstanceWrapper whose registered method then runs.
"""
import App
from engine.appc.events import (
    TGEventManager, TGPythonInstanceWrapper,
)
from engine.appc.float_range_watcher import FloatRangeWatcher


def _make_event(event_type, source, dest):
    pEvent = App.TGFloatEvent_Create()
    pEvent.SetEventType(event_type)
    pEvent.SetSource(source)
    pEvent.SetDestination(dest)
    return pEvent


def _spy_wrapper():
    """Return (wrapper, captured) where captured collects every float value
    delivered to the wrapper's "OnCross" method via the event bus."""
    captured = []

    class Spy:
        def OnCross(self, pEvent):
            captured.append(pEvent.GetFloat())

    spy = Spy()
    wrapper = TGPythonInstanceWrapper()
    wrapper.SetPyWrapper(spy)
    wrapper.AddPythonMethodHandlerForInstance(777, "OnCross")
    return wrapper, captured


def test_frw_below_fires_only_on_downward_crossing():
    mgr = TGEventManager()
    watcher = FloatRangeWatcher(0.5, event_manager=mgr)
    wrapper, captured = _spy_wrapper()
    pEvent = _make_event(777, watcher, wrapper)
    watcher.AddRangeCheck(0.5, FloatRangeWatcher.FRW_BELOW, pEvent)

    watcher._update(0.4)   # 0.5 -> 0.4 : crosses downward, fires
    assert captured == [0.4]

    watcher._update(0.6)   # 0.4 -> 0.6 : crosses upward, FRW_BELOW ignores
    assert captured == [0.4]


def test_frw_above_fires_only_on_upward_crossing():
    mgr = TGEventManager()
    watcher = FloatRangeWatcher(0.4, event_manager=mgr)
    wrapper, captured = _spy_wrapper()
    pEvent = _make_event(777, watcher, wrapper)
    watcher.AddRangeCheck(0.5, FloatRangeWatcher.FRW_ABOVE, pEvent)

    watcher._update(0.3)   # 0.4 -> 0.3 : still below, no upward crossing
    assert captured == []

    watcher._update(0.6)   # 0.3 -> 0.6 : crosses upward, fires
    assert captured == [0.6]

    watcher._update(0.2)   # 0.6 -> 0.2 : downward, FRW_ABOVE ignores
    assert captured == [0.6]


def test_frw_both_fires_on_either_crossing():
    mgr = TGEventManager()
    watcher = FloatRangeWatcher(0.6, event_manager=mgr)
    wrapper, captured = _spy_wrapper()
    pEvent = _make_event(777, watcher, wrapper)
    watcher.AddRangeCheck(0.5, FloatRangeWatcher.FRW_BOTH, pEvent)

    watcher._update(0.4)   # 0.6 -> 0.4 : downward crossing, fires
    watcher._update(0.7)   # 0.4 -> 0.7 : upward crossing, fires
    assert captured == [0.4, 0.7]


def test_no_fire_when_value_moves_without_crossing():
    mgr = TGEventManager()
    watcher = FloatRangeWatcher(0.9, event_manager=mgr)
    wrapper, captured = _spy_wrapper()
    pEvent = _make_event(777, watcher, wrapper)
    watcher.AddRangeCheck(0.5, FloatRangeWatcher.FRW_BOTH, pEvent)

    watcher._update(0.8)   # 0.9 -> 0.8 : both above threshold, no crossing
    watcher._update(0.7)   # 0.8 -> 0.7 : still above, no crossing
    assert captured == []


def test_get_watched_variable_returns_latest_value():
    watcher = FloatRangeWatcher(0.1, event_manager=TGEventManager())
    assert watcher.GetWatchedVariable() == 0.1
    watcher._update(0.42)
    assert watcher.GetWatchedVariable() == 0.42


def test_remove_range_check_stops_further_events():
    mgr = TGEventManager()
    watcher = FloatRangeWatcher(0.6, event_manager=mgr)
    wrapper, captured = _spy_wrapper()
    pEvent = _make_event(777, watcher, wrapper)
    idCheck = watcher.AddRangeCheck(0.5, FloatRangeWatcher.FRW_BOTH, pEvent)

    watcher._update(0.4)   # downward crossing, fires
    assert captured == [0.4]

    watcher.RemoveRangeCheck(idCheck)
    watcher._update(0.7)   # would cross upward, but check removed
    assert captured == [0.4]


def test_app_exposes_float_range_watcher_constant():
    assert hasattr(App, "FloatRangeWatcher")
    assert isinstance(App.FloatRangeWatcher.FRW_BOTH, int)
    assert App.FloatRangeWatcher.FRW_BELOW != App.FloatRangeWatcher.FRW_ABOVE


def test_power_subsystem_cast_matches_and_rejects():
    from engine.appc.subsystems import PowerSubsystem
    pPower = PowerSubsystem.__new__(PowerSubsystem)
    assert App.PowerSubsystem_Cast(pPower) is pPower
    assert App.PowerSubsystem_Cast(object()) is None


def test_shield_and_pulse_casts_match_and_reject():
    from engine.appc.subsystems import ShieldSubsystem, PulseWeapon
    pShield = ShieldSubsystem.__new__(ShieldSubsystem)
    assert App.ShieldSubsystem_Cast(pShield) is pShield
    assert App.ShieldSubsystem_Cast(object()) is None

    pPulse = PulseWeapon.__new__(PulseWeapon)
    assert App.PulseWeapon_Cast(pPulse) is pPulse
    assert App.PulseWeapon_Cast(object()) is None


def test_et_power_fraction_changed_defined_and_unique():
    assert isinstance(App.ET_POWER_FRACTION_CHANGED, int)
    # Must not collide with neighbouring bridge-interaction event ids.
    assert App.ET_POWER_FRACTION_CHANGED != App.ET_CONTACT_STARFLEET
