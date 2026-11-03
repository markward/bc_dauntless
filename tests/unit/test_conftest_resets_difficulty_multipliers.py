"""The per-test reset must put the difficulty multipliers back.

Game_SetDifficultyMultipliers is global game state that a mission sets at
init (E2M2.py:155 sets the defensive multipliers to 0.75). E1M2 never sets
its own, so after a test that loaded E2M2 (test_damage_queue_order's E2M2
splash) E1M2's player was built with a 0.75 defensive multiplier: its
shield generator started at 9000 of 12000, exactly its disabled threshold,
and E1M2.CheckShields skipped Brex's "LoweringShields"
(test_e1m2_supply_transfer[True], main-merge gate 2026-11-03). In play the
two missions are only reached through a new game. This plants the state by
hand -- no mission booted -- and shows the reset clears it.
"""
import App

from tests.conftest import _reset_leakable_engine_globals


def test_the_reset_restores_the_default_difficulty_multipliers():
    App.Game_SetDifficultyMultipliers(1.0, 1.2, 0.9, 1.0, 0.75, 0.75)
    _reset_leakable_engine_globals()
    App.Game_SetDifficulty(App.Game.MEDIUM)
    assert App.Game_GetOffensiveDifficultyMultiplier() == 1.0
    assert App.Game_GetDefensiveDifficultyMultiplier() == 1.0
