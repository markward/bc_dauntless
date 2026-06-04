"""App.py re-exports for the SDK UI shims."""
import App
from engine.appc.windows import _SubtitleWindow, _STStylizedWindow


def test_app_subtitle_window_class_exposes_sm_tactical():
    assert App.SubtitleWindow.SM_TACTICAL == 1


def test_app_subtitle_window_cast_returns_subtitle_instance():
    sw = _SubtitleWindow()
    assert App.SubtitleWindow_Cast(sw) is sw


def test_app_subtitle_window_cast_none_returns_none():
    assert App.SubtitleWindow_Cast(None) is None


def test_app_stylized_window_create_w_returns_instance():
    w = App.STStylizedWindow_CreateW("Title")
    assert isinstance(w, _STStylizedWindow)
    assert w._title == "Title"
