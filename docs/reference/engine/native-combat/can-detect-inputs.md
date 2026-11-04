> Snapshot map written 2026-10-31 at commit 7c6ece598 for the native combat step (spec docs/superpowers/specs/2026-10-30-native-combat-step-design.md). Line numbers drift; re-check them against the code before relying on one.

# `can_detect` port map: native combat step K1 / §7.6 items 2-4

Worktree: `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-visibility` at `7c6ece598` (branch perf/native-combat docs head).
Read-only survey, done 2026-10-31. All line numbers are for this tree. Interpreter: CPython **3.11.15** (`.venv`).
Abbreviations: `sd` = `engine/appc/sensor_detection.py`, `subs` = `engine/appc/subsystems.py`, `occ` = `engine/appc/sensor_occlusion.py`.

---

## 0. TL;DR of hazards (details in §8)

1. **`math.dist` is not `sqrt(dx²+dy²+dz²)`.** The radial profile radius comes from `math.dist` (`engine/systems/profile.py:91`). In CPython 3.11 that is the compensated `vector_norm` algorithm. I measured 37,158 of 200,000 random 3-D pairs (±2e5 GU) where it differs from the naive sqrt. The C++ must port `math_dist_impl` + `vector_norm` verbatim from CPython v3.11.15 `Modules/mathmodule.c`. This matters only where profile rows differ, which is the Vesuvi 116366–130634 GU band and the Belaruz 124385–133304 GU band. Those bands are exactly where the E3M2 Vesuvi4 / Belaruz1 regions sit (anchors at r = 122000 and 128000).
2. **The occlusion pair cache is keyed on game time, not on positions.** It is shared with a Python caller that is not `can_detect` (`sensor_contacts._scan_blocked` calls `occ.blocked` directly). A cached answer survives later ship moves within the same game time, every combat step of a multi-tick frame, and 0-tick frames. The native side must own the same cache with the same signature, or callers will diverge.
3. **`_probe_reach` recursion, `_walking_probes` global, and `probes()` pruning `_probe_ids` on read.** These are side effects inside the predicate.
4. **The step_memo answer table is keyed by `(id(observer), id(target))`.** It memoises only calls with **no** keyword arguments. Its clearing points are listed in §7.1.
5. **Latch writes happen only on the nebula-gate path.** The occlusion branch returns before the latch is read or written.
6. **Python `min`/`max` semantics.** They return the *first* argument unless the second is strictly less/greater, which matters for NaN and ties. `GetConditionPercentage`, the cloak bubble and `concealment_at` all use them.
7. **Exception swallowing differs per caller.** The same predicate failure means "detectable" for `_target_undetectable` and for torpedoes, and propagates everywhere else.

---

## 1. Call graph (file:line)

```
can_detect(observer, target, *, dist_sq_gu=None, apply_concealment=True, concealment=None)   sd:377
├─ memo path (sd:461-469): if step_memo.active() and dist_sq_gu is None and apply_concealment and concealment is None
│     key=(id(observer), id(target)); _answers.get(key); miss -> _answers[key] = _can_detect(..., None, True, None)
│     _answers = step_memo.table()   sd:477
└─ _can_detect(observer, target, *, dist_sq_gu, apply_concealment, concealment)   sd:480
   1. _cloak_subsystem(target)                       sd:188  -> getattr(type(target),"GetCloakingSubsystem",None)(target); except->None
        ShipClass.GetCloakingSubsystem               engine/appc/ships.py:1147 (returns self._cloaking_subsystem)
      cloaked = cloak is not None and bool(cloak.IsCloaked())     sd:494
        CloakingSubsystem.IsCloaked                  subs:3078 (1 iff _cloak_state == CLOAK_CLOAKED)
      if cloaked and not ENHANCED_SENSOR_CONTEST: return False    sd:495-496
   2. r = effective_sensor_range(observer)           sd:227
        implements(ship,"GetSensorSubsystem")        engine/core/ids.py:148 (class-MRO probe, cached per class)
        ship.GetSensorSubsystem()                    ships.py:1069
        sensors None -> _sensorless_range()          sd:217 -> sensor_dials.get("sensorless_range_gu")  (2000.0)
        _is_offline(sensors) -> 0.0                  subs:137
            sub.IsDisabled()                         subs:1168
            sub.IsDestroyed()                        subs:1195
            getattr(sub,"_radiation_out",False) is True       subs:152
            parent=_parent_subsystem; parent._radiation_out is True   subs:154-156
            implements(sub,"GetParentShip") -> ship_death._out_of_action(sub.GetParentShip())
                 subs:650 GetParentShip (self._parent_ship or _climb_to_ship())
                 engine/appc/ship_death.py:58 _out_of_action: IsDying() (objects.py:867) or IsDead() (objects.py:893)
        base = sensors.GetBaseSensorRange()          subs:1478
        base <= 0.0 -> _sensorless_range()
        return base * sensors.GetConditionPercentage() * sensors.GetNormalPowerPercentage()
            GetConditionPercentage                   subs:779 -> GetMaxCondition subs:714 (property template first)
            GetNormalPowerPercentage                 subs:1341 (self._power_factor)
      if r <= 0.0: return False                      sd:499
      if cloaked: r = min(sensor_dials.get("cloak_bubble_cap_gu"), CLOAK_DETECTION_BASE_GU + r * CLOAK_RANGE_FACTOR)   sd:506-507
   3. if ENHANCED_SENSOR_CONTEST: if occ.blocked(observer, target): return _probe_reach(observer, target, apply_concealment, concealment)   sd:513-523
        occ.blocked                                  occ:132  (cache: occ:93 _major_rocks, occ:117 _segment_hits, occ:127 _contains)
            contact_index.ships_in(pset)             engine/appc/contact_index.py:90
            rocks.rock.effective_radius              engine/rocks/rock.py:59
            subs._get_xyz                            subs:3300
   4. if apply_concealment:                          sd:526-541
        conceal = concealment_at(target) if concealment is None else concealment
            concealment_at                           sd:290
              _local_concealment(target)             sd:254
                 implements(ship,"GetContainingSet"), ship.GetContainingSet()   objects.py:315
                 implements(ship,"GetWorldLocation"), ship.GetWorldLocation()   objects.py:344 (TransformStore)
                 _game_time()                        sd:209 -> App.g_kTimerManager.GetGameTime()
                 contact_index.nebulae_in(pSet)      contact_index.py:112
                 App.MetaNebula_Cast(obj)            engine/appc/nebula.py:113
                 neb.GetNebulaSpheres()              nebula.py:32 (list copy)
                 neb.GetFbmDials()                   nebula.py:83
                 neb.GetSeed()                       nebula.py:87 (lazy, cached in neb._seed)
                 nebula_density.density(...)         engine/appc/nebula_density.py:80
                    _sphere_union_falloff :64, fbm :45, _vnoise :26, _hash13 :16, _fract :12, _saturate :60
              profile.locate(target)                 engine/systems/profile.py:78
                 frames.system_position(obj)         engine/systems/frames.py:197
                    frame_of_object -> frame_of(containing_set(obj))   frames.py:55, :34, :48
                       region_hooks.is_mapped(pSet)  engine/systems/region_hooks.py:54
                       resolve.anchor_of(name)       engine/systems/resolve.py:120
                       resolve.system_of(name)       resolve.py:103
                    frames._xyz(obj) = GetWorldLocation   frames.py:180
                 resolve.map_of(system)              resolve.py:63 (lru_cache'd _index)
                 star = first body with orbits is None
                 math.dist(pos[1:], tuple(star.position_gu))
              profile.evaluate(prof, r).sensors      profile.py:47
              _profile_concealment_cap()             sd:305 -> dev_mode.is_enabled() ? dev_nebula_dials.conceal_cap() : PROFILE_CONCEALMENT_CAP
        concealment = conceal
        thresh = LOCK_BREAK_T - (HYSTERESIS if _latched(observer, target) else 0.0)   _latched sd:150
        if conceal >= thresh: _set_latched(observer,target,True) (sd:161); return _probe_reach(observer, target, apply_concealment, concealment)
        _set_latched(observer, target, False)
        r = r * (1.0 - CONCEAL_K * conceal)
   5. if dist_sq_gu is None: _get_xyz(observer), _get_xyz(target); dist_sq_gu = dx*dx + dy*dy + dz*dz   sd:543-547
      if dist_sq_gu <= (r * r): return True          sd:548
   6. return _beyond_range_reach(observer, target, cloaked) or _probe_reach(observer, target, apply_concealment, concealment)   sd:552-553
        _beyond_range_reach                          sd:556
           _same_set                                 sd:348
           sensors = observer.GetSensorSubsystem()
           boosted = implements(sensors,"GetNormalPowerPercentage") and sensors.GetNormalPowerPercentage() > sensor_dials.get("overboost_threshold")
           known = implements(sensors,"IsObjectKnown") and bool(sensors.IsObjectKnown(target))   subs:1514
           return not jammed(observer, target)       sd:355
              contact_index.nebulae_in(observer set); neb.IsObjectInNebula(observer) or neb.IsObjectInNebula(target)   nebula.py:45
        _probe_reach                                 sd:595
           _walking_probes guard, _same_set
           _live_probes(observer) -> sensors.probes()   sd:586, subs:1490 (prunes _probe_ids!)
              engine/core/ids.py:11 get_object_by_id
           if apply_concealment and concealment is None: concealment = concealment_at(target)
           for probe: probe.GetContainingSet() is oset and can_detect(probe, target, apply_concealment=..., concealment=...)   <- RECURSION (one level)
```

