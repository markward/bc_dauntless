> **Superseded (2026-11-03, fire control native only):** the Python path this map traces is deleted. That covers `_pump_held_weapons`' Python loop, `update_weapons`, `try_fire_weapon`, the CanFire→Fire decision code and `TractorBeamSystem.update_weapons`. Fire control has one copy, in C++ (`native/src/combat/src/k1_fire_control.cc`). `CanFire`, `Fire` and `FireDumb` are thin native wrappers. See `docs/superpowers/specs/2026-11-03-fire-control-native-only-design.md` §6.

> **Phase 1b implemented this map** (branch `perf/native-combat-1b`, kernel in `native/src/combat/`). The line numbers below are from the snapshot and have since moved; the kernel's comments cite the current lines.

> Snapshot map written 2026-10-31 at commit 7c6ece598 for the native combat step (spec docs/superpowers/specs/2026-10-30-native-combat-step-design.md), input to the phase 1b (K1 fire control) plan. Line numbers drift; re-check them against the code before relying on one.

# K1 fire control — code map of the path it replaces

Worktree: `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-visibility`, HEAD `7c6ece598` (branch `perf/native-combat`).
File abbreviations: **WS** = `engine/appc/weapon_subsystems.py`, **SS** = `engine/appc/subsystems.py`, **HL** = `engine/host_loop.py`, **SD** = `engine/appc/sensor_detection.py`, **ART** = `engine/appc/articulation.py`, **PS** = `engine/appc/part_severance.py`, **OBJ** = `engine/appc/objects.py`.
`WS` re-exports through `SS` (HL imports `_emitter_in_arc`, `_is_offline`, `_resolve_bank_aim_world` from `engine.appc.subsystems`, HL:112-118; the definitions live in WS).

Corrections to the brief's line hints:
- `WS:2416` is **TractorBeamSystem.update_weapons**. **TorpedoSystem has no `update_weapons` of its own**. It uses the base `WeaponSystem.update_weapons` (WS:1566). Torpedo-specific behaviour comes from `TorpedoTube.CanFire` and `TorpedoTube.Fire`, plus the `TorpedoSystem.StartFiring` ammo gate.
- `CanFire`: WS:753 (energy mixin), WS:1106 (`Weapon`, returns 0), WS:2741 (Pulse), WS:3174 (Tube).
- `_can_engage`: WS:2180 (`_HeldFireWeaponSystem`, True), WS:2225 (Phaser, 700 GU), WS:2410 (Tractor, 120 GU and tractorable).

---

## 1. Per-tick call graph, in order

### 1.0 Where the step runs
- HL:12517-12535, per game tick in the render loop: `_advance_weapons(_ships_this_tick, TICK_DT)` (charge and reload, HL:926; *not* K1), then `_advance_combat(_ships_this_tick, TICK_DT, …)`.
  - `_ships_this_tick = list(_all_ships_for_tick())` (HL:2472) is `engine/appc/ship_iter.iter_ships` (ship_iter.py:62). It walks `list(App.g_kSetManager._sets.items())` in dict order, then `iter_set_objects(pSet)`, and keeps `isinstance(obj, ShipClass)`. Rocks (RockClass) are included.
  - The list is rebuilt between ticks of the same frame (HL:12519-12522).
- `_advance_combat` (HL:1044) wraps `_advance_combat_step` in `with step_memo.combat_step():` (HL:1054).
- `_advance_combat_step` (HL:1058) runs these steps in order:
  1. `cb.eligibility` (HL:1092);
  2. `cb.projectiles` (HL:1095), then `combat.apply_hit` per torpedo hit. Each `apply_hit` calls `forget()` on entry and exit (combat.py:617, 621);
  3. `cb.vfx` (HL:1111);
  4. **`step_memo.forget()` HL:1119**;
  5. `cb.death` (HL:1120);
  6. **`forget()` HL:1130**;
  7. `cb.damage_sys` (HL:1131);
  8. **`forget()` HL:1146**;
  9. **`cb.held_weapons` HL:1147-1148: `_pump_held_weapons(ships_list, dt)`** ← K1;
  10. `cb.phasers` (HL:1155-1302) ← K2. This is NOT K1, but it consumes K1's state: `bank.IsFiring()`, `bank._target`, dwell;
  11. **`forget()` HL:1308**;
  12. `cb.tractors` (HL:1309);
  13. **`forget()` HL:1312**.
- There is **no `forget()` inside `_pump_held_weapons`**. The only forgets that can occur during K1 are nested `combat.apply_hit` calls, and K1 itself never calls apply_hit. Memo answers computed in `cb.held_weapons` are therefore **re-used by `cb.phasers`** (HL:1199 `can_detect(ship, target)`; mount positions from `_resolve_bank_aim_world` and `_strip_emit_position`) until the first phaser `apply_hit` forgets.

### 1.1 `_pump_held_weapons(ships_list, dt)` (HL:984-1021), verbatim logic
```
for ship in ships_list:
    for getter in ("GetPhaserSystem", "GetPulseWeaponSystem",
                   "GetTractorBeamSystem", "GetTorpedoSystem"):
        sys_ = getattr(ship, getter)() if hasattr(ship, getter) else None
        if sys_ is None or not getattr(sys_, "_fire_held", False): continue
        if getattr(sys_, "_pump_self_managed", False):          # Tractor only (class attr WS:2278)
            sys_.update_weapons(dt); continue
        if _is_offline(sys_) or not sys_.IsOn(): sys_.StopFiring(); continue
        held = getattr(sys_, "_held_target", None)
        if held is not None and (hasattr(held, "IsDead") and held.IsDead()): sys_.StopFiring(); continue
        if held is not None and _target_undetectable(sys_, held): sys_.StopFiring(); continue
        if held is not None and hasattr(sys_, "_can_engage") \
                and not sys_._can_engage(ship, held): sys_.StopFiring(); continue
        sys_.update_weapons(dt)
```
- Getters: `ShipClass.GetPhaserSystem/GetPulseWeaponSystem/GetTractorBeamSystem/GetTorpedoSystem` (ships.py:1077/1079/1081/1075) return `_phaser_system`, `_pulse_weapon_system`, `_tractor_beam_system`, `_torpedo_system`.
- `hasattr(sys_, "_can_engage")`:
  - It is True for Phaser, Pulse and Tractor (`_HeldFireWeaponSystem` subclasses).
  - It is **False for TorpedoSystem**. `TGObject.__getattr__` raises AttributeError for single-underscore names (engine/core/ids.py:230), so torpedoes have **no range gate** in the pump.
- `held.IsDead` uses **`hasattr`**, so on a TGObject the check is vacuously True. A target whose class lacks `IsDead`, for example `Planet(ObjectClass)` (planet.py:24), returns a **truthy `_Stub`** and is treated as **dead**, so the pump calls StopFiring. Non-TGObject test fakes without `IsDead` count as alive.
- Branches by system:

| System | `_pump_self_managed` | gates in pump | then |
|---|---|---|---|
| PhaserSystem (WS:2199) | no | `_is_offline`/`IsOn`, held dead, undetectable, `_can_engage` = `_target_within_range_gu(ship, held, 700.0)` (includes `_same_set`) | `WeaponSystem.update_weapons` WS:1566 |
| PulseWeaponSystem (WS:2244) | no | same; `_can_engage` → **True** (WS:2180) | `WeaponSystem.update_weapons` |
| TractorBeamSystem (WS:2256) | **yes** | none in pump | `TractorBeamSystem.update_weapons` WS:2416 |
| TorpedoSystem (WS:1725) | no | `_is_offline`/`IsOn`, held dead, undetectable; **no range gate** | `WeaponSystem.update_weapons` |

### 1.2 `WeaponSystem.update_weapons(dt)` (WS:1566-1637). Used by Phaser, Pulse and Torpedo
```
did_fire = False
ship = self.GetParentShip()                                  # SS:650 (climbs)
if ship is not None and hasattr(ship, "IsDead") and ship.IsDead(): return False   # NB: _force_update NOT cleared on this return
self._prune_targets()                                         # WS:1323 – REPLACES self._target_list with a new list
target = self._target_list[0] if self._target_list else None  # NB: list[0], NOT _held_target
offset = self._live_held_offset()                             # WS:1441
groups = self._active_chain_groups()                          # WS:1302
working = self._resolve_working_group()                       # WS:1311 (calls _active_chain_groups again)
start_group = working
base_idx = self._last_weapon_idx                              # captured once
if self._single_fire:
    lit = self._firing_weapon()                               # WS:1527: first child with IsFiring()
    if lit is not None:
        self.try_fire_weapon(lit, dt, target, offset)
        self._force_update = False
        return bool(lit.IsFiring())
while True:
    self.SetGroupFireMode(working)                            # writes _group_fire_mode
    n = self.GetNumWeapons()                                  # len(self._children), re-read per group
    fired_this_group = False
    for delta in range(1, n + 1):
        idx = (base_idx + delta) % n if n else 0
        weapon = self.GetWeapon(idx)                          # self._children[idx]
        if weapon is None or not weapon.IsMemberOfGroup(working): continue
        if self.try_fire_weapon(weapon, dt, target, offset):
            did_fire = fired_this_group = True
            self._last_weapon_idx = idx
            self._last_group_fired = working
            if self._single_fire:
                self._reseed_all_fire_timers()                # every child _fire_timer = 0.0
                break
        else:
            weapon._target = None                             # ClearTarget (live write on the weapon)
            if self.GetNumTargets() == 0 and weapon.IsDumbFire():   # live len(_target_list)
                weapon.FireDumb(0, 1)                         # only TorpedoTube.IsDumbFire()==1 (WS:3586)
    if fired_this_group or len(groups) <= 1: break
    working = groups[(groups.index(working) + 1) % len(groups)]
    if working == start_group:
        self._last_group_fired = -1
        break
self._force_update = False
return did_fire
```
- `_active_chain_groups`:
  - `chains = self.GetFiringChains()` (WS:1284) reads `prop.GetFiringChains()`, i.e. `list(self._firing_chains)` on WeaponSystemProperty (properties.py:950). Non-list results become `[]`.
  - Empty → `[0]`. Otherwise `_label, groups = chains[self._firing_chain_mode % len(chains)]`, then `list(groups) if groups else [0]`.
