"""ship_icons.icon_path_for_species converts the game's TGA on first
access and serves the cached PNG thereafter."""
import os
import shutil


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
