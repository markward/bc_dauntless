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


def _target_ahead_of(ship, distance=100.0):
    """Build a fake target placed `distance` units ahead of the ship (+Y)."""
    from engine.appc.math import TGPoint3
    class _Target:
        def __init__(self, pos):
            self._pos = pos
        def GetWorldLocation(self):  return self._pos
        def IsDead(self):            return 0
    p = ship.GetWorldLocation()
    return _Target(TGPoint3(p.x, p.y + distance, p.z))


def test_holding_left_button_drains_one_phaser_bank(galaxy_in_red_alert):
    """Galaxy phasers are SingleFire(1): holding LBUTTON drains exactly
    one bank at a time.  After 10 ticks at dt=0.1 the active bank has
    lost ~1.0 charge; all other banks stay full."""
    ship = galaxy_in_red_alert
    phasers = ship.GetPhaserSystem()
    ship.SetTarget(_target_ahead_of(ship))

    starting = [phasers.GetWeapon(i).GetChargeLevel() for i in range(phasers.GetNumWeapons())]
    assert all(c == 5.0 for c in starting), f"Expected all full, got: {starting}"

    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        App.g_kInputManager.OnKeyDown(App.WC_LBUTTON)
        for _ in range(10):
            _advance_weapons([ship], dt=0.1)

    after = [phasers.GetWeapon(i).GetChargeLevel() for i in range(phasers.GetNumWeapons())]
    drained = [i for i, c in enumerate(after) if c < 5.0]
    assert len(drained) == 1, f"SingleFire expected 1 draining bank, got: {drained} levels={after}"
    # 10 ticks × 0.1s × 1.0 discharge/s = 1.0 charge → 5.0 - 1.0 = 4.0
    assert 3.5 < after[drained[0]] < 5.0, (
        f"Bank {drained[0]} charge outside expected range: {after[drained[0]]}"
    )


def test_release_left_button_stops_phaser(galaxy_in_red_alert):
    """SingleFire: after key-up the one active bank stops discharging."""
    ship = galaxy_in_red_alert
    phasers = ship.GetPhaserSystem()
    ship.SetTarget(_target_ahead_of(ship))
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        App.g_kInputManager.OnKeyDown(App.WC_LBUTTON)
        for _ in range(5):
            _advance_weapons([ship], dt=0.1)
        mid = [phasers.GetWeapon(i).GetChargeLevel() for i in range(phasers.GetNumWeapons())]
        firing_idxs = [i for i in range(phasers.GetNumWeapons()) if mid[i] < 5.0]
        assert len(firing_idxs) == 1, (
            f"SingleFire expected 1 bank draining after 5 held ticks, got: {firing_idxs}"
        )
        active = firing_idxs[0]
        assert phasers.GetWeapon(active)._firing is True

        App.g_kInputManager.OnKeyUp(App.WC_LBUTTON)
        assert phasers.GetWeapon(active)._firing is False, (
            f"Bank {active} should stop on key-up"
        )

        for _ in range(5):
            _advance_weapons([ship], dt=0.1)
        after = [phasers.GetWeapon(i).GetChargeLevel() for i in range(phasers.GetNumWeapons())]

    # After key-up the previously firing bank recharges (RechargeRate=0.08)
    # rather than continuing to drain.
    assert after[active] >= mid[active], (
        f"Bank {active} kept draining after key-up: mid={mid[active]:.3f} after={after[active]:.3f}"
    )
