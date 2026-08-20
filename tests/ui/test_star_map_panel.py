"""StarMapPanel — the CEF-facing half of the star map.

Satisfies the SAME contract as SettingCoursePanel: produce a destination
set-module, call on_course_set, close.
"""
import json

import pytest

from engine.ui.star_map_panel import StarMapPanel


class _FakeMenu:
    def __init__(self, label, children=None):
        self._label = label
        self._children = children or []
    def GetLabel(self):
        return self._label


def _payload(js):
    assert js.startswith("setStarMapPanel(") and js.endswith(");")
    return json.loads(js[len("setStarMapPanel("):-2])


def test_panel_name_is_the_routing_prefix():
    assert StarMapPanel().name == "star-map"


def test_opens_and_closes():
    p = StarMapPanel()
    assert p.is_open() is False
    p.open(set_name="Vesuvi6")
    assert p.is_open() is True
    p.close()
    assert p.is_open() is False


def test_esc_closes():
    p = StarMapPanel()
    p.open(set_name="Vesuvi6")
    p.handle_key_esc()
    assert p.is_open() is False


def test_render_payload_is_idempotent():
    """Panel contract: return None when nothing changed, or CEF re-rasters
    every frame — the documented cause of the HUD flicker bug."""
    p = StarMapPanel()
    p.open(set_name="Vesuvi6")
    assert p.render_payload() is not None
    assert p.render_payload() is None


def test_invalidate_forces_a_re_emit():
    p = StarMapPanel()
    p.open(set_name="Vesuvi6")
    p.render_payload()
    p.invalidate()
    assert p.render_payload() is not None


def test_selecting_a_system_lists_its_warp_points():
    p = StarMapPanel()
    p.open(set_name="Vesuvi6")
    assert p.dispatch_event("select-system:vesuvi") is True
    data = _payload(p.render_payload())
    assert data["selected_system"] == "vesuvi"
    assert data["warp_points"], "vesuvi should have warp points"


def test_selecting_a_system_does_not_move_the_camera():
    """Anchor is fixed (spec §5)."""
    p = StarMapPanel()
    p.open(set_name="Vesuvi6")
    before = p.cam.anchor
    p.dispatch_event("select-system:tevron")
    assert p.cam.anchor == before


def test_set_course_calls_back_with_the_module_and_closes():
    seen = []
    p = StarMapPanel(on_course_set=seen.append)
    p.open(set_name="Vesuvi6")
    p.dispatch_event("select-system:vesuvi")
    data = _payload(p.render_payload())
    wp = next(w for w in data["warp_points"] if w["available"])
    assert p.dispatch_event("set-course:" + wp["id"]) is True
    assert len(seen) == 1 and seen[0]
    assert p.is_open() is False


def test_unavailable_destination_does_not_fire_and_stays_open():
    seen = []
    p = StarMapPanel(on_course_set=seen.append)
    p.open(set_name="Vesuvi6")
    p.dispatch_event("select-system:vesuvi")
    assert p.dispatch_event("set-course:definitely-not-a-warp-point") is False
    assert seen == []
    assert p.is_open() is True


def test_cancel_closes_without_setting_a_course():
    seen = []
    p = StarMapPanel(on_course_set=seen.append)
    p.open(set_name="Vesuvi6")
    assert p.dispatch_event("cancel") is True
    assert seen == []
    assert p.is_open() is False


def test_mission_systems_come_from_the_live_menu():
    p = StarMapPanel()
    p.open(set_name="Tevron1",
           course_menu=_FakeMenu("Set Course", [_FakeMenu("Vesuvi", [])]))
    data = _payload(p.render_payload())
    assert "vesuvi" in data["mission_systems"]


def test_here_marker_absent_when_the_set_is_unmapped():
    """A misplaced 'you are here' is worse than none (spec §5)."""
    p = StarMapPanel()
    p.open(set_name="SomewhereUnmapped")
    data = _payload(p.render_payload())
    assert data["here_system"] is None


def test_orbit_and_zoom_events_move_the_camera_not_the_anchor():
    p = StarMapPanel()
    p.open(set_name="Vesuvi6")
    anchor, dist = p.cam.anchor, p.cam.camera.distance
    assert p.dispatch_event("orbit:0.3,0.1") is True
    assert p.dispatch_event("zoom:-2") is True
    assert p.cam.anchor == anchor
    assert p.cam.camera.distance < dist


def test_headless_construction_without_a_callback_is_safe():
    p = StarMapPanel()
    p.open(set_name="Vesuvi6")
    p.dispatch_event("select-system:vesuvi")
    data = _payload(p.render_payload())
    wp = next(w for w in data["warp_points"] if w["available"])
    assert p.dispatch_event("set-course:" + wp["id"]) is True  # no crash


def test_course_system_key_present_and_none_when_no_course_set():
    """Distinct from selected_system: the CEF layer (Task 6) needs three
    visually distinct states — here, course, and mission — so the payload
    must carry course_system even when nothing has been set yet."""
    p = StarMapPanel()
    p.open(set_name="Vesuvi6")
    data = _payload(p.render_payload())
    assert "course_system" in data
    assert data["course_system"] is None


def test_course_system_resolves_from_the_sdk_warp_button(monkeypatch):
    import App

    class _FakeWarpButton:
        def GetDestination(self):
            return "Vesuvi6"

    monkeypatch.setattr(App, "SortedRegionMenu_GetWarpButton",
                         lambda: _FakeWarpButton())
    p = StarMapPanel()
    p.open(set_name="Tevron1")
    data = _payload(p.render_payload())
    assert data["course_system"] == "vesuvi"
