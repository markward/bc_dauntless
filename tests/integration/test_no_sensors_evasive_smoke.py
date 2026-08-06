"""Activation smoke for AI.Compound.Parts.NoSensorsEvasive.

SDK Parts/NoSensorsEvasive.py: CreateAI(pShip) returns
ConditionalAI("SensorsDisabled") wrapping SequenceAI("LoopForever")
wrapping RandomAI("Random") with 4 PlainAI(ManeuverLoop) children."""
import pytest

import App
from engine.appc.ai import (
    ConditionalAI, SequenceAI, RandomAI, PlainAI,
)
from engine.appc.ai_driver import tick_ai
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _build_scene():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours._hull = HullSubsystem("H"); ours._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(ours, "Ours")
    return ours


def test_no_sensors_evasive_create_ai_returns_expected_tree():
    ours = _build_scene()
    import AI.Compound.Parts.NoSensorsEvasive as nse
    ai = nse.CreateAI(ours)
    assert isinstance(ai, ConditionalAI)
    assert ai.GetName() == "SensorsDisabled"
    loop = ai._contained_ai
    assert isinstance(loop, SequenceAI)
    assert loop.GetName() == "LoopForever"
    random_ai = loop._ais[0]
    assert isinstance(random_ai, RandomAI)
    assert random_ai.GetName() == "Random"
    assert len(random_ai._ais) == 4
    leaf_names = [c.GetName() for c in random_ai._ais]
    assert set(leaf_names) == {"DriftUp", "DriftDown", "DriftRight", "DriftLeft"}
    for c in random_ai._ais:
        assert isinstance(c, PlainAI)


def test_no_sensors_evasive_tick_does_not_crash():
    ours = _build_scene()
    import AI.Compound.Parts.NoSensorsEvasive as nse
    ai = nse.CreateAI(ours)
    tick_ai(ai, game_time=0.01)


def _healthy_ship_with_sensors():
    """A ship with a real turn envelope and INTACT sensors.

    Intact matters. Conditions/ConditionSystemDisabled is purely event-driven:
    SubsystemInfo.IsDisabled() reads a cached bDisabled flag that starts at 0 and
    is only raised by the ET_SUBSYSTEM_DISABLED handler, and the initial
    CheckRootState() during setup reads that same cold flag. So a subsystem that
    was ALREADY disabled before the condition existed reads as healthy forever —
    BC's own behaviour, not ours, and the reason this test blinds the ship after
    building the AI rather than before."""
    from engine.appc.subsystems import ImpulseEngineSubsystem, SensorSubsystem

    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ship = ShipClass()
    ship._hull = HullSubsystem("H"); ship._hull.SetMaxCondition(1000.0)
    ies = ImpulseEngineSubsystem("IES")          # Galaxy turn envelope
    ies.SetMaxSpeed(6.3)
    ies.SetMaxAccel(1.5)
    ies.SetMaxAngularVelocity(0.28)
    ies.SetMaxAngularAccel(0.12)
    ship.SetImpulseEngineSubsystem(ies)
    sensors = SensorSubsystem("Sensors")
    sensors.SetMaxCondition(100.0)
    sensors.SetCondition(100.0)
    ship.SetSensorSubsystem(sensors)
    pSet.AddObjectToSet(ship, "Ours")
    return ship, sensors


def test_losing_sensors_makes_the_ship_actually_jink():
    """The whole chain, end to end: sensors cross the disabled threshold →
    ET_SUBSYSTEM_DISABLED → ConditionSystemDisabled flips → ConditionalAI goes
    ACTIVE → SequenceAI → RandomAI draws a child → PlainAI(ManeuverLoop) →
    ShipClass.TurnTowardDifference → the rotation integrator. The ship must
    actually change heading.

    The two tests above cannot see any of that: they assert the tree's SHAPE and
    that one tick doesn't raise, on a ship with no impulse engine, so a
    completely inert evasive passes both. Two real gaps hid behind exactly that
    blind spot — RandomAI had no dispatch branch at all until f631cf31, and
    TurnTowardDifference was a silent no-op until 2026-08-06."""
    from engine.core.loop import GameLoop, TICK_RATE
    from engine.appc.math import TGPoint3

    ship, sensors = _healthy_ship_with_sensors()
    import AI.Compound.Parts.NoSensorsEvasive as nse
    ai = nse.CreateAI(ship)
    ship.SetAI(ai)

    def _forward():
        v = TGPoint3(0.0, 1.0, 0.0)
        v.MultMatrixLeft(ship.GetWorldRotation())
        return v

    GameLoop().advance(TICK_RATE * 1)
    assert [c.GetStatus() for c in ai._conditions] == [0], (
        "sensors are intact — the evasive must be dormant")
    start = _forward()

    # Damage the sensors below the 25% disabled threshold but NOT to zero — the
    # realistic combat path, where condition falls incrementally. Slamming
    # straight to 0.0 instead jumps OPERATIONAL -> DESTROYED, and
    # _condition_changed fires only ET_SUBSYSTEM_DESTROYED for that transition,
    # which ConditionSystemDisabled does not listen for (it registers
    # ET_SUBSYSTEM_DISABLED / _OPERATIONAL only). Worth knowing if this test ever
    # regresses: the doctrine keys off crossing the disabled line, not off death.
    sensors.SetCondition(10.0)
    assert sensors.IsDisabled() and not sensors.IsDestroyed(), (
        "precondition: disabled but not destroyed")

    # Accumulate TOTAL angular travel, not net displacement: the four children
    # drift up / down / left / right at random, so opposing draws largely cancel
    # and the net heading barely moves even while the ship is jinking hard.
    import math
    loop = GameLoop()
    travelled = 0.0
    previous = start
    for _ in range(20):
        loop.advance(TICK_RATE * 1)
        now = _forward()
        dot = previous.x * now.x + previous.y * now.y + previous.z * now.z
        travelled += math.acos(max(-1.0, min(1.0, dot)))
        previous = now

    assert [c.GetStatus() for c in ai._conditions] == [1], (
        "ET_SUBSYSTEM_DISABLED never reached ConditionSystemDisabled")
    # Measured 3.68 rad (211 deg) of cumulative drift over these 20 s, against a
    # net displacement of only 5 deg. The floor is deliberately loose: the child
    # draw is random (RandomAI draws without replacement) so the exact figure
    # varies per run, and one full child maneuver alone is 0.15 x 2pi = 0.94 rad.
    # Anything above zero-ish proves the chain is live; inert scores 0.0.
    assert travelled > 0.5, (
        f"blinded ship never jinked: {travelled:.3f} rad of total travel")
