# Phase 6 follow-up 3 — No per-tick patch scans in K2/K3 damage — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop scanning instance dicts for patched methods every tick before K2 and K3. That means two things:
- the damage "clean" list (`combat_dmg_clean_handles`), whose target scan covers each target's dict plus every reachable subsystem's;
- the instance-attribute half of K2's per-ship scan (`combat_k2_scan_ships`: ship, phaser system and bank dicts).

The kernels then check only representability, answered from the mirror.

**Why:** spec Part A says a patched App method is not honoured. These scans exist only to honour instance patches. In C-341 (128 ships, Release, cProfile), `combat_dmg_clean_handles` took 0.40 s and `combat_k2_scan_ships` 0.37 s of `k2_phasers`' 2.48 s, about 31%, or roughly 0.14 ms a tick at 128 ships. Mark ruled on 2026-11-06 to include the K2 ship scan.

**Architecture:**
- A new combat-library predicate `dmg_target_representable(const Mirror&, int64_t ship)` replaces the `p.clean` set lookup in the K2 pulse and the K3 hits.
- The same predicate replaces the Python `_kdmg_clean([ship])` / `_dmg_patched(ship, …)` checks in `native_combat.apply_hit`.
- The clean machinery, binding and caches are deleted.
- K2's ship scan keeps its class checks: stock identity, the seen set, and `_k2_flag`. Those are per type, and the static guard `tests/unit/test_native_k2_override_guard.py` backs them. It drops every instance-dict key test, and with them `python_banks`.

**Tech Stack:** C++20 combat library (`-ffp-contract=off`), pybind (`native/src/host/host_bindings.cc`), Python 3.11, gtest, pytest.

**Spec:** `docs/superpowers/specs/2026-11-05-phase6-engine-stages-native-design.md` §3 (Part A: "Mods and patches"). Recon: `docs/superpowers/plans/2026-11-05-phase6-a2-a4-recon.md`, A3 §2 (K2) and §7 item 2.

## Global Constraints

- **Branch.** `ws/phase6-clean-list` in `.claude/worktrees/native-motion`, stacked on `ws/phase6-beam-feed` at `dcf2dae71`. Both branches touch `native_combat.py`. If the beam feed is rejected, rebase onto `main`.
- **Tests.** Never run the gate or a whole suite. Run focused test files only, listed literally. Never pass pytest an empty file list.
- **Git.** No destructive git. Stage with explicit paths.
- **Goldens.** `tests/integration/test_golden_fights.py` stays byte-identical. Never set `UPDATE_COMBAT_GOLDEN`. No golden scene patches an instance attribute, so the change in who applies a hit must not show there. If a golden moves, stop and report; do not re-record.
- **Behaviour.** Bit-exact with today for every unpatched object.
  - For a patched instance attribute, the new behaviour is the intended Part A change: the kernel computes the stock answer from the mirror. Tests must say so by name, `test_a_patched_<x>_is_not_honoured`.
- **Kept, not removed:**
  - `p.ok`. It is false when `combat.apply_hit` is not the engine's own (the golden and test spy seam) or the player can't be named.
  - The class checks.
  - `DAUNTLESS_NATIVE_COMBAT=0`.
  - The audit stand-down.
  - Every representability check.
  - The per-call `_DMG_SUB_PATCHES` checks inside `set_condition` / `damage_system`. They are out of scope and not in the measured cost; list them as a follow-up in the report.
- **Build** from the worktree root with `cmake --build build -j`. Combat gtests need `DAUNTLESS_GAME_DIR="/Users/mward/Documents/Star Trek Bridge Commander/game"`.
- **Benchmarks** run only in Task 3, on an idle machine, after Mark clears it.

## Review Focus

1. **A target whose reachable subsystem has no mirror row** must still hand its hit back.
   - The reachable subsystems are its `mount_order`, `_hull` and `_shield_subsystem`.
   - "No mirror row" means `kRefUnrepresentable`, or a handle whose row is gone.
   - Today's clean check returns "not clean" for these. The predicate must return the same answer. Task 1 pins each of the three sources.
2. **A target with no Object row**, or a handle of another kind, hands back. Task 1 pins it.
3. **The hand-back reason is renamed** from `unscanned` to `unrepresentable` everywhere it is counted or printed. That covers counters, dispatch tests and any perf or log line.
4. **K2 ship scan: an unrepresentable bank handle** (a bank with no Subsystem `_nslot`) still sends the ship to Python. Today `_k2_python_ship` does this through the `pulse_banks` path. Task 2 pins it once the instance checks are gone.
5. **`python_banks` and `python_ships`** keep their meaning for class reasons only. A ship sent to Python because of its class is still counted `Overridden`. Task 2 pins a subclass case.

