"""_STStylizedWindow dispatches its registered per-instance handlers."""
import sys
import types

import App
from engine.appc.windows import _STStylizedWindow


def _make_handler_module():
    mod = types.ModuleType("_tmp_infobox_handlers")
    mod.calls = []
    def on_close(obj, event):
        mod.calls.append((obj, event))
    mod.on_close = on_close
    sys.modules[mod.__name__] = mod
    return mod


def test_process_event_invokes_registered_handler():
    mod = _make_handler_module()
    try:
        w = _STStylizedWindow("X")
        w.AddPythonFuncHandlerForInstance(App.ET_INPUT_CLOSE_MENU,
                                          "_tmp_infobox_handlers.on_close")
        ev = App.TGEvent_Create()
        ev.SetEventType(App.ET_INPUT_CLOSE_MENU)
        ev.SetDestination(w)
        w.ProcessEvent(ev)
        assert len(mod.calls) == 1
        assert mod.calls[0][0] is w
    finally:
        del sys.modules["_tmp_infobox_handlers"]


def test_process_event_ignores_non_matching_type():
    mod = _make_handler_module()
    try:
        w = _STStylizedWindow("X")
        w.AddPythonFuncHandlerForInstance(App.ET_INPUT_CLOSE_MENU,
                                          "_tmp_infobox_handlers.on_close")
        ev = App.TGEvent_Create()
        ev.SetEventType(App.ET_INPUT_FIRE_PRIMARY)
        ev.SetDestination(w)
        w.ProcessEvent(ev)
        assert mod.calls == []
    finally:
        del sys.modules["_tmp_infobox_handlers"]


def test_process_event_with_no_handlers_is_inert():
    w = _STStylizedWindow("X")
    ev = App.TGEvent_Create()
    ev.SetEventType(App.ET_INPUT_CLOSE_MENU)
    ev.SetDestination(w)
    w.ProcessEvent(ev)  # must not raise
