"""Resolve a BC set name to the system and region it belongs to.

Every checked-in system map (engine/systems/maps/*.json) places BC's
original sets as regions anchored in one coordinate space per system. This
module is the first thing that reads those maps: given a set name, it
answers which system it is in and which region.

A set absent from every map -- the bridge, QuickBattle arenas, and the
seven single-set multiplayer systems (whose maps carry zero regions) --
resolves to None, and its caller must behave exactly as it does today.

The index is built once, lazily, from engine.systems.map.available() /
load(), and cached with functools.lru_cache. Never capture a path at
import: map_dir() is computed per call inside engine.systems.map, so this
module never touches a path itself, only the already-lazy map API.
"""
from __future__ import annotations

import functools

from engine.systems import map as system_map


@functools.lru_cache(maxsize=None)
def _index() -> tuple[dict, dict]:
    """Build the set_name -> (SystemMap, Region) index and the
    system_name -> [set_name, ...] index, in map order."""
    by_set: dict = {}
    regions_by_system: dict = {}
    for name in system_map.available():
        m = system_map.load(name)
        region_names = []
        for r in m.regions:
            by_set[r.set_name] = (m, r)
            region_names.append(r.set_name)
        regions_by_system[m.system] = region_names
    return by_set, regions_by_system


def reset_cache() -> None:
    """Drop the cached index so the next call rebuilds it. For tests."""
    _index.cache_clear()


def for_set(set_name: str):
    """(SystemMap, Region) for the set, or None if it is not a region of
    any checked-in map."""
    by_set, _ = _index()
    return by_set.get(set_name)


def system_of(set_name: str) -> str | None:
    """The system's name for the set, or None."""
    found = for_set(set_name)
    return found[0].system if found is not None else None


def regions_of(system: str) -> list:
    """Every region set name in that system, in map order. Empty list if
    the system is unknown."""
    _, regions_by_system = _index()
    return list(regions_by_system.get(system, []))
