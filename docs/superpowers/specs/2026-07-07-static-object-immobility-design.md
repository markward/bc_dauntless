# Static-object Immobility + Per-pair Collision Masking — Design

**Date:** 2026-07-07
**Status:** Approved (design), pending implementation plan
**Scope:** Make ships flagged immobile (`SetStatic`/`SetStationary`) actually stay
put, and implement per-pair `EnableCollisionsWith` so a docked ship doesn't
collide with its dock. Fixes the E1M1 "spacedock wiggles and drifts in front of
the player" bug.

This is **not** an extension of the NPC subsystem-targeting spec
(`2026-07-07-npc-subsystem-targeting-design.md`); that is a combat-aim change in
`ai_driver.py`. This is a physics/collision change in `collisions.py`,
`ship_motion.py`, `collision_avoidance.py`, and `objects.py`. Separate blast
radius, separate tests.

## Problem

At E1M1 start the player spawns at placement `"DryDock Start"` — the **same
placement as the first Dry Dock** (`E1M1.py:793` and `E1M1.py:796`), so the
player and Dry Dock are co-located and their bounding spheres overlap. Around
them sit four more objects the mission flags immobile: two more drydocks, the
`SpaceFacility` "Station", and the `Nebula`-class "Nightingale"
(`E1M1.py:796-800`). All five get `SetStatic(TRUE)` (`E1M1.py:808-810`) plus a
"Stay" AI that zeroes their speed/angular velocity every 5 s. The player↔DryDock
pair is meant to be collision-exempt while docked
(`pDryDock.EnableCollisionsWith(pPlayer, 0)`, `E1M1.py:819`), re-enabled after the
undock cutscene (`E1M1.py:1332`).

Observed: from the moment the bridge loads, the whole dock complex rotates,
wiggles, and drifts out in front of the player instead of holding station.

### Root cause (verified in investigation)

Two independent engine gaps combine.

**Gap 1 — immobility flags are stored but never enforced.**

- `SetStatic` saves `_static` (`objects.py:471-475`, initialised `False` at
  `objects.py:400`). `SetStationary` saves `_stationary` (`ships.py:585-586`,
  initialised `0` at `ships.py:77`). Both `IsStatic()` and `IsStationary()`
  return real values (no `_Stub` risk).
- **No runtime path reads either flag.** Grep across `engine/`: motion,
  collision-response, and collision-avoidance never consult them. `IsStationary()`
  is read only by tests. So every `ShipClass` — stations included — is integrated
  as a fully mobile, zero-inertia rigid body.
- `collisions.py:_resolve_body` (lines 78-88) marks **any** `ShipClass`
  `movable=True`; only non-`ShipClass` (Planet/moon/sun) get `movable=False,
  inv_mass=0`. A flagged-immobile dock is therefore pushed by de-penetration
  (`collisions.py:156-163`) and carries a decaying `_collision_velocity` overlay
  (`collisions.py:143-152`, `233-250`, τ=0.5 s) that the Stay AI cannot cancel —
  the Stay AI zeroes the *motion setpoint*, not the collision overlay.
- `ship_motion.py:_step_ship_motion` (lines 119-226) integrates any ship the
  moment a setpoint exists; its only skip is "both setpoints still `None`"
  (lines 136-139). `_integrate_rotation` (lines 285-299) applies angular velocity
  with **no rotational-inertia term**, so a station's large `RotationalInertia`
  (copied at `ships.py:857-858` but otherwise unused) does nothing to resist
  rotation.

**Gap 2 — per-pair `EnableCollisionsWith` is unimplemented.**

- `DamageableObject.EnableCollisionsWith(pOther, bOn)` (SDK `App.py:5355`) has **no
  implementation in `engine/`** → it hits `TGObject.__getattr__`'s `_Stub` and is a
  silent no-op. Only the per-*object* `SetCollisionsOn` flag exists
  (`objects.py:601-613`, read via `_collisions_enabled` in `collisions.py:53-59`).
- So the mission's `pDryDock.EnableCollisionsWith(pPlayer, 0)` does nothing: the
  co-located player and Dry Dock collide every frame.

**Why both must be fixed together.** Fixing Gap 1 alone makes the Dry Dock an
immovable wall that the player is spawned *inside*; de-penetration would then shove
the *player* out of the dock at spawn — a new artifact, and it blocks clean
testing of the E1M1 start. Gap 2 is what stops that. They ship as one change.

## Approach

Two components, both pure Python (no C++ rebuild).

**A. Enforce immobility** via a single predicate applied at the three sites that
currently ignore it.

**B. Implement per-pair collision masking** so `EnableCollisionsWith` actually
suppresses a chosen pair; the mission continues to own the docked→undocked
lifecycle by calling this primitive.

### Predicate

A method on the ship class:

```
class ShipClass:
    def IsImmobile(self):
        return bool(self.IsStatic()) or bool(self.IsStationary())
```

