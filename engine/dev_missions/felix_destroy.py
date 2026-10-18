"""Developer "Felix: Destroy" mission -- perf baseline B2, run unattended.

Five Birds of Prey -- the player's and four AI wingmen in a V behind it --
against one enemy Sovereign ahead. A few seconds in, the player targets the
Sovereign and Felix is ordered to Destroy through the Orders pane's own
Destroy button, so Bridge.TacticalMenuHandlers runs Maneuver -> UpdateOrders
-> StartAI exactly as for a player click. The wingmen and the Sovereign run
the SDK's BasicAttack against the other side, as in combat_stress.

With DAUNTLESS_DEV_AUTOQUIT=1 the run quits POST_DEATH_S after the first ship
is destroyed (ET_OBJECT_DESTROYED, i.e. after its death sequence), or after
TIME_CAP_S if nobody dies. Without it the mission plays on, so it is safe to
load from the dev mission picker.

    DAUNTLESS_MISSION=engine.dev_missions.felix_destroy DAUNTLESS_DEV_AUTOQUIT=1 \\
        DAUNTLESS_DEV_VIEW=exterior \\
        DAUNTLESS_PROFILE_FRAMES=100000000 ./build/dauntless --developer

Each step prints a `[felix_destroy]` line, which marks it in a profiler log.
See docs/engine/perf-register.md (B2).
"""
import math
import os

import App
import MissionLib
import loadspacehelper

from engine import dev_scripted_run

PLAYER_SHIP = "BirdOfPrey"
WINGMAN_SHIP = "BirdOfPrey"
ENEMY_SHIP = "Sovereign"
# A V behind the player, a little over one hull diameter between neighbours.
WINGMAN_POSITIONS = ((-32.0, -8.0, 0.0), (-16.0, -4.0, 0.0),
                     (16.0, -4.0, 0.0), (32.0, -8.0, 0.0))
# Ahead, inside weapons range, so the fight starts in seconds rather than
# after a long approach.
ENEMY_POSITION = (0.0, 40.0, 0.0)
# Seeded only in headless runs, where nothing realizes a model (as in
# combat_stress, whose _NOMINAL_HULL_RADIUS_GU this matches).
NOMINAL_HULL_RADIUS_GU = 4.0
# Long enough for the bridge, its menus and the AI to be up.
ORDER_DELAY_S = 3.0
# After ET_OBJECT_DESTROYED the death sequence is already over; a few seconds
# more catches the wreck settling and the target-list churn.
POST_DEATH_S = 5.0
TIME_CAP_S = 180.0

_ATTACK_AI_MODULE = "AI.Compound.BasicAttack"
_AI_DIFFICULTY = 2

_enemy_names = []
_first_death = None
_first_explosion = None


def autoquit_enabled(environ=None) -> bool:
    environ = os.environ if environ is None else environ
    return environ.get("DAUNTLESS_DEV_AUTOQUIT", "").strip() == "1"


def wants_exterior_view(environ=None) -> bool:
    """DAUNTLESS_DEV_VIEW=exterior: watch the fight from outside, as the
    player did in the hand-run B2 captures (the same switch as B1's)."""
    environ = os.environ if environ is None else environ
    return environ.get("DAUNTLESS_DEV_VIEW", "").strip() == "exterior"


def reset_run_state() -> None:
    global _first_death, _first_explosion
    _first_death = None
    _first_explosion = None


def _log(msg: str) -> None:
    print("[felix_destroy] " + msg, flush=True)


def _headless() -> bool:
    return bool(os.environ.get("OPEN_STBC_HOST_HEADLESS"))


def _seed_radius(pShip) -> None:
    if not _headless():
        return
    try:
        if pShip.GetRadius() <= 0.0:
            pShip.SetRadius(NOMINAL_HULL_RADIUS_GU)
    except Exception:
        pass


def PreLoadAssets(pMission):
    import importlib
    for name in (PLAYER_SHIP, ENEMY_SHIP):
        try:
            mod = importlib.import_module("ships." + name)
            if hasattr(mod, "PreLoadModel"):
                mod.PreLoadModel()
        except Exception:
            pass


def _attach_attack_ai(pShip, pTargets):
    """BasicAttack against `pTargets`, wrapped in AvoidObstacles exactly as
    combat_stress (and the SDK's Fleet doctrines) do."""
    import importlib
    from engine.dev_missions import combat_stress
    pAI = importlib.import_module(_ATTACK_AI_MODULE).CreateAI(
        pShip, pTargets, Difficulty=_AI_DIFFICULTY,
        FollowTargetThroughWarp=1, UseCloaking=1)
    if pAI is None:
        raise RuntimeError("felix_destroy: %s.CreateAI returned None"
                           % _ATTACK_AI_MODULE)
    if combat_stress.avoidance_enabled():
        import AI.Preprocessors
        pScript = AI.Preprocessors.AvoidObstacles()
        pAvoid = App.PreprocessingAI_Create(pShip, "AvoidObstacles")
        pAvoid.SetInterruptable(1)
        pAvoid.SetPreprocessingMethod(pScript, "Update")
        pAvoid.SetContainedAI(pAI)
        pAI = pAvoid
    pShip.SetAI(pAI, 0, 0)


