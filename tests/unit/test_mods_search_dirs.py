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


def test_a_trailing_slash_in_the_caller_prefix_still_matches(monkeypatch, tmp_path):
    """host_loop composes f"{share}/{tier}" from a mod-authored
    SetTextureSharePath. A share ending in "/" yields "data/x//High", whose
    doubled separator prefix-matched no index key at all -- silently
    degrading that whole texture group to stock-only."""
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "g")
    _touch(tmp_path / "mods" / "M" / "Data" / "Textures" / "Shared" / "High" / "a.tga")
    mods.configure(mods.build_index(tmp_path / "mods"))
    share = "data/Textures/Shared/"      # a mod author's trailing slash
    got = paths.game_asset_dirs(f"{share}/High")
    assert got[0] == tmp_path / "mods" / "M" / "Data" / "Textures" / "Shared" / "High"
    # ...and the stock arm is unchanged: Path already collapses the double.
    assert got[-1] == tmp_path / "g" / "data/Textures/Shared/High"


def test_double_separators_are_not_folded_into_the_index_keys(tmp_path):
    """fold() itself must NOT change: native/src/renderer/asset_path.cc's
    fold_key() mirrors it byte-for-byte, and the map's keys are built from
    path parts, so they can never hold a double separator anyway."""
    assert mods.fold("data/x//High/") == "data/x//high"
    assert mods.fold_search_prefix("data/x//High/") == "data/x/high"
