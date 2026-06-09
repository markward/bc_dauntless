"""DamageDisplay atlas tracer + subsystem-class → enum mapping.

BC's damage display picks a glyph per-subsystem at instantiation
time based on the subsystem's C++ type — see the comment in
``sdk/Build/scripts/Icons/DamageIcons.py:17`` ("Icon numbers should
match up with DamageIcon::DamageIcons enum"). We mirror that with
an explicit Python class table.

Glyph sources live as standalone 16x16 TGAs under
``game/data/Icons/Damage/`` (Hull.tga, Impulse.tga, ...). Trace
pipeline is the shared ``engine.ui.icon_tracer`` flow used by
``engine.ui.weapon_icons``. Cache: ``cache/icons/damage/{num}.svg``.
Curated overrides: ``native/assets/ui-cef/icons/damage/{num}.svg``.
"""
from __future__ import annotations

import os
import subprocess
from typing import Optional

from engine.appc import subsystems as ss
from engine.ui.icon_tracer import (
    IconSpec,
    PotraceMissingError,
    _extract_region_from_tga,
    _needs_rebuild,
    _trace_to_svg,
    _wrap_with_inset_clip,
)


_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
_DAMAGE_DIR = os.path.join(_PROJECT_ROOT, "game", "data", "Icons", "Damage")
_CURATED_DIR = os.path.join(
    _PROJECT_ROOT, "native", "assets", "ui-cef", "icons", "damage",
)
_SVG_CACHE_DIR = os.path.join(_PROJECT_ROOT, "cache", "icons", "damage")


# Damage TGAs are 16x16 standalone files (not an atlas), so every
# IconSpec uses (0, 0, 16, 16) with no transform. Numbers mirror the
# DamageIcons enum at sdk/Build/scripts/Icons/DamageIcons.py:17-56.
ICON_REGISTRY: dict[int, IconSpec] = {
    0: IconSpec("Hull.tga",     0, 0, 16, 16),
    1: IconSpec("Impulse.tga",  0, 0, 16, 16),
    2: IconSpec("Phaser.tga",   0, 0, 16, 16),
    3: IconSpec("Power.tga",    0, 0, 16, 16),
    4: IconSpec("Sensor.tga",   0, 0, 16, 16),
    5: IconSpec("Shield.tga",   0, 0, 16, 16),
    6: IconSpec("System.tga",   0, 0, 16, 16),
    7: IconSpec("Torpedo.tga",  0, 0, 16, 16),
    8: IconSpec("Warp.tga",     0, 0, 16, 16),
    9: IconSpec("Disruptor.tga", 0, 0, 16, 16),
}


# Class → enum. First matching isinstance wins, so order subclasses
# before their superclasses if any are listed. The default fallback
# is 6 (System) per the SDK comment.
_CLASS_TABLE: tuple = (
    (ss.HullSubsystem,          0),
    (ss.ImpulseEngineSubsystem, 1),
    (ss.PhaserBank,             2),
    (ss.PowerSubsystem,         3),
    (ss.SensorSubsystem,        4),
    (ss.ShieldSubsystem,        5),
    (ss.TorpedoTube,            7),
    (ss.WarpEngineSubsystem,    8),
    (ss.PulseWeapon,            9),
)


ICON_SYSTEM_FALLBACK = 6  # SDK DamageIcons.System; default glyph for unknown / non-subsystem types


def icon_num_for_subsystem(sub) -> int:
    """Returns the BC DamageIcons enum value for a ShipSubsystem.
    Unknown / None / non-subsystem inputs fall back to 6 (System)."""
    if sub is None:
        return ICON_SYSTEM_FALLBACK
    for cls, num in _CLASS_TABLE:
        if isinstance(sub, cls):
            return num
    return ICON_SYSTEM_FALLBACK


# ── Resolver ───────────────────────────────────────────────────────────

_svg_cache: dict[int, Optional[str]] = {}


def reset_cache() -> None:
    """Drop the in-memory SVG cache. Tests use this between cases."""
    _svg_cache.clear()


def trace_all() -> set[int]:
    """Trace every registered icon into the cache dir. Skips icons
    whose source TGA is missing or whose cache entry is up-to-date.
    Swallows individual potrace failures (one bad icon doesn't block
    the others). Same idempotency contract as weapon_icons.trace_all.
    """
    os.makedirs(_SVG_CACHE_DIR, exist_ok=True)
    written: set[int] = set()
    tga_cache: dict[str, bytes] = {}
    for num, spec in ICON_REGISTRY.items():
        out_path = os.path.join(_SVG_CACHE_DIR, f"{num}.svg")
        source_path = os.path.join(_DAMAGE_DIR, spec.tga)
        if not os.path.isfile(source_path):
            continue
        if not _needs_rebuild(out_path, source_path):
            continue
        if spec.tga not in tga_cache:
            with open(source_path, "rb") as fp:
                tga_cache[spec.tga] = fp.read()
        try:
            w, h, rgba = _extract_region_from_tga(
                tga_cache[spec.tga],
                spec.x, spec.y, spec.w, spec.h,
                spec.rotate, spec.mirror,
            )
            svg = _trace_to_svg(rgba, w, h)
        except (subprocess.CalledProcessError, PotraceMissingError):
            continue
        with open(out_path, "w") as fp:
            fp.write(svg)
        written.add(num)
    return written


def icon_svg_for_num(num: int) -> Optional[str]:
    """Returns SVG text for a DamageIcons enum value, or None for
    unknown numbers / missing source TGA / potrace not installed.

    Lookup order:
    1. Curated ``native/assets/ui-cef/icons/damage/{num}.svg``
    2. Auto-traced ``cache/icons/damage/{num}.svg`` (first call
       triggers ``trace_all`` for the whole registry)
    """
    if num in _svg_cache:
        return _svg_cache[num]
    if num not in ICON_REGISTRY:
        _svg_cache[num] = None
        return None
    curated_path = os.path.join(_CURATED_DIR, f"{num}.svg")
    if os.path.isfile(curated_path):
        with open(curated_path, "r", encoding="utf-8") as fp:
            svg = fp.read()
        svg = _wrap_with_inset_clip(svg)
        _svg_cache[num] = svg
        return svg
    svg_path = os.path.join(_SVG_CACHE_DIR, f"{num}.svg")
    if not os.path.isfile(svg_path):
        try:
            trace_all()
        except OSError:
            _svg_cache[num] = None
            return None
    if not os.path.isfile(svg_path):
        _svg_cache[num] = None
        return None
    with open(svg_path, "r", encoding="utf-8") as fp:
        svg = fp.read()
    svg = _wrap_with_inset_clip(svg)
    _svg_cache[num] = svg
    return svg
