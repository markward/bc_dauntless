> Snapshot map written 2026-11-02 at commit `9102c2f34` (branch `ws/combat-native-damage`, worktree `.claude/worktrees/native-combat-damage`). Input to roadmap workstream **D** ("move damage application to C++", `docs/superpowers/specs/2026-11-01-threaded-weapons-combat-roadmap.md` §4 D, decisions 7-8, §5). It maps facts and does not design; §9 lists candidate splits with their evidence. Line numbers drift: re-check one before relying on it. Anything not read directly off the code is marked **inferred**. Model documents: `k2-beams-map.md`, `k3-k4-map.md`, `remaining-fallbacks-map.md`.

# Weapon damage application — code map of `combat.apply_hit`

File abbreviations:

| Abbrev. | File |
|---|---|
| **CB** | `engine/appc/combat.py` |
| **HF** | `engine/appc/hit_feedback.py` |
| **HL** | `engine/host_loop.py` |
| **NC** | `engine/appc/native_combat.py` |
| **OBJ** | `engine/appc/objects.py` (`DamageableObject.DamageSystem`, `AddDamage`) |
| **SS** | `engine/appc/subsystems.py` |
| **SH** | `engine/appc/ships.py` |
| **WS** | `engine/appc/weapon_subsystems.py` |
| **PR** | `engine/appc/projectiles.py` |
| **SD** | `engine/appc/ship_death.py` |
| **PS** | `engine/appc/part_severance.py` |
| **HW** | `engine/appc/hull_wear.py` |
| **HHS** | `engine/appc/hull_hit_smoke.py` |
| **EV** | `engine/appc/events.py` |
| **HIO** | `engine/host_io.py` |
| **MIRH** | `native/src/combat/include/dauntless/combat/mirror.h` |
| **BG / WG / FG** | `native/src/combat/src/{beam_geometry,weapon_geometry,fire_gates}.cc` |
| **K2H / K3H** | `native/src/combat/include/dauntless/combat/{k2_beams,k3_projectiles}.h` |
| **SDK** | `<sdk root>/Build/scripts/` (resolved via `settings.json`) |

---

## 0. The headline

1. **One hit is a long synchronous Python chain**, not arithmetic. `_apply_hit` (CB:624-913) does ~40 lines of float math, then calls `ShieldSubsystem.ApplyDamage` (SS:2359) and `DamageSystem` (OBJ:1074) per overlapping subsystem; each `DamageSystem` runs `SetCondition` → `_condition_changed` (watchers, `ET_SUBSYSTEM_*` events, `internal_blast.queue`) → repair auto-enqueue (`ET_ADD_TO_REPAIR_LIST`) → zero-crossing routing → on a critical zero, `ship_death.begin` (RNG, the SDK death script, `ET_OBJECT_EXPLODING`, and **death-splash `apply_hit`s on every other ship, nested inside this one**). Then `hit_feedback.dispatch` (renderer calls, RNG, wall-clock audio gate, persistent wear, **part severance that destroys subsystems**), then `ET_WEAPON_HIT`.
2. **Every event dispatches synchronously** (EV:802-845) and handlers run *inside* the hit. Some mutate state later hits read (E8M2 `WeaponHitMatan` calls `SetHurtable(0)`; E3M5 `MatanWeaponHitHandler` clamps hull and power at 15%; §6.3).
3. **Frequency is low** in the 64-ship fight: K2 damage pulses **0.41 per tick**, K3 torpedo hits **0.077 per tick** (`remaining-fallbacks-map.md` §2.3, R1/R3). Resting K2 contacts (presentation only) are **17.6 per tick** and are where the phaser Python cost sits (round-trips spec §10). No measurement of `apply_hit`'s own cost exists (§10).
4. **Half the inputs are already mirrored** (transforms, hull box, shield-generator state, subsystem condition/radius/position/parent, mount order, posed parts, cheat flag for NPC shields). **Not mirrored:** shield face charges and ramp fractions, ship `_invincible`/`_hurtable`, subsystem `_invincible`/`_critical`, `god_mode`/`double_player_weapons` cheats, bank/torpedo `_damage_radius_factor`, bank `_max_damage`/`_max_damage_distance`, `PhaserSystem._power_level`, torpedo `_damage` (§2).
5. **Shield faces are written in place** (`_current_shields[f] = …`, SS:2404/2406, also 2138/2147/2331/2348): the WakeField/NativeField "bypass trap". Mirroring them needs explicit pushes at every writer.
6. **No WakeField/FrozenField is written on the non-lethal chain** (`_condition` is a plain `NativeField`, SS:326; the face list and repair queue are plain containers). The kernels read `_condition`, `_dying` etc. through the mirror, which those NativeFields already push.
7. **The shared SDK RNG** (`App.g_kSystemWrapper`, Python `random.Random`, App.py:993-1003) is drawn by smoke (HHS:94, 145), audio (`GetRandomSound`, SDK `LoadTacticalSounds.py:165`) and death (`death_cascade.py:134`). The audio draw is **gated on wall-clock time** (HF:187-200, `time.monotonic`), so the stream's consumption is already not a pure function of game state when a sound manager exists.
8. **Existing native pieces cover the geometry**: `shields_block`, `shield_bubble_entry` (BG:182, 214), `subsystem_world_position` with posed parts and memo (WG), aggregate `is_disabled`/`is_destroyed` (FG:84, 95), `GetMaxCondition` (sensor_detect.cc:208), mount order (MIRH `ObjectRow::mount_order`), K4's eligibility set. **No native `_shield_face_from_hit_point`, `_splash_weight`, `ApplyDamage` ramp or `DamageSystem`.**

---

## 1. Callers

