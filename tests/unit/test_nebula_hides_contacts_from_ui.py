"""One detection rule everywhere — nebula concealment reaches the UI.

INTENTIONAL STAGE-4 BEHAVIOUR CHANGE. Before this, detection had two rules:
`sensor_detection.can_detect` (weapons, AI targeting, the player's lock) applied
nebula concealment with a per-pair hysteresis latch, while
`perception.perceived_by` (target list, radar) had its own simpler rule that
ignored nebulae entirely. You could select and hold a target you could not fire
on. `perceived_by` now calls `can_detect`, so there is one rule.

Both stage-4 sensing changes (this one and the range-contest cloak) sit behind
the SINGLE `sensor_detection.ENHANCED_SENSOR_CONTEST` toggle, so turning it off
restores the pre-stage-4 game as a set. The "toggle covers BOTH stage-4 changes"
block below pins that, including the deliberate wart in the off state.

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
from engine.appc.subsystems import CloakingSubsystem, SensorSubsystem, _get_xyz

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
    on. Detection is now one rule everywhere.

    Paired with test_toggle_off_restores_the_pre_stage_4_ui_rule below, which
    asserts the opposite under ENHANCED_SENSOR_CONTEST = False.
    """
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


# ── The toggle covers BOTH stage-4 changes ───────────────────────────────────
# ONE flag, by explicit design decision: ENHANCED_SENSOR_CONTEST means "the
# stage-4 sensing changes", not "cloak specifically". Turning it off must give
# back the pre-stage-4 game, warts included.

def test_toggle_off_restores_the_pre_stage_4_ui_rule(monkeypatch):
    """With the toggle off the target list and radar ignore nebulae again —
    exactly as they did before stage 4.

    The off-state is defined as "how the game behaved before", so it restores
    the pre-stage-4 rule wholesale: range + absolute cloak + distance, no
    concealment term.
    """
    monkeypatch.setattr(sd, "ENHANCED_SENSOR_CONTEST", False)
    _pSet, observer, hidden, clear = _scene()

    assert _record_for(observer, hidden).perceivable is True
    assert _record_for(observer, clear).perceivable is True


def test_weapons_still_apply_nebula_concealment_with_the_toggle_off():
    """THE WART, PINNED DELIBERATELY. The toggle gates only who *consults* the
    nebula rule on the UI side; can_detect keeps applying concealment
    unconditionally for weapons and AI, which is what it did before stage 4.

    So with the flag off the two surfaces disagree again — you can select a
    nebula-hidden target you cannot fire on. That inconsistency IS the
    pre-stage-4 behaviour and is the whole point of an off switch. See the
    ENHANCED_SENSOR_CONTEST docstring in sensor_detection.py.
    """
    import pytest as _pytest
    _pSet, observer, hidden, _clear = _scene()
    with _pytest.MonkeyPatch.context() as mp:
        mp.setattr(sd, "ENHANCED_SENSOR_CONTEST", False)
        # UI: perceivable (nebula ignored).
        assert _record_for(observer, hidden).perceivable is True
        # Weapons/AI: still blocked by the same nebula, on the same frame.
        assert can_detect(observer, hidden) is False


def test_toggle_off_leaves_the_hysteresis_latch_untouched_by_the_ui(monkeypatch):
    """Restoring the pre-stage-4 UI rule means the UI stops being a WRITER of
    the shared latch too — before stage 4 it never touched it. Pinning this
    keeps the off-state a true rollback rather than a partial one."""
    monkeypatch.setattr(sd, "ENHANCED_SENSOR_CONTEST", False)
    _pSet, observer, hidden, _clear = _scene()

    perceived_by(observer)
    assert sd._latched(observer, hidden) is False


def _pre_stage_4_rule(observer, ship):
    """VERBATIM copy of the expression perceived_by used before stage 4, kept
    ONLY as a test oracle.

    This is the one place duplicating that rule is right: it is not a code path
    the game can take, it cannot drift silently (the test below fails the moment
    the toggle's off-state stops matching it), and pinning "off == exactly how
    it was" by re-deriving the answer is far stronger than eyeballing that the
    branch looks equivalent. Do NOT lift this into engine/.
    """
    range_gu = sd.effective_sensor_range(observer)
    range_sq = range_gu * range_gu
    ox, oy, oz = _get_xyz(observer)
    sx, sy, sz = _get_xyz(ship)
    dx, dy, dz = sx - ox, sy - oy, sz - oz
    dist_sq = dx * dx + dy * dy + dz * dz
    return (range_gu > 0.0
            and not sd.is_hidden_by_cloak(ship)
            and dist_sq <= range_sq)


@pytest.mark.parametrize("condition", [100.0, 50.0, 20.0])
def test_toggle_off_agrees_with_the_pre_stage_4_rule_everywhere(monkeypatch,
                                                                condition):
    """The off state is a TRUE rollback, checked against an oracle rather than
    asserted by inspection.

    Sweeps a spread of geometries that each exercise a different clause —
    nebula core, nebula edge, cloaked inside and outside the bubble, in and out
    of sensor range — at full, half and offline (20% < the 25% disabled
    threshold) sensor condition. Every contact's `perceivable` must equal what
    the pre-stage-4 expression would have returned.
    """
    monkeypatch.setattr(sd, "ENHANCED_SENSOR_CONTEST", False)
    contact_index.reset()
    pSet, _neb = _tnc._set_with_dense_nebula()
    observer = _observer(pSet, 0.0, 0.0, 300.0, base_range=2000.0)
    observer.GetSensorSubsystem()._condition = condition

    cases = [
        ("in-nebula-core", 0.0, 0.0, 0.0, False),
        ("in-nebula-cloaked", 0.0, 0.0, 10.0, True),
        ("nebula-edge", 0.0, 0.0, 190.0, False),
        ("clear-in-range", 0.0, 0.0, 900.0, False),
        ("clear-out-of-range", 0.0, 0.0, 9000.0, False),
        ("clear-cloaked-close", 5.0, 0.0, 300.0, True),
        ("clear-cloaked-far", 800.0, 0.0, 300.0, True),
    ]
    for name, x, y, z, cloaked in cases:
        _contact(pSet, name, x, y, z, cloaked=cloaked)

    records = perceived_by(observer)
    assert len(records) == len(cases)          # not vacuous
    for rec in records:
        assert rec.perceivable is _pre_stage_4_rule(observer, rec.ship), (
            "off-state disagrees with the pre-stage-4 rule for %s"
            % rec.ship.GetName())

    # And the UI wrote nothing to the shared latch while doing it.
    assert sum(len(t) for t in sd._broken.values()) == 0


# ── Cloak reaches the UI too (the other half of dropping is_hidden_by_cloak) ──

def _cloak_scene(x):
    """Observer with 2000 GU sensors (flat 10 GU plus 1% = 30 GU cloak
    bubble) and one cloaked contact at (x, 0, 0). No nebula."""
    contact_index.reset()
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
    """45 GU clears the 30 GU bubble with a 15 GU margin."""
    observer, target = _cloak_scene(45.0)

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
