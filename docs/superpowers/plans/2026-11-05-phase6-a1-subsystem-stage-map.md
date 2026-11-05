<!-- Recon snapshot 2026-11-05 (ws/motion-phase6-measure). Line numbers drift; find sites by name. Written by a read-only explorer for the phase 6 A1 plan. -->

# A1 recon: `_update_ship_subsystems` → C++

## 1. Per-tick call graph

**Where it runs.** `GameLoop.tick` (engine/core/loop.py:40-150), in this order:
- `native_motion.close_published`, avoidance-snapshot invalidate, `refresh_stale_pulse_params`
- `gl.timers.game`, then `gl.timers.real` (:55-58)
- `gl.timeslice` → `gl.cloak` (`tick_defensive_cloak`) → `gl.ai` (:67-72)
- `apply_pending_alert_levels`, `gl.bridge_chars`, `gl.proximity`, `gl.warp_states`, `gl.shuttles`, `warp_in_flash`
- `gl.motion` (`tick_all_ship_motion`: kernel M, tractors, publish), `gl.rock_motion`, `gl.rock_death`
- **`gl.subsystems` (:126-127)**
- then the native audit (:132-136) and, only if `owns_boundary`, the boundary (:141-150).

In the host: `_whole_tick` (engine/host_loop.py:11153-11176) runs `loop.tick()` with `GameLoop(owns_boundary=False)` (:12649, :12668-12670). After that come `sim.ship_list`, then `_combat_effect_scope()` around `_advance_weapons` (K0) and `_advance_combat`, then `_combat_tick_boundary()` (:973). The subsystem stage therefore runs **outside** the effect-queue deferral scope.

**Ship filter.** `iter_non_rock_ships()` (engine/appc/ship_iter.py:83-89) wraps `iter_ships()` (:60-80).
- `iter_ships` takes a snapshot of `App.g_kSetManager._sets.items()` and a `list()` of each set's `_objects.values()`.
- It keeps objects that are `isinstance(ShipClass)`; `iter_non_rock_ships` then drops `RockClass`.
- Dead and dying ships still in a set are included.
- Both functions do function-local imports on every call.

**Per ship** (loop.py:170-191), dt = `TICK_DELTA = 1.0/60` (:8):
1. `ship.GetShieldSubsystem()` → `ShieldSubsystem.Update(dt)` (subsystems.py:2388-2475)
2. `ship.GetPowerSubsystem()` → `PowerSubsystem.Update(dt)` (:2777-2828). This also runs the consumer pump.
3. `ship.GetCloakingSubsystem()` → `CloakingSubsystem.Update(dt)` (:3431-3475)
4. `ship.GetRepairSubsystem()` → `RepairSubsystem.Update(dt)` (:3108-3157)
5. `articulation.tick_ship(ship, dt)` (articulation.py:417-506)

Ship getters are at ships.py:1195-1209.

**Every subsystem type with per-tick work here:**

| Type | Work |
|---|---|
| ShieldSubsystem | Adds dt to `_charge_accum`. When it reaches ≥ 0.5 s: refreshes `_ramp_fraction` for all faces. If offline, zeroes all faces. Otherwise adds `_charge_per_second[f]*accum` to each face, clamped to max (faces with max 0 skipped). Then updates the 7 shield watchers. |
| PowerSubsystem | Breach check once (`_breach_fired`). Without a property it returns early and pumps nothing. Adds dt to `_interval_elapsed`. At ≥ 1.0: recharges batteries (unless `_is_offline`), seeds conduit budgets and `_available_power`, zeroes `_power_dispensed`. Every tick: consumer pump, then both battery watchers `_update(fraction)`. |
| Powered consumers, via the pump: sensors, impulse, warp, shields, phaser/pulse/torpedo/tractor systems, repair (anything attached through `_attach_subsystem`, in attach order, ships.py:1096-1115) | `PoweredSubsystem._update_power` (:1493-1535) writes `_power_wanted`, `_power_received`, `_efficiency`, `_power_factor` and draws through `plant._draw`. Tractor: `DRAWS_DIRECT_FROM_MAIN` (weapon_subsystems.py:2201), steals from main while a beam fires (`_wants_power` :2233-2246). Cloak: overrides `_update_power` (:3352-3375) to steal `1000*dt` from reserve and snapshot `_backup_reserve`. Child banks and tubes are not consumers. |
| CloakingSubsystem | If IsDisabled or IsDestroyed: force decloak. If trying to cloak and `_backup_reserve <= 0`: force decloak. Otherwise advances `_transition_elapsed` and completes at ≥ `_transition_duration` (default 4.5 s, :3198). |
| RepairSubsystem | Picks the first NumRepairTeams queued items with condition > 0. Destroyed items fire CANNOT_BE_COMPLETED once and are skipped. Each worked item gets `sub.Repair(per_item/complexity)` → SetCondition. Completed items are discarded from the queue and fire ET_REPAIR_COMPLETED. |
| Articulation (per ship) | `leaf_for` is cached. `(leaf, articulated_part.generation())` vs `_rigless_key` is an early out for rigless ships. Otherwise: `state_for(ship)` (warp > player alert > NPC has-target), per-part transitions `u += dt/duration`, interpolate, and if anything moved `push_posed_parts` + `pose_sink.notify` (render node overrides in the host). |
| Hull, sensors, impulse, warp (as subsystems) | No Update in this stage, only consumer draw. The warp state machine is `gl.warp_states`; the tractor force is in `gl.motion` (ship_motion.py:179). |

