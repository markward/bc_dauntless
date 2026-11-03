> **Superseded in part (2026-11-02, native-damage phase):** the damage pulse no longer hands a CONTACT record back to Python. K2 applies it in the walk through the native hit, so the next bank on the same target sees it by construction (ruling P1). See the native-damage spec §10.

> **Implemented 2026-11-01** on branch `perf/native-combat-k2`, tip commit `6418f858f`. Outcome, measurements and rulings: `docs/superpowers/specs/2026-10-31-native-combat-k2-beams-design.md` §10. The map below is the pre-build snapshot and is not updated.

> Snapshot map written 2026-10-31 at commit b1f2675a5 (branch `perf/native-combat-k2`, worktree `.claude/worktrees/native-combat-1b`) for the native combat step (spec docs/superpowers/specs/2026-10-30-native-combat-step-design.md §7.3 "K2 — beams"). It is the input to the K2 plan. Line numbers drift; re-check them against the code before relying on one. The model for this document is `k1-fire-control-map.md`.

# K2 beams — code map of the `cb.phasers` step

File abbreviations:

| Abbrev. | File |
|---|---|
| **HL** | `engine/host_loop.py` |
| **WS** | `engine/appc/weapon_subsystems.py` |
| **SS** | `engine/appc/subsystems.py` |
| **CB** | `engine/appc/combat.py` |
| **HF** | `engine/appc/hit_feedback.py` |
| **HIO** | `engine/host_io.py` |
| **FR** | `engine/systems/frames.py` |
| **NC** | `engine/appc/native_combat.py` |
| **SH** | `engine/appc/ships.py` |
| **OBJ** | `engine/appc/objects.py` |
| **ART** | `engine/appc/articulation.py` |
| **HB** | `native/src/host/host_bindings.cc` |
| **WG** | `native/src/combat/src/weapon_geometry.cc` |

**Corrections to the spec's §7.3 wording**, all checked against the code:

- **No range gate in `cb.phasers`.** The 700 GU phaser range is K1's pump gate (`PhaserSystem._can_engage`, WS:2345, applied in HL:1038). `cb.phasers` computes the distance only for damage falloff.
- **No shield face in `cb.phasers`.** The face is chosen inside `apply_hit` (CB:781, `_shield_face_from_hit_point(ship, shield_point or hit_point)`). By §7.6.1 `apply_hit` stays in Python, so a K2 "face" output would be a second copy of the rule.
- **`_phaser_aim_point` is at HL:1045-1062** and the scope is HL:1176-1322.
- **The hull trace is reached through `combat._resolve_hit_point` (CB:86)**, then `host_io.ray_trace_mesh` (HIO:570), then the `ray_trace_mesh` binding (HB:7625), then `renderer::ray_trace_instance_linear` (`native/src/renderer/ray_trace.cc:540`). The binding reads the global `g_world` (HB:250), which lives in the HOST module, not in the combat library.

---

## 1. Call graph of `cb.phasers`

### 1.0 Where it runs

The step runs once per game tick, from `run()` at HL:12548:

```
_advance_combat(_ships_this_tick, TICK_DT, ship_instances=session.ship_instances, ..., push_render_data=False)
```

`_advance_combat` (HL:1065) wraps the step in `step_memo.combat_step()`. Inside `_advance_combat_step` (HL:1079), `cb.phasers` comes in this order:

- `step_memo.forget()` (HL:1167);
- `cb.held_weapons` (K1, HL:1168);
- **`cb.phasers` (HL:1176-1322)**;
- `forget()` (HL:1329);
- `cb.tractors`.

**No `forget()` runs between K1 and `cb.phasers`.** The memo answers from K1 (can_detect pairs, mount positions) are therefore reused here until the first phaser `apply_hit`, which forgets on entry and on exit (CB:617, CB:621).

- Phase 1b ruling P4: K1 fills only the NATIVE mount memo. With native on, Python's `_mounts` (SS:59) is empty at the start of `cb.phasers`, and the scope recomputes every mount fresh. With native off, Python's K1 fills `_mounts` and the scope reuses those answers.
- A native K2 that reads the native memo therefore matches the native-off path more closely than 1b does today.
- The native can_detect memo is already shared. `sensor_detection.can_detect` dispatches to native when the switch is on, and the memo is cleared at every forget via `step_memo.on_forget(_h.combat_memo_clear)` (NC:1758-1764).

`ship_instances` is `session.ship_instances` in production. It is a dict `ship → InstanceId`, written at:

- HL:6965 and HL:8263 (realize);
- HL:7053 and HL:7297 (`pop`);
- HL:6656 (`clear`).

Every test and differential calls the step headless with `ship_instances=None`, or with a sentinel dict plus a monkeypatched `host_io.ray_trace_mesh` (see §8).

### 1.1 The loop, verbatim in structure (HL:1177-1322)

```
for ship in ships_list:                                                # list order (ship_iter: sets dict order × set order; rocks included)
    sys_ = ship.GetPhaserSystem() if hasattr(ship, "GetPhaserSystem") else None   # SH:1090 → _phaser_system
    if sys_ is None: continue
    if _is_offline(sys_) or not sys_.IsOn():                           # SS:139 (WeaponSystem aggregate IsDisabled/IsDestroyed, radiation, _out_of_action); SS:1351
        sys_.StopFiring()            # EFFECT, EVERY tick for an offline/off system (WS:1536)
        continue
    for i in range(sys_.GetNumWeapons()):                              # len(_children), read ONCE (WS:1583 → SS:1132)
        bank = sys_.GetWeapon(i)                                       # _children[i] re-read live, None if out of range (SS:1135)
        if bank is None: continue
        target = bank._target                                          # read BEFORE IsFiring
        if not bank.IsFiring():                                        # mixin: 1 if _firing (WS:909) — NOT IsBeamOn
            dwell = bank.take_dwell() if hasattr(bank,"take_dwell") else 0.0   # WRITE _dwell = 0.0 on EVERY idle bank, every tick (WS:929)
            if dwell <= 0.0 or target is None or (hasattr(target,"IsDead") and target.IsDead()): continue
            flush_dwell = dwell                                        # "final partial pulse" path: no can_detect, no arc test
        else:
            if target is None or (hasattr(target,"IsDead") and target.IsDead()):
                bank.StopFiring(); continue                            # EFFECT
            flush_dwell = None
        if flush_dwell is None and not can_detect(ship, target):       # native in 1a; memo (observer,target); may write the latch
            bank.StopFiring(); continue                                # EFFECT
        if not _same_set(ship, target):                                # WS:2244: frames.containing_set identity
            if flush_dwell is None: bank.StopFiring()                  # EFFECT; a banked dwell is DROPPED (already taken)
            continue
        target_pos, target_sub = _phaser_aim_point(ship, target)       # §1.2
        emitter_pos = bank._strip_emit_position(target_pos)            # §1.3
        dx,dy,dz = target_pos - emitter_pos ; dist = (dx*dx+dy*dy+dz*dz) ** 0.5           # F1
        aim_unit = TGPoint3(dx/dist, dy/dist, dz/dist) if dist > 1e-6 else None            # F2
        arc_aim = _resolve_bank_aim_world(bank, target_sub or target)  # computed even on the flush path (unused there)
        if flush_dwell is None:
            if not _emitter_in_arc(bank, ship, arc_aim):              # `ship` = the loop ship
                flush_dwell = bank.take_dwell(); bank.StopFiring()     # WRITE + EFFECT; continues to deliver the partial pulse
            else:
                flush_dwell = bank.accumulate_dwell(dt)                # WRITE _dwell; >0 only on a flush tick
        level = sys_.GetPowerLevel() if hasattr(sys_,"GetPowerLevel") else sys_.PP_HIGH   # WS:2339 → _power_level
        impact_point, impact_normal = combat._resolve_hit_point(       # §1.4 — the hull trace, EVERY contact tick
            ship_instances=ship_instances, ship=target, ray_origin=emitter_pos,
            ray_direction=(aim_unit if dist > 1e-6 else None),
            max_dist=(dist * 1.5 if dist > 1e-6 else 0.0), fallback_point=target_pos)
        bubble_entry = (combat.shield_bubble_entry(target, emitter_pos, aim_unit, dist * 1.5)
                        if (aim_unit is not None and combat.shields_block(target)) else None)  # §1.5; shields_block only if aim_unit
        ───────── PURE-GEOMETRY DECISION ENDS HERE (per bank) ─────────
        if flush_dwell <= 0.0:                                         # not a pulse tick (incl. the whole 0.66 s beam-on delay)
            hit_feedback.beam_contact(ship=target, source=ship, point=impact_point, normal=impact_normal,
                shield_point=bubble_entry,
                tick_damage=_phaser_damage_for_tick(max_damage=bank.GetMaxDamage(),
                    max_damage_distance=bank.GetMaxDamageDistance(), dist=dist, dt=dt) * PHASER_INTENSITY_SCALE[level],
                ship_instances=ship_instances, weapon_type="phaser",
                radius=combat.weapon_splash_radius(bank, None))        # EFFECT (§5)
            continue
        damage = _phaser_damage_for_tick(..., dist=dist, dt=flush_dwell) * PHASER_INTENSITY_SCALE[level]   # F14
        if damage > 0:                                                 # NB: a flush tick with damage <= 0 (or NaN) does NOTHING, not even beam_contact
            damage_hull = (sys_.GetPowerLevel() != sys_.PP_LOW if hasattr(sys_,"GetPowerLevel") else True)
            combat.apply_hit(target, damage, impact_point, source=ship, normal=impact_normal,
                ship_instances=ship_instances, weapon_type="phaser", hardpoint_weapon=bank,
                damage_hull=damage_hull, shield_point=bubble_entry)    # EFFECT (§5): forget, shields, DamageSystem, dispatch, ET_WEAPON_HIT
```

