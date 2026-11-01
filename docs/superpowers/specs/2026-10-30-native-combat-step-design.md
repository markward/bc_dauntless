# Native combat step — design

Date: 2026-10-30. Branch: `perf/native-combat` (off main `c93448840`).
Status: draft for Mark's review.

## 1. Why

Mark's target is a 65-ship battle at 60 fps.

At 60 fps a frame is 16.7 ms and runs exactly one game tick. Today a tick of
the 64-ship `combat_stress` fight costs about 12 ms of Python simulation:

- combat about 5.5-6;
- game loop and AI about 5.5;
- weapons and the rest about 1.

On top of that, every frame spends about 16 ms in the renderer's CPU work
(`r.frame`) and about 5 ms of Python render prep and UI. These numbers are
from perf register C-213 and SIG-148.

Two things therefore both have to happen:

- the renderer overlaps the simulation on its own thread (a separate design);
- the simulation shrinks several-fold.

This design is the first and largest part of the second: **the combat step
in C++.**

The CPython 3.11 we run has the global interpreter lock. A Python thread
cannot run the simulation in parallel with other Python. C++ code that
releases the lock can, and C++ is the real lever anyway. The same loops in
C++ are typically 10-50 times faster (an estimate, not a measurement).

## 2. Where the time goes (measured 2026-10-30)

**The capture.** `~/Documents/dauntless-perf/pyprof5-cs64-20261030-2334.*.prof`:
cProfile on named scopes, 64 ships, 1,500 frames, from code equal to main
`a0d81c7d4`. cProfile inflates absolute times; the shares are what matter.
Per-tick costs without the profiler come from C-213:

| Scope | ms per tick | What it is |
|---|---|---|
| `cb.held_weapons` | ~2.8 | Every tick, every ship's phaser, pulse, tractor and torpedo systems ask every bank whether it can fire at its target |
| `cb.phasers` | ~1.7 | Each firing beam: dwell, aim point, emit point on the strip, arc, shield-bubble entry, hull trace, then apply |
| `cb.projectiles` | ~0.9-1.8 | Torpedo homing and flight, broadphase (already native), narrow hit tests |
| `cb.eligibility` | ~0.3 | Which ships may sever parts this tick |
| rest of `sim.combat` | small | VFX ageing, deaths, damage cascades, tractors |

Findings that shape the design:

- **There is no hot spot.** Self time is spread over hundreds of small Python
  functions, none over 8% of any scope:
  - attribute lookups and `implements`/`hasattr` checks;
  - `TGPoint3` construction;
  - `GetChildSubsystem`, `_is_offline`, `GetWorldLocation`.

  Porting single functions will not pay. Whole loops have to move, with the
  state they read.
- **Held weapons:**
  - **a third of the time** is `_target_undetectable` → `can_detect`, mostly
    `concealment_at` (the nebula and dust profile lookup),
    `effective_sensor_range` and rock occlusion;
  - **another third** is `update_weapons` → `try_fire_weapon` → `CanFire` /
    `Fire`: about 215 bank checks per tick, with about 25 actual fires.
- **The game scripts barely appear.** The SDK's own Python is 0% of combat
  self time and only 9.4% of `gl.ai`. The rest of AI is engine code:
  - the `ai_driver` tree dispatcher;
  - `planet.GetNearObjects` and `proximity_table.location_is_stored` (27.7
    million calls);
  - object-type checks.

  That is the next project after this one (§9).

## 3. Goals

1. The combat step (`_advance_combat_step`: held weapons, phasers,
   projectiles, eligibility) costs **at most 1 ms per game tick** at 64 ships,
   down from about 5.5. This is a target; the estimate rests on the C++
   speed-up above.
2. **The game is unchanged.** Every SDK-visible value and every event is the
   same, on the same tick, in the same order, as the Python step:
   - `ET_WEAPON_FIRED`, `ET_TORPEDO_FIRED`, `ET_WEAPON_HIT`,
     `ET_SUBSYSTEM_*`, `ET_OBJECT_EXPLODING` and the rest;
   - shield face charges, conditions, charge levels, torpedo positions.

   Checked bit for bit, as in the passive-state work.
