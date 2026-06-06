"""Unit test for _aggregate_planets in the host loop."""
from engine.appc.planet import Planet
from engine.appc.math import TGPoint3
from engine import host_loop


class _FakeSet:
    def __init__(self, objects):
        self._objects = {i: o for i, o in enumerate(objects)}


def _planet_at(x, y, z, radius):
    p = Planet(radius, "")
    p.SetWorldLocation(TGPoint3(x, y, z))
    return p


def test_aggregate_planets_emits_position_and_radius():
    p = _planet_at(10.0, 20.0, 30.0, 45.0)
    out = host_loop._aggregate_planets([_FakeSet([p])])
    assert len(out) == 1
    assert out[0]["position"] == (10.0, 20.0, 30.0)
    assert out[0]["radius"] == 45.0


def test_aggregate_planets_drops_zero_radius():
    p = _planet_at(0.0, 0.0, 0.0, 0.0)
    out = host_loop._aggregate_planets([_FakeSet([p])])
    assert out == []
