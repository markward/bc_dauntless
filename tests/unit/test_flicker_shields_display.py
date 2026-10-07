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


# --- The HUD follows the panes ------------------------------------------
# BC's TOP_PANE holds the TOP, FRONT, REAR, LEFT and RIGHT shield icons and
# BOTTOM_PANE holds BOTTOM (Tactical/Interface/ShieldsDisplay.py:Create);
# SHIP_ICON is a sibling of both, so the silhouette never flickers.

def _payload_state(panel):
    import json
    script = panel.render_payload()
    if script is None:
        return None
    prefix = "setShipDisplay(" + json.dumps(panel._role) + ", "
    assert script.startswith(prefix)
    return json.loads(script[len(prefix):-2])


def _flicker_setup(monkeypatch, panel):
    import Actions.ShipScriptActions as ssa
    from tests.unit.test_ship_display_panel import _setup_game_with_player

    class _TCW:
        def GetShipDisplay(self):
            return panel

    monkeypatch.setattr(App, "TacticalControlWindow_GetTacticalControlWindow",
                        lambda: _TCW())
    _setup_game_with_player()
    return ssa


def test_payload_carries_hidden_panes_through_a_flicker(monkeypatch):
    from tests.helpers import headless_mission as hm
    from tests.unit.test_ship_display_panel import _teardown_game
    panel = ShipDisplayPanel("player")
    ssa = _flicker_setup(monkeypatch, panel)
    try:
        before = _payload_state(panel)
        assert before["shields_hidden"] == {"top_pane": False, "bottom_pane": False}
        assert panel.render_payload() is None

        ssa.FlickerShields(None, 0, 1)
        hidden = _payload_state(panel)
        assert hidden is not None, "hiding the panes must re-push the panel"
        assert hidden["shields_hidden"] == {"top_pane": True, "bottom_pane": True}
        assert panel.render_payload() is None

        hm.tick(1.5)
        shown = _payload_state(panel)
        assert shown is not None, "restoring the panes must re-push the panel"
        assert shown["shields_hidden"] == {"top_pane": False, "bottom_pane": False}
    finally:
        _teardown_game()


def test_each_pane_reports_independently():
    from tests.unit.test_ship_display_panel import (
        _setup_game_with_player, _teardown_game)
    _setup_game_with_player()
    try:
        panel = ShipDisplayPanel("player")
        _payload_state(panel)
        top, bottom = _panes(panel.GetShieldsDisplay())
        bottom.SetNotVisible()
        state = _payload_state(panel)
        assert state["shields_hidden"] == {"top_pane": False, "bottom_pane": True}
    finally:
        _teardown_game()


def test_target_display_never_flickers():
    from tests.unit.test_ship_display_panel import (
        _setup_game_with_player, _teardown_game)
    _setup_game_with_player()
    try:
        panel = ShipDisplayPanel("target")
        _payload_state(panel)
        top, bottom = _panes(panel.GetShieldsDisplay())
        top.SetNotVisible()
        bottom.SetNotVisible()
        assert panel.render_payload() is None
    finally:
        _teardown_game()


def test_render_payload_does_not_touch_the_panes():
    from tests.unit.test_ship_display_panel import (
        _setup_game_with_player, _teardown_game)
    _setup_game_with_player()
    try:
        panel = ShipDisplayPanel("player")
        top, bottom = _panes(panel.GetShieldsDisplay())
        top.SetNotVisible()
        panel.render_payload()
        panel.render_payload()
        assert not top.IsVisible() and bottom.IsVisible()
    finally:
        _teardown_game()
