"""The evading re-scan cadence must not cost a ship its dodge.

`ai_optimized.AVOID_EVADING_UPDATE_DELAY_S` restores AvoidObstacles'
commented-out `fMinimumUpdateDelay = 0.25`, so a ship that is ACTIVELY EVADING
re-decides 4x/s instead of 60x/s. That is only safe because a cadence-skipped
tick reproduces the last PS_SKIP_ACTIVE (ai_driver._tick_preprocessing's
else-branch), leaving the contained AI suppressed and the ship steering on the
TurnTowardDirection / SetImpulse setpoints already issued.

Nothing in the existing avoidance suite covered this. Those 110 tests all call
`tick_collision_avoidance()` -- the standalone driver -- which has no cadence
and no preprocessor at all. This file drives the REAL path: tick_all_ai over a
ship carrying an SDK AvoidObstacles node, swapped at bind time by
GetOptimizedVersion exactly as a mission's CreateAI builds it.
"""
import importlib
import sys

import pytest
import App
from engine.appc.ships import ShipClass_Create
from engine.appc.math import TGPoint3
from engine.appc.subsystems import HullSubsystem
from engine.appc.ship_motion import tick_all_ship_motion
from engine.appc.ai_driver import tick_all_ai
from engine.appc.objects import PhysicsObjectClass
from engine.appc import collision_avoidance as ca


def _load_galaxy(ship):
    App.g_kModelPropertyManager.ClearLocalTemplates()
    mod_name = "ships.Hardpoints.galaxy"
    if mod_name in sys.modules:
        importlib.reload(sys.modules[mod_name])
    else:
        importlib.import_module(mod_name)
    sys.modules[mod_name].LoadPropertySet(ship.GetPropertySet())
    ship.SetupProperties()


@pytest.fixture(autouse=True)
def _isolate():
    App.g_kSetManager._sets.clear()
    ca.reset_avoidance_state()
    yield
    App.g_kSetManager._sets.clear()
    App.g_kModelPropertyManager.ClearLocalTemplates()
    for k in list(sys.modules):
        if k == "ships" or k.startswith("ships."):
            del sys.modules[k]


def _scene():
    """The head-on charge, built through a mission's own CreateAI shape."""
    pSet = App.SetClass_Create()
    pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet

    attacker = ShipClass_Create("Galaxy")
    _load_galaxy(attacker)
    attacker.SetWorldLocation(TGPoint3(0, 0, 0))
    attacker.SetRadius(20.0)
    pSet.AddObjectToSet(attacker, "Attacker")
    attacker.SetImpulse(1.0, TGPoint3(0, 1, 0),
                        PhysicsObjectClass.DIRECTION_MODEL_SPACE)

    # Exactly AI/Player/InterceptTarget.CreateAI's construction: a contained
    # PlainAI wrapped in a PreprocessingAI running AvoidObstacles.Update.
    # SetContainedAI is the GetOptimizedVersion substitution point, so the
    # engine node is installed by the SDK's own mechanism, not by the test.
    import AI.Preprocessors
    script = AI.Preprocessors.AvoidObstacles()
    node = App.PreprocessingAI_Create(attacker, "AvoidObstacles")
    node.SetInterruptable(1)
    node.SetPreprocessingMethod(script, "Update")
    attacker.SetAI(node)

    charger = ShipClass_Create("Charger")
    h = HullSubsystem("Hull")
    h.SetMaxCondition(1e9)
    charger._hull = h
    charger.SetWorldLocation(TGPoint3(0, 260, 0))
    charger.SetRadius(20.0)
    pSet.AddObjectToSet(charger, "Charger")
    return pSet, attacker, charger


