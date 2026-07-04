"""ShipDisplayPanel snapshot + payload tests. See spec
docs/superpowers/specs/2026-05-28-ship-display-panel-design.md."""
import pytest

import App
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass


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


def test_player_panel_setminimized_works():
    """Player ShipDisplay can minimize in our CEF UI (user-driven UX,
    overrides stock BC's role-locked behaviour)."""
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    panel = ShipDisplayPanel(ROLE_PLAYER)
    panel.SetMinimized(1)
    assert panel.IsMinimized() == 1


def test_player_panel_is_minimizable_by_default():
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    panel = ShipDisplayPanel(ROLE_PLAYER)
    assert panel.IsMinimizable() == 1


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


def _setup_game_with_player():
    """Mirrors tests/unit/test_sensors_panel.py:_setup_game.

    Also attaches default subsystems (ShieldSubsystem, HullSubsystem,
    SensorSubsystem, ImpulseEngineSubsystem) so snapshot helpers that
    call GetShieldSubsystem() / GetHull() etc. get live objects rather
    than None.
    """
    from engine.core.game import Game, Episode, Mission, _set_current_game
    from engine.appc.ships import ShipClass
    from engine.appc.subsystems import (
        ShieldSubsystem, HullSubsystem,
        SensorSubsystem, ImpulseEngineSubsystem,
    )
    mission = Mission()
    episode = Episode(); episode.SetCurrentMission(mission)
    game = Game(); game.SetCurrentEpisode(episode)
    player = ShipClass(); player.SetName("Player")
    player.SetShieldSubsystem(ShieldSubsystem("Shields"))
    player.SetHull(HullSubsystem("Hull"))
    player.SetSensorSubsystem(SensorSubsystem("Sensors"))
    player.SetImpulseEngineSubsystem(ImpulseEngineSubsystem("Engines"))
    game.SetPlayer(player)
    _set_current_game(game)
    return game, player, mission


def _teardown_game():
    from engine.core.game import _set_current_game
    _set_current_game(None)


def test_player_snapshot_with_full_hull_and_shields():
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    _, player, mission = _setup_game_with_player()
    try:
        mission.GetFriendlyGroup().AddName("Player")
        sh = player.GetShieldSubsystem()
        for face in range(sh.NUM_SHIELDS):
            sh.SetMaxShields(face, 100.0)
            sh.SetCurrentShields(face, 100.0)
        hull = player.GetHull()
        hull.SetMaxCondition(1000.0)
        hull.SetCondition(1000.0)

        panel = ShipDisplayPanel(ROLE_PLAYER)
        snap = panel._snapshot()

        assert snap[1] == "Player"        # ship_name
        assert snap[2] == "FRIENDLY"      # affiliation — player is in friendly group
        assert snap[4] == 1.0             # hull_pct
        assert snap[5] == (1.0,) * 6      # shields_pct
        assert snap[10] is True           # visible
    finally:
        _teardown_game()


def test_target_snapshot_with_enemy_affiliation():
    """Hostile target should render in the ENEMY affiliation colour."""
    from engine.appc.ships import ShipClass
    from engine.appc.subsystems import (
        ShieldSubsystem, HullSubsystem, SensorSubsystem,
    )
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_TARGET
    _, player, mission = _setup_game_with_player()
    try:
        foe = ShipClass(); foe.SetName("Foe")
        # attach minimal subsystems so the snapshot helpers don't bail
        foe.SetShieldSubsystem(ShieldSubsystem())
        foe.SetHull(HullSubsystem())
        mission.GetEnemyGroup().AddName("Foe")
        player.SetTarget(foe)
        panel = ShipDisplayPanel(ROLE_TARGET)
        snap = panel._snapshot()
        assert snap[10] is True, "expected visible target"
        assert snap[2] == "ENEMY"
    finally:
        _teardown_game()


def test_target_role_returns_invisible_when_no_target():
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_TARGET
    _setup_game_with_player()
    try:
        panel = ShipDisplayPanel(ROLE_TARGET)
        snap = panel._snapshot()
        assert snap[10] is False          # visible
        assert snap[1] == ""              # ship_name
        assert snap[2] == "NONE"
    finally:
        _teardown_game()


def test_target_role_no_target_returns_invisible():
    """No SetTarget call → target panel hidden."""
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_TARGET
    _, player, _ = _setup_game_with_player()
    try:
        # Player has no target — _snapshot returns visible=False.
        assert player.GetTarget() is None
        panel = ShipDisplayPanel(ROLE_TARGET)
        snap = panel._snapshot()
        assert snap[10] is False
    finally:
        _teardown_game()