Related functions that are **not** part of `can_detect`'s body but share its pieces:
- `in_reach` (sd:654): unshrunk range, then `_beyond_range_reach(observer, target, is_hidden_by_cloak(target))`, then `_probe_in_reach` (sd:632). It writes no latch.
- `is_hidden_by_cloak` (sd:315).
- `jammed` (sd:355).
- `clear_undetectable_player_lock` (sd:673).
- `reset_concealment_state` (sd:176).

---

## 2. Callers of `can_detect` across `engine/`

| # | Group | Site | Call (exact kwargs) | Context / cadence | Memo active? | Exception handling |
|---|---|---|---|---|---|---|
| 1 | Weapons, per-tick chokepoint | `engine/host_loop.py:1199` (`_advance_combat_step`, scope `cb.phasers`) | `can_detect(ship, target)` | Per firing bank per sim tick, only when `flush_dwell is None` (bank `IsFiring()`). Runs after the `_is_offline(sys_)`/`IsOn()` and target-dead checks, and before the `_same_set` cross-set guard (host_loop.py:1211). | **yes** (memoised) | propagates |
| 2 | Weapons, held-fire pump | `engine/host_loop.py:1014` → `_target_undetectable(sys_, held)` → `engine/appc/weapon_subsystems.py:1058-1059` | `can_detect(ship, target)` with `ship = weapon_system.GetParentShip()` (hasattr-guarded) | `_pump_held_weapons` (host_loop.py:984), scope `cb.held_weapons`. Per system with `_fire_held` and not `_pump_self_managed`, in getter order Phaser, Pulse, Tractor, Torpedo (host_loop.py:999). It is asked after the `_is_offline`/`IsOn` and held-target-dead checks, and before `_can_engage`. | **yes** | **any exception → False** ("detectable", weapon_subsystems.py:1060-1061). `target None → False`, `ship None → False`. |
| 3 | Weapons, `StartFiring` | `engine/appc/weapon_subsystems.py:1414` (`WeaponSystem.StartFiring`) → `_target_undetectable(self, target)` | same as #2 | Called by the AI (FireScript etc.), player fire keys and SDK scripts. The order is `IsOn`, `_is_offline`, `_cloak_blocks_fire`, `_dewarp_blocks_fire`, `_target_undetectable`, `_can_engage`, then `update_weapons(0.0)` (weapon_subsystems.py:1428). | normally **no** (AI tick runs outside `combat_step`). It is memoised only if an event handler inside the combat step calls `StartFiring`. | → False on exception |
| 4 | Torpedo guidance | `engine/appc/projectiles.py:1012` and `:1016` in `_target_visible(torpedo, target)` (projectiles.py:988), called from the guide step at projectiles.py:1084 | Same frame: `can_detect(src, target)`. Different region of the same system: `can_detect(src, target, dist_sq_gu=dx*dx + dy*dy + dz*dz)`, where `o = src.GetWorldLocation()`, `p = frames.shifted(target.GetWorldLocation(), off)`, `dx = p.x - o.x` etc. | Per live guided torpedo per sim tick (inside `projectiles.update_all`, scope `cb.projectiles`). Skipped if `off is None`, the target `IsDead()`, or speed < 1e-6 (projectiles.py:1073-1080). `src = torpedo._source_ship`; `None` → True. | **yes** for the same-frame branch. The `dist_sq_gu` branch is never memoised. | **any exception → True** (projectiles.py:1018-1019) |
| 5 | AI candidate filter | `engine/appc/ai_sensor_gate.py:113` (`_gated_active`, the wrapper of `ObjectGroup.GetActiveObjectTupleInSet`) | `can_detect(observer, obj)` for each obj in the SDK result | Only while `_observing_ship` is published, i.e. inside the SDK `SelectTarget.FindGoodTarget` (wrapped ai_sensor_gate.py:174-185, plus the `_best_detectable_candidate` fallback) or `StarbaseAttack.GetTargets` (ai_sensor_gate.py:195). Runs in the AI tick (`GameLoop.tick` → `tick_all_ai`). | no | propagates into SDK |
| 6 | AI firing gate | `engine/appc/ai_sensor_gate.py:222` (`FireScript.TargetVisible` replacement) | `can_detect(ship, pTarget)`; `ship None → visible` | FireScript preprocessor, ~0.2 s cadence, AI tick | no | propagates |
| 7 | Target list / radar | `engine/appc/perception.py:230` (`perceived_by`) | `can_detect(observer, ship, dist_sq_gu=dist_sq, apply_concealment=sd.ENHANCED_SENSOR_CONTEST, concealment=conceal)`. `dist_sq` comes from `contact_index.ship_positions_in` (TransformStore bulk read) minus `_get_xyz(observer)`. `conceal = sd.concealment_at(ship) if (apply_conceal or known) else None`. It is only called when `range_gu > 0.0` (short-circuit). | Per render **frame**, all ships in the player's set, from `host_loop._pump_contacts` (host_loop.py:9651), called at host_loop.py:11992 in the UI section **before** the sim advance. It also runs paused (not sim-gated). `perception.py:309` (wrapper) has tests only. | no | propagates |
| 8 | Player lock guard | `sd:714` (`clear_undetectable_player_lock`) ← `engine/host_loop.py:12028` | `can_detect(player, target)`. Skipped for `Planet`/`PlacementObject` targets. | Per render frame (UI section, before the sim advance). Calls `player.SetTarget(None)` on False. | no | propagates |
| 9 | Sensor continuity | `engine/appc/sensor_contacts.py:202` (`is_concealed`) | `can_detect(player, obj)` after `in_reach` and `is_hidden_by_cloak` | `_continuity` (1 s sweep) and `_commit_due` (scan commits), from `sensor_contacts.tick` ← host_loop.py:12544 (sim-gated, after combat) | no | **exception → False** (sensor_contacts.py:203-205) |
| 10 | Passive identification commit | `engine/appc/sensor_contacts.py:398` (`_commit_due`) | `can_detect(player, obj)` | each `sensor_contacts.tick` | no | propagates |
| 11 | Identification sweep | `engine/appc/sensor_contacts.py:427` (`_sweep`) | `can_detect(player, obj)` | 1 s sweep (`sweep_period_s`) | no | propagates |
| 12 | SDK `IsObjectVisible` | `subs:1673` (`SensorSubsystem.IsObjectVisible`) | `can_detect(ship, obj)` after its own same-set gate | SDK callers: TacticalInterfaceHandlers.py:797, :867, E1M2.py:6694, E3M2.py:2558/2627/2696/2765 (SDK at `/Users/mward/Documents/Star Trek Bridge Commander/sdk/Build/scripts`) | depends on caller | propagates |
| 13 | Internal probe walk | `sd:623` (`_probe_reach`) | `can_detect(probe, target, apply_concealment=apply_concealment, concealment=concealment)`. `concealment` is never None when `apply_concealment` is True, so this call is **never memoised**. | recursion, one level | never | propagates (the `finally` resets `_walking_probes`) |