def _run(attacker, charger, ticks=2400):
    charger_speed = 5.0
    dt = 1.0 / 60.0
    closest = 1e18
    t = 0.0
    for _ in range(ticks):
        p = charger.GetWorldLocation()
        charger.SetWorldLocation(TGPoint3(p.x, p.y - charger_speed * dt, p.z))
        charger.SetVelocity(TGPoint3(0, -charger_speed, 0))
        ca.invalidate_obstacle_snapshot()
        t += dt
        tick_all_ai(game_time=t)
        tick_all_ship_motion(dt)
        d = (charger.GetWorldLocation()
             - attacker.GetWorldLocation()).Length()
        closest = min(closest, d)
    return closest


def test_a_cadenced_ship_still_clears_a_head_on_charge():
    """The dodge itself, through the preprocessor path with the cadence live."""
    pSet, attacker, charger = _scene()
    closest = _run(attacker, charger)
    sum_r = attacker.GetRadius() + charger.GetRadius()
    assert closest > sum_r, (
        f"cadenced avoidance failed to dodge: closest={closest:.1f} GU, "
        f"sum_radii={sum_r:.1f} GU")


def _crowd(n=8, ring_r=90.0):
    """N ships on a ring, every one commanded straight at the centre.

    The single-charger scenario dodges from 188 GU after ONE override tick --
    it clears by such a margin that the cadence never matters, so it cannot
    test the cadence. A crowd converging on a point is what the 100-ship scene
    actually looks like: ships evade continuously, re-entering each other's
    check radius as they scatter, which is exactly the state where
    fMinimumUpdateDelay is the knob doing the work.
    """
    import math
    import AI.Preprocessors

    pSet = App.SetClass_Create()
    pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet

    ships = []
    for i in range(n):
        a = 2.0 * math.pi * i / n
        sh = ShipClass_Create("S%d" % i)
        _load_galaxy(sh)
        sh.SetWorldLocation(TGPoint3(ring_r * math.cos(a),
                                     ring_r * math.sin(a), 0.0))
        sh.SetRadius(20.0)
        pSet.AddObjectToSet(sh, "S%d" % i)
        # Aim at the centre: -radial, in model space via a heading command.
        sh.SetImpulse(1.0, TGPoint3(0, 1, 0),
                      PhysicsObjectClass.DIRECTION_MODEL_SPACE)
        sh.TurnTowardDirection(TGPoint3(-math.cos(a), -math.sin(a), 0.0))

        script = AI.Preprocessors.AvoidObstacles()
        node = App.PreprocessingAI_Create(sh, "AvoidObstacles")
        node.SetInterruptable(1)
        node.SetPreprocessingMethod(script, "Update")
        sh.SetAI(node)
        ships.append(sh)
    return pSet, ships


def _run_crowd(ships, ticks=900):
    dt = 1.0 / 60.0
    t = 0.0
    closest = 1e18
    for _ in range(ticks):
        ca.invalidate_obstacle_snapshot()
        t += dt
        tick_all_ai(game_time=t)
        tick_all_ship_motion(dt)
        for i in range(len(ships)):
            for j in range(i + 1, len(ships)):
                d = (ships[i].GetWorldLocation()
                     - ships[j].GetWorldLocation()).Length()
                if d < closest:
                    closest = d
    return closest


def _run_crowd_scan_profile(ships, ticks=300):
    """Per-tick scan counts, so the PEAK is visible and not just the mean."""
    dt = 1.0 / 60.0
    t = 0.0
    per_tick = []
    for _ in range(ticks):
        ca.invalidate_obstacle_snapshot()
        t += dt
        before = ca._SCAN_COUNT[0]
        tick_all_ai(game_time=t)
        tick_all_ship_motion(dt)
        per_tick.append(ca._SCAN_COUNT[0] - before)
    return per_tick


