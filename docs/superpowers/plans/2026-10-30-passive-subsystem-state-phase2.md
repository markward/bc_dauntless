# Passive Subsystem State — Phase 2 (Power) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The power plant stops re-running every consumer's `_update_power` each tick when nothing that decides its demand has changed. It performs only the draws, and every value and event stays bit-identical to the per-tick model.

**Architecture:** After a full per-tick pump, the plant builds a **draw program** for its ship: one op per consumer that draws, in attach order. A consumer whose demand inputs are watched and whose draw was met in full is **frozen**. Its four output fields are left as they are, and the program only repeats its `_draw(wanted, mode)` call. Any other consumer stays a **call op** and runs its own `_update_power`. A write to any watched field of a frozen consumer (`FrozenField`) **thaws** it and drops the program, so the next tick takes the full path. A draw that comes back short writes the consumer's fields through the same helper `_update_power` uses. That write thaws it. Two exact, unrelated per-tick costs go too: battery-limit reads build a closure per call, and watchers with no checks still do the full crossing work.

**Tech Stack:** Python 3.11, pytest. No native code.

**Spec:** `docs/superpowers/specs/2026-10-30-passive-subsystem-state-design.md` (approved by Mark 2026-10-30). This plan is spec §8 phase 2, as amended by the §8 "Phase 2 as planned" note. That note replaces §6.4's deferral-and-replay and §6.5's tick queue with the draw program, and explains why.

## Global Constraints

- **Bit-exact contract (spec §2.3).** Every getter is identical with `==` (floats by bit pattern), and every event fires on the same tick in the same order. Never use `pytest.approx` in a differential.
- **No second copy of a rule (spec §4).** Draws go through `PowerSubsystem._draw` / `StealPower`, as today. The post-draw field writes go through one helper, `PoweredSubsystem._record_draw`, which `_update_power` also uses. The wanted-total sum goes through one helper, `PowerSubsystem._sum_wanted`, which `_pump_consumers` also uses. Battery-limit reads go through one property lookup, `TGModelProperty._field_value`, which the generated getter also uses.
- **The switch.** `DAUNTLESS_PASSIVE_STATE=0` runs `_pump_consumers` exactly as today, and `DAUNTLESS_PASSIVE_AUDIT=1` turns the audit on. Read them through `passive_state.enabled()` / `audit_enabled()` (configured in `GameLoop.__init__`). Never read the environment at import.
- **Focused tests only** (CLAUDE.md "Test gate"). Never run whole suites or `scripts/check_tests.sh`, and never pass pytest an empty file list.
- **Shared checkout rules** (CLAUDE.md):
  - never run `git checkout --`, `git restore`, `git stash`, `git clean`, `git reset --hard` or `git add -A/.`;
  - stage explicit paths and commit with `git commit -F <file>`;
  - never commit to main.
- **Worktree:** `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-visibility`, branch `perf/passive-power` (off main `6d31e577b`). Its `build/` is current, and no native code changes.

## Review Focus

1. **A battery runs dry during a program tick.** A partial draw is recorded exactly as `_update_power` would record it. Later consumers in the same tick draw from what is left, and the next tick is a full pump. Tested in Task 1 (`test_shortfall_mid_program_matches_per_tick`).
2. **The player moves a power slider, or a script calls `TurnOff` / `SetPowerWanted`, between two ticks.** A read before the next tick sees the rescaled `_power_wanted`, as today, and the next tick re-derives demand. Tested in Task 1 (differential ops `slider`, `turn_off`, `set_power_wanted`).
3. **A cloaking ship drains its reserve while other consumers draw backup-first.** The cloak's own `_update_power` stays a call op in attach order, so the order of backup draws is unchanged. Tested in Task 1 (differential with a `CloakingSubsystem` consumer).
4. **A tractor engages and releases.** Releasing freezes the idle tractor, and the next `_firing` write on any beam thaws it in time for that tick. Tested in Task 2.
5. **A ship's plant or consumer list changes** (`SetPowerSubsystem`, `AddPoweredConsumer`, `AddChildSubsystem`, a Quick Battle restore rebuilding the ship). The stale program is dropped, and no consumer is drawn for twice or skipped. Tested in Task 1 (`test_consumer_added_drops_the_program`, `test_replaced_plant_starts_full`).

