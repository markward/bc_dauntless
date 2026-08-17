"""Cloak-bubble geometry for tests, DERIVED from the live constants.

**Why this exists.** The cloak detection bubble is

    CLOAK_DETECTION_BASE_GU + effective_sensor_range * CLOAK_RANGE_FACTOR

and both dials are play-tested settings that have moved four times. Every retune
used to mean hand-editing dozens of hardcoded "the bubble is 25 GU" claims and
probe distances across nine test files — reliably missing some, which left tests
whose docstrings disagreed with their assertions. Retuning must be a ONE-LINE
change to `sensor_detection`, with no test edits at all. That is what this
module buys.

**Two patterns, pick by constraint count.**

1. The distance's ONLY constraint is bubble-relative → derive it:

       _target(inside_gu())        # comfortably detected
       _target(outside_gu())       # comfortably undetected

2. The distance must ALSO satisfy something else (weapon range, radar range, a
   fixture's fixed layout) → keep the literal and assert the assumption:

       assert_inside(50.0, FALLBACK_SENSOR_GU)   # one line, fails loudly

   Pattern 2 matters because a derived distance can silently violate the other
   constraint: `inside_gu(FALLBACK_SENSOR_GU)` is far beyond a phaser's 60 GU
   reach, so a phaser test that "just derives" would stop testing cloak and
   start testing weapon range instead.

Everything is computed at CALL time, never at import, so `monkeypatch.setattr`
on the constants is honoured.
"""
from engine.appc import sensor_detection as sd

#: A Galaxy's authored BaseSensorRange — the common "real sensors" fixture.
GALAXY_SENSOR_GU = 2000.0

#: What `effective_sensor_range` returns for a ship with NO sensor subsystem.
#: 18 of 52 hardpoint files author no BaseSensorRange, so this is the bubble
#: most bare-ShipClass fixtures actually get, and it is much larger.
FALLBACK_SENSOR_GU = sd.FALLBACK_RANGE_GU

#: Fractions of the bubble radius used for probes. `INSIDE` leaves headroom for
#: float error; `OUTSIDE` is far enough out that no rounding accident passes it.
INSIDE_FRACTION = 0.6
OUTSIDE_MULTIPLE = 3.0


def bubble_gu(effective_range_gu=GALAXY_SENSOR_GU):
    """Cloak bubble radius in GU for an observer with *effective_range_gu*.

    Mirrors `can_detect`'s cloak term exactly. Note the argument is EFFECTIVE
    range (post sensor condition and power), not the authored base range — at
    full condition they coincide, which is why the default is a raw 2000.0.
    """
    return (sd.CLOAK_DETECTION_BASE_GU
            + effective_range_gu * sd.CLOAK_RANGE_FACTOR)


def inside_gu(effective_range_gu=GALAXY_SENSOR_GU):
    """A distance comfortably INSIDE the bubble — a cloaked ship here is seen."""
    return bubble_gu(effective_range_gu) * INSIDE_FRACTION


def outside_gu(effective_range_gu=GALAXY_SENSOR_GU):
    """A distance comfortably OUTSIDE the bubble — a cloaked ship here is not.

    `can_detect` compares `dist_sq <= r * r`, so a probe exactly ON the boundary
    is DETECTED. Never probe the boundary to mean "outside".
    """
    return bubble_gu(effective_range_gu) * OUTSIDE_MULTIPLE


def assert_inside(distance_gu, effective_range_gu=GALAXY_SENSOR_GU):
    """Assert a hardcoded *distance_gu* is inside the bubble (pattern 2)."""
    r = bubble_gu(effective_range_gu)
    assert distance_gu < r, (
        f"fixture assumes {distance_gu} GU is INSIDE the cloak bubble, but a "
        f"retune moved the bubble to {r} GU. This test is no longer testing "
        f"what it names — re-pick the distance, don't relax the assertion.")


def assert_outside(distance_gu, effective_range_gu=GALAXY_SENSOR_GU):
    """Assert a hardcoded *distance_gu* is outside the bubble (pattern 2)."""
    r = bubble_gu(effective_range_gu)
    assert distance_gu > r, (
        f"fixture assumes {distance_gu} GU is OUTSIDE the cloak bubble, but a "
        f"retune moved the bubble to {r} GU. This test is no longer testing "
        f"what it names — re-pick the distance, don't relax the assertion.")
