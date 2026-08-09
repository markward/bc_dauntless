"""Music playback with a volume ramp.

Per the clean-room reference (spec/TGAudio.md §6, *reviewed-not-tested*,
confidence *partial*): TGMusic::StartMusic (0x00713D60) registers a fade timer
via TGTimerManager, so track changes ramp rather than cut.

⚠️ The reference does NOT establish whether BC crossfades (both tracks audible
simultaneously) or fades out then in. This implements **fade-out-then-in**, the
conservative reading — it needs only one sound at a time. If a live listen shows
BC crossfades, this class needs two concurrent sounds, not a tweak. Do not
describe the current behaviour as faithful until that is checked.

`sound_factory` is injected so this is testable with no audio device.
"""

FADE_SECONDS = 2.0


class MusicPlayer:
    def __init__(self, sound_factory) -> None:
        self._factory = sound_factory
        self._sound = None
        self._volume = 0.0
        self._target = 0.0
        self._looping = False
        self._pending = None       # (path, looping) awaiting fade-out
        self._stop_after_fade = False

    def play(self, path, looping=True) -> None:
        if self._sound is None:
            self._begin(path, looping)
            return
        # A track is playing: fade it out first, then swap.
        self._pending = (path, looping)
        self._target = 0.0

    def play_oneshot(self, path) -> None:
        """Fanfare sting layered over the current track — no ramp, no swap.
        DynamicMusic resumes its queue afterwards, so the underlying track must
        keep playing underneath."""
        self._factory(path)

    def stop(self) -> None:
        self._target = 0.0
        self._stop_after_fade = True

    def update(self, dt) -> None:
        if FADE_SECONDS <= 0.0:
            self._volume = self._target
        else:
            step = float(dt) / FADE_SECONDS
            if self._volume < self._target:
                self._volume = min(self._target, self._volume + step)
            elif self._volume > self._target:
                self._volume = max(self._target, self._volume - step)
        if self._sound is not None:
            self._sound.SetVolume(self._volume)

        if self._volume <= 0.0:
            if self._pending is not None:
                path, looping = self._pending
                self._pending = None
                self._teardown()
                self._begin(path, looping)
            elif self._stop_after_fade:
                self._stop_after_fade = False
                self._teardown()

    def finished(self) -> bool:
        """True when a NON-looping track has run out, so the host can fire
        ET_MUSIC_DONE and let DynamicMusic advance its queue.

        A looping track never finishes: reporting otherwise would advance the
        queue on every frame and churn through the playlist.
        """
        if self._sound is None or self._looping:
            return False
        return getattr(self._sound, "playing", True) is False

    def volume(self) -> float:
        return self._volume

    def _begin(self, path, looping) -> None:
        self._sound = self._factory(path)
        self._looping = bool(looping)
        self._volume = 0.0
        self._target = 1.0
        self._sound.SetVolume(0.0)

    def _teardown(self) -> None:
        if self._sound is not None and hasattr(self._sound, "Stop"):
            self._sound.Stop()
        self._sound = None
        self._looping = False
