"""CharacterAction speak action-types route through the speech bus."""
from engine.appc import top_window, crew_speech
from engine.appc.characters import CharacterClass
from engine.appc.ai import CharacterAction, CharacterAction_Create, CSP_NORMAL
from engine.appc.localization import TGLocalizationDatabase


def _subtitle():
    import App
    return App.TopWindow_GetTopWindow().FindMainWindow(App.MWT_SUBTITLE)


def _char(name):
    c = CharacterClass()
    c.SetCharacterName(name)
    return c


def test_speak_line_action_shows_subtitle():
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    db = TGLocalizationDatabase("x.tgl", strings={"L1": "Course laid in"})
    a = CharacterAction_Create(_char("Helm"), CharacterAction.AT_SPEAK_LINE,
                               "L1", "Captain", 0, db, CSP_NORMAL)
    a.Play()
    snap = _subtitle()._snapshot(now=0.0)
    assert snap["speaker"] == "Helm"
    assert snap["speech"] == "Course laid in"


def test_say_line_action_sets_no_subtitle():
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    db = TGLocalizationDatabase("x.tgl", strings={"ack": "Aye sir"})
    a = CharacterAction_Create(_char("XO"), CharacterAction.AT_SAY_LINE,
                               "ack", "Captain", 0, db, CSP_NORMAL)
    a.Play()
    assert _subtitle()._snapshot(now=0.0) is None


def test_non_speech_action_is_silent():
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    a = CharacterAction_Create(_char("Helm"), CharacterAction.AT_MOVE,
                               None, None, 0, None, CSP_NORMAL)
    a.Play()  # must not raise, must not speak
    assert _subtitle()._snapshot(now=0.0) is None
    assert crew_speech.bus()._active_priority == -1  # channel untouched
