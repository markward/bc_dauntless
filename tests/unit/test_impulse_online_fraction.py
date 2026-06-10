"""impulse_online_fraction: online-pod ratio that drives flight degradation."""
from engine.appc.subsystems import (
    impulse_online_fraction, ImpulseEngineSubsystem, ShipSubsystem,
)


def _pod(name, max_condition=100.0, disabled_pct=0.5):
    p = ShipSubsystem(name)
    p.SetMaxCondition(max_condition)
    p.SetDisabledPercentage(disabled_pct)
    p.SetCondition(max_condition)
    return p


def _master_with_pods(n):
    ies = ImpulseEngineSubsystem("Impulse Engines")
    ies.SetMaxCondition(100.0)
    ies.SetDisabledPercentage(0.5)
    ies.SetCondition(100.0)
    for i in range(n):
        ies.AddChildSubsystem(_pod("pod%d" % i))
    return ies


def test_none_ies_returns_full():
    assert impulse_online_fraction(None) == 1.0


def test_no_pods_returns_full():
    assert impulse_online_fraction(_master_with_pods(0)) == 1.0


def test_all_pods_online_returns_full():
    assert impulse_online_fraction(_master_with_pods(4)) == 1.0


def test_three_of_four_offline_returns_quarter():
    ies = _master_with_pods(4)
    for i in range(3):
        ies.GetChildSubsystem(i).SetCondition(0.0)
    assert impulse_online_fraction(ies) == 0.25


def test_all_pods_offline_returns_zero():
    ies = _master_with_pods(3)
    for i in range(3):
        ies.GetChildSubsystem(i).SetCondition(0.0)
    assert impulse_online_fraction(ies) == 0.0


def test_master_offline_forces_zero_even_with_online_pods():
    ies = _master_with_pods(4)        # all pods healthy
    ies.SetCondition(0.0)             # but master itself disabled
    assert impulse_online_fraction(ies) == 0.0
