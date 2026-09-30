"""The rock catalogue: committed, generated rocks under native/assets/rocks.

Spec: docs/superpowers/specs/2026-09-30-rock-catalogue-design.md. The manifest is
read at USE (never at import) because the project asset root is resolved through
engine.paths. Stock BC asteroid NIFs are redirected to a deterministic catalogue
pick at the stock mesh's size; everything else loads unchanged.
"""
from __future__ import annotations

import json
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Optional

MODEL_UNITS_PER_METRE = 1.0 / 1.75

# Bounding radius (largest vertex distance from the model origin, BC model units)
# of each stock asteroid mesh. Measured from the NIFs; tests/unit/test_rock_stock_radius.py
# re-measures them. The h-variants and Amagon load these same files.
STOCK_RADIUS_MU: dict[str, float] = {
    "asteroid.nif": 75.779,
    "asteroid1.nif": 22.451,
    "asteroid2.nif": 65.624,
    "asteroid3.nif": 481.157,
}

# paths-guard: match pattern for stock asteroid NIFs, not a built path
_STOCK_DIR = ("data", "models", "misc", "asteroids")

_enabled = True
_memo: dict[str, tuple] = {}
_warned: set[str] = set()


@dataclass(frozen=True)
class Rock:
    id: str
    kind: str
    family: str
    lod_paths: tuple[str, ...]
    bound_radius_m: float
    avg_albedo: tuple[float, float, float]
    gloss: float
    impostor_albedo: str
    impostor_normal: str
    volume: str


def enabled() -> bool:
    return _enabled


def set_enabled(value: bool) -> None:
    global _enabled
    _enabled = bool(value)


def catalogue_root() -> Path:
    from engine import paths
    return Path(paths.project_asset_root()) / "rocks"


def load() -> tuple[Rock, ...]:
    root = catalogue_root()
    key = str(root)
    if key in _memo:
        return _memo[key]
    rocks: tuple[Rock, ...] = ()
    try:
        man = json.loads((root / "catalogue.json").read_text())
        rocks = tuple(
            Rock(id=r["id"], kind=r["kind"], family=r["family"],
                 lod_paths=tuple(str(root / p) for p in r["lods"]),
                 bound_radius_m=float(r["bound_radius_m"]),
                 avg_albedo=tuple(float(c) for c in r["avg_albedo"]),
                 gloss=float(r["gloss"]),
                 impostor_albedo=str(root / r["impostor"]["albedo"]),
                 impostor_normal=str(root / r["impostor"]["normal"]),
                 volume=str(root / r["volume"]))
            for r in man["rocks"])
    except (OSError, ValueError, KeyError, TypeError) as e:
        if key not in _warned:
            _warned.add(key)
            print(f"[rocks] rock catalogue unavailable at {root}: {e}; "
                  f"stock BC asteroid models will load", file=sys.stderr)
    _memo[key] = rocks
    return rocks


def pick(key: str, kind: str = "major", family: str = "silicate") -> Optional[Rock]:
    candidates = [r for r in load() if r.kind == kind and r.family == family]
    if not candidates:
        return None
    return candidates[zlib.crc32(key.encode("utf-8")) % len(candidates)]


def stock_key(nif_path) -> Optional[str]:
    parts = [p.lower() for p in PurePath(str(nif_path).replace("\\", "/")).parts]
    if len(parts) < 5 or tuple(parts[-5:-1]) != _STOCK_DIR:
        return None
    name = parts[-1]
    return name if name in STOCK_RADIUS_MU else None


def load_scale(rock: Rock, stock: str) -> float:
    return STOCK_RADIUS_MU[stock] / (rock.bound_radius_m * MODEL_UNITS_PER_METRE)


def ship_model_source(ship_name: str, nif_path: str) -> tuple[str, float]:
    if not _enabled:
        return nif_path, 1.0
    stock = stock_key(nif_path)
    if stock is None:
        return nif_path, 1.0
    rock = pick(ship_name)
    if rock is None:
        return nif_path, 1.0
    return rock.lod_paths[0], load_scale(rock, stock)
