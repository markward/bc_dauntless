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

for_set() hands back a copy.deepcopy() of the (SystemMap, Region) pair, not
the cached instances. map.load() re-parses JSON on every call today, so two
callers never share an instance -- returning the raw cached objects here
would be a behaviour change: a caller mutating anything reachable from the
result (a top-level field, an element of `m.bodies`/`m.regions`, or even
`m.region(name).anchor_gu` -- `SystemMap`'s own accessors search whatever
list they're called on, so a shallow copy doesn't stop them handing back
the still-cached instance) would silently corrupt the index for every later
caller in the process. A deep copy closes all of that at once, at the cost
of copying a whole system's bodies/regions/clouds on every call -- accepted
deliberately, because the per-frame path (Task 5, drawing every body every
tick) is meant to call anchor_of() instead, which returns an immutable
tuple and never touches for_set()'s copy machinery.
"""
from __future__ import annotations

import copy
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

    The returned pair is a deep copy: nothing reachable from it, at any
    depth, is shared with the cached index. Mutating it -- including
    through SystemMap's own m.region()/m.body() accessors -- never poisons
    a later caller's lookup.
    """
    by_set, _ = _index()
    found = by_set.get(set_name)
    if found is None:
        return None
    return copy.deepcopy(found)


def system_of(set_name: str) -> str | None:
    """The system's name for the set, or None."""
    found = for_set(set_name)
    return found[0].system if found is not None else None


def regions_of(system: str) -> list[str]:
    """Every region set name in that system, in map order. Empty list if
    the system is unknown."""
    _, regions_by_system = _index()
    return list(regions_by_system.get(system, []))


def anchor_of(set_name: str) -> tuple | None:
    """The owning region's anchor_gu for the set, or None.

    This is the per-frame accessor: a tuple is immutable, so there is
    nothing to copy and nothing a caller can poison the cache with --
    unlike for_set(), which deep-copies a whole SystemMap on every call.
    """
    by_set, _ = _index()
    found = by_set.get(set_name)
    if found is None:
        return None
    _, r = found
    return r.anchor_gu
