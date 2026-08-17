"""Nebulae are indexed per set, not rediscovered per query.

concealment_at used to call pSet.GetClassObjectList(App.CT_NEBULA) — a full
scan of the set — once per ship, per call. Nebulae essentially never
spawn/despawn mid-mission, so the list is event-maintained state, the same
shape as the ship buckets in contact_index. This file pins that the hoisted
lookup path returns identical concealment values to the old scan.
"""
from engine.appc import contact_index
from engine.appc.sets import SetClass

import test_nebula_concealment as _tnc


def test_a_set_with_no_nebulae_reads_empty():
    contact_index.reset()
    assert contact_index.nebulae_in(SetClass()) == ()


def test_concealment_is_zero_and_cheap_without_nebulae():
    """The overwhelmingly common case: no nebulae in the set."""
    from engine.appc.sensor_detection import concealment_at
    from engine.appc.ships import ShipClass
    contact_index.reset()
    pSet = SetClass()
    ship = ShipClass()
    ship.SetName("Galor")
    pSet.AddObjectToSet(ship, "Galor")

    assert concealment_at(ship) == 0.0


def test_nebulae_in_reports_a_nebula_added_to_a_real_set():
    """A nebula added via AddObjectToSet (the same route
    _set_with_dense_nebula uses) shows up in nebulae_in."""
    contact_index.reset()
    s, n = _tnc._set_with_dense_nebula()
    assert contact_index.nebulae_in(s) == (n,)


def test_concealment_at_matches_pre_hoist_value_with_indexed_nebula():
    """concealment_at, now reading the index, returns the same values it did
    when it scanned pSet.GetClassObjectList(App.CT_NEBULA) directly."""
    from engine.appc import sensor_detection as sd
    contact_index.reset()
    s, n = _tnc._set_with_dense_nebula()

    far = _tnc._Ship("P", 5000.0, 0.0, 0.0, s)
    assert sd.concealment_at(far) == 0.0

    core = _tnc._Ship("P", 0.0, 0.0, 0.0, s)
    assert sd.concealment_at(core) > 0.5
