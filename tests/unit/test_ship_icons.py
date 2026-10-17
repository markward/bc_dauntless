"""ship_icons.icon_path_for_species converts the game's TGA on first
access and serves the cached PNG thereafter."""
import os
import shutil
from pathlib import Path

import pytest


def test_returns_none_for_unknown_species(tmp_path, monkeypatch):
    from engine.ui import ship_icons
    monkeypatch.setattr(ship_icons, "_game_icon_file",
                         lambda name: tmp_path / "missing" / (name + ".tga"))
    monkeypatch.setattr(ship_icons, "_CACHE_DIR", str(tmp_path / "cache"))
    ship_icons.reset_cache()
    assert ship_icons.icon_path_for_species("NoSuchShip") is None


def test_an_undecodable_icon_degrades_instead_of_raising(tmp_path, monkeypatch):
    """A silhouette is decoration; it must never be able to kill the run.

    This is not hypothetical: routing mod icons through the decoder surfaced
    a Targa type the decoder refused, and the ValueError went straight up
    through ship_display_panel.render_payload into the host loop and ended
    the session. A mod asset is untrusted input -- an unreadable one costs
    its silhouette and nothing else.
    """
    from engine.ui import ship_icons
    icons_dir = tmp_path / "icons"
    icons_dir.mkdir()
    # A real file, but not a TGA this (or any) decoder can read.
    (icons_dir / "Broken.tga").write_bytes(b"not a targa at all, honestly")

    monkeypatch.setattr(ship_icons, "_game_icon_file",
                         lambda name: icons_dir / (name + ".tga"))
    monkeypatch.setattr(ship_icons, "_CACHE_DIR", str(tmp_path / "cache"))
    ship_icons.reset_cache()

    assert ship_icons.icon_path_for_species("Broken") is None
    # And the failure is remembered, so a per-frame panel render does not
    # re-read and re-fail on the same file every frame.
    assert ship_icons.icon_path_for_species("Broken") is None


def test_converts_tga_and_returns_data_url(tmp_path, monkeypatch):
    """First call decodes the TGA, encodes a PNG, and returns a
    data:image/png;base64,... URL. The disk-cache PNG is also written
    for debugging."""
    import base64
    import struct
    from engine.ui import ship_icons
    icons_dir = tmp_path / "icons"
    icons_dir.mkdir()
    pixels = bytes([0,0,255,255,  255,0,0,255])
    header = struct.pack("<BBBHHBHHHHBB", 0,0,2, 0,0,0, 0,0, 2,1, 32, 0x20)
    (icons_dir / "Galaxy.tga").write_bytes(header + pixels)
    cache_dir = tmp_path / "cache"

    monkeypatch.setattr(ship_icons, "_game_icon_file",
                         lambda name: icons_dir / (name + ".tga"))
    monkeypatch.setattr(ship_icons, "_CACHE_DIR",      str(cache_dir))
    from engine import dev_mode
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    ship_icons.reset_cache()

    url = ship_icons.icon_path_for_species("Galaxy")
    assert url is not None
    assert url.startswith("data:image/png;base64,")
    # The base64 body decodes to a PNG byte stream.
    body = url[len("data:image/png;base64,"):]
    png_bytes = base64.b64decode(body)
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    # Disk cache copy was also written.
    assert (cache_dir / "Galaxy.png").is_file()

    # Second call hits the in-memory cache and returns the same URL.
    assert ship_icons.icon_path_for_species("Galaxy") == url


# ── icon_file_url_for_species: a file:// PNG instead of an inline copy ─────
# The Quick Battle screen inlined 41 icons as base64 (725 KB of its 960 KB
# first push, measured 2026-10-17). A file URL is ~100 bytes.

def _tga(pixels=bytes([0, 0, 255, 255, 255, 0, 0, 255])):
    import struct
    header = struct.pack("<BBBHHBHHHHBB", 0, 0, 2, 0, 0, 0, 0, 0, 2, 1, 32, 0x20)
    return header + pixels


@pytest.fixture
def icon_env(tmp_path, monkeypatch):
    from engine import paths
    from engine.ui import ship_icons
    icons_dir = tmp_path / "icons"
    icons_dir.mkdir()
    monkeypatch.setattr(ship_icons, "_game_icon_file",
                        lambda name: icons_dir / (name + ".tga"))
    monkeypatch.setattr(paths, "cache_dir", lambda: tmp_path / "cache")
    decodes = []
    real = ship_icons.decode_tga
    monkeypatch.setattr(ship_icons, "decode_tga",
                        lambda blob: decodes.append(1) or real(blob))
    ship_icons.reset_cache()
    yield icons_dir, tmp_path / "cache" / "icons" / "ships", decodes
    ship_icons.reset_cache()


