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
