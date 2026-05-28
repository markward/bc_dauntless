"""Species integer → TGA filename stem mapping.

Mirrors the loader at sdk/Build/scripts/Icons/ShipIcons.py:LoadShipIcons,
which keys ship icons by `App.SPECIES_*` (Appc-side integers identical
to sdk/Build/scripts/Multiplayer/SpeciesToShip.py). Each entry maps a
species int to the TGA filename stem under game/data/Icons/Ships/.

Used by ship_display_panel._species_key_for to turn the ShipClass's
GetSpecies() integer into the cache key consumed by ship_icons.
"""
from __future__ import annotations

from typing import Optional


# Source of truth: sdk/Build/scripts/Multiplayer/SpeciesToShip.py
# (constants) paired with sdk/Build/scripts/Icons/ShipIcons.py
# (filename stems).
_SPECIES_TO_STEM: dict[int, str] = {
    1:  "Akira",
    2:  "Ambassador",
    3:  "Galaxy",
    4:  "Nebula",
    5:  "Sovereign",
    6:  "BirdOfPrey",
    7:  "Vorcha",
    8:  "Warbird",
    9:  "Marauder",
    10: "Galor",
    11: "Keldon",
    12: "Hybrid",
    13: "KessokHeavy",
    14: "KessokLight",
    15: "FedShuttle",
    16: "CardFreighter",
    17: "Freighter",
    18: "Transport",
    19: "SpaceFacility",
    20: "CommArray",
    21: "CommLight",
    22: "DryDock",
    23: "Probe",
    25: "Sunbuster",
    26: "CardOutpost",
    27: "CardStarbase",
    28: "CardStation",
    29: "FedOutpost",
    30: "FedStarbase",
    31: "Asteroid",
    43: "LifeBoat",
    44: "KessokMine",
}


def stem_for_species(species: int) -> Optional[str]:
    """Returns the TGA filename stem for the given species int, or None
    if the species has no registered icon (UNKNOWN, DECOY, ASTEROIDh,
    etc.).
    """
    return _SPECIES_TO_STEM.get(int(species))