- `_resolve_working_group`: `if self._last_group_fired != -1 and self._last_group_fired in groups: return it` else `groups[0]`.
- `IsMemberOfGroup(g)`:
  - Defined at WS:1267 for WeaponSystem (and so for PhaserBank, PulseWeapon and TractorBeam) and at WS:1160 for Weapon (TorpedoTube).
  - `g == 0 → 1`, else `int(prop.GetGroups()) & (1 << (g - 1))`.
  - `GetGroups` (properties.py:508) is `int(getattr(self, "_groups", 0))`. A **None property gives mask 0**: not a member of any group except 0.
- `_live_held_offset()` (WS:1441):
  - `ship = self.GetParentShip()`; `probe = getattr(type(ship), "is_using_target_offset", None)`.
  - If callable and `ship.is_using_target_offset()` (ships.py:1767: `bool(self._use_target_offset and self._manual_target_offset is not None)`), it returns `ship.GetTargetOffsetTG()` (ships.py:1730). That is the manual offset copy, else the locked subsystem's `GetPositionTG()`, else `TGPoint3(0,0,0)`.
  - Otherwise it returns `getattr(self, "_held_offset", None)`.

### 1.3 `WeaponSystem.try_fire_weapon(weapon, dt, target, offset)` (WS:1488-1525)
```
if self._force_update: weapon._fire_timer = self.FIRE_TIMER_THRESHOLD            # 0.33 (WS:1486)
else:                  weapon._fire_timer = getattr(weapon, "_fire_timer", 0.0) + dt
if not weapon.IsFiring() and weapon._fire_timer < self.FIRE_TIMER_THRESHOLD: return False
weapon._fire_timer = 0.0
if not weapon.CanFire():
    weapon.StopFiring()            # EFFECT (beam loop-sound stop / Pulse clears _target,_target_offset / Tube _firing=False)
    return False
before = self._fired_counter(weapon)       # weapon.__dict__.get("fired") – test fakes only; None in production
result = weapon.Fire(target, offset)
if self._weapon_did_fire(weapon, result, before): return True    # bool result wins; production Fire returns bool
weapon._target = None
for entry in list(self._target_list):      # LIVE read of the list (may have been changed by Fire's event handlers)
    if entry is None or (hasattr(entry, "IsDead") and entry.IsDead()): continue
    before = self._fired_counter(weapon)
    result = weapon.Fire(entry, offset)
    if self._weapon_did_fire(weapon, result, before): return True
return False
```
- **The target-list retry re-tries `_target_list[0]`, which is the same target that just failed.** It also retries every other live entry. Fire is called 1 + (number of live entries) times on failure.
  - For a tube, each failing targeted Fire **posts `ET_WEAPON_FIRE_FAILED`** (§5).
  - When `target is None` (empty list), Fire(None) is called once and the retry loop has nothing to iterate.
- `_weapon_did_fire` (WS:1556) checks, in order: `isinstance(result, bool)`, then the `fired` counter, then `bool(weapon.IsFiring())`.
- Fire-timer semantics:
  - The `0.33` threshold is skipped entirely for a weapon that `IsFiring()`, i.e. a lit beam.
  - After every attempt that passes the gate, the timer is reset to `0.0`, whether or not the weapon fired.
  - A single-fire success then zeroes all siblings via `_reseed_all_fire_timers` (WS:1535).

### 1.4 Per weapon class: CanFire → Fire
**PhaserBank** (`class PhaserBank(_EnergyWeaponFireMixin, WeaponSystem)` WS:2515)
- `CanFire` is the mixin's (WS:753-791):
  ```
  parent = self.GetParentSubsystem(); on = parent is not None and parent.IsOn()
  if not on: return 0
  ship = self._climb_to_ship() …; if ship is not None and hasattr(ship,"IsDead") and ship.IsDead(): return 0
  if not self._charge_gate(): return 0
  combined = self.GetConditionPercentage() * parent.GetConditionPercentage()
  if self.GetDisabledPercentage() >= combined: return 0
  return 1
  ```
- `_charge_gate` (WS:795) **mutates state**:
  ```
  if self._depleted:
      if self._charge_level < self._min_firing_charge: return False
      self._depleted = False
  return self._charge_level > 0.0
  ```
- `PhaserBank.Fire` (WS:2545):
  ```
  was_firing = self._firing
  fired = _EnergyWeaponFireMixin.Fire(self, target, offset)
  if fired and not was_firing: _post_weapon_fired(self)
  ```
- Mixin `Fire` (WS:805-826):
  ```
  if not self.CanFire(): return False                # CanFire evaluated a 2nd time
  if not self._aim_in_arc(target): return False      # WS:740
  ------ DECISION ENDS ------
  was_firing = self._firing
  self._firing = True; self._target = target; self._target_offset = offset
  if not was_firing:
      self._beam_on_countdown = BEAM_ON_DELAY_S      # 0.66
      self._dwell = 0.0
      self._play_fire_sfx()                          # WS:925
  return True
  ```
- `_aim_in_arc(target)` (WS:740):
  ```
  ship = self._climb_to_ship()
  aim_world = _resolve_bank_aim_world(self, target) if target is not None else _resolve_aim_world(ship, None)
  return _emitter_in_arc(self, ship, aim_world)
  ```
  This aims at the **target centre** (`target.GetWorldLocation()`), never at the subsystem or offset. The `cb.phasers` re-check uses `target_sub or target` (HL:1229). Do not unify them.

**PulseWeapon** (WS:2628)
- `CanFire` (WS:2741): `if self._cooldown_remaining > 0.0: return 0`, then the mixin `CanFire` with Pulse `_charge_gate` (WS:2730): `return self._charge_level >= self._shot_cost() - 1e-9`. This has no mutation.
  - `_shot_cost` = `self._normal_discharge_rate * PULSE_COST_SCALE_BY_POWER_SETTING[self._power_setting]` with table `(0.5, 1.0, 2.0)`.
- `Fire` (WS:2746-2804):
  ```
  if not self.CanFire(): return False
  prop = self.GetProperty(); script = prop.GetModuleName() if (prop is not None and hasattr(prop,"GetModuleName")) else ""
  if not script: return False
  try: mod = importlib.import_module(script)
  except ImportError: _announce_once(("projectile", script), …); return False      # stdout print once/process
  ship = self._climb_to_ship()
  if target is None: target = self._target
  if target is None and ship is not None and hasattr(ship, "GetTarget"): target = ship.GetTarget()
  if target is not None and hasattr(target, "IsDead") and target.IsDead(): target = None
  if target is not None:
      self._target = target                                             # MUTATION BEFORE the arc test
      self._target_offset = offset if isinstance(offset, TGPoint3) else None
      world_dir = _solve_pulse_launch_direction(self, ship, target, mod)  # WS:456 – calls mod.GetLaunchSpeed(), mod.GetLifetime()
      if world_dir is None or not _emitter_in_arc(self, ship, world_dir): return False
  else:
      self._target = None; self._target_offset = None
      world_dir = _emitter_forward_world(self, ship)                    # WS:430, skew=False
  ------ DECISION ENDS ------
  torp = _spawn_projectile(self, mod, drf_override=self.GetDamageRadiusFactor(), world_dir=world_dir)   # WS:522
  if torp is not None: torp._damage = float(torp._damage) * self.GetDamageScale()
  self._charge_level = max(0.0, self._charge_level - self._shot_cost())
  self._cooldown_remaining = self.GetCooldownTime()
  return True
  ```
- `_solve_pulse_launch_direction` reads the cannon's **just-stamped** `_target_offset` through `_resolve_torpedo_aim_point`.
- `StopFiring` (WS:2818): `_firing=False; _target=None; _target_offset=None`.

**TorpedoTube** (`class TorpedoTube(Weapon)` WS:2961)
- `CanFire` (WS:3174-3212):
  ```
  parent = self.GetParentSubsystem()
  if parent is None or not parent.IsOn(): return 0
  if (not self.IsSkewFire() and parent is not None
          and _game_time() - getattr(parent, "_last_system_fire_time", -1000.0) <= 0.5): return 0
  if self._num_ready <= 0: return 0
  if self.IsDisabled(): return 0                       # SS:1168 on the tube
  if _game_time() - self._last_fire_time < self._immediate_delay: return 0
  if self._ammo_exhausted(): return 0                   # WS:3122: finite and ammo.GetAvailable() <= 0
  return 1
  ```
  - `_game_time()` (WS:52) is `float(App.g_kUtopiaModule.GetGameTime())`. On exception it is `0.0` plus `dev_mode.log_swallowed`.
- `Fire` (WS:3214-3272):
  ```
  if not self.CanFire(): return False
  if target is not None:
      aim_point = _resolve_torpedo_aim_point(self, target)          # WS:2911 – uses self._target_offset = the PREVIOUS shot's offset
      if aim_point is None: self._broadcast_weapon_fire_failed(); return False     # EVENT
      if not _in_torpedo_cone(self, self._climb_to_ship(), aim_point):            # WS:2927
          self._broadcast_weapon_fire_failed(); return False                       # EVENT
  ------ DECISION ENDS ------   (phase 1b: _fire_decide returns (target,); the stamp below is the EFFECT's, and K1 logs no tube stamp)
  if target is not None:
      self._target = target; self._target_offset = offset
  else:
      self._target = None; self._target_offset = None
  self._firing = True; now = _game_time()
  self._num_ready -= 1; self._last_fire_time = now
  parent = self.GetParentSubsystem(); if parent is not None: parent._last_system_fire_time = now
  self._start_slot_cooldown(now)                                     # in-place list writes _reload_timers[i], _reload_advanced_at[i]
  self._spawn_torpedo()                                              # WS:3334: ammo.AddAvailable(-1) (finite), script resolve, _spawn_projectile, ET_TORPEDO_FIRED
  self._broadcast_weapon_fired()                                     # ET_WEAPON_FIRED
  self._broadcast_ammo_consumed_if_player()                          # ET_TORPEDO_AMMO_CONSUMED (player only)
  self._firing = False
  return True
  ```
