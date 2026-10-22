"""Build native/assets/sprites/<id>.png from generated source sheets
(spec docs/superpowers/specs/2026-10-16-legacy-fx-api-surface-design.md §7.3).

    uv run python tools/sprites/prep.py            # preview: build all, report, write nothing
    uv run python tools/sprites/prep.py --write    # write <id>.png for every entry with "prep"
    uv run python tools/sprites/prep.py --write fire_jet

Sources live in native/assets/sprites/src/<id>/ (black.jpeg, plus green.jpeg
for green_matte). The output PNGs are GENERATED -- never hand-edit them;
tests/tools/test_sprite_drift.py fails on drift.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[2]


def sprites_dir() -> Path:
    return ROOT / "native" / "assets" / "sprites"


class PrepError(Exception):
    pass


def _pixels(im):
    """Pixel list, version-safe (getdata is deprecated in newer Pillow)."""
    if hasattr(im, "get_flattened_data"):
        return list(im.get_flattened_data())
    return list(im.getdata())


def _cells(img, cols, rows):
    """Rows of cell images; fractional cell sizes allowed."""
    w, h = img.size
    out = []
    for r in range(rows):
        row = []
        for c in range(cols):
            box = (round(c * w / cols), round(r * h / rows),
                   round((c + 1) * w / cols), round((r + 1) * h / rows))
            row.append(img.crop(box))
        out.append(row)
    return out


def _resize(cell, size):
    return cell.resize((size, size), Image.LANCZOS)


def _key_black(cell, cut):
    rgba = []
    for r, g, b in _pixels(cell.convert("RGB")):
        a = max(r, g, b)
        if a <= cut:
            rgba.append((0, 0, 0, 0))
        else:
            rgba.append((min(255, r * 255 // a), min(255, g * 255 // a),
                         min(255, b * 255 // a), a))
    out = Image.new("RGBA", cell.size)
    out.putdata(rgba)
    return out


def _key_black_solid(cell, lo, hi):
    rgb = cell.convert("RGB")
    alpha = Image.new("L", rgb.size)
    alpha.putdata([int(255 * min(1.0, max(0.0, (max(p) - lo) / float(hi - lo))))
                   for p in _pixels(rgb)])
    alpha = alpha.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
    alpha = alpha.filter(ImageFilter.GaussianBlur(0.7))
    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    return out


def _green_alpha(green, lo, hi):
    a = Image.new("L", green.size)
    a.putdata([int(255 * (1.0 - min(1.0, max(0.0, ((g - max(r, b)) - lo) / float(hi - lo)))))
               for r, g, b in _pixels(green.convert("RGB"))])
    return a


def _silhouette_outside(black, green, lo):
    """Fraction of the green-keyed object lying outside the black sheet's
    object (brightness > 16) dilated by 2 px."""
    obj = Image.new("L", black.size)
    obj.putdata([255 if max(p) > 16 else 0 for p in _pixels(black.convert("RGB"))])
    obj = obj.filter(ImageFilter.MaxFilter(5))
    g_obj = [(g - max(r, b)) < lo for r, g, b in _pixels(green.convert("RGB"))]
    total = sum(g_obj)
    if total == 0:
        return 0.0
    outside = sum(1 for inside, o in zip(g_obj, _pixels(obj)) if inside and o == 0)
    return outside / float(total)


def _key_green_matte(black, green, lo, hi, shrink):
    alpha = _green_alpha(green, lo, hi)
    for _ in range(int(shrink)):
        alpha = alpha.filter(ImageFilter.MinFilter(3))
    alpha = alpha.filter(ImageFilter.GaussianBlur(0.6))
    out = black.convert("RGB").convert("RGBA")
    out.putalpha(alpha)
    return out


def _scale_alpha(rgba, weight):
    """Multiply alpha by weight(x, y) in [0, 1]."""
    w, h = rgba.size
    px = rgba.load()
    for y in range(h):
        for x in range(w):
            k = weight(x, y)
            if k < 1.0:
                r, g, b, a = px[x, y]
                px[x, y] = (r, g, b, int(a * k))
    return rgba


def _edge_fade(rgba, frac):
    w, h = rgba.size
    span = max(1.0, frac * min(w, h))
    return _scale_alpha(rgba, lambda x, y: min(1.0, min(x, y, w - 1 - x, h - 1 - y) / span))


def _origin_ramp(rgba, edge, frac):
    w, h = rgba.size
    span = max(1.0, frac * (w if edge in ("left", "right") else h))
    dist = {"left": lambda x, y: x, "right": lambda x, y: w - 1 - x,
            "top": lambda x, y: y, "bottom": lambda x, y: h - 1 - y}[edge]
    return _scale_alpha(rgba, lambda x, y: min(1.0, dist(x, y) / span))


def build(sprite_id: str, prep: dict, src_dir: Path) -> Image.Image:
    cols, rows = prep["grid"]
    cell = int(prep.get("cell", 256))
    mode = prep.get("background", "black")
    if mode == "alpha":
        black_img = Image.open(src_dir / "alpha.png").convert("RGBA")
    else:
        black_img = Image.open(src_dir / "black.jpeg").convert("RGB")
    black_cells = _cells(black_img, cols, rows)
    green_cells = None
    if mode == "green_matte":
        green_cells = _cells(Image.open(src_dir / "green.jpeg").convert("RGB"), cols, rows)

    keep_rows = prep.get("keep_rows", list(range(rows)))
    frames = [(r, c) for r in keep_rows for c in range(cols)]
    if "keep_frames" in prep:
        frames = [frames[i] for i in prep["keep_frames"]]

    bad = []
    out_cells = []
    for r, c in frames:
        blk = _resize(black_cells[r][c], cell)
        if mode == "black":
            rgba = _key_black(blk, int(prep.get("black_cut", 2)))
        elif mode == "black_solid":
            lo, hi = prep.get("solid", [4, 16])
            rgba = _key_black_solid(blk, lo, hi)
        elif mode == "green_matte":
            grn = _resize(green_cells[r][c], cell)
            lo, hi = prep.get("green", [40, 160])
            if _silhouette_outside(blk, grn, lo) > 0.01:
                bad.append(f"row {r} col {c}")
                continue
            rgba = _key_green_matte(blk, grn, lo, hi, prep.get("shrink", 1))
        elif mode == "alpha":
            rgba = blk.convert("RGBA")
        else:
            raise PrepError(f"{sprite_id}: unknown background mode {mode!r}")
        if prep.get("edge_fade"):
            rgba = _edge_fade(rgba, float(prep["edge_fade"]))
        if prep.get("origin_ramp"):
            ramp = prep["origin_ramp"]
            rgba = _origin_ramp(rgba, ramp["edge"], float(ramp["width"]))
        if prep.get("rotate") == "cw":
            rgba = rgba.transpose(Image.Transpose.ROTATE_270)
        elif prep.get("rotate") == "ccw":
            rgba = rgba.transpose(Image.Transpose.ROTATE_90)
        out_cells.append(rgba)
    if bad:
        raise PrepError(f"{sprite_id}: green/black sheets disagree in cell(s): {', '.join(bad)}")

    out_rows = len(frames) // cols if len(frames) % cols == 0 else len(frames) // cols + 1
    sheet = Image.new("RGBA", (cols * cell, out_rows * cell), (0, 0, 0, 0))
    for i, rgba in enumerate(out_cells):
        sheet.paste(rgba, ((i % cols) * cell, (i // cols) * cell))
    return sheet


def _manifest() -> dict:
    return json.loads((sprites_dir() / "manifest.json").read_text(encoding="utf-8"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("ids", nargs="*")
    args = ap.parse_args(argv)
    entries = _manifest()["sprites"]
    ids = args.ids or [k for k, v in entries.items() if isinstance(v, dict) and "prep" in v]
    status = 0
    for sid in ids:
        entry = entries.get(sid) or {}
        if "prep" not in entry:
            print(f"{sid}: no prep section", file=sys.stderr)
            status = 1
            continue
        try:
            sheet = build(sid, entry["prep"], sprites_dir() / "src" / sid)
        except (PrepError, OSError, KeyError, IndexError, ValueError) as e:
            print(f"{sid}: FAILED -- {e}", file=sys.stderr)
            status = 1
            continue
        print(f"{sid}: {sheet.size[0]}x{sheet.size[1]}")
        if args.write:
            sheet.save(sprites_dir() / entry["file"])
    return status


if __name__ == "__main__":
    sys.exit(main())
