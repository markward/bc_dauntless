"""A Foundation ship's icon comes from its authored `iconName`, not its species.

Mod ships routinely reuse a STOCK species id, because in BC `SetSpecies`
drives faction/AI behaviour and networking, not artwork. The LC Intrepid
pack is the measured case: `ships/Hardpoints/LCintrepidHP.py` calls
`LCIntrepidZZ.SetSpecies(103)`, and 103 IS Akira in the Appc species
numbering (engine/ui/species_icons.py). Resolving the silhouette from the
species therefore drew an Akira for the Intrepid.

Foundation's `iconName` is the authored override — the pack ships the
matching art at `data/Icons/Ships/LCIntrepid.tga` — so it must win over
the species map. Stock ships have no ShipDef and keep the species path.
"""

import pytest

from engine import foundation
from engine.foundation import quickbattle
from engine.foundation.shipdef import icon_name_for_script
from engine.ui.species_icons import stem_for_ship, stem_for_species


AKIRA_SPECIES = 103


class _FakeShip:
    """The two getters the resolver reads. `GetScript` returns the dotted
    module `loadspacehelper.CreateShip` stores via `pShip.SetScript`."""

    def __init__(self, script=None, species=AKIRA_SPECIES):
        self._script = script
        self._species = species

    def GetScript(self):
        return self._script

    def GetSpecies(self):
        return self._species


@pytest.fixture(autouse=True)
def _clean():
    foundation.reset()
    quickbattle.reset()
    yield
    foundation.reset()
    quickbattle.reset()


def _intrepid():
    return foundation.FedShipDef(
        "LCintrepidZZ", AKIRA_SPECIES,
        {"name": "USS Intrepid LC",
         "iconName": "LCintrepid",
         "shipFile": "LCintrepidZZ"})


def test_species_103_really_is_akira():
    # Guards the premise: if this ever stops being true the bug this file
    # describes no longer exists in the form described.
    assert stem_for_species(AKIRA_SPECIES) == "Akira"


def test_foundation_iconname_beats_the_species_map():
    _intrepid()
    ship = _FakeShip(script="ships.LCintrepidZZ", species=AKIRA_SPECIES)

    assert stem_for_ship(ship) == "LCintrepid"


def test_stock_ship_with_no_shipdef_still_uses_species():
    ship = _FakeShip(script="ships.Akira", species=AKIRA_SPECIES)

    assert stem_for_ship(ship) == "Akira"


def test_lookup_is_case_insensitive_and_strips_the_module_prefix():
    # Mod authors spell shipFile and the module inconsistently — the LC
    # pack itself ships iconName 'LCintrepid' against LCIntrepid.tga.
    _intrepid()

    assert icon_name_for_script("ships.lcintrepidzz") == "LCintrepid"
    assert icon_name_for_script("LCintrepidZZ") == "LCintrepid"
    assert icon_name_for_script("ships.Galaxy") is None
    assert icon_name_for_script("") is None
    assert icon_name_for_script(None) is None


def test_ship_missing_either_getter_degrades_quietly():
    _intrepid()

    assert stem_for_ship(object()) is None
    assert stem_for_ship(_FakeShip(script=None, species=AKIRA_SPECIES)) == "Akira"
    assert stem_for_ship(_FakeShip(script="ships.Nothing", species=99999)) is None
