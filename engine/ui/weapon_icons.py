"""WeaponsDisplay atlas tracer.

Mirrors ``sdk/Build/scripts/Icons/WeaponIcons.py``: a registry of icon
numbers → ``(tga, x, y, w, h, rotate, mirror)`` tuples that name a
region of one of BC's two atlas TGAs (``PhaserArcs.tga`` and
``PhaserFields.tga`` under ``game/data/Icons/``).

We trace each sprite to **SVG** rather than slicing to PNG. The atlas
images are tiny (4×6 to 54×24 px) and the panel renders them at a
larger size — bitmap sprites blur on high-DPI displays. Vector traces
stay crisp at any zoom and, more importantly, can be themed at runtime
(``fill="currentColor"`` lets CSS swap colour for in-range glow,
faction tinting, damage state, etc.).

Pipeline:

1. Decode the TGA via ``engine.ui.tga``, crop the registered region,
   apply the declared rotation + mirror (all in pure Python).
2. Convert the alpha channel to a greyscale PGM (ink-on-white).
3. Pipe the PGM through ``mkbitmap -s 4 -f 4 -3 -t 0.5`` — scales up
   4×, applies a cubic-interpolation high-pass filter, thresholds to
   monochrome. Critical for the tiny atlas sprites (the 4×6 torpedo
   glyph would otherwise turn into a chunky polygon). mkbitmap ships
   in the same package as potrace.
4. Pipe the resulting PBM through ``potrace --svg``. Output viewBox
   is in 4× coords; we keep that and ask the browser to render at
   the original pixel dimensions, so the extra resolution turns
   into crisper curves rather than a bigger sprite.
5. Post-process the SVG: native pixel dimensions, ``currentColor``
   fill so CSS owns the colour.
6. Cache to ``cache/icons/weapons/{num}.svg`` (gitignored — first
   ``icon_svg_for_num`` call after a fresh checkout traces and writes;
   subsequent calls read from disk).

The cache layout is mod-safe: if a third-party mod ships a replacement
``PhaserArcs.tga`` with new icon shapes or extends ``WeaponIcons.py``
with new sprite numbers, the cache regenerates on first use (the cache
is gitignored so stale entries from a prior install don't survive a
mod swap that bumps TGA mtime). Cache-key files newer than the source
TGA stay; older or missing ones are re-traced.

Registry coordinates are top-left-origin. The TGA decoder normalises
bottom-left source files (descriptor bit 5 clear, which is what BC's
TGAs use) to top-left at decode time, so tracer code never has to
think about origin orientation again.
"""
from __future__ import annotations

import os
from typing import Optional

from engine.ui.png_encoder import encode_png_rgb
from engine.ui.icon_tracer import (
    IconSpec,
    ROTATE_0, ROTATE_180,
    MIRROR_NONE, MIRROR_HORIZONTAL, MIRROR_VERTICAL,
    PotraceMissingError,
    _crop_rgba, _mirror_horizontal, _mirror_vertical, _rotate_180,
    _apply_transform, _extract_region_from_tga, _rgba_to_pgm,
    _potrace_available, _trace_to_svg, _normalize_svg,
    _wrap_with_inset_clip, _needs_rebuild,
)

# subprocess used by trace_atlas error handling.
import subprocess


# Anchor source + output directories at the project root rather than
# CWD. The native host (init_frame / dust_set_enabled / etc.) can
# chdir away from the project root during startup, after which a
# CWD-relative "cache/..." path resolves to nowhere. ship_icons.py
# documents the same risk.
_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)

# Source TGAs live under game/data/Icons/.
_GAME_ICONS_DIR = os.path.join(_PROJECT_ROOT, "game", "data", "Icons")

# Hand-authored SVGs (checked in). When a file exists here for a given
# icon number it overrides the auto-traced fallback — the trace is a
# best-effort approximation, but BC's stock atlas is small enough to
# polish by hand and we want the headline icons crisp. Mod sprites and
# any unauthored stock icons fall through to the cache.
_CURATED_DIR = os.path.join(
    _PROJECT_ROOT, "native", "assets", "ui-cef", "icons", "weapons",
)

