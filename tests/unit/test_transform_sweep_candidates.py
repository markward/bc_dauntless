"""TransformStore.sweep_candidates: which (torpedo, ship) pairs are close
enough for projectiles.update_all's narrow hit tests.

Torpedo t's tick segment starts at starts[3t:3t+3] and is seg_lens[t] long;
ship s is a sphere of radius bounds[s] at centres[3s:3s+3]. The pair is a
candidate unless `dx*dx + dy*dy + dz*dz > reach*reach`, with d = centre - start
and reach = bound + seg_len, in CPython doubles -- update_all's broadphase
exactly, so a NaN distance stays a candidate. skips[t] is a ship index t never
meets (its shooter), or -1. Returned flat, [t0, s0, t1, s1, ...], ordered by
torpedo then ship.
"""
import math
import random
from array import array

import pytest

from engine.appc.transform_store import PythonTransformStore

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

_HAS_NATIVE = _h is not None and hasattr(_h, "transform_sweep_candidates")


def _native():
    from engine.appc.transform_store import NativeTransformStore
    return NativeTransformStore(_h)


BACKENDS = [
    pytest.param(PythonTransformStore, id="python"),
    pytest.param(_native, id="native", marks=pytest.mark.skipif(
        not _HAS_NATIVE, reason="native transform_sweep_candidates not built")),
]


@pytest.fixture(params=BACKENDS)
def store(request):
    return request.param()


def _pack(torps, ships):
    """torps: [(start xyz, seg_len, skip)], ships: [(centre xyz, bound)]."""
    starts, lens, skips = array("d"), array("d"), array("i")
    for p, n, k in torps:
        starts.extend(p)
        lens.append(n)
        skips.append(k)
    centres, bounds = array("d"), array("d")
    for c, b in ships:
        centres.extend(c)
        bounds.append(b)
    return starts, lens, skips, centres, bounds


def _expected(torps, ships):
    out = []
    for t, (p, n, k) in enumerate(torps):
        for s, (c, b) in enumerate(ships):
            if s == k:
                continue
            dx, dy, dz = c[0] - p[0], c[1] - p[1], c[2] - p[2]
            reach = b + n
            if (dx * dx + dy * dy + dz * dz) > reach * reach:
                continue
            out.extend((t, s))
    return out


def test_lists_the_pairs_within_reach_in_torpedo_then_ship_order(store):
    ships = [((0.0, 0.0, 0.0), 4.0), ((100.0, 0.0, 0.0), 4.0),
             ((10.0, 0.0, 0.0), 4.0)]
    torps = [((7.0, 0.0, 0.0), 1.0, -1),     # ship 2 only (ship 0 is 7 > 5)
             ((50.0, 0.0, 0.0), 1.0, -1),    # meets nothing
             ((98.0, 0.0, 0.0), 0.5, -1)]    # meets ship 1
    got = store.sweep_candidates(*_pack(torps, ships))
    assert list(got) == [0, 2, 2, 1]


def test_never_pairs_a_torpedo_with_its_skip_ship(store):
    ships = [((0.0, 0.0, 0.0), 4.0), ((1.0, 0.0, 0.0), 4.0)]
    torps = [((0.0, 0.0, 0.0), 1.0, 0)]
    assert list(store.sweep_candidates(*_pack(torps, ships))) == [0, 1]


def test_a_pair_exactly_at_reach_is_a_candidate(store):
    ships = [((3.0, 4.0, 0.0), 4.0)]
    torps = [((0.0, 0.0, 0.0), 1.0, -1)]          # distance 5 == 4 + 1
    assert list(store.sweep_candidates(*_pack(torps, ships))) == [0, 0]


def test_a_nan_distance_stays_a_candidate(store):
    ships = [((math.nan, 0.0, 0.0), 4.0)]
    torps = [((0.0, 0.0, 0.0), 1.0, -1)]
    assert list(store.sweep_candidates(*_pack(torps, ships))) == [0, 0]


def test_no_torpedoes_or_no_ships(store):
    assert list(store.sweep_candidates(*_pack([], [((0, 0, 0), 1.0)]))) == []
    assert list(store.sweep_candidates(*_pack([((0, 0, 0), 1.0, -1)], []))) == []


@pytest.mark.parametrize("seed", range(6))
def test_matches_the_python_compare_on_the_boundary(store, seed):
    """Spheres placed on and just around reach, in awkward doubles: the
    store must agree with CPython's own arithmetic pair for pair."""
    rng = random.Random(seed)
    ships = [((rng.uniform(-500, 500), rng.uniform(-500, 500),
               rng.uniform(-50, 50)), rng.uniform(0.5, 9.0))
             for _ in range(40)]
    torps = []
    for _ in range(60):
        c, b = ships[rng.randrange(len(ships))]
        n = rng.uniform(0.0, 2.0)
        reach = b + n
        u = [rng.gauss(0, 1) for _ in range(3)]
        m = math.sqrt(sum(x * x for x in u)) or 1.0
        r = reach * rng.choice([1.0, 1.0 - 1e-15, 1.0 + 1e-15, 0.5, 1.5])
        p = tuple(c[i] - u[i] / m * r for i in range(3))
        torps.append((p, n, rng.choice([-1, rng.randrange(len(ships))])))
    got = store.sweep_candidates(*_pack(torps, ships))
    assert list(got) == _expected(torps, ships)
