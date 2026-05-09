# Combat and Damage

How `stbc.exe` resolves collisions, weapon hits, and explosions into
shield/subsystem/hull damage. Every code path eventually funnels into
the same `DoDamage` → `ProcessDamage` pipeline; what differs is *how*
the damage is constructed before it arrives, and *whether* it goes
through the pre-shield gates first.

---

## Damage pipeline at a glance

```
COLLISION
  CollisionDamageWrapper (0x005B0060)
    ├─ SubsystemDamageDistributor (0x005AFD70)   ← shield + per-subsystem absorption
    │    walks ship+0x284 list, modifies *damage in place
    └─ DoDamage_FromPosition (0x00593650)        ← gets REDUCED damage
         └─ DoDamage (0x00594020)
              └─ ProcessDamage (0x00593E50)

  DoDamage_CollisionContacts (0x005952D0)
    └─ loops contact points, each calls DoDamage(damage, 6000.0)

WEAPON
  WeaponHitHandler (0x005AF010)
    ├─ ray-ellipsoid shield gate (0x0056A690)    ← ~72% stopped here
    ├─ SubsystemDamageDistributor (0x005AFD70)   ← same as collision
    └─ ApplyWeaponDamage (0x005AF420)
         └─ DoDamage(damage*2.0, radius*0.5)
              └─ ProcessDamage

EXPLOSION (opcode 0x29)
  Explosion_Net (0x006A0080)
    └─ ProcessDamage  (DIRECT — bypasses DoDamage)
```

`ProcessDamage` always runs at the end. Each `DoDamage` call produces
exactly one `ProcessDamage` call (1:1; no filtering between them).

### Stock-session counts

For a baseline of how many of these hits actually reach damage code,
two stock combat sessions surveyed 79,605 collision-checks vs 229
damage events (~0.3% trigger rate) and 1,939 weapon-hits vs 536 hull
hits (28% pass rate after the shield gate). Numbers worth carrying
forward as sanity checks for any reimplementation, but not gospel —
they reflect the specific scenarios traced.

---

## `DoDamage` (`0x00594020`)

`__thiscall(ECX = ship, float* hitDir, float damage, DWORD radius)`,
`RET 0x0C`. The central damage entry. Every path except direct
explosions goes through here.

### Gates

If either of these is `NULL`, the call **silently drops** — no event,
no error, no log:

| Offset      | Type     | Field                                                   |
|-------------|----------|---------------------------------------------------------|
| `ship+0x18` | `NiNode*`| Scene-graph root — ship must have a loaded model        |
| `ship+0x140`| `NiNode*`| Damage target reference                                 |

### `DamageVolume`

If both gates pass, `DoDamage` builds a `DamageVolume` (`0x38` bytes)
via `FUN_004BBDE0`:

- Hit direction is transformed world → source-local → target-local.
- Uses the NiNode bounding-sphere radius (`node+0x94`) for scaling.
- Uses the rotation matrix at `node+0x64` (3×3) for coord transforms.
- Builds an axis-aligned bounding box from the centre + radius.

Then calls `ProcessDamage` with the volume.

---

## `ProcessDamage` (`0x00593E50`)

`__thiscall(ECX = ship, DamageVolume* dmgVol)`, `RET 0x04`. Distributes
the volume to subsystems and hull.

### Resistance scaling

| Offset       | Field                       | Effect                          |
|--------------|-----------------------------|----------------------------------|
| `ship+0x1B8` | damage radius multiplier    | `1.0` = normal, `0.0` = immune  |
| `ship+0x1BC` | damage falloff multiplier   | applied to falloff curve         |

### Two parallel subsystem catalogues

Critical: the engine maintains **two separate** subsystem
data structures on each ship, and confusing them silently breaks
either damage or state-update behaviour:

| Offset       | Type        | Used for                                          |
|--------------|-------------|---------------------------------------------------|
| `ship+0x128` | handler array (count at `+0x130`) | **Damage distribution** (this section) |
| `ship+0x284` | linked list (count at `+0x280`)   | State serialization, `SubsystemDamageDistributor` |

`ProcessDamage` iterates `+0x128`. The state-update / network code
walks `+0x284`. Both must be populated for a working ship.

### Per-handler dispatch (`FUN_004B1FF0`)

Each handler in the array has two possible actions, gated on flag bytes:

- **Shield path:** `handler+0x20` → if zone's `+0x18` flag set,
  `FUN_004B4B40` (shield-geometry intersection).
- **Hull path:** `handler+0x1C` → if flags `+0x08` or `+0x09` set,
  `FUN_004BD9F0` (**AABB overlap test**, *not* distance-to-nearest).

The hull check is an axis-aligned bounding-box test against all 6
planes of the damage volume vs the subsystem's box. There is no
"50% overflow to nearest" mechanic anywhere in the engine — that's
a misconception worth flagging because it produces structurally
different damage distribution.

### Hull damage and notification

- Hull is forwarded via `ship+0x13C` → `FUN_00593EE0`.
- Notification (`FUN_00593F30`) is **client-only** — gated on
  `IsHost == 0` at `0x0097FA89`. On the server, damage is applied
  silently; clients get the visual/audio feedback via the callback
  at `0x005927E0` → `DamageTickUpdate` (`0x00592960`).

### Conditions that disable damage

| Condition                                     | Where             | Effect                                         |
|-----------------------------------------------|-------------------|-------------------------------------------------|
| `ship+0x18 == NULL`                          | DoDamage gate     | Silent drop                                     |
| `ship+0x140 == NULL`                         | DoDamage gate     | Silent drop                                     |
| `ship+0x128 == NULL` or `+0x130 == 0`        | ProcessDamage     | Subsystem loop is a no-op                       |
| `ship+0x13C == NULL`                         | ProcessDamage     | Hull damage skipped                             |
| `ship+0x1B8 == 0.0`                          | ProcessDamage     | Damage radius zeroed → effectively immune       |
| `ship+0x1BC == 0.0`                          | ProcessDamage     | Falloff zeroed → effectively immune             |
| `handler+0x20+0x18 == 0`                     | per-handler       | Per-handler shield zone inactive — skip shield  |
| Hull damage flags (`+0x08`,`+0x09`) both 0   | AABB handler      | Subsystem won't take damage                     |
| `IsHost == 1`                                 | Notification      | Damage applied, no event callback (by design)   |
| `DAT_008E5C1C == 0`                           | Notification      | Global damage events disabled                   |

