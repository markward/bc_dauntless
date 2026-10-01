"""Population table for the far tier (far-tier plan Task 9, spec §2).

Two populations ride on every disc source: minors (catalogue fragments)
and majors (catalogue "major" rocks). Both read their shape from
engine.rocks.far_dials AT USE, never captured, so a live dial edit is
picked up the next time a source is re-pushed to native.
"""
from __future__ import annotations

from dataclasses import dataclass

from engine.rocks import far_dials


@dataclass(frozen=True)
class Population:
    kind: int
    density_at_1: float
    a_lo: float
    a_hi: float
    r_min: float
    r_max: float
    exponent: float
    families: tuple


def populations(families: dict = {"silicate": 1.0}) -> tuple:
    """(minor, major), both carrying the same `families` weighting."""
    fam = tuple(sorted(families.items()))
    minor = Population(
        kind=0,
        density_at_1=far_dials.get("minor_density_at_1"),
        a_lo=0.0, a_hi=1.0,
        r_min=far_dials.get("minor_r_min"),
        r_max=far_dials.get("minor_r_max"),
        exponent=far_dials.get("minor_exponent"),
        families=fam,
    )
    major = Population(
        kind=1,
        density_at_1=far_dials.get("major_density_at_1"),
        a_lo=far_dials.get("major_a_lo"), a_hi=1.0,
        r_min=far_dials.get("major_r_min"),
        r_max=far_dials.get("major_r_max"),
        exponent=far_dials.get("major_exponent"),
        families=fam,
    )
    return minor, major
