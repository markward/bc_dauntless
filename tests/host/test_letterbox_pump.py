"""_pump_letterbox — the one wire from TopWindow's cutscene state to the GL
letterbox pass. Runs every frame, unconditionally: the bars are not view-gated
(BC letterboxes bridge cutscenes as well as exterior ones)."""
import inspect

import pytest

from engine import host_loop
from engine.appc import top_window
from engine.host_loop import _pump_letterbox
from engine.ui.letterbox import LetterboxAnimator


@pytest.fixture(autouse=True)
def _reset_tw():
    top_window.reset_for_tests()


class _FakeRenderer:
    def __init__(self):
        self.pushed = []

    def letterbox_set(self, covered):
        self.pushed.append(covered)


def test_pushes_zero_when_no_cutscene():
    r, a = _FakeRenderer(), LetterboxAnimator()
    assert _pump_letterbox(r, a, 0.016) == 0.0
    assert r.pushed == [0.0]


def test_cutscene_bars_ease_in_and_reach_the_sdk_covered_fraction():
    r, a = _FakeRenderer(), LetterboxAnimator()
    top_window.TopWindow_GetTopWindow().StartCutscene(1.0, 0.125, 1)
    _pump_letterbox(r, a, 0.5)
    assert 0.0 < r.pushed[-1] < 0.125          # mid-slide
    _pump_letterbox(r, a, 1.0)
    assert r.pushed[-1] == 0.125               # fully in


def test_abort_snaps_the_bars_away():
    r, a = _FakeRenderer(), LetterboxAnimator()
    tw = top_window.TopWindow_GetTopWindow()
    tw.StartCutscene(1.0, 0.125, 1)
    _pump_letterbox(r, a, 99.0)
    tw.AbortCutscene()
    assert _pump_letterbox(r, a, 0.016) == 0.0


def test_mission_swap_mid_cutscene_resets_the_bars():
    """A mission swap must not let the OUTGOING mission's cutscene bars slide
    into the incoming mission's first frames. This survives today only by
    accident: _TopWindow.__init__ happens to default
    _letterbox_transition_s to 0.0, so the post-swap re-target snaps instead
    of easing -- but the animator itself was never in the had_pending_swap
    reset block. Simulate the swap explicitly here (TopWindow reset +
    LetterboxAnimator.reset(), the two calls that block performs) rather
    than relying on that accident, so this test still catches a regression
    even if that default ever changes."""
    r, a = _FakeRenderer(), LetterboxAnimator()
    tw = top_window.TopWindow_GetTopWindow()
    tw.StartCutscene(1.0, 0.125, 1)
    _pump_letterbox(r, a, 0.5)
    assert 0.0 < r.pushed[-1] < 0.125           # genuinely mid-slide

    # The had_pending_swap block in host_loop.run(): clear the outgoing
    # mission's TopWindow cutscene state and reset the shared animator.
    top_window.reset_for_tests()
    a.reset()

    assert a.current == 0.0
    assert _pump_letterbox(r, a, 0.016) == 0.0
    assert r.pushed[-1] == 0.0


# ---------------------------------------------------------------------------
# Source-level guards on the host_loop.run() wiring.
#
# The tests above exercise _pump_letterbox in complete isolation and prove
# the helper itself is correct. None of them can prove the *wiring* in
# run() is correct: the host loop is a single monolithic while-loop (one
# function, thousands of lines, built from real Appc/CEF/GL state) that is
# impractical to unit-test end-to-end. A reviewer proved by mutation that
# each of the following breaks the feature while leaving the entire test
# suite -- including every test above -- green:
#
#   1. wrapping the call site in `if not pause.sim_frozen:` (bars stop
#      being pushed while the sim is frozen)
#   2. constructing `LetterboxAnimator()` inline at the call site every
#      frame (the ease resets every tick, so the bars never finish opening)
#   3. passing a hardcoded `0.0` instead of `_player_dt` (the bars never
#      move, ever)
#   4. deleting the call site outright
#
# These tests pin the exact text and structure of run()'s source so that
# any of those four regressions fails a test. Be honest about the limits
# of a text-level guard: it proves the *shape* of the wiring hasn't
# regressed, not that it behaves correctly at runtime (that's what the
# helper-level tests above are for). It also can't catch every rewording
# of the same bug -- e.g. a rename of `_player_dt` to some other wall-clock
# variable would need the assertion strings updated too. What it reliably
# catches is silent re-gating, re-construction, dt-substitution, or
# deletion introduced by a future refactor that doesn't touch this file.
# ---------------------------------------------------------------------------


def _run_source() -> str:
    return inspect.getsource(host_loop.run)


