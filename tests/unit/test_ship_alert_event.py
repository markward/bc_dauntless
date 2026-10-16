"""ET_SET_ALERT_LEVEL sent to a ship changes its alert level.

In BC the ship's own (C++) handler applied this event; every SDK path that
changes the player's alert ends by posting it to the ship:
Bridge/XOMenuHandlers.SetAlertLevel (the XO's Green/Yellow/Red buttons),
MissionLib.RedAlert, QuickBattle's start/end of simulation, E1M2. With no
ship-side handler the event was dropped -- the XO spoke her line and the
alert never changed.

The engine applies the level only when the ship's instance-handler chain
passes, like every BC default: a newer script handler that returns without
CallNextHandler cancels it. The ship plays no sound -- the SDK scripts play
the klaxon themselves (XOMenuHandlers, MissionLib.RedAlert).
"""
import App
import Bridge.BridgeUtils as BridgeUtils
import Bridge.XOMenuHandlers  # noqa: F401 -- handler lookup reads sys.modules
from engine.appc.ships import ShipClass, ShipClass_Create
from engine.appc.sets import SetClass
from engine.core.game import Game, _set_current_game


def _alert_event(ship, level):
    evt = App.TGIntEvent_Create()
    evt.SetDestination(ship)
    evt.SetEventType(App.ET_SET_ALERT_LEVEL)
    evt.SetInt(level)
    return evt


def _green_player():
    s = SetClass()
    player = ShipClass_Create("Galaxy")
    s.AddObjectToSet(player, "player")
    game = Game()
    game.SetPlayer(player)
    _set_current_game(game)
    player.SetAlertLevel(ShipClass.GREEN_ALERT)
    return player


def test_event_sent_to_a_ship_sets_its_alert_level():
    ship = ShipClass()
    ship.SetAlertLevel(ShipClass.GREEN_ALERT)

    App.g_kEventManager.AddEvent(_alert_event(ship, ShipClass.RED_ALERT))

    assert ship.GetAlertLevel() == ShipClass.RED_ALERT


def test_event_applies_the_alert_power_policy():
    """The event goes through SetAlertLevel, not a bare field write."""
    ship = ShipClass()
    calls = []
    ship.SetAlertLevel = calls.append

    App.g_kEventManager.AddEvent(_alert_event(ship, ShipClass.YELLOW_ALERT))

    assert calls == [ShipClass.YELLOW_ALERT]


def test_xo_red_alert_button_puts_the_player_on_red_alert():
    player = _green_player()
    menu = App.STMenu_CreateW("Commander")
    menu.AddPythonFuncHandlerForInstance(App.ET_SET_ALERT_LEVEL,
                                         "Bridge.XOMenuHandlers.SetAlertLevel")
    button = BridgeUtils.CreateBridgeMenuButton(
        "Red Alert", App.ET_SET_ALERT_LEVEL,
        App.CharacterClass.EST_ALERT_RED, menu)
    menu.AddChild(button, 0.0, 0.0, 0)

    button.SendActivationEvent()

    assert player.GetAlertLevel() == ShipClass.RED_ALERT


def _stop_chain(pShip, pEvent):
    return                                  # no CallNextHandler: cancels


def _pass_chain(pShip, pEvent):
    pShip.CallNextHandler(pEvent)


def test_a_script_handler_that_stops_the_chain_cancels_the_change():
    ship = ShipClass()
    ship.SetAlertLevel(ShipClass.GREEN_ALERT)
    ship.AddPythonFuncHandlerForInstance(App.ET_SET_ALERT_LEVEL,
                                         __name__ + "._stop_chain")

    App.g_kEventManager.AddEvent(_alert_event(ship, ShipClass.RED_ALERT))

    assert ship.GetAlertLevel() == ShipClass.GREEN_ALERT


def test_a_script_handler_that_passes_the_chain_lets_the_change_through():
    ship = ShipClass()
    ship.SetAlertLevel(ShipClass.GREEN_ALERT)
    ship.AddPythonFuncHandlerForInstance(App.ET_SET_ALERT_LEVEL,
                                         __name__ + "._pass_chain")

    App.g_kEventManager.AddEvent(_alert_event(ship, ShipClass.RED_ALERT))

    assert ship.GetAlertLevel() == ShipClass.RED_ALERT


def test_other_events_to_a_ship_leave_the_alert_alone():
    ship = ShipClass()
    ship.SetAlertLevel(ShipClass.GREEN_ALERT)
    evt = App.TGIntEvent_Create()
    evt.SetDestination(ship)
    evt.SetEventType(App.ET_IN_SYSTEM_WARP)
    evt.SetInt(ShipClass.RED_ALERT)

    App.g_kEventManager.AddEvent(evt)

    assert ship.GetAlertLevel() == ShipClass.GREEN_ALERT
