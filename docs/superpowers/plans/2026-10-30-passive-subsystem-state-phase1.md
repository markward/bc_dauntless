# Passive Subsystem State — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Weapon banks and torpedo tubes whose per-tick update would do nothing stop being stepped until something they depend on changes, and ships with no moving parts stop paying for articulation, with every value and event bit-identical to the per-tick model.

**Architecture:** A small `engine/appc/passive_state.py` owns the mode switch, the asleep flag, a write-watching descriptor (`WakeField`) and the sleep audit. `engine/appc/passive_weapons.py` replaces the body of `host_loop._advance_weapons` with a per-ship registry of weapons in today's walk order plus a sorted list of the awake ones. Articulation gets an exact per-ship "no rig" cache keyed on a generation counter.

**Tech Stack:** Python 3.11, pytest. No native code.

**Spec:** `docs/superpowers/specs/2026-10-30-passive-subsystem-state-design.md` (approved by Mark 2026-10-30). This plan is spec §8 phase 1 as narrowed in its §8 "Phase 1 scope" note: weapons and articulation only. Shields, cloak and repair cost ~4% of `gl.subsystems` and are not slept. Power is phase 2, with its own plan after this phase's measurement.

## Global Constraints

- Bit-exact contract (spec §2.3): every getter identical with `==`, every event on the same tick and in the same order. Never `pytest.approx` in a differential.
- No second copy of a rule (spec §4). `UpdateCharge` and `UpdateReload` are called exactly as today. The sleep test reads the same fields their early-outs read.
- `DAUNTLESS_PASSIVE_STATE=0` runs the old walk unchanged. Read in `GameLoop.__init__` via `passive_state.configure()`, never at import (spec §6.7).
- `DAUNTLESS_PASSIVE_AUDIT=1` turns the sleep audit on (spec §7). It is read in the same place.
- Focused tests only (CLAUDE.md "Test gate"). Never run whole suites or `scripts/check_tests.sh`. Never pass pytest an empty file list.
- Shared checkout rules (CLAUDE.md): no `git checkout --`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A/.`. Stage explicit paths. Commit with `git commit -F <file>`. Never commit to main.
- Worktree: `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-visibility`, branch `perf/passive-state`. Its `build/` is current. Phase 1 changes no native code, so no rebuild is needed.

## Review Focus

1. A mission script writes charge on a sleeping full bank (`Actions/ShipScriptActions.py:362` sets every bank to `GetMaxCharge()`). A same-value write wakes the bank harmlessly, and it sleeps again after one step. A drained-then-recharged bank recharges on the same ticks as the per-tick model. Tested in Task 2 (`test_script_recharge_all_matches_per_tick`).
2. A ship is rebuilt or a weapon system is replaced (mission swap, Quick Battle restore `engine/quickbattle/sim_restore.py`, `ShipClass.Set*System`, `AddChildSubsystem`). The registry rebuilds with everything awake, and no stale weapon is stepped. Tested in Task 2 (`test_replacing_a_system_rebuilds_the_registry`).
3. A weapon is woken BEFORE the weapons walk in a tick (AI fire during `GameLoop.tick`) or AFTER it (held-weapon pump during the combat step). The first is stepped in that tick's walk, the second from the next tick, exactly as the per-tick model behaves. Tested by the differential issuing ops at both points (Task 2).
4. A sleeping pulse weapon: cooldown and the `ET_CHARGE_TOGGLE` charge watcher (`Conditions/ConditionPulseReady.py`). The sleep test includes cooldown 0, and the audit snapshots the watcher. Tested in Task 2 (`test_pulse_weapon_sleeps_only_after_cooldown`).
5. An engaged tractor (holding a target) stays awake. On release it recharges, then sleeps. Tested in Task 2 (`test_tractor_sleeps_only_when_released_and_full`).

---

### Task 1: `passive_state` — switch, asleep flag, `WakeField`, audit

**Files:**
- Create: `engine/appc/passive_state.py`
- Modify: `engine/core/loop.py` (add `GameLoop.__init__(self) -> None` — it has none today — calling `passive_state.configure()`)
- Modify: `tests/conftest.py` (`_reset_leakable_engine_globals` calls `passive_state.reset()`)
- Test: `tests/unit/test_passive_state.py`

**Interfaces:**
- Produces:
  - `configure(environ: Mapping[str, str] = os.environ) -> None`. Enabled unless `DAUNTLESS_PASSIVE_STATE == "0"`; audit on iff `DAUNTLESS_PASSIVE_AUDIT == "1"`.
  - `enabled() -> bool`, `audit_enabled() -> bool`.
  - `reset() -> None`. Back to defaults (enabled, no audit), clears the audit record and counters.
  - `class WakeField`: a data descriptor with `__set__` and `__set_name__` but NO `__get__`. A write stores `obj.__dict__[name] = value`, then wakes `obj` if it is asleep. Reads therefore stay plain instance-dict reads.
  - `is_asleep(obj) -> bool` (`obj.__dict__.get("_passive_asleep", False)`).
  - `put_to_sleep(obj) -> None`. Sets the flag, then calls `obj._passive_on_sleep()` if it exists.
  - `wake(obj) -> None`. No-op unless asleep; otherwise clears the flag, then calls `obj._passive_on_wake()` if it exists.
  - `audit_step(obj, step: Callable[[], None]) -> None`. Snapshots `vars(obj)` (list/dict/set values copied one level, plus `vars()` of each attribute named in `obj._passive_audit_children`, a class attribute tuple defaulting to `()`). Then it runs `step()`, records every field that differs from the snapshot, and restores the snapshot IN PLACE: lists via slice-assign, dicts and sets via clear+update, so container identity is preserved.
  - `audit_failures() -> list[tuple[str, str]]` returns `(type name, field)` pairs. `counts() -> dict` returns `{"slept": int, "woke": int}`.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_passive_state.py`:
  - `test_configure_reads_the_switches`: `configure({})` → `enabled() and not audit_enabled()`. `configure({"DAUNTLESS_PASSIVE_STATE": "0", "DAUNTLESS_PASSIVE_AUDIT": "1"})` → `not enabled() and audit_enabled()`.
  - `test_wakefield_write_wakes_a_sleeper_and_reads_stay_plain`: on a class with `x = WakeField()` and `_passive_on_wake` recording calls: `o.x = 1` while awake calls nothing. After `put_to_sleep(o)`, `o.x = 1` (the SAME value) wakes it once (`not is_asleep(o)`, one wake call). `type(o).__dict__["x"]` has no `__get__` attribute, and `o.x == 1` comes from `o.__dict__`.
  - `test_audit_records_a_changing_step_and_restores_in_place`: `o.v = [1, 2]; keep = o.v`. `audit_step(o, lambda: o.v.append(3))` → `audit_failures() == [("Obj", "v")]`, `o.v == [1, 2]`, `o.v is keep`. A step that changes nothing records nothing.
  - `test_game_loop_configures_on_construction`: with `monkeypatch.setenv("DAUNTLESS_PASSIVE_STATE", "0")`, `GameLoop()` → `not enabled()`.
