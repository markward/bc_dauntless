"""Cutscene letterbox easing.

The bars are drawn by the renderer (native/src/renderer/letterbox_pass.cc),
not by CEF, so nothing animates them for free any more — this does it.

TopWindow records the target coverage and the slide duration when a mission
calls StartCutscene / EndCutscene / AbortCutscene; the host loop feeds the
resulting snapshot in here once per frame along with the frame dt, and pushes
the returned fraction at renderer.letterbox_set().

The dt is the host loop's _player_dt, which is 0 while the sim is frozen, so
the bars hold still under the pause menu instead of sliding on wall-clock time.

Spec: docs/superpowers/specs/2026-07-13-letterbox-renderer-pass-design.md
"""
from __future__ import annotations


def _clamp01(v: float) -> float:
    if v != v:  # NaN != NaN; both range checks below are False for NaN, which
        return 0.0  # would let it fall straight through unclamped otherwise.
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


class LetterboxAnimator:
    """Eases the total covered fraction toward the snapshot's target.

    Smoothstep approximates the CSS `ease` curve the DOM bars used, so the
    motion is recognisably the same as before the move to GL.
    """

    def __init__(self) -> None:
        self._current = 0.0
        self._start = 0.0      # value at the last re-target, for the ease
        self._target = 0.0
        self._elapsed = 0.0
        self._duration = 0.0

    @property
    def current(self) -> float:
        return self._current

    def reset(self) -> None:
        """Return all state to construction values.

        Must be called on mission swap (the ``had_pending_swap`` block in
        ``engine/host_loop.py``, alongside ``cutscene.reset()`` and its
        siblings) so the OUTGOING mission's mid-cutscene bar state can never
        leak into the incoming mission's first frames. Today that leak is
        masked by ``_TopWindow.__init__`` happening to default
        ``_letterbox_transition_s`` to 0.0 (which makes the post-swap
        re-target snap instead of ease) -- but that is an accident of an
        unrelated default, not a guarantee, so this animator must not rely
        on it.
        """
        self._current = 0.0
        self._start = 0.0
        self._target = 0.0
        self._elapsed = 0.0
        self._duration = 0.0

    def update(self, dt: float, snapshot: dict) -> float:
        target = _clamp01(float(snapshot.get("covered", 0.0))) \
            if snapshot.get("visible") else 0.0

        if target != self._target:
            # Re-base the ease from wherever the bars are right now. A mission
            # that ends a cutscene while the bars are still sliding IN must
            # reverse from the current height, not jump to full coverage.
            self._target = target
            self._start = self._current
            self._elapsed = 0.0
            self._duration = max(0.0, float(snapshot.get("transition_s", 0.0)))

        if self._duration <= 0.0:
            # AbortCutscene's snap (transition_s = 0.0) lands here.
            self._current = self._target
            return self._current

        self._elapsed += max(0.0, dt)
        t = min(1.0, self._elapsed / self._duration)
        s = t * t * (3.0 - 2.0 * t)              # smoothstep ~= CSS `ease`
        self._current = self._start + (self._target - self._start) * s
        return self._current