- Honours both the mission's per-instance `SetStatic(TRUE)` and the hardpoint's
  per-class `SetStationary(1)`. The OR is required: the `SpaceFacility` "Station"
  declares `SetStationary(0)` (`spacefacility.py:112`) yet the mission marks it
  `SetStatic(TRUE)`, so only `IsStatic()` catches it; the three drydocks carry
  both (`drydock.py:112` sets `SetStationary(1)`).
- Scoped to `ShipClass`. Planets are already immovable by type; `IsStationary`
  exists only on `ShipClass`, and the collision-site call is already inside the
  `isinstance(obj, ShipClass)` branch.
- Reads are safe as direct method calls because both backing fields are
  initialised in `__init__` (no lazy-attribute `_Stub` hazard). Define the helper
  once as `ShipClass.IsImmobile(self)` on the ship class itself (the single
  natural home; both flags live on the ship) and call it from `ship_motion.py`,
  `collisions.py`, and `collision_avoidance.py`. One definition keeps the three
  sites in sync.
- Dynamic: `IsStatic()`/`IsStationary()` are read live each tick, so a later
  `SetStatic(0)` (or a hardpoint that flips stationary) re-mobilises the ship with
  no extra bookkeeping.

### Rejected alternatives

- **Huge-mass threshold** (treat mass/inertia above a cutoff as immobile):
  rejected — introduces a magic number and a second code path when the explicit
  flags already cover every real case.
- **Skip collisions with static objects entirely** (remove them from detection):
  rejected — the player could clip through the spacedock with no bump feedback.
  "Acts like a planet" keeps movers bouncing off and taking impact damage.
- **`IsStationary()`-only or `IsStatic()`-only predicate:** rejected — each misses
  objects the other catches (see Predicate).

## Components / mechanism

### A1. Collision response — `engine/appc/collisions.py`

