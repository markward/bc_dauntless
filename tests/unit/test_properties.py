import pytest
from engine.appc.properties import TGModelProperty


def test_name_storage():
    p = TGModelProperty("Hull")
    assert p.GetName() == "Hull"
    p.SetName("New Hull")
    assert p.GetName() == "New Hull"


def test_bool_is_true():
    p = TGModelProperty("X")
    assert bool(p) is True


def test_repr_contains_class_and_name():
    p = TGModelProperty("Hull")
    assert "TGModelProperty" in repr(p)
    assert "Hull" in repr(p)


def test_data_bag_single_arg():
    p = TGModelProperty("X")
    p.SetMaxCondition(5000)
    assert p.GetMaxCondition() == 5000


def test_data_bag_multi_arg():
    p = TGModelProperty("X")
    p.SetMaxShields(0, 4500.0)
    p.SetMaxShields(1, 3000.0)
    assert p.GetMaxShields(0) == 4500.0
    assert p.GetMaxShields(1) == 3000.0


def test_data_bag_unknown_returns_none():
    p = TGModelProperty("X")
    assert p.GetMaxCondition() is None
    assert p.GetMaxShields(0) is None


def test_unknown_attribute_raises():
    p = TGModelProperty("X")
    with pytest.raises(AttributeError):
        p.NotASetterOrGetter
