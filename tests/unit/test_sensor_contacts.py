"""Player-only contact manager (sensor-tiers spec §1)."""
import App
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import SensorSubsystem
from engine.appc.sets import SetClass
from engine.appc import sensor_contacts
from engine.core.game import Game, _set_current_game

_events: list = []


def _on_any(dest, event):
    _events.append((event.GetEventType(), event.GetSource(),
                    getattr(event, "GetBool", lambda: None)(),
                    event.GetDestination()))


def _subscribe():
    _events.clear()
    for et in (App.ET_SENSORS_SHIP_FAR_PROXIMITY,
               App.ET_SENSORS_SHIP_NEAR_PROXIMITY,
               App.ET_SENSORS_SHIP_IDENTIFIED):
        App.g_kEventManager.AddBroadcastPythonFuncHandler(
            et, None, __name__ + "._on_any")


def _world(base_range=2000.0):
    s = SetClass()
    player = ShipClass_Create("Galaxy")
    sensors = SensorSubsystem("Sensors")
    sensors._max_condition = 100.0
    sensors._condition = 100.0
    sensors.SetBaseSensorRange(base_range)
    player.SetSensorSubsystem(sensors)
    s.AddObjectToSet(player, "player")
    # on_exited_set / player_knows read the CURRENT GAME player
    # (Game_GetCurrentGame().GetPlayer()) -- same idiom as
    # tests/unit/test_game.py::test_game_set_and_get_player.
    game = Game()
    game.SetPlayer(player)
    _set_current_game(game)
    return s, player, sensors


def _ship(s, name, x):
    ship = ShipClass_Create("BirdOfPrey")
    ship.SetTranslateXYZ(float(x), 0.0, 0.0)
    s.AddObjectToSet(ship, name)
    return ship


def _of(et):
    return [e for e in _events if e[0] == et]


def test_far_band_entry_posts_far_with_source_ship_and_no_identify():
    _subscribe()
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 1500.0)          # far, not near
    sensor_contacts.tick(player, 0.0)
    far = _of(App.ET_SENSORS_SHIP_FAR_PROXIMITY)
    assert len(far) == 1
    assert far[0][1] is bird and far[0][2] == 1
    assert far[0][3] is sensors
    assert _of(App.ET_SENSORS_SHIP_NEAR_PROXIMITY) == []
    sensor_contacts.tick(player, 10.0)
    assert sensors.IsObjectKnown(bird) == 0   # never near => never identified


def test_near_band_identifies_after_the_dwell_not_before():
    _subscribe()
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)
    sensor_contacts.tick(player, 0.0)
    near = _of(App.ET_SENSORS_SHIP_NEAR_PROXIMITY)
    assert len(near) == 1 and near[0][1] is bird and near[0][2] == 1
    sensor_contacts.tick(player, 3.9)
    assert sensors.IsObjectKnown(bird) == 0
    sensor_contacts.tick(player, 4.0)
    assert sensors.IsObjectKnown(bird) == 1
    assert [e[3] for e in _of(App.ET_SENSORS_SHIP_IDENTIFIED)] == [bird]


def test_entry_order_is_far_then_near_and_exit_near_then_far():
    _subscribe()
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)
    sensor_contacts.tick(player, 0.0)
    kinds = [e[0] for e in _events]
    assert kinds == [App.ET_SENSORS_SHIP_FAR_PROXIMITY,
                     App.ET_SENSORS_SHIP_NEAR_PROXIMITY]
    _events.clear()
    bird.SetTranslateXYZ(9000.0, 0.0, 0.0)
    sensor_contacts.tick(player, 1.0)
    assert [(e[0], e[2]) for e in _events] == [
        (App.ET_SENSORS_SHIP_NEAR_PROXIMITY, 0),
        (App.ET_SENSORS_SHIP_FAR_PROXIMITY, 0)]


def test_sweep_runs_on_its_period_not_every_tick():
    _subscribe()
    s, player, sensors = _world()
    sensor_contacts.tick(player, 0.0)
    bird = _ship(s, "Bird", 1500.0)
    sensor_contacts.tick(player, 0.5)
    assert _of(App.ET_SENSORS_SHIP_FAR_PROXIMITY) == []
    sensor_contacts.tick(player, 1.0)
    assert len(_of(App.ET_SENSORS_SHIP_FAR_PROXIMITY)) == 1


def test_leaving_the_near_band_mid_dwell_aborts():
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)
    sensor_contacts.tick(player, 0.0)
    bird.SetTranslateXYZ(1500.0, 0.0, 0.0)
    sensor_contacts.tick(player, 4.0)
    assert sensors.IsObjectKnown(bird) == 0


def test_sensors_lost_mid_dwell_aborts():
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)
    sensor_contacts.tick(player, 0.0)
    sensors._power_factor = 0.0
    sensor_contacts.tick(player, 4.0)
    assert sensors.IsObjectKnown(bird) == 0


def test_identity_survives_leaving_range():
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)
    sensor_contacts.tick(player, 0.0)
    sensor_contacts.tick(player, 4.0)
    bird.SetTranslateXYZ(9000.0, 0.0, 0.0)
    sensor_contacts.tick(player, 5.0)
    assert sensors.IsObjectKnown(bird) == 1


