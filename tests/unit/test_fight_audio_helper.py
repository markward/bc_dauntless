"""tests/helpers/fight_audio.py: what every native-combat differential arm
runs so whether a hit plays a sound (one SDK RNG draw) is decided by the
fight alone, never by wall-clock speed or an earlier fight."""
import App
import LoadTacticalSounds

from engine.appc import crew_speech, hit_feedback, speak_queue
from tests.helpers.fight_audio import isolate_fight_audio


def test_clears_the_memories_and_runs_the_gaps_on_game_time(monkeypatch):
    LoadTacticalSounds.g_dRecentSounds[("a", "b")] = ["a"]
    hit_feedback._last_dispatch_time[(1, "x")] = 5.0
    monkeypatch.setattr(App.g_kTimerManager, "_time", 12.5)
    with monkeypatch.context() as mp:
        isolate_fight_audio(mp)
        assert LoadTacticalSounds.g_dRecentSounds == {}
        assert hit_feedback._last_dispatch_time == {}
        for module in (hit_feedback, crew_speech, speak_queue):
            assert module.time.monotonic() == 12.5, module
        App.g_kTimerManager._time = 13.0
        assert hit_feedback.time.monotonic() == 13.0
    # The clocks are the real ones again once the context closes.
    import time
    for module in (hit_feedback, crew_speech, speak_queue):
        assert module.time is time, module
