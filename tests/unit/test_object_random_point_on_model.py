"""ObjectClass.GetRandomPointOnModel + point-valued SetEmitFromObject.

The SDK's death-effect scatter primitive (Effects.py, E1M2 AsteroidExploding):
`pEmitPos = pObject.GetRandomPointOnModel()` must return a real world-space
TGPoint3 (it fell through TGObject.__getattr__ to a _Stub before), and the
particle path must accept that bare point via SetEmitFromObject — previously
it defaulted the emitter to the world origin.
"""
import math

import pytest

from engine.appc import particles as P
from engine.appc import render_instances
from engine.appc.math import TGPoint3
from engine.appc.objects import ObjectClass
from engine.core.ids import _Stub


def _make_object(x=0.0, y=0.0, z=0.0, radius=10.0):
    obj = ObjectClass()
    obj.SetTranslateXYZ(x, y, z)
    obj.SetRadius(radius)
    return obj


def _dist(p, q):
    return math.sqrt((p.x - q.x) ** 2 + (p.y - q.y) ** 2 + (p.z - q.z) ** 2)


@pytest.fixture(autouse=True)
def _clean_registry():
    render_instances.reset()
    yield
    render_instances.reset()


# ── GetRandomPointOnModel ───────────────────────────────────────────────────

def test_returns_real_tgpoint3_not_stub():
    pt = _make_object().GetRandomPointOnModel()
    assert isinstance(pt, TGPoint3)
    assert not isinstance(pt, _Stub)
    assert all(isinstance(v, float) for v in (pt.x, pt.y, pt.z))


def test_registered_instance_samples_surface_points(monkeypatch):
    from engine import renderer
    obj = _make_object(100.0, 200.0, 300.0, radius=5.0)
    render_instances.register(obj, 42)
    surface = [(101.0, 202.0, 303.0), (99.0, 198.0, 297.0)]
    calls = []
    monkeypatch.setattr(renderer, "instance_surface_points",
                        lambda iid: calls.append(iid) or surface)
    pt = obj.GetRandomPointOnModel()
    assert calls == [42]
    assert (pt.x, pt.y, pt.z) in surface


def test_no_instance_falls_back_to_bounding_sphere():
    obj = _make_object(50.0, -20.0, 7.0, radius=12.0)
    center = obj.GetWorldLocation()
    for _ in range(20):
        pt = obj.GetRandomPointOnModel()
        assert _dist(pt, center) == pytest.approx(12.0, abs=1e-6)


def test_repeated_calls_vary():
    obj = _make_object(radius=10.0)
    pts = {(p.x, p.y, p.z)
           for p in (obj.GetRandomPointOnModel() for _ in range(10))}
    assert len(pts) > 1


def test_zero_radius_degrades_to_world_location():
    obj = _make_object(3.0, 4.0, 5.0, radius=0.0)
    pt = obj.GetRandomPointOnModel()
    assert (pt.x, pt.y, pt.z) == (3.0, 4.0, 5.0)


def test_empty_surface_sample_falls_back_to_sphere(monkeypatch):
    from engine import renderer
    obj = _make_object(radius=8.0)
    render_instances.register(obj, 7)
    monkeypatch.setattr(renderer, "instance_surface_points", lambda iid: [])
    pt = obj.GetRandomPointOnModel()
    assert _dist(pt, obj.GetWorldLocation()) == pytest.approx(8.0, abs=1e-6)


def test_registry_reset_clears_entries():
    obj = _make_object()
    render_instances.register(obj, 9)
    assert render_instances.instance_for(obj) == 9
    render_instances.reset()
    assert render_instances.instance_for(obj) is None


def test_reset_sdk_globals_clears_registry():
    import engine.host_loop as host_loop
    obj = _make_object()
    render_instances.register(obj, 11)
    host_loop.reset_sdk_globals()
    assert render_instances.instance_for(obj) is None


# ── point-valued SetEmitFromObject (particles) ──────────────────────────────

def _emitter():
    c = P.AnimTSParticleController()
    c.SetEmitLife(1.0)
    c.SetEmitFrequency(0.05)
    c.SetEffectLifeTime(100.0)
    c.CreateTarget("data/Textures/Effects/ExplosionB.tga")
    c.AddSizeKey(0.0, 1.0)
    c.AddAlphaKey(0.0, 0.5)
    return c


def test_emit_from_point_anchors_emitter_at_world_point():
    P.reset()
    c = _emitter()
    c.SetEmitFromObject(TGPoint3(1.0, 2.0, 3.0))
    P.EffectAction_Create(c).Start()
    P.advance(0.1)

    def resolve(emit_from):  # pragma: no cover - must not be consulted
        raise AssertionError("bare point must not hit resolve_attach")

    d = P.snapshot_descriptors(resolve_attach=resolve)[0]
    assert d["instance_id"] is None
    assert d["emit_pos"] == (1.0, 2.0, 3.0)
    P.reset()


def test_emit_from_tuple_point_also_accepted():
    P.reset()
    c = _emitter()
    c.SetEmitFromObject((4.0, 5.0, 6.0))
    P.EffectAction_Create(c).Start()
    P.advance(0.1)
    d = P.snapshot_descriptors()[0]
    assert d["instance_id"] is None
    assert d["emit_pos"] == (4.0, 5.0, 6.0)
    P.reset()


def test_emit_from_object_still_uses_resolver():
    P.reset()
    c = _emitter()
    ship = _make_object(9.0, 9.0, 9.0)
    c.SetEmitFromObject(ship)
    c.SetEmitPositionAndDirection((0.0, 1.0, 0.0), (0.0, -1.0, 0.0))
    P.EffectAction_Create(c).Start()
    P.advance(0.1)
    d = P.snapshot_descriptors(
        resolve_attach=lambda ef: {"instance_id": (7, 1),
                                   "velocity": (5.0, 0.0, 0.0)})[0]
    assert d["instance_id"] == (7, 1)
    assert d["emit_pos"] == (0.0, 1.0, 0.0)  # body-frame, resolved in the pass
    P.reset()
