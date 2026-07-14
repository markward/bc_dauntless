"""A REAL Federation ship on the REAL shipped doctrine must survive.

This is the guard for the PS_DONE fix (2026-07-14). `AI/Compound/FedAttack.py`
wraps its whole combat subtree in a PreprocessingAI called "PowerManagement",
bound to `AI.Preprocessors.ManagePower`, whose Update body is
`# Unused.  return App.PreprocessingAI.PS_DONE`.

PS_DONE maps to US_DONE, and US_DONE is what tears an AI node down. The shipped
engine never runs that body — SetContainedAI swaps the Python node for a compiled
C++ one via GetOptimizedVersion — and `engine/appc/ai_optimized.py` does the same.

Without the swap, this ship's AI collapses to US_DONE within one 3 s
ManagePower cadence and stops driving the combat subtree entirely. A unit test
with fakes cannot reproduce that: the failure mode lives in the real tree.
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

US_DONE = ArtificialIntelligence.US_DONE


@pytest.fixture
def game_context():
    mission = Mission()
    mission.SetScript("tests.integration.test_fed_attack_survives_power_management")
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


def _build_ship(name, y):
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


def _find_power_management(ai, seen=None):
    """Walk the built tree for the PreprocessingAI named 'PowerManagement'."""
    if seen is None:
        seen = set()
    if ai is None or id(ai) in seen:
        return None
    seen.add(id(ai))
    if getattr(ai, "GetName", None) and ai.GetName() == "PowerManagement":
        return ai
    kids = []
    contained = ai.__dict__.get("_contained_ai")
    if contained is not None:
        kids.append(contained)
    for entry in ai.__dict__.get("_ais", []) or []:
        kids.append(entry[1] if isinstance(entry, tuple) else entry)
    for kid in kids:
        found = _find_power_management(kid, seen)
        if found is not None:
            return found
    return None


def test_a_real_fed_ship_still_has_a_live_ai_after_ten_seconds(game_context):
    pSet = App.SetClass_Create()
    pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet

    ours = _build_ship("Attacker", 0)
    pSet.AddObjectToSet(ours, "Attacker")
    target = _build_ship("Target", 500)
    pSet.AddObjectToSet(target, "Target")

    import AI.Compound.FedAttack as fed_attack
    builder = fed_attack.CreateAI(ours, "Target")
    assert isinstance(builder, BuilderAI)
    ours.SetAI(builder)

    # 10 s of game time at 4 AI ticks/s — well past ManagePower's 3.0 s cadence,
    # so the lethal PS_DONE (were it still reachable) would have fired 3 times.
    t = 0.0
    for _ in range(40):
        t += 0.25
        tick_ai(builder, game_time=t)
        for _ in range(15):
            _step_ship_motion(ours, 1.0 / 60.0)

    assert builder._activated is True, (
        f"BuilderAI activation failed: {builder._activation_error}"
    )

    # The doctrine really does contain the lethal node — if this ever stops
    # being true, the test below is guarding nothing.
    power = _find_power_management(builder)
    assert power is not None, "FedAttack no longer contains a PowerManagement node"

    assert ours.GetAI() is not None
    assert builder._status != US_DONE, "the root AI tore itself down"
    assert power._status != US_DONE, (
        "PowerManagement reported US_DONE — the ManagePower swap is not in effect"
    )
    assert ours._speed_setpoint is not None, (
        "after 10 s the combat subtree should still be driving the ship"
    )
