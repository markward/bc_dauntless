"""End-to-end: a CharacterClass SpeakLine reaches the subtitle snapshot, and
reset_sdk_globals frees the speech channel for the next mission."""
import App
from engine.appc import top_window, crew_speech
from engine.appc.characters import CharacterClass
from engine.appc.localization import TGLocalizationDatabase
from engine.appc.ai import CSP_SPONTANEOUS, CSP_MISSION_CRITICAL


def _subtitle():
    return App.TopWindow_GetTopWindow().FindMainWindow(App.MWT_SUBTITLE)


def test_speakline_reaches_subtitle_snapshot():
    top_window.reset_for_tests()
    crew_speech.bus().reset()

    eng = CharacterClass()
    eng.SetCharacterName("Engineering")
    db = TGLocalizationDatabase(
        "Bridge Crew General.tgl", strings={"ge119": "Warp core stable."})

    eng.SpeakLine(db, "ge119", CSP_SPONTANEOUS)

    snap = _subtitle()._snapshot(now=0.0)
    assert snap is not None
    assert snap["speaker"] == "Engineering"
    assert snap["speech"] == "Warp core stable."


def test_mission_critical_preempts_spontaneous():
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    db = TGLocalizationDatabase(
        "x.tgl", strings={"a": "chatter", "b": "ABANDON SHIP"})

    eng = CharacterClass(); eng.SetCharacterName("Engineering")
    felix = CharacterClass(); felix.SetCharacterName("Felix")

    eng.SpeakLine(db, "a", CSP_SPONTANEOUS)
    felix.SpeakLine(db, "b", CSP_MISSION_CRITICAL)

    snap = _subtitle()._snapshot(now=0.0)
    assert snap["speaker"] == "Felix"
    assert snap["speech"] == "ABANDON SHIP"


def test_reset_sdk_globals_clears_speech_channel():
    from engine.host_loop import reset_sdk_globals

    top_window.reset_for_tests()
    crew_speech.bus().reset()
    db = TGLocalizationDatabase("x.tgl", strings={"crit": "critical"})

    felix = CharacterClass(); felix.SetCharacterName("Felix")
    felix.SpeakLine(db, "crit", CSP_MISSION_CRITICAL)

    reset_sdk_globals()

    # Channel is free: a brand-new low-priority line is accepted immediately
    # (would return False if reset_sdk_globals had not cleared the bus lock).
    assert crew_speech.bus().speak("Eng", "hi", None, CSP_SPONTANEOUS) is True
    # ...and it routes into the freshly rebuilt subtitle window.
    snap = _subtitle()._snapshot(now=0.0)
    assert snap["speaker"] == "Eng"
    assert snap["speech"] == "hi"
