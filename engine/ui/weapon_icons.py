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

import base64
import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional

from engine.ui.png_encoder import encode_png_rgb
from engine.ui.tga import decode_tga


# ── Transform constants ─────────────────────────────────────────────────
# Mirrors ``App.TGIconGroup`` values referenced in WeaponIcons.py.

ROTATE_0 = 0
ROTATE_180 = 1

MIRROR_NONE = 0
MIRROR_HORIZONTAL = 1
MIRROR_VERTICAL = 2


@dataclass(frozen=True)
class IconSpec:
    """One atlas sprite. Coordinates are top-left-origin pixels."""
    tga: str
    x: int
    y: int
    w: int
    h: int
    rotate: int = ROTATE_0
    mirror: int = MIRROR_NONE


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

# Trace tuning. mkbitmap defaults are -f 4 -s 2 -3 -t 0.45; we keep
# the cubic interpolation + highpass filter but double the upscale
# (the 4×6 torpedo glyph at 2× still only gives potrace 8×12 to work
# with) and nudge the threshold up for cleaner edges. The values
# applied here came out of visual comparison of the traced sprites
# against the source TGA at 4× display scale.
_TRACE_UPSCALE = 4
_TRACE_FILTER_RADIUS = 4
_TRACE_THRESHOLD = "0.5"
# Potrace curve smoothing. Alphamax (default 1.0, max ~1.334) is the
# corner-detection threshold — higher values let curves flow through
# what would otherwise be detected as corners. Opttolerance (default
# 0.2) is the segment-merge tolerance — higher values aggressively
# collapse adjacent short segments into longer smooth curves. The arc
# icons are continuous shapes by design, so we lean both knobs hard
# toward "smooth" and let the upscaled trace preserve the fine detail.
_TRACE_ALPHAMAX = "1.3"
_TRACE_OPTTOLERANCE = "1.0"


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


# ── Sprite extraction (pure Python; unchanged from the slicer era) ─────

def _crop_rgba(rgba: bytes, src_w: int, src_h: int,
               x: int, y: int, w: int, h: int) -> bytes:
    """Return the RGBA bytes for the rectangle [(x,y), (x+w, y+h)) of a
    top-left-origin RGBA buffer."""
    if x < 0 or y < 0 or x + w > src_w or y + h > src_h:
        raise ValueError(
            f"region ({x},{y},{w},{h}) out of bounds for {src_w}x{src_h}"
        )
    row = bytearray()
    for j in range(h):
        offset = ((y + j) * src_w + x) * 4
        row.extend(rgba[offset:offset + w * 4])
    return bytes(row)


def _mirror_horizontal(rgba: bytes, w: int, h: int) -> bytes:
    """Flip left↔right. Pixel at (x, y) → (w-1-x, y)."""
    out = bytearray(len(rgba))
    for j in range(h):
        for i in range(w):
            src = (j * w + i) * 4
            dst = (j * w + (w - 1 - i)) * 4
            out[dst:dst + 4] = rgba[src:src + 4]
    return bytes(out)


def _mirror_vertical(rgba: bytes, w: int, h: int) -> bytes:
    """Flip top↔bottom. Pixel at (x, y) → (x, h-1-y)."""
    out = bytearray(len(rgba))
    row_bytes = w * 4
    for j in range(h):
        src_off = j * row_bytes
        dst_off = (h - 1 - j) * row_bytes
        out[dst_off:dst_off + row_bytes] = rgba[src_off:src_off + row_bytes]
    return bytes(out)


def _rotate_180(rgba: bytes, w: int, h: int) -> bytes:
    """180-degree rotation = horizontal + vertical flip composed."""
    return _mirror_vertical(_mirror_horizontal(rgba, w, h), w, h)


def _apply_transform(rgba: bytes, w: int, h: int,
                     rotate: int, mirror: int) -> tuple[int, int, bytes]:
    if rotate == ROTATE_180:
        rgba = _rotate_180(rgba, w, h)
    elif rotate != ROTATE_0:
        raise ValueError(f"unsupported rotate value {rotate}")
    if mirror == MIRROR_HORIZONTAL:
        rgba = _mirror_horizontal(rgba, w, h)
    elif mirror == MIRROR_VERTICAL:
        rgba = _mirror_vertical(rgba, w, h)
    elif mirror != MIRROR_NONE:
        raise ValueError(f"unsupported mirror value {mirror}")
    return w, h, rgba


def _extract_region_from_tga(blob: bytes,
                             x: int, y: int, w: int, h: int,
                             rotate: int, mirror: int
                             ) -> tuple[int, int, bytes]:
    """Decode the TGA, crop the region, apply transforms; return RGBA."""
    src_w, src_h, rgba = decode_tga(blob)
    cropped = _crop_rgba(rgba, src_w, src_h, x, y, w, h)
    return _apply_transform(cropped, w, h, rotate, mirror)


