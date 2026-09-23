"""Apply a system map's authored radius and position to a region's bodies.

engine.systems.resolve resolves a BC set name to the (SystemMap, Region)
pair that places it in one system-wide coordinate space. This module is the
substitution described by the parent spec: when a region's set is created,
each body the map names for that region takes the map's radius and
set-local position -- ``body.position_gu - region.anchor_gu``. Nothing is
created, nothing is deleted, no model is swapped; the same object BC placed
at 538 GU with a 110 GU radius ends up at ~6,000 GU with a 2,200 GU radius,
which is exactly what keeps GetObject, hailing, the target list and the
Orbit command working with zero changes anywhere else.

MUST run before the set is render-realized. ``_RenderState.
planet_natural_scale`` (engine/host_loop.py) caches
``GetRadius() / NIF_extent`` once, at load time -- a radius written after
that cache is populated leaves the body drawn at its old size while every
other system (physics, hailing, target list, Orbit) already sees the new
one. Callers must invoke ``apply_to_set`` as part of creating a set, before
anything realizes it. (Task 4 wires the actual call site; this module only
provides the function.)

The star is the one exception, with two halves. A set that already holds a
Sun -- every original per-locale BC script but Belaruz's and Vesuvi's called
Sun_Create -- keeps that Sun, repositioned to the system star's set-local
position (the star's ``position_gu`` is the system origin, so its set-local
position is the negated anchor) with the map's radius. A set with no Sun
gets one created from the map's star body: Belaruz and Vesuvi render bright
directional light from a source BC never placed, which is why their maps
carry an ``overrides.star`` block explaining it -- but the star Body entry
itself already carries the radius/position/appearance needed here, so no
special-casing of those two systems is required in code.

A body the map does not name for the region is left exactly as BC placed
it -- no removal path exists or is intended (see the parent spec's ruling).
"""
from __future__ import annotations

from engine.appc.planet import Sun, Sun_Create
from engine.systems import resolve


def _set_local_position(position_gu: tuple, anchor_gu: tuple) -> tuple:
    return tuple(p - a for p, a in zip(position_gu, anchor_gu))


def _star_body(m):
    """The map's one Body with orbits is None, or None if it has none."""
    for b in m.bodies:
        if b.orbits is None:
            return b
    return None


def _find_sun(pSet):
    """The Sun already in pSet's object table, or None."""
    for obj in pSet._objects.values():
        if isinstance(obj, Sun):
            return obj
    return None


def _place(obj, position_gu: tuple) -> None:
    x, y, z = position_gu
    obj.SetTranslateXYZ(x, y, z)


def apply_to_set(pSet, set_name: str) -> bool:
    """Apply set_name's map region to pSet's bodies.

    True when set_name resolved to a region and the map was applied; False
    when it resolved to nothing (the set is left completely untouched).

    Must be called before pSet is render-realized -- see module docstring.
    """
    found = resolve.for_set(set_name)
    if found is None:
        return False
    m, region = found

    for body_name in region.body_names:
        body = m.body(body_name)
        if body is None:
            continue
        obj = pSet.GetObject(body_name)
        if obj is None:
            continue
        obj.SetRadius(body.radius_gu)
        _place(obj, _set_local_position(body.position_gu, region.anchor_gu))

    star = _star_body(m)
    if star is not None:
        star_local = _set_local_position(star.position_gu, region.anchor_gu)
        sun = _find_sun(pSet)
        if sun is not None:
            sun.SetRadius(star.radius_gu)
            _place(sun, star_local)
        else:
            sun = Sun_Create(star.radius_gu)
            _place(sun, star_local)
            pSet.AddObjectToSet(sun, star.name)

    return True
