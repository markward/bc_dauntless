# Weapon events and sounds through the boundary queue — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Weapon events and weapon sounds go through one ordered queue delivered at the tick boundary, so K0, K1 and K2 stop handing records back to Python for them; plus the `ET_WEAPON_FIRED` target-pointer and pulse-weapon fix.

**Architecture:** A native ordered effect queue in the host layer takes entries from kernels (mirror handles) and from Python (object references) in one emission order. `host_loop` opens a deferral scope around each sim tick's weapons and combat steps and flushes it at the end. Producers append while the scope is open and act at once otherwise. The kernels turn the converted records into logged writes plus queue entries.

**Tech Stack:** C++17 combat library and pybind11 host bindings, Python 3.11 engine, gtest, pytest.

**Spec:** `docs/superpowers/specs/2026-11-02-combat-fire-events-design.md` (read it first; §n below means that spec).

## Global Constraints

- Worktree `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/native-combat-k3`, branch `ws/combat-fire-events`. Run everything from there.
- Switch `DAUNTLESS_NATIVE_COMBAT=1`, default OFF. Switch off: no scope ever opens, every producer acts at once, byte-identical except the Task 1 bug fix.
- Game state bit-exact with the Python reference, switch on (floats by `.hex()`, writes, damage, deaths, non-queued events in order). The queued kinds (§4.2) compare per tick as an ordered list among themselves.
- Focused tests only: the files each task names. Never whole suites, never `scripts/check_tests.sh`.
- Banned git: `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage explicit paths; `git commit -F <file>`; end messages with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Build: `cmake --build build -j`. Never reconfigure cmake, never change BUILD_TYPE, never run cmake inside `native/`. C++ tests: `ctest --test-dir build -R combat_` (cases are named `combat_K0.*`, `combat_K1.*`, `combat_K2.*`).
- Never launch the game. Never spell `game` or `sdk` as a path segment in code. SDK scripts (read-only) are under `/Users/mward/Documents/Star Trek Bridge Commander/sdk/Build/scripts`.
- Mutation proofs: `cp` backup, mutate, run, `cp` restore, `diff` clean.
- No subagents.

## Review Focus

1. A bank fired by a kernel and stopped from Python in the same tick (a K2 Python record, a death): its loop must start, then stop, at delivery; never be left playing.
2. A tube launch inside the scope: `ET_TORPEDO_FIRED`, `ET_WEAPON_FIRED`, `ET_TORPEDO_AMMO_CONSUMED` delivered in that order, the torpedo object alive at delivery.
3. A K1 system session started by AI outside the scope (`gl.ai`): its entries are delivered when the session ends, not held to the next tick and not lost.
4. An exception in one entry's delivery: the rest still delivered; logged in play, re-raised after the flush under tests/`--developer`; the queue empty afterwards.
5. An abandoned kernel session: the entries it appended stay and are delivered (ruling F5, which replaced "are dropped" during the build: every queued entry belongs to an effect already applied).

---

### Task 1: `ET_WEAPON_FIRED` carries its target; pulse weapons post it

**Files:**
- Modify: `engine/appc/weapon_subsystems.py` (`_post_weapon_fired(weapon, target)`, its callers, `PulseWeapon._fire_effect`)
- Modify: `docs/reference/engine/event-emitter-gaps.md` (#14 → done, summary row)
- Test: `tests/unit/test_weapon_fired_event.py` (create), `tests/integration/test_weapon_fired_mission_handlers.py` (create)

**Interfaces:**
- Produces: `_post_weapon_fired(weapon, target) -> None`: source = weapon, destination = `weapon._climb_to_ship()`, object pointer = `target` (`evt.SetObjPtr(target)`; check `engine/appc/events.py` for the setter name and add it to `TGEvent` if missing). Task 2 routes this function through the queue.

- [ ] **Step 1:** Write tests: a phaser bank's first fire posts `ET_WEAPON_FIRED` whose `GetObjPtr()` is the target ship; a tube launch's does too (and keeps TORPEDO_FIRED → WEAPON_FIRED → AMMO_CONSUMED); a pulse shot posts one per shot with the target; a tractor posts none. Headless mission tests: E1M2's `WeaponFired` (`Maelstrom/Episode1/E1M2/E1M2.py:1384`) advances `g_iNumberTimesWeaponFired` when the player fires at a ship after `g_bHavenSecondHail`; E2M1's `WeaponFired` (`E2M1.py:963`) gets past `pTargetShip` (spy the next call it makes). Run → FAIL.
- [ ] **Step 2:** Implement. Pulse posts from `PulseWeapon._fire_effect` after the shot is spawned.
- [ ] **Step 3:** Run the new files plus `tests/unit/test_native_k1_dispatch.py`, `tests/integration/test_native_k1_differential.py` → PASS (the reference arm carries the fix too).
- [ ] **Step 4:** Mutation: drop `SetObjPtr` → the mission tests fail. Restore, `diff`.
- [ ] **Step 5:** Update event-emitter-gaps #14 to DONE with the emitter; commit.

### Task 2: The effect queue, its scope, and every Python producer

**Files:**
- Create: `native/src/host/combat_effect_queue.{h,cc}` (the queue), `engine/appc/effect_queue.py` (Python API, delivery, decision 13)
- Modify: `native/src/host/host_bindings.cc` (bindings), `native/src/host/CMakeLists.txt` or the target that builds `combat_write_apply.cc` (add the new file), `engine/appc/weapon_subsystems.py` (producers), `engine/appc/float_range_watcher.py` (watcher), `engine/host_loop.py` (scope around `sim.weapons` + `sim.combat`), `engine/appc/native_combat.py` (`reset()` clears the queue)
- Test: `tests/unit/test_effect_queue.py` (create), `tests/unit/test_native_k0_dispatch.py`, `tests/unit/test_native_k1_dispatch.py`, `tests/unit/test_native_k2_dispatch.py`, the differentials (`tests/integration/test_native_k0_differential.py`, `test_native_k1_differential.py`, `test_native_combat_step_differential.py`, `test_native_k3_differential.py`, `tests/host/test_native_k2_differential.py`), `tests/helpers/k3_fight.py`

**Interfaces:**
- Produces (Python, `engine/appc/effect_queue.py`): `deferring() -> bool`; `scope()` context manager (opens; on exit flushes; nestable: only the outermost exit flushes); `post(kind: int, *operands)` (append; caller checked `deferring()`); `flush() -> None`; kinds `FIRE_SOUND, LOOP_STOP, WEAPON_FIRED, WEAPON_FIRE_FAILED, TORPEDO_FIRED, AMMO_CONSUMED, TORPEDO_RELOAD, WATCH`; `counts() -> dict` (`delivered`, `skipped_gone`, `failed`).
- Produces (native): `combat_effect_queue::append_native(kind, handles...)` for kernels (Tasks 3-4) and `mark()`/`truncate(mark)` for a kernel's abandon; bindings `combat_effect_post(kind, *objs)`, `combat_effect_take() -> list` (entries in order, handles or objects), `combat_effect_mark()`, `combat_effect_truncate(mark)`.
- Producers routed (each: `if effect_queue.deferring(): post(...)` else today's code): `_EnergyWeaponFireMixin._fire_effect`'s `_play_fire_sfx` call (`FIRE_SOUND`), `_EnergyWeaponFireMixin.StopFiring`'s loop stop (`LOOP_STOP`), `_post_weapon_fired` (`WEAPON_FIRED`), `_broadcast_weapon_fire_failed`, the tube launch's `ET_TORPEDO_FIRED` and `_broadcast_ammo_consumed_if_player`, `_broadcast_reload`, `FloatRangeWatcher._update` (commit `_value` at once, post `WATCH(watcher, old, new)`; delivery fires the crossed checks).

- [ ] **Step 1:** `tests/unit/test_effect_queue.py`: order across native and Python appends; outside the scope producers act at once; nested scope flushes once; freed handle skipped and counted; decision 13 (play: logged, continues; `--developer`/tests: delivers the rest then raises the first, later ones as notes); `truncate(mark)` drops only later entries; switch off never opens the scope (host_loop). Dispatch tests: Review Focus 1, 2, 4. Run → FAIL.
- [ ] **Step 2:** Implement the native queue, bindings, Python module, producers, watcher, scope in `host_loop` (switch on only), `reset()`.
- [ ] **Step 3:** Differentials: in `tests/helpers/k3_fight.py` (and the K0/K2 differentials' own event spies), events of the queued kinds go to a per-tick ordered list compared on its own; they leave the ordered event log. Sounds are spied at `_play_fire_sfx` and the loop stop. Run the files listed → PASS, every branch tally still firing.
- [ ] **Step 4:** Mutations: deliver in reverse; let one producer act directly inside the scope. Each fails a test. Restore, `diff`.
- [ ] **Step 5:** Commit.

### Task 3: K1 stops returning records for beam starts, cannot-fire and firing stops

**Files:**
- Modify: `native/src/combat/include/dauntless/combat/k1_fire_control.h` (contract), `native/src/combat/src/k1_fire_control.cc`, `native/src/host/host_bindings.cc`, `engine/appc/native_combat.py` (`run_k1`: the converted kinds go; a kernel abandon truncates to the session's mark)
- Test: `native/tests/combat/k1_fire_control_test.cc`, `tests/unit/test_native_k1_dispatch.py`, `tests/integration/test_native_k1_differential.py`, `tests/integration/test_native_combat_step_differential.py`

**Interfaces:**
- Consumes: Task 2's `append_native`, `mark`/`truncate`, kinds.
- Produces: K1 returns `FIRE` only for TorpedoTube/PulseWeapon, plus `FIRE_DUMB`, `ASK`, `RUN_PYTHON`, handed-back `WALK_START`, `DONE`. Beam edge = logged writes (`_firing`, `_target`, `_target_offset`, `_beam_on_countdown` = `BEAM_ON_DELAY_S` sent from Python, `_dwell` = 0.0) + `FIRE_SOUND(bank)` + `WEAPON_FIRED(bank, target)`; `FIRE_FAILED` → `WEAPON_FIRE_FAILED(tube)`; firing `BANK_STOP`/`STOP_SYSTEM` → logged writes + `LOOP_STOP(bank)` per firing energy bank.

- [ ] **Step 1:** C++ tests per conversion (writes in order, entries in walk order, remaining records unchanged, abandon truncates). Dispatch tests: Review Focus 3 (a K1 system session outside the scope delivers at its end). Run → FAIL.
- [ ] **Step 2:** Implement; update the header's RECORDS contract.
- [ ] **Step 3:** Run the C++ and the listed Python files → PASS; the K1 differential's tallies must show beam edges and FIRE_FAILED now produced natively (count entries, not records).
- [ ] **Step 4:** Mutation: drop the `FIRE_SOUND` entry; emit `WEAPON_FIRED` before the writes. Each fails. Restore, `diff`.
- [ ] **Step 5:** Commit.

### Task 4: K0 and K2 stop returning records for stops, reloads and watcher crossings

**Files:**
- Modify: `native/src/combat/include/dauntless/combat/k0_charging.h`, `native/src/combat/src/k0_charging.cc`, `native/src/combat/include/dauntless/combat/k2_beams.h`, `native/src/combat/src/k2_beams.cc`, `native/src/host/host_bindings.cc`, `engine/appc/native_combat.py` (`run_k0`, `run_k2`)
- Test: `native/tests/combat/k0_charging_test.cc`, `native/tests/combat/k2_beams_test.cc`, `tests/unit/test_native_k0_dispatch.py`, `tests/unit/test_native_k2_dispatch.py`, `tests/integration/test_native_k0_differential.py`, `tests/host/test_native_k2_differential.py`

**Interfaces:**
- Consumes: Task 2's queue API.
- Produces: K0 returns only `RUN_PYTHON` and `DONE` (`DEPLETE_STOP` → logged writes + `LOOP_STOP`; `RELOADED` → logged writes + `TORPEDO_RELOAD(tube)`; `WATCH` → the watcher's committed `_value` as a logged write + `WATCH(watcher, old, new)`). K2's firing `BANK_STOP`/`SYSTEM_STOP` → logged writes + `LOOP_STOP` per firing energy bank.

- [ ] **Step 1:** C++ and dispatch tests per conversion; a watcher crossing delivered at the boundary with the committed value (ruling E3). Run → FAIL.
- [ ] **Step 2:** Implement; update both headers' contracts.
- [ ] **Step 3:** Run the listed files → PASS.
- [ ] **Step 4:** Mutation: drop `TORPEDO_RELOAD`; skip the watcher commit. Each fails. Restore, `diff`.
- [ ] **Step 5:** Commit.

### Task 5: Measurement and documentation (controller)

- [ ] Records per tick by kind (spec §1 table), two benchmark runs against the `eq-*` logs, perf register C-266/C-267 and a signal, spec §10, roadmap (§2 table and G), event-inventory §4 (what still runs mid-walk), `remaining-fallbacks-map.md` note. Commit.
