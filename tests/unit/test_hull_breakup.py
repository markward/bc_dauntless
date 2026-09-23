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
        self._articulation_deflection = 0.0
    def GetRadius(self): return self._r
    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot
    def GetVelocity(self): return TGPoint3(0, 0, 0)
    def GetMass(self): return 120.0
    def GetScale(self): return 1.0
    def GetHull(self): return None
    def _iter_subsystems(self): return iter(self._subs)
    def GetArticulationDeflection(self): return self._articulation_deflection


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


def test_a_shuttle_never_sheds(monkeypatch):
    """The Shuttle is the ONLY stock hull below the gate since 2026-09-23 (the
    floor moved 2.381 -> 0.6). This used to be a Galor, which now sheds."""
    from engine.appc import hull_breakup
    monkeypatch.setattr(host_io, "hull_split_detached",
                        lambda iid, m: [_component(9, 500, (1, 0, 0), (0.5, -.5, -.5), (1.5, .5, .5))])
    ship = _Ship(radius=0.141)                    # Shuttle: below the gate
    assert hull_breakup.after_carve(ship, 11) == []


def test_a_bird_of_prey_now_sheds(monkeypatch):
    """The ship the floor was lowered FOR. A regression restoring the old 2.381
    would leave every larger hull working while silently un-breaking this one."""
    from engine.appc import hull_breakup
    monkeypatch.setattr(host_io, "hull_split_detached",
                        lambda iid, m: [_component(9, 500, (1, 0, 0), (0.5, -.5, -.5), (1.5, .5, .5))])
    ship = _Ship(radius=1.335)                    # BirdOfPrey: above the gate
    assert len(hull_breakup.after_carve(ship, 11)) == 1


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


def test_subsystem_kill_uses_the_REST_mount_even_mid_travel(monkeypatch):
    """Mirrors part_severance's REST-mount pin for the other destroy path.

    `_destroy_subsystems_inside` compares each subsystem's body-frame
    `GetPosition()` against a carved component's REST-pose bounds. It never
    calls `GetArticulationDeflection` at all -- there is nothing to correct
    for, because the sim never articulates: the voxel field and the .dhv SDF
    are both baked from the NIF in rest pose. So a ship reporting non-zero
    deflection must attribute exactly as it would at rest.

    This has to actually DISCRIMINATE the two behaviours, not just carry a
    deflection value nothing reads. The `_Ship` double is given a resolvable
    rig (`_articulation_leaf = "birdofprey"`, mirroring
    test_part_severance.py) so `articulation.part_transform_point` would be
    live -- not the identity no-op it is for a ship with no leaf -- if a
    regression routed the mount through it.

    The Star Cannon's authored REST mount, (1.008, 0.450, -0.670), rotates
    under `left wing01`'s full-deflection (1.0) hinge to
    ~(1.269, 0.450, 0.141) -- computed once via
    `articulation.rotation_for` / `_rotate_about` and pinned here as a
    literal, not re-derived by the test. `bounds` below contains the REST
    point but excludes the rotated one on X alone (1.1 < 1.269):

        correct (raw REST mount)   -> inside bounds  -> destroyed
        regressed (transformed)    -> outside bounds -> untouched

    Companion to test_part_severance.py's
    test_subsystem_kill_uses_the_REST_mount_even_mid_travel -- see spec
    §4.1 symptom 2 (withdrawn).
    """
    from engine.appc import hull_breakup
    cannon = _Sub(TGPoint3(1.008, 0.450, -0.670), "Star Cannon")
    ship = _Ship(radius=3.5, subs=[cannon])
    ship._articulation_leaf = "birdofprey"   # pre-cached: resolvable rig
    ship._articulation_deflection = 1.0      # full travel
    lo, hi = (0.9, 0.4, -0.8), (1.1, 0.5, -0.5)
    monkeypatch.setattr(host_io, "hull_split_detached",
                        lambda iid, m: [_component(9, 500, (1, 0, 0), lo, hi)])
    hull_breakup.after_carve(ship, 11)
    assert cannon.IsDestroyed(), (
        "the cannon authored inside these REST bounds must die; routing the "
        "mount through part_transform_point would move it to ~x=1.269, "
        "outside hi.x=1.1, and this assertion would start failing")


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


def test_a_spawn_failure_destroys_the_instance_the_native_side_already_made(monkeypatch):
    # hull_split_detached has ALREADY created the renderer instance by the
    # time Python spawns the body. If spawn raises, the instance must be
    # destroyed, not left orphaned (invisible to the cap, the clear, and
    # the collision system) for the rest of the mission.
    from engine import renderer
    from engine.appc import hull_breakup, debris_chunk as dc
    monkeypatch.setattr(host_io, "hull_split_detached",
                        lambda iid, m: [_component(9, 500, (1, 0, 0), (0.5, -.5, -.5), (1.5, .5, .5))])
    def _boom(*a, **k):
        raise RuntimeError("spawn failed")
    monkeypatch.setattr(dc, "spawn", _boom)
    destroyed = []
    monkeypatch.setattr(renderer, "destroy_instance", lambda iid: destroyed.append(iid))
    assert hull_breakup.after_carve(_Ship(radius=3.5), 11) == []
    assert destroyed == [9]
    assert dc.live() == []