# Rasterised reference PNGs (checked in). 24-bit RGB, native sprite
# dimensions, transparent atlas pixels flattened to black so the icon
# reads white-on-black like the BC HUD. Generated alongside the SVG
# trace via ``export_reference_pngs`` so authors hand-editing the
# committed SVG have a pixel-accurate source to trace from.
_REFERENCE_DIR = os.path.join(_CURATED_DIR, "reference")

# SVG trace cache — gitignored, regenerates on first use after a
# mod swaps the source TGA.
_SVG_CACHE_DIR = os.path.join(_PROJECT_ROOT, "cache", "icons", "weapons")


# ── Registry ────────────────────────────────────────────────────────────
# Mirrors LoadWeaponIcons in sdk/Build/scripts/Icons/WeaponIcons.py.
# Numbers 0 (Destroyed.tga default) and 270 (kessokmine typo) are
# omitted intentionally — they signal "no icon" to the panel.

_ARCS = "PhaserArcs.tga"

ICON_REGISTRY: dict[int, IconSpec] = {
    # ── Phaser Firing Arcs (PhaserArcs.tga) ─────────────────────────
    330: IconSpec(_ARCS,  0,   0, 54, 24),                                       # Top Left
    335: IconSpec(_ARCS,  0,   0, 54, 24, ROTATE_0,   MIRROR_VERTICAL),          # Bottom Left Curve
    340: IconSpec(_ARCS,  0,  28, 31, 54),                                       # Bottom Left Hook
    350: IconSpec(_ARCS,  0,   0, 54, 24, ROTATE_0,   MIRROR_HORIZONTAL),        # Top Right
    355: IconSpec(_ARCS,  0,   0, 54, 24, ROTATE_180, MIRROR_NONE),              # Bottom Right Curve
    360: IconSpec(_ARCS,  0,  28, 31, 54, ROTATE_0,   MIRROR_HORIZONTAL),        # Bottom Right Hook
    361: IconSpec(_ARCS, 47,  28, 16, 40),                                       # Left
    362: IconSpec(_ARCS, 47,  28, 16, 40, ROTATE_0,   MIRROR_HORIZONTAL),        # Right
    363: IconSpec(_ARCS, 33,  87, 30, 10, ROTATE_0,   MIRROR_VERTICAL),          # Rear
    364: IconSpec(_ARCS, 33,  87, 30, 10),                                       # Forward
    # ── Disruptor cannons (PhaserArcs.tga) ──────────────────────────
    365: IconSpec(_ARCS,  0, 107,  5, 10),                                       # Forward disruptor
    366: IconSpec(_ARCS,  0, 107,  5, 10, ROTATE_0,   MIRROR_VERTICAL),          # Rear disruptor
    # ── Torpedo (PhaserArcs.tga) ────────────────────────────────────
    370: IconSpec(_ARCS,  0, 122,  4,  6),                                       # Torpedo glyph
    # Indicator overlays (500-515 from PhaserFields.tga) used to live
    # here, but the panel now expresses "in firing arc" via a CSS
    # stroke around the arc shape rather than a separate sprite layer.
    # The SDK property setters (SetIndicatorIconNum etc.) still exist
    # for SDK fidelity but nothing reads them.
}


# ── Tracer ──────────────────────────────────────────────────────────────

def trace_atlas(tga_dir: str, registry: dict[int, IconSpec],
                output_dir: str) -> set[int]:
    """Trace every registered icon under ``tga_dir`` into
    ``output_dir/{num}.svg``. Returns the set of icon numbers actually
    written this call — fresh cached SVGs are skipped.

    Missing source TGAs are skipped silently so a developer without
    the BC install still gets the rest of the icons. Potrace failures
    on individual sprites are swallowed too — a corrupt sprite
    shouldn't block the rest of the atlas.
    """
    os.makedirs(output_dir, exist_ok=True)
    written: set[int] = set()
    tga_cache: dict[str, bytes] = {}

    for num, spec in registry.items():
        out_path = os.path.join(output_dir, f"{num}.svg")
        source_path = os.path.join(tga_dir, spec.tga)
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


def trace_all(tga_dir: Optional[str] = None,
              output_dir: Optional[str] = None) -> set[int]:
    """Convenience wrapper using the default game / cache directories."""
    return trace_atlas(
        tga_dir=tga_dir or _GAME_ICONS_DIR,
        registry=ICON_REGISTRY,
        output_dir=output_dir or _SVG_CACHE_DIR,
    )


