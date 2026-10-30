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

**After this design** (not part of it): the engine side of AI and motion. It
is about 91% of `gl.ai` time and nearly all of `gl.motion`. Mark has ideas
about reframing how the SDK scripts are driven once the engine is optimised.
That conversation should happen before an AI design is written.

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