3. The C++ work runs **without holding the interpreter lock**, so it can be
   split across cores later if a measurement says it is worth it.
   (Phase 1b amends this for K1: it holds the GIL until the worker-thread
   phase, ruling J in §9.2.)

## 4. Non-goals

- **Ship AI and motion (`gl.ai`, `gl.motion`).** Next project (§9).
- **The render thread.** Separate design.
- **Changing any gameplay rule or BC constant.** This moves code; it does not
  change what it computes.
- **Threading inside the step in this project.** The lock is released so it
  is possible later; splitting work across cores waits for a measurement.

## 5. Anti-goals (a failure even if it runs faster)

- **An event or hit that lands a tick early or late, or in a different
  order.** Game scripts react to these.
- **A value that differs in the last bits from the Python step.** That is
  how desyncs and "it feels different" bugs start.
- **Two copies of a rule that can drift apart.** While both exist, the
  Python step is the test oracle behind a switch. Removing it afterwards is
  Mark's call (§10).
- **Game scripts moved or bypassed.** The SDK boundary is where it is today.

## 6. The constraint that shapes everything: events fire mid-step

`App.g_kEventManager.AddEvent` dispatches synchronously
(`engine/appc/events.py:802-842`). Inside the combat step, posting
`ET_WEAPON_FIRED`, `ET_TORPEDO_ENTERED_SET` or `ET_WEAPON_HIT` runs every SDK
handler right there, and `combat.apply_hit` mutates shields and conditions
and can start a death. Later banks and ships in the same tick read all of
that live:

- a drained face;
- a destroyed sensor that changes `can_detect`;
- a target that turns its weapons off from a handler.

So C++ cannot run the whole step as one batch and return a list of results.
Its decisions are only valid until the next state change. The design keeps
the step's order and makes every decision on current state.

## 7. The design

### 7.1 Ownership: Python owns, C++ mirrors

Python objects stay the owners of all game state, and every SDK getter stays
Python. C++ holds a **mirror** of exactly the fields the combat kernels read,
laid out as flat arrays indexed by ship, subsystem, emitter and torpedo. It
lives in the host module, next to `TransformStore`, which already mirrors
positions and rotations.

**Write-through.** Every mirrored field becomes a `NativeField` descriptor,
the pattern `WakeField` and `FrozenField` already use: on write, it stores
the value and pushes it to the mirror.

- Reads stay plain Python attribute reads, so reading costs nothing.
- One rule, stated in the CLAUDE.md row: **a field a kernel reads MUST be a
  `NativeField`**.
- State held in a list and mutated in place, such as
  `ShieldSubsystem._current_shields[f] = v` (`subsystems.py:2076,2084`),
  bypasses descriptors. Each such site must go through one mutator that
  writes through. The builder lists every one, and §8's mirror audit catches
  a missed one.

**Lifecycle.** A ship, subsystem, emitter or torpedo registers with the
mirror when it is attached or created, and unregisters when it is removed,
dies or its set is unloaded. Mission swap, Quick Battle restore and ship
rebuilds start from a cleared mirror, as with the passive-state registries.

### 7.2 Epochs: when a decision goes stale

The mirror keeps a counter, the **epoch**. Every write-through and every
`step_memo.forget()` raises it. `forget()` is already called around every
`apply_hit`, death, damage cascade and tractor step (`host_loop.py:1119-1312`,
`combat.py:617,621`).

A kernel result records the epoch it was computed at. The Python apply loop
uses a result only if the epoch has not moved since. Otherwise it asks the
kernel again for the remaining items before using them. A recompute is a C++
call over the remaining ships and banks: cheap compared with today's Python.

This makes "decided on current state" true by construction. It is the same
guarantee the step memo gives today, extended to every decision.

### 7.3 The kernels

The kernels are pure C++ functions over the mirror. They release the lock,
never post events, never draw random numbers and never call Python. Each
returns ordered records for Python to apply.

**K1 — fire control** (replaces the gate and decision part of
`_pump_held_weapons` and `WeaponSystem.update_weapons`). For every ship in
list order, then each system in today's order (Phaser, Pulse, Tractor,
Torpedo; `host_loop.py:999`), it computes:

