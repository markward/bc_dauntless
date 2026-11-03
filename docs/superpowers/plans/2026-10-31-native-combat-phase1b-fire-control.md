# Native Combat Step — Phase 1b (K1 Fire Control) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The held-weapons pump decides in C++, for every ship, which systems stop, which banks fire and which fail. Python runs only the effects (events, sounds, projectile spawns), in the same order, and every value and event stays bit-identical to today's Python.

**Architecture:**
- **One C++ kernel, K1.** It walks `_pump_held_weapons` and `WeaponSystem.update_weapons` / `try_fire_weapon` for Phaser, Pulse and Torpedo systems as a state machine over the phase 1a mirror.
- **It stops at the first thing only Python may do.** That is a Fire effect, a StopFiring, an `ET_WEAPON_FIRE_FAILED` post, a dumb fire, or a system it cannot represent. It returns ONE record, then resumes from where it stopped, reading the live mirror again.
- **So no decision ever outlives a Python effect.** Spec §7.2's "decided on current state" holds by construction, without an epoch check (ruling P1).
- **Decision-time writes are mirrored back.** The writes the decision path makes (fire timers, `_depleted`, cleared targets, cursor and group bookkeeping, target-list prune, pulse target stamps) are made in the mirror and handed back as an ordered write log. Python applies the log to its own objects before each effect, without pushing again.
- **The split of each Fire.** Each Python `Fire` splits into `_fire_decide` and `_fire_effect`. The Python path calls both, so there is one copy of each rule.
- **Tractors stay Python.** So do articulated ships, targets without a real `IsDead`, and anything unrepresentable: they run today's Python for that system.

**Tech Stack:** C++20 (`native/src/combat/`, gtest), pybind11 in `native/src/host/host_bindings.cc`, Python 3.11, pytest.

**Spec:** `docs/superpowers/specs/2026-10-30-native-combat-step-design.md` §7.3 K1, §7.4, §7.5, §7.6 (approved by Mark). It builds on phase 1a: plan `docs/superpowers/plans/2026-10-31-native-combat-phase1a-can-detect.md`, rulings R1–R12 in spec §9.1 and the 1a ledger.

**Companion references (read before your task):**
- **K1M:** `docs/reference/engine/native-combat/k1-fire-control-map.md`. It is the exhaustive map of the path K1 replaces:
  - §1 the call graph verbatim;
  - §2 every attribute read, with its write sites;
  - §3 every float expression verbatim (F1–F14);
  - §4 the memos;
  - §5 every decision-path write, event and Python callback;
  - §6 the articulation;
  - §8 the split and risks.

  It is a snapshot at 7c6ece598: re-check line numbers against the code.
- **NIP:** `docs/reference/engine/native-combat/native-infra-patterns.md`.
- **Phase 1a's code:**
  - `engine/appc/native_combat.py`: `NativeField`, `NativeRefField`, `NativeFrozenField`, `register`, `push_field`, `push_ids`, `push_property`, `resync`, `audit_mirror`, `slot`, `now`, `counts`;
  - `native/src/combat/` (`mirror.h`, `sensor_detect.h`, `py_math.h`).

## Global Constraints

- **Bit-exact (spec §3.2, §5).**
  - Every SDK-visible value, every event (type, source, destination, order, tick) and every Python attribute K1 writes is identical to the Python path.
  - Floats are compared by `float.hex()`. Never use `pytest.approx` in a native-vs-Python test.
- **Exactness rules (spec §7.5, K1M §3):**
  - `double`, with Python operand order (left-associative).
  - `-ffp-contract=off` + `#pragma clang fp contract(off)`.
  - `py_min`/`py_max` ternaries in Python argument order. `sorted([a, b])` is `(b < a) ? swap : keep`.
  - `x ** 0.5` → `pow(x, 0.5)`; `TGPoint3.Length` → `std::sqrt`; `atan2`/`asin` from libm.
  - `MultMatrixLeft` sums `m00*x + m01*y + m02*z`.
  - The tube cone crosses LOCAL vectors and then rotates; the arc gate crosses WORLD vectors (K1M F9, F12).
  - Every NaN branch as in Python.
- **Constants come from Python.** These are pushed from the Python module values through `push_globals`, never retyped in C++:
  - `FIRE_TIMER_THRESHOLD`, the 700.0 phaser and 120.0 tractor ranges, `PULSE_COST_SCALE_BY_POWER_SETTING`;
  - the 0.5 s tube stagger, the 0.5235984 cone, `_PULSE_RANGE_GATE_SECONDS`, the 8.0 default lifetime, the 1e-6/1e-9 epsilons named in K1M.
