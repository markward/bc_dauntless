"""Tests for the WeaponIcons atlas tracer.

The tracer mirrors ``sdk/Build/scripts/Icons/WeaponIcons.py``:

* Registry of icon numbers → ``(tga, x, y, w, h, rotate, mirror)``.
* For each registered sprite: decode the source TGA, crop the region,
  apply rotate/mirror, threshold alpha → 1-bit PBM, pipe through
  ``potrace --svg``, post-process to native pixel dimensions with a
  ``currentColor`` fill.
* Cache the SVG under ``cache/icons/weapons/{num}.svg`` so subsequent
  ``icon_url_for_num`` calls are zero-cost.
* Hand the panel a ``data:image/svg+xml;base64,...`` URL.

The fallback path (potrace missing or source TGA absent) is also
tested — the panel must render an empty slot, never crash the host.
"""
from __future__ import annotations

import os
import shutil
import struct
import time

import pytest

from engine.ui import weapon_icons




# Numbers stock hardpoints reference for the weapon glyphs
# (sdk/Build/scripts/ships/Hardpoints/*.py). Generic / out-of-atlas
# fallbacks (0, 270) are intentionally excluded — they signal "no
# icon" and the panel skips them. Indicator overlays (500-515) were
# also dropped from the registry — the panel now expresses "in arc"
# via a CSS stroke, not a separate sprite.
STOCK_ICON_REFS = (
    330, 335, 340, 350, 355, 360, 361, 362, 363, 364, 365, 370,
)


potrace_required = pytest.mark.skipif(
    not weapon_icons._potrace_available(),
    reason="potrace binary not installed (brew install potrace)",
)


@pytest.fixture(autouse=True)
def _reset_svg_cache():
    """Drop the module-level in-memory SVG cache before AND after each
    test. The ``potrace_missing`` test deliberately monkeypatches the
    detector to cache ``None`` for an icon number; without this fixture
    the next test in the file (or any downstream test that asks for
    that icon) reads the stale ``None`` and silently fails the
    descriptor builder."""
    weapon_icons.reset_cache()
    yield
    weapon_icons.reset_cache()


# ── Registry ────────────────────────────────────────────────────────────

def test_registry_covers_every_stock_icon_reference():
    """Every num referenced by a stock hardpoint must be in the
    registry so the tracer emits a sprite. New ships that reach for
    new numbers will fail this check until the registry grows."""
    missing = [n for n in STOCK_ICON_REFS if n not in weapon_icons.ICON_REGISTRY]
    assert missing == [], (
        f"weapon_icons.ICON_REGISTRY missing entries for {missing}; "
        "compare against sdk/Build/scripts/Icons/WeaponIcons.py"
    )


def test_registry_skips_destroyed_slot_sentinel():
    """Number 0 maps to ``Destroyed.tga`` in the SDK — used by tractor
    beams and GenericTemplate as the "no icon" sentinel. The tracer's
    registry must NOT include 0; the panel relies on icon_num == 0 to
    skip drawing."""
    assert 0 not in weapon_icons.ICON_REGISTRY


def test_registry_only_sources_phaser_arcs():
    """All registered icons trace from PhaserArcs.tga. The
    PhaserFields.tga indicator sprites (500-515) used to live here
    too but were dropped in favour of the CSS in-arc stroke."""
    for num, spec in weapon_icons.ICON_REGISTRY.items():
        assert spec.tga == "PhaserArcs.tga", (
            f"#{num} sourced from {spec.tga}, expected PhaserArcs.tga"
        )


# ── Sprite extraction (rotate / mirror) ─────────────────────────────────

def _solid_rgba(w: int, h: int, color: tuple[int, int, int, int]) -> bytes:
    r, g, b, a = color
    return bytes((r, g, b, a)) * (w * h)


def _make_synthetic_tga(width: int, height: int) -> bytes:
    """A 4x4 synthetic TGA — top-left quadrant red, top-right green,
    bottom-left blue, bottom-right white. Used by the extraction
    round-trip test so it doesn't need real BC assets."""
    header = struct.pack(
        "<BBBHHBHHHHBB",
        0,    # id length
        0,    # cmap type
        2,    # image type (uncompressed true-colour)
        0, 0, 0,
        0, 0,
        width, height,
        32,   # bpp
        0x20, # descriptor — top-left origin
    )
    pixels = bytearray()
    for y in range(height):
        for x in range(width):
            if x < width // 2 and y < height // 2:
                pixels.extend((0, 0, 255, 255))    # B,G,R,A = red
            elif x >= width // 2 and y < height // 2:
                pixels.extend((0, 255, 0, 255))    # green
            elif x < width // 2 and y >= height // 2:
                pixels.extend((255, 0, 0, 255))    # blue
            else:
                pixels.extend((255, 255, 255, 255))  # white
    return header + bytes(pixels)


