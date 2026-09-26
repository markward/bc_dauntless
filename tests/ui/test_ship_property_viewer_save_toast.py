import pytest

from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel
from tests.ui.test_ship_property_viewer_save_persistence import _FakeShip, _FAKE_DESCRIPTORS


class _OkTarget:
    def write(self, leaf, edits):
        pass
    def describe(self):
        return "mod file: /mods/M/Scripts/ships/Hardpoints/refit.py"


class _FailTarget:
    def write(self, leaf, edits):
        raise PermissionError("read-only")
    def describe(self):
        return "mod file: x"


def _panel(monkeypatch, target):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [dict(d, emitters=[dict(e) for e in d["emitters"]])
                                      for d in _FAKE_DESCRIPTORS])
    monkeypatch.setattr(mod, "resolve_override_target", lambda ship: target)
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship", lambda ship: "refit")
    p = ShipPropertyViewerPanel(ship_getter=lambda: _FakeShip())
    p.open()
    return p


def test_save_toasts_the_destination(monkeypatch):
    p = _panel(monkeypatch, _OkTarget())
    p.dispatch_event('set_radius:{"i":0,"value":3.0}')
    p.dispatch_event("save")
    assert p._current_toast() == "Saved to mod file: /mods/M/Scripts/ships/Hardpoints/refit.py"


def test_failed_save_toasts_the_error_and_keeps_edits(monkeypatch):
    p = _panel(monkeypatch, _FailTarget())
    p.dispatch_event('set_radius:{"i":0,"value":3.0}')
    p.dispatch_event("save")
    assert p._current_toast() == "Save failed: read-only"
    assert p._pending_radius.get(0) == 3.0