| # | Caller | When | kwargs passed | Reached from a native record? | Frequency evidence |
|---|---|---|---|---|---|
| C1 | `HL._phaser_contact` HL:1249-1256 (damage branch, `flush_dwell > 0` and `damage > 0`) | `cb.phasers`, inside the K2 walk | `(target, damage, impact_point, source=ship, normal=impact_normal, ship_instances, weapon_type="phaser", hardpoint_weapon=bank, damage_hull=(sys_.GetPowerLevel() != sys_.PP_LOW) (HL:1247), shield_point=bubble_entry)` | **Yes, K2 CONTACT record**: `run_k2` NC:3757 → `_k2_contact` NC:3629 → `_k2_run_contact` NC:3664-3682 → `hl._phaser_contact(...)`. The damage arithmetic (`_phaser_damage_for_tick` HL:958-983 × `PHASER_INTENSITY_SCALE[level]` HL:955, level = `sys_.GetPowerLevel()` HL:1193) is Python (K2H:94-96). After it: `cx.resend()` NC:3771 | R3: 1,840 damage pulses / 4,499 ticks = **0.41 per tick** (`remaining-fallbacks-map.md` §2.3, §4) |
| C2 | `HL._advance_combat_step` HL:1332-1341 (after `cb.projectiles`) | once per K3/Python hit, in `hits` order | `(ship, torpedo._damage, hit_point, source=torpedo._source_ship, normal=hit_normal, ship_instances, weapon_type="torpedo", hardpoint_weapon=torpedo, shield_point=torpedo._bubble_entry)` | **Yes, K3 DONE**: `projectiles.update_all` PR:880 → `NC.run_k3` NC:4282 → `_k3_walk` NC:4321-4356 builds `out` (rebuilding the bubble/hit-point identity alias, NC:4344-4352); the loop at HL:1332 calls `apply_hit` per entry | R1: 689 hits / 8,999 ticks = **0.077 per tick** (`remaining-fallbacks-map.md` §2.3) |
| C3 | `collisions._grind_contact` collisions.py:597-616 | per frame, host collision pass (outside `sim.combat`, HL:~12787 comment) | `(obj, damage, pt, source=other, normal, ship_instances, weapon_type="collision", hit_tangent, decal_radius=scuff_radius, decal_dent=0.0, bypass_shields=not shielded, shield_point)` | No | not counted |
| C4 | `collisions._respond_pair` collisions.py:880-905 | per closing impact | as C3 plus `decal_dent=1.0, single_impact=True, shield_radius=flash_r` | No | not counted |
| C5 | `DamageableObject.AddDamage` OBJ:1041-1042 (ShipClass only) | SDK `AddDamage` (Effects, missions), the death cascade (death_cascade.py:246; "roughly 7-20 `AddDamage` calls" per death, death_cascade.py:18), the NanoFX shim (NanoFX_ScriptActions.py:46) | `(self, fDamage, pEmitPos, source=None, splash_radius=fRadius, bypass_shields=True)` | No | not counted; **inferred** a few per death |
| C6 | `splash_damage.apply` splash_damage.py:77-83 (from `ship_death.begin` SD:74-113) | at the blast moment of every death, per ship in range | `(target, amount * w, point, source=ship, normal, ship_instances, weapon_type="torpedo", splash_radius=radius, bypass_shields=True)`; wrapped in try/`log_swallowed` | No — but it runs **nested inside** whatever `DamageSystem` started the death (C1/C2 included) | not counted |
| C7 | `rocks/scenery_contact.respond` scenery_contact.py:136-142 | field-rock contact with the player | `(player, damage, pt, None, normal, ship_instances, weapon_type="collision", hit_tangent, decal_radius, decal_dent=1.0, bypass_shields=not shielded, shield_point, single_impact=True, shield_radius)` | No | not counted |

Not callers but the same mutation surface: `radiation.py:165` calls `ship.DamageSystem(hull, amount)` directly (gated on `IsImmuneToDamage`, radiation.py:150), and stock SDK scripts call `DamageSystem` directly (TacticalInterfaceHandlers, E2M6, E5M2, E6M2, E6M4, E6M5, E7M3, Vesuvi5_S: `grep DamageSystem(` in SDK). `host_loop` reads `combat.apply_hit` as a module attribute so tests can monkeypatch it (HL:102-103).

---

## 2. `_apply_hit` step by step (CB:624-913)

`apply_hit` (CB:610-621) wraps it: `step_memo.forget()` before and in a `finally` after. `forget` also runs the native hook `_h.combat_memo_clear` (registered NC:4433 via `step_memo.on_forget`), so **every hit clears the native sensor and mount memos too**.

### 2.1 Reads, in order

"Native today" = the value is already in a native table the kernels read (MIRH rows, TransformStore, K2/K3 per-step context).

| # | CB line | Read | Native today? |
|---|---|---|---|
| R1 | 718 | `weapon_splash_radius(hardpoint_weapon, payload_template)` CB:64-83: `hasattr(hw,"GetDamageRadiusFactor")`, `hw.GetDamageRadiusFactor()` (bank: `_damage_radius_factor` SS:403/905; torpedo: slot `_damage_radius_factor` PR:112/248), then payload, else `PHASER_DEFAULT_DAMAGE_RADIUS` 0.15 | **No** (neither DRF is mirrored; K2H:96 says "weapon_splash_radius ... stay Python") |
| R2 | 719-720 | `splash_radius` kwarg override | caller-supplied |
| R3 | 727-731 | `App.Game_GetCurrentGame().GetPlayer()` in try/except | Partly: `_k2_player_handle` NC:3503 is sent in the K2/K3 context **only while the disable-NPC-shields cheat is on** (`_K2Context.delta` NC:3538-3600) |
| R4 | 736 | `dev_combat_cheats.double_player_weapons_active()` (dev_combat_cheats.py:47) | **No** |
| R5 | 745-747 | `implements(ship,"IsImmuneToDamage")` (core/ids.py:148) and `ship.IsImmuneToDamage()` = `_invincible or not _hurtable` (SH:1828-1831; set SH:1819-1820, 1825-1826; init SH:121-122) | **No** |
| R6 | 752-753 | `dev_combat_cheats.god_mode_active()` (:43) with `_target_is_player` | **No** |
| R7 | 758 | `ship.GetShields()` | Yes: `ObjectRow::_shield_subsystem` (MIRH), `has_real_get_shields` |
| R8 | 762 | `shields_block(ship)` CB:343-388: `HasShields` (`sum(_max_shields) > 0`), `IsOn`, `IsDisabled`, `IsDestroyed`, `cloak_shields_suspended` (CB:580-591), `disable_npc_shields_active` + player | **Yes**: `BG shields_block` BG:182-209 (`has_shields`, `_is_on`, `_condition/_max_condition/_disabled_percentage/_destroyed`, `_cloak_state`, ctx `npc_shields_off`/`player`). K2 and K3 already compute it per contact/hit (K2H:367, K3H:131) |
| R9 | 765 | `bypass_shields` kwarg | caller |
| R10 | 767 | `hasattr(shields, "ApplyDamage")` | class fact |
| R11 | 781-782 | `_shield_face_from_hit_point(ship, shield_point or hit_point)` CB:485-577: `_body_frame_delta` (CB:144-171: `GetWorldLocation`, `GetWorldRotation().GetCol(0..2)`), `_hull_box_for` (CB:308-340: `_shield_hull_box`, `GetScale()`) | Inputs **yes** (TransformStore pos/rot, `_shield_hull_box_center/_half`, `hull_box_set`, `_scale`); the function itself **no** native port |
| R12 | 785 / 789 | `shields.ApplyDamage(face, remaining)` reads `_current_shields[f]`, `_max_shields[f]`, `_ramp_fraction[f]` (SS:2389-2406); god-mode path reads `GetCurrentShields(face)` | **No** (only the derived `has_shields`, via `HasShieldsField` NC:844 / `push_has_shields`) |
| R13 | 800 | `ship.GetHull()` | Yes: `ObjectRow::_hull` |
| R14 | 809 | `hasattr(ship, "DamageSystem")` | class fact |
| R15 | 839 | `_iter_subsystems(ship)` CB:268-305: `GetSubsystems()` (SH:1202-1223, fixed slot order sensor, impulse, warp, torpedo, phaser, pulse, tractor, shield, power, repair, cloak, hull) then each one's `_children`; hull skipped | Yes: `ObjectRow::mount_order` (pushed by `push_mount_order` NC:1597 from `_mount_order` NC:1583 → `part_severance._mounted_subsystems` PS, same walk, subsystems whose `GetPosition()` answers; -2 for an unnameable one) |
| R16 | 840 | `sub.GetPosition()` (`_position`, default `TGPoint3(0,0,0)` SS:382) | Yes: `_position` (PartKeyField, SS:345) |
| R17 | 843 | `sub.GetRadius()` (`_radius` SS:854) | Yes: `s_radius` |
| R18 | 844 | `_subsystem_world_position(ship, sub)` → `subsystems.subsystem_world_position` (SS memoised by `(id(sub), id(ship))` while `step_memo.active()`; computation: ship pos + R·`part_transform_point(local, prop=physical_parents.property_of(sub))`, no scale) | **Yes**: `WG subsystem_world_position(m, sub, ship_arg, use_memo)` (weapon_geometry.h:50-55), posed parts included, memo in `SensorState::mounts` |
| R19 | 848-853 | `d = (dx*dx+dy*dy+dz*dz) ** 0.5`; `d >= r_sub + r_hit`; `_splash_weight` CB:189-208 | arithmetic, no port |
| R20 | 861-862 | `implements(sub,"IsInvincible")`, `sub.IsInvincible()` (`_invincible` SS:1257-1261) | **No** |
| R21 | 864, 868 | `_subsystem_state_flags(sub)` CB:231-242: `IsDamaged`, `IsDisabled`, `IsDestroyed` (WeaponSystem overrides aggregate over `_children`, WS:1467-1497) | `IsDisabled`/`IsDestroyed`: **yes** (`FG is_disabled`/`is_destroyed` FG:84-103 implement the aggregate; leaf `FG:64-78`). `IsDamaged` reads `_damaged` (**not** mirrored) but `_diff_state` ignores it (CB:245-265) |
| R22 | 873 | `_pick_primary_subsystem_for_dispatch(allocations)` CB:211-228 (strict `w > best`: ties go to first) | arithmetic |
| R23 | 878-894 | `hit_feedback.dispatch(...)` (§4) | — |
| R24 | 910-912 | `_WEAPON_TYPE_IDS` CB:603-607; `isinstance(ship, App.TGEventHandlerObject)` | constants |