- **Optimised inside Debug.** Each new combat `.cc` gets its own per-source `COMPILE_OPTIONS "-ffp-contract=off;$<$<CONFIG:Debug>:-O2>"` (one call per file) and the clang pragma. Never change `CMAKE_BUILD_TYPE`.
- **The switch is phase 1a's.**
  - `DAUNTLESS_NATIVE_COMBAT=1` on, `=0` / unset off. Default OFF until Mark's live check.
  - Read only in `native_combat.configure()`.
  - K1 runs only when `native_combat.enabled()`. Off means today's Python, byte-identical.
- **One live rule (spec §7.6.4).** With the switch on:
  - every held-weapon pump and every `StartFiring`'s immediate `update_weapons(0.0)` goes through K1;
  - the Python `Fire` and the K1 effect path share `_fire_effect`, so no rule exists twice in Python.
- **The lock.** `combat_k1_next` releases the GIL while it computes and reacquires it only to build its return tuple. The kernel touches no Python object (spec §3.3).
- **What K1 hands to Python, whole system** (ruling P2). The record is `RUN_PYTHON`, which runs today's Python for that system:
  - tractor systems (`_pump_self_managed`);
  - systems on a ship with any posed part (`articulation.posed_part_names(ship)` non-empty);
  - systems whose aim needs `target_offset_world` on a target with posed parts;
  - systems whose held target or a target-list entry has no real `IsDead` (its stub records telemetry);
  - pulse banks whose projectile module did not resolve;
  - any system with an unregistered, unrepresentable (-2) or stale row it would read.

  The kernel decides this **before** it writes anything for that system.
- **Memos (spec §7.6.3).** K1 uses 1a's native `can_detect` memo and a new native mount-position memo, keyed `(sub, ship_arg)` exactly as `subsystems._mounts` is. It is consulted only when the session was begun with `use_memo` (`step_memo.active()`), and cleared by the same `step_memo.on_forget` hook.
- **Focused tests only** (CLAUDE.md "Test gate"):
  - name every file;
  - never run whole suites, `scripts/check_tests.sh`, ctest without `-R`, or pytest with an empty file list.
  - C++ runs as `cmake --build build -j` then `ctest --test-dir build -R combat_ --output-on-failure`.
- **Shared checkout rules:**
  - never run `git checkout --`, `git restore`, `git stash`, `git clean`, `git reset --hard` or `git add -A/.`;
  - stage explicit paths; `git commit -F <file>`;
  - never commit to main.
  - Restore a mutated file only by `cp` from a backup.
- **Worktree:** `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-visibility`, branch `perf/native-combat` (head 98cf2ebb8 at plan time). Never run cmake inside `native/`. Never spell `game`/`sdk` as a path segment.

## Rulings made in this plan (surface to Mark)

- **P1. No epoch check in K1.** K1 returns one record per call and resumes against the live mirror, so a decision never spans a Python effect. Spec §7.2's epoch stays maintained for K2/K3. Cost if wrong: none for correctness; one extra binding call per effect (~25 fires, plus stops and fails, per tick).
- **P2. Whole-system Python fallback** for the list above. Cost: those systems are not sped up. Articulated ships (rigged mods, Bird of Prey) are the notable group.
- **P3. No per-decision audit for K1.** Effects post events, so running a Python reference decision beside each native one would double them. K1's oracle is the differential tests plus phase 1a's per-tick mirror audit, which now also covers every K1-written field. Spec §8's "each kernel decision with the Python reference" is narrowed for K1. Cost: a divergence shows only in the differentials, not in a live audit.
- **P4. The Python mount memo is not filled by K1.** Today `cb.phasers` reuses mount positions that `cb.held_weapons` memoised. With K1 native, the phaser step's Python memo is empty and computes fresh. The two differ only when an event handler moves a ship between the two scopes without a `forget()`. This is the same class as R9/R11, accepted and documented; it is fixed when K2 ports phasers. Cost: in that rare state, one phaser aim point uses the moved position.
- **P5. The `_target_offset` stamp uses the walk's own offset object.** Python's `update_weapons` computes `offset = self._live_held_offset()` once per walk. K1 asks Python for it with a `WALK_START` record and Python keeps the object, so each `_target_offset` write is the same object Python would store. Cost: one extra record per walked system (~150 per tick).
- **P6. Pulse projectile parameters are cached when the bank registers.** That is `mod.GetLaunchSpeed()` and `mod.GetLifetime()`, cached once per script and refreshed on mission swap with `_reset_projectile_module_cache`. Cost if a mod computes them dynamically: native uses the first value (the differential would show it).
- **P7. Kernel-written fields are copied back to Python, not native-only.** Spec §7.6.2 made fire timers native-owned, with Python getters reading the mirror. Here the kernel computes every write and Python applies it from the write log without pushing, so Python state, the passive-state machinery and the existing tests all stay valid. Cost: one Python write per logged field, about 0.1 ms a tick at 64 ships (to be measured in Task 7).

## Review Focus

