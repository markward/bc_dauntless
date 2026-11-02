# Native damage (roadmap D) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Damage is computed and applied in C++ for every caller, its effects are queued to the tick boundary, and no kernel checks in with Python to apply a hit.

**Architecture:** First the Python reference takes on the new behaviour: Mark's rulings M1-M4, and hit effects queued as new effect-queue kinds. Then a C++ hit and condition chain reproduce that reference bit-exactly from mirrored inputs, writing through the write log and appending the same queue entries. Then K2 and K3 call it in-kernel.

**Tech Stack:** C++17 combat library and pybind11 bindings, Python 3.11, gtest, pytest.

**Spec:** `docs/superpowers/specs/2026-11-02-native-damage-design.md`. Maps: `docs/reference/engine/native-combat/damage-map.md` (DM), `damage-map-refresh.md` (DR).

**Shape (Mark: "no cut corners, not too much ceremony"):** four implementation tasks, each with its falsifier written first. One task review after Task 2: the Python behaviour is complete there, and it is what the native code must match. One final review on the most capable model. The controller does docs and measurement.

## Global Constraints

- Worktree `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/native-combat-k3`, branch `ws/combat-native-damage`.
- Switch `DAUNTLESS_NATIVE_COMBAT=1`, default OFF. Game state is bit-exact (`.hex()`) against the Python reference with the switch on; queued kinds are compared per tick, in order. The behaviour changes of spec §4.4 apply in both switch states.
- Focused tests only: the files each task names plus every touched module's existing test files. Never whole suites, never `scripts/check_tests.sh`. Use `uv run pytest <files>`; NEVER `uv run --active`.
- C++: build with `cmake --build build -j`; never reconfigure cmake or change BUILD_TYPE; never run cmake inside `native/`. C++ tests: `ctest --test-dir build -R "combat_|EffectQueue"`. A new combat TU joins the `-ffp-contract=off` list (DM H8).
- Never launch the game binary; never benchmark without Mark.
- The banned git commands of CLAUDE.md "Shared checkout" apply. Stage explicit paths; `git commit -F <file> -- <paths>`; end messages with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Never write lifted or decompiled mod text; never commit a mod-derived value in a test; never spell `game` or `sdk` as a path segment in code.
- No red or xfail tests are committed. Mutation proofs: `cp` backup, mutate, run, `cp` restore, `diff` clean. No subagents.

## Review Focus

1. A hit on a ship that dies mid-tick and is hit again in the same tick: the second hit damages but begins no second death; one death (from its `ZERO_CROSS`), one `SPLASH`, in order after the first hit's entries.
2. A splash chain (a splash victim dies and splashes): every entry is delivered in the same flush, in emission order, and terminates (`_out_of_action`).
3. A handler at delivery that writes a flag (`SetHurtable(0)`, `SetInvincible`, a clamp): it takes effect for every hit after the flush, never retroactively, and the native arm reads it at the next step.
4. Shield faces written in place by any of the seven writers (DR §6) between two hits: the native arm sees the new charge (no stale mirror).
5. An invincible ship whose hull reaches 0: no death, no cascade, hull stays at 0; making it vulnerable later does not retro-kill it until the next condition write takes a critical subsystem to 0 (M3).

---

### Task 1: The new semantics in Python (M1, M3, M5, bug 2)

**Files:**
- `engine/appc/ships.py`: immunity. `SetHurtable(0)` = no damage; `SetInvincible` = cannot die.
- `engine/appc/combat.py`: gate on hurtable and on subsystem invincible only.
- `engine/appc/objects.py` and `engine/appc/subsystems.py`: one shared "critical at 0" path for `DamageSystem`, `SetCondition` and severance (R2).
- The M5 boundary check: a pending set drained at the effect-queue flush. Outside a tick it waits for the next flush. It re-reads invincibility, then runs zero crossings (R5) and the death.
- `SetConditionPercentage` on `ShipSubsystem` = fraction × `GetMaxCondition()` through `SetCondition`.
- `engine/appc/radiation.py`: same flags.
- `engine/dev_missions/vesuvi_dust_cloud.py`: R6.

