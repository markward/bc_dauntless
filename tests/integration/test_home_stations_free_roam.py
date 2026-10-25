"""Free roam: warp to Starbase 12, find the station, dock, get repaired.

Free roam is the SDK Quick Battle the game boots into: no objectives, and the
player warps anywhere. The station is not put there by any mission -- the
region hook places it when BC's Starbase12 module builds the set on arrival --
and the Dock button is BC's own (Starbase12_S.SetupGraffSet, run from its
EnterSet broadcast).
"""
import pytest

pytest.importorskip("_dauntless_host")

from tests.helpers import headless_mission as hm  # noqa: E402
from tests.integration.test_quickbattle_setup_e2e import world  # noqa: E402,F401

_DEST = "Systems.Starbase12.Starbase12"


def _player():
    import App
    return App.Game_GetCurrentGame().GetPlayer()


def _dock_button():
    import Bridge.BridgeUtils
    return Bridge.BridgeUtils.GetDockButton()


def _warp_to_starbase_12():
    player = _player()
    assert player.GetContainingSet().GetName() != "Starbase12"
    button = hm.the_warp_button()
    assert button is not None
    hm.plot_course(button, _DEST)
    hm.warp_and_wait(button, player)
    return player


def test_warping_to_starbase_12_finds_the_station_and_the_dock_button(world):
    from engine.systems import home_stations as hs
    dock = _dock_button()
    assert dock is not None
    assert not dock.IsEnabled()
    player = _warp_to_starbase_12()
    pSet = player.GetContainingSet()
    assert pSet.GetName() == "Starbase12"
    station = pSet.GetObject("Starbase 12")
    assert station is not None
    assert hs.home_station_of(station) is not None
    hm.tick(1.0)
    assert _dock_button().IsEnabled()


def test_docking_repairs_the_player(world):
    """The ship's own repair alone needs ~450 s to mend half a Galaxy hull, so
    reaching full within the 300 s bound is the dock's doing."""
    import Systems.Starbase12.Starbase12_S as sb12
    player = _warp_to_starbase_12()
    hm.tick(1.0)
    hull = player.GetHull()
    full = hull.GetMaxCondition()
    hull.SetCondition(full * 0.5)
    assert hull.GetCondition() < full
    sb12.DockStarbase()
    assert player.GetAI() is not None
    hm.tick_until(lambda: hull.GetCondition() >= full, bound_s=300.0)


def test_free_roam_starts_with_repairs_enabled(world):
    """A campaign mission may turn Starbase 12's repairs off and give Graff
    its own docking action (E7M1 does both); Starbase12_S is a cached module,
    so those globals outlive the mission. Free roam starts with BC's
    defaults."""
    _hl, controller, _panel, _QB = world
    import App
    import Systems.Starbase12.Starbase12_S as sb12
    action = App.TGSequence_Create()
    sb12.StarbaseRepairsEnabled(0)
    sb12.SetGraffDockingAction(action, 0)
    assert sb12.g_idGraffAction == action.GetObjID() != App.NULL_ID
    controller.loader.load_quickbattle()
    assert sb12.g_bRepairsEnabled == 1
    assert sb12.__dict__.get("g_idGraffAction", App.NULL_ID) == App.NULL_ID
    assert sb12.__dict__.get("g_bFadeGraffEnd", 1) == 1
