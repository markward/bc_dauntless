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
    planet_radius_scale: float = 20.0
    moon_radius_scale: float = 20.0
    sun_radius_scale: float = 2.0
    framing_scale: float = 2.0
    min_standoff_factor: float = 1.5
    max_standoff_factor: float = 12.0
    default_sun_radius_gu: float = 9000.0
    first_orbit_clearance_gu: float = 30000.0
    orbit_step_gu: float = 26000.0
    region_margin_gu: float = 1500.0
    # Fallback only: used when a region's BC geometry is degenerate (the
    # primary sits exactly on Player Start, so there is no distance/radius
    # ratio to derive a standoff from). See _standoff_factor.
    anchor_standoff_factor: float = 2.2
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


def _orbit_position(index: int, first_orbit: float, t: LayoutTuning):
    r = first_orbit + t.orbit_step_gu * index
    a = _GOLDEN_ANGLE * index
    return (r * math.sin(a), r * math.cos(a), 0.0)


def _standoff_factor(primary, region, t) -> float:
    """How many NEW planet-radii the anchor sits back from the planet's centre.

    Derived from BC's own framing. The artist placed each planet at a distance
    that gave it a particular apparent size, and that varied per map -- Ona 2
    read close, Ona 1 distant. A single constant flattened all of it.

    Because the standoff is measured in radii, the planet's SIZE cancels out of
    the apparent angle: `planet_radius_scale` and `framing_scale` are
    independent knobs. At framing_scale 1.0 the result equals BC's apparent
    size exactly.

    Clamped at both ends. The floor keeps the anchor outside the planet; the
    cap exists because BC's most distant framing (Savoy 1: a 100 GU planet
    5041 GU away, 50:1) would otherwise throw the anchor far enough to pass the
    sun. Both clamps are reported by ambiguities() -- they override BC's intent.
    """
    r_bc = primary.radius_gu
    d_bc = _norm(_sub(primary.offset_gu, region.player_start_gu))
    if r_bc <= 0.0 or d_bc <= 0.0:
        return t.anchor_standoff_factor
    raw = (d_bc / r_bc) / t.framing_scale
    return min(max(raw, t.min_standoff_factor), t.max_standoff_factor)


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


def ambiguities(s, tuning: LayoutTuning | None = None) -> list:
    t = tuning or LayoutTuning()
    notes = []
    for region in s.regions:
        primary_check, _ = _split(region)
        if primary_check is not None:
            r_bc = primary_check.radius_gu
            d_bc = _norm(_sub(primary_check.offset_gu, region.player_start_gu))
            if r_bc > 0.0 and d_bc > 0.0:
                raw = (d_bc / r_bc) / t.framing_scale
                if raw < t.min_standoff_factor:
                    notes.append(
                        f"{region.set_name}: {primary_check.name!r} standoff "
                        f"clamped to the MIN floor ({t.min_standoff_factor} "
                        f"radii) -- BC framed it closer than the floor allows")
                elif raw > t.max_standoff_factor:
                    notes.append(
                        f"{region.set_name}: {primary_check.name!r} standoff "
                        f"clamped to the MAX cap ({t.max_standoff_factor} "
                        f"radii) -- BC framed it farther than the cap allows")
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

    # Two systems (Belaruz, Vesuvi) build a MetaNebula and author no Sun_Create
    # at all -- sun_bc is 0.0 there, and default_sun_radius_gu is the fallback.
    sun_bc = max(
        (b.radius_gu for region in s.regions for b in region.bodies if b.is_sun),
        default=0.0)
    sun_radius = (sun_bc * t.sun_radius_scale) if sun_bc > 0.0 else t.default_sun_radius_gu
    first_orbit = sun_radius + t.first_orbit_clearance_gu

    m.bodies.append(Body(
        name=s.name, display_name=s.name, radius_gu=sun_radius,
        position_gu=(0.0, 0.0, 0.0), orbits=None,
        appearance=Appearance(kind="nif", model=""), owner_region=None))

    for index, region in enumerate(_ordered(s)):
        centre = _orbit_position(index, first_orbit, t)
        primary, companions = _split(region)

        if primary is None:
            m.regions.append(Region(set_name=region.set_name, anchor_gu=centre,
                                    radius_gu=region.content_extent_gu + t.region_margin_gu,
                                    body_names=[]))
            continue

        placed = []
        members = []

        primary_radius = primary.radius_gu * t.planet_radius_scale
        primary_body = Body(
            name=primary.name, display_name=primary.name,
            radius_gu=primary_radius, position_gu=centre, orbits=s.name,
            appearance=Appearance(kind="nif", model=primary.model),
            owner_region=region.set_name)
        m.bodies.append(primary_body)
        placed.append(primary.name)
        members.append(primary_body)

        for j, c in enumerate(companions):
            radius = c.radius_gu * t.moon_radius_scale
            # Keep each moon's original bearing from the primary, at a distance
            # scaled to the new primary radius.
            direction = _unit(_sub(c.offset_gu, primary.offset_gu))
            distance = primary_radius * (t.moon_first_orbit_factor
                                         + t.moon_orbit_step_factor * j)
            companion_body = Body(
                name=c.name, display_name=c.name, radius_gu=radius,
                position_gu=_add(centre, _scale(direction, distance)),
                orbits=primary.name,
                appearance=Appearance(kind="nif", model=c.model),
                owner_region=region.set_name)
            m.bodies.append(companion_body)
            placed.append(c.name)
            members.append(companion_body)

        # The anchor: the group's centroid, displaced back along the ORIGINAL
        # viewing direction by a standoff scaled to the new primary radius.
        # With one body the centroid IS the primary, so the primary's bearing
        # from the anchor is exactly the bearing BC gave it. With companions the
        # centroid shifts and the bearing is approximate -- which is the point:
        # "anchor between the two" frames the group, not just the planet.
        #
        # `members` holds the Body objects just created above directly, NOT a
        # by-name lookup through m.body() -- moon names collide across regions
        # (e.g. "Moon 1" appears in both Geble3 and Geble4), and m.body()
        # returns the first match in the whole map, which silently pulled in
        # a companion from a DIFFERENT region's group and blew up the anchor.
        view = _unit(_sub(primary.offset_gu, region.player_start_gu))
        centroid = tuple(
            sum(b.position_gu[axis] for b in members) / len(members) for axis in range(3))
        standoff = _standoff_factor(primary, region, t) * primary_radius
        anchor = _sub(centroid, _scale(view, standoff))

        reach = max(
            _norm(_sub(b.position_gu, anchor)) + b.radius_gu for b in members)
        m.regions.append(Region(
            set_name=region.set_name, anchor_gu=anchor,
            radius_gu=max(reach, region.content_extent_gu) + t.region_margin_gu,
            body_names=placed))

    return m
