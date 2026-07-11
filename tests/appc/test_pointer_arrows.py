# Ports MissionLib.ShowPointerArrow math (MissionLib.py:4444-4464) for POINTER_LEFT:
#   arrow x = offset.x + width + iconW*spacing ; y = offset.y + h/2 - iconH/2
from engine.appc.tg_ui.widgets import TGPane
from engine.appc.top_window import TopWindow_GetTopWindow


def test_prependchild_records_normalized_placement():
    top = TopWindow_GetTopWindow()
    top._arrow_placements = []
    icon = TGPane(0.02, 0.02)
    top.PrependChild(icon, 0.30, 0.40, 0)
    assert top._arrow_placements[-1][1] == 0.30
    assert top._arrow_placements[-1][2] == 0.40


def test_show_pointer_arrow_left_lands_right_of_widget():
    import App, MissionLib
    from engine.appc.tg_ui.widgets import TGPane
    top = TopWindow_GetTopWindow(); top._arrow_placements = []
    MissionLib.g_lPointerArrows = []
    widget = TGPane(0.143, 0.030)
    # place + resolve the widget at a known offset
    root = TGPane(1.0, 1.0); root.AddChild(widget, 0.0, 0.10); root.Layout()
    MissionLib.ShowPointerArrow(None, widget, MissionLib.POINTER_LEFT, 0.0, None)
    icon, x, y = top._arrow_placements[-1]
    assert abs(x - (0.0 + 0.143)) < 1e-6           # right edge of widget
    assert abs(y - (0.10 + 0.015 - icon.GetHeight() / 2.0)) < 1e-6
    assert len(MissionLib.g_lPointerArrows) == 1


def test_hide_pointer_arrows_clears():
    import MissionLib
    from engine.appc.top_window import TopWindow_GetTopWindow
    top = TopWindow_GetTopWindow()
    MissionLib.HidePointerArrows()
    assert MissionLib.g_lPointerArrows == []
    assert top._arrow_placements == []


def test_emitted_arrows_derives_direction_from_glyph_id():
    # SDK ShowPointerArrow never tags the icon with a direction attribute;
    # the direction is encoded in the icon's glyph id (220 + eDirection).
    # emitted_arrows() must recover it from GetIconID(), not a nonexistent
    # _pointer_dir attribute.
    import MissionLib
    from engine.appc.pointer_arrows import emitted_arrows
    top = TopWindow_GetTopWindow(); top._arrow_placements = []
    MissionLib.g_lPointerArrows = []
    widget = TGPane(0.143, 0.030)
    root = TGPane(1.0, 1.0); root.AddChild(widget, 0.0, 0.10); root.Layout()
    MissionLib.ShowPointerArrow(None, widget, MissionLib.POINTER_UP, 0.0, None)
    arrows = emitted_arrows()
    assert len(arrows) == 1
    assert arrows[0]["dir"] == MissionLib.POINTER_UP
    assert set(arrows[0].keys()) == {"x", "y", "w", "h", "dir"}


def test_hide_pointer_arrows_clears_via_parent_delete():
    # Exercises the actual SDK deletion path: HidePointerArrows resolves the
    # icon back through App.TGObject_GetTGObjectPtr(idArrow) and calls
    # pIcon.GetParent().DeleteChild(pIcon) — proving TopWindow.PrependChild's
    # icon._parent wiring (not a MissionLib-bypassing direct clear) is what
    # empties _arrow_placements.
    import MissionLib
    top = TopWindow_GetTopWindow(); top._arrow_placements = []
    MissionLib.g_lPointerArrows = []
    widget = TGPane(0.143, 0.030)
    root = TGPane(1.0, 1.0); root.AddChild(widget, 0.0, 0.10); root.Layout()
    MissionLib.ShowPointerArrow(None, widget, MissionLib.POINTER_LEFT, 0.0, None)
    icon, _x, _y = top._arrow_placements[-1]
    assert icon.GetParent() is top
    MissionLib.HidePointerArrows()
    assert top._arrow_placements == []
    assert MissionLib.g_lPointerArrows == []
