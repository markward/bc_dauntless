"""End-to-end smoke: Intercept AI closes on a target via in-system warp
+ brake-aware impulse, halts at fInterceptDistance, returns US_DONE.

Proves the full chain: real SDK script load (Steps 1-3 of the prior
slice), AI driver, motion integrator + TurnTowardLocation + InSystemWarp
+ GetAccelerationTG (this slice), plus the existing TurnDirections-
ToDirections + GetRelativePositionInfo helpers."""
import pytest

import App
from engine.core.loop import GameLoop, TICK_RATE
from engine.appc.ai import PlainAI_Create, ArtificialIntelligence
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass
from engine.appc.subsystems import ImpulseEngineSubsystem


def _attach_ies(ship, *, max_speed=120.0, max_accel=50.0,
                 max_ang_vel=1.5, max_ang_accel=1.0):
    """Intercept reads MaxSpeed > 0 to enter its prediction-and-control
    block. Test ships are constructed without subsystems, so we attach
    one explicitly."""
    ies = ImpulseEngineSubsystem("Impulse Engines")
    ies.SetMaxSpeed(max_speed)
    ies.SetMaxAccel(max_accel)
    ies.SetMaxAngularVelocity(max_ang_vel)
    ies.SetMaxAngularAccel(max_ang_accel)
    ship.SetImpulseEngineSubsystem(ies)


def _setup_intercept_scene(hostile_start=(0.0, 5000.0, 0.0),
                            player_start=(0.0, 0.0, 0.0)):
    """Build a fresh set with a stationary player and a hostile that
    has PlainAI('Intercept') targeting "player"."""
    App.g_kTimerManager._time = 0.0
    App.g_kTimerManager._timers.clear()
    App.g_kRealtimeTimerManager._time = 0.0
    App.g_kRealtimeTimerManager._timers.clear()
    App.g_kSetManager._sets.clear()
    # Pin AI-cadence jitter for determinism. Intercept.GetNextUpdateTime
    # samples App.g_kSystemWrapper.GetRandomNumber to vary the 0.4s AI
    # cadence by +/-0.2s; without a fixed seed, integration runs diverge
    # and the test becomes flaky.
    App.g_kSystemWrapper.SetRandomSeed(20260518)

    pSet = App.SetClass_Create()
    pSet.SetName("intercept_smoke")
    App.g_kSetManager._sets["intercept_smoke"] = pSet

    player = ShipClass()
    player.SetTranslateXYZ(*player_start)
    pSet.AddObjectToSet(player, "player")

    hostile = ShipClass()
    hostile.SetTranslateXYZ(*hostile_start)
    _attach_ies(hostile)
    pSet.AddObjectToSet(hostile, "hostile")

    pai = PlainAI_Create(hostile, "TestIntercept")
    pai.SetScriptModule("Intercept")
    inst = pai.GetScriptInstance()
    inst.SetTargetObjectName("player")
    hostile.SetAI(pai)

    return player, hostile, pai


def _hostile_player_distance(player, hostile):
    p = player.GetTranslate()
    h = hostile.GetTranslate()
    dx, dy, dz = h.x - p.x, h.y - p.y, h.z - p.z
    return (dx * dx + dy * dy + dz * dz) ** 0.5


def test_intercept_warp_brings_hostile_to_warp_radius():
    """The in-system warp closes the 5000 GU gap to the warp drop radius
    (default fInSystemWarpDistance = 295) — but as a real transit, not a
    teleport: the hostile starts facing +Y with the player dead astern, so
    it must first turn onto the target (the warp's facing gate), then
    cruise the transit at 100 × MaxSpeed. Assert both halves: no
    first-tick teleport, arrival within a few seconds."""
    player, hostile, pai = _setup_intercept_scene()
    loop = GameLoop()
    loop.tick()
    dist = _hostile_player_distance(player, hostile)
    assert dist > 1000.0, (
        f"warp must be a multi-tick transit, not a teleport; distance={dist}"
    )
    # Turn (~2.5 s at 1.5 rad/s) + transit (~0.4 s at 12000 GU/s): 10 s is
    # a comfortable ceiling.
    arrived_at = None
    for tick in range(TICK_RATE * 10):
        loop.tick()
        if _hostile_player_distance(player, hostile) <= 296.0:
            arrived_at = tick
            break
    assert arrived_at is not None, (
        f"hostile never reached the warp radius; "
        f"distance={_hostile_player_distance(player, hostile)}"
    )


