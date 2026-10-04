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
from typing import Optional

MAX_TABLE_ROWS = 32   # rows sent per source (the old haze shader's cap, kept)

_warned_truncate: set = set()
_warned_no_match: set = set()


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
    # Tile fields (2026-10-02): renderer::far::DiscSource's twins. A
    # "sphere" is an AsteroidField: a == 1 inside, a linear ramp to 0 over
    # the outer sphere_edge_frac of sphere_radius_gu; table unused.
    shape: str = "disc"
    procedural: bool = True        # False: not a belt (native generates no rocks for any source)
    view_space: bool = False       # centre_gu in the viewed set's view space
    sphere_radius_gu: float = 0.0
    sphere_edge_frac: float = 0.2
    # Field noise (every shape since rock-fields R1, 2026-10-02): 0 = off.
    # Belts set the belt_noise_* dials, tile fields the tile_haze_noise_* ones.
    noise_scale_gu: float = 0.0
    noise_contrast: float = 0.0
    noise_octaves: int = 0
    # spike/rock-specks: clump sharpness (1 = off) and the sphere outline
    # warp (0 = off; scale in GU). renderer::far::DiscSource's twins.
    noise_sharpness: float = 1.0
    shape_warp: float = 0.0
    shape_warp_scale_gu: float = 0.0
    pops: Optional[tuple] = None   # explicit populations; None = field_table's


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
        noise_scale_gu=float(far_dials.get("belt_noise_scale_gu")),
        noise_contrast=float(far_dials.get("belt_noise_contrast")),
        noise_octaves=int(far_dials.get("belt_noise_octaves")),
    )


def sources_for_system(system_name: str) -> list:
    s = profile_belt(system_name)
    return [] if s is None else [s]


def tile_field_source(field_obj, view_set, set_name: str, offset: tuple):
    """An AsteroidField's sphere density source, or None when it has no rocks.

    One minor population of density count / (4/3 pi R^3), count = tiles^3 x
    per-tile x tile_count_mult, sizes from the minor_dials tile_* keys, at
    the field's location in VIEW space (`offset` = offset_between(view,
    set)), seeded by crc32("tile:<set>:<name>"). These are the numbers the
    retired tile minor cloud used; test_far_density pins them."""
    from engine.rocks import far_dials, field_table
    from engine.rocks import minor_dials as md
    tiles = int(field_obj.GetNumTilesPerAxis())
    count = int(round(tiles ** 3 * field_obj.GetNumAsteroidsPerTile()
                      * md.get("tile_count_mult")))
    radius = float(field_obj.GetFieldRadius())
    if count <= 0 or radius <= 0.0:
        return None
    loc = field_obj.GetWorldLocation()
    point = (loc.x + offset[0], loc.y + offset[1], loc.z + offset[2])
    r_min = float(md.get("tile_r_min_gu"))
    r_max = max(r_min, md.get("tile_r_per_size_factor")
                * float(field_obj.GetAsteroidSizeFactor()))
    family = "silicate"
    pop = field_table.Population(
        kind=0,
        density_at_1=count / (4.0 / 3.0 * math.pi * radius ** 3),
        a_lo=0.0, a_hi=1.0,
        r_min=r_min, r_max=r_max,
        exponent=float(md.get("tile_size_exponent")),
        families=((family, 1.0),))
    key = "tile:%s:%s" % (set_name, field_obj.GetName())
    seed = zlib.crc32(key.encode("utf-8")) & 0xffffffff
    return DiscSource(
        id=seed & 0x7fffffff,
        frame=set_name,
        centre_gu=point,
        normal=(0.0, 0.0, 1.0),
        table=[],
        outer_fade_gu=0.0,
        scale_height_frac=0.0,
        scale_height_min_gu=0.0,
        families={family: 1.0},
        seed=seed,
        shape="sphere",
        procedural=False,
        view_space=True,
        sphere_radius_gu=radius,
        sphere_edge_frac=float(far_dials.get("tile_haze_edge_frac")),
        noise_scale_gu=float(far_dials.get("tile_haze_noise_scale_gu")),
        noise_contrast=float(far_dials.get("tile_haze_noise_contrast")),
        noise_octaves=int(far_dials.get("tile_haze_noise_octaves")),
        noise_sharpness=float(far_dials.get("tile_noise_sharpness")),
        shape_warp=float(far_dials.get("tile_shape_warp")),
        shape_warp_scale_gu=radius * float(far_dials.get("tile_shape_warp_scale_frac")),
        pops=(pop,),
    )


def _kind_name(pop) -> str:
    return "fragment" if pop.kind == 0 else "major"


def _population_native(pop, rocks):
    """The native population dict, or None when no catalogue rock matches
    this population's kind + families -- an empty `rocks`/`weights` list
    would still carry a live `density_at_1` into native, and
    renderer::far::pick_rock renders every generated rock of an empty
    population as catalogue index 0 regardless of kind or family."""
    kind_name = _kind_name(pop)
    fam_weight = dict(pop.families)
    matched = [(i, fam_weight[r.family]) for i, r in enumerate(rocks)
              if r.kind == kind_name and r.family in fam_weight]
    if not matched:
        return None
    indices = [i for i, _ in matched]
    weights = [w for _, w in matched]
    albedo = tuple(
        sum(rocks[i].avg_albedo[c] for i in indices) / len(indices)
        for c in range(3))
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
    """The dict renderer.far_set_sources's disc_source_of() parses.

    A population with no matching catalogue rock is OMITTED, not sent
    empty (one [far] warning per (system, kind), deduped like
    profile_belt's own truncation warning). A source that ends up with no
    populations at all is still emitted -- the bands then simply find
    nothing to draw for it."""
    from engine.rocks import catalogue, field_table
    wanted = (source.pops if source.pops is not None
              else field_table.populations(source.families))
    rocks = catalogue.load()
    pops = []
    for pop in wanted:
        native_pop = _population_native(pop, rocks)
        if native_pop is None:
            key = (source.frame, _kind_name(pop))
            if key not in _warned_no_match:
                _warned_no_match.add(key)
                print("[far] %s: no catalogue rocks match kind=%s families=%s; "
                      "population dropped"
                      % (source.frame, _kind_name(pop), dict(pop.families)),
                      file=sys.stderr)
            continue
        pops.append(native_pop)
    out = {
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
        "populations": pops,
        "shape": source.shape,
        "procedural": source.procedural,
        "view_space": source.view_space,
        "sphere_radius_gu": source.sphere_radius_gu,
        "sphere_edge_frac": source.sphere_edge_frac,
        # Every shape carries the noise (rock-fields R1).
        "noise_scale_gu": source.noise_scale_gu,
        "noise_contrast": source.noise_contrast,
        "noise_octaves": source.noise_octaves,
        "noise_sharpness": source.noise_sharpness,
        "shape_warp": source.shape_warp,
        "shape_warp_scale_gu": source.shape_warp_scale_gu,
    }
    return out
