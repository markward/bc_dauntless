"""Activation smoke for AI.PlainAI.EvilShuttleDocking.

SDK requires SetObjectToDockWith(s) — a target to dock with."""
import pytest

import App
from engine.appc.ai import PlainAI_Create, ArtificialIntelligence
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem


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


def test_evil_shuttle_docking_update_returns_valid_status():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours._hull = HullSubsystem("H")
    ours._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(ours, "Ours")
    target = ShipClass(); target.SetTranslateXYZ(0, 50, 0)
    target._hull = HullSubsystem("H"); target._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(target, "Target")

    plain = PlainAI_Create(ours, "TestAI")
    plain.SetScriptModule("EvilShuttleDocking")
    inst = plain.GetScriptInstance()
    inst.SetObjectToDockWith("Target")
    result = inst.Update()
    assert isinstance(result, int)
    assert result in _VALID_STATUS
