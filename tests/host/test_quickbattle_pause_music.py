"""Quick Battle music under the pause menu.

Measured on the original (stbc-oracle music probe Q3, native Windows, real
time, UtopiaModule.Pause for 20.25 s mid-fight): the music neither stops nor
ducks. The Combat Neutral track that ended 3.75 s into the pause was followed
at once by the next (ET_MUSIC_DONE still reached DynamicMusic, with game time
frozen), and the one after came exactly 30.0 s of real time later."""
import pytest

pytest.importorskip("_dauntless_host")

from tests.host.test_quickbattle_end_of_fight_music import _fight


def test_a_track_that_ends_under_pause_is_followed_by_the_next(monkeypatch):
    App, DM, frames, player, enemy, log = _fight(monkeypatch)
    state = DM.pStateMachine.GetMusicState()
    playing = frames.made[-1]
    assert playing.playing and not playing.looping
    t_game = App.g_kUtopiaModule.GetGameTime()
    frames.run_paused(40.0)          # longer than one 30.04 s track
    assert App.g_kUtopiaModule.GetGameTime() == t_game
    done = [e for e in log if e[0] == "MusicDone"]
    assert done and all(t == t_game for _n, t, _a in done)
    assert not playing.playing
    current = frames.made[-1]
    assert current is not playing and current.playing and not current.looping
    assert DM.pStateMachine.GetMusicState() == state


def test_a_crossfade_under_pause_completes_on_real_time(monkeypatch):
    App, DM, frames, player, enemy, log = _fight(monkeypatch)
    DM.SwitchMusic("Starting Ambient")
    old = [s for s in frames.made if s.playing and not s.looping]
    frames.run_paused(5.0)
    assert old and all(s.stopped for s in old)
    assert frames.made[-1].playing and frames.made[-1].gain == pytest.approx(1.0)
