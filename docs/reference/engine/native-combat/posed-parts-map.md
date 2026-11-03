> **Implemented 2026-11-01** on branch `ws/combat-posed-parts`, tip `9006951a8` (before docs). Outcome, counts and rulings: `docs/superpowers/specs/2026-11-01-native-combat-posed-parts-design.md` §10. The map below is the pre-build snapshot and is not updated (apart from the `steer_point_native` rename).

> Snapshot map written 2026-11-01 at commit `1c1ab9a12` (branch `ws/combat-posed-parts`, identical to `project/combat_threading`). Input to workstreams **B** (measure before moving more) and **C** (close the routine fallbacks; posed ships first) of `docs/superpowers/specs/2026-11-01-threaded-weapons-combat-roadmap.md`. Line numbers drift; re-check one before relying on it. Model documents: `k1-fire-control-map.md`, `k2-beams-map.md`, `k3-k4-map.md`. Nothing was run except a parse of the two K3+K4 profiler logs (C-246, C-247) in `~/Documents/dauntless-perf/`. Anything not read directly off the code is marked **inferred**.

# Posed parts + timing seams — code map

File abbreviations:

| Abbrev. | File |
|---|---|
| **HL** | `engine/host_loop.py` |
| **NC** | `engine/appc/native_combat.py` |
| **ART** | `engine/appc/articulation.py` |
| **AP** | `engine/appc/articulated_part.py` |
| **PP** | `engine/appc/part_pose.py` |
| **PS** | `engine/appc/part_severance.py` |
| **PHP** | `engine/appc/physical_parents.py` |
| **PROP** | `engine/appc/properties.py` |
| **SS** | `engine/appc/subsystems.py` |
| **WS** | `engine/appc/weapon_subsystems.py` |
| **PR** | `engine/appc/projectiles.py` |
| **SHIPS** | `engine/appc/ships.py` |
| **MATH** | `engine/appc/math.py` |
| **LOOP** | `engine/core/loop.py` |
| **TB** | `engine/core/transform_buffer.py` |
| **FP** | `engine/core/frame_profiler.py` |
| **WG** | `native/src/combat/src/weapon_geometry.cc` |
| **BG** | `native/src/combat/src/beam_geometry.cc` |
| **PG** | `native/src/combat/src/projectile_geometry.cc` |
| **GI** | `native/src/combat/src/geometry_internal.h` |
| **K1C / K2C / K3C** | `native/src/combat/src/k1_fire_control.cc` / `k2_beams.cc` / `k3_projectiles.cc` |
| **MIR** | `native/src/combat/include/dauntless/combat/mirror.h` |

**Corrections to the brief, checked against the code:**

