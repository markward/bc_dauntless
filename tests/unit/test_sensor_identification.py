"""Sensor contact identification pass.

Regression: nothing ever called SensorSubsystem.AddKnownObject or fired
ET_SENSORS_SHIP_IDENTIFIED, so IsObjectKnown was always 0 and the SDK's
Bridge/HelmMenuHandlers.ObjectEnteredSet only ever identified commandable fleet
ships. Planets/stations/neutrals never got a Hail button -> hailing did nothing.

identify_contacts marks newly-detectable contacts known and broadcasts the
SDK's identify event, gated (BC-faithful) by sensor_detection.can_detect.
"""
import App
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import SensorSubsystem
from engine.appc.sets import SetClass
from engine.appc.planet import Planet_Create
from engine.appc import sensor_identification

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
    return s, player, sensors


def test_in_range_contact_is_identified_once():
    _subscribe()
    s, player, sensors = _player_in_set(base_range=2000.0)
    target = ShipClass_Create("BirdOfPrey")
    target.SetTranslateXYZ(1000.0, 0.0, 0.0)   # inside 2000 GU
    s.AddObjectToSet(target, "Bird")

    sensor_identification.identify_contacts(player)
    assert sensors.IsObjectKnown(target) == 1
    assert target in _identified
    assert _identified.count(target) == 1

    # A second sweep must not re-fire for an already-known contact.
    sensor_identification.identify_contacts(player)
    assert _identified.count(target) == 1


def test_out_of_range_contact_not_identified():
    _subscribe()
    s, player, sensors = _player_in_set(base_range=2000.0)
    target = ShipClass_Create("BirdOfPrey")
    target.SetTranslateXYZ(50000.0, 0.0, 0.0)   # far outside range
    s.AddObjectToSet(target, "Bird")

    sensor_identification.identify_contacts(player)
    assert sensors.IsObjectKnown(target) == 0
    assert _identified == []


def _cloaked_contact_in_set(distance_gu):
    """A fully cloaked BirdOfPrey at *distance_gu* in the player's set. The
    player carries 2000 GU sensors, so its cloak bubble (CLOAK_RANGE_FACTOR) is
    20 GU."""
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
    now a multiplier on effective sensor range rather than an absolute. A
    cloaked ship 15 GU away is inside the player's 20 GU bubble, so it IS
    identified: it joins the known set and the callout fires. Deliberate
    divergence from BC — if this fails, ask "was the change reverted?".
    """
    player, sensors, target = _cloaked_contact_in_set(15.0)
    sensor_identification.identify_contacts(player)
    assert sensors.IsObjectKnown(target) == 1
    assert target in _identified


def test_cloaked_contact_outside_the_bubble_is_not_identified():
    """The bubble boundary holds: at 30 GU — well inside the 2000 GU sensor
    reach but outside the 20 GU cloak bubble — a cloaked ship stays unknown and
    silent, exactly as in stock BC."""
    player, sensors, target = _cloaked_contact_in_set(30.0)
    sensor_identification.identify_contacts(player)
    assert sensors.IsObjectKnown(target) == 0
    assert _identified == []


def test_cloaked_contact_is_never_identified_with_the_contest_off(monkeypatch):
    """STOCK-BC BEHAVIOUR, held under ENHANCED_SENSOR_CONTEST = False: cloak is
    absolute, so even the 15 GU contact the contest identifies stays unknown."""
    import engine.appc.sensor_detection as sd
    monkeypatch.setattr(sd, "ENHANCED_SENSOR_CONTEST", False)
    player, sensors, target = _cloaked_contact_in_set(15.0)
    sensor_identification.identify_contacts(player)
    assert sensors.IsObjectKnown(target) == 0
    assert _identified == []


def test_player_not_identified_to_itself():
    _subscribe()
    s, player, sensors = _player_in_set()
    sensor_identification.identify_contacts(player)
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

    sensor_identification.identify_contacts(player)
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

    sensor_identification.identify_contacts(player)
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
    other = ShipClass_Create("BirdOfPrey")
    s.AddObjectToSet(other, "Bird")
    sensor_identification.identify_contacts(player)   # must not raise
    assert _identified == []
