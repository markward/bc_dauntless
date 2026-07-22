"""Model-agnostic lip-sync controller.

Drives officer mouth visemes from BC ``.LIP`` timing using the **discrete**
viseme model: each ``.LIP`` phoneme code resolves through :class:`PhonemeMap`
to one of BC's authored jaw levels (``closed``/``partly``/``open``/``rounded``),
each with a fixed texture (``neutral``/``e``/``a``/``u``) and openness. Poses
are crossfaded from the previous viseme's texture/openness over the first
``xfade`` seconds of a segment. It emits poses to a *sink* callback
``sink(officer, tex_a, tex_b, mix, openness)`` — it never touches GL. That seam
keeps the whole system reusable if the BC heads are ever swapped for rigged
models (only the sink changes). Owned/ticked by ``BridgeCharacterAnimController``.

Pieces:
  * :class:`LipTimeline`     — one spoken line as a discrete-viseme timeline.
  * :class:`LipSyncController`— start/update/preempt across speaking officers.
  * :class:`BlinkScheduler`  — idle probabilistic eye blinks (independent of speech).
"""
from __future__ import annotations

from engine.appc.phoneme_map import default_phoneme_map, Viseme

_BLINK_STAGES = ("blink1", "blink2", "eyesclosed", "blink2", "blink1")


class LipTimeline:
    """A spoken line resolved to a discrete-viseme timeline with crossfade.

    Each .LIP segment maps through PhonemeMap to a Viseme (texture + openness).
    At time t the pose is the current viseme, crossfaded from the previous
    viseme's texture/openness over the first `xfade` seconds of the segment.
    """

    def __init__(self, segments, phoneme_map, t0, xfade=0.06):
        self._segs = list(segments)
        self._vis = [phoneme_map.viseme_for(s.code) for s in self._segs]
        self._t0 = float(t0)
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

    def pose_at(self, now):
        """(tex_a, tex_b, mix, openness) for the renderer sink at `now`."""
        elapsed = now - self._t0
        if not self._segs or elapsed < 0.0 or elapsed >= self._total:
            return ("neutral", "neutral", 0.0, 0.0)
        i = self._index(elapsed)
        cur = self._vis[i]
        into = elapsed - self._segs[i].start
        if self._xfade > 0.0 and into < self._xfade:
            prev = self._vis[i - 1] if i > 0 else Viseme("closed", 0.0, "neutral")
            f = into / self._xfade
            openness = prev.openness * (1.0 - f) + cur.openness * f
            return (prev.texture, cur.texture, f, openness)   # blend prev->cur
        return (cur.texture, cur.texture, 0.0, cur.openness)  # settled on cur


class LipSyncController:
    """Tracks the active spoken line per officer and emits a viseme pose each
    tick. Starting a line for an officer preempts that officer's prior line
    (mirroring crew-speech's single-channel preemption)."""

    def __init__(self, sink=None, phoneme_map=None, xfade=0.06):
        self._sink = sink or (lambda *a: None)
        self._pm = phoneme_map if phoneme_map is not None else default_phoneme_map()
        self._xfade = xfade
        self._active: dict = {}

    def start(self, officer, segments, t0):
        self._active[officer] = LipTimeline(segments, self._pm, t0, self._xfade)

    def update(self, now):
        for officer, tl in list(self._active.items()):
            if tl.done(now):
                self._sink(officer, "neutral", "neutral", 0.0, 0.0)
                del self._active[officer]
            else:
                self._sink(officer, *tl.pose_at(now))

    def stop(self, officer):
        """Cancel an officer's line and revert to neutral (e.g. on mission swap)."""
        if officer in self._active:
            del self._active[officer]
            self._sink(officer, "neutral", "neutral", 0.0, 0.0)

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