- `FireDumb(0,1)` (Weapon, WS:1115): `if _dewarp_blocks_fire(self): return` then `self.Fire(target=None, offset=None)`.
- `StopFiring` (Weapon WS:1109): `self._firing = False`.

### 1.5 TractorBeamSystem.update_weapons(dt) (WS:2416-2471) — pump hands it the frame unconditionally
```
if not self._fire_held or self._held_target is None: return False
if not self.IsOn(): self._sync_firing_event(); return False            # EVENT on edge (WS:2376)
if _is_offline(self): self.StopFiring(); return False                   # StopFiring WS:2509 → WeaponSystem.StopFiring + _sync_firing_event
ship = self.GetParentShip(); target = self._held_target
if hasattr(target, "IsDead") and target.IsDead(): self.StopFiring(); return False
engageable = self._can_engage(ship, target)     # _target_within_range_gu(ship,target,120.0) and _target_tractorable(target) (== target is not None)
for i in range(self.GetNumWeapons()):
    em = self.GetWeapon(i)
    if em is None or not em.IsFiring(): continue
    aim = _resolve_bank_aim_world(em, target)
    if (not engageable) or (not _emitter_in_arc(em, ship, aim)): em.StopFiring()    # mixin StopFiring (ThawParentWakeField write)
if not engageable: self._sync_firing_event(); return False
for i in range(self.GetNumWeapons()):
    em = self.GetWeapon(i)
    if em is not None and em.IsFiring(): self._sync_firing_event(); return False
fired = self._engage_beam(target, self._live_held_offset(), ship)       # WS:2473
self._sync_firing_event(); return fired
```
- There is **no detectability, cloak or dewarp check per tick**; those apply only at `StartFiring`.
- `_engage_beam` (WS:2473-2507):
  - Single-fire: `start = self._next_emitter_index % n`; for `delta in range(n)`, `idx=(start+delta)%n`. It skips None, then `aim_world = _resolve_bank_aim_world(emitter, target)`; if `not _emitter_in_arc` it continues. `if hasattr(emitter,"CanFire") and emitter.CanFire(): emitter.Fire(target, offset); self._next_emitter_index = (idx+1)%n; return True`.
  - Multi-fire: every in-arc emitter with `CanFire` gets `Fire`.
  - Fire's return value is ignored.
  - TractorBeam's `Fire` is the mixin's: it calls `CanFire` again and `_aim_in_arc` again, and posts no ET_WEAPON_FIRED.
  - Note that `_resolve_bank_aim_world` and `_emitter_in_arc` are computed up to twice per emitter (once here, once in `_aim_in_arc`).

### 1.6 StartFiring (outside the step, from SDK AI / UI; runs K1 for one system with `dt=0.0`)
- `WeaponSystem.StartFiring` (WS:1395-1428):
  ```
  if not self.IsOn(): return
  if _is_offline(self): return
  if _cloak_blocks_fire(self): return          # WS:990: ship.GetCloakingSubsystem() and cloak.IsTryingToCloak()
  if _dewarp_blocks_fire(self): return         # WS:1024: warp_state.is_arriving(ship) → WarpEngineSubsystem.is_dewarp_driving()
  if _target_undetectable(self, target): return
  if (target is not None and hasattr(self, "_can_engage") and not self._can_engage(self.GetParentShip(), target)): return
  self._add_target(target)                     # WS:1319 – in-place .append if not already in (== membership via `in`)
  self._held_target = target; self._held_offset = offset; self._fire_held = True
  self.SetForceUpdate(1)
  self.update_weapons(0.0)
  ```
- `_HeldFireWeaponSystem.StartFiring` (WS:2184), used by Phaser and Pulse: `if target is None: return`, then the base.
- `TorpedoSystem.StartFiring` (WS:1745):
  ```
  ammo = self.GetCurrentAmmoType(); finite = ammo is not None and not getattr(ammo, "_unlimited", True)
  if finite and ammo.GetAvailable() <= 0: self._post_cant_fire(); return    # ET_CANT_FIRE, UNGUARDED AddEvent
  super().StartFiring(target, offset)
  ```
- `TractorBeamSystem.StartFiring` (WS:2348):
  - It returns early if `not IsOn() or target is None`, if `_is_offline`, if cloak blocks, or if dewarp blocks. It has **no detectability gate**.
  - It then does `_add_target`, `_fire_held=True`, `_held_target`, `_held_offset`, and `if self._can_engage(ship,target): self._engage_beam(target, offset, ship)`, then `_sync_firing_event()`.
- StartFiring normally runs **outside** `step_memo.combat_step()` (AI and UI tick), so `step_memo.active()` is False and every `can_detect` and mount position is computed fresh.
- Quirk: `_add_target` appends. An AI that re-targets without `StopFiring` leaves `[t1, t2]`. `_held_target` is then `t2`, so the pump gates on `t2`, but `update_weapons` fires at `_target_list[0] == t1`.

### 1.7 StopFiring paths reached from K1 gates
- `WeaponSystem.StopFiring` (WS:1430):
  ```
  _fire_held=False; _held_target=None; _held_offset=None; _target_list=[]; _last_group_fired=-1
  for i in range(GetNumWeapons()): w.StopFiring()
  ```
- Mixin `StopFiring` (WS:828):
  ```
  was_firing = self._firing; self._firing = False; self._beam_on_countdown = 0.0
  if was_firing and self._loop_handle is not None: self._loop_handle.Stop(); self._loop_handle = None
  ```
- TractorBeamSystem `StopFiring` (WS:2509): `_engage_state=None; super().StopFiring(*args); self._sync_firing_event()`.

---

## 2. Every attribute or state read by the decision part

"Desc" is the descriptor already on the class: **WF** = `WakeField` (passive_state.py:59; `__set__` only, wakes a sleeper), **FF** = `FrozenField` (passive_power.py:38; `__set__` only, thaws a frozen power consumer), **TPWF** = `ThawParentWakeField` (passive_power.py:98). "plain" means an instance-dict attribute.

### 2a. Weapon system (PhaserSystem / PulseWeaponSystem / TractorBeamSystem / TorpedoSystem)
| Owner | Attr | Type | Write sites | Desc |
|---|---|---|---|---|
| WeaponSystem | `_fire_held` | bool | WS:1207 init, 1426 StartFiring, 1431 StopFiring, 2362 Tractor StartFiring | plain |
| WeaponSystem | `_held_target` | obj/None | WS:1208, 1424, 1432, 2363 | plain |
| WeaponSystem | `_held_offset` | TGPoint3/None | WS:1209, 1425, 1433, 2364 | plain |
| WeaponSystem | `_target_list` | list | WS:1202 init; **in-place `.append` WS:1321** (`_add_target`); rebound WS:1325 (`_prune_targets`), WS:1434 (StopFiring) | plain |
| WeaponSystem | `_force_update` | bool | WS:1197 init, 1281 `SetForceUpdate`, 1607, 1636 | plain |
| WeaponSystem | `_last_weapon_idx` | int | WS:1199 init, 1620 | plain |
| WeaponSystem | `_last_group_fired` | int | WS:1201 init, 1435, 1621, 1634 | plain |
| WeaponSystem | `_firing_chain_mode` | int | WS:1200 init, 1295 (`SetFiringChainMode`; TorpedoSystem override WS:2059 calls super) | plain |
| WeaponSystem | `_group_fire_mode` | int | WS:1198 init, 1299 (written every update_weapons loop) | plain |
| WeaponSystem | `_single_fire` | int | WS:1213 init, 1224 `SetSingleFire` (ships.py property copy) | plain |
| WeaponSystem | `_children` | list | SS:322 init; **in-place `.append` SS:1121** (`AddChildSubsystem`) | plain |
| WeaponSystem | `_property` → `GetFiringChains()` → `prop._firing_chains` | list[(str, list[int])] | properties.py `SetFiringChainString` (907..) | plain (prop) |
| PoweredSubsystem | `_is_on` | bool | SS:1298 init (False), 1318 TurnOn, 1319 TurnOff; ShieldSubsystem override 2126/2131 (n/a); subclass inits 1465/1690/1803/2020/2780 | **FF** (SS:1270) |
| ShipSubsystem | `_parent_ship` | ship/None | SS:318, SS:677 `SetParentShip` (via ships.py:1040 `_attach_subsystem`) | plain |
| ShipSubsystem | `_parent_subsystem` | sub/None | SS:319, SS:1120 | plain |
| ShipSubsystem | `_radiation_out` | bool | SS:321, radiation.py:81 (False), radiation.py:103 (True) | plain |
| ShipSubsystem | `_destroyed`, `_damaged` | bool | SS:1206 `SetDestroyed` (+ `SetDamaged`) | plain |
| ShipSubsystem | `_condition`, `_max_condition`, `_disabled_percentage` | float | see 2b | plain |
| PhaserSystem | `_power_level` | int | WS:2210 init, 2217 | plain (K1 does not read it; K2 does) |
| TorpedoSystem | `_last_system_fire_time` | float | WS:1743 init (-1000.0), WS:3259 (Fire effect) | plain |
| TorpedoSystem | `_ammo_by_slot` | dict | WS:1731 init, **in-place `[k]=` WS:1922** (AddAmmoType), RemoveAmmoType ~WS:1811-1820 | plain |
| TorpedoSystem | `_selected_slot` | int/None | WS:1737, 1820, 1985, 2001 | plain |
| TorpedoAmmoType | `_unlimited` | bool | WS:1668, 1683 | plain |
| TorpedoAmmoType | `_available` | int | WS:1670, 1685, 1700 `SetAvailable`, 1707 `AddAvailable` (Fire effect `_spawn_torpedo`) | plain |
| TorpedoAmmoType | `_max_torpedoes` | int | WS:1669, 1682 | plain |
| TractorBeamSystem | `_next_emitter_index` | int | WS:1195 init, WS:2493 | plain |
| TractorBeamSystem | `_was_firing` | bool | WS:2308 init, WS:2399 (`_sync_firing_event`) | plain |
| TractorBeamSystem | `_pump_self_managed` | class attr True | – | – |

