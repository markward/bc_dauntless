"""A condition status change broadcasts ET_AI_CONDITION_CHANGED.

Real Appc posts this from ConditionScript::SetStatus.
Conditions/ConditionCriticalSystemBelow.py composes child conditions and
listens for it; without the broadcast the composite condition never updates.

NOTE: App.g_kEventManager.AddEvent dispatches synchronously (destination
first, then broadcast handlers -- see engine/appc/events.py:466), so there
is no separate drain/DispatchAll step to call (no such method exists on
TGEventManager).
"""
import App
from engine.appc.ai import TGCondition


def test_status_change_broadcasts_the_event_with_the_new_status():
    received = []

    class _Sink:
        def Changed(self, pEvent):
            received.append(pEvent.GetInt())

    sink = _Sink()
    handler = App.TGPythonInstanceWrapper()
    handler.SetPyWrapper(sink)
    App.g_kEventManager.AddBroadcastPythonMethodHandler(
        App.ET_AI_CONDITION_CHANGED, handler, "Changed")

    cond = TGCondition()
    cond.SetStatus(1)
    assert received == [1]

    # No change -> no event.
    cond.SetStatus(1)
    assert received == [1]

    cond.SetStatus(0)
    assert received == [1, 0]
