"""Deterministic breakup plan for a rock (rock-class spec §2).

Pure: name + radius (+ generation) in, pieces out. Seeded by the parent's
name so the same rock always breaks the same way. A size-mix split: one
large piece, a few medium, many small; whatever volume is left is dust.
Large and medium pieces are majors (above kMajorMinRadiusGU), small ones are
chunks; then the generation cap and the per-death chunk cap.
"""
import math
import random
import zlib
from dataclasses import dataclass, replace

kMajorMinRadiusGU = 1.0
kChunkMinRadiusGU = 0.08
# Size-mix split after live test 2026-10-01 (Mark: every piece the same size
# read as no variety; he asked for one big, a few medium, many small -- e.g.
# 1 x 0.25, 4 x 0.1, 7 x 0.05 of the parent's volume). Fractions are of the
# parent's VOLUME, each drawn uniform in its range. If the drawn total
# exceeds kVolumeTotalMax the small pieces shrink first, then the medium; the
# large piece is never scaled, so it stays the largest. Replaces the retired
# kVolumeBudget (0.70) and kPieceCountMin/Max (2-3).
kLargeFracMin = 0.20
kLargeFracMax = 0.30
kMediumCountMin = 3
kMediumCountMax = 5
kMediumFracMin = 0.07
kMediumFracMax = 0.12
kSmallCountMin = 5
kSmallCountMax = 8
kSmallFracMin = 0.03
kSmallFracMax = 0.06
kVolumeTotalMax = 1.0
# Tuned after live test 2026-10-01 (unbounded generations read as a lagging
# cascade): a rock whose _rock_generation is already >= kMaxMajorGeneration
# breaks into chunks and dust only -- its would-be majors become chunks --
# and a death keeps at most kMaxChunksPerDeath chunks (the largest); the rest
# become dust. 8 since the size-mix split: up to 8 small pieces.
kMaxMajorGeneration = 1
kMaxChunksPerDeath = 8
# Large remnants listed as targets obstructed E1M2 (Mark's rule, live tests
# 2026-10-01): only the "large" piece may be targetable, and only when its
# BUILT radius is at least this; it then copies the parent's flag. Every
# other piece is untargetable. Scannable/hailable always copy.
kTargetableMinRadiusGU = 2.0
# 0.8 since the size-mix split (was 0.4): with up to six 3-5 GU majors, 0.4
# left sibling pairs overlapping past kGhostMaxTime. Tune by feel.
kSeparationSpeedGU = 0.8
# The large and medium pieces take spread directions: each takes the best of
# kSpreadCandidates seeded unit vectors, the one farthest from the majors
# already placed. Random directions nearly always gave one near-parallel pair
# that never separated (scenario A, 2026-10-01). Small pieces stay random.
kSpreadCandidates = 64
kTumbleRate = 0.5
# A breakup group (parent, major pieces, chunks, killer) ignores collisions
# pair by pair until that pair's contact spheres are kGhostSeparationMarginGU
# clear: pieces are born overlapping, and a grind contact would chain
# breakups. Pieces drift apart over 1-8 s (2026-10-01 cascade probe), so the
# old fixed 1 s window (kPieceGhostTime, retired) let still-overlapping
# siblings grind every frame. kGhostMaxTime is the safety cap: a pair that
# never separates is unmasked after it regardless.
kGhostSeparationMarginGU = 0.25
kGhostMaxTime = 10.0


@dataclass(frozen=True)
class PieceSpec:
    radius_gu: float
    offset: tuple
    v_ratio: float
    tier: str
    rank: str                # "large", "medium" or "small"


def _rng(name: str) -> random.Random:
    return random.Random(zlib.crc32(name.encode("utf-8")))


def _tier(r: float, rank: str) -> str:
    if r < kChunkMinRadiusGU:
        return "dust"
    if rank != "small" and r >= kMajorMinRadiusGU:
        return "major"
    return "chunk"


def _shrink(fracs: list, excess: float) -> float:
    """Scale `fracs` down in place by up to `excess` of their sum; return
    the excess still left."""
    total = sum(fracs)
    if excess <= 0.0 or total <= 0.0:
        return excess
    cut = min(excess, total)
    k = (total - cut) / total
    fracs[:] = [f * k for f in fracs]
    return excess - cut


def _fractions(rng) -> list:
    """[(rank, volume fraction)] in plan order: large, medium..., small..."""
    large = rng.uniform(kLargeFracMin, kLargeFracMax)
    medium = [rng.uniform(kMediumFracMin, kMediumFracMax)
              for _ in range(rng.randint(kMediumCountMin, kMediumCountMax))]
    small = [rng.uniform(kSmallFracMin, kSmallFracMax)
             for _ in range(rng.randint(kSmallCountMin, kSmallCountMax))]
    excess = large + sum(medium) + sum(small) - kVolumeTotalMax
    excess = _shrink(small, excess)
    _shrink(medium, excess)
    return ([("large", large)] + [("medium", v) for v in medium]
            + [("small", v) for v in small])


def _unit(rng) -> tuple:
    z = rng.uniform(-1.0, 1.0)
    t = rng.uniform(0.0, 2.0 * math.pi)
    s = math.sqrt(max(0.0, 1.0 - z * z))
    return (s * math.cos(t), s * math.sin(t), z)


def _spread_unit(rng, placed: list) -> tuple:
    """Best-candidate sampling: the seeded unit vector, of kSpreadCandidates,
    whose nearest already-placed direction is farthest away."""
    if not placed:
        return _unit(rng)
    return max((_unit(rng) for _ in range(kSpreadCandidates)),
               key=lambda c: min(math.dist(c, o) for o in placed))


def plan(parent_name: str, parent_radius_gu: float, generation: int = 0) -> list:
    """`generation` is the PARENT's _rock_generation (0 for a mission rock)."""
    rng = _rng(str(parent_name))
    out = []
    spread = []
    for rank, v in _fractions(rng):
        r = float(parent_radius_gu) * v ** (1.0 / 3.0)
        if rank == "small":
            offset = _unit(rng)
        else:
            offset = _spread_unit(rng, spread)
            spread.append(offset)
        out.append(PieceSpec(radius_gu=r, offset=offset, v_ratio=v,
                             tier=_tier(r, rank), rank=rank))
    if generation >= kMaxMajorGeneration:
        out = [replace(p, tier="chunk") if p.tier == "major" else p for p in out]
    chunks = sorted((i for i, p in enumerate(out) if p.tier == "chunk"),
                    key=lambda i: -out[i].radius_gu)
    for i in chunks[kMaxChunksPerDeath:]:
        out[i] = replace(out[i], tier="dust")
    return out