def test_scans_do_not_all_land_on_the_same_tick():
    """The thundering herd.

    fMinimumUpdateDelay == fMaximumUpdateDelay == 0.25 and the driver
    reschedules as `game_time + interval`, so the cadence is a pure PERIOD with
    no phase: ships that are ever due together stay due together forever, and
    ships spawned in the same frame start that way. Before the first-schedule
    phase offset (ai_optimized._phase_factor) this scene measured
    [8,0,0,...,0,8,0,...] -- the MEAN dropped 15x but the per-tick PEAK was
    unchanged, so the frame-time spike the cadence exists to flatten survived
    intact.

    Ignores the first tick: everything is genuinely due at t=0 (that is the
    node's initial schedule, not a herd), and the offset applies to the
    reschedule that follows it.

    Measured on this scene: peak 8 -> 2 scans per tick, mean unchanged (the
    same total work, spread). The assertion stays at "not all of them" rather
    than pinning 2, because the phase a ship lands in depends on its object id
    and ids move whenever ship construction allocates a different number of
    objects — the structural claim is what matters here.
    """
    App.g_kSetManager._sets.clear()
    ca.reset_avoidance_state()
    pSet, ships = _crowd(n=8)
    per_tick = _run_crowd_scan_profile(ships, ticks=300)[1:]
    assert sum(per_tick) > 0, "nothing re-scanned; the scene is not exercising the cadence"
    assert max(per_tick) < len(ships), (
        "every ship still re-scans on the same tick (peak %d of %d) -- the "
        "first-schedule phase offset is not spreading them"
        % (max(per_tick), len(ships)))


def _measure(delay, ticks=900):
    from engine.appc import ai_optimized
    saved = ai_optimized.AVOID_EVADING_UPDATE_DELAY_S
    ai_optimized.AVOID_EVADING_UPDATE_DELAY_S = delay
    ai_optimized._ENGINE_AVOIDANCE_CLASSES.clear()
    App.g_kSetManager._sets.clear()
    ca.reset_avoidance_state()
    try:
        pSet, ships = _crowd()
        before = list(ca._SCAN_COUNT)
        closest = _run_crowd(ships, ticks=ticks)
        return {
            "closest": closest,
            "scans": ca._SCAN_COUNT[0] - before[0],
            "overriding": ca._SCAN_COUNT[1] - before[1],
            "sum_r": 40.0,
        }
    finally:
        ai_optimized.AVOID_EVADING_UPDATE_DELAY_S = saved
        ai_optimized._ENGINE_AVOIDANCE_CLASSES.clear()


def test_a_converging_crowd_never_overlaps_with_the_cadence_live():
    """The real claim: sustained mutual evasion still keeps ships apart."""
    r = _measure(0.25)
    assert r["overriding"] > 100, (
        "ships barely evaded (%d override ticks); the scenario is not "
        "exercising the cadence" % r["overriding"])
    assert r["closest"] > r["sum_r"], (
        "cadenced avoidance let ships overlap: closest=%.1f GU, "
        "sum_radii=%.1f GU" % (r["closest"], r["sum_r"]))


def test_the_cadence_pays_for_itself_and_costs_no_separation():
    """Differential against SDK-exact 0.0, on one scenario, both directions.

    An absolute scan threshold is not a real guard -- the single-charger
    scenario returned 40 scans at BOTH settings, so a threshold test there
    would have 'passed' while proving nothing. Run the same crowd twice and
    require the saving to show up as a difference.
    """
    slow = _measure(0.0)
    fast = _measure(0.25)

    assert fast["scans"] < slow["scans"] * 0.5, (
        "cadence is not gating: %d scans at 0.25 s vs %d at 0.0 s"
        % (fast["scans"], slow["scans"]))
    # Separation must not degrade. Not "identical" -- a different re-decision
    # schedule genuinely produces a different flight path -- but the safety
    # property (no overlap) has to survive, and the margin must not collapse.
    assert fast["closest"] > fast["sum_r"]
    assert slow["closest"] > slow["sum_r"]
    assert fast["closest"] > slow["closest"] * 0.75, (
        "cadence cut the separation margin: %.1f GU at 0.25 s vs %.1f GU at "
        "0.0 s" % (fast["closest"], slow["closest"]))
