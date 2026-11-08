"""Ships chasing the same target must not fly through each other.

THE BUG THIS PINS. Live report: with the player holding a straight course, the
pursuing ships' paths converge on one point and they end up inside one another.

Measured headlessly before the fix -- six Keldons on QuickBattle's exact AI
construction, player flying a constant-velocity line, 2400 ticks (40 s):

    minimum pairwise separation   15.7 GU -> 3.9 GU   (hulls touch below 8.0)
    ticks with an interpenetration            1230 / 2400
    ticks with avoidance overriding a course     0 / 2400

Avoidance never ran ONCE. ``AvoidObstacles.TestCourseOverride`` walks near
objects with the SDK's three-call ProximityManager contract, and both halves of
that contract were dead (see tests/unit/test_proximity_manager_iteration.py), so
it always returned "nothing to avoid".

The scene is deliberately the one the report describes -- a straight-line
target, pursuers converging from a spread -- rather than a melee: it is the
geometry that makes every pursuer's path cross every other's.
"""
import itertools
import math

import pytest

from tests.helpers import straight_line_chase as chase
from tests.helpers.straight_line_chase import NOMINAL_RADIUS_GU

TICKS = 2400

# A hull "touch": two ships closer than the sum of their radii are inside one
# another. Nothing in the sim stops that -- collision response nudges, it does
# not separate -- so this is the number the player sees.
CONTACT_GU = 2 * NOMINAL_RADIUS_GU


@pytest.fixture
def straight_line_chase(monkeypatch):
    from engine.core.game import _set_current_game
    yield chase.build(monkeypatch)
    _set_current_game(None)


def _is_overriding(ship):
    """The SDK's own definition: AvoidObstacles.Update sets vOverrideDirection
    from TestCourseOverride and treats non-None as "override the course"
    (AI/Preprocessors.py:1696). Read off the script instance rather than any
    engine-side bookkeeping, so this measures whichever scan is in force --
    the SDK's by default, the engine one under DAUNTLESS_ENGINE_AVOIDANCE=1."""
    node = ship.GetAI()
    inst = getattr(node, "_preprocessing_instance", None)
    return getattr(inst, "vOverrideDirection", None) is not None


def _run(loop, player, pursuers):
    """Fly the player dead straight; return (worst separation, contact ticks,
    ticks on which avoidance overrode at least one pursuer's course)."""
    worst = float("inf")
    contact_ticks = 0
    override_ticks = 0
    for _ in range(TICKS):
        chase.fly_player(player)

        loop.tick()

        seps = [_dist(a, b) for a, b in itertools.combinations(pursuers, 2)]
        worst = min(worst, min(seps))
        if min(seps) < CONTACT_GU:
            contact_ticks += 1
        if any(_is_overriding(s) for s in pursuers):
            override_ticks += 1
    return worst, contact_ticks, override_ticks


def _dist(a, b):
    pa, pb = a.GetWorldLocation(), b.GetWorldLocation()
    return math.sqrt((pa.GetX() - pb.GetX()) ** 2
                     + (pa.GetY() - pb.GetY()) ** 2
                     + (pa.GetZ() - pb.GetZ()) ** 2)


def test_pursuers_chasing_a_straight_line_target_do_not_fly_into_each_other(
        straight_line_chase):
    loop, player, pursuers = straight_line_chase

    worst, contact_ticks, _ = _run(loop, player, pursuers)

    assert contact_ticks == 0, (
        f"pursuers were inside one another on {contact_ticks} of {TICKS} ticks "
        f"(closest approach {worst:.2f} GU, hulls touch below {CONTACT_GU:.1f}). "
        "Chasing one target down a straight line converges their paths and "
        "nothing pushed them apart."
    )


def test_avoidance_actually_engages_in_that_scene(straight_line_chase):
    """Guard against the above passing for the wrong reason. If avoidance never
    runs, the first test is only measuring whether the ships happened to miss --
    which is exactly how this shipped broken."""
    loop, player, pursuers = straight_line_chase

    _, _, override_ticks = _run(loop, player, pursuers)

    assert override_ticks > 0, (
        "collision avoidance never overrode a course in a scene built to force "
        "convergence. AvoidObstacles.TestCourseOverride is returning "
        "(None, None) -- it is finding no obstacles to avoid."
    )