def test_exit_set_mid_dwell_never_identifies():
    _subscribe()
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)
    sensor_contacts.tick(player, 0.0)
    s.RemoveObjectFromSet("Bird")
    assert sensor_contacts.is_pending(bird) is False
    s.AddObjectToSet(bird, "Bird")            # back, but the old dwell is gone
    sensor_contacts.tick(player, 4.0)
    assert _of(App.ET_SENSORS_SHIP_IDENTIFIED) == []


def test_exit_set_forgets_a_known_contact():
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)
    sensors.AddKnownObject(bird)
    s.RemoveObjectFromSet("Bird")
    assert sensors.IsObjectKnown(bird) == 0


def test_player_leaving_its_set_wipes_everything():
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)
    sensors.AddKnownObject(bird)
    sensor_contacts.tick(player, 0.0)
    s.RemoveObjectFromSet("player")
    assert sensors.IsObjectKnown(bird) == 0
    assert sensor_contacts.is_pending(bird) is False


def test_a_new_player_starts_with_a_clean_manager():
    _subscribe()
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 1500.0)
    sensor_contacts.tick(player, 0.0)
    other = ShipClass_Create("Galaxy")
    sensors2 = SensorSubsystem("Sensors")
    sensors2._max_condition = 100.0
    sensors2._condition = 100.0
    sensors2.SetBaseSensorRange(2000.0)
    other.SetSensorSubsystem(sensors2)
    s.AddObjectToSet(other, "other")
    _events.clear()
    sensor_contacts.tick(other, 5.0)
    # bird is re-reported as entering the new player's far band
    assert any(e[0] == App.ET_SENSORS_SHIP_FAR_PROXIMITY and e[1] is bird
               for e in _events)


def test_a_dead_player_ref_triggers_a_wipe_like_a_live_swap():
    """A RECORDED ref that no longer resolves to the new player is a swap,
    even when the old player is now dead -- only `_player_ref is None`
    (never-recorded) is first sight. Simulates a dead weakref directly
    (returns None on call, exactly like a collected referent) rather than
    forcing a real GC, which other fixtures' live references would defeat."""
    _subscribe()
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 1500.0)          # far, not near
    sensor_contacts.tick(player, 0.0)
    assert len(_of(App.ET_SENSORS_SHIP_FAR_PROXIMITY)) == 1

    import engine.appc.sensor_contacts as sc
    sc._player_ref = lambda: None            # pretend the old ref died

    other = ShipClass_Create("Galaxy")
    sensors2 = SensorSubsystem("Sensors")
    sensors2._max_condition = 100.0
    sensors2._condition = 100.0
    sensors2.SetBaseSensorRange(2000.0)
    other.SetSensorSubsystem(sensors2)
    s.AddObjectToSet(other, "other")
    _events.clear()
    sensor_contacts.tick(other, 5.0)
    # bird is re-reported as entering the NEW player's far band -- the wipe
    # must have cleared the dead player's `_far` membership for it.
    assert any(e[0] == App.ET_SENSORS_SHIP_FAR_PROXIMITY and e[1] is bird
               for e in _events)


def test_reset_clears_pending():
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 500.0)
    sensor_contacts.tick(player, 0.0)
    sensor_contacts.reset()
    sensor_contacts.tick(player, 4.0)        # sweeps again at 4.0, commit at 8.0
    assert sensors.IsObjectKnown(bird) == 0


def test_planets_are_identified_too():
    from engine.appc.planet import Planet_Create
    s, player, sensors = _world()
    planet = Planet_Create(10.0, "data/models/environment/planet.nif")
    planet.SetTranslateXYZ(500.0, 0.0, 0.0)
    s.AddObjectToSet(planet, "Haven")
    sensor_contacts.tick(player, 0.0)
    sensor_contacts.tick(player, 4.0)
    assert sensors.IsObjectKnown(planet) == 1


def test_scheduled_scan_before_first_tick_still_commits():
    """CONTROLLER RULING: _sync_player must wipe _pending only when a
    PREVIOUS player existed and differs from the new one. When _player_ref
    is None (first sight, or right after reset()), the manager must keep any
    scan already scheduled by schedule_scan (Task 5's IdentifyObject) --
    which can run before this module's first tick of a mission. If
    _sync_player wiped _pending unconditionally on first sight, that scan
    would be silently cancelled the moment tick() first runs."""
    import engine.appc.sensor_contacts as sc
    s, player, sensors = _world()
    bird = _ship(s, "Bird", 1500.0)          # far band: would never be
                                              # picked up by the passive sweep
    fixed_now = 100.0
    orig_now = sc._now
    sc._now = lambda: fixed_now
    try:
        sc.schedule_scan(bird, 4.0)          # due at 104.0, before any tick
        assert sc.is_pending(bird) is True
        # First tick ever, due time not yet reached: still armed.
        sc.tick(player, 103.0)
        assert sc.is_pending(bird) is True
        assert sensors.IsObjectKnown(bird) == 0
        # Due time reached: the scan commits unconditionally (by_scan=True),
        # even though bird is in the far band, not the near band.
        sc.tick(player, 104.0)
        assert sensors.IsObjectKnown(bird) == 1
    finally:
        sc._now = orig_now
