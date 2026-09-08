# tests/unit/test_mods_search_dirs.py
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


def test_no_mods_yields_only_the_stock_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "g")
    assert paths.game_asset_dirs("data/TGL") == [tmp_path / "g" / "data/TGL"]


def test_mod_dirs_come_first(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "g")
    _touch(tmp_path / "mods" / "M" / "Data" / "TGL" / "Extra.TGL")
    mods.configure(mods.build_index(tmp_path / "mods"))
    got = paths.game_asset_dirs("data/TGL")
    assert got == [tmp_path / "mods" / "M" / "Data" / "TGL",
                   tmp_path / "g" / "data/TGL"]


def test_every_providing_mod_contributes(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "g")
    _touch(tmp_path / "mods" / "Alpha" / "Data" / "TGL" / "a.TGL")
    _touch(tmp_path / "mods" / "Bravo" / "Data" / "TGL" / "b.TGL")
    mods.configure(mods.build_index(tmp_path / "mods"))
    got = paths.game_asset_dirs("data/TGL")
    assert len(got) == 3
    assert got[-1] == tmp_path / "g" / "data/TGL"


def test_a_mod_providing_nothing_there_is_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "g")
    _touch(tmp_path / "mods" / "M" / "Data" / "Icons" / "a.tga")
    mods.configure(mods.build_index(tmp_path / "mods"))
    assert paths.game_asset_dirs("data/TGL") == [tmp_path / "g" / "data/TGL"]


def test_tgl_roots_include_mod_dirs(monkeypatch, tmp_path):
    from engine.missions import name_resolver
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "g")
    monkeypatch.setattr(paths, "sdk_data", lambda: tmp_path / "s")
    _touch(tmp_path / "mods" / "M" / "Data" / "TGL" / "FTBShips.TGL")
    mods.configure(mods.build_index(tmp_path / "mods"))
    roots = name_resolver._tgl_roots()
    assert tmp_path / "mods" / "M" / "Data" / "TGL" in roots
    assert tmp_path / "s" / "TGL" in roots
