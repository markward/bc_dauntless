"""The key light of a mapped region comes from the system's star.

BC lights each region with its own authored LightPlacements, aimed for a
region that was a standalone set. Once regions sit in one star system the
authored key light can disagree with the sun the player can see -- at Ona 2 it
points 73 degrees below the visible star, and Ona 3's near-white light lights
a red star's system (live finding 2026-09-27). Mark's call: in a MAPPED region
the key light points FROM THE STAR and takes THE STAR'S COLOUR, at BC's
authored brightness. Every other directional and the ambient stay BC's.

The key light is the brightest directional -- the same rule as
tools/systems/survey.py:_key_light, which picks by dimmer; here the colour is
already rgb*dimmer, so brightness is its luminance.
"""
from __future__ import annotations

import math


def luminance(rgb):
    """Rec. 709 relative luminance of a linear RGB triple."""
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def key_light_from_star(directionals, star_dir, star_color):
    """`directionals` with its brightest entry re-aimed along `star_dir`
    (toward the star) and recoloured to `star_color`'s hue at the entry's own
    luminance. Pure; returns a new list. Unchanged when there is no
    directional, the direction is degenerate, or the star colour is black."""
    if not directionals:
        return directionals
    n = math.sqrt(sum(c * c for c in star_dir))
    star_lum = luminance(star_color)
    if n < 1e-12 or star_lum <= 0.0:
        return directionals
    key = max(range(len(directionals)),
              key=lambda i: luminance(directionals[i][1]))
    scale = luminance(directionals[key][1]) / star_lum
    out = list(directionals)
    out[key] = (tuple(c / n for c in star_dir),
                tuple(c * scale for c in star_color))
    return out


def for_player(pSet, player, directionals):
    """Apply key_light_from_star for `player` when `pSet` is a mapped region
    of the player's own star system; otherwise `directionals` unchanged.

    The direction is from the player's SYSTEM position to the star (the map
    body that orbits nothing), recomputed on every call."""
    from engine.systems import frames, resolve
    lit = frames.frame_of(pSet)
    pos = frames.system_position(player)
    if lit is None or pos is None or lit.key[0] != "system":
        return directionals
    if pos[0] != lit.key:
        return directionals
    m = resolve.map_of(lit.key[1])
    star = None if m is None else next(
        (b for b in m.bodies if b.orbits is None), None)
    if star is None or star.appearance.color is None:
        return directionals
    to_star = tuple(s - p for s, p in zip(star.position_gu, pos[1:]))
    return key_light_from_star(directionals, to_star,
                               tuple(star.appearance.color))
