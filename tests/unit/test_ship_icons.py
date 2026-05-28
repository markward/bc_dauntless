"""ship_icons.icon_path_for_species converts the game's TGA on first
access and serves the cached PNG thereafter."""
import os
import shutil


def test_returns_none_for_unknown_species(tmp_path, monkeypatch):
    from engine.ui import ship_icons
    monkeypatch.setattr(ship_icons, "_GAME_ICONS_DIR", str(tmp_path / "missing"))
    monkeypatch.setattr(ship_icons, "_CACHE_DIR", str(tmp_path / "cache"))
    ship_icons.reset_cache()
    assert ship_icons.icon_path_for_species("NoSuchShip") is None


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

    monkeypatch.setattr(ship_icons, "_GAME_ICONS_DIR", str(icons_dir))
    monkeypatch.setattr(ship_icons, "_CACHE_DIR",      str(cache_dir))
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
