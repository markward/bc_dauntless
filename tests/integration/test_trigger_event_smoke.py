"""Activation smoke for AI.PlainAI.TriggerEvent.

SDK requires SetEvent(pEvent). The script fires that event when
its Update runs."""
import pytest

import App
from engine.appc.ai import PlainAI_Create, ArtificialIntelligence
from engine.appc.events import TGEvent
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


def test_trigger_event_update_returns_valid_status():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours._hull = HullSubsystem("H")
    ours._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(ours, "Ours")

    plain = PlainAI_Create(ours, "TestAI")
    plain.SetScriptModule("TriggerEvent")
    inst = plain.GetScriptInstance()
    evt = TGEvent(); evt.SetEventType(App.ET_MISSION_START)
    inst.SetEvent(evt)
    result = inst.Update()
    assert isinstance(result, int), (
        f"expected int, got {type(result).__name__} (likely _Stub)")
    assert result in _VALID_STATUS, f"unexpected status {result}"
