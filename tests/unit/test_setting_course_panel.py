"""SettingCoursePanel — two-level system/warp-point menu."""
import json

from engine.ui.setting_course_panel import SettingCoursePanel


class _FakeMenu:
    """Stand-in for an STMenu/SortedRegionMenu node."""
    def __init__(self, label, children=None):
        self._label = label
        self._children = children or []
    def GetLabel(self):
        return self._label


def _payload(js):
    assert js.startswith("setSettingCoursePanel(") and js.endswith(");")
    return json.loads(js[len("setSettingCoursePanel("):-2])


def _live_menu():
    # Vesuvi active with one active warp point. The live SDK menu labels its
    # warp points via SetClass_MakeDisplayName (Systems.TGL), so the active
    # label matches the baked catalog: "Vesuvi4" -> "Vesuvi Dust Cloud".
    return _FakeMenu("Set Course", [
        _FakeMenu("Vesuvi", [_FakeMenu("Vesuvi Dust Cloud")]),
    ])


def test_lists_all_systems_with_active_flag():
    p = SettingCoursePanel()
    p.open(course_menu=_live_menu())
    data = _payload(p.render_payload())
    ids = [s["id"] for s in data["systems"]]
    assert "vesuvi" in ids
    assert len(ids) >= 25
    assert "multi1" not in ids
    vesuvi = next(s for s in data["systems"] if s["id"] == "vesuvi")
    assert vesuvi["active"] is True
    other = next(s for s in data["systems"] if s["id"] != "vesuvi")
    assert other["active"] is False


def test_select_system_reveals_warp_points_with_active_overlay():
    p = SettingCoursePanel()
    p.open(course_menu=_live_menu())
    p.render_payload()
    assert p.dispatch_event("select-system:vesuvi") is True
    data = _payload(p.render_payload())
    assert data["selected_system"] == "vesuvi"
    labels = [w["label"] for w in data["warp_points"]]
    assert "Vesuvi Dust Cloud" in labels
    active = next(w for w in data["warp_points"] if w["label"] == "Vesuvi Dust Cloud")
    assert active["active"] is True  # in the live menu


def test_select_warp_records_ui_only_selection():
    p = SettingCoursePanel()
    p.open(course_menu=_live_menu())
    p.dispatch_event("select-system:vesuvi")
    wp_id = _payload_first_warp_id(p)
    assert p.dispatch_event("select-warp:" + wp_id) is True
    data = _payload(p.render_payload())
    sel = next(w for w in data["warp_points"] if w["id"] == wp_id)
    assert sel["selected"] is True


def _payload_first_warp_id(p):
    p2 = _payload(p.render_payload())
    return p2["warp_points"][0]["id"]


def test_open_resets_selection():
    p = SettingCoursePanel()
    p.open(course_menu=_live_menu())
    p.dispatch_event("select-system:vesuvi")
    p.open(course_menu=_live_menu())
    data = _payload(p.render_payload())
    assert data["selected_system"] is None


def test_unknown_action_returns_false():
    p = SettingCoursePanel()
    assert p.dispatch_event("frobnicate") is False
