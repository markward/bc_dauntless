# Ship AI Motion — Design

**Status:** brainstormed 2026-05-18. Next step: implementation plan in `docs/superpowers/plans/`.

**Builds on:** [Ship AI Runtime — Steps 1-3 plan](../plans/2026-05-18-ship-ai-runtime-step1-3.md) (merged 2026-05-18 as `5071ce6`).
**Pulls forward from:** [Ship AI Runtime deferred plan](../deferred/2026-05-18-ship-ai-runtime.md) — closes Step 4 partially (linear + angular setpoints active; `TurnDirectionsToDirections` solver; `GetPredictedPosition`/`GetRelativePositionInfo`). Defers `TurnTowardLocation`, `InSystemWarp`, obstacle avoidance to the Intercept slice.

## Goal

Make AI ships actually move under their script-recorded setpoints. Today `ShipClass.SetSpeed` / `SetTargetAngularVelocityDirect` only *record* values — the ship's transform never changes. After this slice, a `PlainAI("GoForward")` ship drifts forward on screen, and a `PlainAI("TurnToOrientation")` ship rotates to face its target.

## Non-goals

- PyBullet rigid bodies / collision (the existing `engine/physics/simulation.py` stub stays as-is; the integrator is kinematic, mirroring `_PlayerControl.apply()` in [host_loop.py:594-769](../../../engine/host_loop.py)).
- `TurnTowardLocation`, `InSystemWarp`, `StopInSystemWarp`, obstacle avoidance — deferred to the Intercept slice.
- `PriorityListAI` status propagation from active child to parent — deferred to the `Compound.BasicAttack` combat slice, when a real consumer materialises.
- `OptimizedFireScript` / `OptimizedSelectTarget` preprocessor wiring — combat-slice scope.
- `ConditionScript` evaluation — combat-slice scope.
- Save/load of motion state.

## Architecture

The integrator is a separate per-tick step that runs after AI scripts have written setpoints. Per-tick order in `GameLoop.tick()`:

```
1. g_kTimerManager.tick(dt)
   g_kRealtimeTimerManager.tick(dt)
2. g_kAIManager.tick(game_time, real_time)        — TimeSliceProcess scheduler (Step 2 of prior slice)
3. tick_all_ai(game_time)                          — AI tree-walker; scripts call SetSpeed / SetImpulse /
                                                     SetTargetAngularVelocityDirect / TurnDirectionsToDirections
4. tick_all_ship_motion(dt)                        — NEW: integrator applies recorded setpoints
5. per-ship subsystem updates (shields)
```

Step 4 is the only behavioural change to the loop. Existing ordering (timers → AI manager → AI driver) is preserved; the integrator is inserted *between* AI dispatch and per-ship subsystem updates so motion state is up to date before downstream consumers (shield orientation, audio Doppler if it lands later) read it.

## Components

### `engine/appc/ship_motion.py` (new)

Single responsibility: read each ship's setpoints, advance motion state, write back to the ship's transform.

**Public surface:**
```python
def tick_all_ship_motion(dt: float) -> None: ...
```

Iterates `iter_ships()` (same helper the AI driver uses; no separate registry) and calls `_step_ship_motion(ship, dt)` for each.

**Per-ship state** (added to `ShipClass.__init__`):
```python
self._current_speed: float = 0.0
self._current_angular_velocity = TGPoint3(0.0, 0.0, 0.0)
```

**`_step_ship_motion(ship, dt)`:**
1. Resolve target speed and direction from `ship._speed_setpoint`:
   - If `None` → target speed 0 in model-forward direction.
   - If `frame == DIRECTION_MODEL_SPACE` → rotate direction by `ship.GetWorldRotation()` to get world velocity unit vector.
   - If `frame == DIRECTION_WORLD_SPACE` → use direction as-is.
