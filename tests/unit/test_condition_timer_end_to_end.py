"""Conditions.ConditionTimer end-to-end -- the payoff of Task 4.

ConditionTimer (65 SDK call sites, the most-used condition after
ConditionSystemBelow) is a one-shot-looking timer that Activate()
re-arms whenever bResetOnActivate is set (the default -- see
Conditions/ConditionTimer.py:63-78). Before ConditionScript.SetActive
forwarded to the wrapped instance's Activate(), a fired ConditionTimer
latched status=1 FOREVER: nothing ever called Activate() to reset it.

This drives the REAL SDK script through App.ConditionScript_Create (not a
spy), advances App.g_kTimerManager's game clock past the timer's delay,
and proves both the fire and the re-arm.

It also proves a second, independent bug found while writing this test:
Conditions/ConditionTimer.py:73 calls
App.g_kTimerManager.RemoveTimer(self.pTimer.GetObjID()) -- an int, not a
TGTimer object. TGTimerManager.RemoveTimer previously only accepted a
TGTimer (engine/appc/timers.py), so a mid-flight re-arm (Activate() called
BEFORE the timer had fired) raised AttributeError inside Activate(), which
ConditionScript.SetActive swallows -- silently leaving the OLD timer
running at its OLD fire time instead of the reset one. See
tests/unit/test_timers.py::test_remove_timer_accepts_an_obj_id_int for the
isolated regression test on the timer manager itself.
"""
import App


def test_condition_timer_fires_after_its_delay():
    cs = App.ConditionScript_Create("Conditions.ConditionTimer", "ConditionTimer", 5.0)
    assert cs._init_error is None, cs._init_error
    assert cs._instance is not None
    assert cs.GetStatus() == 0

    App.g_kTimerManager.tick(6.0)
    assert cs.GetStatus() == 1


def test_condition_timer_rearms_on_set_active_after_firing():
    """SetActive() after the timer has already fired must reset it back to
    status 0 and it must fire again after another full delay -- the
    ConditionalAI.AddCondition(cond) path (cond.SetActive()) is what makes
    this happen for every repeating-timer branch in the SDK."""
    cs = App.ConditionScript_Create("Conditions.ConditionTimer", "ConditionTimer", 5.0)
    App.g_kTimerManager.tick(6.0)
    assert cs.GetStatus() == 1

    cs.SetActive()
    assert cs.GetStatus() == 0, "Activate() must re-arm and reset status to 0"

    App.g_kTimerManager.tick(4.0)
    assert cs.GetStatus() == 0, "must not fire again before a full delay has elapsed"

    App.g_kTimerManager.tick(2.0)
    assert cs.GetStatus() == 1, "must fire again after the re-armed delay elapses"


def test_condition_timer_rearms_mid_flight_before_firing():
    """Activate() called BEFORE the timer fires takes ConditionTimer's
    "timer already exists" branch (Conditions/ConditionTimer.py:70-75),
    which removes and re-adds the SAME TGTimer with a new start time. This
    is the branch that exposed the RemoveTimer(int) bug."""
    cs = App.ConditionScript_Create("Conditions.ConditionTimer", "ConditionTimer", 5.0)
    App.g_kTimerManager.tick(2.0)
    assert cs.GetStatus() == 0

    cs.SetActive()  # mid-flight re-arm, timer not yet fired
    assert cs.GetStatus() == 0

    # Original delay would have fired at t=5; re-armed delay fires at t=7.
    App.g_kTimerManager.tick(4.0)  # t=6 -- must NOT have fired yet
    assert cs.GetStatus() == 0
    App.g_kTimerManager.tick(2.0)  # t=8 -- now past the re-armed t=7
    assert cs.GetStatus() == 1
