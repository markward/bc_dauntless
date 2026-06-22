"""SettingCoursePanel — two-level system/warp-point menu.

Clicking a warp point SETS THE COURSE (hands the destination module to the
host) and closes the popup; the actual warp is engaged from the SDK Helm
"Warp" button. The popup never warps directly.
"""
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
    assert active["available"] is True  # has a destination module


def test_empty_system_offers_itself_with_a_note():
    # Riha is a single-region system with no catalog warp points: the right
    # column shows the system itself as the set-course target, plus a note.
    # Riha HAS a module (Systems.Riha.Riha1) so it is available.
    p = SettingCoursePanel()
    p.open(course_menu=_live_menu())
    p.dispatch_event("select-system:riha")
    data = _payload(p.render_payload())
    assert data["warp_note"]  # non-empty explanation
    assert len(data["warp_points"]) == 1
    row = data["warp_points"][0]
    assert row["id"] == "riha"
    assert row["available"] is True


def test_unavailable_empty_system_marks_row_and_blocks_course():
    # Tau Ceti / Deep Space are galaxy backdrops with no set module: the
    # self-row is shown but is NOT available, and setting course is a no-op.
    p = SettingCoursePanel()
    p.open(course_menu=_live_menu())
    p.dispatch_event("select-system:tauceti")
    data = _payload(p.render_payload())
    row = data["warp_points"][0]
    assert row["id"] == "tauceti"
    assert row["available"] is False
    assert data["warp_note"]
    # Attempting to set course on it is a no-op (popup stays open).
    assert p.dispatch_event("set-course:tauceti") is False
    assert p.is_open() is True


def test_populated_system_has_no_note():
    p = SettingCoursePanel()
    p.open(course_menu=_live_menu())
    p.dispatch_event("select-system:vesuvi")
    data = _payload(p.render_payload())
    assert data["warp_note"] is None
    assert len(data["warp_points"]) >= 2


def test_set_course_hands_module_to_host_and_closes():
    from engine.appc import sector_model as sm
    expected = sm.warp_points_for("vesuvi")[0]["module"]
    fired = {}
    p = SettingCoursePanel(on_course_set=lambda m: fired.setdefault("m", m))
    p.open(course_menu=_live_menu())
    p.dispatch_event("select-system:vesuvi")
    data = _payload(p.render_payload())
    wp_id = data["warp_points"][0]["id"]
    assert p.dispatch_event("set-course:" + wp_id) is True
    assert fired["m"] == expected
    assert fired["m"] == "Systems.Vesuvi.Vesuvi4"  # first vesuvi warp point module
    assert p.is_open() is False  # popup closes once the course is set


def test_set_course_without_system_is_noop():
    p = SettingCoursePanel(
        on_course_set=lambda m: (_ for _ in ()).throw(AssertionError("should not fire"))
    )
    p.open(course_menu=_live_menu())
    # No system selected yet -> no module resolves.
    assert p.dispatch_event("set-course:vesuvi-dust-cloud") is False
    assert p.is_open() is True


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
