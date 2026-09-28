"""host_io forms the INSTANCE-RELATIVE points the native mesh queries take.

The floating render origin moved the mesh-query bindings (shield_hit,
world_to_body, damage_decal_add, hull_carve_add, hull_carve_capsule,
ray_trace_mesh) to points relative to the instance's translation, so no large
translation is ever inverted in float. Engine code still speaks world points:
the host_io façade subtracts `instance_translation(iid)` (doubles, in Python)
on the way in and adds it back to ray_trace_mesh's hit on the way out.
"""
import types

import pytest

from engine import host_io

T = (1e6 + 0.3, -2.0, 3.5)


class _FakeHost:
    def __init__(self, translation=T):
        self.translation = translation
        self.calls = []

    def instance_translation(self, iid):
        return self.translation

    def _rec(self, name):
        def f(*args):
            self.calls.append((name, args))
            if name == "ray_trace_mesh":
                return ((0.25, 0.5, -0.75), (0.0, 0.0, -1.0), 4.0)
            if name == "world_to_body":
                return ((1.0, 2.0, 3.0), (0.0, 0.0, 1.0))
            return None
        return f

    def __getattr__(self, name):
        return self._rec(name)


@pytest.fixture
def fake(monkeypatch):
    h = _FakeHost()
    monkeypatch.setattr(host_io, "_h", h)
    return h


def _rel(p):
    return (p[0] - T[0], p[1] - T[1], p[2] - T[2])


def test_shield_hit_sends_an_instance_relative_point(fake):
    host_io.shield_hit(7, (T[0] + 1.0, T[1], T[2]), (1, 1, 1, 1), 0.5, 0.2)
    assert fake.calls == [("shield_hit",
                           (7, _rel((T[0] + 1.0, T[1], T[2])), (1, 1, 1, 1), 0.5, 0.2))]
    assert fake.calls[0][1][1] == pytest.approx((1.0, 0.0, 0.0), abs=1e-9)


def test_world_to_body_sends_an_instance_relative_point(fake):
    out = host_io.world_to_body(7, (T[0] + 0.004, 0.0, 0.0), (1.0, 0.0, 0.0))
    (name, args), = fake.calls
    assert name == "world_to_body"
    assert args[1] == pytest.approx((0.004, 2.0, -3.5), abs=1e-9)
    assert args[2] == (1.0, 0.0, 0.0)          # directions are not shifted
    assert out == ((1.0, 2.0, 3.0), (0.0, 0.0, 1.0))


def test_damage_decal_add_sends_an_instance_relative_point(fake):
    host_io.damage_decal_add(7, T, (0.0, 1.0, 0.0), 0.1, 0.5, 1, 2.0)
    (name, args), = fake.calls
    assert name == "damage_decal_add"
    assert args[1] == pytest.approx((0.0, 0.0, 0.0), abs=1e-9)
    assert args[2] == (0.0, 1.0, 0.0)


def test_hull_carve_add_sends_an_instance_relative_point(fake):
    host_io.hull_carve_add(7, (T[0], T[1] + 1.0, T[2]), (0.0, 1.0, 0.0),
                           0.3, 1.0, 2.0)
    (name, args), = fake.calls
    assert name == "hull_carve_add"
    assert args[1] == pytest.approx((0.0, 1.0, 0.0), abs=1e-9)


def test_hull_carve_capsule_sends_instance_relative_endpoints(fake):
    host_io.hull_carve_capsule(7, T, (T[0] + 2.0, T[1], T[2]), 0.6)
    (name, args), = fake.calls
    assert name == "hull_carve_capsule"
    assert args[1] == pytest.approx((0.0, 0.0, 0.0), abs=1e-9)
    assert args[2] == pytest.approx((2.0, 0.0, 0.0), abs=1e-9)


def test_ray_trace_mesh_is_relative_in_and_world_out(fake):
    hit = host_io.ray_trace_mesh(7, (T[0], T[1], T[2] - 10.0), (0.0, 0.0, 1.0), 20.0)
    (name, args), = fake.calls
    assert name == "ray_trace_mesh"
    assert args[1] == pytest.approx((0.0, 0.0, -10.0), abs=1e-9)
    assert args[2] == (0.0, 0.0, 1.0)
    point, normal, t = hit
    assert point == (T[0] + 0.25, T[1] + 0.5, T[2] - 0.75)
    assert normal == (0.0, 0.0, -1.0)
    assert t == 4.0


def test_a_stale_instance_drops_the_point_queries(monkeypatch):
    h = _FakeHost(translation=None)
    monkeypatch.setattr(host_io, "_h", h)
    host_io.shield_hit(7, (1.0, 2.0, 3.0))
    host_io.damage_decal_add(7, (1.0, 2.0, 3.0), (0.0, 0.0, 1.0), 0.1, 0.5, 1, 2.0)
    host_io.hull_carve_add(7, (1.0, 2.0, 3.0), (0.0, 0.0, 1.0), 0.3, 1.0, 2.0)
    host_io.hull_carve_capsule(7, (1.0, 2.0, 3.0), (2.0, 2.0, 3.0), 0.6)
    assert host_io.world_to_body(7, (1.0, 2.0, 3.0), (0.0, 0.0, 1.0)) is None
    assert h.calls == []


def test_ray_trace_mesh_on_a_stale_instance_still_reaches_the_binding(monkeypatch):
    # The binding RAISES on an invalid id; the façade must not turn that into
    # a silent miss.
    h = _FakeHost(translation=None)
    monkeypatch.setattr(host_io, "_h", h)
    host_io.ray_trace_mesh(7, (1.0, 2.0, 3.0), (0.0, 0.0, 1.0), 5.0)
    assert h.calls == [("ray_trace_mesh", (7, (1.0, 2.0, 3.0), (0.0, 0.0, 1.0), 5.0))]


def test_instance_translation_is_a_required_binding():
    assert "instance_translation" in host_io._REQUIRED_BINDINGS


# ── Carried from Task 5's review ────────────────────────────────────────────

class _CountingHost(_FakeHost):
    def __init__(self, translations):
        super().__init__()
        self._seq = list(translations)
        self.translation_reads = 0

    def instance_translation(self, iid):
        self.translation_reads += 1
        return self._seq.pop(0) if self._seq else None


def test_hull_carve_capsule_reads_the_translation_once(monkeypatch):
    # Both endpoints are relative to ONE translation. A second read could see
    # a different (or stale -> None) answer mid-call.
    h = _CountingHost([T, None])
    monkeypatch.setattr(host_io, "_h", h)
    host_io.hull_carve_capsule(7, T, (T[0] + 2.0, T[1], T[2]), 0.6)
    assert h.translation_reads == 1
    (name, args), = h.calls
    assert args[2] == pytest.approx((2.0, 0.0, 0.0), abs=1e-9)

