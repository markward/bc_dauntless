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


def test_get_subviews_returns_defaults_before_adoption():
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    panel = ShipDisplayPanel(ROLE_PLAYER)
    # The SDK construction path is: create sub-views via factory THEN
    # SetXxxDisplay them. Before SetXxxDisplay the panel has empty
    # default sub-views (so calls don't crash); after, the passed
    # sub-view replaces them and gets its parent ref wired.
    sh = panel.GetShieldsDisplay()
    dm = panel.GetDamageDisplay()
    hg = panel.GetHealthGauge()
    assert sh is not None and dm is not None and hg is not None


def test_setshieldsdisplay_adopts_orphan_and_wires_parent():
    from engine.ui.ship_display_panel import (
        ShipDisplayPanel, ROLE_PLAYER, _ShieldsSubview,
    )
    panel = ShipDisplayPanel(ROLE_PLAYER)
    orphan = _ShieldsSubview(parent=None)
    panel.SetShieldsDisplay(orphan)
    assert panel.GetShieldsDisplay() is orphan
    assert orphan.parent is panel


def test_subview_update_for_new_ship_invalidates_parent_cache():
    from engine.ui.ship_display_panel import (
        ShipDisplayPanel, ROLE_PLAYER, _ShieldsSubview,
    )
    panel = ShipDisplayPanel(ROLE_PLAYER)
    panel._last_snapshot = ("cached",)
    orphan = _ShieldsSubview(parent=None)
    panel.SetShieldsDisplay(orphan)
    orphan.UpdateForNewShip()
    assert panel._last_snapshot is None


def test_setdamagedisplay_and_sethealthgauge_adopt_orphans():
    from engine.ui.ship_display_panel import (
        ShipDisplayPanel, ROLE_PLAYER,
        _DamageSubview, _HullGaugeSubview,
    )
    panel = ShipDisplayPanel(ROLE_PLAYER)
    d = _DamageSubview(parent=None)
    h = _HullGaugeSubview(parent=None)
    panel.SetDamageDisplay(d)
    panel.SetHealthGauge(h)
    assert panel.GetDamageDisplay() is d
    assert panel.GetHealthGauge() is h
    assert d.parent is panel
    assert h.parent is panel


def test_sdk_layout_calls_are_noops():
    """SDK ShipDisplay.Create at lines 79-100 calls these on the parent."""
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    panel = ShipDisplayPanel(ROLE_PLAYER)
    panel.SetFixedSize(0.2, 0.2, 0)
    panel.InteriorChangedSize()
    panel.Layout()
    panel.SetPosition(0.5, 0.5, 0)
    assert panel.GetInteriorPane() is not None
    assert panel.GetMaximumInteriorWidth() > 0
    assert panel.GetMaximumInteriorHeight() > 0


def test_sdk_addchild_and_subview_positioning_are_noops():
    """Locks down that SDK ShipDisplay.Create's AddChild() and
    RepositionUI's pHealthGauge.SetPosition/GetHeight calls do not crash.
    Matches sdk/Build/scripts/Tactical/Interface/ShipDisplay.py:53-116."""
    from engine.ui.ship_display_panel import (
        ShipDisplayPanel, ROLE_PLAYER,
        _HullGaugeSubview, _DamageSubview, _ShieldsSubview,
    )
    panel = ShipDisplayPanel(ROLE_PLAYER)
    gauge = _HullGaugeSubview(parent=None)
    damage = _DamageSubview(parent=None)
    shields = _ShieldsSubview(parent=None)
    panel.AddChild(gauge, 0.0, 0.0, 0)
    panel.AddChild(damage, 0.0, 0.0, 0)
    panel.AddChild(shields, 0.0, 0.0, 0)
    # RepositionUI uses these
    gauge.SetPosition(0.0, panel.GetMaximumInteriorHeight() - gauge.GetHeight(), 0)
    assert gauge.GetHeight() == 0.0
