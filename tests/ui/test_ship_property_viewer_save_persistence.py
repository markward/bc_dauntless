"""Saved SPV edits must survive close→reopen of the SAME ship.

Bug: the panel's saved-edit overlay (`_saved_*`) is in-memory only and was
wiped on every `open()`/`close()`, while the subsystem property that
`build_descriptors` reads is never updated by Save. So after Save + close,
re-opening rebuilt descriptors from the unchanged (original) property with an
empty overlay → the SPV showed the ORIGINAL hardpoint, not the just-saved edit.

Fix: persist `_saved_*` across open/close, clearing it only when the player
ship IDENTITY changes (a respawn — at which point the file has been applied to
the fresh property and the descriptors already reflect the edits).

Fixture mirrors test_ship_property_viewer_save_refresh.py.
"""
import pytest

from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel

_DEFAULT_LIGHT_REGION = {
    "shape": "Sphere", "position": (0.0, 0.0, 0.0),
    "axis": (0.0, -1.0, 0.0), "radius": (0.25,),
    "extent": (0.0, 2.0), "scale": (0.25, 0.25, 0.25),
    "orientation": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
}

_FAKE_DESCRIPTORS = [
    {
        "name": "Center Impulse", "kind": "subsystem",
        "properties": {"position": (0.0, 1.0, 0.0), "radius": 0.3},
        "world_pos": (0.0, 1.0, 0.0), "parent_index": None,
        "light": False, "light_region": dict(_DEFAULT_LIGHT_REGION),
        "emitters": [],
    },
    {
        "name": "Aft Impulse", "kind": "subsystem",
        "properties": {"position": (2.0, 0.0, 0.0), "radius": 0.5},
        "world_pos": (2.0, 0.0, 0.0), "parent_index": None,
        "light": False, "light_region": dict(_DEFAULT_LIGHT_REGION),
        "emitters": [],
    },
]


class _FakeSubsystem:
    def GetPosition(self):
        return (0.0, 0.0, 0.0)

    def GetProperty(self):
        return None

    def GetNumChildSubsystems(self):
        return 0


class _FakeShip:
    def __init__(self):
        self._hull = _FakeSubsystem()
        self._sensors = _FakeSubsystem()

    def GetHull(self):
        return self._hull

    def GetSensorSubsystem(self):
        return self._sensors


class _Target:
    def write(self, leaf, edits):
        pass


@pytest.fixture
def make_panel(monkeypatch):
    """Build a panel whose ship_getter reads a mutable holder, so a test can
    simulate a respawn by swapping in a new _FakeShip."""
    import engine.ui.ship_property_viewer_panel as mod

    monkeypatch.setattr(
        mod, "build_descriptors",
        lambda ship: [dict(d, emitters=[dict(e) for e in d["emitters"]])
                      for d in _FAKE_DESCRIPTORS])
    monkeypatch.setattr(mod, "resolve_override_target", lambda ship: _Target())
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship", lambda ship: "galaxy")

    holder = {"ship": _FakeShip()}
    panel = ShipPropertyViewerPanel(ship_getter=lambda: holder["ship"])
    return panel, holder


def test_saved_radius_persists_across_close_reopen(make_panel):
    p, _holder = make_panel
    p.open()
    p.dispatch_event('set_radius:{"i":0,"value":3.0}')
    p.dispatch_event("save")
    assert p._saved_radius.get(0) == 3.0
    p.close()
    p.open()   # SAME ship
    # The just-saved edit must still be shown, not the baked 0.3.
    assert p._saved_radius.get(0) == 3.0
    assert p._effective_radius(0, 0.3) == 3.0


def test_saved_emitter_persists_across_close_reopen(make_panel):
    p, _holder = make_panel
    p.open()
    p.dispatch_event('add_emitter:{"i":0,"kind":"point"}')
    p.dispatch_event("save")
    assert len(p._effective_emitters(0)) == 1
    p.close()
    p.open()   # SAME ship
    assert len(p._effective_emitters(0)) == 1
    assert p._effective_emitters(0)[0]["kind"] == "point"


def test_saved_edits_cleared_on_ship_change(make_panel):
    p, holder = make_panel
    p.open()
    p.dispatch_event('set_radius:{"i":0,"value":3.0}')
    p.dispatch_event("save")
    assert p._saved_radius.get(0) == 3.0
    p.close()
    holder["ship"] = _FakeShip()   # respawn: a brand-new ship object
    p.open()
    # After a respawn the file has been applied to the fresh property, so the
    # stale in-memory overlay must be dropped (else it could misapply).
    assert not p._saved_radius
    assert p._effective_radius(0, 0.3) == 0.3
