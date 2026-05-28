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


def test_converts_tga_and_caches_png(tmp_path, monkeypatch):
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
    assert url == "icons/ships/Galaxy.png"
    assert (cache_dir / "Galaxy.png").is_file()

    first_mtime = (cache_dir / "Galaxy.png").stat().st_mtime
    url2 = ship_icons.icon_path_for_species("Galaxy")
    assert url2 == url
    assert (cache_dir / "Galaxy.png").stat().st_mtime == first_mtime
