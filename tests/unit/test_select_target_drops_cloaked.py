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

⚠️ THE ENEMY SITS OUTSIDE THE CLOAK BUBBLE ON PURPOSE, and the distance is
DERIVED. Since the acquisition half of the stage-4 contest landed
(tests/unit/test_ai_acquires_close_cloaked.py), a cloaked ship INSIDE the
observer's bubble is deliberately retained rather than dropped. These fixtures
author no BaseSensorRange, so they get FALLBACK_RANGE_GU and the game's largest
bubble; the old hardcoded 50 GU sat well inside it, which made both tests here
assert the opposite of the intended behaviour. They pass now because the distance
is outside the bubble, not because cloak is absolute — the subject of this file is
the DROP PLUMBING (re-selection and event routing), which is range-independent.
"""
import App
from engine.appc.ai import PreprocessingAI_Create
from engine.appc.ai_sensor_gate import install_ai_sensor_gate
from engine.appc.objects import ObjectGroup
from engine.appc.ships import ShipClass
from engine.appc.subsystems import (
    HullSubsystem, ShieldSubsystem, CloakingSubsystem,
)
from tests.helpers.cloak_geometry import (
    FALLBACK_SENSOR_GU, inside_gu, outside_gu)


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


import pytest


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    # Install the sensor gate explicitly. It is a GLOBAL monkey-patch on
    # AI.Preprocessors, so without this the file's behaviour depended on whether
    # some earlier test file happened to install it — these tests passed alone
    # and failed in the full suite. Production always installs it, so pin it.
    install_ai_sensor_gate()
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
    enemy = _kitted_ship(0, outside_gu(FALLBACK_SENSOR_GU), 0, cloak=True)
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
    enemy = _kitted_ship(0, outside_gu(FALLBACK_SENSOR_GU), 0, cloak=True)
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


def test_cloaked_target_INSIDE_the_bubble_is_retained():
    """The counterpart of the test above, and the reason its distance is derived.

    INTENTIONAL DIVERGENCE (ENHANCED_SENSOR_CONTEST, default on): a target that
    cloaks while inside the observer's sensor bubble is NOT dropped — the AI can
    still see it, so it keeps the lock and keeps shooting. Same fixture as above
    with only the distance changed, so the two together pin the boundary rather
    than one behaviour."""
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = _kitted_ship(0, 0, 0)
    pSet.AddObjectToSet(ours, "Ours")
    enemy = _kitted_ship(0, inside_gu(FALLBACK_SENSOR_GU), 0, cloak=True)
    pSet.AddObjectToSet(enemy, "Enemy")

    inst, _pp = _wire_select_target(ours, "Enemy")
    inst.Update(dEndTime=999.0)
    assert inst.sCurrentTarget == "Enemy"

    enemy.GetCloakingSubsystem().InstantCloak()
    inst.Update(dEndTime=1000.0)
    assert inst.sCurrentTarget == "Enemy"          # retained, not dropped
    assert ours.GetTarget() is enemy
