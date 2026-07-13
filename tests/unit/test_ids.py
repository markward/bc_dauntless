import pytest
from engine.core.ids import TGObject, get_object_by_id


def test_unique_ids():
    a = TGObject()
    b = TGObject()
    assert a.GetObjID() != b.GetObjID()


def test_id_nonzero():
    obj = TGObject()
    assert obj.GetObjID() != 0


def test_registry_lookup():
    obj = TGObject()
    assert get_object_by_id(obj.GetObjID()) is obj


def test_registry_miss_returns_none():
    assert get_object_by_id(999999) is None


def test_private_attribute_raises_attributeerror():
    """A single-underscore name is OUR OWN Python internal, never engine
    surface: zero of the 36,538 method rows in the q13b live dump of the real
    BC engine start with an underscore. Stubbing one is always a bug — it makes
    hasattr() vacuously true and getattr(obj, name, default) never reach its
    default. See docs/stub_heatmap.md."""
    obj = TGObject()
    with pytest.raises(AttributeError):
        obj._drift_velocity
    assert getattr(obj, "_drift_velocity", None) is None
    assert not hasattr(obj, "_clip")


def test_engine_surface_names_still_stub():
    """Non-underscore (real SWIG surface) names keep the recursive stub, so SDK
    scripts can still chain calls into unimplemented engine methods."""
    obj = TGObject()
    assert obj.GetFriendlyGroup().AddName("x") is not None
    assert hasattr(obj, "SomeUnimplementedEngineCall")
