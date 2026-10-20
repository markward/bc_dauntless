"""A warp that arrives at its course clears the course.

FIELD REPORT (Mark, 2026-10-20): after warping to a star system the Helm
destination stayed set, so the Warp button stayed live and pressing it again
jumped to the same place.

Nothing in the engine ever cleared the warp button's destination once a warp
landed. The SDK never clears it either -- no script calls SetDestination(None)
on the warp button -- yet BridgeHandlers.HelmUpdateToolTip (:1409-1421) has a
``ClearStatus(3)`` branch for a button with no destination, so in BC the
field does go empty after a course is plotted; where the C++ cleared it is
not in the SDK (inferred, not measured).

The rule here: on the PLAYER's arrival, the course is cleared if it is still
the one the warp flew to. A course set while in transit (a mission handler,
the player browsing) is a new course and survives; an NPC's warp never
touches the player's button. The in-system dash follows the same rule and is
covered in tests/unit/test_dash_set_course.py.
"""
import sys
import types

import pytest

import App
from engine.appc import warp
from engine.appc.actions import TGAction
from engine.appc.sets import SetClass_Create
from engine.appc.tg_ui import st_widgets
from engine.appc.tg_ui.st_widgets import STWarpButton

DEST = "FakeCourse.Dest"
OTHER = "FakeCourse.Other"


def _make_set(name):
    s = SetClass_Create()
    App.g_kSetManager.AddSet(s, name)
    wp = App.Waypoint_Create("Player Start", name, None)
    wp.SetTranslateXYZ(10.0, 20.0, 30.0)
    wp.Update(0)
    return s


@pytest.fixture
def world(monkeypatch):
    App.g_kSetManager._sets.clear()
    warp.configure_warp_hooks(realize=None, teardown=None)
    warp.configure_warp_vfx(start=None, stop=None, enabled=None,
                            vantage_of=None)
    src = _make_set("Home")
    player = App.ShipClass_Create()
    player.SetName("player")
    src.AddObjectToSet(player, "player")
    monkeypatch.setattr(App, "Game_GetCurrentPlayer", lambda: player)
    for mod_name in (DEST, OTHER):
        mod = types.ModuleType(mod_name)
        set_name = mod_name.rsplit(".", 1)[1]
        mod.Initialize = (lambda n=set_name: _make_set(n))
        monkeypatch.setitem(sys.modules, mod_name, mod)
    button = STWarpButton("Warp")
    button.SetEnabled()
    st_widgets.SortedRegionMenu_SetWarpButton(button)
    yield types.SimpleNamespace(player=player, src=src, button=button)
    st_widgets._reset_module_state()
    App.g_kSetManager._sets.clear()


def test_arriving_clears_the_players_course(world):
    world.button.set_player_destination(DEST)
    assert world.button.IsEnabled()

    warp.execute_warp(world.button)

    assert App.g_kSetManager.GetSet("Dest").GetObject("player") is world.player
    assert not world.button.GetDestination()
    assert world.button.IsEnabled() == 0, (
        "the Warp button is still live after arriving -- pressing it again "
        "jumps to the same place")


def test_arriving_at_a_missions_destination_clears_its_latch_too(world):
    """A mission's SetDestination (E3M2.py:2124) writes the course AND the
    mission latch the star map's objective marker reads; once the player is
    there, neither still points at it."""
    world.button.SetDestination(DEST)

    warp.execute_warp(world.button)

    assert not world.button.GetDestination()
    assert not world.button.get_mission_destination()


def test_a_mission_latch_elsewhere_survives_the_players_own_warp(world):
    world.button.SetDestination(OTHER)          # the mission's objective
    world.button.set_player_destination(DEST)   # the player goes elsewhere

    warp.execute_warp(world.button)

    assert not world.button.GetDestination()
    assert world.button.get_mission_destination() == OTHER


class _SetCourse(TGAction):
    """A queued in-transit action that plots a new course."""

    def __init__(self, button, dest):
        super().__init__()
        self._button = button
        self._dest = dest

    def _do_play(self):
        self._button.set_player_destination(self._dest)


def test_a_course_set_during_the_transit_survives_arrival(world):
    world.button.set_player_destination(DEST)
    world.button.AddActionDuringWarp(_SetCourse(world.button, OTHER))

    warp.execute_warp(world.button)

    assert App.g_kSetManager.GetSet("Dest").GetObject("player") is world.player
    assert world.button.GetDestination() == OTHER


def test_an_npcs_warp_leaves_the_players_course_alone(world):
    world.button.set_player_destination(DEST)
    npc = App.ShipClass_Create()
    npc.SetName("npc")
    world.src.AddObjectToSet(npc, "npc")

    warp.WarpSequence_Create(npc, DEST, 0.0, "Player Start").Play()

    assert App.g_kSetManager.GetSet("Dest").GetObject("npc") is npc
    assert world.button.GetDestination() == DEST