- [ ] **Step 2: Run them to see them fail.** `uv run pytest tests/unit/test_passive_state.py -q -p no:cacheprovider`. Expected: errors on `import engine.appc.passive_state`.
- [ ] **Step 3: Implement** `engine/appc/passive_state.py` to the Interfaces above. Module docstring: two sentences on why, pointing at the spec. Add `def __init__(self) -> None: passive_state.configure()` to `GameLoop` in `engine/core/loop.py`, and `passive_state.reset()` in `tests/conftest.py`'s `_reset_leakable_engine_globals`.
- [ ] **Step 4: Run them to see them pass.** Same command. Expected: 4 passed.
- [ ] **Step 5: Commit.** `git add engine/appc/passive_state.py engine/core/loop.py tests/conftest.py tests/unit/test_passive_state.py`, then `git commit -F <msg>` with `perf(passive): mode switch, asleep flag, write-watching field and sleep audit`.

---

### Task 2: Sleeping weapons

**Files:**
- Create: `engine/appc/passive_weapons.py`
- Modify: `engine/appc/weapon_subsystems.py`. `WakeField` class attributes and `_passive_at_rest()` on `_EnergyWeaponFireMixin` (`_charge_level`, `_firing`, `_max_charge`), `PulseWeapon` (`_cooldown_remaining`) and `TorpedoTube` (`_num_ready`, `_max_ready`). `_passive_on_wake` on both families delegating to `passive_weapons.on_wake(self)`. `PulseWeapon._passive_audit_children = ("_charge_watcher",)`.
- Modify: `engine/appc/ships.py:1039` (`_attach_subsystem` → `passive_weapons.invalidate(self)`).
- Modify: `engine/appc/subsystems.py:1116` (`AddChildSubsystem` → `passive_weapons.invalidate(ship)` when `self` reaches a ship; climb the same way `_climb_to_ship` does).
- Modify: `engine/host_loop.py` `_advance_weapons`: when `passive_state.enabled()`, call `passive_weapons.advance(ships, dt)` and return. Otherwise run the existing body unchanged.
- Test: `tests/unit/test_passive_weapons.py`, `tests/integration/test_passive_weapons_differential.py`

