"""Planet surface-detail catalogue entries (spec
docs/superpowers/specs/2026-10-08-planet-surface-detail-design.md §7).

`surface` is a nested object inside an atmospheres.json entry. It resolves
INDEPENDENTLY of the atmosphere fields: a "<set>/<name>" override that has no
`surface` inherits the NIF stem's, and `atmosphere: false` disables only the
air. A malformed `surface` warns once and drops only the detail. Resolved at
USE through atmosphere.load(), never at import.
"""
from __future__ import annotations

import zlib
from dataclasses import dataclass

from engine.planets import atmosphere as _atmo

TYPE_CODES: dict = {"none": 0, "rocky": 1, "desert": 2, "ice": 3, "gas": 4, "ocean": 5}
_FIELDS = {"type", "ocean", "ocean_tolerance", "strength", "albedo", "scale"}

_live: list = []

# In-memory overlay set by the "surface" dev dial group (Task 10):
# key -> Surface, consulted by resolve_surface() before the catalogue file.
# Cleared by reload() so the dev "Reload Planet Surfaces" action drops live
# tuning along with re-reading the catalogue (atmosphere._overrides mirror).
_overrides: dict = {}


@dataclass(frozen=True)
class Surface:
    type: str
    ocean: tuple | None          # linear RGB water key, or None
    ocean_tolerance: float = 0.15
    strength: float = 1.0
    albedo: float = 1.0
    scale: float = 1.0
    seed: int = 0                # crc32 of the resolved catalogue key


@dataclass(frozen=True)
class LiveSurface:
    iid: object
    set_name: str
    obj_name: str
    nif_path: str
    source: str = "set"


def _num(obj: dict, name: str, lo: float, hi: float, default: float,
         lo_open: bool = False) -> float:
    if name not in obj:
        return default
    v = obj[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"surface.{name} must be a number")
    v = float(v)
    if (v <= lo if lo_open else v < lo) or v > hi:
        raise ValueError(f"surface.{name}={v} out of range")
    return v


def parse_surface(obj, seed: int):
    if not isinstance(obj, dict):
        raise ValueError("surface must be an object")
    unknown = set(obj) - _FIELDS
    if unknown:
        raise ValueError(f"unknown surface field(s) {sorted(unknown)}")
    t = obj.get("type")
    if t not in TYPE_CODES:
        raise ValueError(f"surface.type {t!r} not one of {sorted(TYPE_CODES)}")
    if t == "none":
        return None
    ocean = _atmo.srgb_hex_to_linear(obj["ocean"]) if "ocean" in obj else None
    return Surface(
        type=t, ocean=ocean,
        ocean_tolerance=_num(obj, "ocean_tolerance", 0.0, 1.0, 0.15, lo_open=True),
        strength=_num(obj, "strength", 0.0, 4.0, 1.0),
        albedo=_num(obj, "albedo", 0.0, 4.0, 1.0),
        scale=_num(obj, "scale", 0.25, 4.0, 1.0),
        seed=seed,
    )


def resolve_surface_key(set_name: str, obj_name: str, nif_path: str):
    raw = _atmo.load()
    override = f"{set_name}/{obj_name}"
    if set_name and isinstance(raw.get(override), dict) and "surface" in raw[override]:
        return override
    stem = _atmo.nif_stem(nif_path)
    if isinstance(raw.get(stem), dict) and "surface" in raw[stem]:
        return stem
    return None


def resolve_surface(set_name: str, obj_name: str, nif_path: str):
    key = resolve_surface_key(set_name, obj_name, nif_path)
    if key is None:
        return None
    if key in _overrides:
        return _overrides[key]
    try:
        return parse_surface(_atmo.load()[key]["surface"],
                             seed=zlib.crc32(key.encode("utf-8")))
    except (ValueError, KeyError, TypeError) as e:
        _atmo._warn(str(_atmo.catalogue_path()), key + "#surface",
                    f"malformed surface ({e}); no surface detail")
        return None


def set_override(key: str, s: Surface) -> None:
    """Overlay `key`'s resolved Surface with `s` (the "surface" dev dial
    group, Task 10). Takes effect for every planet that resolves to `key`,
    not only the one the dial targeted -- the dial edits the CATALOGUE
    entry, not one instance (mirrors engine.planets.atmosphere.set_override)."""
    _overrides[key] = s


def reload() -> None:
    """Drop every dial override. Does NOT clear the shared atmosphere file
    memo -- the "Reload Planet Surfaces" action calls atmosphere.reload()
    separately to re-read the catalogue file (the two 'surface' and
    'atmosphere' blocks live in the same JSON, loaded through one memo)."""
    _overrides.clear()


def to_binding(s):
    if s is None:
        return None
    ocean = tuple(float(c) for c in s.ocean) if s.ocean is not None else (0.0, 0.0, 0.0)
    return (TYPE_CODES[s.type], ocean, s.ocean is not None, float(s.ocean_tolerance),
            float(s.strength), float(s.albedo), float(s.scale), int(s.seed))


def record_live(iid, set_name: str, obj_name: str, nif_path: str, source: str = "set") -> None:
    _live.append(LiveSurface(iid, set_name, obj_name, nif_path, source))


def forget_live(iid) -> None:
    _live[:] = [lp for lp in _live if not _atmo.iid_eq(lp.iid, iid)]


def clear_live() -> None:
    _live.clear()


def clear_live_for_set(set_name: str) -> None:
    _live[:] = [lp for lp in _live if not (lp.source == "set" and lp.set_name == set_name)]


def live() -> tuple:
    return tuple(_live)
