# Launch-script cache (workstream F): code map

> *Built 2026-11-02 as the launch deferral (spec `2026-11-02-combat-launch-deferral-design.md` §10): launches go through `SPAWN` at the boundary; this map is the pre-build snapshot.*

> **Superseded in part (2026-11-03, fire control native only):** the Python launch path (`_spawn_torpedo`, `_spawn_projectile`, `_launch_reads`, `_defer_spawn`), the launch-patch check and the launch-time bake (`_baked_offset`) are deleted. A launch the kernel cannot make is a counted no-fire, not a hand-back. A tube with no ammo type launches slot 0's script from the cache, and a stale cache is re-pushed at the next K1 entry. See `docs/superpowers/specs/2026-11-03-fire-control-native-only-design.md` §6.



Worktree `native-combat-k3`, branch `ws/combat-launch-cache` at `c2b0534c1`. Read-only research, 2026-11-02.
Abbreviations: **NC** `engine/appc/native_combat.py`, **WS** `engine/appc/weapon_subsystems.py`, **PR** `engine/appc/projectiles.py`, **EQ** `engine/appc/effect_queue.py`, **SS** `engine/appc/subsystems.py`, **EV** `engine/appc/events.py`, **SDK** `sdk/Build/scripts/`.
Unmarked claims were read in the code. **inferred** = not verified by running or by a test.

---

## 1. The launch path today

### 1.1 K1 hands back the record

- `run_k1` opens `effect_queue.session()` and runs `_run_k1` (NC:3314-3343). Inside the tick's scope (`sim.weapons` + `sim.combat`) the session opens nothing new (EQ:163-174).
- `FIRE`: `bank._fire_effect(walk.obj(rec[2]), walk.offset, _k1_decision(bank, rec[3], walk))` (NC:3405-3408). The binding has already applied the record's logged writes before `next()` returns (NC:3318-3322 docstring).
- `_k1_decision` (NC:3226-3235): pulse (kind 6) → `(world_dir xyz, target_used, module)`; tube (kind 8) → `(target_used,)`.
- `_k1_pulse_module` (NC:3238-3257) calls `importlib.import_module(script)` **again on every pulse FIRE** (a `sys.modules` hit). A failed import raises and abandons the session.
- `FIRE_DUMB`: `walk.obj(rec[1]).FireDumb(0, 1)` (NC:3413-3414). The ASK `group_step` can also call `weapon.FireDumb(0, 1)` (NC:3306). `Weapon.FireDumb` checks the warp-in hold, then calls `self.Fire(target=None, offset=None)` (WS:1231-1252). That runs Python's whole decide plus effect.
- K1 header: the records left are FIRE for a tube or a cannon, FIRE_DUMB and ASK (`native/src/combat/include/dauntless/combat/k1_fire_control.h:103`). The decision shape for tubes and pulses is at `k1_fire_control.h:272-276`.

### 1.2 TorpedoTube effect (WS:3494-3523)

1. Target stamps. `_target`/`_target_offset` are set to the target and the walk's offset, or both cleared on the dumb path (WS:3495-3505).
2. Stamps, in Python, not logged by the kernel. They are `_firing=True`, `now=_game_time()`, `_num_ready -= 1`, `_last_fire_time`, the parent's `_last_system_fire_time` and `_start_slot_cooldown(now)` (WS:3506-3512).
3. `_spawn_torpedo()` (WS:3596-3645):
   - **Ammo debit.** For a finite type, `parent.GetCurrentAmmoType().AddAvailable(-1)` (WS:3614-3619).
   - **Script name.** It is `ammo.GetTorpedoScript()` (the selected ammo type) (WS:3625-3626). The fallback is `parent.GetProperty().GetTorpedoScript(0)` (WS:3627-3631). The hardpoint authors it as `Torpedoes.SetTorpedoScript(slot, "Tactical.Projectiles.<X>")` on the TorpedoSystemProperty. `ships.py:_resolve_torpedo_ammo` (around ships.py:1953-2010) seeds each ammo type's script and reads the module's `GetName`/`GetLaunchSpeed`/`GetPowerCost`.
   - `mod = _resolve_projectile_module(script_name)` (WS:374-421) is cached per script name in `_projectile_modules` (WS:371). On **any** import exception it substitutes `Tactical.Projectiles.PhotonTorpedo` (WS:366) and announces once. The cache is cleared on mission swap by `_reset_projectile_module_cache` (WS:424-433), which also marks the pulse params stale (`NC:1901`).
   - `torp = _spawn_projectile(self, mod, drf_override=self.GetDamageRadiusFactor())` (WS:3639-3640).
   - `_broadcast_torpedo_fired(torp)` (WS:3645). In scope it is queued as `TORPEDO_FIRED(tube, torp)` (WS:3813-3817).