In `_resolve_body` (lines 71-92), when `obj` is a `ShipClass` **and**
`obj.IsImmobile()`, take the same immovable branch the code already uses for
planets: `inv_mass = 0.0`, `movable = False`, `velocity = TGPoint3(0, 0, 0)`. A
zero velocity is both correct (an anchor isn't moving) and keeps the mover's
closing-speed `v_rel` computed purely from the mover. Everything downstream
already handles an immovable body correctly:

- `_respond_pair` gates `inv_sum <= 0.0` (two immovables) out (lines 137-139); a
  mover-vs-immobile pair still injects impulse into and de-penetrates **only the
  mover** (the `if a.is_movable` / `if b.is_movable` guards, lines 143-163).
- The mover still takes KE impact damage via `apply_hit` (lines 180-199).

No change to overlay decay: an immobile object never receives an overlay, so
`_apply_overlay_all` skips it (no `_collision_velocity` attribute).

### A2. Motion integrator — `engine/appc/ship_motion.py`

In `_step_ship_motion`, add an early return for immobile ships, placed **after**
the in-system-warp check (lines 130-134) and **before** the setpoint read (lines
136-139):

```
if ship.IsImmobile():
    return
```

An anchor never integrates a translation or rotation regardless of what setpoint
the Stay AI (or anything else) wrote. This is the primary stop on drift/rotation.

### A3. Collision avoidance — `engine/appc/collision_avoidance.py`

Skip immobile ships in the per-tick steering loop (they carry the Stay AI, so
`GetAI()` is non-null and they would otherwise be steered). With A2 in place any
setpoint avoidance writes is already inert, so this is a clarity/cheap-correctness
guard, not a second stop.

### B1. Per-pair collision masking — `engine/appc/objects.py`

Add to `DamageableObject`:

```
def EnableCollisionsWith(self, pOther, bOn):
    ids = self.__dict__.setdefault("_collision_disabled_ids", set())
    oid = pOther.GetObjID()
    if bOn:
        ids.discard(oid)   # re-enable
    else:
        ids.add(oid)       # disable this pair
```

- Stores the **other** object's `GetObjID()` (the SDK-native stable handle), not
  an object ref — survives the frame and avoids holding the peer alive.
- `__dict__.setdefault`/lazy-create + `__dict__`-safe reads dodge the
  `_Stub`-truthy trap, matching the existing `_collisions_enabled`/`_overlay_vec`
  pattern in `collisions.py`.
- A companion read helper (in `collisions.py`) returns the id set or empty:
  `_collision_disabled_ids(obj) := obj.__dict__.get("_collision_disabled_ids", ())`.

### B2. Pair skip — `engine/appc/collisions.py`

In `resolve_collisions` (lines 253-266), before calling `_respond_pair(a, b)`,
skip the pair when **either** side lists the other's ObjID:

```
if b.obj.GetObjID() in _collision_disabled_ids(a.obj) \
   or a.obj.GetObjID() in _collision_disabled_ids(b.obj):
    continue
```

Symmetric by design: BC's API is nominally directional, but every caller wants a
mutual exemption, and a symmetric skip removes pair-ordering bugs. The existing
per-object `SetCollisionsOn(0)` filter in `tick_collisions` (lines 299-300) is
unchanged and composes with this (either mechanism can exempt a body/pair).

## Data flow

```
mission setup:   SetStatic(TRUE) / hardpoint SetStationary(1)  -> _static / _stationary
                 pDryDock.EnableCollisionsWith(pPlayer, 0)      -> DryDock._collision_disabled_ids += {player id}

per frame (host_loop):
  tick_all_ai            -> Stay AI writes speed=0 / angvel=0 setpoints on docks (now moot)
  collision_avoidance    -> skips immobile docks (A3)
  tick_all_ship_motion   -> _step_ship_motion early-returns for immobile docks (A2)  => no drift/rotation
  tick_collisions
    _resolve_body        -> immobile docks: movable=False, inv_mass=0 (A1)
    resolve_collisions   -> player↔DryDock pair skipped (B2)                          => player not shoved at spawn
                            player vs other static docks (if overlapping): docks fixed, player bounces + takes damage

undock cutscene end:     pDryDock.EnableCollisionsWith(pPlayer, 1) -> id removed; pair collides normally again
```

## Error handling / edge cases

| Case | Behaviour |
|---|---|
| Ship neither static nor stationary | unchanged — full mobile integration + collision |
| `SetStatic(0)` later (release) | `is_immobile` reads live → ship re-mobilises next tick |
| Immobile vs immobile overlap | already gated by `inv_sum <= 0.0` in `_respond_pair` (no response) |
| Ship flagged immobile *mid-flight* while carrying a live `_collision_velocity` overlay | overlay keeps decaying via `_apply_overlay_all` (pre-existing motion bleeds off over ~τ); not exercised by E1M1, where docks are immobile from creation and never accrue an overlay |
| Mover rams immobile dock | dock fixed; mover de-penetrated + impulsed + takes KE damage (planet semantics) |
| `EnableCollisionsWith` peer with no `GetObjID` | not expected for DamageableObjects; helper reads the set defensively, pair simply not skipped |
| Player↔DryDock while docked | pair skipped (B) → no spawn shove; re-enabled post-undock by the mission |
| Planet/moon/sun | untouched — already immovable by type; predicate is `ShipClass`-scoped |
| Save/load | out of scope (see below) |

## Testing

### Unit / integration (`tests/`)

1. **A1** — immobile ship + a moving neighbour overlapping it: neighbour is
   de-penetrated and takes impact damage; the immobile ship's position and
   rotation are unchanged.
2. **A2** — immobile ship with a non-zero speed and angular-velocity setpoint
   written: `_step_ship_motion` leaves the transform byte-unchanged.
3. **A2** — `IsImmobile()` reads both flags: static-only, stationary-only, and
   neither all resolve correctly (neither → integrates normally).
4. **A3** — immobile ship with an AI is not steered by collision avoidance.
5. **B** — `EnableCollisionsWith(other, 0)` suppresses that pair's
   de-penetration/impulse/damage; `EnableCollisionsWith(other, 1)` restores it;
   an unrelated third-object pair is unaffected; masking is symmetric (works
   whichever object holds the id).
6. **Integration (the repro)** — build the E1M1 dock cluster: player at
   `"DryDock Start"`, Dry Dock co-located with `EnableCollisionsWith(player, 0)`,
   plus Station/Nightingale/other drydocks flagged static nearby; tick
   motion + collisions for N frames and assert (a) every dock's world position
   and rotation are unchanged, and (b) the player is **not** displaced out of the
   Dry Dock.

Run the full gate (`scripts/check_tests.sh`). Pure Python — **no C++ rebuild
required**.

### Live in-game verification

1. Launch `./build/dauntless` and start E1M1 (or the dev **Load Mission…**
   picker → Maelstrom E1M1).
2. On the bridge walk-on, watch the exterior: **the spacedock, drydocks, Station,
   and Nightingale hold station** — no rotation, wiggle, or drift.
3. Complete the undock sequence; confirm the player leaves the dock normally and
   that once clear, collisions with the Dry Dock behave normally again (the
   mission re-enables them at `E1M1.py:1332`).

## Out of scope

- **Rotational-inertia physics** — `RotationalInertia` is copied but unused;
  immobile anchors don't need it, and real torque physics for movers is a
  separate concern.
- **Save/load persistence** of `_static`/`_stationary`/`_collision_disabled_ids` —
  the bug is at fresh mission start (missions re-run setup on load). Track
  separately if a loaded save is later found to drift.
- **Huge-mass-threshold immobility** — rejected per the predicate decision.
- **NPC subsystem targeting / cloak behaviour** — covered by their own specs.
