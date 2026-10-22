"""Generate the Windows application icon from dauntless.svg.

    python tools/gen_app_icon.py --write

GENERATED, like the mesh fixes and the bitmap font: never hand-edit
native/assets/icons/dauntless.ico. Re-run this after changing the SVG.
tests/tools/test_app_icon_drift.py fails if the committed .ico does not match
what this script produces.

The artwork is native/assets/icons/dauntless_icon.svg: the ship path from the
project's dauntless.svg, byte for byte, with that file's rounded-square frame
replaced by a circle of the same palette and stroke. The circle is the frame
Mark asked for; dauntless.svg keeps the square one and nothing else reads it.

RASTERIZER. svglib + reportlab, which are NOT project dependencies: the icon
is a committed artefact, so this runs on a maintainer's machine rather than in
the build. They are pure-Python wheels and need no cairo:

    python -m pip install svglib

A note on why not Pillow alone: Pillow cannot read SVG, and the ship
silhouette is a single 2.5 KB bezier path -- not something to reproduce by
hand without quietly changing the artwork.

SIZES. The set Explorer, the taskbar, Alt-Tab and the window chrome actually
ask for. 256 is stored as PNG inside the .ico (the format allows it and
Windows prefers it); the rest are raw bitmaps, which Pillow handles.
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SVG = PROJECT_ROOT / "native" / "assets" / "icons" / "dauntless_icon.svg"
ICO = PROJECT_ROOT / "native" / "assets" / "icons" / "dauntless.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)


# Render well above the largest icon, then downsample. renderPM applies its own
# 72/96 dpi scale (a 256-unit document comes out 192 px), so asking for the
# exact size gets the wrong one; oversampling makes that irrelevant and gives
# the circular mask below enough resolution to antialias cleanly.
RENDER_PX = 1024

# The frame circle, as fractions of the document box, from dauntless_icon.svg's
# <circle cx="128" cy="128" r="125.4"> in its 256-unit viewBox. If that circle
# moves, these move with it.
FRAME_CENTRE = 128.0 / 256.0
FRAME_RADIUS = 125.4 / 256.0
# Antialias the mask by building it this many times oversampled and shrinking.
MASK_SUPERSAMPLE = 4


def circular_alpha(size: int) -> "Image.Image":
    """An antialiased circular alpha mask matching the artwork's frame.

    Why a mask at all: renderPM has no alpha channel -- it returns RGB and
    fills the background (measured: pure black) -- so the rendered square has
    opaque corners, which on a dark disc is invisible in a preview and obvious
    on a light Explorer background.

    Why not key out the black: the disc's own fill is #1a1613, nearly black,
    and the antialiased boundary between disc and backdrop is a blend of the
    two. Keying would eat into the disc edge and leave a dark halo. The frame
    is a circle of known geometry, so the exact mask is cheap and correct.
    """
    from PIL import Image, ImageDraw

    big = size * MASK_SUPERSAMPLE
    mask = Image.new("L", (big, big), 0)
    cx = cy = FRAME_CENTRE * big
    r = FRAME_RADIUS * big
    # The stroke straddles the radius, so include half of it or the ring's
    # outer edge gets clipped flat.
    r += (2.1 / 256.0) * big / 2.0
    ImageDraw.Draw(mask).ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    return mask.resize((size, size), Image.LANCZOS)


def render_master(svg: Path) -> "Image.Image":
    """Rasterise the artwork once at RENDER_PX, with the frame cut out."""
    from PIL import Image
    from reportlab.graphics import renderPM
    from svglib.svglib import svg2rlg

    drawing = svg2rlg(str(svg))
    if drawing is None:
        raise SystemExit(f"[icon] svglib could not parse {svg}")
    scale = RENDER_PX / max(drawing.width, drawing.height)
    drawing.width *= scale
    drawing.height *= scale
    drawing.scale(scale, scale)
    data = renderPM.drawToString(drawing, fmt="PNG")
    img = Image.open(io.BytesIO(data)).convert("RGBA")
    if img.size != (RENDER_PX, RENDER_PX):
        img = img.resize((RENDER_PX, RENDER_PX), Image.LANCZOS)
    img.putalpha(circular_alpha(RENDER_PX))
    return img


def build(svg: Path) -> bytes:
    master = render_master(svg)
    buf = io.BytesIO()
    # Pillow derives every requested size from this one image, downsampling
    # with LANCZOS -- which is why the master is rendered oversampled.
    master.save(buf, format="ICO", sizes=[(s, s) for s in SIZES])
    return buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true",
                    help="write the .ico; otherwise report what would change")
    args = ap.parse_args()

    if not SVG.is_file():
        raise SystemExit(f"[icon] missing {SVG}")
    data = build(SVG)

    current = ICO.read_bytes() if ICO.is_file() else b""
    if data == current:
        print(f"[icon] up to date ({len(data)} bytes, sizes {list(SIZES)})")
        return 0
    if not args.write:
        print(f"[icon] WOULD CHANGE: {ICO.relative_to(PROJECT_ROOT)} "
              f"({len(current)} -> {len(data)} bytes). Re-run with --write.")
        return 1
    ICO.parent.mkdir(parents=True, exist_ok=True)
    ICO.write_bytes(data)
    print(f"[icon] wrote {ICO.relative_to(PROJECT_ROOT)} "
          f"({len(data)} bytes, sizes {list(SIZES)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
