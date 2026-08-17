"""Lifetime of the per-(observer, target) lock-break latch.

`can_detect` writes a module-global latch so a broken lock needs a margin
(HYSTERESIS) to re-acquire. Two things about that global are properties of the
ENGINE, not of any one caller, and both are pinned here:

  * it must be cleared centrally between tests (tests/conftest.py's autouse
    `_reset_leakable_engine_globals`), not by whichever test remembers to; and
  * it must not outlive the ships it is about. Keyed on `id()`, a dead ship's
    entry could be inherited by an unrelated later object that CPython happens
    to allocate at the same address — silently granting it the easier
    `LOCK_BREAK_T - HYSTERESIS` re-acquisition threshold.

The geometry below is chosen so the latch is BEHAVIOURALLY OBSERVABLE: at
x=180 in test_nebula_concealment's dense sphere the concealment sits inside the
hysteresis band (>= LOCK_BREAK_T - HYSTERESIS, < LOCK_BREAK_T), so the same
position answers True for a fresh pair and False for a latched one. Without a
band position every assertion here would pass for the wrong reason.
"""
import sys

import pytest

from engine.appc import sensor_detection as sd

import test_nebula_concealment as _tnc

# Inside the dense sphere, but far enough out that concealment lands between
# LOCK_BREAK_T - HYSTERESIS and LOCK_BREAK_T. Verified by
# test_the_band_position_really_is_in_the_hysteresis_band below.
_BAND_X = 180.0


def _latched_pairs() -> int:
    """How many (observer, target) pairs are currently latched.

    Counts PAIRS, not dictionary keys: an observer whose targets have all died
    keeps an entry holding an empty WeakSet until the observer itself dies, and
    that entry latches nothing.
    """
    return sum(len(targets) for targets in sd._broken.values())


def _scene():
    """Observer in clear space, one target at the nebula core. Neither models a
    sensor subsystem, so FALLBACK_RANGE_GU applies and range is never the
    reason a detection fails here."""
    sd.reset_concealment_state()
    pSet, _neb = _tnc._set_with_dense_nebula()
    observer = _tnc._Ship("E", 0.0, 0.0, 3000.0, pSet)
    target = _tnc._Ship("P", 0.0, 0.0, 0.0, pSet)
    return pSet, observer, target


def test_the_band_position_really_is_in_the_hysteresis_band():
    """Anti-vacuity guard for the whole file."""
    pSet, _observer, target = _scene()
    band = _tnc._Ship("B", _BAND_X, 0.0, 0.0, pSet)

    conceal = sd.concealment_at(band)

    assert sd.LOCK_BREAK_T - sd.HYSTERESIS <= conceal < sd.LOCK_BREAK_T


def test_a_fresh_pair_in_the_band_is_detected():
    pSet, observer, _target = _scene()
    band = _tnc._Ship("B", _BAND_X, 0.0, 0.0, pSet)

    assert sd.can_detect(observer, band) is True


def test_a_latched_pair_in_the_band_is_not_detected():
    """The latch is what makes the band position answer differently, so every
    id-recycling assertion below has something real to observe."""
    _pSet, observer, target = _scene()

    assert sd.can_detect(observer, target) is False   # core -> lock breaks
    target._x = _BAND_X                                # drift out to the band
    assert sd.can_detect(observer, target) is False    # still latched


# ── Central reset ────────────────────────────────────────────────────────────

def test_the_autouse_conftest_reset_clears_the_latch():
    """The latch must be cleared by tests/conftest.py's autouse
    `_reset_leakable_engine_globals`, alongside contact_index.reset().

    Before this, `reset_concealment_state()` was called only from
    host_loop.py's mission swap, so every test that broke a lock leaked it —
    and tests/unit/test_nebula_hides_contacts_from_ui.py worked around that
    locally with five hand-written calls instead. One mechanism, centrally.
    """
    _pSet, observer, target = _scene()
    assert sd.can_detect(observer, target) is False
    assert _latched_pairs() == 1                       # not vacuous

    sys.modules["tests.conftest"]._reset_leakable_engine_globals()

    assert _latched_pairs() == 0


# ── GC safety: no id() inheritance ───────────────────────────────────────────

def test_a_dead_target_drops_out_of_the_latch():
    """The latch holds no strong reference and does not outlive its target."""
    _pSet, observer, target = _scene()
    assert sd.can_detect(observer, target) is False
    assert _latched_pairs() == 1                       # not vacuous

    del target

    assert _latched_pairs() == 0


def test_a_dead_observer_drops_out_of_the_latch():
    _pSet, observer, target = _scene()
    assert sd.can_detect(observer, target) is False
    assert _latched_pairs() == 1                       # not vacuous

    del observer

    assert _latched_pairs() == 0
    assert len(sd._broken) == 0                        # the key goes too


def test_a_recycled_id_cannot_inherit_a_stale_latch():
    """A NEW object allocated at a dead ship's address must start unlatched.

    CPython reuses the freed slot for the very next same-sized allocation, so
    this is constructible without waiting on chance: drop the last reference to
    the latched target and immediately build its replacement. If the address is
    not reused on this interpreter the test skips rather than passing vacuously.

    The replacement sits at the BAND position, where a fresh pair is detected
    and a latched one is not — so an inherited latch shows up as a False.
    """
    pSet, observer, target = _scene()
    assert sd.can_detect(observer, target) is False    # latch the pair
    dead_id = id(target)

    del target
    replacement = _tnc._Ship("Recycled", _BAND_X, 0.0, 0.0, pSet)
    if id(replacement) != dead_id:
        pytest.skip("CPython did not reuse the freed address on this run")

    assert sd.can_detect(observer, replacement) is True
