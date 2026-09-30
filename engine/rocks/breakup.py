"""Deterministic breakup plan for a rock (rock-class spec §2).

Pure: name + radius in, pieces out. Seeded by the parent's name so the same
rock always breaks the same way. kVolumeBudget of the parent's volume goes
into pieces; the rest is dust. Tier by piece radius.
"""
import math
import random
import zlib
from dataclasses import dataclass

kMajorMinRadiusGU = 1.0
kChunkMinRadiusGU = 0.08
kVolumeBudget = 0.70
kPieceCountMin = 2
kPieceCountMax = 5
kSeparationSpeedGU = 0.4
kTumbleRate = 0.5
# Seconds a new major piece ignores collisions with its siblings and parent:
# pieces are born overlapping, and a grind contact would chain breakups.
kPieceGhostTime = 1.0


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


def plan(parent_name: str, parent_radius_gu: float) -> list:
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
    return out
