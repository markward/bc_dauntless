import App
from engine.core import game as game_mod


def test_default_offensive_multiplier_is_one():
    game_mod.Game_SetDefaultDifficultyMultipliers()
    assert App.Game_GetOffensiveDifficultyMultiplier() == 1.0


def test_default_defensive_multiplier_is_one():
    game_mod.Game_SetDefaultDifficultyMultipliers()
    assert App.Game_GetDefensiveDifficultyMultiplier() == 1.0


def test_set_difficulty_multipliers_round_trip_at_medium():
    """Game_GetDifficulty() returns 1 (MEDIUM) — accessors must read index 1."""
    App.Game_SetDifficultyMultipliers(1.5, 1.2, 1.0, 0.7, 0.85, 0.95)
    assert App.Game_GetOffensiveDifficultyMultiplier() == 1.2
    assert App.Game_GetDefensiveDifficultyMultiplier() == 0.85
    game_mod.Game_SetDefaultDifficultyMultipliers()


def test_set_difficulty_multipliers_accepts_six_floats():
    """E8M2 etc. call with 6 positional floats — must not raise."""
    App.Game_SetDifficultyMultipliers(1.5, 1.5, 1.0, 1.0, 0.8, 0.8)
    game_mod.Game_SetDefaultDifficultyMultipliers()


def test_set_default_resets_to_one():
    App.Game_SetDifficultyMultipliers(2.0, 2.0, 2.0, 0.5, 0.5, 0.5)
    game_mod.Game_SetDefaultDifficultyMultipliers()
    assert App.Game_GetOffensiveDifficultyMultiplier() == 1.0
    assert App.Game_GetDefensiveDifficultyMultiplier() == 1.0
