"""BC's campaign warp-in, end to end through the real SDK chain.

loadspacehelper.CreateShip(..., placement, 1) builds Actions.EffectScriptActions
.CreateEndWarpSequence (InitiateDewarp -> "Exit Warp" sound -> SetWarpStage x2
-> SetImpulse 0.2). The ship must flash in, slide in from the exit point to
the placement over 2 s, hold the placement's heading, then coast.
"""
import math

import App
import pytest

from engine.appc import warp_in_flash, warp_state
from tests.helpers import headless_mission as hm


def _dist(a, b):
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)


def _make_placement(pSet, name, player, ahead=300.0):
    pPlacement = App.PlacementObject_Create(name, pSet.GetName(), None)
    kFwd = player.GetWorldForwardTG()
    kLoc = player.GetWorldLocation()
    kLoc.x += kFwd.x * ahead
    kLoc.y += kFwd.y * ahead
    kLoc.z += kFwd.z * ahead
    toward = player.GetWorldLocation()
    toward.Subtract(kLoc)
    toward.Unitize()
    kUp = player.GetWorldUpTG()
    kUp.GetPerpendicularComponent(toward)
    kUp.Unitize()
    pPlacement.SetTranslate(kLoc)
    pPlacement.AlignToVectors(toward, kUp)
    pPlacement.UpdateNodeOnly()
    return pPlacement


@pytest.fixture
def world(monkeypatch):
    hm.load("Maelstrom.Episode1.E1M2.E1M2")
    warp_in_flash.reset()
    player = App.Game_GetCurrentPlayer()
    sounds = []
    from engine.appc import actions
    real = actions.TGSoundAction._do_play

    def spy(self):
        sounds.append((self._sound_name, self._node))
        return real(self)

    monkeypatch.setattr(actions.TGSoundAction, "_do_play", spy)
    return player.GetContainingSet(), player, sounds


def test_sdk_createship_with_flash_warps_in(world):
    import loadspacehelper
    pSet, player, sounds = world
    placement = _make_placement(pSet, "Test warp in", player)
    p_loc = placement.GetWorldLocation()
    p_fwd = placement.GetWorldRotation().GetCol(1)

    ship = loadspacehelper.CreateShip("Galor", pSet, "Test Galor",
                                      "Test warp in", 1)
    assert ship is not None
    flashes = warp_in_flash.active()
    assert len(flashes) == 1
    warp = ship.GetWarpEngineSubsystem()
    exit_pt = warp.GetWarpExitLocation()
    assert flashes[0].set_name == pSet.GetName()
    assert _dist(App.TGPoint3(*flashes[0].center), exit_pt) < 1e-3

    hm.tick(1.0)
    d_exit = _dist(ship.GetWorldLocation(), exit_pt)
    d_place = _dist(ship.GetWorldLocation(), p_loc)
    assert d_exit > 1e-3 and d_place > 1e-3
    fwd = ship.GetWorldRotation().GetCol(1)
    assert _dist(fwd, p_fwd) < 1e-3

    # Land: the tick the slide ends the ship is on the placement. (The SDK
    # coast, SetImpulse 0.2, then carries it on, so check at the landing.)
    hm.tick_until(lambda: not warp_state.is_arriving(ship), bound_s=3.0)
    assert _dist(ship.GetWorldLocation(), p_loc) < 1e-3
    hm.tick(2.5)
    assert warp_in_flash.active() == []
    assert warp.GetWarpState() == App.WarpEngineSubsystem.WES_NOT_WARPING
    assert not warp_state.is_arriving(ship)
    max_speed = ship.GetImpulseEngineSubsystem().GetAuthoredMaxSpeed()
    assert ship.GetSpeedSetpoint()[0] == pytest.approx(0.2 * max_speed, rel=1e-3)
    from engine.appc.weapon_subsystems import _dewarp_blocks_fire
    assert not _dewarp_blocks_fire(ship.GetPhaserSystem() or warp)
    assert [s for s, _ in sounds].count("Exit Warp") == 1


def test_sdk_createship_flash_without_placement(world):
    import loadspacehelper
    pSet, player, _ = world
    before = warp_in_flash.spawned_count()
    ship = loadspacehelper.CreateShip("Galor", pSet, "Test Galor 2", "", 1)
    hm.tick(0.05)
    assert warp_in_flash.spawned_count() == before + 1
    flashes = warp_in_flash.active()
    assert len(flashes) == 1
    assert _dist(App.TGPoint3(*flashes[0].center), ship.GetWorldLocation()) < 1e-3
    assert not warp_state.is_arriving(ship)
