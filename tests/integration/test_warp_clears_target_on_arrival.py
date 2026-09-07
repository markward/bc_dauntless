"""Warping must not leave the player targeting a ship in the system it left.

FIELD REPORT: target a ship, order Tactical "Destroy", then warp to another
system. In the new system the reticle and the tracking camera stay welded to
the old ship, which the target list cannot even list -- it is still sitting in
the torn-down source set -- so the player can neither select it nor cycle away
from it. Without the tactical order the target drops normally.

THE CHAIN (each step verified by the stack trace this test's first version
captured):

  1. Warp engage runs `warp._ClearTargetsAction` -> `_clear_all_targets` ->
     `player.SetTarget(None)`.
  2. `ShipClass.SetTarget` posts ET_TARGET_WAS_CHANGED SYNCHRONOUSLY. Its SDK
     broadcast handler `Bridge.TacticalMenuHandlers.TargetChanged`
     (registered at TacticalMenuHandlers.py:404) calls `UpdateOrders(0)` ->
     `StartAI`, which rebuilds the player's AI from the STILL-LIVE "Destroy"
     order. The rebuild reads `pPlayer.GetTarget()`, which is now None, so the
     new tree's `SelectTarget` starts with `sCurrentTarget = None`.
  3. One frame later the player is STILL IN THE SOURCE SET -- the flythrough
     align phase lasts seconds -- so that `SelectTarget.Update` re-picks the
     enemy, sees a change from None, and pushes it back through its
     replacement hook `AutoTargetChange` (AI/Preprocessors.py:1376). Player
     AIs use `CallFunctionInsteadOfSetTargets`, so this hook IS the push path.
  4. `AutoTargetChange` obeys the "Target At Will" button, which
     `CreateTacticalMenu` builds `SetChosen(1)` -- ON BY DEFAULT
     (TacticalMenuHandlers.py:379). So it calls `pPlayer.SetTarget("enemy")`,
     which resolves in the source set. The target is back, and nothing in the
     rest of the warp clears it again.

BC DOES NOT HAVE THIS RACE, because BC clears the target on ARRIVAL, not at
engage: `Bridge/HelmMenuHandlers.PostWarpEnableMenu:939-948`, scheduled at the
end of BC's warp sequence (WarpSequence.py:324), with the comment "Clear the
player's target, and the persistent target info in the target menu, so that we
don't retarget the same thing when we return to the old set (or if the object
follows us to the new set)." We had ported that function's menu-enable half as
`_EnableHelmMenuAction` and left the target-clearing half behind; our
engage-time clear is an addition of ours, and on its own it loses the race.

The fix is the missing half, not a new gate: an arrival-time clear, which is
immune by construction rather than by timing -- once the player is in the
destination set, every name the AI can push resolves there or resolves to
nothing. Notably it does NOT touch "Target At Will", so Felix resumes
auto-targeting in the new system exactly as BC does.

Both tests drive the REAL SDK menu state (`g_iOrderState` and friends), not
patched accessors, so `GetHighLevelOrder`/`StartAI` run exactly as they do in
game.
"""
import sys

import App
import LoadBridge
from engine.appc import warp
from engine.appc.ai_driver import tick_ai
from engine.appc.sets import SetClass_Create
from engine.appc.ships import ShipClass
from engine.appc.subsystems import (
    HullSubsystem, ImpulseEngineSubsystem, PhaserSystem, SensorSubsystem,
    TorpedoAmmoType, TorpedoSystem,
)
from engine.appc.target_menu import _reset_target_menu_singleton
from engine.appc.tg_ui import st_widgets
from engine.appc.windows import TacticalControlWindow
from engine.core.game import Episode, Game, Mission, _set_current_game
from engine.sdk_ui.widgets.ship_display import _reset_create_count as _reset_ship_display


def _mk_ship(name):
    s = ShipClass()
    s.SetName(name)
    s._hull = HullSubsystem("H"); s._hull.SetMaxCondition(1000.0)
    s._impulse_engine_subsystem = ImpulseEngineSubsystem("IES")
    s._impulse_engine_subsystem.SetMaxSpeed(120.0)
    s._sensor_subsystem = SensorSubsystem("Sensors")
    phasers = PhaserSystem("P"); phasers._parent_ship = s
    s.SetPhaserSystem(phasers)
    torps = TorpedoSystem("T"); torps._parent_ship = s
    torps._ammo_by_slot = {0: TorpedoAmmoType("Photon", launch_speed=19.0)}
    s.SetTorpedoSystem(torps)
    return s


