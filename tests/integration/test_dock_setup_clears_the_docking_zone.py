"""SetupDockPositions must clear the docking zone instead of crashing.

`AI/Compound/DockWithStarbase.py:52` walks every object within 300 GU of the
"Docking Entry" placement and shoves anything that is neither the docking ship
nor the starbase out of the way, so the docking cutscene doesn't fly through a
bystander.

That walk had never run: `ProximityManager.GetNextObject` was a hardcoded
`return None`. Restoring it (commit 1127d987) turned the loop body live for the
first time and immediately hit line 94:

    if vDiff.SqrLength < 0.5:          # no parens -- a bound METHOD vs a float

which Python 2 evaluated as False (numbers sort before non-numbers) and Python 3
raises TypeError on. So the fix converted a silent no-op into a crash on a live
gameplay path -- docking is scripted in E1M1 and E6M2.

Two things are asserted here, and the second is what makes the first meaningful:
the call completes, AND the bystander actually moved. A `SetupDockPositions`
that returned early without touching anything would satisfy the first alone --
which is exactly the state this was in before.
"""
import pytest


DOCK_CLEAR_RADIUS_GU = 300.0


@pytest.fixture
def docking_scene(monkeypatch):
    monkeypatch.setenv("OPEN_STBC_HOST_HEADLESS", "1")

    from tools import mission_harness
    mission_harness.setup_sdk()

    import App
    import loadspacehelper
    from engine.core.game import Game, Episode, Mission, _set_current_game
    from engine.appc.placement import PlacementObject

    game, ep, mission = Game(), Episode(), Mission()
    ep.SetCurrentMission(mission)
    game.SetCurrentEpisode(ep)
    _set_current_game(game)

    import Systems.QuickBattle.QuickBattleRegion
    Systems.QuickBattle.QuickBattleRegion.Initialize()
    pSet = App.g_kSetManager.GetSet("QuickBattleRegion")

    starbase = loadspacehelper.CreateShip("CardStarbase", pSet, "SB", "")
    ship = loadspacehelper.CreateShip("Galaxy", pSet, "Me", "")
    bystander = loadspacehelper.CreateShip("Keldon", pSet, "Bystander", "")
    for o in (starbase, ship, bystander):
        assert not App.IsNull(o)
        if o.GetRadius() <= 0.0:
            o.SetRadius(4.0)

    entry = PlacementObject()
    entry.SetName("Docking Entry")
    entry.SetTranslateXYZ(0.0, 0.0, 0.0)
    pSet.AddObjectToSet(entry, "Docking Entry")

    # Well inside the 300 GU sweep, so the loop body must run.
    bystander.SetTranslateXYZ(50.0, 0.0, 0.0)
    bystander.UpdateNodeOnly()

    yield ship, bystander, entry
    _set_current_game(None)


def _distance(a, b):
    pa, pb = a.GetWorldLocation(), b.GetWorldLocation()
    return ((pa.GetX() - pb.GetX()) ** 2
            + (pa.GetY() - pb.GetY()) ** 2
            + (pa.GetZ() - pb.GetZ()) ** 2) ** 0.5


def test_setup_dock_positions_moves_a_bystander_clear(docking_scene):
    import AI.Compound.DockWithStarbase as dock

    ship, bystander, entry = docking_scene
    assert _distance(bystander, entry) < DOCK_CLEAR_RADIUS_GU   # not vacuous

    dock.SetupDockPositions(ship, "SB")

    assert _distance(bystander, entry) >= DOCK_CLEAR_RADIUS_GU, (
        "the bystander was left sitting in the docking zone -- the proximity "
        "walk found nothing, or the loop bailed before moving it"
    )
