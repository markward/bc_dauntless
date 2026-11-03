> **Superseded in part (2026-11-02, native-damage phase):** K3 applies its hits natively after the step's expiries, in the same order; the host loop's per-hit `apply_hit` runs only with the switch off. See the native-damage spec §10.

> **Implemented 2026-11-01** on branch `perf/native-combat-k3`, tip commit `0c5d58c81`. Outcome, measurements and rulings: `docs/superpowers/specs/2026-11-01-native-combat-k3-k4-design.md` §10. The map below is the pre-build snapshot and is not updated.

> Snapshot map written 2026-11-01 at commit `6418f858f` (branch `perf/native-combat-k2`) for the native combat step (spec `docs/superpowers/specs/2026-10-30-native-combat-step-design.md` §7.3 "K3 — projectiles" and "K4 — eligibility"). It is the input to `docs/superpowers/specs/2026-11-01-native-combat-k3-k4-design.md`. Line numbers drift; re-check them against the code before relying on one. The model for this document is `k2-beams-map.md`. Nothing here was run except a read of the existing cProfile capture (`pstats`).

# K3 projectiles + K4 eligibility — code map

File abbreviations:

| Abbrev. | File |
|---|---|
| **HL** | `engine/host_loop.py` |
| **PR** | `engine/appc/projectiles.py` |
| **TS** | `engine/appc/torpedo_scan.py` |
| **CB** | `engine/appc/combat.py` |
| **COL** | `engine/appc/collisions.py` |
| **SS** | `engine/appc/subsystems.py` |
| **WS** | `engine/appc/weapon_subsystems.py` |
| **PS** | `engine/appc/part_severance.py` |
| **ART** | `engine/appc/articulation.py` |
| **SD** | `engine/appc/sensor_detection.py` |
| **FR** | `engine/systems/frames.py` |
| **OBJ** | `engine/appc/objects.py` |
| **SETS** | `engine/appc/sets.py` |
| **DE** | `engine/appc/damage_eligibility.py` |
| **HF** | `engine/appc/hit_feedback.py` |
| **NC** | `engine/appc/native_combat.py` |
| **MATH** | `engine/appc/math.py` |
| **PQ** | `native/src/transforms/src/proximity_query.cc` |
| **TSC** | `native/src/transforms/src/torpedo_scan.cc` / `include/dauntless/torpedo_scan.h` |
| **BG** | `native/src/combat/src/beam_geometry.cc` / `beam_geometry.h` |
| **BT** | `native/src/combat/include/dauntless/combat/beam_trace.h` |
| **WG** | `native/src/combat/src/weapon_geometry.cc` / `weapon_geometry.h` |

**Corrections to the spec's §7.3 wording and to the brief**, all checked against the code:

- **`cb.eligibility` does not call `select_eligible` directly.** It calls `damage_eligibility.update(ships_list)` (HL:1313), which resolves the player through `App` and then calls `select_eligible(player, ships)` (DE:96-108). `select_eligible` is also called directly by tests (`test_damage_eligibility.py`, `test_frame_tripwire.py`), so K4 belongs at `update()`, with `select_eligible` kept as the Python reference.
- **The torpedo `apply_hit` loop is OUTSIDE the `cb.projectiles` profiler scope** (HL:1320-1329 is after the `with` block at HL:1315-1319). The measured `cb.projectiles` time is `update_all` alone, including `expire()`'s set removal and event posts.
- **`update_all` posts SDK events mid-scope.** Its last loop calls `expire(t)` for every expired torpedo (PR:979-980), which posts `ET_TORPEDO_EXITED_SET` synchronously. These happen after every decision is made, so they bound the kernel's batch; they are not inside it.
- **No SDK-visible effect runs between the first steer and the last narrow test.** Steps 1-3 of `update_all` (PR:854-977) post no event and call no SDK script. The only state they write besides the torpedoes' own is the native can_detect latch and memo, the TransformStore (torpedo positions), the torpedo_scan rows (velocity), and (once per shot) `_mount_key`. So unlike K1/K2, **K3's decision phase is a genuine batch**: one kernel call can make every decision; no epoch or resume is needed except for ASKs (§8.1).
- **The narrow phase is almost free.** In the capture, 0.51 candidate pairs per tick reach the narrow tests and 0.08 hit (§9). The cost is guidance (44%), the per-ship cache (~14%), the per-torpedo store round-trip (~14%) and Python overhead around them. The narrow code still has to be ported or ASKed, but it is not where the time is.
- **"~1,500 torpedoes" (TS docstring, `torpedo_scan.h`) does not match the captures.** Measured medians of projectiles in flight are 31-87 (C-234..C-245); the pyprof5 capture averages ~89 (§9). Photon torpedoes have no `SetLifetime` in the SDK script, so a miss lives the default `_ttl` 60 s (PR:89), and a long fight can accumulate many. Size the write-back cost (§7.6.2) on the measured 30-110, with the 60 s tail as a stress case.
- **Spec §9.1 R12 is enforced by `_hidden_fields`.** `Torpedo` hides the mirrored `_radius` (a scalar) and `_containing_set` (a ref) behind plain properties (PR:256-280). `register` (NC:805-834) gives any class hiding a scalar **no row at all** (NC:815-816). Every torpedo goes through `ObjectClass.__init__`'s `native_combat.register(self, "Object", ...)` (OBJ:~108) and is silently skipped.

---

# Part A — K3: `cb.projectiles`

## A1. Call graph

### A1.0 Where it runs

`run()` builds `_ships_this_tick = list(_all_ships_for_tick())` once per game tick (HL:12596/12601; `_all_ships_for_tick` HL:2550 → `ship_iter.iter_ships()`: every `ShipClass` in every set of `App.g_kSetManager._sets`, rocks and dead ships included). Then per tick (HL:12602-12612):

- `sim.weapons` → `_advance_weapons(ships, TICK_DT)` (charge, reload; **before** combat);
- `sim.combat` → `_advance_combat(ships, TICK_DT, ship_instances=session.ship_instances, ..., push_render_data=False)` (HL:12605).

`_advance_combat` (HL:1264) wraps the step in `step_memo.combat_step()`. In `_advance_combat_step` (HL:1278):

```
HL:1307  ships_list = list(ships)
HL:1312  cb.eligibility   damage_eligibility.update(ships_list)                 # Part B
HL:1315  cb.projectiles   hits = projectiles.update_all(dt, ships_list, ship_instances=ship_instances)
HL:1320  for torpedo, ship, hit_point, hit_normal in hits:                     # NOT in the scope
             combat.apply_hit(ship, torpedo._damage, hit_point, source=torpedo._source_ship,
                              normal=hit_normal, ship_instances=ship_instances, weapon_type="torpedo",
                              hardpoint_weapon=torpedo, shield_point=torpedo._bubble_entry)
HL:1331  cb.vfx
HL:1339  step_memo.forget()
HL:1340  cb.death ... forget ... cb.damage_sys ... forget ... cb.held_weapons (K1) ... cb.phasers (K2) ...
```

- **No `forget()` runs before `cb.projectiles` in the step.** The memo is empty at step start: the previous step's outermost `combat_step()` exit forgot, and nothing between steps memoises (`step_memo.active()` is False outside the block; AI `StartFiring` runs outside it). So guidance's `can_detect` answers are the first fills of the step's native memo, and they live until the first torpedo `apply_hit` (which forgets on entry, CB:617) or HL:1339.
- A torpedo fired in tick N (by `cb.held_weapons`, after `cb.projectiles`) first moves in tick N+1. A torpedo fired by an SDK handler during the HL:1320 apply loop (e.g. `ET_WEAPON_HIT` → `StartFiring` → K1 single-system `update_weapons(0.0)` → `Fire`) is also first moved in tick N+1.

### A1.1 `update_all` verbatim in structure (PR:791-982)