# ── PGM encoding ───────────────────────────────────────────────────────

def _rgba_to_pgm(rgba: bytes, w: int, h: int) -> bytes:
    """Convert the alpha channel to a PGM (P5 binary, greyscale) where
    ink is black (low values) and background is white (255).

    mkbitmap reads PNM input; PGM with the conventional "black ink on
    white paper" orientation lets us use the default invert behaviour.
    Greyscale (vs PBM) lets mkbitmap's cubic interpolation produce
    anti-aliased edges on the 4× upscale before thresholding — that's
    where most of the curve quality comes from.
    """
    header = f"P5\n{w} {h}\n255\n".encode("ascii")
    out = bytearray(w * h)
    for y in range(h):
        for x in range(w):
            alpha = rgba[(y * w + x) * 4 + 3]
            out[y * w + x] = 255 - alpha
    return header + bytes(out)


# ── Trace pipeline ─────────────────────────────────────────────────────

class PotraceMissingError(RuntimeError):
    """Raised when ``potrace`` or ``mkbitmap`` aren't on PATH. The
    runtime handler downgrades this to "no icon SVG" so the panel
    renders an empty space rather than crashing the host."""


def _potrace_available() -> bool:
    """True when BOTH ``potrace`` and ``mkbitmap`` are on PATH. They
    ship in the same package (``brew install potrace``,
    ``apt install potrace``) so either presence implies the other in
    practice, but we still check both — a partial install would
    otherwise fail mid-pipeline with a confusing error."""
    return (shutil.which("potrace") is not None
            and shutil.which("mkbitmap") is not None)


def _trace_to_svg(rgba: bytes, w: int, h: int) -> str:
    """Run the rgba → pgm → mkbitmap → potrace → svg pipeline and
    return the post-processed SVG text. Returned SVG has native pixel
    dimensions (w × h) but its viewBox covers the 4× internal trace
    coords, so the browser renders the extra precision as smoother
    curves at the original sprite size.
    """
    if not _potrace_available():
        raise PotraceMissingError(
            "potrace + mkbitmap are not installed; "
            "install via 'brew install potrace' on macOS or "
            "'apt install potrace' on Linux"
        )
    pgm = _rgba_to_pgm(rgba, w, h)
    mkbitmap_out = subprocess.run(
        [
            "mkbitmap",
            "-s", str(_TRACE_UPSCALE),
            "-f", str(_TRACE_FILTER_RADIUS),
            "-3",                       # cubic interpolation
            "-t", _TRACE_THRESHOLD,
            "-o", "-",
            "-",
        ],
        input=pgm,
        capture_output=True,
        check=True,
    )
    potrace_out = subprocess.run(
        [
            "potrace",
            "--svg",
            "--turdsize", "0",          # preserve the smallest features
            "--alphamax", _TRACE_ALPHAMAX,
            "--opttolerance", _TRACE_OPTTOLERANCE,
            "--output", "-",
            "-",
        ],
        input=mkbitmap_out.stdout,
        capture_output=True,
        check=True,
    )
    return _normalize_svg(potrace_out.stdout.decode("utf-8"), w, h)


def _normalize_svg(svg: str, w: int, h: int) -> str:
    """Rewrite potrace's SVG so the icon renders at native pixel
    dimensions, uses ``currentColor`` so CSS theming takes over, AND
    supports inset stroking via a self-referencing clipPath.

    Three transforms:

    1. Width/height → native sprite px (potrace defaults to ``pt``
       units, ~33 % bigger than the source). The viewBox stays at the
       upscaled trace coords so the extra resolution survives as
       smoother curves at the displayed size.
    2. Fill ``#000000`` → ``currentColor`` so the panel CSS owns the
       weapon-icon colour.
    3. Move the path geometry into ``<defs>`` under an id, add a
       ``<clipPath>`` that re-uses that id as its clip shape, and
       render the visible content through a single ``<use>`` with
       ``clip-path`` applied. Any stroke set on the use (via CSS, e.g.
       the in-arc indicator) is then drawn centred on the path edge
       — but the OUTER half is clipped away by the path's own shape,
       so visually only the INNER half shows. That's the SVG idiom
       for an "inset" stroke; CSS alone has no equivalent without
       knowing the path ``d`` ahead of time.

    IDs are suffixed with a short hash of the path geometry so two
    different shapes get distinct ids and same-shape duplicates
    share an id harmlessly (the clipPath shape is what matters at
    render time). ``url(#id)`` in SVG attributes resolves
    document-wide, so plain ``id="s"`` would let multiple panel
    icons race for the same clip shape — hash suffix sidesteps it.
    """
    import re
    svg = re.sub(
        r'width="[^"]+"\s+height="[^"]+"',
        f'width="{w}" height="{h}"',
        svg,
        count=1,
    )
    svg = svg.replace('fill="#000000"', 'fill="currentColor"')
    return _wrap_with_inset_clip(svg)