---

### Task 1: Draw program with frozen consumers

**Files:**
- Create: `engine/appc/passive_power.py`
- Modify: `engine/appc/subsystems.py`:
  - `PoweredSubsystem`: `FrozenField` class attributes, `_POWER_FREEZABLE = True`, `_record_draw`, `_passive_power_thaw`;
  - `CloakingSubsystem`: `_POWER_FREEZABLE = False`;
  - `PowerSubsystem`: `_sum_wanted`, and `Update`'s pump call;
  - `AddChildSubsystem`: invalidate.
- Modify: `engine/appc/ships.py` (`_attach_subsystem` calls `passive_power.invalidate(self)`)
- Modify: `engine/appc/passive_state.py` (add `audit_compare`)
- Modify: `tests/conftest.py` (`_reset_leakable_engine_globals` calls `passive_power.reset()`)
- Test: `tests/unit/test_passive_power.py`, `tests/integration/test_passive_power_differential.py`

**Interfaces:**
- Consumes (phase 1, `engine/appc/passive_state.py`):
  - `enabled()`, `audit_enabled()`;
  - the private helpers `_snapshot(d)`, `_restore(d, snap)`, `_diff(d, snap)`;
  - the failures list `_failures` (read by `audit_failures()`).
- Produces (`engine/appc/passive_power.py`):
  - `class FrozenField`: a data descriptor with only `__set_name__` and `__set__`, shaped like `passive_state.WakeField`. On write it stores into `obj.__dict__`, then calls `obj._passive_power_thaw()` if `obj.__dict__.get("_power_frozen")`.
  - `pump(plant, dt: float) -> None`: replaces `plant._pump_consumers(dt)` when passive is enabled.
  - `invalidate(ship) -> None`: drops the program of the ship's current plant (`ship.GetPowerSubsystem()`). It tolerates `None`, doubles, and ships with no plant.
  - `thaw(consumer) -> None`: clears `_power_frozen` and invalidates the consumer's ship. `PoweredSubsystem._passive_power_thaw` calls it.
  - `counts() -> dict` with keys `"program_ticks"`, `"full_ticks"`, `"frozen"`, `"thawed"`, and `reset() -> None`.
- Produces (`engine/appc/subsystems.py`):
  - `PoweredSubsystem._record_draw(self, wanted: float, received: float, base: float) -> None` writes `_power_wanted`, `_power_received`, `_efficiency`, `_power_factor` exactly as the conduit branch of `_update_power` does today. That branch now calls it.
  - `PowerSubsystem._sum_wanted(self, consumers) -> float` is today's total loop, including the `_BASE_GET_POWER_WANTED` guard, moved out of `_pump_consumers`, which now calls it.
  - Class attribute `_POWER_FREEZABLE`: True on `PoweredSubsystem`, False on `CloakingSubsystem`.
- Produces (`engine/appc/passive_state.py`): `audit_compare(objs, reference: Callable[[], None], step: Callable[[], None]) -> None` works as follows:
  1. snapshot `vars(o)` for each object;
  2. run `reference` and capture the after-state;
  3. restore the snapshots;
  4. run `step`;
  5. append `(type name, field)` to the failures for every field whose value differs from the reference after-state (same scalar rules as `_diff`).

  It leaves the state `step` produced.

