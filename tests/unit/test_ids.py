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
