# Phase 6 follow-up 3b — K2's ship scan answered from the mirror — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Win back the regression SIG-203 found. With its dict-version cache gone, `combat_k2_scan_ships` reads every bank's Python dict every tick: 0.57 s against 0.37 s in C-341's cProfile, about 95 µs a tick at 128 ships. After this change it reads one `_nslot` per ship and answers the rest from the mirror.

**Architecture:**
- **What the mirror holds today.** Every object with a mirror row registered its class into `_k2_seen_set` (`native_combat.register` and `reclassify`). The mirror holds each ship's `_phaser_system` ref, each system's `_children` ref list, and each bank's `_target` ref. All are pushed on write.
- **Only missing piece: is a row's class exactly the stock role class?** That means `_k2_stock_bank` for a bank and `_k2_stock_system` for a phaser system.
- **New per-row flag `k2_stock`.** It is pushed wherever the class flags are pushed today: `_push_extras`, at register and at reclassify.
- **New scan.** It reads `_nslot` per ship and walks the mirror:
  - a system row with `k2_stock` 0, or a bank row with `k2_stock` 0, makes the ship unclean;
  - so does any `REF_UNREPRESENTABLE` (-2) in `_phaser_system`, `_children` or a bank's `_target`.
- **What Python still does.** `_k2_python_ship` remains the authority for the unclean ships only, as today.

**Tech Stack:** C++20 combat library, pybind, Python 3.11, gtest, pytest.

**Spec:** `docs/superpowers/specs/2026-11-05-phase6-engine-stages-native-design.md` §3 Part A. Evidence: perf register SIG-203.

## Global Constraints

- Branch `ws/phase6-clean-list`, continued. This fixes a regression that branch introduced.
- Never run the gate or a whole suite. Focused test files only, listed literally. Never pass pytest an empty file list.
- No destructive git. Stage explicit paths.
- Goldens stay byte-identical. Never set `UPDATE_COMBAT_GOLDEN`.
- **Routing must not change.** For every object state the mirror tracks, the set of ships sent to Python, and the whole-step flag, must equal what today's binding gives.
- **Known and accepted divergence:**
  - The case: a bank's `_nslot` deleted or replaced behind the mirror's back, with no `_drop`.
  - Today's binding reads the dict, so it sees the change. The new scan reads the mirror, so it doesn't.
  - Why accepted: every engine path that loses a row goes through `_drop` / `forget_rows`, which re-pushes the referrers.
  - Tests that fake this case are rewritten to go through the real drop path.
- Swapping `__class__` without `reclassify` keeps its documented per-class caveat (`_k2_unseen` docstring). The new flag has the same caveat, and its comment must say so.
- Build from the worktree root with `cmake --build build -j`. Combat gtests need `DAUNTLESS_GAME_DIR="/Users/mward/Documents/Star Trek Bridge Commander/game"`.

## Review Focus

1. **A child that has no row.** The mirror's `_children` must hold -2 for it, never drop it from the list. Pin with a pytest that builds a bank with no row inside a registered system.
2. **A target that has no row.** A bank's `_target` set to an object that was never registered pushes -2, and the ship comes back unclean. Python then decides with `_k2_unseen`, as today.
3. **`reclassify` (rocks).** It must re-push `k2_stock`. Pin it by swapping a bank's class to a subclass and calling `reclassify`: the ship becomes unclean.
4. **A row dropped mid-mission** (`_drop`). Its parent's `_children` is re-pushed with -2, so the ship comes back unclean. Pin it through the real drop path.

---

### Task 1: Per-row `k2_stock` flag, and the scan answered from the mirror

**Files:**
- Modify: `native/src/combat/include/dauntless/combat/mirror.h` and the mirror sources: add `int64_t k2_stock = 0` on `SubsystemRow` and its `Field` entry, following an existing class-flag field. Also add the drift table if one lists Subsystem fields.
- Modify: `engine/appc/native_combat.py`:
  - `_push_extras` (or wherever class flags are pushed per row) pushes `k2_stock` = `type(obj) is _k2_stock_bank` for a bank row, `type(obj) is _k2_stock_system` for a phaser system row, and 0 otherwise;
  - `_k2_ship_handles` calls the new binding.