```
from engine.appc.combat import sphere_hit, _resolve_hit_point, shield_bubble_entry, shields_block, bubble_bound_radius   # per call
hits, expired = [], []
if not _active: return hits                                                  # PR:823 — quiet scene: 0.003 ms/tick (SIG-155/159)

# 0. Per-ship cache (PR:841-849), once per call, in all_ships order
ship_cache = []
for ship in all_ships:
    if ship.IsDead(): continue                                               # NO hasattr guard (unlike _guide): a stub IsDead is a truthy _Stub -> skipped
    pos = ship.GetWorldLocation()                                            # store read
    ship_cache.append((ship, pos.x, pos.y, pos.z, bubble_bound_radius(ship), frames.containing_set(ship)))   # CB:916 (B1), FR:48
offsets = {}                                                                 # (ship_set, torp_set) -> offset_between, filled by _broadphase

# 1. Steer and advance EVERY torpedo (PR:854-892), list order of a SNAPSHOT
moving = []
for t in list(_active):
    if t._target_ship is not None and t._age < t._guidance_lifetime:        # age BEFORE this tick's += dt
        _guide(t, dt)                                                        # A1.2 — may write _velocity, _last_seen_target_pos, _last_target_vel, _mount_key
    prev_pos = t.GetTranslate()                                              # store read (new TGPoint3)
    cur_pos = prev_pos + t._velocity * dt                                    # A2 — the POST-guide velocity
    t._age += dt
    if t._age >= t._ttl:                                                     # NaN age/ttl: never expires
        t.SetTranslateXYZ(cur_pos.x, cur_pos.y, cur_pos.z)                   # store write
        expired.append(t); continue                                          # TTL expiries enter `expired` FIRST, in list order; no hit test
    seg = cur_pos - prev_pos ; seg_len = seg.Length()                        # A3, A4 (sqrt)
    aim_unit = TGPoint3(seg.x/seg_len, seg.y/seg_len, seg.z/seg_len) if seg_len > 1e-9 else None   # A5
    moving.append((t, prev_pos, cur_pos, seg_len, aim_unit, frames.containing_set(t)))           # the torpedo's OWN set (_cset)

# 2. Broadphase (PR:895 -> _broadphase PR:711-788): per moving entry, ascending ship_cache indices
candidates = _broadphase(moving, ship_cache, offsets)                         # A1.4

# 3. Narrow, first hit by ship_cache index wins (PR:898-977)
for (t, prev_pos, cur_pos, seg_len, aim_unit, torp_set), near in zip(moving, candidates):
    source = t._source_ship
    for j in near:
        ship, sx, sy, sz, bound, ship_set = ship_cache[j]
        if ship is source: continue
        off = offsets[(ship_set, torp_set)]                                   # always filled by _broadphase for a candidate
        seg_prev = _shifted(prev_pos, off) ; seg_cur = _shifted(cur_pos, off)   # SAME objects when off is zero
        bubble_entry = (shield_bubble_entry(ship, seg_prev, aim_unit, seg_len)    # CB:403 (K2 F15-F16), max_dist = seg_len
                        if (aim_unit is not None and shields_block(ship)) else None)   # CB:343 (K2 §1.5)
        if bubble_entry is None and not sphere_hit(seg_cur, ship.GetWorldLocation(), world_radius(ship)):   # A8; END point only
            continue
        if bubble_entry is not None:
            seg_cur = bubble_entry                                            # the bubble OBJECT
            cur_pos = _shifted(bubble_entry, off, -1.0)                       # the bubble object itself when off is zero
        t._bubble_entry = bubble_entry                                        # written ONLY for the hit pair (else stays __init__'s None)
        if aim_unit is not None:
            radius = world_radius(ship) if hasattr(ship, "GetRadius") else 0.0
            backoff = radius + seg_len                                        # A9
            ray_origin = TGPoint3(seg_cur.x - aim_unit.x*backoff, ...)        # A10
            ray_max = 2.0 * radius + seg_len                                  # A11
        else:
            ray_origin, ray_max = seg_prev, seg_len
        hit_point, hit_normal = _resolve_hit_point(ship_instances=ship_instances, ship=ship, ray_origin=ray_origin,
                                                   ray_direction=aim_unit, max_dist=ray_max, fallback_point=seg_cur)   # CB:86 (K2 §1.4)
        hits.append((t, ship, hit_point, hit_normal)) ; expired.append(t) ; break
    t.SetTranslateXYZ(cur_pos.x, cur_pos.y, cur_pos.z)                        # store write: post-advance, or ON the bubble

# 4. Effects (PR:979-980)
for t in expired: expire(t)                                                   # A5 — TTL ones first, then hits, each in list order
return hits
```

**Branch facts**

- **Every torpedo is steered and advanced before any narrow test.** Guidance reads ship state and the torpedo's own state only; ships do not move inside `update_all`. The interleaving of guide and advance per torpedo is therefore unobservable, **except** through the can_detect latch and memo (A4.1), which are order-dependent per (observer, target) pair.
- **A TTL-expiring torpedo is still guided this tick** (guide runs before the age test), moved, written, expired, and never hit-tested.
- **The hit test is END-point only** (`sphere_hit(seg_cur, ...)`): a fast shot can tunnel a small sphere between ticks. The bubble test is a segment test. Copy, do not fix.
- **Hits are decided on a static world and applied afterwards** (HL:1320). Two torpedoes can hit a ship whose first hit kills it; both hits are applied. A hit on the source ship is impossible (`ship is source`), on a dead-at-step-start ship impossible (cache filter), on a ship killed earlier this step by a phaser impossible (phasers run later).
- `_bubble_entry` is set only on the hit torpedo. A torpedo that never hits keeps `None`. `apply_hit` reads it as `shield_point`.
- `list(_active)` is a snapshot; nothing in steps 1-3 can append (no SDK runs), so the snapshot equals the list.

### A1.2 `_guide(torpedo, dt)` (PR:1060-1133)

```
target = torpedo._target_ship ; if target is None: return
off = frames.offset_between(frames.containing_set(torpedo), frames.containing_set(target))   # FR:59; torpedo set -> target set
if off is None: return                                         # other frame / no set: ballistic. BEFORE IsDead.
if hasattr(target, "IsDead") and target.IsDead(): return       # ballistic; NOT the cloak cache. Stub IsDead -> truthy -> ballistic (+ stub telemetry)
speed = torpedo._velocity.Length()                             # G1 sqrt
if speed < 1e-6: return
torp_pos = torpedo.GetTranslate()                              # store read (same values as update_all's prev_pos)
if _target_visible(torpedo, target):                           # A1.3 — can_detect from the FIRING ship
    pos = _steer_point(torpedo, target, off)                   # A1.3 — torpedo-set coordinates
    torpedo._last_seen_target_pos = TGPoint3(pos.x, pos.y, pos.z)          # WRITE (copy)
    vel = target.GetVelocityTG() if hasattr(target, "GetVelocityTG") else TGPoint3(0,0,0)
    if not isinstance(vel, TGPoint3): vel = TGPoint3(0.0, 0.0, 0.0)
    to_t = pos - torp_pos ; t_go = to_t.Length() / speed      # G2
    prev_vel = torpedo._last_target_vel
    acc = ((vel - prev_vel) / dt per axis) if isinstance(prev_vel, TGPoint3) and dt > 1e-9 else (0,0,0)   # G3
    torpedo._last_target_vel = TGPoint3(vel.x, vel.y, vel.z)   # WRITE — before the dist<1e-6 return below
    aim = pos + vel*t_go + _LEAD_ACCEL_K*acc*t_go*t_go          # G4
else:
    aim = torpedo._last_seen_target_pos ; if aim is None: return   # frozen last-seen point (torpedo frame at the time it was seen)
to_aim = aim - torp_pos ; dist = to_aim.Length()                # G5
if dist < 1e-6: return
desired = to_aim / dist ; current = _velocity / speed           # G6
remaining = max(0.0, _guidance_lifetime - _age)                 # G7 (age is this tick's PRE-increment value)
initial = _guidance_initial if _guidance_initial > 1e-9 else 1.0
max_step = (remaining / initial) * _max_angular_accel * dt
cos_theta = max(-1.0, min(1.0, current.Dot(desired)))           # G8
theta = math.acos(cos_theta)
if theta <= max_step or theta < 1e-6: new_dir = desired         # NB: `desired` OBJECT (then * speed makes a new one)
else: slerp (G9)
torpedo._velocity = new_dir * speed                              # WRITE through the Torpedo._velocity property -> torpedo_scan.set_velocity
```

- Write order per guided call: `_mount_key` (inside `_steer_point`, first visible steer only), `_last_seen_target_pos`, `_last_target_vel`, then `_velocity`. The first three are written even when the call later returns at `dist < 1e-6`.
- **The `off is None` return comes before the `IsDead` call**: a target in another frame is never IsDead-tested (no stub telemetry for it).
- A Torpedo as a target: `ObjectClass` has no `IsDead` (it is on `DamageableObject`, OBJ:916), so `hasattr` is vacuously True on the TGObject stub, `IsDead()` returns a truthy `_Stub`, and the torpedo goes ballistic, recording stub telemetry. So a guided torpedo never reads another torpedo's mid-step position (inferred safe from this chain).

### A1.3 `_target_visible` (PR:988-1019) and `_steer_point` (PR:1022-1057)

```
_target_visible(torpedo, target):
    src = torpedo._source_ship ; if src is None: return True
    try:
        off = frames.offset_between(frames.containing_set(src), frames.containing_set(target))   # SOURCE set -> target set (the shooter may have moved sets)
        if off is None or off == _ZERO_OFFSET:
            return bool(can_detect(src, target))              # memo-eligible (step_memo active, no optional args). NB: off None still asks!
        o = src.GetWorldLocation() ; p = _shifted(target.GetWorldLocation(), off)
        dx,dy,dz = p - o
        return bool(can_detect(src, target, dist_sq_gu=dx*dx + dy*dy + dz*dz))    # G10; NOT memoised (optional arg)
    except Exception: return True

_steer_point(torpedo, target, off):
    offset = getattr(torpedo, "_target_offset", None)
    if not isinstance(offset, TGPoint3):
        pos = target.GetWorldLocation(); return _shifted(TGPoint3(pos.x,pos.y,pos.z), off)
    key = getattr(torpedo, "_mount_key", None)
    if key is None or key[0] is not target or key[1] != offset.x or key[2] != offset.y or key[3] != offset.z:
        key = torpedo._mount_key = (target, offset.x, offset.y, offset.z,
                                    authored_mount_subsystem(target, (offset.x, offset.y, offset.z)))   # PS:502: scan of _iter_subsystems, eps 1e-5
    return _shifted(target_offset_world(target, offset, key[4]), off)                                # SS:92 (K2 F4 / K1 F11)
```

- `target_offset_world` (SS:92-136): `pos = target.GetWorldLocation()`; `part_transform_point(target, point, authored=mount_sub is not None, prop=physical_parents.property_of(mount_sub) ...)` (ART:718: the point itself unless a posable, non-detached part with a non-identity pose); `scale = float(target.GetScale()) if hasattr(...) else 1.0`; `o = (px*scale, py*scale, pz*scale)`; `o.MultMatrixLeft(rot)` if `rot` is a `TGMatrix3`; `pos + o`. No `scale <= 0` guard.
- **In the capture every visible steer had a target offset** (418,453 `target_offset_world` calls for 418,453 `_steer_point` calls, §9): the SDK AI and K1 stamp a subsystem lock's mount on nearly every torpedo. So the posed-target case (Birds of Prey with wings off identity) reaches `part_transform_point` on the live path, and is the main K3 fallback driver (§8.3 risk 3).
- `_mount_key` is computed at the first VISIBLE guided tick (not at launch), once per shot. The torpedo's target and offset never change after launch (`_target_ship` and `SetTargetOffset` are written only in `_spawn_projectile`, before `register`), so the key is never recomputed in practice. Capture: 1,319 attributions over 22,487 ticks (0.06 a tick).

