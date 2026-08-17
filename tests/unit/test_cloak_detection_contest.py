"""Cloak is a range contest, not an absolute — INTENTIONAL divergence from BC.

Every assertion here pins a deliberate gameplay change. If one of these starts
failing, the question is "was the change reverted?", not "what broke?".
"""
from engine.appc import sensor_detection as sd
from engine.appc.sensor_detection import can_detect
from engine.appc.ai_sensor_gate import observing, _wrap_active_tuple
from engine.appc.ships import ShipClass, ShipClass_Create
from engine.appc.subsystems import CloakingSubsystem, SensorSubsystem


def _observer(base_range=2000.0, condition=100.0):
    """Observer with a REAL sensor subsystem — follows
    tests/unit/test_sensor_detection.py::_ship_with_sensor. A bare ShipClass()
    has none, so effective_sensor_range would return FALLBACK_RANGE_GU (30000),
    fifteen times a Galaxy's real reach, and every assertion below would be
    measuring the fallback instead of the thing it names."""
    ship = ShipClass_Create("Galaxy")
    ship.SetName("player")
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    sensors = SensorSubsystem("Sensors")
    sensors._max_condition = 100.0
    sensors._condition = condition
    sensors.SetBaseSensorRange(base_range)
    ship.SetSensorSubsystem(sensors)
    return ship


def _target(x, cloaked=False, mid_cloak=False):
    """A contact at (x, 0, 0). Cloak construction follows
    tests/unit/test_select_target_drops_cloaked.py::_kitted_ship.

    ``mid_cloak`` drives the subsystem into CLOAK_CLOAKING — the transitional
    state — via the same StartCloaking() the SDK's CloakShip preprocessor
    calls. IsTryingToCloak() is then 1 while IsCloaked() is still 0.
    """
    s = ShipClass()
    s.SetName("Warbird")
    s.SetTranslateXYZ(x, 0.0, 0.0)
    if cloaked or mid_cloak:
        s.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
        if mid_cloak:
            s.GetCloakingSubsystem().StartCloaking()
        else:
            s.GetCloakingSubsystem().InstantCloak()
    return s


def test_cloaked_ship_is_detected_inside_flat_plus_percent_bubble():
    """2000 GU sensors give a flat-10 + 1% = 30 GU cloak bubble — half a
    Galaxy's 60 GU phaser range. You must be effectively on top of it."""
    assert can_detect(_observer(), _target(15.0, cloaked=True)) is True


def test_cloaked_ship_is_not_detected_beyond_the_bubble():
    """45 GU clears the 30 GU bubble with a 15 GU margin — well outside, not
    just past the boundary."""
    assert can_detect(_observer(), _target(45.0, cloaked=True)) is False


def test_uncloaked_ship_at_the_same_distance_is_still_detected():
    """The bubble must apply ONLY to cloaked targets."""
    assert can_detect(_observer(), _target(45.0)) is True


def test_cloak_reach_scales_with_sensor_condition():
    """The 1% term is a percentage of EFFECTIVE range, so damage shrinks the
    bubble toward the flat 10 GU floor — this is what makes boosting sensor
    power meaningful. Full condition: 2000 GU effective -> 10+20=30 GU
    bubble. 50% condition: 1000 GU effective -> 10+10=20 GU bubble. 25 GU
    sits squarely between the two (5 GU margin either side)."""
    assert can_detect(_observer(), _target(25.0, cloaked=True)) is True
    assert can_detect(_observer(condition=50.0),
                      _target(25.0, cloaked=True)) is False


def test_mid_cloak_ship_stays_fully_visible_with_no_bubble_applied():
    """The bubble is gated on IsCloaked(), not IsTryingToCloak(): a ship
    part-way through the fade is still fully sighted at full sensor range.
    500 GU is well beyond the 30 GU cloak bubble, so this only passes if no
    bubble was applied."""
    mid = _target(500.0, mid_cloak=True)
    cloak = mid.GetCloakingSubsystem()
    assert cloak.IsTryingToCloak() == 1
    assert cloak.IsCloaked() == 0
    assert can_detect(_observer(), mid) is True


