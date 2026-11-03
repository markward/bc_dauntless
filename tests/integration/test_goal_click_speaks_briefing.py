"""Clicking an objective in the XO's Objectives menu has the XO say that
goal's briefing line, <goal id>Audio from the same database ("Head to
Starbase 12" -> E1HeadToStarbaseGoalAudio, "Sir, we should head to Starbase
12 to pick up the supplies."), to the Captain. The buttons used to carry no
event, so a click did nothing (user report 2026-11-03)."""
from tests.helpers import headless_mission

E1M1 = "Maelstrom.Episode1.E1M1.E1M1"


def test_clicking_a_goal_has_the_xo_say_its_briefing_line(monkeypatch):
    import App
    from engine.appc import ai, mission_goals
    said = []
    orig = ai.CharacterAction._queue_say_line

    def record(self):
        said.append((self._character.GetName(), self._detail, self._set_name))
        return orig(self)

    monkeypatch.setattr(ai.CharacterAction, "_queue_say_line", record)
    headless_mission.load(E1M1)
    episode = App.Game_GetCurrentGame().GetCurrentEpisode()
    assert episode.GetGoals() == ["E1HeadToStarbaseGoal"]
    button = mission_goals.objectives_submenu().GetButtonW(
        episode._goal_label("E1HeadToStarbaseGoal"))
    assert button is not None

    from engine.core.loop import GameLoop
    loop = GameLoop()
    before = len(said)
    button.SendActivationEvent()
    for _ in range(3):
        loop.tick()
    assert said[before:] == [("XO", "E1HeadToStarbaseGoalAudio", "Captain")]


def test_a_goal_with_no_briefing_line_says_nothing(monkeypatch):
    import App
    from engine.appc import ai, mission_goals
    said = []
    monkeypatch.setattr(ai.CharacterAction, "_queue_say_line",
                        lambda self: said.append(self._detail))
    headless_mission.load(E1M1)
    event = App.TGStringEvent_Create()
    event.SetString("NoSuchGoal")
    mission_goals.GoalClicked(mission_goals._xo(), event)
    assert said == []
