"""The straight-line chase of tests/integration/test_pursuers_avoid_each_other.py
(six Keldons on QuickBattle's AI construction, BasicAttack inside an
AvoidObstacles PreprocessingAI, converging on a player flying a straight
line), shared with the native-AI A/B (tests/helpers/native_ai_ab.py's
``pursuers_converge``): a scene where avoidance really fires.

``build(mp)`` sets the scene up and returns ``(GameLoop(), player,
pursuers)``; the caller clears the game with
``engine.core.game._set_current_game(None)``. ``fly_player(player)`` is the
per-tick straight-line move."""

SHIPS = 6
SPREAD_GU = 14.0
START_BEHIND_GU = 120.0
PLAYER_SPEED_GUPS = 5.0
NOMINAL_RADIUS_GU = 4.0


def build(mp):
    mp.setenv("OPEN_STBC_HOST_HEADLESS", "1")

    from tools import mission_harness
    mission_harness.setup_sdk()

    import App
    import MissionLib
    import loadspacehelper
    from engine.core.game import Game, Episode, Mission, _set_current_game
    from engine.core.loop import GameLoop

    game, ep, mission = Game(), Episode(), Mission()
    ep.SetCurrentMission(mission)
    game.SetCurrentEpisode(ep)
    _set_current_game(game)

    import Systems.QuickBattle.QuickBattleRegion
    Systems.QuickBattle.QuickBattleRegion.Initialize()
    pSet = App.g_kSetManager.GetSet("QuickBattleRegion")

    # Headless has no realize step, so GetRadius() reads 0 -- which removes a
    # ship from avoidance entirely (personal space is radius * multiplier) and
    # would make this test pass vacuously. Same nominal hull as combat_stress.
    player = MissionLib.CreatePlayerShip("Sovereign", pSet, "Player", "")
    player.SetTranslateXYZ(0.0, 0.0, 0.0)
    player.UpdateNodeOnly()
    if player.GetRadius() <= 0.0:
        player.SetRadius(NOMINAL_RADIUS_GU)
    mission.GetFriendlyGroup().AddName("Player")

    pursuers = []
    for i in range(SHIPS):
        name = "Enemy-%d" % (i + 1)
        s = loadspacehelper.CreateShip("Keldon", pSet, name, "")
        if App.IsNull(s):
            continue
        s.SetTranslateXYZ((i - (SHIPS - 1) / 2.0) * SPREAD_GU,
                          -START_BEHIND_GU,
                          ((i % 3) - 1) * SPREAD_GU * 0.5)
        s.UpdateNodeOnly()
        if s.GetRadius() <= 0.0:
            s.SetRadius(NOMINAL_RADIUS_GU)
        mission.GetEnemyGroup().AddName(name)
        pursuers.append(s)
    assert len(pursuers) == SHIPS

    # QuickBattleAI's own construction: BasicAttack (which dispatches a Keldon
    # to NonFedAttack by species) inside an AvoidObstacles PreprocessingAI.
    import AI.Preprocessors
    import AI.Compound.BasicAttack
    for s in pursuers:
        pAI = AI.Compound.BasicAttack.CreateAI(
            s, mission.GetFriendlyGroup(), Difficulty=0.5,
            FollowTargetThroughWarp=1, UseCloaking=1)
        assert pAI is not None
        script = AI.Preprocessors.AvoidObstacles()
        avoid = App.PreprocessingAI_Create(s, "AvoidObstacles")
        avoid.SetInterruptable(1)
        avoid.SetPreprocessingMethod(script, "Update")
        avoid.SetContainedAI(pAI)
        s.SetAI(avoid, 0, 0)

    evt = App.TGEvent()
    evt.SetEventType(App.ET_MISSION_START)
    evt.SetDestination(ep)
    App.g_kEventManager.AddEvent(evt)

    return GameLoop(), player, pursuers


def fly_player(player):
    """One tick of the player's constant-velocity line (+Y)."""
    import App
    p = player.GetWorldLocation()
    q = App.TGPoint3()
    q.SetXYZ(p.GetX(), p.GetY() + PLAYER_SPEED_GUPS / 60.0, p.GetZ())
    player.SetWorldLocation(q)
    player.UpdateNodeOnly()