**Branch facts**

- "Firing" is decided by `_firing` alone.
  - A bank that is lit but still inside its beam-on delay (`_beam_on_countdown > 0`) runs the whole geometry every tick: detect, set, aim, strip, arc, trace, bubble and `beam_contact`.
  - During the delay `accumulate_dwell` returns 0.0 because `IsBeamOn` (WS:912) is False.
  - So sparks and splashes are drawn during the windup.
- **The flush path for a non-firing bank** is a bank that has stopped but still holds banked dwell. It skips `can_detect` and the arc test, but still checks `_same_set`, and delivers the pulse through `apply_hit` with the hull trace.
- On an arc failure the beam is stopped, and the partial pulse **is still delivered on the same tick** with the aim this tick computed.
- `_same_set` failure on the flush path quietly drops the dwell. `take_dwell` already zeroed it.
- **The target's own `IsDead` is gated with `hasattr`.** On a TGObject, `hasattr` is vacuously True. A target class without `IsDead` returns a truthy `_Stub` and records stub telemetry, so the bank treats it as **dead**. This is the same trap as K1 (`has_real_is_dead`, NC:886).
- `GetNumWeapons()` is read once per system, and `GetWeapon(i)` re-reads `_children` live.
- `sys_.StopFiring()` is a **per-tick** effect for every ship whose phaser system is offline or off.
  - `SetAlertLevel` turns phasers off at green and yellow alert (SH:1008-1046).
  - `WeaponSystem.StopFiring` rewrites `_fire_held`, `_held_target`, `_held_offset`, `_target_list = []` and `_last_group_fired`, then calls the mixin `StopFiring` on every bank.
  - That mixin call writes `_firing = False` through a **`NativeWakeField`** (WS:742). WakeField wakes a sleeping owner on every write, even of an equal value (passive_state.py:51-63). So every bank of an off phaser system is woken every tick.
  - This is existing behaviour (§5, §9). K2 must keep calling it.
- **No `forget()` runs inside the scope** except the two inside each `apply_hit`.

### 1.2 `_phaser_aim_point(ship, target)` (HL:1045-1062)

```
probe = getattr(type(ship), "is_using_target_offset", None)              # always ShipClass's (SH:1783)
if callable(probe) and ship.is_using_target_offset():                     # bool(_use_target_offset and _manual_target_offset is not None)
    return target_offset_world(target, ship.GetTargetOffsetTG()), None    # SS:94 (F11 in K1 map); GetTargetOffsetTG copies the manual offset (SH:1746)
target_sub = ship.GetTargetSubsystem() if hasattr(ship, "GetTargetSubsystem") else None   # SH:1743 → _target_subsystem
if target_sub is not None and hasattr(target_sub, "GetWorldLocation"):
    return target_sub.GetWorldLocation(), target_sub                      # SS:935 (below)
return target.GetWorldLocation(), None                                    # OBJ:358 TransformStore
```

**The lock is ship-wide.** `_target_subsystem` is the FIRING SHIP's lock and is never checked against `bank._target`'s ship.

- The writers are:
  - `SetTargetSubsystem` (SH:1744), called from `ai_driver.py:1148`, `target_menu.py:863`, `target_list_view.py`, `ship_death.py:129` (clear) and `warp.py:260` (clear);
  - the init at SH:79.
- `SetTarget` clears the manual offset (SH:1735-1736) but **not** the lock.
- The bank's `_target` is K1's `_target_list[0]` and can differ from the ship's target (K1 map §1.6 quirk).
- So the aim point can be a subsystem on another ship, while the trace, bubble and damage use `target`. Copy this; do not fix it.

**`ShipSubsystem.GetWorldLocation`** (SS:935-947):

```
ship = self._parent_ship
if ship is None: ship = self._climb_to_ship()
if ship is not None: return subsystem_world_position(self, ship)   # memo key (id(sub), id(ship)) — the ship is EXPLICIT here
return self.GetPositionTG()                                         # body-frame local mount returned as a "world" point
```

`target_sub or target`: TGObject defines no `__bool__` or `__len__` (only `_Stub` does, engine/core/ids.py:63), so a subsystem is always truthy.

**In the profile, ~99% of contacts aim at a locked subsystem.** There are 742,680 subsystem `GetWorldLocation` calls for 374,431 contacts, that is 2 per contact: one here and one in `_resolve_bank_aim_world(bank, target_sub)`.

### 1.3 `PhaserBank._strip_emit_position(target_world)` (SS:978-1063)

```
center = self._emitter_world_position()                    # SS:973 → subsystem_world_position(self) — memo key (id(bank), id(None))
length = self.GetLength() if hasattr(self,"GetLength") else 0.0      # _length
if length <= 0.0: return center                            # point emitters (tractors, Length 0)
ship = self._climb_to_ship();  if ship is None: return center
rot = ship.GetWorldRotation() ...;  if not isinstance(rot, TGMatrix3): return center
world_forward = R·_direction ; world_up = R·_up            # FIELDS read directly (not GetDirection/GetUp); NOT the part pose
world_right = world_forward × world_up                     # F5
dx,dy,dz = target_world - center
fwd_proj, right_proj = dot(d, world_forward), dot(d, world_right)    # F6
yaw = 0.0 if (fwd_proj == 0.0 and right_proj == 0.0) else atan2(right_proj, fwd_proj)   # F7
yaw = max(_arc_width_lo, min(_arc_width_hi, yaw))          # F8 — AUTHORED order, NOT sorted (the arc gate sorts)
c, s = cos(yaw), sin(yaw); emit_dir = world_forward*c + world_right*s    # F9
return center + emit_dir * length                          # F10
```

### 1.4 `combat._resolve_hit_point(...)` (CB:86-141): the hull trace

```
if ray_direction is None: return fallback_point, None          # dist <= 1e-6 (or NaN)
iid = ship_instances.get(ship) if ship_instances is not None else None
if iid is None: return fallback_point, None                    # NB: NO sphere fallback when there is no instance (all headless runs)
to_view = frames.view_offset(frames.containing_set(ship))      # FR:144: None unless the target's set is a shifted region of the VIEWED frame
o = frames.shifted(ray_origin, to_view)                        # FR:166: the SAME object when off is None or == (0,0,0)
try: result = host_io.ray_trace_mesh(iid, (o.x,o.y,o.z), (d.x,d.y,d.z), max_dist)
except Exception: result = None                                # stale iid / no model → sphere tier
if result is not None:
    (px,py,pz),(nx,ny,nz),_t = result
    return frames.shifted(TGPoint3(px,py,pz), to_view, -1.0), TGPoint3(nx,ny,nz)
if not sphere_fallback: ...                                    # (True for phasers)
center = ship.GetWorldLocation()
radius = world_radius(ship) if hasattr(ship,"GetRadius") else 0.0     # collisions.py:117: _radius × GetScale() (scale>0 and finite)
entry = ray_sphere_entry(ray_origin, ray_direction, max_dist, center, radius)   # CB:23 (F18)
return (entry, None) if entry is not None else (fallback_point, None)
```

**`host_io.ray_trace_mesh`** (HIO:570-599):

```
if _h is None: return None
t = _h.instance_translation(iid)                               # HB:3674: inst->world_translation_d (double), None if stale
if t is None: return _h.ray_trace_mesh(iid, origin, direction, max_dist)   # stale → the binding THROWS → caught above → sphere tier
rel = (origin[0]-t[0], origin[1]-t[1], origin[2]-t[2])         # double subtract (HIO:369)
hit = _h.ray_trace_mesh(iid, rel, direction, max_dist)
(px,py,pz), normal, dist = hit;  return (px+t[0], py+t[1], pz+t[2]), normal, dist
```

