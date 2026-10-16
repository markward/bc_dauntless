"""Saves follow paths.saves_dir(); loads never create it; no path escape."""
from pathlib import Path

import pytest

from engine import paths
from engine.appc.save_load import SaveLoadManager, _normalize
from engine.core.game import Game, Episode, Mission, _set_current_game


@pytest.fixture
def fresh_game():
    mission = Mission()
    episode = Episode()
    episode.SetCurrentMission(mission)
    game = Game()
    game.SetCurrentEpisode(episode)
    _set_current_game(game)
    yield game
    _set_current_game(None)


def test_autosave_name_lands_in_saves_dir(fresh_game):
    mgr = SaveLoadManager()
    assert mgr.SaveToFile("saves//Captain Save-E1M1Picard.BCS") == 1
    assert (paths.saves_dir() / "Captain Save-E1M1Picard.BCS").is_file()


def test_quicksave_backslash_form(fresh_game):
    mgr = SaveLoadManager()
    assert mgr.SaveToFile("saves\\QuickSav.BCS") == 1
    assert (paths.saves_dir() / "QuickSav.BCS").is_file()


def test_mission_state_lands_in_saves_missions(fresh_game):
    mgr = SaveLoadManager()
    mgr._current_mission_module = lambda: "Maelstrom.Episode1.E1M1"
    assert mgr.SaveMissionState() == 1
    assert (paths.saves_dir() / "missions" / "Maelstrom.Episode1.E1M1.json").is_file()


def test_load_does_not_create_saves_dir(fresh_game, tmp_path, monkeypatch):
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path / "fresh"))
    mgr = SaveLoadManager()
    assert not paths.saves_dir().exists()
    assert mgr.LoadFromFile("saves\\QuickSav.BCS") == 0
    assert not paths.saves_dir().exists()


@pytest.mark.parametrize("name", [
    "saves//../../x.BCS",
    "saves\\..\\..\\x.BCS",
    "/abs/x.BCS",
])
def test_escape_attempts_stay_inside(fresh_game, name):
    mgr = SaveLoadManager()
    root = paths.saves_dir()
    assert mgr.SaveToFile(name) == 0
    assert not (root.parent / "x.BCS").exists()
    assert not (root.parent.parent / "x.BCS").exists()
    assert not Path("/abs/x.BCS").exists()
    with pytest.raises(ValueError):
        _normalize(name)


def test_checkout_saves_path_unchanged(monkeypatch):
    monkeypatch.delenv(paths.DATA_DIR_ENV, raising=False)
    assert _normalize("saves\\QuickSav.BCS") == paths.PROJECT_ROOT / "saves" / "QuickSav.BCS"


@pytest.mark.parametrize("name", ["C:\\x.BCS", "../x.BCS"])
def test_more_escape_forms(fresh_game, name):
    assert SaveLoadManager().SaveToFile(name) == 0
    assert not (paths.saves_dir().parent / "x.BCS").exists()


def test_mission_module_with_dotdot_stays_inside(fresh_game):
    mgr = SaveLoadManager()
    mgr._current_mission_module = lambda: "../../evil"
    assert mgr.SaveMissionState() == 0
    root = paths.saves_dir()
    assert not (root.parent / "evil.json").exists()
    assert not (root.parent.parent / "evil.json").exists()


def test_write_failure_reports_resolved_path(fresh_game, capsys, tmp_path, monkeypatch):
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path / "fresh"))
    paths._reset_write_failure_reports()
    root = paths.saves_dir()
    root.parent.mkdir(parents=True, exist_ok=True)
    root.write_text("a file, so mkdir/write under it fails")
    try:
        assert SaveLoadManager().SaveToFile("saves//Captain Save-E1M1Picard.BCS") == 0
    finally:
        root.unlink()
    err = capsys.readouterr().err
    assert str(root / "Captain Save-E1M1Picard.BCS") in err
