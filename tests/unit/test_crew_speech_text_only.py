"""A Dauntless crew line with no voice file is subtitle-only: it still shows
its subtitle and still has a positive duration (the text-length estimate)."""
from engine.appc import top_window, crew_speech
from engine.appc.localization import TGLocalizationDatabase
from engine.missions import tgl_reader
from tools import gen_dauntless_tgl as g

_TEXT = ("The ship we were assigned to protect has been destroyed. "
         "Ending simulation.")


def _crew_db():
    got = tgl_reader._parse(g.build(), source="test")
    return TGLocalizationDatabase("Dauntless Crew.tgl",
                                  strings=got.strings, sounds=got.sounds)


def test_text_only_line_shows_subtitle_and_has_duration():
    import App
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    duration = crew_speech.emit("XO", _crew_db(), "SaffiQBProtectedLost1", 0)
    assert duration > 0
    sub = App.TopWindow_GetTopWindow().FindMainWindow(App.MWT_SUBTITLE)
    snap = sub._snapshot(now=0.0)
    assert snap["speech"] == _TEXT


def test_new_saffi_lines_present():
    strings = tgl_reader._parse(g.build(), source="test").strings
    assert strings["SaffiQBProtectedLostAll1"] == (
        "The ships we were assigned to protect have been destroyed. "
        "Ending simulation.")
    assert strings["SaffiQBSurvived1"] == (
        "Time is up. We held them off. Ending simulation.")
