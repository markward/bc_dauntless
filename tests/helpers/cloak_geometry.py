"""Cloak-bubble geometry for tests, DERIVED from the live constants.

**Why this exists.** The cloak detection bubble is

    min(cloak_bubble_cap_gu, CLOAK_DETECTION_BASE_GU
                             + effective_sensor_range * CLOAK_RANGE_FACTOR)

where the cap is a `sensor_dials` dial and the two constants are play-tested
settings that have moved four times. Every retune used to mean hand-editing
dozens of hardcoded "the bubble is N GU" claims and probe distances across nine
test files — reliably missing some, which left tests whose docstrings disagreed
with their assertions. Retuning must be a ONE-LINE change to `sensor_detection`
or `sensor_dials`, with no test edits at all. That is what this module buys.

**Two patterns, pick by constraint count.**

1. The distance's ONLY constraint is bubble-relative → derive it:

       _target(inside_gu())        # comfortably detected
       _target(outside_gu())       # comfortably undetected

2. The distance must ALSO satisfy something else (weapon range, radar range, a
   fixture's fixed layout) → keep the literal and assert the assumption:

       WITHIN_PHASER_REACH_GU = 8.0         # the second constraint, named
       assert_inside(WITHIN_PHASER_REACH_GU, sensorless_gu())  # fails loudly

   Pattern 2 matters because a derived distance can silently violate the other
   constraint: a test that "just derives" `inside_gu(sensorless_gu())` would
   track every retune of the dials, and the day it crosses a weapon's reach it
   stops testing cloak and starts testing weapon range instead.

Everything is computed at CALL time, never at import, so `monkeypatch.setattr`
on the constants (and `monkeypatch.setitem` on the dials) is honoured.
"""
from engine.appc import sensor_detection as sd

#: A Galaxy's authored BaseSensorRange — the common "real sensors" fixture.
GALAXY_SENSOR_GU = 2000.0


def sensorless_gu():
    """What `effective_sensor_range` returns for an observer with NO sensor
    subsystem: the live `sensorless_range_gu` dial, read at call time."""
    from engine.appc import sensor_dials
    return sensor_dials.get("sensorless_range_gu")


#: Fractions of the bubble radius used for probes. `INSIDE` leaves headroom for
#: float error; `OUTSIDE` is far enough out that no rounding accident passes it.
INSIDE_FRACTION = 0.6
OUTSIDE_MULTIPLE = 3.0


def bubble_gu(effective_range_gu=GALAXY_SENSOR_GU):
    """Cloak bubble radius in GU for an observer with *effective_range_gu*.

    Mirrors `can_detect`'s cloak term exactly, including the
    `cloak_bubble_cap_gu` dial. The argument is EFFECTIVE range (post sensor
    condition and power), not the authored base range -- at full condition
    they coincide."""
    from engine.appc import sensor_dials
    return min(sensor_dials.get("cloak_bubble_cap_gu"),
               sd.CLOAK_DETECTION_BASE_GU
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