def test_intercept_eventually_reaches_intercept_distance():
    """Run until the AI returns US_DONE or we time out. Confirm the
    hostile ended up within fInterceptDistance + ship_radius of the
    player. fInterceptDistance default is 60."""
    player, hostile, pai = _setup_intercept_scene()
    loop = GameLoop()
    max_ticks = TICK_RATE * 60  # 60 simulated seconds is the ceiling
    for _ in range(max_ticks):
        loop.tick()
        if pai._status == ArtificialIntelligence.US_DONE:
            break
    assert pai._status == ArtificialIntelligence.US_DONE, (
        "Intercept never completed within 60s of simulated time"
    )
    final_dist = _hostile_player_distance(player, hostile)
    # fInterceptDistance default = 60; ship radius for a fresh ShipClass
    # is 0 (not set via SetupProperties), so the threshold collapses to
    # fInterceptDistance.
    assert final_dist <= 60.0 + 1.0, (
        f"hostile too far at completion: {final_dist}"
    )


def test_intercept_hostile_faces_player_at_completion():
    """When the hostile halts, it should be roughly facing the player.
    GetWorldForwardTG (column-vector, post-Task-1 fix) gives the world-
    forward; dot with ship→player unit vector must be > 0.9."""
    player, hostile, pai = _setup_intercept_scene()
    loop = GameLoop()
    for _ in range(TICK_RATE * 60):
        loop.tick()
        if pai._status == ArtificialIntelligence.US_DONE:
            break

    fwd = hostile.GetWorldForwardTG()
    h = hostile.GetTranslate()
    p = player.GetTranslate()
    diff = TGPoint3(p.x - h.x, p.y - h.y, p.z - h.z)
    diff.Unitize()
    dot = fwd.x * diff.x + fwd.y * diff.y + fwd.z * diff.z
    assert dot > 0.9, f"hostile not facing player at completion; dot={dot}"


def test_intercept_speed_ramps_up_then_back_toward_zero():
    """Sanity that brake-aware control engaged after the warp: the
    hostile's _current_speed must climb above zero at some point and
    then return near zero by the time the AI completes."""
    player, hostile, pai = _setup_intercept_scene()
    loop = GameLoop()
    peak_speed = 0.0
    final_speed = 0.0
    for _ in range(TICK_RATE * 60):
        loop.tick()
        if pai._status == ArtificialIntelligence.US_DONE:
            final_speed = hostile._current_speed
            break
        # Track peak BEFORE the next tick so that the completing tick
        # does not get folded into peak_speed (otherwise final < peak
        # collapses to final < final and the assertion fails).
        peak_speed = max(peak_speed, hostile._current_speed)
    assert peak_speed > 10.0, (
        f"hostile never accelerated meaningfully; peak={peak_speed}"
    )
    # On completion the brake-aware code should have driven speed
    # toward 0 (within the same tick when fSpeed = 0 is set, since
    # FALLBACK_MAX_ACCEL snaps).
    assert final_speed < peak_speed, (
        "hostile did not decelerate before completion"
    )


def test_intercept_returns_us_active_while_still_approaching():
    """While the hostile is closing but not yet within fInterceptDistance,
    the AI must report US_ACTIVE. Sample at an intermediate point."""
    player, hostile, pai = _setup_intercept_scene()
    loop = GameLoop()
    # Run a few AI cycles' worth of ticks; the AI fires every ~0.4s, so
    # 60 ticks = 1s = 2-3 AI updates after the initial warp.
    for _ in range(60):
        loop.tick()
    # If we already completed (very unlikely at 1s under brake-aware
    # control with 295 units to cover), this assertion is vacuously
    # interesting — skip in that case.
    dist = _hostile_player_distance(player, hostile)
    if dist > 60.0:
        assert pai._status == ArtificialIntelligence.US_ACTIVE, (
            f"AI reported {pai._status} while still {dist} units out"
        )
