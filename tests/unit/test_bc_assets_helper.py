"""The guard that decides whether a BC-asset-dependent test runs or skips.

Its contract is that a test skips when the retail asset is genuinely absent --
and ONLY then. A guard that also skips when the asset is present under a
different case turns a full retail install into a silently reduced suite, and
does it invisibly: a skip reads the same whether the file is missing or merely
spelled differently.

That is not hypothetical here. BC ships "Bridge Crew General.TGL" while the SDK
scripts (and therefore our call sites) spell it ".tgl", and the engine copes:
assets/src/path_resolver.cc resolves through a lower-cased map of directory
entries. macOS and Windows hide the mismatch behind case-insensitive
filesystems; Linux does not.
"""
from pathlib import Path

import pytest

from tests.helpers import bc_assets


@pytest.fixture
def fake_game(tmp_path, monkeypatch):
    """A game/ tree whose on-disk casing differs from the SDK's spelling."""
    root = tmp_path / "game"
    (root / "data" / "TGL").mkdir(parents=True)
    (root / "data" / "TGL" / "Bridge Crew General.TGL").touch()
    (root / "data" / "Models" / "Ships").mkdir(parents=True)
    monkeypatch.setattr(bc_assets, "GAME_ROOT", root)
    return root


def test_asset_present_under_different_case_does_not_skip(fake_game):
    """The engine finds this file; so must the guard."""
    found = bc_assets.require_game_asset("data/TGL/Bridge Crew General.tgl")
    assert found.is_file()
    assert found.name == "Bridge Crew General.TGL", (
        "the guard must return the REAL path, not the requested spelling -- "
        "callers open what it hands back")


def test_asset_present_with_exact_case_does_not_skip(fake_game):
    found = bc_assets.require_game_asset("data/TGL/Bridge Crew General.TGL")
    assert found.is_file()


def test_genuinely_absent_asset_still_skips(fake_game):
    with pytest.raises(pytest.skip.Exception):
        bc_assets.require_game_asset("data/TGL/Not Shipped.tgl")


def test_directory_present_under_different_case_does_not_skip(fake_game):
    found = bc_assets.require_game_dir("data/models/ships")
    assert found.is_dir()


def test_genuinely_absent_directory_still_skips(fake_game):
    with pytest.raises(pytest.skip.Exception):
        bc_assets.require_game_dir("data/Icons/Ships")


def test_a_file_does_not_satisfy_a_directory_requirement(fake_game):
    with pytest.raises(pytest.skip.Exception):
        bc_assets.require_game_dir("data/TGL/Bridge Crew General.tgl")


def test_a_directory_does_not_satisfy_a_file_requirement(fake_game):
    with pytest.raises(pytest.skip.Exception):
        bc_assets.require_game_asset("data/TGL")


def test_missing_game_root_skips_rather_than_raising(tmp_path, monkeypatch):
    monkeypatch.setattr(bc_assets, "GAME_ROOT", tmp_path / "no-such-game")
    with pytest.raises(pytest.skip.Exception):
        bc_assets.require_game_asset("data/TGL/Anything.tgl")


def test_every_call_site_names_an_asset_this_install_actually_has():
    """Guards are only as good as their spelling, and a typo'd path is a
    permanent silent skip. With a retail install present, every path named by
    a require_game_* call must resolve.

    Best-effort by construction: it reads string literals passed inline, so a
    path held in a variable is not checked. It catches the common shape.
    """
    repo = Path(__file__).resolve().parents[2]
    if not (repo / "game" / "data").is_dir():
        pytest.skip("BC assets not available")

    import re
    pattern = re.compile(r"require_game_(?:asset|dir)\(\s*[\"']([^\"']+)[\"']")
    unresolved = []
    for path in (repo / "tests").rglob("*.py"):
        # This file's own paths are deliberately-absent fixtures for the
        # skip-when-missing branch, and the helper itself only defines the API.
        if path.name in ("bc_assets.py", Path(__file__).name):
            continue
        for relpath in pattern.findall(path.read_text(encoding="utf-8")):
            if bc_assets.resolve_game_path(relpath) is None:
                unresolved.append(f"{path.relative_to(repo)}: {relpath}")
    assert not unresolved, (
        "require_game_* paths that no retail asset satisfies (these tests skip "
        "forever):\n  " + "\n  ".join(unresolved))