Tests: new `tests/unit/test_damage_immunity_semantics.py`, `tests/unit/test_set_condition_percentage.py`, mission tests (spec §6) where the headless harness reaches them, plus the existing tests of each touched module.

- [ ] **Step 1: tests (RED).**
  - M1: a hurtable-0 ship takes nothing. An invincible ship takes damage and never dies at hull 0, and keeps its systems (R5). An invincible subsystem takes nothing.
  - M3 and M5: a critical subsystem at 0 kills at the flush, from `DamageSystem`, `SetCondition`, `SetConditionPercentage` or severance, unless the ship is invincible by the flush. A hull set to 0 then made invincible in the same call sequence survives. R4: no retroactive death.
  - Bug 2: `SetConditionPercentage` posts the same subsystem events as damage, and `MissionLib.SetConditionPercentage` walks children.
  - Missions:
    - E7M1/E7M2: a scripted hull 0 kills.
    - E3M5: GonDev survives creation.
    - E8M2: Matan takes damage and does not die while invincible.
    - E3M1: drill ships are knocked out at their thresholds and repaired; nobody dies; a collision damages the invincible player.
- [ ] **Step 2:** implement.
- [ ] **Step 3:** bug 2's headless pass over the 15 missions (decision text). For each, record whether the scripted effect lands, in the report.
- [ ] **Step 4:** run the new tests, every touched module's existing tests, and the six differential files → PASS. Update any test that pinned the old immunity meaning, keeping its purpose.
- [ ] **Step 5:** mutations: invincible blocks damage again → the M1 test fails; the death check runs inside the write → the GonDev test fails. Commit.

### Task 2: Hit effects queued (M2), Python reference

