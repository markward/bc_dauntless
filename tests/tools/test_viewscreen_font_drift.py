"""The committed viewscreen bitmap font is exactly what the generator produces.

A generator change that alters output fails here; regenerate and commit
deliberately (see native/assets/fonts/README.md).
"""
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "fonts" / "gen_bitmap_font.py"
FONTS = ROOT / "native" / "assets" / "fonts"
PNG = "viewscreen_antonio.png"
JSN = "viewscreen_antonio.json"


def _gen(out):
    r = subprocess.run([sys.executable, str(TOOL), "--out-dir", str(out)],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr


def _pixels(p):
    with Image.open(p) as im:
        return im.mode, im.size, im.tobytes()


def test_committed_font_matches_the_generator(tmp_path):
    _gen(tmp_path)
    assert _pixels(tmp_path / PNG) == _pixels(FONTS / PNG)
    assert json.loads((tmp_path / JSN).read_text()) == json.loads((FONTS / JSN).read_text())


def test_every_printable_ascii_glyph_is_present():
    d = json.loads((FONTS / JSN).read_text())
    assert set(d["glyphs"]) == {str(c) for c in range(32, 127)}
    sp = d["glyphs"]["32"]
    assert (sp["w"] == 0 or sp["h"] == 0) and sp["advance"] > 0


def test_glyph_rects_lie_inside_the_atlas_and_do_not_overlap():
    d = json.loads((FONTS / JSN).read_text())
    rects = []
    for g in d["glyphs"].values():
        if g["w"] == 0 or g["h"] == 0:
            continue
        assert g["x"] >= 0 and g["y"] >= 0
        assert g["x"] + g["w"] <= d["atlas_w"] and g["y"] + g["h"] <= d["atlas_h"]
        rects.append((g["x"], g["y"], g["x"] + g["w"], g["y"] + g["h"]))
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]


def test_generation_is_deterministic(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _gen(a)
    _gen(b)
    for n in (PNG, JSN):
        assert (a / n).read_bytes() == (b / n).read_bytes()
