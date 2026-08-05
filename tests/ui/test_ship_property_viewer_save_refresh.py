"""SPV Save wires a live emitter refresh: on a successful Save, the panel
walks the current subsystems (same skip rule as build_descriptors) and hands
the caller-supplied `on_saved(ship, specs_by_sub_id)` callback the effective
(staged-or-saved-or-baked) emitter list per subsystem, keyed by id(sub). The
callback is best-effort — it must never break Save/persistence.

Fixture mirrors test_ship_property_viewer_pipette.py's `build_descriptors`
monkeypatch pattern, plus a fake ship that satisfies `_iter_subsystems`
(via `_iter_damage_subsystems`'s `_DAMAGE_SOURCE_GETTERS` probe) so the
save handler's own re-walk lines up 1:1 with the two fake descriptors.
"""
import json

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
    def __init__(self):
        self._pos = (0.0, 0.0, 0.0)

    def GetPosition(self):
        return self._pos

    def GetProperty(self):
        return None

    def GetNumChildSubsystems(self):
        return 0


class _FakeShip:
    """Exposes exactly two of _DAMAGE_SOURCE_GETTERS so _iter_subsystems
    yields two subsystems, lining up 1:1 with _FAKE_DESCRIPTORS."""

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
def spv_panel_factory(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod

    monkeypatch.setattr(
        mod, "build_descriptors",
        lambda ship: [dict(d, emitters=[dict(e) for e in d["emitters"]])
                      for d in _FAKE_DESCRIPTORS])
    monkeypatch.setattr(mod, "resolve_override_target", lambda ship: _Target())
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship", lambda ship: "galaxy")

    def _make(on_saved=None):
        ship = _FakeShip()
        return ShipPropertyViewerPanel(
            ship_getter=lambda: ship, on_saved=on_saved)

    return _make


def test_save_invokes_on_saved_with_effective_specs(spv_panel_factory):
    calls = []
    p = spv_panel_factory(on_saved=lambda ship, specs: calls.append((ship, specs)))
    p.open()
    p.dispatch_event('add_emitter:{"i":0,"kind":"point"}')
    p.dispatch_event("save")
    assert len(calls) == 1
    ship, specs = calls[0]
    assert isinstance(ship, _FakeShip)
    # specs is keyed by id(sub); at least one sub maps to a non-empty list
    assert any(v for v in specs.values())
    # strengthen: the edit targeted descriptor i=0 ("Center Impulse"), which
    # walks _iter_subsystems(ship) 1:1 (GetHull first, GetSensorSubsystem
    # second) to di=0 -> ship._hull. A di off-by-one that mapped the edit
    # onto the wrong subsystem would slip past the loose `any(...)` check
    # above but not this: the EDITED sub must carry the new emitter, and the
    # UN-edited sub must not.
    assert id(ship._hull) in specs
    assert len(specs[id(ship._hull)]) == 1
    assert specs[id(ship._hull)][0]["kind"] == "point"
    assert not specs.get(id(ship._sensors))


def test_save_without_callback_does_not_crash(spv_panel_factory):
    p = spv_panel_factory(on_saved=None)
    p.open()
    p.dispatch_event('set_radius:{"i":0,"value":3.0}')
    p.dispatch_event("save")   # must not raise


def test_on_saved_exception_does_not_break_save(spv_panel_factory):
    def boom(ship, specs):
        raise RuntimeError("refresh failed")

    p = spv_panel_factory(on_saved=boom)
    p.open()
    p.dispatch_event('add_emitter:{"i":0,"kind":"point"}')
    p.dispatch_event("save")
    assert not p._pending_emitter   # pending still cleared -> save completed
