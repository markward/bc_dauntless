"""Regression: warp set-entry must not crash the "Entering <system>" banner.

Live E1M2 bug: engaging warp killed the host loop in the real SDK handler
Bridge/HelmMenuHandlers.ObjectEnteredSet (HelmMenuHandlers.py:407) —

    pOptions = pTop.FindMainWindow(App.MWT_OPTIONS)          # line 388
    if (pSet.GetName() != "warp") and (pOptions.IsCompletelyVisible() == 0):
    AttributeError: 'NoneType' object has no attribute 'IsCompletelyVisible'

In real BC the Options main window always exists in the Appc UI hierarchy, so
the SDK never None-checks it. _TopWindow.__init__ now seeds an _OptionsWindow
(never visible — options live in our CEF config panel), which both fixes the
crash and enables the SDK banner branch (gated on IsCompletelyVisible() == 0).

These tests drive the real SDK ObjectEnteredSet with the ET_ENTERED_SET event
shape SetClass.AddObjectToSet broadcasts (destination = the entering ship),
mirroring warp: entry into the "warp" transit set, then the destination set.
pObject mirrors the live registration (HelmMenuHandlers.py:189 registers
pHelmMenu, whose CallNextHandler the handler tail calls).
"""
import App
from engine.appc import top_window
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import SensorSubsystem
from engine.appc.sets import SetClass
from engine.core.game import Game, _set_current_game
import Bridge.HelmMenuHandlers as H


def _player_in_set(set_name):
    """A player ship with sensors inside a set named set_name, registered as
    the current player (MissionLib.GetPlayer -> App.Game_GetCurrentPlayer)."""
    s = SetClass()
    s.SetName(set_name)
    player = ShipClass_Create("Galaxy")
    player.SetSensorSubsystem(SensorSubsystem("Sensors"))
    s.AddObjectToSet(player, "player")
    game = Game()
    game.SetPlayer(player)
    _set_current_game(game)
    return s, player


def _entered_set_event(player):
    """The event shape SetClass._broadcast_set_transition posts on entry."""
    event = App.TGEvent_Create()
    event.SetEventType(App.ET_ENTERED_SET)
    event.SetDestination(player)
    return event


def test_object_entered_warp_set_does_not_raise():
    """Entering the "warp" set skips the banner (GetName() == "warp"
    short-circuits before pOptions is touched) — must be a clean no-op."""
    top_window.reset_for_tests()
    s, player = _player_in_set("warp")
    H.g_bShowEnteringBanner = 1   # other tests (test_stub_modules) zero this
    helm_menu = App.STMenu_CreateW("Helm")
    H.ObjectEnteredSet(helm_menu, _entered_set_event(player))


def test_object_entered_destination_set_shows_banner_without_crash():
    """The live crash path: warp exit into a non-"warp" set evaluates
    pOptions.IsCompletelyVisible() — pOptions must be a real window, and the
    never-visible answer (0) enables the "Entering <system>" TextBanner."""
    top_window.reset_for_tests()
    s, player = _player_in_set("Vesuvi System")
    H.g_bShowEnteringBanner = 1
    helm_menu = App.STMenu_CreateW("Helm")

    H.ObjectEnteredSet(helm_menu, _entered_set_event(player))

    # The banner branch ran: MissionLib.TextBanner played a TGCreditAction
    # into the subtitle main window.
    sub = App.TopWindow_GetTopWindow().FindMainWindow(App.MWT_SUBTITLE)
    assert len(sub._active_texts) == 1
    # And it names the destination system — SetClass.GetDisplayName must fill
    # the TGString out-param (was a _RendererStub no-op: bare "Entering").
    banner_text = sub._active_texts[0][0]
    assert "Vesuvi System" in banner_text
