"""Player sensors disabled → UI blanks target rows / forces UNKNOWN
affiliation / drops the target-role panel. Player-role panel is
unaffected; you always know who you are."""
import App
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import SensorSubsystem
from engine.core.game import (
    Game, Episode, Mission, _set_current_game,
)
from engine.ui.ship_display_panel import (
    ROLE_PLAYER, ROLE_TARGET,
    _resolve_ship_for_role, _affiliation_for, player_sensors_offline,
)


def _setup(enemy_in_group=True):
    App._reset_target_menu_singleton()
    mission = Mission()
    episode = Episode(); episode.SetCurrentMission(mission)
    game = Game(); game.SetCurrentEpisode(episode)

    player = ShipClass_Create("Galaxy")
    player.SetName("Player")
    sensors = SensorSubsystem("Sensors")
    sensors._max_condition = 100.0
    sensors._condition = 100.0
    sensors._disabled_percentage = 0.5
    player.SetSensorSubsystem(sensors)
    game.SetPlayer(player)
    _set_current_game(game)

    enemy = ShipClass_Create("BirdOfPrey")
    enemy.SetName("Enemy")
    if enemy_in_group:
        mission.GetEnemyGroup().AddName("Enemy")
    player.SetTarget(enemy)
    return game, player, enemy, sensors, mission


def teardown_function(_):
    _set_current_game(None)


def test_helper_returns_false_when_sensors_healthy():
    _setup()
    assert player_sensors_offline() is False


def test_helper_returns_true_when_sensors_disabled():
    _, _, _, sensors, _ = _setup()
    sensors.SetCondition(10.0)  # below 0.5 * 100 = 50
    assert player_sensors_offline() is True


def test_helper_returns_true_when_sensors_destroyed():
    _, _, _, sensors, _ = _setup()
    sensors.SetCondition(0.0)
    assert player_sensors_offline() is True


def test_resolve_target_returns_none_when_sensors_offline():
    _, player, enemy, sensors, _ = _setup()
    # Healthy: target resolves.
    assert _resolve_ship_for_role(ROLE_TARGET) is enemy
    sensors.SetCondition(10.0)
    assert _resolve_ship_for_role(ROLE_TARGET) is None
    # Player role still works.
    assert _resolve_ship_for_role(ROLE_PLAYER) is player


def test_resolve_target_restored_after_repair():
    _, _, enemy, sensors, _ = _setup()
    sensors.SetCondition(10.0)
    assert _resolve_ship_for_role(ROLE_TARGET) is None
    sensors.SetCondition(100.0)
    assert _resolve_ship_for_role(ROLE_TARGET) is enemy


def test_affiliation_returns_unknown_when_sensors_offline():
    _, player, enemy, sensors, _ = _setup(enemy_in_group=True)
    # Healthy: classifies as ENEMY.
    assert _affiliation_for(enemy, player) == "ENEMY"
    sensors.SetCondition(10.0)
    assert _affiliation_for(enemy, player) == "UNKNOWN"


def test_player_self_affiliation_unaffected_by_sensors_offline():
    """ship is player short-circuits before the sensor gate."""
    _, player, _, sensors, _ = _setup()
    sensors.SetCondition(10.0)
    assert _affiliation_for(player, player) == "FRIENDLY"


def test_affiliation_restored_after_repair():
    _, player, enemy, sensors, _ = _setup(enemy_in_group=True)
    sensors.SetCondition(10.0)
    assert _affiliation_for(enemy, player) == "UNKNOWN"
    sensors.SetCondition(100.0)
    assert _affiliation_for(enemy, player) == "ENEMY"


def _pump(menu, player):
    """One frame of the host loop's contact push (host_loop._pump_contacts).

    Replaces update_target_list_visibility(..., range_units=30000.0): the
    fixture's SensorSubsystem carries no BaseSensorRange, so
    effective_sensor_range returns FALLBACK_RANGE_GU — which IS 30000.0. Same
    reach, one source.
    """
    from engine.appc.perception import perceived_by
    menu.set_contacts(perceived_by(player))


def _drawable(menu, ship):
    """Is *ship* drawable on the target list / radar? Both surfaces walk the
    menu's children and keep IsVisible() == 1 rows, so a contact leaves the
    display either by losing its row or by having it flagged not-visible. With
    the sensors dead, the contact now loses the row outright — the stronger
    outcome — so "absent" reads as not drawable."""
    row = menu.GetObjectEntry(ship)
    return row is not None and row.IsVisible() == 1


def test_update_visibility_hides_all_rows_when_sensors_offline():
    """When player sensors go offline, no row in the target menu is drawable —
    radar and target-list views read this via row.IsVisible()."""
    from engine.appc.sets import SetClass

    _, player, enemy, sensors, _ = _setup()
    target_menu = App.STTargetMenu_CreateW("Targets")
    enemy.SetTranslateXYZ(1000.0, 0.0, 0.0)  # well within 30000 range
    pSet = SetClass()
    pSet.AddObjectToSet(player, "Player")
    pSet.AddObjectToSet(enemy, "Enemy")
    _pump(target_menu, player)
    assert _drawable(target_menu, enemy) is True

    # Disable sensors; the next push makes it undrawable.
    sensors.SetCondition(10.0)
    _pump(target_menu, player)
    assert _drawable(target_menu, enemy) is False


def test_update_visibility_restores_after_sensor_repair():
    from engine.appc.sets import SetClass

    _, player, enemy, sensors, _ = _setup()
    target_menu = App.STTargetMenu_CreateW("Targets")
    enemy.SetTranslateXYZ(1000.0, 0.0, 0.0)
    pSet = SetClass()
    pSet.AddObjectToSet(player, "Player")
    pSet.AddObjectToSet(enemy, "Enemy")

    sensors.SetCondition(10.0)
    _pump(target_menu, player)
    assert _drawable(target_menu, enemy) is False

    sensors.SetCondition(100.0)
    _pump(target_menu, player)
    assert _drawable(target_menu, enemy) is True