### 2.2 Writes and calls with effects, in order

| # | CB line | Write / call | Notes |
|---|---|---|---|
| W1 | 617 | `step_memo.forget()` + native `combat_memo_clear` | entry |
| W2 | 737 | `damage = float(damage) * 2.0` (cheat, local) | local |
| W3 | 785 | `shields.ApplyDamage(face, remaining)` → in-place `_current_shields[f]` | only if `_commit`; §3.1 |
| W4 | 811 | `ship.DamageSystem(hull, post_shield, source)` | only if `_commit and damage_hull`; §3.2 |
| W5 | 866 | `ship.DamageSystem(sub, post_shield, source)` per overlapping subsystem in `_iter_subsystems` order | only if `_commit and not sub_immune`. Each subsystem is offered the FULL `post_shield` (CB:815-837 comment) |
| W6 | 878 | `hit_feedback.dispatch(...)` in try/except → `dev_mode.log_swallowed` (CB:895-896) | §4 |
| W7 | 902-913 | `WeaponHitEvent(is_hull_hit=post_shield>0)`, `SetSource/Target/Damage/HitPoint/Normal/Radius/Subsystem/WeaponType`, `SetDestination(ship)`, `g_kEventManager.AddEvent` | §6 |
| W8 | 621 | `step_memo.forget()` + native clear | exit (also on exception) |

Locals that feed dispatch/event: `absorbed_shields` (CB:792), `post_shield` (794), `absorbed_hull = post_shield` (812, set even when `damage_hull` is False), `absorbed_subsystem_total += post_shield` per overlap (867, counted even when immune), `allocations`, `primary_transition` (first non-None `_diff_state`, 869-871), `primary_subsystem` (873), `r_hit`, `_commit` (→ `persist_decal`).

`hit_point` is passed by reference to dispatch and to `SetHitPoint` (EV:434). On K3's fallback-tier bubble hit `hit_point is shield_point` (NC:4344-4349; `k3-k4-map.md` A5).

---

## 3. The mutation chain

### 3.1 `ShieldSubsystem.ApplyDamage(face, amount)` SS:2359-2406

`cur = _current_shields[f]`, `mx = _max_shields[f]`; `mx <= 0 or cur <= 0` → return `amt`. `frac = _ramp_fraction[f]` (set only on the 0.5 s charge tick, SS:2318; `None` until then → `cur / mx`). `frac <= 0.1` → bypass (return `amt`); `frac >= 0.6` → `b = 0.0`; else `b = 0.6 * (1.0 - 2.0 * (frac - 0.1))`. `new = cur - (1.0 - b) * amt`; `new >= 0` → `_current_shields[f] = new`, return `b * amt`; else `_current_shields[f] = 0.0`, return `b * amt - new`.

Side effects: **one in-place list write**. No event, no watcher update (watchers are refreshed by `Update` SS:2273-2356 and `SetCurrentShields` SS:2147-2154), no wake, no mirror push. Other writers of the same lists: SS:2138 (`SetMaxShields`), 2147, 2318 (`_ramp_fraction`), 2331, 2348 (charge tick), `__init__` SS:2083-2090, and pickled-state restore (**inferred**, 39 SDK classes round-trip via `__getstate__`).

### 3.2 `DamageableObject.DamageSystem(subsystem, amount, source)` OBJ:1074-1094

