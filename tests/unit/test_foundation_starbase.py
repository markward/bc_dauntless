"""Foundation.ShipDef as a base class, Foundation's race objects, and the
StarBaseDef family.

Real mods use Foundation.ShipDef two ways at once: as the namespace ships
are registered on (`Foundation.ShipDef.X = ...`, and Bridge Commander
Universal Tool scripts write `Foundation.ShipDef.__dict__[name]` directly)
and as the base class new definition kinds derive from
(`class RomulanStarBaseDef(Foundation.ShipDef)`). Every fixture is our own
code, written to those call shapes; no mod content.
"""
import pytest

import Foundation
from engine import foundation
from engine.foundation import quickbattle, shipdef

from tests.unit.test_foundation_quickbattle import _FakeQB


@pytest.fixture(autouse=True)
def _clean():
    foundation.reset()
    quickbattle.reset()
    yield
    foundation.reset()
    quickbattle.reset()


def _details(name="Outpost"):
    return {"name": name, "iconName": name, "shipFile": name}


# -- ShipDef: namespace and base class at once -------------------------------

def test_a_mod_can_subclass_shipdef_and_register_on_it():
    class RaiderBaseDef(Foundation.ShipDef):
        def __init__(self, abbrev, species, dict):
            dict["race"] = Foundation.Romulan
            Foundation.ShipDef.__init__(self, abbrev, species, dict)

        def StrEnemyAI(self):
            return "StarbaseAI"

    Foundation.ShipDef.Raider = RaiderBaseDef("Raider", 7, _details("Raider"))

    d = Foundation.ShipDef.Raider
    assert (d.abbrev, d.species, d.name, d.shipFile) == ("Raider", 7, "Raider", "Raider")
    assert d.race == "Romulan" and d.race.name == "Romulan"
    assert d.StrEnemyAI() == "StarbaseAI"
    assert d in shipdef.all_definitions()


def test_shipdef_dict_is_the_writable_registry_generated_scripts_use():
    d = Foundation.FedShipDef("Long", 1, _details("Long Name"))
    Foundation.ShipDef.__dict__["Long Name"] = d
    assert Foundation.ShipDef.__dict__["Long Name"] is d
    assert getattr(Foundation.ShipDef, "Long Name") is d
    Foundation.ShipDef.Short = d
    assert vars(Foundation.ShipDef) == {"Long Name": d, "Short": d}


def test_reset_clears_registered_ships_but_keeps_the_class():
    Foundation.ShipDef.Gone = Foundation.FedShipDef("Gone", 1, _details("Gone"))
    foundation.reset()
    assert not hasattr(Foundation.ShipDef, "Gone")
    assert vars(Foundation.ShipDef) == {}
    assert callable(Foundation.ShipDef.RegisterQBShipMenu)


def test_a_shipdef_built_directly_reads_its_race_from_the_dict():
    d = Foundation.ShipDef("Plain", 3, dict(_details("Plain"), race=Foundation.Klingon))
    assert d.race == "Klingon"
    assert Foundation.ShipDef("NoRace", 3, _details("NoRace")).race is None


# -- race objects ------------------------------------------------------------

@pytest.mark.parametrize("attr, abbrev, name", [
    ("Federation", "Fed", "Federation"),
    ("Cardassian", "Card", "Cardassian"),
    ("Klingon", "Klingon", "Klingon"),
    ("Romulan", "Romulan", "Romulan"),
    ("Ferengi", "Ferengi", "Ferengi"),
    ("Kessok", "Kessok", "Kessok"),
    ("Dominion", "Dom", "Dominion"),
    ("Breen", "Breen", "Breen"),
    ("Borg", "Borg", "Borg"),
])
def test_foundations_race_objects(attr, abbrev, name):
    race = getattr(Foundation, attr)
    assert (str(race), race.abbrev, race.name) == (abbrev, abbrev, name)


def test_the_fed_factory_and_the_federation_object_agree():
    assert Foundation.FedShipDef("F", 1, _details("F")).race == Foundation.Federation


# -- StarBaseDef -------------------------------------------------------------

@pytest.mark.parametrize("factory, race", [
    ("StarBaseDef", "Federation"),
    ("CardStarBaseDef", "Cardassian"),
])
def test_starbase_defs_are_stations_with_bcs_starbase_ai(factory, race):
    d = getattr(Foundation, factory)("SB", 9, _details("Station"))
    assert d.race.name == race
    assert (d.StrFriendlyAI(), d.StrEnemyAI()) == ("StarbaseFriendlyAI", "StarbaseAI")


def test_a_plain_ship_keeps_quick_battles_ship_ai():
    d = Foundation.FedShipDef("Ship", 1, _details("Ship"))
    assert (d.StrFriendlyAI(), d.StrEnemyAI()) == ("QuickBattleFriendlyAI", "QuickBattleAI")


def test_a_starbase_can_be_assigned_onto_starbasedef_itself():
    # Seen in real ship scripts: the definition assigned onto the factory
    # rather than onto ShipDef. Foundation's StarBaseDef is a class, so this
    # works there and must here.
    Foundation.StarBaseDef.Depot = Foundation.StarBaseDef("Depot", 9, _details("Depot"))
    assert Foundation.StarBaseDef.Depot.name == "Depot"


def test_starbase_quick_battle_rows_name_bcs_starbase_ai():
    qb = _FakeQB()
    base = Foundation.StarBaseDef("SB", 9, _details("Mod Starbase"))
    ship = Foundation.FedShipDef("Ship", 1, _details("Mod Ship"))
    sb_id = base.RegisterQBShipMenu("Stations", qb=qb)
    ship_id = ship.RegisterQBShipMenu("Fed Ships", qb=qb)

    assert qb.g_dFriendlyShipTypeToDetails[sb_id][3] == "StarbaseFriendlyAI"
    assert qb.g_dEnemyShipTypeToDetails[sb_id][3] == "StarbaseAI"
    assert qb.g_dFriendlyShipTypeToDetails[ship_id][3] == "QuickBattleFriendlyAI"
    assert qb.g_dEnemyShipTypeToDetails[ship_id][3] == "QuickBattleAI"


def test_a_subclass_ai_override_reaches_quick_battle():
    class GuardDef(Foundation.ShipDef):
        def StrEnemyAI(self):
            return "StarbaseAI"

    qb = _FakeQB()
    sid = GuardDef("G", 1, _details("Guard")).RegisterQBShipMenu("X", qb=qb)
    assert qb.g_dEnemyShipTypeToDetails[sid][3] == "StarbaseAI"
    assert qb.g_dFriendlyShipTypeToDetails[sid][3] == "QuickBattleFriendlyAI"