- **The pose is NOT render state.** It is Python sim state in `ship._articulation_poses`, written once per GameLoop tick by `articulation.tick_ship` (LOOP:157, inside `gl.subsystems`). The renderer only receives a float32, model-unit copy afterwards (HL:9962-9964, in `sim.render_xforms`). Nothing in combat reads the renderer's copy for mounts. So the pose CAN be mirrored bit-exactly (§2).
- **All of a frame's GameLoop ticks run before all of its weapon/combat ticks.** `advance_ticks` runs `_tick_gameloop` N times (HL:12349-12350, TB:80-87); the `sim.weapons`/`sim.combat` pair then runs N times (HL:12611-12627). So every combat tick of a frame reads the pose (and the ship transforms) left by the frame's **last** GameLoop tick. Python and native read the same dict at the same moment, so this does not affect parity. It does matter for any future pipelining (§5 R9).
- **`sim.weapons` and `sim.combat` are per-tick rows, but the profiler and its doc say they run once per frame.** `PER_TICK_ROOTS` names only `sim.gameloop` (FP:111-119), and `frame-profiler.md` (the "`*` marks per-tick rows" bullet) says `sim.weapons`/`sim.combat` "run once per frame". Both are stale: since the per-tick loop at HL:12611, each runs `_sim_ticks_this_frame` times (the logs' `calls` column shows 3). The perf register already divides them by ticks per frame (SIG-157 method), which is right for them. It is wrong for the rows that really run once per frame (§7).
- **The "~4 ms per tick outside combat and AI" (roadmap §2/§4 B) includes `gl.motion`, `gl.subsystems` and `sim.weapons`.** In C-246/C-247 those three come to 2.59 ms/tick. The residual of `sim` after `sim.combat + gl.ai + gl.motion + gl.subsystems + sim.weapons` is **~1.75 ms/tick**, not ~4. About 1.1 ms of it is once-per-frame work spread across ~3.4 ticks (§7).
- **The arc and strip DIRECTIONS of a bank on a posed part are not posed.** Only the mount POINT follows the part. `_emitter_in_arc` (WS:167) and `_strip_emit_position` (SS:1016-1020) rotate `_direction`/`_up` by the ship rotation only. A native port must copy this, not "fix" it.
- **The only stock rig is the Bird of Prey** (two parts, `left wing` / `left wing01`, HardpointOverrides around `hardpoint_overrides.py:440-454`, under `DAUNTLESS_ENV >= 1`). Its red pose is identity; cruise, yellow and warp swing the wings ±45°. Mod hulls can add rigs (hardpoint `__parts__`).

---

# Part 1 — Posed parts (workstream C)

## 1. What a posed ship or target changes, per kernel

A ship is **posed** when `native_combat._posed_flag(ship)` is 1 (NC:1056-1081). That means some value in `ship._articulation_poses` fails `part_pose.is_identity` (PP:87-91, eps 1e-9 on every R and t element). The flag is mirrored as Object `has_posed_parts` (MIR:52, 138; pushed from `_flags` NC:1100-1101 and `push_posed_parts` NC:1118-1127).

There is one primitive. `articulation.part_transform_point(ship, point, part=None, *, authored=True, prop=None)` (ART:718-756) returns `point` itself unless `_live_part` (ART:774-809) names a posable, non-detached part whose current pose is not identity. In that case it returns `part_pose.apply(pose, point)` (PP:72-75). It is reached through two transforms only:

- **Mount** — `subsystems._subsystem_world_position(sub, ship)` (SS:62-88): `ship_pos + R_ship·part_transform_point(ship, local, prop=property_of(sub))`. No scale.
- **Target offset** — `subsystems.target_offset_world(target, offset, mount_sub=_RESOLVE)` (SS:94-136): `pos + R_target·(scale · part_transform_point(target, offset, authored=mount_sub is not None, prop=property_of(mount_sub)))`. `mount_sub` is `part_severance.authored_mount_subsystem(target, offset)` (PS:502-514) when not given.

### 1.1 K1 fire control (`cb.held_weapons`, and StartFiring's system sessions)

| Computation | Python (operand order) | Posed input | Native today | Fallback line |
|---|---|---|---|---|
| Bank arc aim origin | `_aim_in_arc` WS:804-814 → `_resolve_bank_aim_world(bank, target)` WS:105-135: `origin = bank._emitter_world_position()` (SS:975-978 → mount); `d = target_pos - origin`; `len = (dx*dx+dy*dy+dz*dz) ** 0.5`; `d/len` | **firing ship** (mount) | WG:138-151 → `subsystem_world_position` WG:102-114 → `mount_position` WG:77-90 | WG:87 throws; never reached because prescan K1C:438 `PosedShip` → RUN_PYTHON |
| Arc test | `_emitter_in_arc` WS:167: `R_ship·_direction`, `R_ship·_up`, right = fwd×up (world), atan2 / asin | **not posed** (directions use the ship R only) | WG:169-205 | — |
| Pulse muzzle + lead | `_solve_pulse_launch_direction` WS:509-570: `aim = _resolve_torpedo_aim_point(cannon, target)`; `muzzle = cannon._emitter_world_position()` | firing ship (muzzle); **target** (aim, when the cannon has `_target_offset`) | WG:272-311 | K1C:438 (ship), K1C:473 `PosedTarget` (any target-list entry that is posed, for pulse/torpedo systems) |
| Tube aim point | `_resolve_torpedo_aim_point` WS:3064-3077 → `target_offset_world(target, offset)` (mount_sub resolved by scan) | **target** | WG:230-240 → `target_offset_world` WG:217-226 | WG:221 throws; prescan K1C:473 → RUN_PYTHON |
| Tube cone | `_in_torpedo_cone` WS:3080: `mount = tube._emitter_world_position()`; basis = R_ship·(d, r, d×r_local) | firing ship (mount only; basis not posed) | WG:244-268 | K1C:438 |
| Range gate, detect gate | `_target_within_range_gu` (ship centres), `can_detect` (centres) | — | WG:315; sensor_detect | — |
| Fire effects (spawn point) | `_spawn_projectile` WS:575 (`spawn_pos = emitter._emitter_world_position()` WS:602), `_spawn_torpedo` WS:3503 | firing ship | **always Python** (FIRE record → `_fire_effect`, NC:2306-2308) | — |

K1's prescan rejects a posed firing ship for **every** held system (K1C:438). It rejects a posed target only for pulse and torpedo systems (K1C:470-473). A phaser system's target is aimed at its centre in K1, so a posed phaser target never matters there.

### 1.2 K2 phaser beams (`cb.phasers`)

The Python loop body is `_phaser_step_bank` (HL:1100-1205).

| Computation | Python | Posed input | Native | Fallback |
|---|---|---|---|---|
| Strip centre | `bank._strip_emit_position(target_pos)` SS:~1000 → `center = self._emitter_world_position()` | **firing ship** | BG:79-118 (`strip_emit_position`) → WG `subsystem_world_position(bank, -1)` | prescan `ship_why` K2C:315 `PosedShip` → RUN_PYTHON for the whole ship |
| Strip direction/up/yaw | SS:1016-1050: R_ship·`_direction`, R_ship·`_up` | **not posed** | BG:89-117 | — |
| Aim point, Manual Aim | `_phaser_aim_point` HL:1056-1059 → `target_offset_world(target, ship.GetTargetOffsetTG())` | **target** | BG:57-59 → WG `target_offset_world` | WG:221 throws → ASK `aim_point` (K2C:549-557) |
| Aim point, subsystem lock | HL:1060-1062 → `target_sub.GetWorldLocation()` = `subsystem_world_position(lock, its ship)` (SS:937-948) | the **lock's own ship** (`climb_to_ship` of the lock, which may not be `target`) | BG:62-72 → `mount_position` on the lock's ship | WG:87 throws → ASK `aim_point` (K2C:556) |
| Arc aim origin | `_resolve_bank_aim_world(bank, target_sub or target)` HL:1160 | firing ship (origin); point = aim point above | K2C:584-594 → WG `_resolve_bank_aim_world_at` | covered by `PosedShip` |
| Hull trace | `combat._resolve_hit_point` → renderer `ray_trace_instance_linear(..., &inst->node_overrides)` (k2-beams-map §1.4) | the renderer's drawn pose (float32, pushed by `_sync_ship_articulation` after the frame's combat; §2.4) | same renderer call both paths | — (no parity issue: both paths call the same renderer) |

