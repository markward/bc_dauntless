"""Turn a survey into a system map: bodies on orbits, anchors placed to
reproduce the original artist's framing.

THE ANCHOR RULE is the part with real content. The original set records, for
each body, which DIRECTION you looked to see it (the unit vector from that
set's Player Start to the body) and how far away it was. Distance is discarded
-- bodies are re-authored much larger, so the standoff comes from the new
radius -- but the DIRECTION is reproduced exactly: from the new anchor, the
primary body lies on the same bearing it did in BC.

Because a region's anchor is a translation only (never a rotation), and system
axes are the region's local axes, reproducing that bearing is simply
    anchor = primary_position - view_direction * standoff

With companions the anchor moves to the group centroid first, so a planet and
its moon frame you between them -- which is what "anchor between the two" means.

WHAT THIS CANNOT PRESERVE: lighting direction. Each BC set carries its own sun
at +-70000 GU in whatever direction suited that one map (Alioth1's at +X,
Alioth3's at -X, in nominally the same system). With one real sun at the
centre, light comes from wherever the region actually sits. Per-set suns are
discarded here on purpose.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from engine.systems.map import Appearance, Body, Region, SystemMap

_GOLDEN_ANGLE = 2.399963229728653


@dataclass
class LayoutTuning:
    planet_radius_gu: float = 1800.0
    moon_radius_gu: float = 600.0
    sun_radius_gu: float = 9000.0
    first_orbit_gu: float = 30000.0
    orbit_step_gu: float = 26000.0
    anchor_standoff_factor: float = 2.2
    region_margin_gu: float = 1500.0
    moon_first_orbit_factor: float = 4.0
    moon_orbit_step_factor: float = 1.5


def _norm(v) -> float:
    return math.sqrt(sum(c * c for c in v))


def _unit(v):
    n = _norm(v)
    if n <= 0.0:
        return (0.0, 1.0, 0.0)
    return tuple(c / n for c in v)


def _add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def _sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def _scale(v, k):
    return tuple(c * k for c in v)


def _orbit_position(index: int, t: LayoutTuning):
    r = t.first_orbit_gu + t.orbit_step_gu * index
    a = _GOLDEN_ANGLE * index
    return (r * math.sin(a), r * math.cos(a), 0.0)


def _ordered(s):
    numbered = [r for r in s.regions if r.ordinal is not None]
    unnumbered = [r for r in s.regions if r.ordinal is None]
    numbered.sort(key=lambda r: r.ordinal)
    return numbered + unnumbered


def _split(region):
    """(primary, companions) -- the largest non-sun body wins."""
    planets = [b for b in region.bodies if not b.is_sun]
    if not planets:
        return None, []
    primary = max(planets, key=lambda b: b.radius_gu)
    return primary, [b for b in planets if b is not primary]


def ambiguities(s) -> list:
    notes = []
    for region in s.regions:
        primary_check, _ = _split(region)
        if (primary_check is not None
                and _norm(_sub(primary_check.offset_gu, region.player_start_gu)) <= 0.0):
            # _unit() falls back to +Y for a zero-length vector, which would
            # silently frame the region northward. Measured 2026-09-22: this
            # fires on 0 of the 90 real regions, so reaching it means the survey
            # failed to resolve a waypoint -- say so rather than guess.
            notes.append(
                f"{region.set_name}: {primary_check.name!r} sits exactly on "
                f"Player Start, so there is no original viewing direction -- "
                f"the anchor defaults to +Y and is probably wrong")
        if region.ordinal is None:
            notes.append(
                f"{region.set_name}: no trailing number, so its orbit order is a "
                f"guess -- set it in overrides")
        primary, companions = _split(region)
        for c in companions:
            if "moon" not in c.name.lower():
                notes.append(
                    f"{region.set_name}: {c.name!r} was demoted to a moon of "
                    f"{primary.name!r}, but its name does not say 'Moon' -- it may "
                    f"be a separate world needing its own orbit")
    return notes


def layout(s, tuning: LayoutTuning | None = None) -> SystemMap:
    t = tuning or LayoutTuning()
    m = SystemMap(system=s.name, generated={"tool": "gen_system_maps"})

    m.bodies.append(Body(
        name=s.name, display_name=s.name, radius_gu=t.sun_radius_gu,
        position_gu=(0.0, 0.0, 0.0), orbits=None,
        appearance=Appearance(kind="nif", model=""), owner_region=None))

    for index, region in enumerate(_ordered(s)):
        centre = _orbit_position(index, t)
        primary, companions = _split(region)

        if primary is None:
            m.regions.append(Region(set_name=region.set_name, anchor_gu=centre,
                                    radius_gu=region.content_extent_gu + t.region_margin_gu,
                                    body_names=[]))
            continue

        biggest = max(b.radius_gu for b in [primary] + companions) or 1.0
        placed = []

        primary_radius = t.planet_radius_gu
        m.bodies.append(Body(
            name=primary.name, display_name=primary.name,
            radius_gu=primary_radius, position_gu=centre, orbits=s.name,
            appearance=Appearance(kind="nif", model=primary.model),
            owner_region=region.set_name))
        placed.append(primary.name)

        for j, c in enumerate(companions):
            share = max(c.radius_gu / biggest, 0.25)
            radius = t.moon_radius_gu * share
            # Keep each moon's original bearing from the primary, at a distance
            # scaled to the new primary radius.
            direction = _unit(_sub(c.offset_gu, primary.offset_gu))
            distance = primary_radius * (t.moon_first_orbit_factor
                                         + t.moon_orbit_step_factor * j)
            m.bodies.append(Body(
                name=c.name, display_name=c.name, radius_gu=radius,
                position_gu=_add(centre, _scale(direction, distance)),
                orbits=primary.name,
                appearance=Appearance(kind="nif", model=c.model),
                owner_region=region.set_name))
            placed.append(c.name)

        # The anchor: the group's centroid, displaced back along the ORIGINAL
        # viewing direction by a standoff scaled to the new primary radius.
        # With one body the centroid IS the primary, so the primary's bearing
        # from the anchor is exactly the bearing BC gave it. With companions the
        # centroid shifts and the bearing is approximate -- which is the point:
        # "anchor between the two" frames the group, not just the planet.
        view = _unit(_sub(primary.offset_gu, region.player_start_gu))
        members = [m.body(n) for n in placed]
        centroid = tuple(
            sum(b.position_gu[axis] for b in members) / len(members) for axis in range(3))
        standoff = t.anchor_standoff_factor * primary_radius
        anchor = _sub(centroid, _scale(view, standoff))

        reach = max(
            _norm(_sub(b.position_gu, anchor)) + b.radius_gu for b in members)
        m.regions.append(Region(
            set_name=region.set_name, anchor_gu=anchor,
            radius_gu=max(reach, region.content_extent_gu) + t.region_margin_gu,
            body_names=placed))

    return m
