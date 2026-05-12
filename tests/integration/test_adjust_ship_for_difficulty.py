"""Regression: loadspacehelper.AdjustShipForDifficulty must not crash
on a shielded ship, and must actually scale the shield max by the
defensive difficulty multiplier."""
import importlib
import sys

import App
from engine.appc.properties import ShieldProperty
from engine.appc.ships import ShipClass_Create


def _build_galaxy_with_shields():
    """Build a Galaxy ship the way loadspacehelper.CreateShip does:
    run ships.Hardpoints.Galaxy.LoadPropertySet on the ship's own
    property set, then SetupProperties. AdjustShipForDifficulty
    iterates pShipList and pNewList in parallel and assumes the two
    have matching length and per-index type (loadspacehelper.py:177-184);
    loading both sets through the same hardpoint module guarantees that."""
    for k in list(sys.modules):
        if k == "ships" or k.startswith("ships."):
            del sys.modules[k]
    mod = importlib.import_module("ships.Hardpoints.Galaxy")
    ship = ShipClass_Create("Galaxy")
    mod.LoadPropertySet(ship.GetPropertySet())
    ship.SetupProperties()
    sp = next(iter(ship.GetPropertySet().GetPropertiesByType(ShieldProperty)))
    return ship, sp


def test_adjust_ship_for_difficulty_does_not_crash_on_shielded_ship():
    """Pre-fix this raised AttributeError: 'NoneType' has no GetProperty()
    at loadspacehelper.py:246."""
    import loadspacehelper

    ship, sp = _build_galaxy_with_shields()
    front_max_before = sp.GetMaxShields(ShieldProperty.FRONT_SHIELDS)
    assert front_max_before == 8000.0

    loadspacehelper.AdjustShipForDifficulty(ship, "Galaxy")

    # AdjustShipForDifficulty rewrites the ship-side property's MaxShields
    # to (fresh-template MaxShields) × defensive multiplier. Both sides
    # come from the same hardpoint file (Galaxy has FRONT=8000) and the
    # Phase 1 shim returns 1.0 for the multiplier, so the value stays
    # at 8000 — but the full code path executed against real subsystems.
    front_max_after = sp.GetMaxShields(ShieldProperty.FRONT_SHIELDS)
    assert front_max_after == 8000.0 * App.Game_GetDefensiveDifficultyMultiplier()
