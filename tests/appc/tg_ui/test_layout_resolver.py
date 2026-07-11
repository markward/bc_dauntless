import pytest
from engine.appc.tg_ui.widgets import TGPane
from engine.appc.tg_ui.layout import LayoutNotResolved


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


def test_unresolved_raises_not_zero():
    orphan = TGPane(0.1, 0.1)
    with pytest.raises(LayoutNotResolved):
        orphan.GetScreenOffset(_Pt())
