"""Sensor contact identification commit (``_identify_one``), driven through the
player-only contact manager's passive dwell (``engine.appc.sensor_contacts``).

Regression: nothing ever called SensorSubsystem.AddKnownObject or fired
ET_SENSORS_SHIP_IDENTIFIED, so IsObjectKnown was always 0 and the SDK's
Bridge/HelmMenuHandlers.ObjectEnteredSet only ever identified commandable fleet
ships. Planets/stations/neutrals never got a Hail button -> hailing did nothing.

The passive dwell marks newly-detectable contacts known one identification
time after they enter near band, gated (BC-faithful) by
sensor_detection.can_detect. ``tests.helpers.sensor_time.settle_identification``
drives the manager through one sweep plus one full dwell, which is all any of
these tests need.
"""
import App
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import SensorSubsystem
from engine.appc.sets import SetClass
from engine.appc.planet import Planet_Create
from engine.core.game import Game, _set_current_game
from tests.helpers.cloak_geometry import inside_gu, outside_gu
from tests.helpers.sensor_time import settle_identification

_identified: list = []


def _on_identified(dest, event):
    _identified.append(event.GetDestination())


def _subscribe():
    _identified.clear()
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_SENSORS_SHIP_IDENTIFIED, None, __name__ + "._on_identified")


def _player_in_set(base_range=2000.0, at=(0.0, 0.0, 0.0)):
    s = SetClass()
    player = ShipClass_Create("Galaxy")
    player.SetTranslateXYZ(*at)
    sensors = SensorSubsystem("Sensors")
    sensors._max_condition = 100.0
    sensors._condition = 100.0
    sensors.SetBaseSensorRange(base_range)
    player.SetSensorSubsystem(sensors)
    s.AddObjectToSet(player, "player")
    # The contact manager is player-only and reads the CURRENT GAME player
    # (same idiom as tests/unit/test_sensor_contacts.py::_world).
    game = Game()
    game.SetPlayer(player)
    _set_current_game(game)
    return s, player, sensors


def test_in_range_contact_is_identified_once():
    _subscribe()
    s, player, sensors = _player_in_set(base_range=2000.0)
    target = ShipClass_Create("BirdOfPrey")
    # Exactly half of the 2000 GU range -- the near-band boundary. The near
    # check is `<=`, so a contact sitting exactly on the boundary still gets
    # identified.
    target.SetTranslateXYZ(1000.0, 0.0, 0.0)
    s.AddObjectToSet(target, "Bird")

    settle_identification(player)
    assert sensors.IsObjectKnown(target) == 1
    assert target in _identified
    assert _identified.count(target) == 1

    # A second settle must not re-fire for an already-known contact.
    settle_identification(player, start_gt=100.0)
    assert _identified.count(target) == 1


def test_out_of_range_contact_not_identified():
    _subscribe()
    s, player, sensors = _player_in_set(base_range=2000.0)
    target = ShipClass_Create("BirdOfPrey")
    target.SetTranslateXYZ(50000.0, 0.0, 0.0)   # far outside range
    s.AddObjectToSet(target, "Bird")

    settle_identification(player)
    assert sensors.IsObjectKnown(target) == 0
    assert _identified == []


def _cloaked_contact_in_set(distance_gu):
    """A fully cloaked BirdOfPrey at *distance_gu* in the player's set. The
    player carries 2000 GU sensors. Pass *distance_gu* from
    tests.helpers.cloak_geometry so a cloak retune needs no edit here."""
    from engine.appc.subsystems import CloakingSubsystem
    _subscribe()
    s, player, sensors = _player_in_set(base_range=2000.0)
    target = ShipClass_Create("BirdOfPrey")
    target.SetTranslateXYZ(float(distance_gu), 0.0, 0.0)
    target.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
    target.GetCloakingSubsystem().InstantCloak()
    s.AddObjectToSet(target, "Bird")
    return player, sensors, target


def test_cloaked_contact_inside_the_bubble_is_identified():
    """INTENTIONAL stage-4 gameplay change (ENHANCED_SENSOR_CONTEST, default on).

    The identification sweep gates on sensor_detection.can_detect, and cloak is
    now a flat floor plus a percentage of effective sensor range rather than an
    absolute. A cloaked ship inside the player's bubble IS identified: it joins
    the known set and the callout fires. The cloak bubble distances here are
    well inside half the 2000 GU sensor range, so they land in the near band
    regardless of cloak. Deliberate divergence from BC — if this fails, ask
    "was the change reverted?".
    """
    player, sensors, target = _cloaked_contact_in_set(inside_gu())
    settle_identification(player)
    assert sensors.IsObjectKnown(target) == 1
    assert target in _identified


def test_cloaked_contact_outside_the_bubble_is_not_identified():
    """The bubble boundary holds: well inside the 2000 GU sensor reach (so still
    in near band) but outside the cloak bubble, a cloaked ship stays unknown
    and silent, exactly as in stock BC."""
    player, sensors, target = _cloaked_contact_in_set(outside_gu())
    settle_identification(player)
    assert sensors.IsObjectKnown(target) == 0
    assert _identified == []


