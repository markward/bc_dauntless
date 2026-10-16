"""tools/sprites/prep.py on synthetic sheets (spec 2026-10-16 §7.3)."""
import pytest
from PIL import Image, ImageDraw

from tools.sprites import prep


def _sheet(tmp_path, name, cols, rows, cell, bg, fg, draw_off=0):
    im = Image.new("RGB", (cols * cell, rows * cell), bg)
    d = ImageDraw.Draw(im)
    for r in range(rows):
        for c in range(cols):
            x, y = c * cell + cell // 4 + draw_off, r * cell + cell // 4
            d.ellipse((x, y, x + cell // 2, y + cell // 2), fill=fg)
    (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
    im.save(tmp_path / name)
    return tmp_path


def test_black_mode_alpha_is_brightness_and_colour_restored(tmp_path):
    src = _sheet(tmp_path, "black.jpeg", 2, 1, 64, (0, 0, 0), (200, 100, 50))
    out = prep.build("x", {"grid": [2, 1], "background": "black", "cell": 32}, src)
    assert out.size == (64, 32) and out.mode == "RGBA"
    r, g, b, a = out.getpixel((16, 16))
    assert a >= 190 and r >= 250          # alpha ~ max channel; colour un-darkened
    assert out.getpixel((1, 1))[3] == 0   # black background -> transparent


def test_black_cut_removes_near_black_haze(tmp_path):
    src = _sheet(tmp_path, "black.jpeg", 1, 1, 64, (4, 4, 4), (255, 255, 255))
    out = prep.build("x", {"grid": [1, 1], "background": "black", "black_cut": 6, "cell": 64}, src)
    assert out.getpixel((2, 2))[3] == 0


def test_edge_fade_zeroes_cell_borders(tmp_path):
    im = Image.new("RGB", (64, 64), (255, 255, 255))
    im.save(tmp_path / "black.jpeg")
    out = prep.build("x", {"grid": [1, 1], "background": "black", "edge_fade": 0.1, "cell": 64}, tmp_path)
    assert out.getpixel((0, 32))[3] == 0 and out.getpixel((32, 32))[3] == 255


def test_origin_ramp_then_rotate_cw_puts_origin_on_top(tmp_path):
    im = Image.new("RGB", (64, 64), (255, 255, 255))
    im.save(tmp_path / "black.jpeg")
    out = prep.build("x", {"grid": [1, 1], "background": "black", "cell": 64,
                           "origin_ramp": {"edge": "left", "width": 0.25}, "rotate": "cw"}, tmp_path)
    assert out.getpixel((32, 0))[3] == 0        # ramped edge is now the top
    assert out.getpixel((32, 63))[3] == 255


def test_keep_rows_selects_rows(tmp_path):
    im = Image.new("RGB", (32, 48), (0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 16, 31, 31), fill=(255, 0, 0))     # row 1 red
    im.save(tmp_path / "black.jpeg")
    out = prep.build("x", {"grid": [2, 3], "background": "black", "cell": 16, "keep_rows": [1]}, tmp_path)
    assert out.size == (32, 16) and out.getpixel((8, 8))[0] == 255


def test_green_matte_takes_shape_from_green_colour_from_black(tmp_path):
    _sheet(tmp_path, "black.jpeg", 1, 1, 64, (0, 0, 0), (90, 90, 100))
    _sheet(tmp_path, "green.jpeg", 1, 1, 64, (0, 255, 0), (90, 90, 100))
    out = prep.build("x", {"grid": [1, 1], "background": "green_matte", "cell": 64}, tmp_path)
    r, g, b, a = out.getpixel((32, 32))
    assert a == 255 and (r, g, b) == pytest.approx((90, 90, 100), abs=6)   # dark metal stays opaque
    assert out.getpixel((2, 2))[3] == 0


def test_green_matte_refuses_misaligned_pair(tmp_path):
    _sheet(tmp_path, "black.jpeg", 1, 1, 64, (0, 0, 0), (90, 90, 100))
    _sheet(tmp_path, "green.jpeg", 1, 1, 64, (0, 255, 0), (90, 90, 100), draw_off=20)
    with pytest.raises(prep.PrepError, match="cell"):
        prep.build("x", {"grid": [1, 1], "background": "green_matte", "cell": 64}, tmp_path)
