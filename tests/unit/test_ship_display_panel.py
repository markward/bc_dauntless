"""ShipDisplayPanel snapshot + payload tests. See spec
docs/superpowers/specs/2026-05-28-ship-display-panel-design.md."""
import pytest


def test_player_role_panel_has_correct_name():
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    panel = ShipDisplayPanel(ROLE_PLAYER)
    assert panel.name == "ship-player"


def test_target_role_panel_has_correct_name():
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_TARGET
    panel = ShipDisplayPanel(ROLE_TARGET)
    assert panel.name == "ship-target"


def test_invalid_role_raises():
    from engine.ui.ship_display_panel import ShipDisplayPanel
    with pytest.raises(AssertionError):
        ShipDisplayPanel("middle")


def test_player_panel_not_minimized_by_default():
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    panel = ShipDisplayPanel(ROLE_PLAYER)
    assert panel.IsMinimized() == 0


def test_target_panel_minimizable_by_default():
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_TARGET
    panel = ShipDisplayPanel(ROLE_TARGET)
    assert panel.IsMinimized() == 0
    panel.SetMinimized(1)
    assert panel.IsMinimized() == 1


def test_player_panel_setminimized_is_noop():
    """Player ShipDisplay can't minimize in stock BC."""
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    panel = ShipDisplayPanel(ROLE_PLAYER)
    panel.SetMinimized(1)
    assert panel.IsMinimized() == 0


def test_player_panel_is_not_minimizable():
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    panel = ShipDisplayPanel(ROLE_PLAYER)
    assert panel.IsMinimizable() == 0


def test_target_panel_is_minimizable_by_default():
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_TARGET
    panel = ShipDisplayPanel(ROLE_TARGET)
    assert panel.IsMinimizable() == 1
