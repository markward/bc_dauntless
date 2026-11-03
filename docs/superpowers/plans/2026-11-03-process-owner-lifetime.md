# Process owner lifetime — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `PythonMethodProcess` stops the moment its owner is dropped, with no dependence on the cyclic garbage collector.

**Architecture:** `PythonMethodProcess` holds its instance by weak reference when the instance supports one (strong otherwise); a dead instance makes `Update` a no-op. Nothing else changes.

**Tech Stack:** Python 3.11, pytest.

**Spec:** `docs/superpowers/specs/2026-11-03-process-owner-lifetime-design.md`

## Global Constraints

- Worktree `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/native-combat-k3`, branch `ws/process-replace`.
- No SDK file is edited. No C++ change, so no build is needed.
- Focused tests only, via `uv run pytest <files>`. NEVER `uv run --active`. Never whole suites, never `scripts/check_tests.sh`. Never launch the game.
- The banned git commands of CLAUDE.md "Shared checkout" apply. Stage explicit paths; `git commit -F <file> -- <paths>`; end messages with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- No red or xfail tests committed. Mutation proof by `cp` backup, mutate, run, `cp` restore, `diff` clean. No subagents.

## Review Focus

1. An owner dropped while the manager is mid-`tick` (the owner's own callback drops it, or an earlier callback in the same `due` list drops a later process's owner): no exception, and the dropped process does not fire after its owner is gone.
2. Save/load: `ProcessWrapper.__setstate__` re-runs `SetupProcess`; the condition scripts drop and re-create their process. Both still work.
3. An instance that cannot be weakly referenced (e.g. a module-level function object is fine, but an `int` or a `__slots__` class without `__weakref__` is not): still held and still fires.
4. Re-calling `SetInstance` / `SetFunction` with a different instance replaces the reference, and the old instance is not kept alive.
5. The K1 game-loop differential's event logs (both arms) are unaffected or become equal where they differed only by GC timing.

---

### Task 1: Weak instance reference

**Files:** `engine/appc/time_slice.py` (`PythonMethodProcess`), new `tests/unit/test_time_slice_owner_lifetime.py`, the module docstrings that describe stopping (`time_slice.py` header and `TimeSliceProcessManager` docstring) updated to say a process also stops when its owner goes.

- [ ] Tests (RED), all with `gc.disable()` around the body and `gc.enable()` in `finally`:
  - `test_wrapper_shape_stops_when_owner_dropped`: an owner class whose `__init__` does `self.p = PythonMethodProcess(manager=mgr); self.p.SetInstance(self); self.p.SetFunction("Fire"); self.p.SetDelay(0.5)`, counting calls. Tick to fire once; drop the owner's last reference; assert `mgr.count()` fell by one and further ticks fire nothing — no `gc.collect()` anywhere.
  - `test_two_arg_form_stops_when_owner_dropped`: same with `SetFunction(self, "Fire")`.
  - `test_live_owner_keeps_firing`: fires on each delay while referenced.
  - `test_non_weakrefable_instance_still_fires`: a `__slots__ = ("calls",)` class with a `Fire` method.
  - `test_reassigned_instance_releases_the_old_one`: `SetInstance(a)` then `SetInstance(b)`; dropping `a` frees it (a `weakref.ref(a)` is dead) and `b` is the one called.
  - `test_owner_dropped_mid_tick`: two due processes; the first's callback drops the second's owner; the tick completes and the second does not fire.
  - `test_sdk_power_display_one_refresh_process_per_load` (SDK, headless): with the collector disabled, `tests.helpers.headless_mission.load("Maelstrom.Episode3.E3M2.E3M2")` then `load("Maelstrom.Episode6.E6M1.E6M1")`; after each, the live processes in `engine.appc.time_slice.g_kAIManager` whose instance is a `Bridge.PowerDisplay.ProcessWrapper` number exactly 1. (Measured before the fix: 4.)
- [ ] Run → the owner-drop and SDK tests FAIL; the others may pass.
- [ ] Implement in `PythonMethodProcess`: store the instance through one private setter used by `SetInstance` and the two-argument `SetFunction`; `weakref.ref` when possible, else the object itself; `Update` resolves it and returns when dead. Keep `__init__`'s "no instance" state.
- [ ] Run the new file plus `tests/unit/test_time_slice.py`, `tests/unit/test_time_slice_self_register.py`, `tests/unit/test_condition_timer_end_to_end.py`, `tests/unit/test_timers.py`, `tests/unit/test_loop.py`, `tests/integration/test_native_k1_differential.py` → PASS.
- [ ] Mutation: make the setter always store the object strongly → the owner-drop and SDK tests fail. Restore by `cp`, `diff` clean.
- [ ] Commit.

### Task 2: Docs (controller)

- [ ] Spec §6 outcome; roadmap §7 item resolved plus the condition-cycle item (spec §7); `lock-map.md` point 2 note. Commit.
- [ ] Final review (most capable model); one fix round.