No caller uses the `sensor_detection.can_detect` attribute form. `ai_sensor_gate` binds the name at import (ai_sensor_gate.py:44), so tests patch `ai_sensor_gate.can_detect`. `ai_driver.py:1132` and the others are comments only.

Direct callers of the **pieces** (Python-side, will read native-adjacent state):
- `concealment_at`: perception.py:198 and `sensor_media.medium_unknown` (sensor_media.py:45; exception → 0.0).
- `effective_sensor_range`: perception.py:181, sensor_contacts.py:363 and :404, subs:1608 (`GetSensorRange`, which feeds `IsObjectNear`/`IsObjectFar` bands).
- `in_reach`: sensor_contacts.py:198.
- `is_hidden_by_cloak`: sensor_contacts.py:200, sensor_media.py:61, science_scan_labels.py:89.
- `occ.blocked`: **`sensor_contacts._scan_blocked` (sensor_contacts.py:375)**, which shares the occlusion pair cache.
- `occ.begin_tick`: sensor_contacts.py:446.

---

## 3. Every input read

Legend for the "Changes" column: **T** = per tick (or per frame), **R** = rarely (events, damage, mission setup), **C** = constant per process, **D** = developer dial.

| # | Owner | Exact attribute / function | Type | Write sites | In-place mutation? | Changes |
|---|---|---|---|---|---|---|
| 1 | `sd` module | `ENHANCED_SENSOR_CONTEST` | bool const `True` (sd:108) | none in prod; tests monkeypatch | – | C |
| 2 | `sd` module | `CONCEAL_K=0.9`, `LOCK_BREAK_T=0.28`, `HYSTERESIS=0.08`, `PROFILE_LOCK_MARGIN=0.01`, `PROFILE_CONCEALMENT_CAP = LOCK_BREAK_T - HYSTERESIS - PROFILE_LOCK_MARGIN` (== 0.19 exactly; verified `0.28-0.08-0.01 == 0.19`), `CLOAK_RANGE_FACTOR=0.005`, `CLOAK_DETECTION_BASE_GU=5.0` | float | none | – | C |
| 3 | `sd` module | `_broken` latch | `WeakKeyDictionary[observer → WeakSet[target]]` (sd:147) | `_set_latched` sd:161 (from sd:532, sd:539); `reset_concealment_state` sd:185 ← host_loop.py:4947 (`_reset_sensor_state`, called at host_loop.py:4755 and mission_change.py:220), conftest:1689 | **yes, in place** | T |
| 4 | `sd` module | `_walking_probes` | bool global (sd:59) | sd:618/629, sd:642/651 | yes | transient |
| 5 | `sd` module | `_answers` memo | dict (step_memo table) | sd:466; cleared by `step_memo.forget()` | yes | T |
| 6 | `sensor_dials._dials` | `get("sensorless_range_gu")` (2000.0), `get("cloak_bubble_cap_gu")` (30.0), `get("overboost_threshold")` (1.2), `get("min_blocker_radius_gu")` (2.0, in occ) | float via `float(_dials[name])` | `reset()` sensor_dials.py:56 (conftest:1697 only, **not** on mission swap); `_step` sensor_dials.py:80 (dev `/ L O` keys, `round(...,4)`, clamped) | dict replaced (rebinding, not in place) | D |
| 7 | `dev_mode` | `is_enabled()` | bool | parsed once at boot | – | C |
| 8 | `dev_nebula_dials._dials` | `conceal_cap()` → `_dials["conceal_cap"]` (default 0.19, dev_nebula_dials.py:73) | float | `_step` (dev_nebula_dials.py:141-143: `round(c+dir*step,4)` clamped to `[0, LOCK_BREAK_T-0.001]`) | rebinding | D (only read when `dev_mode.is_enabled()`) |
| 9 | `occ` module | `_enabled` (default True) | bool | `set_enabled` occ:58 (Developer Options → Combat → "Sensor Occlusion"), `reset_enabled` occ:63 (tests) | – | D |
| 10 | `occ` module | `_tick_time` | float or None | `begin_tick` occ:71 ← sensor_contacts.tick (sensor_contacts.py:446) ← host_loop.py:12544 with `App.g_kUtopiaModule.GetGameTime()`; `reset` occ:79 (mission swap host_loop.py:4956, conftest:1717) | – | T (per sim frame, after combat) |
| 11 | `occ` module | `_pair_cache`, `_rock_cache` | `WeakKeyDictionary[SetClass → (sig, …)]` | occ:113, occ:147, occ:166; `reset` | yes | T |
| 12 | `App.g_kTimerManager` | TWO clocks, not one. `sensor_detection._game_time()` (sd:212) calls `App.g_kTimerManager.GetGameTime()`, which does NOT exist on `TGTimerManager` (AttributeError, swallowed), so it always returns 0.0 and the MetaNebula drift is frozen at t=0 today (a latent bug, deliberately copied by the native port, left for Mark). The occlusion cache reads `g_kUtopiaModule.GetGameTime()` (occ:88), which returns `g_kTimerManager.get_time()` (App.py:1161) | float `TGTimerManager._time` | `TGTimerManager.tick`: `self._time += delta` (engine/appc/timers.py:~88) ← `GameLoop.tick` (engine/core/loop.py:36, `TICK_DELTA`) | – | T |
| 13 | target | `type(target).GetCloakingSubsystem` existence (class attr); `target._cloaking_subsystem` | object/None | ships.py:55 (init None), ships.py:1171 `SetCloakingSubsystem` (SetupProperties) | – | R |
| 14 | cloak subsystem | `_cloak_state` (via `IsCloaked`) | int enum | subs:3038 StartCloaking, :3057 StopCloaking, :3066 InstantCloak, :3072 InstantDecloak, :3155 `_force_decloak`, :3211/:3215 `Update` (transition completes) | – | R (an event-driven state machine ticked by `CloakingSubsystem.Update`) |
| 15 | observer | `implements(observer,"GetSensorSubsystem")` (class-level), `observer._sensor_subsystem` | object/None | ships.py:37 init None, ships.py:1070 `SetSensorSubsystem` | – | R |
| 16 | sensor sub | `IsDisabled()`: reads `_max_condition`, `_disabled_percentage`, `_condition`. ⚠️ It uses **`self._max_condition`, not `GetMaxCondition()`**. | float | `_max_condition`: subs:324 init 1.0, subs:738 SetMaxCondition. `_disabled_percentage`: subs:403 init 0.25, subs:1137 setter ← ships.py:1318/1589/1643 | – | R |
| 17 | sensor sub | `IsDestroyed()`: `_destroyed`, `_max_condition`, `_condition` | bool/float | `_destroyed`: subs:419, subs:1206 `SetDestroyed` ← objects.py:1089 | – | R |
| 18 | sensor sub | `_condition` | float | subs:323 init 1.0; subs:698 `SetCondition` (`max(0.0, float(value))`; combat damage, repair `Repair` subs:807, missions); subs:737 SetMaxCondition seeding | – | R (each hit/repair tick) |
| 19 | sensor sub | `_radiation_out`; `_parent_subsystem._radiation_out`. Checked with `is True` (identity). | bool | engine/appc/radiation.py:81 (False), :103 (True); init subs:321. `_parent_subsystem` set by `AddChildSubsystem` subs:1119 | – | R (16 Hz radiation logic) |
| 20 | sensor sub | `GetParentShip()` → `_parent_ship` or `_climb_to_ship()` | ShipClass | `SetParentShip`, `_attach_subsystem` | – | R |
| 21 | observer ship | `IsDying()` = `_dying or _life_time < DYING_THRESHOLD(1.0e6)` (objects.py:867-871); `IsDead()` = `_dead` | bool/float | `_dying`: objects.py:890 SetDying (ship_death.begin). `_life_time`: objects.py SetLifeTime (default `LIFETIME_UNSET=1.0e30`), decremented by `object_lifetime.advance`. `_dead`: objects.py:896 | – | R/T (`_life_time` ticks once finite) |
| 22 | sensor sub | `_base_sensor_range` (`GetBaseSensorRange`) | float | subs:1466 init 0.0; subs:1479 setter ← **ships.py:1330** (SetupProperties from `SensorProperty`), **engine/appc/nebula_runtime.py:160** (`base * _clamp01(density)` on MetaNebula entry), **nebula_runtime.py:175** (restore on exit/no-nebula) | – | R |
| 23 | sensor sub | `GetConditionPercentage()` = `max(0.0, min(1.0, self._condition / mx))`, `mx = GetMaxCondition()`; `mx <= 0` → 0.0 | float | `GetMaxCondition` (subs:714) returns `float(prop.GetMaxCondition())` if the property exists, does not raise, and is > 0.0, else `_max_condition`. The property is a **shared per-class template**, mutable by missions (e.g. E1M2 `pHull.GetProperty().SetMaxCondition(300)`). | – | R |
| 24 | sensor sub | `_power_factor` (`GetNormalPowerPercentage`) | float; `FrozenField` descriptor (subs:1276), plain instance-dict read | subs:1303 init 1.0; subs:1369 (0.0, not wanting power), :1377 (1.0, free consumer), :1391 (`received / base`, direct siphon), :1403 `_record_draw` (`received / base`). Callers: PowerSubsystem update subs:2661, passive_power.py:197 (`_record_draw`) / :199 | – | T (frozen consumers keep their value) |
| 25 | sensor sub | `_known_objects` (`IsObjectKnown(obj)` = `obj.GetObjID() in _known_objects`, any exception → 0) | `set[int]` | `AddKnownObject` subs:1528 ← sensor_identification.py:59 `_identify_one` ← sensor_contacts.py:393/399, subs:1593 `ForceObjectIdentified` (player-only); `RemoveKnownObject` subs:1535 ← sensor_contacts.py:243 (`_lose_track`, after the 5.0 s continuity window), :500 (`on_exited_set`); `.clear()` sensor_contacts.py:497 (player left the set) | **yes, in place** | R. Player-only in practice; AI sensors are never populated. |
| 26 | sensor sub | `_probe_ids` (via `probes()`) | `list[int]` | subs:1488 `AddProbe` ← SDK `Actions/ShipScriptActions.py:500`; **subs:1505 rebound by `probes()` itself (prune on read)** | rebinding | R |
| 27 | any object | `GetObjID()` | int | id registry | – | C per object |
| 28 | observer/target/probe | `_containing_set` (`GetContainingSet`, objects.py:315), compared with `is` | SetClass/None | sets.py:196 (AddObjectToSet), sets.py:317 (`_clear_containing_set` from RemoveObjectFromSet / DeleteObjectFromSet), debris_chunk.py:76/171 | – | R |
| 29 | positions | `_get_xyz(obj)` (subs:3300): first implemented of `GetTranslate`, `GetWorldLocation`, `GetTranslation`, `GetPosition`, `GetTranslateXYZ`, each returning `(float(t.x), float(t.y), float(t.z))`; per-accessor exceptions are logged and fall through; last resort `_position`; else `(0,0,0)`. For every ObjectClass this is `GetTranslate` → `get_store().get_position(*self._xform)` (objects.py:340). `GetWorldLocation` (objects.py:344) reads the same store slot. | double ×3 (TransformStore is double, native/src/transforms/include/dauntless/transform_store.h:44) | `SetTranslateXYZ`/motion: ship_motion, tractors, warp, physics, `projectiles` (torpedoes) | – | T |
| 30 | `contact_index` | `_buckets[pSet]` (ships in insertion order; occlusion iterates it), `_nebula_buckets[pSet]` (`nebulae_in`) | list | `on_added` contact_index.py:55 ← sets.py:208; `on_removed` :72 ← sets.py:273, :291; `reset` :118 ← host_loop.py:4655, conftest:1680; `forget_set` :124 (mission_change) | yes | R |
| 31 | MetaNebula | `_spheres` (`GetNebulaSpheres` returns a list copy) | `list[(x,y,z,r)]` floats | nebula.py:30 `AddNebulaSphere` (SDK `Systems/*_S.py`: Multi5_S 13 calls, Multi6_S 4, Vesuvi4_S 1, Belaruz1_S 1) | yes (append) | R (set setup) |
| 32 | MetaNebula | `_fbm` = `(freq, gain, floor)`, default `DEFAULT_FBM_DIALS = (0.02, 1.5, 0.30)` (nebula.py:12) | tuple | `SetFbmDials` nebula.py:74. **No callers in engine or SDK.** | – | C in practice |
| 33 | MetaNebula | `_seed` (`GetSeed`, lazily `seed_for(first sphere centre)` and cached; `(0,0,0)`-based if called before any sphere) | tuple | nebula.py:93-99 | write-once | C after first read |
| 34 | `App.MetaNebula_Cast` | `isinstance(obj, MetaNebula)` (nebula.py:113) | – | – | – | – |
| 35 | Nebula (jam) | `neb.IsObjectInNebula(obj)` (nebula.py:45): `obj.GetWorldLocation()`, sphere test `dx*dx+dy*dy+dz*dz <= rad*rad`. ⚠️ `jammed` does **not** cast to MetaNebula. A plain `App.Nebula` (App.py:382) would vend a truthy `_Stub`, so it would read as jammed. Nothing creates a plain Nebula today. | int 0/1 | – | – | – |
| 36 | profile | `region_hooks.is_mapped(pSet)` = `getattr(pSet, _FLAG_ATTR, False)` | bool | `mark_mapped` region_hooks.py:58 (apply_map) | attr on set | R (once per set) |
| 37 | profile | `pSet.GetName()` → `resolve.anchor_of(name)`, `resolve.system_of(name)` | str → tuple / str | `_index()` is an `functools.lru_cache`; `reset_cache` is tests-only. ⚠️ QuickBattle renames sets in place ("…Dupe"), which makes the name lookup miss, so the set reads as unmapped. | – | C per process |
| 38 | profile | `resolve.map_of(system)` → `SystemMap.profile` (`Profile(rows, color, full_concealment)`), `SystemMap.bodies[*].orbits`, `.position_gu` | dataclasses from JSON `engine/systems/maps/*.json` (33 maps) | `map._profile_from_json` map.py:143 (no float coercion on `ProfileRow(**row)`: JSON ints stay ints); loaded once per process | **mutating is forbidden by contract** (map_of docstring) | C |
| 39 | profile | `Profile.full_concealment` | float: 0.392642591908 in all 33 maps | – | – | C |
| 40 | rocks (occ) | `isinstance(s, RockClass)` (engine/rocks/rock.py:15); `effective_radius(s)` = `float(GetBaseRadius())`, or if ≤ 0 `float(GetHull().GetRadius())` (or 0.0), times `float(GetScale())` (objects.py:203 `_radius`, :209 `_scale`) | float | SetRadius / SetScale (missions, e.g. E1M2 `SetScale(3..8.5)`), `maybe_become_rock` (class swap) | – | R |
| 41 | `step_memo` | `active()` → `_depth > 0` | int | `combat_step()` engine/core/step_memo.py:40 | – | T |

