"""Music playback — BC CROSSFADES. Two streams are audible at once.

⚠️ Corrected 2026-08-10. The first version of this module implemented
fade-out-then-in as "the conservative reading" of a fade timer. That was WRONG,
and the correction came from the clean-room reference.

**The model.** On a track change, TWO volume-ramp records are scheduled at the
same instant with the same duration: the outgoing stream ramps
current -> 0, the incoming ramps 0 -> 1. Both play for the whole fade. The
manager forgets the outgoing track's name/handle immediately; the outgoing
STREAM lives on inside its ramp record, which is why the record identifies its
stream by handle rather than by name.

**The falsifier — why a sequential design cannot be right.** When there is no
current track, the incoming record is built with startVolume 1 and duration 0.
The fade-in exists ONLY when there is something to fade out of. A sequential
design fades in from 0 every time and cannot produce that asymmetry.

Ramp record (`spec/TGMusic.md 2.1`, 20 bytes, *reviewed-not-tested*):

| Offset | Field | Meaning |
|---|---|---|
| `+0x00` | handle | the stream this ramp drives — survives the manager forgetting the name |
| `+0x04` | duration | total ramp length, seconds |
| `+0x08` | remaining | counts down by the frame delta |
| `+0x0c` | startVolume | |
| `+0x10` | endVolume | |

and "there may be more than one of them live at once".

**Other rules from the same source:**
- Track changes are quantised to the OUTGOING track's own fade grid — the third
  `LoadMusic` argument, 2.0 s in shipping data. The caller passes it as `fade`.
- `stop()` is a HARD stop. It does not wait for, or schedule, a ramp.
- A start requested during a transition is QUEUED by name.

⚠️ **Unconfirmed:** "quantised to the fade grid" may mean only that the duration
comes from the outgoing track's registered value (implemented here), or it may
additionally mean the change is deferred to a grid boundary. The latter would be
a scheduler we have not built. Not inferred either way — confirm before relying
on sample-accurate alignment.

`sound_factory` is injected so this is testable with no audio device.
"""


class _Ramp:
    """One volume-ramp record. Mirrors the 20-byte on-disk shape."""

    __slots__ = ("sound", "duration", "remaining", "start_volume", "end_volume")

    def __init__(self, sound, duration, start_volume, end_volume):
        self.sound = sound                    # +0x00 handle
        self.duration = float(duration)       # +0x04
        self.remaining = float(duration)      # +0x08
        self.start_volume = float(start_volume)  # +0x0c
        self.end_volume = float(end_volume)      # +0x10

    def volume(self) -> float:
        if self.duration <= 0.0:
            return self.end_volume
        # remaining counts DOWN, so elapsed fraction is 1 - remaining/duration.
        t = 1.0 - (self.remaining / self.duration)
        t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
        return self.start_volume + (self.end_volume - self.start_volume) * t

    def done(self) -> bool:
        return self.remaining <= 0.0


class MusicPlayer:
    def __init__(self, sound_factory) -> None:
        self._factory = sound_factory
        self._ramps: list = []          # the +0x28 list; >1 live during a fade
        self._current = None            # incoming/settled stream
        self._looping = False
        self._pending = None            # (path, looping, fade) queued mid-transition

    # ── playback ────────────────────────────────────────────────────────────

    def play(self, path, looping=True, fade=0.0) -> None:
        """Start `path`, crossfading out of whatever is playing.

        `fade` is the OUTGOING track's fade grid, not the incoming one's.
        """
        if self._transitioning():
            # A start during a transition is queued by name, not layered on
            # top — otherwise a burst of ChangeMusic calls would stack ramps.
            self._pending = (path, looping, fade)
            return
        self._begin(path, looping, fade)

    def play_oneshot(self, path) -> None:
        """Fanfare sting layered over the current track — no ramp, no swap.
        The underlying track keeps playing underneath and is resumed by the
        SDK afterwards. Never loops: a looping sting would never stop."""
        self._factory(path, False)

    def stop(self) -> None:
        """HARD stop. Does not wait for, or schedule, a ramp."""
        for ramp in self._ramps:
            self._silence(ramp.sound)
        self._ramps = []
        if self._current is not None:
            self._silence(self._current)
        self._current = None
        self._looping = False
        self._pending = None

    def update(self, dt) -> None:
        for ramp in self._ramps:
            ramp.remaining -= float(dt)
            if ramp.sound is not None:
                ramp.sound.SetVolume(ramp.volume())

        finished = [r for r in self._ramps if r.done()]
        self._ramps = [r for r in self._ramps if not r.done()]

        for ramp in finished:
            if ramp.sound is not None:
                ramp.sound.SetVolume(ramp.end_volume)
            # A ramp that lands on silence was the outgoing half: retire it.
            # The incoming half lands on 1.0 and its stream is `_current`.
            if ramp.end_volume <= 0.0 and ramp.sound is not self._current:
                self._silence(ramp.sound)

        if self._pending is not None and not self._transitioning():
            path, looping, fade = self._pending
            self._pending = None
            self._begin(path, looping, fade)

    # ── queries ─────────────────────────────────────────────────────────────

    def volume(self) -> float:
        """Volume of the incoming/settled stream."""
        if self._current is None:
            return 0.0
        for ramp in self._ramps:
            if ramp.sound is self._current:
                return ramp.volume()
        return 1.0

    def finished(self) -> bool:
        """True when a NON-looping track has run out, so the host can fire
        ET_MUSIC_DONE and let DynamicMusic advance its queue. A looping track
        never finishes — otherwise the queue would advance every frame."""
        if self._current is None or self._looping:
            return False
        return getattr(self._current, "playing", True) is False

    # ── internals ───────────────────────────────────────────────────────────

    def _transitioning(self) -> bool:
        return len(self._ramps) > 1

    def _begin(self, path, looping, fade) -> None:
        outgoing = self._current
        duration = float(fade) if outgoing is not None else 0.0
        outgoing_volume = self._volume_of(outgoing) if outgoing is not None else 0.0

        # Drop the settled track's spent ramp before scheduling the new pair.
        # A completed zero-duration record otherwise lingers in the list and
        # re-applies its end volume in update()'s sweep, stamping the outgoing
        # stream back to full and destroying the fade. `_begin` only runs when
        # NOT transitioning (play() queues otherwise), so at most one ramp is
        # live here and clearing is safe.
        self._ramps = []

        # looping must reach the sound: an ambient bed that plays once and
        # stops is not the same thing as one that loops.
        incoming = self._factory(path, bool(looping))
        self._current = incoming
        self._looping = bool(looping)

        if incoming is None:
            # Factory could not load the file (missing asset / no backend).
            # Leave whatever was playing alone rather than tearing it down for
            # a track that never started.
            self._current = outgoing
            return

        if outgoing is not None:
            # Same instant, same duration, mirrored — this is the crossfade.
            self._ramps.append(_Ramp(outgoing, duration, outgoing_volume, 0.0))
            self._ramps.append(_Ramp(incoming, duration, 0.0, 1.0))
            incoming.SetVolume(0.0)
        else:
            # THE FALSIFIER: nothing to fade out of, so no fade in. The record
            # is startVolume 1, duration 0 — full volume immediately.
            self._ramps.append(_Ramp(incoming, 0.0, 1.0, 1.0))
            incoming.SetVolume(1.0)

    def _volume_of(self, sound) -> float:
        for ramp in self._ramps:
            if ramp.sound is sound:
                return ramp.volume()
        return 1.0

    @staticmethod
    def _silence(sound) -> None:
        if sound is not None and hasattr(sound, "Stop"):
            sound.Stop()
