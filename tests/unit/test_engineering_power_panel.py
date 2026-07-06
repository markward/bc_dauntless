"""TDD tests for EngineeringPowerPanel (Task 13 / payload v2).

Panel renders live power-grid state: sliders per group, grid fractions
(damage/available/used), battery pillars with drain trend, tractor/cloak
presence. Payload v2 schema per docs/superpowers/specs/2026-07-06-power-panel-redesign-design.md.
"""
import json

import App
from engine.appc.subsystems import (
    PowerSubsystem, PoweredSubsystem,
)
from engine.appc.properties import PowerProperty
from engine.ui.engineering_power_panel import _GROUPS


def _fake_player():
    """Ship with full power subsystem + all seven group systems populated.

    Power authored values: output=1000, main_conduit=1200, backup_conduit=200,
    main_battery_limit=250000, backup_battery_limit=80000 (full charge on init).
    Battery levels set to full by SetProperty (fills to limit).
    """
    ship = App.ShipClass_Create("TestShip")

    # Power plant — authored values per brief
    power = PowerSubsystem("Warp Core")
    prop = PowerProperty("Warp Core")
    prop.SetPowerOutput(1000.0)
    prop.SetMainBatteryLimit(250000.0)
    prop.SetBackupBatteryLimit(80000.0)
    prop.SetMainConduitCapacity(1200.0)
    prop.SetBackupConduitCapacity(200.0)
    power.SetProperty(prop)   # fills batteries to limits
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


# ── v2 payload helpers ────────────────────────────────────────────────────────

def _panel():
    """Panel with open engineering menu and full _fake_player."""
    return _make_panel(is_engineering_open=lambda: True)


def _panel_with_power():
    """Return (panel, power_subsystem) so tests can mutate power state."""
    player = _fake_player()
    panel = _make_panel(player, is_engineering_open=lambda: True)
    return panel, player.GetPowerSubsystem()


def _panel_with_player(tractor_weapons=None):
    """Return (panel, player) so tests can mutate any subsystem."""
    player = _fake_player()
    if tractor_weapons is not None:
        tbs = player.GetTractorBeamSystem()
        # Clear existing child weapons down to desired count
        while tbs.GetNumWeapons() > tractor_weapons:
            tbs.RemoveSubsystem(tbs.GetNthChildSubsystem(0))
    panel = _make_panel(player, is_engineering_open=lambda: True)
    return panel, player


def _payload(panel):
    js = panel.render_payload()
    assert js is not None
    assert js.startswith("setEngineeringPower(")
    return json.loads(js[len("setEngineeringPower("):-2])


def _systems(player, getters):
    out = []
    for g in getters:
        getter = getattr(player, g, None)
        sys = getter() if getter else None
        if sys is not None:
            out.append(sys)
    return out


# ── v2 payload tests ──────────────────────────────────────────────────────────

def test_payload_shape_and_diffing():
    """v2 payload has grid/batteries/sliders/tractor/cloak; old power_used/columns absent."""
    panel = _panel()
    js = panel.render_payload()
    assert js is not None
    assert js.startswith("setEngineeringPower(")
    payload = json.loads(js[len("setEngineeringPower("):-2])
    # v2 keys present
    assert "grid" in payload
    assert "batteries" in payload
    assert "sliders" in payload
    assert "tractor" in payload
    assert "cloak" in payload
    # old v1 keys absent
    assert "power_used" not in payload
    assert "columns" not in payload
    # sliders ordered weapons/engines/sensors/shields
    assert [s["key"] for s in payload["sliders"]] == [
        "weapons", "engines", "sensors", "shields"]
    assert payload["tractor"]["active"] in (True, False)
    # unchanged state => no re-send
    assert panel.render_payload() is None


def test_grid_fractions_healthy_full_batteries():
    panel = _panel()
    p = _payload(panel)
    D = 1000.0 + 1200.0 + 200.0
    assert p["grid"]["damage"] == 0.0
    assert abs(p["grid"]["available"]["warp_core"] - round(1000.0 / D, 4)) < 1e-9
    assert abs(p["grid"]["available"]["main"] - round(1200.0 / D, 4)) < 1e-9
    assert abs(p["grid"]["available"]["reserve"] - round(200.0 / D, 4)) < 1e-9
    assert [u["key"] for u in p["grid"]["used"]] == ["weapons", "engines", "sensors", "shields"]
    assert p["grid"]["overload"] is False


def test_damage_column_from_core_condition():
    panel, power = _panel_with_power()
    power.SetCondition(power.GetMaxCondition() * 0.5)     # 50% health
    p = _payload(panel)
    D = 2400.0
    assert abs(p["grid"]["damage"] - round(500.0 / D, 4)) < 1e-9
    assert abs(p["grid"]["available"]["warp_core"] - round(500.0 / D, 4)) < 1e-9


