"""perceived_by answers membership + detectability + distance in one pass."""
import pytest

from engine.appc import contact_index
from engine.appc.perception import Contact, perceived_by, contacts_for
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import SensorSubsystem


def _observer(pSet, base_range=2000.0, condition=100.0):
    """A player-shaped ship with a REAL sensor subsystem.

    Follows tests/unit/test_sensor_detection.py::_ship_with_sensor. This
    matters: a bare ShipClass() has no sensor subsystem, so
    effective_sensor_range falls back to FALLBACK_RANGE_GU (30000) — 15x a
    Galaxy's real range — and every range assertion below would be testing
    the fallback instead of the thing it names.
    """
    ship = ShipClass_Create("Galaxy")
    ship.SetName("player")
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    sensors = SensorSubsystem("Sensors")
    sensors._max_condition = 100.0
    sensors._condition = condition
    sensors.SetBaseSensorRange(base_range)
    ship.SetSensorSubsystem(sensors)
    pSet.AddObjectToSet(ship, "player")
    return ship, sensors


def _placed(pSet, name, x=0.0, radius=0.0):
    """A contact in pSet at (x, 0, 0) with the given bounding radius."""
    s = ShipClass_Create("Galaxy")
    s.SetName(name)
    s.SetTranslateXYZ(x, 0.0, 0.0)
    if radius:
        s.SetRadius(radius)
    pSet.AddObjectToSet(s, name)
    return s


def test_contact_carries_ship_and_flags():
    contact_index.reset()
    pSet = SetClass()
    player, _ = _observer(pSet)
    other = _placed(pSet, "Galor", x=10.0)

    got = perceived_by(player)

    assert len(got) == 1
    assert isinstance(got[0], Contact)
    assert got[0].ship is other
    assert got[0].perceivable is True
    assert got[0].targetable is True


def test_observer_is_never_its_own_contact():
    contact_index.reset()
    pSet = SetClass()
    player, _ = _observer(pSet)

    assert perceived_by(player) == ()


def test_the_record_carries_no_squared_distance():
    """`dist_sq_gu` is NOT on the record, deliberately — do not put it back.

    It had zero readers. `perceived_by` genuinely needs the squared centre
    distance as a LOCAL (it feeds `can_detect`'s `dist_sq_gu=` hand-off and
    `_surface_gu`), but nothing downstream ever asked the record for it: the
    target list reads `targetable`, the radar reads `perceivable` and then
    clips in its own DISC PLANE (a 3D centre distance cannot answer that), and
    the range readouts read `surface_gu`. Carrying it made the record look like
    the answer to a question no consumer asks.

    The two things that DO use it are still pinned, by
    test_surface_distance_subtracts_the_target_radius below and by
    tests/unit/test_nebula_hides_contacts_from_ui.py::
    test_precomputed_distance_is_actually_used.
    """
    assert "dist_sq_gu" not in Contact.__dataclass_fields__


def test_surface_distance_subtracts_the_target_radius():
    """BC's range readout is to the bounding sphere, not the centre —
    negligible for ships, decisive for planets and stations."""
    contact_index.reset()
    pSet = SetClass()
    player, _ = _observer(pSet)
    _placed(pSet, "Starbase", x=100.0, radius=40.0)

    assert perceived_by(player)[0].surface_gu == pytest.approx(60.0)


def test_surface_distance_clamps_at_zero_when_inside_the_radius():
    contact_index.reset()
    pSet = SetClass()
    player, _ = _observer(pSet)
    _placed(pSet, "Planet", x=10.0, radius=90.0)

    assert perceived_by(player)[0].surface_gu == 0.0


def test_contact_beyond_sensor_range_is_not_perceivable():
    """2000 GU sensors, contact at 2500 GU — out of range but still a
    contact record, because membership and perception are separate answers."""
    contact_index.reset()
    pSet = SetClass()
    player, _ = _observer(pSet, base_range=2000.0)
    _placed(pSet, "Faraway", x=2500.0)

    got = perceived_by(player)

    assert len(got) == 1
    assert got[0].perceivable is False


def test_offline_sensors_make_nothing_perceivable():
    """Matches update_target_list_visibility's early return today. 20% is
    below the default 25% disabled threshold, so the array reads offline."""
    contact_index.reset()
    pSet = SetClass()
    player, _ = _observer(pSet, condition=20.0)
    _placed(pSet, "Galor", x=10.0)

    assert all(not c.perceivable for c in perceived_by(player))


def test_non_targetable_contact_is_still_perceivable():
    """targetable and perceivable are different questions — a mission-hidden
    ship is still detected, it just cannot be a target-list row."""
    contact_index.reset()
    pSet = SetClass()
    player, _ = _observer(pSet)
    hidden = _placed(pSet, "Kessok", x=10.0)
    hidden.SetTargetable(0)

    got = perceived_by(player)

    assert got[0].perceivable is True
    assert got[0].targetable is False


def test_targetable_always_implies_perceivable():
    """THE IMPLICATION THE UI RELIES ON — it holds in only one direction.

    `targetable` is built as `perceivable and alive_or_wreck and
    IsTargetable()`, so it can never be True while `perceivable` is False. That
    is what lets the target list and the radar walk the SAME children (filtered
    on `targetable`) without either re-checking perceivability: a listed row is
    a perceivable one by construction. engine/ui/sensors_panel.py used to carry
    a `not record.perceivable: continue` guard inside that walk which could
    therefore never fire; it was removed and this is what replaced it.

    Swept over the clauses that can each pull one flag down independently —
    out of range, mission-untargetable, and both at once.
    """
    contact_index.reset()
    pSet = SetClass()
    player, _ = _observer(pSet, base_range=2000.0)
    _placed(pSet, "Close", x=10.0)
    _placed(pSet, "Faraway", x=2500.0)
    untargetable = _placed(pSet, "Kessok", x=20.0)
    untargetable.SetTargetable(0)
    both = _placed(pSet, "FarAndHidden", x=2600.0)
    both.SetTargetable(0)

    got = perceived_by(player)

    assert len(got) == 4                                   # not vacuous
    assert {c.perceivable for c in got} == {True, False}    # both values seen
    assert {c.targetable for c in got} == {True, False}
    for c in got:
        assert not (c.targetable and not c.perceivable), c.ship.GetName()


def test_contacts_for_still_returns_targetable_ships():
    """Back-compat wrapper — existing callers must not change behaviour."""
    contact_index.reset()
    pSet = SetClass()
    player, _ = _observer(pSet)
    other = _placed(pSet, "Galor", x=10.0)
    hidden = _placed(pSet, "Kessok", x=20.0)
    hidden.SetTargetable(0)

    assert contacts_for(player) == (other,)


def test_no_observer_or_no_set_reads_empty():
    contact_index.reset()
    adrift = ShipClass_Create("Galaxy")
    adrift.SetName("Adrift")
    assert perceived_by(None) == ()
    assert perceived_by(adrift) == ()
