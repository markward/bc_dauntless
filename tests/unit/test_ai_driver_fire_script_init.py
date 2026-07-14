"""FireScript's CodeAISet fires generically at SetPreprocessingMethod bind time.

Historically this covered a driver-side duck-typed hack
(_ensure_fire_script_initialized) that hand-reimplemented FireScript.CodeAISet
(AI/Preprocessors.py:137-145) on first tick. ai.py's SetPreprocessingMethod now
calls the instance's real CodeAISet() generically once pCodeAI is bound (see
tests/unit/test_codeaiset_bind.py), so the SetTarget external function is
already registered by the time _wire_ship_with_fire_script returns — these
tests exercise that same end state through the generic path instead."""
import pytest

import App
from engine.appc.ai import PreprocessingAI_Create
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


def _wire_ship_with_fire_script(target_name="Target"):
    """SelectTarget-style minimal wiring: ship in a set, FireScript as the
    preprocessing instance bound to a PreprocessingAI."""
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours.SetTranslateXYZ(0, 0, 0)
    ours._hull = HullSubsystem("H"); ours._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(ours, "Ours")

    target = ShipClass(); target.SetTranslateXYZ(0, 100, 0)
    target._hull = HullSubsystem("H"); target._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(target, target_name)

    from AI.Preprocessors import FireScript
    inst = FireScript(target_name)
    pp = PreprocessingAI_Create(ours, "FirePP")
    inst.pCodeAI = pp
    pp.SetPreprocessingMethod(inst, "Update")
    return inst, pp, ours, target


def test_first_tick_registers_set_target_external_function():
    """SDK CodeAISet at Preprocessors.py:141 — RegisterExternalFunction.
    SetPreprocessingMethod already ran CodeAISet() at bind time (inside
    _wire_ship_with_fire_script), so pCodeAI has SetTarget in its external
    function map before the first tick, and ticking must not disturb it —
    SelectTarget's dispatch loop reaches FireScript.SetTarget either way."""
    inst, pp, _ours, _target = _wire_ship_with_fire_script()
    tick_ai(pp, game_time=0.0)
    assert "SetTarget" in pp._external_functions


def test_first_tick_is_idempotent():
    """Multiple ticks don't re-register / re-wire — bind-time CodeAISet()
    fires exactly once, and ticking never calls it again."""
    inst, pp, _ours, _target = _wire_ship_with_fire_script()
    tick_ai(pp, game_time=0.0)
    snapshot = dict(pp._external_functions)
    tick_ai(pp, game_time=0.1)
    tick_ai(pp, game_time=0.2)
    assert pp._external_functions == snapshot


def test_duck_typed_gate_skips_select_target_only_instance():
    """A SelectTarget-shaped instance (DamageEvent + no lWeapons, and no
    CodeAISet method at all) must NOT register SetTarget. Slice B's
    SelectTarget init path (_ensure_select_target_initialized) remains the
    one that runs for those instances."""
    # Build a non-FireScript instance that has DamageEvent but no lWeapons.
    class _OnlySelectTargetShape:
        def DamageEvent(self, *args, **kwargs): pass
        def Update(self, dEndTime): return App.PreprocessingAI.PS_NORMAL
        def GetNextUpdateTime(self): return 0.2
        pCodeAI = None

    inst = _OnlySelectTargetShape()
    assert not hasattr(inst, "lWeapons")

    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); pSet.AddObjectToSet(ours, "Ours")
    pp = PreprocessingAI_Create(ours, "PP"); inst.pCodeAI = pp
    pp.SetPreprocessingMethod(inst, "Update")

    tick_ai(pp, game_time=0.0)
    # FireScript-specific RegisterExternalFunction for SetTarget MUST NOT
    # have fired for this instance.
    assert "SetTarget" not in pp._external_functions
