"""Unit tests for the _SubtitleWindow SDK shim (engine/appc/windows.py)."""
from engine.appc.windows import _SubtitleWindow, SubtitleWindow_Cast, SubtitleWindow


def test_initial_state_hidden_and_empty():
    sw = _SubtitleWindow()
    assert sw._visible is False
    assert sw._active_texts == []
    assert sw._id == "subtitle-0"


def test_set_on_off_toggle():
    sw = _SubtitleWindow()
    sw.SetOn()
    assert sw.IsOn() is True
    sw.SetOff()
    assert sw.IsOn() is False


def test_set_visible_alias_matches_set_on():
    sw = _SubtitleWindow()
    sw.SetVisible()
    assert sw.IsOn() is True


def test_set_position_for_mode_stores_int():
    sw = _SubtitleWindow()
    sw.SetPositionForMode(SubtitleWindow.SM_TACTICAL)
    assert sw._mode == SubtitleWindow.SM_TACTICAL


def test_add_text_appends_with_expiry(monkeypatch):
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 100.0)
    sw._add_text("hello", 5.0)
    assert sw._active_texts == [("hello", 105.0)]


def test_snapshot_returns_none_when_hidden_and_empty():
    sw = _SubtitleWindow()
    assert sw._snapshot(now=0.0) is None


def test_snapshot_returns_dict_when_visible():
    sw = _SubtitleWindow()
    sw.SetOn()
    snap = sw._snapshot(now=0.0)
    assert snap == {
        "type": "subtitle", "id": "subtitle-0",
        "visible": True, "mode": SubtitleWindow.SM_TACTICAL, "lines": [],
    }


def test_snapshot_prunes_expired_text(monkeypatch):
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 0.0)
    sw._add_text("expired", 1.0)
    sw._add_text("alive", 10.0)
    snap = sw._snapshot(now=5.0)
    assert snap["lines"] == ["alive"]
    assert sw._active_texts == [("alive", 10.0)]


def test_snapshot_visible_true_when_text_active_even_if_set_off(monkeypatch):
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 0.0)
    sw._add_text("hello", 5.0)
    snap = sw._snapshot(now=1.0)
    assert snap["visible"] is True
    assert snap["lines"] == ["hello"]


def test_subtitle_window_class_exports_sm_constants():
    assert SubtitleWindow.SM_BRIDGE == 0
    assert SubtitleWindow.SM_TACTICAL == 1
    assert SubtitleWindow.SM_FELIX == 2
    assert SubtitleWindow.SM_NONFELIX == 3
    assert SubtitleWindow.SM_MAP == 4
    assert SubtitleWindow.SM_CINEMATIC == 5
    assert SubtitleWindow.SM_END_CINEMATIC == 6
    assert SubtitleWindow.SM_SPECIAL_FELIX == 7


def test_cast_returns_argument_if_subtitle_window():
    sw = _SubtitleWindow()
    assert SubtitleWindow_Cast(sw) is sw


def test_cast_returns_none_for_none():
    assert SubtitleWindow_Cast(None) is None


def test_cast_returns_none_for_non_subtitle_window():
    assert SubtitleWindow_Cast("not-a-window") is None
    assert SubtitleWindow_Cast(object()) is None
    assert SubtitleWindow_Cast(42) is None
