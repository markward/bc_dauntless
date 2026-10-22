"""The committed .ico must be what tools/gen_app_icon.py produces.

Same contract as the other generated artefacts in this tree (mesh fixes, the
bitmap font, the rock catalogue): the file is GENERATED, so a hand-edit or a
stale regeneration is a bug, and this is what catches it.

The rasterizer (svglib + reportlab + rlPyCairo) is deliberately NOT a project
dependency -- the icon is committed, so it is built on a maintainer's machine
rather than in anyone's build. The drift check therefore SKIPS where those are
absent, which is most machines. It still earns its place: it runs for whoever
regenerates the icon, which is exactly who can break it.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ICON = PROJECT_ROOT / "native" / "assets" / "icons" / "dauntless.ico"
ICON_SVG = PROJECT_ROOT / "native" / "assets" / "icons" / "dauntless_icon.svg"

_RASTERIZER = ("svglib", "reportlab", "rlPyCairo", "PIL")


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "gen_app_icon", PROJECT_ROOT / "tools" / "gen_app_icon.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gen_app_icon"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_the_icon_and_its_source_are_committed():
    """Cheap, dependency-free, and the failure that actually bites: the build
    warns and silently drops the icon when the .ico is missing."""
    assert ICON.is_file(), f"missing generated icon {ICON}"
    assert ICON_SVG.is_file(), f"missing icon artwork {ICON_SVG}"
    assert ICON.stat().st_size > 0


def test_the_icon_carries_every_size_windows_asks_for():
    """Explorer, the taskbar and the window chrome pick different sizes; a
    missing one gets scaled from another and looks soft."""
    Image = pytest.importorskip("PIL.Image", reason="Pillow not installed")
    with Image.open(ICON) as im:
        sizes = {s for s in im.ico.sizes()}
    gen = _load_generator()
    assert sizes == {(s, s) for s in gen.SIZES}


def test_the_icon_has_transparent_corners():
    """The frame is a circle, so the corners must be clear.

    renderPM has no alpha channel and fills the background black, which is
    invisible against a dark preview and obvious as a black square on a light
    Explorer background -- it shipped that way once. gen_app_icon applies a
    circular mask; this is the assertion that it still does.
    """
    Image = pytest.importorskip("PIL.Image", reason="Pillow not installed")
    for size in (16, 32, 256):
        with Image.open(ICON) as im:
            im.size = (size, size)
            rgba = im.convert("RGBA")
        assert rgba.getpixel((0, 0))[3] == 0, (
            f"{size}px corner is opaque -- the circular alpha mask is gone")
        centre = rgba.getpixel((size // 2, size // 2))
        assert centre[3] == 255, f"{size}px centre is transparent"


def test_the_committed_icon_matches_the_generator():
    for mod in _RASTERIZER:
        if importlib.util.find_spec(mod) is None:
            pytest.skip(f"{mod} not installed; see tools/gen_app_icon.py")
    gen = _load_generator()
    assert gen.build(ICON_SVG) == ICON.read_bytes(), (
        "native/assets/icons/dauntless.ico is stale or hand-edited. "
        "Regenerate: python tools/gen_app_icon.py --write")
