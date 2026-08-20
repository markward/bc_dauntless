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


def test_set_course_calls_back_with_the_module_and_stays_open():
    seen = []
    p = StarMapPanel(on_course_set=seen.append)
    p.open(set_name="Vesuvi6")
    p.dispatch_event("select-system:vesuvi")
    data = _payload(p.render_payload())
    wp = next(w for w in data["warp_points"] if w["available"])
    assert p.dispatch_event("set-course:" + wp["id"]) is True
    assert len(seen) == 1 and seen[0]
    # The modal STAYS OPEN so the player can see the course they plotted and
    # then press Warp; only the target popup is dismissed.
    assert p.is_open() is True
    data = _payload(p.render_payload())
    assert data["targets_open"] is False


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


def test_close_releases_the_sdk_menu_handle():
    """The panel outlives mission swaps; the SortedRegionMenu does not.
    Holding it past close() keeps the outgoing mission's menu (and everything
    it owns) alive — the failure shape this project has hit repeatedly."""
    p = StarMapPanel()
    menu = _FakeMenu("Set Course", [_FakeMenu("Vesuvi", [])])
    p.open(set_name="Vesuvi6", course_menu=menu)
    p.close()
    assert p._course_menu is None


def test_payload_carries_nebula_labels():
    """The baked nebula `name` had no consumer: it reached disc["label"] and
    stopped there. The payload must carry them so the JS can render them —
    subordinate to the system labels, but present."""
    p = StarMapPanel()
    p.open(set_name="Vesuvi6")
    data = _payload(p.render_payload())
    assert data["disc_labels"], "no nebula labels in the payload"
    assert any("Nebula" in d["label"] or "Veil" in d["label"]
               for d in data["disc_labels"])
    assert set(data["disc_labels"][0]) == {"label", "x", "y", "visible"}


def test_disc_labels_are_empty_while_the_panel_is_closed():
    """Same rule the system labels follow: a closed panel projects nothing."""
    p = StarMapPanel()
    assert _payload(p.render_payload())["disc_labels"] == []


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


def test_rect_tracks_the_live_cef_view_size():
    """The CEF view tracks the host window's size in points and .cp-modal is
    flex-centred in it, so a fixed rect only coincides with its own chrome at
    1280x720. set_view_size moves labels, picks and the GL scissor together —
    they all read self.rect."""
    from engine.ui.star_map_panel import MAP_RECT, rect_for_view

    p = StarMapPanel()
    assert p.rect == MAP_RECT == (256, 108, 880, 478)

    p.set_view_size(1512, 983)
    assert p.rect == rect_for_view(1512, 983)
    # Centred against the modal chrome, not the pinned 1280x720 numbers.
    # 440 = MODAL_W/2, less the 56px offset that clears the Helm menu.
    assert p.rect[:2] == (round(1512 / 2 - 440 + 56), round(983 / 2 - 252))
    assert p.rect[2:] == (880, 478)


def test_the_map_fills_the_modal_width():
    """The target list used to be a right-hand column, reserved in CSS with a
    hard-coded margin-left duplicating MAP_W. It is a centred popup now, so
    the map spans the whole modal and that duplicate is gone."""
    from engine.ui.star_map_panel import MAP_W, MODAL_W

    assert MAP_W == MODAL_W


def test_rect_origin_is_clamped_for_views_smaller_than_the_modal():
    """A negative origin would be rejected by the GL scissor and would
    mis-offset every pick."""
    p = StarMapPanel()
    p.set_view_size(640, 400)
    assert p.rect[0] >= 0 and p.rect[1] >= 0


def test_picking_follows_the_resized_rect():
    """Picking hit-tests in CEF-view coordinates against self.rect, so a
    click that lands on a star in the resized view must not be judged
    against the old rect."""
    from engine.ui import star_map

    p = StarMapPanel()
    p.set_view_size(1512, 983)
    p.open(set_name="Vesuvi6")
    rx, ry, _w, _h = p.rect
    labels = [l for l in star_map.project_points(p.scene, p.cam, p.rect)
              if l["visible"]]
    assert labels, "no projected systems to pick"
    hit = labels[0]
    assert p.dispatch_event("pick:%f,%f" % (rx + hit["x"], ry + hit["y"])) is True
    assert p._selected_system is not None


# --- the target popup is modal over the map -------------------------------

def test_selecting_a_system_opens_the_target_popup():
    p = StarMapPanel()
    p.open(set_name="Vesuvi6")
    assert _payload(p.render_payload())["targets_open"] is False
    p.dispatch_event("select-system:vesuvi")
    data = _payload(p.render_payload())
    assert data["targets_open"] is True
    assert data["targets_title"]          # the system's display label
    assert data["warp_points"]


def test_back_dismisses_the_popup_without_closing_the_modal():
    """Back and Cancel are different: Back returns to the map, Cancel closes
    Set Course entirely."""
    p = StarMapPanel()
    p.open(set_name="Vesuvi6")
    p.dispatch_event("select-system:vesuvi")
    assert p.dispatch_event("back") is True
    data = _payload(p.render_payload())
    assert data["targets_open"] is False
    assert data["selected_system"] is None
    assert p.is_open() is True            # the modal itself stays up


