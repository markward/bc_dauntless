"""ShipSubsystem.IsHittableFromLocation matches the original game.

The stock AI adds 1 to a subsystem's targeting rating when it is hittable
from the firing ship (SDK AI/Preprocessors.py RateSubsystemForTargeting).
Dauntless answered 1.0 for everything. The original answers 0 or 1 by one
rule for every subsystem (engine/appc/hull_line_of_sight.py): trace toward
the subsystem's position; hittable when the trace meets the hull at or before
it, within its radius. The cases are the original's own answers at 57 GU
(elevation, azimuth from the nose, 90 = starboard);
tests/oracle/survey_hittable_vs_original.py compares every subsystem of
fourteen classes against the full captures.
"""
import math
import random

import pytest

from tests.oracle.test_firing_arcs_match_original import _all_subs, _point

CASES = [
    # (attacker, target, which, subsystem, elevation, azimuth, the original's answer)
    ("Sovereign", "Galaxy", "tgt", "Forward Torpedo 1", -60, 90, 1.0),
    ("Sovereign", "Galaxy", "tgt", "Forward Torpedo 1", 60, 300, 0.0),
    ("Sovereign", "Galaxy", "tgt", "Bridge", 30, 0, 1.0),
    ("Sovereign", "Galaxy", "tgt", "Bridge", -30, 180, 0.0),
    ("Sovereign", "Galaxy", "tgt", "Warp Core", -30, 180, 1.0),
    ("Sovereign", "Galaxy", "tgt", "Warp Core", 30, 60, 0.0),
    # A bank outside the hull: the Galaxy's ventral banks from nowhere, the
    # Akira's dorsal banks only from below (the hull just in front of them).
    ("Sovereign", "Galaxy", "tgt", "Ventral Phaser 1", -90, 0, 0.0),
    ("Sovereign", "Galaxy", "tgt", "Ventral Phaser 1", 90, 0, 0.0),
    ("Akira", "Nebula", "atk", "Dorsal Phaser 1", -60, 120, 1.0),
    ("Akira", "Nebula", "atk", "Dorsal Phaser 1", 60, 120, 0.0),
    ("Vorcha", "Keldon", "tgt", "Port Beam", 50, 90, 1.0),
    ("Vorcha", "Keldon", "tgt", "Port Beam", 10, 110, 0.0),
    # A Bird of Prey's wing cannon is traced at rest, as the original does.
    ("Warbird", "BirdOfPrey", "tgt", "Port Cannon", 60, 0, 1.0),
]


@pytest.mark.parametrize("atk,tgt,which,name,el,az,want", CASES,
                         ids=["%s-%s-%d-%d" % (c[1] if c[2] == "tgt" else c[0], c[3], c[4], c[5]) for c in CASES])
def test_hittable_as_the_original_answers(oracle, atk, tgt, which, name, el, az, want):
    s = oracle(attacker=atk, target=tgt, range_gu=57.0)
    ship = getattr(s, which)
    assert _all_subs(ship)[name].IsHittableFromLocation(_point(ship, el, az, 57.0)) == want


def test_a_ship_with_no_model_keeps_everything_hittable(oracle):
    from engine.appc import hull_line_of_sight
    s = oracle(attacker="Sovereign", target="Galaxy", range_gu=57.0)
    s.tgt.__dict__["_hull_los_mesh"] = None
    bridge = _all_subs(s.tgt)["Bridge"]
    assert hull_line_of_sight.hittable_from(bridge, s.tgt, _point(s.tgt, -30, 180, 57.0)) == 1.0


def test_native_trace_gives_the_python_bits(oracle):
    """hull_trace.cc walks damage_point._Bvh's own boxes and triangles."""
    from engine.appc import damage_point
    s = oracle(attacker="Sovereign", target="Galaxy", range_gu=57.0)
    bvh = damage_point._mesh(damage_point._nif_path(s.tgt))
    if bvh.native_handle() is None:
        pytest.skip("native module not built")
    rng = random.Random(20261106)
    hits = 0
    for _ in range(3000):
        el, az = rng.uniform(-1.57, 1.57), rng.uniform(0.0, 6.283)
        r = rng.choice((2000.0, 5700.0, 15000.0))
        o = (r * math.cos(el) * math.sin(az), r * math.cos(el) * math.cos(az), r * math.sin(el))
        tgt = [rng.uniform(-300.0, 300.0) for _ in range(3)]
        v = [tgt[k] - o[k] for k in range(3)]
        n = math.sqrt(sum(x * x for x in v))
        d = [x / n for x in v]
        want = bvh.first_hit_python(o, d)
        got = bvh.first_hit(o, d)
        assert (got is None) == (want is None)
        if want is not None:
            assert got.hex() == want.hex()
            hits += 1
    assert hits > 500