### Positions used, by step
- Range test: `_get_xyz(observer)` / `_get_xyz(target)` (the GetTranslate path).
- Concealment: `target.GetWorldLocation()`, then `.x .y .z`.
- Profile: `frames._xyz(target)` = `GetWorldLocation()` plus the frame anchor.
- Occlusion: `_get_xyz` for observer, target and each rock. Rock positions are frozen in `_rock_cache` per signature.
- Jam: `GetWorldLocation()` of observer and target.
- `perceived_by`'s `dist_sq` uses `TransformStore.get_positions` for targets and `_get_xyz` for the observer. These are the same doubles.

---

## 4. Floating-point expressions, verbatim (operand order matters; Python left-associative)

### 4.1 `_can_detect` (sd:480-553)
```python
cloaked = cloak is not None and bool(cloak.IsCloaked())
r = effective_sensor_range(observer)
if r <= 0.0: return False                      # NaN r does NOT return here
if cloaked:
    r = min(sensor_dials.get("cloak_bubble_cap_gu"),
            CLOAK_DETECTION_BASE_GU + r * CLOAK_RANGE_FACTOR)   # min(cap, 5.0 + (r*0.005))
...
thresh = LOCK_BREAK_T - (HYSTERESIS if _latched(observer, target) else 0.0)   # 0.28-0.08 = 0.2 (repr 0.2) or 0.28-0.0
if conceal >= thresh: ...                      # NaN -> False -> unlatch branch
r = r * (1.0 - CONCEAL_K * conceal)            # r * (1.0 - (0.9*conceal))
dx, dy, dz = tx - ox, ty - oy, tz - oz         # target minus observer
dist_sq_gu = dx * dx + dy * dy + dz * dz       # ((dx*dx)+(dy*dy))+(dz*dz)
if dist_sq_gu <= (r * r): return True          # NaN -> False
```
Python `min(a, b)` returns `b` iff `b < a`, else `a`. So `min(cap, x)` returns `x` iff `x < cap`. With x NaN it returns cap.

