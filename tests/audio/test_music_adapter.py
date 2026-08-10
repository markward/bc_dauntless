"""The host's music sound adapter must LOAD its file, not just name it.

This pins the live bug behind "music not playing" (2026-08-10, found by Mark in
a real run). Every symbol DynamicMusic needs was implemented and reached — the
stub telemetry for that run shows g_kMusicManager gone entirely — but the
adapter built its stream with

    TGSound(path, False)

which does NOT read the file. TGSound's ctor only asks the audio system whether
a sound of that NAME is already registered (`_loaded = _audio.get_sound(name)
!= 0`). An unloaded TGSound's Play() does nothing, so the result was silence
with no error and no log.

TGSoundManager.LoadSound is the route that actually works: it resolves the
path, reads the bytes, calls `_audio.load_sound(...)`, and only then constructs
the handle.

The failure mode is SILENT, which is exactly why it needs a test rather than a
comment.
"""
import engine.host_loop as host_loop


class _FakeSound:
    def __init__(self, name):
        self.name = name
        self.gain = None
        self.looping = None
        self.stopped = False
        self.played = False
    def SetVolume(self, g): self.gain = g
    def SetLooping(self, v): self.looping = v
    def Stop(self): self.stopped = True
    def Play(self):
        self.played = True
        class _H:
            def is_live(self): return True
        return _H()


class _FakeManager:
    """Mirrors TGSoundManager's real LoadSound signature."""
    def __init__(self): self.calls = []
    def LoadSound(self, path, name, loadspec):
        self.calls.append((path, name, loadspec))
        return _FakeSound(name)


def _patch(monkeypatch):
    mgr = _FakeManager()
    import engine.audio.tg_sound as tg

    class _TGSoundShim:
        LS_3D = tg.TGSound.LS_3D
        LS_STREAMED = tg.TGSound.LS_STREAMED
        def __init__(self, *a, **k):
            raise AssertionError(
                "adapter constructed TGSound directly — that does NOT load the "
                "file and plays silence. Use TGSoundManager.LoadSound."
            )

    class _MgrShim:
        @staticmethod
        def instance(): return mgr

    monkeypatch.setattr(tg, "TGSound", _TGSoundShim, raising=True)
    monkeypatch.setattr(tg, "TGSoundManager", _MgrShim, raising=True)
    return mgr


def test_adapter_loads_the_file_through_the_sound_manager(monkeypatch):
    mgr = _patch(monkeypatch)
    snd = host_loop._music_sound_adapter("sfx/Music/EpisGen2.mp3")
    assert snd is not None
    assert len(mgr.calls) == 1, "must go through LoadSound exactly once"
    path, name, loadspec = mgr.calls[0]
    assert path == "sfx/Music/EpisGen2.mp3"


def test_adapter_requests_a_streamed_not_positional_sound(monkeypatch):
    """Music is 2D. LoadSound derives positional from loadspec == LS_3D, so
    asking for LS_3D would anchor the soundtrack in the scene."""
    import engine.audio.tg_sound as tg
    expected = tg.TGSound.LS_STREAMED
    mgr = _patch(monkeypatch)
    host_loop._music_sound_adapter("sfx/Music/EpisGen2.mp3")
    assert mgr.calls[0][2] == expected


def test_adapter_starts_playback_and_applies_looping(monkeypatch):
    _patch(monkeypatch)
    snd = host_loop._music_sound_adapter("sfx/Music/a.mp3", looping=True)
    assert snd.playing is True, "the underlying sound must actually be played"
    assert snd._snd.played is True
    assert snd._snd.looping == 1


def test_a_non_looping_track_is_not_set_to_loop(monkeypatch):
    _patch(monkeypatch)
    snd = host_loop._music_sound_adapter("sfx/Music/sting.mp3", looping=False)
    assert snd._snd.looping == 0


def test_an_unloadable_file_yields_None_rather_than_a_dead_stream(monkeypatch):
    """LoadSound returns None for an unreadable file or absent backend. The
    adapter must pass that through so MusicPlayer can keep the current track
    rather than tearing it down for a stream that never started."""
    import engine.audio.tg_sound as tg

    class _NoneMgr:
        @staticmethod
        def instance():
            class _M:
                def LoadSound(self, *a): return None
            return _M()

    monkeypatch.setattr(tg, "TGSoundManager", _NoneMgr, raising=True)
    assert host_loop._music_sound_adapter("sfx/Music/missing.mp3") is None