- the system gates: `_is_offline`, `IsOn`, target alive;
- target detectability: **native `can_detect`**, including `concealment_at`
  over the radial system profile, `effective_sensor_range`, rock occlusion,
  cloak and the latch;
- `_can_engage` range;
- per bank:
  - the 0.33 s fire timer;
  - `CanFire`: charge, depleted, condition times parent condition, tube
    readiness, ammo;
  - the aim and arc test (`_resolve_bank_aim_world`, `_emitter_in_arc`, with
    the articulation part transform for banks on moving parts);
  - the target-list retry.

Output: per system, either "stop firing" or the ordered list of banks to
`Fire`, with the aim results each `Fire` needs.

**K2 — beams** (replaces the geometry of `cb.phasers`). Per firing bank:

- dwell;
- the aim point (`_phaser_aim_point`: Manual Aim offset, locked subsystem or
  hull centre);
- the emit point on the strip (`_strip_emit_position`);
- arc and range;
- `shields_block` and `shield_bubble_entry`;
- the hull trace (the existing native `ray_trace_mesh`).

Output: per bank, a contact record (flush or not, hit point, shield point,
face) or "no contact".

**K3 — projectiles** (replaces `projectiles.update_all`'s guide, advance and
narrow phase; the broadphase is already native). It steers and advances every
torpedo, then runs the narrow tests in today's order: every torpedo moves
before any test, and the first hit by ship-list index wins.

Output: torpedo positions and velocities written straight into the mirror and
`TransformStore`, plus ordered hit and expiry records.

**K4 — eligibility.** The `damage_eligibility.select_eligible` set, computed
in C++.

### 7.4 The Python apply loop

`_advance_combat_step` keeps its shape and its profiler scopes. Each scope
becomes:

1. call the kernel;
2. walk its records in order:
   - check the epoch; if it moved, re-ask for the rest;
   - do the SDK-facing part exactly as today: `Fire`'s events, sounds and
     `mod.Create` for pulse launches; `apply_hit`; `beam_contact`;
     `expire()` with `ET_TORPEDO_EXITED_SET`; `RemoveObjectFromSet`.

`Fire` and `apply_hit` split cleanly into a decision part, which moves to the
kernel, and an effect part, which stays. Each effect part takes the kernel's
record rather than recomputing it.

Everything that draws random numbers stays in Python, in the same order:
smoke, death timing, particles, sounds.

### 7.5 Exactness rules for the C++

These follow the existing native queries (`proximity_query.cc`,
`torpedo_scan.cc`):

- `double` everywhere a Python float is used;
- the same operand order;
- `-ffp-contract=off` plus `#pragma clang fp contract(off)`, so no fused
  multiply-add;
- the same libm functions: `atan2`, `asin`, `acos`, `sin`, `cos`;
- `x ** 0.5` is `pow(x, 0.5)`, not `sqrt` (`host_loop.py:1221`,
  `combat.py:452,467,848`). `TGPoint3.Length` is `sqrt` (`math.py:41`).
- `MultMatrixLeft` sums in `m00*x + m01*y + m02*z` order (`math.py:91`).
- Comparisons written so NaN takes the same branch as in Python.
- `ray_trace_mesh` stays float32 against the last synced pose, as today
  (`host_bindings.cc:1492`). The kernels call it the same way the Python
  does.

### 7.6 Decisions settled after the builder check (my calls, 2026-10-30)

1. **`apply_hit` stays Python in this design.** It is the game effect, not a
   decision, and it is small. In the profile it is 6.8% of `cb.phasers`
   (8,776 hits), and torpedo hits are applied after `update_all` returns.
   K2 and K3 hand it the same arguments the Python step does. The shield-face
   rule, splash walk and dev cheat hooks stay where they are.
2. **State that only the kernels change is native-owned.** The Python getters
   read it from the mirror. This covers:
   - each bank's fire timer;
   - phaser dwell;
   - the `can_detect` lock-break latch;
   - torpedo flight state: velocity (`GetVelocityTG`), age, last target
     velocity, last seen target position and mount key.

   Writing about 1,500 torpedo velocities back into Python each tick would
   cost as much as the target. All other state stays Python-owned and
   mirrored (§7.1). §10's "native ownership" now means only moving the REST.
