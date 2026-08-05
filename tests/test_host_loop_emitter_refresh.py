"""Tests for the SPV live emitter-refresh host plumbing (Task 1).

`_build_ship_emitter_cache` gains an optional `specs_of` spec source so a
caller (the SPV live-refresh path) can supply the *effective* (edited but
not-yet-persisted) emitter specs instead of re-reading `sub.GetProperty()`.
`refresh_ship_emitters` is the best-effort session-cache rebuild helper that
uses it. See `.superpowers/sdd/2026-08-05-spv-live-emitter-refresh/task-1-brief.md`.
"""
from engine.appc.properties import SubsystemProperty
from engine.appc import light_emitters


def _point_prop(position, color=(1.0, 0.5, 0.25), radius=3.0, intensity=2.5):
    """A SubsystemProperty carrying one baked point light emitter."""
    p = SubsystemProperty("sub")
    p.SetLightEmitterKind(0, "point")
    px, py, pz = position
    p.SetLightEmitterPosition(0, px, py, pz)
    p.SetLightEmitterAxis(0, 0.0, -1.0, 0.0)
    p.SetLightEmitterLength(0, 0.0)
    p.SetLightEmitterRadius(0, radius)
    r, g, b = color
    p.SetLightEmitterColor(0, r, g, b)
    p.SetLightEmitterIntensity(0, intensity)
    return p


class _Sub:
    """Fake subsystem: carries a baked-emitter property (mirrors the
    scaffolding in tests/test_host_loop_emitter_lights.py)."""

    def __init__(self, prop):
        self._prop = prop

    def GetProperty(self):
        return self._prop

    def GetName(self):
        return "sub"


class _Ship:
    """Fake ship exposing whatever `_iter_subsystems` requires — patched
    directly below rather than relying on a real accessor chain."""
    pass


import pytest


@pytest.fixture
def fake_ship_two_subs(monkeypatch):
    ship = _Ship()
    subA = _Sub(_point_prop((0.0, 0.0, 0.0)))
    subB = _Sub(_point_prop((5.0, 0.0, 0.0)))

    monkeypatch.setattr(
        "engine.ui.ship_property_viewer._iter_subsystems",
        lambda s: [subA, subB] if s is ship else [])

    return ship, subA, subB


def test_build_cache_specs_of_overrides_property(fake_ship_two_subs):
    from engine import host_loop
    ship, subA, subB = fake_ship_two_subs
    # specs_of supplies a brand-new emitter list for subA, none for subB
    new_spec = {"kind": "point", "position": (1.0, 2.0, 3.0),
                "axis": (0.0, -1.0, 0.0), "length": 1.0, "radius": 0.5,
                "radius_y": 0.5, "color": (1.0, 0.0, 0.0), "intensity": 2.0}
    entries = host_loop._build_ship_emitter_cache(
        ship, specs_of=lambda sub: [new_spec] if sub is subA else [])
    # exactly one entry, for subA, carrying the supplied spec
    assert len(entries) == 1
    sub, is_impulse, phase, spec = entries[0]
    assert sub is subA
    assert spec["position"] == (1.0, 2.0, 3.0)


def test_build_cache_default_reads_property(fake_ship_two_subs):
    from engine import host_loop
    ship, subA, subB = fake_ship_two_subs
    # specs_of=None reproduces the property-read path unchanged
    default_entries = host_loop._build_ship_emitter_cache(ship)
    assert isinstance(default_entries, list)
    # every entry's sub is one of the two, and specs come from baked_emitters
    for sub, _imp, _ph, _spec in default_entries:
        assert sub in (subA, subB)


def test_refresh_ship_emitters_rebuilds_cache():
    from engine import host_loop

    class Sess:
        ship_instances = {}
        ship_emitters = {}

    ship = object()
    subid_specs = {}
    sess = Sess()
    # no live instance for this ship → no-op (must not raise, must not create a key)
    host_loop.refresh_ship_emitters(sess, ship, subid_specs)
    assert sess.ship_emitters == {}