### Ship damage-related offsets (cross-reference)

| Offset       | Type     | Field                                                |
|--------------|----------|------------------------------------------------------|
| `+0x18`      | `NiNode*`| Scene-graph root                                     |
| `+0xD8`      | `float`  | Mass (collision-damage formula)                      |
| `+0x128`     | `void**` | Subsystem damage handler array                       |
| `+0x130`     | `int`    | Handler count                                        |
| `+0x13C`     | `void*`  | Hull damage receiver                                 |
| `+0x140`     | `NiNode*`| Damage target reference                              |
| `+0x1B8`     | `float`  | Damage resistance multiplier                         |
| `+0x1BC`     | `float`  | Damage falloff multiplier                            |
| `+0x1C4`     | `void*`  | Active damage notification handler (1 = pending)     |
| `+0x280`     | `int`    | Subsystem count (linked list)                        |
| `+0x284`     | `void*`  | Subsystem linked-list head                           |
| `+0x2C0`     | `void*`  | `ShieldClass*`                                       |

---

## Collision

### `CollisionDamageWrapper` (`0x005B0060`)

`__thiscall(ECX = ship, int collider, float searchRadius, float damage)`.
The single-point collision entry. Two-step:

```c
void CollisionDamageWrapper(Ship* this, int collider, float searchRadius, float damage) {
    // 1. Subsystem distributor — modifies damage in place
    FUN_005AFD70(this, collider+0x88, &damage, searchRadius, NULL, /*isCollision*/ 1);

    // 2. Remaining damage → DamageVolume → hull
    DoDamage_FromPosition(this, collider, searchRadius, damage);  // reduced
}
```

Crucially `&damage` is *passed by pointer* — by the time
`DoDamage_FromPosition` sees `damage`, shields and subsystems have
already absorbed their share and reduced it.

### `SubsystemDamageDistributor` (`FUN_005AFD70`)

The primary shield-interaction function for both collision and weapon
paths. Walks `ship+0x284` and applies directional damage subsystem-by-
subsystem (shield facings are subsystems too).

```c
void FUN_005AFD70(
    Ship*  this,
    float* position,        // damage origin in world space
    float* damage,           // pointer — modified in place!
    float  searchRadius,     // spatial-search expansion (1.5 for collisions)
    int*   source,           // attacker (NULL for collisions)
    int*   isCollision);     // 1 = collision, 0 = weapon
```

1. `FUN_005AECC0` walks `ship+0x284` and builds a hit list of
   subsystems within `searchRadius × subsystem.boundingRadius` from
   the damage origin. **Shield facings appear in this list as ordinary
   subsystems.**
2. Power-subsystem exclusion (weapon-only): when `isCollision == 0`
   and more than one subsystem is hit, the power subsystem
   (`ship+0x2C4`) is removed from the list. This is the **only**
   per-call behavioural difference between collision and weapon.
3. For each subsystem, `FUN_005AF4A0` applies damage and returns
   any overflow:

   ```c
   float curHP = subsystem+0x30;
   float maxHP = FUN_0056C310(subsystem);
   float newHP = curHP - damage;
   float overflow = newHP < 0 ? -newHP : 0;
   FUN_0056C470(ship, newHP);   // SetCondition — clamps, fires event
   ```

   `FUN_0056C470` clamps `newHP` to `[0, maxHP]`, computes the
   condition ratio at `+0x34`, and fires `ET_SUBSYSTEM_HIT`
   (`0x0080006B`) when `newHP < maxHP` and the ship is alive.
4. Total overflow is written back to `*damage` for the caller.

The `isCollision` parameter passed to per-subsystem damage is
*always* `'\0'` — collision and weapon damage follow identical logic
at the subsystem level.

### `DoDamage_CollisionContacts` (`0x005952D0`)

Multi-contact collision damage. The `CollisionResult` struct
(`0x58` bytes) carries the contact list:

| Offset | Field                                                    |
|--------|----------------------------------------------------------|
| `+0x38`| `contactCount`                                           |
| `+0x40`| `collision_force` (impulse magnitude)                    |
| `+0x44`| Contact-list head (linked list of `0x1C`-byte contacts)  |

```
raw     = (force / mass) / contactCount
scaled  = raw * 0.1 + 0.1            ; DAT_00893f28 = 0.1, DAT_0088bf28 = 0.1
clamped = min(scaled, 0.5)            ; DAT_008887a8 = 0.5
damage  = clamped × 6000.0            ; max damage cap (0x45BB8000)
```

Each contact point goes through its own `DoDamage` call.

### `HostCollisionEffectHandler` (`0x005AFAD0`)

The *other* collision damage path — fires after a `CollisionEffect`
opcode `0x15` from a peer. Different scaling constants and different
output range:

```
raw = (collisionEnergy / mass) / contactCount
if raw > 0.01:                        ; DAT_00888a78 = 0.01 (dead zone)
    scaled = raw * 900.0 + 500.0      ; absolute HP, NOT fractional
    SubsystemDamageDistributor(ship, dir, &scaled,
                               shieldScale=1.5, attacker, flags=1)
```

Each subsystem receives the *full* per-contact damage; overflow is
accumulated and written back through `*damage` after all subsystems
process. Distinct from `DoDamage_CollisionContacts`: different
constants (`900× + 500` vs `0.1× + 0.1`), no hard cap. Collision
effect goes through this path in multiplayer; the contact-list path
runs in single player and on the server side of the original event.

### Why collision often *appears* to bypass shields

It does not — collision damage uses the same `SubsystemDamageDistributor`
that weapons do. But several factors make it feel that way:

1. Weapons have a **pre-gate**: the ray-ellipsoid intersection at
   `0x0056A690` stops ~72% of weapon hits before any damage code runs.
   Collisions have no such gate; 100% reach the damage path.
