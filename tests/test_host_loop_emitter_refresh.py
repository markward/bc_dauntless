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
    sub, is_impulse, is_warp, phase, spec = entries[0]
    assert sub is subA
    assert spec["position"] == (1.0, 2.0, 3.0)


def test_build_cache_default_reads_property(fake_ship_two_subs):
    from engine import host_loop
    ship, subA, subB = fake_ship_two_subs
    # specs_of=None reproduces the property-read path unchanged: the fixture
    # bakes a real point emitter (via SubsystemProperty.SetLightEmitter*) on
    # each sub, so a regression to "always return []" must fail this test.
    default_entries = host_loop._build_ship_emitter_cache(ship)
    assert isinstance(default_entries, list)
    assert len(default_entries) > 0
    # every entry's sub is one of the two, and specs come from baked_emitters
    for sub, _imp, _warp, _ph, _spec in default_entries:
        assert sub in (subA, subB)
    # the baked positions round-trip through light_emitters.baked_emitters
    # (subA's emitter sits at the origin, subB's at (5, 0, 0)) — confirms
    # the default path actually reads sub.GetProperty(), not a placeholder.
    by_sub = {}
    for sub, _imp, _warp, _ph, spec in default_entries:
        by_sub.setdefault(sub, []).append(spec)
    assert by_sub[subA][0]["kind"] == "point"
    assert by_sub[subA][0]["position"] == (0.0, 0.0, 0.0)
    assert by_sub[subB][0]["kind"] == "point"
    assert by_sub[subB][0]["position"] == (5.0, 0.0, 0.0)
    # and it agrees with reading baked_emitters directly off each property
    assert by_sub[subA][0] == light_emitters.baked_emitters(subA.GetProperty())[0]
    assert by_sub[subB][0] == light_emitters.baked_emitters(subB.GetProperty())[0]


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


def test_refresh_ship_emitters_success_rebuilds_iid_cache(fake_ship_two_subs):
    """A live instance + a supplied spec map: `session.ship_emitters[iid]`
    gets rebuilt via the real `_build_ship_emitter_cache(ship, specs_of=...)`
    line, reflecting the new spec rather than the stale one it started with."""
    from engine import host_loop
    ship, subA, subB = fake_ship_two_subs

    class Sess:
        pass

    iid = 42
    sess = Sess()
    sess.ship_instances = {ship: iid}
    sess.ship_emitters = {iid: "stale-placeholder"}

    new_spec = {"kind": "point", "position": (9.0, 8.0, 7.0),
                "axis": (0.0, -1.0, 0.0), "length": 0.0, "radius": 1.0,
                "radius_y": 1.0, "color": (0.0, 1.0, 0.0), "intensity": 3.0}
    specs_by_sub_id = {id(subA): [new_spec]}

    host_loop.refresh_ship_emitters(sess, ship, specs_by_sub_id)

    assert iid in sess.ship_emitters
    rebuilt = sess.ship_emitters[iid]
    assert rebuilt != "stale-placeholder"
    assert isinstance(rebuilt, list)
    assert len(rebuilt) == 1
    sub, _imp, _warp, _ph, spec = rebuilt[0]
    assert sub is subA
    assert spec["position"] == (9.0, 8.0, 7.0)


def test_refresh_ship_emitters_swallows_build_cache_exception(fake_ship_two_subs, monkeypatch):
    """If `_build_ship_emitter_cache` blows up mid-rebuild, the best-effort
    refresh must swallow it (dev_mode.log_swallowed) rather than propagate,
    per the docstring's "never raises" contract."""
    from engine import host_loop
    ship, subA, subB = fake_ship_two_subs

    class Sess:
        pass

    iid = 7
    sess = Sess()
    sess.ship_instances = {ship: iid}
    sess.ship_emitters = {iid: "unchanged"}

    def _boom(*a, **kw):
        raise RuntimeError("emitter cache rebuild failed")

    monkeypatch.setattr(host_loop, "_build_ship_emitter_cache", _boom)

    # must not raise
    host_loop.refresh_ship_emitters(sess, ship, {})

    assert sess.ship_emitters[iid] == "unchanged"
