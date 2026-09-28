"""The tunnel parks the player in BC's persistent "warp" set (spec §1b)."""
import App
from engine.appc import warp
from engine.appc.sets import SetClass_Create


def setup_function(_):
    App.g_kSetManager._sets.clear()


def test_get_warp_set_creates_one_named_warp_and_returns_it_again():
    s = App.WarpSequence_GetWarpSet()
    assert s is not None and s.GetName() == "warp"
    assert App.WarpSequence_GetWarpSet() is s
    assert App.g_kSetManager.GetSet("warp") is s


def _ship_in(pSet, name):
    ship = App.ShipClass_Create()
    ship.SetName(name)
    pSet.AddObjectToSet(ship, name)
    return ship


def test_departure_parks_the_player_in_the_warp_set_and_keeps_its_contents():
    src = SetClass_Create(); App.g_kSetManager.AddSet(src, "Src")
    ws = App.WarpSequence_GetWarpSet()
    other = _ship_in(ws, "Artrus 1")            # a mission's in-tunnel ship
    player = _ship_in(src, "player")
    warp._WarpDepartAction(src, player).Play()
    assert App.g_kSetManager.GetSet("warp") is ws          # not recreated
    assert ws.GetObject("player") is player
    assert ws.GetObject("Artrus 1") is other               # survives departure


def test_entering_the_warp_set_is_broadcast():
    seen = []
    ws = App.WarpSequence_GetWarpSet()
    ev_type = App.ET_ENTERED_SET
    ws_ship = App.ShipClass_Create(); ws_ship.SetName("player")
    # Broadcast handler records every ET_ENTERED_SET destination. Qualified
    # by __name__ (mirrors test_set_transition_events.py) rather than a
    # hardcoded dotted path -- tests/unit has no __init__.py, so pytest
    # imports this file as top-level "test_warp_set", not
    # "tests.unit.test_warp_set".
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        ev_type, None, __name__ + "._record")
    _record.seen = seen
    ws.AddObjectToSet(ws_ship, "player")
    assert ws_ship in seen


def _record(obj, event):
    _record.seen.append(event.GetDestination())


def test_reset_sdk_globals_drops_the_warp_set():
    from engine import host_loop
    App.WarpSequence_GetWarpSet()
    host_loop.reset_sdk_globals()
    assert App.g_kSetManager.GetSet("warp") is None
