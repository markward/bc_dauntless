import os
from pathlib import Path

import pytest

from engine import mods


def _touch(p: Path, body: str = "x") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def test_fold_lowercases_and_normalises_separators():
    assert mods.fold("Data\\Models\\A.NIF") == "data/models/a.nif"
    assert mods.fold("data/Models/a.nif") == "data/models/a.nif"


def test_data_maps_to_the_game_target(tmp_path):
    _touch(tmp_path / "M" / "Data" / "Models" / "Ships" / "A.NIF")
    idx = mods.build_index(tmp_path)
    hit = idx.lookup("data/Models/Ships/a.nif")
    assert hit is not None
    assert hit.target == "game"
    assert hit.mod_name == "M"
    assert hit.abs_path == tmp_path / "M" / "Data" / "Models" / "Ships" / "A.NIF"


def test_scripts_maps_to_the_sdk_target(tmp_path):
    _touch(tmp_path / "M" / "Scripts" / "Ships" / "Fsteamr.py")
    idx = mods.build_index(tmp_path)
    hit = idx.lookup("ships/Fsteamr.py")
    assert hit is not None and hit.target == "sdk"


def test_case_collisions_all_resolve(tmp_path):
    # The three real collisions from the reference mod.
    _touch(tmp_path / "M" / "Data" / "Models" / "S" / "Fsteamr.NIF")
    idx = mods.build_index(tmp_path)
    for spelling in ("data/Models/S/Fsteamr.nif",
                     "DATA/models/s/FSTEAMR.NIF",
                     "data/models/s/fsteamr.nif"):
        assert idx.lookup(spelling) is not None, spelling


def test_unknown_top_level_dir_is_recorded_not_dropped(tmp_path):
    _touch(tmp_path / "M" / "Data" / "a.nif")
    _touch(tmp_path / "M" / "Sounds" / "b.wav")
    idx = mods.build_index(tmp_path)
    assert idx.lookup("sounds/b.wav") is None
    status = {m.name: m for m in idx.mods}["M"]
    assert "Sounds" in status.unplaced


def test_junk_is_ignored_and_counted(tmp_path):
    _touch(tmp_path / "M" / "Data" / "a.nif")
    _touch(tmp_path / "M" / ".DS_Store")
    _touch(tmp_path / "M" / "Data" / ".DS_Store")
    _touch(tmp_path / "M" / "readme.txt")
    idx = mods.build_index(tmp_path)
    status = {m.name: m for m in idx.mods}["M"]
    assert status.placed == 1
    assert status.ignored == 3


def test_later_mod_wins_and_ordering_is_deterministic(tmp_path):
    _touch(tmp_path / "Alpha" / "Data" / "a.nif", "alpha")
    _touch(tmp_path / "Bravo" / "Data" / "a.nif", "bravo")
    idx = mods.build_index(tmp_path)
    assert idx.lookup("data/a.nif").mod_name == "Bravo"
    assert mods.build_index(tmp_path).lookup("data/a.nif").mod_name == "Bravo"


def test_mod_without_content_root_contributes_nothing(tmp_path):
    _touch(tmp_path / "JustDocs" / "readme.txt")
    idx = mods.build_index(tmp_path)
    assert idx.files == {}
    assert {m.name for m in idx.mods} == {"JustDocs"}


def test_empty_root_yields_empty_index(tmp_path):
    idx = mods.build_index(tmp_path / "absent")
    assert idx.files == {}
    assert idx.mods == []


def test_dirs_for_returns_every_providing_mod_dir(tmp_path):
    _touch(tmp_path / "Alpha" / "Data" / "Tex" / "a.tga")
    _touch(tmp_path / "Bravo" / "Data" / "Tex" / "b.tga")
    idx = mods.build_index(tmp_path)
    got = idx.dirs_for("data/Tex")
    assert sorted(p.name for p in got) == ["Tex", "Tex"]
    assert {p.parent.parent.name for p in got} == {"Alpha", "Bravo"}


@pytest.mark.skipif(getattr(os, "geteuid", lambda: -1)() == 0,
                    reason="root ignores mode 000, so nothing is unreadable")
def test_permission_error_in_one_mod_does_not_prevent_others(tmp_path):
    # Create two mods: one readable, one with an unreadable subdirectory.
    _touch(tmp_path / "Good" / "Data" / "a.nif")
    bad_dir = tmp_path / "Bad" / "Data" / "SubDir"
    _touch(bad_dir / "hidden.nif")

    # Make the subdirectory unreadable.
    os.chmod(bad_dir, 0o000)
    try:
        # Index should skip the Bad mod's files but still include Good's.
        idx = mods.build_index(tmp_path)
        assert idx.lookup("data/a.nif") is not None
        assert idx.lookup("data/a.nif").mod_name == "Good"
        # Bad mod should be present in statuses but have no placed files.
        status_by_name = {m.name: m for m in idx.mods}
        assert "Bad" in status_by_name
        assert status_by_name["Bad"].placed == 0
        # The point of the whole exercise: an unreadable subtree must be
        # OBSERVED, not silently reported as an empty mod. Path.rglob()
        # swallows the permission error and just does not descend, so this
        # assertion is what separates a real walk from a blind one.
        assert status_by_name["Bad"].read_error is True
        text = mods.describe(idx)
        assert "Bad" in text
        assert "could not read mod contents" in text
    finally:
        # Restore permissions so tmp_path teardown can clean up.
        os.chmod(bad_dir, 0o755)


def test_sfx_maps_to_the_game_target(tmp_path):
    """A mod's sfx/ tree is placeable content, not an unplaced curiosity.

    The real BC install root holds data/, scripts/ AND sfx/, and
    engine/lip_sync_runtime.py already resolves "sfx/..." through
    game_asset(). A voice or weapon-sound pack ships only sfx/, so without
    this such a mod reports "no BC content found" and contributes nothing.
    """
    _touch(tmp_path / "M" / "sfx" / "Weapons" / "Zap.wav")
    idx = mods.build_index(tmp_path)
    hit = idx.lookup("sfx/Weapons/zap.wav")
    assert hit is not None
    assert hit.target == "game"
    assert hit.abs_path == tmp_path / "M" / "sfx" / "Weapons" / "Zap.wav"


def test_sfx_is_no_longer_reported_unplaced(tmp_path):
    _touch(tmp_path / "M" / "sfx" / "a.wav")
    idx = mods.build_index(tmp_path)
    status = {m.name: m for m in idx.mods}["M"]
    assert status.unplaced == []
    assert status.placed == 1


def test_sfx_content_root_is_found_from_sfx_alone(tmp_path):
    """A mod shipping ONLY sfx/ must still be recognised as BC content."""
    _touch(tmp_path / "SoundPack" / "sfx" / "Weapons" / "a.wav")
    assert mods.find_content_root(tmp_path / "SoundPack") == tmp_path / "SoundPack"