---

### Task 1: The damage kernels check representability from the mirror; the clean list is deleted

**Files:**
- Modify: `native/src/combat/include/dauntless/combat/damage.h` and `src/damage.cc`: add the predicate.
- Modify: `k2_beams.h` / `k2_beams.cc`:
  - drop `K2PulseCtx::clean`;
  - the pulse calls the predicate;
  - rename `K2PulseWhy::unscanned` to `unrepresentable`.
- Modify: `k3_projectiles.h` / `k3_projectiles.cc`: the hits loop calls the predicate.
- Modify: `native/src/host/host_bindings.cc`:
  - stop parsing `"clean"`;
  - delete `combat_dmg_clean`, `combat_dmg_clean_handles`, `combat_dmg_clean_clear`, `combat_dmg_clean_counts`, `combat_dmg_clean_reset_counts` and the `DmgClean*` caches;
  - wherever the hand-back reason names are exported, rename them;
  - `combat_apply_hit` answers representability with the predicate before applying, and returns False to hand back.
- Modify: `engine/appc/native_combat.py`:
  - `_k2_pulse_ctx` and `_k3_apply_hits` send no clean list;
  - `_k3_apply_hits` drops the `_KDMG_TORP_NAMES` python list. An instance `GetDamageRadiusFactor` on a torpedo is no longer obeyed;
  - `apply_hit` drops `_kdmg_clean([ship])` and `_dmg_patched(ship, _DMG_SHIP_NAMES)`;
  - delete `_kdmg_clean`, `_kdmg_clean_handles`, `_KDMG_SUB_NAMES`, `_KDMG_TORP_NAMES`, the `combat_dmg_clean_clear` call in `reset()` and the `_REQUIRED_BINDINGS` entry;
  - update the block comment above `_KDMG_SUB_NAMES` (NOT OK / "clean") to say what is checked now.
- Tests:
  - ctests in `native/tests/combat/k2_beams_test.cc`, `k3_projectiles_test.cc` and `damage_test.cc`;
  - `tests/unit/test_native_damage_clean_cache.py`: delete it, or rewrite it as below;
  - `tests/unit/test_native_k2_dispatch.py`, `test_native_k2_bindings.py`, `test_native_k3_dispatch.py`, `test_native_k3_bindings.py`: update every clean / `unscanned` reference.

**Interfaces:**
- Produces: `bool dmg_target_representable(const Mirror& m, int64_t ship);`. It returns true when:
  - `ship` names a live Object row; and
  - each handle in that row's `mount_order`, `_hull` and `_shield_subsystem` is either `-1` or a live Subsystem row. It is never `kRefUnrepresentable`.

  These are exactly the conditions `dmg_clean_one` checks today, minus the dict probes.
- Produces: `K2PulseWhy::unrepresentable`, replacing `unscanned`.

- [ ] **Step 1: Write the ctests.**
  - `Damage.RepresentableTargetWithLiveSubsystems`.
  - `Damage.UnrepresentableMountHandsBack`, `Damage.GoneHullRowHandsBack`, `Damage.UnrepresentableShieldHandsBack`.
  - `Damage.NoObjectRowHandsBack`.
  - `K2Beams.PulseNeedsNoCleanList`: a target pulses natively with no clean set. Previously this would have been `unscanned`.
  - `K2Beams.PulseHandsBackAnUnrepresentableTarget`: the count is under `unrepresentable`.
  - `K3Projectiles.HitNeedsNoCleanList`.
  - `K3Projectiles.HitHandsBackAnUnrepresentableTarget`.
- [ ] **Step 2: Write the pytests.**
  - `test_a_patched_damage_method_on_the_target_is_not_honoured`: an instance attribute from today's `_DMG_SHIP_NAMES` on the target ship, and another from `_DMG_SUB_NAMES` on its shield subsystem, then a phaser pulse and a torpedo hit. Both are applied natively: the hand-back counters stay 0, and the patched attribute is never called (a spy).
  - `test_a_patched_torpedo_damage_radius_is_not_honoured`.
  - `test_apply_hit_hands_back_an_unrepresentable_target`.
- [ ] **Step 3: Run them. Expect FAIL.**
- [ ] **Step 4: Implement.**
- [ ] **Step 5: Run the new tests, plus:**
  - the four dispatch and bindings files above;
  - `tests/unit/test_native_k2_override_guard.py`, `tests/unit/test_native_k3_override_guard.py`;
  - `tests/host/test_native_k2_differential.py`, `tests/integration/test_native_k3_differential.py` (or `tests/host/…`, whichever exists);
  - `tests/host/test_native_combat_scene_audit.py`, `tests/unit/test_damage_effect_queue.py`;
  - `tests/integration/test_golden_fights.py`;
  - `ctest --test-dir build -R combat_`.

  Expect PASS, with the goldens byte-identical.