2. Collisions don't exclude the power subsystem (`isCollision = 1`),
   so they can hit the warp core directly.
3. Multi-contact collisions hit shields once per contact point, so
   the same total energy can overwhelm a single facing faster than a
   single weapon hit.

---

## Shields

Each ship has six shield facings; they are independent subsystems
with their own HP and recharge.

### Facings

| Index | Facing  | Ship-local axis  |
|-------|---------|------------------|
| 0     | FRONT   | +Y (forward)     |
| 1     | REAR    | -Y (aft)         |
| 2     | TOP     | +Z (up)          |
| 3     | BOTTOM  | -Z (down)        |
| 4     | LEFT    | -X (port)        |
| 5     | RIGHT   | +X (starboard)   |

Constants:

```c
enum ShieldFacing {
    NO_SHIELD       = -1,
    FRONT_SHIELDS   = 0,
    REAR_SHIELDS    = 1,
    TOP_SHIELDS     = 2,
    BOTTOM_SHIELDS  = 3,
    LEFT_SHIELDS    = 4,
    RIGHT_SHIELDS   = 5,
    NUM_SHIELDS     = 6,
};
```

Opposite pairs: 0↔1, 2↔3, 4↔5.

### `ShieldClass` (vtable `0x00892F34`, size `0x15C`)

Inherits from `PoweredSubsystem`. Important fields:

| Offset  | Type             | Field                                         |
|---------|------------------|-----------------------------------------------|
| `+0x18` | `ShieldProperty*`| Property template (max values, charge rates)  |
| `+0x20` | `void*`          | `Ship*`                                       |
| `+0x38` | `byte`           | `hasActiveHits`                               |
| `+0x40` | `void*`          | `shieldZoneList` (linked list)                |
| `+0x9C` | `byte`           | `isEnabled` — 0 = off (e.g. cloak), nonzero = active |
| `+0xA8` | `float[6]`       | `curShields[facing]` — current HP per facing  |
| `+0xC0` | `float[6]`       | `shieldPercentage` — cached per facing        |
| `+0xDC` | `struct[7]`      | shield watchers (per-facing + 1 overall)      |
| `+0x14C`| `byte[6]`        | `shieldDamaged[facing]` flag                  |
| `+0x154`| `float`          | `envDamageRadius`                             |
| `+0x158`| `float`          | `envDamageRate`                               |

### `ShieldProperty` (vtable `0x00892FC4`, size `0x88`)

Read-only template. Set by hardpoint scripts.

| Offset  | Type        | Field                                                |
|---------|-------------|------------------------------------------------------|
| `+0x20` | `float`     | `maxHP` (overall subsystem health)                   |
| `+0x40` | `float`     | `currentPower`                                       |
| `+0x48` | `float`     | `tickPhaseOffset` — random per-shield event stagger  |
| `+0x60` | `float[6]`  | `maxShields[facing]`                                 |
| `+0x78` | `float[6]`  | `chargePerSecond[facing]`                            |

Default `maxShields` from the constructor: `0x447A0000` = `1000.0`.

### Facing determination (`FUN_0056A8D0`)

It is **not** a dot-product test. It's a **maximum-component**
projection — the cheapest test that produces correct results for an
axis-aligned shield ellipsoid:

1. Reorder impact normal `{X, Y, Z}` → `{Y, Z, X}`.
2. Find the maximum *positive* among indices 0–2.
3. Find the maximum *negated* among indices 3–5 (the most-negative
   of `Y`, `Z`, `X`).
4. The dominant index maps to a facing through a fixed switch:

```c
// indices: 0=+Y, 1=+Z, 2=+X, 3=-Y, 4=-Z, 5=-X
switch (dominant) {
    case 0: return FRONT_SHIELDS;   // +Y
    case 1: return TOP_SHIELDS;     // +Z
    case 2: return RIGHT_SHIELDS;   // +X
    case 3: return REAR_SHIELDS;    // -Y
    case 4: return BOTTOM_SHIELDS;  // -Z
    case 5: return LEFT_SHIELDS;    // -X
}
```

Equivalent to "find the dominant face of a unit cube enclosing the
normal" — no trig, no dot products, pure comparisons.

### Ray-to-facing (`FUN_0056A690`)

When a weapon ray is tested against the shield, the engine:

1. Transforms the ray endpoints from world to the ellipsoid's local
   space.
2. Normalises by the ellipsoid semi-axes (stored at `node+0x24C`,
   `+0x250`, `+0x254`) — the ellipsoid becomes a unit sphere.
3. Runs ray-vs-unit-sphere intersection (`FUN_004570D0`).
4. Computes the outward normal at the hit point.
5. Un-normalises back to ship-local space.
6. Calls `FUN_0056A8D0` to map the normal to a facing.

### Two absorption paths

#### Area-effect (`FUN_00593C10`) — explosion only

Distributes damage *equally* across all 6 facings:

```
damagePerFacing = totalDamage * (1/6)         ; DAT_0088bacc = 0x3E2AAAAB
for facing in 0..5:
    absorbed       = min(damagePerFacing, curShields[facing])
    curShields[facing] -= absorbed
    totalAbsorbed  += absorbed
overflow = totalDamage - totalAbsorbed
if overflow > 0:
    apply to hull
```

Per-facing, *not* all-or-nothing. A ship with 5 full facings and 1
empty absorbs 5/6 of the damage.

#### Directed (via `ProcessDamage`) — weapons and collisions

Damage goes through the handler array described above. The shield
facing's hit list is processed through the event system; the actual
HP decrement happens via `FUN_0056A5C0` (`SetCurShields`).

The weapon hit handler (`FUN_005AF010`) checks `weaponHitInfo+0x58`
to decide whether the hit penetrated:

| `+0x58` | Meaning                                              |
|---------|------------------------------------------------------|
| `== 0`  | Shield absorbed (visual effect, no hull damage)      |
| `!= 0`  | Shield breached (hull effect + DoDamage to hull)     |

#### `SetCurShields` (`FUN_0056A5C0`)