### 4.2 `effective_sensor_range` (sd:251) and `GetConditionPercentage` (subs:785)
```python
return base * sensors.GetConditionPercentage() * sensors.GetNormalPowerPercentage()   # (base*cond)*power
# GetConditionPercentage:
mx = self.GetMaxCondition()
if mx <= 0: return 0.0
return max(0.0, min(1.0, self._condition / mx))
```
Python semantics are `m = (q if q < 1.0 else 1.0); res = (m if m > 0.0 else 0.0)`. NaN gives `min(1.0, NaN) = 1.0`, then 1.0. `-0.0` gives `max(0.0, -0.0) = 0.0`.
`base <= 0.0` → sensorless dial (NaN base proceeds to the multiply).
`IsDisabled`: `threshold = self._disabled_percentage * self._max_condition; return 1 if self._condition <= threshold else 0`, guarded by `if self._max_condition <= 0.0: return 0`.
`IsDestroyed`: `self._destroyed` or `(self._max_condition > 0.0 and self._condition <= 0.0)`.

### 4.3 `concealment_at` (sd:295-302)
```python
local = _local_concealment(ship)
found = _profile.locate(ship)
if found is None or found[0] is None: return local
prof, r = found
profile_term = _profile.evaluate(prof, r).sensors * prof.full_concealment
return max(local, min(profile_term, _profile_concealment_cap()))
```
Python semantics: `min(pt, cap)` returns `cap` iff `cap < pt`, else `pt`; `max(local, m)` returns `m` iff `m > local`, else `local`. NaN case: for pt = NaN, `cap < NaN` is False, so `min` returns **NaN**; then `NaN > local` is False, so `max` returns `local`. Both steps must be mirrored exactly.

### 4.4 `_local_concealment` (sd:274-287)
```python
t = _game_time()                    # float(App.g_kTimerManager.GetGameTime()); exception -> 0.0
best = 0.0
for obj in contact_index.nebulae_in(pSet):      # pSet = TARGET's containing set
    neb = App.MetaNebula_Cast(obj); if neb is None: continue
    spheres = neb.GetNebulaSpheres()
    freq, gain, floor = neb.GetFbmDials()
    d = _nd.density(loc.x, loc.y, loc.z, spheres, neb.GetSeed(), freq, gain, floor, drift_t=t * 0.01)
    if d > best: best = d           # strict; NaN never wins
return best
```

### 4.5 `nebula_density` (verbatim, engine/appc/nebula_density.py)
```python
def _fract(x): return x - math.floor(x)          # math.floor returns a Python INT; x - int -> float
def _hash13(x, y, z):                             # x,y,z are Python ints (from _vnoise) or floats
    px, py, pz = _fract(x * 0.1031), _fract(y * 0.1031), _fract(z * 0.1031)
    d = px * (pz + 31.32) + py * (py + 31.32) + pz * (px + 31.32)
    px, py, pz = px + d, py + d, pz + d
    return _fract((px + py) * pz)
def _vnoise(x, y, z):
    ix, iy, iz = math.floor(x), math.floor(y), math.floor(z)     # ints
    fx, fy, fz = x - ix, y - iy, z - iz
    fx = fx * fx * (3.0 - 2.0 * fx)               # (fx*fx)*(3.0-(2.0*fx))
    fy = fy * fy * (3.0 - 2.0 * fy)
    fz = fz * fz * (3.0 - 2.0 * fz)
    def h(dx, dy, dz): return _hash13(ix + dx, iy + dy, iz + dz)  # int + int
    n00 = h(0,0,0) + (h(1,0,0) - h(0,0,0)) * fx
    n10 = h(0,1,0) + (h(1,1,0) - h(0,1,0)) * fx
    n01 = h(0,0,1) + (h(1,0,1) - h(0,0,1)) * fx
    n11 = h(0,1,1) + (h(1,1,1) - h(0,1,1)) * fx
    n0 = n00 + (n10 - n00) * fy
    n1 = n01 + (n11 - n01) * fy
    return n0 + (n1 - n0) * fz
def fbm(x, y, z):
    a, s = 0.5, 0.0
    for _ in range(5):
        s += a * _vnoise(x, y, z)
        x, y, z = x * 2.02, y * 2.02, z * 2.02
        a *= 0.5
    return s
def seed_for(cx, cy, cz): return (cx * 0.013 + 11.7, cy * 0.013 + 23.1, cz * 0.013 + 47.3)
def _saturate(v): return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)    # NaN passes through
def _sphere_union_falloff(px, py, pz, spheres):
    best = 0.0
    for (cx, cy, cz, r) in spheres:
        if r <= 0.0: continue
        dx, dy, dz = px - cx, py - cy, pz - cz
        d = math.sqrt(dx * dx + dy * dy + dz * dz)       # sqrt (correctly rounded)
        t = _saturate((r - d) / (0.3 * r))
        f = t * t * (3.0 - 2.0 * t)
        if f > best: best = f
    return best
def density(px, py, pz, spheres, seed, freq, gain, density_floor, drift_t):
    bound = _sphere_union_falloff(px, py, pz, spheres)
    if bound <= 0.0: return 0.0
    sx, sy, sz = seed
    n = fbm(px * freq + sx + drift_t, py * freq + sy, pz * freq + sz)   # ((px*freq)+sx)+drift_t
    return bound * _saturate(n * gain - density_floor)
```
Notes for C++:
- `math.floor` returns an int. Every int↔float mix is exact while |value| < 2^53, so `floor()` in double is equivalent here.
- `math.floor(NaN/inf)` **raises** in Python. Ruling R5: native raises ValueError on any non-finite fbm input inside a sphere so the wrapper falls back to Python and raises as today (the earlier "unreachable" claim was wrong).
- `h(0,0,0)` is evaluated 4 times in Python (pure function, so no difference).
- Pinned goldens: tests/unit/test_nebula_density.py:39-50 (`fbm(1.5,2.5,3.5)=0.43832942533588964`, `_hash13(1,2,3)=0.17883083253718723`, `density(...)=0.20645526505610945`), within tolerance 1e-9 (not bitwise).