**Interfaces:**
- Consumes: Task 1's `WakeField`, `put_to_sleep`, `wake`, `is_asleep`, `audit_enabled`, `audit_step`.
- Produces:
  - `_EnergyWeaponFireMixin._passive_at_rest(self) -> bool`: `not self._firing and self._max_charge - self._charge_level <= 0.0`. That is exactly `UpdateCharge`'s idle early-out test.
  - `PulseWeapon._passive_at_rest`: the mixin's test `and self._cooldown_remaining <= 0.0`.
  - `TorpedoTube._passive_at_rest(self) -> bool`: `self._num_ready >= self._max_ready`. That is exactly `UpdateReload`'s first line.
  - `passive_weapons.invalidate(ship) -> None`: marks the ship's registry stale (`ship._passive_weapons = None`).
  - `passive_weapons.advance(ships, dt: float) -> None`. For each ship: get or build its registry, step each awake weapon in registry order (`UpdateReload(dt)` for `TorpedoTube`, `UpdateCharge(dt)` for `_EnergyWeaponFireMixin`, the same isinstance dispatch as today), and put it to sleep after its step if `_passive_at_rest()`. With the audit on, also `audit_step` each sleeping weapon with its update.
  - `passive_weapons.on_wake(weapon) -> None`: re-inserts the weapon's index into its ship's awake list, if its recorded registry is still the ship's current one.
  - Registry: `ship._passive_weapons` holds `entries: list[tuple[weapon, is_tube]]`, in today's order (systems `GetPhaserSystem, GetPulseWeaponSystem, GetTractorBeamSystem, GetTorpedoSystem`, then `GetWeapon(i)`), plus `awake: list[int]`, kept sorted with `bisect.insort`. Each weapon gets `weapon._passive_slot = (registry, index)`. A fresh registry starts with every entry awake and every weapon's asleep flag cleared.

- [ ] **Step 1: Write the failing unit tests** in `tests/unit/test_passive_weapons.py`. Load `engine.dev_missions.combat_stress` with `DAUNTLESS_COMBAT_SHIPS=4` through `tests.helpers.headless_mission.load`. Ships come from `engine.appc.ship_iter.iter_ships()`. Drive `host_loop._advance_weapons(ships, TICK_DELTA)` directly (`from engine.core.loop import TICK_DELTA`).
  - `test_a_full_idle_bank_is_not_stepped`: after one advance, every full idle bank `is_asleep`; spy `UpdateCharge` on the class and assert it is not called for those banks on the next advance.
  - `test_set_charge_level_wakes_a_sleeping_bank`: `SetChargeLevel(0.0)` → not asleep; the next advance steps it.
  - `test_fire_wakes_and_the_bank_drains`: `bank.Fire(target)` on a sleeping bank → awake; stepped while firing.
  - `test_a_launch_wakes_the_tube`: `DecNumReady()` and `SetNumReady(0)` each wake a sleeping tube.
  - `test_replacing_a_system_rebuilds_the_registry`: after an advance, `AddChildSubsystem` a new `PhaserBank` (charge 0) to the phaser system → the next advance steps it. `SetPhaserSystem(new_system)` → the old system's banks are never stepped again.
  - `test_pulse_weapon_sleeps_only_after_cooldown`: a full pulse weapon with `_cooldown_remaining > 0` stays awake until the cooldown reaches 0, then sleeps.
  - `test_tractor_sleeps_only_when_released_and_full`: an engaged (`_firing`) full tractor stays awake; after `StopFiring()` it sleeps.
  - `test_awake_weapons_step_in_todays_order`: record `(ship id, weapon id)` call order in both modes over one advance with mixed awake/asleep weapons. The passive order equals the per-tick order with the asleep weapons removed.