SIG-163 (4): a 9-ship, 600-tick host differential gave 80 ship fallbacks, all `posed_ship`, and every ASK was `aim_point`.

### 1.3 K3 torpedoes (`cb.projectiles`)

| Computation | Python | Posed input | Native | Fallback |
|---|---|---|---|---|
| Steer point (offset shot) | `_steer_point` PR:1065-1100: the `_mount_key` cache (PR:1094-1099, `authored_mount_subsystem` once per (target, offset)) → `target_offset_world(target, offset, key[4])` → `_shifted(..., off)` | **target** | PG:192-207 `steer_point_native` | PG:310: `if (mount_sub == kRefUnrepresentable \|\| tr.has_posed_parts) return ask;` → ASK `steer_point` (K3C:298-308); Python answers with `_steer_point`, and `_mount_key` is pushed into the row. *Since posed parts, posed targets steer natively; since round trips (2026-11-01) an unattributed shot is attributed natively too (`authored_mount_subsystem`, `_mount_key` written at DONE), and the ASK stays only for `kMountUnknown` or a non-ShipClass target.* |
| Steer point (no offset) | PR:1091-1093: target centre | — | PG:196-198 | — |
| Narrow phase / hit point | `sphere_hit`, bubble, `_resolve_hit_point` (renderer trace, as K2) | renderer drawn pose only | as Python | — |

**Task 7 (Mark, 2026-11-01): a picked spot (no mount) is baked at launch** (`projectiles._bake_offset` → `_baked_offset`, pushed) and steered at `body_point_world(target, baked)` with no part pose, natively (K3 ASK `unbaked` only when the bake is not for this target/offset); a mount still follows its part every tick. The rows above predate it.

SIG-165 (3): the only K3 ASK that fires in the differentials is `steer_point` (posed target, mount attribution, cross-region). Per k3-k4-map §A, every visible steer in the pyprof capture carried a target offset, so a posed target ASKs **per guided torpedo per tick**.

---

## 2. Where the pose comes from

### 2.1 Who computes it, in what frame

- **Data.** A part's authored per-state poses live on `ArticulatedPartProperty` templates (AP; e.g. `SetStatePose` in `hardpoint_overrides.py:443-454`). They are snapshotted per hardpoint leaf by `articulated_part.snapshot_for_leaf`, which bumps `_GENERATION` (AP:168, 190, 199). `rig_for(leaf)` (ART:109-114) reads that snapshot.
- **Frame and units.** A pose is `(R, t)`: R is a tuple of 3 ROW tuples, t a 3-tuple, **ship units** (model/100), body frame. It is the part node's parent space, which is model space because Scene Root is identity (ART:54-61, PP:3-12). `part_pose.apply` draws a point x at `R·x + t` (PP:72-75).
- **Who writes it.** Only `articulation.py`:
  - `tick_ship(ship, dt)` (ART:416-502), once per GameLoop tick per non-rock ship, called from `_update_ship_subsystems` (LOOP:136-157) inside `gl.subsystems` (LOOP:109-110). Per part it picks `target_pose(part, state_for(ship))` (or the dev override). It starts or continues a transition with u += dt/duration and writes `poses[name] = part_pose.interpolate(pose0, target, anchor, u)` (ART:497), or `poses[name] = target` exactly at u >= 1 (ART:493). These are IN-PLACE writes into the dict. The first tick rebinds `ship._articulation_poses = {}` (ART:469).
  - SPV `force_pose` / `force_part_pose` / `force_state_poses` → `_store_forced` (ART:281-379): they REBIND the dict at panel event edges (dev only; the sim is frozen while the SPV is open).
  - No other writer exists. A grep of `engine/`, `engine/ui/` and `tools/` finds only readers and docstrings.
- **The interpolation math** (`_to_quat`, `_slerp` with acos/sin, `_from_quat`; PP:114-168) runs in Python. The native side never needs to recompute it: it only needs the resulting doubles.

### 2.2 When, relative to the combat step

Per render frame (HL):

```
HL:12301  frame_profiler.mark("sim")
HL:12349  advance_ticks(_xform_buf, N, _tick_gameloop, ...)      # N x GameLoop.tick (TB:80-87)
            LOOP:54   gl.ai          (StartFiring -> K1 system sessions; reads LAST tick's pose)
            LOOP:109  gl.subsystems  -> tick_ship -> poses written, push_posed_parts
HL:12493  sim.input (manual_aim.update HL:12584-12589: Manual Aim pick pulled back to rest with the live pose)
HL:12611  for _tick_i in range(N):
HL:12616      sim.weapons
HL:12618      sim.combat  -> cb.projectiles (K3), cb.held_weapons (K1), cb.phasers (K2)
HL:12898  sim.render_xforms -> _sync_instance_transforms -> _sync_ship_articulation (HL:10120)
```

- Every `cb.held_weapons` / `cb.phasers` / `cb.projectiles` in the frame reads the pose after the frame's **last** `tick_ship`. Python and native read the same dict, so there is no skew between them.
- K1 **system** sessions opened by `StartFiring` (WS:1536 `native_combat.k1_system`) run inside `gl.ai`, BEFORE that tick's `tick_ship`. They read the previous tick's pose, which again is the same for both paths.
- Nothing writes the pose during the combat step. `sever` (PS:449-476) changes `_parts_detached`, not the poses (§3.3).

### 2.3 How Python reads it

Python reads the dict directly: `pose_for_part(ship, part)` = `ship._articulation_poses.get(name, IDENTITY)` (ART:232-246). No `host_io` call and no cached matrix are involved. A missing name reads IDENTITY. The mount path reads it through `part_transform_point` (ART:753). `_posed_flag` reads `ship.__dict__["_articulation_poses"]` values (NC:1075-1081).