# ── Reference PNG export ───────────────────────────────────────────────

def _rgba_to_rgb_on_black(rgba: bytes, w: int, h: int) -> bytes:
    """Flatten RGBA onto an opaque black background → 24-bit RGB.

    Background colour matches BC's dark HUD so the white-on-black
    reference reads the same way as the in-game icon. Pixel alpha
    multiplies the foreground in; transparent pixels stay black.
    """
    out = bytearray(w * h * 3)
    for i in range(w * h):
        r = rgba[i * 4]
        g = rgba[i * 4 + 1]
        b = rgba[i * 4 + 2]
        a = rgba[i * 4 + 3]
        out[i * 3]     = (r * a) // 255
        out[i * 3 + 1] = (g * a) // 255
        out[i * 3 + 2] = (b * a) // 255
    return bytes(out)


def export_reference_pngs(tga_dir: Optional[str] = None,
                          registry: Optional[dict[int, IconSpec]] = None,
                          output_dir: Optional[str] = None) -> set[int]:
    """Write a 24-bit PNG reference under ``output_dir/{num}.png`` for
    each registered icon. Same per-icon transform pipeline as the
    tracer, so each PNG matches its companion SVG dimension-for-
    dimension; transparent atlas pixels flatten to black so the
    reference reads like the in-game icon.

    Idempotent — fresh PNGs are skipped, just like the tracer.
    """
    tga_dir = tga_dir or _GAME_ICONS_DIR
    registry = registry or ICON_REGISTRY
    output_dir = output_dir or _REFERENCE_DIR
    os.makedirs(output_dir, exist_ok=True)
    written: set[int] = set()
    tga_cache: dict[str, bytes] = {}

    for num, spec in registry.items():
        out_path = os.path.join(output_dir, f"{num}.png")
        source_path = os.path.join(tga_dir, spec.tga)
        if not os.path.isfile(source_path):
            continue
        if not _needs_rebuild(out_path, source_path):
            continue
        if spec.tga not in tga_cache:
            with open(source_path, "rb") as fp:
                tga_cache[spec.tga] = fp.read()
        w, h, rgba = _extract_region_from_tga(
            tga_cache[spec.tga],
            spec.x, spec.y, spec.w, spec.h,
            spec.rotate, spec.mirror,
        )
        rgb = _rgba_to_rgb_on_black(rgba, w, h)
        png = encode_png_rgb(w, h, rgb)
        with open(out_path, "wb") as fp:
            fp.write(png)
        written.add(num)
    return written


# ── Resolver ───────────────────────────────────────────────────────────
#
# We hand the panel the raw SVG text (not a data URL) so the panel JS
# can inject it into the DOM via ``innerHTML``. Inline SVG resolves
# ``fill="currentColor"`` against the parent element's CSS ``color``
# property — that's the whole point of vector tracing — whereas
# ``<img src="data:image/svg+xml,...">`` always renders the SVG with
# its own colour context, ignoring the surrounding CSS. The text is
# safe to drop into ``innerHTML``: it comes from our deterministic
# potrace pipeline, never from user input.

_svg_cache: dict[int, Optional[str]] = {}


def reset_cache() -> None:
    """Drop the in-memory SVG cache. Tests use this to force a re-read
    after manipulating the on-disk cache."""
    _svg_cache.clear()


def icon_svg_for_num(num: int) -> Optional[str]:
    """Returns the raw SVG text for ``num``, or None for the "no icon"
    sentinel (0) and any out-of-atlas value (270 — used by kessokmine
    and silently ignored in stock BC as well). Result cached in
    memory so repeated lookups are cheap.

    Lookup order:

    1. A hand-authored SVG under
       ``native/assets/ui-cef/icons/weapons/{num}.svg`` always wins.
       Drop in a polished version and the panel uses it instead of
       the trace; no other config needed. The dir is checked into
       git, so curated assets travel with the repo.
    2. The auto-traced cache under ``cache/icons/weapons/{num}.svg``
       — first call after a fresh checkout triggers the tracer for
       the whole registry so subsequent lookups are cache hits.

    If both miss (potrace not installed AND no curated SVG; or the
    source TGA is gone, e.g. dev without BC install), returns None
    and the panel renders empty.
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
