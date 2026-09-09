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


def test_zero_mods_is_byte_identical_to_the_stock_path(monkeypatch, tmp_path):
    # THE regression guard: a modless boot must not shift at all.
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "g")
    assert paths.game_asset("data/Textures/x.tga") == tmp_path / "g" / "data/Textures/x.tga"


def test_unconfigured_index_does_not_scan_disk(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "g")
    monkeypatch.setattr(mods, "discover_mods",
                        lambda root: pytest.fail("must not scan"))
    assert paths.game_asset("data/x.tga") == tmp_path / "g" / "data/x.tga"


def test_indexed_file_resolves_to_the_mod(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "g")
    _touch(tmp_path / "mods" / "M" / "Data" / "Textures" / "X.TGA")
    mods.configure(mods.build_index(tmp_path / "mods"))
    got = paths.game_asset("data/Textures/x.tga")
    assert got == tmp_path / "mods" / "M" / "Data" / "Textures" / "X.TGA"


def test_unindexed_file_still_falls_back_to_stock(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "g")
    _touch(tmp_path / "mods" / "M" / "Data" / "Textures" / "X.TGA")
    mods.configure(mods.build_index(tmp_path / "mods"))
    assert paths.game_asset("data/other.tga") == tmp_path / "g" / "data/other.tga"


def test_sdk_targeted_entries_do_not_leak_into_game_asset(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "g")
    _touch(tmp_path / "mods" / "M" / "Scripts" / "ships" / "A.py")
    mods.configure(mods.build_index(tmp_path / "mods"))
    # "ships/A.py" is an SDK path; game_asset must not serve it.
    assert paths.game_asset("ships/A.py") == tmp_path / "g" / "ships/A.py"
