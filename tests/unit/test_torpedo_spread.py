"""Torpedo spread selection state on TorpedoSystem.

Spread = how many tubes fire per trigger: Single=1, Dual=2, Quad=4.
This is pure state + derivation — no firing-behaviour change. The set of
options a loadout can fire is derived from tube count (GetNumWeapons()).
"""
from engine.appc.subsystems import TorpedoSystem, TorpedoTube


def _torp_system_with_tubes(n):
    parent = TorpedoSystem("Torpedoes")
    parent.TurnOn()
    for i in range(n):
        parent.AddChildSubsystem(TorpedoTube("Torpedo %d" % i))
    return parent


def test_default_spread_is_single():
    parent = _torp_system_with_tubes(4)
    assert parent.GetSpread() == 1


def test_options_one_tube():
    parent = _torp_system_with_tubes(1)
    assert parent.GetSpreadOptions() == [1]


def test_options_two_tubes():
    parent = _torp_system_with_tubes(2)
    assert parent.GetSpreadOptions() == [1, 2]


def test_options_three_tubes_still_dual_max():
    parent = _torp_system_with_tubes(3)
    assert parent.GetSpreadOptions() == [1, 2]


def test_options_four_tubes():
    parent = _torp_system_with_tubes(4)
    assert parent.GetSpreadOptions() == [1, 2, 4]


def test_options_five_tubes_still_quad_max():
    parent = _torp_system_with_tubes(5)
    assert parent.GetSpreadOptions() == [1, 2, 4]


def test_set_spread_dual_on_two_tube_system():
    parent = _torp_system_with_tubes(2)
    parent.SetSpread(2)
    assert parent.GetSpread() == 2


def test_set_spread_quad_ignored_on_two_tube_system():
    parent = _torp_system_with_tubes(2)
    parent.SetSpread(2)
    parent.SetSpread(4)  # 4 not a supported option — ignored
    assert parent.GetSpread() == 2


def test_set_spread_quad_on_four_tube_system():
    parent = _torp_system_with_tubes(4)
    parent.SetSpread(2)
    parent.SetSpread(4)
    assert parent.GetSpread() == 4


def test_set_spread_coerces_to_int():
    parent = _torp_system_with_tubes(4)
    parent.SetSpread(2.0)
    assert parent.GetSpread() == 2
