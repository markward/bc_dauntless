"""Activation smoke for AI.PlainAI.StarbaseAttack (the PlainAI body,
not the Compound of the same name).

SDK requires SetTargets(grp) — an ObjectGroup of starbase targets."""
import pytest

import App
from engine.appc.ai import PlainAI_Create, ArtificialIntelligence
from engine.appc.objects import ObjectGroup
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


def test_starbase_attack_plainai_update_returns_valid_status():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours._hull = HullSubsystem("H")
    ours._hull.SetMaxCondition(1000.0)
    ours._impulse_engine_subsystem = ImpulseEngineSubsystem("IES")
    ours._impulse_engine_subsystem.SetMaxSpeed(120.0)
    pSet.AddObjectToSet(ours, "Ours")
    starbase = ShipClass(); starbase.SetTranslateXYZ(0, 200, 0)
    starbase._hull = HullSubsystem("H"); starbase._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(starbase, "Starbase")

    grp = ObjectGroup(); grp.AddName("Starbase")
    plain = PlainAI_Create(ours, "TestAI")
    plain.SetScriptModule("StarbaseAttack")
    inst = plain.GetScriptInstance()
    inst.SetTargets(grp)
    result = inst.Update()
    assert isinstance(result, int)
    assert result in _VALID_STATUS
