"""End-to-end continuous fire: hold LBUTTON, run the tick loop, assert
the active phaser bank's charge drains.

Chain under test:
  g_kInputManager.OnKeyDown(WC_LBUTTON)
  → ET_INPUT_FIRE_PRIMARY(bFiring=1) → TCW → FirePrimaryWeapons
  → GetWeaponSystemGroup(WG_PRIMARY).StartFiring()
  → PhaserBank.Fire() → _is_firing = True
  _advance_weapons([ship], dt) → PhaserBank.UpdateCharge(dt) → charge drains

  g_kInputManager.OnKeyUp(WC_LBUTTON)
  → ET_INPUT_FIRE_PRIMARY(bFiring=0) → StopFiring() → _is_firing = False
  After key-up, _advance_weapons ticks recharge rather than discharge.
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
def galaxy_in_red_alert():
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


def test_holding_left_button_drains_phaser_charge(galaxy_in_red_alert):
    """Holding LBUTTON at RED alert and running 10 × dt=0.1 ticks drains one
    phaser bank.  Galaxy phasers: MaxCharge=5, NormalDischargeRate=1.0.
    After 10 ticks at dt=0.1 the firing bank loses 1.0 unit of charge
    (10 × 0.1 × 1.0).  The remaining 8 banks stay full."""
    ship = galaxy_in_red_alert
    phasers = ship.GetPhaserSystem()

    starting = [phasers.GetWeapon(i).GetChargeLevel() for i in range(phasers.GetNumWeapons())]
    assert all(c == 5.0 for c in starting), f"Expected all full, got: {starting}"

    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        App.g_kInputManager.OnKeyDown(App.WC_LBUTTON)
        # Simulate 10 frames at dt=0.1 each.  NormalDischargeRate=1.0 so
        # each tick removes charge_level × 1.0 × 0.1 = 0.5 (half of
        # GetChargeLevel() × rate × dt from one bank).
        for _ in range(10):
            _advance_weapons([ship], dt=0.1)

    after = [phasers.GetWeapon(i).GetChargeLevel() for i in range(phasers.GetNumWeapons())]
    drained = [i for i, c in enumerate(after) if c < 5.0]
    # Exactly one bank should be draining (Galaxy is SetSingleFire(1)).
    assert len(drained) == 1, f"Expected 1 draining bank, got: {drained} levels={after}"
    # Charge should have dropped but not depleted below MinFiringCharge=3.0
    # (we only ran 10 ticks × 0.1 dt which drains at most 1.0 unit).
    assert 3.5 < after[drained[0]] < 5.0, (
        f"Charge outside expected range: {after[drained[0]]}"
    )


def test_release_left_button_stops_phaser(galaxy_in_red_alert):
    """After key-up, the phaser bank stops discharging and starts recharging."""
    ship = galaxy_in_red_alert
    phasers = ship.GetPhaserSystem()
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        App.g_kInputManager.OnKeyDown(App.WC_LBUTTON)
        for _ in range(5):
            _advance_weapons([ship], dt=0.1)
        mid = [phasers.GetWeapon(i).GetChargeLevel() for i in range(phasers.GetNumWeapons())]

        # Identify the bank that was actively discharging.
        firing_bank_idx = next(
            (i for i in range(phasers.GetNumWeapons()) if mid[i] < 5.0),
            None,
        )
        assert firing_bank_idx is not None, "No bank drained after 5 ticks with LBUTTON held"
        assert phasers.GetWeapon(firing_bank_idx)._firing is True

        App.g_kInputManager.OnKeyUp(App.WC_LBUTTON)
        # Direct check: the bank's _firing must flip to False.
        assert phasers.GetWeapon(firing_bank_idx)._firing is False

        for _ in range(5):
            _advance_weapons([ship], dt=0.1)
        after = [phasers.GetWeapon(i).GetChargeLevel() for i in range(phasers.GetNumWeapons())]

    # After key-up the bank recharges (RechargeRate=0.08) rather than
    # continuing to drain.  Level must be >= mid-point level.
    assert after[firing_bank_idx] >= mid[firing_bank_idx], (
        f"Bank {firing_bank_idx} kept draining after key-up: "
        f"mid={mid[firing_bank_idx]:.3f} after={after[firing_bank_idx]:.3f}"
    )
