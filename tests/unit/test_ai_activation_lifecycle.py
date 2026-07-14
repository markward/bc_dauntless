"""The AI node activation lifecycle -- the driver Task 4's mechanism needed.

Task 4 made ConditionScript.SetActive() forward to the wrapped SDK script's
Activate(), and made ConditionalAI.AddCondition() call it -- but nothing ever
called SetActive() at the *right* moment. It fired exactly once, at
AddCondition time, right after ConditionTimer.__init__ had already armed its
own timer -- so a repeating ConditionTimer fired once and latched forever.

ai-architecture.md Sec.6 (RE'd from the binary): BaseAI's SetActive/
SetInactive (vtable +0x20/+0x24) fire once per tree-activation transition,
guarded by a byte flag; ConditionalAI's only confirmed C++ overrides register/
unregister its condition list against them. So conditions are activated on
NODE activation, not at wiring time -- and re-activation (a PriorityListAI
picking a sibling back up) is what re-arms a repeating timer.

This file proves:
  1. The base ArtificialIntelligence.SetActive/SetInactive edge guard.
  2. ConditionalAI drives its condition list from real dispatch (no hand
     calls), via a PriorityListAI whose picked child changes.
  3. AddCondition on a not-yet-active node must NOT activate the condition;
     on an already-active node it must.
  4. End-to-end with the REAL SDK Conditions.ConditionTimer, driven purely by
     tick_ai + the game clock -- no SetActive() called by hand anywhere. This
     is the proof that the bug described above is actually fixed.
"""
import App
from engine.appc.ai import (
    ArtificialIntelligence, ConditionalAI, ConditionalAI_Create,
    PriorityListAI_Create, TGCondition,
)
from engine.appc.ai_driver import tick_ai

US_ACTIVE = ArtificialIntelligence.US_ACTIVE
US_DORMANT = ArtificialIntelligence.US_DORMANT


# ── 1. Base edge guard ───────────────────────────────────────────────────────

class _Probe(ArtificialIntelligence):
    def __init__(self):
        super().__init__(None, "probe")
        self.calls: list = []

    def _on_activated(self) -> None:
        self.calls.append("activated")

    def _on_deactivated(self) -> None:
        self.calls.append("deactivated")


def test_set_active_fires_on_activated_exactly_once_per_transition():
    node = _Probe()
    assert node._is_active_in_tree is False

    node.SetActive()
    node.SetActive()          # repeated call -- must NOT refire
    node.SetActive()
    assert node.calls == ["activated"]
    assert node._is_active_in_tree is True

    node.SetInactive()
    node.SetInactive()        # repeated call -- must NOT refire
    assert node.calls == ["activated", "deactivated"]
    assert node._is_active_in_tree is False

    node.SetActive()          # the edge guard resets, so this fires again
    assert node.calls == ["activated", "deactivated", "activated"]


# ── 2. ConditionalAI driven by real dispatch (no hand-called SetActive) ─────

def test_conditional_ai_activates_and_deactivates_conditions_via_dispatch():
    flags = {"a": True}

    def eval_a(*_status):
        return US_ACTIVE if flags["a"] else US_DORMANT

    def eval_b(*_status):
        return US_ACTIVE

    a = ConditionalAI_Create(None, "A")
    a.SetEvaluationFunction(eval_a)
    cond_a = TGCondition()
    a.AddCondition(cond_a)

    b = ConditionalAI_Create(None, "B")
    b.SetEvaluationFunction(eval_b)
    cond_b = TGCondition()
    b.AddCondition(cond_b)

    root = PriorityListAI_Create(None, "root")
    root.AddAI(a, 0)   # higher priority (lower int)
    root.AddAI(b, 1)

    tick_ai(root, 0.0)
    assert a._is_active_in_tree is True
    assert b._is_active_in_tree is False
    assert cond_a.IsActive() == 1
    assert cond_b.IsActive() == 0

    # A's EvalFunc goes DORMANT -> the priority list skips it and picks B.
    flags["a"] = False
    tick_ai(root, 1.0)
    assert a._is_active_in_tree is False
    assert b._is_active_in_tree is True
    assert cond_a.IsActive() == 0, "A dropped off the path -> its conditions deactivate"
    assert cond_b.IsActive() == 1, "B was picked back up -> its conditions activate"

    # A regains eligibility -> the priority list picks it back up.
    flags["a"] = True
    tick_ai(root, 2.0)
    assert a._is_active_in_tree is True
    assert b._is_active_in_tree is False
    assert cond_a.IsActive() == 1
    assert cond_b.IsActive() == 0