def Initialize(pMission):
    global _enemy_names
    reset_run_state()
    dev_scripted_run.clear_quit_request()
    App.Game_SetDifficultyMultipliers(1.0, 1.0, 1.0, 1.0, 1.0, 1.0)

    import LoadBridge
    LoadBridge.Load("SovereignBridge")

    import Systems.QuickBattle.QuickBattleRegion
    Systems.QuickBattle.QuickBattleRegion.Initialize()
    pSet = App.g_kSetManager.GetSet("QuickBattleRegion")

    pPlayer = MissionLib.CreatePlayerShip(PLAYER_SHIP, pSet, "Player", "")
    pPlayer.SetTranslateXYZ(0.0, 0.0, 0.0)
    pPlayer.UpdateNodeOnly()
    _seed_radius(pPlayer)

    pFriendlies = pMission.GetFriendlyGroup()
    pEnemies = pMission.GetEnemyGroup()
    pFriendlies.AddName("Player")

    def _spawn(ship_type, name, pos, group):
        pShip = loadspacehelper.CreateShip(ship_type, pSet, name, "")
        if App.IsNull(pShip):
            raise RuntimeError("felix_destroy: could not create %s" % name)
        pShip.SetTranslateXYZ(*pos)
        pShip.UpdateNodeOnly()
        _seed_radius(pShip)
        group.AddName(name)
        return pShip

    wingmen = [_spawn(WINGMAN_SHIP, "Wing-%d" % (i + 1), pos, pFriendlies)
               for i, pos in enumerate(WINGMAN_POSITIONS)]
    _enemy_names = ["Enemy-Sovereign"]
    enemy = _spawn(ENEMY_SHIP, _enemy_names[0], ENEMY_POSITION, pEnemies)

    # AI last, once every ship exists (see combat_stress).
    for pShip in wingmen:
        _attach_attack_ai(pShip, pEnemies)
    _attach_attack_ai(enemy, pFriendlies)

    try:
        pPlayer.SetAlertLevel(App.ShipClass.RED_ALERT)
    except Exception:
        pass

    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_OBJECT_EXPLODING, pMission, __name__ + ".ShipExploding")
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_OBJECT_DESTROYED, pMission, __name__ + ".ShipDestroyed")

    pSeq = App.TGSequence_Create()
    pSeq.AppendAction(App.TGScriptAction_Create(__name__, "OrderDestroyAction"),
                      ORDER_DELAY_S)
    pSeq.Play()

    if autoquit_enabled():
        dev_scripted_run.request_quit(TIME_CAP_S, "time cap, nobody died")
    _log("player %s + %d AI %s vs 1 %s; Destroy order in %.0f s; "
         "autoquit=%s (cap %.0f s)"
         % (PLAYER_SHIP, len(wingmen), WINGMAN_SHIP, ENEMY_SHIP,
            ORDER_DELAY_S, "on" if autoquit_enabled() else "off", TIME_CAP_S))


def _nearest(player, names):
    best, best_d = None, None
    for name in names:
        pSet = player.GetContainingSet() if hasattr(player, "GetContainingSet") else None
        ship = App.ShipClass_GetObject(pSet, name) if pSet is not None else None
        if ship is None or App.IsNull(ship):
            continue
        if hasattr(ship, "IsDead") and ship.IsDead():
            continue
        a, b = player.GetWorldLocation(), ship.GetWorldLocation()
        d = math.dist((a.x, a.y, a.z), (b.x, b.y, b.z))
        if best_d is None or d < best_d:
            best, best_d = ship, d
    return best


def issue_destroy_order(player, enemy_names):
    """Target the nearest live enemy and press Felix's Destroy button.

    Returns the target's name, or None when the order could not be issued
    (no live enemy, or no Destroy button on the Orders pane)."""
    target = _nearest(player, enemy_names)
    if target is None:
        _log("ERROR: no live enemy to target")
        return None
    player.SetTarget(target.GetName())

    import Bridge.TacticalMenuHandlers as TMH
    pDatabase = App.g_kLocalizationManager.Load("data/TGL/Bridge Menus.tgl")
    label = str(pDatabase.GetString("OrderDestroy"))
    App.g_kLocalizationManager.Unload(pDatabase)

    pane = getattr(TMH, "g_pOrdersStatusUIPane", None)
    child = pane.GetFirstChild() if pane is not None else None
    while child is not None:
        if hasattr(child, "GetLabel") and str(child.GetLabel()) == label:
            child.SendActivationEvent()
            return target.GetName()
        child = pane.GetNextChild(child)
    _log("ERROR: no '%s' button on the Orders pane; Felix has no order" % label)
    return None


def OrderDestroyAction(pAction):
    pPlayer = App.Game_GetCurrentPlayer()
    if pPlayer is None:
        _log("ERROR: no player ship at order time")
        return 0
    target = issue_destroy_order(pPlayer, _enemy_names)
    if target is not None:
        _log("Felix ordered to Destroy, target %s" % target)
    if wants_exterior_view():
        App.TopWindow_GetTopWindow().ForceTacticalVisible()
        _log("view exterior")
    return 0


def _event_ship_name(pEvent):
    try:
        obj = pEvent.GetDestination()
        return obj.GetName() if obj is not None else "?"
    except Exception:
        return "?"


def ShipExploding(pObject, pEvent):
    global _first_explosion
    if _first_explosion is None:
        _first_explosion = _event_ship_name(pEvent)
        _log("first ship exploding: %s" % _first_explosion)


def ShipDestroyed(pObject, pEvent):
    global _first_death
    if _first_death is not None:
        return
    _first_death = _event_ship_name(pEvent)
    _log("first ship destroyed: %s" % _first_death)
    if autoquit_enabled():
        dev_scripted_run.request_quit(
            POST_DEATH_S, "%.0f s after %s was destroyed"
            % (POST_DEATH_S, _first_death))
