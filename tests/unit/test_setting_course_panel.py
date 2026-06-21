"""Unit tests for SettingCoursePanel — the placeholder Set Course modal."""
import json

from engine.ui.setting_course_panel import SettingCoursePanel


def _payload_dict(js: str) -> dict:
    """Extract the JSON arg from `setSettingCoursePanel(<json>);`."""
    assert js.startswith("setSettingCoursePanel(")
    assert js.endswith(");")
    inner = js[len("setSettingCoursePanel("):-len(");")]
    return json.loads(inner)


def test_name_is_setting_course():
    assert SettingCoursePanel().name == "setting-course"


def test_starts_hidden():
    p = SettingCoursePanel()
    assert p.is_open() is False
    js = p.render_payload()
    assert _payload_dict(js) == {"visible": False}


def test_open_emits_visible_message_payload():
    p = SettingCoursePanel()
    p.render_payload()  # flush the initial hidden payload
    p.open()
    assert p.is_open() is True
    data = _payload_dict(p.render_payload())
    assert data["visible"] is True
    assert data["title"] == "Set Course"
    assert data["message"] == "Setting course…"
    assert data["destinations"] == []


def test_render_is_snapshot_cached():
    p = SettingCoursePanel()
    p.open()
    first = p.render_payload()
    assert first is not None
    assert p.render_payload() is None  # no state change -> no re-emit


def test_cancel_closes_and_emits_hidden():
    p = SettingCoursePanel()
    p.open()
    p.render_payload()
    assert p.dispatch_event("cancel") is True
    assert p.is_open() is False
    assert _payload_dict(p.render_payload()) == {"visible": False}


def test_unknown_action_returns_false():
    p = SettingCoursePanel()
    assert p.dispatch_event("frobnicate") is False


def test_handle_key_esc_closes_when_open():
    p = SettingCoursePanel()
    p.open()
    p.handle_key_esc()
    assert p.is_open() is False


def test_invalidate_forces_reemit():
    p = SettingCoursePanel()
    p.open()
    p.render_payload()
    assert p.render_payload() is None
    p.invalidate()
    assert p.render_payload() is not None


def test_open_stores_course_menu_for_future_wiring():
    p = SettingCoursePanel()
    sentinel = object()
    p.open(course_menu=sentinel)
    assert p._course_menu is sentinel
