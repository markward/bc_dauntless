from pathlib import Path

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
