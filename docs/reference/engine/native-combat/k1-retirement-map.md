> **Built 2026-11-03** (branch `ws/native-default`). The Python fire-control copy this map describes is deleted, along with its guards, the walk check, the launch check, the Manual Aim slot and the bake. Tractors and the SDK routes are native, and the switch defaults on. Read the spec's outcome for what was built and ruled: `docs/superpowers/specs/2026-11-03-fire-control-native-only-design.md` §6. The map below is the pre-build snapshot and is not updated.

# K1 retirement — code map (switch default ON, fire control's Python copy deleted, tractors ported, aim simplified)

> Snapshot map, written 2026-11-03 on branch `ws/native-default` (worktree `native-combat-k3`, HEAD `2369cba41`, off `project/combat_threading`). Read only; nothing was changed. Line numbers are of that tree. Input to the spec for roadmap workstream **E** (`docs/superpowers/specs/2026-11-01-threaded-weapons-combat-roadmap.md` §4 E, decisions 1-2). Mark's phase decisions (2026-11-03) are quoted as **D1-D7** below in the order of the brief: D1 switch default ON; D2 native module required for fire control; D3 Python copy and its guards deleted (roadmap decision 2); D4 tractors ported; D5 aim simplification (non-mount offset = plain body xyz, box rule out of aiming, ruling C4 reversed); D6 defensive hand-backs → "does not fire that tick, logged once"; D7 differentials → recorded golden fights.
>
> Everything is read off the code unless marked **inferred**. Counts come from the documents cited at each row; none was re-measured for this map.

Abbreviations (as `remaining-fallbacks-map.md`): **NC** `engine/appc/native_combat.py`, **WS** `engine/appc/weapon_subsystems.py`, **HL** `engine/host_loop.py`, **GL** `engine/core/loop.py`, **PR** `engine/appc/projectiles.py`, **PS** `engine/appc/part_severance.py`, **SUB** `engine/appc/subsystems.py`, **ART** `engine/appc/articulation.py`, **TR** `engine/appc/tractor.py`, **EQ** `engine/appc/effect_queue.py`, **K1C/K1H** `native/src/combat/{src/k1_fire_control.cc,include/dauntless/combat/k1_fire_control.h}`, **K0C** `k0_charging.cc`, **K2C** `k2_beams.cc`, **WG** `weapon_geometry.cc`, **BG** `beam_geometry.cc`, **PG** `projectile_geometry.cc`, **PP** `part_pose.cc`, **MIR** `mirror.{h,cc}`, **HB** `native/src/host/host_bindings.cc`. **SDK** = `/Users/mward/Documents/Star Trek Bridge Commander/sdk/Build/scripts/`.

---

## 0. Headline

1. **The switch is a single global** read in `configure()` (NC:158-176: on only for `DAUNTLESS_NATIVE_COMBAT=1` or the audit, AND `available()`), called by `GameLoop.__init__` (GL:33). It gates fire control **and** K0, K2, K3, K4, native damage, the effect-queue scope and the step scan. Deleting K1's Python copy therefore removes the **OFF arm of every other kernel's differential** too (§5.1), unless the switch is split per kernel.
2. **`conftest` turns the switch off before every test** (`tests/conftest.py:955-962` → `nc.reset()` sets `_enabled = False`, NC:187-190). Today about 30 test files fire weapons without any `configure()` and so run the Python copy (§5.2). After D3 there is no Python fire control for them to run. D1 ("on unless `=0`") changes nothing for them unless `_enabled` stops being a per-test reset value (§7 R1).
3. **Three routes into Python fire-control decisions are outside K1 and not counted by any K1 counter:** the SDK's `pTube.FireDumb(0, 1)` (SDK `AI/Preprocessors.py:458`, routine at AI `Difficulty 0.0`), the SDK's `pBank.CanFire()` (SDK `AI/PlainAI/PhaserSweep.py:175`, `Conditions/ConditionInPhaserFiringArc.py:175`), and the tractor's own `TractorBeamSystem.StartFiring`/`update_weapons`/`_engage_beam` → `emitter.Fire` (WS:2724-2883). See §2.6.
4. **Tractors never reach K1's kernel today**, and no K1 test covers them: the K1 differential drops the tractor system from its firing set (`tests/integration/test_native_k1_differential.py:174-175`). The tractor force is not a spring-damper (CLAUDE.md's OQ-2.3 line is inaccurate): it is a mass-capped kinematic displacement written straight into the transform store (`SetTranslateXYZ`) from `cb.tractors` on the Python thread (TR:80-110, HL:1448-1456). See §3.
5. **The aim simplification is not K1-only.** The box rule sits in the Python `subsystems.target_offset_world` (SUB:96-131), `projectiles._bake_offset` (PR:1110-1124) and Manual Aim's pull-back (`engine/manual_aim.py:198-204`). K2 and K3 keep their Python copies this phase, so those Python functions have to change with the native ones, or the K2/K3 differentials stop matching. See §4.6.

---

## 1. The Python copy today

### 1.1 Where the switch-off path runs instead of native

| Site | file:line | Switch-off path | Switch-on path | After this phase |
|---|---|---|---|---|
| `configure()` | NC:158-176 | unset / `0` → off; also off if `not available()` or `_self_check()` fails (NC:415-450) | `=1` or audit → on, `resync()` | D1: on unless `0`. D2: `not available()` / a failed `_self_check` must be an error, not a silent off (§7 R3) |
| `GameLoop.__init__` | GL:33 | — | calls `configure()` | unchanged; it is the only caller in the engine |
| `GameLoop.tick` | GL:43, 122-126, 136 | — | `refresh_stale_pulse_params`, audit, `drain(boundary=True)` | unchanged |
| `host_loop._combat_effect_scope` | HL:958-969 | `nullcontext()`: every weapon producer acts at once | `effect_queue.scope("sim.effects")` | must always open: K1's native effects are queue entries |
| `host_loop._combat_tick_boundary` | HL:972-997 | boundary timed as `sim.effects` | boundary untimed (scope delivered) | collapses to one branch |
| `host_loop._advance_weapons` (K0) | HL:929-955 | `passive_weapons.advance` / `step_every_weapon` | `k0_weapons` | K0 is not retired this phase; its OFF path stays as long as the switch can be `0` |
| `host_loop._pump_held_weapons` (K1) | HL:1036-1064 | loop at HL:1062-1064 over `_PUMP_GETTERS` (HL:1067-1068) → `_pump_held_system` (HL:1071-1093) | `k1_pump` with `_pump_held_system` as `pump_body` (HL:1050-1060) | **DELETE** the OFF loop and `pump_body` (§1.3) |
| `WeaponSystem.StartFiring` (K1 system session) | WS:1766-1771 | `self.update_weapons(0.0)` | `native_combat.k1_system(self, 0.0)` | **DELETE** the OFF branch |
| `k1_system` no-row branch | NC:4249-4256 | — | a system with no Subsystem row runs `system.update_weapons(dt)` | D6 (§2.5) |
| step scan | HL:1370-1371 | skipped | `step_scan(ships_list)` | unchanged (K3/K4) |
| K4 | `engine/appc/damage_eligibility.py:111` | `select_eligible` | `k4_update` | unchanged |
| K3 | PR:909-910 | Python `update_all` body | `run_k3` | unchanged (but §4.6) |
| K2 | HL:1442-1446 | `_phaser_step_ship` per ship | `k2_phasers` | unchanged (but §4.6) |
| native damage | `engine/appc/combat.py:626-629` | Python `_apply_hit` | `native_combat.apply_hit` | unchanged |
| tractors | HL:1448-1456 | `tractor.advance_tractors` | same (no native path) | D4 (§3) |

`GameLoop.tick` does **not** run the combat step (GL:36-137): headless harnesses (`tests/helpers/headless_mission.py:77-91`, `tools/gameloop_harness.py:119-120`) run K1 only through StartFiring's system sessions (`dt = 0.0`), never the pump, K2 or tractors. The host loop runs `_advance_weapons` and `_advance_combat` once per sim tick inside the effect scope (HL:12687-12707).

### 1.2 Fire control's Python decision code (`weapon_subsystems.py`)

"Native" names the C++ twin. **KEEP** means something other than the Python copy needs it; the caller is named.

