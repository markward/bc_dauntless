"""Which factions have a standing home station in each charted system.

The star map's faction icons read this (Mark, 2026-10-25): presence is
stations only, a station's faction is its ship script's species in the ship
catalog, and a station with none (Biranu's, which BC lists Neutral) adds
nothing. A faction leaves a system once every one of its stations there is
destroyed (`home_stations.is_standing`).
"""
from __future__ import annotations

from engine.appc import sector_model as sm
from engine.systems import home_stations

FIRST = "Federation"
NEUTRAL = "Neutral"


def _faction_of_script(script: str):
    from engine.ship_catalog import entry
    e = entry(script)
    return e.species if e is not None else None


def _order(factions) -> tuple:
    return tuple(sorted(factions, key=lambda f: (f != FIRST, f.lower())))


def factions_by_system() -> dict:
    """{system id: factions, Federation first then alphabetical}. Systems
    with no faction are absent. One bad row is skipped, never fatal."""
    found: dict = {}
    for row in home_stations.table():
        if not home_stations.is_standing(row):
            continue
        try:
            faction = _faction_of_script(row.script)
        except Exception:  # noqa: BLE001 -- decoration: costs only this row
            continue
        if not faction or faction == NEUTRAL:
            continue
        found.setdefault(sm.system_id_for_set(row.set_name), set()).add(faction)
    return {sid: _order(f) for sid, f in found.items()}