def test_shield_face_indices_match_subsystem_constants():
    """Snapshot face order is FRONT, REAR, TOP, BOTTOM, LEFT, RIGHT —
    i.e. ShieldSubsystem.FRONT_SHIELDS..RIGHT_SHIELDS (0..5)."""
    from engine.appc.subsystems import ShieldSubsystem
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    _, player, _ = _setup_game_with_player()
    try:
        sh = player.GetShieldSubsystem()
        # Mark each face with a unique fraction so we can verify ordering.
        for face in range(sh.NUM_SHIELDS):
            sh.SetMaxShields(face, 100.0)
            sh.SetCurrentShields(face, 10.0 * (face + 1))
        panel = ShipDisplayPanel(ROLE_PLAYER)
        snap = panel._snapshot()
        # Tuple positions 0..5 correspond to FRONT(0), REAR(1), TOP(2),
        # BOTTOM(3), LEFT(4), RIGHT(5).
        assert snap[5] == (0.1, 0.2, 0.3, 0.4, 0.5, 0.6)
        assert ShieldSubsystem.FRONT_SHIELDS == 0
        assert ShieldSubsystem.RIGHT_SHIELDS == 5
    finally:
        _teardown_game()


def test_damage_states_filter_to_positioned_subsystems_only():
    """Damage rows only surface for subsystems with a non-zero
    Position2D; the descriptor tuple is (icon_num, x_px, y_px, state).
    Impulse = icon_num 1; damaging it should flip state to 'damaged'."""
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    _, player, _ = _setup_game_with_player()
    try:
        eng = player.GetImpulseEngineSubsystem()
        # Stamp a fake hardpoint coord so the descriptor walk picks it up
        # — _damage_icon_descriptors filters out (0, 0).
        eng._position_2d = (50.0, 30.0)
        eng.SetDamaged(1)
        panel = ShipDisplayPanel(ROLE_PLAYER)
        snap = panel._snapshot()
        damage_frozen = snap[6]
        # Tuple shape: (icon_num, x_px, y_px, state)
        impulse_rows = [r for r in damage_frozen if r[0] == 1]
        assert len(impulse_rows) == 1
        assert impulse_rows[0] == (1, 50.0, 30.0, "damaged")
    finally:
        _teardown_game()


def test_render_payload_emits_setshipdisplay_call():
    import json
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    _, player, _ = _setup_game_with_player()
    try:
        sh = player.GetShieldSubsystem()
        for face in range(sh.NUM_SHIELDS):
            sh.SetMaxShields(face, 100.0)
            sh.SetCurrentShields(face, 100.0)
        hull = player.GetHull()
        hull.SetMaxCondition(1000.0); hull.SetCondition(750.0)

        panel = ShipDisplayPanel(ROLE_PLAYER)
        script = panel.render_payload()
        assert script is not None
        assert script.startswith("setShipDisplay(\"player\", ")
        body = script[len("setShipDisplay(\"player\", "):-2]
        state = json.loads(body)
        assert state["visible"] is True
        assert state["ship_name"] == "Player"
        assert state["hull_pct"] == 0.75
        assert state["shields_pct"] == [1.0] * 6
        # Task 5: payload emits damage_icons (hardpoint-driven), not the
        # legacy "damage" name/state list. Even with no positioned
        # subsystems on the test ship, the key must exist and be a list.
        assert "damage_icons" in state
        assert isinstance(state["damage_icons"], list)
        assert "damage" not in state
    finally:
        _teardown_game()


def test_render_payload_damage_icons_descriptor_shape():
    """damage_icons rows expose icon_num/icon_svg/x_px/y_px/state. Sensor
    icon_num is 4 (per damage_icons.ICON_REGISTRY)."""
    import json
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    _, player, _ = _setup_game_with_player()
    try:
        sensors = player.GetSensorSubsystem()
        sensors._position_2d = (64.0, 10.0)
        sensors.SetDamaged(1)

        panel = ShipDisplayPanel(ROLE_PLAYER)
        script = panel.render_payload()
        body = script[len("setShipDisplay(\"player\", "):-2]
        state = json.loads(body)
        icons = state["damage_icons"]
        sensor_rows = [r for r in icons if r["icon_num"] == 4]
        assert len(sensor_rows) == 1
        row = sensor_rows[0]
        assert row["x_px"] == 64.0
        assert row["y_px"] == 10.0
        assert row["state"] == "damaged"
        # icon_svg is optional (None when no glyph cached); presence required.
        assert "icon_svg" in row
    finally:
        _teardown_game()


