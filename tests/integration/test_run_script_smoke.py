"""Activation smoke for AI.PlainAI.RunScript.

SDK requires SetScriptModule(s) + SetFunction(s) — names a module + a
function to call. Point at a guaranteed-importable stub: App itself
has an Update-named member? No — point at a no-op helper. Easiest:
target a function that exists on the SDK's own MissionLib (App is
imported by every SDK module so referencing App.something is safe)."""
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


def test_run_script_update_returns_valid_status():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours._hull = HullSubsystem("H")
    ours._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(ours, "Ours")

    plain = PlainAI_Create(ours, "TestAI")
    plain.SetScriptModule("RunScript")
    inst = plain.GetScriptInstance()
    # Point at any importable module+function pair. The SDK will
    # __import__() this and call getattr(mod, fn)(*lArguments) with the
    # empty arg tuple set by SetupDefaultParams. `MissionLib.GetPlayer`
    # is a zero-arg side-effect-free helper that just returns the current
    # player (None in this headless fixture).
    inst.SetScriptModule("MissionLib")
    inst.SetFunction("GetPlayer")
    result = inst.Update()
    assert isinstance(result, int)
    assert result in _VALID_STATUS
