"""Slice E preview: load AI.Compound.NonFedAttack via _SDKFinder,
call CreateAI(ship), tick once. Marked xfail because NonFedAttack
splices in PlainAI sub-graphs (TorpRun, StationaryAttack, TurnToAttack,
SweepPhasers, ICOMove, WarpBeforeDeath, EvadeTorps) that don't have
headless ports yet.

When Slice D lands those sub-graphs and Slice E wires NonFedAttack's
CreateAI surface, this test should flip to passing — at which point
remove the xfail marker."""
import pytest

import App
from engine.appc.ai import BuilderAI
from engine.appc.ai_driver import tick_ai
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, PhaserSystem, TorpedoSystem
from engine.core.game import Game, Episode, Mission, _set_current_game


@pytest.fixture
def game_context():
    """Mission stack with a non-empty script for sMissionModuleName."""
    mission = Mission()
    mission.SetScript("tests.integration.test_non_fed_attack_smoke")
    episode = Episode()
    episode.SetCurrentMission(mission)
    game = Game()
    game.SetCurrentEpisode(episode)
    _set_current_game(game)
    yield
    _set_current_game(None)


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


@pytest.mark.xfail(
    reason=(
        "Awaits Slice D (PlainAI sub-graphs: TorpRun, StationaryAttack, "
        "TurnToAttack, SweepPhasers, ICOMove, WarpBeforeDeath, EvadeTorps) "
        "and Slice E (NonFedAttack/FedAttack CreateAI assembly)."
    ),
    strict=False,
)
def test_non_fed_attack_create_ai_smoke(game_context):
    """When NonFedAttack lands its sub-graphs, CreateAI should activate
    cleanly. Today it explodes because at least one sub-graph isn't
    importable."""
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours.SetTranslateXYZ(0, 0, 0)
    ours._hull = HullSubsystem("H"); ours._hull.SetMaxCondition(1000.0)
    ours._phaser = PhaserSystem("P"); ours._phaser._parent_ship = ours
    ours._torp = TorpedoSystem("T"); ours._torp._parent_ship = ours
    pSet.AddObjectToSet(ours, "Attacker")
    target = ShipClass(); target.SetTranslateXYZ(0, 200, 0)
    target._hull = HullSubsystem("H"); target._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(target, "Target")

    import AI.Compound.NonFedAttack as non_fed_attack
    builder = non_fed_attack.CreateAI(ours, "Target")
    assert isinstance(builder, BuilderAI)

    tick_ai(builder, game_time=0.01)
    assert builder._activated is True, (
        f"BuilderAI activation failed: {builder._activation_error}"
    )
    assert builder._activation_failed is False
