"""Resolve the open crew-menu officer to a world-space look-at point (step 5a).

The look-at uses the officer's POSED (skinned) centre, not get_instance_bounds:
officers sit at an identity instance transform with their station offset baked
into the bone palette, so the static-AABB bounds collapse every officer to ~the
model origin (the bug that made all crew zoom to the same spot)."""
import engine.host_loop as hl
from engine.host_loop import _active_zoom_officer_world


class _FakePanel:
    def __init__(self, label):
        self._label = label
    def open_menu_label(self):
        return self._label


class _FakeOfficer:
    def __init__(self, iid):
        self._render_instance = iid


class _FakeRenderer:
    def __init__(self, center):
        self._center = center
    def get_instance_head_center(self, iid):
        return self._center


def test_resolves_open_menu_officer_to_skinned_centre(monkeypatch):
    monkeypatch.setattr(
        "engine.ui.crew_menu_hotkeys.resolve_character",
        lambda label: _FakeOfficer(42) if label == "Tactical" else None)
    r = _FakeRenderer((1.0, 2.0, 3.0))
    assert _active_zoom_officer_world(_FakePanel("Tactical"), r) == (1.0, 2.0, 3.0)


def test_none_when_no_menu_open():
    assert _active_zoom_officer_world(_FakePanel(None), _FakeRenderer(None)) is None


def test_none_when_label_resolves_to_no_officer(monkeypatch):
    monkeypatch.setattr("engine.ui.crew_menu_hotkeys.resolve_character",
                        lambda label: None)
    assert _active_zoom_officer_world(_FakePanel("Tactical"),
                                      _FakeRenderer((1, 2, 3))) is None


def test_none_when_officer_has_no_instance(monkeypatch):
    monkeypatch.setattr("engine.ui.crew_menu_hotkeys.resolve_character",
                        lambda label: _FakeOfficer(None))
    assert _active_zoom_officer_world(_FakePanel("Tactical"),
                                      _FakeRenderer((1, 2, 3))) is None


def test_none_when_skinned_centre_unavailable(monkeypatch):
    monkeypatch.setattr("engine.ui.crew_menu_hotkeys.resolve_character",
                        lambda label: _FakeOfficer(7))
    assert _active_zoom_officer_world(_FakePanel("Tactical"),
                                      _FakeRenderer(None)) is None


def test_none_when_panel_missing():
    assert _active_zoom_officer_world(None, _FakeRenderer((1, 2, 3))) is None
