"""native/assets/replacements/ overrides stock game content (and mods)."""
import pytest

from engine import mods, paths


@pytest.fixture
def replacement(tmp_path, monkeypatch):
    project_assets = tmp_path / "assets"
    # Spelled differently from the lookup on purpose: the match is case-folded.
    tex = project_assets / "replacements/Data/Models/Ships/BirdOfPrey/High/BOP_wing.tga"  # paths-guard: test fixture tree
    tex.parent.mkdir(parents=True)
    tex.write_bytes(b"tga")
    monkeypatch.setattr(paths, "project_asset_root", lambda: project_assets)
    monkeypatch.setattr(mods, "_REPLACEMENTS", None)
    yield tex
    mods._REPLACEMENTS = None


def test_game_override_prefers_replacement(replacement):
    assert mods.game_override("data/models/ships/birdofprey/high/bop_wing.tga") == replacement


def test_texture_search_dirs_put_replacement_first(replacement):
    dirs = paths.game_asset_dirs("data/Models/Ships/BirdOfPrey/High")
    assert dirs[0] == replacement.parent
    assert len(dirs) == 2  # replacement dir, then stock


def test_renderer_map_includes_replacement(replacement):
    payload = mods.renderer_overrides_with_replacements(mods.ModIndex(files={}, mods=[]))
    assert payload == {
        "data/models/ships/birdofprey/high/bop_wing.tga": str(replacement)}


def test_no_replacements_dir_is_stock(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "project_asset_root", lambda: tmp_path)
    monkeypatch.setattr(mods, "_REPLACEMENTS", None)
    assert mods.game_override("data/x.tga") is None
    assert len(paths.game_asset_dirs("data")) == 1
    mods._REPLACEMENTS = None


def test_ship_texture_search_puts_replacement_before_own_folder(replacement, tmp_path, monkeypatch):
    """The NIF's own folder is searched before any shared dir, so without this
    a stock bop_wing.tga beside the NIF would beat the replacement."""
    from engine import host_loop
    game = tmp_path / "install"
    monkeypatch.setattr(paths, "game_root", lambda: game)
    monkeypatch.setattr(host_loop, "_ship_texture_share_path", lambda ship: "data/Models/SharedTextures/FedShips")
    nif = game / "data/Models/Ships/BirdOfPrey/BirdOfPrey.nif"  # paths-guard: test fixture tree
    dirs = host_loop._ship_texture_search(str(nif), ship=None)
    assert dirs[0] == str(replacement.parent)
    assert dirs.index(str(replacement.parent)) < dirs.index(str(nif.parent / "High"))
