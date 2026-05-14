"""End-to-end sequential firing with direction gating: Galaxy has 4
forward + 2 aft torpedo tubes.  With no target locked, StartFiring
aims along the ship's body +Y axis, so only the 4 forward tubes (whose
SetDirection is +Y) are eligible — the 2 aft tubes (-Y) are skipped.

After 4 right-clicks the forward tubes are empty and subsequent clicks
are silent no-ops.  The aft tubes never fire in this scenario; they'd
fire only when the aim direction points astern (target behind the ship).
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


def _forward_indices(torps):
    """Indices whose tube SetDirection has positive body-Y (forward-firing)."""
    return [i for i in range(torps.GetNumWeapons())
            if torps.GetWeapon(i).GetDirection().y > 0]


def _aft_indices(torps):
    """Indices whose tube SetDirection has negative body-Y (aft-firing)."""
    return [i for i in range(torps.GetNumWeapons())
            if torps.GetWeapon(i).GetDirection().y < 0]


def test_four_clicks_drain_forward_tubes_only(galaxy_red):
    """With no target locked the aim direction is the ship's body +Y axis,
    so only the 4 forward tubes are eligible.  4 clicks empty them; the
    2 aft tubes remain loaded."""
    ship = galaxy_red
    torps = ship.GetTorpedoSystem()
    assert torps.GetNumWeapons() == 6, "Galaxy should have 6 torpedo tubes"
    fwd = _forward_indices(torps)
    aft = _aft_indices(torps)
    assert len(fwd) == 4 and len(aft) == 2, (
        f"Expected 4 forward + 2 aft tubes, got fwd={fwd} aft={aft}"
    )

    initial = [torps.GetWeapon(i).GetNumReady() for i in range(6)]
    assert all(n == 1 for n in initial), f"All tubes should start ready, got: {initial}"

    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        for _ in range(4):
            App.g_kInputManager.OnKeyDown(App.WC_RBUTTON)
            App.g_kInputManager.OnKeyUp(App.WC_RBUTTON)

    after = [torps.GetWeapon(i).GetNumReady() for i in range(6)]
    assert all(after[i] == 0 for i in fwd), (
        f"Forward tubes should be empty after 4 shots, got: {after} (fwd={fwd})"
    )
    assert all(after[i] == 1 for i in aft), (
        f"Aft tubes should still be loaded, got: {after} (aft={aft})"
    )


def test_fifth_click_with_empty_forward_tubes_is_silent(galaxy_red):
    """Once the 4 forward tubes are drained the 5th right-click finds no
    eligible emitter (aft tubes face the wrong way) and is a silent
    no-op — aft tube counts must not change."""
    ship = galaxy_red
    torps = ship.GetTorpedoSystem()
    aft = _aft_indices(torps)
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        for _ in range(4):
            App.g_kInputManager.OnKeyDown(App.WC_RBUTTON)
            App.g_kInputManager.OnKeyUp(App.WC_RBUTTON)
        before = [torps.GetWeapon(i).GetNumReady() for i in range(6)]

        App.g_kInputManager.OnKeyDown(App.WC_RBUTTON)
        App.g_kInputManager.OnKeyUp(App.WC_RBUTTON)
        after = [torps.GetWeapon(i).GetNumReady() for i in range(6)]

    assert after == before, (
        f"5th click changed tube counts: before={before} after={after}"
    )
    assert all(after[i] == 1 for i in aft), (
        f"Aft tubes must remain loaded, got: {after} (aft={aft})"
    )
