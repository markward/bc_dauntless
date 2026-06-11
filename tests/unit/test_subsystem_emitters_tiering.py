# tests/unit/test_subsystem_emitters_tiering.py
from engine.appc import subsystem_emitters as se
from tests.unit.test_subsystem_emitters_registry import FakeSub


def test_destroyed_takes_precedence():
    sub = FakeSub(state="destroyed")
    assert se.desired_tier(sub) == se.TIER_DESTROYED


def test_disabled_maps_to_disabled():
    assert se.desired_tier(FakeSub(state="disabled")) == se.TIER_DISABLED


def test_damaged_maps_to_damaged():
    assert se.desired_tier(FakeSub(state="damaged")) == se.TIER_DAMAGED


def test_ok_maps_to_none():
    assert se.desired_tier(FakeSub(state="ok")) == se.TIER_NONE


def test_precedence_destroyed_over_disabled_over_damaged():
    # A subsystem reporting multiple predicates resolves to the most severe.
    class MultiSub(FakeSub):
        def IsDamaged(self):   return 1
        def IsDisabled(self):  return 1
        def IsDestroyed(self): return 1
    assert se.desired_tier(MultiSub()) == se.TIER_DESTROYED
