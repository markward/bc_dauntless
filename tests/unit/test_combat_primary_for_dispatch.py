"""Tests for combat._pick_primary_subsystem_for_dispatch.

Used to give hit_feedback.dispatch a single subsystem + transition even
though splash allocation damages many subsystems per hit.
"""

from engine.appc.combat import _pick_primary_subsystem_for_dispatch


def test_returns_highest_weight_candidate():
    allocations = [("sensors", 0.3), ("warp_core", 0.9), ("impulse", 0.5)]
    assert _pick_primary_subsystem_for_dispatch(allocations) == "warp_core"


def test_ties_resolved_by_first_in_list():
    allocations = [("sensors", 0.7), ("warp_core", 0.7)]
    assert _pick_primary_subsystem_for_dispatch(allocations) == "sensors"


def test_empty_allocations_returns_none():
    assert _pick_primary_subsystem_for_dispatch([]) is None


def test_all_zero_weights_returns_none():
    allocations = [("sensors", 0.0), ("warp_core", 0.0)]
    assert _pick_primary_subsystem_for_dispatch(allocations) is None