### 2b. Leaf weapon (PhaserBank / PulseWeapon / TractorBeam / TorpedoTube)
| Owner | Attr | Type | Write sites | Desc |
|---|---|---|---|---|
| Weapon / WeaponSystem | `_fire_timer` | float | WS:1100 / 1203 init; WS:1491, 1493, 1508 (try_fire_weapon), 1539 (`_reseed_all_fire_timers`). **All writes are inside K1.** | plain |
| energy mixin | `_firing` | bool | WS:819, 830; PhaserBank init WS:2526; PulseWeapon init/2820 (no `True` write anywhere for pulse); TractorBeam init | **WF** (mixin WS:686); TractorBeam **TPWF** (WS:2833) |
| Weapon (tube) | `_firing` | bool | WS:1097 init, 1110, 3253 (True), 3271 (False) | plain |
| energy mixin | `_charge_level` | float | ships.py:1497 (spawn full), WS:884 (drain), 923 (recharge), 2578-80/2704-06/2855-57 `SetChargeLevel`, **WS:2802 (pulse Fire effect)** | **WF** |
| energy mixin | `_max_charge` | float | ships.py:1489, properties.py:602 (property side) | **WF** |
| energy mixin | `_min_firing_charge` | float | ships.py:1491 | plain |
| energy mixin | `_depleted` | bool | WS:332 init, **WS:802 (`_charge_gate`, a decision-path write)**, WS:893 (UpdateCharge) | plain |
| energy mixin | `_normal_discharge_rate` | float | ships.py:1493 | plain |
| energy mixin | `_power_setting` | int | WS:323 init (1), WS:870 `SetPowerSetting` | plain |
| PulseWeapon | `_cooldown_remaining` | float | WS:2655 init, **WS:2803 (Fire effect)**, WS:2808 (UpdateCharge) | **WF** (WS:2639) |
| PulseWeapon | `_cooldown_time` | float | ships.py:1501 | plain |
| all leaves | `_target` | obj/None | WS:820 (mixin Fire), 1097, 1191, 1471 `SetTarget`, **1517 & 1626 (K1 ClearTarget)**, 2528, 2650, **2781 (pulse, before arc test)**, 2789, 2821, 3244, 3251 | plain |
| all leaves | `_target_offset` | TGPoint3/None | WS:821, 1098, 2529, 2651, **2782 (pulse, before arc test)**, 2790, 2822, 2840, 3245, 3252 | plain |
| TorpedoTube | `_num_ready` | int | ships.py:1511, WS:3094 (`_clamp_num_ready`), **3255 (Fire effect)**, 3486 (ReloadTorpedo), 3568 (UnloadTorpedo) | **WF** (WS:2976) |
| TorpedoTube | `_max_ready` | int | ships.py:1510, (properties.py:777 property side) | **WF** |
| TorpedoTube | `_last_fire_time` | float | WS:2998 init (-1000.0), 3107 `SetLastFireTime`, **3256 (Fire effect)** | plain |
| TorpedoTube | `_immediate_delay` | float | ships.py:1506 | plain |
| TorpedoTube | `_skew_fire` | bool | WS:3013 init, WS:3594 `SetSkewFire` (from TorpedoSystem.SetSkewFire / SetFiringChainMode WS:2093) | plain |
| ShipSubsystem | `_condition` | float | SS:323, **SS:698** `SetCondition`, SS:737 `SetMaxCondition` | plain |
| ShipSubsystem | `_max_condition` | float | SS:324, SS:738 | plain |
| ShipSubsystem | `_property` → `GetMaxCondition()` | data-bag `_data[("MaxCondition",())]` | properties.py:86-111 `__getattr__` setter (**in-place dict write, property shared per class**; e.g. E1M2 `pHull.GetProperty().SetMaxCondition(300)`) | none |
| ShipSubsystem | `_disabled_percentage` | float | SS:403 init (0.25), SS:1137 | plain |
| ShipSubsystem | `_position` | TGPoint3 | SS:337, SS:473 (`SetProperty`) | plain |
| ShipSubsystem | `_direction` | TGPoint3 | SS:342, 477, 826 `SetDirection` | plain |
| ShipSubsystem | `_up` | TGPoint3 | SS:344, 485, 840 `SetUp` | plain |
| ShipSubsystem | `_right` | TGPoint3 | SS:343, 481, SS:831 `SetRight` (tube cone uses `GetRight`) | plain |
| ShipSubsystem | `_arc_width_lo/_hi`, `_arc_height_lo/_hi` | float | SS:347-350 init (−π, π, −π/2, π/2), SS:493, SS:498 | plain |
| ShipSubsystem | `_arc_set` | bool | SS:393 init False, SS:494, SS:499 | plain |
| WeaponProperty | `_groups` (via `GetGroups`) | int | properties.py:506 `SetGroups` | plain (prop) |
| PulseWeaponProperty | module name (`GetModuleName`) | str | properties.py:732 | plain (prop) |
| SDK projectile module | `GetLaunchSpeed()`, `GetLifetime()` | Python functions | SDK script | **Python callback** |

No SPV live write exists: `set_subsystem_position` (ui/ship_property_viewer_panel.py:1234) only stages edits until the next ship build.

### 2c. Ships and targets
| Owner | Attr | Type | Write sites | Desc |
|---|---|---|---|---|
| DamageableObject | `_dead` | bool | OBJ:855, OBJ:900 `SetDead` | plain |
| DamageableObject | `_dying` | bool | OBJ:854, OBJ:891 `SetDying` (ship_death.begin) | plain |
| DamageableObject | `_life_time` | float | OBJ:861, OBJ:882 `SetLifeTime`, object_lifetime.py:46 | plain. `IsDying` = `_dying or _life_time < 1.0e6` (OBJ:867, DYING_THRESHOLD OBJ:24) |
| ObjectClass | position / rotation | TransformStore | `get_store().set_position/set_rotation` (OBJ:321-438); `GetWorldLocation` OBJ:344, `GetWorldRotation` OBJ:430 (row-major nine floats) | native already |
| ObjectClass | `_containing_set` | set obj | set membership code (`GetContainingSet` OBJ:315) | plain |
| ObjectClass | `_scale` | float | OBJ:213 `SetScale` | plain |
| PhysicsObjectClass | `_velocity` | TGPoint3 | OBJ:623 `SetVelocity` (ship_motion.py:269,298; ships.py:854) – always rebound, never mutated in place | plain |
| ShipClass | `_target` | obj | ships.py:65, 1680, 1698, 1700 | plain (pulse `ship.GetTarget()` fallback) |
| ShipClass | `_target_subsystem` | sub | ships.py `SetTargetSubsystem` 1728 | plain |
| ShipClass | `_use_target_offset`, `_manual_target_offset` | bool, TGPoint3 | ships.py `UseTargetOffsetTG` / `set_manual_target_offset` (~1752-1765), manual_aim.update each frame | plain |
| ShipClass | `_phaser_system` … `_torpedo_system` | sub | ships.py Set*System / SetupProperties | plain |
| ShipClass | `_cloaking_subsystem` → `IsTryingToCloak()` / `IsCloaked()` | cloak state | cloak subsystem (SS:2946+) | StartFiring + can_detect |
| ShipClass | `_articulation_poses` | dict name→(R,t) | ART:376/469 rebind; **in-place `poses[name]=` ART:352, 370, 491, 495** (tick_ship from core/loop.py:148, before combat) | plain |
| ShipClass | `_parts_detached` | set | PS:268 create; **in-place `.add` PS:468** (`sever`, reached from apply_hit) | plain |
| ShipClass | `_articulation_leaf` | str | ART:410 (cached once) | plain |
| sensors | many | – | see §2d | – |

### 2d. `can_detect` (SD:377), reached through `_target_undetectable` (WS:1036) and the HL:1199 phaser gate
`_target_undetectable` does: `if target is None: False`; `ship = weapon_system.GetParentShip()`; `None → False`; `try: return not can_detect(ship, target) except Exception: return False`.

It reads:
- the target cloak: `type(target).GetCloakingSubsystem` → `IsCloaked()`;
- `effective_sensor_range(observer)` (SD:227):
  - `sensors = ship.GetSensorSubsystem()`;
  - `_is_offline(sensors)`;
  - `GetBaseSensorRange()`;
  - `base * sensors.GetConditionPercentage() * sensors.GetNormalPowerPercentage()` (`_power_factor`, **FF**);
  - otherwise `sensor_dials.get("sensorless_range_gu")`;
