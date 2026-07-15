"""End-to-end torpedo trigger under the BC weapon tick: Galaxy has 4
forward + 2 aft torpedo tubes, authored SetSingleFire(0) and firing chain
"Single" = group 0 (all weapons).

Task 7 adds BC's ship-wide 0.5s launch stagger: a single trigger press only
ever launches ONE tube (the first ready one in the round-robin working
group) — every other ready tube's CanFire() fails the stagger gate within
the same tick (gameTime delta is 0).  Sequential presses spaced past 0.5s
of game time walk out across the remaining tubes (round-robin advance via
_last_weapon_idx), restoring BC's audited one-per-tick walk-out.  This
file's tests never lock a target (ship._target stays None throughout — see
TacticalInterfaceHandlers.FireWeapons's ``pShip.GetTarget()`` call site),
so every shot takes the dumbfire path and the ±30 degree cone never
applies here.
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
    App.g_kTimerManager._time = 0.0

    yield ship

    App.g_kTimerManager._time = 0.0
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


def test_one_click_fires_exactly_one_tube(galaxy_red):
    """Task 7 ship-wide stagger: one press+release only ever launches ONE
    tube — every other ready tube's CanFire() fails the stagger gate at the
    same instant (gameTime delta is 0 within the single StartFiring call)."""
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
    assert after.count(0) == 1 and sum(after) == 5, (
        f"One click should empty exactly one tube, got: {after}"
    )


def test_sequential_clicks_beyond_the_stagger_walk_out_every_tube(galaxy_red):
    """Presses spaced past the 0.5s ship-wide stagger walk sequentially
    through the ready tubes (round-robin advance via _last_weapon_idx,
    BC's per-tick walk-out) until all 6 have fired."""
    ship = galaxy_red
    torps = ship.GetTorpedoSystem()

    for _ in range(6):
        with patch("engine.audio.tg_sound.TGSoundManager.instance"):
            App.g_kInputManager.OnKeyDown(App.WC_RBUTTON)
            App.g_kInputManager.OnKeyUp(App.WC_RBUTTON)
        App.g_kTimerManager._time = App.g_kTimerManager.get_time() + 0.6

    after = [torps.GetWeapon(i).GetNumReady() for i in range(6)]
    assert after == [0] * 6, f"6 spaced clicks should drain every tube, got: {after}"


def test_quad_chain_fans_forward_tubes_single_restores_walkout(galaxy_red):
    """2026-07-15 decomp update (BC-intended spread<->skew wire): cycling the
    tactical spread selector to 'Quad' arms skew fire on every tube (this
    task's ``TorpedoSystem.SetFiringChainMode`` override), so one click
    launches all 4 forward tubes (Galaxy's group 5) simultaneously instead of
    BC's shipped one-per-click walk-out; cycling back to 'Single' clears
    skew and restores the original one-click-one-tube behaviour asserted by
    ``test_one_click_fires_exactly_one_tube`` above (that test is untouched
    and must keep passing unchanged — Galaxy defaults to chain mode 0 =
    "Single", so nothing here calls SetFiringChainMode before it runs)."""
    ship = galaxy_red
    torps = ship.GetTorpedoSystem()
    assert torps.GetFiringChainMode() == 0        # Galaxy defaults to "Single"
    assert all(torps.GetWeapon(i).IsSkewFire() == 0 for i in range(6))

    from engine.appc import weapon_config
    weapon_config.cycle_torpedo_spread(ship)       # Single -> Dual
    weapon_config.cycle_torpedo_spread(ship)       # Dual -> Quad
    assert torps.GetFiringChainMode() == 2
    assert all(torps.GetWeapon(i).IsSkewFire() == 1 for i in range(6))

    fwd = _forward_indices(torps)
    aft = _aft_indices(torps)

    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        App.g_kInputManager.OnKeyDown(App.WC_RBUTTON)
        App.g_kInputManager.OnKeyUp(App.WC_RBUTTON)

    after = [torps.GetWeapon(i).GetNumReady() for i in range(6)]
    assert all(after[i] == 0 for i in fwd), (
        f"Quad's group 5 (all 4 forward tubes) must launch simultaneously, got: {after}"
    )
    assert all(after[i] == 1 for i in aft), (
        f"aft tubes are a separate chain group -- untouched by this click, got: {after}"
    )

    weapon_config.cycle_torpedo_spread(ship)       # Quad -> wraps to Single
    assert torps.GetFiringChainMode() == 0
    assert all(torps.GetWeapon(i).IsSkewFire() == 0 for i in range(6))

    App.g_kTimerManager._time = App.g_kTimerManager.get_time() + 0.6
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        App.g_kInputManager.OnKeyDown(App.WC_RBUTTON)
        App.g_kInputManager.OnKeyUp(App.WC_RBUTTON)

    after2 = [torps.GetWeapon(i).GetNumReady() for i in range(6)]
    drained_this_click = sum(1 for b, a in zip(after, after2) if b != a)
    assert drained_this_click == 1, (
        f"Single restores the shipped one-click-one-tube walk-out, got: {after} -> {after2}"
    )


def test_click_with_empty_tubes_is_silent(galaxy_red):
    """Once every tube is drained (via spaced clicks, past the stagger) the
    next right-click finds no eligible emitter (per-tube CanFire: NumReady
    == 0, 40 s reload pending) and is a silent no-op — tube counts must not
    change and nothing raises."""
    ship = galaxy_red
    torps = ship.GetTorpedoSystem()
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        for _ in range(6):
            App.g_kInputManager.OnKeyDown(App.WC_RBUTTON)
            App.g_kInputManager.OnKeyUp(App.WC_RBUTTON)
            App.g_kTimerManager._time = App.g_kTimerManager.get_time() + 0.6
        before = [torps.GetWeapon(i).GetNumReady() for i in range(6)]
        assert before == [0] * 6

        App.g_kInputManager.OnKeyDown(App.WC_RBUTTON)
        App.g_kInputManager.OnKeyUp(App.WC_RBUTTON)
        after = [torps.GetWeapon(i).GetNumReady() for i in range(6)]

    assert after == before, (
        f"Click with empty tubes changed counts: before={before} after={after}"
    )