### 4.6 `profile.locate` / `evaluate` (engine/systems/profile.py)
```python
# locate (:78)
pos = frames.system_position(obj)       # (f.key, x + f.anchor_gu[0], y + f.anchor_gu[1], z + f.anchor_gu[2]); x,y,z = GetWorldLocation()
if pos is None or pos[0][0] != "system": return None
m = resolve.map_of(pos[0][1]); if m is None: return None
star = next((b for b in m.bodies if b.orbits is None), None); if star is None: return None
return m.profile, math.dist(pos[1:], tuple(star.position_gu))      # <-- CPython vector_norm, NOT naive sqrt
# frame anchor: Frame(("system", system), tuple(float(c) for c in anchor))  frames.py:43
# evaluate (:47)
if profile is None or not profile.rows: return CLEAR      # all-zero Sample
rows = profile.rows
if r <= rows[0].distance_gu: return _sample(rows[0])
for a, b in zip(rows, rows[1:]):
    if r == b.distance_gu: return _sample(b)              # exact breakpoint: stored value
    if r <= b.distance_gu:
        span = b.distance_gu - a.distance_gu
        t = 0.0 if span <= 0.0 else (r - a.distance_gu) / span
        return Sample(**{c: getattr(a, c) + (getattr(b, c) - getattr(a, c)) * t for c in COLUMNS})   # a + (b-a)*t
return _sample(rows[-1])                                  # also the NaN-r path
```
- Profile data: every map has `full_concealment = 0.392642591908` and one star at `[0,0,0]` (checked: vesuvi, belaruz, tauceti).
- Row counts: 31 maps have 3 rows; belaruz has 8; vesuvi has 15.
- The `sensors` column is all 0 except in vesuvi and belaruz.
  - Vesuvi: 0.3 everywhere, rising to 1.0 at 123500 between 116366 and 130634.
  - Belaruz: 0 except 1.0 at 128844.695986, between 124385.500214 and 133303.891758.
- Equal-valued neighbouring rows interpolate to exactly the stored value (`a + 0.0*t`), so `math.dist` exactness matters only inside those two bands.
- JSON values may be Python **ints** (e.g. `0`). `int*float` is exact.

### 4.7 Occlusion (occ:117-167), verbatim
```python
def _segment_hits(ax, ay, az, bx, by, bz, cx, cy, cz, r):
    dx, dy, dz = bx - ax, by - ay, bz - az
    seg2 = dx * dx + dy * dy + dz * dz
    px, py, pz = cx - ax, cy - ay, cz - az
    t = 0.0 if seg2 <= 1e-12 else (px * dx + py * dy + pz * dz) / seg2
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)          # NaN passes
    qx, qy, qz = px - t * dx, py - t * dy, pz - t * dz
    return qx * qx + qy * qy + qz * qz < r * r                # strict
def _contains(x, y, z, cx, cy, cz, r):
    dx, dy, dz = x - cx, y - cy, z - cz
    return dx * dx + dy * dy + dz * dz < r * r                # strict
# blocked: for rock in rocks (contact_index order): skip rock is observer/target;
#   skip if _contains(observer) or _contains(target); if _segment_hits: True, break
# _major_rocks: r = effective_radius(s) = base * float(rock.GetScale()); keep if r >= min_r
```

### 4.8 Beyond range / jam / probes
- `sensors.GetNormalPowerPercentage() > sensor_dials.get("overboost_threshold")` is strict.
- `IsObjectInNebula`: `dx * dx + dy * dy + dz * dz <= rad * rad` (inclusive), with `dx = px - cx` (object minus sphere centre).
- `in_reach` (not in `can_detect`): `if dx * dx + dy * dy + dz * dz <= r * r`.

### 4.9 Torpedo cross-frame `dist_sq` (projectiles.py:1013-1016)
```python
o = src.GetWorldLocation(); p = _shifted(target.GetWorldLocation(), off)   # TGPoint3(p.x + 1.0*off[0], ...)
dx, dy, dz = p.x - o.x, p.y - o.y, p.z - o.z
can_detect(src, target, dist_sq_gu=dx * dx + dy * dy + dz * dz)
```
Here `off = offset_between(src set, target set) = tuple(b - a for a, b in zip(fa.anchor_gu, fb.anchor_gu))`.

### 4.10 libm summary
`can_detect` reaches:
- `math.sqrt` (density falloff).
- `math.floor` (fbm).
- `math.dist` (profile radius; CPython `vector_norm`).

There is **no** `** 0.5`, `atan2` or trig inside `can_detect`. (`SensorSubsystem._band_distance` uses `(...)**0.5`, i.e. `pow`, but that is the bands, not `can_detect`.)

---

## 5. State `can_detect` WRITES

| State | Where written | When | Time source |
|---|---|---|---|
| Lock-break latch `_broken[observer] ∋ target` | sd:532 set True when `conceal >= thresh`; sd:539 set False otherwise. Only on the `apply_concealment` path, and only when occlusion did not short-circuit (sd:515 returns before). Probes write their **own** `(probe, target)` pair via the recursive call. | each non-memoised call | none (no time) |
| `_walking_probes` | sd:618 True, sd:629 False (`finally`) | probe walk | – |
| `_answers` memo | sd:466 | inside a combat step | – |
| `SensorSubsystem._probe_ids` | subs:1505 (`probes()` drops ids that no longer resolve; ids stay resolvable for the session because the registry pins TGObjects) | probe walk / `in_reach` | – |
| `occ._rock_cache[pset]`, `occ._pair_cache[pset]` | occ:113, occ:147, occ:166 | first query per signature | `sig_rocks = (now, _tick_time, len(contact_index.ships_in(pset)), min_r)`; `sig_pairs = (now, _tick_time, len(rocks))`; `now = g_kUtopiaModule.GetGameTime()` (game time); `_tick_time` = the sensor manager's last `begin_tick` value (game time at the last `sensor_contacts.tick`) |
| `MetaNebula._seed` | nebula.py:99 (lazy, once) | first `GetSeed` | – |
| `dev_mode.log_swallowed` | `jammed` (sd:373), `occ.blocked` (occ:169), `_get_xyz` (subs:3349) | on exceptions | – (logging only) |

### Identity memory ("hidden < 5 s keeps identity")
This is **not** in `can_detect`. `can_detect` only *reads* it, through `IsObjectKnown` in `_beyond_range_reach`.

It is player-only state in `engine/appc/sensor_contacts.py`:
- `_concealed_since[obj] = now_gt` is set on the first concealed sweep (`_continuity` :434-440).
- `is_concealed` = in reach (`in_reach`) AND not `is_hidden_by_cloak` AND `not can_detect(player,obj)`.
- At `now_gt - since >= continuity_window_s` (5.0 dial), `_lose_track` calls `RemoveKnownObject` (:243).
- The time source is `App.g_kUtopiaModule.GetGameTime()`, passed from host_loop.py:12544. The sweep runs every `sweep_period_s` (1.0).

### Time source used by concealment
Two clocks, not one (row 12 and the 2026-10-31 correction). Concealment's drift reads `sensor_detection._game_time()`, which calls `App.g_kTimerManager.GetGameTime()`: `TGTimerManager` has no such method, the AttributeError is swallowed, so `t` is always 0.0 today and `drift_t = t * 0.01` is frozen at 0 (native copies the 0.0 through `native_combat.now()`). The game clock proper, `TGTimerManager._time` accumulated by `+= TICK_DELTA` in `GameLoop.tick` (loop.py:36), is what `App.g_kUtopiaModule.GetGameTime()` returns, and that is what the occlusion caches and the contact sweep read.