4. `_broadcast_weapon_fired(target)` → queued `WEAPON_FIRED` (WS:3519, 699-705). `_broadcast_ammo_consumed_if_player()` → queued `AMMO_CONSUMED`, with the player gate read at delivery (WS:3520, 3525-3536). The order is BC's audited TORPEDO_FIRED → WEAPON_FIRED → AMMO_CONSUMED.
5. `_firing = False` (WS:3522).

### 1.3 PulseWeapon effect (WS:2990-3015)

- The decision was made natively. K1 had the pulse params `(module_ok, launch_speed, lifetime)` cached per script, which is ruling P6 (`WS:437-475`, `NC:1873-1925`): **a per-script projectile cache already exists for the pulse solve.**
- Python's own `_fire_decide` (WS:2941-2988, used with the switch off, for ASKs and for FIRE_DUMB) reads the module by `prop.GetModuleName()`. A hardpoint authors it as `Cannon.SetModuleName("Tactical.Projectiles.<X>")`. Python's decide imports the module, picks the target (weapon's, else ship's) and solves the led direction (`_solve_pulse_launch_direction` WS:509-570, which reads the module's `GetLaunchSpeed`/`GetLifetime`). **No fallback bolt**: a module that fails to import means no fire.
- Effect:
  - `torp = _spawn_projectile(self, decision[2], drf_override=self.GetDamageRadiusFactor(), world_dir=world_dir)` (WS:2997-2999).
  - Then `torp._damage *= self.GetDamageScale()` (power-setting scale) (WS:3000-3003). This runs **after `register`**, so `ET_TORPEDO_ENTERED_SET` handlers see the unscaled damage (also noted in `k3-k4-map.md` A9).
  - Charge drain `_charge_level -= _shot_cost()` and the cooldown (WS:3008-3009).
  - `_post_weapon_fired(self, decision[1])`, queued (WS:3013-3014). No `ET_TORPEDO_FIRED` (tubes only).

### 1.4 `_spawn_projectile(emitter, mod, drf_override, world_dir)` (WS:575-696): the shared spawn

| Step | Line | Reads |
|---|---|---|
| `torp = Torpedo()` | WS:599 | `Torpedo.__init__` (PR:99-158). `TGObject.__init__` takes an obj id from a global counter (`engine/core/ids.py:215-217`). `ObjectClass.__init__` allocates a TransformStore slot `_xform` and tries a native Object row (`engine/appc/objects.py:91-125`). The flight defaults are `_ttl` 60, `_guidance_lifetime/_initial` 4.0, `_max_angular_accel` 0.125, damage 0 and empty visuals (PR:107-158). |
| `torp._source_ship = emitter._climb_to_ship()` | WS:600-601 | launcher → ship (SS:967) |
| `SetTranslateXYZ(emitter._emitter_world_position())` | WS:602-603 | ship pose plus the emitter mount, through `subsystem_world_position` (SS:32-55, step-memoised) |
| **`mod.Create(torp)`** | WS:605 | the script (§2) |
| DRF override if the launcher's `GetDamageRadiusFactor() > 0` | WS:613-614 | launcher (SS:904) |
| `launch_speed = mod.GetLaunchSpeed()` (missing → 0.0) | WS:616 | module getter, per launch |
| direction: pulse = the kernel's `world_dir`; tube = `_emitter_forward_world(emitter, ship, skew=True)` | WS:618-624, 483-506 | tube `GetDirection`, `IsSkewFire`, `GetRight` and ship `GetWorldRotation`. Tubes are **never** aimed at the target. |
| `_velocity = unit(dir) * launch_speed + ship.GetVelocityTG()` | WS:625-636 | ship velocity |
| homing: `_target_ship = emitter._target` if alive, then `SetTargetOffset(emitter._target_offset)` | WS:644-650 | launcher stamps and the target's `IsDead`. `SetTargetOffset` (PR:230-243) **bakes the offset against the target's pose at launch** (`_bake_offset` PR:1080-1094 → `articulation.part_transform_point`). |
| **`register(torp)`** | WS:652 | §1.5 |
| launch sound: `mod.GetLaunchSound()` → `TGSoundManager.GetSound` → `AttachToNode(torp.GetNode())` → `Play()` | WS:654-694 | module getter, per launch. **Played at once, mid-walk, not queued** (fire-events spec §4.2 left it with the spawn for F). |

### 1.5 `register` and K3's torpedo table

- `register` (PR:528-533) sets `_id = _next_id` (a monotonic module counter), then `_active.append(torp)`, then `_join_source_set`.
- `_ActiveList.append` (PR:357-361) adds the row to the incoming-torpedo scan (`_scan_add`) and calls `native_combat.torpedo_row_add(t)` (NC:2513-2523) → `_torp_put` (NC:2500-2510). `_torp_put` calls `_h.combat_torp_add(xform index, generation)`, then **pushes every `_TORP_FIELDS` value the Python object holds at that moment** (NC:2358-2373).
- After that, every write to a `TorpedoField` descriptor (`PR:85-97`, `NC:2465-2488`) or to the `_velocity`/`_source_ship`/`_containing_set` properties (PR:270-320, `push_torpedo_field` NC:2491-2497) pushes into the row.
- **What K3 reads per torpedo**: position (from the TransformStore slot), `_age`, `_ttl`, `_guidance_lifetime`, `_guidance_initial`, `_max_angular_accel`, `_velocity`, `_target_offset`, `_last_seen_target_pos`, `_last_target_vel`, `_target_ship`, `_source_ship`, `_containing_set`, `_mount_key`, `_baked_offset` (NC:2358-2373).
- **Not in the row:** `_damage`, `_damage_radius_factor` and every visual field. Python reads them:
  - `combat.apply_hit(ship, torpedo._damage, ..., hardpoint_weapon=torpedo)` after K3's hit list (`engine/host_loop.py:1355-1360`);
  - the render payload walks `projectiles._active` every frame (`engine/host_loop.py:1538-1600`).
- `_join_source_set` (PR:536-571): `kset.AddObjectToSet(torp, "Torpedo %d")` (SetName, `_containing_set`, `_fire("added")`, ObjectGroup membership; `engine/appc/sets.py:200-235`), then `_post_set_transition(..., entered=True)` (PR:574-592). That is `ET_TORPEDO_ENTERED_SET` through `TGEventManager.AddEvent`, which **dispatches synchronously** (EV:802-845). It is **not** an effect-queue kind (EQ:95-98), so its handlers run mid-walk today:
  - `Conditions/ConditionIncomingTorps.py:228-255` `EnteredSet` → `CheckTorpedo`, which reads the torpedo's position, velocity and target;
  - `Maelstrom/Episode8/E8M2/E8M2.py:1643-1667` `TorpedoEnterSet`, which reads `GetTargetID` and **calls `SetLifetime(10)` on the torpedo** when locked on Matan.

### 1.6 Random draws on the path

- **None** in K1's effect Python, `_spawn_projectile`, `Torpedo.__init__`, `register`, or any of the 17 projectile scripts that exist (§2, §3). A grep of PR, `objects.py`, `sets.py` and `audio/tg_sound.py` finds `random` only in `GetRandomPointOnModel`/`RandomOrientation`, which are off this path.
- **Reached through events.** Episode7's `TorpedoFired` handler draws `App.g_kSystemWrapper.GetRandomNumber(10)` (`SDK/Maelstrom/Episode7/Episode7.py:110`). It is now delivered at the tick boundary (fire-events spec §10, "Gameplay consequence").
  - Side finding, **inferred**: that handler first compares `pPlayer.GetObjID() == pTorpedo.GetParentID()` (Episode7.py:94). No `GetParentID` exists in `engine/` (grep), so a Torpedo answers a truthy `_Stub`, the compare is False, and the phased-plasma beat may never fire. It is not in `docs/stub_heatmap.md`. Worth a heatmap or a probe check.
- `ConditionIncomingTorps` and E8M2's set-entry handlers draw nothing (read).

### 1.7 State read, by source

- **Launcher:**
  - tube: `_target`, `_target_offset`, `GetDamageRadiusFactor`, `GetDirection`/`IsSkewFire`/`GetRight`, the mount position, the parent's ammo type and its script;
  - pulse: the module name, `GetDamageScale` (power setting) and `_shot_cost`.
- **Ship:** `_climb_to_ship`, world rotation, velocity, containing set; the player check for AMMO_CONSUMED at delivery.
- **Target:** `IsDead`, and its pose at launch for the baked offset (PR:1080-1094). The pulse lead is solved before the effect (native).
- **Script:** nothing. No stock or mod `Create` reads the torpedo, the launcher, the ship or the game (§2, §3).

---

## 2. Stock projectile scripts (`SDK/Tactical/Projectiles/`, 15 modules)

How hardpoints name them: `TorpedoSystemProperty.SetTorpedoScript(slot, "Tactical.Projectiles.<X>")` and `PulseWeaponProperty.SetModuleName("Tactical.Projectiles.<X>")`. Grep counts over `SDK/ships/Hardpoints`:
- torpedo: PhotonTorpedo 8, QuantumTorpedo 5, KlingonTorpedo 4, Antimatter 2, Cardassian 2, Positron 2, PhotonTorpedo2 1, PhasedPlasma 1, PositronTorpedo2 1;
- pulse: CardassianDisruptor 20, RomulanCannon 4, Disruptor 3, FusionBolt 2, PulseDisruptor 2, KessokDisruptor 1.

Nothing else names one: `MissionLib.FireTorpFromPlacement` (MissionLib.py:3215-3337, `App.Torpedo_Create`) has no SDK callers (k3-k4-map A9). `Multiplayer/SpeciesToTorp.py` is multiplayer only. E3M1, E7M1 and Episode7 only import modules to read `GetName()`.

Method: an AST walk of each file (scratch script, `python3 -I`, ast only), checked against a manual read of `PhotonTorpedo.py` and `PulseDisruptor.py`.

| Module | Model | Create calls on `pTorp` | Verdict |
|---|---|---|---|
| AntimatterTorpedo, PhasedPlasma, PositronTorpedo, PositronTorpedo2 | `CreateTorpedoModel` (3 colours: core, glow, flare) | SetDamage, SetDamageRadiusFactor, SetGuidanceLifetime, SetMaxAngularAccel, SetNetType | **PURE** |
| CardassianTorpedo, KlingonTorpedo, PhotonTorpedo, PhotonTorpedo2, QuantumTorpedo | `CreateTorpedoModel` (2 colours) | same | **PURE** |
| CardassianDisruptor, Disruptor, FusionBolt, KessokDisruptor, PulseDisruptor, RomulanCannon | `CreateDisruptorModel` | same + **SetLifetime** | **PURE** |

All 15 are PURE:
- No `if`/loop/`try`, no `global`, no random, no event, no direct sound, no game-state read.
- Every argument is a literal, a local `App.TGColorA()` filled by `SetRGBA(literals)`, a zero-argument module getter returning a constant, or a `Multiplayer.SpeciesToTorp` constant.
- Every module-level getter (`GetLaunchSpeed`, `GetLaunchSound`, `GetPowerCost`, `GetName`, `GetDamage`, `GetGuidanceLifetime`, `GetMaxAngularAccel`, `GetLifetime`) is a single `return <constant>`.

Argument dependence: `Create(pTorp)` takes only the torpedo, and **reads nothing from it** (no `pTorp.Get*`). The position and source set before `Create` are unused, so the result is identical for every launch.

Purity caveats for the cache:
- **(a)** `Create` imports `Multiplayer.SpeciesToTorp` (a side effect on the first call only; the harness provides the `Multiplayer` package, `tools/mission_harness.py:860-863`, `tests/conftest.py:870-873`).
- **(b)** It allocates fresh `TGColorA` objects per launch and the Torpedo stores the **references** (`_core_color`, `_glow_color`, `_flares_color`, `_shell_color`, `_bolt_core_color`, PR:160-198). `TGColorA` is a plain class, not a `TGObject` (`App.py:1336`), so a cache allocates no obj ids. Sharing one colour object between torpedoes is safe only while nothing mutates it; the render only reads it through `_color_tuple` (**inferred**, no writer found).
- **(c)** `SetNetType` is a no-op (PR:254).
- **(d)** Torpedo scripts don't call `SetLifetime`, so `_ttl` stays at the engine default of 60 (PR:110). Pulse scripts set it.

## 3. Installed mods

Both mod trees are byte-identical (`diff -rq`).

| Mod | Projectile modules named by its hardpoints | Present? | Verdict |
|---|---|---|---|
| LC Intrepid Pack | torpedo `ZZ_VoyPhoton`, `ZZ_Tricobalt` | yes, **`.pyc` only** (`scripts/Tactical/Projectiles/`) | **PURE (both)** |
| DCMPv2 | torpedo: 7 `blackelm*` modules (Thunderer, dummy, klingon2, type1/2/3 quantum, type6); pulse: 8 (`BlackElmDefiantPulse`, `IronheartPulse`, `blackelmIronheartPulse`, `blackelmThundPulse`, `blackelmbrelpulsedisruptor`, `blackelmdefiantpulse`, `blackelmsaopaulopulse`, `blackelmtype1microquantum`) | **no**: they need Elminster's Common Weapons Pack, which is not installed (memory `project_mod_missing_dependency_weapons`) | n/a. Torpedo ones launch the stock **PhotonTorpedo** (WS:400-418, pure); pulse ones never fire (WS:2955-2963 / `module_ok` 0) |

How the `.pyc` files were classified:
- `engine/py15.load_tree` lifts straight-line 1.5 bytecode to a Python 3 AST in memory (`engine/py15/__init__.py:26-60`, `lift.py:360`). It refuses jumps, classes and nested or variadic defs (`Py15Unsupported`, which leads to the photon fallback).
- **Both lift**, so neither has conditional logic by construction.
- I walked the lifted ASTs in memory, printing only call names, function names and booleans; no text or values were written. Each `Create(1 arg)` calls only `App.TGColorA`, `SetRGBA` on locals, `CreateTorpedoModel`, SetDamage, SetDamageRadiusFactor, SetGuidanceLifetime, **SetLifetime**, SetMaxAngularAccel, SetNetType and its own zero-arg getters. It imports `Multiplayer.SpeciesToTorp`, and the constant it reads exists there.
- No `Get*` on the argument, no random, no state hints. Every getter is a single constant return, and every argument is constant-shaped.
- No mod Autoload or Custom script references `Tactical.Projectiles` (grep).

**Totals: stock 15 PURE, 0 IMPURE; mods 2 PURE, 0 IMPURE; 15 named mod modules absent, which falls back to the photon (torpedo) or to no fire (pulse).**

---

## 4. What a cached launch needs

### 4.1 Per projectile type (once per resolved module; key = script name → resolved module object, so a missing torpedo module shares the photon's record)

- `damage`, `damage_radius_factor`, `guidance_lifetime` (also `guidance_initial`), `max_angular_accel`, `ttl`, with `None` meaning keep the default of 60.
- `launch_speed`, `launch_sound` (name), and for pulses `lifetime` (P6 already holds `launch_speed`/`lifetime`).
- Render: `is_disruptor`, plus the torpedo-model 14-tuple (3 textures, 3 RGBA, 8 sizes and count) **or** the disruptor 4-tuple (2 RGBA, length, width).
- Optional: `net_type` (unused).
- **Recording** = run `Create` on a recording `Torpedo` once and read these fields back. Pure is decided per module (AST check or an allow-list), not assumed.
- **Invalidation** = `_reset_projectile_module_cache` (WS:424) / `mark_pulse_stale` (NC:1901), plus a guard that `mod.Create` and the getters are still the recorded functions (the K1 override-guard pattern; **inferred** need).

### 4.2 Per launch (C++ can compute all of it; the kernel already has mounts, ship pose and velocity)

| Value | How |
|---|---|
| spawn position | the emitter mount in world space |
| velocity | `unit(dir) · launch_speed + ship velocity`. `dir`: tube Direction (+0.033 Right if skew) × ship R; pulse = the kernel's led `world_dir` |
| source ship, containing set | the firing ship and its set |
| target ship, target offset, baked offset | `_target_ship` and `_target_offset` from the launcher stamps if the target is alive; `_baked_offset` from the target pose at launch (PR:1080-1094) |
| DRF override | `launcher.GetDamageRadiusFactor() > 0` replaces the type's value |
| damage | pulse: × `GetDamageScale()` (power setting) |
| age, last-seen | 0 / None |

Plus the launcher stamps, which become logged writes:
- tube: `_num_ready`, `_last_fire_time`, parent `_last_system_fire_time`, the slot cooldown, `_target`/`_target_offset`, the finite ammo debit (`AddAvailable(-1)`);
- pulse: the charge drain and the cooldown.

### 4.3 Where the Python `Torpedo` must still exist

It is:
- the **source** of `ET_TORPEDO_FIRED` (queued) and `ET_TORPEDO_ENTERED_SET` (synchronous today);
- a **set member** (`CT_TORPEDO` lists: `AI/Preprocessors.py` incoming-damage sum via `GetDamage`/`GetTargetID`, `EvadeTorps`, `ConditionIncomingTorps`, about 20 AI/Bridge/mission files that cast it);
- the **sound node** for its launch sound;
- the **render** source (`_active` per frame);
- the `hardpoint_weapon` passed to `apply_hit`;
- the object E8M2's handler mutates (`SetLifetime`).

The natural place is a new effect-queue kind, e.g. `SPAWN(launcher, record handle, …)`, delivered in emission order. Its delivery builds the `Torpedo` from the record (no `Create`), `register`s it (that creates the K3 row from the record's values), posts `ENTERED_SET` and plays the sound. The already-queued `TORPEDO_FIRED`/`WEAPON_FIRED`/`AMMO_CONSUMED` must follow it.

Consequences to rule on (all **inferred**):
1. **K3 timing.** `cb.projectiles` runs before `cb.held_weapons` in the step (remaining-fallbacks-map §4 "K1 FIRE tube" row), so a torpedo spawned at the boundary is first flown next tick, the same as today. Its position and velocity must be computed at fire time (in C++), not at delivery, or a ship that moved after its weapons step would shift the spawn.
2. **`ET_TORPEDO_ENTERED_SET`** moves from mid-walk to the boundary. ConditionIncomingTorps and E8M2 then react one walk later (decision 9 territory).
3. **Ordering of ids.** `TGObject` obj ids and `projectiles._next_id` are allocated at delivery instead of mid-walk. That only matters if something else allocates ids inside the walk.
4. The pulse damage scale should be applied **before** the set-entry event, which fixes the ordering quirk in §1.3.
5. Switch-off and differential parity: the Python reference arm still runs `Create`, so the differential compares record-built torpedoes field by field.

A thinner alternative that keeps the record: C++ resolves the per-launch values and Python only runs `Torpedo()` + `register` mid-walk. That removes `Create`, the imports and the getter calls, but not the lock.

---

## 5. Frequencies and cost (what is measured)

| Source | Scene | Tube launches / tick | Pulse launches / tick |
|---|---|---|---|
| perf register **SIG-173** (`docs/reference/engine/perf-register.md:434`) | 64 ships, headless, 8,999 ticks | 0.064 | 0.039. K1 records after fire events: 0.103 per tick, all launches |
| fire-events spec §1 table (`2026-11-02-combat-fire-events-design.md`) | same | 0.061 | 0.038 |
| remaining-fallbacks-map §2.3 R3 (`docs/reference/engine/native-combat/remaining-fallbacks-map.md`) | `combat_stress` 64 ships, 4,499 ticks | 245 (0.054) | 166 (0.037) |
| k3-k4-map A10 | 64 ships, cProfile | ~89 torpedoes in flight per tick; expiries about 0.11 per tick | — |

- **Python cost per launch: not measured.** The only per-record timing (remaining-fallbacks-map §2.4) is K1 `FIRE` at 14.81 µs on average, which is 98.8% beam sustains. The roadmap's workstream B lists "actual firing (projectile creation, events, sounds)" as an unmeasured split.
- Derived arithmetic only: at 0.10 launches per tick, every 100 µs per launch is 0.01 ms per tick. So F's value is **taking K1's last mid-walk Python off the lock** (roadmap I), not raw speed.
- `sim.effects` delivery is 0.069 ms per tick for about 1.1 entries per tick (SIG-174), a rough bound on what a queued SPAWN adds per entry (**inferred**).
