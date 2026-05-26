"""Tests for App.RadarDisplay_Create / RadarScope_Create / RadarBlip_Create
and the TacticalControlWindow.SetRadarDisplay accessor.

These cover the surface SDK scripts touch, not the per-tick rendering
(that lives on SensorsPanel)."""
import App


def test_radar_display_create_returns_object_with_sdk_methods():
    p = App.RadarDisplay_Create(0.0, 0.0)
    # All these are no-ops; the test just asserts they exist + are callable
    # without raising. SDK scripts call each of them during bridge load.
    p.SetUseScrolling(0)
    p.SetColorBasedOnFlags()
    p.ResizeUI()
    p.RepositionUI()
    p.InteriorChangedSize(1)
    # Inherits SetName / AddChild from the stylized-window stub.
    p.SetName("Sensors")
    assert p.GetName() == "Sensors"


def test_radar_scope_create_returns_object_with_sdk_methods():
    pScope = App.RadarScope_Create(0.1, 0.1)
    pScope.SetNoFocus()
    # CreateShipIcon returns a TGIcon-shaped object the SDK adds as a child.
    icon = pScope.CreateShipIcon()
    assert icon is not None
    pScope.AddChild(icon, 0.0, 0.0, 0)
    # Target bracket is the one blip the SDK constructs explicitly.
    bracket = App.RadarBlip_Create("LCARS_1024", 430)
    pScope.SetTargetBracket(bracket)
    pScope.AddChild(bracket, 0.0, 0.0, 0)
    # Resize/Reposition handed off to RadarScope.ResizeUI helper module.
    pScope.Resize(0.1, 0.1, 0)
    pScope.Layout()


def test_radar_blip_create_exposes_ship_id_methods():
    blip = App.RadarBlip_Create("LCARS_1024", 400)
    blip.SetShipID(42)
    assert blip.GetShipID() == 42


def test_tactical_control_window_set_get_radar_display():
    pTCW = App.TacticalControlWindow_GetTacticalControlWindow()
    p = App.RadarDisplay_Create(0.0, 0.0)
    pTCW.SetRadarDisplay(p)
    assert pTCW.GetRadarDisplay() is p
