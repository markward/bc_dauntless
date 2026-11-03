> **Superseded in part (2026-11-02, native-damage phase):** §1.1-§1.2 describe the K2 CONTACT damage record and the host-loop K3 hit loop, both removed when the switch is on. K2 applies damage pulses in the walk and K3 applies its hits itself. Every other caller uses the native hit, and every effect is a queued kind. The record of what was built is spec `docs/superpowers/specs/2026-11-02-native-damage-design.md` §10.

> Snapshot map written 2026-11-02 at `e2b100f2c` (branch `ws/combat-native-damage`, worktree `.claude/worktrees/native-combat-k3`), after the effect queue, fire events, launch deferral and presentation-RNG phases landed. Input to roadmap workstream **D** ("move damage application to C++", `docs/superpowers/specs/2026-11-01-threaded-weapons-combat-roadmap.md` §4 D, decisions 7, 8, 9, 12, 13). It **refreshes** `damage-map.md` (written before those four phases) and does not repeat what is still true there: read that map's §2-§3 for the line-by-line `_apply_hit` walk and its §7 for the bit-exactness hazards. It maps facts and does not design. Line numbers drift: re-check one before relying on it. Anything not read off code (or off a measured run, §9) is marked **inferred**.

# Damage application, refreshed: callers, side effects, handlers, death, numbers

Abbreviations: **CB** `engine/appc/combat.py` · **HF** `engine/appc/hit_feedback.py` · **HL** `engine/host_loop.py` · **NC** `engine/appc/native_combat.py` · **OBJ** `engine/appc/objects.py` · **SS** `engine/appc/subsystems.py` · **SH** `engine/appc/ships.py` · **WS** `engine/appc/weapon_subsystems.py` · **SD** `engine/appc/ship_death.py` · **DC** `engine/appc/death_cascade.py` · **SPL** `engine/appc/splash_damage.py` · **RD** `engine/rocks/death.py` · **EQ** `engine/appc/effect_queue.py` · **FRW** `engine/appc/float_range_watcher.py` · **PRNG** `engine/appc/presentation_rng.py` · **PS** `engine/appc/part_severance.py` · **LP** `engine/core/loop.py` · **RAD** `engine/appc/radiation.py` · **COL** `engine/appc/collisions.py` · **SDK** = the SDK scripts root (`paths.sdk_scripts()`). Clean-room reference = `stbc_reference/spec/*.md` (sibling checkout; the MCP server did not connect this session, the local corpus was read directly).

---

## 0. Headline

1. **Damage is still a fully synchronous Python chain, and nothing about it is queued yet.** The effect queue carries nine weapon kinds (fire sound, loop stop, weapon fired/failed, torpedo fired, ammo, reload, charge-watcher crossing, launch); none is a damage kind. `ET_WEAPON_HIT`, `ET_SUBSYSTEM_*`, `ET_ADD_TO_REPAIR_LIST`, condition-watcher crossings and `ET_OBJECT_EXPLODING` are all posted with `AddEvent` inside the hit (CB:920, SS:1123-1138, SS:2900-2901, FRW:171-176, SD:303-309). The only mid-walk Python left in K2 is the damage pulse (C1); K3 hands its hits back after `DONE` (C2) (§1).
2. **Measured: 0.52 hits per tick, 0.09 ms per tick in `apply_hit`** (64 ships, 8,999 ticks, §9). 84% of hits are K2 pulses. 81% of hits overlap no subsystem; 90% post exactly one event (their own `ET_WEAPON_HIT`); 62% are wholly absorbed by a shield face. A tick with two or more hits happens in 9.5% of ticks (max 14). Eight deaths in the fight, every one inside a hit; zero death-splash victims. The largest single cost inside a hit is the splash loop's per-subsystem world position (34%), then `dispatch` (28%) (§9.3). So D's direct saving is small; its value is removing the K2 mid-walk check-in (workstream I) and the event timing.
3. **BC's event bus enqueues** (clean-room `TGEventFamily.md` §5: "An event is delivered by enqueue onto a manager's singly-linked queue … the `TGEventManager` pump later drains the queue"). Our synchronous dispatch is the departure; a handler's change landing after later hits (decision 9) is closer to BC, not further. When BC's pump runs relative to the sim tick is not reconstructed (`TGEventFamily.md` §6 lists the pump as a wall) (§3.6).
4. **`SetInvincible` probably does not mean "takes no damage" in BC, but it does in ours.** SDK scripts use an invincible ship's damage as gameplay: E3M1's drill knocks out an invincible Bird of Prey at hull < 50% (`Maelstrom/Episode3/E3M1/BOPAI.py:37` with `E3M1.py:3310`), E8M2 disables an invincible Matan by his shields/engines (`E8M2.py:2416`, `:4712-4721`, `:6122-6176`), E3M5 says "Set ship invincible so it won't actually blow up" (`E3M5.py:1065`). Ours makes `IsImmuneToDamage = _invincible or not _hurtable` (SH:1828-1831) and skips every mutation (CB:753-760). Under ours, Matan in E8M2 can never be damaged at all, so his `SetHurtable(0)` is redundant and his disable beat cannot fire (**inferred** from the scripts; BC semantics not reverse-engineered) (§3.7). This decides what decision 8's flags mean.
5. **The death path's in-tick gameplay is small and mostly arithmetic**: `SetDying`, two S1 roll families (throes length, blast schedule), and the death splash, whose hit point is **always** the sphere-facing fallback with no normal, because `ship_death.begin` calls `splash_damage.apply(ship)` with no instance map (SD:115, SPL:87-109, CB:108-110). The death script already runs in the presentation scope; `ET_OBJECT_EXPLODING` is order-sensitive and one stock handler changes damage state for the very splash that follows it (E2M2, §3.2, §4).
6. **Shield faces have one SDK entry point** (`SetCurShields` → `SetCurrentShields`, SS:2148-2161) and six in-place engine writers (§6). No pickled restore of a `ShieldSubsystem` exists (the save system stores no ship graph, `engine/appc/save_load.py:15-19`).
7. **Three subsystem events stock missions listen for are never posted**: `ET_SUBSYSTEM_COMPLETELY_DESTROYED` (E8M1, E8M2, `Maelstrom.py`), `ET_SUBSYSTEM_DAMAGED` (E2M0), `ET_SUBSYSTEM_STATE_CHANGED` (E3M4). Not recorded in `event-emitter-gaps.md` (§3.3).

---

## 1. Callers today

### 1.1 C1 — K2 damage pulse (inside the K2 walk)

The only record K2 still hands back for an effect (k2_beams.h:118-131; fire-events spec §10). Per pulse, in Python, in this order:

| Step | Where | What |
|---|---|---|
| 1 | NC:4775-4798 `run_k2` (opens `_effect_queue.session()`, NC:4797) → `_run_k2` NC:4801-4840 | binding applies the record's write log first (the session applier), then `kind == CONTACT` |
| 2 | `_k2_contact` NC:4671-4673 → `_k2_run_contact` NC:4704-4726 | rebuilds 3-5 `TGPoint3`s (`_k2_points` NC:4652-4668, preserving the fallback/origin identity aliases); reads `level = hl._phaser_level(sys_)` (HL:1216-1220: `sys_.GetPowerLevel()`, live) |
| 3 | `HL._phaser_contact` HL:1226-1279, branch `flush_dwell > 0` | damage arithmetic in Python: `_phaser_damage_for_tick(bank.GetMaxDamage(), bank.GetMaxDamageDistance(), dist, flush_dwell) * PHASER_INTENSITY_SCALE[level]` (HL:1258-1263); `damage_hull = sys_.GetPowerLevel() != sys_.PP_LOW` (HL:1270-1271) |
| 4 | HL:1272-1279 | `combat.apply_hit(target, damage, impact_point, source=ship, normal, ship_instances, weapon_type="phaser", hardpoint_weapon=bank, damage_hull, shield_point=bubble_entry)` — the whole §2 chain, `hit_feedback.dispatch`, `ET_WEAPON_HIT` |
| 5 | NC:4832 `cx.resend()` | re-sends whatever per-step context the Python changed; the kernel then re-reads the mirror (`_condition`, `_dying`, `_is_on` pushed by their NativeFields during step 4) — ruling P1: the next bank on the same target sees what this pulse left |

Measured: **0.434 pulses per tick** (3,906 / 8,999, §9). Bank `_max_damage`, `_max_damage_distance` (SS:398-399) and the bank's DRF (SS:403) are not mirrored; `PhaserSystem._power_level` is (WS:2582, weapon-state phase), but the pulse path still reads it live in Python.

### 1.2 C2 — K3 torpedo hits (after the K3 step)

