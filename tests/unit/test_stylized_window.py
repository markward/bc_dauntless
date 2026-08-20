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


def test_parent_layout_does_not_explode_on_stylized_window_children():
    """A parent TGPane's Layout() must survive a stylized-window child.

    _STStylizedWindow inherits TGPane (deliberately, so TGPane_Cast succeeds)
    but stores _children as BARE objects, and overrides Layout() to a no-op.
    It did NOT override the private recursion hook _layout_children(), and
    TGPane._layout_children recurses with `child._layout_children()` -- NOT
    `child.Layout()` -- for every isinstance(child, TGPane). So the inherited
    triple-unpack `for child, _x, _y in self._children` ran against the flat
    list and raised:

        TypeError: cannot unpack non-iterable STRoundedButton object

    Live repro: QuickBattle.SelectShipType:2611 calls g_pPane.Layout(); the
    exception aborted the WHOLE layout pass, so siblings after the stylized
    window were never laid out either.
    """
    from engine.appc.tg_ui.widgets import TGPane
    from engine.appc.tg_ui.st_widgets import STRoundedButton

    root = TGPane(800.0, 600.0)
    mid = TGPane(400.0, 300.0)
    window = _STStylizedWindow("Ships")
    button = STRoundedButton("Add Friend")

    root.AddChild(mid, 10.0, 20.0)
    mid.AddChild(window, 5.0, 5.0)
    window.AddChild(button, 0.0, 0.0)      # flat append -- the window's contract

    root.Layout()                          # must not raise

    # The sibling-starvation half of the bug: a pane added AFTER the stylized
    # window must still get an absolute rect.
    sibling = TGPane(50.0, 50.0)
    mid.AddChild(sibling, 7.0, 9.0)
    root.Layout()
    assert sibling._abs_rect is not None, "sibling after a stylized window was skipped"


# ── Inherited-TGPane-method family (same root cause as the layout crash) ─────
# _children is FLAT here, so every TGPane method that assumes (child, x, y)
# triples is a latent crash or a silent corruption. _layout_children was the
# one that fired live; these three are the rest of the family.

def test_delete_child_removes_from_flat_children():
    """Inherited TGPane.DeleteChild unpacks triples -> TypeError on our flat
    list, the same failure mode as the layout crash."""
    w = _STStylizedWindow("W")
    a, b = object(), object()
    w.AddChild(a)
    w.AddChild(b)

    w.DeleteChild(a)

    assert w.GetNumChildren() == 1
    assert w.GetFirstChild() is b


def test_delete_child_of_absent_child_is_a_no_op():
    w = _STStylizedWindow("W")
    a = object()
    w.AddChild(a)

    w.DeleteChild(object())          # never added

    assert w.GetNumChildren() == 1
    assert w.GetFirstChild() is a


def test_insert_child_stores_bare_child_not_a_triple():
    """Inherited TGPane.InsertChild appends a TRIPLE into the flat list. That
    does not raise at call time -- it silently corrupts the list, so the crash
    surfaces later and far away (GetFirstChild returns a tuple, DeleteChild
    blows up). Assert the stored shape, not just the ordering."""
    w = _STStylizedWindow("W")
    a, c = object(), object()
    w.AddChild(a)
    w.AddChild(c)

    b = object()
    w.InsertChild(1, b)

    assert [w.GetNthChild(i) for i in range(3)] == [a, b, c]
    assert w._children == [a, b, c], (
        "children must be stored bare, not as (child, x, y): %r" % (w._children,)
    )


def test_get_children_returns_bare_children():
    """Regression pin, NOT a bug fix: unlike DeleteChild/InsertChild, the
    inherited TGPane.GetChildren is already correct here by construction --
    it is `list(self._children)`, and list() of a flat list is a flat copy.
    Pinned so a future change to TGPane.GetChildren (e.g. building explicit
    triples) cannot silently change the shape this class hands back."""
    w = _STStylizedWindow("W")
    a, b = object(), object()
    w.AddChild(a)
    w.AddChild(b)

    assert w.GetChildren() == [a, b]


def test_get_children_returns_a_copy():
    """Mutating the returned list must not corrupt the window's own state."""
    w = _STStylizedWindow("W")
    a = object()
    w.AddChild(a)

    got = w.GetChildren()
    got.append(object())

    assert w.GetNumChildren() == 1
