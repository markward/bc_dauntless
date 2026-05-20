"""Activation smoke for AI.PlainAI.Warp (the largest unported
PlainAI at 468 LOC).

SDK has no required setters in SetRequiredParams. The script drives
in-system warp transitions."""
import pytest

import App
from engine.appc.ai import PlainAI_Create, ArtificialIntelligence
from engine.appc.ships import ShipClass
from engine.appc.subsystems import (
    HullSubsystem, ImpulseEngineSubsystem, WarpEngineSubsystem,
)


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


def test_warp_update_returns_valid_status():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours._hull = HullSubsystem("H")
    ours._hull.SetMaxCondition(1000.0)
    ours._impulse_engine_subsystem = ImpulseEngineSubsystem("IES")
    ours._impulse_engine_subsystem.SetMaxSpeed(120.0)
    # Warp script reads pShip.GetWarpEngineSubsystem(); seed it.
    ours._warp_engine_subsystem = WarpEngineSubsystem("WES")
    pSet.AddObjectToSet(ours, "Ours")

    plain = PlainAI_Create(ours, "TestAI")
    plain.SetScriptModule("Warp")
    inst = plain.GetScriptInstance()
    result = inst.Update()
    assert isinstance(result, int)
    assert result in _VALID_STATUS
