"""The rock catalogue: committed, generated rocks under native/assets/rocks.

Spec: docs/superpowers/specs/2026-09-30-rock-catalogue-design.md. The manifest is
read at USE (never at import) because the project asset root is resolved through
engine.paths. Stock BC asteroid NIFs are redirected to a deterministic catalogue
pick at the stock mesh's size; everything else loads unchanged.
"""
from __future__ import annotations

import json
import os
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Optional

MODEL_UNITS_PER_METRE = 1.0 / 1.75

# Bounding radius (largest vertex distance from the model origin, BC model units)
# of each stock asteroid mesh. Measured from the NIFs; tests/unit/test_rock_stock_radius.py
# re-measures them. ships/Asteroidh1-3.py load their own files, asteroidh1-3.NIF:
# separate paths, but the same meshes as asteroid1-3 (same size, vertex count
# and bound), so the same radii.
STOCK_RADIUS_MU: dict[str, float] = {
    "asteroid.nif": 75.779,
    "asteroid1.nif": 22.451,
    "asteroid2.nif": 65.624,
    "asteroid3.nif": 481.157,
    "asteroidh1.nif": 22.451,
    "asteroidh2.nif": 65.624,
    "asteroidh3.nif": 481.157,
}

# paths-guard: match pattern for stock asteroid NIFs, not a built path
_STOCK_DIR = ("data", "models", "misc", "asteroids")

_enabled = True
_memo: dict[str, tuple] = {}
_warned: set[str] = set()
_memo_view_dirs: dict[str, tuple] = {}


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


def impostor_view_dirs() -> tuple:
    """The 64 impostor bake view directions (an 8x8 octahedral layout,
    rock-blend 2026-10-03; far-tier plan Task 9), read from catalogue.json at
    USE and memoised per root like load()."""
    root = catalogue_root()
    key = str(root)
    if key in _memo_view_dirs:
        return _memo_view_dirs[key]
    dirs: tuple = ()
    try:
        man = json.loads((root / "catalogue.json").read_text())
        dirs = tuple(tuple(float(c) for c in d) for d in man.get("impostor_view_dirs", []))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    _memo_view_dirs[key] = dirs
    return dirs


def index_of_path(path) -> int:
    """The position in load() of the rock whose lod_paths[0] normalises to
    `path`, or -1."""
    target = os.path.normpath(str(path))
    for i, r in enumerate(load()):
        if r.lod_paths and os.path.normpath(r.lod_paths[0]) == target:
            return i
    return -1


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


def _under_game_root(nif_path) -> bool:
    """Whether `nif_path` resolves inside the CONFIGURED BC install root.

    A mod override (or any path a mod tree served instead) lies outside
    `paths.game_root()`, so it is never a genuine stock BC asteroid NIF even
    if its basename matches one -- the mod author's own mesh wins, not the
    catalogue. Resolved at USE, like every other paths.py consumer; never
    captured. Any failure to resolve the root (e.g. unconfigured) is treated
    as "not under the root" so the catalogue never blocks spawn.
    """
    from engine import paths
    try:
        root = paths.game_root()
    except Exception:
        return False
    root_parts = PurePath(str(root).replace("\\", "/")).parts
    path_parts = PurePath(str(nif_path).replace("\\", "/")).parts
    return path_parts[:len(root_parts)] == root_parts


def redirected_stock(nif_path) -> Optional[str]:
    """The stock asteroid basename `nif_path` redirects from, or None when it
    does not redirect (catalogue off, not a stock asteroid NIF, or not under
    the configured BC install root -- R13)."""
    if not _enabled:
        return None
    stock = stock_key(nif_path)
    if stock is None or not _under_game_root(nif_path):
        return None
    return stock


def ship_model_source(ship_name: str, nif_path: str) -> tuple[str, float]:
    stock = redirected_stock(nif_path)
    if stock is None:
        return nif_path, 1.0
    rock = pick(ship_name)
    if rock is None:
        return nif_path, 1.0
    return rock.lod_paths[0], load_scale(rock, stock)
