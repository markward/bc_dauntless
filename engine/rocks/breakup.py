"""Deterministic breakup plan for a rock (rock-class spec §2).

Pure: name + radius (+ generation) in, pieces out. Seeded by the parent's
name so the same rock always breaks the same way. One remnant takes 30% of
the parent's volume; up to 12 small rocks of at most 1.5 GU take what they
can of the other 70%; whatever is left is dust. The remnant and every small
rock >= kMajorMinRadiusGU are majors, smaller ones are chunks; then the
generation cap and the per-death chunk cap.
"""
import math
import random
import zlib
from dataclasses import dataclass, replace

kMajorMinRadiusGU = 1.0
kChunkMinRadiusGU = 0.08
# Remnant + capped small rocks after live test 2026-10-01 (third: the
# size-mix split scaled every piece from the parent, so a big rock still threw
# out big pieces). Fractions are of the parent's VOLUME. The remnant is
# exactly kRemnantFrac. Small rocks draw radii uniform in
# [kSmallRadiusMinGU, kSmallRadiusMaxGU], clamped to the remnant's radius,
# and accumulate (r/R)^3 while the total stays <= kSmallVolumeFrac; a draw
# that would overflow is skipped. Stops at kSmallMaxCount pieces or after
# kSmallMaxDraws draws. When the remnant itself is below kSmallRadiusMinGU,
# the range becomes [kTinySmallRadiusMinFrac, kTinySmallRadiusMaxFrac] x the
# remnant's radius, so small rocks stay smaller than it. Replaces the
# retired kLarge*/kMedium*/kSmallCount*/kSmallFrac*/kVolumeTotalMax.
kRemnantFrac = 0.30
kSmallMaxCount = 12
kSmallRadiusMinGU = 0.5
kSmallRadiusMaxGU = 1.5
kSmallVolumeFrac = 0.70
kSmallMaxDraws = 48
kTinySmallRadiusMinFrac = 0.3
kTinySmallRadiusMaxFrac = 0.9
# Tuned after live test 2026-10-01 (unbounded generations read as a lagging
# cascade): a rock whose _rock_generation is already >= kMaxMajorGeneration
# breaks into chunks and dust only -- its would-be majors become chunks --
# and a death keeps at most kMaxChunksPerDeath chunks (the largest); the rest
# become dust. 8 since the size-mix split.
kMaxMajorGeneration = 1
kMaxChunksPerDeath = 8
# Large remnants listed as targets obstructed E1M2 (Mark's rule, live tests
# 2026-10-01): only the remnant may be targetable, and only when its
# BUILT radius is at least this; it then copies the parent's flag. Every
# other piece is untargetable. Scannable/hailable always copy.
kTargetableMinRadiusGU = 2.0
# 0.8 since the size-mix split (was 0.4): with several large majors, 0.4
# left sibling pairs overlapping past kGhostMaxTime. Tune by feel.
kSeparationSpeedGU = 0.8
# Every major (the remnant and each small rock >= kMajorMinRadiusGU) takes a
# spread direction: the best of kSpreadCandidates seeded unit vectors, the one
# farthest from the majors already placed. Random directions nearly always
# gave one near-parallel pair that never separated (scenario A, 2026-10-01).
# Chunk-sized pieces stay random.
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
    rank: str                # "remnant" or "small"


def _rng(name: str) -> random.Random:
    return random.Random(zlib.crc32(name.encode("utf-8")))


def _tier(r: float) -> str:
    if r < kChunkMinRadiusGU:
        return "dust"
    if r >= kMajorMinRadiusGU:
        return "major"
    return "chunk"


def _small_radii(rng, parent_r: float, remnant_r: float) -> list:
    if remnant_r < kSmallRadiusMinGU:
        lo = kTinySmallRadiusMinFrac * remnant_r
        hi = kTinySmallRadiusMaxFrac * remnant_r
    else:
        lo, hi = kSmallRadiusMinGU, kSmallRadiusMaxGU
    out = []
    took = 0.0
    for _ in range(kSmallMaxDraws):
        if len(out) >= kSmallMaxCount:
            break
        r = min(rng.uniform(lo, hi), remnant_r)
        v = (r / parent_r) ** 3
        if took + v > kSmallVolumeFrac:
            continue
        took += v
        out.append(r)
    return out


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
    """`generation` is the PARENT's _rock_generation (0 for a mission rock).
    Plan order: the remnant first, then the small rocks."""
    rng = _rng(str(parent_name))
    R = float(parent_radius_gu)
    remnant_r = R * kRemnantFrac ** (1.0 / 3.0)
    sized = [("remnant", remnant_r, kRemnantFrac)]
    if R > 0.0:
        sized += [("small", r, (r / R) ** 3)
                  for r in _small_radii(rng, R, remnant_r)]
    out = []
    spread = []
    for rank, r, v in sized:
        tier = _tier(r)
        if tier == "major":
            offset = _spread_unit(rng, spread)
            spread.append(offset)
        else:
            offset = _unit(rng)
        out.append(PieceSpec(radius_gu=r, offset=offset, v_ratio=v,
                             tier=tier, rank=rank))
    if generation >= kMaxMajorGeneration:
        out = [replace(p, tier="chunk") if p.tier == "major" else p for p in out]
    chunks = sorted((i for i, p in enumerate(out) if p.tier == "chunk"),
                    key=lambda i: -out[i].radius_gu)
    for i in chunks[kMaxChunksPerDeath:]:
        out[i] = replace(out[i], tier="dust")
    return out