1. **An SDK handler on `ET_WEAPON_FIRED` / `ET_TORPEDO_FIRED` / `ET_WEAPON_FIRE_FAILED` changes state mid-walk.** For example: `StopFiring` on the firing system, `StartFiring` (re-entrant K1), destroying a tube, turning sensors off. The rest of the walk behaves exactly as Python's would. Tested in Task 4 (`ReentrantSessionStack`) and Task 6 (`test_handler_stops_and_restarts_mid_walk`).
2. **A torpedo tube fails against a target outside its cone while two targets are in its list.** `ET_WEAPON_FIRE_FAILED` posts the same number of times, in the same order: 1 + live list entries, including the retry of `_target_list[0]`. Tested in Task 4 (`TubeRetryPostsFailedPerAttempt`) and Task 6.
3. **A phaser bank restarts after running dry.** `_depleted` clears inside `CanFire` exactly as Python does, and a lit beam keeps firing through the 0.33 s timer. Tested in Task 3 (`test_charge_gate_depleted_latch`) and Task 6.
4. **An AI re-targets without `StopFiring`.** The target list is then `[t1, t2]`: the pump gates on `_held_target == t2` but fires at `_target_list[0] == t1` (K1M §1.6), and native must copy it. Tested in Task 4 (`HeldTargetVsListHead`).
5. **The player uses Manual Aim with a locked subsystem, or a ship carries banks on a rig.** Manual aim goes native with the walk's offset object; rigged ships fall back whole. Both give the Python answers. Tested in Task 6 (`test_manual_aim_offset_matches`, `test_rigged_ship_runs_python`).

---

### Task 1: Mirror the weapon systems, banks, tubes, ammo and firing chains

**Files:**
- Modify:
  - `native/src/combat/include/dauntless/combat/mirror.h`, `native/src/combat/src/mirror.cc`: new Subsystem fields, a new row kind `Ammo`, and Property fields `_firing_chains` / `_groups`;
  - `native/tests/combat/mirror_test.cc`;
  - `engine/appc/native_combat.py`: `NativeWakeField` (WakeField + push, shaped like `NativeFrozenField`), `push_ammo`, and registration flags;
  - `engine/appc/weapon_subsystems.py`: descriptors and mutators;
  - `engine/appc/subsystems.py`: `_is_on` becomes a `NativeFrozenField`; `_children` append routed through `push_ids`;
  - `engine/appc/properties.py`: firing-chain and groups writes push;
  - `tests/conftest.py`, only if a new reset is needed.
- Test: `tests/unit/test_native_combat_weapons_mirror.py`

