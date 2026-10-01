"""Disc density sources for the far tier (far-tier plan Task 9, spec §2).

A DiscSource models one radial asteroid belt as a disc: `table` is BC's own
radial system-profile `asteroids` column (engine/systems/profile.py),
reused rather than re-authored, with a soft vertical falloff and an outer
fade past the last row. `table_a` and `evaluate` are the pure-Python twins
of renderer::far::table_a / density_a (native/src/renderer/far_field.cc) --
change one, change both.

Maps resolve at use, through engine.systems.resolve.map_of(): no module-
level paths (tests/unit/test_path_indirection.py).
"""
from __future__ import annotations

import math
import sys
import zlib
from dataclasses import dataclass, field

MAX_TABLE_ROWS = 32   # far_haze.frag's u_table_* arrays

_warned_truncate: set = set()


@dataclass
class DiscSource:
    id: int
    frame: str
    centre_gu: tuple
    normal: tuple
    table: list            # [(r_gu, a)]
    outer_fade_gu: float
    scale_height_frac: float
    scale_height_min_gu: float
    families: dict
    seed: int
    explicit_regions: list = field(default_factory=list)   # [((x,y,z), r)]; sub-project 4


def table_a(source, rho: float) -> float:
    """BC's radial `asteroids` density at radius `rho`: the exact twin of
    renderer::far::table_a -- linear between rows, clamped to the first
    row inward, and a linear ramp to zero over `outer_fade_gu` past the
    last row."""
    t = source.table
    if not t:
        return 0.0
    if rho <= t[0][0]:
        return t[0][1]
    for i in range(1, len(t)):
        if rho <= t[i][0]:
            span = t[i][0] - t[i - 1][0]
            u = (rho - t[i - 1][0]) / span if span > 0.0 else 1.0
            return t[i - 1][1] + (t[i][1] - t[i - 1][1]) * u
    if not (source.outer_fade_gu > 0.0):
        return 0.0
    u = (rho - t[-1][0]) / source.outer_fade_gu
    return 0.0 if u >= 1.0 else t[-1][1] * (1.0 - u)


def evaluate(source, point_gu: tuple) -> float:
    """a(x): table_a at the disc-plane radius times a vertical gaussian
    whose scale height is max(scale_height_frac * rho, scale_height_min_gu)
    -- the twin of renderer::far::density_a."""
    cx, cy, cz = source.centre_gu
    nx, ny, nz = source.normal
    dx, dy, dz = point_gu[0] - cx, point_gu[1] - cy, point_gu[2] - cz
    z = dx * nx + dy * ny + dz * nz
    rho = math.sqrt((dx - nx * z) ** 2 + (dy - ny * z) ** 2 + (dz - nz * z) ** 2)
    h = max(source.scale_height_frac * rho, source.scale_height_min_gu)
    return table_a(source, rho) * math.exp(-0.5 * z * z / (h * h))


def profile_belt(system_name: str):
    """The one DiscSource for a mapped system's radial `asteroids` column,
    or None when the map, its star, or any row with asteroids > 0 is
    missing."""
    from engine.systems import resolve
    m = resolve.map_of(system_name)
    if m is None or m.profile is None:
        return None
    star = next((b for b in m.bodies if b.orbits is None), None)
    if star is None:
        return None
    rows = m.profile.rows
    if not any(row.asteroids > 0.0 for row in rows):
        return None
    table = [(row.distance_gu, row.asteroids) for row in rows]
    if len(table) > MAX_TABLE_ROWS:
        if system_name not in _warned_truncate:
            _warned_truncate.add(system_name)
            print("[far] %s: asteroid profile has %d rows, truncating to %d"
                  % (system_name, len(table), MAX_TABLE_ROWS), file=sys.stderr)
        table = table[:MAX_TABLE_ROWS]
    seed = zlib.crc32(system_name.encode("utf-8")) & 0xffffffff
    from engine.rocks import far_dials
    return DiscSource(
        id=seed & 0x7fffffff,
        frame=system_name,
        centre_gu=tuple(star.position_gu),
        normal=(0.0, 0.0, 1.0),
        table=table,
        outer_fade_gu=far_dials.get("outer_fade_gu"),
        scale_height_frac=far_dials.get("scale_height_frac"),
        scale_height_min_gu=far_dials.get("scale_height_min_gu"),
        families={"silicate": 1.0},
        seed=seed,
    )


def sources_for_system(system_name: str) -> list:
    s = profile_belt(system_name)
    return [] if s is None else [s]


def _population_native(pop, rocks) -> dict:
    kind_name = "fragment" if pop.kind == 0 else "major"
    fam_weight = dict(pop.families)
    matched = [(i, fam_weight[r.family]) for i, r in enumerate(rocks)
              if r.kind == kind_name and r.family in fam_weight]
    indices = [i for i, _ in matched]
    weights = [w for _, w in matched]
    if indices:
        albedo = tuple(
            sum(rocks[i].avg_albedo[c] for i in indices) / len(indices)
            for c in range(3))
    else:
        albedo = (0.4, 0.4, 0.4)
    return {
        "kind": pop.kind,
        "density_at_1": pop.density_at_1,
        "a_lo": pop.a_lo,
        "a_hi": pop.a_hi,
        "r_min": pop.r_min,
        "r_max": pop.r_max,
        "exponent": pop.exponent,
        "rocks": indices,
        "weights": weights,
        "albedo": albedo,
    }


def to_native(source) -> dict:
    """The dict renderer.far_set_sources's disc_source_of() parses."""
    from engine.rocks import catalogue, field_table
    minor, major = field_table.populations(source.families)
    rocks = catalogue.load()
    return {
        "id": source.id,
        "frame": source.frame,
        "centre": tuple(source.centre_gu),
        "normal": tuple(source.normal),
        "table": [(r, a) for r, a in source.table[:MAX_TABLE_ROWS]],
        "outer_fade_gu": source.outer_fade_gu,
        "scale_height_frac": source.scale_height_frac,
        "scale_height_min_gu": source.scale_height_min_gu,
        "seed": source.seed,
        "explicit_regions": [(tuple(c), r) for c, r in source.explicit_regions],
        "populations": [_population_native(minor, rocks), _population_native(major, rocks)],
    }
