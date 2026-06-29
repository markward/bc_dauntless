"""Model-agnostic lip-sync controller.

Drives officer mouth visemes from BC ``.LIP`` timing, **modernized**: cross-fade
between visemes (no hard cuts), continuous blend over the ``{neutral,a,e,u}``
texture basis, and amplitude modulation. It emits poses to a *sink* callback
``sink(officer, slot_a, slot_b, mix)`` — it never touches GL. That seam keeps the
whole system reusable if the BC heads are ever swapped for rigged models (only
the sink changes). Owned/ticked by ``BridgeCharacterAnimController``.

Pieces:
  * :class:`LipTimeline`     — one spoken line as a viseme timeline.
  * :class:`LipSyncController`— start/update/preempt across speaking officers.
  * :class:`BlinkScheduler`  — idle probabilistic eye blinks (independent of speech).
"""
from __future__ import annotations

from engine.appc.lip_visemes import load_viseme_table, viseme_weights, dominant_pair

_NEUTRAL = {"neutral": 1.0}
_BLINK_STAGES = ("blink1", "blink2", "eyesclosed", "blink2", "blink1")


def _lerp(w0: dict, w1: dict, f: float) -> dict:
    keys = set(w0) | set(w1)
    return {k: w0.get(k, 0.0) * (1.0 - f) + w1.get(k, 0.0) * f for k in keys}


def _norm(w: dict) -> dict:
    pos = {k: v for k, v in w.items() if v > 0.0}
    total = sum(pos.values())
    if total <= 0.0:
        return dict(_NEUTRAL)
    return {k: v / total for k, v in pos.items()}


class LipTimeline:
    """A single spoken line: its ``.LIP`` segments resolved to per-segment basis
    weights, with cross-fade at boundaries and optional per-segment amplitude."""

    def __init__(self, segments, table, t0, amplitude=None, xfade=0.06):
        self._segs = list(segments)
        self._w = [viseme_weights(table, s.code) for s in self._segs]
        self._t0 = float(t0)
        self._amp = list(amplitude) if amplitude is not None else None
        self._xfade = float(xfade)
        self._total = self._segs[-1].end if self._segs else 0.0

    @property
    def total(self) -> float:
        return self._total

    def done(self, now) -> bool:
        return (now - self._t0) >= self._total

    def _index(self, elapsed) -> int:
        # Segments are contiguous; linear scan is fine for short lines.
        for i, s in enumerate(self._segs):
            if elapsed < s.end:
                return i
        return len(self._segs) - 1

    def weights_at(self, now) -> dict:
        elapsed = now - self._t0
        if not self._segs or elapsed < 0.0 or elapsed >= self._total:
            return dict(_NEUTRAL)
        i = self._index(elapsed)
        cur = self._w[i]
        # Cross-fade: blend the previous segment's pose into this one over the
        # first `xfade` seconds (from neutral for the first segment).
        into = elapsed - self._segs[i].start
        if into < self._xfade and self._xfade > 0.0:
            prev = self._w[i - 1] if i > 0 else _NEUTRAL
            cur = _lerp(prev, cur, into / self._xfade)
        # Amplitude: scale openness toward neutral for quiet syllables.
        if self._amp is not None:
            a = max(0.0, min(1.0, self._amp[i]))
            cur = _lerp(_NEUTRAL, cur, a)
        return _norm(cur)

    def pose_at(self, now):
        """``(slot_a, slot_b, mix)`` for the renderer sink at ``now``."""
        return dominant_pair(self.weights_at(now))


class LipSyncController:
    """Tracks the active spoken line per officer and emits a viseme pose each
    tick. Starting a line for an officer preempts that officer's prior line
    (mirroring crew-speech's single-channel preemption)."""

    def __init__(self, sink=None, table=None, xfade=0.06):
        self._sink = sink or (lambda *a: None)
        self._table = table if table is not None else load_viseme_table()
        self._xfade = xfade
        self._active: dict = {}

    def start(self, officer, segments, t0, amplitude=None):
        self._active[officer] = LipTimeline(
            segments, self._table, t0, amplitude, self._xfade
        )

    def update(self, now):
        for officer, tl in list(self._active.items()):
            if tl.done(now):
                self._sink(officer, "neutral", "neutral", 0.0)
                del self._active[officer]
            else:
                a, b, mix = tl.pose_at(now)
                self._sink(officer, a, b, mix)

    def stop(self, officer):
        """Cancel an officer's line and revert to neutral (e.g. on mission swap)."""
        if officer in self._active:
            del self._active[officer]
            self._sink(officer, "neutral", "neutral", 0.0)

    def clear(self):
        for officer in list(self._active):
            self.stop(officer)


class BlinkScheduler:
    """Idle, probabilistic eye blinks per officer (BC ``SetBlinkStages(3)``).

    Independent of speech. ``slot_at`` returns the current blink texture slot or
    ``None`` (eyes open). ``rng`` is injectable for deterministic tests.
    """

    def __init__(self, rng, interval=(2.0, 6.0), stage_dt=0.03,
                 stages=_BLINK_STAGES):
        self._rng = rng
        self._lo, self._hi = interval
        self._stage_dt = stage_dt
        self._stages = tuple(stages)
        self._next: dict = {}

    def arm(self, officer, now):
        self._next[officer] = now + self._lo + self._rng() * (self._hi - self._lo)

    def slot_at(self, officer, now):
        nxt = self._next.get(officer)
        if nxt is None:
            self.arm(officer, now)
            return None
        if now < nxt:
            return None
        phase = now - nxt
        seq_len = len(self._stages) * self._stage_dt
        if phase >= seq_len:
            self.arm(officer, now)  # blink finished -> schedule the next
            return None
        return self._stages[int(phase / self._stage_dt)]