```c
void SetCurShields(ShieldClass* this, int facing, float newHP) {
    float maxHP = this->property->maxShields[facing];
    if (maxHP < newHP) newHP = maxHP;       // cap
    if (newHP < 0.0f) newHP = 0.0f;         // floor
    this->curShields[facing] = newHP;
}
```

### Shield recharge (`FUN_0056A420` — `BoostShield`)

```c
float BoostShield(ShieldClass* this, int facing, float powerAmount) {
    float normalizedPower = this->property->currentPower * (1.0f / 6.0f);
    if (normalizedPower <= 0.0f) return powerAmount;          // no power → no recharge
    float chargeRate = this->property->chargePerSecond[facing];
    float hpGain    = (chargeRate * powerAmount) / normalizedPower;
    float newHP     = this->curShields[facing] + hpGain;
    this->curShields[facing] = newHP;
    if (newHP > this->property->maxShields[facing]) {
        float ratio  = chargeRate / normalizedPower;
        float excess = (newHP - max) / ratio;
        this->curShields[facing] = max;
        return excess;                                          // unused power
    }
    return 0.0f;
}
```

`powerAmount` is *not* a frame-time delta — it's an energy budget
allocated by the `PoweredSubsystem` per tick. The `1/6` factor
distributes total power equally across the six facings, and any
overflow is returned to the caller for redistribution.

### Recharge scheduling

Recharge runs through the **event system**, not a direct per-tick
call:

1. `ShieldProperty` constructor (`FUN_0056B970`) seeds a random
   phase offset:
   ```c
   this->tickPhaseOffset = rand() * 0.33 * 3.05e-05;
   ```
   So shields on different ships don't all recharge in lockstep.
2. `FUN_0056BDE0` (called when power changes) schedules periodic
   events `0x0080006D`–`0x00800071` via `FUN_0044C2D0`.
3. `HandleSetShieldState` (`0x0056AAE0`) is the registered handler;
   it calls `BoostShield` per facing and redistributes overflow.

### Cloak / shield interaction

Shields do **not** drop to zero HP when a ship cloaks. The HP is
*preserved*; the subsystem is functionally disabled.

When `StartCloaking` (`FUN_0055F360`) sets `cloakObj+0xAD = 1`:

1. The cloak handler (`FUN_0055F110`) schedules a delayed event
   `0x00800077` (shield-off) using a delay equal to
   `DAT_008E4E20` — the `CloakingSubsystem` `ShieldDelay`, default
   `1.0` seconds.
2. After the delay, event `0x00800077` fires and sets
   `shieldClass+0x9C = 0` (disabled).

On decloak: event `0x00800079` fires immediately, sets
`shieldClass+0x9C` back to nonzero. If shield HP went `<= 0` while
cloaked, it gets reset to `1.0` HP on decloak.

`CloakingSubsystem.SetShieldDelay(n)` modifies the global
`DAT_008E4E20` and therefore affects **every** cloaking ship in the
session — it is class-level state, not per-ship.

### Stock Sovereign shield numbers

| Facing | maxShields | chargePerSecond |
|--------|-----------:|-----------------:|
| Front  | 11,000     | 12.0             |
| Rear   |  5,500     | 12.0             |
| Top    | 11,000     | 12.0             |
| Bottom | 11,000     | 12.0             |
| Left   |  5,500     | 12.0             |
| Right  |  5,500     | 12.0             |

Shield Generator subsystem `MaxCondition`: 10,000.

Other ships (representative): Galaxy 5,600/12, Akira 3,600/11,
Warbird 4,000/8, Vor'cha front 24,000/28, others 2–9.

### Shield gate conditions

| Condition                                  | Where             | Effect                              |
|--------------------------------------------|-------------------|--------------------------------------|
| `shieldClass == NULL`                      | `FUN_00593C10`    | All damage to hull                  |
| `shieldClass+0x9C == 0`                    | shield checks     | Shields disabled (cloak)            |
| `FUN_0056C350(...)` true                   | shield checks     | Shield subsystem destroyed          |
| `handler+0x20+0x18 == 0`                   | per-handler       | Shield zone inactive                |
| `curShields[facing] == 0`                  | absorption        | Facing depleted — overflow to hull  |
| `property+0x48 <= 0`                       | BoostShield       | No power → no recharge              |

### Verified shield constants

| Address      | Value      | Float       | Meaning                              |
|--------------|------------|-------------|---------------------------------------|
| `0x0088BACC` | `0x3E2AAAAB`| `0.16667`  | `1/6` per-facing share                |
| `0x00888B54` | `0x00000000`| `0.0`      | Floor                                 |
| `0x00888860` | `0x3F800000`| `1.0`      | One                                   |
| `0x008887A8` | `0x3F000000`| `0.5`      | Half (weapon damage radius scale)     |
| `0x008E4E20` | `0x3F800000`| `1.0`      | `CloakingSubsystem.ShieldDelay`       |
| `0x008E4E1C` | `0x40A00000`| `5.0`      | Cloak rate                            |
| `0x00892FC0` | `0x3EA8F5C3`| `0.33`     | Random phase scale (shield stagger)   |
| `0x00888B58` | `0x358637BD`| `≈1e-6`    | Epsilon                               |

---

## Weapons

### Class hierarchy

```
Weapon (vtable 0x00892FC4, size ~0x90)
 ├── EnergyWeapon (vtable 0x008930D8, size ~0xC8)
 │    └── PhaserBank (vtable 0x00893194, size 0x128)
 └── (subclass) Weapon (vtable 0x00893834)
      └── TorpedoTube (vtable 0x00893630, size 0xB0)

WeaponSystem
 ├── PhaserSystem
 └── TorpedoSystem
```

### Vtable slots used by every Weapon

| Slot | Offset  | Method                        |
|------|---------|-------------------------------|
| 30   | `+0x78` | `StopFiring`                  |
| 31   | `+0x7C` | `Fire(dt, flag)` — actual fire|
| 32   | `+0x80` | `TryFire(dt, flag)`           |
| 33   | `+0x84` | `CanFire()` — gate            |
| 36   | `+0x90` | `SetPowerSetting(int)`        |

