"""BC-faithful instance-handler chain: LIFO order + CallNextHandler short-circuit.

The most-recently-registered handler runs first; control passes to the next
(older) handler only when a handler calls CallNextHandler. A handler that
returns without calling it stops the chain. This is what lets E1M2.HailHandler
(registered after HelmMenuHandlers.Hail) handle the colony hail and suppress the
generic "no response".
"""
from engine.appc.events import TGEventHandlerObject, TGEvent

ET = 0x4242
_calls: list = []


def _first(obj, event):
    _calls.append("first")
    obj.CallNextHandler(event)


def _second_stops(obj, event):
    _calls.append("second")
    # Deliberately does NOT call CallNextHandler -> chain stops here.


def _third(obj, event):
    _calls.append("third")
    obj.CallNextHandler(event)


def _mk():
    obj = TGEventHandlerObject()
    evt = TGEvent()
    evt.SetEventType(ET)
    return obj, evt


def _q(name):
    return __name__ + "." + name


def test_single_handler_runs_once_even_calling_next():
    _calls.clear()
    obj, evt = _mk()
    obj.AddPythonFuncHandlerForInstance(ET, _q("_first"))
    obj.ProcessEvent(evt)
    assert _calls == ["first"]        # CallNextHandler with no next = no-op


def test_lifo_order_all_pass_through():
    _calls.clear()
    obj, evt = _mk()
    obj.AddPythonFuncHandlerForInstance(ET, _q("_first"))
    obj.AddPythonFuncHandlerForInstance(ET, _q("_third"))  # registered last -> runs first
    obj.ProcessEvent(evt)
    assert _calls == ["third", "first"]


def test_handler_without_call_next_stops_chain():
    _calls.clear()
    obj, evt = _mk()
    # Registration order: first, second_stops, third.
    obj.AddPythonFuncHandlerForInstance(ET, _q("_first"))
    obj.AddPythonFuncHandlerForInstance(ET, _q("_second_stops"))
    obj.AddPythonFuncHandlerForInstance(ET, _q("_third"))
    obj.ProcessEvent(evt)
    # Reverse: third -> (next) second_stops -> STOP. first never runs.
    assert _calls == ["third", "second"]


# ── Models the Hail case ──────────────────────────────────────────────────────
_hail_log: list = []


def _generic_hail(obj, event):
    # HelmMenuHandlers.Hail: plays "no response" then chains.
    _hail_log.append("no-response")
    obj.CallNextHandler(event)


def _mission_hail_handler(obj, event):
    # E1M2.HailHandler: handles "Haven" and returns WITHOUT CallNextHandler.
    _hail_log.append("soams-dialogue")
    # no CallNextHandler -> generic Hail must not fire.


def test_unresolvable_handler_is_skipped_not_stalled():
    """A handler whose module/func can't be resolved is skipped so the chain
    still reaches the next (older) handler rather than stalling."""
    _calls.clear()
    obj, evt = _mk()
    obj.AddPythonFuncHandlerForInstance(ET, _q("_first"))          # older, real
    obj.AddPythonFuncHandlerForInstance(ET, _q("_does_not_exist")) # newer, unresolvable
    obj.ProcessEvent(evt)
    assert _calls == ["first"]


def test_mission_handler_suppresses_generic_hail():
    _hail_log.clear()
    obj, evt = _mk()
    # Bridge load registers the generic Hail first; mission init registers its
    # handler later (so it runs first and wins).
    obj.AddPythonFuncHandlerForInstance(ET, _q("_generic_hail"))
    obj.AddPythonFuncHandlerForInstance(ET, _q("_mission_hail_handler"))
    obj.ProcessEvent(evt)
    assert _hail_log == ["soams-dialogue"]     # NOT "no-response"
