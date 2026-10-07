"""dialogue_patches 'replace' entries are merged into a TGL's database when
TGLocalizationManager builds it."""
import json

import pytest

from engine.appc import dialogue_patches as dp
from engine.appc.localization import TGLocalizationManager
from engine.missions.tgl_reader import write_tgl

TGL = "data/TGL/Test/Patched.tgl"


@pytest.fixture
def setup(monkeypatch, tmp_path):
    """A fake install with one TGL, and a patches.json writer."""
    from engine import paths
    game = tmp_path / "install"
    (game / "data" / "TGL" / "Test").mkdir(parents=True)
    (game / "data" / "TGL" / "Test" / "Patched.tgl").write_bytes(write_tgl([
        ("Keep", "Original keep.", "sfx/keep.mp3"),
        ("Swap", "Original swap.", "sfx/swap.mp3"),
    ]))
    monkeypatch.setattr(paths, "game_asset", lambda rel: game / rel)
    patch_file = tmp_path / "patches.json"
    monkeypatch.setattr(dp, "patches_path", lambda: patch_file)
    dp.reset_cache()

    def write(data):
        patch_file.write_text(json.dumps(data))
        dp.reset_cache()
    yield write
    dp.reset_cache()


def test_no_patch_leaves_the_database_as_bc_ships_it(setup):
    db = TGLocalizationManager().Load(TGL)
    assert db.GetString("Swap") == "Original swap."
    assert db.GetFilename("Swap") == "sfx/swap.mp3"


def test_text_only_replacement_keeps_the_voice(setup):
    setup({TGL: {"replace": {"Swap": {"text": "New swap."}}}})
    db = TGLocalizationManager().Load(TGL)
    assert db.GetString("Swap") == "New swap."
    assert db.GetFilename("Swap") == "sfx/swap.mp3"
    assert db.GetString("Keep") == "Original keep."


def test_sound_only_replacement_keeps_the_text(setup):
    setup({TGL: {"replace": {"Swap": {"sound": "sfx/new.wav"}}}})
    db = TGLocalizationManager().Load(TGL)
    assert db.GetString("Swap") == "Original swap."
    assert db.GetFilename("Swap") == "sfx/new.wav"


def test_a_replace_entry_can_add_a_line_bc_never_had(setup):
    setup({TGL: {"replace": {"Brand": {"text": "Brand new.", "sound": "sfx/brand.wav"}}}})
    db = TGLocalizationManager().Load(TGL)
    assert db.HasString("Brand")
    assert db.GetFilename("Brand") == "sfx/brand.wav"


def test_the_script_spelling_of_the_path_still_matches(setup):
    setup({"data/TGL/Test/PATCHED.TGL": {"replace": {"Swap": {"text": "New swap."}}}})
    db = TGLocalizationManager().Load(TGL)
    assert db.GetString("Swap") == "New swap."
