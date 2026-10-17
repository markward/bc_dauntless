"""Inert, always-on MutatorDef + Race.name (spec 2026-10-16 §6.1, §8.6)."""
import pytest

import Foundation
from engine import foundation


@pytest.fixture(autouse=True)
def _reset():
    foundation.reset()
    yield
    foundation.reset()


def test_mutatordef_is_always_enabled():
    m = Foundation.MutatorDef("My Mod")
    assert m.name == "My Mod"
    assert m.IsEnabled() == 1
    m.Disable()
    m.Deactivate()
    assert m.IsEnabled() == 1


def test_standard_instances_exist():
    for attr in ("Stock", "StockSounds", "StockShips", "QuickBattle"):
        assert isinstance(getattr(Foundation.MutatorDef, attr), Foundation.MutatorDef)


def test_mods_may_attach_attributes():
    mode = Foundation.MutatorDef("NanoFX v2.0 BETA")
    Foundation.MutatorDef.SomeMod = mode
    mode.bBase = 1
    assert Foundation.MutatorDef.SomeMod.bBase == 1
    del Foundation.MutatorDef.SomeMod


def test_mode_dict_accepted_by_defs():
    mode = Foundation.MutatorDef("X")
    d = Foundation.FedShipDef("Foo", 1, {"name": "Foo"}, {"modes": [mode]})
    assert d.race == "Fed"


def test_race_name_long_form():
    d = Foundation.FedShipDef("Foo", 1, {"name": "Foo"})
    assert d.race == "Fed" and d.race.name == "Federation"
    k = Foundation.KlingonShipDef("Bar", 1, {"name": "Bar"})
    assert k.race.name == "Klingon"
