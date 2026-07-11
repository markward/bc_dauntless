"""Task 5b: the officer-menu window resolves its on-screen rect from SDK geometry.

The SDK's Tactical/Interface/TacticalControlWindow.RepositionUI() positions the
officer-menu window (InterfacePane.GetNthChild(TACTICAL_MENU)) via SetPosition(0,0)
and ends with pTacCtrlWindow.Layout(). host_loop.resolve_officer_menu_layout() runs
that SDK layout on mission-load so the window's _abs_rect resolves (GetScreenOffset
stops raising LayoutNotResolved). Geometry is asserted against the SDK LCARS module,
never a bare literal.
"""
import App
import pytest

import Tactical.Interface.TacticalControlWindow as TCWmod
from engine.appc.windows import TacticalControlWindow, INTERFACE_PANE, TACTICAL_MENU
from engine.appc.tg_ui.layout import LayoutNotResolved
from engine.host_loop import resolve_officer_menu_layout


def _fresh_tcw():
    """Drop the singleton so each test builds the tactical control window clean."""
    TacticalControlWindow._instance = None
    return App.TacticalControlWindow_GetTacticalControlWindow()


def _officer_menu_window(tcw):
    ipane = tcw.GetNthChild(INTERFACE_PANE)
    assert ipane is not None, "interface pane not built"
    return ipane.GetNthChild(TACTICAL_MENU)


def _expected_menu_width():
    LCARS = __import__(App.GraphicsModeInfo_GetCurrentMode().GetLcarsModule())
    return LCARS.TACTICAL_MENU_WIDTH  # 146 / SCREEN_PIXEL_WIDTH ≈ 0.1426


def test_tcw_layout_resolves_the_officer_menu_window():
    """The mechanism: a stylized officer-menu window under an interface pane is
    unresolved (GetScreenOffset raises) until TacticalControlWindow.Layout()
    runs the resolver over it; then its rect matches the SDK geometry."""
    from engine.appc.windows import _STStylizedWindow
    from engine.appc.tg_ui.widgets import TGPane_Create

    tcw = _fresh_tcw()
    LCARS = __import__(App.GraphicsModeInfo_GetCurrentMode().GetLcarsModule())

    # Mirror TacticalMenuHandlers.CreateMenus structure minimally: an interface
    # pane sized to the screen, holding the officer-menu window at slot 0.
    ipane = TGPane_Create(LCARS.SCREEN_WIDTH, LCARS.SCREEN_HEIGHT)
    omw = _STStylizedWindow("Tactical")
    omw.SetMaximumSize(LCARS.TACTICAL_MENU_WIDTH + omw.GetBorderWidth(),
                       LCARS.TACTICAL_MENU_HEIGHT + omw.GetBorderHeight())
    ipane.AddChild(omw, 0.0, 0.0, 0)           # AddChild seeds local (0,0)
    tcw.AddChild(ipane, 0.0, 0.0, 0)

    # RED: no Layout() pass has reached the window yet.
    assert omw.__dict__.get("_abs_rect") is None
    with pytest.raises(LayoutNotResolved):
        omw.GetScreenOffset()

    # GREEN: the resolver caches an absolute rect from the recorded SDK geometry.
    tcw.Layout()
    rect = omw.__dict__.get("_abs_rect")
    assert rect is not None
    assert rect.left == pytest.approx(0.0)
    assert rect.top == pytest.approx(0.0)
    assert rect.width == pytest.approx(_expected_menu_width())
    off = omw.GetScreenOffset()
    assert (off.x, off.y) == pytest.approx((0.0, 0.0))


def test_dev_picker_path_builds_and_resolves():
    """Dev-mission-picker path: no interface pane yet → CreateMenus + resolve."""
    tcw = _fresh_tcw()
    assert tcw.GetNthChild(INTERFACE_PANE) is None  # menus not built

    resolve_officer_menu_layout()

    omw = _officer_menu_window(tcw)
    assert omw is not None
    rect = omw.__dict__.get("_abs_rect")
    assert rect is not None, "officer-menu window did not resolve a rect"
    # SDK SetPosition(0.0, 0.0) → top-left at the interface-pane origin.
    assert rect.left == pytest.approx(0.0)
    assert rect.top == pytest.approx(0.0)
    # Width comes from SDK SetMaximumSize(TACTICAL_MENU_WIDTH + border, ...).
    assert rect.width > 0.0
    assert rect.width == pytest.approx(_expected_menu_width())

    off = omw.GetScreenOffset()  # must not raise
    assert off.x == pytest.approx(0.0)
    assert off.y == pytest.approx(0.0)


def test_campaign_path_resolves_after_createmenus():
    """Campaign/QB path: LoadBridge.Load already ran CreateMenus; resolve is idempotent."""
    tcw = _fresh_tcw()
    import Bridge.TacticalMenuHandlers as TMH
    TMH.CreateMenus()  # stands in for LoadBridge.Load

    resolve_officer_menu_layout()

    omw = _officer_menu_window(tcw)
    rect = omw.__dict__.get("_abs_rect")
    assert rect is not None
    assert rect.left == pytest.approx(0.0)
    assert rect.top == pytest.approx(0.0)
    assert rect.width == pytest.approx(_expected_menu_width())
    off = omw.GetScreenOffset()
    assert off.x == pytest.approx(0.0)
    assert off.y == pytest.approx(0.0)


def test_no_tcw_is_a_noop():
    """A missing TCW must not raise — resolve is a guarded best-effort hook."""
    TacticalControlWindow._instance = None
    # No GetInstance() call → _instance stays None; guard must short-circuit.
    import engine.appc.windows as W
    saved = W.TacticalControlWindow._instance
    try:
        W.TacticalControlWindow._instance = None
        # Monkeypatch the getter to return None to exercise the guard.
        import App as _App
        orig = _App.TacticalControlWindow_GetTacticalControlWindow
        _App.TacticalControlWindow_GetTacticalControlWindow = lambda: None
        try:
            resolve_officer_menu_layout()  # must not raise
        finally:
            _App.TacticalControlWindow_GetTacticalControlWindow = orig
    finally:
        W.TacticalControlWindow._instance = saved