- [ ] **Step 6: Commit** `perf(native): damage kernels check representability from the mirror, not a per-tick patch scan`.

### Task 2: K2's ship scan stops reading instance dicts

**Files:**
- Modify: `native/src/host/host_bindings.cc` `combat_k2_scan_ships` and its comment.
  - Drop the `ship_patches`, `system_patches` and `bank_patches` parameters and every dict-key test.
  - Keep the `_nslot` handle reads, the seen-set and stock-class identity tests, and the bank `_target` class test.
  - A bank whose `_nslot` is not a Subsystem handle still makes the ship unclean.
  - Drop the scan's dict-version caches and counters if nothing else needs them, along with their `combat_k2_scan_clear` / counts bindings and their callers.
- Modify: `engine/appc/native_combat.py`:
  - `_k2_ship_handles` and `_k2_python_ship` keep only the class reasons and the unrepresentable-bank reason;
  - delete `_K2_SHIP_PATCHES`, `_K2_SYSTEM_PATCHES`, `_K2_BANK_PATCHES`, `_K2_BANK_PULSE_PATCHES`, `_K2_BANK_WALK_PATCHES` and `pulse_banks`;
  - `_k2_pulse_ctx` sends `python_banks` empty, or K2 drops the field and its `python` reason. Choose one and say which;
  - update the "WHAT THE DRIVER CHECKS BEFORE begin" comment in `k2_beams.h`.
- Tests:
  - `tests/unit/test_native_k2_scan_cache.py`: delete it, or rewrite it as below;
  - `tests/unit/test_native_k2_dispatch.py`;
  - `tests/unit/test_native_k2_override_guard.py`: it parses the role lists out of the header, so update it with the header.

**Interfaces:**
- Consumes: nothing from Task 1, except that `python_banks` is no longer produced.
- Produces: `combat_k2_scan_ships(ships, obj_kind, kind_shift, seen, stock_system, stock_bank) -> (handles, unclean)`.

- [ ] **Step 1: Write the tests.**
  - `test_a_patched_bank_method_is_not_honoured`: an instance attribute shadowing `GetMaxDamage` on a bank. The ship is walked natively and its pulse applied natively.
  - `test_a_patched_ship_method_is_not_honoured`: the same on the ship.
  - `test_a_bank_with_no_subsystem_row_sends_its_ship_to_python`.
  - `test_a_subclassed_bank_still_sends_its_ship_to_python`: a class `_k2_flag` flags.
  - `test_scan_reads_no_instance_dict_keys`: put a sentinel key in every ship, system and bank dict. The handles and `unclean` come out exactly as they do without the sentinel.
- [ ] **Step 2: Run them. Expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the new tests and Task 1's Step 5 list. Expect PASS, goldens byte-identical.**
- [ ] **Step 5: Commit** `perf(native): K2's ship scan reads classes and handles, not instance dicts`.

### Task 3: Measure (shared window with the beam feed's Task 5)

- Do this in the same idle window and the same Release worktree as `2026-11-06-phase6-native-beam-feed.md` Task 5.
- Capture three commits: `main` (`ea9ed08cb`), the beam-feed tip (`dcf2dae71`) and this branch's tip.
  - Each at 64 and 128 ships, exterior view.
  - Two runs each.
  - Plus one cProfile run at 128 on this tip.
- Score per tick: `cb.phasers`, `cb.projectiles`, `sim.combat` and ticks a frame. Use the median of reports 3–11.
- From the cProfile, report `k2_phasers` and its pieces against C-341:
  - the 0.40 s `combat_dmg_clean_handles` (the clean list) should be gone;
  - `combat_k2_scan_ships` keeps its name and still runs every tick, now with no dict probes: compare it against C-341's 0.37 s, don't expect it to vanish.
- The pulse's representability check (`dmg_target_representable`) runs inside the GIL-released K2 compute, so cProfile cannot show it: judge it from `cb.phasers`.
- Hand-back counter names changed across these commits; any cross-commit comparison needs this map:
  - `k2_pulse_python_reasons` / `k3_hit_python_reasons`: `unscanned` → `unrepresentable`; `python` is dropped (no producer).
  - A ship sent to Python for a bank with no Subsystem row counts as RUN_PYTHON `overridden` (`k2_python_reasons`), not `stale_row`.
- Perf register: the captures and one signal. Say plainly what it bought, including if it is inside the run-to-run spread.
- Live-check list:
  - a 64-ship fight;
  - phaser and torpedo damage on shields, hull and subsystems, looking as before;
  - a Quick Battle with an LC Intrepid (mod hardpoints).