### `EnergyWeapon` / `PhaserBank` layout

| Offset  | Type    | Field                                                  |
|---------|---------|--------------------------------------------------------|
| `+0x18` | ptr     | `EnergyWeaponProperty*`                                |
| `+0x24` | ptr     | parent `WeaponSystem*`                                 |
| `+0x34` | float   | `power_level` (0.0–1.0, default 1.0)                   |
| `+0x40` | ptr     | `Ship*` owner                                          |
| `+0x48` | float   | `random_delay` (init: `rand() * scale`)                |
| `+0x88` | byte    | `is_firing`                                            |
| `+0xA0` | float   | `charge_level` (or int `numReady` for `TorpedoTube`)  |
| `+0xBC` | float   | `charge_percentage` (cached for display)               |
| `+0xC0` | char*   | `fire_start_sound` (lazy-built)                        |
| `+0xC4` | char*   | `fire_loop_sound` (lazy-built)                         |
| `+0xF4` | int     | `intensity_mode` — 0 LOW, 1 MED, 2 HIGH                |

### `EnergyWeaponProperty` layout

| Offset  | Field                  | Sovereign default |
|---------|------------------------|------------------:|
| `+0x40` | base subsystem `condition` | 1000.0       |
| `+0x68` | `MaxCharge`            | 5.0               |
| `+0x6C` | `RechargeRate`         | 0.08              |
| `+0x70` | `NormalDischargeRate`  | 1.0               |
| `+0x74` | `MinFiringCharge`      | 3.0               |
| `+0x78` | `MaxDamage`            | 300.0             |
| `+0x7C` | `MaxDamageDistance`    | 70.0              |

### Phaser charge formula (`FUN_00572B80`)

`PhaserBank::UpdateCharge(float dt, float power_multiplier)`. Two
modes by `is_firing`:

#### Mode 1 — recharging (`is_firing == 0`)

```
delta = recharge_rate * power_level * dt * power_multiplier
if !ownerShip:
    delta *= DAT_00890550        ; AI/remote-ship penalty
charge += delta
charge  = min(charge, max_charge)
```

The AI/remote multiplier penalises non-owner ships (other players,
AI). On a host, "owner" means `g_TopWindow->playerShip == owner_ship`.

#### Mode 2 — discharging (firing, intensity HIGH or mode 3)

```
charge -= discharge_rate * dt
if charge <= 0:
    charge = 0
    StopFiring()
```

Discharge rate comes from `FUN_00572B00`:

| Mode          | Constant            |
|---------------|---------------------|
| 0 (LOW)       | `DAT_0089317C`      |
| 1 (MED)       | `DAT_00893180`      |
| 2 (HIGH)      | `DAT_00893184`      |
| other         | `0.0` (no drain)    |

Per-tick damage during phaser fire:

```
damage = max_damage * (power_level * parent_power) * charge_ratio
       * intensity_scale * dt
```

where `charge_ratio = min(charge / max_damage_distance, 1.0)` and
`intensity_scale` comes from `DAT_00893170/0x00893174/0x00893178`
for modes 0/1/2.

### Phaser `CanFire` gate conditions

The vtable slot at `+0x84` (`PhaserBank::CanFire` at `0x00571E60`,
overriding `EnergyWeapon::CanFire` at `0x0056FA10`). Composite of:

1. **Ship is alive** — `GetShipFromParent(parent)` non-NULL and ship
   alive flag set (`FUN_00562210` checks vtable `+0x08` for class
   `0x801C`).
2. **Subsystem is alive (HP > 0)** — `FUN_0056C350` recursive check
   (current HP ≥ threshold across the weapon tree).
3. **Charge ≥ MinFiringCharge** — `charge_level ≥ property+0x74`.
4. **Weapon-system can-fire flag** — `property+0x48` byte.
5. **Cloaking gate** — handled at the **system** level via the event
   system, not in `CanFire` itself. `ET_START_CLOAKING` disables the
   weapon system's ability to call `Fire`; weapons themselves don't
   know about cloak state directly.
6. **Subsystem not "disabled"** — the `DisabledPercentage` threshold
   from the hardpoint (typically 0.75).

### Phaser `Fire`

When `PhaserBank::Fire` (`0x00570FE0`) succeeds:

1. Beam visual is created via `FUN_00578180`.
2. Beam velocity set from weapon direction vectors.
3. `is_firing = 1`.
4. Sound system triggered.
5. If host, `FUN_005762B0` / `FUN_0057D110` serialise the fire over
   the network.
6. Beam damage flows through normal damage pipeline.
7. Subsequent `UpdateCharge` ticks discharge the bank.

When charge depletes:

```
charge_level = 0.0
StopFiring()       ; vtable+0x78
```

### Phaser intensity (opcode `0x12`, `SetPowerSetting`)

`SetPowerSetting` (vtable `+0x90`). In multiplayer, the level change
forwards as opcode `0x12` (`SetPhaserLevel`) through the shared
event handler `FUN_0069FDA0`. The intensity value lives at
`parent+0xF0` and controls discharge rate, damage output, and
charge-consumption rate.

### Phaser beam fire wire format (opcode `0x1A`)

Handler `FUN_0069FBB0`. Forwards to all peers via the "Forward"
group, then reads:

```
[byte:0x1A]
[int32: weapon_object_id]
[byte:  flags]
[CompressedVector3: hit_position]
[byte:  more_flags]
[if has_target: int32 target_id]
```

Looks up the weapon via `FUN_006F0EE0`; calls `FUN_005762B0` (beam
fire init) with the deserialised data.

### Torpedo

`TorpedoTube` (vtable `0x00893630`, size `0xB0`) layout:

| Offset  | Type    | Field                                                    |
|---------|---------|----------------------------------------------------------|
| `+0x18` | ptr     | `TorpedoTubeProperty*`                                   |
| `+0x24` | ptr     | parent `TorpedoSystem*`                                  |
| `+0x34` | float   | `power_level`                                            |
| `+0x40` | ptr     | `Ship*` owner                                            |
| `+0x8C` | int     | `target_id`                                              |
| `+0xA0` | int     | `num_ready`                                              |
| `+0xA4` | float   | `last_fire_time` (init `-1000.0` = `0xC47A0000`)         |
| `+0xA8` | byte    | `is_skew_fire`                                           |
| `+0xAC` | float[] | `reload_timers` — one slot per `max_ready`               |

