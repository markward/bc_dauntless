from engine.appc.tg_ui.widgets import TGPane
from engine.appc.tg_ui.layout import ALIGN_BL, ALIGN_UL


class _Pt:
    def __init__(self): self.x = 0.0; self.y = 0.0


def test_alignto_bl_to_ul_stacks_below():
    # Child B's upper-left aligns to sibling A's bottom-left -> B sits under A.
    root = TGPane(1.0, 1.0)
    a = TGPane(0.2, 0.1); b = TGPane(0.2, 0.1)
    root.AddChild(a, 0.05, 0.05)
    root.AddChild(b, 0.0, 0.0)
    b.AlignTo(a, ALIGN_UL, ALIGN_BL, 0)   # my UL to A's BL
    root.Layout()
    off = _Pt(); b.GetScreenOffset(off)
    assert abs(off.x - 0.05) < 1e-9        # same left as A
    assert abs(off.y - 0.15) < 1e-9        # A.top(0.05) + A.height(0.1)


def test_alignto_via_app_tguiobject_stacks_below():
    # Same geometry as above, but driven through App.TGUIObject.ALIGN_* --
    # the real SDK call shape (widget.AlignTo(other, App.TGUIObject.ALIGN_BL,
    # App.TGUIObject.ALIGN_UL)). Regression guard for the root App.py shim
    # binding: before that binding, App.TGUIObject was undefined and fell
    # through App's module __getattr__ to a _NamedStub whose int() == 0, so
    # BOTH anchors below would collapse to ALIGN_UL (0) regardless of which
    # constant was named. That collapses this alignment to "B's UL sits at
    # A's UL" (off.y == 0.05), not "B's UL sits at A's BL" (off.y == 0.15) --
    # this assertion is the one that would fail under the stub.
    import App

    root = TGPane(1.0, 1.0)
    a = TGPane(0.2, 0.1); b = TGPane(0.2, 0.1)
    root.AddChild(a, 0.05, 0.05)
    root.AddChild(b, 0.0, 0.0)
    b.AlignTo(a, App.TGUIObject.ALIGN_UL, App.TGUIObject.ALIGN_BL, 0)
    root.Layout()
    off = _Pt(); b.GetScreenOffset(off)
    assert abs(off.x - 0.05) < 1e-9        # same left as A
    assert abs(off.y - 0.15) < 1e-9        # A.top(0.05) + A.height(0.1)
