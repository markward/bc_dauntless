# Combat event inventory and presentation queue — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** List every event and effect the per-tick combat path produces and pin E1M2's order rule (step 1). Then move K2's resting-contact presentation out of the walk into a boundary queue, presented natively for shielded targets (step 2).

**Architecture:** K2 appends resting contacts to a per-session native queue instead of riding records. After `DONE`, one binding drain presents shielded entries through the shield pass in C++, and returns the rest to Python as one batch for `beam_contact`. Game-state order is untouched; presentation within a tick becomes order-free (ruling Q1).

**Tech Stack:** C++17 combat library (`native/src/combat`), pybind11 host bindings (`native/src/host/host_bindings.cc`), Python 3.11 engine (`engine/appc/native_combat.py`), gtest, pytest.

**Spec:** `docs/superpowers/specs/2026-11-02-combat-effect-queue-design.md` (read it first; §n below means that spec).

## Global Constraints

- Worktree `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/native-combat-damage`, branch `ws/combat-effect-queue`. Run everything from there.
- Switch `DAUNTLESS_NATIVE_COMBAT=1`, default OFF; switch-off behaviour byte-identical.
- Game state bit-exact with the Python reference, switch on: floats compared by `.hex()`; writes, damage, events, deaths in the same order.
- Focused tests only: the files each task names. Never whole suites (`tests`, `tests/unit`, …), never `scripts/check_tests.sh`.
- Banned git: `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage explicit paths. Commit with `git commit -F <file>`; end messages with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Build: `cmake --build build -j` from the worktree. Never reconfigure cmake, never change BUILD_TYPE, never run cmake inside `native/`. The Python module is `build/python/_dauntless_host*.so`; C++ tests run with `ctest --test-dir build -R <name>`.
- Never launch the game. Never spell `game` or `sdk` as a path segment in code.
- To prove a test catches a bug: back up with `cp`, mutate, run, restore with `cp`, then `diff` to prove the restore.
- No subagents.

## Review Focus

1. A resting contact on a target that a later pulse in the same step kills (ruling Q4): it must still present once, not crash or vanish.
2. An exception inside one Python-batch presentation: the remaining entries still present, then it re-raises; the queue is empty afterwards.
3. An abandoned K2 session (exception mid-walk): the queue is cleared and nothing it held presents in the next step.
4. A shielded contact whose target has no instance or whose set has no view offset: it goes to the Python batch, not dropped and not presented natively with a wrong point.
5. Headless (no shield pass): the native path drops the splash exactly as the `shield_hit` binding does, and the capture hook still records what would have been pushed.

---

### Task 1: Event inventory and the E1M2 order pin (step 1)

**Files:**
- Create: `docs/reference/engine/native-combat/event-inventory.md`
- Create or modify: `tests/integration/test_e1m2_rocks.py` (add a test), only if no existing test pins the lethal case
- Read: `/private/tmp/claude-501/-Users-mward-Documents-Projects-bc-dauntless/5ddd11d1-ec16-4134-949b-d2ec14ac8f02/scratchpad/event-inventory-draft.md` (a research draft; trust nothing in it you have not checked against code)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: the inventory doc, which §4.1 defines. Later phases read its "Ordering rules" section.

- [ ] **Step 1:** Check every row of the draft against the code (`file:line` must point at the cited thing in this tree). Fix wrong rows, delete unverifiable claims or mark them **inferred**. Keep the six sections of spec §4.1, in that order.
- [ ] **Step 2:** Decide from the draft's section 6 and your own reading of `tests/integration/test_e1m2_rocks.py` and `tests/unit/test_planet_collision_event.py` whether any test already pins: *a lethal asteroid impact on Haven is scored as a Haven hit, not a player kill.* If one does, name it in the inventory and skip to Step 6.
- [ ] **Step 3:** Write `test_lethal_asteroid_impact_on_haven_scores_a_haven_hit` in `tests/integration/test_e1m2_rocks.py`, following that file's existing setup (real E1M2 scripts, headless). The asteroid's closing speed and hull must make the collision damage kill it in the impact tick (assert `IsDead()` or the exploding event fired that tick, so the test cannot pass on a non-lethal bump). Assert the mission's Haven-hit path took the rock (the collision handler's effect, read from the mission module's own state as the existing Haven test does) and its player-kill path did not.
- [ ] **Step 4:** Run `uv run pytest tests/integration/test_e1m2_rocks.py -q`. Expected: PASS (it pins today's behaviour).
- [ ] **Step 5:** Prove it guards the order: back up `engine/appc/collisions.py`, move the `_emit_planet_collision` call after the impact damage, re-run the test. Expected: FAIL. Restore by copy and `diff`.
- [ ] **Step 6:** If the inventory found other ordering rules with no test, add at most two more pins the same way (each with its mutation proof); list the rest under "Ordering rules" as open.
- [ ] **Step 7:** Commit the doc and the test.

### Task 2: K2 presentation queue, presented in Python at the drain

**Files:**
- Modify: `native/src/combat/include/dauntless/combat/k2_beams.h` (RESTING CONTACTS and RECORDS contract; `K2Record` loses `contacts`; new `K2Rest` and accessor), `native/src/combat/src/k2_beams.cc`
- Modify: `native/src/host/host_bindings.cc` (record tuples lose `queued`; `K2PendingWrites` segment logic goes; new `combat_k2_drain()`)
- Modify: `engine/appc/native_combat.py` (`run_k2`, `_k2_deliver` removed, `_k2_run_contact` takes carried level/shields, new `_k2_present_batch`; counters)
- Test: `native/tests/combat/k2_beams_test.cc`, `tests/unit/test_native_k2_dispatch.py`, `tests/unit/test_native_k2_bindings.py`, `tests/host/test_native_k2_differential.py`, `tests/helpers/k3_fight.py`, `tests/integration/test_native_k1_differential.py`, `tests/integration/test_native_combat_step_differential.py`, `tests/helpers/posed_fight.py`, `tests/host/test_native_combat_scene_audit.py`

**Interfaces:**
- Produces (C++): `struct K2Rest { K2Contact contact; int64_t level; std::optional<int64_t> iid; std::optional<Vec3> view_offset; };` and `const std::vector<K2Rest>& K2Kernel::rests() const` (cleared by `begin`, `end`, `abandon`). `K2Contact::shields_block` is always set for a resting entry when the kernel could evaluate it natively (spec §4.3).
- Produces (binding): `combat_k2_drain() -> list` of entries, each `(bank, target, ship, system, emitter_xyz, target_pos_xyz, dist, aim_unit_xyz|None, impact_xyz, normal_xyz|None, tier, bubble_xyz|None, shields (True/False/None), flush_dwell, level, iid|None, view_offset_xyz|None)`, clearing the kernel's queue. Valid after `DONE`, before `combat_k2_end`.
- Produces (Python): `_k2_run_contact(c, walk, dt, ship_instances, level=None)` (level None = read `_phaser_level` as today, for damage-pulse CONTACT records); `_k2_present_batch(entries, walk, dt, ship_instances)`.
- Task 3 consumes all three.

- [ ] **Step 1: C++ tests first.** Rewrite `RestingContactsQueueOnTheNextRecord` as `RestingContactsQueueForTheDrain`: same scene; the pulse record and `DONE` carry no contacts; `rests()` after `DONE` holds b0, b1, b3 in walk order with `flush_dwell == 0.0`; `batched_contacts == 3`. Rewrite `QueuedContactCarriesShieldsAsked` as `RestCarriesTheShieldsAnswer`: an ASK answer of `false` is carried as `false` (and `shields_asked` true); a native answer is carried. Add `RestCarriesLevelIidAndViewOffset` (level from the system's `_power_level` at contact time, changed afterwards in the mirror: the entry keeps the old value; iid and view offset from the context; none when the target has no instance), `NoAimRestEvaluatesShieldsNatively`, and `QueueClearedOnBeginEndAbandon`. Adapt `ThrowAfterAQueuedContactRestoresTheQueue` to the new queue. Run: `cmake --build build -j && ctest --test-dir build -R k2_beams` → FAIL (compile or assertions).
- [ ] **Step 2:** Implement the kernel side (spec §4.3). Remove `K2Queued`, `K2Record::contacts`, the `at` bookkeeping. Update the header contract text.
- [ ] **Step 3:** Run `ctest --test-dir build -R k2_beams` → PASS.
- [ ] **Step 4: Python/binding tests.** In `tests/unit/test_native_k2_dispatch.py`: rewrite `test_resting_contacts_batched_in_walk_order` and `test_queued_contacts_precede_damage_pulse` to assert resting presentations run after the step's last record, in walk order, with the level and shields captured at contact time (change the system's power level in a pulse's effect: the earlier rest keeps its level). Rewrite `test_raise_in_a_queued_contact_applies_the_records_later_writes` as `test_raise_in_a_batch_presentation_presents_the_rest_then_raises` (Review Focus 2). Add `test_abandoned_step_presents_nothing_next_step` (Review Focus 3) and `test_rest_on_target_killed_later_in_step_presents_once` (Review Focus 1). Run `uv run pytest tests/unit/test_native_k2_dispatch.py tests/unit/test_native_k2_bindings.py -q` → FAIL.
- [ ] **Step 5:** Implement the binding drain and `run_k2`'s drain after `DONE` (before `combat_k2_end`; the batch runs inside the `try`, so an exception abandons as today but only after presenting the remaining entries). Remove `_k2_deliver` and the K2 segment-apply path; record tuples end `(…, writes)`.
- [ ] **Step 6:** Run the two unit files → PASS.
- [ ] **Step 7: Differentials, ruling Q1.** In `tests/helpers/k3_fight.py` `spy_presentation` and the K2 host differential's spies: presentation entries (`beam_contact`, `vfx`, `shield_hit`) go to a per-tick presentation log compared as a sorted multiset; `apply_hit`, stops and events stay in the ordered log. Update docstrings that describe the old batching. Run `uv run pytest tests/host/test_native_k2_differential.py tests/integration/test_native_k1_differential.py tests/integration/test_native_combat_step_differential.py tests/integration/test_native_k3_differential.py tests/host/test_native_combat_scene_audit.py -q` → PASS, every branch tally still firing.
- [ ] **Step 8:** Mutation proofs: (a) drop the last entry in `combat_k2_drain`; (b) read `level` at the drain instead of carrying it, in a scene where a pulse changes it (use the dispatch test); each must fail a test. Restore by copy, `diff`.
- [ ] **Step 9:** Commit.

### Task 3: Native shield presentation at the drain

**Files:**
- Modify: `native/src/host/host_bindings.cc` (the drain presents shielded entries; `combat_present_capture`; session constants)
- Modify: `engine/appc/native_combat.py` (send intensity and default radius at `k2_phasers`; counters `k2_present_native`, `k2_present_python`)
- Create: `tests/unit/test_native_present_queue.py`
- Test: `tests/host/test_native_k2_differential.py`, `tests/helpers/k3_fight.py`

**Interfaces:**
- Consumes: Task 2's `K2Rest`, `combat_k2_drain`, `_k2_present_batch`.
- Produces: `combat_k2_drain()` now returns only the entries it did not present; `combat_present_capture(lst: list | None) -> None`, each captured item `(bank_handle, target_handle, iid, view_point_xyz, relative_xyz, (0.0, 0.0, 0.0, 0.0), intensity, radius)`: `view_point_xyz` is the anchor shifted into view coordinates (doubles: exactly the `point` a `host_io.shield_hit` spy sees), `relative_xyz` that minus the instance's translation (doubles: exactly what `host_io._instance_relative` returns), or None when the instance is stale; `combat_k2_present_constants(intensity: float, default_radius: float)` sent from `k2_phasers` when changed.

- [ ] **Step 1: Tests first** in `tests/unit/test_native_present_queue.py`:
  - `test_shielded_rest_presents_natively_bit_exact`: for one shielded resting contact, the captured tuple equals what `host_io.shield_hit` receives when the same contact runs through `hit_feedback.beam_contact` on the Python path (iid, the view point by `.hex()`, rgba, intensity, radius), and its `relative_xyz` equals `host_io._instance_relative(iid, point)` by `.hex()`.
  - `test_unshielded_and_unknown_go_to_python`: hull contacts and unknown-shields contacts come back from the drain and run `beam_contact`.
  - `test_missing_iid_or_view_offset_goes_to_python` (Review Focus 4).
  - `test_headless_drops_but_captures` (Review Focus 5): with no shield pass, nothing is pushed, the capture still records, no exception.
  - `test_patched_radius_factor_is_read_at_drain`: the bank's `GetDamageRadiusFactor` result (> 0) is the captured radius; 0 gives the default.
  Run `uv run pytest tests/unit/test_native_present_queue.py -q` → FAIL.
- [ ] **Step 2:** Implement spec §4.4: the native present branch (view shift in double, minus the instance's double translation, cast to float, `relative_to_body`, `ShieldPass::push`, exactly as the `shield_hit` binding; share one helper between them rather than duplicate it), the capture hook, the constants, the counters.
- [ ] **Step 3:** Run the new file and `tests/unit/test_native_k2_dispatch.py` → PASS.
- [ ] **Step 4:** Differentials: the native arm installs `combat_present_capture` and adds captured items to its per-tick presentation multiset as `shield_hit` entries; the reference arm's `beam_contact` entries whose `acted` is true drop out of the comparison (their `shield_hit` stays). Run the five differential files from Task 2 Step 7 → PASS. The K2 differential must show `k2_present_native > 0` and `k2_present_python > 0`.
- [ ] **Step 5:** Mutation proofs: (a) skip the view-offset shift; (b) use the bubble point when the anchor should be the impact point (or the reverse); (c) present an entry whose `iid` is missing. Each must fail a test. Restore by copy, `diff`.
- [ ] **Step 6:** Commit.

### Task 4: Measurement and documentation (controller)

**Files:**
- Modify: the spec (§10 Outcome), `docs/superpowers/specs/2026-11-01-threaded-weapons-combat-roadmap.md` (§2, §4 G and I), `docs/reference/engine/perf-register.md` (C-264 and signals), `docs/reference/engine/native-combat/k2-beams-map.md` and `remaining-fallbacks-map.md` (resting contacts now queued), `CLAUDE.md` native-combat row only if its text becomes wrong.

- [ ] **Step 1:** Rebuild, wait for an idle machine, run `bench_fight.sh <worktree> eq 2`, compare with `compare_native2.py` against the `ms6-weaponstate-*` logs.
- [ ] **Step 2:** Write the outcome and register entries. Commit.
