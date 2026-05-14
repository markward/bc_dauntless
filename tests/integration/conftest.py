"""Shared fixtures for PR 2b integration tests.  Loads Galaxy + sets up
the input pipeline + a configurable target ship.
"""
import importlib
import sys

import pytest
import App
from engine.appc.ships import ShipClass, ShipClass_Create
from engine.appc.math import TGPoint3


def _setup_input_chain(ship):
    """Mirror _bootstrap_firing_pipeline + the RegisterUnicodeKey calls
    that KeyConfig.MapScancodes does in production."""
    App.Game_GetCurrentPlayer = lambda: ship

    # In production KeyConfig.MapScancodes() does this; tests inline it.
    App.g_kInputManager.RegisterUnicodeKey(App.WC_LBUTTON, App.KY_LBUTTON, None, "LButton")
    App.g_kInputManager.RegisterUnicodeKey(App.WC_RBUTTON, App.KY_RBUTTON, None, "RButton")

    tcw = App.TacticalControlWindow_GetTacticalControlWindow()
    # Reset to prevent duplicate handlers from prior fixture runs.
    tcw.RemoveAllInstanceHandlers()
    App.g_kKeyboardBinding.SetDefaultDestination(tcw)
    import DefaultKeyboardBinding
    DefaultKeyboardBinding.Initialize()
    import TacticalInterfaceHandlers
    TacticalInterfaceHandlers.Initialize(tcw)


def _load_galaxy_hardpoint(ship):
    App.g_kModelPropertyManager.ClearLocalTemplates()
    mod_name = "ships.Hardpoints.galaxy"
    if mod_name in sys.modules:
        importlib.reload(sys.modules[mod_name])
    else:
        importlib.import_module(mod_name)
    mod = sys.modules[mod_name]
    mod.LoadPropertySet(ship.GetPropertySet())
    ship.SetupProperties()
    return ship


@pytest.fixture
def galaxy_red():
    """Galaxy at RED alert with hardpoint loaded + input chain wired."""
    from engine.appc import projectiles, hit_vfx
    projectiles._active.clear()
    hit_vfx._active.clear()

    ship = ShipClass_Create("Galaxy")
    _load_galaxy_hardpoint(ship)
    _setup_input_chain(ship)
    ship.SetAlertLevel(ShipClass.RED_ALERT)
    ship.SetWorldLocation(TGPoint3(0, 0, 0))

    yield ship

    projectiles._active.clear()
    hit_vfx._active.clear()
    App.g_kModelPropertyManager.ClearLocalTemplates()
    for k in list(sys.modules):
        if k == "ships" or k.startswith("ships."):
            del sys.modules[k]
    tcw = App.TacticalControlWindow_GetTacticalControlWindow()
    tcw.RemoveAllInstanceHandlers()
    from engine.core.game import Game_GetCurrentPlayer as _real_gcp
    App.Game_GetCurrentPlayer = _real_gcp


@pytest.fixture
def target_ship_at():
    """Factory: returns a function that creates a stub target ship at a
    given world position with hull + optional shields.
    """
    def make(x, y, z, hull_max=10000.0, shields_strength=0.0, radius=20.0):
        from engine.appc.subsystems import HullSubsystem
        tgt = ShipClass_Create("Target")
        hull = HullSubsystem("Hull")
        hull.SetMaxCondition(hull_max)
        tgt._hull = hull
        tgt.SetWorldLocation(TGPoint3(x, y, z))
        tgt._radius = radius
        # Provide GetRadius accessor (some code paths read it).
        type(tgt).GetRadius = lambda self: self._radius
        if shields_strength > 0.0:
            from engine.appc.subsystems import ShieldSubsystem
            from engine.appc.properties import ShieldProperty
            shields = ShieldSubsystem("Shields")
            for f in range(ShieldProperty.NUM_SHIELDS):
                shields.SetMaxShields(f, shields_strength)
            tgt._shield_subsystem = shields
        return tgt
    return make
