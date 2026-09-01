"""BC's 4th argument to AddBroadcastPythonFuncHandler is a destination FILTER.

10 SDK sites pass one. Ours discarded it, so a filtered handler fired for
every event of its type regardless of destination. Live consequence:
Bridge/PowerDisplay.py:340-341 registers HandleCloak filtered to the player,
and HandleCloak repaints the HUD cloak indicator from
App.ShipClass_Cast(pEvent.GetDestination()) -- so any NPC cloaking repainted
the player's indicator from the NPC's state. AddBroadcastPythonMethodHandler
already filtered correctly (events.py:791-793); this brings the func variant
to parity.
"""
import App
import pytest

from engine.appc.objects import ObjectClass

_ET = App.ET_CLOAK_BEGINNING
_HANDLER = __name__ + ".record"

_seen = []


def record(pObject, pEvent):
    _seen.append(pEvent.GetDestination())


@pytest.fixture(autouse=True)
def clean():
    _seen.clear()
    yield
    for entry in list(App.g_kEventManager._broadcast_handlers.get(_ET, [])):
        App.g_kEventManager._broadcast_handlers[_ET].remove(entry)
    _seen.clear()


def _post_to(dest):
    evt = App.TGEvent_Create()
    evt.SetEventType(_ET)
    evt.SetDestination(dest)
    App.g_kEventManager.AddEvent(evt)


def test_a_filtered_handler_ignores_other_destinations():
    watched, other = ObjectClass(), ObjectClass()
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        _ET, ObjectClass(), _HANDLER, watched)

    _post_to(other)
    assert _seen == [], "a handler filtered to one object fired for another"

    _post_to(watched)
    assert _seen == [watched]


def test_an_unfiltered_handler_still_sees_everything():
    """The 3-argument form is the common case (the other ~200 SDK sites) and
    must keep matching every destination."""
    a, b = ObjectClass(), ObjectClass()
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        _ET, ObjectClass(), _HANDLER)

    _post_to(a)
    _post_to(b)
    assert _seen == [a, b]


def test_removal_still_works_for_a_filtered_handler():
    """RemoveBroadcastHandler unpacks the tuple; a shape change breaks it."""
    watched = ObjectClass()
    dest = ObjectClass()
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        _ET, dest, _HANDLER, watched)
    App.g_kEventManager.RemoveBroadcastHandler(_ET, dest, _HANDLER)

    _post_to(watched)
    assert _seen == []