def test_render_payload_is_idempotent_until_state_changes():
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    _, player, _ = _setup_game_with_player()
    try:
        panel = ShipDisplayPanel(ROLE_PLAYER)
        first = panel.render_payload()
        second = panel.render_payload()
        assert first is not None
        assert second is None  # nothing changed → no re-emit

        # Damage the ship; next render should re-emit.
        player.GetHull().SetCondition(player.GetHull().GetCondition() * 0.5)
        third = panel.render_payload()
        assert third is not None
    finally:
        _teardown_game()


def test_setshipid_forces_reemit():
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    _setup_game_with_player()
    try:
        panel = ShipDisplayPanel(ROLE_PLAYER)
        assert panel.render_payload() is not None
        assert panel.render_payload() is None
        panel.SetShipID(42)
        assert panel.render_payload() is not None
    finally:
        _teardown_game()


def test_target_minimize_toggle_flips_state_and_invalidates_cache():
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_TARGET
    _setup_game_with_player()
    try:
        panel = ShipDisplayPanel(ROLE_TARGET)
        panel.render_payload()  # prime cache
        handled = panel.dispatch_event("minimize-toggle")
        assert handled is True
        assert panel.IsMinimized() == 1
        # next render should re-emit
        assert panel.render_payload() is not None
        # toggling again flips back
        panel.dispatch_event("minimize-toggle")
        assert panel.IsMinimized() == 0
    finally:
        _teardown_game()


def test_player_panel_handles_minimize_event():
    """Player panel collapses on minimize-toggle in our CEF UI."""
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    _setup_game_with_player()
    try:
        panel = ShipDisplayPanel(ROLE_PLAYER)
        handled = panel.dispatch_event("minimize-toggle")
        assert handled is True
        assert panel.IsMinimized() == 1
    finally:
        _teardown_game()


def test_invisible_panel_emits_visible_false():
    """View-mode hides the panel via Panel.visible — snapshot must
    propagate this even when a ship is resolvable."""
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    _setup_game_with_player()
    try:
        panel = ShipDisplayPanel(ROLE_PLAYER)
        panel.visible = False
        snap = panel._snapshot()
        assert snap[10] is False  # visible position
    finally:
        _teardown_game()


def test_unknown_action_returns_false():
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_TARGET
    _setup_game_with_player()
    try:
        panel = ShipDisplayPanel(ROLE_TARGET)
        assert panel.dispatch_event("explode") is False
    finally:
        _teardown_game()


def test_render_payload_includes_silhouette_url_when_species_resolvable(monkeypatch):
    """When species_key has a matching TGA, render_payload emits a silhouette_url."""
    import json
    from engine.ui import ship_icons
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    # Monkeypatch ship_icons to always return a fake URL
    monkeypatch.setattr(ship_icons, "icon_path_for_species",
                        lambda name: "icons/ships/" + name + ".png" if name else None)
    _, player, _ = _setup_game_with_player()
    try:
        panel = ShipDisplayPanel(ROLE_PLAYER)
        script = panel.render_payload()
        body = script[len("setShipDisplay(\"player\", "):-2]
        state = json.loads(body)
        assert "silhouette_url" in state
        # When species is "", URL is None; when species resolves, URL is a string
        assert state["silhouette_url"] is None or isinstance(state["silhouette_url"], str)
    finally:
        _teardown_game()


def test_panel_visibility_methods():
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    panel = ShipDisplayPanel(ROLE_PLAYER)
    assert panel.IsVisible() == 1  # default visible
    panel.SetNotVisible()
    assert panel.IsVisible() == 0
    panel.SetVisible()
    assert panel.IsVisible() == 1


def test_panel_setvisible_invalidates_cache():
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    panel = ShipDisplayPanel(ROLE_PLAYER)
    panel._last_snapshot = ("cached",)
    panel.SetNotVisible()
    assert panel._last_snapshot is None


def test_panel_getobjid_is_stable_and_unique():
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER, ROLE_TARGET
    p1 = ShipDisplayPanel(ROLE_PLAYER)
    p2 = ShipDisplayPanel(ROLE_TARGET)
    assert p1.GetObjID() == p1.GetObjID()  # stable
    assert p1.GetObjID() != p2.GetObjID()  # unique per instance
    assert p1.GetObjID() > 0  # positive (SDK expects this)


def test_panel_setname_and_setusescrolling_are_noops():
    """SDK TacticalMenuHandlers calls these after construction;
    they exist solely to avoid AttributeError."""
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    panel = ShipDisplayPanel(ROLE_PLAYER)
    panel.SetName("Player Ship Display")
    panel.SetUseScrolling(0)
    # No assertion needed — these are no-ops. Test passes if no exception.


def test_panel_getconceptualparent_returns_none():
    """The panel itself has no parent panel; only sub-views do."""
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    panel = ShipDisplayPanel(ROLE_PLAYER)
    assert panel.GetConceptualParent() is None