## 2. State read/written, native status, events

**ShieldSubsystem**
- Reads: `_charge_accum` (plain attr, :2218), `_max_shields` (HasShieldsField), `_current_shields` (NativeFloatList), `_charge_per_second` (plain list, not mirrored), `_is_on` (NativeFrozenField, through the watcher getters), `_is_offline` inputs.
- Writes: `_charge_accum`; `_ramp_fraction` (RampField, pushed in place via `push_field` :2434); `_current_shields` (in place, then `push_field` :2448/:2466).
- Watchers: `_shield_watchers[0..6]._update` (FloatRangeWatcher, not mirrored).
- Events: SDK range-check events, e.g. ET_AI_SHIELD_WATCHER from ConditionSingleShieldBelow. They fire synchronously (float_range_watcher.py:143-181 → events.py:802 AddEvent, which dispatches at once). Watchers are fed `GetSingleShieldPercentage`, which reads 0.0 while the generator is off.

**PowerSubsystem** (all plain attributes, none mirrored)
- Plant fields: `_available_power`, `_main_battery_power`, `_backup_battery_power`, `_main_conduit_current`, `_backup_conduit_current`, `_interval_elapsed`, `_power_dispensed`, `_power_wanted_total`, `_breach_fired`, `_main_battery_watcher`, `_backup_battery_watcher` (:2556-2572). Program slot: `__dict__["_passive_power"]`.
- Plant row: inherits the ShipSubsystem NativeFields (`_condition` and so on), read via GetConditionPercentage.
- Property reads every tick: PowerOutput, MainConduitCapacity, BackupConduitCapacity (at the interval), MainBatteryLimit and BackupBatteryLimit (twice per tick, plus once per interval) through `_prop_f` (:2592-2602) → `prop._field_value(name)` (properties.py:89-91), with a `getattr(type(prop), ...)` probe first. GetConditionPercentage → GetMaxCondition → `prop.GetMaxCondition()` through the `__getattr__` closure (properties.py:93-124).
- Consumer fields (PoweredSubsystem :1405-1419):
  - NativeFrozenField (pushes to the mirror and thaws): `_is_on`, `_normal_power`, `_power_percentage_wanted`, `_efficiency`, `_power_factor`.
  - FrozenField only (not mirrored): `_power_wanted`, `_power_received`.
  - Program flag `_power_frozen`.
- Contract comment above `_POWER_FREEZABLE`: subsystems.py:1393-1405. Cloak sets False (:3253); TractorBeamSystem opts in (weapon_subsystems.py:2204); TractorBeam `_firing` is NativeThawParentWakeField (:2601).
- Events: battery watchers' range checks (ET_POWER_FRACTION_CHANGED from ConditionPowerBelow), synchronous. Breach → `death_check.note_breach` (death_check.py:61-65) emits ZERO_CROSS, held to the boundary.
- No ET_SUBSYSTEM_POWER_CHANGED from inside the stage; that only fires from SetPowerPercentageWanted, :1473.

