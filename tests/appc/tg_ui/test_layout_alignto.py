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