**Interfaces:**
- Consumes 1a: `register`, `NativeField(type_)`, `NativeRefField(target)`, `NativeFrozenField`, `push_ids`, `push_property`, `combat_dump`, `audit_mirror`. Rulings R1 (add fields in the same commit), R2, R6 (-2 refs).
- Produces mirrored state that Tasks 2–4 read:
  - **WeaponSystem:**
    - `_fire_held`, `_held_target` (ref), `_held_offset` (fv3 or unset);
    - `_target_list` (ordered handles, `push_ids` after `_add_target`'s append, `_prune_targets`' rebind and `StopFiring`'s rebind);
    - `_force_update`, `_last_weapon_idx`, `_last_group_fired`, `_firing_chain_mode`, `_group_fire_mode`, `_single_fire`;
    - `_children` (ordered);
    - `_last_system_fire_time` (TorpedoSystem);
    - `_selected_slot` and `_ammo_by_slot` (slot → Ammo handle, pushed by a mutator);
    - class flags `weapon_kind` (0 none, 1 phaser system, 2 pulse system, 3 tractor system, 4 torpedo system, 5 phaser bank, 6 pulse weapon, 7 tractor beam, 8 torpedo tube) and `pump_self_managed`.
  - **Banks and tubes:**
    - `_fire_timer`, `_firing`, `_charge_level`, `_min_firing_charge`, `_depleted`;
    - `_normal_discharge_rate`, `_power_setting`, `_cooldown_remaining`, `_cooldown_time`;
    - `_target` (ref), `_target_offset` (fv3 or unset);
    - `_num_ready`, `_last_fire_time`, `_immediate_delay`, `_skew_fire`;
    - `_position`, `_direction`, `_up`, `_right` (fv3);
    - `_arc_width_lo/_hi`, `_arc_height_lo/_hi`, `_arc_set`;
    - pulse `launch_speed`, `lifetime`, `module_ok` (P6; pushed by Python after it resolves the module).
  - **Ammo:** `_unlimited`, `_available`.
  - **Property:** `_firing_chains` (a list of group lists, in mode order), `_groups` (int).
  - **Ships:** `_velocity` (fv3, always rebound per K1M §2c); `_phaser_system`, `_pulse_weapon_system`, `_tractor_beam_system`, `_torpedo_system` (refs); flag `has_posed_parts`, pushed at registration and re-pushed wherever `_articulation_poses` changes (K1M §6 write sites) and on `reclassify`.
  - **Every Object:** flag `has_real_is_dead` = `implements(type(obj), "IsDead")`.
- Fields already behind a `WakeField` become `NativeWakeField`. Fields behind a `FrozenField` become `NativeFrozenField`. Wake and thaw stay exactly as before.

- [ ] **Step 1: Write the failing tests** `tests/unit/test_native_combat_weapons_mirror.py`. Skip unless `hasattr(_h, "combat_register")`; enable native with `native_combat.configure({"DAUNTLESS_NATIVE_COMBAT": "1"})`. Use a real Galaxy (phasers + tubes) and a real Klingon ship with pulse disruptors through the hardpoint setup path.
  - `test_every_weapon_field_writes_through`: drive each field through its public API, and after each write assert `combat_dump` equals the Python value by `.hex()`. The APIs are `StartFiring`, `StopFiring`, `SetSingleFire`, `SetFiringChainMode`, `SetChargeLevel`, `SetPowerSetting`, `ReloadTorpedo`, `SetSkewFire`, `AddAmmoType`, ammo `SetAvailable` / `AddAvailable`, `SetVelocity`, `TurnOff` / `TurnOn`.
  - `test_target_list_order_follows_append_and_prune`: `StartFiring(t1)` then `StartFiring(t2)` without a stop gives a list of `[t1, t2]`.
  - `test_pulse_module_params_pushed` (P6).
  - `test_posed_parts_flag_follows_force_pose`.
  - `test_wake_and_thaw_unchanged`: a sleeping full bank still wakes on `_charge_level` writes; a frozen power consumer still thaws on `_is_on`.
  - `test_audit_mirror_clean_on_combat_stress`: load `engine.dev_missions.combat_stress` headless with 6 ships and native on, drive 120 ticks through `host_loop._advance_weapons` / `_advance_combat`, and assert `audit_mirror()` leaves `audit_failures() == []`.

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_native_combat_weapons_mirror.py -v`. Expected: FAIL (fields absent from `combat_dump`).

- [ ] **Step 3: Implement.** List every write site of every converted field in your report (K1M §2 plus your own grep), and route every in-place mutation through a pushing mutator. The ones K1M names are `_target_list.append`, `_children.append`, `_ammo_by_slot[k] =` and the `_articulation_poses[name] =` sites.

- [ ] **Step 4: Run** the new test plus `tests/unit/test_native_combat_mirror.py tests/unit/test_native_combat_world.py tests/unit/test_passive_power.py tests/unit/test_passive_state.py tests/unit/test_weapon_tick.py tests/unit/test_firing_chains.py tests/unit/test_torpedo_tube_fire.py -v`, and `ctest --test-dir build -R combat_`. Expected: PASS.

- [ ] **Step 5: Commit** (`feat(native-combat): mirror weapon systems, banks, tubes, ammo and chains`).

---

### Task 2: Native weapon geometry and the native mount memo

**Files:**
- Create: `native/src/combat/include/dauntless/combat/weapon_geometry.h`, `native/src/combat/src/weapon_geometry.cc`, `native/tests/combat/weapon_geometry_test.cc`
- Modify: `native/src/combat/CMakeLists.txt`, `native/tests/combat/CMakeLists.txt`, `native/src/host/host_bindings.cc`, `native/src/combat/src/sensor_detect.cc` (the memo clear also clears the mount memo)
- Test: `tests/unit/test_native_weapon_geometry.py`

**Interfaces:**
- Produces, in `dauntless::combat`, one function per Python function, named after it, reading the Mirror and the TransformStore:
  - `subsystem_world_position(sub, ship_arg, use_memo)`, the identity-pose path only: `ship_pos + R·local`, no scale. It throws `std::invalid_argument` if the ship has posed parts. It is memoised by `(sub, ship_arg)` when `use_memo`.
  - `_resolve_aim_world(ship)`, `_resolve_bank_aim_world(bank, target, use_memo)` (K1M F7, `** 0.5` = `pow`).
  - `_emitter_in_arc(emitter, ship, aim)` (F9).
  - `_emitter_forward_world(emitter, ship)`.
  - `target_offset_world(target, offset)` (F11): identity-pose targets only, else throw. `target.GetScale()` applies.
  - `_resolve_torpedo_aim_point(tube, target)`, `_in_torpedo_cone(tube, ship, aim)` (F12).
  - `_solve_pulse_launch_direction(cannon, ship, target)` (F13, using the mirrored `launch_speed`/`lifetime`; target acceleration is (0,0,0)).
  - `_target_within_range_gu(ship, target, max)` (F2, including `_same_set`).
- Each of these gets a `combat_test_<name>(...)` binding taking handles and returning the tuple or bool.

- [ ] **Step 1: Write the failing tests** `tests/unit/test_native_weapon_geometry.py`. Build real ships with native on, then randomise poses and positions through `SetTranslateXYZ` / `SetMatrixRotation` (seeded `random.Random(20261031)`, 2,000 cases each, plus K1M's NaN, degenerate-length and reversed-arc edges). Compare each binding with the Python function by `.hex()`:
  - `test_mount_position_matches`;
  - `test_bank_aim_world_matches` (including the length ≤ 1e-6 fallback);
  - `test_emitter_in_arc_matches` (`_arc_set` false and true, reversed bounds, NaN up_dot → pitch π/2);
  - `test_torpedo_cone_matches` (the boundary at exactly 0.5235984);
  - `test_target_offset_world_matches` (scaled target, offset at a subsystem mount);
  - `test_pulse_launch_matches` (v_eff ≤ 0, t > lifetime, the 30 × v_eff gate);
  - `test_range_gate_matches` (700 / 120, cross-set);
  - `test_posed_ship_throws`.

  The mount memo gets a gtest: `MountMemoKeyIncludesShipArg` (the same sub under ship_arg none vs ship gives two entries), and the memo is cleared by `memo_clear`.

- [ ] **Step 2: Run** the test file and `ctest -R combat_`. Expected: FAIL (bindings missing).

- [ ] **Step 3: Implement.** Port line by line, in K1M operand order; the Python function names are the C++ names.

- [ ] **Step 4: Run** the new pytest file, `tests/unit/test_arc_gate.py tests/unit/test_bank_aim_world.py tests/unit/test_torpedo_fire_gates.py tests/unit/test_pulse_aimed_launch.py -v` and `ctest -R combat_`. Expected: PASS.

- [ ] **Step 5: Commit** (`feat(native-combat): native weapon geometry and mount memo`).

---

### Task 3: Native fire gates: `_is_offline` for weapon systems, `IsOn`, and each `CanFire`

**Files:**
- Create: `native/src/combat/include/dauntless/combat/fire_gates.h`, `native/src/combat/src/fire_gates.cc`, `native/tests/combat/fire_gates_test.cc`
- Modify: `native/src/combat/CMakeLists.txt`, `native/tests/combat/CMakeLists.txt`, `native/src/host/host_bindings.cc`
- Test: `tests/unit/test_native_fire_gates.py`

**Interfaces:**
- Produces:
  - `bool weapon_system_offline(sys)`: `_is_offline` with WeaponSystem's aggregate `IsDisabled` / `IsDestroyed` (all children; K1M F5) plus the radiation and out-of-action checks. It reuses 1a's sensor `_is_offline` pieces where they are the same rule.
  - `struct CanFireResult { bool ok; bool clear_depleted; }`.
  - `CanFireResult can_fire(bank, double now)`, dispatching on `weapon_kind`:
    - the energy mixin (K1M §1.4): parent `IsOn`, ship dead, `_charge_gate` with the `_depleted` clear REPORTED, not written, and the condition product (F3);
    - pulse: cooldown first, then the mixin with the pulse charge gate (F4);
    - tube: K1M §1.4, every gate in order, with `now` as the weapon game time.
  - `bool ship_dead(obj)` honouring `has_real_is_dead` (false → throw: P2 fallback).
- Bindings: `combat_test_can_fire(bank, now) -> (ok, clear_depleted)` and `combat_test_weapon_system_offline(sys)`.

- [ ] **Step 1: Write the failing tests** `tests/unit/test_native_fire_gates.py`. Use real banks, 1,000 seeded random states each, set through public setters (charge, condition, parent condition, disabled percentage, `TurnOff`, power setting, cooldown, ready count, last fire time, ammo, skew). Run Python `CanFire()` on a snapshot and compare `ok` with the native answer and `clear_depleted` with whether Python flipped `_depleted`:
  - `test_charge_gate_depleted_latch` (Review Focus 3);
  - `test_condition_product_nan_passes`;
  - `test_pulse_affordability_1e9_boundary`;
  - `test_tube_stagger_exclusive_boundary` (exactly 0.5 s, skew-exempt);
  - `test_weapon_system_offline_matches`.

- [ ] **Step 2: Run** the test file. Expected: FAIL (bindings missing).

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run** the test file, `tests/unit/test_phaser_canfire_fidelity.py tests/unit/test_energy_weapon_discharge_source.py tests/unit/test_weapons_disabled_blocks_fire.py tests/unit/test_is_offline_helper.py -v` and `ctest -R combat_`. Expected: PASS.

- [ ] **Step 5: Commit** (`feat(native-combat): native fire gates`).

---

### Task 4: The K1 kernel: a resumable pump and walk with one record per call

**Files:**
- Create: `native/src/combat/include/dauntless/combat/k1_fire_control.h`, `native/src/combat/src/k1_fire_control.cc`, `native/tests/combat/k1_fire_control_test.cc`
- Modify: `native/src/combat/CMakeLists.txt`, `native/tests/combat/CMakeLists.txt`, `native/src/host/host_bindings.cc`

**Interfaces:**
- **Sessions.** A session holds the K1 cursor. Sessions form a STACK, so a `StartFiring` from an event handler opens a nested one-system session and finishes it before the outer one resumes.
- **Bindings:**
  - `combat_k1_begin_pump(ship_handles: list[int], dt: float, now: float, use_memo: bool) -> None`;
  - `combat_k1_begin_system(system: int, dt: float, now: float, use_memo: bool) -> None` (StartFiring's `update_weapons(0.0)`);
  - `combat_k1_next() -> tuple` (releases the GIL while computing);
  - `combat_k1_set_offset(xyz: tuple | None) -> None`;
  - `combat_k1_end() -> None` (pops; the session must have returned `DONE`).
- **Record tuples** (`kind` ints exposed by `combat_k1_kinds() -> dict`). Each record carries `writes`, the ordered write log since the last record, as a list of `(handle, field_name, value)`. Python applies it before acting.
  - `("WALK_START", system)`: Python replies with `combat_k1_set_offset(sys._live_held_offset() as xyz or None)`.
  - `("STOP_SYSTEM", system, writes)` → `sys.StopFiring()`.
  - `("RUN_PYTHON", system, writes)` → Python runs that system's today-path step (the pump branch or `update_weapons(dt)`). The kernel guarantees `writes` is empty for this system.
  - `("BANK_STOP", bank, writes)` → `bank.StopFiring()` (the CanFire-failed branch).
  - `("FIRE", bank, target_handle_or_-1, decision, writes)` → `bank._fire_effect(target, offset, decision)`. `decision` is the kernel-computed tuple in exactly the shape Task 5's `_fire_decide` returns per weapon kind (beam `(was_firing,)`; pulse `(world_dir_xyz, target_used_handle)`; tube `(target_used_handle,)`); Python maps handles to objects before calling.
  - `("FIRE_FAILED", tube, writes)` → `tube._broadcast_weapon_fire_failed()`.
  - `("FIRE_DUMB", tube, writes)` → `tube.FireDumb(0, 1)`.
  - `("DONE", writes)`.
- **The kernel never writes Python state.** Its mirror writes are made in the mirror and logged:
  - `_fire_timer`;
  - `_depleted` (from `CanFireResult.clear_depleted`);
  - `_target = None` after a failed attempt;
  - pulse `_target` / `_target_offset` stamps before the arc test (offset value = the walk's offset; Python writes the walk's offset OBJECT, per P5);
  - `_force_update`, `_last_weapon_idx`, `_last_group_fired`, `_group_fire_mode`;
  - `_reseed_all_fire_timers`;
  - `_target_list` after `_prune_targets`.
- **The walk** is K1M §1.1–§1.3, verbatim, including:
  - the dead-ship early return leaving `_force_update` set;
  - `_single_fire`'s lit-weapon path;
  - `n` re-read per group;
  - the retry loop reading the LIVE target list after each effect;
  - `_weapon_did_fire` being True after every FIRE;
  - the dumb-fire branch.
- **Fallback order:** P2's checks run before the first write for a system.

- [ ] **Step 1: Write the failing gtests** `k1_fire_control_test.cc` on hand-built mirror rows (local `TransformStore` and `Mirror`):
  - `GateOrderStopsBeforeWalk`: offline → `STOP_SYSTEM`; then dead held target; undetectable; out of range.
  - `TimerGateAndForceUpdate`: 0.33 s, force bypass, lit beam bypass, reset to 0.0 after every passed gate.
  - `RoundRobinFromLastIdx`.
  - `SingleFireReseedsTimers`.
  - `GroupWalkAdvancesOnDryGroup`.
  - `TubeRetryPostsFailedPerAttempt`: the 1 + live-entries count, including the head retried.
  - `HeldTargetVsListHead` (Review Focus 4).
  - `DumbFireOnlyWithNoTargets`.
  - `DeadShipEarlyReturnKeepsForceUpdate`.
  - `PythonFallbackBeforeAnyWrite`: a posed ship, a -2 list entry, a stub-`IsDead` target, an unresolved pulse module.
  - `ReentrantSessionStack`: begin a pump, take a FIRE, begin and finish a nested system session, resume.
  - `ResumeReadsLiveMirror`: after a FIRE, set the system `_fire_held` false through the mirror, and the next record reflects it.

- [ ] **Step 2: Run** `cmake --build build -j` and `ctest -R combat_K1`. Expected: build failure, then assertion failures as you go.

- [ ] **Step 3: Implement** the state machine as explicit cursor states mirroring the Python control flow.
  - Name each state after the Python line it stands for.
  - Use Tasks 2–3 for every geometry and gate decision, and 1a's `can_detect` for `_target_undetectable` (exception → "detectable", as in Python).
  - A 1a fallback `ValueError` inside the gate stage turns that system into `RUN_PYTHON`. It is safe because no write has happened yet.

- [ ] **Step 4: Run** `ctest --test-dir build -R combat_ --output-on-failure`. Expected: PASS.

- [ ] **Step 5: Commit** (`feat(native-combat): K1 fire-control kernel`).

---

### Task 5: The Python side: split each Fire into decide and effect, and drive K1

**Files:**
- Modify:
  - `engine/appc/weapon_subsystems.py`:
    - mixin `Fire` → `_fire_decide(target, offset) -> tuple | None` and `_fire_effect(target, offset, decision) -> bool`;
    - the same split for `PhaserBank.Fire`, `PulseWeapon.Fire` and `TorpedoTube.Fire`;
    - each `Fire` becomes `d = self._fire_decide(...); return False if d is None else self._fire_effect(..., d)` (tube: its FIRE_FAILED posts stay inside `_fire_decide`'s failure branch on the Python path);
    - `WeaponSystem.StartFiring` dispatches its immediate `update_weapons(0.0)` to K1 when native is on;
  - `engine/host_loop.py`: `_pump_held_weapons` gains its native branch;
  - `engine/appc/native_combat.py`: `run_k1(records_source) -> None`, the shared record loop; `apply_writes(writes) -> None`, which writes each value without pushing (descriptor fields through the descriptor with the push suppressed, so wake and thaw still happen; plain fields into `__dict__`); and counts `k1_records`, `k1_python_systems`.
- Test: `tests/unit/test_native_k1_dispatch.py`

**Interfaces:**
- Consumes the Task 4 bindings and records.
- `_fire_decide` returns, per kind:
  - beam: `(was_firing,)` after CanFire and `_aim_in_arc` pass;
  - pulse: `(world_dir_xyz, target_used)` after the module, fallback-target, stamp, solve and arc steps;
  - tube: `(target_used,)` after the CanFire, aim-point and cone checks.
- `_fire_effect` does exactly today's post-decision lines (K1M §1.4 "DECISION ENDS") and returns True.
- `run_k1` loop:
  1. for each record, `apply_writes(writes)`;
  2. act per Task 4's table, mapping handles to objects through `native_combat`'s registry;
  3. on `WALK_START`, compute and keep the walk's offset object;
  4. call `combat_k1_next()` again until `DONE`, then `combat_k1_end()`.
- `_pump_held_weapons(ships_list, dt)` with native on calls `combat_k1_begin_pump([slot(s) ...], dt, weapon_game_time, step_memo.active())`. Ships without a slot are run through today's Python loop body at their place in the order: the kernel emits `RUN_PYTHON` for each of their systems. Pass a `-1` handle for them.

- [ ] **Step 1: Write the failing tests** `tests/unit/test_native_k1_dispatch.py`. Each runs a scenario twice (native off / on) with real ships and compares every bank's `(IsFiring, _target is None, _fire_timer.hex(), _depleted, GetChargeLevel().hex(), GetNumReady())` and the event log (`ET_WEAPON_FIRED`, `ET_TORPEDO_FIRED`, `ET_WEAPON_FIRE_FAILED`, `ET_TORPEDO_AMMO_CONSUMED`, `ET_CANT_FIRE`: type, source, destination, order) after each tick:
  - `test_phaser_volley_matches`;
  - `test_pulse_lead_and_cooldown_matches`;
  - `test_tube_cone_failures_match`;
  - `test_single_fire_and_chain_modes_match`;
  - `test_start_firing_immediate_update_matches`;
  - `test_fire_split_is_behaviour_neutral`: with native off, the split `Fire` gives identical results on the existing fire tests' scenarios. It runs `tests/unit/test_torpedo_tube_fire.py`'s and `tests/unit/test_pulse_weapon_fire.py`'s cases by importing them, or the step-4 command covers it.
  - `test_unregistered_ship_runs_python_in_order`.
  - `test_apply_writes_wakes_sleeping_bank`.

- [ ] **Step 2: Run** the test file. Expected: FAIL.

- [ ] **Step 3: Implement.** Keep `_fire_effect` the ONLY copy of each effect.

- [ ] **Step 4: Run** the new file plus `tests/unit/test_weapon_tick.py tests/unit/test_start_firing_arms_tick.py tests/unit/test_weapon_system_sequential_firing.py tests/unit/test_firing_chains.py tests/unit/test_torpedo_tube_fire.py tests/unit/test_torpedo_fire_gates.py tests/unit/test_pulse_weapon_fire.py tests/unit/test_pulse_aimed_launch.py tests/unit/test_phaser_canfire_fidelity.py tests/unit/test_energy_weapon_gating.py tests/unit/test_manual_aim.py tests/integration/test_pulse_singlefire_modes.py tests/integration/test_phaser_multi_bank_fire.py tests/integration/test_tractor_singlefire_dispatch.py -v`. Expected: PASS (these run with native off: the split must be neutral).

- [ ] **Step 5: Commit** (`feat(native-combat): fire split and K1 dispatch`).

---

### Task 6: Differentials, the scene audit, and the 1a test follow-ups

**Files:**
- Create: `tests/integration/test_native_k1_differential.py`
- Modify:
  - `tests/integration/test_native_combat_step_differential.py`: add a fractional sensor-power op (`SetPowerPercentageWanted` on sensors), assert `fallbacks == 0` in the on and audit arms, and record K1 counts;
  - `tests/host/test_native_combat_scene_audit.py`: assert `audit_mirror` actually ran (count it) and that `k1_records > 0`.

**Interfaces:** consumes everything above; copies the 1a differential helpers (`_Scene`, `_both`, `_hex`, `record`).

- [ ] **Step 1: Write** `test_native_k1_differential.py`:
  - seeded `combat_stress`, 8 ships, 600 ticks, `ticks_per_frame` 1 and 6, reference arm `"0"` vs native arm `"1"`;
  - assert the scene contains phaser, pulse and torpedo ships (counts > 0);
  - seeded ops between frames through public APIs: `StartFiring` / `StopFiring` / retarget without stop, `SetSingleFire`, `SetFiringChainMode`, `TurnOff` / `TurnOn` weapons, `SetCondition` on banks, `SetPowerSetting`, ammo exhaustion, Manual Aim on and off with a locked subsystem;
  - per tick, compare every bank's state tuple (as in Task 5) and the full event log;
  - `test_handler_stops_and_restarts_mid_walk`: register an SDK-style handler on `ET_WEAPON_FIRED` that calls `StopFiring` and then `StartFiring` on another ship's system (Review Focus 1);
  - `test_manual_aim_offset_matches`;
  - `test_rigged_ship_runs_python`: force a pose on one ship and assert `k1_python_systems > 0` with identical results;
  - assert `k1_records > 0` in the native arm.

- [ ] **Step 2: Run** the three files. Expected: PASS. A difference is a porting bug: fix it in the kernel or a missed write-through, never in the test.

- [ ] **Step 3: Prove each file can fail** under a mutation its own scene exercises, backed up and restored by `cp` and checked with `diff`:
  - the K1 differential: drop `_reseed_all_fire_timers`, or retry the head only once;
  - the step differential: reorder `base*(cond*power)`, which the fractional op now catches;
  - the scene audit: skip one sync-back write.

- [ ] **Step 4: Commit** (`test(native-combat): K1 differentials and 1a test follow-ups`).

---

### Task 7: Measure, record, document

**Files:**
- Modify:
  - `docs/reference/engine/perf-register.md`: new capture rows and signals continuing from the file's maximum IDs;
  - `CLAUDE.md`: update the "Native combat mirror + sensor detection" row to cover K1. Keep it ≤ 1200 chars; it says "R1–R12" plus "P1–P7".
  - the spec: add §9.2 with this plan's rulings P1–P7 and the measurement, and add R12 to §9.1;
  - `docs/reference/engine/native-combat/k1-fire-control-map.md`: a header note that phase 1b implemented it.

- [ ] **Step 1: Take the paired captures** with the 1a method: four runs (fight / quiet × native on / off), 90 s cool-downs, `DAUNTLESS_PROFILE_FRAMES=1500`, 64 ships, bash runner in the scratchpad, after checking `pgrep -fl "pytest|check_tests|dauntless"` is empty.
  - Score per tick as **value ÷ average ticks per frame** (SIG-157), never `value / calls`.
  - Report `cb.held_weapons`, `cb.phasers`, `sim.combat`, `gl.ai`, total sim and python-loop per frame.

- [ ] **Step 2: Judge phase 1 against spec §7.6.6.**
  - Is the native arm's `cb.held_weapons` down by at least half against the off arm?
  - Is total sim per tick not higher?

  Say plainly which. If the fights differ in projectiles in flight by more than 25%, say the pair is not separable.

- [ ] **Step 3: Run** `uv run pytest tests/docs/test_doc_consistency.py -v`. Expected: PASS.

- [ ] **Step 4: Commit** (`docs(native-combat): phase 1b measurements and rulings`).

After Task 7 the controller hands Mark:
- the numbers;
- the live-test command (`DAUNTLESS_NATIVE_COMBAT=1 ./build/dauntless --developer`: a big Quick Battle with Klingon, Romulan and Federation ships, torpedoes, and Manual Aim).

The default flips to on only after his check, as a separate change.
