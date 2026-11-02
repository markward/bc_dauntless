# Native combat: weapon state — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut ~1.3 ms/tick of Python↔C++ sync and Python weapon stepping: K1/K2 write logs applied in C++, a one-call scalar push, and a native charging/reloading kernel (K0).

**Architecture:** The bindings apply write logs straight into the Python objects' `__dict__` (same order, kinds and exception semantics as `apply_writes`). Scalar `NativeField` pushes encode in C++. K0 is a K1-style session over every weapon in the reference order, logging writes and handing back records only for sounds, events, watcher crossings and objects it cannot stand in for.

**Tech Stack:** C++17 combat library (`native/src/combat/`), pybind11 (`native/src/host/host_bindings.cc`), Python driver (`engine/appc/native_combat.py`), pytest + gtest.

**Spec:** `docs/superpowers/specs/2026-11-02-native-weapon-state-design.md`. Maps: `docs/reference/engine/native-combat/weapon-state-map.md` (WSM), `docs/reference/engine/native-combat/native-infra-patterns.md`.

## Global Constraints

- Worktree `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/native-combat-damage`, branch `ws/combat-weapon-state`. Build `cmake --build build -j`; never reconfigure, never cmake inside `native/`, never change BUILD_TYPE; delete the `.o` to force a recompile when mutating.
- Bit-exact: floats by `.hex()` (−0.0 included); Python's write ORDER, object IDENTITY (new lists stay new, in-place lists stay the same object), value TYPES (`True`/`False` stay bool); events in the same order.
- Ruling P1: logged writes are applied before any later Python runs. A field the kernel reads MUST push from every writer, in-place list writers included.
- Switch `DAUNTLESS_NATIVE_COMBAT=1`, default OFF, byte-identical off. `DAUNTLESS_NATIVE_AUDIT=1` / `DAUNTLESS_PASSIVE_AUDIT=1`: K0 stands down (reason `audit`). GIL held.
- K0 steps every weapon (the per-tick model), never consults or changes the passive awake list; tractor beams always hand back (superseded by ruling W6, §10: idle tractors step natively).
- Focused tests only, by name; never whole suites/directories, `scripts/check_tests.sh`, pytest with no files, or `ctest` without `-R`. Engine-class guard active: `monkeypatch` only.
- Git: banned `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage explicit paths; `git commit -F <file>`; end messages with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. Restore mutated files by `cp`, then `diff`.
- Never spell `game` or `sdk` as a path segment. Never launch `./build/dauntless` (the controller runs benchmarks).

## Review Focus

1. A K1 log whose walk-offset `materialise` raises mid-record under C apply: every later write still applied (later markers of that walk skipped), the same exception re-raised with the same notes as `apply_writes`. Test in Task 1.
2. A `RELOADED` record whose `ET_TORPEDO_RELOAD` handler calls `StartFiring` on the same ship (nested K1 system session): K1 sees post-step values for weapons already stepped and pre-step values for later ones, exactly as Python. Test in Task 5.
3. A record's Python writes a later weapon's charge (`SetChargeLevel`) mid-walk: that weapon is stepped this tick from the new value (WakeField wake fired, mirror pushed). Test in Task 5.
4. A multi-tick frame (3 K0 sessions back to back with the same `now`): tubes credit the whole interval in the first session and 0 after, as Python. Test in Task 6.
5. The switch turned on (`configure` → `resync`) after tube slot lists were mutated in place with the switch off: resync pushes the current FloatList values. Test in Task 3.

---

### Task 1: C-applied write logs (K1, K2)

**Files:** create `native/src/host/combat_write_apply.{h,cc}` (added to the host target in its CMakeLists); modify `native/src/host/host_bindings.cc` (`combat_k1_begin_pump`, `combat_k1_begin_system`, `combat_k1_next`, `combat_k2_begin`, `combat_k2_next`), `engine/appc/native_combat.py` (`run_k1`, `run_k2`, `_k2_deliver`, a new `_applier_context(walk)`); tests `tests/unit/test_native_write_apply.py` (new), plus `tests/unit/test_native_k1_dispatch.py`, `tests/unit/test_native_k2_dispatch.py`.

**Interfaces:**
- Produces: binding `combat_set_applier(ctx)` taking `(pins: dict, registry: Mapping, walk: object, kinds: dict[str, int], wake: callable, python_setters: dict[str, callable])`, set per session by the driver; `combat_k1_next()` (and K0's next, Task 5) apply the record's writes before returning and return the record with `writes == []`. A record's writes stay in the binding until applied; `combat_apply_writes(upto=None)` applies the pending ones up to index `upto` (all when None). `combat_k2_next()` applies all writes itself only when the record has no queued resting contacts; otherwise `_k2_deliver` calls `combat_apply_writes(at)` before each contact and `combat_apply_writes()` before the record's own effect, keeping today's interleaving (round-trips Review Focus 4). Its record's `writes` element becomes the count of pending writes. Apply kinds as constants `APPLY_PLAIN, APPLY_REF, APPLY_REFS, APPLY_WAKE, APPLY_PYTHON, APPLY_SLOT, APPLY_WATCHER` (exported via `combat_apply_kinds()`). `native_combat.apply_writes` stays (reference + K0 Task 5 uses the same C path). Counter `counts()["c_applied_writes"]`.
- Consumes: `_quiet_setter(cls, name)` (NC) to build `kinds` per (class, field) — the context maps field name → kind per class via a lookup the binding calls once per (type, field) and caches.

- [ ] **Step 1: Failing tests** in `tests/unit/test_native_write_apply.py`: `test_c_apply_equals_python_apply_random_logs` (2,000 seeded logs over twin objects: dicts equal by `.hex()`/identity-shape, wake counts equal); `test_ref_list_write_is_new_list_each_time`; `test_wake_kind_wakes_sleeping_bank`; `test_bool_values_stay_bool`; `test_materialise_raise_applies_rest_then_reraises` (Review Focus 1: same type, same `__notes__`); `test_python_kind_setter_called_in_order`; `test_records_return_empty_writes` (K1, and K2 without queued contacts); `test_k2_queued_contacts_interleave_with_c_applied_writes` (each contact sees exactly the writes logged before its `at`, none after); `test_c_applied_counter`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_native_write_apply.py -q` → FAIL.
- [ ] **Step 3: Implement** the applier in C++ (GIL held; interned attribute names; per-type kind cache invalidated when `combat_set_applier` is called with a new `kinds`).
- [ ] **Step 4: Run** the new file + `tests/unit/test_native_k1_dispatch.py tests/unit/test_native_k2_dispatch.py tests/unit/test_native_k1_holds_gil.py tests/integration/test_native_k1_differential.py tests/host/test_native_k2_differential.py` + `ctest --test-dir build -R combat_` → PASS.
- [ ] **Step 5: Commit** `perf(native-combat): apply K1/K2 write logs in C++`.