**The program.** `pump` builds and runs it:
- **Program location.** It lives in `plant.__dict__["_passive_power"]`, so the audit's snapshot of the plant covers it. It is keyed by `dt` (exact float) and `len(consumers)`, and a mismatch means a full pump.
- **No program yet:** run `plant._pump_consumers(dt)`, count `full_ticks`, then build. Walk the consumers in attach order and classify each one:
  - Not freezable (`type(c)._POWER_FREEZABLE` is false): **call op**.
  - Freezable but not wanting power, or a free consumer (`_normal_power * dt <= 0`): no op. Freeze it.
  - Freezable, wanting power, and `DRAWS_DIRECT_FROM_MAIN`: **call op**.
  - Freezable, wanting power, with `_power_received == _power_wanted`: **draw op** `(c, wanted, mode, base)` with `wanted = c._power_wanted`, `mode = c.POWER_MODE` and `base = c._normal_power * dt`. Freeze it.
  - Anything else (an unmet draw): **call op**.

  Freezing sets `c.__dict__["_power_frozen"] = True`. If there are no call ops, the program also stores `total = plant._sum_wanted(consumers)`.
- **Program present:** for each op in order:
  - draw op: `got = plant._draw(wanted, mode)`, then `if got != wanted: c._record_draw(wanted, got, base)`;
  - call op: `c._update_power(dt, plant)`.

  Then set `plant._power_wanted_total` to the stored total, or to `plant._sum_wanted(consumers)` when there are call ops. Count `program_ticks`. Hold the program in a local while it runs, because a thaw during the run drops it from the plant.
- **Audit mode:** run the program tick as `passive_state.audit_compare([plant, *consumers], lambda: plant._pump_consumers(dt), <the program run>)`.
- **`PowerSubsystem.Update`:** replace `self._pump_consumers(dt)` with `passive_power.pump(self, dt)` when `passive_state.enabled()`, else the existing call. `_pump_consumers` returns early on no ship or empty consumers. `pump` returns early the same way, before any program work.
- **`FrozenField` on `PoweredSubsystem`**, for the inputs and outputs of the base `_update_power`: `_is_on`, `_normal_power`, `_power_percentage_wanted`, `_power_wanted`, `_power_received`, `_efficiency`, `_power_factor`.

- [ ] **Step 1: Write the failing unit tests** in `tests/unit/test_passive_power.py`. Build a ship by hand (`ShipClass`, a `PowerSubsystem` with a `PowerProperty` carrying `MainBatteryLimit`, `BackupBatteryLimit`, `PowerOutput`, `MainConduitCapacity` and `BackupConduitCapacity`), plus three `SensorSubsystem` / `ShieldSubsystem` / `ImpulseEngineSubsystem` consumers attached through the `Set*` methods and turned on. Call `passive_state.configure({})` first. Drive `plant.Update(TICK_DELTA)` (`from engine.core.loop import TICK_DELTA`). Tests:
  - `test_steady_ship_runs_the_program`: after 3 ticks, `counts()["full_ticks"] == 1` and `counts()["program_ticks"] == 2`, and each consumer has `__dict__["_power_frozen"] is True`.
  - `test_write_thaws_and_next_tick_is_full`: after 3 ticks, `sensor.TurnOff()` sets `"_power_frozen"` to False and the plant's `_passive_power` to None. The next tick raises `full_ticks` by 1.
  - `test_record_draw_matches_update_power`: call `c._update_power(TICK_DELTA, plant)` on a starved plant (main battery 0.0, backup battery 0.0). Then on an identical fresh consumer call `c2._record_draw(wanted, plant2._draw(wanted, c2.POWER_MODE), base)`. The four fields compare equal by `float.hex`.
  - `test_shortfall_mid_program_matches_per_tick`: two identical hand-built ships, one with `configure({"DAUNTLESS_PASSIVE_STATE": "0"})`. On each one, set the main battery to just above one tick's total demand after the first tick. Step 5 ticks, then compare every consumer's `GetPowerWanted/GetPowerReceived/GetPowerPercentage/GetNormalPowerPercentage` and the plant's `GetMainBatteryPower/GetBackupBatteryPower/GetPowerDispensed/GetPowerWanted/GetAvailablePower` with `float.hex` equality each tick. Switch modes with `passive_state.configure` before each ship's step.
  - `test_consumer_added_drops_the_program`: after 3 ticks, `ship.AddPoweredConsumer(new_consumer)` makes the plant's `_passive_power` None.
  - `test_replaced_plant_starts_full`: after 3 ticks, `ship.SetPowerSubsystem(fresh_plant)` means `fresh_plant.Update` is a full tick, and every value equals the per-tick model.
  - `test_cloak_is_a_call_op`: a ship with a `CloakingSubsystem` consumer. It is never frozen, its `_update_power` runs every program tick, and `_backup_reserve` equals the per-tick model's each tick.
  - `test_switch_off_never_builds`: with `configure({"DAUNTLESS_PASSIVE_STATE": "0"})`, after 3 ticks, `counts()["program_ticks"] == 0` and no consumer is frozen.
  - `test_audit_compare_reports_a_difference`: `audit_compare([obj], ref, step)` with a step that writes a different float than `ref` records `(type name, field)`; with equal writes it records nothing.
