"""End-to-end: post OnKeyDown(WC_RBUTTON) via g_kInputManager and assert
the entire chain runs through to one Galaxy torpedo tube firing.

Chain under test:
  g_kInputManager.OnKeyDown(WC_RBUTTON)
  → TGKeyboardEvent(WC_RBUTTON, KS_KEYDOWN) broadcast
  → g_kKeyboardBinding.OnKeyboardEvent
  → TGBoolEvent(ET_INPUT_FIRE_SECONDARY, bFiring=1) → TCW.ProcessEvent
  → TacticalInterfaceHandlers.FireSecondaryWeapons
  → App.Game_GetCurrentPlayer().GetWeaponSystemGroup(WG_SECONDARY).StartFiring()
  → TorpedoTube.Fire() → _num_ready -= 1

Mocks TGSoundManager so the test doesn't depend on a live audio engine.
"""
import importlib
import sys
from unittest.mock import patch

import pytest

import App
from engine.appc.ships import ShipClass, ShipClass_Create


def _setup_input_chain(ship):
    """Wire the input pipeline so OnKeyDown/OnKeyUp route through the full
    SDK-faithful chain to the ship's weapon systems.

    Steps mirror _bootstrap_firing_pipeline in engine/host_loop.py but add
    the RegisterUnicodeKey calls that live in KeyConfig.MapScancodes (called
    by the C++ host at startup but not part of the test bootstrap).

    Resets TCW handlers before calling Initialize so repeated fixture calls
    from multiple tests don't accumulate duplicate handlers.
    """
    App.Game_GetCurrentPlayer = lambda: ship

    # Register mouse buttons with the input manager so OnKeyDown(WC_RBUTTON)
    # actually emits a TGKeyboardEvent.  In production KeyConfig.MapScancodes()
    # does this; in tests we do it inline.
    App.g_kInputManager.RegisterUnicodeKey(App.WC_LBUTTON, App.KY_LBUTTON, None, "LButton")
    App.g_kInputManager.RegisterUnicodeKey(App.WC_RBUTTON, App.KY_RBUTTON, None, "RButton")

    tcw = App.TacticalControlWindow_GetTacticalControlWindow()
    # Reset any handlers from previous test runs to prevent duplicates.
    tcw.RemoveAllInstanceHandlers()
    App.g_kKeyboardBinding.SetDefaultDestination(tcw)

    import DefaultKeyboardBinding
    DefaultKeyboardBinding.Initialize()

    import TacticalInterfaceHandlers
    TacticalInterfaceHandlers.Initialize(tcw)


@pytest.fixture
def galaxy_in_red_alert():
    """Load Galaxy hardpoint, wire input pipeline, return ship at RED alert."""
    ship = ShipClass_Create("Galaxy")

    App.g_kModelPropertyManager.ClearLocalTemplates()
    mod_name = "ships.Hardpoints.galaxy"
    if mod_name in sys.modules:
        importlib.reload(sys.modules[mod_name])
    else:
        importlib.import_module(mod_name)
    mod = sys.modules[mod_name]
    mod.LoadPropertySet(ship.GetPropertySet())
    ship.SetupProperties()

    _setup_input_chain(ship)
    ship.SetAlertLevel(ShipClass.RED_ALERT)

    yield ship

    # Teardown: clear property manager, evict hardpoint modules, reset TCW,
    # restore Game_GetCurrentPlayer to the real engine function so subsequent
    # tests that call Game_SetCurrentPlayer / Game_GetCurrentPlayer work correctly.
    App.g_kModelPropertyManager.ClearLocalTemplates()
    for k in list(sys.modules):
        if k == "ships" or k.startswith("ships."):
            del sys.modules[k]
    tcw = App.TacticalControlWindow_GetTacticalControlWindow()
    tcw.RemoveAllInstanceHandlers()
    from engine.core.game import Game_GetCurrentPlayer as _real_gcp
    App.Game_GetCurrentPlayer = _real_gcp


def test_right_click_fires_torpedo(galaxy_in_red_alert):
    """OnKeyDown(WC_RBUTTON) at RED alert launches a torpedo: Task 7's
    ship-wide 0.5s fire stagger throttles same-tick multi-fire to ONE
    launch — the first tube in the working group stamps
    TorpedoSystem._last_system_fire_time, and every other ready tube's
    CanFire() fails the stagger gate within the same tick (gameTime delta
    is 0)."""
    ship = galaxy_in_red_alert
    torps = ship.GetTorpedoSystem()
    n = torps.GetNumWeapons()
    initial_ready = sum(torps.GetWeapon(i).GetNumReady() for i in range(n))

    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        App.g_kInputManager.OnKeyDown(App.WC_RBUTTON)
        App.g_kInputManager.OnKeyUp(App.WC_RBUTTON)

    final_ready = sum(torps.GetWeapon(i).GetNumReady() for i in range(n))
    assert final_ready == initial_ready - 1


def test_right_click_at_green_alert_does_nothing(galaxy_in_red_alert):
    """Switching to GREEN alert before firing should block the torpedo."""
    ship = galaxy_in_red_alert
    ship.SetAlertLevel(ShipClass.GREEN_ALERT)
    torps = ship.GetTorpedoSystem()
    initial = [torps.GetWeapon(i).GetNumReady() for i in range(torps.GetNumWeapons())]

    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        App.g_kInputManager.OnKeyDown(App.WC_RBUTTON)
        App.g_kInputManager.OnKeyUp(App.WC_RBUTTON)

    final = [torps.GetWeapon(i).GetNumReady() for i in range(torps.GetNumWeapons())]
    assert final == initial
