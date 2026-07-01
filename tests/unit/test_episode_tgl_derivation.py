"""Episode-TGL path derivation + goal-label localization.

The dev picker loads a mission directly, skipping BC's Game.LoadEpisode ->
Episode.Initialize cascade that would SetDatabase the episode TGL. Without it,
goals fall back to raw string ids (E1DestroyDebrisGoal) instead of localized
text (Clear Debris). host_loop._init_episode_context restores just the DB by
deriving its path.
"""
from pathlib import Path

import pytest

from engine.host_loop import _episode_tgl_path, _init_episode_context
from engine.core.game import Episode

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("mission, expected", [
    ("Maelstrom.Episode1.E1M2.E1M2", "data/TGL/Maelstrom/Episode 1/Episode1.tgl"),
    ("Maelstrom.Episode2.E2M2.E2M2", "data/TGL/Maelstrom/Episode 2/Episode2.tgl"),
    ("Maelstrom.Episode10.E10M1.E10M1",
     "data/TGL/Maelstrom/Episode 10/Episode10.tgl"),
])
def test_episode_tgl_path_derivation(mission, expected):
    assert _episode_tgl_path(mission) == expected


def test_episode_tgl_path_none_for_short_names():
    assert _episode_tgl_path("SoloModule") is None
    assert _episode_tgl_path("A.B") is None


def test_init_episode_context_never_raises_on_missing_tgl():
    """A family/episode whose TGL doesn't exist must degrade silently (goals
    then fall back to raw ids), never raise into the mission load."""
    ep = Episode()
    _init_episode_context(ep, "Nonexistent.Episode9.X9M9.X9M9")  # must not raise


@pytest.mark.skipif(
    not (_PROJECT_ROOT / "game" / "data" / "TGL" / "Maelstrom" / "Episode 1"
         / "Episode1.tgl").exists(),
    reason="requires the gitignored BC game/ install (episode TGL)",
)
def test_init_episode_context_localizes_goal_label():
    ep = Episode()
    _init_episode_context(ep, "Maelstrom.Episode1.E1M2.E1M2")
    ep.RegisterGoal("E1DestroyDebrisGoal")
    # The Episode DB is now set; _goal_label resolves the localized text.
    assert ep._goal_label("E1DestroyDebrisGoal") == "Clear Debris"
