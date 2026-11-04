# Combat-path events and effects: inventory for the boundary queue (workstream G)

> Snapshot written 2026-11-02 on branch `ws/combat-effect-queue` (base `e4d675a2b`, which includes Task 2 of the effect-queue plan: resting K2 beam contacts are queued natively and presented in one Python batch after the step's DONE). Line numbers are of that tree; re-check one before relying on it. Input to `docs/superpowers/specs/2026-11-02-combat-effect-queue-design.md` §4.1 and to the ordering work of its later steps. Builds on, and does not repeat, `damage-map.md` §6-7 (the `apply_hit` chain, RNG hazards H9-H10) and `remaining-fallbacks-map.md` §4 (per-record deferability). Everything not read directly off the code is marked **inferred**.

**SDK citations** are relative to the SDK scripts root (`paths.sdk_scripts()`), for example `Maelstrom/Episode1/E1M2/E1M2.py:1139`.

**Abbreviations.** HL `engine/host_loop.py` · LP `engine/core/loop.py` · EV `engine/appc/events.py` · CB `engine/appc/combat.py` · HF `engine/appc/hit_feedback.py` · OBJ `engine/appc/objects.py` · SS `engine/appc/subsystems.py` · WS `engine/appc/weapon_subsystems.py` · PR `engine/appc/projectiles.py` · NC `engine/appc/native_combat.py` · SD `engine/appc/ship_death.py` · DC `engine/appc/death_cascade.py` · RD `engine/rocks/death.py` · COL `engine/appc/collisions.py` · RAD `engine/appc/radiation.py` · NR `engine/appc/nebula_runtime.py` · FRW `engine/appc/float_range_watcher.py` · SETS `engine/appc/sets.py` · PS `engine/appc/part_severance.py` · HHS `engine/appc/hull_hit_smoke.py` · OL `engine/appc/object_lifetime.py` · SH `engine/appc/ships.py` · SPL `engine/appc/splash_damage.py`.

---

## 0. How dispatch and the frame work today

### 0.1 Dispatch (EV)

| Fact | Where |
|---|---|
| `AddEvent` is synchronous. Order inside one post: the destination's instance chain first (**unguarded**: a raise propagates into the combat step), then broadcast function handlers (snapshot, exceptions logged), then broadcast method handlers (snapshot, exceptions logged). | EV:802-845 (destination EV:810-812; function handlers EV:818-828; method handlers EV:830-845) |
| The instance chain is LIFO. A handler that returns without `CallNextHandler` stops it. An unresolvable handler name is skipped. | EV:609-658 (`ProcessEvent`, `_invoke_next_handler`, `CallNextHandler`) |
| `dispatch_passes` posts an event and reports whether the destination chain ran to the end. | EV:860-877 |
| **Only two events have an engine default effect that a chain can cancel**, plus the alert level, which is not combat. The effect runs after `AddEvent` returns, only if the chain passed. | `ET_ENVIRONMENT_DAMAGE`: RAD:36-41, RAD:127-128 (profile drain); NR:23-29, NR:217-219 (nebula stream, drain applied by the listener RAD:134-143). `ET_SET_ALERT_LEVEL`: SH:1005-1022. |
| Every other combat event is posted **after** (collisions: **before**) an effect the engine has already decided. No handler can cancel weapon damage, a death, a launch or a reload. | the emitters in §1 |
| `ET_OBJECT_CONVERTED_TO_HULK` and `ET_SHIELDS_SET_STATE` (roadmap §5.1) are **never posted**. The only engine hits are the constant table. | `engine/appc/constants_generated.py:499, 581` |
| Dispatch is synchronous, so a handler's effects are visible to everything that runs after the post, in the same call stack. Nested posts from handlers run inside the outer dispatch. | EV:802-845 |

### 0.2 Where each source runs in a frame (live host)

| Order | Step | Runs | Event sources |
|---|---|---|---|
| 1 | `advance_ticks(... _tick_gameloop ...)` HL:12357-12358 → `GameLoop.tick` LP:29-118, **N times** | per sim tick | AI, timers; `rock_death.advance` LP:105-107 (rock DESTROYED/EXITED/DELETE); `_update_ship_subsystems` LP:109-110, 127-157 (shield `Update`, power `Update`, repair `Update` → shield-watcher, battery-watcher and repair events) |
| 2 | `for _tick_i in range(_sim_ticks_this_frame)`: `_advance_weapons` HL:12624-12625 (def HL:928), then `_advance_combat` HL:12626-12635 | per sim tick, **after all N GameLoop ticks** | K0 / weapons walk; the whole combat step (def HL:1288) |
| 3 | `sensor_contacts.tick`, crew prompts | per frame | out of scope |
| 4 | `for _tick_i ...`: `NebulaTracker.update`, `RadiationDriver.update` HL:12681-12688 | per sim tick, after all combat ticks | `ET_ENVIRONMENT_DAMAGE`, `ET_ENTERED/EXITED_NEBULA`, their drains and deaths |
| 5 | `debris_chunk.tick`, `hull_breakup.drain`, `hull_wear.drain` HL:12814-12823 | per frame | `hull_breakup` destroys subsystems inside broken structure (`SetCondition(0.0)`, `engine/appc/hull_breakup.py:232` → E10) |
| 6 | `collisions.tick_collisions(_player_dt, ...)` HL:12825-12828 | **once per render frame, wall-clock dt** | `ET_PLANET/CLOAKED/OBJECT_COLLISION`, impact and grind damage |

Inside step 2, the combat step order is: `cb.eligibility` (`step_scan` + `damage_eligibility`) HL:1323-1329 → `cb.projectiles` **K3** `projectiles.update_all` HL:1330-1333 (torpedo expiry E19 inside it) → torpedo hits `apply_hit` HL:1340-1350 (after K3 returns) → `cb.vfx` HL:1351-1355 → `cb.death` HL:1360-1369 (`ship_death.advance`, explosion lights, `object_lifetime.advance`) → `cb.damage_sys` HL:1371-1384 (`subsystem_cascade`, `warp_core_breach`, `visible_damage`, `internal_blast`, `camera_shake`) → `cb.held_weapons` **K1** `_pump_held_weapons` HL:1387-1388 (def HL:994) → `cb.phasers` **K2** (`k2_phasers`, else `_phaser_step_ship`) HL:1395-1399 → `cb.tractors` HL:1407-1409.

Headless: `tests/helpers/headless_mission.py:70-80` (`_sim_tick`) runs only `loop.tick()` and `dash.tick`. No weapons walk, combat step, radiation or collisions; tests that need them call `collisions.tick_collisions` etc. directly.

**Consequence for the queue:** "the tick boundary" is not one point. In a 3-tick frame all three GameLoop ticks (AI included) run before any combat step; radiation for all three ticks runs after all three combat steps; collisions run once, after everything, on wall-clock dt.

---

## 1. Events posted from the combat path

Frequency classes: **tick** (can fire every tick per object), **hit**, **shot**, **edge** (state transition), **death**, **rare**. "Before/after" = relative to the state change the event reports.

| # | Event | Emitter (file:line) | Source → Destination | Trigger / where | Before or after its state change | Freq |
|---|---|---|---|---|---|---|
| E1 | `ET_TORPEDO_RELOAD` | WS:3697-3720 (post WS:3718), from `UpdateReload` (WS:3592) or K0 `RELOADED` record (NC:3675-3676) | none → tube | weapons walk / K0 | after (`_num_ready += 1` first) | edge, per reload |
| E2 | watcher event (SDK-chosen type, e.g. `ConditionPulseReady`'s) | FRW:97-114, `_fire` FRW:128-133; pulse charge WS:2983, K0 `WATCH` record NC:3677-3678 | as the SDK condition built it | weapons walk / K0 | after the charge change, **before** the watcher's own `_value` is committed (FRW:113-114) | edge |
| E3 | `ET_TORPEDO_ENTERED_SET` | PR:528-571 (`register` → `_join_source_set` → `_post_set_transition` PR:574-592), called at WS:652 inside `_spawn_projectile` (WS:575) | torpedo → torpedo | launch (torpedo and pulse bolt). **Only when the source ship is in a set** (PR:557-566): a shooter in no set posts nothing | after set add | shot |
| E4 | `ET_TORPEDO_FIRED` (launch) | WS:3722-3756, from `_spawn_torpedo` WS:3538 (call WS:3587) | torpedo → tube | K1 FIRE tube (NC:3310-3313) / Python `Fire` | after the torpedo exists and `_num_ready -= 1` | shot (tubes only) |
| E5 | `ET_WEAPON_FIRED` | `_post_weapon_fired` WS:699-715; tube WS:3471 / WS:3478-3484; phaser bank WS:2677-2686. **Pulse weapon and tractor do not post it**: `_post_weapon_fired` has only two callers, WS:2685 and WS:3484 (docstring WS:2678-2682) | weapon → ship (no ObjPtr, §7 F5) | K1 FIRE / Python `Fire` | after (tube: after E4; bank: on the was-not-firing edge only) | shot / edge |
| E6 | `ET_TORPEDO_AMMO_CONSUMED` | WS:3517-3536, call WS:3472 | tube → ship (player only) | K1 FIRE tube | after E5 | shot (player) |
| E7 | `ET_WEAPON_FIRE_FAILED` (= `ET_CANT_FIRE`, 0x800037) | WS:3486-3515, from `_fire_decide` WS:3429-3443 or K1 `FIRE_FAILED` record (NC:3316-3317) | none → tube | targeted tube fire fails aim or cone | n/a (no state change) | shot attempt |
| E8 | `ET_TRACTOR_BEAM_STARTED_FIRING` / `_STOPPED_FIRING` | WS:2505-2537 (`_sync_firing_event`); callers WS:2497, 2569-2599, 2641 | tractor system → ship | the pump hands a self-managed tractor system to Python (`_pump_self_managed` WS:2407, HL:1034; K1 `RUN_PYTHON` NC:3320-3324), `StopFiring` | after `IsFiring` flips | edge |
| E9 | `ET_WEAPON_HIT` (`WeaponHitEvent`) | CB:902-913 | firer (None for `AddDamage`) → hit ship | every `apply_hit`: K3 torpedo hits HL:1340-1350; K2 damage pulse via `_phaser_contact` HL:1249-1263 (inline CONTACT record, NC:4375-4376); collisions COL:893-907 (impact) and COL:605-615 (grind); death splash SPL:77-82; death-cascade `AddDamage` OBJ:1020-1042 | **after** shields, hull, subsystems, any death this hit began (E13), and `hit_feedback.dispatch` (CB:878-896) | hit (phaser: one per `BEAM_DWELL_FLUSH_S` = 0.5 s per bank, WS:303; grind: every frame whose grind damage rate is at least `kGrindMinDamageRate`, COL:39, COL:597-615) |
| E10 | `ET_SUBSYSTEM_DESTROYED` / `_DISABLED` / `_OPERATIONAL` | SS:786-815 (`_condition_changed`) → `_fire_threshold_event` SS:1123-1138 | subsystem → owning ship | any condition write: `DamageSystem` OBJ:1090, `DestroySystem` OBJ:1110, `part_severance` PS:546-548, `hull_breakup` (`engine/appc/hull_breakup.py:232`), `subsystem_cascade` (`engine/appc/subsystem_cascade.py:80-81`) | after the condition write | edge |
| E11 | `ET_ADD_TO_REPAIR_LIST` | SS:2881-2898 (post SS:2898), from `SetCondition` SS:733-746 (`_auto_enqueue_for_repair`) | subsystem → repair subsystem | first damage to a subsystem | after enqueue | edge |
| E12 | condition-watcher events (SDK-chosen types) | SS:793-796 → FRW:97-114 | as registered | same writes as E10, run **first** in `_condition_changed` | after the condition write, before the watcher commit | edge |
| E13 | `ET_OBJECT_EXPLODING` | SD:282-306; from `ship_death.begin` SD:103, rock `begin` RD:68 | ship → ship (+ `FiringPlayerID` = killer's ObjID) | first critical subsystem to 0 in `DamageSystem` OBJ:1092-1100 / `DestroySystem` OBJ:1114-1122 | after `SetDying`, after `death_cascade.begin` has drawn the throes length and blast plan (SD:93-94, RNG S1, §4.1), after the death script (SD:97-101 / RD:63-66); **before** the death splash (SD:108-112), before the rest of the killing hit's subsystems, its feedback and its E9 | death |
| E14 | `ET_ENTERED_SET` (ships only) + `ET_OBJECT_GROUP_OBJECT_ENTERED_SET` (groups that asked) | SETS:200-228, `_broadcast_set_transition` SETS:328-355; OBJ:1251-1297 | → piece | rock breakup adds major pieces, RD:271, **inside** the killing `apply_hit` (after E13: RD:57-100) | after set add | death (rocks) |
| E15 | `ET_OBJECT_DESTROYED` | SD:309-321; from `_mark_dead` SD:184-216 (throes end, SD:155-157) and `retire` SD:256-265 (`object_lifetime._expire` OL:54-63 **runs the death splash first**, OL:61; rock `advance` RD:369 in LP) | ship → ship | throes timer / lifetime | after `SetDead` | death |
| E16 | `ET_TARGET_WAS_CHANGED` | SH:1731-1756, via `_clear_target_locks` SD:115-131 (`SetTarget(None)` SD:127) | ship → ship (each ship that had the dead one targeted) | throes end SD:163; removal SD:234 | after `_target` written | death × lockers |
| E17 | `ET_EXITED_SET` (ships only, carries the set name as a string) + `ET_OBJECT_GROUP_OBJECT_EXITED_SET` | SETS:277-293 (post SETS:283, `_broadcast_set_transition` SETS:328-355); OBJ:1251-1297 | → ship | `_remove` SD:219-246 (hulk eviction SD:170-181, `retire`) | posted **during** removal: the object is still in `_objects` and still reports this set (`_clear_containing_set` SETS:291 and the pop SETS:293 come after) | death |
| E18 | `ET_DELETE_OBJECT_PUBLIC` | OBJ:1423-1448, from SD:245-246 | → ship | end of `_remove` | after set removal | death |
| E19 | `ET_TORPEDO_EXITED_SET` | PR:595-607 | torpedo → torpedo | `expire`: TTL or hit, inside `update_all` PR:1037-1038 or after K3's DONE writes (`expire(t)` NC:4977-4979) | after removal from the set | shot |
| E20 | `ET_PLANET_COLLISION` | COL:955-984, posted COL:853 | planet → other body | `_respond_pair` impact path (`v_rel < 0`) only; a resting or receding contact goes to `_grind_contact` and posts nothing (COL:793-809) | **before** impact damage (COL:881-907) | hit |
| E21 | `ET_CLOAKED_COLLISION` | COL:987-1034, posted COL:868 | cloaked → other | impact path; skipped for `DebrisChunk` (COL:863-864) | before damage | hit |
| E22 | `ET_OBJECT_COLLISION` (×2, source and destination swapped) | COL:910-952, posted COL:869 | each body → the other | impact path; skipped for `DebrisChunk` | before damage | hit |
| E23 | `ET_ENVIRONMENT_DAMAGE` (profile) | RAD:36-41 via `dispatch_passes` | none → ship | 16 Hz while irradiated, RAD:107-132 | **before** the drain; drain only if the chain passed | tick (16 Hz) |
| E24 | `ET_ENVIRONMENT_DAMAGE` (nebula) + `ET_ENTERED/EXITED_NEBULA` | NR:23-29, NR:211, 217, 227 | nebula → ship | `NebulaTracker.update` | env: before the profile drain (listener RAD:134-143) | tick / edge |

Adjacent, posted outside the combat step by the same mechanics: `ET_CANT_FIRE` from `TorpedoSystem.StartFiring` (WS:1880-1928: AI and input, not the pump); `ET_TORPEDO_FIRED` unload (WS:3780-3792, from `SetAmmoType`); `ET_PLAYER_TORPEDO_TYPE_CHANGED` (WS:2150-2175, from `SetAmmoType`); shield-watcher events (`ApplyDamage` SS:2359-2400 writes `_current_shields` and updates no watcher; they fire from `ShieldSubsystem.Update`, SS:2273 and SS:2333-2356, and `SetCurrentShields` SS:2145-2155, i.e. in LP and in radiation); battery-watcher events (SS:2704-2707, in LP); repair `ET_REPAIR_COMPLETED` / `_CANNOT_BE_COMPLETED` (SS:2933-2965, in LP).

---

## 2. Stock SDK consumers and classification

Classes: **REPORT** (handlers observe, show UI or score; a one-tick-later delivery changes nothing the engine applies), **GATE** (the engine's effect depends on whether the chain passes), **ORDER** (outcome depends on order relative to another event or state change, or a handler mutates state the rest of the tick reads), **NONE** (no stock consumer can receive it).

### 2.1 Counts

| Class | Events |
|---|---|
| GATE (1) | `ET_ENVIRONMENT_DAMAGE` |
| ORDER (6) | `ET_PLANET_COLLISION`, `ET_OBJECT_COLLISION` (also gate-shaped, see 2.2), `ET_OBJECT_EXPLODING`, `ET_WEAPON_HIT`, `ET_TRACTOR_BEAM_STARTED_FIRING`, `ET_TORPEDO_FIRED` |
| REPORT (17) | `ET_CLOAKED_COLLISION`, `ET_OBJECT_DESTROYED`, `ET_DELETE_OBJECT_PUBLIC`, `ET_SUBSYSTEM_DESTROYED/DISABLED/OPERATIONAL` (3), `ET_TORPEDO_RELOAD`, `ET_TORPEDO_ENTERED_SET`, `ET_TORPEDO_EXITED_SET`, `ET_WEAPON_FIRED`, `ET_TRACTOR_BEAM_STOPPED_FIRING`, `ET_TARGET_WAS_CHANGED`, `ET_ENTERED_SET`, `ET_EXITED_SET`, `ET_OBJECT_GROUP_OBJECT_ENTERED/EXITED_SET` (counted as 1), `ET_ENTERED/EXITED_NEBULA` (counted as 1; E3M2 `InNebula`/`OutNebula` set the mission's own flag and toggle the hail menu and warp button, `Maelstrom/Episode3/E3M2/E3M2.py:1147-1160`, `:1275-1289`; `Conditions/ConditionInNebula.py:70-71` feeds AI conditions), watcher events |
| NONE (3) | `ET_WEAPON_FIRE_FAILED` (no reachable consumer), `ET_TORPEDO_AMMO_CONSUMED` (0 SDK refs), `ET_ADD_TO_REPAIR_LIST` (0 SDK refs) |

### 2.2 Per event

**`ET_ENVIRONMENT_DAMAGE` — GATE (engine default implemented).**
- Missions: `Maelstrom/Episode3/E3M2/E3M2.py:686` `CoreDamage` (player instance; body Maelstrom/Episode3/E3M2/E3M2.py:1370-1386): with the mission terminated it passes; while `g_iAsteroidsScanned == g_iNumToScan and g_iMissionProgress == FIND_CORE` it returns **without** `CallNextHandler` (cancels the drain); otherwise it reads `pShields.IsOn()` and `GetSingleShieldPercentage(NUM_SHIELDS) < 0.05` to play `ShieldProd`, then passes. Maelstrom/Episode3/E3M2/E3M2.py:833 probe → `MissionLib.IgnoreEvent` (MissionLib.py:311, a bare `pass`: permanent cancel).
- Systems: `Systems/Vesuvi/Vesuvi4_S.py:42, 58, 74, 90, 106, 122, 138, 154, 170, 186, 202, 218` → `MissionLib.IgnoreEvent` on objects.

**`ET_PLANET_COLLISION` — ORDER.** One consumer: `Maelstrom/Episode1/E1M2/E1M2.py:1135` → `PlanetCollision` (Maelstrom/Episode1/E1M2/E1M2.py:1308-1336). Reads `Planet_Cast(GetSource()).GetName() == "Haven"` and `ShipClass_Cast(GetDestination()).GetName()` **membership in `g_dAsteroidInfo`** (no `IsDead`/`IsDying` check); deletes the key and calls `AsteroidHitPlanet` (Maelstrom/Episode1/E1M2/E1M2.py:3141-3154: 1st hit → `CheckAllDone` + `AsteroidsStartHitting`, 2nd hit → `MissionLost`). `"Facility"` → `MissionLost`.

**`ET_OBJECT_COLLISION` — ORDER, gate-shaped in E3M1.**
- MissionLib: `MissionLib.py:3582` `FriendlyFireCollisionHandler` (MissionLib.py:3904-3935): player is destination and the source is in the friendly group → a game-time timer posts `ET_FRIENDLY_FIRE_GAME_OVER` 1.5 s later.
- E1M2: `Maelstrom/Episode1/E1M2/E1M2.py:1137` `ObjectCollision` (Maelstrom/Episode1/E1M2/E1M2.py:1351-1373): hitter name in `g_dAsteroidInfo` and hit is `"Facility"` → `AsteroidHitStation`. Does **not** remove the key.
- `Maelstrom/Episode2/E2M1/E2M1.py:570` `KaroonCollision` (Maelstrom/Episode2/E2M1/E2M1.py:647-656): name prefix `"Asteroid"`, one-shot beat (body not re-read for this inventory).
- `Maelstrom/Episode3/E3M1/E3M1.py:1974` / 2943 `PlayerCollisionHandler` (Maelstrom/Episode3/E3M1/E3M1.py:843-853): `pPlayer.SetInvincible(FALSE)`, `RestoreVisibleDamage`, `DamageRefresh`, `CallNextHandler`, then `SetInvincible(TRUE)` unless `IsDying()`. **Inferred:** in BC the collision damage is the chain's default effect, applied inside `CallNextHandler` while the player is briefly hurtable. Ours applies the damage after the event returns (COL:869 then 881-907), when the flag is back on, so `apply_hit`'s immunity gate (CB:738-753, `ShipClass.IsImmuneToDamage` SH:1828-1831) skips it (§7 F1).
- `Maelstrom/Episode7/E7M1/E7M1.py:1700` `StarbaseCollision` (Maelstrom/Episode7/E7M1/E7M1.py:1854-1866): freighter vs Starbase sets `bStarbaseCollision` and kills the freighter with `MissionLib.SetConditionPercentage(hull, 0)`. That call is **unimplemented** on every subsystem class, so the kill is a silent no-op today (§7 F2).
- `Maelstrom/Episode7/E7M2/E7M2.py:1199` `ShipsCollided` (Maelstrom/Episode7/E7M2/E7M2.py:1934-1945): Vorcha vs `"Chairo"` sets `iLossState` and calls `DestroyShip` on both (Maelstrom/Episode7/E7M2/E7M2.py:1954-1961: `MissionLib.SetConditionPercentage(hull, 0)`). In BC that kills both **inside the collision dispatch, before the impact damage**. Ours is inert for the same stub reason (§7 F2); the rule would bind once the stub is real.

**`ET_CLOAKED_COLLISION` — REPORT.** `Bridge/HelmMenuHandlers.py:282` `CloakedCollision` (Bridge/HelmMenuHandlers.py:2660-2675): helm line, 5 s throttle on game time. Note COL:991-1019: the cloak test uses `getattr(instance, ...)` on the instance, so a **planet** party passes it (`_Stub` truthiness) and the line fires on every planet impact (§7 F6).

**`ET_OBJECT_EXPLODING` — ORDER.**
- MissionLib: `MissionLib.py:3590, 3658` `ObjectStartedExploding` (MissionLib.py:4029-4053): `GetFiringPlayerID() == player` and dying object in the friendly group → posts `ET_FRIENDLY_FIRE_GAME_OVER` **synchronously, nested**.
- Missions by episode: Maelstrom/Episode1/E1M1/E1M1.py:847 `ObjectDying` (reads `GetContainingSet().GetName()`); **Maelstrom/Episode1/E1M2/E1M2.py:1133 `ObjectDestroyed`** (Maelstrom/Episode1/E1M2/E1M2.py:1256-1296: name in `g_lDebrisNames` → remove; name in `g_dAsteroidInfo` → delete + `AsteroidDestroyed`; Facility + flags → `MissionWin`); Maelstrom/Episode2/E2M0/E2M0.py:791; Maelstrom/Episode2/E2M2/E2M2.py:561; Maelstrom/Episode3/E3M1/E3M1.py:554; Maelstrom/Episode3/E3M2/E3M2.py:674 `ShipExploding`, Maelstrom/Episode3/E3M2/E3M2.py:682 player instance (registered as `__name__ + "PlayerDestroyed"`, **no dot**: unresolvable, skipped by EV:641-647); Maelstrom/Episode3/E3M4/E3M4.py:1491; Maelstrom/Episode5/E5M2/E5M2.py:366; Maelstrom/Episode5/E5M4/E5M4.py:459; Maelstrom/Episode6/E6M2/E6M2.py:769; Maelstrom/Episode6/E6M3/E6M3.py:686; Maelstrom/Episode6/E6M5/E6M5.py:641 (reads containing set); Maelstrom/Episode7/E7M1/E7M1.py:336; Maelstrom/Episode7/E7M3/E7M3.py:531; Maelstrom/Episode8/E8M1/E8M1.py:411; Maelstrom/Episode8/E8M2/E8M2.py:526; `Custom/Tutorial/Episode/M3Gameflow/M3Gameflow.py:168`.
- QuickBattle: `QuickBattle/QuickBattle.py:1052` `ShipExploding` (QuickBattle/QuickBattle.py:3249-3264).
- Multiplayer: Mission1/2/3/5 (`Multiplayer/Episode/Mission1/Mission1.py:195` etc.; Multiplayer/Episode/Mission5/Mission5.py:210 starbase).

**`ET_WEAPON_HIT` — ORDER (two handlers), otherwise REPORT.**
- AI Conditions: `Conditions/ConditionAttacked.py:54`, `Conditions/ConditionAttackedBy.py:68` (broadcast method, no target filter; read destination name, `IsHullHit`, `GetFiringObject`, shield max via `AddShieldDamage`).
- Bridge: `Bridge/XOCharacterHandlers.py:61` `PlayerHit` (reads alert level; crew line).
- MissionLib: `MissionLib.py:3581, 3613` `FriendlyFireHandler` (MissionLib.py:3688-3746: accumulates `GetDamage()` into `UtopiaModule` friendly fire; may post `ET_FRIENDLY_FIRE_GAME_OVER` **nested**); `MissionLib.py:3439, 3442` `SetupWeaponHitHandlers` (instance handlers named by the mission).
- Missions: Maelstrom/Episode2/E2M0/E2M0.py:819; Maelstrom/Episode2/E2M2/E2M2.py:577 (reads player `GetShieldPercentage`); Maelstrom/Episode2/E2M6/E2M6.py:626; Maelstrom/Episode3/E3M1/E3M1.py:565 `AmagonHit` (counts `PHASER` hits), 2201 `UpdateShieldsGoal`, 2865, 3505, 3593; Maelstrom/Episode3/E3M4/E3M4.py:595-596; Maelstrom/Episode3/E3M5/E3M5.py:516, 726 `MatanWeaponHitHandler`, 762-763; Maelstrom/Episode4/E4M6/E4M6.py:1175, 1179, 2378, 2411, 2447, 2490, 2529; Maelstrom/Episode6/E6M1/E6M1.py:2518-2520; Maelstrom/Episode7/E7M2/E7M2.py:1373, 1431; Maelstrom/Episode8/E8M1/E8M1.py:968-969, 1600; Maelstrom/Episode8/E8M2/E8M2.py:366, 1581-1583 `KessoksAttacked` (draws `GetRandomNumber(2)`), 4707 `WeaponHitMatan`.
- Multiplayer: Mission1/2/3/5 `DamageEventHandler`.
- **ORDER cases:** E8M2 `WeaponHitMatan` (Maelstrom/Episode8/E8M2/E8M2.py:4856-4902) on the first TORPEDO hit calls `pCloak.SetConditionPercentage(0)` (a stub) and `SetHurtable(0)`: today every later hit on Matan **in the same tick** is already immune (`IsImmuneToDamage`, CB:738-753). E3M5 `MatanWeaponHitHandler` (Maelstrom/Episode3/E3M5/E3M5.py:967-988) reads the **post-damage** hull/power percentage and clamps to 15% (`SetConditionPercentage`: a stub today; Matan is also `SetInvincible(TRUE)`, Maelstrom/Episode3/E3M5/E3M5.py:723).

**`ET_OBJECT_DESTROYED` — REPORT.** AI: `AI/Preprocessors.py:1350` `TargetGone` (AI/Preprocessors.py:1293-1294: `ForceUpdate`); Conditions: `Conditions/ConditionDestroyed.py:53, 65`. Missions: Maelstrom/Episode2/E2M1/E2M1.py:702, Maelstrom/Episode2/E2M6/E2M6.py:612, Maelstrom/Episode3/E3M2/E3M2.py:677, Maelstrom/Episode3/E3M4/E3M4.py:531, 1883, Maelstrom/Episode3/E3M5/E3M5.py:514-515, Maelstrom/Episode4/E4M4/E4M4.py:416, Maelstrom/Episode4/E4M5/E4M5.py:408, Maelstrom/Episode4/E4M6/E4M6.py:566, Maelstrom/Episode5/E5M4/E5M4.py:458, Maelstrom/Episode6/E6M1/E6M1.py:740, Maelstrom/Episode6/E6M4/E6M4.py:560, Maelstrom/Episode6/E6M5/E6M5.py:639, Maelstrom/Episode7/E7M1/E7M1.py:334, Maelstrom/Episode7/E7M2/E7M2.py:307, Maelstrom/Episode7/E7M3/E7M3.py:529, Maelstrom/Episode7/E7M6/E7M6.py:467, Maelstrom/Episode8/E8M1/E8M1.py:409, Maelstrom/Episode8/E8M2/E8M2.py:524, `Maelstrom/Maelstrom.py:70`, `Custom/Tutorial/Tutorial.py:44`. `QuickBattle/QuickBattle.py:1051` `ShipDestroyed` (QuickBattle/QuickBattle.py:3291-3339: `del g_kShips[...]`, end-simulation timer, `GetPlayer().SetTarget(None)` → nested E16). Multiplayer Multiplayer/Episode/Mission5/Mission5.py:212.

**`ET_DELETE_OBJECT_PUBLIC` — REPORT** (needs the handle valid). `AI/PlainAI/Warp.py:439` `TowingShipDeleted`; `Bridge/PowerDisplay.py:325`; `Conditions/ConditionExists.py:39, 89`, `Conditions/ConditionInNebula.py:72`, `Conditions/ConditionInRange.py:219`; `MissionLib.py:2488` (mission object); Multiplayer menus.

**`ET_SUBSYSTEM_DESTROYED/DISABLED/OPERATIONAL` — REPORT.** Bridge: `Bridge/EngineerCharacterHandlers.py:82-83`, `Bridge/ScienceCharacterHandlers.py:79-80`. Conditions: `Conditions/ConditionSystemDestroyed.py:97` (SystemDestroyed :112-120 reads `pRoot.IsDisabled()`), `Conditions/ConditionSystemDisabled.py:97-98`, `Conditions/ConditionPulseReady.py:100-101, 153-154`, `Conditions/ConditionTorpsReady.py:80-81`. Missions: Maelstrom/Episode2/E2M0/E2M0.py:2085, 2090; Maelstrom/Episode5/E5M2/E5M2.py:371; Maelstrom/Episode8/E8M2/E8M2.py:2441.

**`ET_TORPEDO_FIRED` — ORDER.** `Conditions/ConditionTorpsReady.py:141` `TorpFired` (:178-184, re-counts ready tubes). `Maelstrom/Episode7/Episode7.py:37` `TorpedoFired` (Maelstrom/Episode7/Episode7.py:88-152): the player's phased-plasma launch draws **`GetRandomNumber(10)`** (shared RNG) and on 1 calls `MissionLib.SetConditionPercentage(pLauncher, 0)` (stub today) plus a sound and a dialogue sequence. When the stub is implemented this becomes a tube destroyed **inside the K1 walk**, between E4 and E5.

**`ET_WEAPON_FIRED` — REPORT (today).** Missions: Maelstrom/Episode1/E1M2/E1M2.py:1139, Maelstrom/Episode2/E2M1/E2M1.py:704, Maelstrom/Episode2/E2M2/E2M2.py:563, Maelstrom/Episode6/E6M4/E6M4.py:564 (`WeaponFired`: read `pEvent.GetObjPtr()`; our event is a plain `TGEvent` with no `GetObjPtr` (EV:117-197), the `_Stub` it vends fails `ShipClass_Cast`, so all four return early — **inert today**, §7 F5; E2M2's would otherwise `SetAI`); Maelstrom/Episode2/E2M0/E2M0.py:2087 `WarbirdWeaponFired` (AI switch); player instance: Maelstrom/Episode2/E2M6/E2M6.py:631, Maelstrom/Episode6/E6M2/E6M2.py:790, Maelstrom/Episode6/E6M4/E6M4.py:579, Maelstrom/Episode6/E6M5/E6M5.py:646 (E6M5 calls `pTractors.StopFiring()` only for a `TractorBeamProjector` source, which never posts this event, WS:2678-2682).

**`ET_TRACTOR_BEAM_STARTED_FIRING` — ORDER; `_STOPPED_FIRING` — REPORT.** `Bridge/PowerDisplay.py:337-338` (destination-filtered to the player), `Conditions/ConditionFiringTractorBeam.py:26-27`, Maelstrom/Episode7/E7M2/E7M2.py:341 `TractorHandler` (reads player target), **Maelstrom/Episode8/E8M2/E8M2.py:528 `TractorHandler`** (Maelstrom/Episode8/E8M2/E8M2.py:1010-1024): inside OD1 it calls `pPlayer.GetTractorBeamSystem().StopFiring()` — cancels the beam before `cb.tractors` (HL:1407-1409) moves anything this tick.

**`ET_TORPEDO_RELOAD` — REPORT.** `Conditions/ConditionTorpsReady.py:140` `TorpReloaded` (:164-171, reads `IsDisabled`).

**`ET_TORPEDO_ENTERED_SET` / `_EXITED_SET` — REPORT.** `Conditions/ConditionIncomingTorps.py:180, 182` (EnteredSet :228-242 reads the torpedo's target and position); Maelstrom/Episode8/E8M2/E8M2.py:4511, 4513 (`TorpedoEnterSet` Maelstrom/Episode8/E8M2/E8M2.py:1643-1658 sets the torpedo's lifetime: a write, but next tick's K3 reads it first, **inferred** no outcome change at tick-end delivery).

**`ET_TARGET_WAS_CHANGED` — REPORT.** `AI/Preprocessors.py:2349`; `Bridge/HelmMenuHandlers.py:280, 2012-2091`, `Bridge/ScienceCharacterHandlers.py:86`, `Bridge/ScienceMenuHandlers.py:133`, `Bridge/TacticalMenuHandlers.py:404`; `Camera.py:719`; Maelstrom/Episode1/E1M2/E1M2.py:1152.

**`ET_ENTERED_SET` / `ET_EXITED_SET` / `ET_OBJECT_GROUP_OBJECT_*` — REPORT.** Mission region state machines, Conditions (`Conditions/ConditionInRange.py:129-139`, `Conditions/ConditionExists.py:45`, `Conditions/ConditionAllInSameSet.py:51-53`, ...), `Camera.py:548`, `Bridge/HelmMenuHandlers.py:1824-1836`. ExitSet handlers read the event's string, not the containing set (SETS:328-337). SDK line counts for the two set events (48 / 28) and the group pair (18 + 6) are from the draft's grep and were not re-counted.

**Watcher events — REPORT.** `Conditions/ConditionSystemBelow.py`, `Conditions/ConditionSingleShieldBelow.py`, `Conditions/ConditionPowerBelow.py`, `Conditions/ConditionPulseReady.py`, Brex (`Bridge/Characters/Brex.py:107-108`) (FRW:1-26).

**NONE.** `ET_WEAPON_FIRE_FAILED`: its consumers (`Bridge/TacticalMenuHandlers.py:422`, `Bridge/TacticalCharacterHandlers.py:58` `PlayerCantFire`) are on the player instance; the post addresses the tube and sets no source (WS:3486-3515). `ET_TORPEDO_AMMO_CONSUMED`, `ET_ADD_TO_REPAIR_LIST`: no SDK reference outside `App.py`.

---

## 3. What consumers read, and whether it can move before end-of-tick delivery

"Changes before delivery?" assumes delivery after the combat step (or after the frame) instead of inline.

| Event | Consumer | Reads | Changes between emission and end-of-tick delivery? |
|---|---|---|---|
| ENVIRONMENT_DAMAGE | E3M2 `CoreDamage` | mission globals; player shields `IsOn`, combined shield % | **Yes**: the drain this very event gates lowers the shields (`apply_chunk` RAD:145-168, `SetCurrentShields` RAD:159). The decision must run before the effect, so the effect must move with the event (or become a flag) |
| PLANET_COLLISION | E1M2 `PlanetCollision` | names; **key in `g_dAsteroidInfo`** | The key is deleted by `ObjectDestroyed` if `ET_OBJECT_EXPLODING` is delivered first. Hull and `IsDead` are not read, so post-damage delivery is fine **if queue order is kept** |
| OBJECT_COLLISION | E1M2 `ObjectCollision` | names, key membership; `AsteroidHitStation` reads Facility position and writes its velocity | Position: moved by the collision's own de-penetration (already done at emission, COL:826-837) and by later ticks. One tick later, **inferred** negligible |
| OBJECT_COLLISION | E3M1 `PlayerCollisionHandler` | writes the invincible flag around the chain | It is the damage's **timing** that matters: see §2.2 |
| OBJECT_COLLISION | E7M2 `ShipsCollided` | names; kills both (inert today) | Today the kill precedes the impact damage in BC's order; queued, the impact lands first (the ram may itself have killed one: a second `DestroyShip` on a dying ship) |
| OBJECT_COLLISION | MissionLib FF | player identity, friendly group | no |
| OBJECT_EXPLODING | E1M2 `ObjectDestroyed` | name, list/dict membership | Membership changes only by the other E1M2 handlers → rule R1 |
| OBJECT_EXPLODING | E1M1 `ObjectDying`, E6M5 `ObjectExploding` | `GetContainingSet().GetName()` | Set removal happens at least the death window later (rock 0.5 s, RD:46-54; ship 5-15 s, DC:137-151) **unless** a lifetime of at most one tick is set; rule R4 |
| OBJECT_EXPLODING | MissionLib `ObjectStartedExploding` | `GetFiringPlayerID`, player id, friendly group | no |
| WEAPON_HIT | ConditionAttacked(By) | destination name, `IsHullHit`, firer, shield max | no (event payload) |
| WEAPON_HIT | MissionLib FF | `GetDamage`, weapon type, friendly group | no |
| WEAPON_HIT | E8M2 `WeaponHitMatan` | weapon type; writes `SetHurtable(0)` | **Yes**: hits later in the same tick on Matan read the immunity flag (CB:738-753) |
| WEAPON_HIT | E3M5 `MatanWeaponHitHandler` | hull/power % after the hit | Yes, more hits may land first (inert today: stub + invincible) |
| WEAPON_HIT | E2M2 `WeaponHitPlayer` | player `GetShieldPercentage` | yes (later hits, regen), dialogue choice only |
| TORPEDO_FIRED | `ConditionTorpsReady.TorpFired` | tube ready count | the weapons walk runs before combat (HL:12624-12626), so no reload lands in between; **inferred** no change |
| TORPEDO_FIRED | Episode7 `TorpedoFired` | ammo type/counts; RNG; writes tube condition | RNG position shifts if delivery moves past other draws (R8) |
| TRACTOR_STARTED | E8M2 `TractorHandler` | writes `StopFiring` | **Yes**: `cb.tractors` read the beam later the same tick. Since 2026-11-04 the force runs in the next motion stage, so the queued `STARTED` stops the beam before any pull |
| OBJECT_DESTROYED | `TargetGone`, `ConditionDestroyed`, QB `ShipDestroyed` | event identity; QB writes `g_kShips`, player target | no / QB nested E16 |
| DELETE_OBJECT_PUBLIC | ConditionExists, Warp | object identity | object must not be reused; **inferred** safe at tick end |
| SUBSYSTEM_* | Conditions, crew | `IsDisabled` of the root (`ConditionSystemDestroyed`) | could be repaired or destroyed further in the same tick, **inferred** rare |
| watcher events | AI conditions | the event's float (stamped at FRW:130); `GetWatchedVariable()` returns the **old** value during inline dispatch (FRW:113-114) | A handler delivered later that calls `GetWatchedVariable()` would see the new value: different. **Inferred** that stock conditions read it only at setup (FRW:9-16 shows that pattern) |

---

## 4. Presentation-only effects, and where they run relative to the kernels

### 4.1 The two shared random streams

- **S1 `App.g_kSystemWrapper.GetRandomNumber`**: one `random.Random` (`App.py:998-1003`, project root shim), also drawn by AI scripts, missions (`Maelstrom/Episode7/Episode7.py:88-152`, E8M2 `KessoksAttacked`), `Effects` (`Effects.CreateDebrisSparks` draws 2) and the death cascade's gameplay rolls (DC:131-176 and DC:227-257: throes length DC:137-151, blast spacing DC:166-176 (planned at `death_cascade.begin`, i.e. before E13), blast scale DC:`roll_blast_scale`, `rand(10) < 3` → `AddDamage` → `apply_hit`, DC:243-246).
- **S2 module-level `random`** (the process-global stream): drawn by `ObjectClass.GetRandomPointOnModel` (OBJ:362-405; also chooses among renderer surface points, OBJ:389), `particles` controller seeds (`engine/appc/particles.py:9, 65`), `debris_chunk` default (`engine/appc/debris_chunk.py:18, 131`), and by **AI** (`engine/appc/ai_driver.py:1008`, `random.choice(ai._untried)`).
- Private streams (safe): radiation `self._rng` (RAD:67), rock gravel `random.Random(crc)` (RD:167), avoidance (`engine/appc/collision_avoidance.py:114`), unit vectors (`engine/appc/math.py:450`).

### 4.2 Table (current tree, after Task 2)

| Presentation call | file:line | Reads | RNG | Runs where |
|---|---|---|---|---|
| Fire SFX start + loop (`_play_fire_sfx`) | WS:1004-1040, from `_fire_effect` WS:890-905 | weapon property, ship node, player identity | none | **inside K1 walk**: FIRE record (NC:3310-3313), ASK `fire` / `retry` answers (`_k1_answer`, NC:3186-3238), RUN_PYTHON (NC:3320-3324) |
| Loop sound stop (`StopFiring`) | WS:907-913 | handle | none | **inside K0** (DEPLETE_STOP, NC:3673-3674), **K1** (BANK_STOP / STOP_SYSTEM, NC:3314-3315), **K2** (BANK_STOP NC:4377-4380, SYSTEM_STOP NC:4381-4382) |
| Torpedo / pulse launch sound | WS:654-694 in `_spawn_projectile` WS:575 | projectile module `GetLaunchSound` | none (the SDK projectile scripts do not call `GetRandomNumber`: draft grep of `Tactical/Projectiles` found none, not re-run) | **inside K1** (FIRE tube/pulse NC:3310-3313, FIRE_DUMB NC:3318-3319) |
| `hit_feedback.beam_contact`, **resting contact** (shield splash or hull flash + sparks) | HF:564-612; `_hull_impact_visual` HF:502-561; reached through `_k2_run_contact` NC:4279-4303 → `_phaser_contact` HL:1219-1243 | the carried `shields_block` and power level, instance map, `host_io.world_to_body` | none (`hit_vfx.spawn` draws nothing) | **after the K2 step's DONE, in one batch**: the kernel queues each resting contact (power level, shields answer, instance id and view offset taken at contact time); `run_k2` calls `combat_k2_drain` NC:4390, which draws shielded contacts with a known instance and view offset natively, and `_k2_present_batch` NC:4251-4276 (called NC:4392) before `combat_k2_end`. An abandoned step drops the queue unpresented (NC:4395-4396). A raising presentation lets the rest present, then re-raises (NC:4271-4276) |
| `_phaser_contact` **damage pulse** (`apply_hit` and everything under it) | HL:1249-1263 | live game state | S1, S2 (below) | **inline in the K2 walk**: CONTACT record (NC:4375-4376 → `_k2_contact` NC:4246-4248 → `_k2_run_contact` with `level=None`) |
| `hit_feedback.dispatch`: shield flash, hull visual | HF:221-348 | absorbed amounts, instance map | none | inside `apply_hit` (CB:878-896): **inside K2** for a damage pulse; **after K3** for torpedo hits (HL:1340-1350); in collisions (frame end); nested in death splash / cascade |
| Hull smoke puff | HHS:57-127 (`Effects.CreateSmokeHigh`), called HF:346-348 | hit, throttle clock (game time, HHS:45-49) | **S1** draw ×2 (the roll HHS:93, then the life HHS:123, only when the roll passes); **S2** via the particle controller seed | same as `dispatch` |
| Hit audio (`_play_audio`) | HF:450-499, gated by `time.monotonic` (HF:187-200, call HF:355) | severity | **S1** via `LoadTacticalSounds.GetRandomSound` (`LoadTacticalSounds.py:150-172`): the draw happens or not depending on **wall time** | same as `dispatch` |
| Camera kick | HF:357-368 → `camera_shake.apply_kick` | player identity | none | same as `dispatch` |
| Scorch decal, plating wear | HF:370-425 (`host_io.damage_decal_add`, `hull_wear`) | game time, instance | none | same as `dispatch` |
| **Part severance (NOT presentation)** | HF:427-447 → PS:291 `record_hit` → `sever` PS:450-481 → `SetCondition(0)` PS:546-548 | renderer instance + `world_to_body` | none | same as `dispatch`. **Gameplay** (destroys subsystems, posts E10) living in the presentation module, and only when `ship_instances` carries an instance and `world_to_body` answers: headless never severs |
| Death script (SDK `SetDeathScript`) | SD:97-101, RD:63-66 | SDK; E1M2 `AsteroidExploding` (Maelstrom/Episode1/E1M2/E1M2.py:3084-3127) | **S1** (`CreateDebrisSparks`, `GetDeathExplosionSound` → `GetRandomSound`), **S2** (`GetRandomPointOnModel`) | inside the killing `apply_hit` → **inside K2** when a phaser pulse kills |
| Death cascade blasts | DC:227-257 (`_fire`), DC:259-295 (`_fire_final`) | ship radius, surface points | **S1** interleaved with gameplay rolls; **S2** for points; `_death_sound` DC:322-332 draws S1 | `cb.death` HL:1360-1369: after K3 hits, before K1 |
| Explosion lights, hit VFX ageing, shockwaves, particles | HL:1351-1355, 1365-1366 | timers | particles: S2 only at creation | between K3 hits and `cb.death` |
| Warp-core breach visuals | `engine/appc/warp_core_breach.py:60-100` (shockwave spawn, `host_io.hull_damage_add`, `hull_breakup.after_wear` → gameplay part check drained HL:12819-12820) | instance | none | `cb.damage_sys`, before K1 |
| `visible_damage`, `internal_blast` | HL:1377-1382 | instance, `host_io.ray_trace_mesh` | none | `cb.damage_sys` |
| Render feeds (torpedoes, beams, lights, ...) | HL:1417-1443 | everything | none | after the camera, outside the step |

**Inside the kernel walks today** (the list asked for):
> *Fire-events phase (2026-11-02, spec `2026-11-02-combat-fire-events-design.md`): weapon events and weapon sounds now go through one ordered effect queue delivered at the tick boundary (`engine/appc/effect_queue.py`). Mid-walk Python left, measured (64 ships, per tick): K0 none but whole-ship RUN_PYTHON; K1 only torpedo and pulse launches (0.10); K2 only damage pulses (0.47). The three bullets below are the pre-phase snapshot.*

- **K0** (`run_k0` NC:3652-3697; records NC:3673-3685): loop-sound `Stop` (DEPLETE_STOP); `ET_TORPEDO_RELOAD` (RELOADED); watcher events (WATCH); whole Python `UpdateCharge` / `UpdateReload` on RUN_PYTHON (a holding tractor's `UpdateCharge` may `StopFiring`, NC:3472-3474).
- **K1** (`run_k1` NC:3240-3340; records NC:3290-3334): fire SFX start/loop, launch sounds, projectile script `Create`, E3/E4/E5/E6/E7, tractor E8 (via RUN_PYTHON), loop-sound stops.
- **K2** (`run_k2` NC:4350-4399): for a **damage pulse**, the **whole** `apply_hit` inline (damage, `dispatch` presentation with its S1/S2 draws and severance, deaths with death scripts and splash, E9-E18 as applicable); loop-sound stops inline. **Resting-contact presentation is no longer inside the walk**: it runs once, after DONE. `combat_k2_drain` draws shielded contacts whose instance id and view offset the kernel took at contact time natively (the shield splash, in C++); the rest go to `_k2_present_batch`, which uses the carried power level and shields answer but reads the instance map and view offset live at the drain (`beam_contact`, `_mesh_xyz`). Ordering consequence: resting presentation for tick N now runs after every damage pulse, death and event of that same K2 step. It draws no shared RNG, so the batch moves no random-stream position (**inferred** from `beam_contact` and `hit_vfx.spawn` containing no draw; HF:502-612).
- **K3** (`run_k3` NC:4906-4943, `_k3_walk` NC:4945-4981): no presentation; only `expire` → set removal + E19, after the DONE writes are applied (NC:4965, 4977-4979). Torpedo-hit presentation runs **after** the K3 walk (HL:1340-1350).

---

## 5. Ordering rules a boundary queue must preserve

- **R1 Collision before its own damage consequences.** Post order today: `ET_PLANET_COLLISION` (COL:853) → `ET_CLOAKED_COLLISION` (COL:868) → `ET_OBJECT_COLLISION` A-destination, B-destination (COL:869, 938-950) → impact `apply_hit` A then B (COL:891-907) → each may emit E10/E12/E13/E14/E9. Delivery must keep the collision events ahead of the `ET_OBJECT_EXPLODING` the impact causes (E1M2 Haven and Facility beats). The E3M1 handler shape says BC applies the collision damage **inside** the chain (**inferred**); keeping today's "events, then damage" order preserves E1M2 but not E3M1. **Pinned**: Haven by `test_moving_asteroid_hitting_haven_counts`, Facility by the test beside it, unit-level by `test_collision_event_precedes_the_impact_damage` (§6).
- **R2 A hit's own order.** `ApplyDamage` (no event) → hull: E12 → E10 → E11 → (lethal) `SetDying` → `death_cascade.begin` (S1 draws) → death script → **E13** → death splash (nested full hits on neighbours: their E9, possibly their E13) → E14 (rock pieces) → remaining subsystems' E12/E10/E11 → `dispatch` (severance E10) → **E9 last** (CB:785-913; OBJ:1074-1100; damage-map §6.1-6.2). So E13 precedes the killing hit's E9. **Pinned** by `test_killing_hit_posts_exploding_before_its_weapon_hit` (§6).
- **R3 Launch order.** E3 (`register` WS:652) → E4 (WS:3587) → E5 (WS:3471) → E6 (WS:3472); BC's audited order is E4 → E5 → E6 (WS:3466-3470). E4 before E5 is pinned; E3 before E4 and E6 after E5 are not.
- **R4 Death lifecycle and existence.** E13 at `begin`; E15 → E16 (per locker) at throes end (SD:155-163); removal: E16 again (nothing left to clear) → E17 → group exit → E18 (SD:219-246). `retire` = E15 → E16 → E17 → E18 (SD:256-265). E13 must be delivered before any of the same object's E15/E17/E18, and before the object leaves its set (handlers read `GetContainingSet`). Rocks: E13 inside the hit; E15-E18 come from `rock_death.advance` in the **next** GameLoop tick at the earliest (LP:105-107), or from `object_lifetime.advance` in the combat step (HL:1367-1369) when the death script set a lifetime (OL:54-63, which also runs the death splash first). A collision kill (frame end) and its retirement can be one frame apart.
- **R5 Torpedo hit.** E19 for the hit torpedo precedes the hit's E9 (expire inside `update_all` PR:1037-1038 / after K3's writes NC:4977-4979; `apply_hit` after it returns, HL:1340; damage-map §6.4). Not pinned.
- **R6 Handlers that mutate state the rest of the tick reads.** E8M2 `WeaponHitMatan` (`SetHurtable(0)`, later same-tick hits); E8M2 `TractorHandler` (`StopFiring` before `cb.tractors`; the force is now in the motion stage, see the TRACTOR_STARTED row); E7M2 `ShipsCollided` (kills before impact damage, once the stub is real); Episode7 `TorpedoFired` (tube destroyed between E4 and E5 once the stub is real); MissionLib FF / `ObjectStartedExploding` and QB `ShipDestroyed` post nested events (`ET_FRIENDLY_FIRE_GAME_OVER`, E16) **inside** the outer dispatch. Inside K1/K2 the walk re-reads the mirror after every record's handlers (K1 `walk.pin_system` NC:3333-3334; K2 `cx.resend` NC:4389), so today these mutations are seen by the rest of the walk; queued, they are not (remaining-fallbacks-map §4 "Not provably"). Not pinned.
- **R7 Gate before effect.** `ET_ENVIRONMENT_DAMAGE`: chain, then drain (RAD:127-128), and the gating handler reads what the drain changes (§3). Either the drain is queued behind the event, or the cancel becomes a flag (roadmap decision 8). `MissionLib.IgnoreEvent` is already special-cased by name for the nebula creation hit (NR:32-37). Pinned for the cancel itself (`test_swallowed_event_applies_no_damage`), not for the read-after-drain.
- **R8 Random-stream order.** S1 draws inside a hit (HHS:93/123, `GetRandomSound`) and inside deaths (cascade plan, death script, cascade rolls) interleave with S1 draws by AI and missions (Episode7, E8M2) and by the cascade's gameplay rolls. S2 draws by presentation (particles, surface points) interleave with AI's `random.choice` (`ai_driver.py:1008`). Moving any presentation call relative to these changes later gameplay draws. The audio draw is already wall-clock dependent (HF:187-200, damage-map H10). Resting K2 contacts draw nothing, so the Task 2 batch does not move this. Not pinned. **Resolved 2026-11-02 for presentation** (presentation RNG, spec `2026-11-02-presentation-rng-design.md`): cosmetic draws come from their own generator, pinned by `tests/integration/test_presentation_rng_falsifier.py`. Gameplay draws (AI, missions, cascade damage rolls) still interleave with each other, by design.
- **R9 Watcher timing.** Inline dispatch happens before the watcher commits its new value (FRW:113-114). Not pinned.
- **R10 Frame vs tick.** Collisions are per frame on wall-clock dt after all ticks (HL:12825-12828); radiation is per tick but after all combat ticks of the frame (HL:12681-12688); GameLoop ticks (AI, rock retirement, shield/repair updates) all run before the first combat tick (HL:12357-12358). The queue must define which boundary each source's events land on; flushing once per frame would deliver tick-1 combat events after tick-3 combat. Not pinned.
- **R11 Destination-chain exceptions propagate** (EV:810-812) into the combat step today; a queue flushed outside the kernel changes where a raising mission handler unwinds (K1/K2 abandon paths, NC:3337-3339, NC:4395-4396). Not pinned.

---

## 6. Tests that pin event order today, and the gaps

| Test | Pins |
|---|---|
| `tests/integration/test_e1m2_rocks.py:80-110` `test_moving_asteroid_hitting_haven_counts` | **The lethal Haven impact, R1.** Real E1M2 handlers (`PlanetCollision`, `ObjectDestroyed`), `AsteroidHitPlanet` / `AsteroidDestroyed` replaced by recorders; an asteroid with closing speed 5 GU/s driven into Haven by `GameLoop.tick()` + `collisions.tick_collisions(1/60)`. Asserts `hit == [1]`, `killed == []`, the key gone, and `rock.IsDying() or rock.IsDead()` after 60 ticks. It does not assert that the first contact was the lethal one; the mutation proof below is what shows the first impact decides the outcome. **Mutation-proven 2026-11-02** (move `_emit_planet_collision` after the impact damage → `assert [] == [1]` fails; `engine/appc/collisions.py` restored by copy and `diff`ed clean). It pins the **outcome** of the order, not an event list |
| `tests/integration/test_e1m2_rocks.py:113-156` facility strike | `beats == ["station", "destroyed"]`: `ET_OBJECT_COLLISION` handled before `ET_OBJECT_EXPLODING`, lethal strike (R1) |
| `tests/integration/test_e1m2_rocks.py:159-` no cascade | one Haven strike after a lethal impact |
| `tests/unit/test_collision_event.py:205-250` `test_collision_event_precedes_the_impact_damage` | `ET_OBJECT_COLLISION` is delivered while the struck rock's hull is full and it is not dying, and `ET_OBJECT_EXPLODING` follows (R1, unit level) |
| `tests/unit/test_killing_hit_event_order.py` (added by this task) | R2: the killing hit's `ET_OBJECT_EXPLODING` precedes its `ET_WEAPON_HIT` for a ship and a rock, and the explosion's `FiringPlayerID` is the firer. **Mutation-proven 2026-11-02** (post the hit event before the damage and skip the late post → both cases fail on the index assertion; `engine/appc/combat.py` restored by copy and `diff`ed clean) |
| `tests/unit/test_planet_collision_event.py` (whole file) | source/destination, one per contact; **no** order vs damage |
| `tests/unit/test_rock_death.py:87-99, 102-120` | E13 at `begin`, E15 only after the lifetime; E15 before E18, E15 while still in the set |
| `tests/unit/test_ship_death.py:~610-640` | the explosion event carries the killer's id (direct `ship_death.begin` only) |
| `tests/unit/test_torpedo_fire_gates.py:162-167` | `ET_TORPEDO_FIRED` before `ET_WEAPON_FIRED` (R3, E4 before E5) |
| `tests/unit/test_subsystem_threshold_events.py:27-60` | which E10 type fires (single-event lists) |
| `tests/unit/test_radiation.py:113-118`, `tests/unit/test_event_chain_passes.py` | the gate: a swallowed `ET_ENVIRONMENT_DAMAGE` applies no damage (R7, cancel half) |
| `tests/integration/test_native_k1_differential.py:185-198, 539-541`, `tests/host/test_native_k2_differential.py:451-460, 880-882`, `tests/helpers/k3_fight.py:431-443, 662-664`, `tests/helpers/k0_fight.py:111` | the whole `AddEvent` log, Python path vs native path: identical order between the two, not against a golden. Since Task 2 the K2 differentials compare presentation calls per tick as a multiset (`compare_calls`, `tests/helpers/k3_fight.py:288-301`) and keep game-state calls and events in exact order |

**Verdict on the E1M2 lethal impact (Task 1 Step 2):** pinned, by `test_moving_asteroid_hitting_haven_counts`, and the pin bites: moving the planet-collision post after the impact damage fails it. No new E1M2 test was added. Two caveats for the queue work:
1. It drives `GameLoop.tick()` and `collisions.tick_collisions` directly and relies on synchronous dispatch. If delivery moves to a host-loop boundary, the test sees nothing (`hit == []`) unless it also flushes the queue the way the host will. It would fail loudly (good), but must be updated to call the same flush.
2. It does not check `ET_OBJECT_EXPLODING`'s `FiringPlayerID` (the killer is Haven, via `source=b.obj`, COL:891-907 → OBJ:1097 → RD:68), so it would not notice a regression where the kill is attributed to the player. `test_killing_hit_event_order.py` pins attribution through `apply_hit`, but no test pins it through the collision path.

**Open (no pin):** R3 (E3 before E4, E6 after E5), R4 (full death lifecycle across the throes), R5, R6, R7 (read-after-drain), R8, R9, R10, R11. R5, R6 and R10 need the host loop or a real mission with stubs implemented and were judged not cheap to pin headlessly with the real scripts: the headless harness runs no combat step (§0.2), and the R6 consumers either act through the unimplemented `SetConditionPercentage` or need a scripted Matan/tractor scene.

---

## 7. Findings outside the ordering rules

Each was checked against the code in this tree. None is fixed here.

| # | Finding | Evidence |
|---|---|---|
| F1 | **The E3M1 invincible player takes no collision damage in its invincible windows.** The SDK handler un-sets invincibility only around `CallNextHandler`; ours applies collision damage after the event returns, so the immunity gate skips it. That BC applies it as the chain's default is **inferred**. | `Maelstrom/Episode3/E3M1/E3M1.py:843-853`; COL:869 then 881-907; CB:738-753; SH:1816-1831 |
| F2 | **`MissionLib.SetConditionPercentage` is a no-op everywhere.** The engine defines it on no subsystem class (the only mention is a docstring, WS:3733); the call resolves through `__getattr__` stubs, and the stub heatmap ranks it. Episode7's tube destruction, E7M1's freighter kill, E7M2's `DestroyShip`, E8M2's cloak kill and E3M5's 15% clamp do nothing today. Implementing it adds same-tick mutations inside K1 and inside collision dispatch. | `MissionLib.py:2293-2301`; `docs/stub_heatmap.md:109-152` (PhaserBank, TorpedoTube, ShipSubsystem, HullSubsystem, TractorBeam, PowerSubsystem, SensorSubsystem, ShieldSubsystem, RepairSubsystem, PulseWeapon, CloakingSubsystem rows) |
| F3 | **Part severance is gameplay inside presentation code and needs a renderer instance.** Headless runs never sever, so headless and live outcomes differ. | HF:427-447; PS:546-548 |
| F4 | **Collisions run once per render frame, after all sim ticks, on wall-clock dt.** | HL:12825-12828 (and §0.2) |
| F5 | **The E1M2 / E2M1 / E2M2 / E6M4 `WeaponFired` handlers are inert**: our `ET_WEAPON_FIRED` carries no `ObjPtr`, and the stub it vends casts to `None`. | `Maelstrom/Episode1/E1M2/E1M2.py:1384-1390`; `docs/stub_heatmap.md:119` (`TGEvent.GetObjPtr`); `_post_weapon_fired` WS:699-715 |
| F6 | **`ET_CLOAKED_COLLISION` fires on planet impacts.** `getattr(planet, "GetCloakingSubsystem")` returns a truthy `_Stub`, the chained `IsTryingToCloak()` is truthy, so the cloak test passes. Checked live: `Planet.GetCloakingSubsystem` and its result are `_Stub` objects and `IsTryingToCloak()` is truthy. The code comment records it as a live bug. | COL:987-1034 |
| F7 | **Death-splash hits report as `TORPEDO`** (`weapon_type="torpedo"`), so E8M2 `WeaponHitMatan`'s torpedo test and E3M1's phaser count can be tripped or not by a neighbour's death. | SPL:77-82; `Maelstrom/Episode8/E8M2/E8M2.py:4856-4866` |
| F8 | **Grinding contact posts an `ET_WEAPON_HIT` (NON_WEAPON) every frame** the grind damage rate reaches `kGrindMinDamageRate`, so `ConditionAttacked` and friendly-fire accounting accumulate per frame while two hulls scrape. No collision event is posted for a grind. | COL:39, 597-615, 792-809 |
| F9 | **(Fixed 2026-11-02, presentation RNG.)** **Presentation draws from both gameplay random streams**, including the process-global `random` the AI's random selector uses, and the hit-audio draw depends on wall-clock time. | HHS:93/123; HF:187-200; `engine/appc/ai_driver.py:1008` |
