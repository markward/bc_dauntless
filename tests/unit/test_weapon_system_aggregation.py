"""WeaponSystem parents aggregate their children's damage state.

Locked semantics (combat damage pipeline roadmap):
  IsDamaged   = any(child.IsDamaged()   for child in children)
  IsDisabled  = bool(children) and all(child.IsDisabled()  for child in children)
  IsDestroyed = bool(children) and all(child.IsDestroyed() for child in children)

Empty-children parents report all zeros (no hardpoints == no row).
Run for all four WeaponSystem subclasses to confirm the override on the
base class flows through every concrete weapon system.
"""
import pytest

from engine.appc.subsystems import (
    PhaserBank, PhaserSystem, PulseWeapon, PulseWeaponSystem,
    TorpedoSystem, TorpedoTube, TractorBeam, TractorBeamSystem,
)


# (parent_cls, child_cls) pairs covering every WeaponSystem subclass.
WEAPON_FAMILIES = [
    (PhaserSystem, PhaserBank),
    (TorpedoSystem, TorpedoTube),
    (PulseWeaponSystem, PulseWeapon),
    (TractorBeamSystem, TractorBeam),
]


def _make_child(cls, name, max_condition=100.0, condition=None,
                disabled_percentage=0.25):
    child = cls(name)
    child._max_condition = float(max_condition)
    child._condition = float(condition if condition is not None
                             else max_condition)
    child._disabled_percentage = float(disabled_percentage)
    return child


@pytest.mark.parametrize("parent_cls,child_cls", WEAPON_FAMILIES)
def test_empty_children_all_zero(parent_cls, child_cls):
    parent = parent_cls("Parent")
    assert parent.IsDamaged() == 0
    assert parent.IsDisabled() == 0
    assert parent.IsDestroyed() == 0


@pytest.mark.parametrize("parent_cls,child_cls", WEAPON_FAMILIES)
def test_any_damaged_child_makes_parent_damaged(parent_cls, child_cls):
    parent = parent_cls("Parent")
    parent.AddChildSubsystem(_make_child(child_cls, "A", condition=50.0))
    parent.AddChildSubsystem(_make_child(child_cls, "B", condition=100.0))
    assert parent.IsDamaged() == 1
    assert parent.IsDisabled() == 0
    assert parent.IsDestroyed() == 0


@pytest.mark.parametrize("parent_cls,child_cls", WEAPON_FAMILIES)
def test_all_disabled_children_make_parent_disabled(parent_cls, child_cls):
    parent = parent_cls("Parent")
    # disabled_percentage 0.25 means condition <= 25.0 == disabled.
    parent.AddChildSubsystem(_make_child(child_cls, "A", condition=10.0))
    parent.AddChildSubsystem(_make_child(child_cls, "B", condition=20.0))
    assert parent.IsDisabled() == 1
    assert parent.IsDamaged() == 1
    assert parent.IsDestroyed() == 0
    # Add a healthy sibling: parent flips back to not-disabled.
    parent.AddChildSubsystem(_make_child(child_cls, "C", condition=100.0))
    assert parent.IsDisabled() == 0


@pytest.mark.parametrize("parent_cls,child_cls", WEAPON_FAMILIES)
def test_all_destroyed_children_make_parent_destroyed(parent_cls, child_cls):
    parent = parent_cls("Parent")
    parent.AddChildSubsystem(_make_child(child_cls, "A", condition=0.0))
    parent.AddChildSubsystem(_make_child(child_cls, "B", condition=0.0))
    assert parent.IsDestroyed() == 1
    assert parent.IsDisabled() == 1
    assert parent.IsDamaged() == 1
    # Add a healthy sibling: parent flips back to not-destroyed.
    parent.AddChildSubsystem(_make_child(child_cls, "C", condition=100.0))
    assert parent.IsDestroyed() == 0


@pytest.mark.parametrize("parent_cls,child_cls", WEAPON_FAMILIES)
def test_mixed_damaged_and_destroyed(parent_cls, child_cls):
    parent = parent_cls("Parent")
    parent.AddChildSubsystem(_make_child(child_cls, "A", condition=50.0))  # damaged
    parent.AddChildSubsystem(_make_child(child_cls, "B", condition=0.0))   # destroyed
    assert parent.IsDamaged() == 1
    assert parent.IsDestroyed() == 0   # not ALL destroyed
    assert parent.IsDisabled() == 0    # not ALL disabled
