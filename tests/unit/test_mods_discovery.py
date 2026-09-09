from pathlib import Path

import pytest

from engine import mods


def _touch(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x")


def test_flat_layout_content_root_is_the_mod_dir(tmp_path):
    mod = tmp_path / "SomeShip"
    _touch(mod / "Data" / "Models" / "a.nif")
    _touch(mod / "Scripts" / "Ships" / "a.py")
    assert mods.find_content_root(mod) == mod


def test_redundant_nesting_is_descended(tmp_path):
    mod = tmp_path / "SomeShip"
    _touch(mod / "SomeShip" / "Data" / "Models" / "a.nif")
    assert mods.find_content_root(mod) == mod / "SomeShip"


def test_descent_stops_at_depth_cap(tmp_path):
    mod = tmp_path / "Deep"
    _touch(mod / "a" / "b" / "c" / "d" / "Data" / "x.nif")
    assert mods.find_content_root(mod, max_depth=3) is None


def test_no_content_dirs_yields_none(tmp_path):
    mod = tmp_path / "JustDocs"
    _touch(mod / "readme.txt")
    assert mods.find_content_root(mod) is None


def test_content_dirs_matched_case_blind(tmp_path):
    mod = tmp_path / "LowerCase"
    _touch(mod / "data" / "x.nif")
    assert mods.find_content_root(mod) == mod


def test_ambiguous_branch_is_not_descended(tmp_path):
    # Two subdirs and no content dir: we cannot know which to follow.
    mod = tmp_path / "Ambiguous"
    _touch(mod / "one" / "Data" / "x.nif")
    _touch(mod / "two" / "Data" / "x.nif")
    assert mods.find_content_root(mod) is None


def test_discover_lists_each_subdir_sorted(tmp_path):
    _touch(tmp_path / "Bravo" / "Data" / "b.nif")
    _touch(tmp_path / "Alpha" / "Data" / "a.nif")
    _touch(tmp_path / "Broken" / "readme.txt")
    found = mods.discover_mods(tmp_path)
    assert [m.name for m in found] == ["Alpha", "Bravo", "Broken"]
    assert found[2].content_root is None


def test_discover_missing_root_is_empty_not_an_error(tmp_path):
    assert mods.discover_mods(tmp_path / "nope") == []


def test_mods_root_defaults_to_project_root(monkeypatch, tmp_path):
    monkeypatch.setattr(mods.paths, "PROJECT_ROOT", tmp_path)
    assert mods.mods_root(argv=[], env={}) == tmp_path / "mods"


def test_mods_root_cli_flag_wins_over_env(tmp_path):
    got = mods.mods_root(argv=["--mods-dir", str(tmp_path / "a")],
                         env={"DAUNTLESS_MODS_DIR": str(tmp_path / "b")})
    assert got == mods.paths.normalise(tmp_path / "a")


def test_mods_root_env_used_when_no_flag(tmp_path):
    got = mods.mods_root(argv=[], env={"DAUNTLESS_MODS_DIR": str(tmp_path / "b")})
    assert got == mods.paths.normalise(tmp_path / "b")


def test_mods_root_empty_env_is_unset(monkeypatch, tmp_path):
    # Mirrors paths.py: an empty env var is idiomatic shell for "unset".
    monkeypatch.setattr(mods.paths, "PROJECT_ROOT", tmp_path)
    assert mods.mods_root(argv=[], env={"DAUNTLESS_MODS_DIR": ""}) == tmp_path / "mods"
