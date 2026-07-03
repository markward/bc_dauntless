"""SelectTarget drops a cloaked target via the event -> TargetGone -> ForceUpdate
path, driven through the AI driver (not a manual second Update).

Contrast with tests/unit/test_select_target_drops_cloaked.py, which calls
inst.Update() directly and so leans on the driver-independent "re-select on the
next Update" behaviour. Here the driver gates SelectTarget on its real 5s cadence,
so a mid-window tick does NOT re-select — the drop lands *only* because the cloak
event fires TargetGone, which calls ForceUpdate to reschedule the preprocessor for
the next tick.
"""
import App
import pytest

from engine.appc.ai import PreprocessingAI_Create
from engine.appc.ai_driver import tick_ai
from engine.appc.objects import ObjectGroup
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, ShieldSubsystem, CloakingSubsystem


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


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
    """SelectTarget preprocessor under a PreprocessingAI, ready for the driver.

    Leaves the CodeAISet analog (event-handler + dDamageReceived + initial
    SetTarget push) to ai_driver._ensure_select_target_initialized, which runs
    on the first tick_ai — the faithful path.
    """
    from AI.Preprocessors import SelectTarget
    pp = PreprocessingAI_Create(ours, "SelectPP")
    pp._has_focus = True
    grp = ObjectGroup()
    for n in target_names:
        grp.AddName(n)
    inst = SelectTarget(grp)
    pp.SetPreprocessingMethod(inst, "Update")
    return inst, pp


def test_forceupdate_drops_cloaked_target_on_next_tick():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = _kitted_ship(0, 0, 0)
    pSet.AddObjectToSet(ours, "Ours")
    enemy = _kitted_ship(0, 50, 0, cloak=True)
    pSet.AddObjectToSet(enemy, "Enemy")

    inst, pp = _wire_select_target(ours, "Enemy")

    # Count re-selections so we can prove the gate suppresses them mid-window.
    orig_find = inst.FindGoodTarget
    finds = []
    inst.FindGoodTarget = lambda *a, **k: (finds.append(1), orig_find(*a, **k))[-1]

    # Tick 0: first (overdue) tick selects the visible enemy. Because the
    # target *changed* (None -> Enemy), SelectTarget's UpdateTargetInfo spread
    # bookkeeping transiently drops fUpdateTime to 0.0, so the cadence hasn't
    # settled to 5s yet — one more tick is needed (faithful BC behaviour).
    tick_ai(pp, game_time=0.0)
    assert inst.sCurrentTarget == "Enemy"
    assert ours.GetTarget() is enemy
    assert len(finds) == 1

    # Tick 1: target re-confirmed (no change), so fUpdateTime resets to the
    # 5s fNormalUpdateTime and the cadence settles: next update ~5s out.
    tick_ai(pp, game_time=0.1)
    assert len(finds) == 2
    assert inst.sCurrentTarget == "Enemy"
    assert pp._next_update_time == pytest.approx(5.1)

    # Mid-window tick (no event): the 5s gate holds — SelectTarget does NOT
    # re-run, so no re-selection happens. This is the contrast against relying
    # on every-tick re-selection.
    tick_ai(pp, game_time=0.2)
    assert len(finds) == 2
    assert inst.sCurrentTarget == "Enemy"
    assert pp._next_update_time == pytest.approx(5.1)

    # Enemy cloaks fully. The routed ET_CLOAK_COMPLETED fires SelectTarget's
    # target-scoped TargetGone handler, which calls ForceUpdate -> reschedules
    # the preprocessor to re-run on the next tick.
    enemy.GetCloakingSubsystem().InstantCloak()
    assert pp._next_update_time == 0.0

    # Next tick (still deep inside the 5s window): the forced re-run re-selects,
    # skips the now-cloaked candidate, and drops the target.
    tick_ai(pp, game_time=0.3)
    assert len(finds) == 3
    assert inst.sCurrentTarget is None
    assert ours.GetTarget() is None
