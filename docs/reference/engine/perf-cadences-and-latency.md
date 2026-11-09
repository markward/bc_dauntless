# Perf cadences that are also gameplay latency

Eleven things that used to run every tick now run on a cadence (the table below). Each was landed as
a performance win, and **each is also a behaviour change**. Read this before
reporting a delayed in-game reaction as a bug — the delay may be the design.

This file is the detail; `CLAUDE.md` carries only the one-line pointer.

---

## The cadences (and one native stage)

| What | Constant | Period | Where |
|---|---|---|---|
| Shield charging | `SHIELD_CHARGE_PERIOD_S` | 0.5 s | `engine/appc/subsystems.py` (`SHIELD_CHARGE_PERIOD_S`) |
| Native subsystem stage (native only, not a cadence) | none (no switch) | every tick | `engine/appc/native_subsystems.py` (`step_all`), `native/src/combat/` (`subsystem_step.cc`) |
| Target-list poll | (panel throttle) | 0.5 s / 2 Hz | `engine/ui/panel_registry.py` |
| Radar poll | `SENSORS_POLL_S` | 0.05 s / 20 Hz, wall clock | `engine/ui/sensors_panel.py` (`PanelRegistry`) |
| Crew menu poll | `CREW_MENU_POLL_S` | 0.1 s / 10 Hz, wall clock | `engine/ui/crew_menu_panel.py` (`PanelRegistry`) |
| Player ship poll | `PLAYER_SHIP_POLL_S` | 0.1 s / 10 Hz, wall clock (role `player` only) | `engine/ui/ship_display_panel.py` (`PanelRegistry`) |
| Weapons poll | `WEAPONS_POLL_S` | 0.1 s / 10 Hz, wall clock | `engine/ui/weapons_display_panel.py` (`PanelRegistry`) |
| Contact list membership | sensor_dials sweep_period_s | 1.0 s game time + events | engine/appc/contact_refresh.py |
| Avoidance re-decision | `AVOID_EVADING_UPDATE_DELAY_S` | 0.25 s / 4 Hz | `engine/appc/ai_optimized.py` (`AVOID_EVADING_UPDATE_DELAY_S`) |
| AI tree sleep | `AI_MAX_SLEEP_TICKS` | up to 4 ticks (~66 ms) | `engine/appc/ai_driver.py` (`AI_MAX_SLEEP_TICKS`; the walk it gates is native, `native/src/host/aitree.cc`) |
| AI ship glow state poll | `AI_GLOW_POLL_S` | 0.05 s game time | `engine/appc/subsystem_glow.py` |
| Hum reallocation | `HUM_REALLOC_PERIOD_S` | 0.1 s wall + on scene switch / removal / death | `engine/audio/hum_allocator.py` |

The avoidance and AI-sleep cadences are environment-overridable — `DAUNTLESS_AVOID_EVADE_DELAY_S` and
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
See [`shield-facing-and-splash.md`](../../engine/shield-facing-and-splash.md).

## 2. The target list polls at 2 Hz

It is additionally marked due immediately on its own events, on a visibility
flip, and (from the host loop) whenever the engine changes the player's target
or subsystem behind its back.

⚠️ **Do not put a game-state mutation inside `render_payload`.**
`_reconcile_subsystem_lock` was there, and the throttle silently gave the
player's phasers up to 0.5 s aiming at an already-destroyed subsystem. It is now
`reconcile_subsystem_lock()` at module scope
(`engine/ui/target_list_view.py:396`), driven per-frame from the host loop
(`engine/host_loop.py`, the `reconcile_subsystem_lock()` call in `run()`'s frame loop) beside `clear_undetectable_player_lock`.

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

## 5. The contact list is re-derived on the sensor sweep and on events

`host_loop._pump_contacts` still runs every frame, but the full re-derivation
(`perception.perceived_by` + `set_contacts` + `ResetAffiliationColors`: which
ships have records, perceivable / targetable / identified /
subsystems_targetable, affiliation colour) runs only when
`engine/appc/contact_refresh.py` is marked, or when the (menu, player, player's
set) key changed. Every other frame refreshes each record's `surface_gu` from
this frame's positions (`perception.refresh_distances`), so range readouts never
lag. Cost reference: SIG-193 (`ui.contacts` ≈ 1.08 ms, `contacts.perceive`
0.96 ms); a clean frame shows as `contacts.distances`.

**What marks it (re-derived on the next frame).** Each is a direct hook, never
an event-manager listener (the mission swap clears those):

- the player's sensor sweep, `sensor_contacts._sweep` (`sweep_period_s`, BC's
  1.0 s of **game** time; a player with no sensor subsystem has no sweep and
  marks every tick instead);