**The binding** (HB:7625-7676) takes `std::tuple<float,float,float>` origin and direction and a `float max_dist`. pybind narrows each double to float.

- It throws on an invalid InstanceId or a missing model handle, and returns None for a null model, a direction with `|d| < 1e-9f`, or `!isfinite(max_dist) || max_dist <= 0`.
- It normalises `d` in float, then calls `renderer::ray_trace_instance_linear(*model, inst->world_linear, o, d, max_dist, &inst->node_overrides)`.
  - The BVH is built lazily per model (ray_trace.cc:~240), a native cache.
  - The trace uses the **last synced pose**. `inst->world_linear` and `world_translation_d` are written by `sync_instance_transforms_from_store()` at the top of each `frame()` (HB:1345, called at HB:1501), by `World::set_world_transform_d` (scenegraph world.cc:47-60), and for split hull parts by `part_severance_check.cc:253-254`.
  - With several ticks a frame, every tick of the frame traces the same stale pose. Copy this exactly by calling the same `g_world`, never by re-syncing.
- `node_overrides` (articulation and severance) are honoured, so a posed or severed part is traced as drawn, independent of the sim's `has_posed_parts`.
- `ray_trace.cc` is compiled with the renderer's default flags: `-O0` in Mark's Debug build, with no `-ffp-contract=off`.

### 1.5 `combat.shields_block(target)` (CB:343-388) and `shield_bubble_entry` (CB:403-482)

`shields_block`:

```
import engine.dev_combat_cheats as _cheats; import App                  # per call
shields = ship.GetShields() if hasattr(ship,"GetShields") else None     # SH:1155 → _shield_subsystem
if shields is None: return False
if not bool(getattr(shields,"HasShields", lambda:1)()): return False     # SS:2100: sum(self._max_shields) > 0.0  (Python 3.11.15: plain left-to-right sum from int 0)
if not bool(getattr(shields,"IsOn", lambda:1)()): return False           # SS:1351 _is_on (ShieldSubsystem default True, SS:2062)
if bool(getattr(shields,"IsDisabled", lambda:0)()): return False         # SS:1199
if bool(getattr(shields,"IsDestroyed", lambda:0)()): return False        # SS:1226
if cloak_shields_suspended(ship): return False                          # CB:580: GetCloakingSubsystem → IsCloaking() or IsDecloaking() (_cloak_state)
if _cheats.disable_npc_shields_active():                                # dev_combat_cheats.py:51: _disable_npc_shields and dev_mode.is_enabled()
    player = App.Game_GetCurrentGame().GetPlayer() (try/except → None)
    if player is None or ship is not player: return False
return True
```

On a non-ship target, `getattr(ship, "GetCloakingSubsystem", None)` and friends go through `TGObject.__getattr__` stubs, so the result is stub-driven. Native must fall back for such targets.

`shield_bubble_entry(ship, ray_origin, ray_direction, max_dist)`:

```
if ray_direction is None: return None
box = _hull_box_for(ship)          # CB:308: ship._shield_hull_box ((cx,cy,cz),(hx,hy,hz)) — set ONLY at realize (HL:6391 via HL:7004/8307); None headless
if box is None: return None
ax..az = h*·SHIELD_ELLIPSOID_AXIS_SCALE                                       # F16
ox,oy,oz = _body_frame_delta(ship, ray_origin)                                # CB:144 (F15)
o = ((ox-cx)/ax, (oy-cy)/ay, (oz-cz)/az)
R = ship.GetWorldRotation(); db = (dir·R.GetCol(0), dir·R.GetCol(1), dir·R.GetCol(2))
d = db/a ; d_len = (Σd²) ** 0.5 ; if d_len < 1e-12: return None ; d /= d_len
b = o·d ; c = o·o - 1.0
if c <= 0.0: return None (inside) ; if b >= 0.0: return None ; disc = b*b - c ; if disc < 0.0: return None
t = -b - disc ** 0.5 ; if t < 0.0 or t > float(max_dist) * d_len: return None
p = ((o+d*t)*a + c) ; p.MultMatrixLeft(ship.GetWorldRotation()) ; p += ship.GetWorldLocation()
```

Headless: no hull box, so this always returns None.

In the capture (§9), `shields_block` was True on 98.8% of contacts (369,792 bubble calls for 374,431 contacts).

### 1.6 Where decide ends and effects begin, per bank

| Step | Pure (K2) | Effect (Python) |
|---|---|---|
| System gate | `_is_offline`, `IsOn` | `sys_.StopFiring()` |
| Idle bank | `IsFiring`, dwell read | `_dwell = 0.0` (deterministic: kernel-owned per §7.6.2) |
| Target dead/None | `IsDead` (has_real_is_dead) | `bank.StopFiring()` |
| Detect | native `can_detect` (+ latch, native-owned) | `bank.StopFiring()` |
| Same set | `_containing_set` identity | `bank.StopFiring()` if firing |
| Aim, strip, dist, arc | all | — |
| Arc fail | `take_dwell` (kernel-owned) | `bank.StopFiring()` |
| Dwell | `accumulate_dwell` (kernel-owned) | — |
| Trace | ray inputs + the trace call (needs `g_world`) | — |
| Shields / bubble | `shields_block`, bubble entry | — |
| Contact | tick damage, splash radius, damage, damage_hull (pure arithmetic) | `beam_contact` or `apply_hit` |

The decision ends after the bubble entry and the damage arithmetic. Everything after it is an effect.

---

## 2. Attributes the geometry reads, and where they are written

"Mirrored" means already a `NativeField` / `NativeRefField` / `NativeWakeField` / `NativeFrozenField` with a row in `mirror.h`, from phase 1a or 1b. "**NEW**" means K2 must add it.

### 2a. Firing ship (ShipClass / ObjectClass)

| Attr | Read by | Type | Write sites | Mirror |
|---|---|---|---|---|
| `_phaser_system` | `GetPhaserSystem` | ref | SH Set*System / SetupProperties | mirrored (SH:24) |
| TransformStore pos/rot | strip, arc, mount, aim | double[3]/[9] | `get_store().set_*` (OBJ:~333-460) | native (TransformStore) |
| `_containing_set` | `_same_set` | ref Set | set membership | mirrored (OBJ:89) |
| `_articulation_poses` → `has_posed_parts` | mount (strip centre) | flag | NC:899 `push_posed_parts`, `PosedPartsField` | mirrored (1b) |
| `_use_target_offset` | `is_using_target_offset` | bool | SH:89 init, 1736 (SetTarget), 1773 (UseTargetOffsetTG), 1781 (set_manual_target_offset) | **NEW** |
| `_manual_target_offset` | same, `GetTargetOffsetTG` | TGPoint3/None (rebound, never mutated) | SH:88, 1735, 1775, 1780 | **NEW** |
| `_target_subsystem` | `GetTargetSubsystem` | ref Subsystem | SH:79, SH:1744 (`SetTargetSubsystem`) | **NEW** (`NativeRefField("Subsystem")`) |

### 2b. PhaserSystem

| Attr | Read by | Type | Write sites | Mirror |
|---|---|---|---|---|
| `_is_on` | `IsOn` | bool | PoweredSubsystem | mirrored (`NativeFrozenField`, SS:1300) |
| condition, radiation, parent fields | `_is_offline` | — | — | mirrored (1b, `weapon_system_offline` in fire_gates.cc) |
| `_children` | `GetNumWeapons`/`GetWeapon` | list | SS init, `AddChildSubsystem` (pushing `NativeRefList`) | mirrored |
| `_power_level` | `GetPowerLevel` (effect args only: intensity, `damage_hull`) | int 0..2 | WS:2330 init, WS:2337 `SetPowerLevel` (clamped) | **NEW** if K2 computes damage; else stays Python |

### 2c. PhaserBank (`_EnergyWeaponFireMixin, WeaponSystem`)

