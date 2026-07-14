"""ConditionSystemBelow / ConditionSingleShieldBelow drive their status off a
FloatRangeWatcher event they build themselves and stamp with a fixed ET.

Those two ET constants were undefined, so App.__getattr__ handed back a fresh
_NamedStub per access (hashed by id()) — the handler registered in the
condition's __init__ could never match the event the watcher later fired, and
the two most-used conditions in the AI (31 + 12 SDK uses) never updated.
"""
import App


def test_watcher_event_types_are_stable_distinct_ints():
    assert isinstance(App.ET_AI_SYSTEM_STATUS_WATCHER, int)
    assert isinstance(App.ET_AI_SHIELD_WATCHER, int)
    assert App.ET_AI_SYSTEM_STATUS_WATCHER != App.ET_AI_SHIELD_WATCHER
    # Stable across accesses — the _NamedStub failure mode was that they weren't.
    assert App.ET_AI_SYSTEM_STATUS_WATCHER == App.ET_AI_SYSTEM_STATUS_WATCHER
    assert hash(App.ET_AI_SHIELD_WATCHER) == hash(App.ET_AI_SHIELD_WATCHER)


def test_a_watcher_crossing_reaches_a_handler_registered_on_the_constant():
    """End-to-end: the exact pattern ConditionSystemBelow.py:88-97 uses.

    NOTE: App.g_kEventManager.AddEvent dispatches synchronously (it calls the
    destination's ProcessEvent directly — see engine/appc/events.py:466) so
    there is no separate drain/DispatchAll step to call.
    """
    from engine.appc.float_range_watcher import FloatRangeWatcher

    received = []

    class _Sink:
        def SystemEvent(self, pFloatEvent):
            received.append(pFloatEvent.GetFloat())

    sink = _Sink()
    handler = App.TGPythonInstanceWrapper()
    handler.SetPyWrapper(sink)
    handler.AddPythonMethodHandlerForInstance(
        App.ET_AI_SYSTEM_STATUS_WATCHER, "SystemEvent")

    watcher = FloatRangeWatcher(initial_value=1.0)
    event = App.TGFloatEvent_Create()
    event.SetEventType(App.ET_AI_SYSTEM_STATUS_WATCHER)
    event.SetDestination(handler)
    watcher.AddRangeCheck(0.5, App.FloatRangeWatcher.FRW_BOTH, event)

    watcher._update(0.2)                 # cross below the threshold

    assert received == [0.2]