3. **Today's memo staleness is copied exactly, not fixed.** The Python step
   reuses `can_detect` answers and mount positions until the next
   `step_memo.forget()`, even when an event handler changed state in between.
   For example, an `ET_WEAPON_FIRED` handler that turns sensors off does not
   change detection until the next hit.

   The native side keeps the same two memo tables with the same clearing
   points. Every other decision (charge, arcs, gates) reads live mirror
   state, as the Python does. The epoch rule in §7.2 applies to those
   decisions; the two memoised answers clear only at `forget()`.

   The staleness itself is a latent behaviour quirk. It is recorded for Mark
   (§10), not changed here, because §5 forbids changing the game.
4. **One rule, wherever it is called.** With the switch on, every caller of
   `can_detect` uses the native version, sharing the latch:
   - AI;
   - the target list;
   - torpedo guidance;
   - `StartFiring`.

   So do `StartFiring`'s `_target_undetectable` and `_can_engage` and its
   immediate `update_weapons(0.0)`, which run K1 for that one system. There
   are never two live copies of a rule.
5. **The kernels are compiled optimised in every build.** Mark plays and
   measures the shared Debug `build/`, and the build type must not change
   (project rule). So the kernel sources get optimisation flags of their own
   inside the Debug build, keeping `-ffp-contract=off`. Captures stay
   Debug-to-Debug comparable.
6. **When a phase lands:**
   - its differential and audit tests are exact;
   - a paired on/off capture shows its own `cb.*` scope down by at least
     half;
   - total `sim` per tick is not higher, so the mirror's write cost
     elsewhere does not eat the gain.

   A phase that is exact but misses the bar is reported to Mark with the
   numbers before the next phase starts.

### 7.7 The switch

`DAUNTLESS_NATIVE_COMBAT=0` runs today's Python step unchanged. It is read
once when a mission's GameLoop starts, like `DAUNTLESS_PASSIVE_STATE`.
Default on once each phase has passed its tests and Mark's live check.

## 8. Verification

- **Differential per kernel.** Seeded, hand-built scenes driven through both
  paths. Every SDK getter is compared each tick with `==` (floats by bit
  pattern). The event logs must be identical: type, source, destination,
  tick and order. Seeded operations cover:
  - fire, stop and retarget;
  - damage, shield drain and subsystem destruction mid-tick;
  - TurnOff from an event handler;
  - Manual Aim, articulated banks, cloak and nebula concealment;
  - torpedo launches and expiries;
  - ship death and set changes.
- **Mirror audit** (`DAUNTLESS_NATIVE_AUDIT=1`). Each tick, every mirrored
  field is compared with its Python owner, and each kernel decision with the
  Python reference decision on the same state. Any difference is recorded
  with the object and field. This is the passive audit's pattern.
- **Whole-scene audit.** `combat_stress` with 16 ships through the real
  `host_loop.run()`, audit on, zero differences. This extends
  `tests/host/test_passive_state_scene_audit.py`'s approach.
- **Measurement.** Paired on/off captures with cool-downs, 64-ship fight and
  quiet scene (perf register SIG-147: one capture per condition cannot
  resolve small changes). Report `sim.combat` and its `cb.*` children per
  tick. Then Mark's live check.

## 9. Phases

Each phase lands with its tests, a paired measurement and Mark's live check
before the next starts.

1. **Mirror + K1 fire control + native `can_detect`.** The biggest scope.
   `can_detect` in C++ also serves AI later.
2. **K2 beams.**
3. **K3 projectiles + K4 eligibility.**
4. **Measure; decide on threads.** If `sim.combat` is then near 1 ms per tick,
   threading inside it is not worth it, and the remaining 60 fps work is AI
   and motion, plus the render thread.

**Note 2026-11-01: phase 2 (K2 beams) is done**, on branch `perf/native-combat-k2` (tip `6418f858f`), default still off. Per game tick, 64-ship fight: `cb.phasers` 1.774 to 0.739 (-58%), `sim.combat` 4.466 to 3.325 (-26%). Details, fallbacks, rulings and known limits: `2026-10-31-native-combat-k2-beams-design.md` §10; signals SIG-162, SIG-163.