### Task 2: One-call scalar push

**Files:** `native/src/host/host_bindings.cc` (new `combat_push_scalar`), `engine/appc/native_combat.py` (`NativeField.__set__`, `NativeWrapped._after_set`, a per-descriptor scalar code set in `__set_name__`); test `tests/unit/test_native_fast_push.py` (new).

**Interfaces:**
- Produces: `combat_push_scalar(h: int, fid: int, code: int, value) -> None` with codes `PUSH_FLOAT, PUSH_INT, PUSH_BOOL, PUSH_IS_TRUE, PUSH_OPT_INT` (`combat_push_codes()`); raises `TypeError`/`ValueError`/`OverflowError` exactly where `NativeField._encode` raises, so the caller's `_drop(obj)` path is unchanged; a stale handle raises `ValueError` as `_call` expects. Counter `fast_pushes`.

- [ ] **Step 1: Failing tests:** `test_fast_push_encodes_like_encode` (per code over floats incl. NaN, ±0.0, inf, ints, bools, `None`, a float subclass, an object with `__float__`/`__index__`, strings → raise), mirror value equal by `.hex()` to the `_push` path; `test_unencodable_drops_row`; `test_switch_off_never_calls_binding`; `test_wake_field_push_uses_fast_path`.
- [ ] **Step 2-4:** FAIL → implement → run the new file + `tests/unit/test_native_combat_weapons_mirror.py tests/unit/test_native_k1_dispatch.py` + `ctest -R combat_` → PASS.
- [ ] **Step 5: Commit** `perf(native-combat): one-call scalar mirror push`.

### Task 3: Mirror K0's inputs

