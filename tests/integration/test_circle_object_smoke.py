"""Activation smoke for AI.PlainAI.CircleObject.

SDK requires SetFollowObjectName(s) + SetNearFacingVector(v: TGPoint3)."""
import pytest

import App
from engine.appc.ai import PlainAI_Create, ArtificialIntelligence
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, ImpulseEngineSubsystem


_VALID_STATUS = (
    ArtificialIntelligence.US_ACTIVE,
    ArtificialIntelligence.US_DONE,
    ArtificialIntelligence.US_DORMANT,
    ArtificialIntelligence.US_INVALID,
)


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def test_circle_object_update_returns_valid_status():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours._hull = HullSubsystem("H")
    ours._hull.SetMaxCondition(1000.0)
    ours._impulse_engine_subsystem = ImpulseEngineSubsystem("IES")
    ours._impulse_engine_subsystem.SetMaxSpeed(120.0)
    pSet.AddObjectToSet(ours, "Ours")
    center = ShipClass(); center.SetTranslateXYZ(0, 100, 0)
    center._hull = HullSubsystem("H"); center._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(center, "Center")

    plain = PlainAI_Create(ours, "TestAI")
    plain.SetScriptModule("CircleObject")
    inst = plain.GetScriptInstance()
    inst.SetFollowObjectName("Center")
    side = App.TGPoint3(); side.SetXYZ(1.0, 0.0, 0.0)
    inst.SetNearFacingVector(side)
    result = inst.Update()
    assert isinstance(result, int)
    assert result in _VALID_STATUS