def test_cloaked_contact_is_never_identified_with_the_contest_off(monkeypatch):
    """STOCK-BC BEHAVIOUR, held under ENHANCED_SENSOR_CONTEST = False: cloak is
    absolute, so even the 15 GU contact the contest identifies stays unknown."""
    import engine.appc.sensor_detection as sd
    monkeypatch.setattr(sd, "ENHANCED_SENSOR_CONTEST", False)
    player, sensors, target = _cloaked_contact_in_set(inside_gu())
    settle_identification(player)
    assert sensors.IsObjectKnown(target) == 0
    assert _identified == []


def test_player_not_identified_to_itself():
    _subscribe()
    s, player, sensors = _player_in_set()
    settle_identification(player)
    assert sensors.IsObjectKnown(player) == 0
    assert player not in _identified


def test_hailable_planet_becomes_identified_in_range():
    """The E1M2 case: a planet in sensor range is identified, so the SDK's
    HailableChange->ObjectEnteredSet gate (IsObjectKnown) can add its button."""
    _subscribe()
    s, player, sensors = _player_in_set(base_range=5000.0)
    haven = Planet_Create(200.0, "colony.nif")
    haven.SetTranslateXYZ(1500.0, 0.0, 0.0)
    s.AddObjectToSet(haven, "Haven")

    settle_identification(player)
    assert sensors.IsObjectKnown(haven) == 1
    assert haven in _identified


def test_non_contact_objects_are_not_identified():
    """Lights, placement markers, grids etc. share the set but are not sensor
    contacts — they must never be identified (which would spam the Hail menu)."""
    _subscribe()
    s, player, sensors = _player_in_set(base_range=30000.0)
    from engine.appc.objects import ObjectClass
    # Bare ObjectClass stands in for the set's non-contact objects (grid,
    # "Player Start" / "* Location" markers, lights) — none are ShipClass/Planet.
    grid = ObjectClass()
    grid.SetTranslateXYZ(100.0, 0.0, 0.0)
    s.AddObjectToSet(grid, "grid")
    marker = ObjectClass()
    marker.SetTranslateXYZ(100.0, 0.0, 0.0)
    s.AddObjectToSet(marker, "Player Start")

    settle_identification(player)
    assert sensors.IsObjectKnown(grid) == 0
    assert sensors.IsObjectKnown(marker) == 0
    assert _identified == []


def test_force_object_identified_marks_planet_known():
    """SDK HelmMenuHandlers.SetupOrbitMenuFromSet calls
    pSensors.ForceObjectIdentified(pPlanet) so orbitable planets are targetable.
    Reuses the identification store (ignores range) and fires the event once."""
    _subscribe()
    s, player, sensors = _player_in_set()
    haven = Planet_Create(200.0, "colony.nif")
    haven.SetTranslateXYZ(999999.0, 0.0, 0.0)   # far away — range is ignored
    s.AddObjectToSet(haven, "Haven")

    sensors.ForceObjectIdentified(haven)
    assert sensors.IsObjectKnown(haven) == 1
    assert haven in _identified
    assert _identified.count(haven) == 1

    # De-dupe: a second force is a no-op.
    sensors.ForceObjectIdentified(haven)
    assert _identified.count(haven) == 1


def test_npc_force_identify_does_not_release_the_players_placeholder():
    """ForceObjectIdentified on an NPC's OWN sensors (not the current GAME
    player's) must mark the contact known to that NPC but leave the PLAYER's
    "Unknown N" placeholder allocated -- the player's target list / reticle
    are still showing it unidentified. Only the current player's own
    identification path may rename/release (`sensors._owner_ship() is
    sensor_contacts.current_player()`)."""
    _subscribe()
    s, player, sensors = _player_in_set()
    from engine.appc import unknown_labels
    unknown_labels.reset()

    npc = ShipClass_Create("Galaxy")
    npc_sensors = SensorSubsystem("Sensors")
    npc.SetSensorSubsystem(npc_sensors)
    s.AddObjectToSet(npc, "npc")

    target = ShipClass_Create("BirdOfPrey")
    s.AddObjectToSet(target, "Bird")
    placeholder = unknown_labels.placeholder(target)   # the player's row number

    npc_sensors.ForceObjectIdentified(target)

    assert npc_sensors.IsObjectKnown(target) == 1
    assert target in _identified
    # The NPC's own identification must not touch the player-visible number.
    assert unknown_labels.current(target) == placeholder


def test_force_object_identified_none_safe():
    _subscribe()
    s, player, sensors = _player_in_set()
    sensors.ForceObjectIdentified(None)   # must not raise
    assert _identified == []


def test_no_sensor_subsystem_is_noop():
    _subscribe()
    s = SetClass()
    player = ShipClass_Create("Galaxy")
    player._sensor_subsystem = None   # force the no-sensor path
    s.AddObjectToSet(player, "player")
    game = Game()
    game.SetPlayer(player)
    _set_current_game(game)
    other = ShipClass_Create("BirdOfPrey")
    s.AddObjectToSet(other, "Bird")
    settle_identification(player)   # must not raise
    assert _identified == []
