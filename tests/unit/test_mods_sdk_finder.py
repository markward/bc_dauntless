from pathlib import Path

import pytest

from engine import mods


def _touch(p: Path, body: str = "x = 1\n") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


@pytest.fixture(autouse=True)
def _clear_index():
    mods.configure(None)
    yield
    mods.configure(None)


def test_sdk_override_returns_the_mod_module(tmp_path):
    _touch(tmp_path / "M" / "Scripts" / "ships" / "Fsteamr.py")
    mods.configure(mods.build_index(tmp_path))
    assert mods.sdk_override("ships/Fsteamr.py") is not None


def test_sdk_override_is_case_blind_both_ways(tmp_path):
    _touch(tmp_path / "M" / "Scripts" / "Ships" / "Fsteamr.py")
    mods.configure(mods.build_index(tmp_path))
    # BC's filesystem made Ships and ships one directory; so do we.
    assert mods.sdk_override("ships/Fsteamr.py") is not None
    assert mods.sdk_override("Ships/Fsteamr.py") is not None


def test_game_targeted_entries_do_not_leak_into_sdk_override(tmp_path):
    _touch(tmp_path / "M" / "Data" / "a.py")
    mods.configure(mods.build_index(tmp_path))
    assert mods.sdk_override("data/a.py") is None


def test_no_index_means_no_override(tmp_path):
    assert mods.sdk_override("ships/Fsteamr.py") is None
