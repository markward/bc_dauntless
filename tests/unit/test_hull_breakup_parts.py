"""after_wear: a structure part the wear has cut off becomes a chunk.

host_io.hull_split_parts (native) finds the severed parts, hides each on the
parent and instances its chunk; hull_breakup.after_wear gives each chunk its
body (debris_chunk.spawn, mass by voxel fraction) and destroys the subsystems
inside the part. Throttled like after_carve.
"""
import pytest

from engine import host_io
from engine.appc.math import TGPoint3, TGMatrix3


class _Sub:
    def __init__(self, pos, name):
        self._pos = pos; self.name = name; self.condition = 100.0
        self.set_calls = 0
    def GetPosition(self): return self._pos
    def GetName(self): return self.name
    def SetCondition(self, v):
        self.condition = v; self.set_calls += 1
    def IsDestroyed(self): return self.condition <= 0.0


class _Ship:
    def __init__(self, radius=3.5, subs=()):
        self._r = radius; self._subs = list(subs)
        self._loc = TGPoint3(0, 0, 0); self._rot = TGMatrix3()
        self._articulation_poses = {}
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


def _part(part, chunk_iid, voxels, lo, hi, total=4000):
    c = tuple(0.5 * (a + b) for a, b in zip(lo, hi))
    return {"parts": [part], "instance_id": chunk_iid, "voxels": voxels,
            "total_voxels": total, "centroid": c, "bounds_min": lo,
            "bounds_max": hi, "radius_gu": 0.75}


@pytest.fixture
def spawns(monkeypatch):
    """debris_chunk.spawn replaced by a recorder; returns the call list."""
    from engine.appc import debris_chunk
    calls = []

    def fake_spawn(iid, ship, cells, centroid, radius, parent_mass, total, rng=None):
        calls.append({"iid": iid, "ship": ship, "cells": cells,
                      "centroid": centroid, "radius": radius,
                      "parent_mass": parent_mass, "total": total})
        return ("chunk", iid)
    monkeypatch.setattr(debris_chunk, "spawn", fake_spawn)
    return calls


def test_after_wear_spawns_a_chunk_per_severed_part(monkeypatch, spawns):
    from engine.appc import hull_breakup
    asked = []

    def fake_split(iid):
        asked.append(iid)
        return [_part(1, 21, 600, (1.0, -.5, -.5), (2.0, .5, .5)),
                _part(3, 22, 200, (-2.0, -.5, -.5), (-1.0, .5, .5))]
    monkeypatch.setattr(host_io, "hull_split_parts", fake_split)
    ship = _Ship(radius=3.5)
    out = hull_breakup.after_wear(ship, 11, now=10.0)
    assert asked == [11]
    assert out == [("chunk", 21), ("chunk", 22)]
    assert [c["iid"] for c in spawns] == [21, 22]
    first = spawns[0]
    assert first["ship"] is ship
    assert first["cells"] == 600 and first["total"] == 4000, \
        "mass by voxel fraction: the part's voxels over the hull's"
    assert first["parent_mass"] == pytest.approx(120.0)
    assert first["centroid"] == pytest.approx((1.5, 0.0, 0.0))
    assert first["radius"] == pytest.approx(0.75)


def test_chunk_mass_is_the_parts_voxel_fraction(monkeypatch):
    from engine.appc import hull_breakup
    monkeypatch.setattr(host_io, "hull_split_parts",
                        lambda iid: [_part(1, 21, 1000, (1.0, -.5, -.5), (2.0, .5, .5))])
    (chunk,) = hull_breakup.after_wear(_Ship(radius=3.5), 11, now=10.0)
    assert chunk.iid == 21
    assert chunk.GetMass() == pytest.approx(120.0 * 1000 / 4000)


def test_severed_part_spawns_once_and_kills_its_subsystems(monkeypatch, spawns):
    from engine.appc import hull_breakup
    inside = _Sub(TGPoint3(1.5, 0.0, 0.0), "Port Nacelle")
    outside = _Sub(TGPoint3(-1.5, 0.0, 0.0), "Bridge")
    ship = _Ship(radius=3.5, subs=[inside, outside])
    monkeypatch.setattr(host_io, "hull_split_parts",
                        lambda iid: [_part(1, 21, 600, (1.0, -.5, -.5), (2.0, .5, .5))])
    hull_breakup.after_wear(ship, 11, now=10.0)
    assert inside.condition == 0.0 and inside.set_calls == 1
    assert outside.set_calls == 0
    assert len(spawns) == 1
    # A second check that reports the same part again spawns nothing and
    # kills nothing again.
    assert hull_breakup.after_wear(ship, 11, now=20.0) == []
    assert len(spawns) == 1
    assert inside.set_calls == 1


def test_small_ships_and_rocks_never_sever(monkeypatch, spawns):
    from engine.appc import hull_breakup
    from engine.rocks.rock import RockClass
    asked = []
    monkeypatch.setattr(host_io, "hull_split_parts",
                        lambda iid: asked.append(iid) or
                        [_part(1, 21, 600, (1.0, -.5, -.5), (2.0, .5, .5))])

    class _Rock(RockClass):
        def GetRadius(self): return 3.5      # well above the size gate

    rock = object.__new__(_Rock)
    assert hull_breakup.after_wear(_Ship(radius=0.141), 11, now=10.0) == []   # Shuttle
    assert hull_breakup.after_wear(rock, 12, now=10.0) == []
    assert hull_breakup.after_wear(_Ship(radius=3.5), None, now=10.0) == []
    assert asked == [] and spawns == []