| Attr | Read by | Type | Write sites | Mirror |
|---|---|---|---|---|
| `_firing` | `IsFiring`, `IsBeamOn` | bool | mixin `_fire_effect` WS:892, `StopFiring` WS:903; init WS:2647 | mirrored (`NativeWakeField`, WS:742) |
| `_target` | loop | ref Object | WS:893 (`_fire_effect`), K1 ClearTarget write log, init WS:2648 | mirrored (`NativeRefField`, WS:1271) |
| `_dwell` | `accumulate_dwell`, `take_dwell` | float | WS:330 init, **WS:897 (`_fire_effect`, K1 effect, on the not-firing edge)**, WS:924/926 (accumulate), WS:933 (take), tests/helpers/beams.py:23 | **NEW**: native-owned per §7.6.2, copied back by write log (1b P7) |
| `_beam_on_countdown` | `IsBeamOn` (`<= 0.0`) | float | WS:329 init, **WS:896 (`_fire_effect`, `BEAM_ON_DELAY_S`)**, WS:904 (StopFiring), **WS:955 (`UpdateCharge` `-= dt`, in `sim.weapons` before the step)**, tests/helpers/beams.py:22 | **NEW** `NativeField(float)` |
| `_position` | mount (strip centre) | VEC3 | SS:367, SS:503 | mirrored |
| `_direction`, `_up` | strip (fields directly), arc (`GetDirection`/`GetUp` copies) | VEC3 | SS:372/374, SS:507/515, setters SS:~855/869 | mirrored |
| `_arc_width_lo/_hi`, `_arc_height_lo/_hi`, `_arc_set` | strip clamp (width, authored order), arc (sorted) | float/bool | SS:379-382/423 init, SS:523-529 | mirrored |
| `_length` | strip | float | SS:392 init, SS:545 (`SetProperty`) | **NEW** |
| `_max_damage`, `_max_damage_distance` | damage (effect arithmetic) | float | SS:383/384, SS:533/537 | **NEW** if K2 computes damage |
| `_damage_radius_factor` | `weapon_splash_radius` (effect arg) | float | SS:388, 541, 893 | **NEW** if K2 computes the radius |
| `_parent_ship`, `_parent_subsystem` | `_climb_to_ship` | ref | SS:348/349, attach | mirrored |

Property-side writers (properties.py:565 `_length`, :597/:603 damage, :505 DRF) write the PROPERTY, not the subsystem. They reach the subsystem only through `SetProperty`.

### 2d. Target (`bank._target`, any ObjectClass) and the locked subsystem

| Attr | Read by | Type | Write sites | Mirror |
|---|---|---|---|---|
| `_dead`, `has_real_is_dead` | IsDead gate | bool/flag | OBJ:851, OBJ:~920 `SetDead` | mirrored |
| TransformStore pos/rot | aim (centre), manual offset, bubble, sphere tier | double | — | native |
| `_scale` | `target_offset_world`, `_hull_box_for`, `world_radius` | float | OBJ:227 `SetScale` | mirrored (OBJ:88) |
| `_radius` | `world_radius` (sphere tier) | float | OBJ:221 `SetRadius` | mirrored (OBJ:87) |
| `_containing_set` | `_same_set`, `view_offset` | ref Set | — | mirrored |
| `_shield_subsystem` | `GetShields` | ref Subsystem | SH:57 init, SH:1153 `SetShieldSubsystem` | **NEW** |
| `_shield_hull_box` | `_hull_box_for` | ((3),(3)) or None | **HL:6391 only** (`_cache_shield_hull_box`, realize), plus tests | **NEW** (6 doubles + set flag) |
| `_cloaking_subsystem` → `_cloak_state` | `cloak_shields_suspended` | ref / int | SS:3062-3117 | mirrored |
| render InstanceId | `ship_instances.get` | (index, gen) | HL:6965, 8263 (set); 7053, 7297 (pop); 6656 (clear) | **NEW** (an Object field, or passed per call) |
| `has_posed_parts` | manual-aim `target_offset_world` | flag | — | mirrored |
| class flags | IsDead / GetShields / GetCloakingSubsystem / GetWorldLocation are the stock ones (not stubs or overrides; e.g. `DebrisChunk` overrides `GetWorldLocation`, debris_chunk.py:86, but has no row) | — | — | partly (`has_real_is_dead`, `has_cloak_getter`); **NEW** `has_real_get_shields` |
| locked sub `_position`, `_parent_ship`/`_parent_subsystem` | `GetWorldLocation` | — | — | mirrored |
| locked sub's ship `has_posed_parts` | mount transform | flag | — | mirrored (**check the lock's ship, not `target`'s**) |

### 2e. Target's ShieldSubsystem

| Attr | Read by | Write sites | Mirror |
|---|---|---|---|
| `_max_shields` (list of 6) | `HasShields` (`sum > 0.0`) | SS:2063 init (rebind), **SS:2119 in-place `self._max_shields[f] = v`** (SetMaxShields) | **NEW**: an in-place mutation that bypasses descriptors. Mirror a derived `has_shields` flag pushed from a mutator. |
| `_is_on`, condition fields | IsOn / IsDisabled / IsDestroyed | — | mirrored |

### 2f. Globals and module state

| Name | Value / source | Mirror |
|---|---|---|
| `BEAM_DWELL_FLUSH_S` | 0.5 (WS:303) | **NEW** global |
| `SHIELD_ELLIPSOID_AXIS_SCALE` | `3.0 ** 0.5` (CB:391; libm pow at import) | **NEW** global (push the Python value, ruling G) |
| `PHASER_INTENSITY_SCALE[0..2]` | (0.25, 0.5, 0.5) (HL:954) | **NEW** if K2 computes damage |
| `PHASER_DEFAULT_DAMAGE_RADIUS` | 0.15 (CB:56) | **NEW** if K2 computes the radius |
| `PP_LOW` | 0 (WS:2324) | class constant |
| `disable_npc_shields_active()` | `_disable_npc_shields` (dev_combat_cheats.py:35/65) and `dev_mode.is_enabled()` | **NEW** flag |
| current player | `App.Game_GetCurrentGame().GetPlayer()` | **NEW** per-call handle (it changes only through SetPlayer) |
| viewing set and frames | `frames.viewing_set()` (FR:242: explicit rendered set if a space scene, else `active_set()`); `frame_of` anchors (FR:34) | **NEW**: a per-set view offset (the existing `SetRow.anchor/mapped` is the PROFILE frame and is not equivalent: a mapped set without a profile reads unmapped) |
| `dt` | `TICK_DT` | argument |

---

## 3. Float expressions in the geometry path

All values are Python floats (double). `TGPoint3.__init__` calls `float()`, which is exact for floats. Use `py_pow` for `** 0.5` (`py_math.h`) and `sqrt` only for `TGPoint3.Length` (not on this path). `MultMatrixLeft` sums in `m00*x + m01*y + m02*z` order (math.py:91). Rotation is stored row-major. `GetCol(i)` = `(m0i, m1i, m2i)` (math.py:269).

**F1. Distance** (HL:1239-1242):

```
dx = target_pos.x - emitter_pos.x ; dy … ; dz …
dist = (dx * dx + dy * dy + dz * dz) ** 0.5
```

- The sum is `((dx*dx)+(dy*dy))+(dz*dz)`, then `py_pow(·, 0.5)`.

**F2. Aim unit** (HL:1243):

```
TGPoint3(dx / dist, dy / dist, dz / dist) if dist > 1e-6 else None
```

- With NaN `dist` the result is None, so there is no trace (fallback point) and no bubble.
- `1e-6` is an inline literal.

**F3. Mount** (`_subsystem_world_position`, SS:62-88, and K1 map F10):

```
ship_pos + R·part_transform_point(local)
```

- With `has_posed_parts == 0` it is `ship_pos + R·local` (WG `mount_position`).
- Memo key `(id(sub), id(ship_arg))`:
  - strip centre: `(bank, None)` (SS:976);
  - locked subsystem: `(sub, its ship)` (SS:946);
  - `_resolve_bank_aim_world` origin: `(bank, None)`.

**F4. Manual-aim point** (`target_offset_world`, SS:94-136):

```
o = TGPoint3(px * scale, py * scale, pz * scale)
o.MultMatrixLeft(rot)
pos + o
```

- `scale = float(target.GetScale())`. There is no `<= 0` guard here, unlike `_hull_box_for`.
- WG already has it (`target_offset_world`) for targets without posed parts.

**F5. Strip right** (SS:1024-1028):

```
(f.y * u.z - f.z * u.y, f.z * u.x - f.x * u.z, f.x * u.y - f.y * u.x)
```

- Computed on the WORLD vectors `f = R·_direction` and `u = R·_up`, each a `MultMatrixLeft` of a copy.

**F6. Strip projections** (SS:1031-1035):

```
dx = target_world.x - center.x …
fwd_proj = dx * f.x + dy * f.y + dz * f.z
right_proj = dx * r.x + dy * r.y + dz * r.z
```

**F7. Strip yaw** (SS:1038-1041):

```
yaw = 0.0 if (fwd_proj == 0.0 and right_proj == 0.0) else atan2(right_proj, fwd_proj)
```

- The explicit zero test matters for signed zeros: `atan2(+0.0, -0.0) = π` and `atan2(-0.0, +0.0) = -0.0`. With the test, `yaw` is exactly `+0.0` for any pair of zeros.
- A NaN projection skips the test, so `atan2` returns NaN.

