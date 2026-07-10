import pytest

from engine.core import stub_telemetry
from engine.core.ids import TGObject, _Stub


@pytest.fixture(autouse=True)
def _clean_telemetry():
    prev = stub_telemetry.ENABLED
    stub_telemetry.reset()
    yield
    stub_telemetry.set_enabled(prev)
    stub_telemetry.reset()


def test_stub_still_truthy_and_chainable_when_disabled():
    stub_telemetry.set_enabled(False)
    obj = TGObject()
    stub = obj.SomeUnimplementedMethod()  # falls through __getattr__ then __call__
    assert bool(stub) is True                 # truthiness unchanged
    assert isinstance(stub.AndThenThis(), _Stub)  # chaining unchanged
    assert stub_telemetry.snapshot()["attr_hits"] == {}


def test_object_attr_access_is_recorded_when_enabled():
    stub_telemetry.set_enabled(True)
    obj = TGObject()
    obj.GetWarpCore  # unimplemented method name
    hits = stub_telemetry.snapshot()["attr_hits"]
    assert hits.get(("TGObject", "GetWarpCore")) == 1


def test_chained_stub_access_records_with_breadcrumb():
    stub_telemetry.set_enabled(True)
    obj = TGObject()
    obj.GetFriendlyGroup().AddName  # chained access through a returned _Stub
    hits = stub_telemetry.snapshot()["attr_hits"]
    # the parent method is recorded on the owning class
    assert hits.get(("TGObject", "GetFriendlyGroup")) == 1
    # the chained access is recorded with a dotted breadcrumb
    assert any(attr.endswith(".AddName") for (_owner, attr) in hits)


def test_internal_stub_bookkeeping_attrs_do_not_recurse():
    # Accessing the private bookkeeping names must raise AttributeError,
    # not build another _Stub (which would infinite-recurse).
    s = _Stub()
    with pytest.raises(AttributeError):
        object.__getattribute__(_Stub, "_stub_name")  # class has no such attr
    # instance access resolves the value set in __init__, never __getattr__
    assert s._stub_name == "?"
    assert s._stub_owner == "?"
