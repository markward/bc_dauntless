"""Validation of a candidate BC game/sdk root.

Every test here runs with no real BC install present: fake_bc_install builds
marker trees under tmp_path.
"""
from engine import paths


def test_a_complete_game_tree_validates(fake_bc_install):
    game, _sdk = fake_bc_install
    v = paths.validate_game_root(game)
    assert v.ok
    assert v.missing == ()
    assert v.hint is None


def test_a_complete_sdk_tree_validates(fake_bc_install):
    _game, sdk = fake_bc_install
    v = paths.validate_sdk_root(sdk)
    assert v.ok
    assert v.missing == ()


def test_missing_markers_are_listed_in_declaration_order(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "Textures").mkdir()
    v = paths.validate_game_root(tmp_path)
    assert not v.ok
    assert v.missing == ("data/Models", "data/Icons")


def test_stbc_exe_and_scripts_are_not_required(fake_bc_install):
    """A content-only copy is usable: neither is loaded at runtime."""
    game, _sdk = fake_bc_install
    assert not (game / "stbc.exe").exists()
    assert not (game / "scripts").exists()
    assert paths.validate_game_root(game).ok


def test_a_nonexistent_path_is_invalid_not_an_error(tmp_path):
    v = paths.validate_game_root(tmp_path / "nope")
    assert not v.ok
    assert v.missing == paths.GAME_MARKERS


# --- diagnoses --------------------------------------------------------------

def test_hint_when_the_parent_was_picked(fake_bc_install):
    """The most common mistake: picking the folder that CONTAINS game/."""
    game, _sdk = fake_bc_install
    v = paths.validate_game_root(game.parent)
    assert not v.ok
    assert v.hint is not None
    assert "contains 'game'" in v.hint
    assert str(game) in v.hint


def test_hint_when_the_two_roots_are_swapped(fake_bc_install):
    game, sdk = fake_bc_install
    v = paths.validate_game_root(sdk)
    assert not v.ok
    assert v.hint == "That's the SDK folder; it belongs in the SDK field."

    v2 = paths.validate_sdk_root(game)
    assert not v2.ok
    assert v2.hint == "That's the game folder; it belongs in the game field."


def test_hint_when_one_level_too_deep(fake_bc_install):
    """Picking game/data instead of game/."""
    game, _sdk = fake_bc_install
    v = paths.validate_game_root(game / "data")
    assert not v.ok
    assert v.hint is not None
    assert "pick its parent" in v.hint
    assert str(game) in v.hint


def test_case_mismatch_improves_the_message_without_changing_the_verdict(tmp_path):
    """On a case-sensitive volume, 'Data/' vs 'data/' is the whole problem.

    The else branch below (the "this volume is case-sensitive" hint path) is
    case-sensitive-filesystem-only coverage: on a case-insensitive volume the
    exact check already succeeds and that branch never runs here. See
    test_case_insensitive_spelling_finds_the_real_on_disk_name and
    test_hint_names_both_spellings_when_every_marker_differs_only_by_case
    below for filesystem-independent coverage of the same feature.
    """
    root = tmp_path / "install"
    for rel in ("Data", "Data/Models", "Data/Textures", "Data/Icons"):
        (root / rel).mkdir(parents=True, exist_ok=True)
    v = paths.validate_game_root(root)
    if (root / "data").exists():
        # Case-insensitive filesystem: the exact check already succeeded and
        # the rescan must never have fired.
        assert v.ok
        assert v.hint is None
    else:
        assert not v.ok
        assert v.hint is not None
        assert "Data" in v.hint and "data" in v.hint


def test_case_insensitive_spelling_finds_the_real_on_disk_name(tmp_path):
    """Deterministic on any filesystem: the lookup compares iterdir() names
    itself rather than asking the OS to match case, so it does not depend on
    the volume being case-sensitive."""
    (tmp_path / "Data" / "Models").mkdir(parents=True)
    assert paths._case_insensitive_spelling(tmp_path, "data") == "Data"
    assert paths._case_insensitive_spelling(tmp_path, "data/models") == "Data/Models"
    assert paths._case_insensitive_spelling(tmp_path, "data/nope") is None
    assert paths._case_insensitive_spelling(tmp_path / "absent", "data") is None


def test_hint_names_both_spellings_when_every_marker_differs_only_by_case(tmp_path):
    """The branch test_case_mismatch_... cannot reach on a case-insensitive
    volume, driven directly so it runs everywhere."""
    for rel in ("Data", "Data/Models", "Data/Textures", "Data/Icons"):
        (tmp_path / rel).mkdir(parents=True, exist_ok=True)
    hint = paths._hint_for(tmp_path, "game", paths.GAME_MARKERS)
    assert hint is not None
    assert "Data" in hint and "data" in hint
    assert "case-sensitive" in hint


def test_hint_is_none_when_the_folder_is_simply_wrong(tmp_path):
    (tmp_path / "unrelated").mkdir()
    v = paths.validate_game_root(tmp_path)
    assert not v.ok
    assert v.hint is None


def test_validation_never_writes_anything(fake_bc_install):
    game, _sdk = fake_bc_install
    before = sorted(p.name for p in game.rglob("*"))
    paths.validate_game_root(game)
    paths.validate_game_root(game.parent)
    assert sorted(p.name for p in game.rglob("*")) == before