**F8. Strip clamp** (SS:1042-1044):

```
yaw = max(yaw_lo, min(yaw_hi, yaw))
```

- Python min/max, so use `py_max(lo, py_min(hi, yaw))`.
- NaN yaw: `min(hi, NaN)` gives `hi`, then `max(lo, hi)`.
- **Reversed authored width (`lo > hi`) always yields `lo`.** The arc gate sorts its bounds; the strip does not. Copy this.
- `getattr(self, "_arc_width_lo", -math.pi)` always resolves on a ShipSubsystem.

**F9. Strip direction** (SS:1052-1057):

```
c, s = cos(yaw), sin(yaw)
emit_dir = (f.x * c + r.x * s, f.y * c + r.y * s, f.z * c + r.z * s)
```

- libm `cos` and `sin`.

**F10. Emit point** (SS:1059-1063):

```
(center.x + emit_dir.x * length, …)
```

- Early returns of `center` (the memo copy):
  - `length <= 0.0` (a NaN length passes the test and continues);
  - no ship;
  - rotation not a TGMatrix3.

**F11. Arc aim** (`_resolve_bank_aim_world`, WS:105-135; K1 map F7):

```
origin = mount(bank, None)
target_pos = (target_sub or target).GetWorldLocation()
… ** 0.5 … if length > 1e-6 else _resolve_aim_world(ship, None)
```

- **The target is the locked SUBSYSTEM when there is one.** Its `GetWorldLocation` is F3 with key `(sub, ship)`.
- WG `_resolve_bank_aim_world` takes only an Object target, so it needs a variant taking a world point.

**F12. Arc gate** (`_emitter_in_arc`, WS:167-249; K1 map F9):

- Unchanged: the WG port already exists.
- It is called with the LOOP's `ship`, not the bank's own climbed ship. These are the same ship for a real bank.

**F13. Dwell** (WS:917-934):

```
accumulate: if not (_firing and _beam_on_countdown <= 0.0): return 0.0
            if self._dwell > BEAM_DWELL_FLUSH_S: flushed, self._dwell = self._dwell + dt, 0.0; return flushed
            self._dwell += dt; return 0.0
take:       flushed, self._dwell = self._dwell, 0.0
```

- NaN countdown: `<=` is False, so the beam is "not on".
- NaN dwell: `>` is False, so `+= dt` and the dwell stays NaN, which never flushes.
- `BEAM_DWELL_FLUSH_S` is the module constant 0.5.
- The flush condition tests the dwell banked before this tick; the flushed value includes this tick's `dt` (WS:299-301).

**F14. Damage** (HL:957-982, :1289-1306):

```
if mdd <= 0.0: 0.0
elif dist <= mdd: md * dt
else: md * (mdd / dist) * dt
```

- The last branch is `((md * (mdd/dist)) * dt)`. Then `* PHASER_INTENSITY_SCALE[level]`.
- `dt` is `TICK_DT` for `beam_contact`'s `tick_damage` and `flush_dwell` for the pulse.
- `if damage > 0` is an int literal compare; with NaN there is no `apply_hit`.

**F15. Body frame** (`_body_frame_delta`, CB:144-171):

```
dx_w = p.x - pos.x …
(dx_w * m00 + dy_w * m10 + dz_w * m20,  dx_w * m01 + dy_w * m11 + dz_w * m21,  dx_w * m02 + dy_w * m12 + dz_w * m22)
```

- This multiplies by Rᵀ via `GetCol`, which reads the transform store again (a fresh `GetWorldRotation`).

**F16. Bubble** (CB:429-482):

```
box: c*scale, h*scale            (h <= 0.0 on the RAW half-extent → None; scale = float(GetScale()); scale <= 0.0 → 1.0; NaN passes)
a = h_scaled * SHIELD_ELLIPSOID_AXIS_SCALE
o = ((ox - cx) / ax, …)
db_i = dir.x * R.m0i + dir.y * R.m1i + dir.z * R.m2i
d = (db0/ax, db1/ay, db2/az)
d_len = (d0*d0 + d1*d1 + d2*d2) ** 0.5           ; d_len < 1e-12 → None (NaN passes)
d = d / d_len
b = o0*d0 + o1*d1 + o2*d2 ;  c = o0*o0 + o1*o1 + o2*o2 - 1.0
c <= 0.0 → None ; b >= 0.0 → None ; disc = b*b - c ; disc < 0.0 → None
t = -b - disc ** 0.5          # (-b) - py_pow(disc, 0.5)
t < 0.0 or t > float(max_dist) * d_len → None      # max_dist = dist * 1.5
p = ((o0 + d0*t) * ax + cx, …) ; p.MultMatrixLeft(R) ; p.x += pos.x …
```

- **With NaN `c`, `b` or `t`, every compare is False, so it returns a point with NaN coordinates, not None.**
- `R` and `pos` are read from the store three times (in `_body_frame_delta`, in `db` and at the end). They are equal within one call.

**F17. Trace inputs and outputs** (HIO:369, HIO:595-599, HB:7625):

```
rel_i = (origin_i + view_off_i) - t_i      (origin shifted first, only when off is a real shift; FR:174-177: p.x + sign * off[0])
pybind: float(rel_i), float(dir_i), float(dist * 1.5)          # double → float, round to nearest
hit:    px_double = float_px + t[0] ; then shifted back: px + (-1.0 * off[0])
normal: TGPoint3(float nx …)
```

- `off == (0.0, 0.0, 0.0)` is a tuple compare, so `-0.0` counts as zero.
- The trace itself is float32 `renderer::ray_trace_instance_linear`.

**F18. Sphere tier** (CB:32-53, collisions.py:117-142):

```
radius = r * s if s > 0.0 and math.isfinite(s) else r       (r = float(GetRadius()), s = float(GetScale()); DebrisChunk: r)
radius <= 0.0 → None
ox = origin.x - center.x … ; b = ox*dx + oy*dy + oz*dz ; c = ox*ox + oy*oy + oz*oz - radius*radius
c <= 0.0 → return origin (the SAME TGPoint3 object as emitter_pos)
b >= 0.0 → None ; disc = b*b - c ; disc < 0.0 → None
t = -b - disc ** 0.5 ; t < 0.0 or t > max_dist → None
(origin.x + dir.x * t, …)
```

**F19. Splash radius** (`weapon_splash_radius(bank, None)`, CB:64-83):

```
drf = bank.GetDamageRadiusFactor()
if drf > 0.0: float(drf) else PHASER_DEFAULT_DAMAGE_RADIUS
```

**Named constants versus inline literals.**

- Named: `BEAM_DWELL_FLUSH_S`, `BEAM_ON_DELAY_S` (the K1 effect only), `SHIELD_ELLIPSOID_AXIS_SCALE`, `PHASER_INTENSITY_SCALE`, `PHASER_DEFAULT_DAMAGE_RADIUS`, `PP_LOW`, `PP_HIGH`.
- Inline: `1e-6` (HL:1243, :1266-1267, WS:91/100/130), `1.5` (HL:1267, :1277), `1e-12` (CB:453), `1.0` (CB:459), and `0.0` in many compares.
- Ruling G: inline literals are ported verbatim with a comment citing the source line; only named constants are pushed.

---

## 4. Memos and caches touched

| Cache | Where | Key | Cleared | K2 note |
|---|---|---|---|---|
| Python `_mounts` | SS:59 | `(id(sub), id(ship_arg))` | every `forget` (step_memo.py:45) | empty at scope start with native on (P4); filled here |
| native mount memo | `SensorState::mounts` (sensor_state.h:69-91) | `(sub handle, ship_arg handle)` | `combat_memo_clear` on every forget (NC:1758-1764) | **filled by K1 this step**; K2 should read and fill it (same staleness as the native-off path) |
| can_detect answers | native `SensorState` memo (Python `_answers`, sensor_detection.py:705, when off) | `(observer, target)` | forget | K1 asked the same pair this step; the profile shows 63,513 real computes for 374,284 calls (83% hits) |
| lock-break latch | native-owned (1a R7) | pair | never per step | `can_detect` may write it |
| `sensor_occlusion._pair_cache` | sensor_occlusion.py | per set `(now, tick, len(rocks))` | signature change | inside `can_detect` |
| `part_severance._mount_parts` | PS:118 | `(leaf, rounded point)` | never in-step | rigged ships only (filled while `has_posed_parts == 0` too; harmless) |
| `articulation.leaf_for` | ART | `ship._articulation_leaf` | never | **a write on first call**; K1's note applies (native must not trigger it) |
| `ids.implements` | ids.py:148 | (class, name) | never | `frames.containing_set` |
| renderer BVH | ray_trace.cc ~:200-240 | per model | model unload | built lazily on a model's first trace |
| `hit_feedback._last_dispatch_time` | HF | wall clock | — | `apply_hit` → dispatch audio gating (effect); differentials pin it |

