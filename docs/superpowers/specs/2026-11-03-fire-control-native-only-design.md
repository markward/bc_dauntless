# Fire control native only, switch default on — design (2026-11-03)

**Status:** approved direction (Mark, 2026-11-03). Branch `ws/native-default`, off `project/combat_threading` at `2369cba41`.
**Roadmap:** workstream E, option B: the switch defaults on **and** fire control's Python copy is retired before `project/combat_threading` merges to main.
**Input map:** `docs/reference/engine/native-combat/k1-retirement-map.md` (KRM). Its file abbreviations are used here.

## 1. Goal

Fire control (K1) has one copy of its rules, in C++, and every route into it is native, including tractors and the SDK's own weapon calls. The native switch is on unless `DAUNTLESS_NATIVE_COMBAT=0`. After this phase, the project branch can merge to main.

**Non-goals:**
- retiring K0, K2, K3, K4 or native damage's Python copies (each is a later phase);
- the per-core split;
- J.

## 2. Mark's decisions

- **M1. The switch defaults on.**
- **M2. The native module is required for fire control.**
- **M3. Fire control's Python copy is deleted** with its patch, override, instance-patch and unseen-class guards and its whole-system fallback (roadmap decision 2).
- **M4. Tractors are moved to C++ and cleaned up.**
- **M5. Aim points do not follow articulated parts.** A non-mount aim point (a Manual Aim pick, a stale pick, an NPC offset kept across a re-target) is a plain xyz in the target's body frame. Mark: "we dont need torpedoes to track articulated parts moving mid flight".
  - This reverses ruling C4 of the posed-parts spec and removes the box rule from all aiming.
  - A subsystem mount on a posed part is still aimed at its posed position when the shot is fired.
  - The box rule stays for hit attribution and severance.
- **M6. The defensive hand-backs become "does not fire that tick, logged once".**
- **M7. Recorded golden fights replace the both-ways tests for fire control.**
- **M8. The eight routes the decisions did not cover** (KRM §2.7) are ruled as follows:
  1. SDK dumb fire becomes native: a one-tube session on the kernel's `dumb_fire`.
  2. A tube with no ammo type fires the hardpoint's slot-0 script: that script goes into the launch cache.
  3. A stale launch cache (a re-imported pulse module, the P6 window) is re-pushed at the next K1 entry. It is not a no-fire.
  4. A ship whose part resolution raised: no fire and log once, retried every step.
  5. An offset within 1e-5 of a mount but not bit-equal is a plain point.
  6. The SDK's `CanFire`, `Fire` and `FireDumb` become thin wrappers over the native rule.
  7. K2's override guard (which reads K1's `k1_overridden`) is deleted too, under decision 2.
  8. The walk's shared offset object is built natively.
- **M9. Fire control is always native; the switch keeps governing the other kernels.** Their both-ways tests run with native fire control in both arms.
- **M10. Failures are loud.** A stale build (missing bindings) or a failed `_self_check()` raises at start-up instead of quietly leaving native off.

## 3. Rulings (mine; Mark may overturn)

- **R1. The test reset.** `tests/conftest.py`'s per-test reset stops turning fire control off.
  - Fire control is gated on `available()`, not on the switch.
  - The reset still restores the switch's value for the other kernels, and `configure()` sets it: on unless `DAUNTLESS_NATIVE_COMBAT=0`.
  - A test that needs the old Python arm of K0, K2, K3, K4 or damage pins `=0` explicitly.
- **R2. What "does not fire that tick" means** (KRM R8):
  - A failure found before a system's first shot of the tick rolls that system's unreturned writes back (`k1_roll_back`), so the tick is as if it had not walked.
  - A failure found after a shot (`reseed`, `retry`, `is_dead` in the retry loop) keeps what happened, and treats the failing entry as gone or the reseed as skipped.
  - Both are counted under one new `k1_no_fire` counter by reason, and logged once per reason per session through `[native-combat]` on stderr.
- **R3. A dropped row** (`_drop`, KRM R5) is the same no-fire: counted, logged once. Every golden scene asserts zero drops and zero `k1_no_fire`.
- **R4. Mod ship classes.** The "ship class not stock" hand-back is deleted. Mods supply ships as data (hardpoints and ship scripts), not as `ShipClass` subclasses, under decision 2 (**inferred** from the mod categories; KRM R14).
- **R5. Manual Aim stores the pick as it is.** Manual Aim stores the posed body point it hit, rather than pulling it back to the rest frame (`manual_aim.py:198-204`; `rest_point_for_live_point` is deleted). A torpedo at a picked spot steers to that body point for its whole flight; there is no launch-time bake.
- **R6. D5 lands in the Python copies of K2 and K3 too.** That is `subsystems.target_offset_world`, `projectiles._steer_point` and `_bake_offset`, at the same time as the native geometry, so their both-ways tests stay meaningful (KRM §4.5).
- **R7. The tractor force moves to C++ as its own step**, in the same place as today: after K2, inside the combat step, writing the transform store.
  - It is a kernel with its own inputs (tractor system state, mass, poses) and outputs (pose writes), so a later motion thread can take it over without untangling it from fire control.
  - Its force law is the existing one: a mass-capped kinematic displacement, `speed = clamp(5·100/mass, 0, 20)` GU/s. It is not a spring-damper; CLAUDE.md's OQ-2.3 line is corrected at the main merge.
