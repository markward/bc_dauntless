"""Root-cause reproduction for 'AI awful at torpedoes': an AI ship running
the real NonFedAttack tree must set its ship Target (via SelectTarget ->
pShip.SetTarget) so that torpedoes home instead of dumbfiring forward.

Currently FAILS: CodeAI._has_focus is never set True, so HasFocus() == 0,
so SelectTarget's `if self.bSetShipTarget and self.pCodeAI.HasFocus()` gate
(AI/Preprocessors.py:1257) never calls pShip.SetTarget. The AI ship's
GetTarget() stays None and every torpedo dumbfires.
"""
import pytest

import App
from engine.appc.ai import BuilderAI
from engine.appc.ai_driver import tick_ai
from engine.appc.ships import ShipClass
from engine.appc.subsystems import (
    HullSubsystem, PhaserSystem, TorpedoSystem, TorpedoAmmoType,
    ImpulseEngineSubsystem, SensorSubsystem,
)
from engine.core.game import Game, Episode, Mission, _set_current_game


@pytest.fixture
def game_context():
    mission = Mission()
    mission.SetScript("tests.integration.test_ai_sets_ship_target")
    episode = Episode()
    episode.SetCurrentMission(mission)
    game = Game()
    game.SetCurrentEpisode(episode)
    _set_current_game(game)
    yield
    _set_current_game(None)


@pytest.fixture(autouse=True)
def _isolate():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()
    yield
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


def test_ai_sets_ship_target_for_torpedo_homing(game_context):
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet

    ours = ShipClass(); ours.SetTranslateXYZ(0, 0, 0)
    ours._hull = HullSubsystem("H"); ours._hull.SetMaxCondition(1000.0)
    ours._impulse_engine_subsystem = ImpulseEngineSubsystem("IES")
    ours._impulse_engine_subsystem.SetMaxSpeed(120.0)
    ours._sensor_subsystem = SensorSubsystem("Sensors")
    ours._phaser = PhaserSystem("P"); ours._phaser._parent_ship = ours
    ours._torpedo_system = TorpedoSystem("T"); ours._torpedo_system._parent_ship = ours
    ours._torpedo_system._ammo_by_slot = {0: TorpedoAmmoType("Photon", launch_speed=19.0)}
    pSet.AddObjectToSet(ours, "Attacker")

    target = ShipClass(); target.SetTranslateXYZ(0, 150, 0)
    target._hull = HullSubsystem("H"); target._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(target, "Target")

    import AI.Compound.NonFedAttack as non_fed_attack
    builder = non_fed_attack.CreateAI(ours, "Target")
    assert isinstance(builder, BuilderAI)

    # Tick enough for SelectTarget to run and choose "Target".
    for i in range(40):
        tick_ai(builder, game_time=0.01 + i * 0.25)

    got = ours.GetTarget()
    assert got is target, (
        f"AI ship should lock its Target so torps home; GetTarget()={got!r}"
    )


def test_select_target_node_gains_focus_when_dispatched(game_context):
    """The focus surrogate: a PreprocessingAI reached on the active dispatch
    path must report HasFocus()==1, so SelectTarget's change-path
    pShip.SetTarget (Preprocessors.py:1257) fires when the AI switches
    targets mid-combat. Before the fix _has_focus was initialised False and
    never set, so HasFocus() was always 0."""
    from engine.appc.ai import PreprocessingAI

    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours.SetTranslateXYZ(0, 0, 0)
    ours._hull = HullSubsystem("H"); ours._hull.SetMaxCondition(1000.0)
    ours._impulse_engine_subsystem = ImpulseEngineSubsystem("IES")
    ours._impulse_engine_subsystem.SetMaxSpeed(120.0)
    ours._sensor_subsystem = SensorSubsystem("Sensors")
    ours._phaser = PhaserSystem("P"); ours._phaser._parent_ship = ours
    ours._torpedo_system = TorpedoSystem("T"); ours._torpedo_system._parent_ship = ours
    ours._torpedo_system._ammo_by_slot = {0: TorpedoAmmoType("Photon", launch_speed=19.0)}
    pSet.AddObjectToSet(ours, "Attacker")
    target = ShipClass(); target.SetTranslateXYZ(0, 150, 0)
    target._hull = HullSubsystem("H"); target._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(target, "Target")

    import AI.Compound.NonFedAttack as non_fed_attack
    builder = non_fed_attack.CreateAI(ours, "Target")
    for i in range(20):
        tick_ai(builder, game_time=0.01 + i * 0.25)

    # At least one dispatched PreprocessingAI node holds focus.
    def _walk(node, seen):
        if node is None or id(node) in seen:
            return False
        seen.add(id(node))
        if isinstance(node, PreprocessingAI) and node.HasFocus():
            return True
        for attr in ("_contained_ai",):
            if _walk(getattr(node, attr, None), seen):
                return True
        for child in getattr(node, "_ais", []) or []:
            sub = child[1] if isinstance(child, tuple) else child
            if _walk(sub, seen):
                return True
        return False

    assert _walk(builder, set()), "a dispatched PreprocessingAI should report HasFocus()==1"