`projectiles.update_all` → `NC.run_k3` NC:5362 → `_k3_walk` NC:5401-5436: on `DONE` the binding applied the write log; `_k3_walk` turns hit handles into objects **before** any `expire()`, rebuilds the bubble/hit-point identity alias, then runs `expire(t)` for every expiring torpedo (set removal + `ET_TORPEDO_EXITED_SET`) and returns `out` (NC:5414-5436). Back in `_advance_combat_step`, after `clear_step()`, one `combat.apply_hit(ship, torpedo._damage, hit_point, source=torpedo._source_ship, normal, ship_instances, weapon_type="torpedo", hardpoint_weapon=torpedo, shield_point=torpedo._bubble_entry)` per hit, in `hits` order (HL:1355-1364). Each hit runs fully, events included, before the next.

Measured: **0.071 hits per tick** (640 / 8,999). The torpedo's `_damage` and `_damage_radius_factor` are slots, not mirrored (`engine/appc/projectiles.py:69-72`, `_TORP_FIELDS` NC:2583-2598 lists neither).

### 1.3 What the effect queue already carries, and where it delivers

- **Kinds** (EQ:125-130, `combat_effect_queue.h` order): `FIRE_SOUND`, `LOOP_STOP`, `WEAPON_FIRED`, `WEAPON_FIRE_FAILED`, `TORPEDO_FIRED`, `AMMO_CONSUMED`, `TORPEDO_RELOAD`, `WATCH` (a **weapon's charge** watcher only: FRW:137-145 queues only for an owned watcher, and only a weapon owns one; fire-events ruling F1), `SPAWN` (launches). **No damage kind.** `ET_WEAPON_HIT` and everything under `apply_hit` post synchronously (CB:920).
- **Delivery point:** the tick scope opened by `_combat_effect_scope` around `sim.weapons` + `sim.combat` (HL:958-969, opened HL:12651-12663), flushed when it closes, i.e. after each tick's combat step, in emission order, with decision 13's error handling (EQ:291-346). A native session outside the scope (an AI `StartFiring` from `gl.ai`) opens its own deferral and delivers at its end (ruling F3, EQ:195-243).
- **Separate:** K2's resting-contact presentation queue (`K2Rest`), drained after the K2 step's `DONE` (`combat_k2_drain` NC:4833, `_k2_present_batch` NC:4676-4701), presentation only.
- **Consequence inside a hit:** a handler that reacts to a hit event and produces a queued kind (e.g. a mission `StopFiring` on a firing bank → `LOOP_STOP`) appends it while the scope is open; its non-queued writes (`_firing`) land at once (fire-events ruling E4).

### 1.4 Non-kernel callers, relative to the sim tick and the flush

Frame order (live host): N × `GameLoop.tick` (AI, timers, `rock_death.advance`, shield/power/cloak/repair `Update`; LP:29-116) → for each tick: **[scope open]** `sim.weapons` + `sim.combat` **[flush]** (HL:12644-12663) → sensor contacts → N × nebula + radiation (HL:12708-12716) → `hull_breakup.drain`, `hull_wear.drain` (HL:12845-12851) → collisions once (HL:12853-12857) → scenery/minor contact (HL:12862-12867).

| Caller | Entry | Runs | Relative to the flush |
|---|---|---|---|
| C3 collision grind | `COL._grind_contact` → `apply_hit` COL:597-616 | per **frame**, wall-clock dt | after every tick's flush; outside any scope (synchronous) |
| C4 collision impact | `COL._respond_pair` → `apply_hit` COL:880-907, after the collision events | per frame | same as C3; R1 order (event, then damage) |
| C5 `AddDamage` | OBJ:1032-1055 → `apply_hit(..., source=None, splash_radius, bypass_shields=True)` (ShipClass only) | the death cascade's damaging blasts in `cb.death` (DC:265-284, inside the scope); SDK `Effects.DeathExplosionDamage` via `DamageableObject_GetObjectByID` (OBJ:1554-1565); NanoFX shim (`engine/compat/fx_api/NanoFX_ScriptActions.py:50`); mission scripts (wherever they run: timers in `GameLoop.tick`, before the scope; handlers, inside whatever posted) | cascade blasts: inside the tick, before K1/K2 |
| C6 death splash | `SPL.apply` SPL:34-85, from `SD.begin` SD:113-118 and `object_lifetime._expire` (`engine/appc/object_lifetime.py:54-63`, `cb.death`) | nested inside the killing `DamageSystem`, or in `cb.death` | wherever the death happened |
| C7 scenery contact | `engine/rocks/scenery_contact.py:136` (`respond`, from `pump` :146, HL:5673-5679) | per frame, player only | after collisions |
| Radiation | `RAD.apply_chunk` RAD:144-168 → `ship.DamageSystem(hull, amount)` RAD:165 (or `SetCurrentShields` RAD:159), gated on `ET_ENVIRONMENT_DAMAGE` passing | per tick, after **all** combat ticks of the frame | after the flush; never inside a scope |
| Subsystem cascade | `subsystem_cascade._fire` → `DestroySystem` (`engine/appc/subsystem_cascade.py:62-81`) | `cb.damage_sys`, 1.5 s after hull 0 | inside the tick |
| Power-plant breach | `PowerSubsystem._trigger_breach` SS:2615-2660 → `warp_core_breach.arm` + `ship_death.begin` | `GameLoop.tick` (`_update_ship_subsystems` LP:127-157) | before the tick's scope |
| Severance | `PS._destroy_subsystems_on_part` PS:526-552 (`SetCondition(0.0)`), inside `dispatch`; `hull_breakup._destroy_subsystems_inside` (`SetCondition(0.0)`, `hull_breakup.py:232`) per frame | live only (needs a render instance) | F7 inside the hit; B after the flush |
| SDK `DamageSystem`/`DestroySystem`/`AddDamage` | 15 SDK files call them directly (grep: `AI/PlainAI/SelfDestruct.py`, `Effects.py`, `TacticalInterfaceHandlers.py`, `Systems/Vesuvi/Vesuvi5_S.py`, `Maelstrom.py`, E2M1, E2M6, E3M2, E3M4, E3M5, E5M2, E6M2 (18 calls), E6M4, E6M5, E7M3) | wherever the script runs | mostly AI/timers (before the scope) or inside a handler |
| Dev | `]` key / `DAUNTLESS_DEV_DESTROY` (`DestroySystem(hull)`, `engine/dev_keybindings.py:117`, HL:11904) | input | outside |

`apply_hit` asserts it is not inside a presentation scope (CB:621-622 → PRNG:89; raises under pytest, logs once under `--developer`).

---

## 2. The `SetCondition` side-effect chain

### 2.1 The chain, current lines

`DamageableObject.DamageSystem` OBJ:1086-1112: `amt <= 0` → return; `new = max(0, cur - amt)`; `SetCondition(new)`; `_route_zero_crossing` (OBJ:826-850) on `cur > 0 and new <= 0`; then, if `new <= 0`, critical, not dying, not dead: `rock_death.begin` or `ship_death.begin(self, killer=source)`.

`ShipSubsystem.SetCondition` SS:733-746:

| # | Line | Effect | Who reads it, and when |
|---|---|---|---|
| S1 | SS:743 | `_condition = max(0, v)` — `NativeField(float)` SS:326: pushes to the mirror row | K1 fire gates, K2 `shields_block` (generator condition), K0 `_is_offline`, Python `IsDisabled`/`IsDestroyed`; **the rest of the same tick** (K2: after `cx.resend`, same walk) |
| S2 | SS:793-796 | `_combined_watcher._update(pct)`, `_condition_watcher._update(pct)`: both **unowned** FRWs created lazily (SS:1083-1108), so both fire synchronously (FRW:146-149) | SDK `Conditions/ConditionSystemBelow.py` (`GetConditionWatcher`, `ET_AI_SYSTEM_STATUS_WATCHER`), Brex / Engineer (`GetCombinedPercentageWatcher`). Handlers read the **stamped float** (`ConditionSystemBelow.SystemEvent` reads `pFloatEvent.GetFloat()`), not the watcher, after setup |
| S3 | SS:797-815 | threshold state machine (`_threshold_state`, Python only) → `_fire_threshold_event` SS:1123-1138: `ET_SUBSYSTEM_DESTROYED` (+ `internal_blast.queue`, `engine/appc/internal_blast.py:61-78`), `ET_SUBSYSTEM_DISABLED` (only from OPERATIONAL), `ET_SUBSYSTEM_OPERATIONAL`; src = subsystem, dest = owning ship | §3 handlers. `internal_blast._pending` → `internal_blast.advance` in `cb.damage_sys` (HL:1396), live-only wear |
| S4 | SS:744-746 → SS:748-757 → `AddToRepairList` SS:2884-2902 | append to `RepairSubsystem._queue` + `ET_ADD_TO_REPAIR_LIST` (dest = the bay), on the first damage below max | `RepairSubsystem.Update` (SS:2919-2968) in `GameLoop.tick` (LP:150-152): the **next** GameLoop tick, which in a multi-tick frame is in the next frame, because all of a frame's GameLoop ticks run before its first combat tick (HL:12382, 12644). Also `IsBeingRepaired` (SS:2915-2917, SDK), `HandleIncreasePriority` (SS:2990-3002), the UI pane (`engine/ui/eng_repair_pane.py:60`). `ET_ADD_TO_REPAIR_LIST` has no SDK consumer (event-inventory §2.2) |
| S5 | OBJ:836-850 | power plant (targetable) → `warp_core_breach.arm` (`_armed` list, `engine/appc/warp_core_breach.py:51-58`); hull → `subsystem_cascade.schedule` (`_active`, `engine/appc/subsystem_cascade.py:36-45`, gated on `IsDestroyBrokenSystems`) | `warp_core_breach.advance` (HL:1390) and `subsystem_cascade.advance` (HL:1388) in `cb.damage_sys`. A K3 hit (C2, before `cb.damage_sys`) is acted on **the same tick**; a K2 pulse (after it), a collision or radiation **the next tick** (read off the step order HL:1355-1416). The breach deals no damage (`warp_core_breach.py:15-19`); the cascade `DestroySystem`s every subsystem after `CASCADE_DELAY` 1.5 s |
| S6 | OBJ:1102-1112 | death: §4 | `_dying` NativeField (OBJ:862) → kernels the same tick; `ship_death._active` → `cb.death` (HL:1375-1384) |

`SetCondition(0.0)` from severance (PS:548, `hull_breakup.py:232`) and from scripts runs S1-S4 but **not** S5/S6: only `DamageSystem`/`DestroySystem` route a zero crossing or a death (OBJ:1086-1134; severance-map §2.1). Death is otherwise reached only from `PowerSubsystem`'s destroyed-plant trigger (SS:2615-2660, next `GameLoop.tick`) and dev paths (grep of `ship_death.begin(`).

### 2.2 What already has a native counterpart

| Piece | Native today | Gap |
|---|---|---|
| `_condition` write (S1) | yes: the row field; K0/K1/K2 write logs already apply logged values through `apply_writes` with quiet setters (NC write-apply path) | a native write must still run S2-S6, or the kernel must own them |
| `IsDisabled`/`IsDestroyed`/`GetMaxCondition` | `sensor_detect.cc:128-140, 206-215`, `fire_gates.cc` (leaf + aggregate) | — |
| Threshold state machine (S3) | none; `_threshold_state` is a plain Python attribute | small: three states from `IsDestroyed`/`IsDisabled`, both native |
| Condition watchers (S2) | **K0's `WATCH`** is the precedent: a kernel commits the value and appends `WATCH(weapon, old, new)`; delivery runs `_fire_crossed(old, new)` against the checks registered **at delivery** (EQ:398-403, FRW:151-157; ruling E3). The kernel learns "has checks" from `_watch_checks`, pushed by the watcher's `_owner` on `AddRangeCheck`/`RemoveRangeCheck` (FRW:88-104), and the old value from `_watch_value` (NC:894-911) | condition watchers have no owner and no row fields; there are **two** per subsystem (condition, combined) watching the same fraction with separate check sets; `WATCH` names a weapon and resolves `weapon._charge_watcher` at delivery (EQ:398-403), so a subsystem kind would need its own resolution. Today's semantics differ in one way that matters to a handler: inline dispatch fires **before** the watcher commits (`GetWatchedVariable` returns the old value, FRW:146-147); `WATCH` commits first (E3). Stock condition handlers read only the stamped float after setup (§2.1 S2), so **inferred** harmless |
| Repair enqueue (S4) | none; `_queue` is a Python list of objects with an identity scan | the queue's only same-tick reader is none (the bay updates in `GameLoop.tick`); the event has no SDK consumer |
| Zero-crossing queues (S5) | none; Python lists of ship objects | both consumers run in `cb.damage_sys`; ordering relative to C1 vs C2 differs (S5 row) |
| Death (S6) | `_dying` only (mirror) | §4 |

### 2.3 Measured frequency of the chain inside hits (§9)

3,809 `DamageSystem` calls in 4,670 hits; 1,791 watcher updates that had checks (condition/combined watchers being watched by AI conditions), **9** crossings fired; 623 repair enqueues; 40 `ET_SUBSYSTEM_DESTROYED`, 36 `ET_SUBSYSTEM_DISABLED`, 0 `ET_SUBSYSTEM_OPERATIONAL`; 40 internal blasts queued; 8 hull zero crossings (cascade scheduled), 0 breach arms inside hits (16 outside: the cascade's `DestroySystem` and the plant trigger).

---

## 3. Handler scan

### 3.1 Method

A read-only scan of every SDK registration (`AddPythonFuncHandlerForInstance`, `AddBroadcastPythonFuncHandler`, `AddBroadcastPythonMethodHandler`, `AddPythonMethodHandlerForInstance`) of `ET_WEAPON_HIT`, `ET_SUBSYSTEM_DISABLED/DESTROYED/OPERATIONAL/DAMAGED`, `ET_ADD_TO_REPAIR_LIST`, `ET_OBJECT_EXPLODING` and the two AI watcher event types, extracting each handler's body and listing direct calls that write combat state (`SetInvincible`, `SetHurtable`, `SetCondition*`, `DamageSystem`, `DestroySystem`, `AddDamage`, shield setters, `TurnOn/Off`, `StopFiring`, `SetAI`, cloak calls, …). 91 registrations. Handlers that call a helper were then read by hand (E2M0 `DoDamageToTheSovereign`, E8M2 `DisableMatan`, E8M1 `KessokHeavyAttacked`, E2M2 `ObjectDestroyed`, E2M6 `WeaponHitStation`, E7M2 `VorchaHitWarbird`/`WarbirdHitVorcha`, E6M1 `TransportHit`, E4M6 `PlayerFired`, E8M1 `DeviceAttacked`). Scratch script, not in the repo. **Not covered:** helpers more than one call deep that were not read, and Multiplayer handlers (report only, by name).

Everything else (AI `Preprocessors.DamageEvent` SDK `AI/Preprocessors.py:1303`, `ConditionAttacked(By)`, Bridge crew handlers, `ConditionSystemDestroyed/Disabled`, `ConditionPulseReady`, `ConditionTorpsReady`, MissionLib `FriendlyFireHandler`, QuickBattle `ShipExploding`, E1M1, E1M2, E3M1 handlers, E3M4, E4M6, E5M2, E5M4, E6M1-E6M5, E7M1, E7M3, E8M1 `ObjectExploding`) records mission flags, plays dialogue, changes AI or groups, or removes its own handler: **REPORT** for damage purposes (their AI/mission writes are read by `GameLoop.tick`, which never runs between two hits of one combat step).

### 3.2 Handlers that change state a later hit in the same tick reads

| Handler | Event | Write | Read by a later same-tick hit? | Reading under decision 9 / flag under decision 8 |
|---|---|---|---|---|
| E8M2 `WeaponHitMatan` (SDK `Maelstrom/Episode8/E8M2/E8M2.py:4856-4925`, registered :4707) | `ET_WEAPON_HIT` (instance, Matan) | first TORPEDO hit: cloak `SetConditionPercentage(0)` (stub today), `SetHurtable(0)`, `SetHidden(0)`/`InstantCloak`, sequence | yes: `IsImmuneToDamage` (CB:753) — but see §3.4: already immune | §3.4 |
| E3M5 `MatanWeaponHitHandler` (`E3M5.py:967-1015`, registered :726) | `ET_WEAPON_HIT` (instance, Matan) | hull and power `SetConditionPercentage(0.15)` when below 15% (stub today) | yes: the clamped condition | §3.5 |
| E8M2 `MatanDisableHandler` (`E8M2.py:6122-6176`, registered :2441 and :4723 on `ET_SUBSYSTEM_COMPLETELY_DESTROYED`) | `ET_SUBSYSTEM_DISABLED` (instance, Matan) | before `bCanDisableMatan`: the disabled subsystem `SetConditionPercentage(GetDisabledPercentage() + 0.1)` — a "never disabled" clamp; after it, `DisableMatan` (`:6181-6225`) drives shields, engines and weapons to 1% | yes (once the stub is real): the clamped condition, read by K1 fire gates and K2 `shields_block` | **Clamp reading:** the mission wants "Matan's systems cannot be disabled before the beat", which is a floor, not an event reaction: a per-subsystem minimum condition the kernel reads (decision 8) would express it with no handler; at the boundary the clamp lands one tick late, so a system can read disabled for one tick (its weapons skip one fire check, **inferred**) |
| E2M0 `WeaponHitSov` → `DoDamageToTheSovereign` (`E2M0.py:1306-1316`, `:2235-2280`) | `ET_WEAPON_HIT` (instance, Sovereign), first enemy hit | draws `GetRandomNumber` (S1) per phaser and torpedo child and `SetConditionPercentage` below the disabled percentage (stub today) | yes: the Sovereign's own K2 banks later in the same walk read the disabled banks (K2 re-reads after `cx.resend`) | Scripted damage, not a gate: at the boundary the Sovereign keeps firing for one tick and the S1 draws move after the step's other S1 draws (a gameplay-stream reorder, decision 12 does not cover it) |
| E8M1 `KessokHeavyAttacked` (`E8M1.py:3367-3400`, registered :968-969) | `ET_WEAPON_HIT` (instance, Kessok Heavy / Device 3) | `pShields.TurnOn()` on the Kessok; group change friendly → enemy | yes: `shields_block` reads `_is_on` (NativeFrozenField SS:1317) | The mission turned them off when the Kessok was detected (`E8M1.py:2302-2303`). Today a second same-tick hit already meets raised shields; at the boundary they come up one tick later, so the rest of that tick's hits reach the hull. Flag reading: none obvious (it is a reaction to being attacked) |
| E2M2 `ObjectDestroyed` (`E2M2.py:721-743`, registered :561) | `ET_OBJECT_EXPLODING` | the **other** Cardassian ship `SetInvincible(TRUE)`, `SetCollisionsOn(FALSE)` | yes, and inside the same `begin`: `_broadcast_exploding` (SD:108) runs before `splash_damage.apply` (SD:113-118), so today the survivor is immune to its partner's death splash | At the boundary the splash lands first. Mission intent: keep one ship alive (**inferred**). A flag reading cannot see "the partner died"; this is a sequencing case |
| MissionLib `ObjectStartedExploding` (SDK `MissionLib.py:4029-4053`) | `ET_OBJECT_EXPLODING` | posts `ET_FRIENDLY_FIRE_GAME_OVER` nested | no damage state | REPORT for damage |
| E7M2 `VorchaHitWarbird` / `WarbirdHitVorcha` (`E7M2.py:1391-1460`) | `ET_WEAPON_HIT` | play a sequence whose actions (`DamageWarbird`, `DamageWarbirdAndVorcha`) damage later | not same tick (the sequence plays later) | REPORT |
| Episode 7 `TorpedoFired` (event-inventory §2.2) | `ET_TORPEDO_FIRED` (already queued) | tube `SetConditionPercentage(0)` on a 1-in-10 S1 roll | already delivered at the boundary since fire events | — |

Watcher events in hits (`ET_AI_SYSTEM_STATUS_WATCHER`, 9 in the fight) go to AI conditions, whose `SetStatus` posts `ET_AI_CONDITION_CHANGED` nested (29 in the fight): AI state, read by `GameLoop.tick`. No stock `ET_ADD_TO_REPAIR_LIST` or `ET_SUBSYSTEM_OPERATIONAL` handler writes combat state.

### 3.3 Events stock missions listen for that the engine never posts

The engine posts only `ET_SUBSYSTEM_DESTROYED/DISABLED/OPERATIONAL/POWER_CHANGED` from subsystems (grep: SS:802, 812, 814, 1380). Never posted, with stock listeners:

| Event | Listeners |
|---|---|
| `ET_SUBSYSTEM_COMPLETELY_DESTROYED` | SDK `Maelstrom/Maelstrom.py:223` (player, `HandleSubsystemDestroyed`), `Maelstrom/Episode8/E8M1/E8M1.py:889` (`GalorDisableHandler`), `Maelstrom/Episode8/E8M2/E8M2.py:4723` (`MatanDisableHandler`) |
| `ET_SUBSYSTEM_DAMAGED` | `Maelstrom/Episode2/E2M0/E2M0.py:825` (`PlayerSubsystemDamaged`: Picard suggests repair after 5 damaged systems) |
| `ET_SUBSYSTEM_STATE_CHANGED` | `Maelstrom/Episode3/E3M4/E3M4.py:533` (`SubsystemStateChanged`) |

When they would be posted in BC is not established (no RE read). A native damage design decides whether they become queue kinds.

### 3.4 E8M2: `WeaponHitMatan` in depth

**What the mission intends** (SDK E8M2.py): Matan arrives cloaked and `SetInvincible(1)` (`MatanCometh`, :2408-2441), with `MatanDisableHandler` holding his systems above disabled. `StartTaunting` (:4698-4723) adds `WeaponHitMatan`, sets `bCanDisableMatan = TRUE` and builds three `ConditionSystemDisabled` conditions (shields, impulse, warp) → `DisableMatan`. `WeaponHitMatan`: a non-torpedo hit sets `bTorpedoFired`, `bMatanHit = -1` and returns without `CallNextHandler` (and, since `not -1 == TRUE`, the next hit re-enters the same branch); the first TORPEDO hit decloaks him, destroys his cloak (`SetConditionPercentage(0)`), makes him "temporarily invincible" (`SetHurtable(0)`, comment :4884) and plays a sequence; `MatanVulnerable` (:4932-4943), 5 s after `MatanAttackPlayer` in that sequence, sets `SetHurtable(1)` and raises his shields. So: the torpedo that reveals him should be the last damage for ~5 s plus dialogue.

**Today, two hits in one tick:** both read `IsImmuneToDamage()` True **because of `SetInvincible(1)` alone** (SH:1828-1831; nothing in E8M2 clears it: grep of `Invincible`/`Hurtable` in Episode 8 finds :2416, :2591, :4885, :4935 only). Every hit on Matan, whenever it lands, mutates nothing (CB:759-760); feedback and `ET_WEAPON_HIT` still fire (CB:885-920). The handler runs inside each hit: first torpedo → the first branch; a second hit in the same tick → the `elif bMatanPunishment` branch (false unless set at :6324) → no-op. The cloak kill is a stub no-op (event-inventory F2). **So the same-tick question is moot in our engine today, and so is the whole disable beat**: `ConditionSystemDisabled` on shields/impulse/warp can never fire because no damage lands (**inferred** from the code; not run).

**If the handler runs at the boundary (decision 9):** with our semantics, nothing changes (Matan is immune throughout). With the BC reading of §3.7 (invincible = takes damage, cannot die), a second same-tick hit after the revealing torpedo would land damage before `SetHurtable(0)`. Given BC's own bus enqueues (§3.6), that leak is plausibly BC's behaviour too (**inferred**). A flag form (decision 8) exists already: `SetHurtable` is the flag; what a native design must decide is when a handler-written flag takes effect (end of tick vs. immediately).

### 3.5 E3M5: `MatanWeaponHitHandler` in depth

**Intent** (SDK E3M5.py): Matan's Keldon warps in `SetInvincible(TRUE)` with engines invincible (`MatanWarpsIn` :718-737); every hit re-reads hull and power percentage and clamps each back to 15% ("Don't allow the keldon to get too damaged", :1003-1013); the handler also records whether the player attacked first. Read with E3M5's other comment ("Set ship invincible so it won't actually blow up", :1065), the design is: Matan takes damage, never dies, and never looks worse than 15%.

**Today:** the clamp is a stub no-op (`MissionLib.SetConditionPercentage`, event-inventory F2) and Matan is immune (invincible), so nothing is damaged and nothing is clamped. Two hits in one tick: both immune; the handler runs twice.

**At the boundary, once the stub is real and if invincible stops meaning immune:** two hits in one tick both apply before one clamp; the clamp then restores 15% for hull and power. A hit large enough to take the hull from above 15% to 0 would start the death **inside** `DamageSystem` (OBJ:1104-1112) before any clamp, today as well as at the boundary, unless "invincible" also blocks death. **The mission's intent maps to one flag: "cannot die" (and a 15% floor is scripted on top).** A per-ship minimum-condition floor read natively (decision 8) would replace the handler's write entirely; the handler at the boundary would only differ for one tick of reading below 15% (the AI's `ConditionSystemBelow` thresholds could see it, **inferred**).

### 3.6 BC's event bus queues

Clean-room `TGEventFamily.md` §5: "An event is delivered by **enqueue** onto a manager's singly-linked queue (`0x006DA2A0 → 0x006DE330`, head/tail/count); the `TGEventManager` pump later drains the queue." The dispatch pump itself is a documented wall (§6 there). So in BC a `ET_WEAPON_HIT` handler does not run inside the hit that posted it, and E3M1's `PlayerCollisionHandler` comment ("apply the damage immediately") reads as BC applying collision damage as a chain default inside the pump (campaign bug 3). **Not established:** when the pump runs relative to BC's per-tick damage, and whether `ET_OBJECT_EXPLODING` / `ET_SUBSYSTEM_*` share that queue. Our synchronous `AddEvent` (EV:802-845) is the departure, and every "handler inside the hit" behaviour mapped here is ours, not BC's.

### 3.7 What `SetInvincible` and `SetHurtable` mean (SDK evidence)

| Evidence (SDK) | Reading |
|---|---|
| `E3M5.py:1060-1067` `KillGonDev`: "Destroy the hull. `SetCondition(0)`. Set ship invincible so it won't actually blow up. We want to be able to target it." | invincible = cannot die; a hull at 0 otherwise blows up |
| `E6M1.py:3099, 3143, 3191`: "make the ship invincible so it doesn't blow up on its way home" | invincible = cannot die |
| `E3M1.py:3309-3310` BoP `SetInvincible(TRUE)` + `BOPAI.py:37` (`ConditionSystemBelow` hull 0.5 ends its drill); Geronimo invincible (:390, :1742, :2001) + `GeronimoAttackAI.py:18` (hull 0.25) | an invincible ship's hull drops |
| E8M2 Matan invincible (:2416) + disable conditions on shields/impulse/warp (:4712-4721) | an invincible ship's subsystems drop |
| E2M0 Warbirds "Make the Warbirds invincible" (:2072) + `WarbirdSystemDisabled` (:1254-1273: warp out when an engine is disabled) | same |
| `E7M2.py:1973` "Make the JonKa and Chairo not hurtable, in case of collision or stray torpedoes"; E3M1 "Player can't be hurt" around `SetHurtable` (:3193, :3691, :3786) | hurtable 0 = takes no damage |
| `MissionLib.MakeSubsystemsInvincible` header: "Makes the specified subsystems invincible/not invincible to damage" (`MissionLib.py:2230-2245`) | subsystem invincible = takes no damage (a different flag) |

Ours: ship `IsImmuneToDamage = _invincible or not _hurtable` (SH:1828-1831), introduced by `e41e4fca2` ("Invincible is a permanent 'never take damage' mark (E7M2 boss ships)"); radiation copies it (RAD:150-152). The clean-room `ShipClass.md` lists the flags (§2 `+0x2e8` cluster, "exact bit assignments not yet mapped"; §5 setter/getter addresses) but not their effect. **Inferred** BC model from the scripts: `SetHurtable(0)` blocks damage; `SetInvincible(1)` lets damage land but prevents death (and possibly clamps the hull above 0); subsystem `SetInvincible` blocks that subsystem's damage. Consequences under ours (**inferred**, not run): E8M2's Matan disable and E3M1's drill knock-outs cannot happen by damage; E2M0's Warbird warp-out cannot trigger. The 26-mission headless sweep would not notice (it checks loads and transitions, not combat beats; not verified).

---

## 4. Death

### 4.1 `ship_death.begin` (SD:74-118), split

| Order | Step | Line | Gameplay effect | Must be in-tick? |
|---|---|---|---|---|
| 1 | `_out_of_action` guard | SD:82-83 | idempotence | yes (cheap) |
| 2 | `SetDying(True)` | SD:84-85; `_dying` NativeField OBJ:862 | kernels stop targeting/firing at it (fire gates, K3 targets) the same tick; `DamageSystem` skips a second death (OBJ:1104-1105) | **yes** |
| 3 | `death_cascade.roll_duration` | SD:89; DC:152-166 | **S1** `rand(100)` when no lifetime is set: the throes length → `_mark_dead`, `ET_OBJECT_DESTROYED`, lock clearing | the draw's position in S1 is gameplay; the value is needed by `cb.death` (HL:1375-1384) |
| 4 | `death_cascade.begin` → `plan` | SD:90-95 (called inside the append); DC:184-213 | **S1** `rand(4)` per blast, all drawn now: when each damaging blast lands | same |
| 5 | `_active.append` | SD:90-95 | registers the cascade; `cb.death` advances it. The first blast (offset 0.0) fires at the first `advance`: **the same tick for a K3 kill** (`cb.death` follows the K3 hits), **the next tick for a K2 kill** (K2 runs after `cb.death`) — read off HL:1355-1416 and DC:215-232 | — |
| 6 | `RunDeathScript()` in `presentation_rng.scope()` | SD:101-106 | presentation draws (P). **Gameplay writes inside stock scripts:** E1M2 `AsteroidExploding` `SetLifeTime(0.5)` + `SetCollisionsOn(FALSE)` (SDK `E1M2.py:3084-3127`), E7M1/E3M2 likewise per rng-map D10. A ship's throes length is rolled **before** the script (step 3), so a script's `SetLifeTime` there only registers `object_lifetime` retirement (OBJ:908-920), whose `_expire` runs the death splash **again** (`object_lifetime.py:54-63`) if the ship is not yet dead (**inferred** double splash; not run) | movable (presentation scope) except its gameplay writes |
| 7 | `_broadcast_exploding` → `ET_OBJECT_EXPLODING` (synchronous) | SD:108, 287-311 | handlers: E1M2 scoring, MissionLib friendly fire (nested game over), E2M2's partner invincibility (§3.2) | order-sensitive (event-inventory R2, R4, §5.2) |
| 8 | `splash_damage.apply(ship)` | SD:113-118; SPL:34-85 | **gameplay damage** to every non-rock ship within `GetSplashDamageRadius` (no allegiance filter), nested `apply_hit`s, possibly further deaths | **yes** if splash is to stay at the blast moment |

### 4.2 `rocks/death.begin` (RD:57-89)

`SetDying(True)` → `GetContainingSet`/`GetName` → `RunDeathScript` in the presentation scope (RD:62-68) → `ship_death._broadcast_exploding` (RD:71) → `SetCollisionsOn(0)` (RD:74) → `_dying.append` with `_life(rock)` read **after** the script (RD:76; E1M2 sets 0.5 there) → `_break_up` (RD:77-80, body RD:195-: pieces join the set, `ET_ENTERED_SET` per major piece, private crc32 RNG). No splash (SPL:40-41: "a rock's death splashes nothing"), no S1/S2 draws of its own (rng-map §1.2). In-tick gameplay: `SetDying`, collisions off, the pieces (targetable remnant); the lifetime read depends on the script having run first.

### 4.3 Can the death splash be computed natively?

Yes, from data the mirror nearly has (read off SPL:34-109 and CB:86-143):
- **Inputs:** the dying ship's `_splash_damage`, `_splash_damage_radius` (OBJ:881-882, plain attributes, **not mirrored**), its world location (TransformStore), its set; every target's location, `world_radius` (native `world_radius`, beam_geometry), set and the set-frame offset (`frames.offset_between`; native set frames are pushed by `push_set_frame` NC:2343), `is_rock` (mirrored).
- **Hit point:** `ship_death.begin` passes **no** `ship_instances` (SD:115), so `_impact_point` → `_resolve_hit_point(None, …)` returns the caller's fallback at once (CB:108-110): `loc − dir·r_tgt`, normal `None`. Pure arithmetic; no mesh trace. `object_lifetime._expire` is the same (`object_lifetime.py:61`).
- **Damage:** `amount · _splash_weight(r_tgt, radius, d)` (SPL:72-83) → `apply_hit(..., weapon_type="torpedo", splash_radius=radius, bypass_shields=True)`: no shield face, hull + overlapping subsystems at `r_hit = radius`, then the nested chain. With no instance map, the nested hit's `dispatch` draws no shield flash, decal, wear or severance (HF:312-314, 383-384, 438-440).
- **Recursion:** a victim killed by the splash begins its own death inside the same call, with its own splash (unbounded chain, terminated by `_out_of_action`). Measured: 8 splash calls, **0** victims in range in the 64-ship fight (§9), so the recursion's cost is unmeasured in combat.
- Reports as `TORPEDO` (event-inventory F7): E8M2's torpedo test and any weapon-type counter can be tripped by a neighbour's death.

### 4.4 Random draws of one death, in order today

1. `roll_duration`: S1 × 1 (if no lifetime set).
2. `plan`: S1 × (number of blasts), up front.
3. Death script (scope): P only; any `GetRandomPointOnModel` answers from P (OBJ:378-384).
4. `ET_OBJECT_EXPLODING` handlers: S1 only if a handler draws (stock: friendly-fire line picks, MissionLib.py:3970-4100 per rng-map M2).
5. Splash hits: presentation in them draws P; a victim's own death repeats 1-5; their `ET_WEAPON_HIT` handlers may draw S1 (E8M2 `KessoksAttacked`, E2M0 `DoDamageToTheSovereign`).
6. Back in the killing hit: remaining subsystems, `dispatch` (P), `ET_WEAPON_HIT` handlers (S1 if any draws).
7. Later ticks, `cb.death`, per blast `_fire` (DC:245-292): **S1** `rand(10)` damage roll; damaging → **S2** point (`GetRandomPointOnModel` outside a scope: `randrange` over the renderer's surface points when an instance exists, else 3 × `gauss`, OBJ:386-415) then **S1** × 2 blast size, then `AddDamage` (C5, a full hit with its own handlers); non-damaging → P point, P size. Final barrage (DC:295-332) and sounds: P only.

Note for a native port: a damaging blast's **gameplay** point comes from the renderer's surface-point list when the ship has an instance (OBJ:389-404), so a run with instances and one without (the `headless_mission` harness) draw S2 differently (rng-map D3), and a native cascade needs a sim-side point source.

### 4.5 What could move to the boundary (facts, not a choice)

- Already presentation-scoped and order-free with respect to gameplay streams: the death script's draws, every P draw.
- Order-sensitive and handler-visible: `ET_OBJECT_EXPLODING` (R2: before the killing hit's `ET_WEAPON_HIT`; R4: before the object leaves its set; E2M2 before the splash).
- Needed by later same-tick code: `SetDying` (kernels), the S1 position of steps 1-2 (if any other S1 draw happens in the tick between death and boundary: AI does not run in the combat step, but mission handlers on in-step events do, e.g. E2M0 / E8M2 above), the splash if it stays at the blast moment.

---

## 5. Part severance (F7) and `hull_breakup`

`severance-map.md` (written at `5163932f4`, still accurate: neither file changed since, `git log` of PS / `hull_breakup.py`) is the full map. Summary of what a native decision would need:

| | A: appendage (`part_severance`) | B: structure (`hull_breakup`) |
|---|---|---|
| Game-state writes | `_parts_detached.add` → `push_posed_parts` (synchronous, PS:469-472); `SetCondition(0.0)` per subsystem on the part (PS:548): S1-S4 of §2.1, **no** zero crossing, **no** death; hull spheres stop colliding; debris chunk body (S2 tumble, 3 draws) | `parent.severed_parts |= parts` on the **render instance** (native PSC.cc:267); `SetCondition(0.0)` per subsystem in the piece (`hull_breakup.py:232`); debris chunk |
| Timing | synchronous, inside `dispatch` (HF:438-453), so inside the hit and, for C1, inside the K2 walk | worker thread, collected by a per-**frame** poll (`hull_breakup.drain` HL:12848); a result whose inputs moved is dropped and re-queued (wall-clock dependent) |
| Gates today | structural, `absorbed_hull > 0`, **mesh normal**, `persist_decal`, instance map, `damage_eligibility.is_eligible` (K4's set, HF:438-453) | instance, radius > 0.6 GU, not rock, not rigged; native gates in PSJ |
| Inputs a native decision needs | per-ship part damage totals (`_part_damage`, Python); detachable thresholds (`articulation.detachable_for`); the hit point in the **body frame at the sim pose** (today `host_io.world_to_body`, render pose); part boxes (`articulation.part_boxes_for`, from `host_io.model_nodes(iid)`: needs a loaded model); mount → part (`physical_parents.part_for_property`, else `model_nearest_part`); max hull; K4 eligibility (native today) | the wear store (`HullDamageStore`, on the render instance); the structure segmentation (GL-free voxel lib, keyed by model source); dials `params[7]`, `[24]` (renderer globals); `structure_part_at` (instance + model) |
| Without a renderer (the `headless_mission` harness) | never (every gate in severance-map §1.5 fails) | never |
| Measured, 64-ship hidden-window run (§9.2) | 95 `record_hit` calls, 0 severs | 1,161 `after_wear` checks, **3** piece spawns (`_spawn_components`) |

So severance is gameplay that a renderer-less run never makes, and that a run with instances does make: B severed pieces three times in the measured fight, on the frame poll; A attributed 95 hits and severed nothing. The death-routing bypass (a severed critical subsystem leaves the ship alive at 0) stands.

---

## 6. Shield faces: every writer

`_current_shields`, `_max_shields`, `_ramp_fraction` are per-face lists on `ShieldSubsystem` (SS:2086-2093). `_max_shields` is a `HasShieldsField` (SS:2071; NC:1110-1150): rebinding it pushes `has_shields`, in-place writes do not.

| # | Writer | Line | Writes | Watchers updated? | Callers |
|---|---|---|---|---|---|
| W1 | `__init__` | SS:2086-2093 | binds all three lists (current 0, max 0, ramp `None`) | — | construction |
| W2 | `SetMaxShields(face, v)` | SS:2137-2143 | in place: `_current[f] = v` if it was 0.0; `_max[f] = v`; `push_has_shields` | no | `ShipClass` property copy SH:1364-1374 (from SDK hardpoints / `ShieldProperty`); `engine/rocks/rock.py:39` (zero); hardpoint override writer (`engine/appc/hardpoint_override_writer.py:36`, via the property) |
| W3 | `SetCurrentShields(face, v)` (and `SetCurShields`, SS:2159-2161) | SS:2148-2157 | in place `_current[f]` | yes (face + combined) | **SDK** `SetCurShields`: `loadspacehelper.py:257`, `Actions/ShipScriptActions.py:289`, E2M1 :597-607, E6M1 :1772-1784, E6M5 :1802-1805; engine: radiation RAD:159, nebula `engine/appc/nebula_runtime.py:94`, rocks `rock.py:40`, QB restore `engine/quickbattle/sim_restore.py:122`, dev `engine/dev_keybindings.py:94` |
| W4 | `Update` charge tick, ramp refresh | SS:2318-2321 | `_ramp_fraction[f] = cur/max` for every face, once per 0.5 s accumulated | — | `GameLoop.tick` → `_update_ship_subsystems` (LP:137-139) |
| W5 | `Update`, generator offline | SS:2323-2339 | every face → 0.0 | yes | same |
| W6 | `Update`, regen | SS:2340-2361 | `_current[f] += rate·dt`, clamped to max | yes | same |
| W7 | `ApplyDamage(face, amount)` | SS:2362-2410 (writes 2407, 2409) | `_current[f]` | **no** (they catch up at the next W6/W5) | `combat._apply_hit` CB:792 only |

Not writers: god mode reads `GetCurrentShields` without writing (CB:794-797). No engine path pickles or copies a `ShieldSubsystem` (grep of `__setstate__`, `pickle`, `deepcopy` under `engine/appc`; `save_load.py:15-19` stores no ship graph). `_charge_per_second` (W6's rate) is written only by `SetShieldChargePerSecond` (SS:2276-2277). Measured: 4,504 `ApplyDamage` calls in 8,999 ticks (§9).

---

## 7. Unmirrored inputs, re-checked against the current mirror

`damage-map.md` §2.1 / headline 4, item by item (✓ = now mirrored):

| Input | Status at `e2b100f2c` | Evidence |
|---|---|---|
| Shield face charges, max per face, ramp fractions | **not mirrored** (only derived `has_shields`) | §6; NC:1110-1150 |
| Ship `_invincible`, `_hurtable` | **not mirrored** | SH:1816-1831 plain attributes |
| Subsystem `_invincible`, `_critical`, `_targetable` | **not mirrored** | SS:440-447, SS:1257-1261 |
| `god_mode`, `double_player_weapons` cheats | **not mirrored**; only `disable_npc_shields` rides the K2 context, with the player handle only while that cheat is on | NC:4545, 4621-4625 |
| Player identity (for the cheats, camera kick) | only with the NPC-shields cheat on | same |
| Phaser bank `_damage_radius_factor`, `_max_damage`, `_max_damage_distance` | **not mirrored** (DRF read through the C API at the K2 drain) | SS:398-403; effect-queue spec §4.4 |
| Pulse cannon / torpedo tube DRF override | ✓ (launch deferral: K1 reads it for `SPAWN`) | WS:3028, WS:3438 |
| Torpedo `_damage`, `_damage_radius_factor` | **not mirrored** (slots; the SPAWN record carries the launcher's override at fire time) | `projectiles.py:69-72`; `_TORP_FIELDS` NC:2583-2598 |
| `PhaserSystem._power_level` | ✓ (weapon state) | WS:2582 |
| `_condition`, `_max_condition`, `_disabled_percentage`, `_destroyed`, `_radius`, `_position`, parents | ✓ | SS:326-345 |
| `_dying`, `_dead` | ✓ | OBJ:862-863 |
| Hull box, transforms, scale (face choice) | ✓ | damage-map R11 |
| `_splash_damage`, `_splash_damage_radius` | **not mirrored** | OBJ:881-882 |
| `IsDestroyBrokenSystems` | **not mirrored** | SH:1807-1811 |
| Condition-watcher check counts / values | **not mirrored** (weapon charge watchers are: `_watch_checks`, `_watch_value`) | §2.2 |
| Repair queue membership | **not mirrored** | SS:2850 |
| Cutscene flag (decision 7) | **not built** | roadmap §4 H |

Weapon state mirrored `_power_level` and the launchers' DRF; nothing else on the old list moved.

---

## 8. Hit presentation (`hit_feedback.dispatch` F0-F7) after the queue and RNG phases

| Step | HF line | Native or queued counterpart now | What the rest needs |
|---|---|---|---|
| F0 classify | HF:285-293 | none | pure arithmetic on the absorbed amounts and `sub_transition` |
| F1 shield flash | HF:309-339 | **partly**: the K2 drain's native splash (`push_shield_hit`, `native/src/host/host_bindings.cc:697`, shared with the `shield_hit` binding) presents resting contacts in C++ with iid + view offset from the kernel tables | the damage version scales intensity by `absorbed_shields / damage` and gates at `SHIELD_IMPACT_MIN_ABSORBED_FRACTION`; `single_impact`, `shield_radius` (collisions only) |
| F2 hull spark/flash | HF:342-347 → `_hull_impact_visual` HF:518-577 → `hit_vfx.spawn` | none (`hit_vfx._active` is a Python list, `engine/appc/hit_vfx.py:31`, aged in `cb.vfx` HL:1366-1370) | a native owner or a batch at the boundary (as `_k2_present_batch`) |
| F3 smoke | HF:349-354 → `hull_hit_smoke.maybe_emit` | **RNG separated**: rolls draw P (`hull_hit_smoke.py:93-95, 125`), the SDK recipe runs in a scope (`:128`) | can move anywhere without shifting a gameplay roll (decision 12 done); throttle dict keyed by `id()` on game time (`_last_smoke_roll`, `hull_hit_smoke.py:42`) |
| F4 audio | HF:360-361, `_play_audio` HF:456-486 | **RNG separated + game-time throttle** (HF:190-206; P in scope HF:476-477) | same: movable; `_last_dispatch_time` dict (HF:177) |
| F5 camera kick | HF:366-374 | none | player identity |
| F6 decal + plating wear | HF:383-430 | none | renderer stores via `host_io`; game-time throttle `_last_decal_emit` (HF:139); `hull_wear._pending` (`hull_wear.py:66`); `hull_breakup.after_wear` (gameplay B, §5); gated on a mesh normal (61% of hits in the measured run; none without a renderer) |
| F7 severance | HF:438-453 | K4 eligibility only | §5: gameplay, synchronous, renderer-gated |

Since the presentation-RNG phase, **no presentation step in a hit draws S1 or S2** (rng-map superseded; falsifier `tests/integration/test_presentation_rng_falsifier.py`), so F1-F6 can be reordered or deferred without moving a gameplay roll. F7 is the only gameplay inside `dispatch`. Measured cost of `dispatch`: ~48 µs per hit (§9.3), in a run where 97% of hits had an instance and 61% a mesh normal (§9.2), so close to live.

---

## 9. Numbers

### 9.1 How it was run

The host loop under pytest with a **hidden window** (`OPEN_STBC_HOST_HEADLESS=1` only hides it: the renderer, the instances and the mesh trace are live, `host_bindings.cc:1249-1250`), the scene-audit pattern (`tests/host/test_native_combat_scene_audit.py::_run`) with: `DAUNTLESS_COMBAT_SHIPS=64`, `DAUNTLESS_NATIVE_COMBAT=1`, audit off, `DAUNTLESS_MODS_DIR` empty, `OPEN_STBC_HOST_HEADLESS=1`, `_frame_clock` stepped 0.05 s (3 ticks per frame), `seed_every_rng(5)` (`tests/helpers/k3_fight.py:69-81`), `native_combat.reset()`, `hl.run("engine.dev_missions.combat_stress", max_ticks=3000)` = **8,999 ticks**. All instrumentation was `monkeypatch` wrappers in a scratch test outside the repo (no tracked file was edited, so there was nothing to restore): `combat.apply_hit` (caller from the calling frame, nesting, `perf_counter` inclusive/exclusive), `combat._splash_weight` (overlaps with `w > 0` called from `_apply_hit`), `hit_feedback.dispatch`, `DamageableObject.DamageSystem`, `ship_death.begin`, `rocks.death.begin`, `splash_damage.apply`, `FloatRangeWatcher._fire` / `_fire_crossed`, `TGEventManager.AddEvent` (type names from `App.ET_*`), `warp_core_breach.arm`, `subsystem_cascade.schedule`, `internal_blast.queue`, `ShieldSubsystem.ApplyDamage`, and `host_loop._advance_combat` (tick count). None of these names is in a kernel's stand-in guard (`_K2_FUNCTIONS` NC:4168-4185, `_K3_FUNCTIONS` NC:5215-5232; K0 guards `FloatRangeWatcher._update`, which was not wrapped). Command, from the worktree:

```
DMG_FRAMES=3000 DMG_OUT=<scratch>/run1.json uv run pytest -p tests.conftest --rootdir=. -c pyproject.toml <scratch>/test_damage_counts.py -x -q -s
```

Run 2 (`test_damage_cost.py`: only the outermost `apply_hit` and six inner functions timed) and run 3 (`test_damage_live.py`: counters only, for instances, normals, decals, wear and severance) use the same command with their own file. All three fights were the same hit for hit (4,670 hits in 8,999 ticks each), so the counts combine. `<scratch>` is the session scratchpad; the three scratch tests are not in the repo.

Build: `build/python/_dauntless_host.cpython-311-darwin.so` dated 16:58:50 (launch-deferral sources; the presentation-RNG phase changed no native code). Debug. Shared machine; timings indicative. Wall time 170 s (run 1), 194 s (run 2).

### 9.2 Counts (runs 1 and 3, 8,999 ticks)

| Measure | Total | Per tick |
|---|---|---|
| `apply_hit`, all callers | 4,670 | **0.519** |
| … C1 K2 damage pulse | 3,906 | 0.434 |
| … C2 K3 torpedo hit | 640 | 0.071 |
| … C5 `AddDamage` from the death cascade | 116 | 0.013 |
| … C4 collision impact | 8 | 0.001 |
| … C3 grind, C6 death splash, C7 scenery, other | 0 | 0 |
| … nested inside another hit | 0 | 0 |
| Ticks with ≥ 1 hit / ≥ 2 hits / max in one tick | 3,597 / 852 / 14 | 40% / 9.5% of ticks |
| Hits reaching a shield face (`ApplyDamage`) | 4,504 | 96% of hits |
| `ET_WEAPON_HIT` shield-only / hull | 2,876 / 1,794 | 62% / 38% |
| Hits on an immune ship | 0 | — |
| Hits on a ship with a render instance / with a mesh normal (run 3) | 4,551 / 2,862 | 97% / 61% of hits |
| Python `shield_hit` (F1) / decals (F6) / `hull_damage_add` (F6 wear) (run 3) | 3,920 / 1,015 / 191 | |
| Severance A `record_hit` / `sever`; B `after_wear` / piece spawns (run 3) | 95 / 0; 1,161 / 3 | |
| Subsystems overlapped per hit: 0 / 1 / 2 / ≥3 | 3,793 / 496 / 260 / 121 | 81% / 11% / 6% / 3%; mean 0.43, max 14 |
| `DamageSystem` inside hits | 3,809 | 0.82 per hit |
| Watcher updates with checks inside hits / crossings fired | 1,791 / **9** | crossings 0.001 per tick (351 more outside hits: shields, charge, power) |
| Events per hit: exactly 1 / 2 / ≥3 | 4,197 / 345 / 128 | mean 1.16 |
| Events posted inside hits by type | `ET_WEAPON_HIT` 4,670 · `ET_ADD_TO_REPAIR_LIST` 623 · `ET_SUBSYSTEM_DESTROYED` 40 · `ET_SUBSYSTEM_DISABLED` 36 · `ET_AI_CONDITION_CHANGED` 29 (nested from AI condition handlers) · `ET_AI_SYSTEM_STATUS_WATCHER` 9 · `ET_OBJECT_EXPLODING` 8 | |
| Ship deaths (`ship_death.begin`) | 8, all inside a hit | 0.0009 |
| Rock deaths | 0 | |
| Death splash calls / victims | 8 / **0** | |
| Hull zero crossings (cascade scheduled) inside hits | 8 | |
| Breach arms inside / outside hits | 0 / 16 | |
| Internal blasts queued inside / outside hits | 40 / 96 | |

### 9.3 Cost

Run 1 (heavy instrumentation, so an upper bound):

| Scope | Total | Per tick | Per call |
|---|---|---|---|
| `apply_hit` exclusive of nested hits, all callers | 808.9 ms | **0.090 ms** | 173 µs |
| … C1 | 668.6 ms | 0.074 | 171 µs |
| … C2 | 103.3 ms | 0.011 | 161 µs |
| … C5 | 34.8 ms | 0.004 | 300 µs |
| `hit_feedback.dispatch` | 227.9 ms | 0.025 | 49 µs |
| `DamageSystem` (incl. its chain and deaths) | 35.7 ms | 0.004 | 9.4 µs |
| `ET_WEAPON_HIT` post (all handlers) | 77.1 ms | 0.009 | 16.5 µs |
| `ship_death.begin` (8) | 0.34 ms | — | 42 µs |

Run 2, the same fight with lean instrumentation (only `apply_hit` outermost and six inner functions timed; the hit stream was identical: 4,670 hits in 8,999 ticks), scratch `test_damage_cost.py`, same command shape:

| Scope | Calls | Total | Per tick | Per call | Share of `apply_hit` |
|---|---|---|---|---|---|
| `apply_hit`, outermost | 4,670 | 801.9 ms | **0.089 ms** | 172 µs | 100% |
| `_subsystem_world_position` (the splash loop's mount positions) | 36,215 (20.2 per hull hit) | 269.0 ms | 0.030 | 7.4 µs | 34% |
| `hit_feedback.dispatch` | 4,670 | 226.0 ms | 0.025 | 48 µs | 28% |
| `_shield_face_from_hit_point` | 4,504 | 26.4 ms | 0.003 | 5.9 µs | 3% |
| `shields_block` | 4,670 | 8.0 ms | 0.001 | 1.7 µs | 1% |
| `weapon_splash_radius` | 4,670 | 3.1 ms | — | 0.7 µs | <1% |
| rest (derived): `ApplyDamage`, `DamageSystem` chain (~36 ms in run 1), `ET_WEAPON_HIT` construction and post (~77 ms in run 1), player lookup, cheats, immunity, the loop body | — | ~269 ms | 0.030 | ~58 µs | 34% |

(`_iter_subsystems` is a generator: its wrapper timed only creation, 0.4 ms; the iteration is inside "rest".) Reading: the splash loop's per-subsystem world position, for the 81% of hits that overlap nothing, is the single largest piece; then presentation. Both are already native elsewhere (`subsystem_world_position` in `weapon_geometry.h`, the shield splash in the K2 drain). The whole of `apply_hit` is ~0.09 ms per tick in this fight, below the ~0.3 ms bound the roadmap recorded (SIG-168).

---

## 10. Campaign bugs 2 and 3 in the damage path

**Bug 2, `SetConditionPercentage` (decided, not built; grep finds no definition, only a docstring at WS:4051).** Decision: "condition = fraction × max condition, through the same path as any other condition change … posts the same events as weapon damage". In the damage path that means:
- It enters at `SetCondition` (S1-S4 of §2.1), not `DamageSystem`: **no zero-crossing routing and no death**. Scripts that use it to kill (E7M1 `StarbaseCollision` hull 0, E7M2 `DestroyShip` hull 0, Episode 7's tube at 0) would leave a hull at 0 and a live ship, unless the design routes a 0 through death. SDK evidence that BC kills on a hull set to 0: E3M5 `KillGonDev` (§3.7) sets it invincible precisely so it "won't actually blow up".
- "Max condition": `GetConditionPercentage` uses `GetMaxCondition()` (the property's, SS:759-772, 824-830) while `IsDisabled`/`IsDestroyed` use `_max_condition` (SS:1215-1249; native the same, `sensor_detect.cc:128-140`). Scripts read the percentage back (E3M5's clamp compares `GetConditionPercentage() < 0.15`), so a fraction of `GetMaxCondition()` round-trips; the two maxima differ only when a property was edited after load (E1M2's asteroids).
- Once real, it turns four stock handlers into same-tick state changes inside hits (E3M5's clamp, E8M2's cloak kill, E8M2's `MatanDisableHandler` clamp and `DisableMatan`, E2M0's Sovereign, §3.2) and adds `ET_SUBSYSTEM_*` events from inside those handlers (nested dispatch, synchronous today). E8M1's `DisableGalor` stays inert: its handler listens on `ET_SUBSYSTEM_COMPLETELY_DESTROYED`, which is never posted (§3.3).
- `MissionLib.DamageShip` draws S1 per subsystem (`MissionLib.py:5286`, rng-map M1): gameplay draws from inside whatever runs it.

**Bug 3, E3M1 simulation mode (decided, not built; grep finds no `g_bSimulationMode` in `engine/`).** It touches the damage path in three places:
- **A damage scale read by the hit:** "every weapon hit deals 0.1% of its normal damage, from any ship", applied before shields (it must reach shields, subsystems and hull). Which callers count as "weapon": C1 and C2 clearly; **not decided:** the death splash (reports `TORPEDO`, F7), cascade `AddDamage` (`source=None`, `NON_WEAPON`), radiation. Collisions are explicitly unchanged. Not 0 because a zero-damage phaser pulse never reaches `apply_hit` (HL:1264) and E3M1's `AmagonHit` counts phaser hits.
- **Player invincibility ignored:** E3M1's `MakePlayerInvincible` and `PlayerCollisionHandler` re-arm. Under today's `IsImmuneToDamage`, this is what lets the player take collision damage. The other drill ships keep `SetInvincible(TRUE)`; under ours they take **no** damage, so their drill knock-outs (`ConditionSystemBelow` hull 0.5 / 0.25, §3.7) cannot happen, with or without 0.1% (**inferred**; not run). The decision's own check ("the drill's outcome … is unaffected by 0.1% damage") depends on §3.7's semantics.
- **Where the flag lives:** a load-time AST listener on the mission global (decision text). A native damage step reads it as a flag (decision 8 shape), not through a handler.

---

## 11. Shape implied

Facts above that a native damage design has to decide on. Not chosen here.

1. **What the immunity flags mean.** Today `invincible` = `not hurtable` = no damage (SH:1828-1831). The SDK uses `invincible` as "cannot die" in at least five missions (§3.7) and the measured fight never exercised either (0 immune hits). Decision 8 makes these flags the native interface, so their semantics (no damage / no death / per-subsystem / a floor such as E3M5's 15%) are part of the kernel contract, and they decide whether E8M2, E3M1 and E2M0's damage beats can happen at all.
2. **Where side effects run: in the kernel, or as queued records.** The chain is S1 (mirror field, already native) plus five Python effects (§2.1). Measured, they are rare: 0.82 `DamageSystem` per hit, 9 watcher crossings, 76 threshold events, 623 repair enqueues, 8 deaths in 8,999 ticks (§9.2). The precedent for watchers is K0's `WATCH` (commit, then deliver against the checks registered at delivery); the precedent for writes is the logged write. Repair enqueue and zero-crossing queues have no same-tick reader except `cb.damage_sys`, whose order relative to K2 already makes them next-tick for C1 (§2.1 S4-S5).
3. **When a handler's write takes effect.** BC enqueues events (§3.6); ours runs handlers inside the hit. Six stock handlers change what a later same-tick hit reads (§3.2), all but E8M1's shield `TurnOn` through the `SetConditionPercentage` stub (bug 2) or an immunity flag; E2M2's partner invincibility is ordered against the death splash **inside** one `begin` (SD:108 then SD:113). The design decides whether `ET_WEAPON_HIT` / `ET_SUBSYSTEM_*` / `ET_OBJECT_EXPLODING` become queue kinds (decision 9), and whether E2M2-style "react to a death before its splash" survives.
4. **Death: what stays at the blast moment.** In-tick gameplay is `SetDying`, two S1 roll families and the splash (§4.1); the splash hit point is pure arithmetic with no mesh (§4.3), so it can be native; the death script and `ET_OBJECT_EXPLODING` cannot be native and are order-sensitive. The cascade's damaging point currently depends on the renderer's surface points (§4.4).
5. **Shield faces as mirrored state.** Seven writers, one SDK entry (§6); `ApplyDamage` does not update watchers (W7), so a native write keeps that property for free. The K2 pulse would be the first kernel to read face charges.
6. **Severance and the subsystem-event set.** F7 is gameplay inside presentation, renderer-gated (§5); three subsystem events missions listen for are never posted (§3.3). Whether native damage posts `COMPLETELY_DESTROYED` / `DAMAGED` / `STATE_CHANGED`, and whether a severed critical subsystem routes through death, are open.

---

## 12. Not established

- When BC's event pump runs relative to its damage tick, and whether all event kinds share one queue (clean-room wall).
- BC's real semantics of `SetInvincible` / `SetHurtable` (the binary's damage path was not read; §3.7 is script intent).
- Whether a ship whose death script calls `SetLifeTime` takes its death splash twice (§4.1 step 6; not run).
- The cost of a death-splash chain in combat (no victim was in range in the measured fight).
- Severance A's frequency with a Bird of Prey in range of fire (the measured fight attributed 95 hits but severed nothing); a visible-window run's cost (the run hid the window; render-side costs were not measured).
- Whether the 26-mission sweep exercises any of the §3.2 handlers (not checked).
- Handler helpers deeper than one call that were not read by hand (§3.1).