### A1.4 `_broadphase(moving, ship_cache, offsets)` (PR:711-788)

```
out = [[] for _ in moving]
by_set = {}                                                     # torpedo set -> member indices, in moving order
for torp_set, members in by_set.items():
    same, other = [], []
    for j, entry in enumerate(ship_cache):
        off = offsets.setdefault((entry[5], torp_set), frames.offset_between(entry[5], torp_set))   # SHIP set -> torpedo set
        if off is None: continue                                # another frame: never interacts
        (same if off == _ZERO_OFFSET else other).append(j [, off])          # tuple ==: -0.0 counts as zero
    if same:
        at = {id(ship_cache[j][0]): k for k, j in enumerate(same)}          # duplicate ship: LAST k wins
        starts = prev_pos xyz per member ; lens = seg_len per member ; skips = at.get(id(t._source_ship), -1)
        centres = (sx,sy,sz) per same ; bounds = bound per same
        pairs = get_store().sweep_candidates(starts, lens, skips, centres, bounds)   # PQ:60 — native, exact, NaN stays a candidate
        for (ti, si) in pairs: out[members[ti]].append(same[si])
    for j, off in other:                                        # a ship in ANOTHER REGION of the same system
        for i in members:
            if ship is t._source_ship: continue
            seg_prev = _shifted(prev_pos, off) ; d = (sx,sy,sz) - seg_prev ; reach = bound + seg_len
            if d·d > reach*reach: continue                      # B2, same expression as PQ
            out[i].append(j)
    if other: for i in members: out[i].sort()                   # merge to ascending j
return out
```

- Candidate order is ascending `ship_cache` index for every torpedo, so "first hit wins" means **first by `all_ships` order among ships alive at step start**.
- `sweep_candidates` is the existing native kernel, bit-exact with the Python rejection by construction (PQ comment, `test_transform_sweep_candidates.py`).

### A1.5 `expire(torpedo)` (PR:545-557) — the only effects inside the scope

```
try: _active.remove(torpedo)                   # _ActiveList.remove -> _scan_drop: torpedo_scan row removed, _group_leave, _scan_live = 0
except ValueError: return                      # already gone: no set removal, no event
kset = torpedo.GetContainingSet() ; if kset is None: return
kset.RemoveObjectFromSet(torpedo.GetName())    # SETS:277: contact_index.on_removed, _fire("removed"), _broadcast_set_transition (ShipClass-filtered),
                                               #   sensor_contacts.on_exited_set, ObjectGroup.broadcast_membership (WeakSet walk), _clear_containing_set (-> Torpedo._containing_set = None)
_post_set_transition(torpedo, entered=False)   # PR:524: TGEvent ET_TORPEDO_EXITED_SET, source = dest = torpedo, AddEvent (synchronous SDK handlers)
```

### A1.6 Where decide ends and effects begin

| Step | Pure (K3) | Effect (Python) |
|---|---|---|
| Empty registry | `if not _active` | — (stay Python, before any marshalling) |
| Ship cache | `IsDead` (needs `has_real_is_dead`), position, `bubble_bound_radius`, set | — |
| Guide | offset, IsDead, speed, visibility (native can_detect + latch), steer point, lead, turn | writes are kernel-owned flight state (§7.6.2) |
| Advance | position, age, TTL | store write (native can write the store directly) |
| Broadphase | all (already native in part) | — |
| Narrow | `shields_block`, bubble, sphere, ray, hull trace | `_bubble_entry` write (record field) |
| Expire | the ordered list | `expire(t)` each: set removal + `ET_TORPEDO_EXITED_SET` |
| Hits | the ordered list, with tier for object identity | returned; HL:1320 `apply_hit` per hit |

---

## A2. Attributes the path reads, and where they are written

"Mirrored" = already a Native descriptor with a row in `mirror.h`. "**NEW**" = K3 must add it. "row" for torpedo fields means a new torpedo row (there is none today; §A9).

### A2a. Torpedo (`Torpedo(ObjectClass)`, PR:27-299)

| Attr | Read by | Type | Write sites | Mirror |
|---|---|---|---|---|
| transform (pos) | `GetTranslate` (update_all, `_guide`) | double[3] in TransformStore via `_xform` | `SetTranslateXYZ`: WS:602 (spawn), PR:873 (TTL), PR:977 (advance / bubble); tests | native store; row holds `_xform` (TSC rows already do) |
| `_vel` (behind property `_velocity`) | guide (speed, current), advance | TGPoint3, rebound (never mutated in place) | PR:87 `__init__` (zeros), WS:629 spawn (only if `|world_dir| > 1e-6`), PR:1133 `_guide`; tests set `_velocity` | TSC row has `vel` (pushed by the setter only while the table is live, PR:243); **NEW** kernel-owned |
| `_age` | guidance window, G7, TTL | float | PR:88 init, PR:871 `+= dt`; tests | **NEW** kernel-owned |
| `_ttl` | TTL | float | PR:89 init 60.0, `SetLifetime` PR:218 (SDK `mod.Create`, before `register`) | **NEW** (push on write) |
| `_target_ship` | guide gate, `_guide` | ref Object or None | PR:92 init; WS:647/650 spawn (before `register`) | **NEW** ref |
| `_target_offset` | `_steer_point` | TGPoint3 copy or None | PR:99 init; `SetTargetOffset` PR:205 (WS:648, before `register`) | **NEW** vec3 + set flag |
| `_mount_key` | `_steer_point` | tuple (target, x, y, z, Subsystem or None) | PR:102 init; PR:1054 (first visible steer) | **NEW** or ASK (§A8.3 risk 3). *Round trips (2026-11-01): attributed natively (`authored_mount_subsystem`) and written quietly at DONE, unless `kMountUnknown` or a non-ShipClass target (still the ASK `unattributed`).* |
| `_guidance_lifetime`, `_guidance_initial` | gate, G7 | float | PR:103/104 init 4.0; `SetGuidanceLifetime` PR:215 (both) | **NEW** |
| `_max_angular_accel` | G7 | float | PR:105 init 0.125; `SetMaxAngularAccel` PR:219 | **NEW** |
| `_last_seen_target_pos` | `_guide` invisible branch | TGPoint3 or None | PR:106 init; PR:1087 | **NEW** kernel-owned (vec3 + set flag) |
| `_last_target_vel` | G3 | TGPoint3 or None | PR:107 init; PR:1101 | **NEW** kernel-owned (vec3 + set flag) |
| `_src` (behind `_source_ship`) | `_target_visible`, broadphase skip, narrow skip | ref Object (strong) or None | PR:83/108 init; WS:601 spawn (before `register`) | TSC row has source **id**; **NEW** ref handle |
| `_cset` (behind `_containing_set`) | `frames.containing_set(t)` | ref Set or None | PR:82 init; ObjectClass init; `SetClass.AddObjectToSet` at `_join_source_set` (PR:520, inside `register`); `_clear_containing_set` (expire) | TSC row has `group = id(set)`; **NEW** Set handle |
| `_bubble_entry` | HL:1329 `shield_point` | TGPoint3 or None | PR:114 init; PR:943 (hit pair only) | output of the hit record |
| `_damage`, `_damage_radius_factor` | HL:1321 (`apply_hit` args), `weapon_splash_radius(torpedo)` | float | spawn / SDK `SetDamage`; **pulse `_damage *= GetDamageScale()` AFTER `register` (WS:2949)** | not read by the kernel; stay Python |
| `_id`, name | `expire` (`GetName`), render | int / str | `register` PR:480, `_join_source_set` PR:520 | not read by the kernel |
| `GetObjID()` | TSC row id | int | TGObject | TSC |

### A2b. Ships (each `all_ships` entry: ship-cache and narrow test)

| Attr | Read by | Type | Write sites | Mirror |
|---|---|---|---|---|
| `_dead`, `has_real_is_dead` | cache filter (no `hasattr`), `_guide` IsDead | bool / flag | OBJ:851 NativeField; `SetDead` OBJ:~920 | mirrored |
| TransformStore pos / rot | cache, sphere, bubble, steer, ray sphere tier | double | store | native |
| `_radius`, `_scale` | `world_radius`, `bubble_bound_radius`, `target_offset_world` | float | OBJ:87/88 NativeField | mirrored |
| `_shield_hull_box` | `_hull_box_for` in bound and bubble | ((3),(3)) | HL `_cache_shield_hull_box` (realize) | mirrored (K2: center/half/`hull_box_set`) |
| `_containing_set` | cache, frames | ref Set | OBJ:89 NativeRefField | mirrored |
| `_shield_subsystem` + shield row (`has_shields`, `_is_on`, condition) | `shields_block` | — | — | mirrored (K2) |
| `_cloaking_subsystem` → `_cloak_state` | `shields_block` | — | — | mirrored |
| `_velocity` | G3/G4 lead (`GetVelocityTG` on the TARGET) | VEC3 | OBJ:627 NativeField (`PhysicsObjectClass`) | mirrored (1b) |
| `has_posed_parts` | target offset on a posed target | flag | NC `push_posed_parts` | mirrored (1b) |
| child subsystems' `_position` | `authored_mount_subsystem` (once per shot) | VEC3 | — | mirrored per subsystem; the ship's child list is **not** a ship-row field (only `_hull` and the 4 weapon systems are) → ASK (inferred: no `_children`-style list on the Object row) |
| render InstanceId | `_resolve_hit_point` | — | `session.ship_instances` (TrackedInstances) | K2 context table (`_k2_iids`) |
| class flags | IsDead / GetWorldLocation / GetRadius / GetScale / GetVelocityTG / GetShields not overridden | — | — | K2 override guard (`test_native_k2_override_guard.py`) covers most; K3 adds its own list |
| source ship's `_containing_set` and pos | `_target_visible` | — | — | mirrored |

### A2c. Sets and frames (NEW for K3 and K4)

