"""Systems BC splits across several SDK folders.

Almost every system is one folder, Systems/<System>/, whose head script
<System>.py builds its CreateSystemMenu and whose region modules are
Systems.<System>.<Region>. Tau Ceti is the exception: BC ships its two places
as two folders, each a one-region "system" with its own menu script --
Systems/Starbase12/Starbase.py and Systems/DryDock/DryDockSystem.py -- and
never groups them. They are one system here (Dry Dock's planet is "Tau Ceti
Prime", both suns are SunBlueWhite, and engine/appc/sector_model.py already
folds both onto the star map's `tauceti`).

FOLDED is the one authority for that. Its system name lower-cases to the
sector model's id, so the map file (tauceti.json) and the star-map entry
agree. Each member is (folder, menu script stem); the folder's region module
is Systems.<folder>.<region>.
"""
from __future__ import annotations

FOLDED: dict = {
    "TauCeti": (("Starbase12", "Starbase"), ("DryDock", "DryDockSystem")),
}


def members(system: str):
    """[(folder, menu script stem)] for a folded system, else None."""
    return FOLDED.get(system)


def folded_folders() -> set:
    """Every SDK folder that belongs to a folded system -- never a system of
    its own."""
    return {folder for parts in FOLDED.values() for folder, _ in parts}


def region_module(system: str, region: str) -> str:
    """The module that builds `region`'s set: Systems.<folder>.<region>, where
    the folder is the system's own unless the system is folded."""
    for folder, _menu in FOLDED.get(system, ()):
        if folder == region:
            return f"Systems.{folder}.{region}"
    return f"Systems.{system}.{region}"
