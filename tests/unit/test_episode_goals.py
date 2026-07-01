"""Episode goal registration + XO Objectives submenu wiring.

Before this, Episode had no RegisterGoal/RemoveGoal, so MissionLib.AddGoal ->
pEpisode.RegisterGoal fell through TGObject.__getattr__ to a silent _Stub and
every mission objective vanished. These tests pin the data model and the
best-effort submenu display.
"""
import App
import pytest

from engine.core.game import Episode, Mission
from engine.appc import mission_goals


def test_register_goal_tracks_on_episode():
    ep = Episode()
    ep.RegisterGoal("E2InvestigateSerrisGoal")
    ep.RegisterGoal("E2ScanSerris3Goal")
    assert ep.GetNumGoals() == 2
    assert ep.GetGoals() == ["E2InvestigateSerrisGoal", "E2ScanSerris3Goal"]


def test_register_goal_is_idempotent():
    ep = Episode()
    ep.RegisterGoal("G")
    ep.RegisterGoal("G")
    assert ep.GetGoals() == ["G"]


def test_remove_goal_drops_from_active_but_keeps_order_of_rest():
    ep = Episode()
    ep.RegisterGoal("A")
    ep.RegisterGoal("B")
    ep.RegisterGoal("C")
    ep.RemoveGoal("B")
    assert ep.GetGoals() == ["A", "C"]
    assert ep.GetNumGoals() == 3   # total registered, incl. disabled


def test_get_database_round_trips_a_prebuilt_db():
    ep = Episode()
    sentinel = object()
    assert ep.SetDatabase(sentinel) is sentinel
    assert ep.GetDatabase() is sentinel


def test_register_goal_does_not_raise_without_a_bridge():
    """Goal registration happens deep in mission Initialize; a missing bridge /
    XO menu must degrade to 'tracked but not shown', never throw."""
    App.g_kSetManager._sets.pop("bridge", None)
    ep = Episode()
    ep.RegisterGoal("SomeGoal")  # must not raise
    assert ep.GetGoals() == ["SomeGoal"]


class _FakeButton:
    def __init__(self, label):
        self.label = label
        self.enabled = True

    def SetDisabled(self, *a):
        self.enabled = False


class _FakeObjectivesMenu:
    def __init__(self):
        self.buttons: list = []

    def GetButtonW(self, label):
        for b in self.buttons:
            if b.label == label:
                return b
        return None


def test_add_and_disable_goal_button_via_submenu(monkeypatch):
    """add_goal_button adds once; disable_goal_button strikes it."""
    menu = _FakeObjectivesMenu()

    def _add_child(btn, *a):
        menu.buttons.append(btn)

    menu.AddChild = _add_child
    monkeypatch.setattr(mission_goals, "objectives_submenu", lambda: menu)
    monkeypatch.setattr(App, "STButton_CreateW", _FakeButton, raising=False)

    mission_goals.add_goal_button("Investigate Serris")
    mission_goals.add_goal_button("Investigate Serris")  # dedup
    assert [b.label for b in menu.buttons] == ["Investigate Serris"]

    mission_goals.disable_goal_button("Investigate Serris")
    assert menu.buttons[0].enabled is False


def test_goal_label_prefers_first_db_with_the_string():
    class _DB:
        def __init__(self, mapping):
            self._m = mapping

        def HasString(self, k):
            return k in self._m

        def GetString(self, k):
            return self._m[k]

    ep_db = _DB({"G": "Episode Text"})
    mission_db = _DB({"G": "Mission Text"})
    assert mission_goals.goal_label("G", ep_db, mission_db) == "Episode Text"
    assert mission_goals.goal_label("G", None, mission_db) == "Mission Text"
    assert mission_goals.goal_label("G", None, None) == "G"   # raw fallback