### 2.4 The renderer's copy (do not mirror from it)

`_sync_ship_articulation` (HL:9904-9968) is documented read-only on game state. It runs per frame in `sim.render_xforms`, **after** the frame's combat ticks. It pushes `part_pose.matrix4_model(pose, 0.01)` (PP:171-179: translation ×(1/0.01)) to `set_instance_node_transform`. The renderer stores this as `glm::mat4`, which is **float32** (`renderer/frame.h:347` `std::unordered_map<int, glm::mat4>* node_overrides`). It is also change-guarded on the 6-tuple. The node transform is **not** render-interpolated: the live sim pose is pushed, and interpolation applies only to ship world transforms via `TransformBuffer`.

**Verdict:** the pose is per-tick sim state, in doubles, owned by Python. It can be mirrored bit-exactly by pushing those doubles from Python at the existing push points (`push_posed_parts`). It must NOT be read from the renderer's node overrides: they are float32, in model units, and one frame stale relative to the combat that reads them.

---

## 3. The mount → part mapping

### 3.1 The resolution chain (`_live_part`, ART:774-809)

1. `names = posed_part_names(ship)` (ART:202-219): the rig's part names in rig order, then any OTHER key of `_articulation_poses`, **sorted** (SPV-forced names). An empty tuple → None, which means identity.
2. If no `name` was given:
   - authored point with a `prop` → `physical_parents.part_for_property(leaf, prop, point)` (PHP:70-85):
     - `explicit_parent(leaf, prop)` (PHP:52-57): the SPV preview overlay `_preview[leaf][prop name]`, else `prop.GetPhysicalParent()` (PROP:75-80).
     - If that names a part that exists (`not is_missing`, which checks `part_boxes_for(leaf)`), use it.
     - Else (with a one-time `sys.stderr` warning, PHP:79-84) `part_severance.part_for_mount(leaf, point)`.
   - authored point, no prop → `part_for_mount(leaf, point)` (PS:118-163): cache `_mount_parts[(leaf, round(v, 6) per axis)]`. On a miss, `host_io.model_nearest_part(model, point)` if the leaf's model is known (cached when it answers). Otherwise the box rule `part_for_point` (PS:76-110), which is **not cached**.
   - non-authored point (Manual Aim pick) → `part_for_point` box rule.
3. `is_detached(ship, name)` (PS:274-275: `name in ship._parts_detached`) → None.
4. `name in names` → the name, else None.

Then `pose = pose_for_part(ship, name)`. If `is_identity(pose)` the point is returned unchanged; otherwise `apply(pose, point)` (ART:753-756).

`property_of(sub)` (PHP:40-49) is `sub.GetProperty()` when the property's CLASS defines `GetPhysicalParent`, else the object itself if its class does, else None.

### 3.2 Rigged vs unrigged; severed parts

- **Unrigged hull, nothing forced:** `names == ()` → identity, and `_posed_flag` is 0 (the dict is absent or empty). That is every ship except a rigged one.
- **Unrigged hull with an SPV-forced name:** `names` = the forced keys. Dev only.
- **Rigged ship:** the rig's parts. `tick_ship` caches a `_rigless_key` for ships with no rig (ART:444-454). The renderer flags rigged instances at realize (`_mark_rigged` HL:6823-6833; layered damage keeps their hits on the part struck).
- **Severed part:** `_live_part` returns None, so a mount on a severed wing reads its **rest** point. Its pose is still in the dict, so `_posed_flag` stays 1. `part_for_live_point` (PS:166-226) deliberately does NOT skip detached parts (attribution of the hit that severs it).
- **Explicit physical parents in stock data:** the BoP's `Impulse Engines`, `Sensor Array` and `Warp Engines` are `SetPhysicalParent("birdofprey")` (`hardpoint_overrides.py:430-438`). These are system parents. A child at the same point may resolve differently (relevant to §3.4).

### 3.3 Mutation sites — what must push (the "a field the kernel reads MUST push" rule)

| Input | Written at | Today's push | Needed for a native posed path |
|---|---|---|---|
| `ship._articulation_poses` (rebind) | ART:469 (first tick), ART:376 (`_store_forced`) | `PosedPartsField.__set__` → `push_posed_parts` (NC:662-685) | push the pose table |
| `ship._articulation_poses[name] =` (in place) | ART:493, ART:497 | `push_posed_parts` at the end of `tick_ship` when `moved` (ART:499-502) | same, extended to the pose table |
| first script resolution | `SetupProperties` → SHIPS:1647 `push_posed_parts` | flag | table (empty) |
| `ship._parts_detached` | PS:268 (create), PS:468 (`sever` add), PS:556-558 (`reset_ship` → None) | **none** (the flag ignores it) | push a per-slot `detached` bit, or re-push the table |
| `PropertyClass._physical_parent` | PROP:75-77 `SetPhysicalParent` (hardpoint load; SPV save) | none | invalidate the resolved part slots of every subsystem using that property |
| SPV preview overlay | PHP:95-103 `set_preview` / `clear_preview` (called from `ship_property_viewer_panel.py:1506-1510`) | none | invalidate (dev only) |
| leaf model learned | ART:650-657 `_remember_leaf_model` (via `part_boxes_for(leaf, iid)`, first realize: `hull_bounds.cache_hull_bound_spheres` → `part_for_point`; HL:7032, 8332) | none | invalidate the leaf: `part_for_mount` answers change from the box rule to `model_nearest_part` |
| derived boxes learned | ART:702-703 `_derived_boxes[leaf] = boxes` | none | invalidate the leaf: `is_missing` and the box rule change |
| rig snapshot | AP:168/190/199 `_GENERATION += 1` | none (tick_ship re-reads per tick) | invalidate (part list and order) |
| subsystem `_position` | `SetPosition` (already a mirrored field) | `_position` | invalidate that subsystem's slot (`part_for_mount` keys on the point) |
| `ship._articulation_leaf` | ART:410 (`leaf_for`, first call, caches `""` for good if the script is unresolved) | — | **native must never trigger it**; resolve slots only from Python, after the leaf is known (the trap `_posed_flag` documents, NC:1072-1073) |

