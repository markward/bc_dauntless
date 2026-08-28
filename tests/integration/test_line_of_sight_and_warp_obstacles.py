"""The two live consumers of GetLineIntersectObjects.

`ProximityManager.GetLineIntersectObjects` was a hardcoded `return ()` — the
second Phase-1 placeholder alongside `GetNextObject`'s `return None`. Fixing
GetNextObject alone left every caller of this one still dead.

THREE SDK call sites are genuinely live and are revived by implementing it:

    Conditions/ConditionInLineOfSight.py:128  — covered here
    MissionLib.py:4930  GrabWarpObstaclesFromSet — covered here
    AI/PlainAI/Intercept.py:269  AdjustDestinationForLargeObstacles

A FOURTH, `AI/Preprocessors.py:373` (FireScript.TargetVisible), is NOT revived
and must not be: the SDK authors disabled it themselves. `TargetVisible` opens
with

    # For now, skip this check.
    self.bTargetVisible = 1
    return self.bTargetVisible

so its whole body — including the `for eType in ( App.CT_TORPEDO ):` typo that
would raise on any occluder — is unreachable in BC too. That early return is
why the typo could ship. Do not "fix" either of them.
"""
import pytest


@pytest.fixture
def line_scene(monkeypatch):
    monkeypatch.setenv("OPEN_STBC_HOST_HEADLESS", "1")

    from tools import mission_harness
    mission_harness.setup_sdk()

    import App
    import loadspacehelper
    from engine.core.game import Game, Episode, Mission, _set_current_game

    game, ep, mission = Game(), Episode(), Mission()
    ep.SetCurrentMission(mission)
    game.SetCurrentEpisode(ep)
    _set_current_game(game)

    import Systems.QuickBattle.QuickBattleRegion
    Systems.QuickBattle.QuickBattleRegion.Initialize()
    pSet = App.g_kSetManager.GetSet("QuickBattleRegion")

    ships = {}
    for name, (x, y, z) in (("Alpha", (0.0, 0.0, 0.0)),
                            ("Omega", (0.0, 200.0, 0.0)),
                            ("Blocker", (0.0, 100.0, 0.0))):
        s = loadspacehelper.CreateShip("Galaxy", pSet, name, "")
        assert not App.IsNull(s)
        s.SetTranslateXYZ(x, y, z)
        s.UpdateNodeOnly()
        if s.GetRadius() <= 0.0:
            s.SetRadius(4.0)
        ships[name] = s

    yield pSet, ships
    _set_current_game(None)


# ── ConditionInLineOfSight ──────────────────────────────────────────────────

def _los_condition():
    import App
    return App.ConditionScript_Create(
        "Conditions.ConditionInLineOfSight", "ConditionInLineOfSight",
        "Alpha", "Omega", "Blocker")


def test_a_blocker_squarely_between_the_two_objects_blocks_line_of_sight(
        line_scene):
    cond = _los_condition()
    assert cond._instance is not None, cond._init_error

    assert cond.GetStatus() == 1, (
        "Blocker sits exactly halfway between Alpha and Omega and was not "
        "found on the line — GetLineIntersectObjects returned nothing"
    )


def test_line_of_sight_is_clear_once_the_blocker_moves_aside(line_scene):
    """Without this, the test above would pass on an implementation that
    reported every object as blocking."""
    pSet, ships = line_scene
    ships["Blocker"].SetTranslateXYZ(0.0, 100.0, 500.0)
    ships["Blocker"].UpdateNodeOnly()

    cond = _los_condition()
    assert cond._instance is not None, cond._init_error

    assert cond.GetStatus() == 0


# ── MissionLib.GrabWarpObstaclesFromSet ─────────────────────────────────────

def test_warp_obstacles_are_found_along_the_warp_path(line_scene):
    """AI/PlainAI/Warp.py:400 and FollowThroughWarp.py:276 steer around
    whatever this returns. It returned [] unconditionally."""
    import App
    import MissionLib

    pSet, ships = line_scene
    start, end = App.TGPoint3(), App.TGPoint3()
    start.SetXYZ(0.0, 0.0, 0.0)
    end.SetXYZ(0.0, 200.0, 0.0)

    obstacles = MissionLib.GrabWarpObstaclesFromSet(
        start, end, pSet, 4.0, 0, ships["Alpha"].GetObjID())

    names = {o[0].GetName() for o in obstacles}
    assert "Blocker" in names, (
        f"nothing on the warp path was reported as an obstacle (got {names})"
    )


def test_the_ignored_object_is_excluded_from_warp_obstacles(line_scene):
    """The warping ship passes its own id as idIgnore; reporting itself as an
    obstacle would make it dodge its own start point."""
    import App
    import MissionLib

    pSet, ships = line_scene
    start, end = App.TGPoint3(), App.TGPoint3()
    start.SetXYZ(0.0, 0.0, 0.0)
    end.SetXYZ(0.0, 200.0, 0.0)

    obstacles = MissionLib.GrabWarpObstaclesFromSet(
        start, end, pSet, 4.0, 0, ships["Alpha"].GetObjID())

    assert "Alpha" not in {o[0].GetName() for o in obstacles}


def test_a_clear_warp_path_reports_nothing(line_scene):
    import App
    import MissionLib

    pSet, ships = line_scene
    for name in ("Blocker", "Omega"):
        ships[name].SetTranslateXYZ(5000.0, 5000.0, 5000.0)
        ships[name].UpdateNodeOnly()

    start, end = App.TGPoint3(), App.TGPoint3()
    start.SetXYZ(0.0, 0.0, 0.0)
    end.SetXYZ(0.0, 200.0, 0.0)

    obstacles = MissionLib.GrabWarpObstaclesFromSet(
        start, end, pSet, 4.0, 0, ships["Alpha"].GetObjID())

    assert obstacles == []