def _file_of(url):
    from urllib.parse import unquote, urlparse
    assert url.startswith("file://")
    return Path(unquote(urlparse(url).path))


def test_file_url_points_at_a_png_in_the_user_cache(icon_env):
    from engine.ui import ship_icons
    icons_dir, cache, decodes = icon_env
    (icons_dir / "Galaxy.tga").write_bytes(_tga())
    url = ship_icons.icon_file_url_for_species("Galaxy")
    f = _file_of(url)
    assert f.parent == cache and f.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert ship_icons.icon_file_url_for_species("Galaxy") == url
    assert len(decodes) == 1


def test_a_cached_png_is_reused_next_session_without_decoding(icon_env):
    from engine.ui import ship_icons
    icons_dir, _cache, decodes = icon_env
    (icons_dir / "Galaxy.tga").write_bytes(_tga())
    url = ship_icons.icon_file_url_for_species("Galaxy")
    ship_icons.reset_cache()                      # a new session
    assert ship_icons.icon_file_url_for_species("Galaxy") == url
    assert len(decodes) == 1


def test_a_changed_tga_never_serves_the_old_png(icon_env):
    """The cache file is named by the TGA's content: a mod replacing the
    icon must not be shown the stale PNG from an earlier session."""
    from engine.ui import ship_icons
    icons_dir, _cache, _d = icon_env
    (icons_dir / "Galaxy.tga").write_bytes(_tga())
    old = ship_icons.icon_file_url_for_species("Galaxy")
    ship_icons.reset_cache()
    (icons_dir / "Galaxy.tga").write_bytes(_tga(bytes([9, 9, 9, 255, 1, 2, 3, 255])))
    assert ship_icons.icon_file_url_for_species("Galaxy") != old


def test_a_converter_change_never_serves_the_old_png(icon_env, monkeypatch):
    """The PNGs outlive the build: a decoder/encoder fix must bump the cache
    version, which renames every file."""
    from engine.ui import ship_icons
    icons_dir, _cache, _d = icon_env
    (icons_dir / "Galaxy.tga").write_bytes(_tga())
    old = ship_icons.icon_file_url_for_species("Galaxy")
    ship_icons.reset_cache()
    monkeypatch.setattr(ship_icons, "_PNG_CACHE_VERSION", ship_icons._PNG_CACHE_VERSION + 1)
    assert ship_icons.icon_file_url_for_species("Galaxy") != old


def test_a_leftover_temp_path_does_not_break_the_write(icon_env):
    """Two game processes at once used to share one fixed temp name."""
    from engine.ui import ship_icons
    icons_dir, cache, _d = icon_env
    (icons_dir / "Galaxy.tga").write_bytes(_tga())
    url = ship_icons.icon_file_url_for_species("Galaxy")
    target = _file_of(url)
    target.unlink()
    (cache / (target.name + ".tmp")).mkdir()        # the old fixed name, taken
    ship_icons.reset_cache()
    assert ship_icons.icon_file_url_for_species("Galaxy") == url
    assert target.is_file()


def test_missing_or_undecodable_icons_give_none(icon_env):
    from engine.ui import ship_icons
    icons_dir, _cache, _d = icon_env
    (icons_dir / "Broken.tga").write_bytes(b"not a targa at all, honestly")
    assert ship_icons.icon_file_url_for_species("NoSuchShip") is None
    assert ship_icons.icon_file_url_for_species("Broken") is None


def test_an_unwritable_cache_falls_back_to_a_data_url_and_says_so(icon_env, monkeypatch):
    from engine import paths
    from engine.ui import ship_icons
    icons_dir, cache, _d = icon_env
    (icons_dir / "Galaxy.tga").write_bytes(_tga())
    cache.parent.parent.write_text("a file where the cache dir should be")
    reported = []
    monkeypatch.setattr(paths, "report_write_failure",
                        lambda path, exc: reported.append(path))
    url = ship_icons.icon_file_url_for_species("Galaxy")
    assert url.startswith("data:image/png;base64,") and reported