def test_extract_sprite_no_transform_round_trip():
    blob = _make_synthetic_tga(4, 4)
    w, h, rgba = weapon_icons._extract_region_from_tga(
        blob, 0, 0, 2, 2,
        weapon_icons.ROTATE_0, weapon_icons.MIRROR_NONE,
    )
    assert (w, h) == (2, 2)
    assert rgba == _solid_rgba(2, 2, (255, 0, 0, 255))


def test_extract_sprite_mirror_horizontal_swaps_columns():
    blob = _make_synthetic_tga(4, 4)
    w, h, rgba = weapon_icons._extract_region_from_tga(
        blob, 0, 0, 4, 1,
        weapon_icons.ROTATE_0, weapon_icons.MIRROR_HORIZONTAL,
    )
    assert (w, h) == (4, 1)
    assert rgba == (bytes((0, 255, 0, 255)) * 2
                    + bytes((255, 0, 0, 255)) * 2)


def test_extract_sprite_mirror_vertical_swaps_rows():
    blob = _make_synthetic_tga(4, 4)
    w, h, rgba = weapon_icons._extract_region_from_tga(
        blob, 0, 0, 1, 4,
        weapon_icons.ROTATE_0, weapon_icons.MIRROR_VERTICAL,
    )
    assert (w, h) == (1, 4)
    expected = (bytes((0, 0, 255, 255)) * 2
                + bytes((255, 0, 0, 255)) * 2)
    assert rgba == expected


def test_extract_sprite_rotate_180_swaps_both_axes():
    blob = _make_synthetic_tga(4, 4)
    w, h, rgba = weapon_icons._extract_region_from_tga(
        blob, 0, 0, 4, 4,
        weapon_icons.ROTATE_180, weapon_icons.MIRROR_NONE,
    )
    assert (w, h) == (4, 4)
    row_top    = bytes((255, 255, 255, 255)) * 2 + bytes((0, 0, 255, 255)) * 2
    row_bottom = bytes((0, 255, 0, 255))     * 2 + bytes((255, 0, 0, 255)) * 2
    expected = row_top * 2 + row_bottom * 2
    assert rgba == expected


# ── PGM encoding ────────────────────────────────────────────────────────

def test_rgba_to_pgm_inverts_alpha_for_mkbitmap():
    """PGM convention is "black ink on white paper" — the trace
    target. Opaque pixels (alpha=255) become black (0); fully
    transparent pixels (alpha=0) stay white (255)."""
    rgba = bytearray()
    for _ in range(4):
        rgba.extend((255, 0, 0, 255))  # row 0, opaque → black
    for _ in range(4):
        rgba.extend((255, 0, 0, 0))    # row 1, transparent → white
    pgm = weapon_icons._rgba_to_pgm(bytes(rgba), 4, 2)
    assert pgm.startswith(b"P5\n4 2\n255\n")
    payload = pgm[len(b"P5\n4 2\n255\n"):]
    assert payload == bytes([0, 0, 0, 0, 255, 255, 255, 255])


def test_rgba_to_rgb_on_black_premultiplies_alpha():
    """Authoring reference PNGs flatten the atlas onto black so the
    sprite reads like the in-game HUD. Pixel with alpha=128 should
    half-bright the underlying colour."""
    rgba = bytes((200, 100, 0, 255) + (200, 100, 0, 128) + (200, 100, 0, 0))
    rgb = weapon_icons._rgba_to_rgb_on_black(rgba, 3, 1)
    assert rgb == bytes([
        200, 100, 0,    # opaque → full colour
        100, 50, 0,     # half-alpha → half-bright (rounded)
        0, 0, 0,        # transparent → black
    ])


def test_export_reference_pngs_writes_native_dimension_files(tmp_path):
    """Each registered icon should produce a PNG at the registry's
    native pixel dimensions. The same source-newer-than-output
    idempotency that protects the SVG cache applies here too."""
    source = tmp_path / "Synth.tga"
    source.write_bytes(_make_synthetic_tga(4, 4))
    spec = weapon_icons.IconSpec(tga="Synth.tga", x=0, y=0, w=4, h=4)
    registry = {999: spec}

    written = weapon_icons.export_reference_pngs(
        tga_dir=str(tmp_path),
        registry=registry,
        output_dir=str(tmp_path / "ref"),
    )
    out = tmp_path / "ref" / "999.png"
    assert out.exists()
    assert 999 in written
    # PNG signature.
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_rgba_to_pgm_preserves_partial_alpha():
    """Mod TGAs with AA edges will produce partial alpha; mkbitmap's
    cubic interpolation needs the grey midtones to do its job."""
    rgba = bytes((255, 0, 0, 64) + (255, 0, 0, 192))
    pgm = weapon_icons._rgba_to_pgm(rgba, 2, 1)
    payload = pgm.split(b"\n", 3)[3]
    assert payload == bytes([255 - 64, 255 - 192])


