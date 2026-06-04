"""Unit tests for the _STStylizedWindow SDK shim (engine/appc/windows.py)."""
import pytest

from engine.appc.windows import _STStylizedWindow, STStylizedWindow_CreateW


@pytest.fixture(autouse=True)
def _reset_counter():
    _STStylizedWindow._counter = 0


def test_factory_returns_instance_with_title():
    w = STStylizedWindow_CreateW("Briefing")
    assert isinstance(w, _STStylizedWindow)
    assert w._title == "Briefing"


def test_id_increments_per_instance():
    a = STStylizedWindow_CreateW("A")
    b = STStylizedWindow_CreateW("B")
    assert a._id == "stylized-1"
    assert b._id == "stylized-2"


def test_initial_state_visible():
    w = STStylizedWindow_CreateW("X")
    assert w._visible is True
    assert w._children == []


def test_set_visible_toggle():
    w = STStylizedWindow_CreateW("X")
    w.SetNotVisible()
    assert w._visible is False
    w.SetVisible()
    assert w._visible is True


def test_add_child_records_without_x_y_validation():
    w = STStylizedWindow_CreateW("X")
    child = object()
    w.AddChild(child, 10.0, 20.0)
    assert child in w._children


def test_add_child_extra_args_accepted():
    w = STStylizedWindow_CreateW("X")
    # SDK call sites occasionally pass z or other extras; we accept *args.
    w.AddChild(object(), 0.0, 0.0, "extra", 99)


def test_get_obj_id_returns_python_id():
    w = STStylizedWindow_CreateW("X")
    assert w.GetObjID() == id(w)


def test_snapshot_shape():
    w = STStylizedWindow_CreateW("Mission Briefing")
    snap = w._snapshot()
    assert snap == {
        "type": "stylized",
        "id": "stylized-1",
        "visible": True,
        "title": "Mission Briefing",
    }


def test_snapshot_reflects_visibility():
    w = STStylizedWindow_CreateW("X")
    w.SetNotVisible()
    assert w._snapshot()["visible"] is False


def test_factory_accepts_extra_args_silently():
    # SDK signature is STStylizedWindow_CreateW(title, parent, x, y, w, h, ...).
    w = STStylizedWindow_CreateW("Title", None, 0.0, 0.0, 400, 300, 0)
    assert w._title == "Title"


def test_add_python_func_handler_for_instance_records():
    w = STStylizedWindow_CreateW("X")
    w.AddPythonFuncHandlerForInstance(7, "module.handler")
    assert w._handler_registrations == [(7, "module.handler")]


def test_add_python_func_handler_accepts_extra_args():
    w = STStylizedWindow_CreateW("X")
    # SDK chains additional positional args (priority, flags) in some forms.
    w.AddPythonFuncHandlerForInstance(7, "module.handler", "extra1", 99)
    assert len(w._handler_registrations) == 1


def test_interior_changed_size_accepts_any_args():
    w = STStylizedWindow_CreateW("X")
    w.InteriorChangedSize()         # no args
    w.InteriorChangedSize(10, 20)   # SDK sometimes passes new bounds
    # No assertion needed — must not raise.