⚠️ `advance_ticks` runs ALL of a frame's GameLoop ticks first (host_loop.py:12257). After that, the frame's N `_advance_weapons`/`_advance_combat` steps run in `for _tick_i in range(_sim_ticks_this_frame)` (host_loop.py:12519). So every combat step in a multi-tick frame sees the **same, final** game time. The AI calls within GameLoop see the per-tick times.

---

## 6. Events, randomness, SDK callbacks

- `can_detect` **posts no events and draws no random numbers.**
- It does not call SDK Python directly. Every method it reaches is engine-side: `GetMaxCondition` → engine property class; `IsObjectInNebula`; `probes()` → `ids.get_object_by_id`.
- Reachable side effects: logging (`log_swallowed`), probe-id pruning, latch, caches, lazy seed.
- `GetMaxCondition` calls `prop.GetMaxCondition()` on the engine `SubsystemProperty`, in a try block.
- Callers do have effects:
  - #1 `bank.StopFiring()`.
  - #2 `sys_.StopFiring()`.
  - #3 an early return from `StartFiring` (so no warm-up SFX and no `update_weapons(0.0)`).
  - #8 `player.SetTarget(None)`.
  - #9 `RemoveKnownObject` and Helm `ExitedSet` (SDK `Bridge.HelmMenuHandlers.ExitedSet`).
  - #10/#11 `_identify_one`, which posts `ET_SENSORS_SHIP_IDENTIFIED` and renames.
  - #5 SDK target ranking.

---

## 7. Data a C++ port must mirror

| Structure | Size | Built / reset | Change rate |
|---|---|---|---|
| Per ship: sensor sub fields `_base_sensor_range`, `_condition`, `_max_condition`, property max (shared template → mirror the resolved `GetMaxCondition()`, or mirror the template), `_disabled_percentage`, `_destroyed`, `_radiation_out` (self + `_parent_subsystem`), `_power_factor`, `_probe_ids`, `_known_objects` (set of obj ids) | 1 sensor per ship | SetupProperties (ships.py:1330), damage/repair, radiation, power plant, nebula_runtime, identification | condition/power: per hit / per tick; others rare |
| Per ship: has-sensor (class implements + `_sensor_subsystem` not None), has-cloak (`type(target)` defines `GetCloakingSubsystem` and returns non-None), `_cloak_state == CLOAKED`, `_dying`, `_life_time`, `_dead`, `_containing_set` (as set id), `GetObjID` | – | – | rare; `_life_time` per tick once finite |
| Positions | TransformStore doubles (already native) | – | per tick |
| Set membership: ordered ships per set (`contact_index._buckets`, the occlusion iteration order), ordered nebulae per set (`_nebula_buckets`) | dozens of ships, 0–N nebulae | sets.py:208/273/291; reset on mission swap (host_loop.py:4655), `forget_set` on carry-over change | rare |
| MetaNebula: spheres list `(x,y,z,r)` (≤13 per set in stock: Multi5), `_fbm` (3 doubles), seed (3 doubles) | small | SDK `Systems/*_S.py` at set creation | effectively constant |
| Rocks: per set, `RockClass` flag, `effective_radius` inputs (`_radius`, hull radius, `_scale`) | up to dozens (E1M2 rocks, promoted "Field Rock" ≤8 near the player) | spawn, SetScale, breakup (rocks/death), field promotion (rocks/promotion.py) | rare; positions per tick |
| Profiles: for each mapped set → (map key, anchor_gu (3 doubles), star position, rows `[distance_gu, sensors]`, `full_concealment`) | 33 maps, 3–15 rows | JSON once per process (resolve `_index` lru_cache); mapped flag set once per set (`mark_mapped`) | constant (plus the set-name-lookup quirk) |
| Dials: `sensorless_range_gu`, `cloak_bubble_cap_gu`, `overboost_threshold`, `min_blocker_radius_gu`; `conceal_cap` (dev only); `dev_mode.is_enabled`; `occ._enabled`; `ENHANCED_SENSOR_CONTEST` | scalars | dev keys / Developer Options; **not** reset on mission swap | developer-only changes |
| Latch `_broken` | pairs | reset on mission swap (`_reset_sensor_state`, host_loop.py:4919-4947; mission_change.py:220) and conftest. Python uses weak keys; ships are pinned by the id registry, so entries persist for the session. | per call |
| Occlusion caches + `_tick_time` | per set | reset on mission swap (host_loop.py:4956), conftest; `begin_tick` per sim frame | per game time |
| step_memo `_answers` | pairs | §7.6-3: the same clearing points (§7.1 below) | per step |
| Game time | scalar | GameLoop | per tick |

### 7.1 step_memo clearing points (exact)
- The block opens at host_loop.py:1054 (`with step_memo.combat_step()` around `_advance_combat_step`). The outermost exit calls `forget()` (step_memo.py:49-50). There is no other `combat_step()` user.
- `forget()` is called at:
  - host_loop.py:1119: after `cb.vfx`, before `cb.death`. ⚠️ There is **no** forget between the block start / `cb.projectiles` and the torpedo `apply_hit`s; but `apply_hit` forgets anyway.
  - host_loop.py:1130: after `cb.death`.
  - host_loop.py:1146: right before `cb.held_weapons`. ⚠️ There is **no forget between `cb.held_weapons` and `cb.phasers`**, so phaser-tick asks reuse the held-weapon answers, unless an `apply_hit` (a phaser hit in that loop) forgets in between.
  - host_loop.py:1308 / 1312: around `cb.tractors`.
  - engine/appc/combat.py:617 and :621: before and after every `apply_hit`, including on exception.
- Second table: `_mounts` (subs:57), `(id(sub), id(ship_arg)) → (x,y,z)`.
- The memo is used only when `dist_sq_gu is None and apply_concealment and concealment is None`. So in practice callers #1, #2, #4 (same-frame branch), and #3/#5/#6/#12 if reached from an event handler during the step.

---

## 8. Existing tests

Core rule:
- `tests/unit/test_sensor_detection.py`: range scaling, offline, sensorless dial, keyword-only args at :140.
- `test_sensor_step_answers.py`: memo; forget around `apply_hit`; idempotence across the latch band (:108, parametrised offsets −0.2…1.5).
- `test_concealment_latch_lifetime.py`: hysteresis band and weak-key lifetime.
- `test_nebula_concealment.py`.
- `test_profile_concealment.py`: the profile cap, E3M2 Berkeley start, dev cap dial.
- `test_nebula_density.py`: goldens, tolerance 1e-9.
- `test_cloak_detection_contest.py`: bubble formula/magnitudes, cap, AI acquisition, toggle off.
- `test_sensor_reach.py`: jam, memory, boost (strict >), `in_reach`, cross-set `dist_sq` path.
- `test_sensor_probes.py`: probe walk, recursion, single concealment sample, rock from the probe position, jam not cancelling probes.
- `test_sensor_occlusion.py`: segment/contains, scaled radius, same-tick rock add, `begin_tick` invalidation, alternating-set cache, mission-swap reset.
- `test_sensor_occlusion_bench.py`, `test_sensor_reach_bench.py`.
- `test_nebula_hides_contacts_from_ui.py`: the off-toggle wart at the weapons.
- `test_nebula_list_hoisted.py`.

Callers / surfaces:
- `test_perceived_by.py`.
- `test_player_lock_sensor_gate.py`.
- `test_phaser_cloaked_target_no_fire.py`.
- `test_ai_sensor_gate.py`, `test_ai_acquires_close_cloaked.py`.
- `test_cloak_target_visibility.py`, `test_cloak_combat_rules.py`, `test_cloak_subsystem_suppression.py`.
- `test_sensor_bands_and_visibility.py`, `test_sensor_visibility.py`.
- `test_sensor_continuity.py`, `test_sensor_identification.py`, `test_sensor_media.py`.
- `test_shield_sensor_power_factor.py`, `test_setup_properties_sensor.py`.
- `test_torpedo_guidance_fidelity.py`.
- `test_sensors_disabled_blanks_target_ui.py`, `test_target_list_view.py`.
- `test_developer_options_panel.py`, `tests/ui/test_developer_options_lighting_tab.py`.

