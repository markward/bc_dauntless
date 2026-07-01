"""SetClass add/remove broadcasts ET_ENTERED_SET / ET_EXITED_SET.

BC mission region state machines (E2M2.EnterSet -> TrackPlayer, ExitSet, the
Marauder/Galor warp-in/out beats) hang off these broadcasts. Without them every
set-transition-gated beat and viewscreen cutscene stays dead. These tests pin
the event shape the SDK handlers rely on:

  ET_ENTERED_SET: destination = the ship; ship.GetContainingSet() is the new set.
  ET_EXITED_SET : destination = the ship; pEvent.GetCString() = the left set name.
"""
import App
import pytest

from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass
from engine.appc.warp import _WARP_TRANSIT_SET_NAME


@pytest.fixture(autouse=True)
def _clean_event_manager():
    App.g_kEventManager._broadcast_handlers.clear()
    App.g_kEventManager._method_handlers.clear()
    yield
    App.g_kEventManager._broadcast_handlers.clear()
    App.g_kEventManager._method_handlers.clear()


# The broadcast func handler signature the SDK uses: (broadcaster, event).
_captured: list = []


def _record_enter(broadcaster, event):
    _captured.append(("entered", event.GetDestination(), event.GetEventType()))


def _record_exit(broadcaster, event):
    _captured.append(("exited", event.GetDestination(), event.GetCString()))


def setup_function(_):
    _captured.clear()


def _register():
    mgr = App.g_kEventManager
    mgr.AddBroadcastPythonFuncHandler(
        App.ET_ENTERED_SET, ShipClass(),
        __name__ + "._record_enter")
    mgr.AddBroadcastPythonFuncHandler(
        App.ET_EXITED_SET, ShipClass(),
        __name__ + "._record_exit")


def test_adding_a_ship_broadcasts_entered_set():
    _register()
    pSet = SetClass(); pSet.SetName("Serris3")
    pShip = ShipClass()
    pSet.AddObjectToSet(pShip, "player")
    assert ("entered", pShip, App.ET_ENTERED_SET) in _captured


_seen_containing_set: list = []


def _record_containing_set(broadcaster, event):
    ship = event.GetDestination()
    _seen_containing_set.append(ship.GetContainingSet().GetName())


def test_entered_event_sees_the_new_containing_set():
    """EnterSet reads pShip.GetContainingSet().GetName(); it must already point
    at the destination set when the event dispatches."""
    _seen_containing_set.clear()
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_ENTERED_SET, ShipClass(), __name__ + "._record_containing_set")
    pSet = SetClass(); pSet.SetName("Serris3")
    pSet.AddObjectToSet(ShipClass(), "player")
    assert _seen_containing_set == ["Serris3"]


def test_removing_a_ship_broadcasts_exited_set_with_left_set_name():
    _register()
    pSet = SetClass(); pSet.SetName("Serris2")
    pShip = ShipClass()
    pSet.AddObjectToSet(pShip, "Marauder")
    _captured.clear()
    pSet.RemoveObjectFromSet("Marauder")
    assert ("exited", pShip, "Serris2") in _captured


def test_delete_object_from_set_also_broadcasts_exit():
    _register()
    pSet = SetClass(); pSet.SetName("Serris2")
    pShip = ShipClass()
    pSet.AddObjectToSet(pShip, "Galor 2")
    _captured.clear()
    pSet.DeleteObjectFromSet("Galor 2")
    assert ("exited", pShip, "Serris2") in _captured


def test_non_ship_objects_do_not_broadcast():
    _register()
    pSet = SetClass(); pSet.SetName("Serris3")

    class _Waypoint:
        def SetName(self, _): pass

    pSet.AddObjectToSet(_Waypoint(), "Player Start")
    assert _captured == []


def test_warp_transit_set_is_suppressed():
    """The engine-internal warp-transit set has no BC equivalent; moving a ship
    through it must not inject a spurious region entry/exit."""
    _register()
    pTransit = SetClass(); pTransit.SetName(_WARP_TRANSIT_SET_NAME)
    pShip = ShipClass()
    pTransit.AddObjectToSet(pShip, "player")
    pTransit.RemoveObjectFromSet("player")
    assert _captured == []
