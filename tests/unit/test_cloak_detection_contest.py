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
    """2000 GU sensors give a flat-10 + 0.5% = 20 GU cloak bubble — well under
    half a Galaxy's 60 GU phaser range. You must be effectively on top of it."""
    assert can_detect(_observer(), _target(15.0, cloaked=True)) is True


def test_cloaked_ship_is_not_detected_beyond_the_bubble():
    """45 GU clears the 20 GU bubble with a 25 GU margin — well outside, not
    just past the boundary."""
    assert can_detect(_observer(), _target(45.0, cloaked=True)) is False


def test_uncloaked_ship_at_the_same_distance_is_still_detected():
    """The bubble must apply ONLY to cloaked targets."""
    assert can_detect(_observer(), _target(45.0)) is True


def test_cloak_reach_scales_with_sensor_condition():
    """The 0.5% term is a percentage of EFFECTIVE range, so damage shrinks the
    bubble toward the flat 10 GU floor — this is what makes boosting sensor
    power meaningful. Full condition: 2000 GU effective -> 10+10=20 GU
    bubble. 50% condition: 1000 GU effective -> 10+5=15 GU bubble.

    ⚠️ THE MARGIN THIS TEST HAS TO WORK IN IS NARROW AND SHRINKING. Raising the
    flat base while cutting the factor (5 GU/1% -> 10 GU/0.5% on 2026-08-17)
    compressed the full-vs-half spread from 25/15 GU to 20/15 GU, so the probe
    distance has only a 5 GU window and sits at its midpoint: 2.5 GU inside the
    full bubble, 2.5 GU outside the half. A further retune in the same direction
    closes the window entirely and makes this test unwritable — which is itself
    the signal that the condition lever has stopped meaning anything. Do not
    respond by moving the probe onto a boundary (`dist == r` DETECTS, so a
    boundary pick passes for the wrong reason); re-derive both legs."""
    assert can_detect(_observer(), _target(17.5, cloaked=True)) is True
    assert can_detect(_observer(condition=50.0),
                      _target(17.5, cloaked=True)) is False


def test_mid_cloak_ship_stays_fully_visible_with_no_bubble_applied():
    """The bubble is gated on IsCloaked(), not IsTryingToCloak(): a ship
    part-way through the fade is still fully sighted at full sensor range.
    500 GU is well beyond the 20 GU cloak bubble, so this only passes if no
    bubble was applied."""
    mid = _target(500.0, mid_cloak=True)
    cloak = mid.GetCloakingSubsystem()
    assert cloak.IsTryingToCloak() == 1
    assert cloak.IsCloaked() == 0
    assert can_detect(_observer(), mid) is True


def test_cloak_bubble_is_exactly_base_plus_factor_of_effective_range():
    """The bubble's boundary is exactly CLOAK_DETECTION_BASE_GU +
    effective_range * CLOAK_RANGE_FACTOR — the formula's SHAPE, pinned.

    Why this exists: every other test here probes a distance with a margin, so
    the whole file passed identically under BOTH the 5 GU/1% and the 10 GU/0.5%
    tunings (verified by mutation 2026-08-17). That left the arithmetic
    untested — dropping the flat term, multiplying instead of adding, or
    fat-fingering 0.05 for 0.005 would all have stayed green while gutting
    cloak. This test reads the constants rather than hardcoding them, so a
    deliberate retune stays free; only a change to the SHAPE fails it.

    `can_detect` compares `dist_sq <= r * r`, so a target exactly ON the
    boundary IS detected and the first assertion is the true edge."""
    r = sd.CLOAK_DETECTION_BASE_GU + 2000.0 * sd.CLOAK_RANGE_FACTOR
    assert can_detect(_observer(), _target(r, cloaked=True)) is True
    assert can_detect(_observer(), _target(r + 0.5, cloaked=True)) is False


def test_cloak_bubble_stays_well_inside_phaser_range():
    """A TUNING GUARD, not a formula test: the bubble must stay a fraction of a
    Galaxy's 60 GU phaser range, because "you must be effectively on top of it"
    is the whole design intent — a bubble approaching weapon range would mean
    cloak no longer protects anyone from the player.

    Deliberately a loose bound (half of phaser range), so ordinary retuning
    never trips it. It catches the order-of-magnitude slip — 0.05 for 0.005
    gives a Galaxy 110 GU, nearly twice its phaser reach — which is exactly the
    error no other assertion here would notice."""
    r = sd.CLOAK_DETECTION_BASE_GU + 2000.0 * sd.CLOAK_RANGE_FACTOR
    assert 0.0 < r <= 30.0, f"Galaxy cloak bubble {r} GU vs 60 GU phaser range"


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
# ships inside their bubble, and the bubble is a flat 10 GU plus 0.5% of
# BaseSensorRange: fedstarbase 12000 GU -> 70 GU, cardstarbase 5000 -> 35,
# and the 18 of 52 hardpoint files that author no SetBaseSensorRange inherit
# FALLBACK_RANGE_GU (30000) -> 160 GU. Whether those numbers are right is a
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
    flat-10-plus-0.5% bubble. This is acquisition from cold, not re-engagement
    of an existing lock."""
    cloaked = _target(15.0, cloaked=True)
    assert _candidates(_observer(), [cloaked]) == (cloaked,)


def test_ai_does_not_acquire_a_cloaked_contact_outside_the_bubble():
    """The boundary holds on this surface too: at 45 GU — well inside the
    2000 GU sensor reach, well outside the 20 GU cloak bubble — the contact
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