def _bridge_world():
    """A loaded GalaxyBridge over a fresh Game/Episode/Mission.

    Mirrors tests/integration/test_bridge_menu_activation.py::_fresh_world --
    the real Bridge/*MenuHandlers must run, because the buttons and handlers
    they register ARE the subject here.
    """
    TacticalControlWindow._instance = None
    _reset_target_menu_singleton()
    st_widgets._reset_module_state()
    _reset_ship_display()
    App.g_kSetManager._sets.clear()
    App.g_kEventManager._broadcast_handlers.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()
    App.g_kTimerManager._timers.clear()
    App.g_kTimerManager._time = 0.0
    game = Game(); episode = Episode(); mission = Mission()
    episode.SetCurrentMission(mission)
    game.SetCurrentEpisode(episode)
    _set_current_game(game)
    for name in list(sys.modules):
        mod = sys.modules[name]
        if name.startswith("Bridge.") and "StubModule" in type(mod).__name__:
            sys.modules.pop(name)
    LoadBridge.Load("GalaxyBridge")
    # Boot state for two SDK process-globals LoadBridge does not reset. Both
    # are load-bearing here, so leaving a previous test's values in place
    # silently changes what this file measures: with the controller already
    # "Tactical", `TargetChanged` unchooses Target At Will the moment the
    # player picks a target, closing the gate before the warp ever runs and
    # masking the bug entirely.
    import Bridge.TacticalMenuHandlers as TMH
    import MissionLib
    MissionLib.g_sPlayerShipController = None
    TMH.g_iAutoTargetChange = 0
    return mission


def _target_at_will_button():
    menu = TacticalControlWindow.GetInstance().GetTacticalMenu()
    db = App.g_kLocalizationManager.Load("data/TGL/Bridge Menus.tgl")
    label = db.GetString("Target At Will")
    App.g_kLocalizationManager.Unload(db)
    return App.STButton_Cast(menu.GetButtonW(label))


def _combat_scene(mission):
    """Player + enemy in a source set, player targeting the enemy."""
    src = SetClass_Create(); App.g_kSetManager.AddSet(src, "Src")
    player = _mk_ship("player"); src.AddObjectToSet(player, "player")
    App.Game_SetCurrentPlayer(player)
    enemy = _mk_ship("enemy"); enemy.SetTranslateXYZ(0.0, 150.0, 0.0)
    src.AddObjectToSet(enemy, "enemy")
    mission.GetEnemyGroup().AddName("enemy")
    player.SetTarget(enemy)
    return src, player, enemy


def _order_tactical_to_destroy(player):
    """What clicking Tactical -> Destroy does: set the menu state, then let
    UpdateOrders build and install the player AI (StartAI)."""
    import Bridge.TacticalMenuHandlers as TMH
    # StartAI refuses attack orders with cold weapons (the "NeedPower" line).
    player.GetTorpedoSystem().TurnOn()
    player.GetPhaserSystem().TurnOn()
    TMH.g_iOrderState = 0        # OrderDestroy
    TMH.g_iTacticState = 0       # TacticAtWill
    TMH.g_iManeuverState = 0     # ManeuverAtWill
    TMH.UpdateOrders()
    assert TMH.GetHighLevelOrder() == "OrderDestroy"
    assert player.GetAI() is not None, "Felix's attack AI was not installed"


def _dest_module():
    import types
    mod = types.ModuleType("FakeSys.Dst")

    def Initialize():
        s = SetClass_Create(); App.g_kSetManager.AddSet(s, "Dst")
        wp = App.Waypoint_Create("Player Start", "Dst", None)
        wp.SetTranslateXYZ(42.0, 0.0, 0.0); wp.Update(0)
    mod.Initialize = Initialize
    sys.modules["FakeSys.Dst"] = mod
    return "FakeSys.Dst"


def test_warp_spine_clears_targets_again_on_arrival():
    """The warp sequence must carry BC's ARRIVAL clear, not just our
    engage-time one. Asserted on the built sequence so the requirement is
    pinned even if the align/transit timing that exposes it ever changes."""
    mission = _bridge_world()
    _src, player, _enemy = _combat_scene(mission)
    _order_tactical_to_destroy(player)

    warp.configure_warp_hooks(realize=None, teardown=None)
    warp.configure_warp_vfx(enabled=lambda: True,
                            start=lambda *a, **k: None,
                            stop=lambda: None,
                            vantage_of=lambda key: (1.0, 2.0, 3.0))
    seq = warp.WarpSequence_Create(player, _dest_module(), placement="Player Start")
    kinds = [type(step.action).__name__ for step in seq._steps]
    assert "_ClearTargetsAction" in kinds
    assert "_ArrivalClearTargetsAction" in kinds, (
        "no arrival-time clear in the warp spine: %s" % (kinds,))
    assert (kinds.index("_ArrivalClearTargetsAction")
            > kinds.index("_ClearTargetsAction"))


def test_felix_still_auto_targets_after_the_warp():
    """The fix must not cost Felix his auto-targeting. BC's arrival clear does
    not touch "Target At Will"; a fix that unchose it would silently stop
    Tactical picking targets in the new system for the rest of the session."""
    mission = _bridge_world()
    _src, player, _enemy = _combat_scene(mission)
    _order_tactical_to_destroy(player)

    warp._clear_all_targets(player)

    assert player.GetTarget() is None
    assert _target_at_will_button().IsChosen() == 1