def test_wear_inside_the_throttle_window_is_drained_later(monkeypatch, spawns):
    from engine.appc import hull_breakup
    calls = []
    monkeypatch.setattr(host_io, "hull_split_parts",
                        lambda iid: calls.append(iid) or [])
    ship = _Ship(radius=3.5)
    hull_breakup.after_wear(ship, 11, now=10.0)
    hull_breakup.after_wear(ship, 11, now=10.1)
    hull_breakup.after_wear(ship, 11, now=10.2)
    assert calls == [11], "throttled: one native check per window"
    hull_breakup.drain(now=10.3)
    assert calls == [11]
    hull_breakup.drain(now=10.0 + hull_breakup.kBreakupCheckInterval)
    assert calls == [11, 11], "the deferred check runs once the window elapses"
    hull_breakup.drain(now=20.0)
    assert calls == [11, 11]


def test_a_failed_native_check_spawns_nothing(monkeypatch, spawns):
    from engine.appc import hull_breakup

    def boom(iid):
        raise RuntimeError("stale")
    monkeypatch.setattr(host_io, "hull_split_parts", boom)
    assert hull_breakup.after_wear(_Ship(radius=3.5), 11, now=10.0) == []
    assert spawns == []


def test_a_part_reported_again_destroys_its_new_instance(monkeypatch, spawns):
    """The native side instances a chunk before Python sees the dict: a part
    the Python guard drops must not leave that instance in the scene."""
    from engine import renderer
    from engine.appc import hull_breakup
    destroyed = []
    monkeypatch.setattr(renderer, "destroy_instance", destroyed.append)
    reply = [[_part(1, 21, 600, (1.0, -.5, -.5), (2.0, .5, .5))],
             [_part(1, 31, 600, (1.0, -.5, -.5), (2.0, .5, .5))]]
    monkeypatch.setattr(host_io, "hull_split_parts", lambda iid: reply.pop(0))
    ship = _Ship(radius=3.5)
    hull_breakup.after_wear(ship, 11, now=10.0)
    assert hull_breakup.after_wear(ship, 11, now=20.0) == []
    assert [c["iid"] for c in spawns] == [21]
    assert destroyed == [31]


def test_the_severed_record_does_not_keep_a_ship_alive(monkeypatch):
    import gc
    import weakref
    from engine.appc import debris_chunk, hull_breakup
    monkeypatch.setattr(debris_chunk, "spawn", lambda *a, **k: object())
    monkeypatch.setattr(host_io, "hull_split_parts",
                        lambda iid: [_part(1, 21, 600, (1.0, -.5, -.5), (2.0, .5, .5))])
    ship = _Ship(radius=3.5)
    assert len(hull_breakup.after_wear(ship, 11, now=10.0)) == 1
    ref = weakref.ref(ship)
    del ship
    gc.collect()
    assert ref() is None, "hull_breakup._severed held the ship alive"


def test_an_articulated_ship_at_rest_never_structure_severs(monkeypatch, spawns):
    """A rigged ship at rest has NO node overrides (set_instance_node_transform
    erases identity ones), so the native articulation gate cannot see it --
    yet its parts already leave through part_severance. A structure sever
    there would detach the same nacelle twice (two chunks, two kills)."""
    from engine.appc import articulation, hull_breakup
    asked = []
    monkeypatch.setattr(host_io, "hull_split_parts",
                        lambda iid: asked.append(iid) or
                        [_part(1, 21, 600, (1.0, -.5, -.5), (2.0, .5, .5))])
    ship = _Ship(radius=3.5)
    ship._articulation_leaf = "birdofprey"   # resolvable rig, poses at rest
    assert articulation.parts_for_ship(ship), "fixture: the ship is rigged"
    assert ship._articulation_poses == {}, "fixture: no pose overrides"
    assert hull_breakup.after_wear(ship, 11, now=10.0) == []
    hull_breakup.drain(now=20.0)
    assert asked == [] and spawns == []


def test_an_assembly_leaves_as_one_chunk(monkeypatch, spawns):
    """Ruling 4: the native side reports a cut-off assembly once, with every
    part in it -- one chunk, one body; a later report naming any of its parts
    again is an orphan."""
    from engine import renderer
    from engine.appc import hull_breakup
    destroyed = []
    monkeypatch.setattr(renderer, "destroy_instance", destroyed.append)
    piece = _part(1, 21, 900, (1.0, -.5, -.5), (3.0, .5, .5))
    piece["parts"] = [1, 2]
    again = _part(2, 31, 300, (2.0, -.5, -.5), (3.0, .5, .5))
    reply = [[piece], [again]]
    monkeypatch.setattr(host_io, "hull_split_parts", lambda iid: reply.pop(0))
    ship = _Ship(radius=3.5)
    assert len(hull_breakup.after_wear(ship, 11, now=10.0)) == 1
    assert [c["iid"] for c in spawns] == [21] and spawns[0]["cells"] == 900
    assert hull_breakup.after_wear(ship, 11, now=20.0) == []
    assert destroyed == [31]