def test_available_battery_segments_shrink_with_charge():
    panel, power = _panel_with_power()
    power.SetMainBatteryPower(125000.0)                   # 50% charge
    p = _payload(panel)
    assert abs(p["grid"]["available"]["main"] - round(1200.0 * 0.5 / 2400.0, 4)) < 1e-9


def test_used_overload_clamps_and_flags():
    panel, player = _panel_with_player()
    for key, _label, getters in _GROUPS:                  # crank demand way past supply
        for s in _systems(player, getters):
            s.SetNormalPowerPerSecond(5000.0)
    p = _payload(panel)
    used_total = sum(u["frac"] for u in p["grid"]["used"])
    avail_total = sum(p["grid"]["available"].values())
    assert p["grid"]["overload"] is True
    assert abs(used_total - avail_total) < 1e-3


def test_battery_draining_trend():
    panel, power = _panel_with_power()
    _payload(panel)                                       # snapshot 1: baseline
    power.SetMainBatteryPower(power.GetMainBatteryPower() - 500.0)
    panel._last_pushed = None                             # force re-snapshot
    p = _payload(panel)
    assert p["batteries"]["main"]["draining"] is True
    assert p["batteries"]["reserve"]["draining"] is False


def test_tractor_presence_requires_emitters():
    panel, player = _panel_with_player(tractor_weapons=0)
    assert _payload(panel)["tractor"]["present"] is False


def test_shields_label_renamed():
    p = _payload(_panel())
    assert [s["label"] for s in p["sliders"]] == ["Weapons", "Engines", "Sensor Array", "Shields"]


def test_batteries_charge_fractions():
    """Batteries in payload carry correct charge fractions."""
    panel, power = _panel_with_power()
    # Full batteries after SetProperty
    p = _payload(panel)
    assert abs(p["batteries"]["main"]["charge"] - 1.0) < 1e-9
    assert abs(p["batteries"]["reserve"]["charge"] - 1.0) < 1e-9
    # Half charge on main
    power.SetMainBatteryPower(125000.0)
    panel._last_pushed = None
    p2 = _payload(panel)
    assert abs(p2["batteries"]["main"]["charge"] - 0.5) < 1e-9


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


def test_slider_event_sets_group_and_refreshes():
    player = _fake_player()
    panel = _make_panel(player)
    # dispatch_event receives the post-slash action (PanelRegistry strips the
    # "engpower/" prefix before calling it).
    assert panel.dispatch_event("set:weapons:0.75")
    for sys in (player.GetPhaserSystem(), player.GetTorpedoSystem(),
                player.GetPulseWeaponSystem()):
        if sys:
            assert abs(sys.GetPowerPercentageWanted() - 0.75) < 1e-9
    assert panel.dispatch_event("set:engines:1.25")
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
    assert panel.dispatch_event("bogus") is False


def test_dispatch_unknown_group_early_outs_without_cache_bust():
    """A well-formed engpower:set event for a group we don't publish is
    handled (True) but must NOT invalidate the render cache — no state
    changed, so no re-emit."""
    panel = _make_panel()
    panel.render_payload()                  # prime cache
    assert panel.render_payload() is None   # deduped
    assert panel.dispatch_event("set:bogusgroup:0.5") is True
    assert panel.render_payload() is None   # still deduped: no cache bust


def test_dispatch_invalidates_cache():
    """After dispatch_event, render_payload re-emits (cache cleared)."""
    player = _fake_player()
    panel = _make_panel(player)
    panel.render_payload()          # prime cache
    assert panel.render_payload() is None  # deduped
    panel.dispatch_event("set:weapons:0.5")
    assert panel.render_payload() is not None  # re-emits


def test_slider_event_routes_through_panel_registry():
    """The live entry point is PanelRegistry.dispatch (wired as the single
    CEF event handler). A slider oninput fires the panel's JS event string;
    delivering that SAME string through dispatch() must reach the panel and
    change the subsystem pct.

    This is the test that catches the reset-to-100% bug: the earlier tests
    called panel.dispatch_event directly, bypassing the slash-prefix routing
    layer, so a colon-only event string (never routed to the panel, snapping
    back on the next render tick) went unnoticed.
    """
    from engine.ui.panel_registry import PanelRegistry
    player = _fake_player()
    panel = _make_panel(player, is_engineering_open=lambda: True)
    legacy_calls = []
    reg = PanelRegistry(legacy_handler=legacy_calls.append)
    reg.register(panel)

    # The exact string the slider oninput sends via dauntlessEvent(...).
    handled = reg.dispatch("engpower/set:weapons:0.5")

    assert handled is True
    # It reached the panel, not the legacy pause-menu handler.
    assert legacy_calls == []
    for sys in (player.GetPhaserSystem(), player.GetTorpedoSystem(),
                player.GetPulseWeaponSystem()):
        if sys:
            assert abs(sys.GetPowerPercentageWanted() - 0.5) < 1e-9