**Consequences**

- Within `cb.phasers` nothing that moves a ship runs outside `apply_hit`:
  - `beam_contact` only pushes VFX;
  - `StopFiring` only writes weapon state and stops a sound.
- So memo answers stay valid between banks until a hit. That is also why the mount memo's fill on the flush path (`arc_aim` computed but unused) does not matter for exactness.
- **After an `apply_hit`, every later bank recomputes mounts and detection** (forget). The kernel must re-read the live mirror after each effect record. The 1b P1 model is one record per call, resumed on the live mirror.

---

## 5. Decision-path writes, events and Python callbacks, in order

For each ship in list order:

1. **System offline or off** → `sys_.StopFiring()` (WS:1536). It writes:
   - `_fire_held`, `_held_target`, `_held_offset` (NativeFields, pushed);
   - `_target_list = []` (`NativeRefList`);
   - `_last_group_fired`.

   Then, per bank, the mixin `StopFiring` (WS:901):
   - `_firing = False` (`NativeWakeField`: **wakes the sleeping bank**, then pushes);
   - `_beam_on_countdown = 0.0`;
   - if the bank was firing: `_loop_handle.Stop()` (TGSoundManager) and `_loop_handle = None`.

   No events. **Every tick** for every green- or yellow-alert ship.
2. **Idle bank** → `take_dwell()`: a plain write `_dwell = 0.0`. Profile: ~280 per tick (§9). The kernel can own it and skip unchanged writes, because a plain attribute has no descriptor side effect.
3. **Firing with a dead or None target** → `bank.StopFiring()` (as above, one bank).
4. **`can_detect`.**
   - It can write the native latch.
   - On a fallback (unregistered pair, probe walk) it runs Python, which reads the `sensor_dials`, `dev_mode`, `contact_index` and probe recursion, and can call `log_swallowed`.
   - If the target is undetectable → `bank.StopFiring()`.
5. **Cross-set** → `bank.StopFiring()` if the bank was firing.
6. **Stub telemetry.**
   - `hasattr(target, "IsDead")` / `target.IsDead()` on a class without `IsDead` records stub telemetry (engine/core/stub_telemetry.py) and reads as dead.
   - The `shields_block` / `cloak_shields_suspended` getattrs on non-ship targets go through the same stubs.
7. **Arc fail** → `take_dwell()` write, then `bank.StopFiring()`. **Arc pass** → `accumulate_dwell` write.
8. **Trace** (native, no Python state written; may build the BVH lazily). `log_swallowed` is not called: the `except` is bare.
9. **`shields_block`**: imports (cached), and `App.Game_GetCurrentGame().GetPlayer()` only when the dev cheat is on.
10. **Not a flush tick** → `hit_feedback.beam_contact` (HF:561):
    - **`shields_block(ship)` is evaluated again.**
    - If it is True: `host_io.shield_hit(iid, _mesh_xyz(...), …)` (renderer push; `_mesh_xyz` evaluates `frames.view_offset` again).
    - Otherwise `_hull_impact_visual` (HF:502):
      - `spark_params`;
      - `is_rock`;
      - `host_io.world_to_body` (native);
      - `hit_vfx.spawn(...)` (a Python VFX list).
    - No events. No random draws: `hit_vfx.spawn` and `_hull_impact_visual` draw none in this path.
11. **Flush tick with `damage > 0`** → `combat.apply_hit` (CB:610-913):
    - `forget()` on entry;
    - dev cheats (2× player damage, god mode, immune);
    - `shields_block` (a **third** evaluation);
    - face choice + `shields.ApplyDamage`;
    - `ship.DamageSystem(hull, …)` (can post `ET_SUBSYSTEM_*`, start a death);
    - splash walk over `_iter_subsystems` with `subsystem_world_position(sub, ship)` (F3 memo) and `DamageSystem(sub, …)` per hit subsystem;
    - `hit_feedback.dispatch`: audio (wall-clock gated), smoke, decal, plating wear, camera shake; wrapped in `try`/`log_swallowed`;
    - **`App.g_kEventManager.AddEvent(WeaponHitEvent)`**: synchronous SDK handlers;
    - `forget()` on exit.

    Handlers may StopFiring, StartFiring (K1 re-entry for one system), retarget, TurnOff systems or kill ships. Later banks and ships read all of that live.

**There are no random draws in the decision path.** Randomness is confined to `apply_hit`'s effects (dispatch smoke, decals and so on), and those stay in Python.

---

## 6. Articulation and posed parts

How a pose reaches each beam input:

