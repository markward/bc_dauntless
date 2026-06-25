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


def test_default_difficulty_is_medium():
    assert App.Game_GetDifficulty() == 1


def test_set_difficulty_round_trip():
    try:
        App.Game_SetDifficulty(0)
        assert App.Game_GetDifficulty() == 0
        App.Game_SetDifficulty(2)
        assert App.Game_GetDifficulty() == 2
    finally:
        App.Game_SetDifficulty(1)


def test_set_difficulty_clamps_out_of_range():
    try:
        App.Game_SetDifficulty(99)
        assert App.Game_GetDifficulty() == 2
        App.Game_SetDifficulty(-5)
        assert App.Game_GetDifficulty() == 0
    finally:
        App.Game_SetDifficulty(1)


def test_difficulty_drives_active_multiplier_index():
    """Game_GetDifficulty() selects which multiplier the accessors return."""
    App.Game_SetDifficultyMultipliers(1.5, 1.2, 1.0, 0.7, 0.85, 0.95)
    try:
        App.Game_SetDifficulty(0)
        assert App.Game_GetOffensiveDifficultyMultiplier() == 1.5
        App.Game_SetDifficulty(2)
        assert App.Game_GetDefensiveDifficultyMultiplier() == 0.95
    finally:
        App.Game_SetDifficulty(1)
        game_mod.Game_SetDefaultDifficultyMultipliers()
