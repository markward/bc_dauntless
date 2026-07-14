"""ShipSubsystem.GetConditionWatcher() — closes the second, independent gap
that kept Conditions.ConditionSystemBelow (the most-used AI condition in the
whole SDK, 31 call sites) permanently pinned at status 0.

Conditions/ConditionSystemBelow.py:94-101 does:

    pWatcher = pSystem.GetConditionWatcher()
    iRangeID = pWatcher.AddRangeCheck(self.fFraction, App.FloatRangeWatcher.FRW_BOTH, pEvent)
    self.dWatchInfo[pSystem.GetObjID()] = iRangeID
    fFraction = pWatcher.GetWatchedVariable()
    if fFraction < self.fFraction:
        bStatus = 1

GetConditionWatcher() returned a hardcoded None, so AddRangeCheck raised
AttributeError inside the condition's __init__, which ConditionScript
(engine/appc/ai.py) swallows into self._init_error, leaving self._instance
None -- the condition silently never fires.

Level 1 (below) is a unit test of the accessor in isolation. Level 2 is the
point of the task: it builds the REAL SDK script through
App.ConditionScript_Create end to end and would NOT be caught by Level 1
alone, because the original bug was that the SDK script failed to
*construct*, not a bad return value in isolation.
"""
import pytest

import App
from engine.appc.float_range_watcher import FloatRangeWatcher
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import HullSubsystem


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate_app_state():
    _reset_app_state()
    yield
    _reset_app_state()


# ── Level 1: unit test of the accessor ──────────────────────────────────────

def test_get_condition_watcher_returns_a_float_range_watcher_not_none():
    hull = HullSubsystem("Hull")
    watcher = hull.GetConditionWatcher()
    assert watcher is not None
    assert isinstance(watcher, FloatRangeWatcher)


def test_get_condition_watcher_is_stable_across_calls():
    hull = HullSubsystem("Hull")
    first = hull.GetConditionWatcher()
    second = hull.GetConditionWatcher()
    assert first is second


def test_get_condition_watcher_seeded_with_current_condition_fraction():
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(200.0)
    hull.SetCondition(150.0)
    watcher = hull.GetConditionWatcher()
    assert watcher.GetWatchedVariable() == pytest.approx(0.75)


def test_get_condition_watcher_distinct_from_combined_percentage_watcher():
    hull = HullSubsystem("Hull")
    assert hull.GetConditionWatcher() is not hull.GetCombinedPercentageWatcher()


def test_get_condition_watcher_tracks_set_condition_changes():
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(100.0)
    hull.SetCondition(100.0)
    watcher = hull.GetConditionWatcher()
    assert watcher.GetWatchedVariable() == pytest.approx(1.0)

    hull.SetCondition(30.0)
    assert watcher.GetWatchedVariable() == pytest.approx(0.3)


# ── Level 2: end-to-end through the real SDK script ─────────────────────────

def test_condition_system_below_constructs_against_real_hull_subsystem():
    """The condition must actually CONSTRUCT -- this is the original bug:
    it silently degraded to _instance is None, _init_error set."""
    _reset_app_state()
    pSet = App.SetClass_Create(); pSet.SetName("S")
    ship = ShipClass_Create("Test")
    ship.SetHull(HullSubsystem("Hull"))
    pSet.AddObjectToSet(ship, "Test Ship")
    App.g_kSetManager._sets["S"] = pSet

    cs = App.ConditionScript_Create(
        "Conditions.ConditionSystemBelow", "ConditionSystemBelow",
        "Test Ship", App.CT_HULL_SUBSYSTEM, 0.5)

    assert cs._init_error is None, cs._init_error
    assert cs._instance is not None


def test_condition_system_below_flips_status_on_hull_damage_and_repair():
    _reset_app_state()
    pSet = App.SetClass_Create(); pSet.SetName("S")
    ship = ShipClass_Create("Test")
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(100.0)
    hull.SetCondition(100.0)
    ship.SetHull(hull)
    pSet.AddObjectToSet(ship, "Test Ship")
    App.g_kSetManager._sets["S"] = pSet

    cs = App.ConditionScript_Create(
        "Conditions.ConditionSystemBelow", "ConditionSystemBelow",
        "Test Ship", App.CT_HULL_SUBSYSTEM, 0.5)
    assert cs._instance is not None, cs._init_error

    # Healthy hull, fraction 1.0 >= 0.5 threshold -> status starts false.
    assert cs.GetStatus() == 0

    # Damage the hull below the 0.5 fraction threshold -> status flips true.
    hull.SetCondition(30.0)
    assert cs.GetStatus() == 1

    # Repair it back above the threshold -> status returns false.
    hull.SetCondition(80.0)
    assert cs.GetStatus() == 0