`TorpedoTubeProperty`:

| Offset  | Field            | Sovereign default |
|---------|------------------|------------------:|
| `+0x88` | `ReloadDelay`    | 40.0              |
| `+0x8C` | `MaxReady`       | 1                 |
| (?)     | `ImmediateDelay` | 0.25              |

`TorpedoSystem` (parent):

| Offset      | Type   | Field                                            |
|-------------|--------|--------------------------------------------------|
| `+0x1C`     | int    | `num_weapons`                                    |
| `+0xF0`     | float  | `last_system_fire_time`                          |
| `+0xF4 + N*4`| int[] | per-type ammo remaining                          |
| `+0x114`    | int    | `current_ammo_type`                              |
| `+0x118`    | int    | `total_ammo_consumed`                            |

### Reload timer states

Per slot at `tube+0xAC`:

| Value     | Meaning                              |
|-----------|--------------------------------------|
| `-1.0f`   | Loaded / ready                       |
| `0.0f`    | Cooldown just started                |
| `> 0.0f`  | Cooling down                         |
| `<= 0.0f` (other negative) | Available for reload   |

### `ReloadTorpedo` (`FUN_0057D8A0`)

```
if num_ready >= max_ready:        return  ; tube full
if no ammo left:                   return  ; out of ammo
num_ready++
total_ammo_consumed++              ; system-wide
find slot with greatest timer; set to -1.0 (loaded)
post ET_RELOAD_TORPEDO (0x00800065)
```

### `Fire` (`FUN_0057C9E0`)

```
if !CanFire():               return false
torpedo = CreateTorpedoProjectile()
last_fire_time = g_Clock->gameTime
num_ready--
system->available_count--
system->total_available--
mark a free slot timer to 0.0   ; cooldown started
SetupTorpedo(this, torpedo)
post ET_WEAPON_FIRED (0x0080007C)        ; NB: NOT ET_TORPEDO_FIRED (0x66)
system->last_system_fire_time = gameTime
if host:
    SendTorpedoFirePacket(...)            ; opcode 0x19
return true
```

Cooldown timers do not appear to "tick down" via an explicit
function. Instead the engine reads `last_fire_time` and compares
against `g_Clock->gameTime + ReloadDelay` to schedule reloads via
the event system.

### Torpedo `CanFire` conditions

Compositionally similar to the phaser, plus:

- `num_ready > 0`
- Ammo available (`ammo_remaining > total_consumed` for current type)
- Cooldown expired (`gameTime - last_fire_time >= ImmediateDelay`,
  typically 0.25 s, prevents rapid double-fires)

### Torpedo type switch (`FUN_0057B230`)

There is **no explicit lockout timer**. The "lockout" is implicit:

1. `SetAmmoType(type, immediate=1)` — multiplayer / SWIG path:
   - Unloads every tube (`num_ready → 0`) via `FUN_0057D9A0`.
   - Clears every reload timer (sets to `0.0`) via `FUN_0057C740`.
   - Does **not** call `ReloadTorpedo` (the `immediate == 0` branch
     is skipped).
2. Tubes start empty and must reload from scratch.
3. Effective lockout = the longest `ReloadDelay` across the system
   (e.g. 40 s for the Sovereign), because every tube restarts its
   reload cycle simultaneously.
4. `SetAmmoType(type, immediate=0)` — local/offline path: unloads
   *and* immediately reloads → no lockout.

### Torpedo fire wire format (opcode `0x19`)

```
[byte:0x19]
[int32: weapon_object_id]
[byte:  torpedo_model_index]   ; from torpedo+0x14C
[byte:  flags]                 ; bit0=skew, bit1=isSkewFire(+0xA8), bit2=noTarget
[CompressedVector3: velocity]  ; normalized direction × speed
[if !noTarget:
    int32 target_id
    CompressedVector4 target_offset]
```

Handler `FUN_0069F930` forwards to all other peers, then deserialises
and calls `FUN_0057D110` (system-level fire handler) with the
parameters.

### `WeaponSystem::UpdateWeapons` (`FUN_00584930`)

The per-frame weapon tick. Skeleton:

```
if owner_ship.isDead:           return NULL
CleanupTargetList()
chain    = GetFiringChain(current_chain_index)
groupId  = chain ? GetFirstGroup(chain) : 0
startIdx = (last_weapon_idx + 1)
                                ; round-robin fairness
build list of weapons matching groupId
for w in candidates:
    result = TryFireWeapon(w, dt)
    if FIRED:
        last_weapon_idx = w; mark fired
        if singleFire: break
    elif CANNOT_FIRE:
        try direct fire (no-target) if eligible
if no fire and chain has next group: retry with next group
```

Per-weapon attempt (`FUN_00584E40`):

```
weapon.timer += dt              ; randomized fire-delay
if !weapon.is_firing && timer < FIRE_DELAY_THRESH: return DELAY
weapon.timer = rand_float()
if !weapon.CanFire():           StopFiring; return CANNOT_FIRE
return weapon.Fire(dt, 1) ? FIRED : CANNOT_FIRE
                                ; tries supplementary target list if direct fire fails
```

### Shared event-forwarding handler (`FUN_0069FDA0`)

Opcodes `0x07`–`0x0C` and `0x0E`–`0x12` all route here. It:

1. Reads the raw packet data.
2. Deserialises it into a `TGMessage`.
3. Forwards to all clients (broadcast via `FUN_006B4EC0`).
4. Posts the message to the local event queue (`FUN_006DA300`).
5. C++/Python event handlers process it.

So weapon-control commands (start firing, stop firing, phaser level
change, torpedo type change, etc.) are events relayed from one peer
through the host to all peers.

### Notable weapon constants

