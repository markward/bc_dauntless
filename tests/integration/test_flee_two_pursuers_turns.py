"""A ship fleeing TWO pursuers must change heading.

With one pursuer Flee.py:106-109 takes the exact opposite direction, so the
old status-only smoke passed. With two or more, Flee.py:115 draws random
candidates via App.TGPoint3_GetRandomUnitVector; undefined, every candidate
was a stub, TurnTowardDirection got the zero vector and returned early, and
the ship charged straight ahead at full impulse forever."""
import math
import pytest

import App
from engine.appc.ai import PlainAI_Create
from engine.appc.math import TGPoint3
from engine.appc.objects import ObjectGroup
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, ImpulseEngineSubsystem
from engine.core.loop import GameLoop, TICK_RATE


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _ship(pSet, name, x, y, z):
    s = ShipClass(); s.SetTranslateXYZ(x, y, z)
    s._hull = HullSubsystem("H"); s._hull.SetMaxCondition(1000.0)
    s._impulse_engine_subsystem = ImpulseEngineSubsystem("IES")
    s._impulse_engine_subsystem.SetMaxSpeed(120.0)
    pSet.AddObjectToSet(s, name)
    return s


def _forward(ship):
    v = TGPoint3(0.0, 1.0, 0.0)
    v.MultMatrixLeft(ship.GetWorldRotation())
    return v


def test_fleeing_two_pursuers_accumulates_heading_change():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = _ship(pSet, "Ours", 0, 0, 0)
    # Two pursuers on opposite flanks: their mean direction is ~zero, so the
    # single-pursuer "exact opposite" shortcut cannot apply and the random
    # candidate draw is the only path to a heading.
    _ship(pSet, "P1", 300, 0, 0)
    _ship(pSet, "P2", -300, 50, 0)

    grp = ObjectGroup(); grp.AddName("P1"); grp.AddName("P2")
    plain = PlainAI_Create(ours, "Flee")
    plain.SetScriptModule("Flee")
    plain.GetScriptInstance().SetFleeFromGroup(grp)
    ours.SetAI(plain)

    loop = GameLoop()
    travelled = 0.0
    previous = _forward(ours)
    for _ in range(10):
        loop.advance(TICK_RATE * 1)
        now = _forward(ours)
        dot = previous.x * now.x + previous.y * now.y + previous.z * now.z
        travelled += math.acos(max(-1.0, min(1.0, dot)))
        previous = now

    assert travelled > 0.3, (
        f"fleeing ship never turned: {travelled:.3f} rad of total travel — "
        "Flee's random candidate draw is inert")