**Files:** `native/src/combat/include/dauntless/combat/mirror.h` + `src/mirror.cc` (new `FieldType::FloatList`, fields `_recharge_rate`, `_reload_delay`, `_reload_timers`, `_reload_advanced_at`, `_watch_checks` on SubsystemRow; `_power_level` on the phaser system row; global `phaser_discharge_by_power_level`), `host_bindings.cc` (`combat_set_floats`, dump support), `engine/appc/native_combat.py` (`NativeFloatList` descriptor + `push_field` support, `push_globals` table, `audit_mirror` coverage), `engine/appc/weapon_subsystems.py` (descriptors; push after every in-place slot write: `_start_slot_cooldown`, `_sync_slots_to_num_ready`, `_resize_slots`, `ReloadTorpedo`, `UpdateReload`, `UnloadTorpedo`), `engine/appc/float_range_watcher.py` (check add/remove pushes the owner weapon's `_watch_checks`; the weapon gives its watcher a back-reference at creation); tests `tests/unit/test_native_k0_mirror.py` (new), `native/tests/combat/mirror_test.cc`.

**Interfaces:**
- Produces: mirror fields readable by K0 (`Mirror::get_f/get_i/get_floats`); `NativeFloatList` (push on assignment, `push_field(obj, name)` after in-place writes); global `kPhaserDischargeByPowerLevel` pushed by `push_globals`.

- [ ] **Step 1: Failing tests:** `test_each_writer_pushes` (parametrised over every writer above: after the write, `combat_dump` equals the Python value by `.hex()`); `test_resync_pushes_in_place_slot_lists` (Review Focus 5); `test_audit_flags_missing_slot_push` (an in-place write with no push is caught by `audit_mirror`); `test_watch_checks_follows_add_remove`; `test_discharge_table_global`; gtest `MirrorTest.FloatListRoundTrip`.
- [ ] **Step 2-4:** FAIL → implement → run the new file + `tests/unit/test_native_combat_weapons_mirror.py tests/unit/test_passive_weapons.py tests/unit/test_torpedo_reload*.py` (name the files that exist) + `ctest -R combat_` → PASS.
- [ ] **Step 5: Commit** `feat(native-combat): mirror charging and reload inputs`.

### Task 4: K0 kernel (C++)

**Files:** create `native/src/combat/include/dauntless/combat/k0_charging.h`, `native/src/combat/src/k0_charging.cc`, `native/tests/combat/k0_charging_test.cc`; add to the combat library and test CMake lists.

**Interfaces:**
- Produces: pure step functions `step_energy(...)`, `step_pulse(...)`, `step_tube(...)` over mirror rows (formulas, operand order, `py_min`/`py_max`, NaN and −0.0 rules: WSM §1.3-1.6, D1-D11), and a session class `K0Session` modelled on `K1Session`: `begin(ships, dt, now)`, `next() -> K0Record` (`DONE, DEPLETE_STOP, RELOADED, WATCH, RUN_PYTHON`), a write log with the K1 value encoding plus `SlotWrite{field, index, value}` and `WatcherWrite{value}`, undo of unreturned writes on throw, `abandon()`, counters (`steps`, `records[kind]`, `python_reasons[reason]`, `logged_writes`).
- Hand-back reasons: `tractor`, `no_row`, `not_weapon_system`, `stale_row`, `slot_heal`, `override` (set by the driver via a per-class/instance flag table, Task 5), `audit`.

- [ ] **Step 1: Failing gtests** (`K0Charging.*`): each step against literal expectations derived from the Python reference for: countdown branch; drain at each power level and an out-of-range level (0.0); depletion → record; idle early-out; recharge with NaN power (0.0), NaN condition (reads full), `headroom` NaN; −0.0 charge stays +0.0 through `max(0.0, …)`; pulse cooldown; tube one attempt per call, strict `>` ties to the first index, NaN factor stalls, `game_dt < 0` clamp, ammo denial; walk order phaser → pulse → tractor → torpedo; RELOADED stops the walk before the next weapon; undo on throw.
- [ ] **Step 2-4:** FAIL → implement → `ctest --test-dir build -R combat_` → PASS.
- [ ] **Step 5: Commit** `feat(native-combat): K0 charging kernel`.

### Task 5: K0 driver and integration

**Files:** `host_bindings.cc` (`combat_k0_begin(handles, dt, now, ctx)`, `combat_k0_next`, `combat_k0_end`, `combat_k0_abandon`, `combat_k0_kinds`, counters), `engine/appc/native_combat.py` (`k0_weapons(ships, dt) -> bool`, `run_k0`, the K0 override guard over WSM A6's methods, counters), `engine/host_loop.py` (`_advance_weapons`: `if native_combat.enabled() and native_combat.k0_weapons(ships, dt): return` before the passive branch); tests `tests/unit/test_native_k0_dispatch.py`, `tests/unit/test_native_k0_override_guard.py` (new).

**Interfaces:**
- Consumes: Task 1's applier (writes applied before each record returns), Task 3's fields, Task 4's session.
- Produces: `native_combat.k0_weapons(ships, dt) -> bool` (False → caller runs Python; reasons counted in `counts()["k0_python_step_reasons"]`); `counts()` keys `k0_steps`, `k0_records`, `k0_python_reasons`, `k0_logged_writes`.

- [ ] **Step 1: Failing tests:** `test_k0_matches_python_per_tick` (a small scripted fight: phaser banks drain/deplete/recharge, a pulse cannon with and without watcher checks, tubes reloading with ammo limits; per-tick `.hex()` state and event log equal to the switch-off run); `test_deplete_stop_plays_loop_stop`; `test_reloaded_handler_starts_firing_same_ship` (Review Focus 2); `test_handler_sets_later_weapon_charge` (Review Focus 3); `test_tractor_handed_back`; `test_class_override_of_update_charge_runs_python` and the instance-attribute variant; `test_audit_stands_down`; `test_switch_off_never_enters_k0`.
- [ ] **Step 2-4:** FAIL → implement → run the new files + `tests/unit/test_passive_weapons.py tests/unit/test_passive_weapons_differential.py` (if at that path; name what exists) + the K1/K2 dispatch files + `ctest -R combat_` → PASS.
- [ ] **Step 5: Commit** `perf(native-combat): charging and reloading through K0`.

### Task 6: Differentials, scene audit, mutation proofs

**Files:** `tests/integration/test_native_k0_differential.py` (new, headless fight on/off), the passive weapons differential (switch its float compare to `.hex()`), `tests/helpers/k3_fight.py` / `tests/helpers/posed_fight.py` (assert `k0_steps`, `c_applied_writes`, `fast_pushes` > 0 when on), `tests/host/test_native_combat_scene_audit.py` (an unaudited run asserts K0 counters > 0).

- [ ] **Step 1:** write the differential (per tick, per weapon: `_charge_level`, `_beam_on_countdown`, `_depleted`, `_cooldown_remaining`, `_num_ready`, both slot lists by `.hex()`; ordered `ET_TORPEDO_RELOAD`/`ET_CHARGE_TOGGLE`/`ET_WEAPON_FIRED` log) including a 3-sessions-per-frame case (Review Focus 4); counter assertions in the helpers and scene audit.
- [ ] **Step 2: Run** all K0/K1/K2/K3/posed differentials + scene audit, both orders → PASS (a difference is a porting bug: fix code).
- [ ] **Step 3: Mutation proofs** (each must fail a test; `cp` + `diff` restore): recharge operand order; `max` argument order (−0.0); a skipped slot-list push; a C-applied write moved after its record's Python; a wake not fired on a WakeField write; WATCH emitted after the next weapon's step; fast push encoding `bool` as int.
- [ ] **Step 4: Commit** `test(native-combat): weapon-state differentials and mutation proofs`.

### Task 7: Benchmarks and docs (controller runs the benchmarks)

- [ ] **Step 1 (controller):** 2 runs of the 64-ship fight, switch on, at `9102c2f34` and 2 at the branch tip, idle machine, scratchpad `bench_fight.sh`; score per tick (`sim.weapons`, `cb.held_weapons`, `cb.phasers`, `sim.combat`, `sim`).
- [ ] **Step 2:** docs — spec §10 Outcome; perf register (capture + signal IDs next free on this line, incl. the 2026-11-02 split measurements from spec §1); CLAUDE.md native-combat row (within its limit); roadmap §2 table + §4 (D deferred with DM's findings, this phase added); `native-infra-patterns.md` (C apply kinds, fast push, FloatList). `uv run pytest tests/docs/test_doc_consistency.py -q` → PASS.
- [ ] **Step 3: Commit** `docs(native-combat): weapon state outcome and measurements`.
