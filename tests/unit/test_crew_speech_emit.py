"""crew_speech.emit -- shared line resolution feeding the bus."""
from engine.appc import top_window, crew_speech
from engine.appc.localization import TGLocalizationDatabase
from engine.appc.ai import CSP_NORMAL


def _subtitle():
    import App
    return App.TopWindow_GetTopWindow().FindMainWindow(App.MWT_SUBTITLE)


def test_emit_speak_routes_text_and_wav():
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    db = TGLocalizationDatabase("x.tgl", strings={"L1": "Shields holding"})
    crew_speech.emit("Tactical", db, "L1", CSP_NORMAL, voice_only=False)
    snap = _subtitle()._snapshot(now=0.0)
    assert snap["speaker"] == "Tactical"
    assert snap["speech"] == "Shields holding"


def test_emit_voice_only_sets_no_subtitle():
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    db = TGLocalizationDatabase("x.tgl", strings={"L1": "Shields holding"})
    crew_speech.emit("XO", db, "L1", CSP_NORMAL, voice_only=True)
    assert _subtitle()._snapshot(now=0.0) is None


def test_emit_missing_string_shows_no_subtitle():
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    db = TGLocalizationDatabase("x.tgl")  # no strings -> HasString False
    crew_speech.emit("Eng", db, "ge119", CSP_NORMAL, voice_only=False)
    assert _subtitle()._snapshot(now=0.0) is None


def test_emit_none_db_is_safe():
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    crew_speech.emit("Eng", None, "ge119", CSP_NORMAL, voice_only=False)
    assert _subtitle()._snapshot(now=0.0) is None