def test_target_does_not_survive_warp_under_tactical_attack_orders():
    """The reported symptom, end to end: after the warp the player must not
    still be targeting a ship left behind in the source system."""
    mission = _bridge_world()
    src, player, enemy = _combat_scene(mission)
    _order_tactical_to_destroy(player)
    # The precondition that makes the bug possible: the player picked the
    # target before giving orders, so nothing has unchosen Target At Will.
    assert _target_at_will_button().IsChosen() == 1

    warp.configure_warp_hooks(realize=None, teardown=None)
    warp.configure_warp_vfx(enabled=lambda: True,
                            start=lambda *a, **k: None,
                            stop=lambda: None,
                            vantage_of=lambda key: (1.0, 2.0, 3.0))

    button = App.STWarpButton_CreateW("Warp")
    App.SortedRegionMenu_SetWarpButton(button)
    button.SetDestination(_dest_module())
    warp.execute_warp(button)

    # 20 s of frames: covers the align phase (player still in the source set,
    # which is when the AI gets its chance to re-target) and the transit.
    for _ in range(1200):
        App.g_kTimerManager.tick(1.0 / 60.0)
        ai = player.GetAI()
        if ai is not None:
            tick_ai(ai, App.g_kTimerManager._time)

    assert player.GetContainingSet().GetName() == "Dst"     # the warp happened
    assert enemy.GetContainingSet() is not player.GetContainingSet()
    assert player.GetTarget() is None, (
        "player arrived still targeting %r, which is in the source system and "
        "so cannot be selected or cycled away from"
        % (player.GetTarget().GetName(),))


def test_target_stays_clear_for_the_whole_transit_not_just_arrival():
    """The target must be gone from the moment warp engages, not merely by the
    time we arrive.

    Live report 2026-09-07: with only the arrival clear, the reticle, the
    target ship-display panel and the range/speed readouts stayed on the old
    ship for the WHOLE align+transit — Felix's rebuilt AI re-targeted one frame
    after the engage clear (see `_ArrivalClearTargetsAction`) and nothing
    dislodged it until arrival. Sampling every frame, not just the end, is the
    point of this test: an end-state assertion passes on exactly the behaviour
    that was reported as wrong.
    """
    mission = _bridge_world()
    _src, player, _enemy = _combat_scene(mission)
    _order_tactical_to_destroy(player)

    warp.configure_warp_hooks(realize=None, teardown=None)
    warp.configure_warp_vfx(enabled=lambda: True,
                            start=lambda *a, **k: None,
                            stop=lambda: None,
                            vantage_of=lambda key: (1.0, 2.0, 3.0))

    button = App.STWarpButton_CreateW("Warp")
    App.SortedRegionMenu_SetWarpButton(button)
    button.SetDestination(_dest_module())
    warp.execute_warp(button)

    reacquired = []
    for i in range(1200):
        App.g_kTimerManager.tick(1.0 / 60.0)
        ai = player.GetAI()
        if ai is not None:
            tick_ai(ai, App.g_kTimerManager._time)
        target = player.GetTarget()
        if target is not None:
            reacquired.append((i, target.GetName()))

    assert not reacquired, (
        "target was back on screen for %d of 1200 warp frames (first at frame "
        "%d, %r) — it must never reappear once warp engages"
        % (len(reacquired), reacquired[0][0], reacquired[0][1]))


def test_felix_resumes_when_you_pick_a_target_in_the_new_system():
    """Standing the AI down for the warp must not retire Felix for the session.

    `g_iOrderState` is left alone and the controller is reset to None (not
    "Helm"), so the player's first target pick in the destination system runs
    TargetChanged -> UpdateOrders -> StartAI and the attack order resumes
    against the new contact. Asserted, not assumed: park the controller on
    "Helm" instead and `GetOrderString` returns None here, silently retiring
    Tactical until something else resets it.
    """
    mission = _bridge_world()
    _src, player, _enemy = _combat_scene(mission)
    _order_tactical_to_destroy(player)

    warp.configure_warp_hooks(realize=None, teardown=None)
    warp.configure_warp_vfx(enabled=lambda: True,
                            start=lambda *a, **k: None,
                            stop=lambda: None,
                            vantage_of=lambda key: (1.0, 2.0, 3.0))
    button = App.STWarpButton_CreateW("Warp")
    App.SortedRegionMenu_SetWarpButton(button)
    button.SetDestination(_dest_module())
    warp.execute_warp(button)
    for _ in range(1200):
        App.g_kTimerManager.tick(1.0 / 60.0)
        ai = player.GetAI()
        if ai is not None:
            tick_ai(ai, App.g_kTimerManager._time)

    assert player.GetAI() is None, "precondition: Felix stood down for the warp"

    # A hostile in the destination system, and the player targets it.
    destination = player.GetContainingSet()
    newcomer = _mk_ship("raider")
    newcomer.SetTranslateXYZ(0.0, 120.0, 0.0)
    destination.AddObjectToSet(newcomer, "raider")
    mission.GetEnemyGroup().AddName("raider")
    player.SetTarget(newcomer)

    assert player.GetAI() is not None, (
        "Felix never came back: the attack order is still set but no AI was "
        "rebuilt when the player picked a target in the new system")