- [ ] **Step 2: Write the failing differential** `tests/integration/test_passive_weapons_differential.py::test_weapons_match_per_tick[seed-ticks_per_frame]`, with seeds `range(6)` × ticks per frame `(1, 6)`.
  - Two fresh loads of `combat_stress` (`DAUNTLESS_COMBAT_SHIPS=6`), one with `configure({"DAUNTLESS_PASSIVE_STATE": "0"})` and one passive with the audit on.
  - The same `random.Random(seed)` op stream per frame. Ops: `Fire` on a random bank at a random enemy, `StopFiring`, `SetChargeLevel(random fraction × max)`, the script recharge-all (`SetChargeLevel(GetMaxCharge())` on every bank), tube `Fire`/`DecNumReady`/`SetNumReady`, `SetCondition` on a weapon system or bank, `SetPowerPercentageWanted`, `TurnOff`/`TurnOn`.
  - Frame order like the host: ops; N × `engine.core.loop._update_ship_subsystems()` (no AI, so no unseeded randomness); more ops; N × `_advance_weapons(ships, TICK_DELTA)`.
  - Record per tick, for every weapon: `GetChargeLevel()`, `IsFiring()`, `_depleted`, `_cooldown_remaining` (pulse), `GetNumReady()` and `_reload_timers` (tubes). Also log `ET_TORPEDO_RELOAD`, `ET_WEAPON_FIRED` and `ET_CHARGE_TOGGLE` events (type, destination name, tick) by wrapping `App.g_kEventManager.AddEvent`.
  - Assert the two logs are `==`, the passive run's `passive_state.audit_failures() == []`, and `counts()["slept"] > 0 and counts()["woke"] > 0`.
  - Add `test_script_recharge_all_matches_per_tick`: same harness, seed fixed, only drain-then-recharge-all ops.
- [ ] **Step 3: Run both files to see them fail.** `uv run pytest tests/unit/test_passive_weapons.py tests/integration/test_passive_weapons_differential.py -q -p no:cacheprovider`. Expected: failures on missing `passive_weapons` and `_passive_at_rest`.
- [ ] **Step 4: Implement** to the Interfaces. `advance` iterates `list(registry.awake)`, so a wake during the walk cannot disturb the loop. `_passive_on_sleep` removes the index from `awake`. Keep `_advance_weapons`' existing docstring and add one paragraph pointing at `passive_weapons`.
- [ ] **Step 5: Run them to see them pass.** Same command. Expected: all pass.
- [ ] **Step 6: Run the focused neighbours.** Use `grep -rl -e "UpdateCharge" -e "UpdateReload" -e "_advance_weapons" -e "SetChargeLevel" -e "NumReady" -e "AddChildSubsystem" -e "_attach_subsystem" tests | grep -v -e conftest.py -e /helpers/ | sort -u > $SP/pw_tests.txt`, check the list is non-empty, then `uv run pytest $(cat $SP/pw_tests.txt) tests/host/test_frame_rate_independence.py -q -p no:cacheprovider`. Expected: no failures. If a test passes alone but fails in the batch, apply the "Check whether a failure is pre-existing" rule below before changing anything.
- [ ] **Step 7: Commit** the files above with `perf(passive): full idle weapons and loaded tubes sleep until a watched field changes`.

---

### Task 3: Articulation skips ships with no rig, exactly

**Files:**
- Modify: `engine/appc/articulated_part.py` (module `_GENERATION: int`, bumped in `snapshot_for_leaf` and `reset`; `generation() -> int`).
- Modify: `engine/appc/articulation.py` `tick_ship`. At the top: `key = (leaf_for(ship), articulated_part.generation())`. If `ship.__dict__.get("_rigless_key") == key`, return. After `rig_for` returns `()`, store `ship._rigless_key = key`, guarded like `leaf_for`'s own cache write so test doubles that reject attributes still work.
- Test: `tests/unit/test_articulation_rigless_cache.py`

**Interfaces:**
- Produces: `articulated_part.generation() -> int`.

- [ ] **Step 1: Write the failing tests:**
  - `test_an_unrigged_ship_looks_up_its_rig_once`: spy `articulated_part.parts_for_leaf`; two `tick_ship` calls → one lookup.
  - `test_a_new_snapshot_for_any_leaf_is_seen`: after the cached tick, `snapshot_for_leaf` for the ship's leaf (use the rig fixture pattern from `tests/unit/test_articulation.py`) → the next `tick_ship` looks up again and creates `_articulation_poses`.
  - `test_reset_is_seen`: `articulated_part.reset()` bumps `generation()`.
- [ ] **Step 2: Run to see them fail.** `uv run pytest tests/unit/test_articulation_rigless_cache.py -q -p no:cacheprovider`.
- [ ] **Step 3: Implement** as described in Files.
- [ ] **Step 4: Run them plus the articulation tests.** `uv run pytest tests/unit/test_articulation_rigless_cache.py $(ls tests/unit/test_articulation*.py) -q -p no:cacheprovider`. Expected: all pass.
- [ ] **Step 5: Commit** with `perf(articulation): a ship with no rig skips the lookup until the snapshots change`.