- [ ] **Step 2: Run them and watch them fail.** Run `uv run pytest tests/unit/test_passive_power.py -q`. Expected: ImportError or AttributeError (no `passive_power`, no `_record_draw`).
- [ ] **Step 3: Implement** everything listed under Files / Interfaces and *The program*. Extract `_record_draw` and `_sum_wanted` by moving today's code, not rewriting it. In `ShipClass._attach_subsystem` and `ShipSubsystem.AddChildSubsystem`, call `passive_power.invalidate(ship)` next to the existing `passive_weapons.invalidate`. In `tests/conftest.py`, call `passive_power.reset()` beside `passive_state.reset()`.
- [ ] **Step 4: Run the unit tests and see them pass.** Run `uv run pytest tests/unit/test_passive_power.py tests/unit/test_passive_state.py -q`.
- [ ] **Step 5: Write the differential** `tests/integration/test_passive_power_differential.py`:
  - Load two fresh `combat_stress` scenes (`DAUNTLESS_COMBAT_SHIPS=6`) through `tests.helpers.headless_mission.load`, as `tests/integration/test_passive_weapons_differential.py` does: one with `configure({"DAUNTLESS_PASSIVE_STATE": "0"})`, and one passive with the audit on.
  - Drive 600 ticks of `_update_ship_subsystems()` (`engine.core.loop`). Before the walk on seeded ticks (`random.Random(20261030)`, the same draws for both scenes), apply one op to the same ship by index:
    - `slider`: `SetPowerPercentageWanted` with one of 0.0/0.5/1.25;
    - `turn_off` / `turn_on` on a random consumer;
    - `set_power_wanted`;
    - `steal`: `StealPower` of half the main battery;
    - `drain`: `SetMainBatteryPower(0.0)`;
    - `cloak` (`StartCloaking` on a ship that has a cloak);
    - `add_consumer`: a new `SensorSubsystem` turned on, attached with `AddPoweredConsumer`.
  - After every tick, compare every SDK getter listed in Step 1 for every ship's plant and consumers, plus each plant's two watcher `GetWatchedVariable()`, with `float.hex` equality.
  - Assert `passive_state.audit_failures() == []`, `counts()["program_ticks"] > 0` and `counts()["thawed"] > 0`.
  - Add one `test_..._six_ticks_per_frame` variant that calls the walk in bursts of 6 with ops only between bursts.
- [ ] **Step 6: Run** `uv run pytest tests/integration/test_passive_power_differential.py tests/unit/test_passive_power.py tests/integration/test_passive_weapons_differential.py tests/unit/test_passive_weapons.py -q` and expect a pass. Also run the existing power tests for the code that moved: `uv run pytest $(git ls-files 'tests/**/test_*power*.py' | tr '\n' ' ') -q`. Check the file list is non-empty before running.
- [ ] **Step 7: Commit** the files above with `git commit -F`, message `perf(passive): power draw program with frozen consumers`.