**Note 2026-11-01: phase 3 (K3 projectiles + K4 eligibility) is done**, on branch `perf/native-combat-k3` (tip `0c5d58c81`), default still off, not yet live-verified. Per game tick, 64-ship fight: `cb.projectiles` 0.827 to 0.166 (-80%), `cb.eligibility` 0.277 to 0.042 (-85%), `sim.combat` 3.325 to 2.453 (-26%); goal 1 (at most 1 ms a tick) still not met. Details, fallbacks, rulings and parked items: `2026-11-01-native-combat-k3-k4-design.md` §10; signals SIG-164, SIG-165.

### 9.1 Note, 2026-10-31: phase 1 split into 1a and 1b, and what 1a decided

**The split.** Phase 1 ships in two parts. **1a** (branch `perf/native-combat`,
commits up to `388e18754`) is the mirror plus native `can_detect` for every
caller of sensor detection, behind `DAUNTLESS_NATIVE_COMBAT` (**unset means
off**; `=1` on, `=0` forced off; `DAUNTLESS_NATIVE_AUDIT=1` runs the audit and
implies on). **1b** is K1 fire control (the batch kernels, where the GIL is
released). The phase 1 bar ("own scope down half", §7.6.6) is judged after 1b.
Flipping the default to on is a separate change after Mark's live check
(`DAUNTLESS_NATIVE_COMBAT=1 ./build/dauntless --developer`, in E3M2 Vesuvi, a
nebula and a cloak fight).

**Rulings made while building 1a** (each: what, then cost if wrong):

- **R1.** The row structs carry the full field set from the start, including class flags; a later task may add a field with its enum entry in the same commit. Cost if wrong: a later edit to `mirror.h`.
- **R2.** A `NativeField` push or `unregister` that hits a stale handle drops the object's slot and goes quiet; the object then takes the Python path. Reachable only after a test's `combat_clear()`. Cost if wrong: a production staleness bug could be masked; the scene audit compares every registered object.
- **R3.** The kernel takes the `TransformStore&` it reads from, so gtests use local instances. Cost if wrong: none.
- **R4.** Each Task 7 test must fail under a mutation its own scenario exercises (not all three under one). Cost if wrong: none.
- **R5.** Native concealment and `can_detect` never return NaN where Python raises: a non-finite fbm input inside a sphere raises `ValueError` and the wrapper falls back to the Python body. Cost if wrong: one extra branch per density call.
- **R6.** A reference to an unregistered, non-None object pushes sentinel -2 ("unrepresentable"); a query that reads one raises and falls back to Python. Cost if wrong: one more sentinel check per reference read.
- **R7.** The lock-break latch has ONE owner in native mode (native, via `combat_set_latched`), with a hand-off to Python's `_broken` when a row is dropped. Cost if wrong: one binding call per fallback latch access.
- **R8.** While Python's `_walking_probes` is True every `can_detect` takes the Python body, so a fallback's probe walk keeps the one-level rule. Cost if wrong: none (fallback-only).
- **R9.** On a fallback query the Python occlusion caches are used; a later native query at the same game time may recompute where Python would have hit its cache. Reachable only when a set holds an unrepresentable entry. Cost if wrong: an occlusion answer can differ within one game time in that rare state.
- **R10.** The zero-sphere MetaNebula seed gap (Python caches `seed_for(0,0,0)` if queried before any sphere; native derives from the first sphere) is accepted. No stock SDK path does it (0 hits). Cost if wrong: a mod that does so gets a different nebula noise seed with native on.
- **R11.** The memo sibling of R9: a pair that falls back inside a combat step and later answers natively in the same step (or the reverse) without a `forget()` can return a different answer than a Python-only run. Cost if wrong: one stale-vs-fresh answer within one step in that rare state.
- **R12.** Torpedoes get no mirror row, so they run in Python. Cost if wrong: the torpedo path is not sped up by the native path.

