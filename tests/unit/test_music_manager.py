"""g_kMusicManager — the surface DynamicMusic.py drives.

DynamicMusic is live: the Maelstrom campaign (Maelstrom.py:111 Initialize, :265
Terminate, ChangeMusic from Episodes 1-8) AND QuickBattle
(QuickBattleGame.py:66 SetupMusic). Every symbol below was absent, so
App.<name> resolved to a _NamedStub and the whole music system was a silent
no-op (stub heatmap ranks 163/164, last seen 2026-08-06).

Every signature asserted here comes from a real SDK call site. An earlier draft
of this module guessed them and got the argument ORDER, UnloadMusic's arity,
StartMusic's return value and the enable/disable pair all wrong — the SDK is
ground truth, not intuition.
"""
import App
from engine.appc.music_manager import MusicManager


class _Backend:
    """Mirrors MusicPlayer's real surface — including `fade`. A double that
    omits a parameter the real class requires hides exactly the bug it should
    catch."""
    def __init__(self):
        self.played, self.oneshots, self.stopped = [], [], 0
        self.fades = []
    def play(self, path, looping=True, fade=0.0):
        self.played.append(path)
        self.fades.append(fade)
    def play_oneshot(self, path): self.oneshots.append(path)
    def stop(self): self.stopped += 1


def test_app_exposes_the_music_manager_and_event_types():
    assert isinstance(App.g_kMusicManager, MusicManager)
    # Undefined App constants collapse to int()==0 and silently match each
    # other; these must be distinct real ints.
    assert type(App.ET_MUSIC_DONE) is int
    assert type(App.ET_MUSIC_CONDITION_CHANGED) is int
    assert App.ET_MUSIC_DONE != App.ET_MUSIC_CONDITION_CHANGED


def test_load_music_takes_path_first_then_name():
    """DynamicMusic.py:60 calls LoadMusic(sFile, sMusicType, 2.0) — FILE first.
    Reversing these silently registers every track under its own filename."""
    m = MusicManager()
    m.LoadMusic("sfx/Music/EpisGen2.mp3", "Starting Ambient", 2.0)
    assert m.StartMusic("Starting Ambient") == 1
    assert m.current() == "Starting Ambient"


def test_start_music_returns_1_on_success_and_0_on_failure():
    """DynamicMusic.py:178 reads `if StartMusic(...)`. A None return would make
    every track look unplayable and silently drain the queue."""
    m = MusicManager()
    m.LoadMusic("sfx/Music/a.mp3", "Known")
    assert m.StartMusic("Known", 1) == 1
    assert m.StartMusic("Never Loaded", 1) == 0
    assert type(m.StartMusic("Known", 1)) is int


def test_failed_start_does_not_become_current():
    m = MusicManager()
    m.StartMusic("Never Loaded")
    assert m.current() is None


def test_unload_music_takes_a_name_and_drops_only_that_track():
    """DynamicMusic.UnloadMusic loops dsMusicTypes.values() calling
    App.g_kMusicManager.UnloadMusic(sMusic) per track — not a clear-all."""
    m = MusicManager()
    m.LoadMusic("sfx/Music/a.mp3", "A")
    m.LoadMusic("sfx/Music/b.mp3", "B")
    m.UnloadMusic("A")
    assert m.StartMusic("A") == 0, "unloaded track must no longer start"
    assert m.StartMusic("B") == 1, "sibling track must survive"


def test_unloading_the_current_track_stops_playback():
    m = MusicManager()
    b = _Backend()
    m.set_backend(b)
    m.LoadMusic("sfx/Music/a.mp3", "A")
    m.StartMusic("A")
    m.UnloadMusic("A")
    assert m.current() is None
    assert b.stopped == 1


def test_stop_music_clears_current():
    m = MusicManager()
    m.LoadMusic("sfx/Music/a.mp3", "A")
    m.StartMusic("A")
    m.StopMusic()
    assert m.current() is None


def test_starting_a_second_track_replaces_the_first():
    m = MusicManager()
    m.LoadMusic("sfx/Music/a.mp3", "A")
    m.LoadMusic("sfx/Music/b.mp3", "B")
    m.StartMusic("A")
    m.StartMusic("B")
    assert m.current() == "B"


