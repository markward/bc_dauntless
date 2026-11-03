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

Built 2026-11-03 on branch `ws/native-default`, off `project/combat_threading` at `2369cba41`. Commits: map and spec `c93856d22`; plan `1e5f836bc`; Task 1 `aae2cdaa2`, fix round `5f1e67065`; Task 2 `23b3845d5`; Task 3 `57767f45c`, fix round `095109cdf`; Task 4 `de59c20f9`; Task 5 `044cbfa9f`, fix round `9c3db5ec6`; Task 6 `a0fbbb83e` + `86baac29e`, fix round `0447023e1`. Not merged to `project/combat_threading` or main yet.

**Benchmark** (SIG-179, C-281/C-282 against SIG-178's C-278/C-279, 64 ships, no switch set, Debug): no regression. Per tick, `cb.held_weapons` 0.593 → 0.547 ms, `sim.combat` 1.458 → 1.379, `sim` 9.311 → 9.033 (about half of that is `sim.effects`, which swings run to run, so no `sim` gain is claimed).

**After the final review** (`cbc2f2c5c`): a stale build is refused at start-up (every K1 binding listed, record kinds must be exactly DONE); every fire-control entry makes the mirror live first; a held or listed target with no real IsDead (a planet picked by a script or the AI) reads as dead, so phasers, torpedoes and tractors on it stop as the Python copy did. Parked: no K1 test reaches the unplaced-target `stub_or_unplaced` returns (defensive; objects are always placed); a script's direct `TorpedoTube.Fire(planet)` is a counted no-fire where the Python copy posted `ET_WEAPON_FIRE_FAILED` (no SDK caller). The mission-booting files and the campaign sweep were re-run on the final code: 108 passed, 1 xfailed.

**Live check: pending (Mark).**

### What was built, task by task

- **Task 1, golden fights (M7, R9, R10).** `tests/helpers/golden_fight.py` records each scene tick by tick: every ship's pose, every weapon, tube and tractor field (floats by `.hex()`), the ordered event log, the effect-queue and sound rows, the hit calls and the presentation. `check()` names the first differing tick, component, row and field, and verifies the stored per-tick SHA-256. A missing platform file skips (R9). `UPDATE_COMBAT_GOLDEN=1` with a `COMBAT_GOLDEN_REASON` re-records and skips. All seven scenes were recorded from the Python arm before anything was deleted, and native matched scenes 1-5 with no mismatch. The fix round added torpedo reload timers and last fire time to the rows (schema 2; all seven re-recorded from Python), pinned the tractor range at 110 and 125 GU, and proved the dumb-fire scene by a call count.
- **Task 2, aim points are plain body-frame points (M5, R5, R6, M8.5).** An offset that is bit for bit a subsystem's own mount is posed with that mount's part, as before. Anything else (a Manual Aim pick, a stale pick, an NPC offset kept across a re-target, an offset within 1e-5 of a mount) is `pos + R·(scale·offset)`, with no part pose, in both the Python and native geometry. Deleted: the Manual Aim slot, the launch-time bake (`_bake_offset`, `_baked_offset`), the `no_mount` and `offset_off_mount` reasons, K2's Manual-Aim-on-posed route, K3's `unbaked`, and `rest_point_for_live_point`. Manual Aim now stores the posed body point it hit. The box rule stays for hit attribution and severance. `test_native_manual_slot.py` is deleted.
- **Task 3, tractors native (M4, R7, R8).** K1 gained a tractor walk: the pump's sustain, the drop out of range or arc and the re-grip, the emitter round robin, and `StartFiring` as a native system session (its gates stay a Python wrapper). K0 gained the holding branch: a tractor whose parent is off, gone or starved stops. A native force step, `native/src/combat/src/tractor_force.cc`, replaces the Python force in the same place (`cb.tractors`, after K2). Its law is unchanged: a mass-capped kinematic displacement, speed `min(5·100/mass, 20)` GU/s, mass ≤ 0 read as 1e4, constants pushed from `engine/appc/tractor.py`. `ET_TRACTOR_BEAM_STARTED_FIRING` and `_STOPPED_FIRING` are effect-queue kinds. The self-managed hand-back, `TractorBeamSystem.update_weapons`, `_engage_beam`, `_can_engage` and `_target_tractorable` are deleted. The fix round made sure a tractor getter is never handed to Python, and made one bad target skip only itself in the force step.
- **Task 4, the SDK's routes native (M8.1-3, M8.6).** `FireDumb` is a one-tube native session. `Fire` and `CanFire` call the native rule, and `CanFire` keeps its `_depleted` clear. A tube with no ammo type launches the hardpoint's slot-0 script from the launch cache. A stale launch cache is re-pushed at the next K1 entry and is not counted as a no-fire. The `sdk_dumb_fire` golden passed its Python recording unchanged on the native arm.
- **Task 5, the switch defaults on, fire control always native (M1, M2, M9, M10, R1).** `DAUNTLESS_NATIVE_COMBAT` is on unless `=0`. `fire_control_native()` means "the mirror is live" and never reads the switch, which still governs K0, K2, K3, K4, damage, the effect scope and the sensor queries. `configure()` raises on a stale build (it names the missing bindings), an absent module or a failed `_self_check()`. The per-test reset in `tests/conftest.py` calls `configure()`. The fix round made the first fire-control call bring the mirror live itself, so fire control is native even before a mission loader has configured anything. It also pinned only the 36 sensor tests (39 ids) that test the Python sensor rules to `=0`, and reset Felix's order globals in `Bridge/TacticalMenuHandlers` per test: they leaked between tests and were the cause of a golden order dependency.
- **Task 6, the Python copy deleted (M3, M6, M8.4, M8.7, M8.8, R2-R4).** Deleted: the decision code in `weapon_subsystems.py` (`update_weapons`, `try_fire_weapon`, `_fire_decide` and its family, the spawn and launch helpers); the host loop's Python pump (`_PUMP_GETTERS`, `_pump_held_system`); K1's override, patch and ship-class guards, the walk check, the launch check, the ASKs and their answers, and `RUN_PYTHON`; and K2's three `k1_overridden` reads (M8.7). `CanFire`, `Fire` and `FireDumb` remain as one native call each. K1's only record kind is `DONE`. A part resolution that raises is retried at every step (M8.4). The walk's shared offset object is built natively (M8.8). `tests/unit/test_fire_control_python_retired.py` is the source guard: it fails if any deleted name comes back in Python or C++.

### No-fire reasons (R2, R3)

Every former hand-back is now a no-fire: counted in `k1_no_fire` by reason, and logged once per reason per session through `[native-combat]` on stderr.

- **The kernel's reasons:** `tractor_row`, `stale_row`, `stub_or_unplaced`, `pulse_ship_target`, `pulse_module`, `ammo_row`, `part_stale`, `unslotted_ship`, `gate`, `structure`, `not_k1_system`, `can_fire`, `decision`, `launch`, `walk`, `reseed`, `retry`, `is_dead`.
- **The Python driver's reasons:** `no_row`, `unnamed_target`, `sdk_can_fire`, `dropped` (a `_drop`, R3) and `tractor_row`. They are merged into the same counter by name.

A failure before the walk's first shot rolls the walk back (writes, entries and counters), so the tick is as if it had not walked. A failure after it keeps the shot and ends the walk. A shot here is a fire, a refused fire (`WEAPON_FIRE_FAILED`) or a dumb launch.

The fix round split the pre-scan in two. `gate_prescan` runs before the stop gates and checks only what the gates read: the system's row and kind, its ship (real `IsDead`, placed), the pump's ship, the held target and its set, and each child's row. `walk_prescan` runs after the gates and checks the rest: the target list and a pulse system's ship target, the chain table, each child's parent, ship and property, part staleness, the pulse module and the ammo rows. Before the split, a pulse system whose held target died was never stopped: it failed the walk-only check before the gates could stop it.

### Goldens

Seven scenes, macOS recordings in `tests/fixtures/golden_fights/<scene>.darwin.json.gz`: `k1_ops_tpf1`, `k1_ops_tpf6`, `k1_gameloop_ai`, `k1_midwalk_handler`, `posed_fight`, `tractor_modes` and `sdk_dumb_fire`.

Three were re-recorded for an intended change, each in the commit that made it:

- **`posed_fight`** (M5): 151 of 660 ticks moved, all in the Manual Aim window and the flight of the four torpedoes fired at the pick. The hit count did not change.
- **`k1_ops_tpf1`** (M5): one presented row at tick 217. combat_stress has a posed Bird of Prey, and the op stream's Manual Aim pick lands in its wing. Restoring the box rule in Python alone reproduced the old recording, which proves the move is M5 and not an unposed scene moving.
- **`tractor_modes`** (R8): one notes row at tick 720. The STARTED handler's stop now delivers after STARTED's other handler instead of nested inside it, so the SDK's `ConditionFiringTractorBeam` ends the tick at 0 with the beam off, where before it read 1.

The other four pass their Python recordings unchanged. The recorder went to schema 3 when `_baked_offset` was deleted. It reads schema-2 files by dropping that one torpedo column, so the unposed scenes did not have to be re-recorded.

Under R3, every scene now asserts zero dropped rows and zero `k1_no_fire`. The only arm is `native`, and any other arm raises.

### Recorded expectations

`test_native_k1_dispatch.py` and `test_native_sdk_weapon_routes.py` used to compare native against the Python copy. They now compare against recordings of that copy taken at `9c3db5ec6`, in `tests/fixtures/k1_dispatch/` (40 files, 540 KB). About 37 dispatch tests that tested only deleted scaffolding were deleted, and 50 remain.

`UPDATE_K1_DISPATCH=1` (fix round) records the native values as the new expectation, then skips and names the file. The rule is the goldens' rule: a re-record goes in its own commit and says why.

### Intended behaviour changes

Under M6, these follow from deleting the Python copy (Task 6 report, as amended by the fix round):

- A launch with no script spends no round.
- A tube whose slot lists are out of step with `MaxReady` does not fire. Python repaired them (`_ensure_slots`).
- A script-less ammo slot takes slot 0's script (fix round). Task 6 had made it launch nothing. If slot 0 is empty too, there is still no launch.
- K2 no longer obeys a class-patched `StopFiring` (M8.7).
- A fake target the mirror cannot name cannot be fired at.
- A pulse system whose held target dies is stopped again (fix round). Before the fix round it was not stopped at all.

Earlier tasks made two more. Native `CanFire` reads the mirrored `_dead`, so a ship whose `IsDead` is patched on the instance is not seen as dead (Task 5). A launch inside the stale-cache window uses the old cached module until the next K1 entry (Task 4, M8.3).

### Parked

- A no-fire found after a shot keeps `_force_update` set.
- A refused fire counts as a shot for R2's rollback.
- An offline system whose held target is a stub or not placed is never stopped: `gate_prescan` returns `stub_or_unplaced` every tick. Stub or unplaced held targets do not occur in stock play, and the goldens assert zero no-fires.
- `_go_live` (the first fire-control call bringing the mirror live) has no lock. Combat threading's workers never call fire control before `GameLoop.__init__`. A note for the next project.
- `tractor_row` over-counts on non-ship stubs. This is harmless.
- A call to a deleted method on an engine object (for example `update_weapons`) becomes a silent stub no-op through `TGObject.__getattr__`. The source guard stops the names coming back, but it does not find callers. The review found no live callers.

### Coverage lost

- The rollback when the whole session throws (`next()`'s catch) is not tested directly.
- The mid-walk "re-read the weapon count per group" and "retry snapshot" cases cannot be reached any more, and their tests are deleted.
- The K0 differential's stood-down raw-asleep case.
- The fake-weapon cloak and range pump-gate tests. The C++ `GateOrderStopsBeforeWalk` and the `can_detect` tests cover them.
- The fake sequential-firing and firing-chain walk tests. The C++ walk tests cover them.
- Three test files are deleted: `tests/integration/test_native_k1_differential.py` (its scenes now live in `tests/helpers/k1_fight.py`), `tests/unit/test_weapon_tick.py` (a fake-weapon walk) and `tests/unit/test_phaser_fire_sfx_edge_trigger.py` (now covered by the beam-edge recording and C++ tests).
- The recordings are Darwin only. Other platforms skip.

### Tests

- **Task 6:** focused set 4,928 passed, 20 xfailed, 0 failed; `ctest -R "combat_|EffectQueue"` 361/361. Every golden scene passed unchanged under the R3 assertion. With Mark's clearance, the mission-booting batch (86 passed, 1 xfailed) and the campaign sweep (8 passed) ran green.
- **Fix round:** ctest 362/362. The native list without its 8 mission-booting files: 2,098 passed, 0 failed. Goldens unchanged.
- **Owed:** a re-run of those 8 mission-booting files after the pre-scan reorder, on Mark's word.

Against §5: the source guard and the macOS goldens are done. The benchmark against SIG-178, the live check, the gate and the merge are open.
