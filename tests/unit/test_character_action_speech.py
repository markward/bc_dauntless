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


def test_say_line_action_now_routes_subtitle():
    # With voice_only removed, AT_SAY_LINE routes a subtitle like AT_SPEAK_LINE.
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    db = TGLocalizationDatabase("x.tgl", strings={"ack": "Aye sir"})
    a = CharacterAction_Create(_char("XO"), CharacterAction.AT_SAY_LINE,
                               "ack", "Captain", 0, db, CSP_NORMAL)
    a.Play()
    snap = _subtitle()._snapshot(now=0.0)
    assert snap is not None
    assert snap["speech"] == "Aye sir"


def test_non_speech_action_is_silent():
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    a = CharacterAction_Create(_char("Helm"), CharacterAction.AT_MOVE,
                               None, None, 0, None, CSP_NORMAL)
    a.Play()  # must not raise, must not speak
    assert _subtitle()._snapshot(now=0.0) is None
    assert crew_speech.bus()._active_priority == -1  # channel untouched


def test_create_by_name_uses_string_character_as_speaker():
    # CharacterAction_CreateByName(setName, charName, action_type, detail, ...)
    # stores charName as a STRING in _character (no CharacterClass object), e.g.
    # CreateByName("LiuSet", "Liu", AT_SPEAK_LINE, "L1", None, 0, db). The
    # speaker label must be "Liu", not blank.
    from engine.appc.ai import CharacterAction_CreateByName
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    db = TGLocalizationDatabase("x.tgl", strings={"L1": "Torpedoes loaded"})
    a = CharacterAction_CreateByName(
        "LiuSet", "Liu", CharacterAction.AT_SPEAK_LINE, "L1", None, 0, db)
    a.Play()
    snap = _subtitle()._snapshot(now=0.0)
    assert snap["speaker"] == "Liu"
    assert snap["speech"] == "Torpedoes loaded"
