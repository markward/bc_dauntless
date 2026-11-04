> **Implemented 2026-11-02** on branch `ws/combat-weapon-state` (tip `1d714e767`): C-applied write logs, the one-call scalar push and kernel K0 (charging and reloading). Outcome, measurements and rulings: `docs/superpowers/specs/2026-11-02-native-weapon-state-design.md` §10. The rows below are the pre-build snapshot (§4.1's `K1Write` field note was updated since).

> Snapshot map written 2026-11-02 at commit 9102c2f34 (branch `ws/combat-native-damage`). It covers weapon charging and reloading (`sim.weapons`) and the weapon fields the K1/K2 kernels log back to Python. It is the factual input for "charging native + native-owned logged fields". It maps facts and does not design anything. Line numbers drift. "Inferred" marks anything not read directly in code or measured.

# Weapon state map: charging, reloading and the logged fields

Paths are relative to the worktree root. `WS` = `engine/appc/weapon_subsystems.py`, `NC` = `engine/appc/native_combat.py`, `HL` = `engine/host_loop.py`, `PW` = `engine/appc/passive_weapons.py`, `PS` = `engine/appc/passive_state.py`, `SDK` = `paths.sdk_scripts()`. On this machine that is `/Users/mward/Documents/Star Trek Bridge Commander/sdk/Build/scripts`, from `settings.json` `paths.sdk`.

## 0. What most affects feasibility

| # | Fact | Evidence |
|---|---|---|
| 0.1 | `sim.weapons` has **no native branch**. With the switch on it runs the same Python, and every charge, countdown or `_num_ready` write also pushes into the mirror through its descriptor. | HL:928-945; NC:680-688 (`NativeWakeField.__set__` → `_after_set` → `combat_set_f`) |
| 0.2 | With native on, `sim.weapons` rose from 0.443 to 0.616 ms/tick (+39%). The attribution to pushes and effects is **inferred**. | perf-register SIG-161, SIG-158 |
| 0.3 | Several charging/reloading inputs are **not mirrored**: `_recharge_rate`; PhaserSystem `_power_level` and the `PHASER_DISCHARGE_BY_POWER_LEVEL` table; the tractor parent's `_efficiency` and `_normal_power`; the tube's `_reload_delay`, `_reload_timers` and `_reload_advanced_at`; and the pulse charge watcher. The mirror has no float-list field type for the slot arrays. | mirror.h:56-117 (Field enum), 198-221 (SubsystemRow), :39 (FieldType) |
| 0.4 | The walk posts events **synchronously, mid-walk**. ET_TORPEDO_RELOAD goes to SDK `ConditionTorpsReady` (`SetStatus`, then `ET_AI_CONDITION_CHANGED`, which can run AI). The pulse watcher's ET_CHARGE_TOGGLE handler reads the charge of the ship's OTHER pulse weapons, including ones not yet stepped this tick. | WS:3655-3656, 3658-3680; WS:2969; float_range_watcher.py:96-118; events.py:802-842; SDK Conditions/ConditionTorpsReady.py:163-175, ConditionPulseReady.py:169-192; ai.py:76-105 |
| 0.5 | Sleep state is **Python-owned**: a per-ship `_Registry` holding a sorted awake list, plus `_passive_asleep` and `_passive_slot` in each weapon's `__dict__`. Wakes come from Python descriptors (`WakeField.__set__` → `on_wake` → `insort`). A weapon woken mid-walk is stepped this tick only if its index is still ahead. | PW:41-48, 133-196; PS:43-63 |
| 0.6 | `NativeField` has **no `__get__`**, so every Python read is a plain `__dict__` read. Readers bypass descriptors in many places: the passive audit (`vars(obj)`), `audit_mirror` (`attr in d`), the K1/K2 differentials (`__dict__.get`), and the RUN_PYTHON/ASK Python copies. A field with no `__dict__` value is silently skipped by `audit_mirror`. | NC:459-463, 2405-2414; PS:118-130; tests/integration/test_native_k1_differential.py:414-460 |
| 0.7 | With the switch on, Python copies still run every tick. Tractor systems are always RUN_PYTHON (`_pump_self_managed`). ASKs (`fire`, `retry`, `group_step`, `reseed`, `can_fire`) and handed-back WALK_STARTs run `try_fire_weapon`, `update_weapons` and `Fire`, which read and write the logged fields. | WS:2402; k1_fire_control.h:180-181 (`SelfManaged`), :140-170; NC:2880-2931, 2984-3006 |
| 0.8 | Identity matters for two logged fields. `_target_list` gets a NEW list on every prune or stop, and `_add_target` appends in place. `_target_offset` must be the walk's own offset OBJECT (ruling P5), which can be the caller's `_held_offset` object. | WS:1423-1434, 1544; NC:2649-2668; test_native_k1_differential.py:418-454 |
| 0.9 | Many Python writers of the logged fields live outside the kernels: StartFiring/StopFiring (AI FireScript, player keys, cloak and dewarp stops), SetForceUpdate (SDK player fire), PhaserSweep's `CanFire` (writes `_depleted`), UpdateCharge (`_depleted`, `_beam_on_countdown`), and render/tractor readers every frame or tick. | §3 tables |
| 0.10 | In a multi-tick frame, all N GameLoop ticks run first, then N × (weapons, combat). Tubes read the game clock, so every inner step of the frame sees the same `now`. Energy weapons integrate `dt` once per inner step. | HL:12321-12350, 12608-12627; transform_buffer.py:65-87; loop.py:29-39; WS:3603-3612 (inferred: clock is fixed during the inner steps) |
| 0.11 | No single-field read-back binding exists. `combat_dump(h)` returns the whole row as a dict and is also the liveness probe (`_live`). C++ has typed getters (`Mirror::get_f/get_i/get_ref/get_ids/get_fv`) but they are not bound. | host_bindings.cc:9985-10066; mirror.h:369-375; NC:442-447 |
| 0.12 | No subsystem or weapon defines `__getstate__`. There is no engine save today, but code comments assume serialisation walks `__dict__`. | subsystems.py:2101-2106, 2450; passive spec §5 |

## 1. Charging and reloading today

### 1.1 Where it runs (once per game tick)

| Step | Site |
|---|---|
| Frame: N GameLoop ticks (`advance_ticks` → `loop.tick()`, which advances `g_kTimerManager` by `TICK_DELTA` and runs AI, power and subsystems) | HL:11729-11731, 12350; loop.py:29-39, 112 |
| Then, for each of the N ticks: `_ships_this_tick = list(_all_ships_for_tick())`, rebuilt after the first tick | HL:12608-12615 |
| `with scope("sim.weapons"): _advance_weapons(_ships_this_tick, TICK_DT)`, `TICK_DT = 1.0 / 60.0` | HL:12616-12617, 11708 |
| `with scope("sim.combat"): _advance_combat(...)`: K4, K3, …, `cb.held_weapons` (K1 pump), `cb.phasers` (K2), `cb.tractors` (moved to the motion stage's `motion.tractors`, 2026-11-04) | HL:12618-12626, 1266-1401 |
| Ship order: `iter_ships()` walks `App.g_kSetManager._sets` and yields ShipClass instances | HL:2562-2572 |
| The headless harness (`headless_mission._sim_tick`) runs GameLoop.tick only. Tests call `_advance_weapons` directly. | passive spec §5; test_passive_weapons_differential.py |

`_advance_weapons` (HL:928-945): if `passive_state.enabled()` it calls `passive_weapons.advance(ships, dt)`, otherwise `step_every_weapon(ship, dt)` per ship. It never consults `native_combat`.

### 1.2 The walk (`PW`)

| Item | Detail | Site |
|---|---|---|
| Group order | `GetPhaserSystem, GetPulseWeaponSystem, GetTractorBeamSystem, GetTorpedoSystem`, the same order as the K1 pump's `_PUMP_GETTERS` (HL:1022-1023) | PW:62-66 |
| Dispatch | `isinstance(TorpedoTube)` → `UpdateReload(dt)`; `isinstance(_EnergyWeaponFireMixin)` → `UpdateCharge(dt)`; anything else is skipped | PW:69-84, 113-130 |
| Registry | Built once per ship only for a real `ShipClass` whose groups are `WeaponSystem`s, otherwise `step_every_weapon` runs every tick. Entries are `(weapon, is_tube)` in walk order. `awake` is the sorted index list. Every weapon starts awake (`_passive_asleep=False`, `_passive_slot=(registry, i)`). | PW:87-110 |
| Invalidate | `ShipClass._attach_subsystem` (ships.py:1080), the property scrub (ships.py:1495) and `ShipSubsystem.AddChildSubsystem` (subsystems.py:1173) | PW:50-59 |
| Step | `bisect_right(awake, last)` finds the next awake index by value. After the step, `if weapon._passive_at_rest(): put_to_sleep(weapon)` (the hook `on_sleep` removes it from `awake`). | PW:156-170 |
| Audit (`DAUNTLESS_PASSIVE_AUDIT=1`) | For each sleeper, after the walk: `audit_step(weapon, lambda: update(dt))` snapshots `vars(weapon)` (and `_charge_watcher` for pulse), runs the real update, records changed fields, and restores by dict write | PW:171-175; PS:118-130, 74-87 |
| Mid-walk wake | `on_wake` does `insort` into a live registry. A woken weapon is stepped this tick if its index > `last`, otherwise next tick. | PW:187-196; passive spec §6.3 |
| Invalidate mid-walk | The rest of that walk uses the stale registry. The next advance rebuilds with everything awake. | PW:145-149 |

**Sleep predicates** (`_passive_at_rest`):

| Class | Asleep when | Site |
|---|---|---|
| Energy (phaser, pulse, tractor) | `not _firing and _max_charge - _charge_level <= 0.0` | WS:753-758 |
| PulseWeapon | the above **and** `_cooldown_remaining <= 0.0` | WS:2769-2771 |
| TorpedoTube | `_num_ready >= _max_ready` | WS:3136-3141 |

**Wake fields** (any write wakes, even with an equal value): `_charge_level`, `_firing`, `_max_charge` (mixin, WS:741-743); `_cooldown_remaining` (pulse, WS:2765); `_num_ready`, `_max_ready` (tube, WS:3129-3130). TractorBeam's `_firing` is `NativeThawParentWakeField` (WS:2986). It also thaws a frozen parent power program, or drops it, when the value changes (passive_power.py:98-125).

### 1.3 `_EnergyWeaponFireMixin.UpdateCharge` (WS:955-1000): phaser banks; pulse and tractor reach it via super

Reads and writes, in order:

| # | Line | Op | Field / call | Mirrored? |
|---|---|---|---|---|
| 1 | 956 | read | `_firing` | yes (NativeWakeField bool) |
| 2 | 957 | read | `_beam_on_countdown > 0.0` | yes (NativeField float) |
| 3 | 959 | **write** | `_beam_on_countdown -= dt`, then return | push |
| 4 | 961-962 | read + call | `_charge_level - self._discharge_rate_per_second() * dt` | see below |
| 4a | 2655-2665 (PhaserBank) | call | `GetParentSubsystem()` → `parent.GetPowerLevel()` (hasattr) → `PHASER_DISCHARGE_BY_POWER_LEVEL[level]`; IndexError/TypeError gives 0.0 | `_parent_subsystem` yes; `_power_level` **no** (WS:2334-2344); table (WS:265) **not a Global** |
| 4b | 949-953 (mixin default) | read | `_normal_discharge_rate` | yes |
| 5 | 961 | **write** | `_charge_level = max(0.0, …)` | push (NativeWakeField) |
| 6 | 964 | read | `_charge_level <= 0.0` | |
| 7 | 970 | **write** | `_depleted = True` | push |
| 8 | 971 | call | `self.StopFiring()` (WS:905-911): read `_firing`; **write** `_firing=False` (wake, and parent thaw for tractor), `_beam_on_countdown=0.0`; if it was firing and `_loop_handle` is set, `_loop_handle.Stop()` (**sound**) and `_loop_handle=None` | `_loop_handle` no |
| 9 | 984 | read | `_max_charge - _charge_level <= 0.0` → return (the idle early-out) | yes |
| 10 | 986-987 | call | `GetParentSubsystem()`; `parent is None or parent.IsOn()` (`_is_on`) | yes, yes |
| 11 | 988-989 | call | `max(0.0, parent.GetNormalPowerPercentage() if parent else 1.0)` → `_power_factor` (subsystems.py:1388) | yes (NativeFrozenField float) |
| 12 | 995 | call | `GetConditionPercentage()` (subsystems.py:824-831): `GetMaxCondition()` (property `GetMaxCondition()` if > 0, else `_max_condition`, subsystems.py:759-775); `0.0 if mx <= 0`; `max(0.0, min(1.0, _condition / mx))` | yes (`_condition`, `_max_condition`, Property `MaxCondition`/`_set`); native port `condition_percentage` in fire_gates.cc:153 |
| 13 | 996-1000 | read, **write** | `headroom = max - charge`; `if headroom > 0.0: want = min(_recharge_rate * pf * cf * dt, headroom); _charge_level += want` | `_recharge_rate` **no** (WS:322, ships.py:1522) |

No event is posted. The only Python-only effect is the depletion `StopFiring` (sound handle, wake/thaw).

### 1.4 `PulseWeapon.UpdateCharge` (WS:2959-2969)

| # | Line | Op | Detail |
|---|---|---|---|
| 1 | 2960-2961 | read, **write** | `if _cooldown_remaining > 0.0: _cooldown_remaining = max(0.0, _cooldown_remaining - dt)` (NativeWakeField) |
| 2 | 2965 | call | the mixin `UpdateCharge`. `_firing` is always False on a pulse cannon (WS:2845-2853), so this is always the recharge branch (§1.3 rows 9-13) |
| 3 | 2969 | call | `_charge_watcher._update(self.GetChargePercentage())`. `GetChargePercentage` (WS:2830-2833) is `0.0 if _max_charge <= 0.0 else _charge_level / _max_charge`, with no parent/IsOn check, unlike PhaserBank's (WS:2689-2700). The watcher (float_range_watcher.py:96-118) stores `_value` when it has no checks. With checks it compares old and new values against each threshold and, on a crossing, calls `pEvent.SetFloat(v)` and `AddEvent` → **synchronous** `ET_CHARGE_TOGGLE` handler. The watcher is a Python object and is not mirrored. |

`_passive_audit_children = ("_charge_watcher",)` (WS:2767): the passive audit also snapshots the watcher's dict.

### 1.5 `TractorBeam.UpdateCharge` (WS:3012-3049)

| Line | Op |
|---|---|
| 3027 | read `_firing` |
| 3028-3033 | `parent = GetParentSubsystem()`; `parent is None or not parent.IsOn()` → `StopFiring()` (sound + wake + **parent power thaw/drop**) and return |
| 3038-3042 | `hasattr(parent, "GetPowerPercentage") and parent.GetPowerPercentage() <= 0.0 and parent.GetNormalPowerWanted() > 0.0` → `StopFiring()` and return. Reads `_efficiency` and `_normal_power` (subsystems.py:1385-1387), FrozenFields that are **not mirrored** (subsystems.py:1318-1322) |
| 3044 | firing and powered: return, with charge untouched |
| 3049 | not firing: `super().UpdateCharge(dt)` (§1.3 recharge branch; idle TractorBeamSystem `_power_factor` is 0 because `_wants_power` is false, WS:2434-2448) |

### 1.6 `TorpedoTube.UpdateReload` (WS:3557-3616) and `ReloadTorpedo` (WS:3618-3656)

| # | Line | Op | Detail / mirrored? |
|---|---|---|---|
| 1 | 3587 | call | `_ensure_slots()` (WS:3181-3192): if `len(_reload_timers) != _max_ready` or `len(_reload_advanced_at) != _max_ready`, it calls `_resize_slots()` (WS:3172-3179), which **rebinds** both lists with all slots loaded. Lists are not mirrored. |
| 2 | 3588 | read | `_num_ready >= _max_ready` → return (yes, yes) |
| 3 | 3590-3592 | call | `parent.GetNormalPowerPercentage() if parent else 1.0` (`_power_factor`, yes). No `IsOn()` read. |
| 4 | 3601-3602 | check | `not isinstance(factor, (int, float)) or factor < 0.0` → 0.0. NaN passes. |
| 5 | 3603 | call | `now = _game_time()` = `float(App.g_kUtopiaModule.GetGameTime())` = `g_kTimerManager.get_time()`; 0.0 + `log_swallowed` on exception (WS:53-77; App.py:1161-1162). K1 receives the same clock as `now` (NC:2623-2632). |
| 6 | 3604-3612 | read/**write in place** | per slot: skip `== _SLOT_LOADED` (-1.0); `game_dt = now - _reload_advanced_at[i]`, clamped at 0 if `< 0.0`; `_reload_timers[i] = prog + factor * game_dt`; `_reload_advanced_at[i] = now`. In-place list stores: **no descriptor fires** |
| 7 | 3613-3616 | call | first slot with `prog != -1.0 and prog >= _reload_delay` → `ReloadTorpedo()` and **return** (at most one attempt per call, even when ammo denies it). `_reload_delay` is **not mirrored** |
| R1 | 3640-3642 | | `_ensure_slots()`; `_num_ready >= _max_ready` → return |
| R2 | 3643 | call | `_reload_denied_by_ammo()` (WS:3313-3329): `_parent_ammo()` → `parent.GetCurrentAmmoType()` (WS:2081-2091, `_ammo_by_slot[GetCurrentAmmoSlot()]`, WS:2093+, `_selected_slot`); `getattr(ammo, "_unlimited", True)`; `ammo.GetAvailable()` (`_available`); `_rounds_loaded_systemwide()` (WS:3292-3311) sums `GetNumReady()` over `parent._children` that are tubes. All mirrored (`_ammo_by_slot`, `_selected_slot`, `_unlimited`, `_available`, `_children`, `_num_ready`); K1's `ammo_exhausted` ports the slot resolve (fire_gates.cc:159-190) |
| R3 | 3645-3651 | read | largest progress with strict `>` (the first index wins ties) |
| R4 | 3654-3656 | **write** | `_reload_timers[oldest] = -1.0` (in place); `_num_ready += 1` (NativeWakeField: push); `_broadcast_reload()` → `ET_TORPEDO_RELOAD`, Destination = tube, no Source, **synchronous** (WS:3658-3680) |

`dt` is ignored (WS:3557-3586 docstring). Other writers of the slot arrays outside the walk: `_start_slot_cooldown` (Fire effect WS:3427, `UnloadTorpedo` WS:3738) and `_sync_slots_to_num_ready` (Set/Inc/DecNumReady, WS:3207-3255).

### 1.7 What is mirrored on these classes

| Class | Native descriptors (WS line) | Not mirrored but read by the update |
|---|---|---|
| `_EnergyWeaponFireMixin` | `_charge_level`, `_firing`, `_max_charge` NativeWakeField; `_min_firing_charge`, `_depleted`, `_normal_discharge_rate`, `_power_setting`, `_beam_on_countdown`, `_dwell` NativeField (741-751) | `_recharge_rate`, `_loop_handle`, parent `_power_level` |
| PulseWeapon | + `_cooldown_remaining` NativeWakeField, `_cooldown_time` NativeField (2765-2766) | `_charge_watcher` |
| TractorBeam | `_firing` NativeThawParentWakeField (2986) | parent `_efficiency`, `_normal_power` |
| Weapon (tube base) | `_firing`, `_target_offset`, `_fire_timer` NativeField; `_target` NativeRefField (1170-1173) | |
| TorpedoTube | `_num_ready`, `_max_ready` NativeWakeField; `_last_fire_time`, `_immediate_delay`, `_skew_fire` NativeField (3129-3134) | `_reload_delay`, `_reload_timers`, `_reload_advanced_at` |
| ShipSubsystem / PoweredSubsystem | `_condition`, `_max_condition`, … NativeField (subsystems.py:326-355); `_is_on`, `_power_factor` NativeFrozenField (1317, 1323) | `_efficiency`, `_normal_power`, … (plain FrozenField, 1318-1322) |
| TorpedoAmmoType | `_unlimited`, `_available` NativeField (1759-1760) | `_max_torpedoes` |

mirror.h's SubsystemRow (198-221) holds `_charge_level`, `_max_charge`, `_min_firing_charge`, `_depleted`, `_normal_discharge_rate`, `_power_setting`, `_cooldown_remaining`, `_cooldown_time`, `_num_ready`, `_max_ready`, `_last_fire_time`, `_immediate_delay`, `_skew_fire`, `_beam_on_countdown`, `_dwell`. Kernel readers today: `_charge_level`, `_min_firing_charge`, `_depleted`, `_cooldown_remaining`, `_num_ready`, `_last_fire_time`, `_immediate_delay`, `_normal_discharge_rate`, `_power_setting`, `_available`, `_unlimited` (fire_gates.cc); `_beam_on_countdown`, `_dwell`, `_firing` (k1/k2/beam_geometry). No kernel reads `_max_charge` or `_max_ready` today (grep over native/src/combat/src).

### 1.8 Calls out during the walk (Python-only effects)

| Effect | Trigger | Frequency |
|---|---|---|
| `_loop_handle.Stop()` (sound) | depletion `StopFiring` on a firing bank (WS:971, 909-911) | when a beam runs dry |
| Tractor `StopFiring` (sound; parent power thaw/drop via ThawParentWakeField) | power lost or starved (WS:3029-3042) | rare |
| `ET_CHARGE_TOGGLE` (SDK ConditionPulseReady) | pulse watcher crossing (WS:2969) | per crossing, only if an AI registered checks |
| `ET_TORPEDO_RELOAD` (SDK ConditionTorpsReady, the passive differential's event log) | each reload (WS:3656) | per round loaded |
| `passive_state.wake/put_to_sleep` + registry hooks | every WakeField write; at-rest after a step | per write / per step |
| Mirror pushes (`combat_set_f/i`) | every write of a Native* field with the switch on | per write |
| `dev_mode.log_swallowed` | `_game_time` failure | exceptional |

No `GetParentShip`, cloak or `IsDead` read occurs in either update (verified by reading WS:955-1000, 2959-2969, 3012-3049, 3557-3656).

## 2. SDK, engine and UI surface over charge/reload/fire state

SDK counts exclude `App.py` (`grep -rn --include='*.py' "\.<M>("`).

| Method | SDK call sites | Kind / frequency |
|---|---|---|
| `GetChargeLevel` | loadspacehelper.py:235; AI/PlainAI/PhaserSweep.py:179; Conditions/ConditionPulseReady.py:185 | ship setup; PhaserSweep per AI evaluation for each bank that passes `CanFire`; on ET_CHARGE_TOGGLE |
| `SetChargeLevel` | loadspacehelper.py:237; Actions/ShipScriptActions.py:362, 369 | setup / action |
| `GetMaxCharge` | loadspacehelper.py:235-236; ConditionPulseReady.py:166; ShipScriptActions.py:362, 369 | setup / init |
| `GetMinFiringCharge`, `GetRechargeRate` | loadspacehelper.py:238-239; ConditionPulseReady.py:166, 185 | setup / event |
| `GetChargeWatcher` | ConditionPulseReady.py:50, 163 | condition init |
| `CanFire` | PhaserSweep.py:175 (**writes `_depleted=False`** via `_charge_gate`, WS:863-866); ConditionInPhaserFiringArc.py:175 | per AI evaluation |
| `GetNumReady` | Bridge/TacticalCharacterHandlers.py:223; TacticalMenuHandlers.py:2007; ConditionTorpsReady.py:152 | UI event; torp event |
| `GetNumAvailableTorpsToType` | 14 calls in 9 files (MissionLib.py:619, 3041; AI/Preprocessors.py:537; E3M1, E5M2, E6M2, E6M4, Episode7, Bridge handlers) | AI fire evaluation (Preprocessors:537); missions |
| `IsFiring` | E6M2.py:1900; E3M1.py:2153; Bridge/PowerDisplay.py:1024; AI/Preprocessors.py:486; ConditionFiringTractorBeam.py:52 | AI/UI/missions |
| `SetForceUpdate` | TacticalInterfaceHandlers.py:363; TacticalControlHandlers.py:130 (player fire); E8M2.py:6467 (on a warp set, not a weapon) | player key press |
| `StartFiring` / `StopFiring` / `StopFiringAtTarget` | 6 sites in 5 files / 16 sites in 9 files (Preprocessors FireScript :173-469; StarbaseAttack.py:115; E3M1) | AI FireScript per AI update (AI tree may sleep up to 4 ticks, CLAUDE.md perf-cadence row) |
| `IsInTargetList` | AI/PlainAI/StarbaseAttack.py:114 | per AI update |
| `GetTargetList` | AI/PlainAI/Warp.py:415 (`pTractor.GetTargetList()[0]`). Not defined on our WeaponSystem, so it hits the `__getattr__` stub (inferred; grep of WS) | rare |
| `UpdateCharge`, `ReloadTorpedo` | 0 SDK callers. SWIG surface: `EnergyWeapon.UpdateCharge`, `PhaserBank.UpdateCharge`, `TorpedoTube.ReloadTorpedo` (SDK App.py:6440, 6510, 6029). `UpdateReload` is our own name and not SWIG. | — |
| Set/Inc/DecNumReady, Get/SetLastFireTime, GetReloadDelay, GetMaxReady, Get/SetGroupFireMode, GetForceUpdate, GetNumTargets, IsBeamOn, Get/SetPowerSetting, GetCooldownTime | 0 SDK callers | — |

Engine readers (outside WS/NC):

| Reader | Reads | Frequency |
|---|---|---|
| `_build_phaser_beam_render_data` / `_build_tractor_beam_render_data` (HL:2486-2551) → `_beam_descriptor_pair` (HL:2370-2391) | `bank.IsFiring()` on every phaser/tractor bank of every ship in view; `bank._target` | per frame (`cb.render_data`) |
| `tractor.advance_tractors` (tractor.py:112-133) | `sys_.IsFiring()`, `emitter.IsFiring()`, `getattr(emitter, "_target")` | per tick (`cb.tractors`, HL:1401) |
| `_spawn_projectile` (WS:575-648) | `getattr(emitter, "_target")`, `getattr(emitter, "_target_offset")` (the torpedo copies it, projectiles.py:238) | per launch |
| TractorBeamSystem `_wants_power` → `_any_child_firing` (WS:2434-2448) | each beam's `IsFiring()` | power pump per tick, unless frozen (passive_power) |
| `weapons_display_panel` (`_snapshot` :90-101 → `_icon_descriptor_for_mount` :302-345) | `IsFiring`, `GetChargePercentage`, `GetMaxCharge`, `GetNumReady` of the **player's** mounts | per frame while visible (inferred: panel render_payload) |
| `weapon_config.read_weapon_config` (:191-232) | `GetNumAvailableTorpsToType`, `GetNumReady` (player) | per frame with the HUD (inferred) |
| `ai_inspector_model._tube_report` (:353-365) | `getattr(tube, "_reload_timers")`, `GetNumReady`, `GetMaxReady`, `GetReloadDelay`, `CanFire` | dev tool, on demand |
| `ships.py` property copy (:1512-1539) | **writes** `_max_charge`, `_charge_level`, `_recharge_rate`, `_cooldown_time`, `_max_ready`, `_num_ready`, `_reload_delay`; calls `_resize_slots` | ship build |
| Python K2 copy `_phaser_step_bank` (HL:1100-1197) | `bank._target`, `IsFiring`, `take_dwell`, `accumulate_dwell` | switch off, or a K2 RUN_PYTHON ship |
| `engine/appc/ai*.py` | no direct reads of these fields (grep) | — |
| Save / pickle | none: no `__getstate__` on any subsystem or weapon | — |

## 3. The logged fields

Descriptor classes (WS line):

| Field | Owner(s) | Descriptor | A write triggers |
|---|---|---|---|
| `_fire_timer` | Weapon (1173), WeaponSystem (1277; banks inherit) | NativeField(float) | dict store; push if enabled |
| `_target` | Weapon (1171), WeaponSystem (1275) | NativeRefField("Object") | store; push handle (-1 None, -2 unrepresentable); a stale referent drops the referent |
| `_target_offset` | Weapon (1172), WeaponSystem (1276) | NativeField(OFFSET) | store; push xyz, or unset if not a TGPoint3 |
| `_target_list` | WeaponSystem (1282) | NativeRefList("Object") | store; push handle list. An in-place append calls `push_field` (WS:1426) |
| `_force_update` | WeaponSystem (1283) | NativeField(bool) | store; push |
| `_group_fire_mode` | WeaponSystem (1287) | NativeField(int) | store; push |
| `_last_weapon_idx` | WeaponSystem (1284) | NativeField(int) | store; push |
| `_last_group_fired` | WeaponSystem (1285) | NativeField(int) | store; push |
| `_firing` | mixin (742) NativeWakeField(bool); TractorBeam (2986) NativeThawParentWakeField(bool); Weapon/tube (1170) NativeField(bool) | as listed | bank: store, **wake** if asleep, push. Tractor: also parent power thaw/drop on a value change. Tube: store, push |
| `_dwell` | mixin (751) | NativeField(float) | store; push |
| `_beam_on_countdown` | mixin (750) | NativeField(float) | store; push |
| `_depleted` | mixin (745) | NativeField(bool) | store; push |

Measured volume (caller's 64-ship capture, 2026-11-02): about 780 logged writes/tick in ~17 `apply_writes` calls. `_fire_timer` ~270, `_target` ~254, `_target_list` ~71, `_force_update` ~71, `_group_fire_mode` ~53, `_target_offset` ~23, `_firing` ~20, `_dwell` ~14, `_beam_on_countdown` ~1.

### 3.1 Python readers outside the kernels' own Python copies

"Copies" = `update_weapons`, `try_fire_weapon`, `_fire_decide`, the K2 Python body: these run on switch off, RUN_PYTHON, ASK and handed-back walks.

| Field | Readers (file:line) | Identity matters? |
|---|---|---|
| `_fire_timer` | only the copies: `try_fire_weapon` WS:1600-1618, `_reseed_all_fire_timers` WS:1645-1649; tests (5 files) | no (float; `.hex()` in differentials) |
| `_target` (bank) | HL:2391 (render, per frame); tractor.py:126 (per tick); WS:644 (`_spawn_projectile`, per launch); PulseWeapon `_fire_decide` WS:2913-2930 (copy); HL:1106 (K2 copy) | referent identity: it must be the same Python object |
| `_target` (system) | `WeaponSystem.GetTarget` WS:1580 (0 SDK callers on a weapon system, grep) | referent |
| `_target_offset` | WS:648 (`_spawn_projectile`; the torpedo copies the point); WS:3072 (`_resolve_torpedo_aim_point`, tube decide copy); projectiles.py:1125 reads the TORPEDO's own field, not the bank's | **yes**: ruling P5 says the bank holds the walk's offset OBJECT, which can be the system's `_held_offset` object (passed in by the AI or SDK caller) or a fresh copy (`GetTargetOffsetTG` copies, ships.py:1772-1779). Pinned by test_native_k1_differential.py:436-454 (`first[id(off)]`, `off is _held_offset`). No live in-place mutation of a held offset was found (inferred). |
| `_target_list` | `GetNumTargets` WS:1436; `IsInTargetList` WS:1447 (SDK StarbaseAttack per AI update); `_add_target` WS:1423-1426 (`in` test, then **in-place append**, then `push_field`); StopFiring WS:1544 (new `[]`); copies WS:1628, 1699, 1430 | **yes**: the prune and StopFiring bind a NEW list each time; `_add_target` appends into whatever list is current; the retry loop snapshots `list(...)`. The K1 differential records "new object since last record" (:418-424). |
| `_force_update` | `GetForceUpdate` WS:1386 (0 SDK callers); copies WS:1600, 1717, 1746 | no (bool type: Python stores `bool(flag)`) |
| `_group_fire_mode` | `GetGroupFireMode` WS:1404 (0 SDK callers); writer `SetGroupFireMode` WS:1403 is called from the copy WS:1720 | no |
| `_last_weapon_idx` | copy only WS:1711, 1730 | no |
| `_last_group_fired` | `_resolve_working_group` WS:1419-1420 (copy); writers StopFiring WS:1545, copies 1731, 1744 | no |
| `_firing` | `IsFiring` WS:913, 1195 → HL:2499, 2547 (render, per frame); tractor.py:119-124 (per tick); `_any_child_firing` WS:2441-2448 (power); `WeaponSystem.IsFiring` WS:1571-1578 (SDK 5 sites); weapons_display_panel.py:317 (per frame); `_passive_at_rest` WS:757 (per step); `UpdateCharge` WS:956, 3027; `StopFiring` WS:906; `_fire_decide` WS:886 (`was_firing`); `IsBeamOn` WS:919 | no (bool; type: Python writes `True/False`, K1 logs bool) |
| `_dwell` | `accumulate_dwell`/`take_dwell` WS:921-939 → K2 copy HL:1112, 1164-1167 | no; **sign of zero** matters: K2 elides a +0.0-over-+0.0 idle write (k2_beams.cc:248-255) |
| `_beam_on_countdown` | `IsBeamOn` WS:919 (K2 copy); `UpdateCharge` WS:957-959 (**the charging walk reads and writes it every tick a beam is lit**); `_fire_effect` WS:900; StopFiring WS:908 | no |
| `_depleted` | `_charge_gate` WS:863-866 (CanFire: K1 copy, **SDK PhaserSweep and ConditionInPhaserFiringArc via CanFire**, which also **write** it); `UpdateCharge` WS:970 (writes) | no |

Tests that touch the logged fields directly: **45 files**. Charge/reload fields: **65 files**. Tests calling `UpdateCharge/UpdateReload/_advance_weapons/passive_weapons`: **43 files** (grep -w over `tests/`). Tests reading them through `__dict__`: test_native_k1_dispatch.py, test_native_k2_dispatch.py, tests/host/test_native_k2_differential.py, tests/integration/test_native_k1_differential.py, tests/helpers/k3_fight.py.

### 3.2 Python writers of the logged fields outside the kernels

| Writer | Fields | When |
|---|---|---|
| `WeaponSystem.StartFiring` WS:1500-1536 | `_target_list` (in place), `_held_target`, `_held_offset`, `_fire_held`, `_force_update` (SetForceUpdate), then `k1_system` | AI FireScript / player keys / missions (gl.ai or input) |
| `WeaponSystem.StopFiring` WS:1540-1549 | `_fire_held`, `_held_*`, `_target_list = []`, `_last_group_fired = -1`, each bank's StopFiring | AI, K1/K2 stop records, cloak (subsystems.py:3300-3307), dewarp (subsystems.py:1993-1999), weapon_config toggle_tractor (:288) |
| Bank `StopFiring` WS:905-911, 2971-2975, 1192-1193 | `_firing`, `_beam_on_countdown` / `_target`, `_target_offset` | as above, plus UpdateCharge depletion |
| `SetForceUpdate` WS:1385 | `_force_update` | SDK player fire |
| `_charge_gate` WS:863-866 | `_depleted = False` | any CanFire (SDK AI conditions included) |
| `UpdateCharge` WS:959, 970 | `_beam_on_countdown`, `_depleted` | sim.weapons |
| Fire effects WS:888-903, 2937-2957, 3411-3438 | `_firing`, `_target`, `_target_offset`, `_beam_on_countdown`, `_dwell`, `_charge_level`, `_cooldown_remaining`, `_num_ready`, `_last_fire_time`, slot lists | K1 FIRE records (Python) |

## 4. The native side today

### 4.1 K1 write log

| Item | Detail | Site |
|---|---|---|
| Value type | `K1Value = variant<monostate, bool, int64, double, K1WalkOffset, vector<int64>>`; `K1Write{handle, std::string_view field, value}` (a static name; `std::string` until native weapon state Task 5 fix round 2) | k1_fire_control.h:207-224 |
| Make + log | `write_float/write_i/write_flag/write_int/write_target/write_target_list/write_target_offset`: read the old value for the undo, `m_.set_*`, push the undo, `log(h, "<name>", v)` | k1_fire_control.cc:289-363 |
| Row gone | `_target` on a dropped bank row is logged only (no mirror write) | k1_fire_control.cc:317-324 |
| Undo | A throw from `next()` undoes the writes made but not yet returned. A returned record's writes are final. | k1_fire_control.h:87-99 |
| Idle stops / beam sustain | logged with no record (`idle_stop`, beam `was_firing`) | k1_fire_control.cc:366-389; h:63-72 |
| Record | `writes` is the record's LAST element; the walk tag is second to last | k1_fire_control.h:233-251 |
| Binding | `combat_k1_next` (GIL held) builds a `py::list` with one `(handle, field_str, value)` tuple per write: a `py::str` from `std::string`, a value boxed per write, and `("walk_offset", walk, system)` for the marker | host_bindings.cc:10665-10737 |
| K2 | Same encoding (`K2Write`, k2_beams.h:377-381): `_dwell`, plus the offline stop's `_fire_held`, `_held_target`, `_held_offset`, `_target_list` (`[]`), `_last_group_fired`, and per bank `_firing`, `_beam_on_countdown` | k2_beams.cc:248-334 |

### 4.2 Python apply

| Item | Detail | Site |
|---|---|---|
| `apply_writes(writes, walk)` | in order; on a raise, applies the rest (`_apply_rest`) and re-raises | NC:2764-2810, 2826-2843 |
| `_apply_write` | `walk.obj(h)` (pins dict, else `_registry` WeakValueDictionary, checked `_nslot == h`); `_quiet_setter(type(obj), field)` (cached per (cls, name)); a ref → object; a ref list → a NEW list of objects; the walk-offset marker → `walk.materialise` (calls `_live_held_offset()` once per walk) | NC:2813-2823, 2635-2722, 2727-2761 |
| Quiet setter | NativeField/ref/plain: `obj.__dict__[name] = value`. NativeWrapped: the passive base's `__set__` (WakeField or ThawParentWakeField), so wake and thaw still happen. NativeSlotMap is refused. | NC:2727-2761 |
| Callers | `run_k1` per record (NC:2984-2986); K2 `run_k2` (`_k2_deliver` until the presentation queue, 2026-11-02) | NC:2934-3027, 3634-3776 |

### 4.3 Handles and registry

| Item | Detail | Site |
|---|---|---|
| Handle | int64 = index, generation << 32, kind << 60; stale handles throw `invalid_argument` (ValueError) | mirror.h:22-28 |
| Object → handle | `obj.__dict__["_nslot"]` | NC:342-346, 957-959 |
| Handle → object | `_registry` (WeakValueDictionary) and K1/K2 walk pins | NC:65, 2635-2722 |
| Registration | `register(obj, kind)` in `__init__` (rows exist whenever bindings are built, even with the switch off; pushes only when enabled); finalizer unregisters | NC:945-973, 999-1005 |
| Switch-on resync | `configure` → `resync()` pushes every row | NC:114-132, 1942 |
| Python id | Object rows carry `py_id` (K3/K4 name objects back by it) | mirror.h:146-149 |

### 4.4 Mirror storage and read-back

| Item | Detail | Site |
|---|---|---|
| Storage | `Table<T>{rows, gen, live, free}` per kind; SubsystemRow is a flat struct, one member per Field | mirror.h:399-449, 169-227 |
| Setters | `set_f/i/ref/ids/fv/id_lists`, each does `++epoch_` (no consumer of `epoch()` besides the `combat_epoch` binding) | mirror.cc:627-700; host_bindings.cc:9958 |
| Field types | `F, I, Ref, Ids, Vec3, Spheres, Rows, IdLists`. No list-of-doubles type (needed for `_reload_timers` / `_reload_advanced_at` if mirrored) | mirror.h:39-41 |
| Typed C++ getters | `get_f, get_i, get_ref, get_ids, get_fv, get_id_lists` (refs re-checked: stale reads -1) | mirror.h:369-375 |
| Python read-back | only `combat_dump(h)`: a dict of **every** field of the row (plus pose/slot extras). Also used as the liveness probe `_live`. No single-field getter binding. | host_bindings.cc:9985-10066; NC:442-447 |
| Name ↔ id | `combat_field_names()` → `_fid(key)` cache | NC:319-324 |

## 5. Switch-off and audit paths

| Path | What it does | Site |
|---|---|---|
| Switch off (`DAUNTLESS_NATIVE_COMBAT` unset or 0) | `NativeField.__set__` = dict store + `if _enabled` (false). Reads are dict reads. `_advance_weapons`, the K1/K2 Python bodies and `_pump_held_system` run unchanged. Behaviour must be byte-identical (roadmap §2, round-trips spec §3). | NC:474-479; HL:928-945, 986-1019 |
| Passive switch | `DAUNTLESS_PASSIVE_STATE=0` → `step_every_weapon` every tick (independent of the native switch) | PS:14-18; HL:942-945 |
| `DAUNTLESS_NATIVE_AUDIT=1` | implies native on. At the end of every `GameLoop.tick`, `audit_mirror()` compares every live row with its Python object: flags (`_flags`), property values, pulse module params, `py_id`, every Native field **present in `__dict__`** (`if attr not in d: continue`), hidden refs, sets, poses, slots, torpedoes, globals. Floats compare by `.hex()`, refs by handle, lists by handle lists. | loop.py:112-116; NC:2365-2427 |
| Audit + the kernels | Sensor queries run both paths and record differences (sensor_detection.py:289-888). K2, K3 and K4 run whole in Python under audit (reason "audit"). K1 has **no** audit path (roadmap §8 "the K1 audit gap"; no `_audit` read in `k1_pump`/`k1_system`, NC:3030-3071). | NC:65-67 |
| Passive audit + native | `PS._restore` writes `__dict__` directly, which leaves the mirror on the audited step's value; `audit_mirror` would flag it if both audits ran together | PS:74-87 (comment) |
| Differentials | `test_passive_weapons_differential.py` records `(GetChargeLevel, IsFiring, _depleted, _cooldown_remaining)` and `(GetNumReady, tuple(_reload_timers))` per tick and compares with `==` (**not** `.hex()`), plus the ET_TORPEDO_RELOAD / ET_WEAPON_FIRED / ET_CHARGE_TOGGLE event log (:90-108, :159-167). The K1 differential compares the logged fields from `__dict__` with `.hex()`, list newness, offset identity and asleep state (:414-460). | |
| Native test files | integration: native_can_detect, native_combat_step, native_k1, native_k3, native_posed differentials; host: native_beam_trace, native_combat_scene_audit, native_k2, native_k3, native_posed; unit: 14 `test_native_*` files incl. `test_native_combat_weapons_mirror.py`, `test_native_k1_holds_gil.py` | `ls tests/*/` |
| Test reset | conftest `_reset_leakable_engine_globals`: `native_combat.reset()`, `combat_clear()`, `forget_rows()`; `passive_state.reset()` | tests/conftest.py:942-967 |
| Tests that patch the walk | `monkeypatch.setattr(PhaserBank, "UpdateCharge", …)` and `TorpedoTube.UpdateReload` | tests/unit/test_passive_weapons.py:257-278 |

## 6. Determinism hazards for a bit-exact charging kernel

| # | Hazard | Evidence |
|---|---|---|
| D1 | Operand order: `_recharge_rate * power_factor * condition_factor * dt` is left-associative; drain is `charge - rate_ps * dt`; then `max(0.0, …)`, `min(want, headroom)`. `-ffp-contract=off` and `py_min`/`py_max` (first argument wins ties and NaN) already exist. | WS:961-962, 998-1000; py_math.h:21-27; native/src/combat/CMakeLists.txt |
| D2 | NaN: `max(0.0, NaN power)` → 0.0; `min(1.0, NaN cond)` → 1.0, so a NaN condition reads as FULL condition; `headroom > 0.0` is false for NaN; a NaN tube factor passes `factor < 0.0` and makes `prog` NaN forever (never `>=` delay); a NaN `game_dt` passes the `< 0.0` clamp. | WS:988, 830, 997, 3601, 3609 |
| D3 | Signed zero: `max(0.0, -0.0)` → +0.0 (first argument). The differentials compare `.hex()` (K1) but the passive differential uses `==`, which does not see −0.0. | WS:961; test_passive_weapons_differential.py:159-167 |
| D4 | dt accumulation cannot be batched: `_beam_on_countdown -= dt` and `_cooldown_remaining = max(0.0, c - dt)` are stepped per tick; recharge adds per tick; `dt` = `1.0 / 60.0` (HL:11708) or `TICK_DELTA = 1.0 / TICK_RATE` in tests (loop.py:8). Same double (inferred: 60 → 60.0). | WS:959, 2961, 1000 |
| D5 | Tube clock: `now` is read once per `UpdateReload` call (per tube); progress is a game-clock delta. In a multi-tick frame every inner step sees the same `now`, so the first inner step credits the whole interval and later ones credit 0 (inferred from §1.1). One ReloadTorpedo attempt per call; ties go to the first index (strict `>`); `_sync_slots_to_num_ready` uses a stable sort with `reverse=True`. | WS:3603-3616, 3645-3651, 3226-3235 |
| D6 | Power factor timing: weapons read `_power_factor` written by the power pump in `gl.subsystems`; in a multi-tick frame that is the LAST GameLoop tick's value for all N inner steps (inferred from `advance_ticks` order). The mirror holds the latest push, which is the same value. | loop.py:112; HL:12350, 12608-12617 |
| D7 | Iteration order: ships in `_ships_this_tick` order; groups phaser → pulse → tractor → torpedo; children by `GetWeapon(i)`; with passive on, the sorted awake list with by-value `bisect_right`; a mid-walk wake joins this tick only if its index > `last`. With passive off, `GetNumWeapons()`/`GetWeapon(i)` are re-read live per group. | PW:62-66, 113-130, 156-170 |
| D8 | Events relative to the walk: ET_TORPEDO_RELOAD and ET_CHARGE_TOGGLE dispatch synchronously before the next weapon steps. Their handlers may read later weapons (pre-step values), call `SetStatus` → `ConditionChanged` / `ET_AI_CONDITION_CHANGED` (AI Python), and could StartFiring (a nested K1 system session reading the mirror's charge) (inferred: no such stock handler traced end to end). | events.py:802-842; ai.py:76-105; SDK ConditionPulseReady.py:169-192 |
| D9 | Type coercion: the tube factor accepts any `int`/`float` (bool included). The mirror pushes `float(value)`, and a non-number drops the row (the kernel then falls back). Python stores bool for `_firing`/`_depleted`; the passive audit's `_unchanged` compares `type(now) is type(orig)`. | WS:3601; NC:487-492, 506-510; PS:93-102 |
| D10 | Watcher update order: the pulse watcher receives `GetChargePercentage()` AFTER the cooldown and charge writes, every awake tick. Crossings compare the stored `_value` (old) with the new value against each check, iterating a snapshot of `_checks.values()` in insertion order. | WS:2959-2969; float_range_watcher.py:96-118 |
| D11 | `_ensure_slots` self-heal rebinds both slot lists (all loaded) when `_max_ready` and the list lengths disagree. This can happen on the first `UpdateReload` after a direct `_max_ready` write. | WS:3181-3192 |

## 7. Open questions and hazards

### (a) Charging and reloading as a native kernel

| # | Question / hazard | Evidence |
|---|---|---|
| A1 | Unmirrored inputs need mirror fields or a fallback: `_recharge_rate`, the PhaserSystem `_power_level` plus the discharge table, the tractor parent's `_efficiency` and `_normal_power` (FrozenFields: a native mirror needs NativeFrozenField and a push), and the tube slot lists plus `_reload_delay` (a new float-list FieldType). | §1.3-1.7 |
| A2 | Python effects mid-walk under ruling P1: depletion StopFiring (sound), tractor StopFiring (sound plus power program thaw), ET_TORPEDO_RELOAD, pulse watcher crossings. Each is a point where Python must run with the weapons EARLIER in the walk already stepped and LATER ones not. A batch "all ships, then events" order would change what handlers read. | §1.8, D8 |
| A3 | The pulse watcher is a Python object. Its `_value` is read by `GetWatchedVariable` (SDK conditions) and by the passive audit. A native kernel either keeps it updated every tick, which is a Python call per awake pulse weapon, or makes it lazy, which changes when the crossing is detected (open). | WS:2969; float_range_watcher.py:86-89 |
| A4 | The awake set and registry are Python. Wakes come from WakeField writes everywhere: Python setters, K1/K2 quiet setters, SDK `SetChargeLevel`. A native walk needs the same awake set in the same order, including the mid-walk wake rule. Whether native derives "awake" from pushes of WakeFields is open; pushes happen only while enabled. | PW; NC:680-688 |
| A5 | The passive audit runs the Python update on sleepers and restores the dict, behind the mirror. With native charging it would compare a Python step against nothing native, or desync the mirror. | PW:171-175; PS:74-87 |
| A6 | Override guard: the update reaches `UpdateCharge`, `UpdateReload`, `_discharge_rate_per_second`, `GetParentSubsystem`, `IsOn`, `GetNormalPowerPercentage`, `GetPowerPercentage`, `GetNormalPowerWanted`, `GetConditionPercentage`, `GetMaxCondition`, `GetPowerLevel`, `StopFiring`, `GetChargePercentage`, `_passive_at_rest`, `_ensure_slots`, `ReloadTorpedo`, `_reload_denied_by_ammo`, `_parent_ammo`, `GetCurrentAmmoType/Slot`, `GetAvailable`, `_rounds_loaded_systemwide`, `GetNumReady`, `_broadcast_reload`. Tests class-patch `UpdateCharge`/`UpdateReload` (test_passive_weapons.py:257-278); SWIG exposes `UpdateCharge`/`ReloadTorpedo`. None of these are in `_K1_LEAF_METHODS` today (NC:1044-1049) except `GetConditionPercentage`, `GetParentSubsystem`, `StopFiring`, `IsFiring`. | *(2026-11-02, fire-events phase: `StopFiring`, `_broadcast_reload` and the watcher's `_update` are now K0 stand-ins too, guarded; see weapon-state spec W9's superseded note.)* |
| A7 | Ships without a registry (non-ShipClass, non-WeaponSystem groups) take `step_every_weapon`. Those are the test doubles and fakes the kernel must hand to Python. | PW:87-99, 143-149 |
| A8 | The split of `sim.weapons` 0.77 ms/tick (pushes vs Python stepping vs events vs registry bisect) is **not measured**. Neither is the count of awake weapons per tick in the 64-ship fight. SIG-161's +39% with native on is inferred to be pushes. | perf-register SIG-161, SIG-148/149 |
| A9 | Ordering with K1: charging runs before `cb.held_weapons` in each tick, so K1 reads post-recharge charge from the mirror. An AI `StartFiring` in `gl.ai` (before charging) reads the PREVIOUS step's charge. Both orders must hold. | HL:12616-12626; WS:1500-1536 |
| A10 | `_game_time()` failure gives 0.0 plus a log. A native kernel takes `now` from Python per step (as K1 does), and this fallback stays Python's. | WS:53-77; NC:2623-2632 |
| A11 | Tube `UpdateReload` does not check `IsOn()`; the energy recharge does. A port must keep the asymmetry. | WS:3590-3592 vs 986-987 |

### (b) Native-owned logged fields (Python reads lazily)

| # | Question / hazard | Evidence |
|---|---|---|
| B1 | No `__get__` exists on NativeField by design. A lazy read needs one (precedents: `PosedPartsField`, `HullBoxField` with `__get__` over `__dict__`). That puts a descriptor call on every Python read, including with the switch off, unless the class attribute differs by switch (open). | NC:459-463, 750-772, 775-800 |
| B2 | Direct `__dict__` readers bypass any `__get__`: `audit_mirror` (`attr not in d` skips silently, so the audit goes blind for an absent field), passive `audit_step`/`_snapshot(vars(obj))`, `_repush_field`, the quiet setter (writes `__dict__`), the K1/K2 differentials and dispatch tests (`d.get("_fire_timer")` etc.), `tests/helpers/k3_fight.py`, and `_pump_held_system`'s `getattr(sys_, "_fire_held", False)` (a `getattr` does go through `__get__`). | NC:2405-2414; PS:118-130; tests listed in §3.1 |
| B3 | Python copies run with the switch on: tractor systems are always RUN_PYTHON; ASK answers and handed-back walks run `try_fire_weapon`/`update_weapons`/`Fire` on live objects. Before they run, every native-owned field they read must be current in Python. After them, their writes must reach native: today the descriptor push does that. | k1_fire_control.h:180; NC:2880-2931, 2984-3006 |
| B4 | Python writers outside the kernels (§3.2) must write through to native: StartFiring's in-place `_target_list.append` + `push_field`, StopFiring's new `[]`, SetForceUpdate, `_charge_gate`'s `_depleted=False` (SDK CanFire), UpdateCharge's `_depleted`/`_beam_on_countdown`, and the fire effects. | WS:1423-1426, 1540-1549, 1385, 863-866, 959-970 |
| B5 | Identity: `_target_list` must be a NEW list object after every prune or stop, and the same object for an `_add_target` append that follows. `_target_offset` must be the walk's offset OBJECT (P5), possibly aliasing `_held_offset`. A lazily built Python value has to reproduce both (open: cache per write, or per walk). | §3.1; NC:2649-2668 |
| B6 | Wake and thaw: `_firing` writes must still wake a sleeping bank (and thaw/drop the tractor parent's power program on a change). Today the quiet setter does this in Python per logged write. A native-owned `_firing` still needs that Python-side effect (or a native awake set, A4). | NC:2727-2761; passive_power.py:98-125 |
| B7 | Hot readers: the render builders read `IsFiring()` and `_target` for every bank of every in-view ship per frame; `tractor.advance_tractors` reads per tick; `_spawn_projectile` per launch; the weapons display per frame for the player; the power pump's `_any_child_firing` per tick for unfrozen tractors. A lazy read per access could cost more than the write-back saved (not measured). | HL:2486-2551; tractor.py:112-133 |
| B8 | Types: Python stores real `bool` for `_firing`, `_force_update`, `_depleted` and the kernels log bool. A value read back from an int64 row must come back with the same Python type (`_unchanged` compares types; tests use `is True` style checks via `_t`, inferred). | k1_fire_control.cc:311-316; PS:93-102 |
| B9 | Rollback: K1/K2 undo only the writes not yet returned. With native-owned fields the mirror is the only copy, so `abandon()` after a Python raise mid-record leaves nothing to compare against (open). | k1_fire_control.h:87-99; NC:2764-2843 |
| B10 | Row drop: `_drop(obj)` makes an object take the Python path (an unencodable value). A native-owned field on a dropped row would have to be materialised into `__dict__` first, or its value is lost (inferred). | NC:349-380 |
| B11 | Mission swap and fresh world: rows die with their objects (finalizer), and `combat_clear`/`forget_rows` drop all handles in tests. Native-owned values then vanish with no Python copy (inferred hazard for tests that read fields after a clear). | NC:976-1005; tests/conftest.py:957-967 |
| B12 | Write-log cost today: per write, one tuple, one `py::str` field name and one boxed value in the binding, plus `_apply_write` (two dict lookups, a ref map, a setter call). Which part of the 0.35 ms is binding construction and which is apply is **not measured**. | host_bindings.cc:10679-10697; NC:2813-2823 |
| B13 | No save path exists today, but `__dict__`-walking serialisation is the stated assumption (39 SDK classes round-trip via `__getstate__`). Native-owned fields would be invisible to it. | subsystems.py:2101-2106 |

## Could not establish

- The count of awake weapons per tick, and the internal split of `sim.weapons`, in the 64-ship fight (not captured; A8).
- Whether any stock or SDK handler of ET_TORPEDO_RELOAD or ET_CHARGE_TOGGLE ends up in `StartFiring` synchronously (only traced to `SetStatus` and `ET_AI_CONDITION_CHANGED`; D8).
- The frequency of `IsInTargetList`, `GetNumAvailableTorpsToType` and `CanFire` from AI in the fight (per AI update, with an AI-tree sleep of up to 4 ticks; not counted).