def test_pump_letterbox_call_passes_wall_clock_dt_not_a_literal():
    """Guards mutations 2, 3 and 4 above.

    The call site must read exactly `_pump_letterbox(r, _letterbox_anim,
    _player_dt)`. If a future edit hardcodes a literal dt (mutation 3),
    swaps in a freshly-constructed animator (mutation 2), or deletes the
    call outright (mutation 4), this exact string disappears from run()'s
    source and the assertion fails. A text match can't prove `_player_dt`
    carries the correct *value* at runtime -- only that the call site still
    references the wall-clock dt variable and the shared animator instance
    instead of a substitute.
    """
    src = _run_source()
    assert "_pump_letterbox(r, _letterbox_anim, _player_dt)" in src, (
        "the letterbox pump call must read exactly "
        "'_pump_letterbox(r, _letterbox_anim, _player_dt)' -- a hardcoded "
        "dt literal freezes the bars forever, and a fresh animator or a "
        "deleted call site both silently drop the feature")


def test_pump_letterbox_call_is_unconditional_same_indent_as_frame():
    """Guards mutation 1 above.

    `_pump_letterbox` must run every frame the renderer does, with no extra
    gating -- BC letterboxes bridge cutscenes as well as exterior ones, so
    there is no view-mode or pause-state condition under which the bars
    should stop updating. The most natural way to smuggle in an unwanted
    gate is to nest the call inside a further `if` block, which increases
    its indentation relative to `r.frame()` in the same loop body. This
    test compares indentation rather than searching for specific `if`
    text, so it also catches gates the reviewer didn't enumerate (e.g.
    `if view_mode == ...:`) -- but it cannot detect a gate that reuses the
    same indentation level (there is no such Python construct without an
    `if` block increasing indent, so this is not a practical gap).
    """
    src = _run_source()
    frame_indent = None
    pump_indent = None
    for line in src.splitlines():
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        if stripped.startswith("_pump_letterbox(r, _letterbox_anim, _player_dt)"):
            pump_indent = indent
        if stripped.startswith("r.frame()"):
            frame_indent = indent
    assert pump_indent is not None, "_pump_letterbox call site not found in run()"
    assert frame_indent is not None, "r.frame() not found in run()"
    assert pump_indent == frame_indent, (
        "the letterbox pump call must sit at the same indentation level as "
        "r.frame() in the main loop body -- wrapping it in an extra `if` "
        "(e.g. `if not pause.sim_frozen:`) would silently stop the bars "
        "from being pushed under that condition, without breaking any "
        "isolated test of the _pump_letterbox helper itself")


def test_letterbox_animator_constructed_once_outside_the_main_loop():
    """Guards mutation 2 above (belt-and-suspenders alongside the exact
    call-site string match).

    `LetterboxAnimator()` owns an internal ease that must persist across
    frames to animate the bars sliding in/out. It must be constructed
    exactly once in run(), before the main `while not r.should_close():`
    loop starts, and bound to `_letterbox_anim`. Constructing it inline at
    the call site each frame produces a brand-new, never-progressed
    animator every tick, so the ease target is recomputed from zero every
    time and the bars never appear to move. This test locates the
    construction and the loop header by line and asserts the construction
    precedes the loop, then independently asserts there is exactly one
    `LetterboxAnimator()` construction anywhere in run() -- a second one
    (in addition to or instead of the real one) is exactly the "rebuilt
    every frame" mutation.
    """
    src = _run_source()
    lines = src.splitlines()
    construct_line_no = None
    while_line_no = None
    call_line_no = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "_letterbox_anim = LetterboxAnimator()":
            construct_line_no = i
        if while_line_no is None and stripped.startswith("while ") and "should_close" in stripped:
            while_line_no = i
        if call_line_no is None and "_pump_letterbox(r, _letterbox_anim, _player_dt)" in stripped:
            call_line_no = i
    assert construct_line_no is not None, (
        "'_letterbox_anim = LetterboxAnimator()' not found in run()")
    assert while_line_no is not None, "main while-loop header not found in run()"
    assert call_line_no is not None, "_pump_letterbox call site not found in run()"
    assert construct_line_no < while_line_no < call_line_no, (
        "LetterboxAnimator() must be constructed exactly once, before the "
        "main while-loop starts -- constructing it inline at the call site "
        "resets its ease every frame, so the bars never finish opening")
    assert src.count("LetterboxAnimator()") == 1, (
        "LetterboxAnimator() must be constructed exactly once in run() -- "
        "a second construction (e.g. inline at the call site every frame) "
        "means a fresh, never-progressed animator gets used instead of the "
        "shared one")
