"""The native combat library's Python-exact math, bit for bit.

The combat step's sensor query (can_detect) is moving into C++
(native/src/combat/). Its answers must be IDENTICAL to today's Python, so
every primitive it is built on is checked here against the Python it
replaces, on random inputs and on the edges where a float rounds or a NaN
picks a branch:

  * dist3 is CPython 3.11.15's math.dist (the compensated vector_norm, not a
    naive sqrt): the radial profile radius comes from it;
  * density / fbm are engine.appc.nebula_density's;
  * the profile's sensors column is engine.systems.profile.evaluate's, on
    every checked-in system map;
  * segment_hits / contains are engine.appc.sensor_occlusion's.

Floats are compared by float.hex(): no tolerance, ever.
"""
import math
import random

import pytest

from engine.appc import nebula_density as nd
from engine.appc import sensor_occlusion as occ
from engine.systems import map as system_map
from engine.systems import profile, resolve

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_test_dist3"),
    reason="native combat bindings not built")

SEED = 20261031
NAN = float("nan")
INF = float("inf")


def _same(native: float, python: float) -> bool:
    if math.isnan(python):
        return math.isnan(native)
    return float(native).hex() == float(python).hex()


def _assert_same(native, python, what):
    assert _same(native, python), (
        f"{what}: native {float(native).hex()} != python {float(python).hex()}")


# ── math.dist ────────────────────────────────────────────────────────────────

_EDGE_COORDS = (0.0, -0.0, 1.0, -1.0, 1e-300, -1e-300, 5e-324, -5e-324,
                2.2250738585072014e-308, 1e300, -1e300, 1.7e308, -1.7e308,
                INF, -INF, NAN, 3.0, 4.0, 122000.0, 128000.0)


