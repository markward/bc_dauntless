"""tests/helpers/fight_audio.py: what every native-combat differential arm
runs so whether an officer speaks (an animation and a line pick on the SDK
RNG) is decided by the fight alone, never by wall-clock speed or an earlier
fight. (hit_feedback's contact gap runs on game time itself.)"""
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
        for module in (crew_speech, speak_queue):
            assert module.time.monotonic() == 12.5, module
        App.g_kTimerManager._time = 13.0
        assert speak_queue.time.monotonic() == 13.0
    # The clocks are the real ones again once the context closes.
    import time
    for module in (crew_speech, speak_queue):
        assert module.time is time, module


def test_resets_the_bridge_crew_announcement_stamps(monkeypatch):
    """A Bridge.*Handlers module kept from an earlier load holds its last
    call-out's game time: each arm gets the SDK's initial 0 back (restored
    when the context closes)."""
    import sys
    import types
    mod = types.ModuleType("Bridge.FakeCrewHandlers")
    mod.g_fLastAnnounceSpecificShield = 10.25
    mod.g_fCommunicate = 3
    mod.g_fTargetSetTime = 7.5
    mod.g_fOther = 9.0              # not a throttle stamp: left alone
    mod.g_fLastName = "x"           # not a number: left alone
    monkeypatch.setitem(sys.modules, "Bridge.FakeCrewHandlers", mod)
    with monkeypatch.context() as mp:
        isolate_fight_audio(mp)
        assert mod.g_fLastAnnounceSpecificShield == 0.0
        assert type(mod.g_fLastAnnounceSpecificShield) is float
        assert mod.g_fCommunicate == 0 and type(mod.g_fCommunicate) is int
        assert mod.g_fTargetSetTime == 0.0
        assert mod.g_fOther == 9.0 and mod.g_fLastName == "x"
    assert mod.g_fLastAnnounceSpecificShield == 10.25
