"""A folded system's regions live in OTHER SDK folders than the system's
name (engine/systems/folds.py)."""
from engine.systems import folds


def test_an_ordinary_region_module_is_under_its_system():
    assert folds.region_module("Ona", "Ona1") == "Systems.Ona.Ona1"


def test_a_folded_region_module_is_under_its_own_folder():
    assert folds.region_module("TauCeti", "Starbase12") == "Systems.Starbase12.Starbase12"
    assert folds.region_module("TauCeti", "DryDock") == "Systems.DryDock.DryDock"
