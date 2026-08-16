"""One detection rule everywhere — nebula concealment reaches the UI.

INTENTIONAL STAGE-4 BEHAVIOUR CHANGE. Before this, detection had two rules:
`sensor_detection.can_detect` (weapons, AI targeting, the player's lock) applied
nebula concealment with a per-pair hysteresis latch, while
`perception.perceived_by` (target list, radar) had its own simpler rule that
ignored nebulae entirely. You could select and hold a target you could not fire
on. `perceived_by` now calls `can_detect`, so there is one rule.

If an assertion here starts failing, the question is "was the change reverted?",
not "what broke?".

NOT VACUOUS BY CONSTRUCTION: the contacts below are real `ShipClass` instances
added through `AddObjectToSet` — the only door into `contact_index`'s buckets.
`test_nebula_concealment`'s own `_Ship` fake is not a `ShipClass` and would
never be bucketed, so `perceived_by` would read an empty tuple and every
"not perceivable" assertion would pass for the wrong reason.
`test_the_contacts_are_really_indexed` pins that they are.
"""
import pytest

from engine.appc import contact_index
from engine.appc import sensor_detection as sd
from engine.appc.perception import perceived_by
from engine.appc.sensor_detection import can_detect
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import CloakingSubsystem, SensorSubsystem

import test_nebula_concealment as _tnc


def _contact(pSet, name, x, y, z, cloaked=False):
    """A REAL ShipClass contact, placed and indexed. See the module docstring."""
    s = ShipClass_Create("Galaxy")
    s.SetName(name)
    s.SetTranslateXYZ(x, y, z)
    if cloaked:
        s.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
        s.GetCloakingSubsystem().InstantCloak()
    pSet.AddObjectToSet(s, name)
    return s


def _observer(pSet, x, y, z, base_range=30000.0):
    """A player-shaped observer with a REAL sensor subsystem, following
    tests/unit/test_perceived_by.py::_observer. Explicit range so no assertion
    here is silently measuring FALLBACK_RANGE_GU."""
    ship = ShipClass_Create("Galaxy")
    ship.SetName("player")
    ship.SetTranslateXYZ(x, y, z)
    sensors = SensorSubsystem("Sensors")
    sensors._max_condition = 100.0
    sensors._condition = 100.0
    sensors.SetBaseSensorRange(base_range)
    ship.SetSensorSubsystem(sensors)
    pSet.AddObjectToSet(ship, "player")
    return ship


def _scene():
    """The dense clump from test_nebula_concealment (sphere r=200 at the
    origin), an observer 300 GU out in clear space, one contact buried in the
    core and one contact far outside."""
    contact_index.reset()
    sd.reset_concealment_state()
    pSet, neb = _tnc._set_with_dense_nebula()
    observer = _observer(pSet, 0.0, 0.0, 300.0)
    hidden = _contact(pSet, "Hidden", 0.0, 0.0, 0.0)
    clear = _contact(pSet, "Clear", 0.0, 0.0, 5000.0)
    return pSet, observer, hidden, clear


def _record_for(observer, ship):
    for c in perceived_by(observer):
        if c.ship is ship:
            return c
    raise AssertionError("no contact record for %r" % (ship.GetName(),))


def test_the_contacts_are_really_indexed():
    """Anti-vacuity guard for the whole file: the ships really are ShipClass
    instances in the set's contact_index bucket, so a "not perceivable"
    assertion below is a real answer and not an empty tuple."""
    pSet, observer, hidden, clear = _scene()

    assert contact_index.ships_in(pSet) == (observer, hidden, clear)
    assert len(perceived_by(observer)) == 2
    assert sd.concealment_at(hidden) > 0.5
    assert sd.concealment_at(clear) == 0.0


def test_a_ship_in_dense_nebula_is_not_perceivable():
    """INTENTIONAL BEHAVIOUR CHANGE. Before stage 4 the target list ignored
    nebulae entirely — you could select and hold a target you could not fire
    on. Detection is now one rule everywhere."""
    _pSet, observer, hidden, _clear = _scene()

    assert _record_for(observer, hidden).perceivable is False


def test_a_ship_in_dense_nebula_is_not_targetable():
    """INTENTIONAL BEHAVIOUR CHANGE — the target-list row goes with it.
    `targetable` folds in `perceivable`, so concealment removes the row."""
    _pSet, observer, hidden, _clear = _scene()

    assert _record_for(observer, hidden).targetable is False


def test_a_ship_in_clear_space_is_unaffected():
    """The change must cost nothing outside a nebula: same set, same frame."""
    _pSet, observer, _hidden, clear = _scene()

    record = _record_for(observer, clear)
    assert record.perceivable is True
    assert record.targetable is True


def test_a_concealed_contact_still_reports_its_real_distance():
    """Concealment removes perceivability, NOT the record. The range readouts
    read `dist_sq_gu`/`surface_gu` off it, so those must stay the true
    geometric distance — observer at z=300, contact at the origin."""
    _pSet, observer, hidden, _clear = _scene()

    record = _record_for(observer, hidden)
    assert record.perceivable is False
    assert record.dist_sq_gu == pytest.approx(90000.0)