| Address     | Use                                              |
|-------------|--------------------------------------------------|
| `0x00888B54`| `0.0`                                            |
| `0x00888B58`| epsilon                                          |
| `0x00888860`| `1.0`                                            |
| `0x00890550`| AI/remote recharge multiplier                    |
| `0x00893170/74/78`| Phaser damage scale per intensity mode      |
| `0x0089317C/80/84`| Phaser discharge rate per intensity mode    |
| `0x00893830`| `FIRE_DELAY_THRESH`                              |
| `0x008936C0`| `SKEW_FIRE_SCALE`                                |
| `0x0088B9C0`| `1.0` (max charge ratio cap)                     |
| `0x008E53DC`| `RANGE_SCALE` (phaser beam range normalisation)  |

---

## Collision detection

Bridge Commander's collision detection is **custom** — *not* part
of NetImmerse's built-in collision (`NiCollisionSwitch` exists but
is only used as a toggle). It runs in three tiers.

### Tier 1 — Sweep-and-prune broad phase

`ProximityManager` (vtable `0x008942D4`, size `0x64`). Each game
`Set` owns one at `set+0xF4`. Layout:

| Offset    | Field                                                       |
|-----------|-------------------------------------------------------------|
| `+0x0C`   | collision-pairs list (circular doubly-linked)               |
| `+0x10`   | active pair count                                           |
| `+0x14..` | three `AxisSort` structures (5 DWORDs each, x/y/z)          |
| `+0x50`   | `object_count`                                              |
| `+0x54`   | `object_table` — array of `0x1C`-byte entries               |
| `+0x58`   | `overlap_tracker` — axis-overlap counts per pair            |

**3-axis sort-and-sweep**:

1. **Add** (`FUN_005A7640`): compute object AABB
   (`GetBoundingBox` at vtable `+0xE8`); each axis gets two endpoint
   entries (12 bytes: `{ float value, int next_ptr, int object_idx }`)
   inserted in sorted order via `FUN_005A8CC0`.
2. **Per frame** (`FUN_005A83A0`): refresh AABB endpoints
   (`FUN_005A8470`); call `FUN_005A8500` (`SweepAxis`) on each axis;
   call `FUN_005A8740` to dispatch overlapping pairs.
3. **Sweep** (`FUN_005A8500`): bubble-sort-like pass swaps
   out-of-order endpoints. Each swap is either an interval *start
   meeting end* (potential new overlap) or *end meeting start*
   (potential separation). When all 3 axes overlap, the pair is
   *eligible*; if `CollisionFlagsCompatible` agrees, it's added to
   the active pair list.

The "nearly sorted" property of frame-to-frame motion means the
bubble-sort runs O(n) in practice rather than O(n²).

### Collision-flag compatibility (`FUN_005A7890`)

```c
bool CompatibleFlags(int a, int b) {
    byte fa = *(byte*)(a + 0x3C);
    byte fb = *(byte*)(b + 0x3C);
    if (((fb >> 1) & fa & 0x2A) != 0) return true;
    if (((fa >> 1) & fb & 0x2A) != 0) return true;
    return false;
}
```

The flag byte at `obj+0x3C`:

- Bits 0/2/4 = "collides AS type X"
- Bits 1/3/5 = "collides WITH type X"
- `0x2A` = `0b00101010` is the "with" mask.

Python access via `ObjectClass_GetCollisionFlags`.

### Tier 2 — Hierarchical bounding-sphere

`ObjectClass::CheckCollision` (`FUN_005671D0`) — about 79,605
calls per 15-min combat session. Steps:

1. Early-out if `IsDead` or `collision_active == 0`.
2. Ship-type check: if the other is a ship with collision disabled
   (`ship+0x2DC->+0xAC`), bail.
3. Both objects must be in the same game set.
4. Walk the per-set exclusion list (event `0x800E`); already-known
   collisions return true (re-trigger).
5. Cooldown check: if `obj+0x98 > DAT_0089054C` and no exclusion
   found, return true (still in cooldown — keep reporting).
6. Bounding-sphere intersection (`FUN_00567640`).
7. Recurse into attached sub-objects (`obj+0xB0`).
8. Static-collision check (terrain / static geometry).

Sphere intersection (`FUN_00567640`):

```c
float distance = sqrt(dx² + dy² + dz²) /* + child-bound modifiers */;
float radius   = NiNode->bound_radius_0x4C * scale_0x98 * radiusMult_0x34;
return distance < radius;
```

Note: ship-to-ship collisions use **only** bounding spheres — no
triangle-mesh test. That's why long ships with elongated geometry
collide before they visually touch.

### Tier 3 — Narrow phase, per-type

`ProcessCollisionPair` (`FUN_005A8810`) dispatches by RTTI type:

| Type ID  | Object                              | Handler                              |
|----------|-------------------------------------|---------------------------------------|
| `0x8125` | `DamageableObject` / `Ship`         | `FUN_005A61C0` ship-ship              |
| `0x8009` | `Torpedo` / projectile              | `FUN_00579010` torpedo-object         |
| `0x8007` | `PhysicsObject`                     | `FUN_005A88E0` physics-physics        |
| `0x8003` | Generic                             | AABB-overlap only                     |

#### Ship-ship (`FUN_005A61C0`)

```
gap = sqrt(distance²) - radius_a;
if !ship_a.byte_0x7C: gap -= radius_b
if gap < 0:           PostCollisionEvent(ship_a, ship_b)
elif gap > 0 && was_colliding: PostCollisionEvent(ship_a, ship_b)
```

The "was_colliding" branch is how separation events fire; both onset
and offset are notified.

#### Physics-physics (`FUN_005A88E0`)

Includes:

1. Eligibility: both objects' `collision_enabled_0x1A8` set;
   `g_CollisionEnabled` (`DAT_008E5F58`) on.
2. Velocity threshold: both must have `|velocity|² >= DAT_008942DC`,
   else (combined with angular-energy threshold) skipped — resting
   objects don't generate constant collisions.
3. Contact-history check.
4. Detailed test: `vtable+0x148` (`BeginIntersectionTest`) and
   `vtable+0x150` (mesh test). Fills a `CollisionResult` struct
   (`0x58` bytes) — frame, position, velocity per object, contact
   list, etc.

