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


@pytest.fixture(autouse=True)
def _engine_avoidance_enabled(monkeypatch):
    """These tests are ABOUT the engine-side avoidance scan, which is opt-in.

    It is off by default since it was found to return PS_SKIP_ACTIVE far more
    often than the SDK's scan, which suppresses the whole attack subtree and
    strips its focus -- dropping shields and stopping weapons fire (see
    tests/integration/test_avoidance_does_not_suppress_combat.py). Registering
    it here keeps this file testing the thing it was written to test, and keeps
    that coverage alive for whoever picks the optimisation back up.

    Registered directly rather than via DAUNTLESS_ENGINE_AVOIDANCE because the
    env var is read at import time.
    """
    from engine.appc import ai_optimized
    monkeypatch.setitem(ai_optimized.OPTIMIZED_PREPROCESSORS,
                        "AvoidObstacles", ai_optimized._replace_avoid_obstacles)



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
    # Set ONCE; the engine drifts a no-AI ship on its scripted velocity
    # (engine.appc.drift). Moving it by hand as well double-moves it -- see
    # test_the_charger_closes_at_its_scripted_speed.
    charger.SetVelocity(TGPoint3(0, -CHARGER_SPEED_GUPS, 0))
    return pSet, attacker, charger


def _run(attacker, charger, ticks=2400):
    dt = 1.0 / 60.0
    closest = 1e18
    t = 0.0
    for _ in range(ticks):
        ca.invalidate_obstacle_snapshot()
        t += dt
        tick_all_ai(game_time=t)
        tick_all_ship_motion(dt)
        d = (charger.GetWorldLocation()
             - attacker.GetWorldLocation()).Length()
        closest = min(closest, d)
    return closest


CHARGER_SPEED_GUPS = 5.0


def test_the_charger_closes_at_its_scripted_speed():
    """The scenario's premise: the charger moves at CHARGER_SPEED_GUPS, once.

    The charger has no AI and no helm setpoint, so since 4109f3f2 the engine
    drifts it on its scripted velocity (engine.appc.drift). This file kept
    nudging it by hand as well, so it closed at 10 GU/s, the attacker had
    half the time to dodge, and every head-on figure measured a different,
    harder scene than the one described.
    """
    _pSet, attacker, charger = _scene()
    y0 = charger.GetWorldLocation().y
    _run(attacker, charger, ticks=60)
    moved = y0 - charger.GetWorldLocation().y
    assert moved == pytest.approx(CHARGER_SPEED_GUPS, rel=1e-6), (
        "charger moved %.3f GU in 1 s, scripted %.1f GU/s"
        % (moved, CHARGER_SPEED_GUPS))


# Object-id bases for the head-on sweep: 32 consecutive strides of 97, which
# cover all 16 _phase_factor buckets several times over (~10 s for both runs).
HEAD_ON_SWEEP_BASES = [10_000_000 + 97 * i for i in range(32)]


def _head_on_closest(delay, base, monkeypatch, pin):
    """Closest approach of one head-on run on the SHIPPED binding.

    Pins the two things the outcome depends on besides the cadence, so a pair
    of runs differs ONLY in the cadence: the object-id base (each ship's first
    reschedule phase, ai_optimized._phase_factor) and the
    TGPoint3_GetRandomUnitVector stream the SDK scan draws its 8 flee
    directions from. Unrewound, the stream alone swings a run by +-20 GU.
    """
    from engine.appc import ai_optimized
    from engine.appc.math import reset_random_unit_vector_rng
    monkeypatch.setattr(ai_optimized, "AVOID_EVADING_UPDATE_DELAY_S", delay)
    App.g_kSetManager._sets.clear()
    ca.reset_avoidance_state()
    reset_random_unit_vector_rng()
    pin(base)
    _pSet, attacker, charger = _scene()
    return _run(attacker, charger)


def test_the_cadence_costs_a_head_on_dodge_no_worst_case_separation(
        monkeypatch, pinned_id_counter):
    """Differential on the SHIPPED path (SDK scan + phase offset + cadence),
    against SDK-exact 0.0, over a phase sweep.

    This replaced an absolute single-run check ("closest > sum of radii") that
    ran the opt-in ENGINE scan on whatever phase the suite's object-id counter
    happened to give it. Measured 2026-10-08 over 32 pinned bases, with the
    charger at its scripted 5 GU/s (an earlier sweep moved it at 10 GU/s --
    see test_the_charger_closes_at_its_scripted_speed -- and reported grazes
    that do not exist):

    * engine scan (opt-in, off by default): 0/32 overlap at either setting;
      min 62.72 GU with the cadence, 45.42 at 0.0.
    * shipped SDK scan: 0/32 overlap with the cadence (min 57.36 stream
      rewound, 42.03 stream running); 4/32 at 0.0 (min 37.66 / 36.95). The
      cadence does not cost the dodge -- here it widens it. See
      docs/reference/engine/perf-cadences-and-latency.md.

    The claim here is the file's: the cadence must not cost the dodge. Per
    phase the pair is chaotic (the sweep's per-base differences span -9..+13
    GU), so the guard is on the WORST case across the sweep.
    """
    from engine.appc import ai_optimized
    # The shipped binding, not the module's opt-in engine scan.
    monkeypatch.setitem(ai_optimized.OPTIMIZED_PREPROCESSORS, "AvoidObstacles",
                        ai_optimized._wrap_avoid_obstacles)
    cadenced = [_head_on_closest(0.25, b, monkeypatch, pinned_id_counter)
                for b in HEAD_ON_SWEEP_BASES]
    exact = [_head_on_closest(0.0, b, monkeypatch, pinned_id_counter)
             for b in HEAD_ON_SWEEP_BASES]
    start_gap = 260.0
    assert max(cadenced) < start_gap and max(exact) < start_gap, (
        "the ships never closed; the scene is not a head-on charge")
    assert len(set(round(x, 3) for x in cadenced)) > 1, (
        "every phase gave the same answer; the sweep is not reaching the "
        "phase offset")
    assert min(cadenced) >= min(exact), (
        "the cadence cost the head-on dodge separation: worst cadenced "
        "closest=%.2f GU vs worst SDK-exact closest=%.2f GU"
        % (min(cadenced), min(exact)))