- `sensor_dials.get("cloak_bubble_cap_gu")`;
- `sensor_occlusion.blocked(observer, target)` (sensor_occlusion.py:132): major rocks and a segment test, with its **own pair cache** `_pair_cache[pset]` keyed by `(now, _tick_time, len(rocks))`;
- `concealment_at(target)` (SD:290): MetaNebula fbm density via `contact_index.nebulae_in` and `_nd.density(..., drift_t=t*0.01)` with `t = App.g_kTimerManager.GetGameTime()` (**a different clock from the weapons' `g_kUtopiaModule.GetGameTime()`**), plus the radial profile `_profile.locate/evaluate`;
- `dev_mode.is_enabled()` → `dev_nebula_dials.conceal_cap()`;
- the latch `_broken` (a WeakKeyDictionary of WeakSets, SD:147);
- `_get_xyz` (SS:3300);
- `_beyond_range_reach` (SD:556): `_same_set`, `GetNormalPowerPercentage() > sensor_dials.get("overboost_threshold")`, `IsObjectKnown(target)`, `jammed` → `neb.IsObjectInNebula(...)`;
- `_probe_reach` (SD:595): the `sensors.probes()` list, with recursive `can_detect` per probe and the global `_walking_probes` flag.

**can_detect is a sub-project of its own.** This map lists the entry points only; port it from SD:377-672 directly.

---

## 3. Float computations in the decision path (verbatim, with operand order)

All values are Python `float` (double). `TGPoint3` stores `float(x)`.

**F1 fire timer** (WS:1491-1495):
```
weapon._fire_timer = self.FIRE_TIMER_THRESHOLD                 # 0.33
weapon._fire_timer = getattr(weapon, "_fire_timer", 0.0) + dt
not weapon.IsFiring() and weapon._fire_timer < self.FIRE_TIMER_THRESHOLD
```
dt is `TICK_DT` (1/60) from the pump, `0.0` from StartFiring. A NaN timer gives `<` False, so it proceeds.

**F2 range gate** `_target_within_range_gu` (WS:2133-2160):
```
dx, dy, dz = tp.x - sp.x, tp.y - sp.y, tp.z - sp.z
dist_sq = dx*dx + dy*dy + dz*dz
return dist_sq <= max_range_gu * max_range_gu        # 700.0*700.0 (phaser) / 120.0*120.0 (tractor)
```
- Evaluation order: `((dx*dx) + (dy*dy)) + (dz*dz)`. NaN gives False, so the pump calls StopFiring.
- Before the distance it returns: `False` if ship or target is None; `True` if either lacks `GetWorldLocation` (by `hasattr`, so effectively always present on TGObjects); `False` if `not _same_set`.
- `_same_set` (WS:2124) is `frames.containing_set(a)` (engine/systems/frames.py:48: `implements(obj,"GetContainingSet")` then `obj.GetContainingSet()`), followed by `set_a is not None and set_a is containing_set(b)`.

**F3 condition product** (WS:790-792):
```
combined = self.GetConditionPercentage() * parent.GetConditionPercentage()
if self.GetDisabledPercentage() >= combined: return 0
```
- `GetConditionPercentage` (SS:779):
  ```
  mx = self.GetMaxCondition()
  if mx <= 0: return 0.0
  return max(0.0, min(1.0, self._condition / mx))
  ```
- `GetMaxCondition` (SS:714): `prop.GetMaxCondition()` inside `try`; if `pm is not None and float(pm) > 0.0` return `float(pm)`, else `self._max_condition`.
- **Python `min(1.0, x)`** is `x if x < 1.0 else 1.0`, so NaN becomes 1.0. **`max(0.0, y)`** is `y if y > 0.0 else 0.0`. Write these as explicit ternaries in C++ (std::min/std::max happen to match; `fmin`/`fmax` do NOT).
- `>=` with NaN `combined` gives False, so the gate passes.

**F4 charge gates**:
- Beam (WS:800-803): `self._charge_level < self._min_firing_charge` (only when `_depleted`), then `self._charge_level > 0.0`.
- Pulse (WS:2739): `self._charge_level >= self._shot_cost() - 1e-9` with `_shot_cost = self._normal_discharge_rate * PULSE_COST_SCALE_BY_POWER_SETTING[self._power_setting]`. Order: `level >= ((rate*scale) - 1e-9)`.
- Pulse cooldown (WS:2742): `self._cooldown_remaining > 0.0`.

**F5 IsDisabled / IsDestroyed** (SS:1168, 1195), which use **`_max_condition`, not the property max**:
```
if self._max_condition <= 0.0: return 0
threshold = self._disabled_percentage * self._max_condition
return 1 if self._condition <= threshold else 0
IsDestroyed: self._destroyed or (self._max_condition > 0.0 and self._condition <= 0.0)
```
- WeaponSystem aggregates when it has children (WS:1374 IsDisabled = all children disabled; WS:1383 IsDestroyed = `_destroyed` or all children destroyed). Leaf weapons (no children) use the ShipSubsystem rule.

**F6 torpedo time gates** (WS:3196-3211; `_game_time` at WS:3198 and WS:3208):
```
_game_time() - getattr(parent, "_last_system_fire_time", -1000.0) <= 0.5
self._num_ready <= 0
_game_time() - self._last_fire_time < self._immediate_delay
ammo.GetAvailable() <= 0           # int
```

**F7 `_resolve_bank_aim_world`** (WS:104-134):
```
origin = bank._emitter_world_position()             # = subsystem_world_position(bank)  (memo key (id(bank), id(None)))
target_pos = target.GetWorldLocation()
dx = target_pos.x - origin.x; dy = …; dz = …
length = (dx * dx + dy * dy + dz * dz) ** 0.5       # pow(x, 0.5), NOT sqrt
if length > 1e-6: return TGPoint3(dx / length, dy / length, dz / length)
ship = bank._climb_to_ship(); return _resolve_aim_world(ship, None)
```
`_resolve_aim_world(ship, None)` (WS:79):
```
fwd = TGPoint3(0.0, 1.0, 0.0); fwd.MultMatrixLeft(rot)
length = (fwd.x * fwd.x + fwd.y * fwd.y + fwd.z * fwd.z) ** 0.5
if length > 1e-6: return TGPoint3(fwd.x / length, …)
return TGPoint3(0.0, 1.0, 0.0)
```
- NaN `length` gives `> 1e-6` False, so it falls back to ship-forward.
- Bank without `_emitter_world_position` (fakes) → `_resolve_aim_world(ship, target)`: same formula from the ship centre, `** 0.5`.

**F8 `MultMatrixLeft`** (engine/appc/math.py:86-96):
```
x = m00*sx + m01*sy + m02*sz; y = m10*sx + m11*sy + m12*sz; z = m20*sx + m21*sy + m22*sz
```
Row-major storage `m00..m22` (math.py:161-195). `GetWorldRotation` fills it from the TransformStore tuple (OBJ:430).

**F9 `_emitter_in_arc`** (WS:166-246):
```
world_dir = R·GetDirection()                                  # copy then MultMatrixLeft
# not _arc_set (ShipSubsystem default False): 
return (world_dir.x * aim_world.x + world_dir.y * aim_world.y + world_dir.z * aim_world.z) > 0.0
# _arc_set:
world_up = R·GetUp()
world_right = (world_dir.y * world_up.z - world_dir.z * world_up.y,
               world_dir.z * world_up.x - world_dir.x * world_up.z,
               world_dir.x * world_up.y - world_dir.y * world_up.x)
fwd_dot   = world_dir.x   * aim_world.x + world_dir.y   * aim_world.y + world_dir.z   * aim_world.z
right_dot = world_right.x * aim_world.x + world_right.y * aim_world.y + world_right.z * aim_world.z
up_dot    = world_up.x    * aim_world.x + world_up.y    * aim_world.y + world_up.z    * aim_world.z
yaw   = math.atan2(right_dot, fwd_dot)
pitch = math.asin(max(-1.0, min(1.0, up_dot)))
yaw_lo, yaw_hi = sorted(arc_w)            # arc_w = (self._arc_width_lo, self._arc_width_hi), authored order
pitch_lo, pitch_hi = sorted(arc_h)
return (yaw_lo <= yaw <= yaw_hi) and (pitch_lo <= pitch <= pitch_hi)
```
- Early returns `True`: no `GetDirection` (hasattr), GetDirection raises, or the result is not TGPoint3. None of these happen for real subsystems.
- `use_arc_check = getattr(emitter,"_arc_set",None)` is never None for ShipSubsystems. The tuple-probe branch (WS:200-206) is test-fake only.
- `GetArcHeightAngles()` always returns a 2-tuple for ShipSubsystems, so the width-only branch (WS:240-243) is fakes only.
- **NaN:**
  - `min(1.0, NaN)` = 1.0, so NaN `up_dot` gives pitch = asin(1.0) = π/2.
  - `sorted([a, b])` swaps only if `b < a`, so with NaN the order is preserved; C++ `lo=(b<a)?b:a; hi=(b<a)?a:b`.
  - A NaN yaw makes the chained comparison False (out of arc).
  - The dot-cone `> 0.0` with NaN is False.
- libm: `atan2`, `asin`.

**F10 mount position** `_subsystem_world_position` (SS:60-89), with articulation in §6:
```
ship_pos = ship.GetWorldLocation(); local = sub.GetPosition()
px, py, pz = part_transform_point(ship, (local.x, local.y, local.z), prop=physical_parents.property_of(sub))
offset = TGPoint3(px, py, pz); offset.MultMatrixLeft(rot)
return TGPoint3(ship_pos.x + offset.x, ship_pos.y + offset.y, ship_pos.z + offset.z)
```
- No scale is applied. With no ship it returns `(0,0,0)`; with no TGPoint3 local it returns `ship_pos`.

**F11 torpedo aim point** (WS:2911) and `target_offset_world` (SS:92-134):
```
offset = getattr(tube, "_target_offset", None)          # the TUBE's stored offset
if not isinstance(offset, TGPoint3): pos = target.GetWorldLocation(); return copy
# target_offset_world:
mount_sub = authored_mount_subsystem(target, point)     # PS:502: first subsystem with |mount-point| <= 1e-5 per axis, iter order of combat._iter_subsystems
px, py, pz = part_transform_point(target, point, authored=mount_sub is not None, prop=property_of(mount_sub) or None)
scale = float(target.GetScale())
o = TGPoint3(px * scale, py * scale, pz * scale); o.MultMatrixLeft(rot)
return TGPoint3(pos.x + o.x, pos.y + o.y, pos.z + o.z)
```
It returns None for a None target, a target without `GetWorldLocation`, or one with `IsDead()` true (hasattr-based again).

**F12 torpedo cone** `_in_torpedo_cone` (WS:2927-2958):
```
mount = tube._emitter_world_position(); to_aim = aim_point - mount          # TGPoint3.__sub__: componentwise a-b
if to_aim.Length() < 1e-6: return False                                    # Length = math.sqrt(x*x + y*y + z*z)
d = GetDirection() or (0,1,0); r = GetRight() or (1,0,0)
u = (d.y * r.z - d.z * r.y, d.z * r.x - d.x * r.z, d.x * r.y - d.y * r.x)  # LOCAL cross, then rotated
basis = [R·d, R·r, R·u]                                                    # each copy MultMatrixLeft(rot)
fwd = basis[0].Dot(to_aim)                                                 # x*x' + y*y' + z*z'
if fwd <= 0.0: return False
yaw = math.atan2(abs(basis[1].Dot(to_aim)), fwd)
pitch = math.atan2(abs(basis[2].Dot(to_aim)), fwd)
return yaw <= 0.5235984 and pitch <= 0.5235984
```
- Note that `u` is the cross product of the LOCAL vectors, rotated after, while the arc gate crosses the WORLD vectors.
- NaN: `Length() < 1e-6` is False, so it continues; `fwd <= 0.0` is False, so it continues; the final `<=` is False, so the shot is rejected.

**F13 pulse launch solve** (WS:456-519):
```
aim = _resolve_torpedo_aim_point(cannon, target); muzzle = cannon._emitter_world_position()
to_aim = aim - muzzle; dist = to_aim.Length()       # sqrt
if dist < 1e-6: return None
u = TGPoint3(to_aim.x / dist, to_aim.y / dist, to_aim.z / dist)
ship_vel = ship.GetVelocityTG(); tgt_vel = target.GetVelocityTG(); tgt_acc = target.GetAccelerationTG()   # accel is always (0,0,0) (OBJ:631)
launch_speed = float(mod.GetLaunchSpeed()) if hasattr(mod, "GetLaunchSpeed") else 0.0
v_eff = launch_speed + (ship_vel - tgt_vel).Dot(u)
if v_eff <= 0.0: return None
t = dist / v_eff
if t <= 0.0: return None
lifetime = float(mod.GetLifetime()) if hasattr(mod, "GetLifetime") else 8.0
if t > lifetime: return None
pred = (aim.x + tgt_vel.x * t + 0.5 * tgt_acc.x * t * t - ship_vel.x * t, …y, …z)
       # = (((aim.x + (tgt_vel.x*t)) + (((0.5*tgt_acc.x)*t)*t)) - (ship_vel.x*t))
launch = pred - muzzle; n = launch.Length()
if n < 1e-6 or n > _PULSE_RANGE_GATE_SECONDS * v_eff: return None      # 30.0 * v_eff
return TGPoint3(launch.x / n, launch.y / n, launch.z / n)
```
- The `_vec` helper (WS:491) substitutes `(0,0,0)` for any non-TGPoint3.
- Then `_emitter_in_arc(self, ship, world_dir)` (F9).
- The no-target branch uses `_emitter_forward_world(self, ship)` (WS:430): a copy of `GetDirection`, then `MultMatrixLeft(rot)`, with no normalisation and skew=False.

**F14 tractor** reuses F2 (120.0) and F7/F9.

**F15 can_detect** (SD:480-553), entry only:
```
r = effective_sensor_range(observer) = base * sensors.GetConditionPercentage() * sensors.GetNormalPowerPercentage()
cloaked: r = min(sensor_dials.get("cloak_bubble_cap_gu"), CLOAK_DETECTION_BASE_GU + r * CLOAK_RANGE_FACTOR)   # 5.0 + r*0.005
thresh = LOCK_BREAK_T - (HYSTERESIS if _latched(observer, target) else 0.0)  # 0.28 - 0.08
conceal >= thresh → latch, probe walk
r = r * (1.0 - CONCEAL_K * conceal)                                          # 0.9
dx, dy, dz = tx - ox, ty - oy, tz - oz; dist_sq_gu = dx * dx + dy * dy + dz * dz
dist_sq_gu <= (r * r)
```
- `concealment_at` = `max(local, min(profile_term, cap))`, with `profile_term = evaluate(prof, r).sensors * prof.full_concealment`.

**Not in K1:** `_strip_emit_position` (SS:960+, K2) and `CanHit` (uses `_math.sqrt`, WS:2582; an AI-condition caller only).

---

## 4. Memoisation and caches

| Cache | Location | Key | Filled when | Cleared |
|---|---|---|---|---|
| `step_memo` tables | engine/core/step_memo.py | – | only while `_depth > 0` (`active()`) | `forget()` clears every table (step_memo.py:33); the outermost `combat_step()` exit forgets (step_memo.py:48). Calls: HL:1119, 1130, 1146, 1308, 1312; combat.py:617 & 621 (every `apply_hit`, in and out) |
| `_mounts` | SS:57 (`step_memo.table()`) | `(id(sub), id(ship_arg))` → `(x,y,z)`. **`ship_arg` is part of the key**: `_emitter_world_position()` passes `None`; `GetWorldLocation()` on a subsystem (SS:905) passes the ship; CanHit passes the ship. The same mount can therefore be memoised under 2 keys, computed at different moments. | `subsystem_world_position` when `active()` | step_memo forget |
| `_answers` | SD:477 | `(id(observer), id(target))` → bool | `can_detect` with **no optional args** and `active()` | step_memo forget. A memo hit does NOT re-run the latch write (claimed idempotent; tests/unit/test_sensor_step_answers.py) |
| `sensor_occlusion._pair_cache` | sensor_occlusion.py:144 | per set: `(now, _tick_time, len(rocks))` → `{(id(obs), id(tgt)): bool}` | always | when the signature changes |
| `part_severance._mount_parts` | PS:151 | `(leaf, rounded(point,6))` → part name (native `host_io.model_nearest_part`) | when a model answers | never in-step (fallback answers are not cached) |
| `ids.implements` cache | engine/core/ids.py:148 | (class, name) | always | never |
| `articulation.leaf_for` | ART:393 | `ship._articulation_leaf` | first call | never |
| `_projectile_modules` | WS (`_resolve_projectile_module`) | script name | torpedo effect only | mission swap `_reset_projectile_module_cache` |
| `sys.modules` | pulse `importlib.import_module(script)` | – | – | – |

Consequences (§7.6.3 "copy staleness exactly"):
- **Inside `cb.held_weapons` nothing forgets**, so every `can_detect` and mount answer from the first system walked is reused for every later system, ship and the immediately following `cb.phasers` tick until its first `apply_hit`. This holds even if an `ET_WEAPON_FIRED` / `ET_TORPEDO_FIRED` handler moved a ship or toggled sensors.
- **StartFiring outside the step:** `active()` is False, so Python computes fresh every time and **stores nothing**. The native memo must not be read or written there.

---

## 5. Things in the decision path that block a pure-C++ port

| # | Site | What | Movable to "effect"? |
|---|---|---|---|
| 1 | WS:802 `_charge_gate` | **writes `_depleted = False`** inside CanFire (beam/tractor). Also reached from non-K1 CanFire callers (UI/AI conditions) | Make `_depleted` a NativeField. K1 computes the clear and returns it as a record field, and Python applies it (or the kernel owns `_depleted`). Deterministic. |
| 2 | WS:1491/1493/1508/1539 | `_fire_timer` writes | native-owned per §7.6.2; deterministic |
| 3 | WS:1607/1636, 1620, 1621/1634, 1299, 1325 | `_force_update=False`, `_last_weapon_idx`, `_last_group_fired`, `_group_fire_mode` (`SetGroupFireMode`), `_prune_targets` list rebind | deterministic bookkeeping; K1 returns the final values (or owns them). `_prune_targets` drops dead entries, so it needs the IsDead semantics of §1.1 |
| 4 | WS:1517, 1626 | `weapon._target = None` (ClearTarget) after a failed attempt | deterministic; emit as a record. **It feeds K2**: `cb.phasers` reads `bank._target` (HL:1179) and StopFirings a lit bank whose `_target` was cleared |
| 5 | WS:1513 `weapon.StopFiring()` on CanFire fail | beam: `_loop_handle.Stop()` (sound), `_firing` WF write → passive wake; pulse clears target refs | effect record "stop", applied in Python in order. *Round trips (2026-11-01): a bank NOT firing is the class's StopFiring writes, logged (the WakeField still wakes); only a firing bank's stop (the loop sound) stays a `BANK_STOP` record.* |
| 6 | WS:2781-2782 pulse | `_target`/`_target_offset` stamped **before** the arc test, so they persist on failure (`_target` is then cleared by #4, **`_target_offset` is not**) | deterministic; emit |
| 7 | WS:2763-2770 pulse | `importlib.import_module(script)`, `mod.GetLaunchSpeed()`, `mod.GetLifetime()` (SDK Python), `_announce_once` print | cache per script at mirror registration (value-check; mods may differ). Missing module means "decision: False" plus a Python-side announce |
| 8 | WS:3239, 3242 tube | `_broadcast_weapon_fire_failed()` → `App.g_kEventManager.AddEvent(ET_WEAPON_FIRE_FAILED)` **synchronous dispatch** per failing targeted Fire (1 + live target-list entries per attempt) | must stay Python, in order. The kernel returns ordered "fire_failed(tube)" records. Handlers can mutate state, so check the epoch after each |
| 9 | WS:1115 `FireDumb` | `_dewarp_blocks_fire` → `warp_state.is_arriving(ship)` → `WarpEngineSubsystem.is_dewarp_driving()` | mirror a per-ship "arriving" flag, or keep Python |
| 10 | WS:52 `_game_time()` | `App.g_kUtopiaModule.GetGameTime()` (SWIG-shaped Python), `log_swallowed` on failure | pass game time into the kernel per call (constant within a step) |
| 11 | all Fire effects | PhaserBank: `_play_fire_sfx` (TGSoundManager), `_post_weapon_fired` (ET_WEAPON_FIRED). Pulse: `_spawn_projectile` (Torpedo(), **`mod.Create(torp)` SDK**, `register`, launch sound), damage scale, charge and cooldown writes. Tube: `_spawn_torpedo` (ammo debit, `mod.Create`, ET_TORPEDO_FIRED), ET_WEAPON_FIRED, ET_TORPEDO_AMMO_CONSUMED | all effect; stay Python |
| 12 | Tractor WS:2376 `_sync_firing_event` | ET_TRACTOR_BEAM_STARTED/STOPPED_FIRING on edges, on almost every return path | Python effect (edge state `_was_firing` stays Python) |
| 13 | StartFiring | `_post_cant_fire` (ET_CANT_FIRE, unguarded), `_cloak_blocks_fire`, `_dewarp_blocks_fire` | gates mirrorable; the event stays Python |
| 14 | can_detect | latch write `_set_latched` (SD:529/537), `sensor_dials.get`, `dev_mode.is_enabled`, `dev_nebula_dials`, nebula density, `contact_index`, `IsObjectKnown`, probes recursion, `log_swallowed` | §7.6.2: native latch. The rest needs its own map |
| 15 | `part_for_property` | one-time `sys.stderr.write` warning (physical_parents.py) | resolve the part per subsystem in Python at registration |
| 16 | hasattr-on-TGObject | `hasattr(x,"IsDead")` etc. are vacuous; `IsDead` on a class lacking it returns a truthy `_Stub` (and records stub telemetry) | the mirror needs a per-object flag "IsDead is real". A target without it reads as **dead** |

Random numbers: **none** in K1. The fire-timer re-seed is deterministic 0.0 (WS:1500-1508 comment). Radiation outages and Episode7's 10% tube kill are random but happen in handlers, which are effects.

---

## 6. Articulated-part transform for banks on moving parts

Mount world position = `subsystem_world_position(sub, ship=None)` (SS:30). It is memoised by `(id(sub), id(None))` in the step, then `_subsystem_world_position` (SS:60):
1. `ship = sub._climb_to_ship()` (SS:922): `_parent_ship`, else walk `_parent_subsystem` reading each node's `_parent_ship` FIELD, with cycle guard.
2. `ship_pos = ship.GetWorldLocation()` (TransformStore) and `local = sub.GetPosition()` (copy of `_position`; authored mount, body frame, ship units, **unscaled**).
3. `part_transform_point(ship, (lx,ly,lz), prop=physical_parents.property_of(sub))` (ART:712):
   - `property_of(sub)` (physical_parents.py): `sub.GetProperty()` if its class defines `GetPhysicalParent`, else None.
   - `_live_part(ship, None, point, authored=True, prop)` (ART:768):
     - `names = posed_part_names(ship)` (ART:202) is `rig_for(leaf_for(ship))` part names in rig order, plus sorted extra keys of `ship._articulation_poses` (SPV forced). An empty result means **identity, return point unchanged**, which is the overwhelming common case.
     - If `prop is not None`, it uses `physical_parents.part_for_property(leaf, prop, point)`: `explicit_parent` (SPV preview overlay `_preview[leaf][prop name]`, else `prop.GetPhysicalParent()`) if that part exists in `articulation.part_boxes_for(leaf)`. Otherwise it uses `part_severance.part_for_mount(leaf, point)` (PS:118: cache `_mount_parts[(leaf, rounded point)]` → native `host_io.model_nearest_part(model, point)`, fallback `part_for_point` box rule, not cached).
     - If `prop` is None, it uses `part_for_mount` directly.
     - It returns None if `is_detached(ship, name)` (`name in ship._parts_detached`) or `name not in names`.
   - `pose = pose_for_part(ship, name)` (ART:232) is `ship._articulation_poses.get(name, IDENTITY)`, where a pose is `(R, t)`: R is a 3×3 tuple of row tuples and t is a 3-tuple, in ship units.
   - `part_pose.is_identity(pose)` (part_pose.py:87): every `abs(R[i][j]-I[i][j]) <= 1e-9` and `abs(t[k]) <= 1e-9`. If so it returns the point unchanged (bit-exact passthrough, not the multiply).
   - Otherwise `part_pose.apply(pose, x)` (part_pose.py:72): `r = (R[i][0]*x[0] + R[i][1]*x[1] + R[i][2]*x[2] for i)`, then `(r[0]+t[0], r[1]+t[1], r[2]+t[2])`.
4. `offset.MultMatrixLeft(R_ship)` (F8), then `ship_pos + offset` componentwise.

When the inputs change:
- `_articulation_poses` changes in `tick_ship` (engine/core/loop.py:148, GameLoop tick, **before** the combat step) and in SPV `force_pose` / `force_part_pose` (ART:352, 370, 376, 469).
- `_parts_detached` gains entries in `sever` (PS:468), reached from `apply_hit`, which forgets.
- The physical parent changes via SPV preview `set_preview` or a property `SetPhysicalParent`.

**Phase 1b as built (Task 6b).** The mirror carries one Object flag, `has_posed_parts` = `native_combat._posed_flag(ship)`: 1 while any value in `ship._articulation_poses` fails `part_pose.is_identity`, else 0. That is exactly the set of ships for which step 3 can return anything but the point itself (a part absent from the dict reads IDENTITY), so with the flag 0 the native identity path is bit-exact, signed zeros included (pinned by `tests/unit/test_native_posed_flag.py`). A rigged ship at its natural pose, such as a Bird of Prey in "red", therefore walks natively; a flagged ship or offset target falls back whole (P2). Re-pushes: the `PosedPartsField` rebind (`force_pose`, `force_part_pose`, `force_state_poses` via `_store_forced`, tick_ship's first dict) and the end of a `tick_ship` that moved a part in place.

Recommendation: resolve **part name → part index** per subsystem in Python at mirror registration. Re-resolve on detach, preview change, physical-parent write, or rig change. Mirror per-ship pose arrays `(R,t)` plus an `is_identity` flag computed with the same 1e-9 rule. The kernel then does `identity ? local : R·local + t`, then `R_ship·offset + pos`.

The **target-side** transform (`target_offset_world`, F11) adds `authored_mount_subsystem`: a linear scan over `combat._iter_subsystems(target)` (PS:479-514), comparing within 1e-5. It uses `authored=False` (`part_for_point` box rule) for non-mount offsets such as Manual Aim picks. This matters for tube and pulse aim. Precompute it per (target, offset) when the offset is set: the offset only changes on StartFiring, manual-aim update, or lock change.

---

## 7. Existing tests on this path (all focused; none run here)

| File | Checks |
|---|---|
| tests/unit/test_weapon_tick.py (7) | 0.33 timer gate and force-update bypass; CanFire failure calls StopFiring; round-robin resumes past `_last_weapon_idx`; single-fire stops after first success; multi-fire tries every group member; dumb-fire only on zero targets and a dumb weapon; group advance on a dry group |
| tests/unit/test_start_firing_arms_tick.py (4) | StartFiring arms and fires via force update; StopFiring disarms and clears targets; idempotent re-StartFiring; IsFiring reflects `_fire_held` |
| tests/unit/test_weapon_system_sequential_firing.py (10) | off and no-emitter no-ops; multi vs single fire; cursor advance and wrap; skip ineligible |
| tests/unit/test_firing_chains.py | chain-mode clamp; active groups and group-0 fallback; working-group resume; authored chain order; prune dead targets; `IsMemberOfGroup`; TorpedoSystem.SetSingleFire |
| tests/unit/test_torpedo_tube_fire.py (18) | tube CanFire and Fire bookkeeping, dumb vs targeted, ammo-type projectile selection, launch sound |
| tests/unit/test_torpedo_fire_gates.py (15) | ship-wide 0.5 s stagger (exclusive boundary), skew exemption, ±30° cone incl. boundary, FIRE_FAILED post, event order TORPEDO_FIRED → WEAPON_FIRED, ammo-consumed player-only, aim-point None cases |
| tests/unit/test_torpedo_tube_dumb_clears_stale_lock.py | dumb fire clears `_target` |
| tests/integration/test_fire_secondary_chain.py | right-click torpedo; green alert does nothing |
| tests/unit/test_arc_gate.py (11) | arc inside/outside width/height, behind, 90° fallback, reversed bounds |
| tests/unit/test_phaser_arc_handedness.py (3) | pitch gate; starboard banks; strip emit faces target |
| tests/unit/test_bank_aim_world.py (5) | aim origin is the mount; unit length; degenerate fallback; no-parent fallback |
| tests/unit/test_phaser_fire_range_gate.py (10) | 700 GU constant and boundary; StartFiring out of range no-op; pump stops on drift out |
| tests/unit/test_phaser_cloaked_target_no_fire.py (6) | StartFiring no SFX on cloaked target; cloak bubble; pump stops when target cloaks |
| tests/unit/test_weapon_no_target_bail.py (3) | None-target StartFiring no-op for phaser and pulse; no flicker |
| tests/unit/test_weapons_disabled_blocks_fire.py (9) | offline (all children disabled) blocks; repair restores; pump stops on offline; `_advance_combat` stops disabled / sensors-offline / powered-off |
| tests/integration/test_weapon_cross_set_interim_guard.py (7) | cross-set and setless targets out of range (phaser, tractor) |
| tests/unit/test_phaser_canfire_fidelity.py | start/sustain need only nonzero charge; restart after depletion needs MinFiringCharge (`_depleted` latch); dead ship; condition-product gate incl. parent |
| tests/unit/test_energy_weapon_gating.py, tests/unit/test_phaser_charge_stops_fire.py | CanFire charge and on gates; Fire records; SFX; auto-stop at 0 |
| tests/unit/test_energy_weapon_discharge_source.py (9) | pulse shot cost and affordability, refire cadence, power-setting vs power-level |
| tests/unit/test_pulse_aimed_launch.py, tests/unit/test_pulse_weapon_fire.py | lead solve, lifetime and outrun refusal, arc on the LED direction, no-target forward, ship-target fallback, offset threaded through StartFiring |
| tests/integration/test_pulse_singlefire_modes.py (6) | pulse single and multi fire, cooldown, out-of-arc |
| tests/integration/test_disruptor_fire_and_damage.py (2) | held disruptor through the `_advance_combat` hook |
| tests/integration/test_tractor_singlefire_dispatch.py (9), tests/integration/test_tractor_engage_intent.py (4) | tractor engage, sustain, range drop, arc loss and reacquire, shield independence |
| tests/integration/test_phaser_multi_bank_fire.py, tests/integration/test_sequential_firing_galaxy.py, tests/integration/test_galaxy_hardpoint_emitters.py | Galaxy single-fire one bank at a time; multi-fire; behind-target; uncharged skipped |
| tests/unit/test_manual_aim.py | `_live_held_offset` follows manual offset; `_phaser_aim_point` |
| tests/unit/test_mount_position_step_answers.py (5), tests/unit/test_sensor_step_answers.py (7), tests/host/test_combat_step_sensor_answers.py (1) | memo semantics: compute-once inside, forget, block-close drop, latch idempotence, pumps run inside the block |
| tests/unit/test_is_offline_helper.py (6), tests/unit/test_radiation.py | `_is_offline` incl. radiation flag |
| tests/integration/test_passive_weapons_differential.py, tests/host/test_passive_state_scene_audit.py | **template for a K1 differential**: two seeded `combat_stress` loads compared tick by tick with `==` on charge, firing, depletion latch, cooldown, ready, slots and events |
| tests/unit/test_tier_bc_event_emitters.py | event emitters incl. ET_WEAPON_FIRED and tractor STARTED/STOPPED |

There is no test of `_solve_pulse_launch_direction` by name (it is covered via pulse fire tests), and none for `FIRE_TIMER_THRESHOLD` or `_charge_gate` by name.

---

## 8. Recommended decision/effect split, and risks

### 8.1 Kernel shape
The decision of bank k+1 depends on the effect of bank k:
- tube stagger `_last_system_fire_time`, `_num_ready`, `ammo._available`;
- pulse `_charge_level` and `_cooldown_remaining`;
- the `_reseed_all_fire_timers` timer reset;
- whatever the synchronous event handlers change.

So K1 should be **resumable per system**. The kernel walks the update_weapons state machine and stops at the first record that needs Python (a Fire effect, a StopFiring, a FIRE_FAILED post, or a FireDumb). *Round trips (2026-11-01, spec `2026-11-01-native-combat-round-trips-design.md` §10): a walk start is no record (the kernel computes the offset), a Fire on a beam already firing and a StopFiring of a bank not firing are logged writes, so the records left are a beam's lit edge, tube and pulse fires, a firing bank's stop, FIRE_FAILED, FireDumb, ASKs and STOP_SYSTEM.* It returns the decision records plus a **cursor**: the locals `target`, `offset`, `groups`, `working`, `start_group`, `base_idx`, `delta`, `did_fire`, `fired_this_group`, and the position inside the retry loop.

Python applies the record. On resume:
- `n`, `_single_fire`, `_target_list` (retry and `GetNumTargets`) are **re-read live**, as Python does;
- `target`, `offset`, `groups`, `base_idx` stay as captured.

Deterministic bookkeeping can be computed in the kernel and written back once per system:
- `_fire_timer`, `_depleted` clear, `_target=None` clears, `_force_update`, `_last_weapon_idx`, `_last_group_fired`, `_group_fire_mode`, pruned `_target_list`.

The kernel must **simulate** the deterministic parts of each Fire effect it does not hand back, or hand back and re-ask. The epoch rule covers handler side effects.

### 8.2 Per method

**PhaserBank.Fire**
- Decision: CanFire (with the `_depleted` clear), `_aim_in_arc(target)` (centre aim from the mount), and `was_firing`.
- Effect, in Python: `_firing=True` (WF), `_target`, `_target_offset`; on the edge `_beam_on_countdown=0.66`, `_dwell=0.0`, `_play_fire_sfx()`, `_post_weapon_fired`.
- A failed decision has no side effect besides the latch.

**PulseWeapon.Fire**
- Decision:
  - CanFire (cooldown, IsOn, ship alive, afford, condition product);
  - the module present (cached launch speed and lifetime);
  - target fallback (`self._target` → `ship.GetTarget()` → IsDead → None);
  - stamp target/offset (even on failure);
  - the lead solve and arc on `world_dir`, or `_emitter_forward_world` for no target.
- Effect: `_spawn_projectile(world_dir)` with **`mod.Create`**, damage scale, `_charge_level -= shot_cost` (clamped at 0), `_cooldown_remaining = GetCooldownTime()`. Hand `world_dir` (and the target used) to the effect.

**TorpedoTube.Fire**
- Decision:
  - CanFire (game time in);
  - aim point from the tube's **stored** `_target_offset` (previous shot);
  - the cone.
- Effect on failure: post ET_WEAPON_FIRE_FAILED (an ordered record per attempt).
- Effect on success: stamp or clear `_target` and `_target_offset`, `_firing=True`, `_num_ready-=1`, `_last_fire_time`, parent `_last_system_fire_time`, `_start_slot_cooldown`, `_spawn_torpedo`, ET_WEAPON_FIRED, ammo-consumed, `_firing=False`.
- **FireDumb** stays a Python call (dewarp check plus Fire(None)), or the kernel takes a per-ship arriving flag.

**TractorBeam (mixin Fire via `_engage_beam`)**
- Decision: arc and CanFire per emitter in `_next_emitter_index` order.
- Effect: mixin state and SFX, `_next_emitter_index`, then `_sync_firing_event` (Python, edges).
- `TractorBeamSystem.update_weapons` is cheap and rare (only held tractors). Consider leaving it entirely in Python for phase 1 and porting only Phaser, Pulse and Torpedo.

**StartFiring (all four)**
- Decision: IsOn, `_is_offline`, cloak (IsTryingToCloak), dewarp (`is_arriving`), native `can_detect` (no memo outside the step), `_can_engage` (Phaser 700; Pulse True; Torpedo none; Tractor 120 for engage only).
- Effect: TorpedoSystem `_post_cant_fire`; arm (`_add_target` append, held fields, `_fire_held`, force update); then K1 for this one system with `dt=0.0` and **no memo**.

### 8.3 Risks
1. **Mid-system effects change later decisions.** Every Fire effect posts synchronous events (ET_WEAPON_FIRED, ET_TORPEDO_FIRED, FIRE_FAILED, AMMO_CONSUMED, tractor edges). SDK handlers can StopFiring, StartFiring (re-entrant K1 for the same system), destroy the tube (Episode7.py:88-115, random), or change targets. The kernel must stop at each effect and re-check the epoch, rather than batching a system.
2. **Decision-side writes that are not "native-owned" in §7.6.2:**
   - `_depleted` (written by CanFire from any caller, WS:802);
   - pulse `_target_offset` persisting after a failed arc;
   - `weapon._target=None`, which K2 reads to stop a lit beam;
   - `_target_list` rebind.

   Each needs NativeField write-through or kernel ownership. The design's list (fire timer, dwell, latch, torpedo flight) does not cover them.
3. **Truthy-stub "dead".** A target or list entry whose class lacks `IsDead` (Planet, Sun, other ObjectClass) is "dead" via hasattr plus `_Stub` truthiness, in the pump (HL:1011), `_prune_targets` (WS:1323), the retry (WS:1520), pulse (WS:2777), aim point (WS:2917), and `_out_of_action` (which uses `implements`, the opposite answer). The mirror needs a per-object "has real IsDead" bit. Unmirrored targets must be treated as Python does.
4. **`_target_list[0]` vs `_held_target` divergence** when StartFiring is re-called with a new target without a StopFiring. The pump gates on the held target but fires at the list head.
5. **Tube cone uses the PREVIOUS `_target_offset`.** Pulse uses the current one. The phaser arc uses the target centre while `cb.phasers` uses the subsystem. Do not "fix" any of these (§5 anti-goal).
6. **Retry semantics:** the failing target is retried once more as `_target_list[0]`. For tubes that doubles FIRE_FAILED posts; the record count must match exactly.
7. **Two game clocks:** weapons use `App.g_kUtopiaModule.GetGameTime()` (fallback 0.0 bricks tubes); sensors use `App.g_kTimerManager.GetGameTime()`. Pass both in.
8. **Memo key includes the `ship` argument** (`(id(sub), id(None))` vs `(id(sub), id(ship))`). Memo answers survive handler-driven moves until the next forget. **StartFiring outside the step must neither read nor write the native memo.** The outermost-block-exit forget matters too.
9. **Property-backed reads:**
   - `GetMaxCondition` from the shared property data bag (in-place dict write via `SetMaxCondition`, mission-driven);
   - `GetGroups` (`_groups`) and `GetFiringChains` (`_firing_chains`);
   - `GetModuleName`, `GetPhysicalParent`, the SPV preview overlay.

   These bypass any subsystem descriptor and need their own write-through or registration-time snapshot with invalidation.
10. **`IsDisabled` uses `_max_condition` but `GetConditionPercentage` uses the property max.** The two can disagree after a property `SetMaxCondition`. Mirror both.
11. **NaN branches:** use Python's `min`/`max`/`sorted` semantics with explicit ternaries (NaN `up_dot` becomes pitch π/2). Use `pow(x,0.5)` for `** 0.5` (F7) but `sqrt` for `TGPoint3.Length` (F12, F13). Keep the MultMatrixLeft summation order, use local-cross-then-rotate in the tube cone, and keep the pulse `pred` association.
12. **Radiation on a CHILD bank does not gate firing.** `_is_offline` is only called on the system and checks the system and its parent; CanFire never checks `_radiation_out`. Preserve this.
13. **Descriptor bypasses:**
    - passive audit `_restore` writes `obj.__dict__[k]` directly (passive_state.py:82-91);
    - in-place mutations: `_target_list.append` (WS:1321), `_children.append` (SS:1121), `_ammo_by_slot[k]=` (WS:1922), `_reload_timers[i]=` (Fire effect), `_articulation_poses[name]=` (ART:352/370/491/495), `_parts_detached.add` (PS:468).

    The §8 mirror audit must cover all of them.
14. **The early return on a dead ship (WS:1586-1587) leaves `_force_update` set.** The pump's ship-death path normally StopFirings first via `_is_offline`/`_out_of_action`, but `update_weapons` can still see `IsDead` with `_force_update=1` after StartFiring. Copy it exactly.
15. **Ordering:**
    - ships come in `g_kSetManager._sets` dict order × set object order;
    - systems run Phaser, Pulse, Tractor, Torpedo;
    - weapons run round-robin from `base_idx+1`, then the group walk;
    - the ship list is rebuilt per tick within a frame.
16. **`_announce_once` and log_swallowed** produce stdout/stderr output once per process. Python must still emit them on the native path (pulse missing module; fire sound).