def _edge_pairs():
    rng = random.Random(SEED)
    pairs = [((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
             ((-0.0, -0.0, -0.0), (0.0, 0.0, 0.0)),
             ((3.0, 4.0, 0.0), (0.0, 0.0, 0.0)),
             ((1e-300, 0.0, 0.0), (0.0, 1e-300, 0.0)),
             ((5e-324, 5e-324, 5e-324), (0.0, 0.0, 0.0)),
             ((1e300, 1e300, 1e300), (-1e300, 0.0, 0.0)),
             ((INF, NAN, 0.0), (0.0, 0.0, 0.0)),
             ((NAN, 0.0, 0.0), (0.0, 0.0, 0.0)),
             ((INF, 0.0, 0.0), (INF, 0.0, 0.0)),
             ((-INF, 1.0, 2.0), (3.0, 4.0, 5.0))]
    for _ in range(3000):
        a = tuple(rng.choice(_EDGE_COORDS) for _ in range(3))
        b = tuple(rng.choice(_EDGE_COORDS) for _ in range(3))
        pairs.append((a, b))
    for _ in range(200):
        a = tuple(rng.uniform(-2e5, 2e5) for _ in range(3))
        pairs.append((a, a))                       # equal points
    return pairs


def test_dist3_matches_math_dist():
    rng = random.Random(SEED)
    pairs = [(tuple(rng.uniform(-2e5, 2e5) for _ in range(3)),
              tuple(rng.uniform(-2e5, 2e5) for _ in range(3)))
             for _ in range(20000)]
    # The E3M2 bands: a star at the origin, points 116k-134k GU out.
    for _ in range(5000):
        r = rng.uniform(116000.0, 134000.0)
        v = [rng.gauss(0.0, 1.0) for _ in range(3)]
        n = math.sqrt(sum(c * c for c in v))
        pairs.append((tuple(r * c / n for c in v), (0.0, 0.0, 0.0)))
    pairs += _edge_pairs()
    for a, b in pairs:
        _assert_same(_h.combat_test_dist3(a, b), math.dist(a, b), f"dist{a}{b}")


# ── nebula density ───────────────────────────────────────────────────────────

def test_fbm_matches_python():
    rng = random.Random(SEED)
    points = [(1.5, 2.5, 3.5), (0.0, 0.0, 0.0), (-0.0, -0.0, -0.0),
              (-1.0, -2.0, -3.0), (1e6, -1e6, 3e5), (1e15, 1e16, -1e17)]
    points += [tuple(rng.uniform(-1e4, 1e4) for _ in range(3)) for _ in range(2000)]
    points += [tuple(rng.uniform(-50.0, 50.0) for _ in range(3)) for _ in range(2000)]
    for x, y, z in points:
        _assert_same(_h.combat_test_fbm(x, y, z), nd.fbm(x, y, z), f"fbm{(x, y, z)}")


def _random_density_case(rng):
    n = rng.randint(1, 13)
    spheres = []
    for _ in range(n):
        c = tuple(rng.uniform(-3000.0, 3000.0) for _ in range(3))
        r = rng.choice([rng.uniform(50.0, 1500.0), rng.uniform(50.0, 1500.0),
                        rng.uniform(50.0, 1500.0), 0.0, -10.0])
        spheres.append((*c, r))
    cx, cy, cz, cr = rng.choice(spheres)
    reach = abs(cr) * 1.2 + 1.0
    p = (cx + rng.uniform(-reach, reach), cy + rng.uniform(-reach, reach),
         cz + rng.uniform(-reach, reach))
    seed = nd.seed_for(*(rng.uniform(-3000.0, 3000.0) for _ in range(3)))
    freq = rng.uniform(0.001, 0.08)
    gain = rng.uniform(0.5, 3.0)
    floor = rng.uniform(0.0, 0.6)
    drift_t = rng.uniform(0.0, 50.0)
    return p, spheres, seed, freq, gain, floor, drift_t


def _check_density(p, spheres, seed, freq, gain, floor, drift_t):
    native = _h.combat_test_density(p[0], p[1], p[2], spheres, seed,
                                    freq, gain, floor, drift_t)
    python = nd.density(p[0], p[1], p[2], spheres, seed, freq, gain, floor, drift_t)
    _assert_same(native, python, f"density{(p, spheres, seed, freq, gain, floor, drift_t)}")


def test_density_matches_python():
    rng = random.Random(SEED)
    inside = 0
    for _ in range(2000):
        case = _random_density_case(rng)
        _check_density(*case)
        if nd.density(*case[0], *case[1:]) > 0.0:
            inside += 1
    assert inside > 200          # the fbm path is exercised, not just the bound
    # The pinned golden case from tests/unit/test_nebula_density.py.
    _check_density((20.0, 10.0, 5.0), [(0.0, 0.0, 0.0, 100.0)],
                   nd.seed_for(0.0, 0.0, 0.0), 0.05, 1.6, 0.4, 0.0)


def test_density_non_finite_noise_input_raises_like_python():
    """Python's math.floor raises when a non-finite drift_t, freq or seed
    reaches fbm at a point inside a sphere; native raises ValueError there
    (ruling R5) so its caller asks the Python, never a silent NaN. Outside
    every sphere neither reaches fbm and both answer 0.0."""
    seed = nd.seed_for(0.0, 0.0, 0.0)
    spheres = [(0.0, 0.0, 0.0, 100.0)]
    cases = [(NAN, 0.05, seed), (INF, 0.05, seed), (0.0, INF, seed),
             (0.0, 0.05, (seed[0], NAN, seed[2]))]
    for drift, freq, s in cases:
        with pytest.raises((ValueError, OverflowError)):
            nd.density(20.0, 10.0, 5.0, spheres, s, freq, 1.6, 0.4, drift)
        with pytest.raises(ValueError):
            _h.combat_test_density(20.0, 10.0, 5.0, spheres, s, freq, 1.6,
                                   0.4, drift)
        _check_density((500.0, 0.0, 0.0), spheres, s, freq, 1.6, 0.4, drift)


def test_py_min_max_nan_order():
    """NaN follows Python's comparison order: a NaN sphere radius or position
    never wins the union (`f > best` is False), a NaN gain or floor reaches the
    result (`_saturate` passes NaN through), and a NaN sphere beside a real one
    leaves the real one's falloff."""
    seed = nd.seed_for(0.0, 0.0, 0.0)
    cases = [
        ((1.0, 2.0, 3.0), [(0.0, 0.0, 0.0, NAN)], 0.05, 1.6, 0.4),
        ((NAN, 2.0, 3.0), [(0.0, 0.0, 0.0, 100.0)], 0.05, 1.6, 0.4),
        ((1.0, 2.0, 3.0), [(NAN, 0.0, 0.0, 100.0)], 0.05, 1.6, 0.4),
        ((1.0, 2.0, 3.0), [(0.0, 0.0, 0.0, NAN), (0.0, 0.0, 0.0, 100.0)], 0.05, 1.6, 0.4),
        ((1.0, 2.0, 3.0), [(0.0, 0.0, 0.0, 100.0), (0.0, 0.0, 0.0, NAN)], 0.05, 1.6, 0.4),
        ((1.0, 2.0, 3.0), [(0.0, 0.0, 0.0, 100.0)], 0.05, NAN, 0.4),
        ((1.0, 2.0, 3.0), [(0.0, 0.0, 0.0, 100.0)], 0.05, 1.6, NAN),
        ((1.0, 2.0, 3.0), [(0.0, 0.0, 0.0, INF)], 0.05, 1.6, 0.4),
        ((INF, 2.0, 3.0), [(0.0, 0.0, 0.0, 100.0)], 0.05, 1.6, 0.4),
        ((1.0, 2.0, 3.0), [(0.0, 0.0, 0.0, 100.0)], 0.05, INF, 0.4),
        ((1.0, 2.0, 3.0), [(0.0, 0.0, 0.0, 100.0)], 0.05, -INF, 0.4),
        ((1.0, 2.0, 3.0), [], 0.05, 1.6, 0.4),
    ]
    for p, spheres, freq, gain, floor in cases:
        _check_density(p, spheres, seed, freq, gain, floor, 0.0)


# ── radial profile ───────────────────────────────────────────────────────────

def _maps():
    return [resolve.map_of(system_map.load(name).system)
            for name in system_map.available()]


def _rows(prof):
    return [(float(row.distance_gu), float(row.sensors)) for row in prof.rows]


def _radii(prof, rng):
    ds = [float(row.distance_gu) for row in prof.rows]
    rs = [0.0, -0.0, -1.0, NAN, INF, -INF, ds[-1] * 2.0 + 1.0]
    for d in ds:
        rs += [d, math.nextafter(d, INF), math.nextafter(d, -INF)]
    for a, b in zip(ds, ds[1:]):
        rs.append((a + b) / 2.0)
        rs += [rng.uniform(a, b) for _ in range(50)]
    return rs


def test_profile_sensors_matches_python():
    rng = random.Random(SEED)
    maps = _maps()
    # A floor, not a pin: it proves the walk reached the real maps, and a
    # new system map must not fail this unrelated test.
    assert len(maps) >= 33
    varying = 0
    for m in maps:
        prof = m.profile
        rows = _rows(prof)
        if len({s for _, s in rows}) > 1:
            varying += 1
        for r in _radii(prof, rng):
            _assert_same(_h.combat_test_profile_sensors(rows, r),
                         profile.evaluate(prof, r).sensors, f"{m.system} r={r!r}")
    assert varying >= 2          # Vesuvi and Belaruz: the bands that matter
    # No profile (or no rows) is clear space.
    _assert_same(_h.combat_test_profile_sensors([], 5.0),
                 profile.evaluate(profile.Profile(rows=[]), 5.0).sensors, "empty")


# ── occlusion ────────────────────────────────────────────────────────────────

def _occlusion_cases(rng):
    cases = []
    for _ in range(4000):
        a = [rng.uniform(-1000.0, 1000.0) for _ in range(3)]
        kind = rng.random()
        if kind < 0.15:
            b = list(a)                                         # zero-length
        elif kind < 0.3:
            b = [c + rng.uniform(-4e-7, 4e-7) for c in a]       # seg2 <= 1e-12
        else:
            b = [rng.uniform(-1000.0, 1000.0) for _ in range(3)]
        t = rng.uniform(-0.5, 1.5)
        c = [a[i] + (b[i] - a[i]) * t + rng.uniform(-200.0, 200.0) for i in range(3)]
        r = rng.uniform(0.0, 300.0)
        cases.append((*a, *b, *c, r))
    cases.append((0.0, 0.0, 0.0, 10.0, 0.0, 0.0, 5.0, 3.0, 0.0, 3.0))  # touching: strict
    cases.append((NAN, 0.0, 0.0, 10.0, 0.0, 0.0, 5.0, 1.0, 0.0, 3.0))
    cases.append((0.0, 0.0, 0.0, 10.0, 0.0, 0.0, 5.0, 1.0, 0.0, NAN))
    cases.append((0.0, 0.0, 0.0, 1e-7, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0))
    return cases


def test_occlusion_primitives_match():
    rng = random.Random(SEED)
    hits = 0
    for case in _occlusion_cases(rng):
        expected = occ._segment_hits(*case)
        assert _h.combat_test_segment_hits(*case) == expected, case
        hits += expected
        ax, ay, az, bx, by, bz, cx, cy, cz, r = case
        for x, y, z in ((ax, ay, az), (bx, by, bz)):
            assert (_h.combat_test_contains(x, y, z, cx, cy, cz, r)
                    == occ._contains(x, y, z, cx, cy, cz, r)), case
    assert hits > 100
