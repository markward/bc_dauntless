"""End-to-end sequential firing: 6 right-clicks at RED → each fires from
a different tube; 7th click wraps around and finds no eligible tube
(all empty) → silent no-op.

Galaxy has 6 torpedo tubes, each with MaxReady=1.  WeaponSystem.StartFiring
uses round-robin: after each fire the cursor advances to the next tube.
After 6 shots the cursor has visited all tubes; the 7th click finds no
CanFire()-eligible tube and exits quietly.
"""
import importlib
import sys
from unittest.mock import patch

import pytest

import App
from engine.appc.ships import ShipClass, ShipClass_Create


def _setup_input_chain(ship):
    """Wire the input pipeline for a ship.  See test_fire_secondary_chain.py
    for the detailed rationale."""
    App.Game_GetCurrentPlayer = lambda: ship
    App.g_kInputManager.RegisterUnicodeKey(App.WC_LBUTTON, App.KY_LBUTTON, None, "LButton")
    App.g_kInputManager.RegisterUnicodeKey(App.WC_RBUTTON, App.KY_RBUTTON, None, "RButton")
    tcw = App.TacticalControlWindow_GetTacticalControlWindow()
    tcw.RemoveAllInstanceHandlers()
    App.g_kKeyboardBinding.SetDefaultDestination(tcw)
    import DefaultKeyboardBinding
    DefaultKeyboardBinding.Initialize()
    import TacticalInterfaceHandlers
    TacticalInterfaceHandlers.Initialize(tcw)


@pytest.fixture
def galaxy_red():
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

    App.g_kModelPropertyManager.ClearLocalTemplates()
    for k in list(sys.modules):
        if k == "ships" or k.startswith("ships."):
            del sys.modules[k]
    tcw = App.TacticalControlWindow_GetTacticalControlWindow()
    tcw.RemoveAllInstanceHandlers()
    from engine.core.game import Game_GetCurrentPlayer as _real_gcp
    App.Game_GetCurrentPlayer = _real_gcp


def test_six_right_clicks_fire_six_tubes(galaxy_red):
    """Six right-clicks at RED alert each decrement a different torpedo tube."""
    ship = galaxy_red
    torps = ship.GetTorpedoSystem()
    assert torps.GetNumWeapons() == 6, "Galaxy should have 6 torpedo tubes"
    initial = [torps.GetWeapon(i).GetNumReady() for i in range(6)]
    assert all(n == 1 for n in initial), f"All tubes should start ready, got: {initial}"

    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        for _ in range(6):
            App.g_kInputManager.OnKeyDown(App.WC_RBUTTON)
            App.g_kInputManager.OnKeyUp(App.WC_RBUTTON)

    after = [torps.GetWeapon(i).GetNumReady() for i in range(6)]
    assert after == [0, 0, 0, 0, 0, 0], (
        f"Expected all tubes empty after 6 shots, got: {after}"
    )


def test_seventh_click_is_silent_no_op(galaxy_red):
    """After all 6 tubes are empty the 7th right-click is a silent no-op:
    no tube count changes, no exception raised."""
    ship = galaxy_red
    torps = ship.GetTorpedoSystem()
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        # Empty all 6 tubes.
        for _ in range(6):
            App.g_kInputManager.OnKeyDown(App.WC_RBUTTON)
            App.g_kInputManager.OnKeyUp(App.WC_RBUTTON)
        after_6 = [torps.GetWeapon(i).GetNumReady() for i in range(6)]
        assert after_6 == [0, 0, 0, 0, 0, 0], f"Not all tubes emptied: {after_6}"

        # 7th click — no eligible emitter, should be silent.
        App.g_kInputManager.OnKeyDown(App.WC_RBUTTON)
        App.g_kInputManager.OnKeyUp(App.WC_RBUTTON)
        after_7 = [torps.GetWeapon(i).GetNumReady() for i in range(6)]

    assert after_7 == after_6, (
        f"7th click changed tube counts: before={after_6} after={after_7}"
    )