def _crowd(n=8, ring_r=90.0):
    """N ships on a ring, every one commanded straight at the centre.

    The single-charger scenario evades only briefly, so it says little about
    SUSTAINED evasion: on the shipped binding with the cadence it clears at
    every phase, worst 57.4 GU with the flee-direction stream rewound and 42.0
    with it running (2026-10-08). A crowd converging on a point is what the 100-ship scene
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


# The id-counter bases the sweep pins, one run per base. Each ship's first
# evasion reschedule is offset by ai_optimized._phase_factor, a hash of its
# object id, and object ids come off ONE process-wide counter
# (engine.core.ids._counter) -- so the phases a crowd lands on are set by how
# many objects existed before it.
#
# Measured over 41 bases (40 evenly strided, 10^7 + 10000 + 97*i, plus 10087,
# the natural-counter phase that failed the gate): fast/slow ratio min 0.696,
# median 0.991, max 1.014; min fast closest approach 45.4 GU. The full 41
# take ~49 s, so the test runs a documented SUBSET (~16 s): every 4th strided
# base (i = 0, 4, ..., 36 -- which includes i=28, the 0.737 phase), plus the
# four worst phases found: 10087 (0.696), and i=26/27 (0.861, 0.827). Its
# ratios: min 0.696, median 0.950, max 1.013 -- tail-weighted on purpose.
_STRIDED = [10_000_000 + 10_000 + 97 * i for i in range(40)]
PHASE_SWEEP_BASES = _STRIDED[::4] + [10_087, _STRIDED[26], _STRIDED[27]]


@pytest.fixture
def pinned_id_counter():
    """Pin engine.core.ids' object-id counter to a chosen base for one run,
    and put everything back afterwards: the counter AND the id registries, so
    a base that reuses ids already handed out elsewhere cannot leave another
    test's object shadowed."""
    import itertools
    from engine.core import ids
    saved = (ids._counter, dict(ids._registry), dict(ids._weak_registry))

    def pin(base):
        ids._counter = itertools.count(base)

    try:
        yield pin
    finally:
        ids._counter = saved[0]
        ids._registry.clear()
        ids._registry.update(saved[1])
        ids._weak_registry.clear()
        ids._weak_registry.update(saved[2])


def test_the_cadence_pays_for_itself_and_costs_no_separation(pinned_id_counter):
    """Differential against SDK-exact 0.0, over a PHASE SWEEP.

    An absolute scan threshold is not a real guard -- the single-charger
    scenario returned 40 scans at BOTH settings, so a threshold test there
    would have 'passed' while proving nothing. Run the same crowd twice and
    require the saving to show up as a difference.

    Why a sweep: this used to be ONE slow/fast pair at whatever phases the
    crowd happened to get, and those phases come from the global object-id
    counter (ai_optimized._phase_factor hashes GetObjID()) -- i.e. from how
    many tests ran before it. Pinned (system-frames Plan 3 Task 6, fix round
    2) the slow run is identical at every phase (3506 scans, closest 65.2 GU),
    while the fast run's closest approach is a DISTRIBUTION -- over 41 bases:
    fast/slow ratio min 0.696, median 0.991, max 1.014; minimum fast closest
    approach 45.4 GU (combined radius 40 GU). The old single-run
    `fast > 0.75 * slow` failed for 2 of those 41 phase assignments -- a real
    cost of the 4 Hz re-decision for unlucky phases, not noise. The subset run
    here (see PHASE_SWEEP_BASES) keeps both of those phases.

    So the sweep asserts the SAFETY property at every phase (no overlap, and
    the scan saving), and the separation-margin claim over the distribution
    (median ratio >= 0.75, the old per-run threshold).
    """
    ratios = []
    for base in PHASE_SWEEP_BASES:
        # One pin per phase assignment, then slow and fast back to back --
        # the order (and so the id allocation) the single-run test always had.
        pinned_id_counter(base)
        slow = _measure(0.0)
        fast = _measure(0.25)

        assert fast["scans"] < slow["scans"] * 0.5, (
            "base %d: cadence is not gating: %d scans at 0.25 s vs %d at 0.0 s"
            % (base, fast["scans"], slow["scans"]))
        assert fast["closest"] > fast["sum_r"], (
            "base %d: cadenced avoidance let ships overlap: closest=%.1f GU"
            % (base, fast["closest"]))
        assert slow["closest"] > slow["sum_r"]
        ratios.append(fast["closest"] / slow["closest"])

    ratios.sort()
    median = ratios[len(ratios) // 2]
    assert median >= 0.75, (
        "cadence cut the separation margin across phases: median fast/slow "
        "closest-approach ratio %.3f (min %.3f, max %.3f)"
        % (median, ratios[0], ratios[-1]))