| Input | Firing ship posed | Target posed |
|---|---|---|
| Strip centre (`mount(bank, None)`) | `part_transform_point` moves the CENTRE onto the posed part (SS:78-80; ART:718) | — |
| Strip direction and up, arc direction and up | **NOT posed**: R·`_direction` and R·`_up` only (SS:1015-1018, WS:156-213). Python ignores the part's rotation for directions. Copy this. | — |
| Locked-subsystem aim point (F3 on the lock's ship) | — | posed if the LOCK's ship is posed. That ship may not be `target` (§1.2). |
| Manual-aim point (F4) | — | `authored_mount_subsystem` scan + `part_transform_point(authored=…)` (SS:116-130; PS:502) |
| Hull-centre aim | — | unaffected |
| Hull trace | — | the renderer's `node_overrides` (drawn pose, synced by `_sync_ship_articulation` at render time), whatever the sim flag says |
| Bubble and sphere tier | — | body box / centre; unaffected by parts |

**Phase 1b's `has_posed_parts`** (`_posed_flag`, NC:842) is 1 while any value in `_articulation_poses` fails `part_pose.is_identity` (1e-9).

- With the flag at 0, `part_transform_point` returns the point itself for every call above. So the identity path in WG (`mount_position`, `target_offset_world`) is bit-exact, signed zeros included (tests/unit/test_native_posed_flag.py).
- K2 must check the flag on:
  1. the firing ship, for the strip centre and the F11 origin;
  2. the **locked subsystem's own ship** (`climb_to_ship` of `_target_subsystem`) when locked;
  3. `target` when Manual Aim is in use.
- Falling back for the bank, or asking Python for one point, matches K1's P2/H choice.
- A severed part (`_parts_detached`) only matters when the flag is 1: `_live_part` returns None for it, and the result is still the point itself.

---

## 7. What K1 already computes that K2 can reuse

| K1 piece | File | K2 use |
|---|---|---|
| `subsystem_world_position(m, sub, ship_arg, use_memo)` | WG:146 | strip centre `(bank, -1)`; lock point `(sub, ship)`; the memo is shared with K1's fills |
| `_resolve_bank_aim_world` | WG:182 | needs a variant whose target is a world POINT (the lock's F3), for `target_sub or target` |
| `_emitter_in_arc` | WG:199-235 | as is (F12) |
| `target_offset_world` | WG:247 | Manual Aim (F4), with the posed-target fallback |
| `containing_set` / `_same_set` logic | WG `containing_set`, `_target_within_range_gu` | `_same_set` without the distance |
| `climb_to_ship_of` | WG:140 | the lock's ship, the strip's ship |
| `weapon_system_offline`, `ship_dead` | fire_gates.h | the system gate; the target IsDead (`has_real_is_dead`) |
| native `can_detect` + memo + latch | sensor_detect.h | the detect gate (memo-eligible: no optional args) |
| `py_pow`, `py_min`, `py_max` | py_math.h | F1, F2, F8, F16, F18 |
| `mult_matrix_left`, `world_location`, `xform`, `dot` | WG anonymous namespace | **move to a shared header**; K2 needs them |
| K1 session and record protocol, write log (P7), `ASK` (H), `RUN_PYTHON` (P2) | k1_fire_control.h, NC:1648 `run_k1` | the K2 driver: resumable, one record per effect |
| class override detection (`_k1_overridden`, NC:736-841) | NC | K2 needs its own list (§8.3 risk 7) |

**K2 needs new:**

- the strip (F5-F10);
- the dwell (F13);
- the trace input and output marshalling (F17) plus a call into the renderer's trace;
- the sphere tier (F18);
- `shields_block` (§1.5);
- the bubble (F15-F16);
- the damage and radius arithmetic (F14, F19), optional.

---

## 8. Risks, a suggested decide/effect split, and existing tests

### 8.1 Suggested kernel shape

Copy K1's resumable session. `combat_k2_begin(ships, dt, use_memo, player, view_offsets…)`, then `combat_k2_next()`, one record per Python effect. Records:

- `SYSTEM_STOP(sys)`: Python calls `sys_.StopFiring()`.
- `BANK_STOP(bank)`: Python calls `bank.StopFiring()`. For an arc failure it is followed by the same bank's `CONTACT` (the partial pulse).
> *Round trips (2026-11-01, spec `2026-11-01-native-combat-round-trips-design.md` §10):* every K2 record now ends `(..., queued, writes)`. On the record path `CONTACT` is a **damage pulse** only: a resting contact (`flush_dwell <= 0`) is queued, in walk order, onto the next record that runs Python (or DONE), and the driver runs it before that record's effect. `SYSTEM_STOP` is emitted only when a bank is firing (below, risk 11).

> *Presentation queue (2026-11-02, spec `2026-11-02-combat-effect-queue-design.md` §10):* records end `(..., writes)` again. A resting contact goes to a per-session native queue and is presented after `DONE` (`combat_k2_drain`): natively when the target is shielded and its instance and view offset are known, else in one Python batch (`_k2_present_batch`).

- `CONTACT(bank, target, ship, impact_xyz, normal_xyz|None, impact_tier, bubble_xyz|None, shields_block, dist, flush_dwell, writes)`:
  - Python does `beam_contact` (with `flush <= 0`) or `apply_hit` (with `damage > 0`), using the record.
  - It must rebuild the exact objects:
    - `impact_tier ∈ {mesh, sphere, fallback, origin}`, because the sphere tier can return the `emitter_pos` object itself and the fallback returns `target_pos`;
    - `target_sub` for nothing (it is not passed on).
- `RUN_PYTHON(ship)` / `ASK(...)`: unrepresentable state:
  - unmirrored target;
  - stub target class;
  - posed ship, lock or target;
  - patched module function;
  - `ship_instances` that is not the session's dict.
- `DONE`.

Writes:

- The kernel writes `_dwell` into a write log, applied before the record's effect, as in 1b P7. Idle zero-writes can be elided when the Python value is already `0.0` (a plain attribute, no descriptor).
- `_beam_on_countdown` is only READ.

Python keeps:

- every `StopFiring` (sound handle, WakeField wake);
- `beam_contact` and `apply_hit`;
- `GetPowerLevel` (or mirror `_power_level`).

`beam_contact` should take the kernel's `shields_block` answer instead of re-evaluating it (nothing runs in between). The spec permits this (§7.4: "each effect part takes the kernel's record").

**The trace** must be the renderer's one compiled function on `g_world`. The combat library does not link the renderer or see `g_world`.

- Pass a `std::function` (or a function pointer + context) from HB into the kernel at `begin`. The pointer would receive `InstanceId`, float origin_rel, float dir, float max_dist, and return `optional<RayHit>` + throw-means-stale.
- Do NOT recompile `ray_trace.cc` with the combat flags. The Python reference calls the renderer's `-O0`, default-contract copy, and a recompiled copy could differ in the last float bits.

### 8.2 Ordering contract

The kernel must reproduce, per bank:

1. the gate order: system, then bank, then None/dead, then detect, then set;
2. the aim point, the strip, the distance, `arc_aim`, then the arc/dwell decision;
3. **the trace BEFORE `shields_block`**, then `shields_block` only when `aim_unit` is not None, then the bubble;
4. the record.

Ships go in list order. Banks go in `_children` order, with the length read once and the elements live.

### 8.3 Risks

1. **The headless differentials cannot see the parts K2 ports.**
   - Every `_advance_combat` in the 1a and 1b differentials passes `ship_instances=None`, so `_resolve_hit_point` returns the aim point (no trace, no sphere tier).
   - No hull box is cached headless, so `shield_bubble_entry` always returns None.
   - The K2 differential needs a host-level scene: a real `g_world` with instances (tests/host style, as in `tests/host/test_mesh_ray_trace.py`, which builds a headless host with a Galaxy) plus `_cache_shield_hull_box`.
   - Otherwise the trace, sphere and bubble code is tested only by unit tests.
2. **Capture finding, not investigated: 62% of phaser traces missed the mesh** (232,137 sphere-tier calls for 374,431 traces in pyprof5).
   - Possible causes (inferred, not checked):
     - a stale ship-wide `_target_subsystem` on another ship;
     - the aim point (a subsystem mount) lying inside the hull, combined with the `dist * 1.5` reach;
     - the stale pose.
   - A bit-exact port freezes whatever this is. Worth a look before K2, and a fix is Mark's call (§5 forbids changing the game).
3. **The lock is not tied to the target** (§1.2). Native must resolve the lock's own ship and its pose flag, not `target`'s.
4. **There is a Python crossing for every contact bank on every tick.** `beam_contact` runs on every non-flush contact tick (16.5 per tick in the capture), so K2 cannot batch. In the capture `beam_contact` + `apply_hit` + `StopFiring` are ~18% of the scope's cProfile time and stay Python (§9). The "own scope down by half" bar rests on the geometry share.
5. **Mirroring gaps.** These fields are **new**:
   - `_target_subsystem`, `_use_target_offset`, `_manual_target_offset` and `_shield_subsystem` on the ship;
   - `_shield_hull_box` and the render InstanceId on the target;
   - `_length`, `_beam_on_countdown` and `_dwell` on the bank;
   - a `has_shields` flag fed from the **in-place** `_max_shields[f] = v` (SS:2119);
   - the NPC-shield cheat flag, the player, and the per-set view offsets.

   `SetMaxShields` is an in-place list write and needs a pushing mutator (§7.1 rule). The audit must cover every one.
6. **`ship_instances` semantics have three outcomes.**
   - No iid gives the fallback point, with **no sphere tier**.
   - A stale iid makes the binding raise, which is caught and leads to the sphere tier.
   - A live iid traces, and on a miss falls to the sphere tier.

   Native must keep "absent" and "stale" apart, and must use the native trace only when the argument IS `session.ship_instances`. Tests pass sentinel dicts.
7. **Python patch points that tests use.**
   - Tests monkeypatch `host_io.ray_trace_mesh` (tests/unit/test_combat_hit_resolution.py, tests/integration/test_phaser_damage_applied_through_apply_hit.py and others), `combat._resolve_hit_point` (tests/unit/test_manual_aim.py:214) and `combat.apply_hit` (17 sites).
   - A native K2 bypasses the first two.
   - It needs K1-style override detection: an identity check of the module functions and of the bank and ship methods at K2 entry, with whole-step or per-bank fallback. These tests run with the switch off by default.
8. **Signed zeros and NaN.**
   - F7's explicit zero test.
   - F8's unsorted clamp: a reversed width always emits at `lo`.
   - F16 returns a NaN point, not None.
   - F2 NaN gives None; F14 NaN gives no hit and NaN `tick_damage`.
9. **Two clocks of pose.** The sim reads the TransformStore at this tick; the trace reads `g_world` as of the last `frame()` sync, so it can be several ticks stale in a catch-up frame. Native must call the same `g_world` at the same point in the order, never re-sync.
10. **`view_offset` depends on the viewing set.** That is the player's set or the explicit rendered set (FR:242), which handlers can change (SetPlayer, ChangeRenderedSet). It is almost always the identity: one set, no shift. Pass per-set offsets at begin, and re-check the viewing set identity on resume, or fall back when the target's set is not the viewed set.
11. **StopFiring on off systems every tick** wakes every bank of that system (equal-value WakeField write). This is pre-existing behaviour. K2 must emit `SYSTEM_STOP` exactly as often; it must not skip the call because the system is "already stopped". *Round trips (2026-11-01): when every bank is idle the stop is logged writes instead of a record (the system's five fields, a new `[]`, each bank's two), still every tick and still waking; a firing bank keeps the `SYSTEM_STOP` record.*
12. **`shields_block` on non-ship targets** goes through `_Stub` chains with telemetry. Fall back (needs a new class flag, `has_real_get_shields` or "is ShipClass").
13. **The dwell is written by two owners.** K1's `_fire_effect` (Python, WS:897) resets it to 0 on the lit edge; K2 accumulates and takes it. `tests/helpers/beams.py` writes `_dwell` and `_beam_on_countdown` directly. A native-owned dwell needs Python's copy to stay authoritative for those writers (a NativeField push) or a write log.

### 8.4 Existing tests on this path

All are focused; none were run for this map.

| File | Pins |
|---|---|
| tests/integration/test_phaser_damage_applied_through_apply_hit.py (6) | held fire drains the target's shield; drift out of arc auto-stops; the hit point comes from `host_io.ray_trace_mesh` (monkeypatched, sentinel iid); the render endpoint is clipped to the mesh; per-frame flash on a bare hull; per-frame splash on a raised shield (`beam_contact`) |
| tests/integration/test_phaser_target_drifts_out_of_arc.py | a target drifting astern stops every forward bank (arc-fail path) |
| tests/integration/test_weapon_cross_set_interim_guard.py (7) | cross-set and setless targets get no damage and stop the bank (`_same_set`) |
| tests/unit/test_weapons_disabled_blocks_fire.py | `_advance_combat` stops disabled, sensors-offline and powered-off systems (system gate + `can_detect`) |
| tests/integration/test_disruptor_fire_and_damage.py | the shared `_advance_combat` path |
| tests/unit/test_strip_emit_position_arc.py (6) | emit on the sphere of radius Length; faces the target; yaw clamps to the width; Length 0 collapses to the mount; `SetProperty` mirrors up and width |
| tests/unit/test_phaser_arc_handedness.py (3) | pitch gate; starboard banks; the strip emit faces the target |
| tests/unit/test_bank_aim_world.py (5), tests/unit/test_arc_gate.py (11) | F11, F12 |
| tests/unit/test_manual_aim.py | `_phaser_aim_point`: lock, centre, manual offset rotated and scaled; `_advance_combat` routes damage at the manual offset (spies on `_resolve_hit_point`) |
| tests/unit/test_target_offset_articulation.py | `target_offset_world` on posed targets; wings-down exactness |
| tests/unit/test_combat_hit_resolution.py (10) | `ray_sphere_entry` cases; `_resolve_hit_point` tiers: mesh, sphere on miss, fallback, no direction, no instances |
| tests/unit/test_shield_bubble_entry.py, tests/unit/test_shield_bubble_wiring.py (10), tests/unit/test_shield_facing_from_bubble_entry.py | the bubble geometry; `shields_block` cases (on, off, destroyed, unshielded, empty slot); splash anchor; damage on the hull point; the beam stops at the bubble only while shields hold |
| tests/unit/test_cloak_transition_vulnerable.py, tests/unit/test_shield_display_matches_blocking.py | `shields_block` during a cloak transition; HUD parity |
| tests/unit/test_rock_shield_collision.py | `beam_contact` on rocks |
| tests/unit/test_phaser_damage_falloff.py | F14 plateau and R/d |
| tests/oracle/test_beams.py (B1-B9, F1) | measured BC timing: 1.156 s windup, 0.53 s quanta, rates by intensity, R/d falloff, stop at zero charge, Fed single fire (headless: no trace, no bubble) |
| tests/unit/test_energy_weapon_update_charge.py | no drain during the beam-on delay (`_beam_on_countdown`) |
| tests/integration/test_native_k1_differential.py | ET_WEAPON_HIT payloads (damage, hit point, normal by `.hex()`) of phaser hits from `cb.phasers` with K1 on vs off. **The template for a K2 differential**, but headless: no trace and no bubble. |
| tests/integration/test_native_combat_step_differential.py | the 1a step differential (fired and hit events in order) |
| tests/host/test_combat_step_sensor_answers.py, tests/unit/test_mount_position_step_answers.py | memo semantics across the step |
| tests/host/test_mesh_ray_trace.py, native/tests/renderer/ray_trace_test.cc | the trace binding and algorithm on a real Galaxy and synthetic models |
| tests/host/test_render_space_feeds.py | `_advance_combat` and `_resolve_hit_point` with real instances (view-space shift) |
| native/tests/combat/weapon_geometry_test.cc | WG pieces K2 will reuse |

No test pins by name: `take_dwell`, `accumulate_dwell` (except via oracle timing), `PHASER_INTENSITY_SCALE` (except the oracle rates), the strip's reversed-width clamp, F7's zero test, or the NaN bubble.

---

## 9. Per-tick cost composition (inferred)

**Source:** `~/Documents/dauntless-perf/pyprof5-cs64-20261030-2334.cb.phasers.prof`.

- Python step, code equal to main `a0d81c7d4` (pre-1a): 64 AI ships + player, 1,500 frames at the 15-tick catch-up cap.
- Ticks ≈ `GetPhaserSystem` calls ÷ 65 ships = 1,440,617 ÷ 65 ≈ **22,160 ticks** (derived).
- cProfile inflates times about 2× (74.5 s ÷ 22,160 = 3.4 ms a tick, against 1.61 ms unprofiled in C-238, SIG-158). **Shares are what matter.**

**Counts per tick (derived from call counts ÷ 22,160)**

| Quantity | Calls/tick | Source |
|---|---|---|
| ships walked | 65 | `GetPhaserSystem` |
| systems reaching the offline/on gate | ~57 | `_is_offline` (minus 63,513 from sensors) |
| systems stopped (off or offline) | ~4.0 | `WeaponSystem.StopFiring` 89,223 |
| bank visits | ~297 | `IsFiring` 6,582,226 |
| idle-bank `take_dwell` | ~280 | 6,207,408 |
| **contacts (full geometry)** | **~16.9** | `_phaser_aim_point` / `_resolve_hit_point` / `ray_trace_mesh` 374,431 |
| of which flush-path (non-firing) | ~0.007 | aim 374,431 − arc 374,284 |
| trace misses → sphere tier | ~10.5 (62%) | `ray_sphere_entry` 232,137 |
| `shields_block` True → bubble computed | ~16.7 | `shield_bubble_entry` 369,792 |
| `beam_contact` | ~16.5 | 365,655 |
| **`apply_hit` (pulses)** | **~0.40** | 8,776 (1 per ~43 contacts) |
| `GetWorldRotation` (a new TGMatrix3 from the store) | ~124 (≈7.3 per contact) | 2,749,754: bubble 2, body delta 1, mount ~1.4, strip 1, arc 2 |
| mount recomputes (memo misses) | ~23 | `_subsystem_world_position` 508,640 |

**Share of the scope's cProfile cumulative time (74.5 s)**

| Group | Calls | Time | Share | Notes |
|---|---|---|---|---|
| `_resolve_hit_point` | — | 9.49 s | 12.7% | native trace 4.17 s (5.6%, ~11 µs a trace incl. the binding, Debug `-O0` renderer); `view_offset` 2.43 s |
| `shield_bubble_entry` | — | 9.42 s | 12.6% | |
| `_phaser_aim_point` | — | 9.38 s | 12.6% | almost all the lock's mount |
| `beam_contact` (effect) | — | 6.58 s | 8.8% | its own `shields_block`, `_mesh_xyz`/`view_offset`, `shield_hit` |
| `_emitter_in_arc` | — | 6.01 s | 8.1% | |
| `_is_offline` | — | 6.01 s | 8.1% | mostly the per-ship gate's WeaponSystem aggregate over children |
| `_strip_emit_position` | — | 5.93 s | 8.0% | |
| `apply_hit` (effect) | — | 5.03 s | 6.8% | |
| `shields_block` | 748,862 | 3.85 s | — | 2 per contact |
| `can_detect` | — | 3.23 s | 4.3% | |
| `GetWeapon` | 6.9 M | 3.73 s | — | the loop + the `IsDisabled` aggregate |
| `_resolve_bank_aim_world` | — | 2.03 s | 2.7% | |
| `StopFiring` | — | ~2.1 s | — | both kinds |

**Inferred composition of the unprofiled 1.61 ms per tick (Python reference)**

- **Idle walk** (system gates + ~280 idle banks + ~4 system stops): **~0.22-0.25 ms**. The measured quiet-scene `cb.phasers` is 0.224-0.246 ms a tick (SIG-155, SIG-159), where nobody fires. This is pure gate work plus `StopFiring`, a good native target.
- **Per contact: ~80 µs** = (1.61 − 0.24) ÷ 16.9 (inferred). About 80% of it is geometry and gates; about 20% is effect (`beam_contact`, or `apply_hit` once per ~43 contacts).
- **What stays in Python after K2:**
  - `beam_contact` per contact;
  - `apply_hit` per pulse;
  - `StopFiring` calls;
  - the record crossing;
  - the native trace (≈0.17 ms a tick at ~10 µs each in Debug, unless `ray_trace.cc` is optimised, which changes its float results; see the trace paragraph in §8.1).
- On these shares the "own scope down by at least half" bar (§7.6.6) is plausible but not certain. This is inferred and needs a paired capture.

**Out of scope, but the same cost again.** `_build_phaser_beam_render_data` (HL:2416, `cb.render_data`) recomputes, once per frame, for every firing bank:

- the aim point;
- the strip;
- the distance;
- `shields_block`;
- the bubble;
- the trace (`_beam_endpoint`, HL:2267, bubble first, then the trace);

with cross-set shifts (HL:2303-2384). It runs outside the step memo, after tractors and the camera. It cannot reuse K2's records as they stand (different time and frame), but it can reuse K2's kernels (a "K2-render" pass).