def test_set_enabled_zero_mutes_and_stops(monkeypatch):
    """E8M2.py:6559 disables music for a scripted sequence and restores the
    previous value at :6568."""
    m = MusicManager()
    b = _Backend()
    m.set_backend(b)
    m.LoadMusic("sfx/Music/a.mp3", "A")
    m.StartMusic("A")
    m.SetEnabled(0)
    assert m.IsEnabled() == 0
    assert m.current() is None, "disabling must stop what is playing"
    assert m.StartMusic("A") == 0, "disabled manager must refuse to start"


def test_is_enabled_defaults_on_and_round_trips():
    m = MusicManager()
    assert m.IsEnabled() == 1
    assert type(m.IsEnabled()) is int
    was = m.IsEnabled()
    m.SetEnabled(0)
    m.SetEnabled(was)
    assert m.IsEnabled() == 1


def test_play_fanfare_does_not_replace_the_current_track():
    """DynamicMusic resumes its queue after a fanfare, so the underlying track
    is still what is playing."""
    m = MusicManager()
    b = _Backend()
    m.set_backend(b)
    m.LoadMusic("sfx/Music/a.mp3", "A")
    m.LoadMusic("sfx/Music/fanfare.mp3", "Kessok Fanfare")
    m.StartMusic("A")
    m.PlayFanfare("Kessok Fanfare")
    assert m.current() == "A"
    assert b.oneshots == ["sfx/Music/fanfare.mp3"]


def test_manager_forwards_playback_to_its_backend():
    """The manager must actually drive a backend — it is inert otherwise."""
    m = MusicManager()
    b = _Backend()
    m.set_backend(b)
    m.LoadMusic("sfx/Music/combat.mp3", "Combat")
    m.StartMusic("Combat")
    assert b.played == ["sfx/Music/combat.mp3"]
    m.StopMusic()
    assert b.stopped == 1


def test_track_end_broadcasts_et_music_done_carrying_the_track_name(monkeypatch):
    """DynamicMusic.MusicDone gates its queue advance on
    `pEvent.GetCString() == dsMusicTypes[sCurrentMusicType]`, so the event MUST
    carry the finished track's name. Without it the playlist stalls on track one
    while music is still audible — a silent failure."""
    sent = []

    class _EvtMgr:
        def AddBroadcastPythonFuncHandler(self, *a, **k): pass
        def BroadcastEvent(self, evt): sent.append(evt)

    monkeypatch.setattr(App, "g_kEventManager", _EvtMgr(), raising=False)

    m = MusicManager()
    m.LoadMusic("sfx/Music/combat.mp3", "Cbt Panic 1")
    m.StartMusic("Cbt Panic 1")
    m.notify_track_finished()

    assert len(sent) == 1
    assert sent[0].GetEventType() == App.ET_MUSIC_DONE
    assert sent[0].GetCString() == "Cbt Panic 1"
    assert m.current() is None, "a finished track is no longer current"


def test_track_end_on_an_idle_manager_is_a_no_op(monkeypatch):
    sent = []

    class _EvtMgr:
        def AddBroadcastPythonFuncHandler(self, *a, **k): pass
        def BroadcastEvent(self, evt): sent.append(evt)

    monkeypatch.setattr(App, "g_kEventManager", _EvtMgr(), raising=False)

    m = MusicManager()
    m.notify_track_finished()
    assert sent == [], "no track was playing, so nothing finished"


def test_fade_passed_to_the_backend_is_the_OUTGOING_tracks_grid():
    """A track change is quantised to the grid of what is already playing, not
    of the track being started. Registered per track by LoadMusic's third
    argument (2.0 in shipping data)."""
    m = MusicManager()
    b = _Backend()
    m.set_backend(b)
    m.LoadMusic("a.mp3", "A", 2.0)
    m.LoadMusic("b.mp3", "B", 5.0)

    m.StartMusic("A")
    assert b.fades[0] == 0.0, "nothing playing => duration-0 record, no fade-in"

    m.StartMusic("B")
    assert b.fades[1] == 2.0, "A's grid (2.0), not B's (5.0)"