**Lifecycle, lock and fallbacks** (settled earlier, same plan): mirror rows live
exactly as long as their Python object (registered in `__init__`, removed by its
`weakref.finalize`); a mission swap does NOT clear rows. The latch, occlusion
caches and memo reset at exactly the points Python's do. Per-call queries hold
the GIL. Unregistered pairs (test fakes, non-ship targets) take the Python
path. Probe ids are skipped, not pruned. A stale transform is unreachable.

**Rule for every later phase.** A field the kernel reads MUST be a
`NativeField` (or a `NativeRefField`), and an in-place mutation (list append,
dict write) of mirrored state MUST go through a pushing mutator, or native
reads a stale value.

**Latent bug found (for Mark, not fixed).** `sensor_detection._game_time()`
calls `App.g_kTimerManager.GetGameTime()`, which does not exist on
`TGTimerManager`; the `AttributeError` is swallowed and it returns 0.0 every
time. MetaNebula concealment drift is therefore frozen at t=0 in today's game.
The native port copies the 0.0 (bit-exact rule). The occlusion caches read
`g_kUtopiaModule.GetGameTime()`, which works. Two clocks, not one; the
can-detect inputs document is corrected. Fixing `_game_time()` changes
gameplay (the fog starts to move) and is Mark's call; the native clock must
change in the same commit.

