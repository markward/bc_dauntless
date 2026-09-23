import pytest

from engine.appc import hull_carve


def test_strength_scales_with_absorbed_hull():
    # strength = absorbed_hull * STRENGTH_PER_HULL (1:1) — accumulates gradually
    # rather than a single moderate hit one-shotting a breach.
    assert hull_carve.carve_strength(0.0) == 0.0
    assert hull_carve.carve_strength(60.0) == pytest.approx(60.0 * hull_carve.STRENGTH_PER_HULL)
    # Monotonic and never negative.
    assert hull_carve.carve_strength(-5.0) == 0.0
    assert hull_carve.carve_strength(120.0) > hull_carve.carve_strength(60.0)


def test_influ_floored_and_scaled():
    # Merge influence is floored so clustered light fire accumulates even with a
    # tiny weapon splash, and scales above the floor.
    assert hull_carve.carve_influ_gu(0.0) == hull_carve.CARVE_INFLU_MIN_GU
    big = hull_carve.carve_influ_gu(10.0)
    assert big >= hull_carve.CARVE_INFLU_MIN_GU
    assert big == max(hull_carve.CARVE_INFLU_MIN_GU,
                      10.0 * hull_carve.CARVE_INFLU_SCALE)


def test_constants_sane():
    assert hull_carve.STRENGTH_PER_HULL > 0.0
    assert hull_carve.CARVE_INFLU_MIN_GU > 0.0
    assert hull_carve.MIN_CARVE_RADIUS_GU > 0.0
    assert hull_carve.CARVE_EMIT_INTERVAL > 0.0


# The C++ iso, MIRRORED. `kHullCarveStrengthIso` lives in
# native/src/scenegraph/include/scenegraph/hull_carve.h and is not exposed to
# Python, so the calibration below spans the C++/Python boundary with nothing
# holding the two halves together. That gap is exactly how the 2026-09-23
# regression shipped. Keep this literal in step with the header.
_CPP_STRENGTH_ISO = 150.0

# A Bird of Prey's PortCannon does SetMaxDamage(200); a Galaxy's VentralPhaser3
# does 250. These are the real authored numbers from ships/Hardpoints/.
_ONE_FULL_HIT_ABSORBED_HULL = 200.0


def test_one_full_strength_hit_can_open_a_hole():
    """A single full-damage weapon hit that lands entirely on hull must cross
    the carve iso.

    THIS TEST EXISTS BECAUSE OF A REAL REGRESSION. STRENGTH_PER_HULL was cut
    1.0 -> 0.25 to make hulls "carve like butter" less, which raised the
    per-site threshold to 600 absorbed hull. Nothing caught it and craters
    stopped appearing entirely across three live battles.

    The reasoning error was a category mistake: the change was calibrated
    against a ship's TOTAL hull HP ("a Galaxy craters at 4% of 15000"), but the
    iso is not a fraction of a health pool — strength accumulates PER CARVE
    SITE (hull_carve.cc: `c.strength += strength` merged within ~0.09 GU), so
    the only denominator that matters is damage delivered at ONE POINT. On a
    manoeuvring target, consecutive hits rarely land within 15 m of each other.

    So hole SIZE is tuned with kHullCarveRadiusMaxGu, and hole READINESS with
    STRENGTH_PER_HULL — and readiness must stay within reach of a single hit.
    """
    assert hull_carve.carve_strength(_ONE_FULL_HIT_ABSORBED_HULL) >= _CPP_STRENGTH_ISO, (
        "a full-strength weapon hit no longer opens a hole: "
        "STRENGTH_PER_HULL=%r puts one %g-damage hit at %g strength, "
        "below the C++ iso of %g"
        % (hull_carve.STRENGTH_PER_HULL, _ONE_FULL_HIT_ABSORBED_HULL,
           hull_carve.carve_strength(_ONE_FULL_HIT_ABSORBED_HULL),
           _CPP_STRENGTH_ISO))
