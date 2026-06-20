"""Bake game backdrop TGAs -> appearance table for the procedural sky.

Offline build step (needs game/ + Pillow). The runtime consumes the JSON;
it never decodes a TGA. Ports poc/extract_map.py:tga_appearance.
"""
import json
import os
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GAME_DIRS = ["game/data/Backgrounds/High", "game/data/Backgrounds"]
DEFAULT_OUT = ROOT / "engine" / "appc" / "backdrop_appearance.json"


def compute_appearance(img):
    """Mean colour, dominant 5-palette, and lit-coverage for a PIL image."""
    im = img.convert("RGBA")
    small = im.resize((48, 48))
    raw = small.tobytes()  # RGBA
    px = [tuple(raw[i:i + 4]) for i in range(0, len(raw), 4)]
    opaque = [(r, g, b) for r, g, b, a in px if a > 16]
    lit = [c for c in opaque if max(c) > 24]
    mean = [round(sum(c[i] for c in opaque) / max(len(opaque), 1)) for i in range(3)]
    q = small.convert("RGB").quantize(colors=5)
    pal = q.getpalette()[:15]
    palette = [[pal[i], pal[i + 1], pal[i + 2]] for i in range(0, len(pal), 3)]
    # Pad palette to exactly 5 colors with black if quantize produced fewer
    while len(palette) < 5:
        palette.append([0, 0, 0])
    return {
        "meanColor": mean,
        "palette": palette,
        "coverage": round(len(lit) / max(len(px), 1), 3),
    }


def main(game_root=ROOT, out_path=DEFAULT_OUT):
    dirs = [game_root / d for d in DEFAULT_GAME_DIRS]
    table = {}
    for d in dirs:
        if not d.is_dir():
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.lower().endswith(".tga"):
                continue
            if fn in table:
                continue
            try:
                table[fn] = compute_appearance(Image.open(d / fn))
            except Exception as e:  # corrupt/unsupported - skip, don't fail bake
                print(f"[bake] skip {fn}: {e}", file=sys.stderr)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(table, indent=2, sort_keys=True) + "\n")
    print(f"[bake] wrote {len(table)} entries -> {out_path}")
    return table


if __name__ == "__main__":
    main()
