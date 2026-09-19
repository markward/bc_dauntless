"""The player's tactical fire-control toggles (Manual Aim / Phasers Only /
Target At Will) reach the ship's FireScript only if the node's preprocessing
instance isinstance-matches App.OptimizedFireScript
(Bridge/TacticalMenuHandlers.py:1861, GetPlayerFiringAIScripts). Our wrapper
subclassed the SDK FireScript only, so g_lPlayerFireAIs was always empty and
the toggles were no-ops."""
import sys

import App
import LoadBridge
from engine.appc.ai import PreprocessingAI_Create
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


def test_bound_fire_script_is_an_optimized_fire_script():
    import AI.Preprocessors
    ship = ShipClass(); ship._hull = HullSubsystem("H"); ship._hull.SetMaxCondition(1000.0)
    node = PreprocessingAI_Create(ship, "Fire")
    node.SetPreprocessingMethod(AI.Preprocessors.FireScript("X"), "Update")
    inst = node.GetPreprocessingInstance()
    assert isinstance(inst, App.OptimizedFireScript)
    # And it still is the SDK class, with the control surface BC's binding lists.
    assert isinstance(inst, AI.Preprocessors.FireScript)
    for name in ("AddWeaponSystem", "RemoveAllWeaponSystems", "SetEnabled",
                 "HasSubsystemTargets", "IgnoreSubsystemTargets",
                 "RestoreSubsystemTargets"):
        assert callable(getattr(inst, name))


def test_other_preprocessors_are_not_optimized_fire_scripts():
    import AI.Preprocessors
    ship = ShipClass(); ship._hull = HullSubsystem("H"); ship._hull.SetMaxCondition(1000.0)
    node = PreprocessingAI_Create(ship, "Alert")
    node.SetPreprocessingMethod(AI.Preprocessors.AlertLevel(App.ShipClass.RED_ALERT), "Update")
    assert not isinstance(node.GetPreprocessingInstance(), App.OptimizedFireScript)


def test_fire_script_non_lethal_mro_is_trivial():
    """MRO sanity: the dynamic wrapper class sits in front of (SDK FireScript,
    OptimizedFireScript) with no diamond and no surprise resolution order --
    guards against a future refactor of `_non_lethal_class`'s `bases` tuple."""
    import AI.Preprocessors
    ship = ShipClass(); ship._hull = HullSubsystem("H"); ship._hull.SetMaxCondition(1000.0)
    node = PreprocessingAI_Create(ship, "Fire")
    node.SetPreprocessingMethod(AI.Preprocessors.FireScript("X"), "Update")
    inst = node.GetPreprocessingInstance()
    assert [c.__name__ for c in type(inst).__mro__] == [
        "FireScript_NonLethal", "FireScript", "OptimizedFireScript", "object",
    ]


def _mk_ship(name):
    """Same fixture shape as
    tests/integration/test_warp_clears_target_on_arrival.py::_mk_ship --
    powered weapon systems so StartAI's "NeedPower" gate does not refuse the
    attack order. Registers every subsystem through its real setter (which
    attaches the parent ship via ShipClass._attach_subsystem) rather than
    poking private attributes -- ``ship._hull`` is the one conventional
    exception (see the task brief)."""
    s = ShipClass()
    s.SetName(name)
    s._hull = HullSubsystem("H"); s._hull.SetMaxCondition(1000.0)
    impulse = ImpulseEngineSubsystem("IES")
    impulse.SetMaxSpeed(120.0)
    s.SetImpulseEngineSubsystem(impulse)
    s.SetSensorSubsystem(SensorSubsystem("Sensors"))
    s.SetPhaserSystem(PhaserSystem("P"))
    torps = TorpedoSystem("T")
    torps.AddAmmoType(TorpedoAmmoType("Photon", launch_speed=19.0))
    s.SetTorpedoSystem(torps)
    return s


def _bridge_world():
    """A loaded GalaxyBridge over a fresh Game/Episode/Mission.

    The real Bridge/TacticalMenuHandlers must run un-stubbed, because
    StartAI and GetPlayerFiringAIScripts -- the subject of this test -- live
    there and read real STButton state (Manual Aim / PhasersOnly / Target At
    Will) off a real TacticalControlWindow menu. Lifted verbatim from
    tests/integration/test_warp_clears_target_on_arrival.py::_bridge_world,
    which already proved this harness drives StartAI successfully.
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
    import Bridge.TacticalMenuHandlers as TMH
    import MissionLib
    MissionLib.g_sPlayerShipController = None
    TMH.g_iAutoTargetChange = 0
    return mission


def test_tactical_menu_collects_the_players_fire_scripts():
    """End to end through the REAL SDK path, not a hand-rolled reproduction
    of it: order Tactical "Disable" (which builds a DisableFreely tree --
    AI/Player/DisableFreely.py -- carrying an authored TargetSubsystems
    list), let StartAI (Bridge/TacticalMenuHandlers.py:1812-1861) run for
    real, and check its `isinstance(pScript, App.OptimizedFireScript)`
    discovery loop actually found the fire node. That isinstance check is
    the exact line this task fixes; before the fix g_lPlayerFireAIs stayed
    empty no matter what order was given.

    GetPlayerFiringAIScripts() (TacticalMenuHandlers.py:1787-1798) takes no
    args -- it reads the module global g_lPlayerFireAIs that StartAI just
    populated, per the SDK's own docstring ("This assumes the
    g_lPlayerFireAIs list has already been setup").
    """
    import AI.Preprocessors
    import Bridge.TacticalMenuHandlers as TMH

    mission = _bridge_world()
    src = SetClass_Create(); App.g_kSetManager.AddSet(src, "Src")
    player = _mk_ship("player"); src.AddObjectToSet(player, "player")
    App.Game_SetCurrentPlayer(player)
    enemy = _mk_ship("enemy"); enemy.SetTranslateXYZ(0.0, 150.0, 0.0)
    src.AddObjectToSet(enemy, "enemy")
    mission.GetEnemyGroup().AddName("enemy")
    player.SetTarget(enemy)

    player.GetTorpedoSystem().TurnOn()
    player.GetPhaserSystem().TurnOn()
    TMH.g_iOrderState = 1       # OrderDisable
    TMH.g_iTacticState = 0      # TacticAtWill
    TMH.g_iManeuverState = 0    # ManeuverAtWill
    TMH.UpdateOrders()
    assert TMH.GetHighLevelOrder() == "OrderDisable"
    assert player.GetAI() is not None, "Felix's attack AI was not installed"

    # THE bug this task fixes: before it, g_lPlayerFireAIs stayed empty
    # because the wrapper's isinstance check against App.OptimizedFireScript
    # (StartAI:1861) was always False, so the discovery loop found nothing.
    assert TMH.g_lPlayerFireAIs, (
        "StartAI's OptimizedFireScript discovery loop found no fire nodes")

    found = TMH.GetPlayerFiringAIScripts()
    assert found, "GetPlayerFiringAIScripts returned nothing"
    for script in found:
        assert isinstance(script, AI.Preprocessors.FireScript)
        assert isinstance(script, App.OptimizedFireScript)

    # DisableFreely authors a TargetSubsystems list at construction
    # (AI/Player/DisableFreely.py:263), so the script starts with subsystem
    # targets and the toggle round-trips true -> false.
    script = found[0]
    assert script.HasSubsystemTargets()
    script.IgnoreSubsystemTargets()
    assert not script.HasSubsystemTargets()