| Step | Line | Effect |
|---|---|---|
| D1 | 1083-1089 | `None` or `amt <= 0` → return. `cur = GetCondition()`, `new_cond = max(0.0, cur - amt)` |
| D2 | 1090 | `subsystem.SetCondition(new_cond)` → SS:733-745 |
| D2a | SS:743 | `_condition = max(0.0, float(value))` — **NativeField push** (SS:326) |
| D2b | SS:744 → `_condition_changed` SS:786-811 | `_combined_watcher._update(GetConditionPercentage())`, `_condition_watcher._update(...)` (FloatRangeWatcher, float_range_watcher.py: fires a registered check's event via `AddEvent` on a crossing; checks iterate `self._checks.values()` in insertion order). SDK consumer: `Conditions/ConditionSystemBelow.py:94,139` (`GetConditionWatcher`) — AI conditions |
| D2c | SS:797-811 | threshold state machine (`_threshold_state_now`: `IsDestroyed`, `IsDisabled`): on change `_fire_threshold_event` SS:1123-1137 posts **`ET_SUBSYSTEM_DESTROYED`** (+ `internal_blast.queue(self)`, a list append, internal_blast.py:61) / **`ET_SUBSYSTEM_DISABLED`** (only from OPERATIONAL) / **`ET_SUBSYSTEM_OPERATIONAL`**; source = subsystem, destination = owning ship (`_owning_ship` SS:1110) |
| D2d | SS:744-745 → `_auto_enqueue_for_repair` SS:748-757 | if `_condition < GetMaxCondition()`: `ship.GetRepairSubsystem().AddToRepairList(self)` SS:2881-2899: rejects duplicates (identity scan of `_queue`), `cond <= 0`, undamaged; on add appends and posts **`ET_ADD_TO_REPAIR_LIST`** (dest = the repair subsystem, `_fire_repair_event` SS:2968). Exceptions swallowed |
| D3 | 1091 → `_route_zero_crossing` OBJ:814-836 | only on `cur > 0 and new <= 0`: power plant (targetable) → `warp_core_breach.arm(ship)` (list append, warp_core_breach.py:51-58); hull → `subsystem_cascade.schedule(ship)` (list append, gated on `SetDestroyBrokenSystems`, subsystem_cascade.py:36-45) |
| D4 | 1092-1100 | `new_cond <= 0 and IsCritical() and not IsDying() and not IsDead()` → rock: `rocks.death.begin(self, killer=source)`; else `ship_death.begin(self, killer=source)` |

`ship_death.begin` SD:74-113: `_out_of_action` guard; `SetDying(True)` (`_dying` NativeField push); `death_cascade.roll_duration` + `death_cascade.begin` (**RNG**: `GetRandomNumber`, death_cascade.py:134-279, plus `GetRandomPointOnModel`); `_active.append`; `RunDeathScript()` (**SDK Python**, swallowed); `_broadcast_exploding` SD:282-306 → **`ET_OBJECT_EXPLODING`** (src = dest = ship, killer as firing id); `splash_damage.apply(ship)` → **nested `apply_hit` (C6) on every other ship in range**, each with its own events and possibly its own death. All of this happens **before** the outer hit's remaining subsystems, its feedback and its `ET_WEAPON_HIT`.

Not on this chain: `SetDestroyed` (only `DestroySystem` OBJ:1102), `IsDead` (set later in `ship_death.advance`), lock clearing (later). Deferred work queued here runs in `cb.death` / `cb.damage_sys` (HL:1350-1375).

### 3.3 Passive state, power, repair

- **No WakeField or FrozenField is written** by D1-D4 or ApplyDamage (read off: `_condition` is `NativeField(float)` SS:326; faces and `_queue` are plain lists). A full idle bank does not read condition before its early-out (WS:955-983; passive spec 2026-10-30 §6.3 "Power and condition changes do NOT wake a full idle bank"); the power plant is never frozen (passive_power.py:3-4) and reads its own condition every tick (SS:2502, 2520); the repair bay reads its condition in `Update` (SS:2953). Nested paths (death script, SDK handlers, `part_severance.sever`) were not traced exhaustively.
- **Mirror pushes on the chain:** `_condition` per `SetCondition`, `_dying` on death, `push_posed_parts` on a sever (PS `sever`). Each is one native call through `NativeField.__set__` (NC:459).

### 3.4 Where SDK / mission Python can intercept

| Lever | Where read | Kind |
|---|---|---|
| `ShipClass.SetInvincible` / `SetHurtable` (SH:1816-1831; SDK: 18 files call `SetInvincible(`, 3 `SetHurtable(`) | R5 → `_commit` | flag (decision 8 shape) |
| `ShipSubsystem.SetInvincible` / `MissionLib.MakeSubsystemsInvincible` (SDK MissionLib.py:2237-2251, recurses into children) | R20 | flag |
| `SetCritical` (SS:1178) | D4 | flag |
| `SetDestroyBrokenSystems` (SH:1810; read by `subsystem_cascade.schedule`, subsystem_cascade.py:40) | D3 | flag |
| `SetDeathScript` → `RunDeathScript` | D4 | SDK Python inside the hit |
| Condition watchers (`GetConditionWatcher`, `GetCombinedPercentageWatcher`, shield `GetShieldWatcher`) with registered ranges | D2b | events inside the hit |
| Handlers on `ET_SUBSYSTEM_*`, `ET_ADD_TO_REPAIR_LIST`, `ET_OBJECT_EXPLODING`, `ET_WEAPON_HIT` | D2c, D2d, D4, W7 | synchronous handlers (§6.3) |
| `GetMaxCondition` via a **shared property template** (SS:759-772; E1M2 `SetMaxCondition(300)`) | D2b/D2d | data |
| Dev cheats (god mode, 2× weapons, NPC shields off) | R3-R8 | dev-only flags |
| Tests monkeypatching `combat.apply_hit` (HL:102-103) | callers | scaffolding |

No handler can gate the hit that posts `ET_WEAPON_HIT`: it is posted after every mutation (W7). Roadmap §5.1's deciding events (`ET_ENVIRONMENT_DAMAGE`, `ET_OBJECT_CONVERTED_TO_HULK`, `ET_SHIELDS_SET_STATE`) are not posted on this chain.

---

## 4. `hit_feedback.dispatch` HF:221-447

Inputs: `ship, source, point, normal, damage, subsystem (primary), absorbed_shields, absorbed_subsystem, absorbed_hull, sub_transition, ship_instances, weapon_type, radius (r_hit), persist_decal (_commit), allow_structural_wear (damage_hull), tangent, decal_radius, decal_dent, shield_point, single_impact, shield_radius`.

Order of operations:

| # | HF line | Step | Class |
|---|---|---|---|
| F0 | 278-287 | `hull = ship.GetHull()`; `classify(...)` HF:152-160 → SHIELD / HULL / CRITICAL | pure |
| F1 | 303-330 | `_absorbed_fraction = absorbed_shields / damage`; if ≥ 0.05 and the ship has an iid: `host_io.shield_hit(iid, _mesh_xyz(ship, shield_point or point), (0,0,0,0), shield_impact_intensity(weapon_type, single_impact) * fraction, shield_radius or radius)` | (a) presentation |
| F2 | 335-338 | `severity != SHIELD` → `_hull_impact_visual` HF:502-561: `spark_params`, `is_rock` → rock sparks, `host_io.world_to_body` (needs iid and a normal), `hit_vfx.spawn(...)` (appends a dict to `hit_vfx._active`, hit_vfx.py:34-70; aged in `cb.vfx`, pushed in `cb.render_data`) | (a) presentation (Python-side VFX list) |
| F3 | 345-348 | `hull_hit_smoke.maybe_emit` HHS:57-104: weapon roll table, `is_rock`, effect level, `normal`, **phaser throttle per `(id(ship), id(source))` on game time** (HHS:86-91, `_last_smoke_roll`), then **`GetRandomNumber(10)`** (HHS:94), iid, `world_to_body`, `_emit_smoke` → **`GetRandomNumber(30)`** (HHS:145) + SDK `Effects.CreateSmokeHigh(...)` (SDK Python; builds a particle controller) | (a) presentation + (c) RNG |
| F4 | 354-355 | `_audio_should_play(ship, severity)` HF:187-200: **`time.monotonic()`** edge trigger per `(id(ship), severity)` (0.15 s gap), writes `_last_dispatch_time` every call → `_play_audio` HF:450-499: needs `App.g_kSoundManager`; SHIELD+non-torpedo silent; else `LoadTacticalSounds.GetRandomSound` (**RNG**, SDK LoadTacticalSounds.py:150-172, also mutates `g_dRecentSounds`) or `LoadDamageHitSounds`; `mgr.GetSound(name).Play(position=...)` | (a) + (c), **wall-clock gated** |
| F5 | 360-368 | player lookup again (`Game_GetCurrentGame().GetPlayer()`); player and not SHIELD → `camera_shake.apply_kick(damage)` (module float, camera_shake.py:71-78) | (a) presentation |
| F6 | 376-424 | `persist_decal and absorbed_hull > 0 and normal and iid`: decal throttle `_last_decal_emit[(id(ship), wclass)]` on game time (0.2 s, HF:113-114); on emit `host_io.damage_decal_add(...)` (renderer decal ring). Then if `_structural_hit` (HF:203-218): `hull_wear.wear_for_hit` (HW:74-84); phaser → `accumulate_phaser` (HW:115-142: 1-2 `world_to_body`, body-frame `_pending[id(ship)]`, may `flush` first) and `flush` on emit; else `hull_wear.send` (HW:101-108: `host_io.hull_damage_add` to the renderer HullDamageStore, then `hull_breakup.after_wear`) | (b) **persistent**: decal ring and HullDamageStore records live in the renderer; `hull_breakup.after_wear` (hull_breakup.py) throttles per ship and queues a native structure-part check whose result is applied later by `hull_breakup.drain` (HL:12812) — chunk spawns and `SetCondition(0.0)` on subsystems inside the severed piece (deferred game state) |
| F7 | 431-447 | structural, `absorbed_hull > 0`, normal, `persist_decal`, iid, and `damage_eligibility.is_eligible(ship)` (K4's set, damage_eligibility.py:86-88) → `world_to_body` → `part_severance.record_hit(ship, iid, body_point, absorbed_hull)`: per-part totals; past the threshold `sever` → `_parts_detached.add`, `native_combat.push_posed_parts`, `_destroy_subsystems_on_part` (**`SetCondition(0.0)` per subsystem on the part → D2b/D2c events, synchronously, inside the hit**), emitters silenced, `part_detach_render.detach` | (b) **game state, synchronous** |

(c) **Random numbers:** all from `App.g_kSystemWrapper` (one `random.Random`, App.py:993-1003; tests seed it with `seed_every_rng`, tests/helpers/k3_fight.py:63-73). Per hit: F3 0-2 draws plus whatever `Effects.CreateSmokeHigh` draws (SDK, not counted here); F4 0-1 draw (wall-clock and sound-manager gated). `death_cascade` draws on a lethal hit (§3.2). No other RNG in `_apply_hit` itself (read off CB:624-913).

(d) **Cost structure** (read off the code; not measured, §10): no loops in dispatch except inside `record_hit`'s geometry (only ships with detachable parts) and `GetRandomSound`'s list copy. Host calls per hit, upper bound: F1 2 (`instance_translation` + `shield_hit`, HIO:384-404), F2 2 (`world_to_body` = `instance_translation` + the call, HIO:406-416), F3 2, F6 2 (decal) + 2-4 (phaser wear) or 2 (`hull_damage_add`) + 1 (`hull_damage_add_body` on flush), F7 2. Each `_mesh_xyz` (HF:143-149) calls `frames.containing_set`, `frames.view_offset`, `frames.shifted` (a TGPoint3). Two player lookups per hit (CB:727-731, HF:360-365). Allocations: TGPoint3s, tuples, one dict per `hit_vfx.spawn`, one `WeaponHitEvent`. Module dicts keyed by `id()`: `_last_dispatch_time`, `_last_decal_emit`, `_last_smoke_roll`, `hull_wear._pending`.

---

## 5. K2 resting contacts (no damage pulse) — the "level ii" lever

Path at the time of writing (after round trips, Task 3): the kernel queues the contact; `_k2_deliver` NC:3634-3661 runs it before the next Python-running record → `_k2_run_contact` NC:3664-3682: `_k2_points` (3-5 TGPoint3s, NC:3610-3626), `hl._phaser_level(sys_)` (`sys_.GetPowerLevel()`, `PhaserSystem._power_level` WS:2343, **not mirrored**) → `_phaser_contact` HL:1203-1235 branch `flush_dwell <= 0`: *(Superseded 2026-11-02 by the presentation queue, spec `2026-11-02-combat-effect-queue-design.md`: resting contacts are queued natively and drained after DONE; shielded ones are presented in C++, the rest by `_k2_present_batch`; records end `(..., writes)`. `PhaserSystem._power_level` is mirrored since weapon state.)*

| Step | Line | Read / call | Native today? |
|---|---|---|---|
| P1 | HL:1222-1226 | `tick_damage = _phaser_damage_for_tick(bank.GetMaxDamage(), bank.GetMaxDamageDistance(), dist, dt) * PHASER_INTENSITY_SCALE[level]` | `dist`, `dt` yes; `_max_damage`, `_max_damage_distance` (SS:398-399), `_power_level` **no** |
| P2 | HL:1230 | `combat.weapon_splash_radius(bank, None)` | **no** (bank DRF) |
| P3 | HF:564-612 `beam_contact` | `shields_block` (passed in by K2 unless an ASK answered it, NC:3678-3682) | yes |
| P4a | HF:595-607 | shielded: `ship_instances.get`, `_mesh_xyz(ship, shield_point or point)`, `host_io.shield_hit(iid, xyz, (0,0,0,0), shield_impact_intensity("phaser")=0.325, radius)` | iid table and view offset are in the K2 context; the call is Python→host |
| P4b | HF:609-612 | not shielded: `_hull_impact_visual(severity=HULL, absorbed_hull=tick_damage)` → `spark_params` (sparks iff `tick_damage >= 80` HF:33), `is_rock` (mirrored), `world_to_body` (needs a normal: mesh tier only), `frames.containing_set`, `hit_vfx.spawn` | `is_rock` yes; the VFX list is Python |

Per contact: no damage, no event, no RNG, no persistent state (K2H:59; `remaining-fallbacks-map.md` §3.3). 17.6 per tick (R1), ~0.25 ms per tick of Python with round trips (R2), and that presentation is why `cb.phasers` stayed flat at 0.749 → 0.737 ms (round-trips spec §10).

**Overlap with `dispatch`:** P4a is F1 without the absorbed-fraction gate and scaling (and without `single_impact`/`shield_radius`); P4b is exactly F2 (`_hull_impact_visual`) with `severity=HULL`. A resting contact never runs F3-F7 (smoke, audio, shake, decal, wear, severance) or any of §2-§3. A native port of P4a/P4b is therefore also a native port of F1/F2 for damage hits (inferred from the shared function).

---

## 6. Events and ordering

### 6.1 One non-lethal hit, in order

1. `step_memo.forget` (+ native memo clear).
2. Shield face write (no event).
3. Hull `DamageSystem` (if `damage_hull`): watcher events (if ranges registered and crossed) → `ET_SUBSYSTEM_DISABLED/DESTROYED/OPERATIONAL` (hull) → `ET_ADD_TO_REPAIR_LIST` (first damage) → zero-crossing queues.
4. Per overlapping subsystem in `_iter_subsystems` order: the same events for that subsystem.
5. `hit_feedback.dispatch`: renderer calls; on a severing hit, `ET_SUBSYSTEM_DESTROYED` for each subsystem on the part (F7).
6. `ET_WEAPON_HIT`: `AddEvent` EV:802-845 runs the destination's instance handlers first (`dest.ProcessEvent`, EV:811; chained by `CallNextHandler`), then broadcast function handlers (snapshot, EV:818-828, exceptions logged), then broadcast method handlers (EV:830-842).
7. `step_memo.forget`.

### 6.2 A lethal hit

At the first critical subsystem reaching 0 (normally the hull at step 3): `SetDying` → death cascade planned (RNG) → death script (SDK) → `ET_OBJECT_EXPLODING` → death-splash `apply_hit`s on other ships (each a full §6.1/§6.2, recursively) → back to the remaining subsystems of the original hit → feedback → `ET_WEAPON_HIT`. A ship hit again later in the same tick still takes the hit (K3 applies every hit in the list even if an earlier one killed the target, `k3-k4-map.md` A6.7); `DamageSystem` skips only the death call (`IsDying`, OBJ:1093).

### 6.3 SDK handlers on these events (stock scripts)

| Event | Handler | Reads / does | Effect on later hits |
|---|---|---|---|
| `ET_WEAPON_HIT` | `MissionLib.FriendlyFireHandler` (SDK MissionLib.py:3581, 3688-) broadcast | accumulates friendly damage (`GetDamage`), may end the mission | mission state |
| | `Conditions/ConditionAttacked.py:54`, `ConditionAttackedBy.py:68` (method broadcast, no target filter: **every instance runs on every hit**) | `GetDestination`, name compare, `IsHullHit`, `GetFiringObject`, `GetShields().GetMaxShields` | AI condition state |
| | `Bridge/XOCharacterHandlers.PlayerHit` (player instance) | crew reaction | UI |
| | **E8M2 `WeaponHitMatan`** (E8M2.py:4856-) | on a TORPEDO hit: cloak `SetConditionPercentage(0)`, **`SetHurtable(0)`** | **gates every later hit on Matan, including later hits in the same tick** |
| | **E3M5 `MatanWeaponHitHandler`** (E3M5.py:967-) | clamps hull and power to ≥ 15% (`MissionLib.SetConditionPercentage`) | **reads the post-damage state and rewrites it**; a hull hit to 0 has already begun the death (D4) before this runs |
| | E7M2 (1373, 1431), E8M1 (968-969, 1600), E6M1 (2518-2520), E4M6, E3M4 (595-596), E3M1 (565, 2201, 2865, 3505, 3593), E2M6 (626), E2M2 (577), E2M0 (819) | mission beats (AI changes, dialogue, goals) | mission state |
| `ET_SUBSYSTEM_*` | Engineer crew (`EngineerCharacterHandlers`, SS:1126 comment), AI conditions | report | AI/UI |
| `ET_OBJECT_EXPLODING` | missions (E1M2 counting, friendly-fire game over SD:283-294) | report; order-sensitive (roadmap §5.2) | mission state |
| watcher events | `ConditionSystemBelow`, `ConditionSingleShieldBelow`, Brex | AI / crew | AI/UI |

### 6.4 Ordering relative to the kernels

- **K2:** a damage pulse is applied **mid-walk**; ruling P1 requires the next bank on the same target to see the shields and hull it left (`remaining-fallbacks-map.md` §4). Resting contacts queued before it run first (ruling E5). After the record, `cx.resend()` (NC:3771) and the kernel re-reads the mirror (`_condition`, `_dying` pushed by NativeFields). Face charges are not read by K2 (its `shields_block` is generator-level), so a native damage pulse would be the first kernel to need them.
- **K3:** hits are decided on a static world and applied after the step, in `moving` order, each fully (events included) before the next (`k3-k4-map.md` A6.7). Every `ET_TORPEDO_EXITED_SET` for a hit torpedo precedes its `ET_WEAPON_HIT` (A5).
- `cb.vfx` ages `hit_vfx` after the torpedo loop and before the phaser step (HL:1343-1348), so a hit VFX spawned by K3 hits is aged once in the same tick and a K2 one is not (read off the order).

---

## 7. Determinism hazards for a bit-exact port (`.hex()` parity)

| # | Where | Hazard |
|---|---|---|
| H1 | CB:848; also CB:46, 452, 467 in the bubble/sphere helpers (`** 0.5`) | `x ** 0.5` is libm `pow`, not `sqrt`: use `py_pow` (py_math.h:30-40), never `std::sqrt`/`std::pow` with a literal |
| H2 | CB:791, OBJ:1089, SS:743, `GetConditionPercentage` SS:824-832 | Python `max`/`min` NaN semantics: use `py_max`/`py_min` (py_math.h:24-27) |
| H3 | CB:189-208 `_splash_weight`; CB:849 `d >= r_sub + r_hit` | operand order `(r_sub + r_hit - d) / r_hit`; the sum is computed twice (849 and inside `_splash_weight`) |
| H4 | SS:2395-2406 ApplyDamage | `0.6 * (1.0 - 2.0 * (frac - 0.1))`, `cur - (1.0 - b) * amt`, `b * amt - new`; `frac` is the tick-time `_ramp_fraction` or `cur / mx` |
| H5 | CB:144-171, 571-577 | `_body_frame_delta` dot products in `x, y, z` order against `GetCol(i)` (TransformStore rot is row-major: col i = `R[i], R[3+i], R[6+i]`, as BG:236-238 does); normalise by scaled box `(bx - cx*s) / (hx*s)`; tie order y → z → x with `>=`; `bx <= 0` → LEFT (4) |
| H6 | HL:958-983, HL:1240-1246 | `max_damage * (max_damage_distance / dist) * dt` then `* PHASER_INTENSITY_SCALE[level]` (left-associative, separate multiply) |
| H7 | CB:867, CB:792 | `absorbed_subsystem_total` sums `post_shield` per overlap, in iteration order; `absorbed_shields = before - remaining` |
| H8 | FMA | combat sources build with `-ffp-contract=off` plus the clang pragma (py_math.h:7-9); a new damage TU must join that list |
| H9 | RNG | one shared `random.Random` (App.py:993-1003) also drawn by AI, missions, `Effects`, death cascade. Draw sites in a hit: HHS:94, HHS:145, SDK `Effects.CreateSmokeHigh`, `GetRandomSound`, death_cascade.py:134. A native port that draws must either call back into the Python RNG in the same order or leave those draws in Python. **Superseded 2026-11-02 (presentation RNG):** the smoke rolls, `CreateSmokeHigh`, `GetRandomSound` and the cascade's cosmetic draws now come from the presentation generator; the cascade draws its damage roll first. |
| H10 | HF:187-200 | `time.monotonic()` audio gate decides whether `GetRandomSound` draws: RNG consumption already depends on wall time when `g_kSoundManager` exists (differentials must keep it out, or run with no sound manager; **inferred** that headless runs have none — not checked). **Superseded 2026-11-02:** the gap is on game time, and the sound pick draws the presentation generator. The "headless has no sound manager" guess was wrong (rng-map §0.1). |
| H11 | iteration order | subsystems: `GetSubsystems` slot order + `_children` list order (SH:1210-1223, CB:281-292) = `mount_order`; watcher checks: dict insertion order; event handlers: registration order with snapshot copies (EV:818, 830); `primary` ties: first strict max (CB:224) |
| H12 | `id()` keys | `_last_dispatch_time`, `_last_decal_emit`, `_last_smoke_roll`, `hull_wear._pending`, step-memo keys: never iterated in a hit (only `hull_wear.drain`, per tick, insertion order) |
| H13 | memo | Python's mount memo is cleared at hit entry/exit; inside one hit each subsystem's mount is computed once. The native memo (`SensorState::mounts`) is cleared by the same forget hook (NC:4433), so a native loop inside a hit must not reuse entries across a nested `apply_hit` (death splash) |
| H14 | object identity | `hit_point is shield_point` on K3 fallback-tier bubble hits; `WeaponHitEvent.SetHitPoint` stores by reference (EV:434). Any native path must hand Python the same aliasing |
| H15 | float(damage) | callers pass `torpedo._damage`, `float(fDamage)`, `amount * w`; CB:756 `float(damage)`; the 2× cheat multiplies first (CB:737) |

---

## 8. Existing native pieces

| Python | Native | File | Used by |
|---|---|---|---|
| `combat.shields_block` (generator, cloak, NPC-shields cheat) | `shields_block(m, target, npc_shields_off, player)` | BG:182-209 | K2, K3 |
| `combat.shield_bubble_entry`, `_hull_box_for`, `_body_frame_delta` | `shield_bubble_entry(m, target, origin, dir, max_dist)` | BG:214-268 | K2, K3 (gives `shield_point`, the facing input) |
| `ShipSubsystem.IsDisabled` / `IsDestroyed` (leaf) | `shield_is_disabled/destroyed` BG:32-43; `leaf_is_disabled/destroyed` FG:64-78 | BG, FG | K1, K2 |
| `WeaponSystem.IsDisabled` / `IsDestroyed` (aggregate) | `is_disabled`/`is_destroyed` | FG:84-103 | K1 |
| `ShipSubsystem.GetMaxCondition` | `GetMaxCondition(m, s)` | sensor_detect.cc:206-215 | sensors |
| `subsystems.subsystem_world_position` (posed parts, memo) | `subsystem_world_position(m, sub, ship_arg, use_memo)` | weapon_geometry.h:50-55 | K1, K2 |
| `_climb_to_ship` | `climb_to_ship_of` | weapon_geometry.h:47 | K1, K2 |
| `collisions.world_radius` | `world_radius` | BG:172-177 | K2, K3 |
| `_iter_subsystems` order | `ObjectRow::mount_order` (+ `part_pose.h authored_mount_subsystem`) | MIRH, part_pose.h:97-106 | K1, K2, K3 attribution |
| `_resolve_hit_point` + mesh trace | `beam_trace` (`TraceHooks`: host bindings install C++ hooks on `g_world`, no Python) | beam_trace.h | K2, K3 |
| `damage_eligibility` set | K4 kernel | k4_eligibility.cc | F7's gate |
| beam dwell / damage-pulse timing | K2 `_dwell` write log, `BEAM_DWELL_FLUSH_S` global | k2_beams.cc | K2 |
| `x ** y`, `min`, `max`, `math.dist` | `py_pow`, `py_min`, `py_max`, `dist3` | py_math.h | all |
| write log + quiet setters (WakeField/FrozenField bases still fire) | `apply_writes` / `_quiet_setter` | NC:2727-2810 | K1, K2, K3 |

The `TraceHooks` pattern (beam_trace.h: the combat library never links the renderer; the host bindings install std::function hooks that call the same C++ the Python binding calls) is the existing precedent for reaching renderer state (`shield_hit`, `world_to_body`, `hull_damage_add`, `damage_decal_add`, host_bindings.cc:8133, 8978, 8373, 8535) from the combat library (**inferred** applicable; not tried).

Not native anywhere: `_shield_face_from_hit_point`, `_splash_weight`, the ApplyDamage ramp, `DamageSystem`/`SetCondition` and their side effects, `classify`, `spark_params`, `_phaser_damage_for_tick`, `weapon_splash_radius`.

---

## 9. Candidate splits

Common facts for all: decision 8 (flags over handlers) needs `_invincible`, `_hurtable`, subsystem `_invincible` (and the cutscene flag of decision 7, not built) mirrored; any split that applies damage natively inside K2 needs the face charges mirrored with pushes at every in-place writer (§3.1); `SetCondition`'s side effects (§3.2) are SDK-visible and cannot be replaced by a quiet write.

### (A0) Decide natively, apply in Python (no new writes)

The kernel computes, from the mirror: `r_hit`, face, the overlap list `(sub, weight)` in `mount_order`, `primary` (by weight), `is_hull_hit` for unshielded cases. Python receives one record per hit and runs `ApplyDamage`, `DamageSystem` per listed subsystem, dispatch and the event, unchanged.
- **Python still runs per hit:** everything in §3, §4, §6. Saves only the splash loop (`_iter_subsystems`, per-subsystem `subsystem_world_position`, `** 0.5`; CB:839-871 minus the `DamageSystem` calls). 58% of hull hits overlap no subsystem (CB:829-833 comment, measured on a Galaxy), so the loop is mostly misses.
- **Blocks:** bank/torpedo DRF (R1), `sub._invincible` (R20) unmirrored; `primary_transition` needs before/after flags around each `DamageSystem`, so it stays Python. The shield face needs no new data (box + transform mirrored) but the absorbed amount needs face charges.
- **Evidence of value:** none measured; with 0.49 weapon hits per tick (§1) the saving is small (**inferred**).

### (A) Arithmetic native + logged writes; side effects stay Python records

As A0, plus the kernel computes shield absorption and the new conditions, writes the mirror, and logs the face write and each `_condition` value; Python applies the logged values **through `SetCondition`** (not a quiet setter) so D2b-D4 still fire, then dispatch and the event, at the record.
- **Python still runs per hit:** `SetCondition` side effects per damaged subsystem, `_route_zero_crossing`, death, dispatch, `ET_WEAPON_HIT`.
- **Blocks:** face charges/ramp mirrored and pushed at SS:2138, 2147, 2318, 2331, 2348, 2404, 2406 and on restore (bypass trap, §3.1); immunity flags and the two dev cheats pushed (god mode changes `_commit` and the face path CB:786-791); `PhaserSystem._power_level` and bank `_max_damage*` mirrored to move the K2 pulse's damage arithmetic (HL:1236-1247). Ruling P1 is met only if the record is applied before the walk continues (as today's CONTACT record). A fast path that skips Python when `SetCondition` would have no effect (no watcher ranges, no threshold change, already queued for repair, no zero crossing, not critical) would need "watcher has checks" and "in repair queue" mirrored (**inferred** feasible; no evidence on how often it holds).
- **Evidence:** `_condition` already pushes (SS:326) and `apply_writes` already applies logged values (NC:2764); the kernels already read `_condition` for fire gates (FG). Every `SetCondition` side effect is listed in §3.2.

### (B) A + batched presentation

As (A), plus F1/F2 (and the resting-contact P4a/P4b, §5) produced as a presentation list delivered with the record or DONE (the round-trips E5 pattern); Python applies the list (host calls, `hit_vfx.spawn`), then F3-F7 and the event.
- **Python still runs per hit:** F3 (RNG), F4 (wall clock + RNG), F5, F6 (persistent wear, `hull_breakup`), F7 (severance → synchronous `SetCondition(0)`), events. Per resting contact: only the list application.
- **Blocks:** bank `_max_damage`, `_max_damage_distance`, DRF and `_power_level` mirrored (P1-P2); `spark_params`, `classify`, `shield_impact_intensity`, `_mesh_xyz` ported; the view offset is already in the K2 context. "Bit-exact" for presentation = the same `shield_hit`/`hit_vfx` call list in the same order (round-trips spec §3), which the K2 differentials already compare per tick (round-trips spec §10, Task 5).
- **Evidence:** resting contacts are 17.6/tick and their presentation is most of the ~0.25 ms/tick left in `cb.phasers` (`remaining-fallbacks-map.md` §2.4, §3.3; round-trips §10). This is the only split with a measured cost behind it.

### (C) B + native feedback

As (B), but C++ calls the renderer through installed hooks (TraceHooks pattern, §8) for `shield_hit`, `world_to_body`, `damage_decal_add`, `hull_damage_add(_body)`, and keeps its own hit-VFX list.
- **Python still runs per hit:** F3 smoke (shared RNG + SDK `Effects`), F4 audio (shared RNG, wall-clock gate, SDK `LoadTacticalSounds`), F7 severance and `hull_breakup` (game state), death, all events.
- **Blocks:** `hit_vfx._active` is a Python list aged in `cb.vfx` and pushed in `cb.render_data` (hit_vfx.py:34-86) — needs a native owner; the decal/smoke throttles are Python dicts keyed by `id()`; `hull_wear._pending` holds a strong ship ref (HW:44-63); the renderer state is touched on the sim thread today (**inferred**; workstream K's threading rules apply).
- **Evidence:** none measured.

### (D) Full native with queued events (workstream G)

Damage and side effects native; events queued to the boundary.
- **Blocks:** synchronous dispatch is relied on inside the hit (§6.1-6.2); E8M2 `SetHurtable(0)` and E3M5's 15% clamp change later hits in the same tick (§6.3); `RunDeathScript` and death-splash recursion run inside `DamageSystem` (§3.2); the death cascade and smoke draw the shared RNG (H9); roadmap §5.2's event-order rule. Not a damage-only change.

---

## 10. Not established

- **`apply_hit`'s own cost per call** (shield, loop, `DamageSystem`, dispatch, event): no capture splits it. No `hit.*` profiler scope is committed; the R2 per-record CONTACT time (15.18 µs, `remaining-fallbacks-map.md` §2.4) mixes resting contacts and pulses.
- **Collision, AddDamage and death-splash `apply_hit` frequency** in the 64-ship fight: no counter exists.
- **How many subsystems a typical hit overlaps** in that fight (the 58%-no-overlap figure is from a Galaxy hardpoint sample, CB:829-833).
- **Whether headless runs have `App.g_kSoundManager`** (decides whether F4 draws the RNG in differentials).
- **How many `Effects.CreateSmokeHigh` RNG draws** one smoke puff makes (SDK, not traced).
- **Whether any stock handler on `ET_SUBSYSTEM_*` / `ET_ADD_TO_REPAIR_LIST` / watcher events changes damage state** (only `ET_WEAPON_HIT` handlers were scanned, §6.3).
- **ConditionAttacked/AttackedBy instance counts** in the benchmark scene (each runs on every hit).
- **Pickled-state restore writers** of the shield face lists (§3.1, inferred).
- BC's own order of hull damage vs death vs `ET_WEAPON_HIT` (the clean-room reference server was not reachable this session).
