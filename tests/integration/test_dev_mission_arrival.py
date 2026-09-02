"""Direct-loaded missions never "arrive", so their set-entry scripting is dead.

BC starts most missions by WARPING you in: the mission initializes, then the
warp places the player into its starting set, and that entry fires the
ET_ENTERED_SET handlers the mission registered moments earlier. 24 Maelstrom
missions hang opening beats off that event.

The dev picker loads a mission directly, with no warp. The mission's own
Initialize places the player BEFORE it registers the handler — E3M2 calls
CreateShips() at :155 and SetupEventHandlers() at :157 — so the placement
cannot fire it and the opening never runs. E3M2's Warbird scene, and with it
SetCourseForDustCloud, simply never happen.

_init_mission is the direct-load path, and already compensates for the
episode cascade BC's Game.LoadEpisode would have run. The arrival belongs
beside it, for the same reason.
"""
import sys
import types

import pytest

import App
from engine import dev_mode, host_loop


@pytest.fixture
def developer(monkeypatch):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)


def _e3m2_shaped_mission(name, arrivals):
    """A mission that places the player, THEN listens for its own arrival."""
    mod = types.ModuleType(name)

    def Handler(pObject, pEvent):
        ship = App.ShipClass_Cast(pEvent.GetDestination())
        if ship is not None and ship.GetName() == "player":
            arrivals.append(ship.GetContainingSet().GetName())

    def Initialize(mission):
        from engine.appc.sets import SetClass_Create
        s = SetClass_Create()
        App.g_kSetManager.AddSet(s, "Vesuvi6")
        player = App.ShipClass_Create()
        player.SetName("player")
        s.AddObjectToSet(player, "player")          # placed FIRST...
        App.Game_SetCurrentPlayer(player)
        App.g_kEventManager.AddBroadcastPythonFuncHandler(
            App.ET_ENTERED_SET, mission, name + ".Handler")   # ...listening AFTER

    mod.Initialize = Initialize
    mod.Handler = Handler
    sys.modules[name] = mod
    return mod


def test_the_player_arrives_after_initialize_so_set_entry_scripting_runs(
        developer):
    arrivals = []
    _e3m2_shaped_mission("FakeArrivalMission", arrivals)

    host_loop._init_mission("FakeArrivalMission")

    assert arrivals == ["Vesuvi6"]


def test_the_placement_during_initialize_still_does_not_fire_it(developer):
    """The arrival must come from the post-Initialize hook, not from the
    in-Initialize placement — otherwise this passes for the wrong reason and
    would keep passing if the hook were deleted."""
    arrivals = []
    _e3m2_shaped_mission("FakeArrivalMission2", arrivals)
    mod = sys.modules["FakeArrivalMission2"]

    mod.Initialize(object())            # Initialize ALONE
    assert arrivals == []               # nothing was listening yet


def test_production_is_untouched_without_developer_mode(monkeypatch):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: False)
    arrivals = []
    _e3m2_shaped_mission("FakeArrivalMission3", arrivals)

    host_loop._init_mission("FakeArrivalMission3")

    assert arrivals == []
