"""`_is_offline(sub)` returns True iff the subsystem reports IsDisabled
OR IsDestroyed. Used by every Project 5 gate as the single source of
truth for "this capability is offline." Repair lifting condition flips
the gate back automatically because the predicate is read at use-time.
"""
from engine.appc.subsystems import _is_offline, ShipSubsystem


def _sub(condition, max_condition=100.0, disabled_percentage=0.5):
    s = ShipSubsystem("test")
    s._max_condition = float(max_condition)
    s._condition = float(condition)
    s._disabled_percentage = float(disabled_percentage)
    return s


def test_none_returns_false():
    assert _is_offline(None) is False


def test_healthy_returns_false():
    assert _is_offline(_sub(condition=100.0)) is False


def test_disabled_returns_true():
    # disabled_percentage 0.5 of max 100 -> threshold 50, condition 40 is disabled
    assert _is_offline(_sub(condition=40.0)) is True


def test_destroyed_returns_true():
    assert _is_offline(_sub(condition=0.0)) is True


def test_explicit_disabled_flag_returns_true():
    s = _sub(condition=100.0)
    s.SetDamaged(False)
    # SetDestroyed flips IsDestroyed -> _is_offline True via the destroy branch.
    s.SetDestroyed(True)
    assert _is_offline(s) is True


def test_repair_lifts_offline():
    s = _sub(condition=40.0)
    assert _is_offline(s) is True
    s.SetCondition(100.0)
    assert _is_offline(s) is False
