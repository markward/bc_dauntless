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
        # Mark target as known so the sensor gate passes
        player.GetSensorSubsystem().AddKnownObject(foe)
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


def test_target_role_unknown_target_returns_invisible():
    """Sensor knowledge gate: unknown target = no panel data."""
    from engine.appc.ships import ShipClass
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_TARGET
    _, player, _ = _setup_game_with_player()
    try:
        foe = ShipClass(); foe.SetName("Foe")
        player.SetTarget(foe)
        # Sensor subsystem returns IsObjectKnown==0 by default; if not,
        # force it via the subsystem's known-objects set.
        try:
            player.GetSensorSubsystem()._known_objects.discard(foe.GetObjID())
        except Exception:
            pass
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


def test_damage_states_filter_to_named_subsystems_only():
    """Only Engines, Weapons, Sensors, Shield Generator appear in the
    damage list; healthy subsystems are omitted."""
    from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER
    _, player, _ = _setup_game_with_player()
    try:
        eng = player.GetImpulseEngineSubsystem()
        eng.SetDamaged(1)
        panel = ShipDisplayPanel(ROLE_PLAYER)
        snap = panel._snapshot()
        damage = snap[6]
        # Engines should appear; everything else healthy → omitted.
        assert ("Engines", "damaged") in damage
        for name, state in damage:
            assert state in ("damaged", "disabled", "destroyed")
            assert name in ("Engines", "Weapons", "Sensors", "Shield Generator")
    finally:
        _teardown_game()