Integration:
- `tests/integration/test_sensor_memory_missions.py`.
- `test_sensor_continuity_missions.py`, `test_sensor_continuity_science.py`.
- `test_sensor_probe_launch.py`.
- `test_disable_order_targets_child_subsystems.py`.

Helpers: `tests/helpers/cloak_geometry.py`, `tests/helpers/rocks.py`.

Conftest resets: tests/conftest.py:1679-1742 (contact_index, latch, sensor_dials, occlusion + enabled, sensor_contacts, sensor_mission_guards).

There is **no** differential/bit-exact test against a second implementation today. The goldens are tolerance-based.

---

## 9. Risks / things that make bit-exactness hard

1. **`math.dist` (profile radius).** This is CPython 3.11's `vector_norm`: scale by a power of two from the max |diff|, lossless squares, a compensated sum, then `sqrt` plus one correction step. Port it verbatim from the v3.11.15 source and pin the interpreter version. Measured: 18.6% of random pairs differ from naive sqrt. It is live in Vesuvi4/Belaruz1 (E3M2), where `sensors` varies and the profile term (≤0.3926) is not always clipped by the 0.19 cap. The cap wins only when `sensors*0.3926 > 0.19`, i.e. sensors > ~0.484.
2. **The occlusion cache is keyed on game time, not position, and is shared with `sensor_contacts._scan_blocked`.**
   - The first `(observer,target)` answer at a given `(game_time, _tick_time, len(rocks))` holds for the rest of that game time. That includes the AI tick, the N combat steps of a multi-tick frame (same final game time), and UI-frame queries in 0-tick frames.
   - `_tick_time` changes only at `sensor_contacts.tick` (after combat, player present, sim-gated).
   - The rock list is frozen per `(game_time, _tick_time, len(ships_in_set), min_r)`.
   - The native side must own both caches with identical signatures, and Python `_scan_blocked`/tests must hit the same cache. Otherwise the cache order makes answers diverge.
   - Pair keys are `id()`s. The caches are per-set (weak), and `occ.reset` runs on mission swap.
3. **Ordering of gates and latch writes.** The order is cloak → range (0 → False, **no latch write**) → cloak bubble → occlusion (→ probes, **no latch write**) → concealment latch read/write → distance → beyond-range → probes. Any reordering changes latch state.
4. **Memo semantics.**
   - Keys are `(id(observer), id(target))`.
   - Only no-kwarg calls are memoised.
   - The memo is shared across all callers inside the block, including SDK event handlers fired mid-step.
   - The staleness is deliberate (§7.6-3). There is no forget between `cb.held_weapons` and `cb.phasers`.
   - The probe walk's inner calls are never memoised. A memoised top-level call does not repeat its latch writes or its `probes()` pruning (the prune is idempotent anyway).
5. **Exception behaviour differs per caller.**
   - `_target_undetectable` → False (detectable).
   - torpedo `_target_visible` → True.
   - `is_concealed` → False.
   - Everything else propagates.
   - Raising paths inside the rule: `_local_concealment` calls `ship.GetWorldLocation()` unguarded (a freed TransformStore handle raises `StaleHandleError`); `profile.locate` / `resolve` load; `GetConditionPercentage` on odd properties (guarded).
   - `_get_xyz` swallows a stale handle and returns **(0,0,0)** (logged).
   - The native port needs an error code per pair so each caller can apply its own fallback.
6. **NaN.** Every comparison is written so that NaN makes the "positive" test fail: `r <= 0.0`, `conceal >= thresh`, `dist_sq <= r*r`, `d > best`, `f > best`, `_saturate`, `t` clamp, `> overboost`. Python `min`/`max` return the first argument unless the second strictly wins (see 4.1–4.3). `std::min`/`std::max`/`fmin`/`fmax` do NOT match. Write explicit ternaries in Python's argument order.
7. **Identity semantics.** `_same_set` uses `oset is not None and oset is tset`; `probe.GetContainingSet() is oset`; `rock is observer/target`. Map each to object-id/set-id equality.
8. **`implements()` class probes.** `_cloak_subsystem` uses `getattr(type(target), ...)`. Planets/placements/torpedoes have no cloak and may have no sensor subsystem. A target that is a torpedo or a non-ShipClass object takes the no-cloak path. An observer without a sensor subsystem gets 2000 GU. Rocks (RockClass ⊂ ShipClass) may be observers or targets.
9. **Two "max condition"s.** `IsDisabled`/`IsDestroyed` read `_max_condition`; `GetConditionPercentage` reads the property-template max (`GetMaxCondition`). They can differ (e.g. E1M2 property mutation), and both must be mirrored.
10. **`_base_sensor_range` is mutated by `nebula_runtime`.** Base × clamp01(MetaNebula sensor density) applies on entry and is restored on exit. It is a Python write the mirror must see.
11. **`_power_factor` is a `FrozenField`.** The value read is the instance dict. Writes come from the power plant per tick or the passive program; the mirror must update on every write (the descriptor `__set__` is the natural hook).
12. **Game time.**
    - Two clocks (correction, 2026-10-31). Concealment drift reads `sensor_detection._game_time()`, which today always returns 0.0 (`App.g_kTimerManager.GetGameTime()` does not exist, the error is swallowed), so drift is frozen at t=0; native copies the 0.0 (`nc.now()`). The occlusion caches read `g_kUtopiaModule.GetGameTime()`, the accumulated double `TGTimerManager._time` (`+= TICK_DELTA`; `t*0.01` form). Pass each its own exact double, never recompute as ticks×dt. If `_game_time()` is ever fixed, drift starts moving and the native clock must change in the same commit (a pinning clock test exists).
    - In multi-tick frames all combat steps see the final time.
    - The UI-section callers (#7, #8) run before that frame's GameLoop ticks, so they see the previous time.
13. **Python ints.** `math.floor` returns an int; JSON profile values may be ints. These are exact in double for realistic magnitudes (< 2^53). `math.floor` of NaN/inf raises in Python. Ruling R5: native does NOT return NaN there: when any fbm input (drift_t, freq, seed, sample point) is non-finite inside a sphere, the native call raises ValueError and the wrapper falls back to the Python body, which raises exactly as today. (The earlier claim that this is unreachable because a NaN position gives bound 0 was wrong for non-finite freq, seed or drift.)
14. **Jam on a plain `Nebula`.** `jammed` does not cast, and a plain `App.Nebula` would answer jammed via a truthy `_Stub`. None exist today. Document it rather than replicate it.
15. **Set-name dependence of the profile.** `frame_of` looks up the anchor by `pSet.GetName()` (QuickBattle renames). Mirror the resolved per-set frame (mapped?, system key, anchor), not the name, and refresh it when the name or mapped flag changes.
16. **`perceived_by` and `concealment_at` stay Python callers.** Their `concealment=` hand-off value must equal what native `concealment_at` would compute. If native owns `can_detect`, also expose native `concealment_at`/`effective_sensor_range` (Python callers: perception, sensor_media, sensor_contacts bands, `GetSensorRange`), or keep both and test them differentially. Per §7.6-4 there must be one live copy.
17. **The paused UI still mutates the latch.** `_pump_contacts` and `clear_undetectable_player_lock` run every render frame, paused or not. The writes are idempotent given unchanged inputs.
18. **`_walking_probes` is a process global.** Re-entrancy from an SDK handler during the walk is not possible today, because the walk calls only engine code.
19. **Cross-frame torpedo path.** `blocked()` and `concealment_at` use raw set-local positions of observer and target in **different** sets: the rock test compares a source-set rock list against target-set raw coordinates. This is today's behaviour (documented "exactly today's"); copy it, don't fix it.
