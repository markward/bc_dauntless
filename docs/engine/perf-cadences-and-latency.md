# Perf cadences that are also gameplay latency

Four things that used to run every tick now run on a cadence. Each was landed as
a performance win, and **each is also a behaviour change**. Read this before
reporting a delayed in-game reaction as a bug — the delay may be the design.

This file is the detail; `CLAUDE.md` carries only the one-line pointer.

---

## The four cadences

| What | Constant | Period | Where |
|---|---|---|---|
| Shield charging | `SHIELD_CHARGE_PERIOD_S` | 0.5 s | `engine/appc/subsystems.py:115` |
| Target-list poll | (panel throttle) | 0.5 s / 2 Hz | `engine/ui/panel_registry.py` |
| Avoidance re-decision | `AVOID_EVADING_UPDATE_DELAY_S` | 0.25 s / 4 Hz | `engine/appc/ai_optimized.py:138` |
| AI tree sleep | `AI_MAX_SLEEP_TICKS` | up to 4 ticks (~66 ms) | `engine/appc/ai_driver.py:1548` |

The last two are environment-overridable — `DAUNTLESS_AVOID_EVADE_DELAY_S` and
`DAUNTLESS_AI_MAX_SLEEP`. Setting the avoid delay to `0.0` restores the SDK's
exact every-tick behaviour, which is the cleanest way to test whether a
suspected latency bug is this cadence.

---

## 1. Shields charge every 0.5 s, not per tick

Total charge is **conserved** — the banked interval is applied whole — but regen
is a staircase rather than a ramp. Consequences:

- The HUD shield bar and the bubble intensity **step** visibly.
- `_shield_watchers` crossing events (`ConditionSingleShieldBelow` and friends)
  fire **up to 0.5 s late** — a 30× latency increase on shield-threshold AI
  reactions.

**Evidence tier:** the 0.5 s figure is BC's own, from `stbc_reference`
`spec/ShieldFacingDamage.md §6.1`, graded **reviewed-not-tested**. That is
RE-tier, *not* TESTED — the routine was read, never executed.

Related: BC applies beam damage in 0.5 s pulses matching this same tick, because
the pulse refreshes the `m_fraction` that the shield pass-through ramp reads.
See [`shield-facing-and-splash.md`](shield-facing-and-splash.md).

## 2. The target list polls at 2 Hz

It is additionally marked due immediately on its own events, on a visibility
flip, and (from the host loop) whenever the engine changes the player's target
or subsystem behind its back.

⚠️ **Do not put a game-state mutation inside `render_payload`.**
`_reconcile_subsystem_lock` was there, and the throttle silently gave the
player's phasers up to 0.5 s aiming at an already-destroyed subsystem. It is now
`reconcile_subsystem_lock()` at module scope
(`engine/ui/target_list_view.py:523`), driven per-frame from the host loop
(`engine/host_loop.py:7778`) beside `clear_undetectable_player_lock`.

One accepted wrinkle, documented at `panel_registry.py:24-36`: the panel
throttle runs on **wall** clock while the shield period accumulates **game** dt,
so the two decouple under a time scale. It only ever fails safe — a slowed sim
ticks shields slower than wall clock, so the panel over-polls rather than
missing a change.

## 3. An evading ship re-decides avoidance at 4 Hz

`AVOID_EVADING_UPDATE_DELAY_S = 0.25` is BC's own commented-out
`fMinimumUpdateDelay` — `sdk/Build/scripts/AI/Preprocessors.py:1624` literally
reads `0.0 # 0.25`. Against the `fPredictionTime` lookahead a 0.25 s stale
decision is 1.7% of the horizon.

**It does cost separation, for some phases — and the phase depends on object
creation order.** Each ship's first evasion reschedule is offset by
`ai_optimized._phase_factor`, a hash of `ship.GetObjID()`; object ids come off
one process-wide counter (`engine.core.ids._counter`), so which phases a crowd
lands on is set by how many objects were created before it. Measured over a
sweep of 41 pinned counter bases (same crowd, SDK-exact `0.0` vs `0.25`):

| | fast/slow closest-approach ratio |
|---|---|
| min | 0.696 |
| median | 0.991 |
| max | 1.014 |

The `0.0` run is identical at every phase; only the `0.25` run varies. The
minimum closest approach at `0.25` was **45.4 GU** against a combined radius
of **40 GU** — the margin shrinks by up to ~30% for unlucky phases, but no
phase produced an overlap. A single slow/fast pair at whatever phase the test
order happened to give (the old guard) failed its `fast > 0.75 × slow` check
for 2 of the 41 phases.

