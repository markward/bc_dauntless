"""Visible-damage volumes are emitted under a per-frame time budget.

A dying ship's SDK cascade can land 2-6 AddDamage volumes in one frame. When
each was a voxel carve (a whole reach-box brush pass, ~5.7 ms in Debug for a
Sovereign) that was 34 ms in one frame (perf-register P-4, SIG-044); each is
now an Internal record plus a mesh probe, but the budget still bounds the
frame. advance() emits queued volumes in order until the budget is spent --
always at least one, so the queue drains -- and leaves the rest for the next
frames. Only the visible hole waits: the gameplay half of AddDamage is
applied when it is called.
"""
import pytest

from engine import host_io
from engine.appc import visible_damage
from engine.appc.math import TGMatrix3, TGPoint3


class _Ship:
    def __init__(self):
        self._loc = TGPoint3(0.0, 0.0, 0.0)
        self._rot = TGMatrix3()

    def GetWorldLocation(self):  return self._loc
    def GetWorldRotation(self):  return self._rot
    def GetRadius(self):         return 3.0


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


@pytest.fixture
def rig(monkeypatch):
    clock = _Clock()
    carves = []
    cost = {"ms": 5.0}

    def spy(iid, point, normal, radius, wear, kind, rest_frame=False):
        carves.append(point)
        clock.t += cost["ms"] / 1000.0

    from engine.appc import hull_breakup
    monkeypatch.setattr(host_io, "hull_damage_add", spy)
    monkeypatch.setattr(host_io, "ray_trace_mesh", lambda *a, **k: None)
    monkeypatch.setattr(hull_breakup, "after_wear", lambda *a, **k: [])
    visible_damage.reset()
    yield clock, carves, cost
    visible_damage.reset()


def _queue(ship, n):
    for i in range(n):
        visible_damage.queue_body_volume(ship, float(i), 0.0, 0.0, 1.0)


def test_slow_carves_drain_one_per_frame_in_order(rig):
    clock, carves, cost = rig
    ship = _Ship()
    _queue(ship, 3)
    xs = []
    for _ in range(3):
        visible_damage.advance(0.016, {ship: 1}, budget_ms=3.0, clock=clock)
        xs.append(len(carves))
    assert xs == [1, 2, 3], "at least one per frame, never more past the budget"
    assert [round(p[0]) for p in carves] == [0, 1, 2], "queue order kept"


def test_cheap_carves_all_fit_in_one_frame(rig):
    clock, carves, cost = rig
    cost["ms"] = 0.5
    ship = _Ship()
    _queue(ship, 4)
    visible_damage.advance(0.016, {ship: 1}, budget_ms=3.0, clock=clock)
    assert len(carves) == 4


def test_a_carve_held_back_by_the_budget_does_not_age(rig):
    """Ageing is for ships not yet realised; a realised ship's carve waiting
    on the budget must never time out."""
    clock, carves, cost = rig
    ship = _Ship()
    _queue(ship, 2)
    visible_damage.advance(10.0, {ship: 1}, budget_ms=3.0, clock=clock)
    visible_damage.advance(10.0, {ship: 1}, budget_ms=3.0, clock=clock)
    assert len(carves) == 2


def test_unrealised_ships_still_age_and_wait(rig):
    clock, carves, cost = rig
    early, late = _Ship(), _Ship()
    _queue(late, 1)
    _queue(early, 1)
    visible_damage.advance(0.016, {early: 1}, budget_ms=3.0, clock=clock)
    assert len(carves) == 1, "the realised ship's carve goes; the other waits"
    visible_damage.advance(0.016, {early: 1, late: 2}, budget_ms=3.0, clock=clock)
    assert len(carves) == 2
