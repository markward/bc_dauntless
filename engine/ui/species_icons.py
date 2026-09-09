"""Species integer → TGA filename stem mapping.

The species integers used at runtime come from the hardpoint files
under sdk/Build/scripts/ships/Hardpoints/<ship>.py, where each ship
property calls SetSpecies(N) with the Appc-side species constant
(NOT the Multiplayer.SpeciesToShip enum — that's a separate
networking-only numbering). The values are organised by faction:

    100s — Federation
    200s — Cardassian
    300s — Romulan
    400s — Klingon
    500s — Kessok
    600s — Ferengi
    700s — Stations / utilities / asteroids

The icon filename for each species is whatever ShipIcons.py registers
under that key. ShipIcons.py uses App.SPECIES_* symbolic names (e.g.
SPECIES_GALAXY) but the underlying integers match the hardpoint
SetSpecies values one-to-one.

Used by ship_display_panel._species_key_for to turn the ShipClass's
GetSpecies() integer into the cache key consumed by ship_icons.
"""
from __future__ import annotations

from typing import Optional


_SPECIES_TO_STEM: dict[int, str] = {
    # Federation
    101: "Galaxy",
    102: "Sovereign",
    103: "Akira",
    104: "Ambassador",
    105: "Nebula",        # peregrine.py also uses 105 — both render as Nebula
    106: "FedShuttle",
    107: "Transport",
    108: "Freighter",

    # Cardassian
    201: "Galor",
    202: "Keldon",
    203: "CardFreighter",
    204: "Hybrid",        # cardhybrid → Hybrid.tga per ShipIcons.py

    # Romulan
    301: "Warbird",

    # Klingon
    401: "BirdOfPrey",
    402: "Vorcha",

    # Kessok
    501: "KessokHeavy",
    502: "KessokLight",   # KessokDestroyer also = 502
    503: "KessokMine",

    # Ferengi
    601: "Marauder",

    # Stations & utilities
    701: "FedStarbase",
    702: "FedOutpost",
    703: "CardStarbase",
    704: "CardOutpost",   # cardfacility.py also uses 704
    705: "CardStation",
    706: "DryDock",
    707: "SpaceFacility",
    708: "CommArray",     # commlight.py shares this slot
    710: "Probe",
    711: "ProbeType2",
    712: "Asteroid",
    713: "Sunbuster",
    714: "LifeBoat",      # EscapePod's TGA is named LifeBoat.tga
}


def stem_for_species(species: int) -> Optional[str]:
    """Returns the TGA filename stem for the given species int, or None
    if the species has no registered icon."""
    return _SPECIES_TO_STEM.get(int(species))


def stem_for_ship(ship) -> Optional[str]:
    """Icon stem for one ship: a Foundation ShipDef's authored `iconName`
    if it has one, else the species map above.

    The species is NOT a mod ship's artwork. `SetSpecies` drives faction,
    AI and networking behaviour, so mod hardpoints reuse a stock id --
    the LC Intrepid pack calls `SetSpecies(103)`, and 103 is Akira here,
    which is exactly why an Intrepid used to fly under an Akira
    silhouette. Foundation carries the icon separately in `iconName`, and
    a pack ships the matching TGA (`data/Icons/Ships/LCIntrepid.tga`),
    which the mod overlay places for `ship_icons` to find.

    No fall-through from a Foundation stem to the species: a mod that
    declares an `iconName` and ships no art gets no silhouette, the same
    as it would under Foundation. Falling back would put a stock ship's
    outline on a modded hull, which is the bug this replaced.
    """
    script = None
    getter = getattr(ship, "GetScript", None)
    if callable(getter):
        try:
            script = getter()
        except Exception:
            script = None
    if script:
        from engine.foundation.shipdef import icon_name_for_script
        icon = icon_name_for_script(script)
        if icon:
            return icon

    getter = getattr(ship, "GetSpecies", None)
    if not callable(getter):
        return None
    try:
        species = getter()
    except Exception:
        return None
    if not isinstance(species, int):
        return None
    return stem_for_species(species)