- **R8. Tractor events go through the effect queue.** `ET_TRACTOR_BEAM_STARTED_FIRING` and `ET_TRACTOR_BEAM_STOPPED_FIRING` become queue kinds, posted on the firing edge (source the system, destination the ship). Under decision 9, E8M2's OD1 `StopFiring` handler then lands one tick later, which is at most about 0.33 GU of extra pull. E7M2's win also moves one tick.
- **R9. Goldens are per platform.** A golden is compared only on the platform that recorded it. Others skip, with a message naming the missing file (KRM R9).
- **R10. Determinism of a golden scene:** every RNG is seeded, `headless_mission.clear_in_flight` runs, `gc.collect()` runs at scene load, and fight audio is isolated (KRM R10).

## 4. Design

### 4.1 Switch, module, loud failures
- `native_combat.configure()`: on unless `DAUNTLESS_NATIVE_COMBAT=0`.
- Fire control's entry points (`k1_pump`, `k1_system`, the dumb-fire session, the SDK wrappers) always take the native path. They raise a clear error if the module or a binding is missing.
- `available()` false, or a failed `_self_check()`, raises at `configure()` with the missing names. It no longer silently disables.

### 4.2 Golden fights (M7)
- A recorder built from the K1 differential's `_Scene.record`. Per tick it writes canonical rows by `.hex()`, labelled by ship name, getter and child index, plus the ordered event log and effect-queue rows (KRM §5.5).
- Stored as `tests/fixtures/golden_fights/<scene>.<platform>.json.gz`, holding the per-tick SHA-256 plus the rows.
- Re-recorded with `UPDATE_COMBAT_GOLDEN=1`, which writes the file and then skips. The file header names scene, seed, ships, ticks, tpf, schema version, platform, and the reason for the last re-record.
- **Scenes:**
  1. the K1 op-stream fight at tpf 1 and 6;
  2. the same under GameLoop AI;
  3. the mid-walk handler scene;
  4. the posed fight;
  5. a tractor scene: each mode, range and arc loss, power loss, a STARTED handler that stops the beam, and a `ConditionFiringTractorBeam` listener;
  6. an SDK dumb-fire scene.
- **Recording order:**
  - Scenes 1-5 are recorded **from the Python arm first**, before anything is deleted, and native is checked against them.
  - Each intended behaviour change then re-records only the scenes it touches, in its own commit that says why: D5 the posed scenes (the unposed scenes must not move), the tractor event deferral scene 5, the dumb-fire port scene 6.
  - Scene 6 is recorded from Python before its port.

### 4.3 Aim simplification (M5, R5, R6)
Delete everything in KRM §4.1-4.2:
- the manual slot and its per-step re-resolution;
- the bake;
- `NoMount`, `PosedOffset`, K2's manual-on-posed route and K3's `unbaked`.

No mount means the offset itself. That applies in both native and Python geometry.

### 4.4 Tractors native (M4, R7, R8)
- Mirror the tractor system's `_mode`, `_engage_state` (hold point or tow offset), `_was_firing` and `_next_emitter_index`; the parent's `_efficiency` and `_normal_power` as native frozen fields; ship mass; and the tractor constants.
- **K1 gains a tractor walk** covering:
  - engage from `StartFiring`, as a native system session;
  - per-tick sustain;
  - drop-out-of-arc and re-acquire;
  - the emitter round-robin.
- K0 gains the holding branch: power-loss and starvation stop.
- A native force step replaces `tractor.advance_tractors`.
- **Delete** the self-managed flag and hand-back, `_pump_held_system`, `TractorBeamSystem.update_weapons`, and `_target_tractorable`.
- Writes to `_firing` keep going through the Python setter, so the power thaw stays correct.

### 4.5 SDK routes native (M8 1-3, 6)
- `FireDumb` runs a native one-tube session.
- `CanFire` and `Fire` call the native rule, including `CanFire`'s `_depleted` side effect.
- The no-ammo slot-0 script goes into the launch cache.
- A stale cache is re-pushed at the next K1 entry.

### 4.6 Delete the Python copy (M3, M6, M8 4-5, 7-8, R2-R4)
- Delete everything KRM §1 marks DELETE: the Python decision code in `weapon_subsystems.py`, the `host_loop` pump's off loop, K1's guards and walk check, the launch patch guard, `RUN_PYTHON`, the ASKs and their answers, and K2's override guard.
- Keep every SDK-facing method KRM §1 marks KEEP.
- `_drop` and every former hand-back follow R2 and R3.

### 4.7 Tests
- The K1 differential and `test_native_k1_dispatch.py`'s Python comparisons become golden or recorded-expectation tests.
- The guard and hand-back tests that only test deleted scaffolding are deleted, each named in the task report.
- `test_native_manual_slot.py` is deleted.
- Tests that fired weapons through the Python copy (KRM §5.2) run native. A test whose fake weapon only the Python walk accepted moves to a real weapon or a native-level test.
- The other kernels' differentials keep both arms, with native fire control in both (M9).
- The 26-mission campaign sweep runs with the new default.

## 5. Done when

- No Python fire-control decision code remains (a source guard test lists the deleted names).
- All golden scenes pass on macOS, and the focused test set is green, including the campaign sweep and every native test file in one process.
- A 64-ship benchmark against SIG-178 shows no regression in `cb.held_weapons` or `sim`.
- Mark has live-verified a session with no switch set, including tractors (E7M2 or E8M2, or Quick Battle).
- Then the gate runs and the project branch merges to main, on Mark's say.

## 6. Outcome

(Filled in when built.)
