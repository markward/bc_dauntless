"""MusicManager — App.g_kMusicManager.

The SDK's DynamicMusic.py owns the music STATE MACHINE (EnqueueMusic,
ProcessQueue, SwitchMusic, OverrideMusic, StandardCombatMusic). This class
supplies only the primitives it drives.

Why this exists: DynamicMusic is live and was a silent no-op. It is driven by
the Maelstrom campaign (Maelstrom.py:111 Initialize, :265 Terminate, ChangeMusic
from Episodes 1-8) *and* by QuickBattle (QuickBattleGame.py:66 SetupMusic). Every
engine symbol it needed was absent, so `App.<name>` resolved to a `_NamedStub`.
Confirmed by live telemetry: docs/stub_heatmap.md ranks 163/164 recorded
App.g_kMusicManager and PlayFanfare at 21 hits, last seen 2026-08-06.

**Every signature below is taken from a real SDK call site, not inferred:**

| Call site | Signature |
|---|---|
| `DynamicMusic.py:60` | `LoadMusic(sFile, sMusicType, 2.0)` — **path first, then name**, plus beat info |
| `DynamicMusic.py:78` | `UnloadMusic(sMusic)` — unloads **one track by name**, looped over `dsMusicTypes.values()` |
| `DynamicMusic.py:119` | `StopMusic()` |
| `DynamicMusic.py:178` | `if StartMusic(sMusicName, bLooping):` — **returns success**; the else-branch drops the track from the queue |
| `DynamicMusic.py:222`, `E4M6.py:2958` | `PlayFanfare(sMusicName)` |
| `E8M2.py:6558-6568` | `IsEnabled()` / `SetEnabled(bEnabled)` |

Per the clean-room reference (spec/TGAudio.md §6, *reviewed-not-tested*,
confidence *partial*): TGMusic::StartMusic (0x00713D60) registers a fade timer
via TGTimerManager, so transitions are volume-ramped rather than abrupt, and
LoadMusic (0x00713AD0) reads a `Sound/StreamMusic` config toggle. BC's second
path, TGRedbook (CD audio via mciSendCommandA), does not apply to us.

Playback is injected via set_backend so this class stays testable with no audio
device present.
"""


class MusicManager:
    def __init__(self) -> None:
        self._paths: dict[str, str] = {}   # music NAME -> file path
        self._fades: dict[str, float] = {}  # music NAME -> fade grid (seconds)
        self._current: "str | None" = None
        self._enabled: bool = True
        self._backend = None               # injected by the host, see set_backend

    def set_backend(self, backend) -> None:
        """Host-injected player. None means 'no audio' — the manager still
        tracks state so mission logic and tests behave identically."""
        self._backend = backend

    # ── SDK surface ──────────────────────────────────────────────────────────

    def LoadMusic(self, path, name, beat=0.0) -> None:
        """Register `name` -> `path`. Argument order is BC's: the FILE comes
        first (`DynamicMusic.py:60` passes `(sFile, sMusicType, 2.0)`).

        `beat` is the track's **fade grid**, and it is LOAD-BEARING — a track
        change is quantised to the OUTGOING track's value (2.0 s in shipping
        data). An earlier version of this method accepted and discarded it as a
        mere "beat/tempo hint"; that was wrong, and it is stored now.
        """
        key = str(name)
        self._paths[key] = str(path)
        self._fades[key] = float(beat)

    def UnloadMusic(self, name) -> None:
        """Unload ONE track by name. `DynamicMusic.UnloadMusic` loops over
        `dsMusicTypes.values()` calling this per track — it is not a clear-all.
        Stops playback first if this is the current track."""
        key = str(name)
        if self._current == key:
            self.StopMusic()
        self._paths.pop(key, None)
        self._fades.pop(key, None)

    def StartMusic(self, name, looping=1) -> int:
        """Begin `name`. Returns 1 on success, 0 on failure.

        The return value is load-bearing: `DynamicMusic.py:178` reads
        `if StartMusic(...)` and, on a falsy result, drops that track from the
        queue and tries the next one. Returning None here would silently make
        every track look unplayable and drain the queue.
        """
        key = str(name)
        path = self._paths.get(key)
        if path is None or not self._enabled:
            return 0
        # The fade is the OUTGOING track's grid, not the incoming one's — a
        # change is quantised to what is already playing. With nothing playing
        # the player builds a duration-0 record and the track starts at full
        # volume (the falsifier that proves BC crossfades rather than
        # fading out then in).
        fade = self._fades.get(self._current, 0.0) if self._current else 0.0
        self._current = key
        if self._backend is not None:
            self._backend.play(path, looping=bool(looping), fade=fade)
        return 1

    def StopMusic(self) -> None:
        self._current = None
        if self._backend is not None:
            self._backend.stop()

    def PlayFanfare(self, name) -> None:
        """One-shot sting over the current track. Does NOT become `current`:
        DynamicMusic resumes the queue after it, so the underlying track is
        still what is playing."""
        if not self._enabled:
            return
        path = self._paths.get(str(name))
        if path is not None and self._backend is not None:
            self._backend.play_oneshot(path)

    def IsEnabled(self) -> int:
        """1 if music may play. Real int, not bool: E8M2.py:6558 stores this and
        hands it straight back to SetEnabled."""
        return 1 if self._enabled else 0

    def SetEnabled(self, value) -> None:
        """Mute/unmute. E8M2.py:6559 disables music for a scripted sequence and
        restores the previous value at :6568. Disabling stops any current
        track — a muted manager that keeps playing would defeat the purpose."""
        self._enabled = bool(value)
        if not self._enabled:
            self.StopMusic()

    # ── host-facing ──────────────────────────────────────────────────────────

    def notify_track_finished(self) -> None:
        """Called by the host when the current track reaches its end.

        Broadcasts ET_MUSIC_DONE **carrying the finished track's name**, which
        DynamicMusic.MusicDone (DynamicMusic.py:121) handles to advance its
        queue via ProcessQueue (:132).

        The name payload is load-bearing: MusicDone gates on
        `pEvent.GetCString() == dsMusicTypes[sCurrentMusicType]`. Send the event
        without it and the comparison never matches, ProcessQueue never runs,
        and the playlist stalls on its first track — with music still audible,
        so the failure is silent.
        """
        if self._current is None:
            return
        finished = self._current
        self._current = None
        import App
        evt = App.TGEvent_Create()
        evt.SetEventType(App.ET_MUSIC_DONE)
        evt.SetCString(finished)
        App.g_kEventManager.BroadcastEvent(evt)

    def current(self) -> "str | None":
        return self._current
