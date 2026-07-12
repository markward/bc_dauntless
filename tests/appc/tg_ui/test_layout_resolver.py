from engine.appc.tg_ui.widgets import TGPane


class _Pt:
    def __init__(self): self.x = 0.0; self.y = 0.0


def test_setposition_then_layout_resolves_absolute():
    root = TGPane(1.0, 1.0)
    child = TGPane(0.2, 0.1)
    root.AddChild(child, 0.0, 0.0)
    child.SetPosition(0.3, 0.4, 0)
    root.Layout()
    off = _Pt(); child.GetScreenOffset(off)
    assert abs(off.x - 0.3) < 1e-9
    assert abs(off.y - 0.4) < 1e-9
    assert abs(child.GetLeft() - 0.3) < 1e-9


def test_nested_offsets_accumulate():
    root = TGPane(1.0, 1.0)
    mid = TGPane(0.5, 0.5); leaf = TGPane(0.1, 0.1)
    root.AddChild(mid, 0.1, 0.2)
    mid.AddChild(leaf, 0.05, 0.05)
    root.Layout()
    off = _Pt(); leaf.GetScreenOffset(off)
    assert abs(off.x - 0.15) < 1e-9
    assert abs(off.y - 0.25) < 1e-9


def test_move_accumulates():
    root = TGPane(1.0, 1.0); child = TGPane(0.1, 0.1)
    root.AddChild(child, 0.0, 0.0)
    child.SetPosition(0.1, 0.1, 0); child.Move(0.05, 0.0, 0)
    root.Layout()
    off = _Pt(); child.GetScreenOffset(off)
    assert abs(off.x - 0.15) < 1e-9


def test_unresolved_falls_back_to_local_placement():
    # GetScreenOffset must never raise onto an SDK call path (BC's own
    # script-action convention: "Return 0 to keep calling sequence from
    # crashing"). This used to raise LayoutNotResolved for any pane with no
    # _abs_rect — that's what killed E1M1's crew-intro sequence when it
    # called MissionLib.MoveMouseCursorToUIObject(App.g_kRootWindow, ...) on
    # a TGPane nothing ever laid out. A never-laid-out pane now falls back
    # to its local placement (0.0, 0.0 by default) instead of raising.
    orphan = TGPane(0.1, 0.1)
    out = _Pt()
    result = orphan.GetScreenOffset(out)
    assert (out.x, out.y) == (0.0, 0.0)
    assert result is out

    # Same fallback on the no-arg (return-a-point) call shape.
    pt = TGPane(0.1, 0.1).GetScreenOffset()
    assert (pt.x, pt.y) == (0.0, 0.0)


def test_unresolved_falls_back_to_nonzero_local_placement():
    # The fallback reads the widget's own _local_left/_local_top, not a
    # hardcoded 0.0 — prove it's not a fabricated constant.
    orphan = TGPane(0.1, 0.1)
    orphan.SetPosition(0.3, 0.4, 0)   # local placement only, no Layout()
    out = _Pt()
    orphan.GetScreenOffset(out)
    assert (out.x, out.y) == (0.3, 0.4)