- a ship's death (`ship_lifecycle` "destroyed", i.e. `SetDead`), and any
  `IsDying()` flip (`SetDying`, or `SetLifeTime` crossing `DYING_THRESHOLD`:
  rock death, SDK E7M1 / E3M2 lifetimes); the lifetime countdown never crosses
  the threshold on its own;
- a set's contact view changing (`set_index._push`: add, leave, remove, hide,
  reset), which covers a ship entering or leaving the player's set;
- every cloak transition (`CloakingSubsystem._fire`, reached by the native
  completion `native_subsystems._cloak_done` too);
- an identification commit (`sensor_identification._identify_one`) and a lost
  track (`sensor_contacts._lose_track`, `on_exited_set`), so a row's caption
  never trails the reticle;
- `Game.SetPlayer`, the SDK's `STTargetMenu.ClearTargetList`, and `run()`'s
  existing target-identity compare (target or subsystem changed, including a
  lock break by `clear_undetectable_player_lock`);
- the player changing set (warp, hand-off) or a re-created target menu, via the
  pump's own key, with no mark needed;
- `reset_mission_state` (so the first frame of a mission is a full rebuild).

**What waits for the sweep (up to one sweep, ≤ 1 s game time).** Anything with
no event: a ship crossing sensor range or a cloak bubble, the player's sensor
damage or power, `SetTargetable`, a mission regrouping that does not call
`ResetAffiliationColors` (E2M2 and E2M6 do call it, which recolours at once),
and a row an SDK script hid with `SetNotVisible` (re-asserted on the next
re-derivation). This is the lag Mark accepted for everything not event-driven,
and it matches BC's own 1 s sweep. It is **game** time, so under a time scale it
stretches in wall clock, and it does not run while the sim is paused.

**ET_TARGET_LIST_OBJECT_ADDED / _REMOVED** are posted by `set_contacts` when the
targetable membership changes, so they now post at this cadence: on the next
frame for an event above, at the next sweep for a range or bubble crossing.

**The current target is exact every frame.** On a frame that does not
re-derive, the pump compares `perception.target_verdict(player, target)` (the
same expressions `perceived_by` uses, `perception._identity_verdict`) with the
target's record, and a difference re-derives in that same frame. Every reader of
`subsystems_targetable` concerns the player's target, and medium entry/exit and
a scan glimpse expiring post nothing.

`can_detect`'s hysteresis latch is now written by the UI only on a
re-derivation; the per-tick firing chokepoint and `clear_undetectable_player_lock`
keep feeding it, and the latch is idempotent set membership, so the lock guard
and the list cannot disagree on a lock break: the break changes the target, and
the target compare marks the list.

## 6. An AI ship's glow state is polled at 20 Hz

`ShipGlowController.update` (`engine/appc/subsystem_glow.py`) reads each glow
region's subsystem state, condition and the ship's commanded throttle only
every `AI_GLOW_POLL_S` (0.05 s of game time) for AI ships, staggered across
ships by instance id; the player's ship still polls every frame. Consequence,
**accepted** (perf tier 1, spec `2026-11-08-perf-tier1-design.md` §2.3): an AI
ship's damage flicker, disabled/destroyed blow-out and throttle ease start **up
to 50 ms late**, because the edge time is the detection time. Purely visual: no
gameplay reads it.

The impulse glow's ease and slow pulse are no longer stepped in Python: the
renderer evaluates them at upload (`native/src/renderer/include/renderer/glow_impulse.h`)
from the glow flicker's game clock, so a held throttle is one push. AI
combat throttles rarely hold (the SDK's CircleObject / FollowObject /
ManeuverLoop re-blend speed every AI update), so for combat AI the push rate
is capped by the 20 Hz poll rather than reduced to one. The warp
gain stays per-frame Python (only the player warps).

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

## Not a cadence, same trap: tractor events land one tick later

Since fire control went native only (2026-11-03,
`docs/superpowers/specs/2026-11-03-fire-control-native-only-design.md`,
ruling R8), `ET_TRACTOR_BEAM_STARTED_FIRING` and
`ET_TRACTOR_BEAM_STOPPED_FIRING` are **effect-queue entries**: the native
tractor walk (`k1_fire_control.cc` `tractor_sync`) queues them on the firing
edge, and `engine/appc/effect_queue.py` posts them when the queue is
delivered, **one tick after the beam gripped or dropped**. A handler that
reacts to the grip therefore acts a tick late. E7M2's tractor win also lands
one tick later. That is the design, not a missed event. The `tractor_modes`
golden records it: the SDK's `ConditionFiringTractorBeam` ends the tick at 0
with the beam off.

