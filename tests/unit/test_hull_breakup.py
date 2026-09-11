"""after_carve: the one place a severing carve becomes chunks."""
import pytest

from engine import host_io
from engine.appc.math import TGPoint3, TGMatrix3


class _Sub:
    def __init__(self, pos, name):
        self._pos = pos; self.name = name; self.condition = 100.0
    def GetPosition(self): return self._pos
    def GetName(self): return self.name
    def SetCondition(self, v): self.condition = v
    def IsDestroyed(self): return self.condition <= 0.0


class _Ship:
    def __init__(self, radius=3.5, subs=()):
        self._r = radius; self._subs = list(subs)
        self._loc = TGPoint3(0, 0, 0); self._rot = TGMatrix3()
    def GetRadius(self): return self._r
    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot
    def GetVelocity(self): return TGPoint3(0, 0, 0)
    def GetMass(self): return 120.0
    def GetScale(self): return 1.0
    def GetHull(self): return None
    def _iter_subsystems(self): return iter(self._subs)


@pytest.fixture(autouse=True)
def _clean():
    from engine.appc import debris_chunk as dc, damage_geometry as dg
    from engine.appc import hull_breakup
    class _R:
        def set_world_transform(self, *a): pass
        def destroy_instance(self, *a): pass
    dc.clear(_R()); dg.reset(); hull_breakup.reset()
    yield
    dc.clear(_R()); dg.reset(); hull_breakup.reset()


def _component(iid, cells, centroid, lo, hi):
    return {"instance_id": iid, "cells": cells, "centroid": centroid,
            "bounds_min": lo, "bounds_max": hi, "radius_gu": 0.5,
            "main_body_cells": 1000}


def test_a_galor_never_sheds(monkeypatch):
    from engine.appc import hull_breakup
    monkeypatch.setattr(host_io, "hull_split_detached",
                        lambda iid, m: [_component(9, 500, (1, 0, 0), (0.5, -.5, -.5), (1.5, .5, .5))])
    ship = _Ship(radius=2.38)                     # Galor: below the gate
    assert hull_breakup.after_carve(ship, 11) == []


def test_a_severed_component_becomes_a_chunk(monkeypatch):
    from engine.appc import hull_breakup, debris_chunk as dc
    monkeypatch.setattr(host_io, "hull_split_detached",
                        lambda iid, m: [_component(9, 500, (1, 0, 0), (0.5, -.5, -.5), (1.5, .5, .5))])
    ship = _Ship(radius=3.5)                      # Galaxy: above the gate
    chunks = hull_breakup.after_carve(ship, 11)
    assert len(chunks) == 1 and chunks[0].iid == 9
    assert chunks[0].GetMass() == pytest.approx(120.0 * 500 / 1500)
    assert chunks[0] in dc.live()


def test_sub_floor_component_bursts_instead_of_spawning(monkeypatch):
    from engine.appc import hull_breakup, debris_chunk as dc
    monkeypatch.setattr(host_io, "hull_split_detached",
                        lambda iid, m: [_component(None, 3, (1, 0, 0), (0.9, -.1, -.1), (1.1, .1, .1))])
    bursts = []
    monkeypatch.setattr(hull_breakup, "_burst", lambda ship, iid, c: bursts.append(c))
    assert hull_breakup.after_carve(_Ship(radius=3.5), 11) == []
    assert bursts == [(1, 0, 0)]
    assert dc.live() == []


def test_subsystem_inside_the_component_is_destroyed_outside_untouched(monkeypatch):
    from engine.appc import hull_breakup
    inside = _Sub(TGPoint3(1.0, 0.0, 0.0), "Port Nacelle")
    outside = _Sub(TGPoint3(-1.0, 0.0, 0.0), "Bridge")
    ship = _Ship(radius=3.5, subs=[inside, outside])
    monkeypatch.setattr(host_io, "hull_split_detached",
                        lambda iid, m: [_component(9, 500, (1, 0, 0), (0.5, -.5, -.5), (1.5, .5, .5))])
    hull_breakup.after_carve(ship, 11)
    assert inside.IsDestroyed()
    assert not outside.IsDestroyed()


def test_nothing_severed_is_a_noop(monkeypatch):
    from engine.appc import hull_breakup, debris_chunk as dc
    monkeypatch.setattr(host_io, "hull_split_detached", lambda iid, m: [])
    assert hull_breakup.after_carve(_Ship(radius=3.5), 11) == []
    assert dc.live() == []


def test_a_second_carve_inside_the_window_is_deferred_then_drained(monkeypatch):
    from engine.appc import hull_breakup, debris_chunk as dc
    calls = []
    monkeypatch.setattr(host_io, "hull_split_detached",
                        lambda iid, m: calls.append(iid) or [])
    ship = _Ship(radius=3.5)
    hull_breakup.after_carve(ship, 11, now=100.0)
    hull_breakup.after_carve(ship, 11, now=100.1)      # inside the window
    assert calls == [11]                               # only the first ran
    hull_breakup.drain(now=100.3)
    assert calls == [11]                               # still inside
    hull_breakup.drain(now=100.6)
    assert calls == [11, 11]                           # drained exactly once
    hull_breakup.drain(now=100.7)
    assert calls == [11, 11]                           # nothing left pending