def test_concealment_does_not_depend_on_the_cloak_toggle(monkeypatch):
    """Nebula concealment is NOT gated by ENHANCED_SENSOR_CONTEST — that flag
    only guards the cloak branch of can_detect. Stock-BC cloak still hides
    nebula-concealed contacts from the UI."""
    monkeypatch.setattr(sd, "ENHANCED_SENSOR_CONTEST", False)
    _pSet, observer, hidden, clear = _scene()

    assert _record_for(observer, hidden).perceivable is False
    assert _record_for(observer, clear).perceivable is True


# ── Cloak reaches the UI too (the other half of dropping is_hidden_by_cloak) ──

def _cloak_scene(x):
    """Observer with 2000 GU sensors (20 GU cloak bubble) and one cloaked
    contact at (x, 0, 0). No nebula."""
    contact_index.reset()
    sd.reset_concealment_state()
    from engine.appc.sets import SetClass
    pSet = SetClass()
    observer = _observer(pSet, 0.0, 0.0, 0.0, base_range=2000.0)
    target = _contact(pSet, "Warbird", x, 0.0, 0.0, cloaked=True)
    return observer, target


def test_a_cloaked_ship_inside_the_bubble_is_now_perceivable():
    """INTENTIONAL BEHAVIOUR CHANGE. The UI used to run the absolute
    `is_hidden_by_cloak`, so a cloaked ship you could already shoot was absent
    from the radar and target list. It now runs the same range contest."""
    observer, target = _cloak_scene(15.0)

    assert _record_for(observer, target).perceivable is True


def test_a_cloaked_ship_beyond_the_bubble_is_still_hidden():
    observer, target = _cloak_scene(25.0)

    assert _record_for(observer, target).perceivable is False


def test_toggle_off_restores_absolute_cloak_in_the_ui(monkeypatch):
    """Stock BC: flipping ENHANCED_SENSOR_CONTEST off makes cloak absolute for
    the UI as well as for the weapons — one rule, one toggle."""
    monkeypatch.setattr(sd, "ENHANCED_SENSOR_CONTEST", False)
    observer, target = _cloak_scene(15.0)

    assert _record_for(observer, target).perceivable is False


# ── The precomputed-distance parameter ───────────────────────────────────────

def test_precomputed_distance_matches_the_internal_computation():
    """`perceived_by` already holds the observer→contact distance for its
    record; passing it in must not change the answer. This is what protects the
    hand-off from drifting away from the real computation."""
    contact_index.reset()
    sd.reset_concealment_state()
    from engine.appc.sets import SetClass
    pSet = SetClass()
    observer = _observer(pSet, 0.0, 0.0, 0.0, base_range=2000.0)
    near = _contact(pSet, "Near", 500.0, 0.0, 0.0)
    far = _contact(pSet, "Far", 2500.0, 0.0, 0.0)

    assert can_detect(observer, near) is True
    assert can_detect(observer, near, dist_sq_gu=250000.0) is True
    assert can_detect(observer, far) is False
    assert can_detect(observer, far, dist_sq_gu=6250000.0) is False


def test_precomputed_distance_is_actually_used():
    """Guards against the parameter being accepted and then ignored: a
    deliberately wrong value must change the answer."""
    contact_index.reset()
    sd.reset_concealment_state()
    from engine.appc.sets import SetClass
    pSet = SetClass()
    observer = _observer(pSet, 0.0, 0.0, 0.0, base_range=2000.0)
    near = _contact(pSet, "Near", 500.0, 0.0, 0.0)

    assert can_detect(observer, near) is True
    # 3000 GU claimed, 2000 GU sensors -> out of range despite the real geometry
    assert can_detect(observer, near, dist_sq_gu=9000000.0) is False


def test_the_hysteresis_latch_is_idempotent_within_a_frame():
    """`perceived_by` calls can_detect once per contact, but the player's
    CURRENT target legitimately sees a second call in the same frame from
    `clear_undetectable_player_lock` (host loop, every frame). That pair must
    not step the latch twice.

    It doesn't, because concealment is stable within a frame: re-running with
    the same conceal value either stays broken (conceal >= the LOWERED
    threshold too) or stays detected (conceal < the RAISED threshold too). Pin
    it — if the latch ever gains a per-call time or counter term, the UI and the
    lock guard would start disagreeing on the frame a lock breaks.
    """
    _pSet, observer, hidden, clear = _scene()

    # Concealed: broken on the first call, still broken on the second.
    assert can_detect(observer, hidden) is False
    assert can_detect(observer, hidden) is False
    # And the UI's answer agrees with a lock-guard call made after it.
    assert _record_for(observer, hidden).perceivable is False
    assert can_detect(observer, hidden) is False

    # Clear: detected, and stays detected however many times it is asked.
    assert can_detect(observer, clear) is True
    assert can_detect(observer, clear) is True
    assert _record_for(observer, clear).perceivable is True
    assert can_detect(observer, clear) is True
