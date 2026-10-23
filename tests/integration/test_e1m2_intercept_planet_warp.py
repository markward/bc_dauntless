"""Intercepting a planet must not warp the player inside it.

Helm's Intercept (and Ctrl+I) puts AI.Player.InterceptTarget on the player.
Its SDK Intercept (AI/PlainAI/Intercept.py) aims for the target's radius +
60 GU and, far away, calls ``pShip.InSystemWarp(pObject, 295.0)``. BC stops
that warp at the target's RADIUS + the standoff (RE: ShipClass::InSystemWarp,
engage while ``distance > target_radius + standoff``; the stbc-oracle
``warp_*`` captures, asked 50 GU at a 4.37 GU Galaxy, drop out 52-54 GU from
its centre). Stopping 295 GU from the CENTRE put the ship deep inside our
map-rescaled planets: E1M2's Haven is 90 GU in BC's script and 1800 GU on
the Vesuvi map, so the warp ended ~280 GU from its centre and the AI then
flew back out through the planet.
"""
import math

import App
from engine.core.loop import GameLoop, TICK_DELTA
from tests.helpers import headless_mission


E1M2_MODULE = "Maelstrom.Episode1.E1M2.E1M2"
# Intercept's own approach distance (AI/Player/InterceptTarget.py).
INTERCEPT_DISTANCE_GU = 60.0
FINISH_TOLERANCE_GU = 30.0
RUN_S = 150.0
# The host seeds a ship's GetRadius() when it realises the model
# (host_loop._seed_ship_radius); headless never realises, so the player would
# read 0 -- and SDK Intercept finishes only once it is within its OWN radius
# of the destination, so a 0 radius never finishes. A Galaxy's radius
# (stbc-oracle warp_* captures' target_radius) keeps the order's live ending.
GALAXY_RADIUS_GU = 4.366


def _distance(a, b) -> float:
    pa, pb = a.GetWorldLocation(), b.GetWorldLocation()
    return math.dist((pa.x, pa.y, pa.z), (pb.x, pb.y, pb.z))


def _intercept(body_name):
    """Load E1M2, give the player Helm's Intercept AI on ``body_name`` and
    fly it until the order finishes. Returns (body radius, distances from the
    body's centre per tick, whether an in-system warp ran, the distance when
    the order finished or None)."""
    headless_mission.load(E1M2_MODULE)
    import AI.Player.InterceptTarget
    player = App.Game_GetCurrentPlayer()
    body = App.g_kSetManager.GetSet("Vesuvi6").GetObject(body_name)
    assert body is not None and player is not None
    player.SetRadius(GALAXY_RADIUS_GU)
    radius = body.GetRadius()
    # The map rescale this bug hides behind (BC authors Haven at 90 GU).
    assert radius > 295.0, radius
    start = _distance(player, body)
    assert start > radius + 295.0, (start, radius)

    player.SetTarget(body_name)
    player.SetAI(AI.Player.InterceptTarget.CreateAI(player, body))
    loop = GameLoop()
    distances, warped, finished = [], False, None
    for _ in range(int(round(RUN_S / TICK_DELTA))):
        loop.tick()
        warped = warped or player.IsDoingInSystemWarp()
        distances.append(_distance(player, body))
        if player.GetAI() is None:
            # Done. From here the live host's player control flies the ship
            # (the throttle the player set); headless has no one at the helm.
            finished = distances[-1]
            break
    return radius, distances, warped, finished


def _assert_never_inside_and_finishes_at_standoff(body_name):
    radius, distances, warped, finished = _intercept(body_name)
    assert warped, "the intercept never in-system warped"
    closest = min(distances)
    assert closest >= radius, (
        f"the ship went {radius - closest:.0f} GU inside {body_name} "
        f"(closest {closest:.0f} GU from its centre, radius {radius:.0f})")
    goal = radius + INTERCEPT_DISTANCE_GU
    assert finished is not None, (
        f"the intercept never finished; last {distances[-1]:.0f} GU from "
        f"{body_name}'s centre, expected ~{goal:.0f}")
    assert abs(finished - goal) <= FINISH_TOLERANCE_GU, (
        f"finished {finished:.0f} GU from {body_name}'s centre, "
        f"expected ~{goal:.0f}")


def test_intercepting_haven_stops_outside_it():
    _assert_never_inside_and_finishes_at_standoff("Haven")


def test_intercepting_moon_stops_outside_it():
    _assert_never_inside_and_finishes_at_standoff("Moon 1")
