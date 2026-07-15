"""End-to-end torpedo trigger under the BC weapon tick: Galaxy has 4
forward + 2 aft torpedo tubes, authored SetSingleFire(0) and firing chain
"Single" = group 0 (all weapons).  One right-click therefore fires EVERY
ready tube in the same tick — all 6, aft included, since the tick carries
no per-tube direction gate yet.

This is the task's transitional state, pinned deliberately: Task 7 adds
BC's ship-wide 0.5 s launch stagger (one tube per tick, walk-out under a
held trigger) and the per-tube ±30° launch cone (which blocks the aft
tubes at a forward aim), restoring the audited BC behaviour.  Update these
assertions there.
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


def test_one_click_fires_all_ready_tubes(galaxy_red):
    """SetSingleFire(0) + chain "Single" (group 0 = all weapons): one click
    empties every ready tube in the same tick — all 6 (Task 7's stagger +
    launch cone will shrink this back to one forward tube per tick)."""
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
        App.g_kInputManager.OnKeyDown(App.WC_RBUTTON)
        App.g_kInputManager.OnKeyUp(App.WC_RBUTTON)

    after = [torps.GetWeapon(i).GetNumReady() for i in range(6)]
    assert after == [0] * 6, (
        f"One click should empty every ready tube, got: {after}"
    )


def test_click_with_empty_tubes_is_silent(galaxy_red):
    """Once every tube is drained the next right-click finds no eligible
    emitter (per-tube CanFire: NumReady == 0, 40 s reload pending) and is a
    silent no-op — tube counts must not change and nothing raises."""
    ship = galaxy_red
    torps = ship.GetTorpedoSystem()
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        App.g_kInputManager.OnKeyDown(App.WC_RBUTTON)
        App.g_kInputManager.OnKeyUp(App.WC_RBUTTON)
        before = [torps.GetWeapon(i).GetNumReady() for i in range(6)]
        assert before == [0] * 6

        App.g_kInputManager.OnKeyDown(App.WC_RBUTTON)
        App.g_kInputManager.OnKeyUp(App.WC_RBUTTON)
        after = [torps.GetWeapon(i).GetNumReady() for i in range(6)]

    assert after == before, (
        f"Click with empty tubes changed counts: before={before} after={after}"
    )
