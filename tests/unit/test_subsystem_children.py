"""ShipSubsystem child-list storage — replaces the always-0/None stubs.

SDK semantics (App.py:5645+): subsystems form a parent/child tree.
WeaponSystemProperty(WST_TRACTOR) is the parent; each TractorBeamProperty
is a child.  AddChildSubsystem appends and sets the parent back-ref;
GetChildSubsystem(index|name|None) is the SDK-compatible getter.
"""
from engine.appc.subsystems import ShipSubsystem


def test_new_subsystem_has_no_children():
    s = ShipSubsystem("parent")
    assert s.GetNumChildSubsystems() == 0


def test_add_child_appends_and_counts():
    parent = ShipSubsystem("parent")
    a = ShipSubsystem("a")
    b = ShipSubsystem("b")
    parent.AddChildSubsystem(a)
    parent.AddChildSubsystem(b)
    assert parent.GetNumChildSubsystems() == 2


def test_add_child_sets_parent_back_reference():
    parent = ShipSubsystem("parent")
    child = ShipSubsystem("child")
    parent.AddChildSubsystem(child)
    assert child.GetParentSubsystem() is parent


def test_get_child_by_index_returns_child():
    parent = ShipSubsystem("parent")
    a = ShipSubsystem("a")
    b = ShipSubsystem("b")
    parent.AddChildSubsystem(a)
    parent.AddChildSubsystem(b)
    assert parent.GetChildSubsystem(0) is a
    assert parent.GetChildSubsystem(1) is b


def test_get_child_out_of_range_returns_none():
    parent = ShipSubsystem("parent")
    parent.AddChildSubsystem(ShipSubsystem("a"))
    assert parent.GetChildSubsystem(5) is None
    assert parent.GetChildSubsystem(-1) is None


def test_get_child_by_name_returns_matching_child():
    parent = ShipSubsystem("parent")
    a = ShipSubsystem("Aft Tractor 1")
    b = ShipSubsystem("Forward Tractor 1")
    parent.AddChildSubsystem(a)
    parent.AddChildSubsystem(b)
    assert parent.GetChildSubsystem("Forward Tractor 1") is b


def test_get_child_by_name_unknown_returns_none():
    parent = ShipSubsystem("parent")
    parent.AddChildSubsystem(ShipSubsystem("a"))
    assert parent.GetChildSubsystem("unknown") is None


def test_get_child_no_arg_returns_none_for_backwards_compat():
    """The original stub took no arguments and returned None; some SDK
    iterators rely on the zero-arg overload."""
    parent = ShipSubsystem("parent")
    parent.AddChildSubsystem(ShipSubsystem("a"))
    assert parent.GetChildSubsystem() is None