- Create: `native/src/combat/include/dauntless/combat/k2_scan.h` and `src/k2_scan.cc`, holding `std::vector<size_t> k2_unclean_ships(const Mirror& m, const std::vector<int64_t>& handles);`. It returns the indexes of unclean ships, in order. For each handle ≥ 0, the ship is unclean when:
  - the Object row is gone;
  - `_phaser_system` is -2;
  - the system row has `k2_stock` 0;
  - `_children` holds a -2, or a bank row with `k2_stock` 0, or a bank whose `_target` is -2.

  A system ref of -1 (no system) is clean, as today. A ship handle of -1 is "no row": as today, it is not checked, and its handle -1 goes to begin.
- Modify: `native/src/host/host_bindings.cc`:
  - replace the body of `combat_k2_scan_ships` with `combat_k2_scan_rows(ships, obj_kind, kind_shift) -> (handles, unclean)`. It reads each ship's `_nslot` exactly as today's code does, calls `k2_unclean_ships`, and returns `unclean` as (ship, handle) pairs in order;
  - delete `k2_clean_system` / `k2_scan_ships` and the old binding;
  - replace the `combat_k2_scan_version` marker with `combat_k2_scan_rows` in `_REQUIRED_BINDINGS`; the new name is the marker.
- Tests:
  - ctests `native/tests/combat/k2_scan_test.cc` (register with the combat tests);
  - `tests/unit/test_native_k2_bindings.py`, `tests/unit/test_native_k2_dispatch.py`: rework `test_binding_scan_matches_the_python_clean_check` and its siblings so they drive state through registration and pushes, never by editing `_nslot` behind the mirror.

**Interfaces:**
- Produces: `k2_unclean_ships` (above), the field `SubsystemRow::k2_stock`, and the binding `combat_k2_scan_rows`.

- [ ] **Step 1: Write the tests.**
  - ctests `K2Scan.StockShipIsClean`, `K2Scan.NoSystemIsClean`, `K2Scan.UnrepresentableSystemIsUnclean`, `K2Scan.SubclassedSystemIsUnclean`, `K2Scan.SubclassedBankIsUnclean`, `K2Scan.NoRowChildIsUnclean`, `K2Scan.NoRowTargetIsUnclean`, `K2Scan.GoneShipRowIsUnclean`, `K2Scan.OrderIsKept`.
  - pytest `test_scan_rows_matches_the_python_authority`. For a fleet built through the real API, the scan's unclean set equals the ships `_k2_python_ship` would not call 0. The fleet has:
    - stock ships;
    - a subclassed bank, and a subclassed system;
    - a bank with no row (built so it never registers);
    - a target with no row;
    - a ship with no phaser system;
    - a dropped row (through `_drop`).
  - Also pytests for Review Focus items 3 and 4.
- [ ] **Step 2: Run them. Expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the new tests, plus:**
  - `tests/unit/test_native_k2_dispatch.py`, `tests/unit/test_native_k2_bindings.py`, `tests/unit/test_native_k2_override_guard.py`;
  - `tests/host/test_native_k2_differential.py`, `tests/host/test_native_combat_scene_audit.py`;
  - `tests/integration/test_golden_fights.py`, `tests/unit/test_gate_tiers.py`;
  - `ctest --test-dir build -R combat_`.

  Expect PASS with goldens byte-identical. If `test_gate_tiers` fails because a renamed test is listed in `deep_pytest.txt`, stop and report it. Do not edit that file.
- [ ] **Step 5: Commit** `perf(native): K2's ship scan answered from the mirror`.

### Task 2: Measure (needs an idle window from Mark)

- Release in `.claude/worktrees/release-macos`. Capture `dda9402b2` (before) and this tip (after), back to back.
  - 128 ships, exterior, two runs each.
  - One cProfile run at 128 on the tip (`DAUNTLESS_PROFILE_PY`, frames 500:400).
- Score `cb.phasers` and `sim.combat` per tick, and ticks a frame. In the cProfile, compare `combat_k2_scan_rows` with SIG-203's 0.566 s `combat_k2_scan_ships`.
- Add the captures and one signal to the perf register.