The value is **pinned by a test** that runs a subset of that sweep —
`tests/integration/test_avoid_cadence_still_clears.py::test_the_cadence_pays_for_itself_and_costs_no_separation`
(no overlap and the scan saving at every phase; median ratio ≥ 0.75). Its
docstring and `PHASE_SWEEP_BASES` hold the full numbers. Re-run it before
changing the value. The sweep is one synthetic converging crowd, ticked
headlessly through `tick_all_ai` with the default `AI_MAX_SLEEP_TICKS` in
effect in both arms; it varies only the avoidance delay. It is not the live
measurement of the two cadences together that the section below says is still
missing — see
[Cadences 3 and 4 COMPOUND](#️-cadences-3-and-4-compound--and-the-combination-is-unmeasured)
below.

### Head-on charge: the cadence does not cost the dodge (2026-10-08)

A single ship charging head-on at an evading Galaxy (the `_scene` in
`test_avoid_cadence_still_clears.py`), swept over 32 pinned object-id bases.
Closest approach against a combined radius of 40 GU, charger at its scripted
5 GU/s:

| scan | `0.25` (shipped) | `0.0` (SDK-exact) |
|---|---|---|
| engine scan (opt-in) | 0/32 overlap, min 62.72 | 0/32, min 45.42 |
| shipped SDK scan, flee-direction stream rewound | 0/32, min 57.36 | 4/32 overlap, min 37.66 |
| shipped SDK scan, stream running (as in a game) | 0/32, min 42.03 | 4/32 overlap, min 36.95 |

What ships (SDK scan + the 0.25 s cadence) clears at every phase. The cadence
widens the dodge rather than costing it. Two things remain worth knowing:

* **The worst shipped case is thin: 42.03 GU, 2 GU clear.** That is with the
  `TGPoint3_GetRandomUnitVector` stream left running, as in a game. The SDK
  scan draws its 8 flee directions from it, and that stream moves a run by
  about ±20 GU.
* **The every-tick setting overlaps in 4/32 phases.** We don't ship it. In BC
  this Python body never runs (the native AvoidObstacles replaces it and has
  not been recovered), so `0.0` is not "what BC does" either.

**Retracted.** Two OPEN findings were recorded here earlier the same day: "the
cadence costs the opt-in engine scan its head-on dodge (8/32 graze)" and "the
shipped dodge is marginal whatever the cadence (about half overlap with the
stream running)". Both were measured on a broken scene. Since `4109f3f2` the
engine drifts a no-AI ship on its scripted velocity, but the test still nudged
the charger by hand as well, so it closed at **10 GU/s** (measured). Re-running
the identical sweep on that scene reproduces the retracted table exactly, and
with the double-move removed the grazes vanish.
`test_the_charger_closes_at_its_scripted_speed` now pins the speed.

The original head-on test asserted an absolute "closest > sum of radii" at
whatever phase the suite's id counter gave it. On the double-speed scene that
straddled 40 GU, so it went red on main at `6811cbf8` when three unrelated host
tests moved the counter. It is now
`test_the_cadence_costs_a_head_on_dodge_no_worst_case_separation`: the shipped
binding, phase and stream pinned, asserting only the cadence's claim (worst
cadenced closest ≥ worst SDK-exact closest over the sweep).

### ⚠️ Until 2026-08-28 this described a configuration nobody ran

The cadence, and the `_phase_factor` herd-breaker beside it, were applied only
in `_replace_avoid_obstacles` — i.e. to the *engine* scan, which is opt-in
behind `DAUNTLESS_ENGINE_AVOIDANCE=1` and **off by default**. The default SDK
path got neither.

That went unnoticed because avoidance was **wholly inert**:
`ProximityManager.GetNextObject` was a hardcoded `return None`, so BC's
`GetNearObjects` / `GetNextObject` / `EndObjectIteration` walk exited before its
first iteration and `AvoidObstacles.TestCourseOverride` always reported
"nothing to avoid."

Both are fixed; both now apply on the default path. Re-measured cost: **+0.27 ms
of sim per tick at 16 and at 32 ships** — it was +1.4 ms / +3.4 ms with the
cadence missing.

## 4. A ship's AI tree may sleep up to `AI_MAX_SLEEP_TICKS`

Default 4 ticks (~66 ms at 60 Hz). **`ForceUpdate` is therefore no longer
"next tick."**

---

## ⚠️ Cadences 3 and 4 COMPOUND — and the combination is unmeasured

Avoidance now lives *inside* the sleeping AI tree: `tick_collision_avoidance`
was removed from `GameLoop.tick` (see `engine/core/loop.py:63-71`, and
[`avoidance-duplication.md`](avoidance-duplication.md) for why running it there
made missions pay for avoidance twice and discard the first answer). The
standalone `tick_collision_avoidance` function still exists in
`engine/appc/collision_avoidance.py` but is now **called only from tests**.

So worst-case re-decision latency is **0.25 s of cadence + up to 66 ms of sleep
skew**.

**Each cadence was measured alone. The combination has never been measured
live.** This is the single largest unquantified behaviour risk in the perf work.
Treat the compounded figure as a hypothesis sitting next to numbers, which makes
it read more settled than it is.

To test: set `DAUNTLESS_AVOID_EVADE_DELAY_S=0` and `DAUNTLESS_AI_MAX_SLEEP=0`
and compare separation and reaction timing against the defaults in a live combat
scene (`DAUNTLESS_MISSION=engine.dev_missions.combat_stress`).

---

## Not a cadence, same trap: a long warp tunnel is the preload

Since the warp tunnel became the loading screen (2026-10-16,
`docs/superpowers/specs/2026-10-16-warp-tunnel-preload-design.md`), the
player's tunnel lasts its normal length **and then waits for the destination
to finish loading** (`engine/warp_preload.py`, held by `_HoldUntilAction` in
`engine/appc/warp.py`). On a slow machine that wait can run up to
`PRELOAD_CAP_S` = **30 s past the normal length** — 30 s of *sim ticks*
(`g_kRealtimeTimerManager`, frozen under pause, at most `MAX_FRAME_DT` per
render frame), so wall clock can be longer still. That is the preload, not a
hang. At the cap the warp releases anyway and prints
`[warp-preload] late: <items>` to stderr, naming what was still loading.
NPC warps never wait.
