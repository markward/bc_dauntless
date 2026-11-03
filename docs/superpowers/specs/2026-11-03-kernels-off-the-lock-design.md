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
- **Measured** (SIG-177): kernel compute is ≈ 0.59 ms per tick of ≈ 1.70 in the combat rows (K0 14%, K1 26%, K2 63%, K3 small). The release changes no combat row beyond spread; `sim` 9.138 → 9.311, with `sim.effects` and `gl.ai` varying run to run.
- **Ruling, per-core split** (spec §3): not built and not recommended yet. It is bounded by the 0.59 ms of compute, most of it K2, which under native damage writes its targets in order. The larger remaining cost is the binding and Python around the kernels (≈ 1.1 ms).
- **Known limits for J:**
  - Off the main thread, these push paths are not queued: `push_mount_order`, `push_posed_parts`, `push_arriving`, `HullBoxField.__delete__`, `push_ids`/`push_field`, `push_set_members`, `register`, the torpedo table, the globals.
  - Other combat bindings called off the main thread are unguarded, `combat_can_detect` included.
  - Transform-store and `g_world` writes from another thread are unguarded.
  
  No SDK `__del__` reaches any of these today. A combat thread beside Python (J) needs them, through its snapshot and outbox.
- **Found:** `test_shuttle_service.py::test_neighbouring_docks_keep_their_shuttles_apart` failed once in a combined native run and passed alone and on rerun (see the final review).