2. Resolve target angular velocity from `ship._target_angular_velocity_setpoint`; `None` → zero vec.
3. Ramp `_current_speed` toward target speed magnitude at `max_accel * dt` (linear `_ramp_toward` helper — same shape as `_PlayerControl._ramp_toward`).
4. Ramp each component of `_current_angular_velocity` toward target at `max_angular_accel * dt`.
5. Integrate rotation: build pitch/yaw/roll rotation matrices from `_current_angular_velocity * dt`, pre-multiply existing world rotation (matches `_PlayerControl` convention: row-vector matrices, Y-forward, pre-multiply for body-frame deltas).
6. Integrate position: compute world-space forward via `GetWorldRotation().GetRow(1)`, advance translation by `forward * _current_speed * dt`.

**MaxAccel / MaxAngularAccel resolution:** mirrors `_PlayerControl._max_accel` and `_angular_accel`:
- If `ship.GetImpulseEngineSubsystem()` returns a populated IES with `GetMaxSpeed() > 0` and `GetMaxAccel() > 0`, use that value.
- Otherwise fall back to a large constant (same `FALLBACK_MAX_ACCEL = 1e9` rate `_PlayerControl` uses) so test ships without an IES snap to target same-tick.

The integrator does NOT touch ships whose setpoints were never set (`_speed_setpoint is None` AND `_target_angular_velocity_setpoint is None`) so the existing player ship — which uses `_PlayerControl` directly on the transform, not setpoints — is untouched. AI ships call the setters; their setpoints become non-None; the integrator picks them up.

### `engine/appc/ships.py` (modified)

New fields on `ShipClass`: `_current_speed`, `_current_angular_velocity` (see above).

New methods:

- `SetImpulse(self, speed, direction, frame) -> None` — alias for `SetSpeed`. Records to the same `_speed_setpoint` tuple.
- `GetPredictedPosition(self, p: TGPoint3, v: TGPoint3, a: TGPoint3, t: float) -> TGPoint3` — returns `p + v*t + 0.5*a*t²`. Pure math, no ship state read.
- `GetRelativePositionInfo(self, target_vec: TGPoint3) -> tuple[TGPoint3, float, TGPoint3, float]` — returns `(diff_vec, distance, unit_dir, angle_off_forward_rad)` where `diff_vec = target_vec - ship_world_location`, `distance = |diff_vec|`, `unit_dir = diff_vec / distance` (zero vec if distance ≈ 0), `angle_off_forward = acos(clamp(unit_dir · ship_forward, -1, 1))`.
- `TurnDirectionsToDirections(self, primary_from, primary_to, secondary_from, secondary_to) -> float` — see solver section below.

### `TurnDirectionsToDirections` solver

Called by SDK `TurnToOrientation.py` each tick (cadence 0.5 s) to maintain orientation toward a target. Conceptually identical to the deferred `TurnTowardLocation` — both compute the angular velocity needed to close a rotation gap, clamp to `MaxAngularVelocity`, and call `SetTargetAngularVelocityDirect` internally.

**Signature:**
```python
def TurnDirectionsToDirections(
    self,
    primary_from: TGPoint3,    # world-space, current orientation reference vector
    primary_to: TGPoint3,      # world-space, desired direction for primary_from
    secondary_from: TGPoint3,  # world-space, current secondary reference (or zero vec)
    secondary_to: TGPoint3,    # world-space, desired direction for secondary (or zero vec)
) -> float:                    # estimated seconds to finish
```

