"""A REAL Federation ship must re-engage after its target dies.

Guard for the dormant-PriorityList-child fix (2026-07-14).

`AI/Compound/FedAttack.py:1384` adds the `SelectTarget` PreprocessingAI as a
DIRECT child of the `FleeAttackOrFollow` PriorityListAI. When SelectTarget runs
out of targets it returns `PS_SKIP_DORMANT` (`AI/Preprocessors.py:1092`), which
maps to US_DORMANT.

Our `_tick_priority_list` used to treat US_DORMANT as a permanent skip, so the
node was never dispatched again and could never leave dormancy: an NPC whose
target died never engaged reinforcements that warped in.

BC does not latch dormancy. `PriorityListAI::Update` (0x00490340) sets the
per-entry skip byte ONLY on US_DONE; a US_DORMANT child keeps its entry and is
re-probed the next tick through the live `IsDormant` virtual (+0x38).

A unit test with fakes cannot reproduce this: the failure mode lives in the
real tree, behind SelectTarget's real 5 s cadence and its real target group.
"""
import pytest

import App
from engine.appc.ai import ArtificialIntelligence, BuilderAI
from engine.appc.ai_driver import tick_ai
from engine.appc.ships import ShipClass
from engine.appc.ship_motion import _step_ship_motion
from engine.appc.subsystems import (
    HullSubsystem, ImpulseEngineSubsystem, SensorSubsystem,
)
from engine.appc.weapon_subsystems import PhaserSystem, TorpedoSystem, TorpedoAmmoType
from engine.core.game import Game, Episode, Mission, _set_current_game

US_DORMANT = ArtificialIntelligence.US_DORMANT


@pytest.fixture
def game_context():
    mission = Mission()
    mission.SetScript("tests.integration.test_dormant_priority_child_recovers")
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


def _build_ship(y):
    ship = ShipClass()
    ship.SetTranslateXYZ(0, y, 0)
    ship._hull = HullSubsystem("H")
    ship._hull.SetMaxCondition(1000.0)
    ship._impulse_engine_subsystem = ImpulseEngineSubsystem("IES")
    ship._impulse_engine_subsystem.SetMaxSpeed(120.0)
    ship._sensor_subsystem = SensorSubsystem("Sensors")
    ship._phaser = PhaserSystem("P")
    ship._phaser._parent_ship = ship
    ship._torpedo_system = TorpedoSystem("T")
    ship._torpedo_system._parent_ship = ship
    ship._torpedo_system._ammo_by_slot = {
        0: TorpedoAmmoType("Photon", launch_speed=19.0)
    }
    return ship


def _find_named(ai, name, seen=None):
    """Walk the built tree for the node with this name."""
    if seen is None:
        seen = set()
    if ai is None or id(ai) in seen:
        return None
    seen.add(id(ai))
    getname = getattr(ai, "GetName", None)
    if callable(getname) and getname() == name:
        return ai
    kids = []
    contained = ai.__dict__.get("_contained_ai")
    if contained is not None:
        kids.append(contained)
    for entry in ai.__dict__.get("_ais", []) or []:
        kids.append(entry[1] if isinstance(entry, tuple) else entry)
    for kid in kids:
        found = _find_named(kid, name, seen)
        if found is not None:
            return found
    return None


def _run(builder, ship, seconds, t0):
    """Tick the AI at 4 Hz and the ship's motion at 60 Hz. Returns new t."""
    t = t0
    for _ in range(int(seconds * 4)):
        t += 0.25
        tick_ai(builder, game_time=t)
        for _ in range(15):
            _step_ship_motion(ship, 1.0 / 60.0)
    return t


def test_npc_re_engages_reinforcements_after_its_target_dies(game_context):
    pSet = App.SetClass_Create()
    pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet

    ours = _build_ship(0)
    pSet.AddObjectToSet(ours, "Attacker")
    target = _build_ship(500)
    pSet.AddObjectToSet(target, "Target")

    # The reinforcement is in the doctrine's target group from the start, but is
    # NOT in the set yet -- it warps in later. This is the stock shape: a mission
    # names every hostile up front and streams them in.
    import AI.Compound.FedAttack as fed_attack
    builder = fed_attack.CreateAI(ours, "Target", "Reinforcement")
    assert isinstance(builder, BuilderAI)
    ours.SetAI(builder)

    t = _run(builder, ours, seconds=10.0, t0=0.0)
    assert builder._activated is True, (
        f"BuilderAI activation failed: {builder._activation_error}"
    )

    select_target = _find_named(builder, "SelectTarget")
    assert select_target is not None, "FedAttack no longer contains a SelectTarget node"

    # Baseline: it engaged the only hostile in the set.
    assert ours.GetTarget() is target, "the NPC never acquired its initial target"

    # The target dies and leaves the set.
    pSet.RemoveObjectFromSet("Target")

    t = _run(builder, ours, seconds=10.0, t0=t)

    # With no target, SelectTarget reports PS_SKIP_DORMANT -> US_DORMANT. This
    # is the state our PriorityList used to latch forever.
    assert select_target._status == US_DORMANT, (
        "setup is not exercising the bug: SelectTarget never went dormant"
    )

    # Reinforcements warp in.
    reinforcement = _build_ship(400)
    pSet.AddObjectToSet(reinforcement, "Reinforcement")

    t = _run(builder, ours, seconds=15.0, t0=t)

    # THE ASSERTION: a dormant SelectTarget must be re-dispatched, re-run its
    # preprocess, and re-acquire. If the parent latches dormancy, the node is
    # never reached again and the NPC sits there forever.
    assert ours.GetTarget() is reinforcement, (
        "the NPC never re-engaged: its SelectTarget stayed latched in US_DORMANT"
    )
    assert select_target._status != US_DORMANT, (
        "SelectTarget never left dormancy"
    )
