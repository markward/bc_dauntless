"""End-to-end test of the SDK construction path for ShipDisplay,
matching sdk/Build/scripts/Tactical/Interface/ShipDisplay.py:Create."""
import App


def setup_function(_):
    from engine.sdk_ui.widgets.ship_display import _reset_create_count
    _reset_create_count()
    from engine.ui.panel_registry import PanelRegistry
    from engine.sdk_ui.widgets.ship_display import set_panel_registry
    set_panel_registry(PanelRegistry())


def test_first_create_returns_player_panel():
    panel = App.ShipDisplay_Create(0.0, 0.0)
    assert panel.name == "ship-player"


def test_second_create_returns_target_panel():
    App.ShipDisplay_Create(0.0, 0.0)
    target = App.ShipDisplay_Create(0.0, 0.0)
    assert target.name == "ship-target"


def test_panels_register_with_active_registry():
    from engine.sdk_ui.widgets.ship_display import _active_registry
    p1 = App.ShipDisplay_Create(0.0, 0.0)
    p2 = App.ShipDisplay_Create(0.0, 0.0)
    names = [p.name for p in _active_registry()._panels]
    assert "ship-player" in names
    assert "ship-target" in names


def test_full_sdk_construction_path_runs_without_exceptions():
    """Replays sdk/Build/scripts/Tactical/Interface/ShipDisplay.py:Create."""
    pDisplay = App.ShipDisplay_Create(0.0, 0.0)
    pHealthGauge   = App.STFillGauge_Create()
    pDamageDisplay = App.DamageDisplay_Create(0.0, 0.0)
    pShieldsDisplay = App.ShieldsDisplay_Create(0.0, 0.0)
    pDisplay.SetHealthGauge(pHealthGauge)
    pDisplay.SetDamageDisplay(pDamageDisplay)
    pDisplay.SetShieldsDisplay(pShieldsDisplay)
    # Adoption wires parent refs
    assert pHealthGauge.parent is pDisplay
    assert pDamageDisplay.parent is pDisplay
    assert pShieldsDisplay.parent is pDisplay


def test_ship_display_cast_returns_panel_or_none():
    panel = App.ShipDisplay_Create(0.0, 0.0)
    assert App.ShipDisplay_Cast(panel) is panel
    assert App.ShipDisplay_Cast(object()) is None
