"""Deterministic breakup plan for a rock (rock-class spec §2).

Pure: name + radius (+ generation) in, pieces out. Seeded by the parent's
name so the same rock always breaks the same way. kVolumeBudget of the
parent's volume goes into pieces; the rest is dust. Tier by piece radius,
then the generation cap and the per-death chunk cap.
"""
import math
import random
import zlib
from dataclasses import dataclass, replace

kMajorMinRadiusGU = 1.0
kChunkMinRadiusGU = 0.08
kVolumeBudget = 0.70
kPieceCountMin = 2
kPieceCountMax = 3
# Tuned after live test 2026-10-01 (5 pieces and unbounded generations read as
# a lagging cascade): a rock whose _rock_generation is already
# >= kMaxMajorGeneration breaks into chunks and dust only -- its would-be
# majors become chunks -- and a death keeps at most kMaxChunksPerDeath chunks
# (the largest); the rest become dust.
kMaxMajorGeneration = 1
kMaxChunksPerDeath = 3
kSeparationSpeedGU = 0.4
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


def _rng(name: str) -> random.Random:
    return random.Random(zlib.crc32(name.encode("utf-8")))


def _tier(r: float) -> str:
    if r >= kMajorMinRadiusGU:
        return "major"
    if r >= kChunkMinRadiusGU:
        return "chunk"
    return "dust"


def _unit(rng) -> tuple:
    z = rng.uniform(-1.0, 1.0)
    t = rng.uniform(0.0, 2.0 * math.pi)
    s = math.sqrt(max(0.0, 1.0 - z * z))
    return (s * math.cos(t), s * math.sin(t), z)


def plan(parent_name: str, parent_radius_gu: float, generation: int = 0) -> list:
    """`generation` is the PARENT's _rock_generation (0 for a mission rock)."""
    rng = _rng(str(parent_name))
    n = rng.randint(kPieceCountMin, kPieceCountMax)
    weights = [rng.uniform(0.3, 1.0) for _ in range(n)]
    total = sum(weights)
    ratios = [kVolumeBudget * w / total for w in weights]
    # Make the budget exact despite float summation.
    ratios[-1] = kVolumeBudget - sum(ratios[:-1])
    out = []
    for v in ratios:
        r = float(parent_radius_gu) * v ** (1.0 / 3.0)
        out.append(PieceSpec(radius_gu=r, offset=_unit(rng), v_ratio=v, tier=_tier(r)))
    if generation >= kMaxMajorGeneration:
        out = [replace(p, tier="chunk") if p.tier == "major" else p for p in out]
    chunks = sorted((i for i, p in enumerate(out) if p.tier == "chunk"),
                    key=lambda i: -out[i].radius_gu)
    for i in chunks[kMaxChunksPerDeath:]:
        out[i] = replace(out[i], tier="dust")
    return out
