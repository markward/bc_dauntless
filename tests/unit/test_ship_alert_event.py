"""ET_SET_ALERT_LEVEL sent to a ship changes its alert level.

In BC the ship's own (C++) handler applied this event; every SDK path that
changes the player's alert through an event ends by posting it to the ship:
Bridge/XOMenuHandlers.SetAlertLevel (the XO's Green/Yellow/Red buttons),
MissionLib.RedAlert, QuickBattle's start/end of simulation, E1M2. With no
ship-side handler the event was dropped -- the XO spoke her line and the
alert never changed.

The engine applies the level only when the ship's instance-handler chain
passes, like every BC default: a newer script handler that returns without
CallNextHandler cancels it. It applies it on the next GameLoop tick, after
the AI window -- BC queues AddEvent (docs/gap_analysis.md OQ-4.2), and
MissionLib.RedAlert depends on it: it posts the event, THEN reads
pShields.IsOn() to pick the XO's line. The ship plays no sound -- the SDK
scripts play the klaxon themselves (XOMenuHandlers, MissionLib.RedAlert).
"""
import App
import Bridge.BridgeUtils as BridgeUtils
import Bridge.XOMenuHandlers  # noqa: F401 -- handler lookup reads sys.modules
from engine.appc.ships import (
    ShipClass, ShipClass_Create, apply_pending_alert_levels,
)
from engine.appc.sets import SetClass
from engine.core.game import Game, _set_current_game
from engine.core.loop import GameLoop


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


def _xo_red_alert_button():
    menu = App.STMenu_CreateW("Commander")
    menu.AddPythonFuncHandlerForInstance(App.ET_SET_ALERT_LEVEL,
                                         "Bridge.XOMenuHandlers.SetAlertLevel")
    button = BridgeUtils.CreateBridgeMenuButton(
        "Red Alert", App.ET_SET_ALERT_LEVEL,
        App.CharacterClass.EST_ALERT_RED, menu)
    menu.AddChild(button, 0.0, 0.0, 0)
    return button


def test_event_sent_to_a_ship_sets_its_alert_level():
    ship = ShipClass()
    ship.SetAlertLevel(ShipClass.GREEN_ALERT)

    App.g_kEventManager.AddEvent(_alert_event(ship, ShipClass.RED_ALERT))
    apply_pending_alert_levels()

    assert ship.GetAlertLevel() == ShipClass.RED_ALERT


def test_the_level_lands_after_the_posting_code_not_during_it():
    ship = ShipClass()
    ship.SetAlertLevel(ShipClass.GREEN_ALERT)

    App.g_kEventManager.AddEvent(_alert_event(ship, ShipClass.RED_ALERT))

    assert ship.GetAlertLevel() == ShipClass.GREEN_ALERT


def test_the_game_loop_tick_applies_it():
    ship = ShipClass()
    ship.SetAlertLevel(ShipClass.GREEN_ALERT)

    App.g_kEventManager.AddEvent(_alert_event(ship, ShipClass.RED_ALERT))
    GameLoop().tick()

    assert ship.GetAlertLevel() == ShipClass.RED_ALERT


def test_queued_levels_apply_in_posting_order():
    ship = ShipClass()
    ship.SetAlertLevel(ShipClass.GREEN_ALERT)

    App.g_kEventManager.AddEvent(_alert_event(ship, ShipClass.RED_ALERT))
    App.g_kEventManager.AddEvent(_alert_event(ship, ShipClass.YELLOW_ALERT))
    apply_pending_alert_levels()

    assert ship.GetAlertLevel() == ShipClass.YELLOW_ALERT


def test_event_applies_the_alert_power_policy():
    """The event goes through SetAlertLevel, not a bare field write."""
    ship = ShipClass()
    calls = []
    ship.SetAlertLevel = calls.append

    App.g_kEventManager.AddEvent(_alert_event(ship, ShipClass.YELLOW_ALERT))
    apply_pending_alert_levels()

    assert calls == [ShipClass.YELLOW_ALERT]


def test_xo_red_alert_button_puts_the_player_on_red_alert():
    player = _green_player()

    _xo_red_alert_button().SendActivationEvent()
    apply_pending_alert_levels()

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
    apply_pending_alert_levels()

    assert ship.GetAlertLevel() == ShipClass.GREEN_ALERT


def test_a_script_handler_that_passes_the_chain_lets_the_change_through():
    ship = ShipClass()
    ship.SetAlertLevel(ShipClass.GREEN_ALERT)
    ship.AddPythonFuncHandlerForInstance(App.ET_SET_ALERT_LEVEL,
                                         __name__ + "._pass_chain")

    App.g_kEventManager.AddEvent(_alert_event(ship, ShipClass.RED_ALERT))
    apply_pending_alert_levels()

    assert ship.GetAlertLevel() == ShipClass.RED_ALERT


def test_other_events_to_a_ship_leave_the_alert_alone():
    ship = ShipClass()
    ship.SetAlertLevel(ShipClass.GREEN_ALERT)
    evt = App.TGIntEvent_Create()
    evt.SetDestination(ship)
    evt.SetEventType(App.ET_IN_SYSTEM_WARP)
    evt.SetInt(ShipClass.RED_ALERT)

    App.g_kEventManager.AddEvent(evt)
    apply_pending_alert_levels()

    assert ship.GetAlertLevel() == ShipClass.GREEN_ALERT


def test_one_xo_click_plays_the_klaxon_exactly_once(monkeypatch):
    """XOMenuHandlers plays the klaxon; the ship's step must not add one."""
    from engine.audio.tg_sound import TGSoundManager
    played = []
    monkeypatch.setattr(TGSoundManager.instance(), "PlaySound",
                        lambda name, *a, **k: played.append(name))
    _green_player()

    _xo_red_alert_button().SendActivationEvent()
    apply_pending_alert_levels()

    assert played == ["RedAlertSound"]


def test_missionlib_red_alert_from_green_says_shields_up(monkeypatch):
    """MissionLib.RedAlert posts the event and only THEN reads
    pShields.IsOn(): shields still down => "RedAlert" ("Red Alert, shields
    up"), not "RedAlert2". Applying the level mid-call flipped the line."""
    import MissionLib
    lines = []
    real_create = App.CharacterAction_Create

    def _record(*args):
        if len(args) > 2 and args[1] == App.CharacterAction.AT_SAY_LINE:
            lines.append(args[2])
        return real_create(*args)

    monkeypatch.setattr(App, "CharacterAction_Create", _record)
    player = _green_player()
    assert not player.GetShields().IsOn()

    MissionLib.RedAlert()
    apply_pending_alert_levels()

    assert lines == ["RedAlert"]
    assert player.GetAlertLevel() == ShipClass.RED_ALERT
