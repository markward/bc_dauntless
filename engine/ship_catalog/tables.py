"""Display tables for ship metadata: eras, roles, stock species.

Pure constants. Mod files name eras and roles by ID only, so names, tags and
years can change here without touching any mod. Insignia paths are NOT here:
they resolve at use (catalog.insignia_path), never at import.

Spec: docs/superpowers/specs/2026-10-01-ship-metadata-catalog-design.md §4.1
"""
from __future__ import annotations

from collections import namedtuple

Era = namedtuple("Era", "id name tag start end")

ERAS = (
    Era("ENT", "Pre Federation", "ENT", 2140, 2240),
    Era("TOS", "Early Federation", "TOS", 2240, 2293),
    Era("MOV", "Expansion Era", "MOV", 2293, 2330),
    Era("TNG", "High Era", "TNG", 2330, 2367),
    Era("DS9", "Quadrant Wars", "DS9 · VOY", 2367, 2399),
    Era("PIC", "Romulan Vacuum", "PIC", 2399, 2499),
    Era("DISC", "Distant Future", "DISC", 2500, 3200),
)
ERA_IDS = tuple(e.id for e in ERAS)
ALL_ERAS = "all"
DEFAULT_ERAS = ("DS9",)          # BC is set after the Dominion War

Role = namedtuple("Role", "id label")

ROLES = (
    Role("tactical", "Tactical"),
    Role("auxiliary", "Auxiliary"),
    Role("station", "Station"),
    Role("automated", "Automated / Unmanned"),
)
ROLE_IDS = tuple(r.id for r in ROLES)

# insignia is a Path or None; always None here, filled by catalog.species().
Species = namedtuple("Species", "name flagship insignia")

STOCK_SPECIES = (
    Species("Federation", "Sovereign", None),
    Species("Klingon", "Vorcha", None),
    Species("Romulan", "Warbird", None),
    Species("Cardassian", "Keldon", None),
    Species("Ferengi", "Marauder", None),
    Species("Kessok", "KessokHeavy", None),
    Species("Civilian", "Freighter", None),
    Species("Neutral", "Asteroid", None),
)

MANDATORY = ("era", "role", "playable", "title", "species")