# ── Potrace driver ──────────────────────────────────────────────────────

@potrace_required
def test_trace_to_svg_produces_themable_currentcolor_fill():
    """Solid 4x4 square should trace to a single path with a
    currentColor fill so CSS can recolour it."""
    rgba = _solid_rgba(4, 4, (255, 0, 0, 255))
    svg = weapon_icons._trace_to_svg(rgba, 4, 4)
    assert svg.startswith("<?xml") or svg.lstrip().startswith("<svg")
    assert 'fill="currentColor"' in svg
    # Default potrace ``#000000`` fill must be gone.
    assert 'fill="#000000"' not in svg


@potrace_required
def test_trace_to_svg_uses_native_pixel_dimensions():
    """Potrace defaults to ``pt`` units which would render the sprite
    33% larger than the bitmap. Post-processing rewrites width/height
    to native pixel units (matching the source sprite size) while
    keeping the upscaled viewBox so the extra trace resolution
    renders as smoother curves at the displayed size."""
    rgba = _solid_rgba(54, 24, (255, 0, 0, 255))
    svg = weapon_icons._trace_to_svg(rgba, 54, 24)
    assert 'width="54"' in svg
    assert 'height="24"' in svg
    # viewBox stays in the upscaled coord space (54 × 4 = 216,
    # 24 × 4 = 96). The browser scales the path content down to
    # the declared width/height, preserving curve precision.
    assert 'viewBox="0 0 216 96"' in svg or 'viewBox="0 0 216.000000 96.000000"' in svg
    # No stray ``pt`` units smuggled in by the default potrace header.
    assert "pt\"" not in svg


def test_trace_to_svg_raises_when_potrace_missing(monkeypatch):
    """When potrace isn't on PATH the runtime path catches the error
    and returns ``None`` from ``icon_url_for_num``; the explicit
    helper raises so callers can disambiguate "binary missing" from
    a corrupt sprite."""
    monkeypatch.setattr(weapon_icons, "_potrace_available", lambda: False)
    with pytest.raises(weapon_icons.PotraceMissingError):
        weapon_icons._trace_to_svg(_solid_rgba(4, 4, (255, 0, 0, 255)), 4, 4)


# ── Tracer end-to-end ───────────────────────────────────────────────────

@potrace_required
def test_tracer_writes_svg_to_cache(tmp_path):
    source = tmp_path / "Synth.tga"
    source.write_bytes(_make_synthetic_tga(4, 4))
    spec = weapon_icons.IconSpec(tga="Synth.tga", x=0, y=0, w=4, h=4)
    registry = {999: spec}

    written = weapon_icons.trace_atlas(
        tga_dir=str(tmp_path),
        registry=registry,
        output_dir=str(tmp_path / "cache"),
    )

    out_svg = tmp_path / "cache" / "999.svg"
    assert out_svg.exists()
    assert 999 in written
    body = out_svg.read_text()
    assert "<svg" in body
    assert 'fill="currentColor"' in body


@potrace_required
def test_tracer_is_idempotent_when_cache_is_fresh(tmp_path):
    source = tmp_path / "Synth.tga"
    source.write_bytes(_make_synthetic_tga(4, 4))
    spec = weapon_icons.IconSpec(tga="Synth.tga", x=0, y=0, w=4, h=4)
    registry = {999: spec}

    weapon_icons.trace_atlas(
        tga_dir=str(tmp_path),
        registry=registry,
        output_dir=str(tmp_path / "cache"),
    )
    out_svg = tmp_path / "cache" / "999.svg"
    future = time.time() + 60
    os.utime(out_svg, (future, future))
    mtime_before = out_svg.stat().st_mtime

    written = weapon_icons.trace_atlas(
        tga_dir=str(tmp_path),
        registry=registry,
        output_dir=str(tmp_path / "cache"),
    )

    assert written == set(), "second pass should be a no-op when fresh"
    assert out_svg.stat().st_mtime == mtime_before


