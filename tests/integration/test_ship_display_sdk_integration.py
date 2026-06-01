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


def test_set_panel_registry_routes_factory_to_live_registry():
    """The host loop calls set_panel_registry once at startup; subsequent
    ShipDisplay_Create calls must register with that registry."""
    from engine.ui.panel_registry import PanelRegistry
    from engine.sdk_ui.widgets.ship_display import (
        set_panel_registry, ShipDisplay_Create, _reset_create_count,
    )
    _reset_create_count()
    live = PanelRegistry()
    set_panel_registry(live)
    p = ShipDisplay_Create(0.0, 0.0)
    assert any(panel is p for panel in live._panels)


def test_reset_for_bridge_teardown_clears_counter_and_registry():
    """Bridge teardown must clear BOTH the counter and the registry
    reference. Otherwise the next bridge load tries to re-register
    'ship-player' into the old registry and PanelRegistry.register
    raises ValueError('duplicate panel name')."""
    from engine.ui.panel_registry import PanelRegistry
    from engine.sdk_ui.widgets.ship_display import (
        set_panel_registry, _reset_for_bridge_teardown, _active_registry,
        _reset_create_count, ShipDisplay_Create,
    )
    _reset_create_count()
    first_registry = PanelRegistry()
    set_panel_registry(first_registry)
    ShipDisplay_Create()
    ShipDisplay_Create()

    _reset_for_bridge_teardown()
    assert _active_registry() is None

    # Now a fresh bridge load can re-inject and start clean.
    second_registry = PanelRegistry()
    set_panel_registry(second_registry)
    p1 = ShipDisplay_Create()
    p2 = ShipDisplay_Create()
    assert p1.name == "ship-player"
    assert p2.name == "ship-target"
    # second_registry has the two new panels; first_registry has the
    # two stale ones — verify the new factory call routed to the new
    # registry, not the old.
    assert any(p is p1 for p in second_registry._panels)
    assert not any(p is p1 for p in first_registry._panels)


def test_third_create_call_raises_explicit_error():
    """The factory hands out player on call 1, target on call 2.
    A third call is unexpected — fail loudly rather than silently
    return a duplicate-role panel."""
    import pytest
    from engine.ui.panel_registry import PanelRegistry
    from engine.sdk_ui.widgets.ship_display import (
        set_panel_registry, ShipDisplay_Create, _reset_create_count,
    )
    _reset_create_count()
    set_panel_registry(PanelRegistry())
    ShipDisplay_Create()
    ShipDisplay_Create()
    with pytest.raises((RuntimeError, AssertionError)):
        ShipDisplay_Create()
