import json
import os
from pathlib import Path
import pytest
import App
from engine.appc.save_load import SaveLoadManager
from engine.core.game import Game, Episode, Mission, _set_current_game


@pytest.fixture
def saves_under_tmp(tmp_path, monkeypatch):
    """Re-anchor the saves/ directory to a tmp path so tests don't pollute
    the project's saves/ directory."""
    monkeypatch.chdir(tmp_path)
    yield tmp_path / "saves"


@pytest.fixture
def fresh_game():
    """Set up a Game/Episode/Mission graph for save/load round-trip tests."""
    mission = Mission()
    episode = Episode()
    episode.SetCurrentMission(mission)
    game = Game()
    game.SetCurrentEpisode(episode)
    _set_current_game(game)
    yield game, episode, mission
    _set_current_game(None)


# ── SaveLoadManager directly ─────────────────────────────────────────────────

def test_save_to_file_writes_json_under_saves(saves_under_tmp, fresh_game):
    mgr = SaveLoadManager()
    rc = mgr.SaveToFile("saves\\QuickSav.BCS")
    assert rc == 1
    assert (saves_under_tmp / "QuickSav.BCS").exists()


def test_save_to_file_handles_unix_slashes(saves_under_tmp, fresh_game):
    mgr = SaveLoadManager()
    rc = mgr.SaveToFile("saves//Captain-Picard.BCS")
    assert rc == 1
    assert (saves_under_tmp / "Captain-Picard.BCS").exists()


def test_save_to_file_records_save_filename(saves_under_tmp, fresh_game):
    mgr = SaveLoadManager()
    mgr.SaveToFile("saves/X.BCS")
    out = mgr.GetSaveFilename()
    assert out == "saves/X.BCS"
    assert out.GetCString() == "saves/X.BCS"


def test_load_from_missing_file_returns_zero(saves_under_tmp, fresh_game):
    mgr = SaveLoadManager()
    assert mgr.LoadFromFile("saves/NoSuch.BCS") == 0


def test_save_load_round_trip_restores_captain_name(saves_under_tmp, fresh_game):
    mgr = SaveLoadManager()
    App.g_kUtopiaModule.SetCaptainName("Janeway")
    App.g_kUtopiaModule.SetCurrentFriendlyFire(42.5)
    mgr.SaveToFile("saves/RoundTrip.BCS")

    # Mutate state so the load has something to restore over
    App.g_kUtopiaModule.SetCaptainName("Sisko")
    App.g_kUtopiaModule.SetCurrentFriendlyFire(0.0)
    assert App.g_kUtopiaModule.GetCaptainName() == "Sisko"

    rc = mgr.LoadFromFile("saves/RoundTrip.BCS")
    assert rc == 1
    assert App.g_kUtopiaModule.GetCaptainName() == "Janeway"
    assert App.g_kUtopiaModule.GetCurrentFriendlyFire() == 42.5

    # Reset for later tests.
    App.g_kUtopiaModule.SetCaptainName("Picard")
    App.g_kUtopiaModule.SetCurrentFriendlyFire(0.0)


def test_save_load_round_trip_restores_var_manager(saves_under_tmp, fresh_game):
    mgr = SaveLoadManager()
    App.g_kVarManager.DeleteAllVariables()
    App.g_kVarManager.SetFloatVariable("global", "PlayedTutorial", 1.0)
    App.g_kVarManager.SetStringVariable("Options", "MissionOverride", "E1M2")
    mgr.SaveToFile("saves/Vars.BCS")

    App.g_kVarManager.DeleteAllVariables()
    assert App.g_kVarManager.GetFloatVariable("global", "PlayedTutorial") == 0.0

    mgr.LoadFromFile("saves/Vars.BCS")
    assert App.g_kVarManager.GetFloatVariable("global", "PlayedTutorial") == 1.0
    assert App.g_kVarManager.GetStringVariable("Options", "MissionOverride") == "E1M2"
    App.g_kVarManager.DeleteAllVariables()


