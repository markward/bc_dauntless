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
    crew_speech.emit("Tactical", db, "L1", CSP_NORMAL)
    snap = _subtitle()._snapshot(now=0.0)
    assert snap["speaker"] == "Tactical"
    assert snap["speech"] == "Shields holding"


def test_emit_say_line_now_routes_subtitle():
    # SayLine-style line (previously voice_only=True -> no subtitle). With the
    # voice_only distinction removed, a line with text routes a subtitle like
    # any other spoken line.
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    db = TGLocalizationDatabase("x.tgl", strings={"L1": "Shields holding"})
    crew_speech.emit("XO", db, "L1", CSP_NORMAL)
    snap = _subtitle()._snapshot(now=0.0)
    assert snap is not None
    assert snap["speech"] == "Shields holding"


def test_emit_no_subtitle_when_subtitles_disabled():
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    db = TGLocalizationDatabase("x.tgl", strings={"L1": "Shields holding"})
    crew_speech.set_subtitles_enabled(False)
    try:
        crew_speech.emit("XO", db, "L1", CSP_NORMAL)
        assert _subtitle()._snapshot(now=0.0) is None
    finally:
        crew_speech.set_subtitles_enabled(True)


def test_emit_missing_string_shows_no_subtitle():
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    db = TGLocalizationDatabase("x.tgl")  # no strings -> HasString False
    crew_speech.emit("Eng", db, "ge119", CSP_NORMAL)
    assert _subtitle()._snapshot(now=0.0) is None


def test_emit_none_db_is_safe():
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    crew_speech.emit("Eng", None, "ge119", CSP_NORMAL)
    assert _subtitle()._snapshot(now=0.0) is None


# ---- "Disable Annoying Dialogue" gate (Configuration > Gameplay) ----------

def test_annoying_dialogue_disabled_default_is_true():
    assert crew_speech.annoying_dialogue_disabled() is True


def test_emit_annoying_line_dropped_when_disabled(monkeypatch):
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    db = TGLocalizationDatabase("x.tgl", strings={"QBExposition": "Our ship..."})
    calls = []
    monkeypatch.setattr(crew_speech.bus(), "speak",
                        lambda *a, **k: calls.append(a) or 9.9)
    # Default is ON (suppress) -> 0.0, no subtitle, bus.speak never called.
    assert crew_speech.emit("XO", db, "QBExposition", CSP_NORMAL) == 0.0
    assert calls == []
    assert _subtitle()._snapshot(now=0.0) is None


def test_emit_annoying_line_plays_when_flag_disabled(monkeypatch):
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    db = TGLocalizationDatabase("x.tgl", strings={"QBExposition": "Our ship..."})
    calls = []
    monkeypatch.setattr(crew_speech.bus(), "speak",
                        lambda *a, **k: calls.append(a) or 9.9)
    crew_speech.set_annoying_dialogue_disabled(False)
    try:
        assert crew_speech.emit("XO", db, "QBExposition", CSP_NORMAL) == 9.9
        assert len(calls) == 1
    finally:
        crew_speech.set_annoying_dialogue_disabled(True)


def test_emit_non_annoying_line_unaffected_by_flag(monkeypatch):
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    db = TGLocalizationDatabase("x.tgl", strings={"SomeOtherLine": "Shields up"})
    calls = []
    monkeypatch.setattr(crew_speech.bus(), "speak",
                        lambda *a, **k: calls.append(a) or 4.4)
    # Flag ON (suppress annoying) but this key is not annoying -> normal.
    assert crew_speech.annoying_dialogue_disabled() is True
    assert crew_speech.emit("XO", db, "SomeOtherLine", CSP_NORMAL) == 4.4
    assert len(calls) == 1
