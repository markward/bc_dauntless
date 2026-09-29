"""The radial system profile: space as a function of distance from the star.

Design: docs/superpowers/specs/2026-09-23-radial-system-profile-design.md.
Pure data + evaluation. Must not import engine.systems.map (map imports this).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

COLUMNS = ("nebula", "dust", "sensors", "radiation", "asteroids")


@dataclass
class ProfileRow:
    distance_gu: float
    nebula: float = 0.0
    dust: float = 0.0
    sensors: float = 0.0
    radiation: float = 0.0
    asteroids: float = 0.0


@dataclass
class Profile:
    rows: list = field(default_factory=list)   # sorted by distance_gu, first at 0.0
    color: tuple | None = None                 # the clump's RGB (0-1); None = no cloud
    full_concealment: float = 0.0              # C_V, generator-measured


@dataclass(frozen=True)
class Sample:
    nebula: float = 0.0
    dust: float = 0.0
    sensors: float = 0.0
    radiation: float = 0.0
    asteroids: float = 0.0


CLEAR = Sample()


def _sample(row) -> Sample:
    return Sample(**{c: getattr(row, c) for c in COLUMNS})


def evaluate(profile, r: float) -> Sample:
    """Every column at radius `r`: linear between rows, each column on its
    own; the last row persists outward forever; None/empty is clear space."""
    if profile is None or not profile.rows:
        return CLEAR
    rows = profile.rows
    if r <= rows[0].distance_gu:
        return _sample(rows[0])
    for a, b in zip(rows, rows[1:]):
        if r == b.distance_gu:
            # An exact hit on a breakpoint returns that row's own stored
            # value rather than a t=1.0 lerp -- `a + (b - a) * 1.0` is not
            # bit-exact in IEEE754 (e.g. 1.0 + (0.2 - 1.0) == 0.19999999999999996),
            # and compose_max() re-samples a profile at its own breakpoints.
            return _sample(b)
        if r <= b.distance_gu:
            span = b.distance_gu - a.distance_gu
            t = 0.0 if span <= 0.0 else (r - a.distance_gu) / span
            return Sample(**{c: getattr(a, c) + (getattr(b, c) - getattr(a, c)) * t
                             for c in COLUMNS})
    return _sample(rows[-1])


def clump_radius(region, star_position) -> float:
    """Distance from the star to a region's authored nebula clump: the
    region anchor plus the FIRST sphere's set-local centre."""
    x, y, z, _r = region.nebula["spheres"][0]
    ax, ay, az = region.anchor_gu
    return math.dist((ax + x, ay + y, az + z), tuple(star_position))


def locate(obj):
    """(profile, distance from the star) for an object in a mapped region,
    else None. Resolved at use; never cached."""
    from engine.systems import frames, resolve
    pos = frames.system_position(obj)
    if pos is None or pos[0][0] != "system":
        return None
    m = resolve.map_of(pos[0][1])
    if m is None:
        return None
    star = next((b for b in m.bodies if b.orbits is None), None)
    if star is None:
        return None
    return m.profile, math.dist(pos[1:], tuple(star.position_gu))


def sample_for_object(obj) -> Sample:
    found = locate(obj)
    if found is None:
        return CLEAR
    return evaluate(found[0], found[1])


VEIL_DEFAULT = 0.15   # star transmittance through the whole cloud from the
                      # system's outermost region (spec 2026-09-29, "The veil")


def radial_integral(profile, r_a: float, r_b: float) -> float:
    """Exact integral of the `nebula` column over [min(r_a,r_b), max(...)].
    Piecewise-linear between rows; the last row persists outward."""
    if profile is None or not profile.rows:
        return 0.0
    lo, hi = (r_a, r_b) if r_a <= r_b else (r_b, r_a)
    pts = sorted({lo, hi} | {row.distance_gu for row in profile.rows
                             if lo < row.distance_gu < hi})
    total = 0.0
    for a, b in zip(pts, pts[1:]):
        total += 0.5 * (evaluate(profile, a).nebula + evaluate(profile, b).nebula) * (b - a)
    return total


def _star_and_outer(m):
    star = next((b for b in m.bodies if b.orbits is None), None)
    if star is None or not m.regions:
        return None, 0.0
    r_outer = max(math.dist(tuple(r.anchor_gu), tuple(star.position_gu))
                  for r in m.regions)
    return star, r_outer


def k_sys(m, veil: float = VEIL_DEFAULT) -> float:
    """Extinction per GU per unit `nebula` so the star's transmittance seen
    from the outermost region equals `veil`. 0.0 when there is nothing to veil."""
    if m is None or m.profile is None:
        return 0.0
    star, r_outer = _star_and_outer(m)
    if star is None:
        return 0.0
    integral = radial_integral(m.profile, star.radius_gu, r_outer)
    if integral <= 0.0:
        return 0.0
    return -math.log(veil) / integral


def star_transmittance(obj, veil: float = VEIL_DEFAULT) -> float:
    """exp(-k_sys * integral from the star's surface to the object's radius):
    how much of the star shows through the cloud. The eye->star line is radial,
    so this is exact. 1.0 outside a mapped system."""
    from engine.systems import frames, resolve
    pos = frames.system_position(obj)
    if pos is None or pos[0][0] != "system":
        return 1.0
    m = resolve.map_of(pos[0][1])
    if m is None or m.profile is None:
        return 1.0
    star, _ = _star_and_outer(m)
    if star is None:
        return 1.0
    r = math.dist(pos[1:], tuple(star.position_gu))
    return math.exp(-k_sys(m, veil) * radial_integral(m.profile, star.radius_gu, r))
