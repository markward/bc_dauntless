# Kernels off the lock (roadmap I) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** K0-K3 compute with the GIL released, safe against any Python that runs meanwhile, with the compute's own cost measured.

**Architecture:**
- Native timers wrap each kernel's compute call.
- Mirror-row and transform-slot frees, and mirror pushes from threads other than the main one, are deferred to fixed drain points under the GIL.
- The four compute calls are then wrapped in `py::gil_scoped_release`.

**Tech Stack:** C++17 combat library and pybind11 bindings, Python 3.11, gtest, pytest.

**Spec:** `docs/superpowers/specs/2026-11-03-kernels-off-the-lock-design.md`. Map: `docs/reference/engine/native-combat/lock-map.md` (LM).

**Shape (Mark: "nothing overcomplicated"):** three implementation tasks, each with its proof written first, and one final review. The controller benchmarks and writes the docs.

## Global Constraints

- Worktree `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/native-combat-k3`, branch `ws/combat-off-lock`, off D's tip.
- Switch `DAUNTLESS_NATIVE_COMBAT=1`. Game state stays bit-exact (`.hex()`) with the switch on and off, and with and without the GIL released.
- Focused tests only: the files each task names plus every touched module's existing tests. Never whole suites, never `scripts/check_tests.sh`. Use `uv run pytest <files>`; NEVER `uv run --active`.
- C++: build with `cmake --build build -j`. Never reconfigure cmake or change BUILD_TYPE; never run cmake inside `native/`. Run `ctest --test-dir build -R "combat_|EffectQueue"`.
- Never launch the game binary. The controller benchmarks; Mark allowed benchmarks until I completes.
- The banned git commands of CLAUDE.md "Shared checkout" apply. Stage explicit paths; `git commit -F <file> -- <paths>`; end messages with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- No red or xfail tests are committed. Mutation proofs: `cp` backup, mutate, run, `cp` restore, `diff` clean. No subagents.

## Review Focus

1. A row freed by a finalizer while a session is open: the kernel keeps reading valid data, and the handle is not reused until the drain.
2. A finalizer or SDK `__del__` that runs on the main thread between records: today's behaviour is unchanged. Main-thread pushes keep their direct path, and only frees are deferred.
3. An exception thrown inside compute with the GIL released: the GIL is re-acquired, the session is abandoned as today, and nothing leaks.
4. A mission swap or a `nc.reset()` with frees pending: the pending list is drained or cleared, never applied to a rebuilt mirror.
5. The packaged log follower, or any other Python thread, running during compute: no mirror, transform-store or sensor-state container is mutated from it.

---

### Task 1: Compute timers

**Files:** `native/src/host/host_bindings.cc` (a `steady_clock` accumulator around each of the four `next()` compute calls and `k4_eligible`, plus a binding that reads and resets them), `engine/appc/native_combat.py`, and the frame profiler's Python side (`engine/core/frame_profiler.py`, and wherever the `sim.*`/`cb.*` rows are recorded). The goal is nested rows `k0.compute` (under `sim.weapons`), `k1.compute` (under `cb.held_weapons`), `k2.compute` (under `cb.phasers`), `k3.compute` (under `cb.projectiles`) and `k4.compute` (under `cb.eligibility`). Tests: new `tests/unit/test_native_compute_timers.py`, plus the existing frame-profiler tests.

- [ ] Tests (RED):
  - the rows appear, nested, when the switch is on;
  - each reads at most its parent row;
  - they are absent or zero with the switch off;
  - the accumulator resets per report.
- [ ] Implement. The timer must not add a CPython call inside compute.
- [ ] Run the tests → PASS. Commit.

### Task 2: Deferred frees and queued off-main pushes

**Files:**
- `engine/appc/native_combat.py`: `unregister_handle` and `_drop` record the handle; drain at `combat_k*_begin` and at the tick boundary.
- `engine/appc/objects.py`: the combined row-plus-transform finalizer.
- The `NativeField.__set__` path: a push from a non-main thread is queued.
- The binding entry points that drain: before each kernel session begins, and at `host_loop._combat_tick_boundary` and the GameLoop end-of-tick drain.
- `nc.reset()` and the mission swap clear the pending lists.

Tests: new `tests/unit/test_native_deferred_frees.py`, plus the existing native-combat registry, mirror and finalizer tests.

- [ ] Tests (RED):
  - Review Focus 1, 2 and 4;
  - a push from a `threading.Thread` lands at the next drain, not at once, and in recorded order;
  - frees drain before pushes;
  - `k1_launch_module_release` and `_forget_part_caches` are deferred with their row;
  - `TransformStore::free` is deferred with its row.
- [ ] Implement (spec ruling R2).
- [ ] Run the tests, the six differential files and the damage falsifier → PASS.
- [ ] Mutation: free at once in the finalizer → the Review Focus 1 test fails. Commit.

### Task 3: Release the GIL around compute

**Files:** `native/src/host/host_bindings.cc` (`py::gil_scoped_release` around exactly the four compute calls of LM §5.1), `tests/unit/test_native_k1_holds_gil.py` (revised: it asserts the release wraps exactly the compute call, and K0, K2 and K3 gain the same guard), and a new `tests/integration/test_native_off_lock_stress.py`.

- [ ] Tests (RED):
  - **The stress test.** The headless 64-ship fight (the DR §9 harness or `tests/helpers/k3_fight.py`) is run twice with the same seeds. The second run has a Python thread that churns cyclic garbage with finalizers, plus an object whose `__del__` pushes an idempotent value into a live row, all while compute runs. Per-tick state matches by `.hex()`, and the queued entries match in order.
  - **A proof the release happens:** a test-only native hook records `PyGILState_Check()` == 0 inside compute.
  - **Review Focus 3:** an exception thrown in compute.
  - **The guards.**
- [ ] Implement.
- [ ] Run the stress test, the GIL tests, the six differentials, the host K2/K3/posed differentials, the damage falsifier and ctest → PASS.
- [ ] Mutation: remove Task 2's off-main queue → the stress test (or a targeted variant) fails. Commit.

### Task 4: Benchmark and documentation (controller)

- [ ] Benchmark two 64-ship runs like for like with C-274/C-275 (SIG-176), reporting each `k*.compute` row's share of its parent. Perf register entries.
- [ ] Spec §10. Roadmap: I done, with the per-core split's decision data. Lock map superseded notes. CLAUDE.md only if a row becomes wrong. Commit.
- [ ] Final whole-branch review (most capable model); one fix round.
