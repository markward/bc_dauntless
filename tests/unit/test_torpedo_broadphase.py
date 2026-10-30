"""projectiles.update_all finds its torpedo/ship candidates in one store call.

Testing every torpedo against every ship in Python was ~45% of torpedo
flight in a 64-ship fight (~100 torpedoes x 64 ships a tick, nearly all far
apart). The rejection is TransformStore.sweep_candidates now; only the pairs
it returns reach the narrow tests, in ship order, first hit wins -- so the
hits are exactly the ones a test of every pair finds.
"""
import random

import pytest

from engine.appc import projectiles
from engine.appc.math import TGPoint3
from engine.appc.projectiles import Torpedo, register, update_all, _active
from engine.appc.transform_store import get_store
from tests.helpers.one_set import InSet, one_set_for


class _Ship(InSet):
    def __init__(self, x, y, z, radius):
        self._loc = TGPoint3(x, y, z)
        self._r = radius

    def GetWorldLocation(self): return self._loc
    def GetRadius(self): return self._r
    def IsDead(self): return 0
    def GetHull(self): return None
    def GetShields(self): return None
    def GetNumChildSubsystems(self): return 0
    def GetSubsystems(self): return []
    def GetObjID(self): return id(self)


@pytest.fixture(autouse=True)
def _scene(monkeypatch):
    _active.clear()
    one_set_for(_Ship, monkeypatch=monkeypatch)
    yield
    _active.clear()


def _torp(src, x, y, z, vx, vy, vz):
    t = Torpedo()
    t.SetTranslateXYZ(x, y, z)
    t._velocity = TGPoint3(vx, vy, vz)
    t._ttl = 30.0
    t._source_ship = src
    t._damage = 10.0
    register(t)
    return t


def _build(seed, n_ships=24, n_torps=60):
    rng = random.Random(seed)
    ships = [_Ship(rng.uniform(-60, 60), rng.uniform(-60, 60),
                   rng.uniform(-10, 10), rng.uniform(1.0, 8.0))
             for _ in range(n_ships)]
    torps = []
    for _ in range(n_torps):
        src = rng.choice(ships)
        aim = rng.choice(ships)
        p = (rng.uniform(-70, 70), rng.uniform(-70, 70), rng.uniform(-12, 12))
        d = [aim._loc.x - p[0], aim._loc.y - p[1], aim._loc.z - p[2]]
        m = max(1e-6, sum(c * c for c in d) ** 0.5)
        v = rng.uniform(10.0, 40.0)
        torps.append(_torp(src, *p, *(c / m * v for c in d)))
    return ships, torps


def _fly(ships, torps, ticks=150):
    index = {id(t): k for k, t in enumerate(torps)}
    sidx = {id(s): k for k, s in enumerate(ships)}
    log = []
    for tick in range(ticks):
        for t, ship, point, _n in update_all(1.0 / 60.0, ships):
            log.append((tick, index[id(t)], sidx[id(ship)],
                        point.x, point.y, point.z))
    flying = sorted((index[id(t)],) + tuple(
        getattr(t.GetTranslate(), a) for a in "xyz") for t in _active)
    return log, flying


def _every_pair(starts, seg_lens, skips, centres, bounds):
    out = []
    for t in range(len(seg_lens)):
        for s in range(len(bounds)):
            if s != skips[t]:
                out.extend((t, s))
    return out


@pytest.mark.parametrize("seed", range(8))
def test_hits_are_exactly_those_of_testing_every_pair(monkeypatch, seed):
    # The tightest bound that is still correct for these shieldless ships:
    # the hull sphere itself. The production bound adds the shield bubble's
    # margin, which would hide a broadphase that drops real hits.
    from engine.appc import combat
    monkeypatch.setattr(combat, "bubble_bound_radius",
                        lambda ship: ship.GetRadius())
    log, flying = _fly(*_build(seed))
    _active.clear()
    monkeypatch.setattr(type(get_store()), "sweep_candidates",
                        lambda self, *a: _every_pair(*a))
    ref_log, ref_flying = _fly(*_build(seed))
    assert len(ref_log) > 10                 # the scene really fights
    assert log == ref_log
    assert flying == ref_flying


def test_far_torpedoes_test_no_pair_in_python(monkeypatch):
    ships = [_Ship(1000.0 + 20 * k, 0.0, 0.0, 4.0) for k in range(20)]
    for k in range(50):
        _torp(ships[0], 0.0, 10.0 * k, 0.0, 0.0, 0.0, 20.0)
    calls = []
    real = projectiles._shifted

    def counting(*a, **k):
        calls.append(1)
        return real(*a, **k)
    monkeypatch.setattr(projectiles, "_shifted", counting)
    assert update_all(1.0 / 60.0, ships) == []
    assert calls == []
