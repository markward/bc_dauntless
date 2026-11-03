# Kernels off the lock (roadmap I) — design

**Status:** built 2026-11-03 (§10); not live-verified; unmerged. Roadmap workstream I, after native damage (D). Mark asked overnight to spec, plan and build it ("nothing overcomplicated").
**Branch:** `ws/combat-off-lock`, off D's tip `a338e21fa` on `ws/combat-native-damage` (unmerged until Mark checks D), worktree `.claude/worktrees/native-combat-k3`.
**Input map:** `docs/reference/engine/native-combat/lock-map.md` (LM §n).

## 1. Why

After D, no kernel asks Python anything inside its compute: the combat library contains no CPython (LM §0). What still ties combat to the Python thread is that every kernel computes while holding the GIL, and nothing guarantees the mirror tables stay still if it did not. This phase makes the compute run with the GIL released, safely and provably, so the next phase (J, combat on its own thread beside Python) starts from kernels that already run without the lock.

## 2. Goals

1. **Measure first.** Add a compute-only timer per kernel call (none exists, LM §7.1). It is a native `steady_clock` accumulator around each kernel's compute, exposed to the frame profiler as rows `k0.compute`, `k1.compute`, `k2.compute`, `k3.compute` and `k4.compute`, nested under their existing `sim.*`/`cb.*` rows.
2. **Row lifetime made safe for any Python running during compute** (LM §8 point 2):
   - **Deferred frees.** The mirror-row and transform-slot finalizers (`unregister_handle`, `objects.py`'s combined finalizer, `k1_launch_module_release`, `_forget_part_caches`) record the handle in a pending list. The list is drained under the GIL at fixed points: the start of every kernel session and the tick boundary. A pending row stays valid until drained. This also fixes when frees happen, where today it is GC timing.
   - **Off-main pushes queued.** A mirror push (`NativeField.__set__` and the `combat_set_*` bindings reached from it) made on a thread other than the main thread is queued and applied at the next drain point. This covers SDK `__del__` methods that push into live rows (LM §2.2 point 2: `ConditionPulseReady` → `_watch_checks`).
3. **The GIL is released around exactly the compute call** of K0, K1, K2 and K3: the four `next()` calls of LM §5.1. Everything before and after stays under the GIL. K4 and `can_detect` keep it: they are single short calls (LM §5.2).
4. **Proven:**
   - a stress test runs a Python thread that churns garbage collection, finalizers and `__del__` pushes while the 64-ship fight runs; the per-tick state matches a run without the thread by `.hex()`, and the queued entries match in order;
   - every differential stays green;
   - a source guard asserts that the four release sites wrap only the compute call.
5. **A benchmark** before and after, per tick, like for like with SIG-176.

## 3. Non-goals

- **Per-ship work across cores** (LM §6). It needs `SensorState` partitioning and an order-preserving merge. It is decided on goal 1's numbers in a follow-on phase: if the compute share of the combat rows is small, the split is not worth its complexity.
- **A combat thread concurrent with Python** (J, LM §2.4).
- **Making the packaged log follower a native thread** (LM §5.1 option 3). Goal 2 makes it harmless, so it can stay as it is.

## 4. Design notes

- **Drain points** are the start of each `combat_k*_begin` and the tick boundary (`host_loop._combat_tick_boundary`, plus the GameLoop end-of-tick drain for headless runs). Pending frees drain before pending pushes, in recorded order.
- **The main thread** is identified once at host start; `threading.main_thread()` is acceptable in Python.
- **A kernel's compute never takes the GIL.** If compute throws, pybind's `gil_scoped_release` re-acquires the lock during unwinding; that path gets a test.
- **`test_native_k1_holds_gil.py` is revised deliberately**: it now asserts the release wraps exactly the compute call, and guards are added for K0, K2 and K3 (LM §5.2).

## 5. Rulings (mine; Mark may overturn)

- **R1. Scenario A only** (release in place, LM §8 point 1). It is inert in a checkout build and safe in a packaged one once goal 2 is in. It is the prerequisite for B; C is deferred to its own phase, decided on the numbers.
- **R2. Deferred frees and queued off-main pushes** (LM §5.1 options 1 and 4), not a mirror mutex (option 2). Both keep every kernel lock-free and add no cost to the ~244 pushes a tick on the main thread, which keep their direct path.
- **R3. Bit-exactness is unchanged.** A free or a push that lands at a drain point instead of mid-step changes nothing a kernel computes. Frees only name unreachable objects. Off-main pushes happen today only at GC points, which are already timing-dependent.

## 6. Testing

- A compute timer test: the rows exist and are nested, and they read 0 with the switch off.
- Deferred-free tests:
  - a row freed during a session stays valid until the drain;
  - a handle is not reused before the drain;
  - draining at the boundary frees it.
- An off-main push test: a push from a `threading.Thread` lands at the next drain, not at once; a main-thread push is unchanged.
- The stress test (goal 4).
- The GIL guards (goal 4), and an exception-in-compute test.
- Every existing differential, the damage falsifier and the presentation falsifier.

## 10. Outcome

Built 2026-11-03 on `ws/combat-off-lock`:
- Task 1, compute timers: `cb4310bea`.
- Task 2, deferred frees and queued off-main pushes: `7b8c75c79`.
- Task 3, the release: `e2be25c80`.

D's late fixes were merged in at `b2e8bd703`: a K2 regression for patched damage getters, and test-isolation leaks.

- **Kernels compute without the GIL.** K0-K3's `next()` and K3's `apply_hits` release it around exactly their compute; K4 and `can_detect` keep it (single short calls).
  - A test-only native probe confirms the GIL was released in compute.
  - Guards pin that the release wraps only the compute call. `test_native_k1_holds_gil.py` was revised deliberately, and K0, K2 and K3 gained guards.
  - An exception thrown in compute re-acquires the GIL and abandons the session as before.
- **Safe against Python running meanwhile.**
  - Every mirror-row and transform-slot free waits for a drain point: each session's start and the tick boundary.
  - Mirror pushes from a non-main thread are queued; main-thread pushes keep their direct path.
  - Deviation: a main-thread `_drop` still frees at once. It runs between records under the GIL, and the mid-walk "row gone" tests depend on it.
  - The stress test runs a Python thread that churns cyclic garbage, finalizers and an idempotent `__del__` push while the 64-ship fight computes. Per-tick state matches by `.hex()`, and pushes match by label and order. Removing the off-main queue, or the free deferral, makes it fail.
  - Since the final review it also has a **real-race case** (`1d170e432`): during compute, the off-main thread writes a different value into a field a kernel reads, and the expected run applies the same write at the same drain point. Sending that push direct instead fails the state comparison, on a bank's charge level at tick 75.
- **Measured** (SIG-177): kernel compute is ≈ 0.59 ms per tick of ≈ 1.61 in the five combat rows. As a share of each kernel's own parent row: K0 14%, K1 26%, K2 63%, K3 14%. Of the 0.59 ms itself, K2 is about 62% and K0 about 6%. The release changes no combat row beyond spread; `sim` 9.138 → 9.311, with `sim.effects` and `gl.ai` varying run to run. **Qualifier:** this was a checkout build, where no second Python thread exists, so the release is inert there. In a packaged build the log follower, or a CPU-bound mod thread, can take the GIL at each of about 5 releases a tick, and each re-acquire can then wait up to a switch interval (5 ms). That case is not measured.
- **Ruling, per-core split** (spec §3): not built and not recommended yet. It is bounded by the 0.59 ms of compute, most of it K2, which under native damage writes its targets in order. The larger remaining cost is the binding and Python around the kernels (≈ 1.1 ms).
- **Known limits for J** (final review M1; none is reachable from an SDK `__del__` today, and a combat thread beside Python needs all of them through its snapshot and outbox):
  - **Push paths not queued off the main thread:**
    - `push_mount_order`, `push_posed_parts`, `push_arriving`;
    - `HullBoxField.__delete__`, `push_ids` / `push_field`, `push_set_members`, `register`;
    - the torpedo table, `push_globals`, `push_property`, `push_pulse_params`;
    - `push_set_frame` / `_profile_handle`, `_push_ammo_row`, the part-slot and pose pushes, `_set_condition_py`.
  - **Other combat bindings** called off the main thread are unguarded, `combat_can_detect` included, which writes sensor state.
  - **Transform-store and `g_world` writes** from another thread are unguarded.
  - **The trace hook writes during compute:** it lazily builds `Model::trace_accel`. That is safe while only the main thread renders and loads models, not once J moves render work.
- **R3 holds with one property J must keep** (final review M4). A push queued off the main thread during a session is invisible to the kernel until the session ends, because the drain skips while a session is open. Today that is safe only because the reachable fields (`_watch_checks`, the condition-watch counts) are conservative when stale-high: they hand the work back to Python.
- **Final review: ready with fixes** (0 critical, 2 important, 9 minor). The real-race case and the robustness fixes are in `1d170e432` and `48197eb47`:
  - a queued push that raises is logged and the drain continues;
  - the audit runs after the drain;
  - a collected probe is no longer findable by id natively (`combat_set_obj_id_findable`; queued off the main thread);
  - a paused frame drains;
  - one-time logs fire when pending frees pass 10,000, or when a drain is skipped at a boundary with a session open.
  
  The doc findings are fixed here and in SIG-177.
- **Parked for Mark, the shuttle flake (final review I2).** It predates this branch and is not about threading.
  - `test_shuttle_service.py::test_neighbouring_docks_keep_their_shuttles_apart` fails when the process-wide object-id counter starts at certain values. The cause: the AI's avoidance phase is keyed on `GetObjID()` (`ai_optimized._phase_key`), so it depends on how many objects were made before.
  - Keying the phase on the ship's name (as the K1 differential does) makes the test deterministic, but deterministically failing. Over 26 phase choices, about 1 in 5 dips the Tau Ceti shuttle up to 3.97 GU past `BAND_SLACK_IN` (2.25 GU), below the service's own 20 GU floor from the dock. No collision or separation check failed.
  - Options:
    - (A) fix the shuttle service so the band holds for every phase (recommended);
    - (B) name-key the phase and loosen the slack;
    - (C) pin a passing phase, which hides the problem.
  - Separately, the comment in `ai_optimized` that "the same ship gets the same phase on every run" is wrong across load histories.
  - The test is left unchanged, so it can flake in combined runs until this is decided.