def _wrap_with_inset_clip(svg: str) -> str:
    """Add a ``<clipPath>`` that duplicates the rendered geometry and
    apply ``clip-path`` to the visible element. The CSS stroke then
    renders centred on the path edge with the outer half clipped away,
    so only the inner half shows — an inset stroke. No-op when the SVG
    already declares a ``<clipPath>``.

    Handles two structures:

    1. ``<g>...</g>`` block — potrace's default. Add clip-path to the g.
    2. Bare ``<path>`` at root — what Inkscape produces when an author
       saves a single-path edit. Add clip-path directly to the path.

    The clipPath gets its own copy of the block (geometry only —
    clipPath ignores fill/stroke attrs), with any ``id="..."``
    stripped to avoid duplicate-id collisions. Older Chromium
    versions in CEF had bugs with ``<use>`` inside ``<clipPath>`` so
    we sidestep that by duplicating the geometry directly.

    Called both from ``_normalize_svg`` at trace time AND from
    ``icon_svg_for_num`` at load time so curated SVGs hand-edited
    before the inset feature landed still get inset strokes without
    requiring the author to re-copy from cache.
    """
    import re
    # Strip the XML declaration + SVG DTD DOCTYPE. The panel injects
    # SVGs via ``element.innerHTML``, which routes through Chromium's
    # HTML parser (not XML), and the HTML parser handles ``<?xml ?>``
    # + ``<!DOCTYPE>`` inconsistently when they appear mid-body. The
    # downstream <svg> element gets dropped silently and the icon
    # never renders. Strip both unconditionally — they're optional in
    # SVG anyway, and our hand-authored curated SVGs that worked all
    # along happened to lack the DOCTYPE.
    svg = re.sub(r'<\?xml[^?]*\?>\s*', '', svg, count=1)
    svg = re.sub(r'<!DOCTYPE[^>]*>\s*', '', svg, count=1, flags=re.DOTALL)

    if "<clipPath" in svg:
        return svg

    # Flatten ``<g transform=...><path d=.../></g>`` (potrace's wrap, and
    # what older cache copies still have on disk) into a single
    # ``<path transform=...>``. CEF's clip-path behaviour on ``<g>`` with
    # transforms is unreliable — icons silently fail to render. Flat
    # paths with the same transform attribute work correctly.
    g_with_path = re.search(
        r'<g\b([^>]*)>\s*<path\b([^/>]*)/?>\s*</g>',
        svg, flags=re.DOTALL,
    )
    if g_with_path:
        g_attrs = g_with_path.group(1).strip()
        path_attrs = g_with_path.group(2).strip()
        flat = f'<path {g_attrs} {path_attrs}/>'
        svg = svg.replace(g_with_path.group(0), flat, 1)

    path_match = re.search(
        r'<path\b[^/>]*(?:/>|>.*?</path>)',
        svg, flags=re.DOTALL,
    )
    if path_match:
        block = path_match.group(0)
    else:
        g_match = re.search(r'<g\b[^>]*>.*?</g>', svg, flags=re.DOTALL)
        if not g_match:
            return svg
        block = g_match.group(0)

    suffix = hashlib.sha256(block.encode()).hexdigest()[:10]
    clip_id = f"c{suffix}"

    # Build the clip shape from the visible block, stripping both the
    # ``id="..."`` (avoids duplicate-id collision in the document) AND
    # any ``transform="..."`` attribute. The clipPath's content is
    # interpreted in the user coord system of the referencing element —
    # which already has the visible's transform baked in — so leaving
    # the transform on the clipPath copy would compose it a second time
    # and the clip shape would no longer match the visible. Empirically
    # this is what made cache-style icon 360 vanish: visible at scale
    # 0.1 was being clipped by a region at scale 0.01.
    clip_block = re.sub(r'\sid="[^"]*"', '', block)
    clip_block = re.sub(
        r'\stransform="[^"]*"', '', clip_block, count=1, flags=re.DOTALL
    )
    clip_def = (
        '<defs><clipPath id="' + clip_id + '">' + clip_block + '</clipPath></defs>'
    )

    # Add clip-path attribute to the visible block's outer tag.
    # Handles both ``<g ...>`` and ``<path .../>`` (self-closing
    # paths and open/close pairs alike).
    block_with_clip = re.sub(
        r'^(<(?:g|path)\b[^/>]*?)(\s*/?>)',
        r'\1 clip-path="url(#' + clip_id + r')"\2',
        block,
        count=1,
        flags=re.DOTALL,
    )

    return svg.replace(block, clip_def + block_with_clip, 1)


# ── Tracer ──────────────────────────────────────────────────────────────

def _needs_rebuild(out_path: str, source_path: str) -> bool:
    """True if ``out_path`` is missing or older than ``source_path``."""
    if not os.path.isfile(out_path):
        return True
    try:
        return os.path.getmtime(out_path) < os.path.getmtime(source_path)
    except OSError:
        return True


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
