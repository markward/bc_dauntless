"""CharacterClass.GetLastTalkTime -- backed by the crew-speech chokepoint.

GetLastTalkTime is a real Appc getter (App.py:4819) that mission/bridge scripts
read via `GetGameTime() - GetLastTalkTime()` to throttle idle chatter (e.g. the
E1M2 Miguel asteroid-close >30s gate and Saffi friendly-fire <5s gate). It has no
SDK setter -- BC's engine stamps it whenever the character speaks. We stamp it in
CrewSpeechBus.speak() (the single chokepoint every speech path funnels through),
keyed by character name, using GAME time.
"""
import App
from engine.appc import top_window, crew_speech
from engine.appc.characters import CharacterClass
from engine.appc.ai import (
    CharacterAction, CharacterAction_Create, CSP_NORMAL, CSP_SPONTANEOUS,
)
from engine.appc.localization import TGLocalizationDatabase


def _set_game_time(t: float) -> None:
    App.g_kTimerManager._time = float(t)


def _char(name: str) -> CharacterClass:
    c = CharacterClass()
    c.SetCharacterName(name)
    return c


def _db(line="L1", text="Asteroid closing, Captain."):
    return TGLocalizationDatabase("x.tgl", strings={line: text})


def test_default_before_speaking_is_zero():
    # BC-faithful: a character that has never spoken reads 0.0 ("no recent
    # speech history"), so GetGameTime() - 0.0 == current game time.
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    miguel = _char("Miguel")
    assert miguel.GetLastTalkTime() == 0.0


def test_speaking_stamps_game_time():
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    miguel = _char("Miguel")
    _set_game_time(42.0)
    miguel.SpeakLine(_db(), "L1", CSP_NORMAL)
    assert miguel.GetLastTalkTime() == 42.0


def test_character_action_say_line_stamps():
    # The path E1M2 actually uses: CharacterAction_Create(char, AT_SAY_LINE, ...).Play()
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    saffi = _char("Saffi")
    _set_game_time(17.5)
    action = CharacterAction_Create(
        saffi, CharacterAction.AT_SAY_LINE, "L1", "Captain", 1, _db())
    action.Play()
    assert saffi.GetLastTalkTime() == 17.5


def test_elapsed_gate_fires_after_threshold():
    # E1M2 Miguel idle gate: GetGameTime() - GetLastTalkTime() > 30.
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    miguel = _char("Miguel")
    _set_game_time(10.0)
    miguel.SpeakLine(_db(), "L1", CSP_NORMAL)

    # 2s later: within the 5s throttle window (Saffi-style <5.0 holds), and the
    # 30s idle gate has NOT elapsed.
    _set_game_time(12.0)
    since = App.g_kUtopiaModule.GetGameTime() - miguel.GetLastTalkTime()
    assert since == 2.0
    assert not (since > 30)

    # 35s after the last line: the >30 idle gate now fires.
    _set_game_time(45.0)
    since = App.g_kUtopiaModule.GetGameTime() - miguel.GetLastTalkTime()
    assert since == 35.0
    assert since > 30


def test_reset_clears_on_mission_swap():
    # crew_speech.bus().reset() runs on every mission swap; a stale timestamp
    # must not leak into the next mission.
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    miguel = _char("Miguel")
    _set_game_time(99.0)
    miguel.SpeakLine(_db(), "L1", CSP_NORMAL)
    assert miguel.GetLastTalkTime() == 99.0

    crew_speech.bus().reset()
    assert miguel.GetLastTalkTime() == 0.0


def test_priority_dropped_line_does_not_stamp():
    # A lower-priority line rejected while a higher-priority line is still live
    # must leave the dropped speaker's timestamp untouched (it never spoke).
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    bus = crew_speech.bus()

    _set_game_time(100.0)
    # High-priority line takes the channel (explicit wall-clock `now`).
    assert bus.speak("Picard", "Report.", None, CSP_NORMAL, now=100.0) > 0.0
    assert bus._last_talk["Picard"] == 100.0

    # Lower-priority line arrives while Picard is still talking -> dropped.
    _set_game_time(100.5)
    assert bus.speak("Miguel", "Uh, sir?", None, CSP_SPONTANEOUS, now=100.1) == 0.0
    assert "Miguel" not in bus._last_talk
    assert crew_speech.last_talk_time("Miguel") == 0.0