**Files:** `engine/appc/effect_queue.py` (kinds `COND_WATCH`, `SUBSYS_EVENT`, `REPAIR_ADD`, `ZERO_CROSS` (carries Task 1's boundary death check), `SPLASH`, `HIT_PRESENT`, `WEAPON_HIT`, spec §4.3; delivery for each; entries appended during delivery delivered in the same flush), `native/src/host/combat_effect_queue.{h,cc}` (the same kinds, so the native arm can append them in Task 3; the C++ enum order matches Python's), `engine/appc/combat.py`, `engine/appc/objects.py`, `engine/appc/subsystems.py`, `engine/appc/float_range_watcher.py` (condition watchers queue like an owned watcher), `engine/appc/ship_death.py` and `engine/rocks/death.py` (`SPLASH` appended after `ET_OBJECT_EXPLODING`; Task 1's pending death set becomes the ordered `ZERO_CROSS` entries), `engine/appc/hit_feedback.py` (dispatch from `HIT_PRESENT`, F7 included). Outside the tick scope, a caller's entries deliver at the end of its call (ruling F3). Tests: new `tests/unit/test_damage_effect_queue.py`, `tests/integration/test_damage_queue_order.py`, plus the existing effect-queue, hit-feedback, ship-death, collision and differential tests.

- [ ] **Step 1: tests (RED).**
  - Per-hit emission order equals today's synchronous order minus nesting.
  - Handlers run at the flush, not inside the hit: a handler sees every same-tick hit already applied.
  - Review Focus 1, 2, 3 and 5.
  - E2M2: the partner is made invincible before the splash and survives it.
  - E3M5: the clamp holds after two same-tick hits.
  - A collision outside the scope delivers its events right after its damage.
  - Decision 13 error handling on the new kinds.
- [ ] **Step 2:** implement.
- [ ] **Step 3:** run the new tests, the touched modules' tests and all six differential files → PASS. Fix coverage counts only where the branch still fires.
- [ ] **Step 4:** mutations: deliver `SPLASH` before `ET_OBJECT_EXPLODING` → the E2M2 test fails; post `ET_WEAPON_HIT` synchronously → the handler-timing test fails. Commit.

**Task review after this task** (spec compliance and quality), before Task 3.

### Task 3: The native hit, used by every non-kernel caller

**Files:** new `native/src/combat/{include/dauntless/combat,src}/damage.{h,cc}` (the hit and the condition chain, spec §4.2), `mirror.h` + push paths (spec §4.1), `native/src/host/host_bindings.cc` (a `combat_apply_hit` binding and the condition-chain entry points for Python callers), `engine/appc/native_combat.py` (mirror pushes at every writer, DR §6-§7; routing every caller of spec §3 goal 4 to the binding when the switch is on), `engine/appc/combat.py`, `objects.py`, `subsystems.py`; tests new `tests/integration/test_native_damage_differential.py` (the falsifier), `native/tests/combat/damage_test.cc`, plus the existing differentials.

**Interfaces (produced, used by Task 4):** a C++ entry `apply_hit(Mirror&, HitInput, Context&, WriteLog&, EffectQueue&)` (names are the implementer's; record them in the report) that the kernels can call without the GIL, and the queue entries of Task 2 appended natively in the same order as the Python reference.

- [ ] **Step 1: falsifier (RED).** `test_native_damage_differential.py` runs every non-kernel caller with the switch on and off. Callers: collisions, `AddDamage`, splash chains, scripted `SetCondition` / `SetConditionPercentage`, radiation, direct `apply_hit` calls. It compares the `.hex()` of every condition, face charge, ramp and `_dying`, plus the queued entries per tick, kind by kind, in order. Cover:
  - shielded, unshielded and bypass hits;
  - every ramp band;
  - god mode, double damage and NPC shields off;
  - hurtable, invincible and invincible subsystems;
    - zero and multiple overlaps, and ties for the primary subsystem;
  - deaths and a splash chain;
  - Review Focus 4, with all seven face writers between hits.
  
  It must fail on the first native arm.
- [ ] **Step 2:** implement the mirror fields and pushes.
- [ ] **Step 3:** implement `damage.cc` and the binding, and route the callers.
- [ ] **Step 4:** run the falsifier, `ctest -R "combat_|EffectQueue"` and all six differential files → PASS.
- [ ] **Step 5:** mutations: `std::sqrt` for `py_pow(x, 0.5)` → the differential fails; skip one face writer's push → Review Focus 4 fails. Commit.

### Task 4: K2 and K3 apply damage in-kernel

**Files:** `native/src/combat/src/k2_beams.cc` + header (the pulse applied in the walk via Task 3's entry; no CONTACT damage record; the pulse damage arithmetic `_phaser_damage_for_tick` × level and `damage_hull` native), `k3_projectiles.cc` + header (hits applied at `DONE`, in today's order), `native/src/host/host_bindings.cc`, `engine/appc/native_combat.py` (`run_k2` / `run_k3` without the damage hand-backs), `engine/host_loop.py` (the K3 hit loop only with the switch off); tests the K2, K3, step and falsifier differentials, the damage differential, `tests/unit/test_native_k2_dispatch.py`, `test_native_k3_dispatch.py`, `ctest -R combat_`.

- [ ] **Step 1: kernel guard (RED):** in the 64-ship fight with the switch on, K2 damage-pulse records = 0 and K3 hit hand-backs = 0, and the differentials still match.
- [ ] **Step 2:** implement.
- [ ] **Step 3:** run the listed files and ctest → PASS.
- [ ] **Step 4:** mutation: K2 hands a pulse back → the guard fails. Commit.

### Task 5: Measurement and documentation (controller)

- [ ] Headless counts with the switch on (the DR §9 command): records per tick by kind, hits, and the cost of `apply_hit` against DR §9.3. Run benchmarks of the game binary only if Mark agrees.
- [ ] Docs:
  - spec §10;
  - the roadmap: §2 table, decision 9 consequences, D done, I's remaining blockers;
  - `event-emitter-gaps.md`: the three never-posted subsystem events (DR §3.3);
  - the campaign bug decisions: bugs 2 and 3 built (that doc is on main; note it for the main merge);
  - CLAUDE.md, only if a row becomes wrong.
  
  Commit.
- [ ] Final whole-branch review (most capable model); one fix round.