def test_slider_zero_turns_shields_off():
    """Setting shields to 0% must TurnOff() the shield generator (BC SDK
    SetPowerToSubsystem:  if pct == 0.0 → TurnOff)."""
    player = _fake_player()
    shields = player.GetShields()
    shields.TurnOn()
    assert shields.IsOn() == 1
    panel = _make_panel(player)
    panel.dispatch_event("set:shields:0")
    assert shields.IsOn() == 0, "shields should be off after pct=0 dispatch"


def test_slider_zero_turns_weapons_off():
    """All weapons systems in the group must TurnOff when group slider goes to 0."""
    player = _fake_player()
    for sys in (player.GetPhaserSystem(), player.GetTorpedoSystem(),
                player.GetPulseWeaponSystem()):
        if sys:
            sys.TurnOn()
            assert sys.IsOn() == 1
    panel = _make_panel(player)
    panel.dispatch_event("set:weapons:0")
    for sys in (player.GetPhaserSystem(), player.GetTorpedoSystem(),
                player.GetPulseWeaponSystem()):
        if sys:
            assert sys.IsOn() == 0, f"{sys} should be off after weapons pct=0"


def test_slider_nonzero_turns_shields_on_when_off():
    """Raising shields from 0% must TurnOn() the shield generator (BC SDK
    SetPowerToSubsystem:  if not IsOn() and pct > 0 → TurnOn)."""
    player = _fake_player()
    shields = player.GetShields()
    shields.TurnOff()
    assert shields.IsOn() == 0
    panel = _make_panel(player)
    panel.dispatch_event("set:shields:0.75")
    assert shields.IsOn() == 1, "shields should be on after pct=0.75 when previously off"
    assert abs(shields.GetPowerPercentageWanted() - 0.75) < 1e-9


def test_slider_nonzero_does_not_turn_off_when_already_on():
    """A non-zero slider on an already-ON subsystem must NOT call TurnOff."""
    player = _fake_player()
    shields = player.GetShields()
    shields.TurnOn()
    panel = _make_panel(player)
    panel.dispatch_event("set:shields:0.5")
    assert shields.IsOn() == 1, "shields should still be on after non-zero pct"


def test_slider_zero_shields_drains_all_faces_to_zero():
    """engpower set:shields:0 on charged shields must set every face to 0.

    This is alert-drop parity: the status widget reads face charge, so
    powered-down shields must visibly show 0%, not stuck at 100%.
    """
    player = _fake_player()
    shields = player.GetShields()
    # Seed with max charge on all faces.
    for f in range(shields.NUM_SHIELDS):
        shields.SetMaxShields(f, 1000.0)
        shields.SetCurrentShields(f, 1000.0)
    shields.TurnOn()
    panel = _make_panel(player)
    panel.dispatch_event("set:shields:0")
    assert shields.IsOn() == 0
    for f in range(shields.NUM_SHIELDS):
        assert shields.GetCurShields(f) == 0.0, (
            f"face {f} should be drained after slider→0; got {shields.GetCurShields(f)}"
        )


def test_slider_raise_from_zero_snaps_faces_to_max():
    """engpower set:shields:0.75 when shields are off must snap every face
    to max — same raise semantics as the alert-level raise path."""
    player = _fake_player()
    shields = player.GetShields()
    for f in range(shields.NUM_SHIELDS):
        shields.SetMaxShields(f, 1000.0)
        shields.SetCurrentShields(f, 0.0)
    shields.TurnOff()
    panel = _make_panel(player)
    panel.dispatch_event("set:shields:0.75")
    assert shields.IsOn() == 1
    for f in range(shields.NUM_SHIELDS):
        assert shields.GetCurShields(f) == shields.GetMaxShields(f), (
            f"face {f} should snap to max on raise; got {shields.GetCurShields(f)}"
        )


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_panel(player=None, is_engineering_open=None):
    from engine.ui.engineering_power_panel import EngineeringPowerPanel
    if player is None:
        player = _fake_player()
    kwargs = {"get_player": lambda: player}
    if is_engineering_open is not None:
        kwargs["is_engineering_open"] = is_engineering_open
    return EngineeringPowerPanel(**kwargs)