### 3.4 What the native side would need

- **Per ship (Object row):** `part_poses`: one entry per name of `posed_part_names(ship)`, in that order. Each entry holds `R` as 9 doubles flattened row-major exactly as Python stores it (`R[i][j]` → `r[3i+j]`), `t` as 3 doubles, `identity` (Python's `is_identity`, pushed and not recomputed), and `detached` (`name in _parts_detached`).
- **Per subsystem (Subsystem row):** `part_slot`: the index into the owning ship's `part_poses` of the name `_live_part` resolves for the subsystem's own `_position` with `prop = property_of(sub)`, ignoring detachment (the per-slot bit carries that). -1 for None or a name not in `names`. Plus a `part_gen` stamp of the resolution generation (§5 design), so a stale slot is never silently used.
- **Target offsets:**
  - K3 already has the mount (`_mount_key`, `row.mount_attributed`). The native side may use `part_slot` of `mount_sub` **only when the offset equals `mount_sub._position` bit for bit**: `part_for_mount` keys on the rounded offset (PS:150), and `authored_mount_subsystem` matches within 1e-5 (PS:511-512), so a near-equal offset could resolve differently. In SDK use the offset is a `GetPosition()` copy (SS:99-101), so it is equal (**inferred**); otherwise ASK.
  - For K1's tube and pulse aim (`_RESOLVE`), `authored_mount_subsystem` returns the FIRST match in `combat._iter_subsystems` order (`combat.py:268-292`: each top-level subsystem, then its `_children`). A system parent and its child can share a point but carry different physical parents. Either mirror that iteration order per Object row, or ASK once per (target, offset).
  - Manual Aim (`authored=False`, box rule) stays an ASK.

---

## 4. Every float operation on the posed path, in operand order

All doubles. The combat library compiles with `-ffp-contract=off` (`native/src/combat/CMakeLists.txt:44`), and each source carries `#pragma clang fp contract(off)` (WG:5-7). A new source must do the same.

**P1. Pose apply** (`part_pose.apply`, PP:72-75 with `_mat_vec` PP:26-28):

```
r_i = (R[i][0]*x0 + R[i][1]*x1) + R[i][2]*x2        # i = 0,1,2; left to right
p_i = r_i + t_i
```

This is exactly `detail::mult_matrix_left(r_flat, x)` (GI:61-66) on the row-major flattening, followed by a componentwise `+ t`.

**P2. Identity passthrough.** If the pose passes `is_identity` (PP:87-91: `abs(R[i][j] - I[i][j]) <= 1e-9` for all i, j and `abs(t_k) <= 1e-9`), Python returns the input tuple **itself**. Do not multiply by an identity: `-0.0*1.0 + 0.0*y + 0.0*z` gives `+0.0` and flips a signed zero that later reaches `atan2`. Branch on the pushed `identity` bit. A part with no slot (None) is the same passthrough.

**P3. Mount** (`_subsystem_world_position`, SS:68-88):

```
(px,py,pz) = P1/P2(local)                 # local = sub.GetPosition() = _position
offset = R_ship · (px,py,pz)              # MultMatrixLeft MATH:91-93: m00*x + m01*y + m02*z, row by row
result = (ship_pos.x + offset.x, ship_pos.y + offset.y, ship_pos.z + offset.z)
```

The pose applies BEFORE the ship rotation. There is no scale. `TGPoint3(px, py, pz)` calls `float()` on floats (exact). In the step it is memoised by `(id(sub), id(ship_arg))` (SS:48-54); the native twin is `SensorState::mounts` (WG:104-111).

**P4. Target offset** (`target_offset_world`, SS:119-136):

```
(px,py,pz) = P1/P2(offset)                # in the TARGET's rest frame, unscaled
scale = float(target.GetScale())          # mirrored _scale; no <= 0 guard
o = (px*scale, py*scale, pz*scale)
o = R_target · o                          # MultMatrixLeft
result = (pos.x + o.x, pos.y + o.y, pos.z + o.z)
```

The pose applies BEFORE the scale. Its `t` is in unscaled ship units, so a scaled target scales the posed point (`DockWithStarbase` shrink, rocks).

**P5.** Downstream of P3/P4 nothing changes. The aim normalisation `** 0.5` (`py_pow`), the cone/arc `atan2`/`asin` and the pulse lead solve are as in k1-fire-control-map F7-F13 and k2-beams-map F1-F10, which WG/BG already port.

**P6. Not on the combat path, for completeness:** `inverse_apply` (PP:82-84: `Rᵀ·(x - t)`) is used by `part_for_live_point` (hit attribution, Manual Aim pull-back), and `_rot_angle`/`_dist` by transition timing. Neither is read by K1-K3.

---

## 5. Risks, and the cheapest bit-exact design

### 5.1 Risks

| # | Risk | Severity |
|---|---|---|
| R1 | Reading the pose from the renderer (`node_overrides`) would be float32, in model units, and one frame stale. | Avoided by design: the pose is pushed from Python (§2.4) |
| R2 | The part resolution depends on renderer model queries (`host_io.model_nearest_part`) and derived boxes that appear only at first realize. Before that, `part_for_mount` answers by the box rule and does not cache (PS:146-163), so a slot computed early goes stale. | Needs the invalidation in §3.3; a generation stamp makes a missed trigger a fallback, not a wrong answer |
| R3 | `authored_mount_subsystem` is a first-match scan within 1e-5 in `_iter_subsystems` order; a parent and child can share a point with different physical parents. | ASK, or mirror the order (§3.4) |
| R4 | `part_for_property` writes a one-time stderr warning (PHP:79-84). | Only Python resolves parts; the kernel never does |
| R5 | `leaf_for` caches `""` for good if called before the script is set (NC:1072-1073, ART:393-413). | Resolve slots only for ships whose `_articulation_leaf` is already a non-empty str (any posed ship that `tick_ship` has run on) |
| R6 | `sever` mid-step (`apply_hit` → `record_hit` → `sever`, PS:290-339, 449-476) makes a severed part read rest. `apply_hit` already forgets the memo (combat.py:617, k1-map §4). | Push the detached bit synchronously in `sever` / `reset_ship` |
| R7 | Directions are NOT posed (§1.1, §1.2): a port that applied `R_part` to `_direction` would diverge. | Copy Python |
| R8 | Signed zeros at identity (P2). | Branch, never multiply |
| R9 | All N GameLoop ticks run before all N combat ticks (§2.2). A future one-tick pipeline (roadmap J) must snapshot poses together with transforms, or AI and combat will see different poses. | Design note for J |
| R10 | `tick_ship` raising mid-loop (e.g. in `interpolate`) leaves in-place writes without the end-of-tick push (ART:474-502). Inferred unreachable for well-formed poses. | `DAUNTLESS_NATIVE_AUDIT=1` (`audit_mirror`, NC:1847, run each tick from LOOP:115-116) should compare the pose table too |
| R11 | `posed_part_names` order is rig order plus sorted extras (ART:214-219). Slots must use exactly that order, or be keyed by name. | Build both slot and table from one call |
| R12 | The K1 `decide_*` functions are not resumable mid-geometry (**inferred** from K1C's structure: ASKs exist only at record boundaries, k1_fire_control.h stage 2). A design that ASKs for each posed mount would need new resume points in K1 and in K2's GEOMETRY state. | Prefer pure data (design A) for K1/K2 |

### 5.2 Design A (recommended): push pose tables and part slots, compute natively

1. Extend `push_posed_parts` (NC:1118-1127; already called at every pose write, §3.3) to push the ship's `part_poses` table (§3.4) when `_posed_flag` is 1, and an empty table when it is 0.
   - Cost: 2 parts × 13 numbers for a BoP, and only on ticks where a part moved. A settled posed ship (e.g. a BoP in cruise) pushes nothing per tick.
2. Push a `part_slot` per subsystem of a posed ship, computed in Python by the same `_live_part` call minus the detached test. Stamp it with a global part-map generation. Bump the generation at every trigger in §3.3 (model/boxes learned, physical parent set, preview, rig generation, `_position` write, change of `posed_part_names`).
   - Re-resolve lazily, from Python, for posed ships only, at a step boundary (e.g. `step_scan` / `k1_pump` begin) when the generation moved.
   - The kernel falls back (or ASKs) when a slot's stamp is stale, so a missed trigger costs speed, not exactness.
3. Native `mount_position` (WG:77-90): replace `if (o.has_posed_parts) fall_back(...)` with: slot = `s.part_slot`; if slot ≥ 0 and the entry is neither `identity` nor `detached` → P1 on `_position`; else `_position` unchanged; then the existing P3.
   - This removes K1's `PosedShip` (K1C:438) and K2's `PosedShip` (K2C:315), and the lock-ship half of K2's `aim_point` ASK.
4. Native `target_offset_world` (WG:217-226): take the mount subsystem, use its slot when `offset == _position` bit for bit (K3 `_mount_key`), else ASK.
   - This removes K3's posed-target `steer_point` ASK (PG:310) for subsystem locks.
   - K1 tube/pulse aim on a posed target (K1C:473) needs the mount first (R3). Either mirror `_iter_subsystems` order per Object (new Ids field, pushed on subsystem attach and `_children` change), or keep K1's `PosedTarget` as a narrower ASK `offset_point(target, offset) -> (px,py,pz)` computed by Python's `part_transform_point` (bit-exact, since Python makes the same doubles).
   - Manual Aim stays an ASK.
5. Keep `has_posed_parts` as the fast gate: with it 0, the path is byte-identical to today (pinned by `tests/unit/test_native_posed_flag.py`).

### 5.3 Design B (cheaper to write, narrower): push the posed LOCAL mount

Python pushes, per subsystem of a posed ship, `posed_local = part_transform_point(ship, local, prop=property_of(sub))`. That is P1/P2 done in Python, at the same push points plus `sever` and every §3.3 trigger. The native mount then uses `posed_local` instead of `_position`. This is bit-exact by construction and needs no part logic in C++.

Costs and limits:

- It recomputes every subsystem of a moving ship each tick of a transition: dozens of `part_for_property` calls, mostly `_mount_parts` dict hits.
- It does not serve arbitrary target offsets. K3 only works when the offset equals a mount bit for bit; Manual Aim and K1 `_RESOLVE` still need ASKs.

Good as a first cut for K1/K2 `PosedShip`.

**Tests to extend** (all focused, none run here): `tests/unit/test_native_posed_flag.py` (identity exactness), `test_target_offset_articulation.py` (posed offsets, wings-down exactness), `test_physical_parents.py`, `test_physical_parent_consumers.py`, `test_part_severance.py`, `test_articulation_transitions.py`, `test_part_pose.py`. A posed differential needs a BoP that is mid-transition and one that is settled in cruise, firing at and being fired at; SIG-160 notes the BoPs' opening ~5 s before target acquisition as the natural case.

---

# Part 2 — Timing seams (workstream B)

## 6. Sub-scopes inside `cb.held_weapons`

### 6.1 How scopes are declared, and the constraint

- `with frame_profiler.scope("name"):` (FP:269-296) records the scope as a child of the innermost open scope (or the open `mark()` phase), and **children are included in their parent's total** (FP:29-31; frame-profiler.md "Indented rows are INCLUDED"). Nested scopes nest; do not sum them.
- A name entered several times in a frame sums within the frame, then folds into the EMA (FP:60-66, 306-323).
- `scope()` costs ~0.36 µs per use **even when disabled** (FP:36-41, 276-279). It belongs at seams, never per record or per ship. `run_k1` handles one record per effect, so per-record `with` blocks would cost on every tick of production.
- **Pattern for per-record buckets** (a proposal; there is no public API yet): read `frame_profiler.is_enabled()` once per `run_k1` call. When it is on, time each dispatch branch with `time.perf_counter()` pairs into a local dict, and at the end hand each total to a small new public helper that does `_note(name, _scope_stack[-1])` + `_accumulate(name, ms)` (FP:299-310 are private today). When it is off the cost is one bool test per call.
- `run_k1` sessions **nest**: an effect's event handler may `StartFiring`, which opens a nested system session (k1_fire_control.h "SESSIONS form a stack"; WS:1536). A bucket measured around `_fire_effect` therefore includes any nested session. Either keep a timer stack and report exclusive time, or label the bucket inclusive.
- The C++ `FrameTimer` lives in the renderer. The combat library does not reference it (a grep of `native/src/combat` finds no `frame_timer`/`FrameTimer`), so a native-internal split of `combat_k1_next` would need its own `steady_clock` counters exported through `combat_k1_counts()` (**inferred** design).

### 6.2 The seams, in execution order

| # | Sub-scope (proposed name) | What it covers | Where |
|---|---|---|---|
| 0 | `hw.dispatch` | `_pump_held_weapons`: list conversion, then `k1_pump` | HL:1000-1009 (native) / HL:1011-1013 (Python path: `_pump_held_system` per ship × 4 getters) |
| 1 | `k1.begin` | `_k1_recheck_overrides()` (class-override re-check), `refresh_stale_pulse_params`, the handle list (`slot(ship)` per ship), `_k1_clocks()`, `_h.combat_k1_begin_pump` | NC:2355-2363, once per tick; a plain `scope()` is fine here |
| 2 | `k1.next` (the hand-off) | `_h.combat_k1_next()`: the native walk up to the next record, plus pybind marshalling of the record and its write list | NC:2290, per record (perf_counter) |
| 3 | `k1.writes` | `apply_writes(writes, walk)`: the write log, quiet setters, ref mapping | NC:2303-2304, per record |
| 4 | `k1.fire` | FIRE → `bank._fire_effect(...)`: the actual firing. Beam: SFX + `ET_WEAPON_FIRED`. Pulse: `_spawn_projectile` (Torpedo(), SDK `mod.Create`, launch sound). Tube: `_spawn_torpedo`, ammo, `ET_TORPEDO_FIRED`, ... (WS:888, 2672, 2937, 3411, 3503) | NC:2305-2308 |
| 4b | `k1.stop` / `k1.fire_failed` / `k1.fire_dumb` | `StopFiring()`; `_broadcast_weapon_fire_failed()` (synchronous `ET_WEAPON_FIRE_FAILED`, WS:3451); `FireDumb(0, 1)` | NC:2326-2331 |
| 5 | `k1.walk_start` | instance-patch check + pinning (`walk.walk_start`), `_live_held_offset()` (WS:1551), `combat_k1_set_offset`. A patched system runs `update_weapons` whole (NC:2314-2320) | NC:2309-2324 |
| 6 | `k1.run_python` | RUN_PYTHON: `pump_body(ship, getter)` = `_pump_held_system` (HL:1021-1045) or `system.update_weapons(dt)` | NC:2332-2336. The record carries system, ship index and getter, **not the reason** (k1_fire_control.h:164-167). To time per `K1Why` (posed_ship, ...), add the reason to the record or re-derive it Python-side. |
| 7 | `k1.ask.<query>` | ASK answered in Python (`_k1_answer`, NC:2217-2268) + `combat_k1_answer`. **`fire`, `retry` and `group_step` ASKs run real firing** (`bank.Fire`, `try_fire_weapon`) and belong with #4 for a "firing cost" total; `can_fire`, `is_dead`, `is_member`, `is_dumb` and `reseed` are questions | NC:2337-2338 |
| 8 | `k1.pin` | `walk.pin_system(walked)` after each record | NC:2343-2344 |
| 9 | `k1.end` | `_h.combat_k1_end()` | NC:2345 |

Also outside `cb.held_weapons` but part of K1's bill:

- StartFiring's system sessions (`k1_system`, NC:2367-2380) run where the SDK calls `StartFiring`: mostly inside `gl.ai`, or nested inside another effect's handler.
- SIG-161 inferred that the write-log and effect cost may surface in `sim.weapons` (0.443 → 0.616 per tick with native on). That attribution was never measured; #3/#4 above would settle it.

Counts that already exist and should be read next to these timers: `k1_records`, `k1_python_systems`, `k1_asks`, `k1_python_reasons` {pump, system} (NC:193-218).

## 7. The rest of `sim`, per tick

### 7.1 Measured (C-246 / C-247, K3+K4, 64-ship fight, Debug; median of reports 3-11 of value ÷ printed average ticks per frame, the register's method)

| Row | run 1 | run 2 | Runs |
|---|---|---|---|
| `sim` | 10.017 | 9.954 | — |
| `sim.combat` | 2.459 | 2.446 | per tick |
| `gl.ai` | 3.244 | 3.206 | per tick |
| `gl.motion` | 1.376 | 1.354 | per tick |
| `gl.subsystems` | 0.618 | 0.600 | per tick |
| `sim.weapons` | 0.589 | 0.607 | per tick |
| **residual** | **1.73** | **1.74** | — |
| of which `sim.render_xforms` | 0.531 | 0.527 | **once per frame** |
| `sim.input` | 0.331 | 0.324 | once per frame |
| `sim.collisions` | 0.165 | 0.165 | once per frame |
| `sim.reconcile` | 0.064 | 0.064 | once per frame |
| small `gl.*` (cloak 0.080, timeslice 0.030, warp_states 0.030, timers 0.018, proximity 0.013, bridge_chars 0.008, rock 0.009) | ~0.19 | ~0.18 | per tick |
| `sim.gameloop` unscoped (5.480 − Σ children 5.427) | ~0.05 | ~0.05 | per tick |
| `sim` unscoped (10.017 − Σ direct children 9.654) | ~0.36 | ~0.35 | mostly per frame |

Ticks a frame: median 3.4 / 3.5. Medians of ratios do not add exactly; read the residual split as ±0.05 ms.

**Reading:** about 1.1 ms of the 1.74 ms residual is once-per-frame work divided by ~3.4 ticks. Moving it saves once per frame, not 3-4 times. At one tick a frame the same work would read ~3.7 ms "per tick". The roadmap's ~4 ms "outside combat and AI" is this 1.74 plus `gl.motion` + `gl.subsystems` + `sim.weapons` (2.59).

### 7.2 Unscoped work, and where a scope would go

**Inside `sim.gameloop`, outside any `gl.*`** (per tick, ~0.05 ms total):

- `invalidate_obstacle_snapshot()` + `native_combat.refresh_stale_pulse_params()` (LOOP:33-36)
- `apply_pending_alert_levels()` (LOOP:58-59)
- `warp_in_flash.advance` (LOOP:96-97)
- `audit_mirror` when audited (LOOP:115-116)

Proposed scope: one `gl.misc`.

**Inside `sim`, outside every `sim.*` scope** (~1.2 ms a frame):

| Work | Where | Cadence | Proposed scope |
|---|---|---|---|
| `step_accumulator`, `perf_monitor_panel.tick` | HL:12305-12324 | frame | (negligible, inferred) |
| `advance_ticks` overhead: `buf.roll()` and, on frames with 2+ ticks, `_interp_live_poses()` reading `GetWorldLocation`/`GetWorldRotation` for every realised ship (HL:11733-11741) and `set_previous` | TB:82-86, outside `sim.gameloop` | frame | `sim.xform_roll` inside `advance_ticks` around TB:82 and TB:84-86 |
| pending mission swap block (`_drain_pending_swap` etc.) | HL:12358-12388 | frame | `sim.swap` |
| `_sync_player_identity` | HL:12421-12422 | frame | `sim.player_sync` |
| contact manager `sensor_contacts.tick` | HL:12632-12636 | frame (1 s internal cadence) | `sim.contacts` |
| crew hazard prompts | HL:12641-12647 | frame (1 Hz) | `sim.hazard_prompts` |
| nebula tracker + radiation driver, **per tick** over the active set's `CT_SHIP` list | HL:12654-12681 | tick | `sim.nebula` |
| nebula thunder / hull discharge / wake drivers | HL:12683-12781 | frame | `sim.nebula_fx` |
| `warp_state.sync_flythrough` | HL:12802-12804 | frame | `sim.flythrough` |

**Inside `sim.combat`, outside any `cb.*`:**

- the torpedo `apply_hit` loop (HL:1332-1341, after `cb.projectiles` closes — k3-k4-map's correction)
- the `step_memo.forget()` calls (HL:1351, 1362, 1378, 1398, 1402)

Proposed scope: `cb.torp_hits` around HL:1332-1341.

**Already-scoped once-per-frame rows worth a split:**

- `sim.render_xforms` (~1.8 ms a frame): `_sync_instance_transforms` (HL:10017) = per-ship transform push + `_sync_ship_articulation` + glow.
- `sim.input` (~1.1 ms a frame): `_apply_input`, the poll functions, `manual_aim.update` (HL:12584-12589).

**Profiler fix to make before measuring:**

- Add `sim.weapons`, `sim.combat` and `sim.ship_list` to `PER_TICK_ROOTS` (FP:119), or restate that comment and the frame-profiler.md bullet. Today the report leaves them unmarked, which reads as "once per frame" (§ corrections).
- Divide only `*` rows by ticks; report once-per-frame rows per frame.

**Generation bumps are global.** Any bump of the part-map generation makes every posed ship re-resolve its slots at the next step boundary (cheap after the first call), so never add a per-tick bump trigger (e.g. a `SetName` in UI code).
