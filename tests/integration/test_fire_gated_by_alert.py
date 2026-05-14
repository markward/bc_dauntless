"""End-to-end gating: same Galaxy + LBUTTON / RBUTTON sequences at GREEN
alert should not drain any charge, not flip any bank to firing, and
should not decrement any torpedo tube.

GREEN alert calls TurnOff() on all weapon systems, so WeaponSystem.StartFiring
returns immediately because IsOn() → False.
"""
import importlib
import sys
from unittest.mock import patch

import pytest

import App
from engine.appc.ships import ShipClass, ShipClass_Create
from engine.host_loop import _advance_weapons


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
def galaxy_at_green_alert():
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
    ship.SetAlertLevel(ShipClass.GREEN_ALERT)

    yield ship

    App.g_kModelPropertyManager.ClearLocalTemplates()
    for k in list(sys.modules):
        if k == "ships" or k.startswith("ships."):
            del sys.modules[k]
    tcw = App.TacticalControlWindow_GetTacticalControlWindow()
    tcw.RemoveAllInstanceHandlers()
    from engine.core.game import Game_GetCurrentPlayer as _real_gcp
    App.Game_GetCurrentPlayer = _real_gcp


def test_left_click_at_green_does_not_drain_charge(galaxy_at_green_alert):
    """Holding LBUTTON at GREEN alert leaves all phaser banks at full charge."""
    ship = galaxy_at_green_alert
    phasers = ship.GetPhaserSystem()
    starting = [phasers.GetWeapon(i).GetChargeLevel() for i in range(phasers.GetNumWeapons())]

    with patch("engine.audio.tg_sound.TGSoundManager.instance") as mock_mgr:
        App.g_kInputManager.OnKeyDown(App.WC_LBUTTON)
        for _ in range(10):
            _advance_weapons([ship], dt=0.1)
        # SFX should never be triggered since no weapon fired.
        mock_mgr.return_value.PlaySound.assert_not_called()

    after = [phasers.GetWeapon(i).GetChargeLevel() for i in range(phasers.GetNumWeapons())]
    assert after == starting, (
        f"Phaser charge changed at GREEN alert: before={starting} after={after}"
    )


def test_right_click_at_green_does_not_decrement_torpedoes(galaxy_at_green_alert):
    """Right-clicking at GREEN alert leaves torpedo tubes untouched."""
    ship = galaxy_at_green_alert
    torps = ship.GetTorpedoSystem()
    starting = [torps.GetWeapon(i).GetNumReady() for i in range(torps.GetNumWeapons())]

    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        App.g_kInputManager.OnKeyDown(App.WC_RBUTTON)
        App.g_kInputManager.OnKeyUp(App.WC_RBUTTON)

    after = [torps.GetWeapon(i).GetNumReady() for i in range(torps.GetNumWeapons())]
    assert after == starting, (
        f"Torpedo counts changed at GREEN alert: before={starting} after={after}"
    )
