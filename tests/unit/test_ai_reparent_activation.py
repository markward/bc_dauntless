"""Regression: re-parenting an AI tree onto a new root must not strand it
"active" -- the exact sequence HelmMenuHandlers.OverrideAIInternal runs when
Fleet Command overrides a ship's orders (sdk/.../Bridge/HelmMenuHandlers.py:
2292-2329):

    pOverrideAI.AddAI(pOldAI, 2)     # graft the SAME old AI object, lower prio
    pShip.ClearAI(0, pOldAI)         # 0 == do NOT delete the old AI
    pShip.SetAI(pOverrideAI)

Before this fix, ai_driver._reconcile_active stored the "active this tick"
set on ``root_ai._active_nodes`` -- PER ROOT. A node activated while its old
root (pOldAI, ticked directly as the ship's AI) was in charge could only be
deactivated by that same root's next reconciliation. Once ClearAI/SetAI
re-parented it under pOverrideAI, the old root never ticks again, so its
nodes' ``_is_active_in_tree`` flags stayed stuck at True forever -- and
because SetActive()/SetInactive() are edge-guarded, a LATER real activation
under the new root (pOverrideAI reaching pOldAI again once the override is
lifted) would be silently swallowed: no _on_activated, so ConditionalAI never
re-registers its condition list, and a re-armed Conditions.ConditionTimer
never re-fires.

This test builds the real sequence (no hand-called SetActive()) and drives a
real SDK ConditionTimer through it via tick_ai + the game clock, mirroring
tests/unit/test_ai_activation_lifecycle.py's end-to-end recipe.
"""
import App
from engine.appc.ai import (
    ArtificialIntelligence, ConditionalAI_Create, PriorityListAI_Create,
)
from engine.appc.ai_driver import tick_ai
from engine.appc.ships import ShipClass

US_ACTIVE = ArtificialIntelligence.US_ACTIVE


def _advance(ship, dt: float) -> None:
    """Advance the real game clock and tick the ship's installed AI by the
    same amount -- the only two things a production frame does."""
    App.g_kTimerManager.tick(dt)
    tick_ai(ship.GetAI(), App.g_kTimerManager.get_time())


def _always_active(*_status):
    return US_ACTIVE


def test_fleet_command_override_reparent_deactivates_and_later_reactivates():
    ship = ShipClass()

    # pOldAI: the ship's current orders -- a ConditionalAI (always eligible)
    # wrapping a real Conditions.ConditionTimer, exactly like a combat/patrol
    # branch that re-polls on a cadence.
    old_ai = ConditionalAI_Create(ship, "OldOrders")
    old_ai.SetEvaluationFunction(_always_active)
    timer = App.ConditionScript_Create("Conditions.ConditionTimer", "ConditionTimer", 5.0)
    assert timer._init_error is None, timer._init_error
    old_ai.AddCondition(timer)

    ship.SetAI(old_ai)

    # Drive it for real: old_ai activates in the tree, its condition
    # registers, and the timer fires once on schedule.
    _advance(ship, 0.0)
    assert old_ai._is_active_in_tree is True
    assert timer.IsActive() == 1
    _advance(ship, 6.0)
    assert timer.GetStatus() == 1, "timer fires under its own root"

    # ── The real SDK override sequence (HelmMenuHandlers.OverrideAIInternal) ──
    override_ai = PriorityListAI_Create(ship, "FleetCommandOverrideAI")
    override_ai.SetInterruptable(1)
    override_ai.AddAI(old_ai, 2)          # graft the SAME old AI, lower prio

    new_ai = ConditionalAI_Create(ship, "FleetCommandOrder")
    new_ai.SetEvaluationFunction(_always_active)
    override_ai.AddAI(new_ai, 1)          # higher prio -- this is what runs

    ship.ClearAI(0, old_ai)               # 0 == do NOT delete the old AI
    ship.SetAI(override_ai)

    # While overridden: new_ai (priority 1) is always eligible, so the
    # priority list never reaches old_ai. Assert the re-parented subtree is
    # NOT stuck "active" from its old life as a direct root.
    _advance(ship, 1.0)
    assert new_ai._is_active_in_tree is True
    assert old_ai._is_active_in_tree is False, (
        "re-parented subtree must not be stranded active by its old root"
    )
    assert timer.IsActive() == 0, (
        "the old condition must be unregistered while its branch is overridden"
    )

    # Advance well past the timer's cadence while overridden -- with the bug,
    # a still-"active" timer would keep re-arming/firing on its own even
    # though its branch is not supposed to be running at all.
    _advance(ship, 20.0)
    assert old_ai._is_active_in_tree is False

    # ── Lift the override (StopOverridingAI's essential action) ──
    override_ai.RemoveAIByPriority(1)

    # Now old_ai (priority 2) is the sole child -- the priority list picks it
    # back up. This must be a REAL edge: _on_activated must actually fire
    # again (not be swallowed by a stuck True flag), which re-registers the
    # condition and re-arms the timer.
    _advance(ship, 1.0)
    assert old_ai._is_active_in_tree is True
    assert timer.IsActive() == 1
    assert timer.GetStatus() == 0, "re-activation must re-arm the timer"

    # Past the freshly re-armed delay -> fires again, proving this is a live
    # re-registration, not a stale latch.
    _advance(ship, 6.0)
    assert timer.GetStatus() == 1, "timer must fire again after re-arming"
