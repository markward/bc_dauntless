"""Tests for weapon firing-chain state and group resolution.

Covers WeaponSystem._firing_chain_mode, _group_fire_mode, _last_group_fired,
_target_list, and the resolution helpers _active_chain_groups() and
_resolve_working_group().
"""

import pytest
from engine.appc.weapon_subsystems import WeaponSystem, PhaserBank
from engine.appc.properties import WeaponSystemProperty


def _system_with_chains(raw="0;Single;123;Dual;53;Quad"):
    sys_ = WeaponSystem("Torpedoes")
    prop = WeaponSystemProperty("Torpedoes")
    prop.SetFiringChainString(raw)
    sys_.SetProperty(prop)
    return sys_


def test_chain_mode_clamps_to_chain_count():
    sys_ = _system_with_chains()
    sys_.SetFiringChainMode(2)
    assert sys_.GetFiringChainMode() == 2
    sys_.SetFiringChainMode(99)          # BC clamps below chain count
    assert sys_.GetFiringChainMode() == 2
    sys_.SetFiringChainMode(-1)
    assert sys_.GetFiringChainMode() == 0


def test_active_chain_groups_ordered_and_group0_fallback():
    sys_ = _system_with_chains()
    sys_.SetFiringChainMode(2)           # "Quad" -> [5, 3] (authored order)
    assert sys_._active_chain_groups() == [5, 3]
    bare = WeaponSystem("NoChains")      # no property / empty chain string
    assert bare._active_chain_groups() == [0]


def test_resolve_working_group_resume_semantics():
    sys_ = _system_with_chains()
    sys_.SetFiringChainMode(1)           # "Dual" -> [1, 2, 3]
    assert sys_._resolve_working_group() == 1        # sentinel -> first group
    sys_._last_group_fired = 2
    assert sys_._resolve_working_group() == 2        # resume last-fired
    sys_._last_group_fired = 7                       # no longer in the chain
    assert sys_._resolve_working_group() == 1        # fall back to first


def test_target_list_prunes_dead():
    class _T:
        def __init__(self, dead): self._dead = dead
        def IsDead(self): return self._dead
    sys_ = _system_with_chains()
    live, dead = _T(False), _T(True)
    sys_._add_target(live); sys_._add_target(dead); sys_._add_target(live)
    assert sys_.GetNumTargets() == 2      # deduped
    sys_._prune_targets()
    assert sys_.GetNumTargets() == 1


def test_phaser_bank_is_member_of_group():
    """PhaserBank derives from WeaponSystem and should inherit IsMemberOfGroup."""
    bank = PhaserBank("b")
    # Group 0 is always a member
    assert bank.IsMemberOfGroup(0) == 1
    # With no property, should not be member of group 1+
    assert bank.IsMemberOfGroup(1) == 0
    # Set groups bitmask
    prop = bank.GetProperty()
    if prop is None:
        from engine.appc.properties import WeaponProperty
        prop = WeaponProperty("b")
        bank.SetProperty(prop)
    prop.SetGroups(1)  # bit 0 set -> group 1 member
    assert bank.IsMemberOfGroup(1) == 1
    assert bank.IsMemberOfGroup(2) == 0
    # Set bit 1 for group 2
    prop.SetGroups(2)
    assert bank.IsMemberOfGroup(1) == 0
    assert bank.IsMemberOfGroup(2) == 1
