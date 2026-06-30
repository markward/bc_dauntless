"""Phase B — player Alt+C cloak control.

BC's *player* cloak is not the SDK-Python path the AI/missions use.  Alt+C goes
through BridgeHandlers.ToggleCloak → ET_OTHER_CLOAK_TOGGLE_CLICKED → the C++
TacWeaponsCtrl, which is what actually engages the cloak (BridgeHandlers.py:163).
Our headless `_TacWeaponsCtrl` shim reproduces that contract:

  * GetCloakToggle()      — None for ships with no cloaking device.
  * RefreshCloakToggle()  — resync the button to the device's real state.
  * the ET_OTHER_CLOAK_TOGGLE_CLICKED instance handler — Start/StopCloaking.
  * ToggleCloakFromInput() — the Alt+C keyboard entry point (host_loop poller).
"""
import App
import pytest

from engine.appc.ships import ShipClass
from engine.appc.subsystems import CloakingSubsystem


def _player(with_cloak):
    ship = ShipClass()
    if with_cloak:
        ship.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
    return ship


@pytest.fixture
def game_with_player():
    """Factory: install a current game whose player ship optionally carries a
    cloak.  Resets the current game and the singleton TacWeaponsCtrl (so its
    toggle state never leaks between tests)."""
    def _make(with_cloak):
        player = _player(with_cloak)
        game = App.Game()
        App._set_current_game(game)
        game.SetPlayer(player)
        return player
    yield _make
    App._set_current_game(None)
    App._g_tac_weapons_ctrl = None


# ── GetCloakToggle gating (BC: "Not all ships can cloak…") ────────────────────

def test_get_cloak_toggle_none_without_cloak(game_with_player):
    game_with_player(with_cloak=False)
    ctrl = App.TacWeaponsCtrl_GetTacWeaponsCtrl()
    assert ctrl.GetCloakToggle() is None


def test_get_cloak_toggle_present_with_cloak(game_with_player):
    game_with_player(with_cloak=True)
    ctrl = App.TacWeaponsCtrl_GetTacWeaponsCtrl()
    assert ctrl.GetCloakToggle() is not None


# ── The instance event handler honours the toggle state (SDK re-fire path) ────

def test_toggle_event_handler_engages_and_disengages(game_with_player):
    player = game_with_player(with_cloak=True)
    ctrl = App.TacWeaponsCtrl_GetTacWeaponsCtrl()
    cloak = player.GetCloakingSubsystem()

    # Toggle ON, dispatch the event to the control → StartCloaking.
    ctrl._cloak_toggle.SetState(1)
    evt = App.TGEvent_Create()
    evt.SetEventType(App.ET_OTHER_CLOAK_TOGGLE_CLICKED)
    ctrl.ProcessEvent(evt)
    assert cloak.IsCloaking() == 1

    # Now fully cloaked; toggle OFF + dispatch → StopCloaking.
    cloak.InstantCloak()
    ctrl._cloak_toggle.SetState(0)
    ctrl.ProcessEvent(evt)
    assert cloak.IsDecloaking() == 1


# ── ToggleCloakFromInput (Alt+C keyboard path) ────────────────────────────────

def test_toggle_from_input_cloaks_then_decloaks(game_with_player):
    player = game_with_player(with_cloak=True)
    cloak = player.GetCloakingSubsystem()

    App.ToggleCloakFromInput()          # first press → CLOAKING
    assert cloak.IsCloaking() == 1

    cloak.InstantCloak()                # let it finish
    App.ToggleCloakFromInput()          # second press → DECLOAKING
    assert cloak.IsDecloaking() == 1


def test_toggle_from_input_is_noop_without_cloak(game_with_player):
    player = game_with_player(with_cloak=False)
    App.ToggleCloakFromInput()          # must not raise, must not invent a cloak
    assert player.GetCloakingSubsystem() is None


# ── RefreshCloakToggle keeps the button in sync with the real device ──────────

def test_refresh_cloak_toggle_syncs_to_device_state(game_with_player):
    player = game_with_player(with_cloak=True)
    ctrl = App.TacWeaponsCtrl_GetTacWeaponsCtrl()
    cloak = player.GetCloakingSubsystem()

    cloak.StartCloaking()               # a mission script cloaks directly
    ctrl.RefreshCloakToggle()
    assert ctrl._cloak_toggle.GetState() == 1

    cloak.InstantDecloak()              # forced decloak (e.g. damaged cloak)
    ctrl.RefreshCloakToggle()
    assert ctrl._cloak_toggle.GetState() == 0


def test_toggle_from_input_recovers_after_forced_decloak(game_with_player):
    """A cloak that auto-decloaked (damaged device) must re-cloak on the next
    press.  The RefreshCloakToggle resync inside ToggleCloakFromInput prevents
    the toggle sticking 'on' and swallowing the press as a redundant decloak."""
    player = game_with_player(with_cloak=True)
    cloak = player.GetCloakingSubsystem()

    App.ToggleCloakFromInput()          # → CLOAKING, toggle now on
    cloak.InstantCloak()
    cloak.InstantDecloak()              # forced decloak, no button press

    App.ToggleCloakFromInput()          # next press must re-cloak, not no-op
    assert cloak.IsCloaking() == 1