**Cloak**
- `_cloak_state` is a NativeField (:3244). `_transition_elapsed`, `_transition_duration` and `_backup_reserve` are plain.
- Events: ET_CLOAK_COMPLETED / ET_DECLOAK_COMPLETED via `_fire` (:1550-1568), synchronous, source and destination the ship. Dev-mode `print` in `_cloak_dev_log`.
- The cloak SFX and `_stop_weapons` run only in Start/StopCloaking, not in Update.

**Repair**
- Plain state: `_queue` (`_RepairQueue`, which keeps each member's `_in_repair_queue` NativeField, :2946-3016) and `_cannot_complete_notified` (a set of `id()`s).
- Property reads: GetMaxRepairPoints and GetNumRepairTeams through `__getattr__` closures.
- Per item: GetCondition, GetMaxCondition (property, twice), GetRepairComplexity, then `Repair` → `SetCondition` → `_set_condition` (:784-807). With DAUNTLESS_NATIVE_COMBAT on this goes to `native_combat.set_condition` (native_combat.py:6671) → `combat_dmg_set_condition` (host_bindings.cc:6239-6290), the C++ `set_condition` in damage.h/damage.cc. That writes `_condition`/`_threshold_state` and the watcher values, and queues COND_WATCH, SUBSYS_EVENT (e.g. OPERATIONAL when crossing the disabled threshold) and ZERO_CROSS to the effect queue, held to the boundary. REPAIR_ADD is not emitted because the item is already queued.
- Events: ET_REPAIR_CANNOT_BE_COMPLETED (inside the queue loop, :3136-3139) and ET_REPAIR_COMPLETED (:3155-3157), as TGObjPtrEvent with source and objptr the sub, synchronous (:3160-3177).

**Articulation**
- `ship._articulation_poses` is a PosedPartsField (ships.py, about :53; native_combat.py:1502-1524). `_articulation_transitions`, `_articulation_leaf` and `_rigless_key` are plain.
- Reads: rig `ArticulatedPartProperty` (hardpoint data), warp_state, the current player, GetAlertLevel, GetTarget.
- Pushes: `push_posed_parts` (native_combat.py:2210-2224: flag plus pose table) and `pose_sink.notify` (pose_sink.py:22-33, the render sink in the host). No events.

## 3. Time and cadence rules a port must match exactly

- **Shields** (`SHIELD_CHARGE_PERIOD_S = 0.5`, subsystems.py:232; logic :2425-2475).
  - Accumulate with `accum = accum + float(dt)`. If `< 0.5`, return.
  - Otherwise `dt = accum; accum = 0.0` (an unconditional reset, before the offline branch). The first charge lands on tick 30 or 31, depending on the IEEE sum of 1/60.
  - Regen is not gated by IsOn, the alert level or power. Offline drains to 0.
  - Documented in docs/reference/engine/perf-cadences-and-latency.md §1 (:27-43). The table row at :15 points to `subsystems.py:115`, which is out of date.
- **Power** (`POWER_INTERVAL = 1.0`, :2719; Update :2789-2813).
  - `_interval_elapsed += dt`. At ≥ 1.0: `elapsed = accum; accum = 0.0` (reset, not subtract; comment :2792-2794).
  - Recharge, unless offline: `PowerOutput*condPct*elapsed`. Main first up to MainBatteryLimit, spill to backup up to BackupBatteryLimit, the rest discarded (:2721-2730).
  - Conduit budgets are computed unconditionally: `main = min(main_batt, MainConduitCapacity*condPct*elapsed)`, `backup = min(backup_batt, BackupConduitCapacity*elapsed)` (backup not health-scaled). `available = main + backup`.
  - Per tick per consumer: `base = normal*dt`, `wanted = base*pct`.
  - `_draw` order and clamps (:2880-2927): MAIN_FIRST is main conduit and battery then backup; BACKUP_FIRST; else BACKUP_ONLY. PSM_DIRECT_MAIN (3) falls to the else branch.
  - `_record_draw`: `eff = recv/wanted` (1.0 if wanted 0), `factor = recv/base`.
  - Free consumer (base ≤ 0): eff = factor = 1.0. Not wanting power: all four fields 0.
  - Tractor direct steal: `wanted = base*pct`, `recv = StealPower(base)`, eff = factor = recv/base, not added to `_power_dispensed`.
  - Cloak: base = 1000*dt reserve steal, factor = eff, not added to `_power_dispensed`.
  - `_power_wanted_total` is the ordered sum (:2846-2878, with the `_BASE_GET_POWER_WANTED` identity guard :1574).
  - Watchers: `batt/limit` (0 when limit is 0), every tick.
  - The interval math is not in perf-cadences-and-latency.md. The references are docs/reference/gameplay/ship-subsystems.md (cited at :2801) and the test pins test_power_interval_tick.py / test_power_reference_values.py.
- **Passive power program** (passive_power.py:165-241): freeze, replay `_draw(wanted, mode)` and rebuild. It is designed to be bit-identical to the full pump. The phase-6 spec §3 allows dropping it if the goldens hold.
- **Repair**: `raw = points*bayCondPct*dt; per_item = raw/len(worked); gain = per_item/complexity` (complexity ≤ 0 treated as 1). No power term. The repair bay at condition 0 does not repair.
- **Cloak**: elapsed `+= dt`, complete at ≥ duration, then reset to 0.
- **Articulation**: `u += dt/max(duration, 1e-6)`. Duration scales with the fraction of swing remaining (`_transition_duration`).
- Whole-tick ordering effects: perf-cadences-and-latency.md:237-280, row 2 (:256).

## 4. Native mirror pattern to follow

- **Descriptors** (native_combat.py).
  - `NativeField` (:737-876): `__set__` stores into `__dict__`, then `combat_push_scalar` (one raw METH_FASTCALL call) or `_push`. Off the main thread it queues the push. No `__get__`.
  - Variants: NativeRefField :882, NativeRefList :930, NativeFloatList :958 (in-place writers must call `push_field`), RampField :1401, HasShieldsField :1646, PosedPartsField :1502.
  - Wrapped: NativeFrozenField / NativeWakeField / NativeThawParentWakeField (:1154-1210) do the thaw or wake first, then the push.
  - `register` (:1751-1779) stores `_nslot` and a weakref finalizer that defers the free. `_push_all`/`resync` (:2812, :3077). `audit_mirror` (:3482). `drain` (:1973-2007).
  - Mirror field ids come from `combat_field_names()`. A new field needs the `Field` enum (mirror.h:42-202), the row struct (mirror.h:286-356) and the FieldInfo table in mirror.cc (:14ff; e.g. `_power_factor` :67).
- **Direction today: Python is authoritative.** No descriptor `__get__` reads C++. The kernels write back into `__dict__` through C appliers (combat_write_apply.cc, `combat_set_applier` host_bindings.cc:14400; kernel M motion_write_apply.cc). Moving state to native-authoritative with descriptor reads would be new.
- **K0** (kernel structure).
  - Python: `k0_weapons` :4654-4699 stands down on off, audit, passive audit or nested, drains, retries `combat_k0_begin` with fresh class verdicts. `run_k0` :4729-4747 inside `effect_queue.session()`. `_run_k0` :4750-4783 sets the applier and loops `combat_k0_next` until DONE; RUN_PYTHON calls the Python `UpdateCharge`/`UpdateReload`/`passive_weapons.advance`. The override-guard comment is at about :4400-4540.
  - C++: k0_charging.h (pure steps, session begin/next/end/abandon, write log + undo, K0Entry effects, hand-back reasons), k0_charging.cc; bindings host_bindings.cc:4908 (begin scan), :13631 (begin), :13697 (next).
- **Kernel M.**
  - engine/appc/native_motion.py: docstring :1-56. `enabled` :168-179 checks switch, mirror, native store and stock snapshot. `_SURFACE`/`_SNAPSHOT` :291-332 hold functions, the roster iterators and class method resolution, compared as a tuple by identity. Class watch :368-416 pushes `motion_stock` etc. per class. `_overridden` instance scan :459-489. `step_all`/`_step_set` :514-597 run segments, hand WARP_ROW/PYTHON_ROW to Python, then re-read the rest of the set and re-check the snapshot. `_resync` on raise :609-621.
  - Entry: ship_motion.tick_all_ship_motion :155-182.
  - C++: motion_step.h/.cc (commit per row, PythonRow with nothing written). Bindings host_bindings.cc:12775-12900 (`combat_motion_step` releases the GIL to compute, then C write-back).
- **Effects back to Python.** engine/appc/effect_queue.py: docstring :1-~220, `scope` :320, `session` :367, `boundary` :417, `emit` :430, `flush` :530, `_drain` :570-605 (damage kinds held until the boundary). C++ queue: native/src/host/combat_effect_queue.h. Kernels append by handle and the binding resolves them. Damage chain: damage.h `DamageOut{writes, entries, undo}`.

## 5. Callers and our own wrappers

- `GameLoop.tick`: host (host_loop.py:12649/12670), tools/gameloop_harness.py:119-123, tests/helpers/headless_mission.py:89/106/157.
- tools/mission_harness.py: no GameLoop or stage call found.
- Direct `game_loop._update_ship_subsystems()` callers in tests: golden_fight.py:541, k1_fight.py:543, posed_fight.py:805, test_passive_power_differential.py:118, test_passive_weapons_differential.py:195, the native K0/K2/K3/combat-step/can-detect/off-lock differentials, and test_native_gil_release / compute_timers / weapons_mirror / k2_mirror / passive_weapons unit tests (17 files).
- No engine or tools code calls these Update methods except loop.py. Many unit tests call them directly.
- No monkeypatch or wrapper of the stage, its Update methods or `tick_ship` was found in engine/tools/tests.
- dev_combat_cheats is read only in apply_hit, not in this stage.
- `repair_ship_fully` (subsystems.py:3668) is called from the developer options panel (ui/developer_options_panel.py:478), outside the stage.
- QB `sim_restore` (engine/quickbattle/sim_restore.py:95-122) writes conditions and shields through SetCondition/SetCurShields.
- DAUNTLESS_PASSIVE_AUDIT=1: `passive_power.pump` runs `audit_compare` (reference `_pump_consumers` vs program), and K0 stands down ("audit", native_combat.py:4660). DAUNTLESS_PASSIVE_STATE=0: `_pump_consumers` (subsystems.py:2814-2817). Both are read in `passive_state.configure` (passive_state.py:14-17) from `GameLoop.__init__`.
- DAUNTLESS_NATIVE_AUDIT=1 runs `audit_mirror` after the stage (loop.py:132-136).

## 6. Tests

- **Golden fights.** tests/integration/test_golden_fights.py; helper tests/helpers/golden_fight.py.
  - Recordings: tests/fixtures/golden_fights/<scene>.darwin.json.gz, compared as per-tick SHA-256 plus rows. Re-record with `UPDATE_COMBAT_GOLDEN=1 COMBAT_GOLDEN_REASON=...`.
  - Scenes: k1_ops_tpf1/tpf6, k1_gameloop_ai, k1_midwalk_handler, posed_fight, tractor_modes, sdk_dumb_fire, motion_branches, host_frames(_tpf1).
  - State rows: per ship IsDead, hull condition and 6 shield faces (k1_fight.py:480-487); weapon `_charge_level` etc., which catch power-factor changes; AddEvent rows; queued effects; posed ships' articulation (posed_fight). Batteries, the repair queue and non-hull conditions are not recorded; repair is caught only through hull condition and events.
- **Host:** tests/host/test_passive_state_scene_audit.py (combat_stress, 16 ships, 120 ticks, audit on, asserts no failures plus program_ticks/frozen > 0), test_power_display_sdk.py.
- **Integration:** test_passive_power_differential.py (bit-exact SDK getters and watchers, per-tick vs program), test_power_reference_values.py, test_repair_oracle_galaxy.py, test_whole_ticks.py, test_gameloop_harness.py, test_fed_attack_survives_power_management.py, test_quickbattle_fed_starbase_shields.py.
- **Unit (tests/unit):**
  - Power: test_power_subsystem_update, _budget, _conduits, _breach, test_power_interval_tick, test_power_consumer_draws, test_power_draw_inline_equivalence, test_conduit_getters_battery_limited, test_passive_power, test_passive_state.
  - Repair: test_repair_subsystem, test_repair_app_surface, test_power_repair_subsystems, test_gameloop_repair_tick.
  - Shields: test_gameloop_shield_regen, test_shield_subsystem, test_shields, test_shield_charge_accum_state, test_shield_generator_disabled_stops_regen, test_shield_alert_cycle_does_not_recharge, test_shields_default_on, test_shield_sensor_power_factor.
  - Watchers and effects: test_subsystem_watchers, test_float_range_watcher, test_condition_watcher_events, test_damage_effect_queue.
  - Cloak: test_cloaking_subsystem, test_cloak_power_starvation, test_cloak_reserve_depletion, test_cloak_event_destination.
  - Articulation: test_articulation*, nine files.
  - Breach: test_warp_core_breach*.
  - Power factor in weapons and motion: test_weapon_power_factor, test_torpedo_reload_power_banking, test_energy_weapon_power_gate, test_motion_power_factor.
- **ctest combat_*** (native/tests/combat/): damage_test.cc (set_condition ordering, including REPAIR_ADD), k0_charging_test, motion_step_test, mirror_test. None covers power, repair or shield regen.

## 7. Hot SDK accessors

- Plain `__dict__` reads (the Native* fields have no `__get__`):
  - GetCondition (:763), GetPowerPercentageWanted (:1475), IsOn, GetPowerPercentage (`_efficiency`), GetNormalPowerPercentage (`_power_factor`).
  - GetMainBatteryPower / GetBackupBatteryPower / GetAvailablePower (:2574-2579).
  - GetCurrentShields / GetMaxShields, GetSingleShieldPercentage / GetShieldPercentage (sums, :2330-2380).
- Through the property data bag:
  - GetMainBatteryLimit / GetBackupBatteryLimit / GetPowerOutput / conduit capacities (`_prop_f` → `_field_value`).
  - GetMaxCondition (`prop.GetMaxCondition()` closure, plus try/except, :829-845) and therefore GetConditionPercentage and GetCombinedConditionPercentage (:913-924).
  - GetMaxRepairPoints / GetNumRepairTeams (closures).
- IsDisabled and IsDestroyed use `_max_condition`, not the property (:1304-1338).

## 8. Surprises and risks

- **Synchronous SDK callbacks mid-stage.** Shield and battery watcher crossings, cloak completion and repair events dispatch inside the walk (AddEvent, events.py:802). A handler can change any ship's state before later ships or subsystems update. ET_REPAIR_CANNOT_BE_COMPLETED fires while iterating `self._queue` (:3132-3139), so a handler that changes the queue is reentrant on that list.
- **Mixed delivery.** Repair's SetCondition reports are held to the boundary, but REPAIR_COMPLETED is immediate.
- **Runtime property mutation without a push.** E2M0:754/2935, E2M1:592, E6M2:602/629/656/2500/2546 and E6M4:1751/1950 call `pProp.SetMaxRepairPoints`. Shared templates use `__getattr__` setters, and only MaxCondition pushes (properties.py:100-104). SDK DockWithStarbase.py:128 and ShipScriptActions.py:294 call SetMain/BackupBatteryPower. Several SDK scripts call SetShieldChargePerSecond / SetCurShields / SetPowerPercentageWanted / TurnOff.
- **Ordering dependencies.**
  - Power must run before cloak in each ship (cloak reads the fresh `_backup_reserve`).
  - The stage's `_power_factor`/`_efficiency`/`_is_on` writes feed K0 (k0_charging.cc:267-380) and sensors (sensor_detection.py:333) in the same tick.
  - Kernel M reads `_power_percentage_wanted` before this stage.
  - Repair's condition writes gate next tick's shields and power through `_is_offline`.
  - Ship order is set-dict order.
- **Asymmetric gates.** Repair ignores `_is_offline`, dying ships and radiation (only bay condition > 0), though the `_is_offline` docstring lists repair. The cloak offline test is IsDisabled/IsDestroyed only. The power recharge and shield branches use full `_is_offline`, which includes `_radiation_out` and `ship_death._out_of_action`.
- **Edge semantics.** PowerSubsystem with no property skips the pump entirely, leaving consumer fields stale. `_draw`'s else branch makes PSM_DIRECT_MAIN act as BACKUP_ONLY. Direct steals are not counted in `_power_dispensed`. `_cannot_complete_notified` is keyed by `id()`.
- **Articulation dependencies.** It calls the render sink (`pose_sink`) and uses Python AI and warp state. Rigs come from hardpoint `__parts__` (articulated_part, hardpoint_overrides) with a generation counter.
- **Save/restore.** State must stay visible in `__dict__`: `_charge_accum` comment :2213-2217 ("39 SDK classes round-trip through __getstate__"), `_breach_fired` TODO :2570, and QB `sim_restore`.
- **Audit interplay.** Passive audit `_restore` writes behind the mirror (passive_state.py:83-87). K0 stands down under the passive audit.