#### Torpedo (`FUN_00579010`)

```
if torpedo.dead || target.dead || target == torpedo.owner: return
if target is type 0x8007:
    contact, vel = torpedo.GetWorldTranslation()
    hit = target.TestIntersection(torpedo.collision_shape+0x150, contact)
    if hit:
        for up to 2 iterations of time-of-impact refinement:
            if contact_distance <= 0: torpedo.dead = true; trigger
            else: refine TOI
```

Torpedoes *do* use detailed mesh intersection — the time-of-impact
loop refines the impact point with up to two iterations.

### Collision-energy formula

`DoDamage_CollisionContacts` reads the `CollisionEvent`:

| Offset | Field                                |
|--------|--------------------------------------|
| `+0x38`| `num_points`                         |
| `+0x40`| `collision_force` (impulse magnitude)|

The force itself is computed by the physics-engine collision
response (the `vtable+0x150` mesh handlers) from relative velocity,
mass, and coefficient of restitution. It's an output of detection,
not a separate calculation.

### Per-set / global collision storage

| Address        | Field                                                        |
|----------------|--------------------------------------------------------------|
| `0x008E5F58`   | `g_CollisionEnabled` (`SetPlayerCollisionsEnabled`)          |
| `0x0098D328`   | `collisionPairCount`                                          |
| `0x0098D32C/30/34/38` | pair list head/tail/free-pool/chunks                  |
| `0x0098D33C`   | `collisionPairPoolSize` — init 2                              |
| `0x008942DC`   | `velocityThresholdSq` — min `|v|²` for physics collision      |
| `0x0089054C`   | `collisionCooldownTime`                                       |
| `0x00893F28`   | collision damage tuning constant                              |
| `0x0088BF28`   | base damage offset                                            |
| `0x008887A8`   | per-contact damage clamp (0.5)                                |

### Collision events

| Code        | Name                                              |
|-------------|---------------------------------------------------|
| `0x00800050`| `ET_OBJECT_COLLISION` — client-detected           |
| `0x008000FC`| `ET_HOST_OBJECT_COLLISION` — host-validated       |
| `0x00800053`| `ET_COLLISION_BROADCAST` — effect to clients      |
| `0x0000800E`| Exclusion event (temporary cooldown)              |
| `0x00008124`| `CT_COLLISION_EVENT` — `CollisionEvent` class type|

### Notable design choices

1. **No mesh-level ship-ship detection.** Bounding spheres only.
2. **Torpedoes mesh-test**, with a 2-iteration TOI refinement.
3. **Sweep-and-prune is the workhorse.** ~80,000 calls per
   15 minutes; the incremental sort is the entire reason it's
   tractable.
4. **Cooldown timer at `obj+0x98`** prevents rapid re-trigger when
   ships grind together.
5. **Detection runs on the client.** Clients send opcode `0x15` to
   the host, which validates distance and applies damage. A headless
   server doesn't need to run collision detection itself.
6. **Velocity threshold for physics objects** — resting objects are
   excluded from physics collision to avoid constant events.

---

## Ship death and explosion

When hull HP `<= 0`:

1. Server sends opcode `0x14` (`DestroyObject`):
   `[byte:0x14][int32:object_id]`.
2. Server sends opcode `0x29` (`Explosion`):
   `[byte:0x29][int32:object_id][CompressedVector4:impact][CF16:damage][CF16:radius]`.
3. Ship marked dead via `vtable[0x138](1, 0)`.
4. Destructor invoked via `vtable[0](1)` — full cleanup.

There is **no dedicated respawn mechanism**. Respawn = destroy old
object + create a new one (`ObjCreateTeam` `0x03` with fresh HP).

### `DestroyObject_Net` (`0x006A01E0`, opcode `0x14`)

`__cdecl(void* stream)`, `RET 0x04`. Reads `objectID`, looks up via
`FUN_00434E00` (type `0x8003`); if it has a parent, calls
`parent->vtable[0x5C](objectID)`; if it's a ship (type `0x8006`),
calls `vtable[0x138](1, 0)` to mark dead/hide; calls `vtable[0](1)`.

### `Explosion_Net` (`0x006A0080`, opcode `0x29`)

`__cdecl(void* stream)`, `RET 0x04`. Reads `objectID`, decompresses
3D position, reads CF16 damage/radius. Looks up target via
`FUN_00590A50` (type `0x8007`). Allocates an `AoEDamage` object
(`0x38` bytes) and calls `ProcessDamage` directly — bypassing
`DoDamage`.

The two `0x14` and `0x29` flow as **server-to-client only**: the
host *sends* them; clients *receive* and replay. (Confirmed in stock
host traces: `DestroyObject_Net` and `Explosion_Net` never fire on
the host.)

---

## Sovereign-class reference values

Useful as a baseline when validating a reimplementation against
stock content. From `sovereign.py`:

### Hull

- Hull `MaxCondition`: **12,000**

### Subsystems

| Subsystem                  | MaxCondition | RepairComplexity |
|----------------------------|-------------:|------------------:|
| Shield Generator           |       10,000 | —                 |
| Sensor Array               |        8,000 | 1.0               |
| Warp Core (reactor)        |        7,000 | 2.0               |
| Impulse Engines (system)   |        3,000 | 3.0               |
| Port/Starboard Impulse (each)|      3,000 | —                 |
| Torpedo System             |        6,000 | —                 |
| Forward Torpedo (each, ×4) |        2,200 | —                 |
| Aft Torpedo (each, ×2)     |        2,200 | —                 |
| Phaser Emitter (each, ×8)  |        1,000 | —                 |
| Phaser Controller          |        8,000 | —                 |
| Repair                     |        8,000 | 1.0               |
| Warp Engines (system)      |        8,000 | —                 |
| Port/Starboard Warp (each) |        4,500 | —                 |
| Tractor System             |        3,000 | 7.0               |
| Tractor (each, ×4)         |        1,500 | 7.0               |
| Bridge                     |       10,000 | 4.0               |
| Hull                       |       12,000 | 3.0               |
