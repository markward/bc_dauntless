# Phase 6 AI, Part 4 — A5, the AI Tree Engine in C++ — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the AI tree engine into C++: the per-tick roster and sleep scheduling, condition evaluation, the container walk and the focus/activation bookkeeping. It must call SDK scripts, conditions and preprocessors at exactly the points and in exactly the order the Python driver does. Results stay bit-identical.

**Architecture:**
- **One walker over the live Python node objects.** A C++ walker in `native/src/host/` (a new `aitree::` unit beside the Part 2 bindings) walks the existing `engine/appc/ai.py` node objects. It reads and writes their state (`_status`, `_has_focus`, `_got_focus_called`, `_next_update_time`, `_last_preprocess_status`, `_current_index`, `_loops_remaining`, the root's `_focused_preprocessors` / `_active_nodes`, the ship's `_ai_next_walk_due`) in each object's `__dict__` through the C API.
- **Python stays the only authority for node state.** There is no native mirror of the tree. SDK reads mid-walk (`HasFocus`, `IsActive`, `GetFocusAIs`, `GetAllAIsInTree`), the AI inspector, mission scripts and tests all keep seeing and writing the same attributes. This is "shape (b)" from the recon, the pattern of Part 2's native FireScript: C++ holding owned references and calling Python inline in the SDK's order. A batch stop-and-resume protocol would stop at about every sixth node.
- **Python calls stay Python.** Every call the driver makes into Python stays a Python call at the same point: PlainAI `Update` / `GetNextUpdateTime`, preprocessor methods, `GotFocus` / `LostFocus`, EvalFunc on a memo miss, condition `Activate` / `Deactivate` (via `SetActive` / `SetInactive`), `BuilderCreateN`, `random.choice`, `ClearAI`, the engine glue (`_ensure_select_target_initialized`, `_sync_fire_script_target_subsystem`, `_out_of_action`, `defensive_cloak.is_defensive`) and `_run_script_step`'s exception handling.
- **Order of work.** The walker is built in seams (recon S1 → S2 → S4 → S3). Each task replaces one set of Python driver functions with native code, and a differential test compares every tick against the Python driver.
- **End state.** The Python walker functions leave the engine and become a frozen test oracle (Mark's 2026-11-07 direction: no permanent Python copy).

**Tech Stack:** C++20, CPython C API (`native/src/host/host_bindings.cc` + a new `aitree` source file), Python 3.11, gtest, pytest.

**Spec:** `docs/superpowers/specs/2026-11-05-phase6-engine-stages-native-design.md` §3 (A5 row; Part A rules; "Python copies"), §2 anti-goals, §7. Kept behaviour: `docs/reference/engine/perf-cadences-and-latency.md` (the 4-tick tree sleep; `ForceUpdate` is not next-tick; avoidance at 4 Hz).

## Why, and what to expect

The numbers come from the Part 3 cProfile, C-438: 128 ships, 22.4 s of AI over 3,246 ticks, 118 k root walks, 1.40 M node visits, about 82 k Python callbacks.

| Seam | Functions | Self time | Share of AI |
|---|---|---|---|
| S1 roster + sleep | `tick_all_ai`, `_note_due`, the out-of-action gate, the defensive-cloak skip | 0.39 s (≈ 1.0 s cumulative) | 1.8% |
| S2 condition evaluation | `_refresh_conditional_status`, `_eval_conditional`, `_tick_conditional`'s status read, `TGCondition.GetStatus` | 1.30 s | 5.8% |
| S4 container walk | `_dispatch_ai`, `tick_ai`, `_tick_preprocessing`, `_tick_priority_list`, `_dispatch_priority_child`'s walk, `_tick_plain`, `_tick_sequence`, `_tick_builder`, `_tick_random` | 3.94 s | 17.6% |
| S3 focus + activation | `_reconcile_focus`, `_reconcile_active`, `_queue_got_focus`, `_flush_pending_got_focus`, `_retain_subtree_focus`, the priority-child rollback | 1.59 s | 7.1% |

Together that is about 32% of profiled AI time. cProfile inflates Python call overhead, and that overhead is exactly what this part removes, so the real Release gain will be smaller than 32%. Task 7 measures it.

## Global Constraints

- **Branch.** Worktree `.claude/worktrees/phase6-ai`, branch `ws/ai-p4-tree-engine`, stacked on `ws/ai-p3-app-methods` (`20d988947`). Part 3 awaits Mark's live check; neither part merges into `project/phase6-ai` before it. A Part 3 fix lands on the Part 3 branch and is merged up.
- **Testing.** Never run the gate or whole suites. Run focused files only, listed literally, and never with an empty or unsplit pytest list. Tree guards are allowed: `tests/docs`, `tests/unit/test_path_indirection.py`, `tests/unit/test_install_write_guard.py`, `tests/unit/test_gate_tiers.py`.
- **Git.** No destructive git. Stage explicit paths. Never force-add anything under `.superpowers/`. For a temporary mutation: cp a backup, mutate, run, cp it back, diff.
- **Goldens and A/B.** The golden fights (`tests/integration/test_golden_fights.py`: `k1_gameloop_ai`, `sdk_dumb_fire`, `host_frames`, `host_frames_tpf1` run real trees) and the Part 2 A/B (`tests/integration/test_native_ai_ab.py`) stay byte-identical. Never set `UPDATE_COMBAT_GOLDEN`.
- **Bit-exact with the Python driver:**
  - the same Python callbacks, in the same order, with the same arguments;
  - the same node-state writes, at the same points, with the same values and types (int statuses via `int(status)`; due times as `game_time + interval` doubles, built with fp-contract off);
  - the same exceptions escaping at the same points;
  - the same swallowed-and-logged exceptions (`_run_script_step`: once per (node ID, exception type), returning `None`);
  - the same RNG draws (`random.choice` stays a Python call on the global stream);
  - the same ID allocations (all in Python).
- **Re-entrancy, matching Python.**
  - A callback may run `ForceUpdate`, `Reset`, `SetAI` / `ClearAI`, `AddAI` / `RemoveAI`, `SetInterruptable` or a condition `SetStatus`, or start a nested root walk.
  - Re-read every piece of node state the Python driver re-reads after a callback, and only those.
  - Iterate lists the way Python iterates them: a live `for` over a list mutated in place sees the mutation, a rebound list does not, and Sequence reads `_ais[idx]` live with `n` taken once.
  - Never hold a borrowed reference across a Python call.
- **Dispatch.** Dispatch stays exact-type through `_DISPATCH_BY_TYPE` with its issubclass fallback. A type whose handler is not one of the stock driver handlers (tests inject them) is handled by calling that Python handler. A patched or replaced stock handler is called, not bypassed.
- **Kept behaviour.** The kept cadences stay as they are: `AI_MAX_SLEEP_TICKS` (env `DAUNTLESS_AI_MAX_SLEEP`, read where Python reads it), the sleep stamp, the "no wake on `ForceUpdate`" rule, and the 4 Hz avoidance.
- **Selecting the walker.** The native walker is selected by a module-level flag, `ai_driver._native_walker` (default on once Task 4 lands). The differential tests set it per test. No environment switch is added. The flag and the Python walker leave the engine in Task 8.
- **Build.** Build with `cmake --build build -j` from the worktree root. Mark has pre-approved game launches for this programme's measurement tasks; tell him when one runs.

## Review Focus

1. **A callback that mutates the tree mid-walk.** Cases: a SelectTarget `TargetGone` handler calling `ForceUpdate`; `ResetOnTargetChange` calling `Reset` through `CallExternalFunction`; a script calling `SetAI` on the walking ship; the helm `AddAI` sorting a list mid-scan. The native walker must see exactly what the Python one sees. Task 1's differential scenes include each case.
2. **An exception escaping the walk.** Sources: `GetNextUpdateTime`, `int(status)`, `GetStatus`, `IsInterruptable`, `_out_of_action`, `_sync_fire`, `_ensure_select`. The depth restores, root reconciliation and the sleep stamp are skipped, and the remaining ships are skipped for that tick, as today.
3. **The priority-child rollback.** A child probed and then rejected truncates the reached and pending lists and restores `_has_focus` / `_got_focus_called`. Its script still saw `HasFocus()==1` during its own `Update`. Task 4 pins this.
4. **A nested root walk** started from a focus or activation hook, which rebinds the module-level walk state. The native walker must keep per-walk state on its own stack and match Python's visible effect.
5. **A test or mod type outside the stock node set**, and a monkeypatched driver function (`_tick_plain`, `_note_due`, a `_DISPATCH_BY_TYPE` entry). It must be honoured.

---

### Task 1: The differential harness and the walker selector

**Files:**
- Create: `tests/helpers/ai_walk_diff.py`, `tests/unit/test_ai_walk_differential.py`
- Modify: `engine/appc/ai_driver.py` (only `_native_walker = False` and the one dispatch point `tick_all_ai` uses to choose the walker; nothing native yet)

**Interfaces:**
- Produces `run_walk_diff(scene, ticks) -> None`. It runs the same seeded scene twice in one process (Python walker, then native walker), with fresh module state for each and the same RNG seeds (`tests/helpers/k1_fight.py` `_seed_every_rng`). It raises `AssertionError`, naming the tick and the first difference, unless:
  - the full call log is identical: every Python callback the driver makes, recorded by wrapping each SDK script, condition and preprocessor method at the instance level, plus the engine glue (method, node ID, args);
  - every node's `__dict__` state is identical after each tick: statuses, focus flags, due times, indices, root lists, per-ship `_ai_next_walk_due`.
- Scenes, one test each:
  - `k1_gameloop_ai` trees (FedAttack / NonFedAttack / CloakAttack via BasicAttack), 600 ticks;
  - `sdk_dumb_fire`;
  - a RandomAI tree (`NoSensorsEvasive`);
  - a SequenceAI with `skip_dormant` 0 and 1 and loops;
  - a BuilderAI whose `BuilderCreate` raises;
  - the re-entrancy scenes of Review Focus 1;
  - an escaping exception (Review Focus 2);
  - a nested root walk (Review Focus 4);
  - a test-injected node type (Review Focus 5).
- In this task the native side IS the Python walker, so every test passes trivially. That proves the harness is deterministic: two Python runs are identical. Later tasks make the native side real.

- [ ] **Step 1: Write the harness and its tests**, plus a negative test: mutate one node's status in the second run, and the harness must catch it.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_ai_walk_differential.py -q`. Expect PASS. If two Python runs differ, find the nondeterminism (dict or set iteration, id-ordered sets) and report it before going on.
- [ ] **Step 3: Run** `tests/integration/test_golden_fights.py` and `tests/integration/test_native_ai_ab.py`. Expect them unchanged.
- [ ] **Step 4: Commit** `test(ai): tree-walk differential harness and walker selector`.

### Task 2: S1 — roster and sleep scheduling native

**Files:**
- Create: `native/src/host/aitree.cc` (+ header), registered from `host_bindings.cc`
- Modify: `engine/appc/ai_driver.py` (`tick_all_ai` calls `_h.aitree_tick_all(...)` when `_native_walker` is on)
- Test: `tests/unit/test_ai_walk_differential.py`, `tests/unit/test_ai_scheduler_invariants.py`, `tests/unit/test_ai_due_time_walking.py`

**Interfaces:**
- Produces `aitree_tick_all(game_time)`, which is `tick_all_ai` (`ai_driver.py` ~1665-1746) in C++:
  - the live roster from `iter_non_rock_ships()`, called and iterated in Python;
  - the `defensive_cloak.is_defensive` skip and the sleep check with its upper bound;
  - `ship.GetAI()`, the walk-min-due reset, then a call to Python `tick_ai(root)` per root (native in Task 4);
  - the `_ai_next_walk_due` stamp: `min(walk_min_due, game_time + max_sleep * _TICK_SECONDS)` as doubles;
  - the DONE handling: the `_done_event_fired` latch, the still-installed check, `ClearAI()` / `fire_ai_done`.
- `_note_due` / `_note_due_ret` become native, and they write into the native walk-min-due. Python callers still work while the walk stays Python, through a thin binding.
- `AI_MAX_SLEEP_TICKS` and `_TICK_SECONDS` are read from the module at the same points Python reads them, so a test monkeypatch keeps working.

- [ ] **Step 1: Make the differential's native side real for S1.** Write the scheduler tests:
  - a ship skipped while asleep;
  - a stale stamp from an earlier mission above the upper bound;
  - `SetAI` on a sleeping ship;
  - a `ClearAI` that fires `ET_AI_DONE` once.
- [ ] **Step 2: Run them; they fail** (no binding yet).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest tests/unit/test_ai_walk_differential.py tests/unit/test_ai_scheduler_invariants.py tests/unit/test_ai_due_time_walking.py tests/unit/test_ai_done_event.py tests/unit/test_out_of_action_slot.py tests/unit/test_ai_driver.py tests/integration/test_golden_fights.py tests/integration/test_native_ai_ab.py -q`. Expect PASS, goldens unchanged. `test_ai_scheduler_invariants.py`'s AST check on `_note_due` must keep holding for whatever Python remains. Update it to also assert the native walker's gate sites if needed, and say how.
- [ ] **Step 5: Commit** `perf(ai): AI roster and sleep scheduling native`.

### Task 3: S2 — condition evaluation native

**Files:**
- Modify: `native/src/host/aitree.cc`, `engine/appc/ai_driver.py` (`_refresh_conditional_status`, `_eval_conditional`, `_tick_conditional`'s status read call the binding)
- Test: `tests/unit/test_ai_walk_differential.py`, `tests/unit/test_conditional_eval_memo.py`, `tests/unit/test_priority_list_refreshes_conditional.py`

**Interfaces:**
- Produces `aitree_refresh_conditional(ai)` and `aitree_eval_conditional(ai, statuses)`. They reproduce `ai_driver.py` ~755-898 exactly:
  - the `GetStatus()` reads, in condition order (a Python call when the condition's `GetStatus` is not `TGCondition.GetStatus`; a direct `_status` read when it is stock and unshadowed);
  - the memo key `(fn, tuple(args), status)`, applied only where `_memoisable_evalfunc` passes and every argument is a scalar of the listed types, with exceptions not cached;
  - EvalFunc as a Python call on a miss, where an exception maps to DORMANT, unlogged;
  - the no-EvalFunc rule ("any condition non-zero" means ACTIVE, else DORMANT);
  - the DONE fold, outside the memo.
- The memo stays in `ai._evalfn_cache` (the Python dict), so the inspector and tests see it.

- [ ] **Step 1: Write the failing tests:**
  - the differential's native side with S2 on;
  - an EvalFunc that raises;
  - a non-memoisable EvalFunc (ChainFollow's global);
  - a condition class with its own `GetStatus`;
  - a condition `_status` written directly by a test.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest tests/unit/test_ai_walk_differential.py tests/unit/test_conditional_eval_memo.py tests/unit/test_priority_list_refreshes_conditional.py tests/unit/test_condition_external_functions.py tests/unit/test_condition_activate.py tests/integration/test_golden_fights.py tests/integration/test_native_ai_ab.py -q`. Expect PASS.
- [ ] **Step 5: Commit** `perf(ai): conditional evaluation native`.

### Task 4: S4 — the container walk native

**Files:**
- Modify: `native/src/host/aitree.cc`, `engine/appc/ai_driver.py` (`tick_ai` calls `_h.aitree_tick(root)` when `_native_walker` is on)
- Test: `tests/unit/test_ai_walk_differential.py` plus the files in Step 4

**Interfaces:**
- Produces `aitree_tick(root)`, which is `tick_ai`, `_dispatch_ai` and every stock `_tick_*` handler (`ai_driver.py` ~67-170, 507-1537) in C++. It includes:
  - the root-only resets of the per-walk state, kept on the native walk frame. The Python module globals `_reached_this_tick` etc. are still written when a Python handler or a test reads them; list in the report which ones are read outside the driver, and keep those exact;
  - the one-slot out-of-action cache;
  - the exact-type dispatch with its fallback, where a non-stock handler is called as Python;
  - PriorityList (one child dispatched per tick, the dormant-preprocessing probe, the status update rules), the priority-child rollback (Review Focus 3), Sequence (`n` taken once, live `_ais[idx]`, `skip_dormant`, `_wrap_or_finish`), Random (`random.choice` in Python), Conditional (via Task 3), Preprocessing (first-tick init, focus before `Update`, the arity cache, the non-interruptable bypass, due and not-due arms, PS_* mapping, `_retain_subtree_focus` on SKIP_ACTIVE, the DONE fold), Builder (first-tick activation stays Python: `_activate_builder`) and Plain;
  - `_run_script_step` semantics (catch `Exception`, record `_last_script_error`, log once per (node ID, type), return None), done natively or by calling the Python `_run_script_step`. Pick one and say why.
- The focus and activation reconciliation (S3) stays Python in this task. The native walk produces the same reached and pending lists, which are handed to the Python `_reconcile_focus` / `_flush_pending_got_focus` / `_reconcile_active`.
- This is the largest task. If it grows past what you can hold correctly, commit a coherent exact subset: for example the walk for Plain / PriorityList / Preprocessing / Conditional natively, with Sequence / Random / Builder still dispatched to their Python handlers. Report DONE_WITH_CONCERNS, listing what is still Python. Never ship anything inexact.

- [ ] **Step 1: Make the differential's native side real for S4**, and add per-node-type tests for each Review Focus item.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest tests/unit/test_ai_walk_differential.py tests/unit/test_ai_driver.py tests/unit/test_ai_primitives.py tests/unit/test_ai_reset_and_status_values.py tests/unit/test_ai_dispatch_cache.py tests/unit/test_ai_scheduler_invariants.py tests/unit/test_ai_due_time_walking.py tests/unit/test_preprocess_done_is_lethal.py tests/unit/test_preprocessing_ai_propagates_done.py tests/unit/test_interruptable_bypass.py tests/unit/test_force_update_reschedule.py tests/unit/test_sequence_ai_flags.py tests/unit/test_random_ai_without_replacement.py tests/unit/test_out_of_action_slot.py tests/unit/test_ai_script_exception_guard.py tests/unit/test_builder_ai_activation.py tests/unit/test_ai_driver_subsystem_target_sync.py tests/unit/test_native_fire_script.py tests/unit/test_native_target_rating.py tests/unit/test_native_avoid_scan.py tests/integration/test_dormant_priority_child_recovers.py tests/integration/test_avoid_cadence_still_clears.py tests/integration/test_select_target_in_priority_list.py tests/integration/test_cloak_focus_cadence.py tests/integration/test_golden_fights.py tests/integration/test_native_ai_ab.py -q`. Expect PASS, goldens unchanged.
- [ ] **Step 5: Commit** `perf(ai): the AI tree walk runs natively`.

### Task 5: S3 — focus and activation bookkeeping native

**Files:**
- Modify: `native/src/host/aitree.cc`, `engine/appc/ai_driver.py`, `engine/appc/ships.py` only if `_deactivate_ai_tree` must call a binding
- Test: `tests/unit/test_ai_walk_differential.py` plus the focus and activation files

**Interfaces:**
- `_reconcile_focus`, `_flush_pending_got_focus`, `_reconcile_active`, `_queue_got_focus` and `_retain_subtree_focus` become native, at the root end of `aitree_tick`. The call order is unchanged:
  1. `LostFocus`, in previous focus order;
  2. `GotFocus`, in arrival order;
  3. `SetInactive`, in previous active order;
  4. `SetActive`, in reached order.

  Edges still call the Python `SetActive` / `SetInactive` methods, which reach condition `Activate` / `Deactivate`. The fast path skips the call when the edge test (`_is_active_in_tree`) says nothing changes, and the method must be the stock one.
- The root's `_focused_preprocessors` and `_active_nodes` stay Python lists on the root (`ships._deactivate_ai_tree` writes them).

- [ ] **Step 1: Write the failing tests:**
  - the differential's native side with S3 on;
  - a node whose `SetActive` is patched (it must be called);
  - a ConditionalAI whose conditions' `Activate` raises (swallowed, as today);
  - a focus hook that starts a nested walk.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** Task 4's Step 4 list, plus `tests/unit/test_ai_driver_focus_loss.py tests/unit/test_ai_driver_focus_handover.py tests/unit/test_ai_driver_leaf_focus.py tests/unit/test_ai_driver_got_focus.py tests/unit/test_ai_activation_lifecycle.py tests/unit/test_ai_reparent_activation.py tests/unit/test_ai_detach_clears_focus.py tests/unit/test_get_focus_ais.py tests/unit/test_ai_teardown_on_death.py`. Expect PASS.
- [ ] **Step 5: Commit** `perf(ai): AI focus and activation bookkeeping native`.

### Task 6: Smoke coverage over the SDK's own AI scripts

**Files:**
- Test: run, not modify, the existing per-script smoke tests (about 40 `tests/**/*_smoke.py`), with `_native_walker` on. Add a parametrised differential over the PlainAI and compound AI modules in the SDK's `AI/` package whose smoke tests exist, so each tree is walked by both walkers and compared for 120 ticks.
- Fix only real divergences in `aitree.cc`. A divergence in an SDK script path that Tasks 1-5 missed gets a focused test first.

- [ ] **Step 1: List the smoke files** (`ls tests/**/*_smoke.py`). Write the parametrised differential.
- [ ] **Step 2: Run** the differential and the smoke files, literally listed. Fix and re-run until green.
- [ ] **Step 3: Commit** `test(ai): every SDK AI script walked by both walkers`.

### Task 7: Measure, record, live-check list

- [ ] **Step 1: Tell Mark** a measurement is starting. Launches are pre-approved for this programme.
- [ ] **Step 2: Release** in `.claude/worktrees/release-macos`. Before is `20d988947` (the Part 3 tip); after is this branch's tip. Run back to back using the Part 3 capture script shape (`scratchpad/p6ai3_capture.sh`): 64 and 128 ships, exterior and bridge, two runs each, plus one cProfile run a side at 128 exterior.
- [ ] **Step 3: Score** as in SIG-207: per-tick `gl.ai` and `ai.avoid`, frame ms, ticks a frame. From cProfile, report `tick_all_ai`'s share of the root and each seam's remaining Python self time.
- [ ] **Step 4: Perf register.** Add the captures and one signal (the next SIG id), and state the catch-up confound.
- [ ] **Step 5: Commit** `docs(perf): phase 6 AI part 4, the AI tree engine (SIG-…)`.
- [ ] **Step 6: Live-check list** for Mark:
  - a 64-ship and a 128-ship Quick Battle;
  - E1M1 (scripted tutorial AI, docking);
  - E1M2 Haven;
  - a cloaked Warbird fight;
  - a helm order to an AI wingman (helm `AddAI`);
  - a mission swap mid-fight;
  - the LC Intrepid mod ship.

### Task 8: Retire the Python walker; record the design

**Files:**
- Modify: `engine/appc/ai_driver.py`. Delete the Python walker functions the native walker replaced, and the `_native_walker` flag. Keep everything native calls back: `_run_script_step` if Task 4 kept it in Python, `_ensure_select_target_initialized`, `_sync_fire_script_target_subsystem`, `_activate_builder`, `fire_ai_done`, `_dispatch_lost_focus` (used by `ships.py`), `_memoisable_evalfunc` if called back, and the `_DISPATCH_BY_TYPE` table.
- Create: `tests/helpers/ai_walker_oracle.py`, a frozen verbatim copy of the deleted walker with a docstring naming the source commit. Repoint `tests/helpers/ai_walk_diff.py` to it.
- Modify: CLAUDE.md. Add one row, "Native AI tree engine", in the style of the rows around it:
  - files;
  - the walker-over-Python-objects design;
  - what stays Python;
  - the differential test;
  - the ⚠️ that a new node type or driver hook must be added to the native walker, or dispatched to Python through `_DISPATCH_BY_TYPE`;
  - SIG headline.

  Update `docs/reference/engine/perf-cadences-and-latency.md`'s stale line references (the recon found ai_driver.py:1548 → 1621, ai_optimized.py:138 → 167).
- Test: the files from Task 5's Step 4 plus Task 6's differential, and `tests/docs`.

- [ ] **Step 1: Write the failing test** `test_no_python_tree_walker_remains`. It checks that `ai_driver` defines none of the deleted walker functions and has no `_native_walker` attribute.
- [ ] **Step 2: Run it; it fails.**
- [ ] **Step 3: Delete, move, document.**
- [ ] **Step 4: Run** the listed files. Expect PASS.
- [ ] **Step 5: Commit** `refactor(ai): the AI tree engine is native; the Python walker is a test oracle`.