def test_map_input_is_ignored_while_the_popup_is_open():
    """Modal by decision: with the card over the centre of the map, a click
    or drag near its edge would otherwise be ambiguous."""
    p = StarMapPanel()
    p.open(set_name="Vesuvi6")
    p.dispatch_event("select-system:vesuvi")
    anchor, dist, yaw = p.cam.anchor, p.cam.camera.distance, p.cam.camera.yaw

    assert p.dispatch_event("orbit:0.5,0.2") is False
    assert p.dispatch_event("zoom:-3") is False
    assert p.dispatch_event("pick:520,368") is False

    assert p.cam.anchor == anchor
    assert p.cam.camera.distance == dist
    assert p.cam.camera.yaw == yaw


def test_map_input_resumes_after_back():
    p = StarMapPanel()
    p.open(set_name="Vesuvi6")
    p.dispatch_event("select-system:vesuvi")
    p.dispatch_event("back")
    before = p.cam.camera.yaw
    assert p.dispatch_event("orbit:0.5,0.2") is True
    assert p.cam.camera.yaw != before


def test_set_course_still_works_from_the_popup():
    """The popup gates MAP actions only — choosing a target must still reach
    on_course_set, which is the whole point of the panel."""
    seen = []
    p = StarMapPanel(on_course_set=seen.append)
    p.open(set_name="Vesuvi6")
    p.dispatch_event("select-system:vesuvi")
    wp = next(w for w in _payload(p.render_payload())["warp_points"]
              if w["available"])
    assert p.dispatch_event("set-course:" + wp["id"]) is True
    assert len(seen) == 1
    assert p.is_open() is True          # stays open; Warp closes it


# --- the in-modal Warp button ---------------------------------------------

class _FakeWarpButton:
    def __init__(self, dest=None):
        self._dest = dest
    def GetDestination(self):
        return self._dest
    def SetDestination(self, d):
        self._dest = d


def _with_warp_button(monkeypatch, dest=None):
    """Point App.SortedRegionMenu_GetWarpButton at a stand-in."""
    import App
    btn = _FakeWarpButton(dest)
    monkeypatch.setattr(App, "SortedRegionMenu_GetWarpButton",
                        lambda: btn, raising=False)
    return btn


def test_warp_is_disabled_until_a_course_is_set(monkeypatch):
    _with_warp_button(monkeypatch, dest=None)
    p = StarMapPanel()
    p.open(set_name="Vesuvi6")
    assert _payload(p.render_payload())["warp_enabled"] is False


def test_warp_enables_once_the_warp_button_holds_a_destination(monkeypatch):
    """Read from the SDK warp button, not from a flag this panel sets — so a
    course plotted before the map opened, or from the old Set Course list,
    enables it too."""
    _with_warp_button(monkeypatch, dest="Systems.Vesuvi.Vesuvi4")
    p = StarMapPanel()
    p.open(set_name="Vesuvi6")
    assert _payload(p.render_payload())["warp_enabled"] is True


def test_warp_engages_the_same_hook_as_the_helm_button_and_closes(monkeypatch):
    btn = _with_warp_button(monkeypatch, dest="Systems.Vesuvi.Vesuvi4")
    engaged = []
    p = StarMapPanel(on_warp_engage=engaged.append)
    p.open(set_name="Vesuvi6")

    assert p.dispatch_event("warp") is True
    assert engaged == [btn], "must hand the SDK warp button to the same hook"
    assert p.is_open() is False


def test_warp_without_a_course_is_refused(monkeypatch):
    """The greyed button is a hint, not the guard: dispatch re-checks, so a
    stale payload or a synthetic event cannot warp with no destination."""
    _with_warp_button(monkeypatch, dest=None)
    engaged = []
    p = StarMapPanel(on_warp_engage=engaged.append)
    p.open(set_name="Vesuvi6")

    assert p.dispatch_event("warp") is False
    assert engaged == []
    assert p.is_open() is True


def test_warp_label_falls_back_without_the_tgl(monkeypatch):
    """Headless (or game/ absent) must still render a usable button rather
    than an empty one."""
    p = StarMapPanel()
    p.open(set_name="Vesuvi6")
    assert _payload(p.render_payload())["warp_label"]


def test_setting_a_course_enables_warp_in_the_same_payload(monkeypatch):
    """End to end: pick a target, and the button the player must press next
    is live without reopening anything."""
    btn = _with_warp_button(monkeypatch, dest=None)
    p = StarMapPanel(on_course_set=btn.SetDestination)
    p.open(set_name="Vesuvi6")
    p.dispatch_event("select-system:vesuvi")
    wp = next(w for w in _payload(p.render_payload())["warp_points"]
              if w["available"])
    p.dispatch_event("set-course:" + wp["id"])

    data = _payload(p.render_payload())
    assert data["warp_enabled"] is True
    assert data["targets_open"] is False
    assert p.is_open() is True
