"""TGModelProperty.SetPhysicalParent / GetPhysicalParent (physical-parents spec).

A real method on the base class, so the value never lands in the ``_data``
bag that ``__getattr__`` fills for unknown Set*/Get* names.
"""
from engine.appc.properties import TGModelProperty, BlinkingLightProperty


class _StrSub(str):
    pass


def test_unset_is_none():
    assert TGModelProperty("Port Cannon").GetPhysicalParent() is None


def test_set_then_get():
    p = TGModelProperty("Port Cannon")
    p.SetPhysicalParent("left wing")
    assert p.GetPhysicalParent() == "left wing"


def test_none_unsets():
    p = TGModelProperty("Port Cannon")
    p.SetPhysicalParent("left wing")
    p.SetPhysicalParent(None)
    assert p.GetPhysicalParent() is None


def test_is_a_real_method_not_the_data_bag():
    p = TGModelProperty("x")
    p.SetPhysicalParent("hull")
    assert "PhysicalParent" not in {k[0] for k in p._data}
    assert "SetPhysicalParent" in TGModelProperty.__dict__


def test_running_light_inherits_it():
    p = BlinkingLightProperty("Nav 1")
    p.SetPhysicalParent("wing left")
    assert p.GetPhysicalParent() == "wing left"


def test_value_is_coerced_to_plain_str():
    p = TGModelProperty("x")
    p.SetPhysicalParent(_StrSub("hull"))
    assert type(p.GetPhysicalParent()) is str