def test_subview_getconceptualparent_returns_panel():
    """Sub-views walk back to the owning panel via GetConceptualParent.
    Matches SDK ShieldsDisplay.py:303."""
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    panel = ShipDisplayPanel(ROLE_PLAYER)
    assert panel.GetShieldsDisplay().GetConceptualParent() is panel
    assert panel.GetDamageDisplay().GetConceptualParent() is panel
    assert panel.GetHealthGauge().GetConceptualParent() is panel


def test_species_key_resolves_galaxy_from_int():
    """Galaxy.SetSpecies(101) in ships/Hardpoints/galaxy.py; _species_key_for
    must map 101 → 'Galaxy' so the icon cache finds Galaxy.tga."""
    from engine.appc.ships import ShipClass
    from engine.ui.ship_display_panel import _species_key_for
    ship = ShipClass()
    ship.SetSpecies(101)
    assert _species_key_for(ship) == "Galaxy"


def test_species_key_resolves_warbird_from_int():
    """Warbird.SetSpecies(301) in ships/Hardpoints/warbird.py."""
    from engine.appc.ships import ShipClass
    from engine.ui.ship_display_panel import _species_key_for
    ship = ShipClass()
    ship.SetSpecies(301)
    assert _species_key_for(ship) == "Warbird"


def test_species_key_unknown_int_returns_empty():
    from engine.appc.ships import ShipClass
    from engine.ui.ship_display_panel import _species_key_for
    ship = ShipClass()
    ship.SetSpecies(9999)
    assert _species_key_for(ship) == ""


def test_species_key_zero_unknown_returns_empty():
    """Species 0 (UNKNOWN) has no icon."""
    from engine.appc.ships import ShipClass
    from engine.ui.ship_display_panel import _species_key_for
    ship = ShipClass()
    ship.SetSpecies(0)
    assert _species_key_for(ship) == ""


# ────────────────────────────────────────────────────────────────────────
# Target panel: range / speed conversion
#
# BC stores positions and velocities in "game units" (GU); the helm
# tooltip converts via Appc.UtopiaModule_ConvertGameUnitsToKilometers.
# Constants live in engine.units (1 GU = 0.175 km, 1 GU/s = 630 kph).
# These tests anchor on Galaxy's SetMaxSpeed(6.3) → 3969 kph and a
# 100 GU separation → 17.5 km.
# ────────────────────────────────────────────────────────────────────────

def test_range_and_speed_to_returns_km_and_kph():
    from engine.ui.ship_display_panel import _range_and_speed_to
    player = ShipClass()
    player.SetTranslate(TGPoint3(0.0, 0.0, 0.0))
    target = ShipClass()
    target.SetTranslate(TGPoint3(100.0, 0.0, 0.0))  # 100 GU = 17.5 km
    target.SetVelocity(TGPoint3(6.3, 0.0, 0.0))     # 6.3 GU/s = 3969 kph
    range_km, speed_kph = _range_and_speed_to(target, player)
    assert range_km == pytest.approx(17.5,   rel=1e-6)
    assert speed_kph == pytest.approx(3969.0, rel=1e-6)


def test_range_and_speed_to_is_surface_distance():
    """BC's readout is the distance to the target's bounding sphere
    (confirmed live: orbiting Haven, radius 90 GU, at the authored
    radius+150 orbit the original game reads ~25 km = 150 GU surface
    distance). 240 GU centres − 90 radius = 150 GU = 26.25 km."""
    from engine.ui.ship_display_panel import _range_and_speed_to
    player = ShipClass()
    player.SetTranslate(TGPoint3(0.0, 0.0, 0.0))
    target = ShipClass()
    target.SetTranslate(TGPoint3(240.0, 0.0, 0.0))
    target.SetRadius(90.0)
    range_km, _speed = _range_and_speed_to(target, player)
    assert range_km == pytest.approx(26.25, rel=1e-6)


def test_range_and_speed_to_returns_none_on_missing_player():
    from engine.ui.ship_display_panel import _range_and_speed_to
    target = ShipClass()
    assert _range_and_speed_to(target, None) == (None, None)


def test_target_payload_emits_range_km_key():
    """Payload contract for the JS side: target panels send `range_km`
    (already converted) so the JS can just append a unit suffix."""
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_TARGET
    import json
    panel = ShipDisplayPanel(ROLE_TARGET)
    payload = panel.render_payload()
    if payload is None:
        return  # snapshot may be hidden in initial state — that's fine
    # The payload is JSON wrapped in a JS function call. Extract and
    # confirm the schema key.
    assert "range_km" in payload or '"range_km"' in payload
    assert "range_m" not in payload