`frames.offset_between(a, b)` (FR:59-67): `a is b` → `(0,0,0)` if `a` is a `SetClass` else None; otherwise `frame_of` both (FR:34-45: `region_hooks.is_mapped(set)` → `Frame(("system", system_of(name)), anchor_of(name))`, else `Frame(("set", set), (0,0,0))`; non-set → None); different keys → None; else `tuple(b - a for a, b in zip(fa.anchor, fb.anchor))`.

- **The Set row's `mapped`/`anchor` (`push_set_frame`, NC:1300) is NOT this.** It is the PROFILE frame: `_resolve_frame` (NC:1251) returns None for a mapped system without a profile or a star. K2's map §2f says the same.
- K3 needs, per Set row: a frame key id (an interned system id, or the set's own handle for a one-set frame) and `anchor_gu` (3 doubles, Python's `float(c)` values). The inputs change at the same two points `push_set_frame` is called (`SetClass.SetName`, `region_hooks.mark_mapped`), or K3 can resolve the few distinct sets per step at begin (inferred: 1-3 sets in a fight).

### A2d. Globals and per-step context

| Name | Value / source | Mirror |
|---|---|---|
| `_LEAD_ACCEL_K` | 0.5 (PR:985) | **NEW** global (ruling G: named constant pushed) |
| `_ZERO_OFFSET` | (0.0, 0.0, 0.0) | literal |
| `SHIELD_ELLIPSOID_AXIS_SCALE` | `3.0 ** 0.5` (CB:391) | mirrored (K2) |
| inline literals | `1e-6` (G1, G5, G8 theta), `1e-9` (A5 seg_len, G3 dt, G7 initial), `1.0` (G7), `-1.0`/`1.0` (G8), `2.0` (A11) | ported verbatim with source-line comments (ruling G) |
| `dt` | `TICK_DT` | argument |
| `ship_instances`, view offsets, NPC-shield cheat, player | K2 `_K2Context` | reuse (K2) |
| can_detect clocks | `_k1_clocks()` (NC:1585): `now()` for nebula drift (frozen at 0.0, 1a latent bug), occlusion `_now()` | reuse (K1) |
| `step_memo.active()` | True inside the step | use_memo flag, as K1/K2 |

---

## A3. Float expressions on the path

All doubles. `TGPoint3.__init__` applies `float()` (exact for floats). `+ - *` on TGPoint3 are component-wise (MATH:140-150). `Length` is `math.sqrt(x*x + y*y + z*z)` (MATH:41: libm `sqrt`, correctly rounded, so `std::sqrt` is exact). `Dot` is `x*o.x + y*o.y + z*o.z`. Left-to-right sums throughout.

**Ship cache and bound**