| Python | file:line | Verdict | Native equivalent / the caller that keeps it |
|---|---|---|---|
| `WeaponSystem.update_weapons` | WS:1913-1984 | **DELETE** once tractors are ported (the tractor class overrides it, WS:2792) | K1C walk states `UW_*` (`Walker::run`, K1C:1187-1700). Engine callers today: `_pump_held_system` HL:1077, 1093; `StartFiring` WS:1771; K1 driver NC:4180, 4207 (RUN_PYTHON / skip_walk); `_k1_answer` none. No SDK call site (it is not SWIG surface) |
| `WeaponSystem.try_fire_weapon` | WS:1835-1872 | **DELETE** | K1C `TF_*` states (K1C:1490-1690). Callers: `update_weapons`, `_k1_answer` `group_step` NC:4086 |
| `FIRE_TIMER_THRESHOLD` | WS:1833 | **DELETE** (move the constant into the kernel's globals if not there) | **inferred**: pushed via `_WEAPON_CONSTANTS` (NC:2832) |
| `_firing_weapon`, `_reseed_all_fire_timers`, `_fired_counter`, `_weapon_did_fire` | WS:1874-1911 | **DELETE**. `_fired_counter`/`_weapon_did_fire` exist only for test fakes' `fired` counters (WS:1889-1911) | `fired_bookkeeping` K1C:783-806; ASK `reseed` |
| `_prune_targets`, `_active_chain_groups`, `_resolve_working_group` | WS:1661, 1639, 1648 | **DELETE** `_prune_targets` and `_resolve_working_group` (only `update_weapons` calls them). `_active_chain_groups` **KEEP** while `SetFiringChainMode` (WS:2432-2456) calls it | `active_chain_groups` K1C:768-778 |
| `WeaponSystem._live_held_offset` | WS:1788-1801 | **DELETE** after the tractor port (TractorBeamSystem.update_weapons WS:2845 and `_K1Walk.materialise` NC:3734 call it) | `k1_live_held_offset` K1C:1815-1840 (def at 1827) |
| `_EnergyWeaponFireMixin.Fire` / `_fire_decide` / `_fire_effect` | WS:1070-1109 | `_fire_decide` **DELETE** (after tractors). `_fire_effect` **DELETE** (K1 logs it: K1H:83-87). `Fire` — see §2.6: SWIG `Weapon.Fire` (SDK `App.py:5784`), zero stock SDK call sites; the tractor `_engage_beam` calls it (WS:2868, 2881) | beam edge/sustain writes K1C:1560-1585 |
| `_EnergyWeaponFireMixin._aim_in_arc` | WS:1005-1016 | **DELETE** with `_fire_decide` | `_emitter_in_arc` port in WG |
| `_EnergyWeaponFireMixin.CanFire`, `_charge_gate` | WS:1018-1068 | **KEEP** (SDK): `AI/PlainAI/PhaserSweep.py:175`, `Conditions/ConditionInPhaserFiringArc.py:175`. `_charge_gate` writes `_depleted = False` as a side effect of that SDK read (WS:1064-1067). Leaves a second copy of the rule (§2.6, §7 R6) | `can_fire` `fire_gates.cc` |
| `_EnergyWeaponFireMixin.StopFiring` | WS:1111-1126 | **KEEP** (SDK `StopFiring`: 16 SDK call sites, e.g. `TacticalControlHandlers.py:135`, `AI/Preprocessors.py:173`; engine cloak/dewarp stops SUB:3457-3467, SUB:2068-2080) | `stop_firing.h` (logged) |
| `PhaserBank._fire_effect` | WS:2924-2932 | **DELETE** | beam edge `WEAPON_FIRED` entry K1C:1578 |
| `PulseWeapon.Fire` / `_fire_decide` / `_fire_effect` | WS:3145-3246 | **DELETE** `_fire_decide`, `_fire_effect`; `Fire` as the mixin's (§2.6) | `decide` pulse branch + `plan_pulse_launch`/`log_pulse_launch` K1C:1040-1095 |
| `PulseWeapon._shot_cost`, `_charge_gate`, `CanFire` | WS:3122-3143 | `CanFire` **KEEP** (SDK CanFire is called on banks; on a cannon **inferred** reachable via `ConditionInPhaserFiringArc` only for phaser banks, so possibly dead). `_shot_cost` **KEEP** while K0/K1 C twins cite it as reference; no other Python caller (WS:3138, 3239) | `pulse_shot_cost` |
| `_solve_pulse_launch_direction` | WS:565-629 | **DELETE** (only caller `PulseWeapon._fire_decide` WS:3192) | WG:331-372 |
| `TorpedoTube.CanFire` | WS:3651-3689 | **KEEP** as the method `FireDumb` → `Fire` reaches from the SDK (§2.6) and that UI/AI may read (**inferred**; no stock SDK `CanFire` on a tube) | `can_fire` |
| `TorpedoTube.Fire` / `_fire_decide` / `_fire_effect` | WS:3691-3765 | **DELETE** `_fire_decide`/`_fire_effect` only if the SDK `FireDumb` route is ported (§2.6) | `decide_tube` + `plan_launch`/`log_launch` K1C:880-1140 |
| `_resolve_torpedo_aim_point`, `_in_torpedo_cone` | WS:3357-3405 | **DELETE** (callers: `_fire_decide` WS:3722, 3726). `manual_aim.py:146`, HL:1102, SUB:110 mention it only in docstrings | WG:285-329 |
| `TorpedoTube._spawn_torpedo`, `_start_slot_cooldown`, `_broadcast_weapon_fired`, `_broadcast_ammo_consumed_if_player` | WS:3837-3900, 3498, 3767, 3811 | `_spawn_torpedo` **DELETE** with `_fire_effect`. `_broadcast_*` **KEEP**: the effect queue's deliveries call them (EQ:28-31, 636-649) | `log_launch` K1C:1114-1145 |
| `TorpedoTube._broadcast_weapon_fire_failed` | WS:3775-3809 | **KEEP** (EQ:29, 641 deliver it; `TorpedoSystem.StartFiring` WS:2146) | `WEAPON_FIRE_FAILED` entry |
| `Weapon.FireDumb` + `_dumb_firing` | WS:1421-1452, 886 | **KEEP** (SDK: `AI/Preprocessors.py:458`, SWIG `App.py:5785`); see §2.6 | `dumb_fire` K1C:1151-1185 |
| `_spawn_projectile`, `_launch_reads`, `_defer_spawn` | WS:631-746 | `_defer_spawn` **DELETE** with Python's launches (callers WS:3209-3223, 3890). `_spawn_projectile`/`_launch_reads` **DELETE** once no Python launch remains (only `_spawn_torpedo` WS:3892 and the non-deferred cannon branch WS:3228 call them) | K1 `launch_reads` K1C:984-1040 |
| `_new_projectile`, `_launch_projectile`, `spawn_launch`, `_play_launch_sound` | WS:748-886 | **KEEP**: the SPAWN delivery (EQ:665-666 → `spawn_launch` WS:843) | — |
| `_post_weapon_fired`, `_play_fire_sfx`, `_stop_loop_sound` | WS:889, 1223, 1128 | **KEEP**: EQ deliveries (EQ:628, 636-637) | — |
| `_target_undetectable`, `_can_engage`, `_target_within_range_gu`, `_cloak_blocks_fire`, `_dewarp_blocks_fire` | WS:1334, 2553/2601/2786, 2506, 1288, 1322 | **KEEP**: `StartFiring`'s gates (WS:1745-1759, 2733-2742), cloak (SUB:3457). Their pump use (HL:1086-1090) goes with `_pump_held_system` | `pump_stops` K1C:739-761 |
| `_resolve_bank_aim_world`, `_emitter_in_arc`, `_resolve_aim_world` | WS:105, 167, 80 | **KEEP**: K2's Python copy (HL:1210-1212), UI (`engine/ui/weapons_display_panel.py:280-299`, `engine/ui/phaser_overlay.py:94, 112`), tractors (WS:2833-2878) | WG ports |
| `IsFiring`, `IsMemberOfGroup`, `IsDumbFire`, `GetNumTargets`, `IsInTargetList`, `GetFiringChains` | WS:1134, 1418, 1476-1491, 1808, 1669-1698, 1621 | **KEEP**: SDK `IsFiring` (5 sites, e.g. `Bridge/PowerDisplay.py:1024`), `IsInTargetList` (`AI/PlainAI/StarbaseAttack.py:114`); SWIG surface | — |
| `StartFiring`, `StopFiring`, `StopFiringAtTarget`, `SetForceUpdate`, `SetTarget`/`GetTarget` | WS:1733-1818 | **KEEP** (SDK: `TacticalControlHandlers.py:129-135`, `TacticalInterfaceHandlers.py:362-368`, `AI/Preprocessors.py:274, 465, 469`, `AI/PlainAI/StarbaseAttack.py:115, 132`, `Maelstrom/Episode3/E3M1/E3M1.py:2153-2155, 3288-3290`; `SetForceUpdate` SDK 3) | — |

The SWIG surface was checked against `SDK/App.py:5783-5882` (`Weapon.StopFiring/Fire/FireDumb/CanFire/IsFiring/IsMemberOfGroup/IsDumbFire`, `WeaponSystem.IsTryingToFire/IsFiring/CanFire/StartFiring/StopFiring/Fire`), not by `def` grep. Stock SDK call sites were counted with `grep -E "[.]<Name> *\("` over the SDK minus `App.py`: `Fire` 0, `CanFire` 2, `IsFiring` 5, `FireDumb` 1, `StartFiring` 6, `StopFiring` 16, `StopFiringAtTarget` 2, `SetForceUpdate` 3, `IsInTargetList` 1, `IsTryingToFire` 1, `GetTargetOffsetTG` 3, `UseTargetOffsetTG` 1.

### 1.3 `host_loop.py` pump

| Python | file:line | Verdict |
|---|---|---|
| `_pump_held_weapons` OFF loop | HL:1062-1064 | **DELETE** (D3) |
| `_pump_held_weapons` `pump_body` lambda | HL:1056-1060 | **DELETE** with RUN_PYTHON (§2.1) |
| `_PUMP_GETTERS` | HL:1067-1068 | **DELETE** (only the OFF loop and `pump_body` use it) |
| `_pump_held_system` | HL:1071-1093 | **DELETE**: its tractor branch HL:1076-1078 goes with D4; the gates are K1's `pump_stops` (K1C:739-761) |
| `_phaser_aim_point` | HL:1096-1115 | **KEEP** (K2 Python copy, tractor/phaser beam render HL:2455), but its Manual Aim branch changes (§4.6) |

### 1.4 `native_combat.py`: K1's guards, comparison scaffolding and driver

| Piece | NC line | What it is | Verdict |
|---|---|---|---|
| `_K1_LEAF_METHODS`, `_K1_SYSTEM_METHODS` | 1740-1763 | class names K1 stands in for → `k1_overridden` | **DELETE** (D3), but **K2 reads the flag** (K2C:388, 578, 794): K2's override guard depends on K1's (§7 R4) |
| `_K1_SYSTEM_PATCHES`, `_K1_LEAF_PATCHES`, `_K1_SHIP_PATCHES` | 1772-1781 | instance-patch names for the bindings' walk check | **DELETE** |
| `_k1_ship_stock`, `_k1_walk_check_sent`, `_k1_stock`, `_k1_overridden_by_type`, `_k1_watch` | 1784-1792 | snapshots and caches | **DELETE** |
| `_k1_resolve`, `k1_snapshot_stock`, `_k1_raw`, `k1_snapshot_ship`, `_k1_send_walk_check`, `_k1_overridden`, `_k1_recheck_overrides` | 1795-1909 | the override guard (called at WS:4135-4137, `ships.py:1958`) | **DELETE**; `_k1_send_walk_check` also sends the launch check and the pulse-module list (NC:1844-1849) — the pulse-module list is not pure scaffolding (§2.4 `Unresolved`) |
| `_flags`: `k1_overridden`, `pump_self_managed` | 1973-1975 | per-row flags | `k1_overridden` **DELETE** only with K2's guard (R4). `pump_self_managed` **DELETE** with D4 |
| `_K1_LAUNCH_FUNCS`, `_k1_launch_mods/_stock`, `k1_snapshot_launch`, `_k1_launch_funcs`, `_k1_launch_funcs_names`, `_k1_launch_check`, `launch_patched` | 2527-2576 | launch-function patch guard (K1LaunchWhy::Patched) | **DELETE**; `launch_patched` is read by WS:3218, 3885 (Python launches, deleted too) |
| `_manual_resolved`, `_manual_slot`, `_resolve_manual_slot`, the manual branch of `resolve_stale_part_slots`, manual parts of `_forget_part_caches` | 2264-2316, 2230-2232, 2060, 2064 | Manual Aim slots | **DELETE** (D5, §4) |
| `_audit_manual_slot` | 3421-3443 (called 3418) | audit of the manual slot | **DELETE** (D5) |
| `_k1_compute`, `_k1_compute_enter/exit` | 3628, 3647-3674 | K1 compute timers (nesting) | **KEEP** (native sessions still nest: an effect delivery may StartFiring) |
| `_k1_kinds` | 3681-3688 | record kinds | **KEEP**, trimmed to the kinds left |
| `_k1_clocks` | 3691-3700 | clocks | **KEEP** — K2 (NC:5484) and K3 (NC:5965) use it |
| `_K1Walk` | 3703-3801 | pin set + materialise + `walk_start` | `walk_start` (3755-3776) **DELETE**. `materialise` (3717-3737) calls Python `_live_held_offset` for the offset object: **DELETE** with it, but the logged `("walk_offset", n, h)` write still needs an object (§7 R7). Base class of `_K2Walk` (NC:5098): pins **KEEP** |
| `_quiet_setter`, `apply_writes`, `_apply_write`, `_apply_rest`, `_ApplyKinds`, `_applier_context` | 3804-4005 | write apply; `apply_writes` is the Python reference of the C applier (`tests/unit/test_native_write_apply.py`) | **KEEP** (K0 and K2 apply through it) |
| `_k1_decision`, `_k1_pulse_module` | 4008-4041 | FIRE-record decision objects | **DELETE** (no FIRE record left) |
| `_k1_answer` | 4044-4095 | ASK answers on live objects | **DELETE** (D6) |
| `run_k1` / `_run_k1` | 4098-4224 | record loop: WALK_START 4169-4188, FIRE 4193-4196, BANK_STOP/STOP_SYSTEM 4197-4200, FIRE_DUMB 4201-4202, RUN_PYTHON 4203-4207, ASK 4208-4211 | **KEEP** the loop for `DONE` + compute + applier context; delete every branch but DONE (or a "log once" record, §2.7) |
| `k1_pump` | 4227-4246 | entry | **KEEP**; drop `_k1_send_walk_check`, `_k1_recheck_overrides`; keep `resolve_stale_part_slots` (mount slots) and `refresh_stale_pulse_params` |
| `k1_system` | 4249-4269 | StartFiring entry; no-row Python fallback 4253-4256 | **KEEP**; fallback → D6 |
| `_k1_system_ships` | 4272-4280 | ships for the slot sweep | **KEEP** |
| `counts()` K1 docstring/keys | 281-405 | `k1_python_systems`, `k1_python_reasons`, `k1_fire_ask_reasons`, `k1_launch_reasons` … | retire the Python-hand-back keys; add the D6 "no fire" counter |
| `_drop` | 491-538 | "From then on it takes the Python path" (NC:492-494) | **KEEP**, but its meaning changes: a dropped weapon system or ship never fires again (§7 R5) |

### 1.5 The C++ side that goes with them

| Piece | Where | Verdict |
|---|---|---|
| `K1Why` (RUN_PYTHON reasons), `K1Kind::RUN_PYTHON/WALK_START/ASK/FIRE/FIRE_DUMB/STOP_SYSTEM/BANK_STOP`, `K1LaunchWhy` | K1H:287-399 | trim; every reason becomes D6's counted "no fire" or goes (§2) |
| `prescan` | K1C:633-737 | keeps its checks; outcome "no fire, log once" instead of RUN_PYTHON |
| walk check, verdict sets, `k1_scan`, caches | HB:4786-5715 (`K1WalkCheckRefs` 4815-4828, `k1_scan` 5661-5704), `combat_k1_set_walk_check` HB:13420-13470 | **DELETE** (D3) |
| launch check / `K1_LAUNCH_PATCHED` | HB:4220-4264, `combat_k1_set_launch_check` HB:13500 | **DELETE** |
| `K1_PULSE_MODULE_STALE`, `combat_k1_set_pulse_modules` | HB:4237-4279, HB:13486 | not a patch guard: it notices a re-imported cannon module (§2.4) |
| `set_offset`, `skip_walk`, `answer` | K1H:493-503 | **DELETE** |
| `bake_offset` + `manual_slot_pose`, `PosedOffset` | K1C:1098-1112, PP:43-60 | **DELETE** (D5, §4) |

### 1.6 Shared pieces K1 does not own (KEEP)

`apply_writes` & co. (K0/K2), `_k1_clocks` (K2/K3), `_K1Walk` pins (K2), `resolve_stale_part_slots` mount half and `_heal_part_slots` (K2, K3, step scan: NC:5480, 2235-2246), `push_pulse_params` / `push_ammo_launch` / `_tube_launch_cache` (the native launch reads them), `push_mount_order`, pose tables.

---

## 2. Every route into the Python copy with the switch on

Classes: **DEL2** deleted by decision 2 (D3); **AIM** replaced by the aim simplification (D5); **NF** becomes "does not fire that tick, logged once" (D6); **PORT** ported (D4, tractors); **⚠ ELSE** not covered by the decisions — listed in §2.7.

Counts: R1 = 64-ship `combat_stress`, 8,999 ticks; R4 Felix 7,199; R5 16 ships 720 (`remaining-fallbacks-map.md` §2.2, measured 2026-11-01). "Posed diff" = posed differentials, 660 ticks (`2026-11-01-native-combat-posed-parts-design.md` §10). Re-verified against current code. Some of the K1C line numbers in the fallbacks map have moved.

### 2.1 Whole system → Python (`RUN_PYTHON`, `K1Why`, K1H:376-398)

| K1Why | Raised at (current) | Trigger | Class | Measured |
|---|---|---|---|---|
| `SelfManaged` | K1C:639-640 (prescan), K1C:1222-1224 (pump) | a held tractor (`pump_self_managed`), **or** a system whose kind is not phaser/pulse/torpedo (`leaf_kind_of(kind) < 0`, e.g. a plain `WeaponSystem` instance) | **PORT** (tractors); the non-K1-kind half is **NF** | 0 in R1/R4/R5 (no tractors in those scenes); never measured with tractors |
| `Overridden` | K1C:642, 707 | class override (`k1_overridden`) | **DEL2** | 0 |
| `InstancePatch` | counted at `skip_walk` (K1C:1792); Python decides in `_K1Walk.walk_start` NC:3755-3776 | instance attribute shadowing a K1 method | **DEL2** | 0 |
| `PosedShip`, `PosedTarget` | never raised (K1H:380-381 "retired") | — | delete the enum values | 0 |
| `PartStale` | K1C:718-721 | a posed ship's leaf slot not current at the prescan; slots are re-resolved at every K1 entry (`k1_pump` NC:4239, `k1_system` NC:4264) so only a slot whose resolution **raised** stays stale (`_part_slot` NC:2153-2173 returns None → stamp 0) | **⚠ ELSE** (not in the D6 list; such a ship would never fire, §2.7 #4) | 0 |
| `MountUnknown`, `NoMount`, `OffsetOffMount` | never RUN_PYTHON (K1H:383-388) — ASK-only | — | see §2.2 | 0 |
| `StubOrUnplaced` | K1C:653-665, 683-685 | no real `IsDead` / invalid transform | **NF** | 0 |
| `PulseShipTarget` | K1C:689 | pulse system, no live list entry (Python's `Fire(None)` would use `ship.GetTarget()`, WS:3175-3178) | **NF** | 0 |
| `PulseModule` | K1C:722-724 | module unresolved or power setting outside 0-2 | **NF** | 0 |
| `AmmoRow` | K1C:732 | ammo slot names no live Ammo row | **NF** | 0 |
| `StaleRow` | K1C:636, 649, 652, 657, 662, 674, 683, 695, 705, 712, 715, 1212 | unnamed (-2) or freed row | **NF** | 0 |
| `UnslottedShip` | K1C:1199 | pump ship with no Object row (passed as -1 by `k1_pump` NC:4241) | **NF** | 0 |
| `Gate` | K1C:1232 | `pump_stops` threw | **NF** | 0 |
| `Other` | K1C:698, 706, 708, 710 | structure (negative group, wrong child kind/parent/ship) | **NF** | 0 |

### 2.2 ASKs (`_k1_answer` NC:4044-4095)

| ASK | Raised at | Trigger | Class | Measured |
|---|---|---|---|---|
| `fire` / `part_stale` | K1C:1545-1552 via `fire_ask_why` K1C:81 | a slot went stale mid-walk. With D3, no Python runs mid-walk except launch hand-backs (gone too), so the part generation cannot move mid-walk (**inferred**) | **NF** (likely unreachable) | 0; posed diff 0 |
| `fire` / `mount_unknown` | WG:305-307 (`_resolve_torpedo_aim_point`), BG:63-67 (K2) | a posed target's offset meets a mount-order entry the mirror cannot name | **NF** (a stale-row case) | 0 |
| `fire` / `no_mount` | WG:242-252 | posed target, offset no mount, no Manual Aim slot holds it (box rule, ruling C4) | **AIM** | 0 in R1/R4/R5; **4-22 per 660-tick posed diff run** (posed-parts spec §10, "What stays in Python") |
| `fire` / `offset_off_mount` | WG:257-263 | offset within 1e-5 of a mount but not bit-equal. Python's `authored_mount_subsystem` (PS:525-537) and the native one (PP:82) both match within 1e-5, but the native slot is used only on bit equality | **⚠ ELSE** (§2.7 #5) | 0 |
| `fire` / `other` | any other `decide` throw (pulse module unresolved, cannon `_target` unnamed, the `ship.GetTarget()` fallback) | | **NF** | 0 |
| `can_fire` | K1C:1503-1507 | native `can_fire` threw (an unnamed ref) | **NF** | 0 |
| `retry` | K1C:1650-1656 | a retry-list entry has no row or no real `IsDead` | **NF** | 0 |
| `is_dead` | K1C:1671-1676 | `ship_dead` threw | **NF** | 0 |
| `is_member` | K1C:1379-1382 | the weapon's Property row is gone | **NF** | 0 |
| `is_dumb` | K1C:1422-1425 | an effect's handler dropped the weapon's row. With no mid-walk Python, **inferred** unreachable | **NF** | 0 |
| `group_step` | K1C:1369-1373 | a handler swapped the system's children; same | **NF** | 0 |
| `reseed` | K1C:793-797 | single-fire bookkeeping with an unnamed child | **NF** — but "no fire" is not the right word: the shot already fired; it is the reseed that cannot be made (§7 R8) | 0 |

### 2.3 Walk-check hand-backs (the bindings' `k1_scan`, HB:5661-5704; Python `walk_start` NC:3755-3776, `run_k1` NC:4169-4188)

| Hand-back | Trigger | Record | Class | Measured |
|---|---|---|---|---|
| system or child instance patch | `_K1_SYSTEM_PATCHES` / `_K1_LEAF_PATCHES` in an instance dict | WALK_START → `skip_walk` (whole walk in Python) | **DEL2** | 0 (R1: `k1_python_systems` 0) |
| ship instance patch | `is_using_target_offset` / `GetTargetOffsetTG` on the ship's dict | WALK_START → Python `_live_held_offset` | **DEL2** | 0 |
| ship class not stock | the class's `is_using_target_offset` / `GetTargetOffsetTG` differ from `ShipClass`'s, or a non-`ShipClass` has the probe, or a `ShipClass` lacks it (HB:5600-5626) | WALK_START | **DEL2** (mod policy: ship classes are not a mod surface; **inferred** that this needs Mark's confirmation for mod ship *classes*, if any exist) | 0 |
| "cannot read" | no registry entry, no dict, a dict not yet materialised, `_children` not a list/tuple, a CPython error (HB:4808-4810; tests `test_walk_check_hands_back_an_unmaterialised_dict`, `…ship_with_an_unmaterialised_dict`) | WALK_START | **DEL2**: the only reason to read the dict is the patch scan; the kernel can compute the offset itself | 0 counted (not counted separately) |
| pump stop of a system the check flags | same names (a patched `StopFiring`) | STOP_SYSTEM | **DEL2** | ~0 (4 STOP_SYSTEM in all of R1, `remaining-fallbacks-map.md` §2.3) |

### 2.4 Launch hand-backs (`K1LaunchWhy`, K1H:356-371; FIRE / FIRE_DUMB records)

| Why | Raised at | Trigger | Class | Measured |
|---|---|---|---|---|
| `Patched` | K1C:931-933, 1054-1056 | `K1_LAUNCH_PATCHED` (a launch function not stock) | **DEL2** | 0 |
| `PosedOffset` | K1C:1030-1039 via `bake_offset` K1C:1102-1112 | a posed target's offset no Manual Aim slot holds | **AIM** | **2 per 8,999 ticks** in the 64-ship fight (launch-deferral spec §10, `2026-11-02-combat-launch-deferral-design.md:86`) |
| `Unresolved` — no ammo type | K1C:944-947 | `GetCurrentAmmoType()` is None: Python's `_spawn_torpedo` then launches the **property's slot-0 script** (WS:3866-3872), which is not mirrored | **⚠ ELSE** (§2.7 #2) | 0 measured; stock hardpoints declare ammo types (**inferred**); a legacy/mod tube may not |
| `Unresolved` — no script / no module | K1C:950-951 (`ammo_launch_state == 2`) | `_resolve_projectile_module` failed even for the photon fallback | **NF** (Python also launches nothing: WS:3878-3879) | 0 |
| `Unresolved` — pulse module stale | K1C:1057-1062 | a cannon's cached module is not `sys.modules`' (re-imported since cached) | **⚠ ELSE** (§2.7 #3) | 0 |
| `Uncached` | K1C:952 | the type's launch not cached: a projectile-cache reset inside a K1 session (THE P6 WINDOW, K1H:183-192), or a `GetLaunchSpeed` that raises (WS:461-475) | **NF** for the raise (Python raises it too: WS:470-472); the P6 window case is transient — **⚠ ELSE**-lite, fold into §2.7 #3 | 0 after Task 5 (`launch_uncached` 0, launch spec §10) |
| `Other` | K1C:956-960, 983, 1081 | slot lists out of step with `MaxReady`, an unnamed set, an unreadable row | **NF** | 0 |

### 2.5 Other records and entry routes

| Route | Where | Class |
|---|---|---|
| `BANK_STOP` for a row gone | K1C:1517-1525 → `walk.obj(rec[1]).StopFiring()` NC:4197-4200 | not a decision: a stop. Keep it as Python's SDK `StopFiring` or log the writes; either is consistent with D6 |
| `FIRE_DUMB` record | K1C:1150-1185 → `FireDumb(0, 1)` NC:4201-4202 | the launch reasons of §2.4 |
| `k1_system` with no Subsystem row | NC:4253-4256 → `system.update_weapons(dt)` | **NF** |
| `run_k1`'s RUN_PYTHON for a system session | NC:4203-4207 (`system.update_weapons(dt)`) | the §2.1 reasons |

### 2.6 Routes outside K1 (not counted by any K1 counter)

| Route | Where | What runs | Class |
|---|---|---|---|
| **SDK dumb fire** | SDK `AI/Preprocessors.py:445-458` (`pTube.FireDumb(0, 1)` when `bDumbFireTorps`); `AI/Compound/BasicAttack.py:181` turns `DumbFireTorps` on at `Difficulty 0.0`; explicit in SDK `Maelstrom/Episode2/E2M0/E2M0_AI_Klingon.py:39`, `Episode3/E3M2/BasicWarbirdAI.py:44`, `Episode4/E4M6/Galor3AI.py:9` | `Weapon.FireDumb` WS:1421-1452 → `TorpedoTube.Fire` → Python `_fire_decide`/`_fire_effect`/`_spawn_torpedo` (defers its SPAWN, WS:3885-3891) | **⚠ ELSE** #1 |
| **SDK `CanFire`** | SDK `AI/PlainAI/PhaserSweep.py:175`, `Conditions/ConditionInPhaserFiringArc.py:175` | mixin `CanFire` WS:1018-1058, writes `_depleted = False` (WS:1064-1067) | **⚠ ELSE** #6 (a second copy of a K1 rule stays) |
| `Weapon.Fire` (SWIG) | `SDK/App.py:5784`; 0 stock SDK call sites; 37 test files call `.Fire(` | Python decide + effect | **⚠ ELSE** #6 (surface without callers: delete, or route to a native one-weapon session) |
| Tractor engage | `TractorBeamSystem.StartFiring` WS:2724-2744 (from SDK `StartFiring` via FireScript, `weapon_config.toggle_tractor` `engine/appc/weapon_config.py:277-293`, `App.ToggleTractorFromInput` `App.py:1754`) | `_engage_beam` → `emitter.Fire` (mixin decide/effect), `_sync_firing_event` | **PORT** |
| Tractor pump | K1 `SelfManaged` → `_pump_held_system` → `TractorBeamSystem.update_weapons` WS:2792-2847 | same | **PORT** |
| K0 holding tractor | K0C:257-258, 739-740 (`K0Reason::Tractor`) → Python `TractorBeam.UpdateCharge` WS:3305-3346 | power-loss / starvation `StopFiring` | **PORT** (K0 is not retired, but the port should take it) — one hand-back per holding beam per tick (`tests/unit/test_native_k0_dispatch.py:309`: `41 * len(beams)` over 41 holding ticks) |

### 2.7 ⚠ SOMETHING ELSE — routes the decisions do not cover

1. **SDK `TorpedoTube.FireDumb`** (§2.6). AI FireScript calls it outside any K1 session, so Python's tube decision, launch bookkeeping and spawn run there. Routine for low-difficulty AI and three stock missions. Deleting the tube's Python decision needs a native one-tube "dumb fire" session (the kernel already has `dumb_fire`, K1C:1151-1185) or the Python copy stays.
2. **`Unresolved` launch, tube with no ammo type** (K1C:944-947). Python launches the property's slot-0 script (WS:3866-3872). Under D6 such a tube would never fire. Porting it means pushing the property's slot-0 script into the launch cache (the cache is keyed by script name, NC:2417-2448).
3. **Re-imported pulse module** (`K1_PULSE_MODULE_STALE`, HB:4237-4279) and the **P6 window** (`Uncached` after a mid-session reset). Both are "the cache is out of date", not "the shot is impossible". Re-pushing the params at the next K1 entry (`refresh_stale_pulse_params`, NC:2579-2596, already does it after a mission swap) fits better than "no fire".
4. **`PartStale` at the prescan** (K1C:718-721). Not in D6's list. It persists only when Python's part resolution raises for a leaf (`_part_slot` NC:2165-2166), so under D6 that ship would never fire again. Needs a ruling (no fire + log once, or treat a stale mount slot as identity).
5. **`OffsetOffMount`** (WG:257-263, PG:356-359). An offset within 1e-5 of a mount, not bit-equal: Python treats it as the mount (`authored_mount_subsystem`, PS:525-537), native refuses. Under D5 a near-mount offset is neither "a mount" nor "a non-mount" without a rule. Options: native uses the mount's slot within tolerance (accepting `part_for_mount(point)` vs the slot of `_position`), or near-mount = plain xyz.
6. **Python copies the SDK still reaches** (§2.6): `CanFire` (with its `_depleted` write), `Weapon.Fire`, `FireDumb`. Decision 1 ("one copy of each rule") is not met while these stay Python. Native twins exist (`can_fire`, `decide`).
7. **K2's override guard reads K1's `k1_overridden` flag** (K2C:388, 578, 794; NC:4690 "the K1 watch"). Deleting K1's guard silently weakens K2's, which keeps its Python copy this phase.
8. **The logged `walk_offset` write needs a Python object** (`_K1Walk.materialise` NC:3717-3737 calls `_live_held_offset`). A bank's `_target_offset` is the walk's offset *object*, identical across banks (ruling P5; checked by the K1 differential's "which bank's offset is the same OBJECT" record, `test_native_k1_differential.py:15-16`). With `_live_held_offset` deleted, the driver needs another way to make that object.

---

## 3. Tractors

### 3.1 The Python tractor model

| Part | file:line | What it does |
|---|---|---|
| Class flags | WS:2654 `_pump_self_managed = True`; WS:2661 `DRAWS_DIRECT_FROM_MAIN = True`; WS:2664 `_POWER_FREEZABLE = True`; modes WS:2668-2673 (`TBS_HOLD`=0 … `TBS_DOCK_STAGE_2`=5) | |
| State | WS:2675-2684: `_mode`, `_engage_state` (HOLD point / TOW offset dict), `_was_firing` (event edge); inherited `_next_emitter_index` (WS:1532), `_fire_held`, `_held_target`, `_held_offset`, `_target_list` | `_mode`, `_engage_state`, `_was_firing`, `_next_emitter_index` are **not mirrored** (MIR field list, MIR.cc:40-90) |
| **Fire decision: engage** | `StartFiring` WS:2724-2744: `IsOn`, target, `_is_offline`, `_cloak_blocks_fire`, `_dewarp_blocks_fire`; records intent (`_add_target`, `_fire_held`, `_held_*`) BEFORE the range gate; `_can_engage` → `_engage_beam`; `_sync_firing_event` | |
| **Fire decision: sustain** | `update_weapons` WS:2792-2847: needs `_fire_held` and a held target; power-off → sync only; offline → `StopFiring`; dead target → `StopFiring`; `_can_engage` (range `TRACTOR_MAX_RANGE_GU` = 120 GU WS:2476 via `_target_within_range_gu` WS:2506-2533, same-set guard; `_target_tractorable` WS:2481-2494 is "not None"); drop every firing emitter out of arc (`_resolve_bank_aim_world` + `_emitter_in_arc`); if none firing, `_engage_beam(target, self._live_held_offset(), ship)` | |
| Emitter pick | `_engage_beam` WS:2849-2883: single-fire round-robin from `_next_emitter_index`, first in-arc emitter whose `CanFire()` → `emitter.Fire(target, offset)`; multi-fire: every in-arc `CanFire` emitter | |
| Leaf | `TractorBeam` WS:3271-3346: `_firing = NativeThawParentWakeField(bool)` WS:3279 (a write thaws or drops the parent's power program, `engine/appc/passive_power.py:98-125`); `Fire`/`CanFire`/`StopFiring` are the mixin's (WS:1018-1126) | |
| **Charge / power** | `TractorBeam.UpdateCharge` WS:3305-3346: firing → drops on parent `IsOn()` false, or `GetPowerPercentage() <= 0` (`_efficiency`) with `GetNormalPowerWanted() > 0` (`_normal_power`), SUB:1463-1465; never discharges while holding; idle → mixin recharge. Power draw: `_wants_power` = `IsOn() and _any_child_firing()` WS:2686-2700; `DRAWS_DIRECT_FROM_MAIN` → a direct main-battery siphon in `PoweredSubsystem._update_power` (SUB:1490, 1504) | `_efficiency`, `_normal_power` are `FrozenField`s, not mirrored (SUB:1396-1400; `weapon-state-map.md` §0.3) |
| **Beam geometry** | render: `_build_tractor_beam_render_data` HL:2578-2614 → shared `_beam_descriptor_pair` HL:2427-2470, endpoint from `_phaser_aim_point(ship, target)` (the SHIP's Manual Aim / subsystem lock, not the emitter's `_target_offset`), `TRACTOR_BEAM_END_WIDTH_SCALE` 1.25, `TRACTOR_BEAM_BRIGHTNESS` 0.5 (HL:2571-2575); pushed by `host_io.set_tractor_beams` HL:1489 → `g_tractor_beams` drawn by the phaser pass (HB:467-469, 2064, 9654-9662) | |
| **Force** | §3.6 | |
| **Events** | `_sync_firing_event` WS:2752-2784: `ET_TRACTOR_BEAM_STARTED_FIRING` / `_STOPPED_FIRING` on an `IsFiring()` edge, source the system, destination the parent ship, posted **synchronously** with `App.g_kEventManager.AddEvent` (not an effect-queue kind; EQ:18-60 lists none). Called from `StartFiring`, `update_weapons` (5 sites), `StopFiring` WS:2885-2889. `ET_TRACTOR_BEAM_STARTED_HITTING` / `_STOPPED_HITTING` and `ET_TRACTOR_TARGET_DOCKED` exist as constants only (`engine/appc/constants_generated.py:652-656`); no engine emitter (grep `ET_TRACTOR` in `engine/`) | |
| **Sounds** | mixin `_fire_effect` edge → `FIRE_SOUND` entry when deferring, else `_play_fire_sfx` (WS:1104-1108); tractor convention bare `"<name>"` with no Start/Loop pair (WS:1243-1246); `StopFiring` → `LOOP_STOP` (WS:1121-1124) | |
| Damage | none: `weapon_type="tractor"` is mapped (`engine/appc/combat.py:605`, EQ:248) but nothing produces a tractor hit (grep) | |

### 3.2 SDK callers

- **Events.** `Conditions/ConditionFiringTractorBeam.py:26-27` (broadcast method handlers on STARTED/STOPPED filtered to the ship; `:47-52` re-reads each `TractorBeamProjector_Cast(child).IsFiring()`), used by `Maelstrom/Episode1/E1M2/E1M2_AI_Intercept.py:22` and `Episode2/E2M1/E2M1_AI_Intercept.py:23`. `Bridge/PowerDisplay.py:337-338, 371-372` register `HandleTractor` (`:1010-1044`) on the player, which walks `GetWeapon(i).IsFiring()` (`:1022-1024`). `Maelstrom/Episode7/E7M2/E7M2.py:341` `TractorHandler` (`:708-731`: reads the player's target; wins the mission when it is the Vor'cha). `Maelstrom/Episode8/E8M2/E8M2.py:528` `TractorHandler` (`:1010-1034`): in OD1 it calls `pPlayer.GetTractorBeamSystem().StopFiring()` — a handler that **gates** the effect (event inventory classes STARTED as ORDER, `event-inventory.md:88, 134, 172`).
- **Direct calls.** `StopFiring`: E7M2.py:2158, E8M2.py:1023, E6M5.py:913, MissionLib.py:741. `IsFiring`: E6M2.py:1900, PowerDisplay.py:1024, Preprocessors.py:486. `GetMode`/`SetMode`: Preprocessors.py:486-491 (FireScript `AddTractorBeam` `:166-170` adds the system as a weapon; StartFiring with the subsystem offset `:465`), `AI/PlainAI/Warp.py:409` (`IsTryingToFire`), `TractorDockTargets.py`, `EvilShuttleDocking.py`. `SetConditionPercentage` on the tractor system: E7M2.py:1647-1649, E8M2.py:6223-6225. Hardpoints: `ships/Hardpoints/GenericTemplate.py` (16 mentions).
- `Warp.py:415` reads `pTractor.GetTargetList()[0]`, which our `WeaponSystem` does not define (`weapon-state-map.md` §2, **inferred** stub).

### 3.3 Hand-backs today that involve tractors

| Kernel | Where | Per | Note |
|---|---|---|---|
| K1 | `SelfManaged`, K1C:1222-1224 (pump) | per held tractor system per tick | the walk check also skips it (HB:5696). StartFiring never reaches K1 (the tractor's own StartFiring, WS:2724) |
| K0 | `K0Reason::Tractor`, K0C:257-258 / 739-740 | per holding beam per tick | idle beams step natively (ruling W6; `test_native_k0_dispatch.py:313-336`) |
| K2 | none: K2 walks `GetPhaserSystem()` only (HL:1131) | | |
| Effect queue | none: STARTED/STOPPED post synchronously, inside the deferral scope when the pump runs them | | `2026-11-02-combat-fire-events-design.md:36` kept them so on purpose |

No measured count with tractors exists: none of R1/R4/R5 uses tractors (`remaining-fallbacks-map.md` §6, "Not exercised").

### 3.4 What a native port needs (inferred from the Python above)

- **Mirror fields:** tractor system `_mode`, `_was_firing`, `_next_emitter_index`, and the engage state (`hold_point` world xyz, `tow_offset` body xyz, or none); parent `_efficiency` and `_normal_power` (as `NativeFrozenField`, the `_power_factor` pattern at SUB:1401) for K0's holding branch; globals `TRACTOR_MAX_RANGE_GU` and the TR:43-50 constants; ship mass (`GetMass`, not mirrored; `_radius` is, MIR.cc:33). Arcs, mounts, `_firing`, charge and condition are already mirrored for phasers.
- **Kernel steps:** a K1 tractor walk (StartFiring's engage, `update_weapons`' drop-out-of-arc / re-acquire, `_engage_beam`'s round-robin). StartFiring would become a native system session like `k1_system`. A K0 holding-tractor branch (power-loss / starvation stop). A force step (§3.6). The mixin `CanFire`/arc/`_fire_effect` twins already exist in K1 for phaser banks.
- **Writes:** `_firing` on a `TractorBeam` is `NativeThawParentWakeField`, so the applier classifies it `APPLY_PYTHON` (its setter is not `WakeField.__set__`, NC:3973-3980). That keeps the power thaw correct, at a Python call per write.
- **Events through the effect queue:** two new kinds (STARTED/STOPPED), produced on the edge with the system as source and the ship as destination. Consequence (decision 9): E8M2's `StopFiring` handler then lands one tick later, so one tick of tractor force applies in OD1 before the stop. Today it stops the beam before `cb.tractors` in the same tick (`event-inventory.md:172`). PowerDisplay and ConditionFiringTractorBeam re-read live state, so they only report.
- **Sounds:** `FIRE_SOUND` / `LOOP_STOP` entries already exist (K1H:304-312).

### 3.5 What can be cleaned up

- `_pump_self_managed` (WS:2654), the K1 `SelfManaged` hand-back, `pump_self_managed` in `_flags` (NC:1974-1975), the walk-check skip (HB:5696) and `_pump_held_system`'s branch (HL:1076-1078).
- `_live_held_offset` (only the tractor and K1's materialise need it after D3).
- `TractorBeamSystem.update_weapons` overriding the deleted base (WS:2792). The base `update_weapons` cannot be deleted while it exists.
- `_target_tractorable` (WS:2481-2494): it now answers only `target is not None`.
- The comments that call the force a spring-damper (CLAUDE.md OQ-2.3 line, `docs/gap_analysis.md:198-225`, which says "Phase 2 force law: implement as a spring-damper ... Scale by MaxDamage"): the code neither damps nor reads `MaxDamage`.
- `_build_tractor_beam_render_data` aims the beam at the SHIP's Manual Aim / subsystem lock through `_phaser_aim_point` (HL:2455), not at the emitter's own `_target_offset`.

### 3.6 Tractor force: does it write ship motion directly, and from where?

**Yes, directly, from Python, once per sim tick.** `host_loop._advance_combat_step` calls `tractor.advance_tractors(ships_list, dt)` in `cb.tractors` (HL:1448-1456), after K1 (`cb.held_weapons`) and K2 (`cb.phasers`), inside the host's per-tick effect scope (HL:12693-12707). `advance_tractors` (TR:112-133) walks every ship's tractor system with `IsFiring()`, then each firing emitter's `_target`, and calls `_apply_mode` (TR:136-212). That function moves objects by **position writes**:
- `_displace` → `obj.SetTranslateXYZ(p + d)` (TR:80-83): PUSH (target and reciprocal source), TOW's reciprocal drag;
- `_spring_toward` → `SetTranslateXYZ` capped at `max_speed * dt`, snapping inside one step (TR:86-101): PULL (target and source to a standoff), HOLD (to the captured hold point), TOW (to the captured body-frame offset rotated by the source), DOCK 1/2 (gentle pull, ×0.4);
- `_zero_velocity` → `SetVelocity(0)` (TR:104-109), HOLD only.

The speed is `clamp(5.0 * 100 / mass, 0, 20)` GU/s (TR:67-77). Non-`ShipClass` objects get 0 (immovable). `SetTranslateXYZ` writes the transform store (`engine/appc/objects.py:327-328`), which the mirror reads for every Object row (`register` passes `_xform`, NC:1447-1449), so later kernels in the same step and the next tick see the moved ships. `_engage_state` is written on the system (TR:181-196) and cleared on `SetMode` (WS:2705-2711) and `StopFiring` (WS:2885-2889). The docstring's "before collisions" (TR:36-38) holds: collisions run once per frame after the sim ticks (roadmap decision 10). **GameLoop never runs it** (GL:36-137), so headless harnesses never move a tractored ship.

---

## 4. Aim-slot machinery to delete (D5)

### 4.1 Python

| Piece | file:line | Role | Verdict |
|---|---|---|---|
| `_manual_resolved`, `_manual_slot`, `_resolve_manual_slot` | NC:2264-2316 | the box rule per (target, offset, generation) → firing ship's manual slot | **DELETE** |
| manual branch in `resolve_stale_part_slots` | NC:2230-2232 | **the per-step re-resolution**: runs at every `k1_pump` (NC:4239), `k1_system` (NC:4264), `k2_phasers` (NC:5480), `step_scan` (`remaining-fallbacks-map.md` §1.5: 4.2 calls, 0.027 ms per tick for slots overall) and the K2 heal (NC:2235-2246) | **DELETE** the manual half |
| `_forget_part_caches` manual lines | NC:2060, 2064 | | **DELETE** |
| `_audit_manual_slot` | NC:3421-3443 | | **DELETE** |
| `projectiles._bake_offset`, `_baked_offset` TorpedoField, `SetTargetOffset`'s bake, `_set_launch_offset(offset, baked)`, `_steer_point`'s bake branch | PR:1110-1124, 96, 129, 244-245, 250-258, 1169-1174 | launch-time posed point of a picked spot | **DELETE**: a non-mount offset steers at `body_point_world(target, offset)` |
| `_enc_baked`, `"_baked_offset"` in `_TORP_FIELDS`, its push | NC:3021-3034, 3050, 3114, 3124 | K3 table encoding | **DELETE** |
| `_launch_reads`' bake | WS:713-717 | Python launch's bake | goes with Python launches |
| SPAWN's `baked xyz` operands | EQ:41-47, `_defer_spawn` WS:741-746 | | **DELETE** the operand (and `K1Spawn::baked`, K1H:335) |
| `subsystems.target_offset_world` with no mount on a posed target | SUB:96-131 (`authored=mount_sub is not None` → `part_transform_point(authored=False)` → box rule ART:780-830, PS:76-110) | the box rule in AIMING | **CHANGE**: no mount → `body_point_world(target, point)` |
| Manual Aim pull-back | `engine/manual_aim.py:198-204` (`rest_point_for_live_point`, PS:229-247, via `part_for_live_point`) | pick on the posed hull stored rest-frame | **CHANGE**: store the posed body point as it is. Otherwise a pick on a raised wing aims at the rest-pose point, now that no forward pose is applied. `rest_point_for_live_point` has no other caller (grep) → **DELETE** |
| `ART.part_transform_point(authored=False)` / `_live_part(..., authored=False)` | ART:724-779, 780-830 | | the `authored=False` path loses its aiming callers. `hull_bounds.py:113` and severance use `part_for_point` directly; **KEEP** the box rule for hits and severance (`record_hit` PS:291-348, `_emit_pos_on_part` PS:421-447, `hull_bounds`) |

### 4.2 Native

| Piece | Where | Verdict |
|---|---|---|
| `ObjectRow` manual slot fields | MIR.h:226-235 (`manual_slot_target`, `manual_slot_offset`, `manual_slot`, `manual_slot_gen`); `Mirror::set_manual_slot` MIR.cc:918-930; binding `combat_set_manual_slot` HB:12533-12540 | **DELETE** |
| `manual_slot_pose` | PP:43-60, part_pose.h:74-82 | **DELETE** |
| `target_offset_world` no-mount branch + `manual_ship` param | WG:233-253, weapon_geometry.h:88-92 | **CHANGE**: no mount → the offset itself (no `NoMount` throw) |
| `_resolve_torpedo_aim_point` manual ship | WG:308-315 | **DELETE** the manual ship |
| K1 `bake_offset`, `PosedOffset` | K1C:1098-1112, 1030-1039; K1H:364-366 | **DELETE**; the spawn carries the offset only |
| K1 `fire_ask_why` `NoMount` | K1C:83; K1H:384-386 | **DELETE** |
| K2 Manual Aim on posed | BG:58-72 (`mount_unknown` fallback stays a stale-row case), K2C:505-511 `manual_on_posed`, K2C:983-984 `posed_manual_aims`; K2 `aim_point` ASK `no_mount` | **DELETE** the manual-slot route; keep the mount route |
| K3 `unbaked`, `baked` row fields, `baked_steer`, `no_mount` | PG:362-371, 197-206, 387; torpedo_table.h:41-43, torpedo_table.cc:18, 166-172; SteerWhy PG.h:128-137 | **DELETE**; no mount → `body_point_world(target, offset)` |

### 4.3 What stays

Subsystem mounts on posed parts keep their posed aim: pose tables, part slots, the part generation and mount order (NC:2018-2350; `slot_pose`, `check_slot_owner`, `posed_local` in PP/WG). So do K2's posed lock aims (BG:74-85), K3's mount steer (PG:349-360) and the K2 heal (NC:2235-2246). The box rule stays for hit attribution and severance.

### 4.4 What changes behaviourally (derived from the code; not measured)

An offset is either an authored mount (`authored_mount_subsystem`, eps 1e-5) or not. Only "not" changes, and only on a **posed** target (unposed: `part_transform_point` returns the point already, ART:768-772).

| Shot | Today | After D5 | When it differs |
|---|---|---|---|
| Manual Aim phaser (K2) | re-picked every tick, pulled back to rest, re-posed by the box rule | the live pick as body xyz | Same point whenever the pull-back and re-pose round-trip exactly, which they are designed to do (PS:229-237). Differs only where they did not: ambiguous box overlaps that `part_for_live_point` and `part_for_point` resolve differently (**inferred** rare) |
| Manual Aim torpedo/pulse fired at the current pick | fire-time aim and launch-time bake = box-rule posed point | the pick as body xyz | ≈ same (same round trip) |
| **Stale pick** — a tube's stored `_target_offset` from an earlier tick (posed-parts spec §10, "a player tube whose stored offset is the previous pick") | posed by the wing's **current** pose at fire time | stays where the wing **was** when picked | while the wing moves between pick and shot (BoP wings in cruise/transition) |
| **NPC offset kept across a re-target** (a tube keeps the old target's mount offset; SDK FireScript passes `pSubsystem.GetPositionTG()` or (0,0,0), `AI/Preprocessors.py:459-465`) | box rule on the NEW target: may land on a posed part and follow its pose | plain body xyz on the new target | only if the new target is posed and the point falls in a posed part's box |
| AI (0,0,0) offset | box rule; the origin is normally in the body, not a rig part (**inferred**) → identity | identity | effectively never |
| Torpedo in flight at a picked spot | steers at the launch-time **posed** point (bake, ruling of 2026-11-01) | steers at the un-posed body xyz | when the target was posed **at launch** and the spot is on a posed part: aim moves from "where the wing was at launch" to "where the wing is at rest". Mark's ruling accepts that picked spots never follow parts. Not having the launch pose either is a further change, worth confirming |
| Subsystem lock on a wing | follows the wing every tick | unchanged | — |

Fire gates read the aim too: the torpedo cone and the pulse lead (WG:311-372). A changed aim point can flip `WEAPON_FIRE_FAILED` vs launch for those cases.

### 4.5 The Python copies of K2/K3 must change too

K2 (`_phaser_aim_point` HL:1096-1115 → `target_offset_world`) and K3 (`_steer_point` PR:1127-1174, `_bake_offset`) keep their Python copies this phase. Their differentials compare Python and native. D5 has to land in `subsystems.target_offset_world`, `projectiles`, and `manual_aim` at the same time as in WG/BG/PG, or the K2/K3/posed differentials diverge on posed scenes.

---

## 5. Tests

### 5.1 Tests that compare Python against native

All pick the arm through the global `DAUNTLESS_NATIVE_COMBAT` → `nc.configure(env)`. So after D3 **every OFF arm loses Python fire control**, including the arms that exist to check K0, K2, K3 or damage.

| File | Lines | Compares | Fate |
|---|---|---|---|
| `tests/integration/test_native_k1_differential.py` | 1170 lines; OFF/ON 76-77, `_both` 660-672, tests 685, 739, 810, 873, 895, 934, 1132 | K1 fight with seeded ops (tpf 1, 6), K0 stood down, handler stop/restart mid-walk, Manual Aim, forced pose, BoP at red, under GameLoop AI | → golden fights (D7) |
| `tests/integration/test_native_posed_differential.py`, `tests/host/test_native_posed_differential.py`, `tests/helpers/posed_fight.py` (961 lines; OFF/ON 95-96, `configure` 325) | posed fights, headless and host | → golden, re-recorded for D5 |
| `tests/integration/test_native_combat_step_differential.py` | OFF/ON 58-59 | whole combat step (1a) | OFF arm needs Python K1 → golden or split switch |
| `tests/integration/test_native_k0_differential.py`, `tests/helpers/k0_fight.py` | `configure(ON)` k0_fight:76 | K0 | OFF arm runs Python K1 too (**inferred** from the global switch) |
| `tests/host/test_native_k2_differential.py` | OFF/ON 117-118, 400 | K2 | same |
| `tests/integration/test_native_k3_differential.py`, `tests/host/test_native_k3_differential.py`, `tests/helpers/k3_fight.py` | OFF/ON 90-91 / 79-80 | K3 | same |
| `tests/integration/test_native_damage_differential.py` | OFF/ON 70-71 | native damage | same |
| `tests/integration/test_native_can_detect_differential.py`, `tests/unit/test_native_can_detect.py` | 54-55 | can_detect | same |
| `tests/integration/test_presentation_rng_falsifier.py` | 107 (`=0`) | cosmetic noise falsifier, switch off | must run ON |
| `tests/unit/test_native_k1_dispatch.py` | 85 tests (3,541 lines) | unit-level K1 vs Python | about 30 test guards/hand-backs (DEL2/AIM): e.g. `test_class_override_runs_python` 547, `test_instance_patch_runs_python` 589, `test_stock_class_patch_runs_python` 748, `test_live_held_offset_override_runs_python` 1475, `test_walk_check_*` 1938-2015, `test_mid_pump_instance_patch_is_obeyed_the_same_tick` 2079, `test_stop_firing_override_runs_python` 1873, `test_system_instance_stop_patch_runs_python` 2526, `test_launches_the_kernel_cannot_make_run_python` 2943, `test_python_fallback_launch_defers_its_spawn` 2968, `test_python_pulse_launch_defers_its_spawn` 3020, `test_pulse_launch_with_a_patched_launch_function_runs_python` 3125, `test_patched_launch_function_seen_by_the_next_walk` 3440, `test_posed_target_offset_hand_back_has_its_own_reason` 3419, `test_manual_aim_on_posed_target_native` 1228, `test_stale_slot_falls_back_part_stale` 1162, `test_unregistered_ship_runs_python_in_order` 391, `test_python_dumb_fire_spawn_is_tagged_dumb` 3521. The rest compare K1's writes/entries with Python's: they need a recorded expectation |
| `tests/unit/test_native_k0_dispatch.py`, `test_native_k2_dispatch.py`, `test_native_k3_dispatch.py` | | per-kernel dispatch with `run_both` | OFF arm loses Python fire control where they fire (**inferred**) |
| `tests/unit/test_native_manual_slot.py` | 9 tests 103-232 | manual slot vs box rule | **DELETE** (D5) |
| `tests/unit/test_native_part_slots.py` | 15 tests | pose tables, mount slots | **KEEP** (mount half) |
| `tests/unit/test_native_write_apply.py` | | C applier vs `apply_writes` | **KEEP** (K0/K2) |
| `tests/host/test_native_combat_scene_audit.py` | | mirror audit in a host scene | **KEEP** |

### 5.2 Tests that exercise the Python copy directly (switch off by the conftest reset)

They call `StartFiring` / `_pump_held_weapons` / `_advance_combat` / `update_weapons` / `try_fire_weapon` with no `configure()`, so today they run Python fire control:
- `update_weapons`/`try_fire_weapon`/`_fire_decide`/`_pump_held_*` direct (13 files): `tests/unit/test_phaser_fire_range_gate.py`, `test_weapons_disabled_blocks_fire.py`, `test_weapon_no_target_bail.py`, `test_native_combat_weapons_mirror.py`, `test_tier_bc_event_emitters.py`, `test_start_firing_arms_tick.py`, `test_weapon_system_sequential_firing.py`, `test_weapon_tick.py`, `test_native_k1_dispatch.py`, `test_phaser_cloaked_target_no_fire.py`, `tests/integration/test_tractor_singlefire_dispatch.py`, `test_pulse_singlefire_modes.py`, `tests/helpers/k0_fight.py`.
- `StartFiring` with no `configure` (29 files), among them `tests/unit/test_manual_aim.py`, `test_pulse_aimed_launch.py`, `test_spread_skew_wiring.py`, `test_cloak_combat_rules.py`, `test_dewarp_drive.py`, `test_torpedo_ammo_selection.py`, `test_render_feeds_by_frame.py`, `test_tractor_beam_render_data.py`, `tests/integration/test_fire_primary_continuous.py`, `test_phaser_damage_applied_through_apply_hit.py`, `test_disruptor_fire_and_damage.py`, `test_phaser_multi_bank_fire.py`, `test_phaser_target_drifts_out_of_arc.py`, `test_weapon_cross_set_interim_guard.py`, `test_fire_secondary_chain.py`, `test_tractor_effect.py`, `test_tractor_engage_intent.py`, `tests/oracle/conftest.py`.
- `_advance_combat` callers: 39 test files.
- Fake weapons the Python walk accepts and K1 would hand back as `Overridden`: `tests/unit/test_weapon_tick.py` (the `fired` counter that `_fired_counter` exists for, WS:1889-1901), `test_torpedo_tube_invariants.py`, `test_torpedo_tube_weapon_base.py`, `test_dewarp_drive.py`, `test_death_cascade.py`, `test_subsystem_watchers.py`.
- Direct `.Fire(` calls: 37 test files.
- Tractor tests (all Python today): `tests/integration/test_tractor_effect.py`, `test_tractor_engage_intent.py`, `test_tractor_singlefire_dispatch.py`, `test_tractor_toggle_wiring.py`, `tests/unit/test_tractor_beam_render_data.py`, `test_tractor_direct_main_siphon.py`, `test_damage_source_getters_tractor.py`.

### 5.3 Tests that silently rely on the switch defaulting OFF

Every test that constructs a `GameLoop()` without pinning `DAUNTLESS_NATIVE_COMBAT` (`configure()` reads the real env, GL:33) runs Python today and native after D1. That is **51 of the 57** test files that construct a `GameLoop()`. The ones that also fire weapons: `tests/unit/test_dewarp_drive.py`, `tests/oracle/conftest.py` (all of `tests/oracle/*`: `test_beams.py`, `test_projectiles.py`, `test_shields_and_hull.py`, … ; it calls `_advance_weapons`/`_advance_combat` at `tests/oracle/conftest.py:82-83` with no effect scope), `tests/integration/test_m2objects_live_path.py`, `test_weapon_fired_mission_handlers.py`, `test_galaxy_combat_fire_diagnostic.py`, `test_quickbattle_station_defends.py`, `test_station_hostility_free_roam.py`, `test_free_roam_death.py`, `tests/host/test_qb_late_arrivals.py`, `tests/unit/test_rock_death.py`, and everything through `tests/helpers/headless_mission.py` (`tick` / `warp_and_wait` build a `GameLoop`, lines 91, 107), i.e. the 26-mission campaign sweep. One explicit assertion of the off default exists: `tests/unit/test_native_combat_k3_mirror.py:411-412` (`test_switch_off_registers_nothing`).

### 5.4 Tests that break when the native module is required

- **Without a build** (`_dauntless_host` missing): today the suite degrades to Python (`native_combat._h = None`, NC:58-61; the transform store falls back to `PythonTransformStore`, `engine/appc/transform_store.py:313-329`). After D2/D3, every test that fires a weapon errors instead of running Python. No CI exists (no `.github/workflows`); the gate builds first (`scripts/check_tests.sh`).
- **With a build**, the break is §5.2's: those tests run with `_enabled` False. They break unless the switch is on for them (§7 R1).
- Tests that stub the binding (`monkeypatch.setattr(nc, "_h", …)`): `tests/unit/test_native_part_slots.py:508`, `test_native_manual_slot.py:220`, `tests/unit/test_effect_queue.py:343`.
- `tests/unit/test_native_k1_holds_gil.py` guards the binding source for K1's walk check and launch recheck (lines 1-25); it changes when those leave.

### 5.5 Golden fights: proposal

**What to record, per tick, as canonical rows** (the K1 differential already builds them: `_Scene.record`, `test_native_k1_differential.py:466-537`):
- each weapon system and leaf in a stable label order (ship name, getter, child index — never mirror handles or `id()`): `_fire_timer`, `_firing`, `_target` label, `_target_offset` by `.hex()`, the offset-object identity classes, `_charge_level`, `_depleted`, `_beam_on_countdown`, `_dwell`, `_cooldown_remaining`, `_num_ready`, `_reload_timers`, `_last_fire_time`, `_fire_held`, `_held_target`, `_target_list` labels, `_last_weapon_idx`, `_last_group_fired`, `_force_update`;
- tractor system `_mode`, `_engage_state`, `_was_firing`, `_next_emitter_index` (new);
- every ship's position, rotation, velocity, hull condition and six shield faces by `.hex()`;
- the torpedo table rows (`torp_row`, line 297);
- **event order**: the full ordered `AddEvent` log (type, source label, destination label, tick, order, weapon-hit payload by `.hex()`; projectiles numbered by first sight, line 207-224), the effect-queue rows in delivery order (`effect_split`), the `apply_hit` log, and per-tick multisets of hit VFX and shield hits (`compare_calls`, `tests/helpers/k3_fight.py`);
- per tick, a SHA-256 of the canonical rows, plus the rows themselves.

Store the digests for every tick and the full rows gzipped, so a failure names its first differing tick and field. **inferred**: about 600 ticks × ~10 ships of hex tuples is a few MB uncompressed, so measure before deciding whether to keep full rows for every tick or every Nth with digests between.

**Scenes** (all exist as helpers today):
1. `combat_stress`, 8 ships, the K1 op stream (`OPS`, `test_native_k1_differential.py:597-603`): SetSingleFire, chains, TurnOff/On, SetCondition, power, magazine drain/fill, nudges, Manual Aim on/off. tpf 1 and 6.
2. The same under `GameLoop` AI (`test_k1_matches_python_under_the_game_loop_ai`, line 1132): StartFiring system sessions.
3. The mid-walk handler scene (line 810).
4. The posed fight (`tests/helpers/posed_fight.py`; host and headless): BoP wings moving, Manual Aim and subsystem locks on posed targets. Re-record for D5.
5. **New: a tractor scene**: each mode, HOLD/TOW/PULL/PUSH/DOCK 1-2, out of range and back, out of arc and re-acquire, power off/on and starvation, `StopFiring` from a STARTED handler (an E8M2 stand-in), plus a `ConditionFiringTractorBeam` listener.
6. **New: an SDK dumb-fire scene** (a `Difficulty 0.0` BasicAttack) if §2.7 #1 is ported.
7. Optionally a 64-ship `combat_stress` digest-only run for scale.

**Order of recording, so the golden is the reference:** record scenes 1-5 from the **Python** arm on the current code, before anything is deleted. Check native against them (it already matches where the differentials are green). Then delete. Each intended behaviour change re-records only the scenes it touches, in its own commit that says why: D5 (posed scenes; the unposed scenes must not move, which proves the change is local), the tractor port's event deferral (scene 5), and any D6 change. The K1 differential's arms and op streams become the recorder.

**Re-recording legitimately:** an env switch, after the repo's precedent `UPDATE_STOCK_PARTICLE_GOLDEN=1` (`tests/unit/test_stock_particle_output_unchanged.py:7, 65-68`), e.g. `UPDATE_COMBAT_GOLDEN=1 uv run pytest <file>::<case>`. It writes and skips. Each file carries a header: scene, seed, ships, ticks, tpf, schema version, platform, and the reason for the last re-record.

**Where:** `tests/fixtures/golden_fights/<scene>.<platform>.json.gz` next to the existing `tests/fixtures/stock_particle_descriptors.json` (§7 R9 explains the platform suffix).

Keep `tests/oracle/*`: those tests compare against the original `stbc.exe` captures. They are a different kind of golden and they flip to native with D1 (§5.3).

---

## 6. What must run without the native module

| Consumer | Native module present? | Needs fire control? | Evidence |
|---|---|---|---|
| The game (`build/dauntless`, packaged or not) | always: `_dauntless_host` is built into the host via `PyImport_AppendInittab` (`native/src/host/host_main.cc:257-260`), with `dauntless_combat` linked statically (`native/src/host/CMakeLists.txt:28`) | yes | so D2 costs production nothing |
| Packaged builds | as above; `docs/packaging/{README.txt,MODDING.txt}` do not mention the switch or a Python-only mode | yes | grep |
| `tools/mission_harness.py` | importable if built: `engine/__init__.py:42-44` prepends `build/python` | **no**: Initialize-only, no `GameLoop`, no combat (lines 923-973) | |
| `tools/gameloop_harness.py` | mirrors conftest's path insert (line 21) | yes: `GameLoop()` (line 119-120) → `configure()`; AI StartFiring → `k1_system` | so a no-build run of it would need the module after D2 |
| Other tools that import `_dauntless_host` | `tools/bridge_shape_diff.py`, `bake_impulse_glow.py`, `bench_idle_passes.py`, `gen_mesh_fixes.py`, `shape_diff/{verify,frames}.py`, `probes/analyze_q13_constants.py` | no combat (**inferred** from their purpose) | |
| `tests/conftest.py` | optional: adds `build/python` if present (lines 60-64); every native test file skips without bindings (`skipif(_h is None …)`) | the reset turns the switch off (955-967) | |
| Transform store | `PythonTransformStore` without the module (`transform_store.py:325-328`); `tests/unit/test_transform_store_conformance.py` runs both backends | a native mirror needs the native store (**inferred**: rows register `_xform` slots, NC:1447-1449) | |
| Headless host under pytest (`OPEN_STBC_HOST_HEADLESS=1`) | uses the built `.so` | yes | `remaining-fallbacks-map.md` §2.1 |
| Sibling repos (`stbc-oracle`, `bc_mod_tools`) | not checked | unknown | **open** |

**Conclusion (derived):** nothing in production or in the engine's own tools needs fire control without the module. The only no-module consumers are a test run with no build and `tools/gameloop_harness.py` on an unbuilt tree. The remaining question is the test switch (§7 R1), not the module.

---

## 7. Risks and open questions

**R1. How does fire control run in a test that never calls `configure()`?** The conftest reset sets `_enabled = False` before every test (`tests/conftest.py:955-962`, NC:187-190), and D1 only changes what `configure()` decides (NC:158-176, called by `GameLoop.__init__`). After D3, `_pump_held_weapons` and `StartFiring` have nothing to run while `_enabled` is False (§5.2: about 40+ files). Options: the reset leaves it on (configure once per session); `enabled()` becomes "available"; or fire control ignores `_enabled`. Then `=0` still has to mean something for K0/K2/K3 (R2).

**R2. One global switch, four kernels.** `DAUNTLESS_NATIVE_COMBAT=0` turns off K0, K2, K3, K4, damage and the effect scope as well as K1 (§1.1). With K1's Python gone, `=0` cannot mean "all Python" any more, so the K0/K2/K3/damage differentials lose their reference arm (§5.1). Either split the switch (K1 always native, `=0` for the rest), or move those differentials to goldens in the same phase.

**R3. Silent off becomes a hard failure.** `configure()` quietly stays off when `available()` is false (a stale `.so` missing one of 21 bindings, NC:133-155) or `_self_check()` disagrees with the interpreter's `math.dist` / density (NC:415-450; "another interpreter may round differently, and then native must stay off"). With fire control required, each of these must raise loudly, or a stale build plays with no weapons. Linux runs live (MEMORY: Linux merged b9341c081). Windows has not been verified to pass `_self_check` (**open**).

**R4. K2's override guard is K1's.** K2 hands a ship or bank to Python on `k1_overridden` (K2C:388, 578, 794), which K1's watch maintains (NC:1852-1909, re-checked at K1 entry). Deleting it weakens K2's guard while K2 keeps its Python copy, or forces K2 its own flag.

**R5. `_drop` was designed around a Python fallback.** A value the mirror cannot encode drops the object's row; "from then on it takes the Python path" (NC:491-538, reached through `_call` NC:613-619). Nothing re-registers it (`register` runs at construction, NC:1434-1462). After D6, a dropped weapon system or ship never fires again, and K3/K4 already lose their whole step for a dropped ship (`remaining-fallbacks-map.md` §5.7). Counted drops: none in R1/R4/R5. Needs a ruling: refuse the value at the field, or re-register.

**R6. SDK reads keep Python copies of K1 rules.** `CanFire` (SDK 2 sites, with the `_depleted` side effect WS:1064-1067), `FireDumb` (SDK AI), and SWIG `Fire` (§2.6). Keeping them breaks decision 1. Routing them to native makes an SDK read a native call. The mirror is current between records, so that is **inferred** safe.

**R7. The walk's offset object.** Banks share the walk's offset *object* (ruling P5; differential line 15-16). `materialise` makes it with `_live_held_offset()` (NC:3734). With that deleted, the driver must build one per walk: a `TGPoint3` from the kernel's xyz, or the ship's/system's own object. That changes object identity relative to today's record, so the golden's "same object" field must be defined anew.

**R8. "Does not fire that tick" is not "nothing happened".** Every K1 write before the failing point is already logged and applied (K1H:62-67, 210-221): fire timers advanced, `_depleted` cleared, target list pruned, a cooldown set. For ASKs raised after a shot (`reseed`, K1C:793-797; `retry`/`is_dead` in the retry loop) the system **has** fired. D6 needs a definition per point: abort the walk with the partial writes kept, roll back to the system's first write (the kernel can roll back unreturned writes, `k1_roll_back`), or finish natively with a safe default.

**R9. Goldens across platforms.** The differentials compare two arms on one machine. A golden recorded on macOS compared on Linux or Windows depends on libm for `atan2`, `asin`, `sqrt` and on CPython's `math.dist` port (NC:415-431). Bit-exact digests may differ per platform (**inferred**; untested). Per-platform files, or a run that compares only on the recording platform, avoid false failures.

**R10. Determinism the goldens assume.** The K1 differential seeds every RNG (`_seed_every_rng`, line 121) and drives "the host's way, without GameLoop.tick" because AI draws on the unseeded module `random` (docstring lines 30-31). It isolates fight audio (`isolate_fight_audio`) and clears in-flight objects (`headless_mission.clear_in_flight`). A golden adds two dependencies the differentials did not have: test order and earlier tests' leaks (`project_pytest_order_pollution_17`) and GC timing (roadmap §7: process-owner lifetime resolved; `ConditionScript` cycle still open). A golden scene must pin both: a fresh process or `gc.collect()` at load (**inferred**).

**R11. Tractor port changes event timing.** STARTED/STOPPED post synchronously today, even inside the deferral scope (§3.1). Queued, E8M2's OD1 `StopFiring` lands one tick later (decision 9), after one tick of `cb.tractors`. Displacement ≤ `20 GU/s × 1/60 s` ≈ 0.33 GU (TR:45; derived). E7M2's win (`TractorHandler`) also moves a tick.

**R12. Tractor force cost and placement.** The force is per-ship Python every tick (TR:112-133) and writes the transform store mid-step. A native port moves the same writes into C++ (the combat library links `dauntless_transforms`, `native/src/combat/CMakeLists.txt:36`). Collisions still read them at frame end. With roadmap J (pipelining) that is a cross-thread write to poses (**open**).

**R13. Headless coverage gap.** `GameLoop` runs no combat step (GL:36-137). The campaign sweep and `tools/gameloop_harness.py` exercise StartFiring sessions only: no pump, no K2, no tractor force. Goldens for the pump have to be host-style (`_advance_weapons`/`_advance_combat` per tick, as the K1 differential and the oracle conftest do).

**R14. Mod ship classes.** The walk check's "ship class not stock" hand-back (HB:5600-5626) protects mod `ShipClass` subclasses that override `is_using_target_offset`/`GetTargetOffsetTG`. Roadmap decision 2 lists "ships" as a mod category, and for ships that is data, not Python classes (**inferred**). Confirm before deleting.

**R15. Box rule in aiming outside combat.** `_build_tractor_beam_render_data` and `_build_phaser_beam_render_data` draw beams through `_phaser_aim_point` → `target_offset_world` (HL:2455). D5 moves where Manual Aim beams are *drawn* on posed targets as well as where they hit. Render and damage stay consistent because they share the helper.

**Open (not established here):** whether any stock or installed mod hardpoint has a torpedo system with no ammo type (§2.7 #2); whether `stbc-oracle`/`bc_mod_tools` import `engine` without the module; the real size of a golden file; whether `TorpedoTube.CanFire` and `PulseWeapon.CanFire` have any SDK reader (the two stock `CanFire` sites read phaser banks, **inferred** from their names).
