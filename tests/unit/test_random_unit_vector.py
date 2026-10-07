"""App.TGPoint3_GetRandomUnitVector — heatmap rank 1 (80,805 hits).
Undefined, every call returned a truthy _NamedStub whose .x/.y/.z were
stubs, so Flee/EvadeTorps/Warp/AvoidObstacles scored every random
candidate as the zero vector."""
import math
import subprocess
import sys

import App
from engine.appc.math import TGPoint3


def test_is_real_surface_not_a_stub():
    assert not isinstance(App.TGPoint3_GetRandomUnitVector, App._NamedStub)


def test_returns_a_unit_tgpoint3():
    v = App.TGPoint3_GetRandomUnitVector()
    assert isinstance(v, TGPoint3)
    assert abs(math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z) - 1.0) < 1e-6


def test_successive_calls_differ_and_cover_every_octant():
    seen = set()
    for _ in range(400):
        v = App.TGPoint3_GetRandomUnitVector()
        seen.add((v.x > 0, v.y > 0, v.z > 0))
    assert len(seen) == 8, "not uniformly distributed over the sphere"


def test_each_call_is_a_fresh_object():
    a = App.TGPoint3_GetRandomUnitVector()
    b = App.TGPoint3_GetRandomUnitVector()
    assert a is not b


def _first_draw_from_a_fresh_process(repo_root):
    """A brand-new interpreter imports engine.appc.math fresh and takes the
    FIRST draw from TGPoint3_GetRandomUnitVector -- i.e. whatever the
    module-level RNG was seeded with at import, untouched by any other
    test or call in this process."""
    out = subprocess.run(
        [sys.executable, "-c",
         "from engine.appc.math import TGPoint3_GetRandomUnitVector as f\n"
         "v = f()\n"
         "print(repr((v.x, v.y, v.z)))"],
        cwd=repo_root, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def test_first_draw_is_the_same_across_fresh_processes(request):
    """Pins the live bug: AI/Preprocessors.py:1904 (AvoidObstacles), plus
    Flee.py/EvadeTorps.py/Warp.py, draw their candidate flee/evade
    directions straight from this function. A module-level
    ``random.Random()`` with no seed argument pulls from OS entropy at
    import, so the SAME scripted scene (same ship count, same geometry,
    same tick count) steers a DIFFERENT heading every fresh process --
    which is exactly how
    test_pursuers_avoid_each_other.py::test_pursuers_chasing_a_straight_line_target_do_not_fly_into_each_other
    flaked across repeated `scripts/run_tests.sh` runs of an otherwise
    byte-identical tree, with no change in test order (there is no
    randomized-order plugin in this project) and no change in the scene.
    A seed-sweep of 45 values reproduced a hull interpenetration on 2/45
    (seeds 12 and 39) with the real fixture, confirming the draw -- not
    the order -- decides the outcome. The module must seed from a fixed
    constant so two fresh interpreters draw identically."""
    repo_root = str(request.config.rootpath)
    first = _first_draw_from_a_fresh_process(repo_root)
    second = _first_draw_from_a_fresh_process(repo_root)
    assert first == second, (
        "TGPoint3_GetRandomUnitVector's first draw differs between two "
        "fresh interpreters -- the module-level RNG is seeded from OS "
        "entropy, not a fixed constant, so this function (and every SDK "
        "flee/evade/avoidance scan built on it) is non-deterministic "
        "across process runs."
    )


def test_reset_restores_the_seeded_sequence():
    """reset_random_unit_vector_rng() rewinds the shared RNG to its seed, so a
    test's draws never depend on how many draws earlier tests made (the
    conftest autouse reset calls it before every test)."""
    from engine.appc import math as appc_math
    appc_math.reset_random_unit_vector_rng()
    first = App.TGPoint3_GetRandomUnitVector()
    for _ in range(17):
        App.TGPoint3_GetRandomUnitVector()
    appc_math.reset_random_unit_vector_rng()
    again = App.TGPoint3_GetRandomUnitVector()
    assert (again.x, again.y, again.z) == (first.x, first.y, first.z)


def test_each_test_starts_from_the_seed(request):
    """The conftest autouse reset rewound the RNG before this test ran: its
    first draw is the seed's first draw, regardless of earlier tests."""
    import random as _random
    from engine.appc import math as appc_math
    rng = _random.Random(appc_math._UNIT_VECTOR_RNG_SEED)
    while True:
        a, b = rng.uniform(-1.0, 1.0), rng.uniform(-1.0, 1.0)
        s = a * a + b * b
        if 0.0 < s < 1.0:
            break
    k = 2.0 * math.sqrt(1.0 - s)
    v = App.TGPoint3_GetRandomUnitVector()
    assert (v.x, v.y, v.z) == (a * k, b * k, 1.0 - 2.0 * s)
