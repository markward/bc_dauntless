"""Headless frames that run what the live host runs each frame for a fight's
end: the SetDeleteMe sweep (host_loop._process_object_deletions; EndSimulation
clears the battle this way, so without it every ship outlives the battle), the
GameLoop tick, ship deaths (ship_death.advance -- the host calls it from its
combat step, so a bare GameLoop leaves a dying ship dying forever) and the
music pump (MusicPlayer.update, then ET_MUSIC_DONE when a track ends, as
host_loop._pump_music)."""
from engine.audio.music import MusicPlayer

DT = 1.0 / 60.0


class FakeSound:
    def __init__(self, path, looping):
        self.path, self.looping = path, looping
        self.gain = 1.0
        self.playing = True
        self.stopped = False

    def SetVolume(self, g):
        self.gain = g

    def Stop(self):
        self.stopped = True
        self.playing = False


class Frames:
    """`run(seconds)` steps 60 Hz frames. Music goes to a fake MusicPlayer whose
    streams end at their real file length (`lengths`, by path suffix)."""

    def __init__(self, lengths=None):
        import App
        from engine.core.loop import GameLoop
        self.loop = GameLoop()
        self.made = []
        self.lengths = dict(lengths or {})
        self.t = 0.0
        self._ends = {}

        def factory(path, looping=True):
            s = FakeSound(path, looping)
            self.made.append(s)
            for suffix, length in self.lengths.items():
                if str(path).endswith(suffix) and not looping:
                    self._ends[id(s)] = (s, self.t + length)
            return s
        self.player = MusicPlayer(sound_factory=factory)
        self.mgr = App.g_kMusicManager
        self.mgr.set_backend(self.player)

    def frame(self):
        from engine.appc import ship_death
        from engine.host_loop import _process_object_deletions
        _process_object_deletions()
        self.loop.tick()
        ship_death.advance(DT)
        self._streams(DT)
        self.player.update(DT)
        if self.player.finished():
            self.mgr.notify_track_finished()

    def paused_frame(self):
        """A frame with the sim frozen (the pause menu): no tick, game time
        stands still, the streams play on and the host pumps the music on
        real time (host_loop._pump_music_paused)."""
        from engine import host_loop
        self._streams(DT)
        saved = host_loop._music_player
        host_loop._music_player = self.player
        try:
            host_loop._pump_music_paused(DT)
        finally:
            host_loop._music_player = saved

    def _streams(self, dt):
        self.t += dt
        for key, (s, end) in list(self._ends.items()):
            if self.t >= end and s.playing:
                s.playing = False
                del self._ends[key]

    def run_paused(self, seconds):
        for _ in range(int(round(seconds / DT))):
            self.paused_frame()

    def run(self, seconds, until=None):
        n = int(round(seconds / DT))
        for _ in range(n):
            self.frame()
            if until is not None and until():
                return True
        return False