### Task 2: An idle tractor freezes, and a beam's `_firing` thaws it

**Files:**
- Modify: `engine/appc/weapon_subsystems.py` (`TractorBeamSystem._POWER_FREEZABLE = True`; `TractorBeam._firing` becomes a `WakeField` subclass that also thaws a frozen parent system)
- Test: `tests/unit/test_passive_power.py` (add)

**Interfaces:**
- Consumes: Task 1's `passive_power.thaw(consumer)` and the `_power_frozen` flag; phase 1's `passive_state.WakeField`; `ShipSubsystem.GetParentSubsystem()`.
- Produces: `passive_power.ThawParentWakeField(WakeField)`. On write it does everything `WakeField.__set__` does, then calls `thaw(parent)` when `obj.GetParentSubsystem()` is not None and that parent's `__dict__.get("_power_frozen")`.

`TractorBeamSystem._wants_power` reads `IsOn()` (the system's `_is_on`, a FrozenField) and each beam's `IsFiring()`. `TractorBeam` resolves `IsFiring` to the mixin's `return 1 if self._firing else 0`. Beams are added through `AddChildSubsystem`, which invalidates (Task 1). A wanting tractor is still a call op (`DRAWS_DIRECT_FROM_MAIN`), so only the idle tractor freezes.

- [ ] **Step 1: Write failing tests:**
  - `test_idle_tractor_is_frozen`: a hand-built ship with a `TractorBeamSystem` (turned on, one `TractorBeam` child, not firing). After 2 plant ticks it is frozen and is not a call op.
  - `test_beam_firing_thaws_the_tractor_system`: after that, setting the beam's `_firing = True` sets the system's `"_power_frozen"` to False, and the next plant tick is full. Then with the beam firing, the system's four fields and the main battery match the per-tick model with `float.hex` for 5 ticks.
- [ ] **Step 2: Run and watch them fail.** Run `uv run pytest tests/unit/test_passive_power.py -q`.
- [ ] **Step 3: Implement** the descriptor in `passive_power.py`, with the `TractorBeam._firing = ThawParentWakeField()` override and the `_POWER_FREEZABLE` flag.
- [ ] **Step 4: Run** `uv run pytest tests/unit/test_passive_power.py tests/integration/test_passive_power_differential.py tests/unit/test_passive_weapons.py -q` and expect a pass. Also run the tractor tests: `uv run pytest $(git ls-files 'tests/**/test_*tractor*.py' | tr '\n' ' ') -q`, after checking the list is non-empty.
- [ ] **Step 5: Commit** with message `perf(passive): idle tractor freezes; a beam's firing write thaws it`.

### Task 3: Cheap property reads and a no-check watcher path

**Files:**
- Modify: `engine/appc/properties.py`. Add `TGModelProperty._field_value(self, field: str, args: tuple = ())`, which returns `self._data.get((field, _hashable_key(args)), None)`, and make `__getattr__`'s generated getter return `self._field_value(field, args)`.
- Modify: `engine/appc/subsystems.py`. `PowerSubsystem._prop_f(getter_name)` reads `prop._field_value(getter_name[3:])` when `getattr(type(prop), getter_name, None) is None` and the property has `_field_value`, else calls the getter as today.
- Modify: `engine/appc/float_range_watcher.py`. At the top of `_update`, when `self._checks` is empty, store `float(new_value)` into `_value` and return.
- Test: `tests/unit/test_property_field_value.py`, `tests/unit/test_float_range_watcher.py` (add, or create if absent)

**Interfaces:**
- Produces: `TGModelProperty._field_value(field: str, args: tuple = ()) -> object`.
- Consumes: nothing new.

The 2026-10-29 profile of `gl.subsystems` puts 6.5 of the plant's 30.8 s in `GetMainBatteryLimit`/`GetBackupBatteryLimit`, through `_prop_f` → `__getattr__`, which builds a closure every call. Another 1.5 s goes to watcher `_update`. Both are run every tick by `PowerSubsystem.Update`, and neither changes a value.

- [ ] **Step 1: Write failing tests:**
  - `test_field_value_matches_generated_getter`: for a `PowerProperty` with `SetMainBatteryLimit(12345.678)`, `prop._field_value("MainBatteryLimit") == prop.GetMainBatteryLimit()`. An unset field returns None from both.
  - `test_prop_f_prefers_a_real_getter`: a `PowerProperty` subclass defining `GetMainBatteryLimit` as a real method returning 7.0 makes `plant.GetMainBatteryLimit() == 7.0`.
  - `test_prop_f_skips_the_generated_getter`: monkeypatch `TGModelProperty.__getattr__` to raise for `GetMainBatteryLimit`. `plant.GetMainBatteryLimit()` still returns the stored value (it fails before Step 3).
  - `test_watcher_without_checks_tracks_value`: `_update(0.4)` then `GetWatchedVariable() == 0.4`. Adding a check, then updating across the threshold, fires exactly as before (one event, same float).
- [ ] **Step 2: Run them and watch the new ones fail.** Run `uv run pytest tests/unit/test_property_field_value.py tests/unit/test_float_range_watcher.py -q`.
- [ ] **Step 3: Implement** as specified under Files.
- [ ] **Step 4: Run** the new tests, Task 1's tests, and the existing property and watcher tests (`git ls-files 'tests/**/test_*propert*.py' 'tests/**/test_*watcher*.py'`, after checking the list is non-empty), and expect a pass.
- [ ] **Step 5: Commit** with message `perf(power): property field reads without a closure; watcher skips crossing work with no checks`.

### Task 4: Whole-scene audit, measurement, docs

**Files:**
- Modify: `tests/host/test_passive_state_scene_audit.py`
- Modify: `docs/superpowers/specs/2026-10-30-passive-subsystem-state-design.md` (§8 measured note)
- Modify: `CLAUDE.md` (the "Passive subsystem state" row: add phase 2)

- [ ] **Step 1: Extend** `test_combat_stress_runs_clean_under_the_audit`. Also assert `passive_power.counts()["program_ticks"] > 0` and `["thawed"] > 0`, and keep `audit_failures() == []`. Run `uv run pytest tests/host/test_passive_state_scene_audit.py -q` and expect a pass.
- [ ] **Step 2: Capture.** From the worktree, run `TS=$(date +%Y%m%d-%H%M) && OPEN_STBC_HOST_HEADLESS=1 DAUNTLESS_WINDOW_SIZE=1280x720 DAUNTLESS_MISSION=engine.dev_missions.combat_stress DAUNTLESS_COMBAT_SHIPS=64 DAUNTLESS_DEV_VIEW=bridge DAUNTLESS_PROFILE_FRAMES=1500 caffeinate -i ./build/dauntless --developer > ~/Documents/dauntless-perf/passive2-cs64-bridge-$TS.log 2>&1`. Make sure nothing else heavy is running.
- [ ] **Step 3: Compare** against `~/Documents/dauntless-perf/passive1-cs64-bridge-20261030-1629.log`. Use the median of reports 3–11 of `gl.subsystems` and `sim.weapons` per game tick (value ÷ calls), plus `r.frame` and frame ms. Allow for a run-wide drift by comparing `r.frame`, as the phase 1 note did. Expected: `gl.subsystems` down by roughly half (estimate). Write the numbers into a §8 "Measured (phase 2)" note.
- [ ] **Step 4: Docs.** In the CLAUDE.md row, add the frozen consumers and draw program, `passive_power.counts()`, and that `DAUNTLESS_PASSIVE_STATE=0` also restores the per-tick pump.
- [ ] **Step 5: Commit** the test, spec and CLAUDE.md with message `docs(passive): phase 2 measured; scene audit covers the power program`.
