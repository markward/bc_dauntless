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
position is the negated anchor) with the map's radius -- and with its
atmosphere radius scaled by that same factor, since the rescale is ours and
an atmosphere left at BC's authored value ends up inside the enlarged star
(see ``_rescale_sun``). A set with no Sun gets one created from the map's
star body: Belaruz and Vesuvi render bright directional light from a source
BC never placed, which is why their maps
carry an ``overrides.star`` block explaining it -- but the star Body entry
itself already carries the radius/position/appearance needed here, so no
special-casing of those two systems is required in code.

A created star must be given ALL FIVE of ``Sun_Create``'s arguments. A star
built from radius alone has no atmosphere radius (so no keep-out band and
nothing for the AI to steer around), zero environmental hull damage (flying
into it is free, where every sun BC authored does 500/s) and no textures.
The four values the map does not carry directly are surveyed from BC's own
authored calls -- see ``STAR_ATMOSPHERE_RATIO``, ``STAR_DAMAGE_PER_SEC`` and
``STAR_TEXTURES`` below, which record what was counted and what was chosen.

A body the map does not name for the region is left exactly as BC placed
it -- no removal path exists or is intended (see the parent spec's ruling).

Body lookup within a region MUST be scoped to that region's owner_region,
never a bare name search across the whole system map. BC's display names
are not unique within a system -- ``engine/systems/maps/geble.json`` names
a "Moon 1" in both Geble3 and Geble4, with different radii and positions --
so a plain ``SystemMap.body(name)`` first-match scan silently applies the
wrong region's body data (mirrors the same collision ``validate.py``'s
``_resolve(by_name, name, owner=...)`` disambiguates).
"""
from __future__ import annotations

from engine.appc.planet import Sun, Sun_Create
from engine.systems import resolve


# -- What a CREATED star takes from BC's own suns ----------------------------
#
# Belaruz and Vesuvi are the only systems where a star is constructed rather
# than repositioned, so these are the only values this module has to choose.
# None of them is invented: they are surveyed from BC's authored
# ``App.Sun_Create`` calls in the per-system placement scripts, read as TEXT
# (those scripts are Python 1.5 and must never be imported).
#
# 86 live calls. 84 pass the full (radius, atmosphere, damage) triple:
#   * 82 of the 84 pass atmosphere EXACTLY equal to radius. The two exceptions
#     are Itari2_S (5000/6000) and OmegaDraconis1_S (360/180).
#   * 83 of the 84 pass damage_per_sec == 500. The one exception is again
#     OmegaDraconis1_S (360) -- the same deliberate one-off, which also halves
#     its atmosphere, so it is one authored star and not a second convention.
# The remaining 2 calls are multiplayer (Multi4_S, Multi7_S) and pass radius
# alone; Multi4 then sets 25 hull / 10 shield damage by hand and Multi7 leaves
# its star harmless. Belaruz and Vesuvi are single-player locales, so the
# locale family -- atmosphere == radius, 500/s -- is the one to follow, and a
# created star is deliberately NOT harmless.
STAR_ATMOSPHERE_RATIO: float = 1.0
STAR_DAMAGE_PER_SEC: float = 500.0

# star_class -> (base_texture, flare_texture).
#
# The map's ``star_class`` is BC's own texture choice re-labelled: across the
# 23 systems BC gave a sun the correspondence is exact and total.
#   red         -> SunRed        Albirea, Ona, Cebalrai, Serris, Voltair  5/5
#   red_orange  -> SunRedOrange  Ascella, Yiles, Chambana, XiEntrades     4/4
#   yellow      -> SunYellow     Tevron, Savoy, Prendel, Geble, Alioth,
#                                OmegaDraconis                            6/6
#   blue_white  -> SunBlueWhite  Artrus, Tezle, Beol                      3/3
#   white       -> (none)        Biranu, Nepenthe, Itari, Riha, Poseidon  5/5
#
# The FLARE is not a function of class and this table does not pretend it is:
# BC splits within two classes (red takes SunFlaresRed twice and
# SunFlaresRedOrange three times; blue_white takes SunFlaresWhite twice and
# SunFlaresBlue once). Each row carries its class's majority choice.
#
# "white" and "brown_dwarf" are empty ON PURPOSE rather than for want of a
# value: every BC script for a white star, and both multiplayer star calls,
# pass no texture arguments at all, so the engine's own SunBase.tga default IS
# the authored look. planet.aggregate_suns_for_renderer substitutes it, and an
# empty flare means "skip the overlay layer" -- body and corona still draw.
#
# "remnant_hot" is Vesuvi's alone and BC never drew it, so it is the one row
# decided rather than recovered. Vesuvi's authored colour (0.78, 0.86, 1.0)
# sits 0.045 away from blue_white's (0.74, 0.84, 1.0) in RGB and 0.31 from the
# next nearest class, and the map's own override note calls the remnant
# "small, luminous, blue-white" -- so it takes the blue-white sun.
#
# An unrecognised class falls back to BC's default, which is safe but silent;
# tests/unit/test_apply_system_map.py requires every class the checked-in maps
# actually use to be a row here, so a regenerated map cannot add one quietly.
STAR_TEXTURES: dict = {
    "red":         ("data/Textures/SunRed.tga",
                    "data/Textures/Effects/SunFlaresRedOrange.tga"),
    "red_orange":  ("data/Textures/SunRedOrange.tga",
                    "data/Textures/Effects/SunFlaresRedOrange.tga"),
    "yellow":      ("data/Textures/SunYellow.tga",
                    "data/Textures/Effects/SunFlaresYellow.tga"),
    "blue_white":  ("data/Textures/SunBlueWhite.tga",
                    "data/Textures/Effects/SunFlaresWhite.tga"),
    "remnant_hot": ("data/Textures/SunBlueWhite.tga",
                    "data/Textures/Effects/SunFlaresWhite.tga"),
    "white":       ("", ""),
    "brown_dwarf": ("", ""),
}


def _set_local_position(position_gu: tuple, anchor_gu: tuple) -> tuple:
    return tuple(p - a for p, a in zip(position_gu, anchor_gu))


def _region_body(m, name: str, owner_region: str):
    """The map's Body named `name` AND owned by `owner_region`, or None.

    Never use SystemMap.body(name) for a region-scoped lookup -- display
    names collide across regions in the same system (e.g. "Moon 1" in both
    Geble3 and Geble4), and a bare name match silently picks whichever body
    happens to come first in the map's body list.
    """
    for b in m.bodies:
        if b.name == name and b.owner_region == owner_region:
            return b
    return None


def _star_textures(star) -> tuple:
    """(base, flare) texture paths for a star Body, from its star_class."""
    star_class = getattr(getattr(star, "appearance", None), "star_class", "")
    return STAR_TEXTURES.get(star_class or "", ("", ""))


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


def _rescale_sun(sun, radius_gu: float) -> None:
    """Resize an authored Sun to the map's star radius -- atmosphere and all.

    The rescale is OURS. BC's Ona sun is 5,000 GU and the map's is 10,000, and
    BC's data was self-consistent before we touched it: 82 of its 84 authored
    ``Sun_Create`` calls pass atmosphere EXACTLY equal to radius. Growing the
    body and leaving the atmosphere behind buries the keep-out band inside the
    very star it exists to keep ships out of, across ~30 authored systems.

    The authored RATIO is preserved rather than forced to 1.0, because two of
    the 84 deliberately are not (Itari2_S at 6000/5000, OmegaDraconis1_S at
    180/360) and BC's authoring is what this module follows. A zero ratio is a
    ratio too -- Multi7_S's star has no band and must not grow one. Only a sun
    with no usable prior radius has nothing to scale, and falls back to the
    majority convention.

    Environmental damage is deliberately NOT touched here. BC authored those
    values, they are already correct, and rescaling geometry is no reason to
    restate them -- OmegaDraconis1_S's 360/sec stays 360/sec.
    """
    old_radius = float(sun.GetRadius())
    ratio = (float(sun.GetAtmosphereRadius()) / old_radius
             if old_radius > 0.0 else STAR_ATMOSPHERE_RATIO)
    sun.SetRadius(radius_gu)
    sun.SetAtmosphereRadius(radius_gu * ratio)


def apply_to_set(pSet, set_name: str) -> bool:
    """Apply set_name's map region to pSet's bodies.

    True when set_name resolved to a region and the map was applied; False
    when it resolved to nothing (the set is left completely untouched).

    Must be called before pSet is render-realized -- see module docstring.

    Degrades to False (no-op) for a pSet that isn't a real set -- None, or
    missing the GetObject/_objects surface -- rather than raising, since
    Task 4 wires this into real set-creation paths where a
    partially-constructed set is plausible.
    """
    if pSet is None or not hasattr(pSet, "GetObject") or not hasattr(pSet, "_objects"):
        return False
    found = resolve.for_set(set_name)
    if found is None:
        return False
    m, region = found

    for body_name in region.body_names:
        body = _region_body(m, body_name, region.set_name)
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
            _rescale_sun(sun, star.radius_gu)
            _place(sun, star_local)
        else:
            base_texture, flare_texture = _star_textures(star)
            sun = Sun_Create(
                star.radius_gu,
                star.radius_gu * STAR_ATMOSPHERE_RATIO,
                STAR_DAMAGE_PER_SEC,
                base_texture,
                flare_texture,
            )
            _place(sun, star_local)
            pSet.AddObjectToSet(sun, star.name)

    return True
