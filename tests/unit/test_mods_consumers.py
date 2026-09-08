from pathlib import Path

import pytest

from engine import mods, paths


def _touch(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x")


@pytest.fixture(autouse=True)
def _clear_index():
    mods.configure(None)
    yield
    mods.configure(None)


def test_ship_icon_path_prefers_a_mod(monkeypatch, tmp_path):
    from engine.ui import ship_icons
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "g")
    _touch(tmp_path / "mods" / "M" / "Data" / "Icons" / "Ships" / "Fsteamr.tga")
    mods.configure(mods.build_index(tmp_path / "mods"))
    got = ship_icons._game_icon_file("Fsteamr")
    assert got == tmp_path / "mods" / "M" / "Data" / "Icons" / "Ships" / "Fsteamr.tga"


def test_ship_icon_path_falls_back_to_stock(monkeypatch, tmp_path):
    from engine.ui import ship_icons
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "g")
    got = ship_icons._game_icon_file("Galaxy")
    assert got == tmp_path / "g" / "data/Icons/Ships/Galaxy.tga"


def test_viewscreen_static_frames_prefer_a_mod(monkeypatch, tmp_path):
    from engine.appc import viewscreen_static
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "g")
    _touch(tmp_path / "mods" / "M" / "Data" / "Textures" / "Effects" / "Noise2.tga")
    mods.configure(mods.build_index(tmp_path / "mods"))
    got = viewscreen_static.static_texture_paths("View Screen Static")
    assert got[1] == str(
        tmp_path / "mods" / "M" / "Data" / "Textures" / "Effects" / "Noise2.tga")
    # The other two frames are unmodded and still come from stock.
    assert got[0] == str(tmp_path / "g" / "data/Textures/Effects/Noise1.tga")


def test_viewscreen_static_unknown_group_is_still_empty(monkeypatch, tmp_path):
    from engine.appc import viewscreen_static
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "g")
    assert viewscreen_static.static_texture_paths("nope") == []