### 2026-11-04, briefly: the pull itself started a FRAME later

⚠️ **Superseded the same day by whole ticks** (below, row 14): the pull now
starts one TICK after the grip, as Mark ruled. The history is kept because
the two consequences listed here still hold.

The tractor force moved from the combat step (`cb.tractors`) into the motion
stage (`ship_motion.tick_tractors`, row `motion.tractors` under `gl.motion`;
Mark's ruling, native motion phase 2 Task 7). Headless, where a frame is one
tick, the pull starts one tick after the K1 tractor walk grips. **In the host
it starts one frame later**: a host frame runs all N `GameLoop` ticks first,
then N weapon and combat steps, so a beam gripped in frame k's combat steps
first pulls in frame k+1's game ticks. That is up to N ticks later (about 3 at
64 ships in a Debug build; the catch-up cap is 15). HOLD, release and dock
react on the same one-frame delay.

Two consequences:

- **E8M2's OD1** (`StopFiring` on `STARTED`): the queued event now stops the
  beam **before any pull**. Under `cb.tractors` it pulled for one tick first
  (≤ 0.33 GU).
- **Smoother tows**: the displacement now lands per tick, inside the
  interpolation buffer's prev→cur span. Before, a multi-tick frame's N pulls
  all landed after the buffer had recorded the frame's poses.

The ruling assumed a one-tick delay; the one-frame figure comes from the
phase 2 closing review (reasoned from `host_loop.py`'s frame order, not
measured live).

---

## Not a cadence, same trap: whole ticks (ruling 2)

Since native motion phase 4 (2026-11-04,
`docs/superpowers/specs/2026-11-03-native-motion-and-proximity-design.md`
§5.4, ruling 2), **each sim tick runs whole**: GameLoop tick *i* (AI, motion),
then weapons and combat tick *i*, then the combat tick boundary, before tick
*i+1* starts (`_whole_tick` in `engine/host_loop.py:_run_frame_sim`, driven
by `advance_ticks`). Before, a host frame ran all of its GameLoop ticks, then
all of its combat ticks. The per-frame input and session stages (the swap
drain, Quick Battle's preload-done spawn, object deletions, player identity,
`sim.keys`, `sim.input`, the fire keys and Manual Aim) moved to **frame
start, before tick 0**. Game time and tick counts are unchanged, so none of
the four cadences above moved. On a one-tick frame with no input the two
orders are the same sequence (the `host_frames_tpf1` golden is unchanged);
every shift shows on multi-tick frames, i.e. below 60 fps.

