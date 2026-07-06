"""TDD tests for EngineeringPowerPanel (Task 13).

Panel renders live power-grid state: sliders per group, banded Power Used bar,
Warp Core / Main / Reserve columns, and tractor/cloak siphon lines.
"""
import json

import App
from engine.appc.subsystems import (
    PowerSubsystem, PoweredSubsystem,
)
from engine.appc.properties import PowerProperty


def _fake_player():
    """Ship with full power subsystem + all seven group systems populated."""
    ship = App.ShipClass_Create("TestShip")

    # Power plant
    power = PowerSubsystem("Warp Core")
    prop = PowerProperty("Warp Core")
    prop.SetPowerOutput(1000.0)
    prop.SetMainBatteryLimit(800.0)
    prop.SetBackupBatteryLimit(200.0)
    prop.SetMainConduitCapacity(1200.0)
    prop.SetBackupConduitCapacity(200.0)
    power.SetProperty(prop)
    power.SetMainBatteryPower(400.0)
    power.SetBackupBatteryPower(100.0)
    ship.SetPowerSubsystem(power)

    # The systems all come pre-set by ShipClass_Create, so we just make sure
    # each one has NormalPower configured so GetNormalPowerWanted() is non-zero.
    for sys in (
        ship.GetPhaserSystem(),
        ship.GetTorpedoSystem(),
        ship.GetPulseWeaponSystem(),
    ):
        sys.SetNormalPowerPerSecond(50.0)
        sys.TurnOn()

    for sys in (
        ship.GetImpulseEngineSubsystem(),
        ship.GetWarpEngineSubsystem(),
    ):
        sys.SetNormalPowerPerSecond(80.0)
        sys.TurnOn()

    ship.GetSensorSubsystem().SetNormalPowerPerSecond(60.0)
    ship.GetSensorSubsystem().TurnOn()

    ship.GetShields().SetNormalPowerPerSecond(100.0)
    ship.GetShields().TurnOn()

    return ship


def test_payload_shape_and_diffing(monkeypatch):
    panel = _make_panel()
    js = panel.render_payload()
    assert js is not None
    assert js.startswith("setEngineeringPower(")
    payload = json.loads(js[len("setEngineeringPower("):-2])
    # columns must be a dict with the three keys
    assert set(payload["columns"]) == {"warp_core", "main", "backup"}
    # sliders ordered weapons/engines/sensors/shields
    assert [s["key"] for s in payload["sliders"]] == [
        "weapons", "engines", "sensors", "shields"]
    assert 0.0 <= payload["power_used"]["fraction"] <= 1.0
    assert set(payload["power_used"]["bands"]) == {"blue", "yellow", "red"}
    assert payload["tractor"]["active"] in (True, False)
    # unchanged state => no re-send
    assert panel.render_payload() is None


def test_slider_event_sets_group_and_refreshes():
    player = _fake_player()
    panel = _make_panel(player)
    assert panel.dispatch_event("engpower:set:weapons:0.75")
    for sys in (player.GetPhaserSystem(), player.GetTorpedoSystem(),
                player.GetPulseWeaponSystem()):
        if sys:
            assert abs(sys.GetPowerPercentageWanted() - 0.75) < 1e-9
    assert panel.dispatch_event("engpower:set:engines:1.25")
    assert abs(player.GetWarpEngineSubsystem().GetPowerPercentageWanted() - 1.25) < 1e-9
    assert not panel.dispatch_event("other:noise")


def test_no_player_returns_not_visible():
    from engine.ui.engineering_power_panel import EngineeringPowerPanel
    panel = EngineeringPowerPanel(get_player=lambda: None)
    js = panel.render_payload()
    assert js is not None
    payload = json.loads(js[len("setEngineeringPower("):-2])
    assert payload["visible"] is False


def test_name_is_engpower():
    from engine.ui.engineering_power_panel import EngineeringPowerPanel
    panel = EngineeringPowerPanel(get_player=lambda: None)
    assert panel.name == "engpower"


def test_dispatch_unknown_event_returns_false():
    panel = _make_panel()
    assert panel.dispatch_event("other:noise") is False
    assert panel.dispatch_event("engpower:bogus") is False


def test_dispatch_unknown_group_early_outs_without_cache_bust():
    """A well-formed engpower:set event for a group we don't publish is
    handled (True) but must NOT invalidate the render cache — no state
    changed, so no re-emit."""
    panel = _make_panel()
    panel.render_payload()                  # prime cache
    assert panel.render_payload() is None   # deduped
    assert panel.dispatch_event("engpower:set:bogusgroup:0.5") is True
    assert panel.render_payload() is None   # still deduped: no cache bust


def test_dispatch_invalidates_cache():
    """After dispatch_event, render_payload re-emits (cache cleared)."""
    player = _fake_player()
    panel = _make_panel(player)
    panel.render_payload()          # prime cache
    assert panel.render_payload() is None  # deduped
    panel.dispatch_event("engpower:set:weapons:0.5")
    assert panel.render_payload() is not None  # re-emits


def test_tractor_active_when_firing():
    """tractor.active is True when the tractor is firing."""
    from engine.appc.weapon_subsystems import TractorBeamSystem
    player = _fake_player()
    panel = _make_panel(player)
    # Force the tractor to appear active via monkeypatching _wants_power
    tbs = player.GetTractorBeamSystem()
    tbs._wants_power = lambda: True
    # Invalidate to force a fresh snapshot
    panel._last_pushed = None
    js = panel.render_payload()
    payload = json.loads(js[len("setEngineeringPower("):-2])
    assert payload["tractor"]["active"] is True


def test_cloak_present_and_inactive_by_default():
    """cloak.present is False for a basic ship (no cloaking subsystem set)."""
    from engine.ui.engineering_power_panel import EngineeringPowerPanel
    player = _fake_player()
    # ShipClass_Create does NOT set a CloakingSubsystem by default
    panel = EngineeringPowerPanel(get_player=lambda: player)
    js = panel.render_payload()
    payload = json.loads(js[len("setEngineeringPower("):-2])
    assert payload["cloak"]["present"] is False
    assert payload["cloak"]["active"] is False


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_panel(player=None):
    from engine.ui.engineering_power_panel import EngineeringPowerPanel
    if player is None:
        player = _fake_player()
    return EngineeringPowerPanel(get_player=lambda: player)