**Algorithm per tick:**
1. **Primary alignment.** axis = `primary_from × primary_to`; angle = `acos(clamp(primary_from · primary_to, -1, 1))`. If `axis` magnitude near zero (vectors collinear) and `angle ≈ π` (opposite), pick an arbitrary perpendicular axis: cross with world up `(0,0,1)`; if still collinear, cross with world right `(1,0,0)`. If `angle ≈ 0` (aligned), set angular velocity to zero and return 0.
2. **Secondary roll constraint** (skip if `secondary_from` or `secondary_to` is zero). Project both onto the plane perpendicular to `primary_to`; compute the signed angle between the projections around `primary_to`. Add this roll angular velocity to the result.
3. **Build angular velocity target.** Combine primary + roll as an axis-angle vector. Per-axis clamp magnitude to `GetImpulseEngineSubsystem().GetMaxAngularVelocity()` (fallback: a large constant). Soft stop emerges naturally because the gap-derived velocity shrinks as alignment closes.
4. **`self.SetTargetAngularVelocityDirect(angular_velocity)`.** The integrator picks this up next.
5. **Return estimate.** `total_angle / max_angular_velocity` (used by `TurnToOrientation`'s `bDoneOnLineup` heuristic but not load-bearing for the smoke test, which sets `bDoneOnLineup=0`).

**Damping:** deliberately not added. Real PD tuning lands when `Intercept` needs it; for now the natural soft stop from gap-shrinking velocity is enough to pass the smoke test. Documented as a known follow-up.

### `engine/core/loop.py` (modified)

`GameLoop.tick()` adds one call after `tick_all_ai`:

```python
from engine.appc.ship_motion import tick_all_ship_motion
# ... existing AI block ...
tick_all_ship_motion(TICK_DELTA)
# ... existing shield subsystem updates ...
```

Lazy import to avoid the cyclic-import concerns that drove the same pattern for `g_kAIManager` and `tick_all_ai`.

## Test plan

### Unit tests

| File | Count | Coverage |
|---|---|---|
| `tests/unit/test_ship_motion.py` (new) | ~12 | Stay-equivalent (zero setpoints → no drift); linear ramp; SetSpeed WORLD vs MODEL frame; angular ramp per axis; soft stop on zero setpoint; IES-fallback path; forward-direction follows rotation; `GetPredictedPosition` math; `GetRelativePositionInfo` math; `SetImpulse` records same as `SetSpeed` |
| `tests/unit/test_turn_directions.py` (new) | ~6 | Aligned → zero angular velocity; 90° turn → angular velocity around expected axis; 180° degenerate → perpendicular axis chosen; secondary constraint applies roll; clamp to MaxAngularVelocity; both inputs zero → no-op |
| `tests/unit/test_loop.py` (modified) | +1 | Order-of-ops: `g_kAIManager.tick` → `tick_all_ai` → `tick_all_ship_motion`. One `PythonMethodProcess` flips a flag, one AI's `Update` asserts the flag set + records a setpoint, one integrator step assertion that the setpoint was already recorded. Three asserts pin the within-tick contract. |

### Integration tests

| File | Count | Coverage |
|---|---|---|
| `tests/integration/test_ai_goforward_smoke.py` (new) | 3 | Ship + `PlainAI("GoForward")` + `SetImpulse(50.0)` → after 6 s, `GetTranslate().y ≈ 300` (within ramp tolerance) and X/Z ≈ 0; AI stays `US_ACTIVE` |
| `tests/integration/test_ai_turn_to_orientation_smoke.py` (new) | 3 | Ship at origin facing +Y, target at (1000,0,0), `PlainAI("TurnToOrientation")` → after N s, ship's `GetWorldRotation().GetRow(1).x > 0.9`. `bDoneOnLineup=1` variant → AI returns `US_DONE` once aligned. Target on -X → rotates the other way (no shortest-path bug) |
| `tests/integration/test_ai_stay_smoke.py` (modified) | +1 | After integrator runs, `ship.GetTranslate()` matches initial position exactly (Stay's zero setpoints survive the integrator round-trip) |

Total: ~26 new tests on top of the 93 from the previous slice. All headless, deterministic, sub-second.

### Visible verification

`sdk_overlays/Missions/Test/<name>.py` (new — exact path picked during plan writing based on existing Test mission conventions): spawns the player ship and one AI hostile at +1000 units in front; attaches `PlainAI("GoForward")` with a modest `SetImpulse`. User runs `./build/open_stbc`, picks the mission, watches the hostile drift forward. The mission file is acceptance for both the implementer (must launch cleanly) and the user (must visibly move).

## File map

| File | Change | Lines (est) |
|---|---|---|
| `engine/appc/ship_motion.py` | New: integrator | ~130 |
| `engine/appc/ships.py` | Add 4 methods, 2 fields | ~80 |
| `engine/core/loop.py` | One added call inside `tick()` | ~5 |
| `tests/unit/test_ship_motion.py` | New, ~12 tests | ~220 |
| `tests/unit/test_turn_directions.py` | New, ~6 tests | ~120 |
| `tests/unit/test_loop.py` | One appended test | ~30 |
| `tests/integration/test_ai_goforward_smoke.py` | New, 3 tests | ~90 |
| `tests/integration/test_ai_turn_to_orientation_smoke.py` | New, 3 tests | ~110 |
| `tests/integration/test_ai_stay_smoke.py` | One appended assertion | ~10 |
| `sdk_overlays/Missions/Test/<name>.py` | New mission fixture | ~50 |
| `docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md` | Strike completed items | ~20 |

Total: ~900 LOC across ~11 files. Roughly comparable to the just-merged Steps 1-3 slice.

## Implementation sequencing (preview for the plan)

1. **Integrator scaffold + Stay regression** — `ship_motion.py` skeleton that runs but does nothing for zero setpoints; add `_current_*` fields to `ShipClass`; wire into `GameLoop`; extended Stay test passes.
2. **Linear motion** — implement linear ramp + position integration; `SetImpulse` alias; linear `test_ship_motion.py` tests pass.
3. **Angular motion** — implement angular ramp + rotation integration; angular `test_ship_motion.py` tests pass.
4. **Trivial math helpers** — `GetPredictedPosition` + `GetRelativePositionInfo`; their unit tests pass.
5. **`TurnDirectionsToDirections` solver** — `test_turn_directions.py` passes.
6. **Order-of-ops test** — `test_loop.py` addition passes.
7. **GoForward smoke** — `test_ai_goforward_smoke.py` passes end-to-end.
8. **TurnToOrientation smoke** — `test_ai_turn_to_orientation_smoke.py` passes end-to-end.
9. **Visible mission + deferred-doc update** — mission script lands; user confirms visibly in `./build/open_stbc`.

Each task = one TDD cycle (failing test → minimal implementation → green → commit), same shape as the previous slice.

## Risks + open questions

1. **MaxAngularAccel per-axis vs scalar.** `_PlayerControl` ramps each axis independently using a scalar `MaxAngularAccel`. The integrator follows the same pattern. If a hardpoint somewhere distinguishes per-axis values, that asymmetry won't be modelled here. Action: confirm by reading a representative hardpoint during plan writing; if per-axis, decide whether to model now or accept the simplification.
2. **Direction-vec ownership.** `SetSpeed` records the direction vector by reference (current stub). The integrator reads it each tick; if a caller mutates the same TGPoint3 after calling, motion changes underneath. Stay/GoForward pass `TGPoint3_GetModelForward()` which is a fresh constant per call — safe — but other call sites may reuse a stack vec. Action: defensively copy the direction vec in `SetSpeed` (mirror the existing copy in `SetTargetAngularVelocityDirect`).
3. **Test ship without an IES.** Many existing tests construct `ShipClass()` without populating subsystems. The fallback path (`FALLBACK_MAX_ACCEL = 1e9`) snaps to target same-tick. This matches `_PlayerControl` semantics so existing tests should keep passing, but worth a sanity sweep during the integrator task.
4. **Renderer-host visibility.** The user has to build `./build/open_stbc` to do the visible test. CMake configuration is unchanged by this slice, so a fresh `cmake --build build -j` should suffice — but if shader edits ever land between this and that, the [shader-edits-need-reconfigure](../../../memory/project_shader_edits_need_reconfigure.md) gotcha applies. Action: the visible-test task in the plan should remind the implementer of the build step.

## What this unlocks

After this slice merges:
- The Intercept slice has every linear-motion primitive it needs; only `TurnTowardLocation` (largely same math as `TurnDirectionsToDirections` solver), `InSystemWarp`/`StopInSystemWarp`, and obstacle avoidance remain.
- The `FollowObject`/`CircleObject` slice has `GetRelativePositionInfo` already and can land directly on top of Intercept's warp.
- The combat slice still depends on `ConditionScript` eval + `OptimizedFireScript`/`OptimizedSelectTarget` + `BasicAttack` Compound — none of those are motion-dependent and could land in parallel.