# ── 3. AddCondition gates on the node's current tree-activation state ──────

def test_add_condition_only_activates_immediately_on_an_already_active_node():
    node = ConditionalAI_Create(None, "n")
    cond1 = TGCondition()
    node.AddCondition(cond1)
    assert cond1.IsActive() == 0, "node is not yet active in the tree"

    node.SetActive()   # node becomes active in the tree
    assert cond1.IsActive() == 1, "pre-existing condition activates with the node"

    cond2 = TGCondition()
    node.AddCondition(cond2)
    assert cond2.IsActive() == 1, "late-added condition on an already-active node activates immediately"


# ── 4. End-to-end proof: the real SDK ConditionTimer re-arms ───────────────

def _advance(root, dt: float) -> None:
    """Advance the real game clock and tick the AI tree by the same amount --
    the only two things a production frame does."""
    App.g_kTimerManager.tick(dt)
    tick_ai(root, App.g_kTimerManager.get_time())


def test_priority_list_reactivation_rearms_real_condition_timer_end_to_end():
    """Build a real PriorityListAI with two ConditionalAI children, the
    lower-priority one gated on a REAL Conditions/ConditionTimer built via
    App.ConditionScript_Create. Drive ONLY tick_ai + the game clock -- never
    call SetActive() by hand. Prove the timer fires, gets deactivated and
    reactivated by the priority list, and RE-ARMS (status back to 0) and
    fires again.

    Without this task: SetActive() is called exactly once, at AddCondition
    time -- right after ConditionTimer.__init__ has already armed its own
    timer. So the status latches at 1 forever the first time it fires; the
    re-arm below (status back to 0 after the second activation) is the
    behaviour this task must produce.
    """
    flags = {"a": True}

    def eval_a(*_status):
        return US_ACTIVE if flags["a"] else US_DORMANT

    def eval_b(*_status):
        return US_ACTIVE

    a = ConditionalAI_Create(None, "A")
    a.SetEvaluationFunction(eval_a)

    b = ConditionalAI_Create(None, "B")
    b.SetEvaluationFunction(eval_b)
    cs = App.ConditionScript_Create("Conditions.ConditionTimer", "ConditionTimer", 5.0)
    assert cs._init_error is None, cs._init_error
    b.AddCondition(cs)
    # B is not active in the tree yet -- AddCondition must not have armed it
    # via the tree lifecycle (ConditionTimer.__init__'s own SetupTimer still
    # ran, independently, at construction time).
    assert cs.GetStatus() == 0

    root = PriorityListAI_Create(None, "root")
    root.AddAI(a, 0)   # higher priority
    root.AddAI(b, 1)

    # A is active -> B is never reached -> B's tree-activation never fires.
    _advance(root, 0.0)
    assert b._is_active_in_tree is False

    # A goes dormant -> the priority list picks B -> B activates in the tree
    # -> ConditionalAI._on_activated -> cs.SetActive() -> Activate() resets
    # the already-running timer to fire 5s from now.
    flags["a"] = False
    _advance(root, 1.0)
    assert b._is_active_in_tree is True
    assert cs.GetStatus() == 0

    # Past the (freshly re-armed) 5s delay -> fires.
    _advance(root, 6.0)
    assert cs.GetStatus() == 1, "timer must fire"

    # A reclaims the priority list -> B drops off the active path ->
    # ConditionalAI._on_deactivated -> cs.SetInactive() (no re-arm from this
    # alone -- ConditionTimer has no Deactivate(), only Activate()).
    flags["a"] = True
    _advance(root, 1.0)
    assert b._is_active_in_tree is False
    assert cs.GetStatus() == 1, "deactivation alone does not clear the latched status"

    # A goes dormant again -> B is picked back up -> re-activated -> THE
    # RE-ARM: cs.SetActive() -> ConditionTimer.Activate() rebuilds the timer
    # and resets status to 0. Without this task, status stays latched at 1
    # forever from here on.
    flags["a"] = False
    _advance(root, 1.0)
    assert b._is_active_in_tree is True
    assert cs.GetStatus() == 0, "re-activation must re-arm the timer"

    # Past the newly re-armed delay -> fires again.
    _advance(root, 6.0)
    assert cs.GetStatus() == 1, "timer must fire again after re-arming"