@potrace_required
def test_tracer_rewrites_when_source_is_newer(tmp_path):
    """Mod swaps a TGA — the cache entries with older mtime must be
    regenerated on the next host start."""
    source = tmp_path / "Synth.tga"
    source.write_bytes(_make_synthetic_tga(4, 4))
    spec = weapon_icons.IconSpec(tga="Synth.tga", x=0, y=0, w=4, h=4)
    registry = {999: spec}

    weapon_icons.trace_atlas(
        tga_dir=str(tmp_path),
        registry=registry,
        output_dir=str(tmp_path / "cache"),
    )
    future = time.time() + 60
    os.utime(source, (future, future))

    written = weapon_icons.trace_atlas(
        tga_dir=str(tmp_path),
        registry=registry,
        output_dir=str(tmp_path / "cache"),
    )

    assert written == {999}, "stale SVG must be regenerated"


# ── SVG resolver ────────────────────────────────────────────────────────

@potrace_required
def test_icon_svg_for_num_returns_inline_svg_text_for_known_num():
    """The panel injects the SVG inline via innerHTML so CSS theming
    cascades into the path. The resolver returns raw text — not a
    data URL — so the panel can append it directly. The curated
    layer can override the trace with a hand-authored SVG that may
    have arbitrary fill values (the panel CSS forces currentColor
    on every path regardless), so we only assert it's recognisable
    SVG text; the trace pipeline's own ``currentColor`` rewrite is
    asserted by ``test_trace_to_svg_produces_themable_currentcolor_fill``."""
    weapon_icons.reset_cache()
    svg = weapon_icons.icon_svg_for_num(350)
    assert svg is not None
    assert "<svg" in svg


def test_icon_svg_for_num_returns_none_for_skip_sentinel():
    assert weapon_icons.icon_svg_for_num(0) is None


def test_icon_svg_for_num_returns_none_for_unknown():
    # 270 — used by kessokmine but not in the SDK atlas.
    assert weapon_icons.icon_svg_for_num(270) is None


@potrace_required
def test_icon_svg_for_num_caches_result():
    weapon_icons.reset_cache()
    a = weapon_icons.icon_svg_for_num(350)
    b = weapon_icons.icon_svg_for_num(350)
    assert a is b


def test_icon_svg_for_num_returns_none_when_potrace_missing(monkeypatch, tmp_path):
    """The panel must not crash the host when potrace is uninstalled.
    Returning None drops the icon silently — the rest of the UI
    continues to render."""
    monkeypatch.setattr(weapon_icons, "_CURATED_DIR", str(tmp_path / "curated"))
    monkeypatch.setattr(weapon_icons, "_SVG_CACHE_DIR", str(tmp_path / "empty"))
    monkeypatch.setattr(weapon_icons, "_potrace_available", lambda: False)
    weapon_icons.reset_cache()
    assert weapon_icons.icon_svg_for_num(350) is None


def test_curated_svg_overrides_auto_trace(monkeypatch, tmp_path):
    """A hand-authored SVG under native/assets/ui-cef/icons/weapons/
    must win over the cache trace. The point of the dual-tier lookup
    is to let curated assets travel with the repo while the trace
    handles everything else (mods, unauthored sprites)."""
    curated = tmp_path / "curated"
    curated.mkdir()
    (curated / "350.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="54" height="24">'
        '<title>hand-authored</title></svg>'
    )
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "350.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="54" height="24">'
        '<title>auto-traced</title></svg>'
    )
    monkeypatch.setattr(weapon_icons, "_CURATED_DIR", str(curated))
    monkeypatch.setattr(weapon_icons, "_SVG_CACHE_DIR", str(cache))
    weapon_icons.reset_cache()

    svg = weapon_icons.icon_svg_for_num(350)
    assert svg is not None
    assert "hand-authored" in svg
    assert "auto-traced" not in svg


def test_curated_dir_miss_falls_through_to_cache(monkeypatch, tmp_path):
    """When no hand-authored SVG exists for a num, the lookup falls
    through to the auto-traced cache — that's how the curated layer
    can be incrementally populated without losing icons in the
    interim."""
    curated = tmp_path / "curated"
    curated.mkdir()  # empty
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "350.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="54" height="24">'
        '<title>auto-traced</title></svg>'
    )
    monkeypatch.setattr(weapon_icons, "_CURATED_DIR", str(curated))
    monkeypatch.setattr(weapon_icons, "_SVG_CACHE_DIR", str(cache))
    weapon_icons.reset_cache()

    svg = weapon_icons.icon_svg_for_num(350)
    assert svg is not None
    assert "auto-traced" in svg
