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
    panel = _make_panel(is_engineering_open=lambda: True)
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


def test_is_showing_false_without_player():
    """Clickable-state contract: the host loop gates click-forwarding on
    is_showing(), mirroring crew_menu_panel.has_open_menu(). No player =>
    the JS root hides itself => the panel is not clickable."""
    from engine.ui.engineering_power_panel import EngineeringPowerPanel
    panel = EngineeringPowerPanel(get_player=lambda: None)
    assert panel.is_showing() is False


def test_is_showing_true_with_powered_player():
    """A player with a power subsystem renders the panel, so clicks over its
    top-right region must be forwarded to CEF (is_showing() True)."""
    panel = _make_panel(is_engineering_open=lambda: True)
    assert panel.is_showing() is True


def test_is_showing_false_when_engineering_menu_not_open():
    """is_showing() is False when the Engineering crew menu is closed.
    The click region must be released so top-right clicks reach the game."""
    panel = _make_panel(is_engineering_open=lambda: False)
    assert panel.is_showing() is False


def test_is_showing_true_when_engineering_menu_open():
    """is_showing() is True only when Engineering menu is open (and player+power
    present). Opening the menu must activate the click region."""
    panel = _make_panel(is_engineering_open=lambda: True)
    assert panel.is_showing() is True


def test_snapshot_visible_false_when_engineering_menu_closed():
    """_snapshot visible=False when Engineering menu is not open, so JS hides
    the grid even when a powered player exists."""
    panel = _make_panel(is_engineering_open=lambda: False)
    js = panel.render_payload()
    assert js is not None
    import json
    payload = json.loads(js[len("setEngineeringPower("):-2])
    assert payload["visible"] is False


def test_snapshot_visible_true_when_engineering_menu_open():
    """_snapshot visible=True when Engineering menu is open and player+power
    present — the grid is rendered and the click region is live."""
    panel = _make_panel(is_engineering_open=lambda: True)
    js = panel.render_payload()
    assert js is not None
    import json
    payload = json.loads(js[len("setEngineeringPower("):-2])
    assert payload["visible"] is True


def test_snapshot_transitions_on_menu_toggle():
    """render_payload re-emits when the menu opens/closes (diff detects
    visible flip), so the JS picks up both show and hide transitions."""
    open_state = [False]
    panel = _make_panel(is_engineering_open=lambda: open_state[0])
    import json
    # First tick: menu closed → visible False
    js1 = panel.render_payload()
    assert js1 is not None
    p1 = json.loads(js1[len("setEngineeringPower("):-2])
    assert p1["visible"] is False
    # Same state → deduped
    assert panel.render_payload() is None
    # Open the menu → visible True, re-emits
    open_state[0] = True
    js2 = panel.render_payload()
    assert js2 is not None
    p2 = json.loads(js2[len("setEngineeringPower("):-2])
    assert p2["visible"] is True
    # Close the menu → visible False, re-emits
    open_state[0] = False
    js3 = panel.render_payload()
    assert js3 is not None
    p3 = json.loads(js3[len("setEngineeringPower("):-2])
    assert p3["visible"] is False


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
    panel = _make_panel(player, is_engineering_open=lambda: True)
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
    panel = EngineeringPowerPanel(get_player=lambda: player,
                                  is_engineering_open=lambda: True)
    js = panel.render_payload()
    payload = json.loads(js[len("setEngineeringPower("):-2])
    assert payload["cloak"]["present"] is False
    assert payload["cloak"]["active"] is False


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_panel(player=None, is_engineering_open=None):
    from engine.ui.engineering_power_panel import EngineeringPowerPanel
    if player is None:
        player = _fake_player()
    kwargs = {"get_player": lambda: player}
    if is_engineering_open is not None:
        kwargs["is_engineering_open"] = is_engineering_open
    return EngineeringPowerPanel(**kwargs)