**Measurement summary** (perf register SIG-154 to SIG-157, C-234 to C-237,
Debug, 64 ships, one capture per condition; medians of the 9 reports after the first 2, the compare script's 1-based reports 3-11). Quiet scene: total sim per tick
**did not change** (5.303 off, 5.275 on). Fight: total sim per tick 12.826 off,
12.196 on (-4.9%), `cb.held_weapons` 2.840 to 1.981 and `sim.combat` 6.068 to
4.929, but the two fights differed (median 87 vs 48 projectiles in flight), so
the gain is not separated from the fight; the -4.9% total-sim difference is
inside SIG-147's spread and does not read as a win. The switch-off cost against the
previous passive-on captures is not separable from the spread (SIG-156,
derived). Phase 1a therefore shows no rise and no clear fall in total sim;
whether the phase 1 bar is reachable is a 1b question. Two things to
remember when reading these: the `calls` column is the last frame's tick
count (SIG-157), and one capture cannot resolve ~25% on upkeep rows
(SIG-147).

**After this design** (not part of it): the engine side of AI and motion. It
is about 91% of `gl.ai` time and nearly all of `gl.motion`. Mark has ideas
about reframing how the SDK scripts are driven once the engine is optimised.
That conversation should happen before an AI design is written.

### 9.2 Phase 1b rulings and measurement (K1 fire control)

Branch `perf/native-combat-1b`, forked from `perf/native-combat` at `93c690f4d`. K1 is the held-weapon walk (beams, pulses, torpedo tubes): the kernel returns one record per call and Python applies each effect, then resumes it. Switch `DAUNTLESS_NATIVE_COMBAT` as in 1a, **default off**. `native_combat.counts()["k1_python_reasons"]` says why a system fell back to Python.

**Rulings from the plan** (what; cost if wrong is in the plan):

- **P1.** No epoch check in K1: one record per call, resumed on the live mirror, so no decision spans a Python effect.
- **P2.** Whole-system Python fallback (`RUN_PYTHON`) for unrepresentable state, checked before the first write.
- **P3.** No per-decision audit for K1 (effects post events); the oracle is the differential tests plus the per-tick mirror audit.
- **P4.** The Python mount memo is not filled by K1; the phaser step computes fresh until K2 ports phasers.
- **P5.** `_target_offset` uses the walk's own offset object, fetched with a `WALK_START` record.
- **P6.** Pulse launch speed and lifetime are cached at bank registration and refreshed on mission swap.
- **P7.** Kernel-written fields are copied back to Python from a write log, not native-only; Python state and passive-state machinery stay valid.

**Rulings from the controller** (each cost-if-wrong in the SDD ledger):

- **A.** Every K1 record carries `writes` as its last element, `WALK_START` included.
- **B.** Work in `native-combat-1b`; the plan's worktree line is superseded.
- **C.** The 120-tick differential drives ticks as the 1a step differential does.
- **D.** No standalone behaviour-neutrality test; the existing fire tests with native off are the proof.
- **E.** The timing captures launch the game, so they wait for Mark's go-ahead.
- **F.** Implementers run focused test files only.
- **G.** Inline Python epsilon literals are ported verbatim with a source-line comment; only named module constants are pushed.
- **H.** Two-stage fallback: a pre-scan before the first write for a system, then after the first record an `ASK` record has Python answer the one question on live objects (can_fire, fire, retry, is_dead, is_member, group_step, reseed, is_dumb), counted as `k1_asks`.
- **I.** The final whole-branch review ran while the timing waited.
- **J.** K1 holds the GIL (no release) until the worker-thread phase, amending §3.3: the packaged log thread and mid-walk Python callbacks make a release unsafe now. Cost: none now; revisit with threading.

**Mark's natural-pose rule (Task 6b).** `has_posed_parts` is true when some part's current pose differs from identity (the NIF's natural pose), not when the ship has a rig. Mark's convention: author "red" as the natural mesh pose (the Bird of Prey already does). At identity Python's rigged math returns the original point, so native is bit-identical; `tick_ship` re-pushes the flag when a pose leaves or returns to identity; a mid-transition ship still falls back. Fallbacks in 120 headless frames of `combat_stress`: 929 → 222 (SIG-160).

**Measurement** (perf register C-238 to C-241, SIG-158 to SIG-161; **Debug**, 64 ships, one capture per condition, HEAD `34f1ecba0`; medians of reports 3-11, value ÷ average ticks per frame). Fight, per tick off → on: `cb.held_weapons` 2.870 → 1.238 (-57%) and `sim.combat` 6.123 → 4.142, total sim 12.684 → 11.738 (-7.5%, inside SIG-147's spread). Judged against §7.6.6: the held-weapon scope is **down by at least half (met)** and total sim per tick is **not higher (met)**. Projectiles in flight: median 65 vs 55, 15% apart, under the plan's 25% limit, so the pair is comparable, with the caveats in SIG-158. Quiet: flat (5.454 → 5.524, +1.3%). Goal 1 (combat step at most 1 ms a tick) is not met: 4.142 ms. The extra costs (switch-off descriptor writes, re-pinning, session copy, the ~1.9 µs override re-check, write-log application) are not separable at this resolution (SIG-161).

**Open after phase 1b:**

- Engine nondeterminism unrelated to native: the avoidance phase is keyed on object id, sound gating reads the wall clock, and the first fight in a process diverges for a cause not found. The differentials pin the first two in test code only.
- The latent nebula-drift clock bug from 1a (`sensor_detection._game_time()` is always 0.0): Mark's call.
- A system row dropped while its walk runs is a documented invariant; `run_k1` raises `RuntimeError` if it happens.
- Tractor beams and swung-wing (posed) ships stay in Python.
- The default flip to on is a separate change after Mark's live check (`DAUNTLESS_NATIVE_COMBAT=1 ./build/dauntless --developer`: a big Quick Battle with Klingon, Romulan and Federation ships, torpedoes and Manual Aim).

## 10. Left for later / decisions not taken here

- **Whether to delete the Python step** once the native one is accepted.
  While both exist, every rule change must land in both, or the
  differential fails. Mark's call after phase 4.
- **Threads inside the step.** §9 phase 4.
- **Native ownership of the rest.** Kernel-only state is already
  native-owned (§7.6.2). C++ owning the rest, with Python getters reading
  it, would remove the write-through cost. It is a larger change; consider
  it only if the mirror's write cost shows up in a profile.
- **The memo staleness quirk (§7.6.3).** Within one combat step, detection
  and mount positions can lag an event handler's change until the next hit.
  Fixing it changes behaviour, so it is Mark's call.

## 11. Left to the builder

- **The mirror's layout and index management:** free lists, generation
  counters for stale handles.
- **The binding surface:** how kernels return records (struct arrays in a
  buffer vs pybind lists) and how Python walks them cheaply.
- **The full list of fields each kernel reads,** each made a `NativeField`,
  and every in-place mutation site routed through a write-through mutator.
- **Where `Fire` and `apply_hit` split into decision and effect,** keeping
  each effect's code where it is.
- **Profiler scopes for the kernels and the apply loops.**