| # | What changes | Before | After | Pinned by |
|---|---|---|---|---|
| 1 | Poses combat reads on a multi-tick frame | every combat tick saw the poses after the frame's last motion tick | combat tick *i* sees motion tick *i* | `host_frames` golden |
| 2 | Combat results the AI sees | all of the frame's AI ticks ran before any of its combat | AI tick *i+1* sees combat tick *i*'s hits, deaths and events; so do the per-ship subsystem updates in `GameLoop.tick` (shields, power and its passive thaw, cloak, repair), which before saw them next frame | `host_frames` |
| 3 | GameLoop effect delivery (`owns_boundary=False`) | every GameLoop tick's held effects landed at combat boundary 1 | GameLoop tick *i*'s effects land at combat boundary *i* | `host_frames` |
| 4 | Fire keys, mouse fire, chords, raw keys, skip-dialogue | after the frame's GameLoop ticks | before tick 0; still before the first combat tick, and this frame's AI sees the firing state | `test_fire_press_reaches_the_frames_first_combat_tick`; ⚠️ Mark's live check |
| 5 | Manual Aim pick | after this frame's motion, with last frame's camera | at frame start, with last frame's camera: the pick traces the target's sim pose, which is within one tick of the pose last frame drew (before: the frame's n ticks plus that) | live-verified 2026-11-04 (moving target) |
| 6 | Manual player integrator `_apply_input`, and the manual→AI seed | after the frame's AI ticks | before them: AI, proximity and combat all see this frame's manual pose, and a UI helm order is seeded before the first AI tick | the source guard `tests/host/test_scene_reconcile_ordering.py::test_whole_tick_order_and_frame_start_stages` (`_apply_input(` before `advance_ticks(`: headless has no window, so the integration tests never reach `_apply_input`); ⚠️ Mark's live check |
| 7 | Mission-swap drain | after the GameLoop ticks, before combat | frame start; a mid-tick request drains next frame, so the old mission finishes the frame's ticks, combat included | `test_swap_requested_during_a_tick_drains_at_next_frame_start` |
| 8 | Quick Battle preload-done spawn (`_fire_pending_preload_done`) | after the ticks, before the frame's combat | frame start. A spawn the SDK triggers inside a tick (`StartSimulationAction` storing the preload-done event) now fires at the NEXT frame's start: AI first sees the ships at the same tick as before, combat and render one frame later. Only a spawn triggered outside the sim (UI) is seen by this frame's AI | `test_frame_start_stages_run_before_tick_0` (the stage's position) |
| 9 | `_process_object_deletions` | before the frame's combat | frame start only (Mark's decision 2): a ship flagged mid-frame stays in its set, and in combat, until the next frame starts | `test_ship_flagged_for_deletion_mid_frame_leaves_at_next_frame_start` |
| 10 | Ship list per combat tick | tick 0's list was built after all GameLoop ticks | built after GameLoop tick *i* | `test_ship_spawned_in_tick_2_reaches_combat_tick_2_only` |
| 11 | A frame frozen by `sim.keys` (a dev key) | GameLoop ticks ran, combat did not | the frame's whole ticks run (*n* is decided at frame top). So that frame has `_ships_this_tick` set, and the render section applies the render origin and pushes combat feeds for the ticks that ran (a frame frozen from its top still runs none and pushes none) | `test_frame_frozen_mid_frame_still_runs_its_whole_ticks` |
| 12 | Interpolation re-seat | prev = pose before the last GameLoop tick | prev = pose after whole tick *n−1* | `test_reseat_runs_after_the_penultimate_boundary` |
| 14 | Tractor pull, HOLD and release latency | one FRAME after the K1 grip (the motion stage ran all of a frame's ticks before any combat) | one TICK, as Mark ruled | `tractor_modes` golden (unchanged: headless, one tick a frame); ⚠️ Mark's live check |
| 13 | Unchanged | — | collisions, debris, dash, hand-off, the frame-end boundary, nebula and radiation (still batched after all ticks, Mark's decision 3), the cadences above | existing tests |

The tests named are in `tests/integration/test_whole_ticks.py` (real host
frames through `_run_frame_sim`, headless). Two more pins: a RecreatePlayer
inside a tick reaches the post-tick pass (sensor contacts, crew prompts,
dash, hand-off) the same frame through a second player-identity sync after
the ticks (`test_recreate_player_inside_a_tick_reaches_the_post_tick_pass`),
and a fire press on a frame that runs no tick reaches the next frame's first
combat tick (`test_fire_press_on_a_zero_tick_frame_reaches_the_next_combat_tick`).
The source order is guarded by
`tests/host/test_scene_reconcile_ordering.py::test_whole_tick_order_and_frame_start_stages`.
`host_frames` and `k1_ops_tpf6` (now driven in whole ticks) were re-recorded
once for this ruling; every other golden is unchanged.

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

---

## The native subsystem stage (native only)

The per-tick subsystem stage (shields, power plant and consumers, cloak,
repair, rigless-ship articulation skip) runs in C++ only
(`engine/appc/native_subsystems.py` driving `native/src/combat/`
`subsystem_step.cc`). It is not a cadence and changes no timing. Phase 6 Task 8
deleted the Python loop and its `DAUNTLESS_NATIVE_SUBSYSTEMS` switch, so a
suspected subsystem fault can no longer be A/B'd against a Python copy. Look
instead at `native_subsystems.skip_counts()` and the stderr `native subsystems:
... skipped` lines. A piece the mirror cannot run (a dropped row, an unnamed
subsystem) is skipped, not run, and is counted and logged once per (piece,
reason). Under `DAUNTLESS_NATIVE_AUDIT=1` a skip is an audit failure. The
goldens pin the stage bit for bit and assert zero skips; a unit test ticks
its own ships through `tests/helpers/subsystem_stage.py`, which fails on any
skip. The shield cadence above is unchanged.

---

## 7. HUD panels poll at 10-20 Hz

The radar (20 Hz) and the crew menu, player ship and weapons panels (10 Hz)
used to rebuild every frame. Continuous data now trails by up to one interval:

- Firing and charge icons, shield and hull bars and the speed readout may trail
  by up to 100 ms.
- Radar blips move at 20 Hz (up to 50 ms behind).

Interaction never waits: clicks (`dispatch_event`), visibility flips, keyboard
menu open/close (`show_menu` / `hide_menu`), a target change (radar, weapons)
and an alert-level change (crew menu, weapons) all `mark_due` the panel for the
next frame. The last two are `host_loop._mark_hud_due_on_changes`, an identity
compare each frame. Damage cannot be event-driven (`ET_SUBSYSTEM_*` are never
posted, event-emitter-gaps #15), so the interval is a floor, not a fallback.
