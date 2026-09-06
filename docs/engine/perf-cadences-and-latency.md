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

Measured **not** to degrade separation at realistic radii, but the value is
**pinned by a test** — re-run the separation probes before changing it.

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