---

### Task 4: Whole-scene audit run, docs

**Files:**
- Test: `tests/host/test_passive_state_scene_audit.py`
- Modify: `CLAUDE.md` (one row in "Key reference material", after the "Perf cadences" row).
- Modify: `docs/superpowers/specs/2026-10-30-passive-subsystem-state-design.md` (§8 "Phase 1 scope" note: mark Tasks 1-3 landed).

**Interfaces:**
- Consumes: `passive_state.audit_failures()`, `counts()`; the `_frame_clock` seam (`tests/host/test_frame_rate_independence.py` shows how to drive `host_loop.run` with a fake clock).

- [ ] **Step 1: Write** `test_combat_stress_runs_clean_under_the_audit`. Set `DAUNTLESS_COMBAT_SHIPS=16`, `DAUNTLESS_PASSIVE_AUDIT=1`, `OPEN_STBC_HOST_HEADLESS=1`. Patch the fake frame clock to 0.1 s per frame (6 ticks). Run `host_loop.run("engine.dev_missions.combat_stress", max_ticks=120)`. Assert the return code is 0, `audit_failures() == []`, `counts()["slept"] > 0` and `counts()["woke"] > 0`. Skip like `test_frame_rate_independence.py` when BC assets are absent.
- [ ] **Step 2: Run it.** `uv run pytest tests/host/test_passive_state_scene_audit.py tests/host/test_frame_rate_independence.py -q -p no:cacheprovider`. Expected: pass. A failure here names the class and field of a missed wake: go back to Task 2's watched fields, add the wake, and add a unit test for that path in Task 2's test file.
- [ ] **Step 3: Add the CLAUDE.md row.** Columns: `Passive subsystem state — sleeping weapons`; files `engine/appc/passive_state.py`, `engine/appc/passive_weapons.py`, the spec. Content, one dense cell like its neighbours:
  - full idle banks and loaded tubes leave the per-tick walk;
  - a write to a `WakeField` wakes them;
  - registry rebuilt on `_attach_subsystem` / `AddChildSubsystem`;
  - ⚠️ a new field read by `UpdateCharge`'s or `UpdateReload`'s early-out must become a `WakeField`;
  - `DAUNTLESS_PASSIVE_STATE=0` is the old path, `DAUNTLESS_PASSIVE_AUDIT=1` the audit;
  - power is phase 2.
- [ ] **Step 4: Commit** with `test(passive): combat_stress runs clean under the sleep audit; docs`.

---

### Task 5: Measure

- [ ] **Step 1: Make sure nothing else is running** (`ps -Ao pid,pcpu,comm -r | head -5`). No test runs may overlap the capture.
- [ ] **Step 2: Capture.** From the worktree, run `TS=$(date +%Y%m%d-%H%M) && OPEN_STBC_HOST_HEADLESS=1 DAUNTLESS_WINDOW_SIZE=1280x720 DAUNTLESS_MISSION=engine.dev_missions.combat_stress DAUNTLESS_COMBAT_SHIPS=64 DAUNTLESS_DEV_VIEW=bridge DAUNTLESS_PROFILE_FRAMES=1500 caffeinate -i ./build/dauntless --developer > ~/Documents/dauntless-perf/passive1-cs64-bridge-$TS.log 2>&1`.
- [ ] **Step 3: Compare** against `~/Documents/dauntless-perf/mounts-cs64-bridge-20261030-1153.log`. Use the median of reports 3–11 of `sim.weapons`, `gl.subsystems` and `sim.combat` per game tick (value ÷ calls), and frame ms. Expected direction: `sim.weapons` well below 0.62 ms, `gl.subsystems` down by the articulation share. Write the numbers into the spec's §8 note.
- [ ] **Step 4: Commit** the spec update with `docs(spec): passive state phase 1 measured`.

---

## Check whether a failure is pre-existing

A test that passes alone but fails in a batch may be pre-existing order sensitivity. `test_shuttle_service.py::test_neighbouring_docks_keep_their_shuttles_apart` fails on unchanged main whenever `engine.host_loop` was imported earlier in the run. To decide whether this branch caused a failure:
1. Back up the changed source files with `cp`.
2. Copy main's versions in with `git show main:<path> > <path>`.
3. Run the same batch.
4. Copy the backups back and `diff` them to confirm the restore.

Never decide by eye.