def test_save_load_round_trip_restores_difficulty_multipliers(saves_under_tmp, fresh_game):
    from engine.core import game as game_mod
    mgr = SaveLoadManager()
    App.Game_SetDifficultyMultipliers(1.5, 1.2, 1.0, 0.7, 0.85, 0.95)
    mgr.SaveToFile("saves/Diff.BCS")

    game_mod.Game_SetDefaultDifficultyMultipliers()
    assert App.Game_GetOffensiveDifficultyMultiplier() == 1.0

    mgr.LoadFromFile("saves/Diff.BCS")
    assert App.Game_GetOffensiveDifficultyMultiplier() == 1.2  # MEDIUM index
    assert App.Game_GetDefensiveDifficultyMultiplier() == 0.85
    game_mod.Game_SetDefaultDifficultyMultipliers()


# ── Mission state ────────────────────────────────────────────────────────────

def test_save_mission_state_returns_zero_when_no_mission_module(saves_under_tmp, fresh_game):
    mgr = SaveLoadManager()
    # Stub tracker is not set to a mission name → empty string → fail.
    App._stub_tracker._mission = None
    assert mgr.SaveMissionState() == 0


def test_save_and_load_mission_state_round_trip(saves_under_tmp, fresh_game):
    mgr = SaveLoadManager()
    _, _, mission = fresh_game

    # Populate group memberships.
    mission.GetFriendlyGroup().AddName("Enterprise")
    mission.GetEnemyGroup().AddName("Galor1")
    mission.GetEnemyGroup().AddName("Galor2")

    App._stub_tracker._mission = "Maelstrom.Episode1.E1M1.E1M1"
    try:
        assert mgr.SaveMissionState() == 1

        # Wipe groups; LoadMissionState should restore them.
        mission.GetFriendlyGroup().RemoveAllNames()
        mission.GetEnemyGroup().RemoveAllNames()

        rc = mgr.LoadMissionState("Maelstrom.Episode1.E1M1.E1M1")
        assert rc == 1
        assert mission.GetFriendlyGroup().GetNumActiveObjects() == 1
        assert mission.GetEnemyGroup().GetNumActiveObjects() == 2
    finally:
        App._stub_tracker._mission = None


def test_load_mission_state_unknown_module_returns_zero(saves_under_tmp, fresh_game):
    mgr = SaveLoadManager()
    assert mgr.LoadMissionState("nope.NoSuch.Mission") == 0


# ── Filename queue ───────────────────────────────────────────────────────────

def test_set_load_from_filename_round_trip(saves_under_tmp):
    mgr = SaveLoadManager()
    mgr.SetLoadFromFileName("saves/Q.BCS")
    out = mgr.GetLoadFilename()
    assert out == "saves/Q.BCS"
    assert out.GetCString() == "saves/Q.BCS"


def test_internal_load_filename_used_when_external_unset(saves_under_tmp):
    mgr = SaveLoadManager()
    mgr.SetInternalLoadFileName("saves/internal.BCS")
    assert mgr.GetLoadFilename() == "saves/internal.BCS"


def test_external_load_filename_takes_precedence_over_internal(saves_under_tmp):
    mgr = SaveLoadManager()
    mgr.SetInternalLoadFileName("internal.BCS")
    mgr.SetLoadFromFileName("external.BCS")
    assert mgr.GetLoadFilename() == "external.BCS"


# ── App namespace integration ────────────────────────────────────────────────

def test_app_utopia_module_save_to_file_is_wired(saves_under_tmp, fresh_game):
    """SDK pattern: App.g_kUtopiaModule.SaveToFile(filename)."""
    rc = App.g_kUtopiaModule.SaveToFile("saves/AppWired.BCS")
    assert rc == 1
    assert (saves_under_tmp / "AppWired.BCS").exists()


def test_app_utopia_module_load_mission_state_is_wired(saves_under_tmp, fresh_game):
    """SDK pattern: MissionLib.TryLoadMission delegates to LoadMissionState."""
    assert App.g_kUtopiaModule.LoadMissionState("nope.unknown") == 0


def test_app_save_load_writes_real_json_file(saves_under_tmp, fresh_game):
    """Verify the on-disk format is JSON we can inspect."""
    App.g_kUtopiaModule.SetCaptainName("Riker")
    App.g_kUtopiaModule.SaveToFile("saves/JSONShape.BCS")
    raw = (saves_under_tmp / "JSONShape.BCS").read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert parsed["format_version"] == 1
    assert parsed["utopia"]["captain_name"] == "Riker"
    App.g_kUtopiaModule.SetCaptainName("Picard")
