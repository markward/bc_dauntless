"""Shared TGA → SVG trace pipeline.

Used by ``engine.ui.weapon_icons`` (PhaserArcs atlas) and
``engine.ui.damage_icons`` (per-system 16x16 TGAs in
``game/data/Icons/Damage/``). The pipeline is identical: TGA crop
→ alpha-to-PGM → mkbitmap upscale + threshold → potrace --svg →
normalise dimensions + currentColor → wrap with inset clipPath.

Trace tuning lives here too (``_TRACE_UPSCALE`` etc.) so both
consumers stay in sync. If the damage icons want different tuning
later, parametrise then.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from dataclasses import dataclass

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