def test_offline_sensors_detect_nothing_even_point_blank():
    """20% is below the default 25% disabled threshold -> range 0."""
    assert can_detect(_observer(condition=20.0),
                      _target(1.0, cloaked=True)) is False


def test_toggle_off_restores_absolute_cloak(monkeypatch):
    """Flipping the flag must return stock BC exactly: cloak is absolute."""
    monkeypatch.setattr(sd, "ENHANCED_SENSOR_CONTEST", False)
    assert can_detect(_observer(), _target(1.0, cloaked=True)) is False


def test_toggle_off_leaves_uncloaked_detection_untouched(monkeypatch):
    monkeypatch.setattr(sd, "ENHANCED_SENSOR_CONTEST", False)
    assert can_detect(_observer(), _target(500.0)) is True


# ── AI ACQUISITION: the candidate filter ─────────────────────────────────────
#
# The biggest gameplay consequence of the contest, and it is NOT covered by the
# FireScript tests in tests/unit/test_ai_sensor_gate.py — those pin the
# *firing* half, where the AI already holds a lock.
#
# `ai_sensor_gate._wrap_active_tuple` is the candidate filter: it gates
# ObjectGroup.GetActiveObjectTupleInSet on `can_detect` while an observer is
# published. Two SDK enumerators publish one. `SelectTarget.FindGoodTarget`
# carries its OWN absolute cloak skip downstream (AI/Preprocessors.py:1446),
# so a cloaked contact never survives THAT path — but
# `AI/PlainAI/StarbaseAttack.py::GetTargets` has no such skip and returns
# `GetActiveObjectTupleInSet` straight out. So stations DO acquire cloaked
# ships inside their bubble, and the bubble is a flat 10 GU plus 1% of
# BaseSensorRange: fedstarbase 12000 GU -> 130 GU, cardstarbase 5000 -> 60,
# and the 18 of 52 hardpoint files that author no SetBaseSensorRange inherit
# FALLBACK_RANGE_GU (30000) -> 310 GU. Whether those numbers are right is a
# TUNING question for the project owner; these tests pin only that the
# mechanism reaches this surface, both on and off.

def _candidates(observer, contacts):
    """Run *contacts* through the AI candidate filter as *observer* sees them.

    Wraps a fake enumerator the way install_ai_sensor_gate wraps the real
    ObjectGroup.GetActiveObjectTupleInSet, then publishes the observer exactly
    as _wrap_get_targets does around StarbaseAttack.GetTargets.
    """
    wrapped = _wrap_active_tuple(lambda self, pSet: tuple(contacts))
    with observing(observer):
        return wrapped(object(), None)


def test_ai_acquires_a_cloaked_contact_inside_the_bubble():
    """A station/AI enumerating candidates GETS a cloaked ship inside its
    flat-10-plus-1% bubble. This is acquisition from cold, not re-engagement
    of an existing lock."""
    cloaked = _target(15.0, cloaked=True)
    assert _candidates(_observer(), [cloaked]) == (cloaked,)


def test_ai_does_not_acquire_a_cloaked_contact_outside_the_bubble():
    """The boundary holds on this surface too: at 45 GU — well inside the
    2000 GU sensor reach, well outside the 30 GU cloak bubble — the contact
    is filtered out, while an uncloaked ship at the same range survives."""
    cloaked = _target(45.0, cloaked=True)
    plain = _target(45.0)
    assert _candidates(_observer(), [cloaked, plain]) == (plain,)


def test_ai_acquires_no_cloaked_contact_at_all_with_the_contest_off(monkeypatch):
    """STOCK BC, held under ENHANCED_SENSOR_CONTEST = False: cloak is absolute
    on the acquisition path too, so even a point-blank contact is dropped."""
    monkeypatch.setattr(sd, "ENHANCED_SENSOR_CONTEST", False)
    cloaked = _target(1.0, cloaked=True)
    plain = _target(1.0)
    assert _candidates(_observer(), [cloaked, plain]) == (plain,)
