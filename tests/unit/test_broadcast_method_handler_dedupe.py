"""AddBroadcastPythonMethodHandler registers an identical handler once.

SDK Conditions/ConditionInRange.SetObjects registers its five broadcast
handlers every time it runs, and it runs again from SetTarget and from its
own GroupChanged handler -- which re-registers GroupChanged itself. Appended
blindly, every target change grew the lists, and every ET_OBJECT_GROUP_CHANGED
doubled the GroupChanged handlers (each copy re-registers one more), so a
group of ten names cost ~2^10 sphere rebuilds."""
import App
import pytest

_ET = App.ET_OBJECT_GROUP_CHANGED


class _Rec:
    def __init__(self):
        self.n = 0

    def Hit(self, evt):
        self.n += 1


@pytest.fixture(autouse=True)
def clean():
    App.g_kEventManager._method_handlers.pop(_ET, None)
    yield
    App.g_kEventManager._method_handlers.pop(_ET, None)


def _wrapper(rec):
    w = App.TGPythonInstanceWrapper()
    w.SetPyWrapper(rec)
    return w


def _post(dest):
    evt = App.TGEvent_Create()
    evt.SetEventType(_ET)
    evt.SetDestination(dest)
    App.g_kEventManager.AddEvent(evt)


def test_the_same_handler_registered_three_times_runs_once():
    rec = _Rec()
    w = _wrapper(rec)
    target = App.ObjectGroup()
    for _ in range(3):
        App.g_kEventManager.AddBroadcastPythonMethodHandler(_ET, w, "Hit", target)
    _post(target)
    assert rec.n == 1
    assert len(App.g_kEventManager._method_handlers[_ET]) == 1


def test_a_different_target_is_a_different_handler():
    rec = _Rec()
    w = _wrapper(rec)
    a, b = App.ObjectGroup(), App.ObjectGroup()
    App.g_kEventManager.AddBroadcastPythonMethodHandler(_ET, w, "Hit", a)
    App.g_kEventManager.AddBroadcastPythonMethodHandler(_ET, w, "Hit", b)
    _post(a)
    _post(b)
    assert rec.n == 2


def test_one_remove_unregisters_a_handler_added_twice():
    rec = _Rec()
    w = _wrapper(rec)
    target = App.ObjectGroup()
    App.g_kEventManager.AddBroadcastPythonMethodHandler(_ET, w, "Hit", target)
    App.g_kEventManager.AddBroadcastPythonMethodHandler(_ET, w, "Hit", target)
    App.g_kEventManager.RemoveBroadcastHandler(_ET, w, "Hit", target)
    _post(target)
    assert rec.n == 0
