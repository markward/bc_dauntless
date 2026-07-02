"""SelectTarget drops a target that cloaks.

Two SDK mechanisms, both exercised here:

  1. Re-selection: SelectTarget.FindGoodTarget skips any ShipClass candidate
     whose cloaking subsystem IsCloaked() (Preprocessors.py:1444-1450), so the
     next Update re-selects away from a cloaked target.

  2. Event routing (the fix): cloak completion now fires ET_CLOAK_COMPLETED with
     the ship as destination, so SelectTarget's target-scoped "TargetGone"
     handler — registered on the current target in UpdateTargetInfo — actually
     receives it. Before the fix the event was sourced from the subsystem with
     no destination and the handler never fired.

Mirrors the wiring in test_select_target_dispatch.py.
"""
import App
from engine.appc.ai import PreprocessingAI_Create
from engine.appc.objects import ObjectGroup
from engine.appc.ships import ShipClass
from engine.appc.subsystems import (
    HullSubsystem, ShieldSubsystem, CloakingSubsystem,
)


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


import pytest


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _kitted_ship(x, y, z, cloak=False):
    s = ShipClass(); s.SetTranslateXYZ(x, y, z)
    s._hull = HullSubsystem("H"); s._hull.SetMaxCondition(1000.0)
    s._shield_subsystem = ShieldSubsystem("Shd")
    if cloak:
        s.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
    return s


def _wire_select_target(ours, *target_names):
    from AI.Preprocessors import SelectTarget
    pp = PreprocessingAI_Create(ours, "SelectPP")
    pp._has_focus = True
    grp = ObjectGroup()
    for n in target_names:
        grp.AddName(n)
    inst = SelectTarget(grp); inst.pCodeAI = pp
    inst.dDamageReceived = {}
    inst.pEventHandler = App.TGPythonInstanceWrapper()
    inst.pEventHandler.SetPyWrapper(inst)
    pp.SetPreprocessingMethod(inst, "Update")
    return inst, pp


def test_target_dropped_after_it_cloaks():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = _kitted_ship(0, 0, 0)
    pSet.AddObjectToSet(ours, "Ours")
    enemy = _kitted_ship(0, 50, 0, cloak=True)
    pSet.AddObjectToSet(enemy, "Enemy")

    inst, _pp = _wire_select_target(ours, "Enemy")

    # First selection: enemy is visible → locked.
    inst.Update(dEndTime=999.0)
    assert inst.sCurrentTarget == "Enemy"
    assert ours.GetTarget() is enemy

    # Enemy cloaks fully.
    enemy.GetCloakingSubsystem().InstantCloak()

    # Re-selection drops the now-cloaked target.
    inst.Update(dEndTime=1000.0)
    assert inst.sCurrentTarget is None
    assert ours.GetTarget() is None


def test_cloak_event_reaches_target_gone_handler():
    """The routed ET_CLOAK_COMPLETED fires SelectTarget's target-scoped
    TargetGone handler (registered on the current target in UpdateTargetInfo)."""
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = _kitted_ship(0, 0, 0)
    pSet.AddObjectToSet(ours, "Ours")
    enemy = _kitted_ship(0, 50, 0, cloak=True)
    pSet.AddObjectToSet(enemy, "Enemy")

    inst, _pp = _wire_select_target(ours, "Enemy")
    inst.Update(dEndTime=999.0)
    assert inst.sCurrentTarget == "Enemy"

    # Spy on TargetGone to prove the event routing reaches the handler.
    calls = []
    orig = inst.TargetGone
    inst.TargetGone = lambda pEvent: (calls.append(pEvent), orig(pEvent))[-1]

    enemy.GetCloakingSubsystem().InstantCloak()

    assert len(calls) == 1
