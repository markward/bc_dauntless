"""LetterboxAnimator — eases the cutscene bars in/out on the sim clock.

Replaces the CSS `transition: height Ns ease` that animated the bars while
they were CEF DOM. Driven from TopWindow.letterbox_snapshot() by the host
loop; see docs/superpowers/specs/2026-07-13-letterbox-renderer-pass-design.md
"""
from engine.ui.letterbox import LetterboxAnimator


def _snap(visible, covered=0.125, transition_s=1.0):
    return {"type": "letterbox", "visible": visible,
            "covered": covered, "transition_s": transition_s}


def test_starts_closed():
    assert LetterboxAnimator().current == 0.0


def test_slide_in_is_monotonic_and_reaches_the_target():
    a = LetterboxAnimator()
    prev = 0.0
    for _ in range(10):                      # 10 x 0.1 s = the full 1.0 s
        cur = a.update(0.1, _snap(True))
        assert cur >= prev                   # never retreats
        prev = cur
    assert a.update(0.0, _snap(True)) == 0.125


def test_does_not_overshoot_past_the_target():
    a = LetterboxAnimator()
    assert a.update(99.0, _snap(True)) == 0.125


def test_slide_out_eases_back_to_zero():
    a = LetterboxAnimator()
    a.update(99.0, _snap(True))               # fully in
    a.update(0.5, _snap(False, transition_s=1.0))
    assert 0.0 < a.current < 0.125            # mid-slide, not snapped
    a.update(1.0, _snap(False, transition_s=1.0))
    assert a.current == 0.0


def test_zero_duration_snaps():
    """AbortCutscene sets transition_s = 0.0 — the bars must vanish in one
    frame, not ease."""
    a = LetterboxAnimator()
    a.update(99.0, _snap(True))
    assert a.update(0.016, _snap(False, transition_s=0.0)) == 0.0


def test_frozen_dt_holds_the_bars_still():
    """dt == 0 is how the host loop reports pause / DevTools freeze. The bars
    must hold, not keep sliding on wall-clock time (which is what the old CSS
    transition did)."""
    a = LetterboxAnimator()
    a.update(0.3, _snap(True))
    held = a.current
    assert 0.0 < held < 0.125                 # genuinely mid-slide
    for _ in range(5):
        assert a.update(0.0, _snap(True)) == held


def test_retarget_mid_slide_eases_from_the_current_value():
    """EndCutscene while the bars are still sliding IN must reverse from where
    they are, not jump to full coverage first."""
    a = LetterboxAnimator()
    a.update(0.3, _snap(True))
    mid = a.current
    after = a.update(0.0, _snap(False, transition_s=1.0))
    assert after == mid                       # no jump on the retarget frame
    assert a.update(0.1, _snap(False, transition_s=1.0)) < mid


def test_clamps_a_hostile_covered_value():
    """fCoveredArea comes from mission script; a bogus value must not produce a
    negative or >1 fraction for the scissor rect downstream."""
    a = LetterboxAnimator()
    assert a.update(99.0, _snap(True, covered=5.0)) == 1.0
    a2 = LetterboxAnimator()
    assert a2.update(99.0, _snap(True, covered=-1.0)) == 0.0


def test_nan_covered_value_does_not_permanently_poison_the_animator():
    """A NaN fCoveredArea (e.g. StartCutscene(1.0, float('nan'))) must clamp
    to 0.0 rather than propagate -- both `v < 0.0` and `v > 1.0` are False for
    NaN, so the naive clamp lets it straight through. Once `_current` is NaN,
    `self._start = self._current` on the next re-target makes every later
    ease NaN forever, which is the actual bug: a SUBSEQUENT valid snapshot
    must still ease normally."""
    a = LetterboxAnimator()
    result = a.update(99.0, _snap(True, covered=float("nan")))
    assert result == 0.0
    assert a.current == 0.0

    # Recovery: a later, valid re-target must ease normally, not stay NaN.
    recovered = a.update(99.0, _snap(True, covered=0.125))
    assert recovered == 0.125
    assert a.current == 0.125


def test_reset_returns_all_state_to_construction_values():
    """A mission swap must not let the OUTGOING mission's cutscene state leak
    into the incoming mission's first frames. reset() must fully undo any
    mid-slide state, including a re-target in progress, back to exactly what
    a freshly-constructed LetterboxAnimator would report."""
    a = LetterboxAnimator()
    a.update(0.3, _snap(True))                    # mid-slide, non-zero
    a.update(0.0, _snap(False, transition_s=1.0))  # re-target in progress
    assert a.current != 0.0

    a.reset()

    assert a.current == 0.0
    fresh = LetterboxAnimator()
    # Both animators must behave identically going forward: same easing
    # trajectory for the same subsequent snapshot sequence.
    assert a.update(0.3, _snap(True)) == fresh.update(0.3, _snap(True))
