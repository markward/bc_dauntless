"""The helm calls out an impending collision.

`Bridge/HelmMenuHandlers.CollisionAlertCheck` runs on a 5 s LOW-priority
process and sweeps every object within `12 + 10*speed` GU of the player,
classifying each with DoPlanetCheck / DoShipCheck / DoObjectCheck. On a hit it
either has the helm officer speak a `CollisionAlert*` line or plays the
`CollisionAlertSound` alarm.

That sweep had never run: `ProximityManager.GetNextObject` was a hardcoded
`return None`, so the `while pObject != None` loop exited before its first
iteration and the alert was unreachable. Restoring the walk (1127d987) makes it
live, which means these bridge voice lines can fire in-game for the first time.

This test drives the real SDK function against a real scene and asserts an
alarm is actually raised, so the newly-live path is covered rather than assumed
to work. The no-collision case is asserted too — an implementation that alarmed
unconditionally would pass the first assertion alone, and a 5-second klaxon
loop on a clear course is worse than silence.
"""
import pytest


@pytest.fixture
def helm_scene(monkeypatch):
    monkeypatch.setenv("OPEN_STBC_HOST_HEADLESS", "1")

    from tools import mission_harness
    mission_harness.setup_sdk()

    import App
    import MissionLib
    import loadspacehelper
    from engine.core.game import Game, Episode, Mission, _set_current_game

    game, ep, mission = Game(), Episode(), Mission()
    ep.SetCurrentMission(mission)
    game.SetCurrentEpisode(ep)
    _set_current_game(game)

    import Systems.QuickBattle.QuickBattleRegion
    Systems.QuickBattle.QuickBattleRegion.Initialize()
    pSet = App.g_kSetManager.GetSet("QuickBattleRegion")

    player = MissionLib.CreatePlayerShip("Sovereign", pSet, "Player", "")
    player.SetTranslateXYZ(0.0, 0.0, 0.0)
    player.UpdateNodeOnly()
    if player.GetRadius() <= 0.0:
        player.SetRadius(4.0)

    # CollisionAlertCheck bails unless the Captain is flying, the ship is
    # moving, and the tactical view (not the bridge) is up.
    MissionLib.g_sPlayerShipController = "Captain"
    velocity = App.TGPoint3()
    velocity.SetXYZ(0.0, 3.0, 0.0)          # +Y is model forward
    player.SetVelocity(velocity)

    top = App.TopWindow_GetTopWindow()
    monkeypatch.setattr(type(top), "IsBridgeVisible", lambda self: 0, raising=False)
    monkeypatch.setattr(type(top), "IsCutsceneMode", lambda self: 0, raising=False)

    # The alert is rate-limited off two module globals, and CollisionAlertCheck
    # returns immediately while BOTH windows are shut. They start at 0 and
    # headless game time is 0, so at t=0 everything is throttled. Backdating
    # them opens both windows without depending on a settable clock.
    import Bridge.HelmMenuHandlers as helm
    helm.g_fLastCollisionAlertTime = -1000.0
    helm.g_fLastCollisionAlarmTime = -1000.0

    # Assert the preconditions instead of hoping. CollisionAlertCheck has eight
    # early returns before it reaches the proximity sweep; any one of them
    # silently turns this whole file into a test that asserts nothing.
    assert App.CharacterClass_IsCollisionAlertEnabled()
    assert MissionLib.GetPlayer() is player
    assert not top.IsBridgeVisible(), "bridge visible -- Helm has the wheel, sweep skipped"
    assert not top.IsCutsceneMode()
    assert player.GetVelocityTG().Length() >= 0.05
    assert not player.IsDocked()
    assert MissionLib.GetPlayerShipController() == "Captain"

    yield helm, player, pSet
    _set_current_game(None)


@pytest.fixture
def alarms(monkeypatch):
    """Record every alert the SDK raises, by either route."""
    import App

    raised = []
    real_sound = App.TGSoundAction_Create
    real_action = App.CharacterAction_Create

    def sound(name, *a, **k):
        raised.append(("sound", name))
        return real_sound(name, *a, **k)

    def action(pChar, eType, line=None, *a, **k):
        if line is not None and str(line).startswith("CollisionAlert"):
            raised.append(("speak", str(line)))
        return real_action(pChar, eType, line, *a, **k)

    monkeypatch.setattr(App, "TGSoundAction_Create", sound)
    monkeypatch.setattr(App, "CharacterAction_Create", action)
    return raised


def test_the_helm_raises_an_alarm_on_a_collision_course(helm_scene, alarms):
    import App
    import loadspacehelper

    helm, player, pSet = helm_scene

    # Dead ahead and close: inside the 12 + 10*speed = 42 GU sweep, and well
    # inside DoShipCheck's 40 GU "worry" distance with a dot product of 1.0.
    blocker = loadspacehelper.CreateShip("Galaxy", pSet, "Blocker", "")
    assert not App.IsNull(blocker)
    blocker.SetTranslateXYZ(0.0, 20.0, 0.0)
    blocker.UpdateNodeOnly()
    if blocker.GetRadius() <= 0.0:
        blocker.SetRadius(4.0)

    helm.CollisionAlertCheck(0.0)

    assert alarms, (
        "the helm said nothing with a ship 20 GU dead ahead — the proximity "
        "sweep in CollisionAlertCheck found nothing to check"
    )


def test_the_helm_stays_quiet_on_a_clear_course(helm_scene, alarms):
    """Nothing within the sweep, so no alarm. Guards the test above against
    passing on an implementation that always alarms."""
    import App
    import loadspacehelper

    helm, player, pSet = helm_scene

    far = loadspacehelper.CreateShip("Galaxy", pSet, "FarAway", "")
    assert not App.IsNull(far)
    far.SetTranslateXYZ(0.0, 5000.0, 0.0)
    far.UpdateNodeOnly()
    if far.GetRadius() <= 0.0:
        far.SetRadius(4.0)

    helm.CollisionAlertCheck(0.0)

    assert not alarms, f"spurious collision alarm on a clear course: {alarms}"
