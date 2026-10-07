"""Actions.ShipScriptActions.FlickerShields against the player's
ShieldsDisplay: BC's pane tree, at BC's measured indices
(ShieldsDisplay DISPLAY_PANE=0; inside it TOP_PANE=0, SHIP_ICON=1,
BOTTOM_PANE=2 -- engine/appc/constants_generated.py)."""
import App

from engine.ui.ship_display_panel import ShipDisplayPanel


def _panes(display):
    pane = App.TGPane_Cast(display.GetNthChild(display.DISPLAY_PANE))
    return pane.GetNthChild(display.TOP_PANE), pane.GetNthChild(display.BOTTOM_PANE)


def test_shields_display_has_bcs_pane_tree():
    display = ShipDisplayPanel("player").GetShieldsDisplay()
    assert (display.DISPLAY_PANE, display.TOP_PANE,
            display.SHIP_ICON, display.BOTTOM_PANE) == (0, 0, 1, 2)
    pane = App.TGPane_Cast(display.GetNthChild(display.DISPLAY_PANE))
    assert pane is not None
    top, bottom = _panes(display)
    assert top is not None and bottom is not None and top is not bottom
    assert top.IsVisible() and bottom.IsVisible()


def test_flicker_shields_hides_then_restores_the_panes(monkeypatch):
    import Actions.ShipScriptActions as ssa
    from tests.helpers import headless_mission as hm
    panel = ShipDisplayPanel("player")

    class _TCW:
        def GetShipDisplay(self):
            return panel

    monkeypatch.setattr(App, "TacticalControlWindow_GetTacticalControlWindow",
                        lambda: _TCW())
    top, bottom = _panes(panel.GetShieldsDisplay())
    assert ssa.FlickerShields(None, 0, 1) == 0
    assert not top.IsVisible() and not bottom.IsVisible()
    hm.tick(1.5)
    assert top.IsVisible() and bottom.IsVisible()
