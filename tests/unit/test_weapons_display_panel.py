"""WeaponsDisplayPanel weapon-settings wiring.

The panel gains a settings-view toggle and dispatches each config control to the
shared engine.appc.weapon_config helpers.  The status-view payload keys stay
unchanged; a new "config" block carries the weapon-config snapshot + open state.
"""
from unittest.mock import patch

import pytest

from engine.appc.ships import ShipClass_Create
from engine.appc.math import TGPoint3
from engine.appc.properties import WeaponSystemProperty
from engine.appc.subsystems import (
    PhaserSystem,
    PhaserBank,
    TorpedoSystem,
    TorpedoTube,
)
from engine.appc.weapon_subsystems import TorpedoAmmoType
from engine.ui.weapons_display_panel import WeaponsDisplayPanel


def _player_ship():
    ship = ShipClass_Create("Player")
    ship.SetWorldLocation(TGPoint3(0, 0, 0))
    # Torpedoes with two ammo types + two tubes.
    torps = TorpedoSystem("Torpedoes")
    torps.TurnOn()
    torps.SetProperty(WeaponSystemProperty("Torpedoes"))
    torps._parent_ship = ship
    torps.AddAmmoType(TorpedoAmmoType("Photon", power_cost=20.0))
    torps.AddAmmoType(TorpedoAmmoType("Quantum", power_cost=30.0))
    for i in range(2):
        tube = TorpedoTube(f"Tube {i}")
        tube._max_ready = 100
        tube._num_ready = 100
        torps.AddChildSubsystem(tube)
    ship._torpedo_system = torps
    # Phasers.
    phasers = PhaserSystem("Phasers")
    phasers.TurnOn()
    phasers._parent_ship = ship
    phasers.AddChildSubsystem(PhaserBank("Bank 0"))
    ship._phaser_system = phasers
    return ship


def _panel_with_player(ship):
    panel = WeaponsDisplayPanel()
    panel._visible = True
    return panel


@pytest.fixture
def panel_ctx():
    ship = _player_ship()
    panel = _panel_with_player(ship)
    with patch("engine.ui.weapons_display_panel._get_player", return_value=ship):
        yield panel, ship


# ── config block in payload ──────────────────────────────────────────────────

def test_payload_gains_config_block(panel_ctx):
    import json
    panel, ship = panel_ctx
    out = panel.render_payload()
    assert out is not None
    body = out[len("setWeaponsDisplay("):-len(");")]
    payload = json.loads(body)
    assert "config" in payload
    cfg = payload["config"]
    assert cfg["has_torpedoes"] is True
    assert cfg["has_phasers"] is True
    assert cfg["show_settings"] is False
    # Status-view keys unchanged.
    assert "weapon_icons" in payload
    assert "speed_label" in payload


def test_toggle_view_flips_and_rerenders(panel_ctx):
    import json
    panel, ship = panel_ctx
    panel.render_payload()  # prime snapshot
    assert panel.render_payload() is None  # deduped

    assert panel.dispatch_event("toggle-view") is True
    out = panel.render_payload()
    assert out is not None
    payload = json.loads(out[len("setWeaponsDisplay("):-len(");")])
    assert payload["config"]["show_settings"] is True

    panel.dispatch_event("toggle-view")
    out = panel.render_payload()
    payload = json.loads(out[len("setWeaponsDisplay("):-len(");")])
    assert payload["config"]["show_settings"] is False


# ── control actions dispatch to the right helper ─────────────────────────────

@pytest.mark.parametrize("action, helper", [
    ("cycle-type", "cycle_torpedo_type"),
    ("cycle-spread", "cycle_torpedo_spread"),
    ("cycle-intensity", "toggle_phaser_intensity"),
    ("toggle-tractor", "toggle_tractor"),
    ("toggle-cloak", "toggle_cloak"),
])
def test_control_action_calls_helper(panel_ctx, action, helper):
    panel, ship = panel_ctx
    with patch(f"engine.ui.weapons_display_panel.weapon_config.{helper}") as spy:
        result = panel.dispatch_event(action)
    assert result is True
    spy.assert_called_once_with(ship)


def test_control_action_invalidates_snapshot(panel_ctx):
    panel, ship = panel_ctx
    panel.render_payload()
    assert panel.render_payload() is None  # deduped
    with patch("engine.ui.weapons_display_panel.weapon_config.cycle_torpedo_type"):
        panel.dispatch_event("cycle-type")
    # Snapshot was invalidated → next render emits again.
    assert panel.render_payload() is not None


def test_unknown_action_returns_false(panel_ctx):
    panel, ship = panel_ctx
    assert panel.dispatch_event("no-such-action") is False


def test_dispatch_no_player_returns_false():
    panel = WeaponsDisplayPanel()
    panel._visible = True
    with patch("engine.ui.weapons_display_panel._get_player", return_value=None):
        assert panel.dispatch_event("cycle-type") is False
        # toggle-view still works without a player (pure UI state).
        assert panel.dispatch_event("toggle-view") is True
