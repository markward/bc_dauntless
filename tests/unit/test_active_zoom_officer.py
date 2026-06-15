"""Resolve the open crew-menu officer to a world-space look-at point (step 5a)."""
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
    def __init__(self, bounds):
        self._bounds = bounds
    def get_instance_bounds(self, iid):
        return self._bounds


def test_resolves_open_menu_officer_to_world_centre(monkeypatch):
    monkeypatch.setattr(
        "engine.ui.crew_menu_hotkeys.resolve_character",
        lambda label: _FakeOfficer(42) if label == "Tactical" else None)
    r = _FakeRenderer((1.0, 2.0, 3.0, 9.0))
    assert _active_zoom_officer_world(_FakePanel("Tactical"), r) == (1.0, 2.0, 3.0)


def test_none_when_no_menu_open():
    assert _active_zoom_officer_world(_FakePanel(None), _FakeRenderer(None)) is None


def test_none_when_label_resolves_to_no_officer(monkeypatch):
    monkeypatch.setattr("engine.ui.crew_menu_hotkeys.resolve_character",
                        lambda label: None)
    assert _active_zoom_officer_world(_FakePanel("Tactical"),
                                      _FakeRenderer((1, 2, 3, 4))) is None


def test_none_when_officer_has_no_instance(monkeypatch):
    monkeypatch.setattr("engine.ui.crew_menu_hotkeys.resolve_character",
                        lambda label: _FakeOfficer(None))
    assert _active_zoom_officer_world(_FakePanel("Tactical"),
                                      _FakeRenderer((1, 2, 3, 4))) is None


def test_none_when_bounds_unavailable(monkeypatch):
    monkeypatch.setattr("engine.ui.crew_menu_hotkeys.resolve_character",
                        lambda label: _FakeOfficer(7))
    assert _active_zoom_officer_world(_FakePanel("Tactical"),
                                      _FakeRenderer(None)) is None


def test_none_when_panel_missing():
    assert _active_zoom_officer_world(None, _FakeRenderer((1, 2, 3, 4))) is None
