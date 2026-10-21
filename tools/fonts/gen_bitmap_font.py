"""Bake printable ASCII of Antonio-Regular into a greyscale coverage atlas + metrics JSON
for the viewscreen target bars (spec docs/superpowers/specs/2026-10-21-viewscreen-target-bars-design.md 4.2).

    uv run python tools/fonts/gen_bitmap_font.py              # write native/assets/fonts
    uv run python tools/fonts/gen_bitmap_font.py --out-dir D  # write elsewhere
    uv run python tools/fonts/gen_bitmap_font.py --check      # exit 1 if committed files differ

The outputs are GENERATED -- never hand-edit; tests/tools/test_viewscreen_font_drift.py fails on drift.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]

PIXEL_SIZE = 28  # cap height ~65% of the 36 px band; the live-tuning knob
PADDING = 2
MIN_ATLAS_W = 256
FONT_FILE = "Antonio-Regular.ttf"
ATLAS_NAME = "viewscreen_antonio.png"
JSON_NAME = "viewscreen_antonio.json"


def font_path() -> Path:
    return ROOT / "native" / "assets" / "ui-cef" / "fonts" / FONT_FILE


def default_out_dir() -> Path:
    return ROOT / "native" / "assets" / "fonts"


def _pack(sizes, width):
    """Shelf-pack left to right; returns (positions, height) or None if a glyph is wider than width."""
    pos, x, y, shelf = {}, PADDING, PADDING, 0
    for cp, (w, h) in sizes:
        if w + 2 * PADDING > width:
            return None
        if x + w + PADDING > width:
            x, y, shelf = PADDING, y + shelf + PADDING, 0
        pos[cp] = (x, y)
        x += w + PADDING
        shelf = max(shelf, h)
    return pos, y + shelf + PADDING


def generate(out_dir: Path) -> None:
    font = ImageFont.truetype(str(font_path()), PIXEL_SIZE)
    ascent, descent = font.getmetrics()
    glyphs, sizes = {}, []
    for cp in range(32, 127):
        ch = chr(cp)
        l, t, r, b = font.getbbox(ch, anchor="ls")
        w, h = (r - l, b - t) if ch != " " else (0, 0)
        glyphs[cp] = {"l": l, "t": t, "w": w, "h": h, "advance": int(round(font.getlength(ch)))}
        sizes.append((cp, (w, h)))
    # tall glyphs first keeps shelves tight; stable order keeps output deterministic
    order = sorted(sizes, key=lambda s: (-s[1][1], s[0]))
    width = MIN_ATLAS_W
    while True:
        packed = _pack(order, width)
        if packed is not None and packed[1] <= width:
            break
        width *= 2
    pos, height = packed
    atlas = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(atlas)
    out = {}
    for cp in range(32, 127):
        g = glyphs[cp]
        x, y = pos[cp]
        if g["w"] and g["h"]:
            draw.text((x - g["l"], y - g["t"]), chr(cp), fill=255, font=font, anchor="ls")
        out[str(cp)] = {"x": x, "y": y, "w": g["w"], "h": g["h"],
                        "bearing_x": g["l"], "bearing_y": -g["t"], "advance": g["advance"]}
    meta = {
        "generator": "tools/fonts/gen_bitmap_font.py",
        "font": FONT_FILE,
        "pixel_size": PIXEL_SIZE,
        "atlas": ATLAS_NAME,
        "atlas_w": width,
        "atlas_h": height,
        "line_height": ascent + descent,
        "ascent": ascent,
        "glyphs": out,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    atlas.save(out_dir / ATLAS_NAME, optimize=False)
    (out_dir / JSON_NAME).write_text(json.dumps(meta, indent=1) + "\n")


def _pixels(p: Path):
    with Image.open(p) as im:
        return im.mode, im.size, im.tobytes()


def check(committed: Path) -> bool:
    with tempfile.TemporaryDirectory() as td:
        generate(Path(td))
        same_png = _pixels(Path(td) / ATLAS_NAME) == _pixels(committed / ATLAS_NAME)
        same_json = json.loads((Path(td) / JSON_NAME).read_text()) == json.loads((committed / JSON_NAME).read_text())
    return same_png and same_json


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir", type=Path, default=default_out_dir())
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    if args.check:
        ok = check(args.out_dir)
        print("up to date" if ok else "DRIFT: regenerate", file=sys.stderr)
        return 0 if ok else 1
    generate(args.out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