- **B1. `bubble_bound_radius(ship)`** (CB:916-960):
  ```
  try: radius = world_radius(ship)            # COL:117: r = float(GetRadius()); s = float(GetScale()) via the CLASS attr; r*s if s > 0.0 and isfinite(s) else r
  except Exception: radius = inf
  box = _hull_box_for(ship)                   # CB:308: centre/half * scale; None if any RAW h <= 0.0 (NaN passes); scale <= 0.0 -> 1.0 (NaN passes)
  if box is None: return radius * (1.0 + SHIELD_ELLIPSOID_AXIS_SCALE)
  centre_len = (cx*cx + cy*cy + cz*cz) ** 0.5                 # py_pow, NOT sqrt
  max_semi = max(abs(hx), abs(hy), abs(hz)) * SHIELD_ELLIPSOID_AXIS_SCALE   # 3-arg builtin max = py_max(py_max(a, b), c); fabs
  return max(radius, centre_len + max_semi)                    # py_max
  ```
  - `(1.0 + S)` is evaluated first (parenthesised), then `radius * (...)`.
  - NaN: `max(NaN, x)` is NaN (first argument kept); `max(x, NaN)` is x. A NaN bound keeps every pair a candidate (B2's `>` is False), as PQ documents.
- **B2. Broadphase rejection** (PR:778-783 and PQ:71-77): `ddx = sx - seg_prev.x ...; reach = bound + seg_len; (ddx*ddx + ddy*ddy + ddz*ddz) > reach*reach → reject`. For the shifted case, `seg_prev.x = prev.x + 1.0*off[0]` (FR:177; `1.0*x` is exact).

**Guidance** (`_guide`, PR:1078-1133)

- **G1.** `speed = sqrt(vx*vx + vy*vy + vz*vz)`; `speed < 1e-6 → return` (NaN continues).
- **G2.** `to_t = pos - torp_pos`; `t_go = sqrt(to_t·to_t) / speed`.
- **G3.** `acc_i = (vel_i - prev_vel_i) / dt` when `prev_vel` is a TGPoint3 and `dt > 1e-9`, else `0.0`. `prev_vel` is the last value cached at a VISIBLE tick, possibly many ticks old (a target that re-emerges from cloak gets a large acc spike; copy).
- **G4.** `aim_i = pos_i + vel_i * t_go + _LEAD_ACCEL_K * acc_i * t_go * t_go` → `(pos_i + (vel_i*t_go)) + (((K*acc_i)*t_go)*t_go)`.
- **G5.** `to_aim = aim - torp_pos`; `dist = sqrt(...)`; `dist < 1e-6 → return` (NaN continues).
- **G6.** `desired_i = to_aim_i / dist`; `current_i = v_i / speed`.
- **G7.** `remaining = max(0.0, gl - age)` → `py_max(0.0, gl - age)` (NaN → 0.0); `initial = gi if gi > 1e-9 else 1.0` (NaN → 1.0); `max_step = ((remaining / initial) * maa) * dt`.
- **G8.** `cos_theta = max(-1.0, min(1.0, current·desired))` → `py_max(-1.0, py_min(1.0, d))` (NaN d → 1.0 → theta 0 → `desired`); `theta = acos(cos_theta)` (libm `acos`; CPython's `math.acos` is `acos` with errno checks, the clamp keeps it in domain).
- **G9.** `theta <= max_step or theta < 1e-6 → new_dir = desired`; else `s = sin(theta); a = sin(theta - max_step) / s; b = sin(max_step) / s; new_dir_i = current_i * a + desired_i * b`. Three libm `sin` calls: use `py_sin` (its own noinline TU, py_math.h) so no call is merged or reassociated. `velocity_i = new_dir_i * speed`.
  - NaN `desired` (from NaN aim) passes every guard and yields a NaN velocity; the torpedo then flies NaN until TTL. Copy.
- **G10.** `_target_visible` cross-region distance: `p_i = target_i + 1.0*off_i`; `dx = p.x - o.x ...`; `dist_sq_gu = dx*dx + dy*dy + dz*dz`; passed as a Python float (so the native `can_detect` path is taken, SD:525).
- **G11.** `target_offset_world` (SS:126-136): `(p*scale)` per axis, then `MultMatrixLeft` (`m00*x + m01*y + m02*z` order, MATH:91), then `pos + o`. WG `target_offset_world` already ports it for unposed targets.
- **G12.** `_steer_point` without an offset: `TGPoint3(pos)` then `_shifted(..., off)`: `p_i + 1.0*off_i` only when `off` is non-zero.

**Advance and narrow** (update_all)

- **A1/A2.** `cur_i = prev_i + (v_i * dt)` (`t._velocity * dt` builds the product vector first, then `+`).
- **A3.** `seg_i = cur_i - prev_i` (NOT `v_i * dt`: rounding differs).
- **A4.** `seg_len = sqrt(seg·seg)`.
- **A5.** `aim_unit_i = seg_i / seg_len` if `seg_len > 1e-9` (NaN → None: no bubble, fallback hit point).
- **A6.** `age = age + dt`; `age >= ttl → expire`.
- **A7.** Bubble: K2 F15-F16 (CB:403-482) with `max_dist = seg_len` (`t > float(max_dist) * d_len`). NaN inputs return a NaN POINT, not None.
- **A8.** `sphere_hit` (CB:14-20): `dx = p.x - c.x ...; r = float(radius); (dx*dx + dy*dy + dz*dz) <= r*r` (NaN → False → no hit).
- **A9-A11.** `backoff = radius + seg_len`; `origin_i = seg_cur_i - (aim_i * backoff)`; `ray_max = (2.0 * radius) + seg_len`. `radius` here uses `hasattr(ship, "GetRadius")` (vacuous on a TGObject; ships always have it).
- **A12.** `_resolve_hit_point` tiers (K2 F17/F18, BT `resolve_hit_point`, sphere_fallback=True). The fallback point is `seg_cur`.
- **A13.** Bubble write-back: `cur_pos_i = bubble_i + (-1.0 * off_i)` only when `off` is non-zero.

**Exactness hazard summary for K3**

| Hazard | Where | Rule |
|---|---|---|
| `** 0.5` | B1 `centre_len`, A7 bubble (`d_len`, `disc ** 0.5`), A12 sphere tier | `py_pow` |
| `sqrt` | G1, G2, G5, A4 (`Length`) | `std::sqrt` |
| `acos` | G8 | libm, after the py_min/py_max clamp |
| `sin` ×3 | G9 | `py_sin` |
| `min`/`max` | B1 (2- and 3-arg), G7, G8 | `py_min`/`py_max`, argument order |
| NaN branches | G1/G5 (`<` False → continue), G7 (→ 0.0 / 1.0), G8 (→ 1.0), A5 (→ None), A6 (never expires), A7 (NaN point), A8 (no hit), B2 (candidate) | compare written as Python |
| int/float | `TGPoint3(0, 0, 0)` (float() → 0.0); `max(0.0, ...)`; none else | — |
| signed zero | `off == _ZERO_OFFSET` is a tuple `==` (−0.0 equals 0.0); `_shifted` returns the SAME object on zero | match `==`, keep object identity (§A5) |
| random numbers | **none** in steps 1-3 | — |
| float32 | the hull trace only (BT, renderer's own compiled function) | K2 hooks |

---

## A4. Memos and caches touched

| Cache | Where | Key | Cleared | K3 note |
|---|---|---|---|---|
| native can_detect memo | `SensorState` (Python `_answers` when off) | (observer, target) | every `forget` (`step_memo.on_forget(_h.combat_memo_clear)`, NC:2627) | empty at step start; **guidance is its first filler this step**. Only the same-set / other-frame calls are memoised (`use_memo` requires no `dist_sq_gu`). Capture: 419,816 calls, 205,213 computes (51% memo hits) |
| lock-break latch | native-owned (1a R7) | pair | never per step | written by every non-memo-hit `can_detect`; **order matters** within a pair, so the kernel must call in list order |
| `sensor_occlusion._pair_cache` | per set signature | — | — | inside `can_detect` (native path has its own) |
| Python `_mounts` / native mount memo | SS:59 / SensorState | (sub, ship_arg) | forget | **not used by K3**: `target_offset_world` does not go through `subsystem_world_position` |
| `_mount_key` | per torpedo | (target, offset) | never (per shot) | §A1.3 |
| `articulation.leaf_for` | `ship._articulation_leaf` | — | never | first `part_transform_point` on a posable target writes it (harmless; native must not, as K1/K2) |
| `ids.implements` | ids.py:148 | (class, name) | never | `frames.containing_set` |
| `offsets` dict | update_all local | (ship_set, torp_set) | per call | native: per-call table |
| TransformStore | — | — | — | torpedo positions are read once and written once per torpedo per tick |
| torpedo_scan rows | TSC | torpedo id | `_ActiveList` mutators, rebuild on dirty | `_velocity` setter pushes `set_velocity` only while `_scan_live == _scan_gen and not _scan_dirty` (PR:243) |
| renderer BVH | ray_trace.cc | model | — | lazy, on a hit's trace |

**Consequence.** Nothing inside steps 1-3 can invalidate another decision in them. The only cross-torpedo coupling is the can_detect memo/latch per (source, target) pair, which a native implementation reproduces by calling native `can_detect` in the same order with the same arguments (it is the same function the Python dispatches to).

---

## A5. Decision-path writes, events and Python callbacks, in order

Within one `update_all` call, with `_active` non-empty:

1. **Ship cache.** Reads only. A stub `IsDead` on a ship class without a real one records stub telemetry (an effect) — native must fall back for such a ship (`has_real_is_dead == 0`).
2. **Per torpedo, list order:**
   1. `_guide` (if gated): may call `IsDead` (stub telemetry for a non-DamageableObject target), `can_detect` (native: latch + memo; Python fallback: `log_swallowed`, probe walk, telemetry), `authored_mount_subsystem` (first visible tick), then writes `_mount_key`, `_last_seen_target_pos`, `_last_target_vel`, `_velocity` (→ `torpedo_scan.set_velocity`, a native call).
   2. Store read, `_age += dt`.
   3. TTL: store write, append to `expired`.
3. **Broadphase**: `frames.offset_between` per (ship set, torpedo set); `sweep_candidates`. No writes outside locals.
4. **Narrow, per moving torpedo:** `shields_block` (dev-cheat read; `App.Game_GetCurrentGame().GetPlayer()` only when the cheat is on), bubble, sphere, `_bubble_entry` write on a hit, `_resolve_hit_point` (native trace, may build a BVH lazily), store write of the final position.
5. **`expire(t)` for each of `expired`, in order: TTL-expired (list order), then hit (list order).** Each:
   - `_active.remove` → torpedo_scan row removed;
   - `RemoveObjectFromSet` → `contact_index.on_removed`, the set's "removed" listeners, `sensor_contacts.on_exited_set` (try/`log_swallowed`), `ObjectGroup.broadcast_membership(entered=False)` (a WeakSet walk: ~1,970 iterations per call in the capture), `_clear_containing_set`;
   - **`ET_TORPEDO_EXITED_SET`** via `AddEvent` (SDK handlers: `Conditions/ConditionIncomingTorps.ExitedSet`, E8M2's two handlers; synchronous).
6. Return `hits`. Then, outside the scope, **per hit in order: `combat.apply_hit`** (CB:610: forget, shields, `DamageSystem`, splash, `hit_feedback.dispatch` (audio wall-clock gating, smoke, decals, hull wear, **part severance gated on K4's set**), **`ET_WEAPON_HIT`**, forget).

So the event order of a tick is: all `ET_TORPEDO_EXITED_SET` (TTL first, then hits), then the hits' `ET_WEAPON_HIT` cascades. Every `ET_TORPEDO_EXITED_SET` for a hit torpedo precedes its own `ET_WEAPON_HIT`.

**Random draws:** none in steps 1-5 (inferred from the code read: no `random` in PR, the guidance helpers, or the narrow functions; `apply_hit`'s effects draw, and stay Python).

**Object identity the consumers see** (the K2 "tier" problem):

- Fallback tier: `hit_point` IS `seg_cur`. With a bubble hit, `seg_cur` IS the `bubble_entry` object, which is also `torpedo._bubble_entry` → passed as `shield_point`. **`hit_point is shield_point`** in that case. `WeaponHitEvent.SetHitPoint` stores by reference (events.py:434), so an SDK handler mutating `GetHitPoint()` in place would also move `shield_point`. K3's Python side must rebuild that alias.
- Fallback tier without a bubble and `off` zero: `hit_point` is the `cur_pos` local (a fresh TGPoint3 from `prev_pos + ...`); no other holder.
- Sphere tier "Origin" (`ray_sphere_entry` returns `ray_origin` itself when inside): `ray_origin` is a fresh TGPoint3 (aim branch) or `seg_prev` (= `prev_pos`, a fresh store-read TGPoint3); no other holder (inferred).
- Mesh tier: fresh points.

---

## A6. Ordering contract

1. Ship cache in `all_ships` order, dead-at-start ships dropped.
2. Torpedoes in `_active` order; per torpedo: guide (if `_target_ship is not None and _age < _guidance_lifetime`, the PRE-increment age), advance, age, TTL.
3. Broadphase candidates per torpedo in ascending ship-cache index.
4. Narrow per torpedo in `moving` order (= `_active` order minus TTL expiries); per torpedo, the first candidate (lowest index) that passes the bubble-or-sphere test wins; `break`.
5. Store write of every non-TTL torpedo's final position after its narrow loop.
6. `expire` in `expired` order: TTL list first, then hits.
7. `hits` returned in `moving` order; consumed in that order by HL:1320, each `apply_hit` fully (events and all) before the next. A hit is applied even if an earlier hit killed the ship or an SDK handler removed something.
8. A torpedo registered during HL:1320's loop (by a handler) is not moved until the next tick.

**What can change between ticks and therefore must be re-read at every K3 begin:** the ship list, all positions, `_dead`, shields state, frames, the iids table, the viewing set, the torpedo list (registered in `cb.held_weapons`, by handlers, by K1 effects).

---

## A7. What already exists that K3 can reuse

| Piece | File | K3 use |
|---|---|---|
| `sweep_candidates` | PQ:60-82 | broadphase, same-set case, as is (call it in-kernel instead of through the Python wrapper) |
| `TorpedoScan` rows (id, `_xform` handle, velocity, source id, group = id(set), insertion order, tombstones + compaction) | TSC | **the natural home for K3's torpedo rows** (§A8.1): already kept in `_active` order by `_ActiveList`, already reading positions live from the store |
| `resolve_hit_point` + `TraceHooks` + `narrow_like_pybind` | BT, `beam_trace.cc` | A12 unchanged (the torpedo call passes `fallback_point = seg_cur`) |
| `ray_sphere_entry`, `world_radius`, `shields_block`, `shield_bubble_entry` (with `_hull_box_for` rules) | BG | A7-A12 |
| `_K2Context` (iids table, view offsets, NPC-shield cheat, player) | NC:2370 | the same per-step context |
| `target_offset_world` (unposed target) | WG | G11 |
| `ship_dead` / `has_real_is_dead` | `fire_gates.h` | cache filter, `_guide` IsDead |
| native `can_detect` (memo, latch, `dist_sq_gu`) | `sensor_detect.h` | `_target_visible`, called in-kernel |
| `py_pow`, `py_min`, `py_max`, `py_sin`, `dist3` | `py_math.h` | B1, G7-G9 (and K4) |
| `_k1_clocks`, resumable session, write log (P7), `ASK` (H), `RUN_PYTHON` (P2), pinning | NC:1585, `_K1Walk`, `run_k1`, `run_k2` | ASK protocol |
| override snapshot / unseen-class / `combat_k2_scan_ships` | NC:2065-2290 | K3's patch-point check; one shared ships→handles scan per step (K4, K3, K2 all take `ships_list`) |

**K3 needs new:** a torpedo row; a set-frame table (A2c); `bubble_bound_radius` (B1); `sphere_hit` (A8); the guide (G1-G10); the advance (A1-A6); the narrow loop's control flow; `_LEAD_ACCEL_K`; an `acos` wrapper (consider a noinline TU next to `py_sin` for symmetry; inferred unnecessary since nothing pairs `acos`).

---

## A8. Risks, kernel shape, tests

### A8.1 Suggested kernel shape

Because steps 1-3 post no event (§A1 corrections), K3 can be **one batch call per tick** plus ASKs:

- Python, unchanged first line: `if not _active: return []` (zero cost in the quiet scene).
- `combat_k3_begin(ship_handles, dt, clocks, use_memo, ctx)` where `ship_handles` is the same array K4 and K2 use this step (one `combat_k2_scan_ships`-style scan per step), and `ctx` is the K2 context plus the set-frame table.
- The kernel walks: ship cache → per torpedo row (table order = `_active` order) guide/advance/TTL → broadphase → narrow → writes the store positions directly → returns `DONE(writes, expired[], hits[])`, or an `ASK` first.
- Records:
  - `ASK steer_point(t)` → Python `_steer_point(t, target, off)` (posed target, or `_mount_key` attribution needed). Cheaper alternative for the attribution: `ASK mount_key(t)` once per shot at its first visible tick (0.06/tick in the capture), then native `target_offset_world` when the target is unposed.
  - `ASK guide(t)` → run Python `_guide(t, dt)` whole for one torpedo (unregistered target, stub IsDead, non-float state), then the kernel re-reads that torpedo's Python state (requires the write log to have been applied up to that torpedo, or the torpedo's fields pushed back).
  - `ASK narrow(t)` / `ASK resolve_hit(...)` for an unrepresentable ship or set (K2 precedent).
  - `RUN_PYTHON` (whole step) for: `type(_active) is not _ActiveList` (tests monkeypatch `_active` with a plain list), a patched module function (§A8.3 risk 9), a dirty scan table that cannot be rebuilt, an unseen class.
  - `DONE(writes, expired, hits)`: `writes` = per torpedo `_age`, and for guided ones `_vel`, `_last_seen_target_pos`, `_last_target_vel` (and `_mount_key` if native attributed it); `expired` = torpedo ids in `expired` order; `hits` = (torpedo, ship, point, tier, normal | None, bubble | None).
- Python then: apply `writes` (bypassing the `_velocity` property's scan push when the kernel already updated the row), call `expire(t)` for each in order, rebuild `hits` with the tier-correct object identity (§A5), return.

**State ownership.** Spec §7.6.2 makes flight state native-owned, but phase 1b's P7 chose write-log copy-back so Python state stays valid. For K3 copy-back is cheap at the measured 30-110 torpedoes (≈ one `_age` write each plus ~19 guided velocity writes a tick, inferred ~10-30 µs in Debug) and it is **required** by `_scan_rebuild` (PR:467): a dirty table is rebuilt from the Python `_vel`, `_xform`, `_src`, `_cset`, so a native-only velocity would be overwritten by a stale Python one. Recommend P7 copy-back; revisit native-only getters only if a profile shows the copy-back.

### A8.2 Ordering contract for the kernel

Reproduce §A6 exactly, plus within `_guide`: `offset_between` before `IsDead`; `IsDead` before speed; `_target_visible` before the steer point; the three writes before the `dist < 1e-6` return.

### A8.3 Risks

1. **No torpedo mirror row (R12).** `_hidden_fields` refuses Torpedo (hidden scalar `_radius`). A K3 row is new work: either a `Kind::Torpedo` in the mirror or an extended `TorpedoScan` row. The TorpedoScan route reuses the `_ActiveList` sync, insertion order and live store reads, but the table is **only live after the first `incoming_ids` rebuild** (`_scan_dirty` starts True, PR:392); while dirty, writers skip it. K3 begin must rebuild a dirty table (or fall back).
2. **Python readers of flight state outside `update_all`.** `_build_torpedo_render_data` reads `t._age` and `_torpedo_forward(t)` reads `t._velocity` (HL:1460-1527, once per frame per torpedo); `_build_dynamic_light_render_data` (HL:1541); `GetVelocityTG` (SDK `EvadeTorps`, camera_modes torpedo cam); `_walk_incoming_ids` / `_closing_time` (the plain-list path); `_scan_rebuild`. Each needs the current value at its read time → copy-back before control returns to Python (§A8.1).
3. **Posed targets.** Every visible steer in the capture used a target offset, so `part_transform_point` runs on the hot path. For a target with a part off identity (Birds of Prey with wings moved; all of K2's 80 ship fallbacks were `posed_ship`), the kernel must ASK. Also the `_mount_key` attribution scans the target's child subsystems, which the Object row does not list; and Python attributes it at the FIRST VISIBLE guided tick, so a native version that attributes later (or earlier) could pick a different subsystem only if the target's subsystem list changed meanwhile (inferred rare). ASK at the same tick keeps it exact.
4. **Frames.** Guidance (torpedo set → target set), visibility (source set → target set), broadphase and narrow (ship set → torpedo set) all use `offset_between`, which needs a frame key + anchor per set that the mirror does not have (A2c). Cross-region torpedoes exist in production (in-system warp regions of one star system); the tripwire test `test_frame_tripwire.py` covers them.
5. **The ship cache's `IsDead` has no `hasattr` guard** (PR:843). A ship class without a real `IsDead` would be a stub call → telemetry + "dead". Fall back for `has_real_is_dead == 0`.
6. **Event order.** `ET_TORPEDO_EXITED_SET` for TTL expiries first, then for hits, all before any `ET_WEAPON_HIT`. Keep `expire()` Python and call it in the kernel's `expired` order.
7. **Object identity** of `hit_point` / `shield_point` (§A5). Carry a tier and a "hit point is the bubble object" flag.
8. **Headless coverage.** As K2 risk 1: no instances and no hull boxes headless, so the bubble and the mesh trace are invisible to headless differentials. Several torpedo tests monkeypatch `_hull_box_for` to get a bubble; a host-level differential (real `g_world`, cached boxes) is needed for the trace tier.
9. **Patch points used by tests** (all must send the step to Python, by identity snapshot as in K2 §5.3 / C2): `projectiles._target_visible`, `projectiles._shifted`, `projectiles._active` (plain list), `frames.offset_between`, `combat._hull_box_for`, `combat.bubble_bound_radius`, `combat.apply_hit` (outside the kernel; fine), `host_io.ray_trace_mesh`, `part_severance._mounted_subsystems`, `sensor_detection.ENHANCED_SENSOR_CONTEST` (a constant: push, as 1a does), `collisions._BROADPHASE` (not on this path). Plus the functions K3 replaces: `_guide`, `_steer_point`, `_broadphase`, `sphere_hit`, `shield_bubble_entry`, `shields_block`, `_resolve_hit_point`, `ray_sphere_entry`, `world_radius`, `subsystems.target_offset_world`, `part_severance.authored_mount_subsystem`, `sensor_detection.can_detect`, `frames.containing_set`, and the Torpedo / ship methods `GetTranslate`, `SetTranslateXYZ`, `GetVelocityTG`, `IsDead`, `GetWorldLocation`, `GetScale`, `GetRadius`.
10. **can_detect order.** The memo and latch make visibility order-dependent per (source, target) pair. The kernel calls the same native `can_detect` in list order; cross-region calls carry `dist_sq_gu` and skip the memo, exactly as Python. `_target_visible`'s `off is None` case still calls plain `can_detect` (it does not short-circuit to "invisible").
11. **Mission swap never clears `_active`** (inferred: no engine site calls `_active.clear()`; only tests do, via `tests/helpers/in_flight.py` and `tests/integration/conftest.py`). Torpedoes of the previous mission keep flying in their (deleted) set until TTL, and `expire` then removes them from that set and posts `ET_TORPEDO_EXITED_SET` into the new mission's handlers. K3 rows must survive a swap with their Python objects, and this latent quirk is copied, not fixed (for Mark).
12. **Population and cost model.** Captures show 31-110 in flight; the TS docstring's 1,500 is unconfirmed. The per-tick cost is dominated by per-torpedo Python overhead and the ship cache; a native kernel removes almost all of it, but the effect part (`expire`, ~3.5% of the scope) and the write-back stay.
13. **Hits are batch decisions.** The static-world assumption (no ship moves or dies inside `update_all`) holds today because effects run after. A K3 that applied hits as it found them would change the game.
14. **Torpedo targets are ships in practice, but not by type.** A target with a stub `IsDead` (e.g. a torpedo or a non-DamageableObject) goes ballistic with telemetry → ASK `is_dead` (K2's precedent).

### A8.4 Existing tests on this path

All focused; none were run for this map.

| File | Pins |
|---|---|
| `tests/unit/test_torpedo_advance.py` (10) | position += v·dt, age, TTL expiry, sphere collision, source skip, dead-ship skip, homing turns, dumbfire unchanged, guidance window ends, host trace used |
| `tests/unit/test_torpedo_guidance_fidelity.py` (9) | BC ctor defaults, lead pursuit, linearly decaying turn budget, dead target ballistic, cloaked target → frozen last-seen, cloak inside/outside the bubble, contest off, constant speed (FakeShip fixtures: native must fall back) |
| `tests/unit/test_torpedo_subsystem_homing.py` (6) | steer to the aimed subsystem, centre without offset, target frame, scale, mount attributed once per shot, re-attributed on a new offset/target |
| `tests/unit/test_target_offset_articulation.py` (7) | `target_offset_world` on posed targets; wings-down exactness |
| `tests/unit/test_projectile_broadphase.py` (8) | `bubble_bound_radius` is conservative (sphere, ellipsoid, off-centre, no box, unreadable radius → inf), inf never culls, idle scene builds no cache |
| `tests/unit/test_torpedo_broadphase.py` (2), `tests/unit/test_transform_sweep_candidates.py` (6) | the native sweep and update_all's use of it |
| `tests/unit/test_projectiles_hit_point_shape.py`, `tests/integration/test_torpedo_hit_point_on_mesh.py`, `tests/unit/test_torpedo_decal_emission.py` (2) | hit tuple shape; hit point from the mesh trace; normal forwarded to apply_hit |
| `tests/unit/test_torpedo_shield_impact_vfx.py` (7), `tests/unit/test_shield_bubble_entry.py`, `tests/unit/test_shield_facing_from_bubble_entry.py`, `tests/unit/test_rock_shield_collision.py` | bubble detonation and the shield flash through `_advance_combat` |
| `tests/unit/test_torpedo_set_membership.py` (18) | ENTERED/EXITED_SET events, set membership, single post on double expire |
| `tests/unit/test_cross_set_interaction_gate.py` (22), `tests/integration/test_frame_tripwire.py` (9) | cross-frame never interacts; cross-region hit/homing in system coordinates |
| `tests/unit/test_collision_radius_scale.py` (12) | hit radius = GetRadius × GetScale |
| `tests/unit/test_torpedo_scan_conformance.py` (13), `native/tests/transforms/torpedo_scan_test.cc` | the scan table vs the Python walk |
| `tests/integration/test_torpedo_lock_homes_to_target.py`, `test_torpedo_no_lock_dumbfires.py`, `test_torpedo_targets_subsystem.py`, `test_torpedo_launcher_drf_override.py`, `test_disruptor_fire_and_damage.py`, `test_evade_torps_sees_incoming.py` | end-to-end fire → fly → hit |
| `tests/host/test_combat_step_sensor_answers.py` | guidance shares can_detect answers with the pumps inside the step |
| `tests/unit/test_lc_intrepid_pyc_projectiles.py`, `test_pulse_aimed_launch.py`, `test_spread_skew_wiring.py` | launch-side state the kernel reads |
| `tests/integration/test_native_k1_differential.py`, `test_native_combat_step_differential.py` | headless step differentials; torpedoes fly in Python under them today; the template for a K3 differential (add torpedo positions/velocities by `.hex()` and the EXITED_SET/WEAPON_HIT order) |

No test pins by name: the TTL-before-hit order of `ET_TORPEDO_EXITED_SET`, the `hit_point is shield_point` alias, the NaN-velocity path, or `_target_visible`'s `off is None` case.

---

## A9. Torpedo lifecycle (new mirror rows)

1. **Create.** Only `weapon_subsystems._spawn_projectile` (WS:575) constructs a `Torpedo` in production (WS:599), called from `TorpedoTube` fire (WS:3546, then `_broadcast_torpedo_fired`) and `PulseWeapon._fire_effect` (WS:2944). `App.Torpedo_Create` does not exist in our `App.py`; its only SDK caller, `MissionLib.FireTorpFromPlacement`, has no SDK callers.
   - `Torpedo.__init__` (PR:78-133): `_scan_live = 0`, `_cset = None`, `_src = None` BEFORE `super().__init__()`; `ObjectClass.__init__` allocates `_xform` and tries `native_combat.register(self, "Object")` (refused: hidden scalar). Then the flight fields get their defaults (`_velocity` zeros, `_ttl` 60.0, `_guidance_lifetime/_initial` 4.0, `_max_angular_accel` 0.125, ...).
   - `_spawn_projectile` order: `_source_ship = climb_to_ship()`; `SetTranslateXYZ(emitter world position)`; **`mod.Create(torp)`** (SDK script: `CreateTorpedoModel`/`CreateDisruptorModel`, `SetDamage`, `SetDamageRadiusFactor`, `SetGuidanceLifetime`, `SetMaxAngularAccel`, `SetLifetime`, `SetNetType`); DRF override; `_velocity` (if `|dir| > 1e-6`); `_target_ship` + `SetTargetOffset` (only if the emitter's `_target` is alive); **`register(torp)`**; launch sound attach + Play.
   - Pulse only: `torp._damage *= GetDamageScale()` AFTER `register` (WS:2949), so `ET_TORPEDO_ENTERED_SET` handlers see the unscaled damage. Not a kernel field.
2. **Register** (PR:478-521): `_id = _next_id` (monotonic); `_active.append` (→ `_scan_add`: a torpedo_scan row unless the table is dirty); `_join_source_set`: if the source implements `GetContainingSet` and is in a set, `AddObjectToSet(torp, "Torpedo %d")` (→ `_containing_set` setter → scan group) and **`ET_TORPEDO_ENTERED_SET`** (synchronous). A sourceless torpedo flies in no set (frames → None → interacts with nothing).
   - **K3 row creation point:** at `_active.append` (where the scan row is created), with every flight field captured from the Python object then; later writes to `_ttl`, `_guidance_*`, `_max_angular_accel`, `_target_ship`, `_target_offset`, `_src` must push (all happen before `register` in production, but the setters are SDK surface, so make them pushing).
3. **Fly.** `update_all` each tick (Part A).
4. **Expire** (PR:545): from `update_all` only in production (TTL or hit). `_active.remove` → `_scan_drop` (row removed); set removal; `ET_TORPEDO_EXITED_SET`. A second `expire` is a no-op (ValueError path).
5. **List mutations other than append/remove** (`clear`, `insert`, `__setitem__`, `__delitem__`, `sort`, `reverse`): mark the scan dirty → rebuilt in list order from Python state at the next query. Used by fixtures (tests clear `_active` between tests via `tests/helpers/in_flight.py`). K3 must treat dirty as "rebuild from Python before running".
6. **Store replaced** (tests): `torpedo_scan.get_scan()` notices a new store singleton, clears, and calls `projectiles._scan_reset()` (TS:156-172).
7. **Mission swap**: nothing clears `_active` or the scan in production (inferred, §A8.3 risk 11). Rows live as long as the torpedo is in `_active`; the Python object lives at least that long (strong ref), and its `_xform` is freed by `ObjectClass`'s finalizer after collection.
8. **Quick Battle restore / ship rebuild**: not torpedo-specific (inferred: no site touches `_active`). A torpedo whose target is rebuilt keeps a strong ref to the old ship object; the old ship's mirror row stays alive with it.

---

## A10. Per-tick cost composition (inferred)

**Source:** `~/Documents/dauntless-perf/pyprof5-cs64-20261030-2334.cb.projectiles.prof` (pre-1a Python, code equal to main `a0d81c7d4`, worktree `anim-visibility`; 64 AI ships + player). 22,487 `update_all` calls (ticks). cProfile total 66.3 s → 2.95 ms a tick profiled, against ~0.8-1.1 ms unprofiled (≈3× inflation). **Shares are what matter.**

**Counts per tick (derived: calls ÷ 22,487)**

| Quantity | /tick | Source |
|---|---|---|
| torpedoes in flight (store writes) | ~89 | `SetTranslateXYZ` 2,005,778 |
| guided (`_guide` calls) | ~18.7 (21%) | 419,816 |
| visible steers / with a target offset | ~18.6 / ~18.6 | `_steer_point` / `target_offset_world` 418,453 |
| real can_detect computes (rest memo hits) | ~9.1 (51% hits) | `_can_detect` 205,213 |
| mount attributions | ~0.06 | `authored_mount_subsystem` 1,319 |
| ships cached | ~58.4 | `bubble_bound_radius` 1,314,014 |
| narrow pairs reaching `shields_block` | ~0.51 | 11,555 |
| hits (`_resolve_hit_point`) | ~0.082 | 1,837 |
| expiries (hits + TTL) | ~0.11 | `expire` 2,528 (TTL ≈ 691 ≈ 0.03/tick) |

**Share of the scope's cProfile time (66.3 s)**

| Group | Time | Share | Notes |
|---|---|---|---|
| `_guide` (cumulative) | 29.3 s | 44% | `_target_visible` 11.3 s (17%; can_detect 9.35 s, native since 1a), `_steer_point` 8.75 s (13%; `target_offset_world` 7.76 s, `part_transform_point` 3.1 s), own math |
| per-torpedo store round trip | ~9.2 s | ~14% | `GetTranslate` 5.7 s (126/tick: step 1 + guide), `SetTranslateXYZ` 3.5 s |
| ship cache | ~9 s | ~14% | `bubble_bound_radius` 6.5 s (9.8%) + IsDead, GetWorldLocation, containing_set for ~58 ships |
| `frames.containing_set` (all) | 5.8 s | 8.7% | 5.2 M calls, 3.3 M from update_all |
| `update_all` self | 5.45 s | 8.2% | |
| `_broadphase` | 4.45 s | 6.7% | native sweep 0.53 s of it |
| `expire` (effect, stays Python) | 2.29 s | 3.5% | `RemoveObjectFromSet` 1.27 s (broadcast_membership WeakSet walk 1.2 s), EXITED_SET post 1.0 s |
| `torpedo_scan.set_velocity` | 0.67 s | 1.0% | one native call per guided torpedo |
| narrow (bubble, shields_block, sphere, resolve) | ~0.35 s | <1% | |

**Unprofiled per-tick measurements (perf register):** fight `cb.projectiles` 1.144 (87 in flight) / 0.875 (48) (SIG-154, 1a off/on); 0.991 (65) / 0.772 (55) (SIG-158, 1b off/on); 0.916 / 0.827 (SIG-163, K1 → K2, ~61 → ~38 in flight). Quiet: 0.003 (SIG-155, SIG-159). `cb.projectiles` "falls with the projectile count by itself" (SIG-154, SIG-158). Derived: ~13-22 µs per torpedo per tick in Debug including the fixed ship cache (inferred split: ~0.12 ms fixed + the rest per torpedo, weighted toward guided torpedoes).

**What stays Python after K3:** `if not _active`, begin/marshalling, the write-back (~89 `_age` + ~19 velocity triples), `expire()` per expiry (~0.11/tick but each is costly: set removal + SDK event), building the hit list, and ASKs (posed targets).

---

# Part B — K4: `cb.eligibility`

## B1. Call graph

### B1.0 Where it runs

HL:1312-1313, first thing in the step, before `cb.projectiles`:

```
with frame_profiler.scope("cb.eligibility"):
    damage_eligibility.update(ships_list)
```

Also `damage_eligibility.reset()` at mission swap (`_drain_pending_swap`, HL:7795, call at HL:7858) → `_current = frozenset()`.

### B1.1 The code verbatim in structure (DE:31-108)

```
update(ships):                                                       # DE:96
    try:
        import App
        game = App.Game_GetCurrentGame() if hasattr(App, "Game_GetCurrentGame") else None
        player = game.GetPlayer() if game is not None and hasattr(game, "GetPlayer") else None
    except Exception: player = None
    set_current(select_eligible(player, ships))                       # DE:75: _current = frozenset(ids)

select_eligible(player, ships, *, max_count=DEFAULT_MAX_ELIGIBLE):   # DE:35; DEFAULT_MAX_ELIGIBLE (6) bound at DEF time
    ships = list(ships)
    eligible = set()
    if player is not None: eligible.add(id(player))                  # player always, even if not in `ships`
    max_r = max((_radius(s) for s in ships), default=0.0) or 1.0    # E1
    def score(s):                                                     # E2
        size = _radius(s) / max_r
        if player is None: return SIZE_WEIGHT * size
        prox = 1.0 / (1.0 + frames.system_distance(s, player))       # FR:205 (E3)
        return PROX_WEIGHT * prox + SIZE_WEIGHT * size
    others = [s for s in ships if player is None or id(s) != id(player)]
    others.sort(key=lambda s: (-score(s), id(s)))                    # E4: key computed ONCE per element
    for s in others:
        if len(eligible) >= max_count: break
        eligible.add(id(s))
    return frozenset(eligible)

_radius(ship) = float(ship.GetRadius()) if hasattr(ship, "GetRadius") else 0.0          # DE:31 — RAW radius (not × scale)
```

**Facts**

- `ships` is every ShipClass in every set: alive and dead, rocks, the player, ships in unrelated frames. No IsDead filter.
- The result is a frozenset of `id()`s (CPython addresses), not object ids.
- `PROX_WEIGHT` / `SIZE_WEIGHT` (1.0 each) are module globals read at CALL time; `DEFAULT_MAX_ELIGIBLE` is the default argument, frozen at definition (patching the global has no effect).

## B2. Attributes read, and where they are written

| Object | Attr | Read by | Mirror |
|---|---|---|---|
| every ship | `_radius` (via `GetRadius`, raw) | E1, E2 | mirrored (`o_radius`, OBJ:87) |
| every ship + player | TransformStore position | `system_distance` (`_xyz` → `GetWorldLocation`) | native store |
| every ship + player | `_containing_set` | `frames.containing_set` (via `implements(..., "GetContainingSet")`) | mirrored |
| sets | frame key + anchor (`frame_of`) | `offset_between` | **NEW** (A2c; shared with K3) |
| every ship | `id(s)` | tie-break, result | **NEW**: an `id()` per row (constant for the object's lifetime) or passed per step |
| player | `App.Game_GetCurrentGame().GetPlayer()` | `update` | per-step argument (K2 already resolves the player for the cheat, `_k2_player_handle`) |
| module | `PROX_WEIGHT`, `SIZE_WEIGHT` | E2 | push at call or snapshot-check (ruling G) |
| class flags | `GetRadius`, `GetWorldLocation`, `GetContainingSet` are the stock ones | — | the K2 override guard covers `GetWorldLocation`/`GetRadius`; add `GetContainingSet` |

## B3. Float expressions

- **E1.** `max(gen, default=0.0) or 1.0`: builtin max keeps the first maximum (`item > current` replaces), so `py_max` folded left from the first element; empty → `0.0`; then Python truthiness: `0.0` and `-0.0` → `1.0`; **NaN is truthy and stays NaN** (a NaN first radius makes max_r NaN; a NaN later radius is never chosen).
- **E2.** `size = r / max_r`; `prox = 1.0 / (1.0 + d)`; `score = (PROX_WEIGHT * prox) + (SIZE_WEIGHT * size)`, or `SIZE_WEIGHT * size` without a player.
- **E3.** `system_distance(a, b)` (FR:205): `pb = local_in(containing_set(a), b)` = `(bx + off0, by + off1, bz + off2)` (always adds, even a zero offset: `-0.0 + 0.0 = +0.0`, irrelevant to the distance); None (other frame, or either side in no set) → `math.inf` → `prox = 0.0`. Else `math.dist(_xyz(a), pb)`: **CPython 3.11.15's `vector_norm`, not `sqrt(dx²+dy²+dz²)`** (differs on ~1 pair in 5, py_math.h) → use the existing `dist3`.
- **E4.** Sort key `(-score, id)`: tuple compare is `==` then `<` per element. `-0.0 == 0.0`, so a zero score ties to `id`. Keys are unique (id), so for non-NaN scores the order is total and any exact top-N selection by this comparator gives the same SET as Python's sort.
- **NaN hazard.** A NaN score makes the key incomparable (`nan == x` and `nan < x` both False): timsort's result then depends on its exact merge pattern. A native port must not try to reproduce that: **fall back to Python when any score is NaN** (or any radius/position is non-finite).
- **inf hazards.** `max_r = inf` → `size = r/inf` = 0.0 or NaN (inf/inf) → covered by the NaN rule. `d = inf` → `prox = 0.0`.
- No `** 0.5`, no trig, no random numbers. `dist3` is the only nontrivial primitive (already ported and self-checked at import, NC:205).

## B4. Memos and caches

None. `frames` is uncached by design (FR docstring: a set's frame changes once, at `mark_mapped`). The result `_current` is the only state.

## B5. Writes, events, callbacks

- One write: `damage_eligibility._current = frozenset(...)`.
- No events. `App.Game_GetCurrentGame()` / `GetPlayer()` reads. A ship class with a stub `GetRadius` / `GetContainingSet` would record stub telemetry (`hasattr` vacuous on TGObject; `implements` is not vacuous): fall back for unrepresentable rows.

## B6. Ordering contract and what the result feeds

- Computed once per step from positions at step start (before torpedoes move).
- **Consumer: `hit_feedback.dispatch` §5 only** (HF:426-446): `damage_eligibility.is_eligible(ship)` gates `part_severance.record_hit` for a structural hit with `absorbed_hull > 0`, a mesh normal, `persist_decal` and `ship_instances`. It is reached through `apply_hit` for: torpedo hits (HL:1320, same step), phaser pulses (`cb.phasers`, same step), and any `apply_hit` / dispatch outside the step until the next one (inferred: collisions in `gl.motion` read the previous step's set).
- K4 can therefore be a pure function returning ≤ 6 ships; Python builds the frozenset of `id()`s. Nothing between `cb.eligibility` and its consumers needs a re-ask.

## B7. What exists to reuse

- `dist3` (py_math.h; `combat_test_dist3` self-check at import).
- The step's ship→handle array (K2's `combat_k2_scan_ships`), shared with K3.
- The player handle resolution (`_k2_player_handle`, NC:2335) — but K4's `update` uses the same `hasattr` + swallow chain, so the same function serves.
- Set-frame table: shared new work with K3 (A2c).

## B8. Risks, kernel shape, tests

**Suggested shape.** `combat_k4_eligible(ship_handles, player_handle, max_count, prox_w, size_w) -> list[int]` returning indices into `ships_list` (or `RUN_PYTHON`). Python: `ids = {id(player)} if player is not None else set(); ids.update(id(ships_list[i]) for i in idx); set_current(ids)`. Keep `select_eligible` untouched as the reference and test entry point; switch only `update()`.

**Fallback (whole function) when:** any ship has no row or a −2 ref; the player is not None and has no row; a set has no frame entry; any radius, position or score is non-finite; a patched `select_eligible`/`frames.system_distance`/`frames.offset_between`/`math.dist`/`_radius`; an override of the read methods.

**Risks**

1. **`id()` tie-break.** Python's ids are addresses; the kernel needs them per ship (a constant row field set at register, or a per-step array). Equal scores are common (identical stock ships at identical distance, `prox = 0.0` for every cross-frame ship, `player is None` with equal radii), so the tie-break is load-bearing.
2. **NaN ordering** (B3): fall back.
3. **`math.dist`**, not `sqrt`: use `dist3`.
4. **Duplicates.** A ship listed twice is added twice to `others`; the second `add` does not grow the set, so a seventh distinct ship can get in (inferred harmless edge; the native top-N must walk the sorted order and count distinct ids the same way, or fall back on duplicate handles).
5. **The quiet-scene tax.** `cb.eligibility` costs 0.267-0.291 ms per tick whether or not anyone fires (SIG-154/155/158/159/163). It is the one combat scope that is fully paid in the quiet scene, so K4 is the only K-phase gain the quiet capture can show.
6. **Driver overhead dominates a native K4** (inferred): the kernel is ~63 `dist3` calls; the ships→handles scan and the result build are the cost. Share the scan with K3/K2 (one per step) or K4 alone may not halve its scope in Debug.

**Existing tests**

| File | Pins |
|---|---|
| `tests/unit/test_damage_eligibility.py` (12) | player always, cap, nearest preferred at equal size, largest at equal distance, size-only without player, `is_eligible` reads `_current`, max_count 0, all-zero radii (the `or 1.0`), empty list, `update` without a game, `update` resolves the player, cross-frame ship gets no proximity credit (fakes and direct `select_eligible` calls: unaffected by a native `update`) |
| `tests/integration/test_frame_tripwire.py::test_damage_eligibility_never_ranks_cross_frame_above_same_frame` | cross-frame ship never outranks a same-frame one |
| `tests/unit/test_hull_wear.py`, `tests/unit/test_collision_hull_wear.py`, `tests/unit/test_apply_hit_intensity.py`, `tests/host/test_render_space_feeds.py` | the consumer, mostly with `is_eligible` monkeypatched |

No test drives `update()` through `_advance_combat` and checks the set against a reference; a K4 differential should compare `_current` per tick (as sets of ids) in the K3 step differential.

## B9. Per-tick cost composition

**Source:** `pyprof5-cs64-20261030-2334.cb.eligibility.prof`, 22,487 calls, 14.94 s → 0.66 ms profiled vs 0.27-0.29 ms unprofiled (≈2.3× inflation).

| Group | Time | Share | Notes |
|---|---|---|---|
| `others.sort` (all key calls) | 13.66 s | 91% | 63 keys a tick (1,418,130 ÷ 22,487) |
| `system_distance` | 10.97 s | 73% | 2 `GetWorldLocation` per key (the player's is re-read 63 times a tick), `containing_set`, `offset_between`, `local_in` |
| `GetWorldLocation` (store reads) | 5.40 s | 36% | 2,836,260 calls |
| `math.dist` | 0.11 s | 0.7% | the arithmetic itself is negligible |
| `_radius` | 1.12 s | 7.5% | 2 per ship (max and key) |
| `max(...)` generator | 0.79 s | 5% | |

Native K4 (inferred): ~63 distance evaluations reading the store directly, well under 10 µs of kernel time; the remaining cost is the call, the handle array and the frozenset build.
