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

for_set() hands back dataclasses.replace() copies, not the cached
SystemMap/Region instances. map.load() re-parses JSON on every call today,
so two callers never share an instance -- returning the raw cached objects
here would be a behaviour change: a caller mutating a field (e.g.
`r.anchor_gu = adjusted`) would silently corrupt the index for every later
caller in the process. The copy is shallow -- nested lists such as
`m.bodies`/`m.regions`/`r.body_names` are still shared with the cache -- so
this protects reassigning a top-level field on the returned instances, not
mutating those nested containers in place.
"""
from __future__ import annotations

import dataclasses
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


def for_set(set_name: str) -> tuple | None:
    """(SystemMap, Region) for the set, or None if it is not a region of
    any checked-in map.

    The returned instances are copies -- mutating them never poisons the
    cached index for a later caller.
    """
    by_set, _ = _index()
    found = by_set.get(set_name)
    if found is None:
        return None
    m, r = found
    return dataclasses.replace(m), dataclasses.replace(r)


def system_of(set_name: str) -> str | None:
    """The system's name for the set, or None."""
    found = for_set(set_name)
    return found[0].system if found is not None else None


def regions_of(system: str) -> list[str]:
    """Every region set name in that system, in map order. Empty list if
    the system is unknown."""
    _, regions_by_system = _index()
    return list(regions_by_system.get(system, []))
