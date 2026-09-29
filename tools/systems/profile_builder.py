"""Derive a system's radial profile from its committed map.

Design: docs/superpowers/specs/2026-09-23-radial-system-profile-design.md
("How the profiles get authored"). Every number is derived from the map at
generation time -- never hard-code a clump radius (two layout doublings made
the first draft's literals wrong within two days).
"""
from __future__ import annotations

from engine.appc.nebula import DEFAULT_FBM_DIALS
from engine.appc.nebula_density import density, seed_for
from engine.systems.profile import COLUMNS, Profile, ProfileRow, clump_radius, evaluate

RISE_START = 0.5          # nebula/dust start rising at 0.5 R
FLOOR_AT = 2.0            # ... fall to FLOOR at 2 R, which persists outward
FLOOR = 0.05
BAND_REGION_RADII = 2.0   # sensors/radiation: 0 at R +- 2 x region radius
STAR_REACH_RADII = 3.0    # star radiation reaches 0 at 3 star radii
VIS_A, VIS_B = 55.625, 89.375   # visibility = a + b / i, exact through BC's two samples

# BC's authored Vesuvi 4 sphere (Systems/Vesuvi/Vesuvi4_S.py AddNebulaSphere).
# Pinned against the surveyed map by tests/unit/test_system_maps_valid.py.
VESUVI_4_SPHERES = [(0.0, 1500.0, 0.0, 1500.0)]


def nebula_intensity(visibility_gu: float) -> float:
    if visibility_gu <= VIS_A:
        return 1.0
    return min(1.0, VIS_B / (visibility_gu - VIS_A))


def core_concealment(spheres) -> float:
    """Mean fbm concealment over a 5x5x5 grid within half the first sphere's
    radius, with the runtime's own default dials and seed, drift_t = 0.
    Measured, not guessed -- this is what concealment_at would read there."""
    cx, cy, cz, radius = spheres[0]
    freq, gain, floor = DEFAULT_FBM_DIALS
    seed = seed_for(cx, cy, cz)
    steps = [(-0.5 + i / 4.0) * radius for i in range(5)]
    total = 0.0
    for dx in steps:
        for dy in steps:
            for dz in steps:
                total += density(cx + dx, cy + dy, cz + dz, spheres, seed,
                                 freq, gain, floor, drift_t=0.0)
    return total / 125.0


FULL_CONCEALMENT = core_concealment(VESUVI_4_SPHERES)


def star_rows(star_radius_gu: float) -> list:
    return [ProfileRow(0.0, radiation=1.0),
            ProfileRow(star_radius_gu, radiation=1.0),
            ProfileRow(STAR_REACH_RADII * star_radius_gu, radiation=0.0)]


def cloud_rows(region, star_position, full_concealment: float) -> list:
    neb = region.nebula
    R = clump_radius(region, star_position)
    band = BAND_REGION_RADII * region.radius_gu
    peak_neb = nebula_intensity(neb["visibility_gu"])
    peak_sens = (core_concealment(neb["spheres"]) / full_concealment
                 if full_concealment > 0.0 else 0.0)
    peak_rad = 1.0 if (neb["damage_hull_per_s"] > 0.0
                       or neb["damage_shield_per_s"] > 0.0) else 0.0

    def wide(r):
        if r <= RISE_START * R:
            return 0.0
        if r <= R:
            return peak_neb * (r - RISE_START * R) / ((1.0 - RISE_START) * R)
        if r <= FLOOR_AT * R:
            return peak_neb + (FLOOR - peak_neb) * (r - R) / ((FLOOR_AT - 1.0) * R)
        return FLOOR

    def narrow(r, peak):
        d = abs(r - R)
        return 0.0 if d >= band else peak * (1.0 - d / band)

    points = sorted({0.0, RISE_START * R, max(0.0, R - band), R, R + band, FLOOR_AT * R})
    return [ProfileRow(d, nebula=min(1.0, wide(d)), dust=min(1.0, wide(d)),
                       sensors=min(1.0, narrow(d, peak_sens)),
                       radiation=narrow(d, peak_rad))
            for d in points]


def compose_max(a_rows: list, b_rows: list) -> list:
    """Per-column max of two piecewise-linear profiles, exact: breakpoints of
    both plus every point where a column's leader changes."""
    pa, pb = Profile(rows=list(a_rows)), Profile(rows=list(b_rows))
    pts = sorted({0.0} | {r.distance_gu for r in a_rows} | {r.distance_gu for r in b_rows})
    extra = set()
    for lo, hi in zip(pts, pts[1:]):
        a0, a1, b0, b1 = evaluate(pa, lo), evaluate(pa, hi), evaluate(pb, lo), evaluate(pb, hi)
        for c in COLUMNS:
            d0 = getattr(a0, c) - getattr(b0, c)
            d1 = getattr(a1, c) - getattr(b1, c)
            if d0 * d1 < 0.0:
                extra.add(lo + (hi - lo) * d0 / (d0 - d1))
    out = []
    for d in sorted(set(pts) | extra):
        sa, sb = evaluate(pa, d), evaluate(pb, d)
        out.append(ProfileRow(d, **{c: max(getattr(sa, c), getattr(sb, c)) for c in COLUMNS}))
    return out


def override_rows(raw: dict) -> list:
    return [ProfileRow(**row) for row in raw["rows"]]


def build_profile(m, override, *, campaign: bool) -> Profile:
    star = next(b for b in m.bodies if b.orbits is None)
    clouds = [r for r in m.regions if r.nebula is not None and r.nebula.get("spheres")] \
        if campaign else []
    if override is not None:
        base = override_rows(override)
    else:
        base = []
        for region in clouds:
            base = compose_max(base, cloud_rows(region, star.position_gu, FULL_CONCEALMENT))
    rows = compose_max(base, star_rows(star.radius_gu))
    color = tuple(clouds[0].nebula["color"]) if clouds else None
    return Profile(rows=rows, color=color, full_concealment=FULL_CONCEALMENT)
