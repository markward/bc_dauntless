# Torpedo combat (PR 2b of 2c)

**Status:** design
**Date:** 2026-05-14
**Predecessors:**
- [2026-05-13-weapon-emitter-scaffolding-design.md](2026-05-13-weapon-emitter-scaffolding-design.md) (PR 1, merged)
- [2026-05-14-weapon-firing-pipeline-design.md](2026-05-14-weapon-firing-pipeline-design.md) (PR 2a, merged)

## Context

PR 2a closed the audible firing loop: right-click in red alert fires a torpedo (state flips, `_num_ready` decrements) and audibly fires a phaser bank. Nothing is yet visible in 3D, and no damage is applied. PR 2b closes the **visible + damaging loop for torpedoes** specifically:

- Right-click launches a visible torpedo sprite from the firing tube.
- With a target locked, the torpedo homes toward the target (or target subsystem if cycled) until its guidance time expires; otherwise it dumbfires straight from the emitter.
- On contact, the torpedo applies damage to the target — shields take it first, then the nearest subsystem to the hit point, then the hull.
- Mission scripts receive `ET_WEAPON_HIT` events. `MissionLib.FriendlyFireHandler` fires when the player hits a friendly NPC.

**Phasers, AI ship firing, and cursor-aim are explicitly deferred to PR 2c.** This keeps PR 2b roughly the same size as PR 2a.

## Goals

1. With a Galaxy at RED alert and a locked target, the player can right-click, see a torpedo sprite leave the tube, watch it home toward the target, see it impact, and observe the target ship's hull/subsystem condition decrement.
2. Without a target lock, the right-click still launches; the torpedo flies straight from the emitter's local direction and expires on TTL with no hit.
3. The 17 SDK projectile scripts under `sdk/Build/scripts/Tactical/Projectiles/` drive both the visual model (`CreateTorpedoModel`) and the behaviour (`GetLaunchSpeed`, `GetLaunchSound`, `GetDamage`, `GetGuidanceLifetime`, `GetMaxAngularAccel`). No hard-coded colors, speeds, or sounds in the engine.
4. `WeaponHitEvent` broadcasts on every hit; mission-script handlers (e.g. `FriendlyFireHandler`) receive it.

## Non-goals (deferred to PR 2c)

- Phaser beam rendering + damage (phasers stay in PR 2a's "audible Start sound, no visible beam, no hit" state).
- Phaser fire-loop sustain (Start → Loop audio transition).
- Disruptor cannons (similar pulse-projectile pipeline, follows phaser work).
- AI ship firing verification.
- Cursor-aim / manual free-aim mode.
- Per-emitter color overrides on the renderer side (BC's `SetInnerCoreColor` etc. on EnergyWeapon hardpoints — defer with phaser visuals).
- Hit explosion SFX (the launch-sound whoosh is the only audible cue in PR 2b; a separate impact sound waits for PR 2c).

## End-to-end data flow

```
Player right-clicks (or holds right-button, then releases)
  ↓ PR 2a input chain dispatches ET_INPUT_FIRE_SECONDARY → FireWeapons →
  ↓ pShip.GetWeaponSystemGroup(WG_SECONDARY).StartFiring(target, offset)
  ↓ Sequential cursor picks the next loaded tube
TorpedoTube.Fire(target, offset)
  ↓ Existing PR 2a gating: parent.IsOn() AND _num_ready > 0
  ↓ Look up the bound projectile script via the parent system property:
  ↓   parent.GetProperty().GetTorpedoScript(ammo_slot)
  ↓     → e.g. "Tactical.Projectiles.PhotonTorpedo"
  ↓ importlib.import_module(script_name)
  ↓ Create Torpedo() at emitter world position
  ↓ Call <module>.Create(torpedo) — fills CreateTorpedoModel(...) visuals
  ↓ Read <module>.GetLaunchSpeed/GetLaunchSound/GetDamage/
  ↓      GetGuidanceLifetime/GetMaxAngularAccel
  ↓ Compute initial velocity:
  ↓   pShip = self.GetParentShip()  (climb subsystem tree)
  ↓   if pShip.GetTarget() is not None:
  ↓     target = pShip.GetTargetSubsystem() or pShip.GetTarget()
  ↓     aim_point = target.GetWorldLocation()
  ↓     velocity = normalize(aim_point - emitter_world_pos) * launch_speed
  ↓     torpedo.set_homing_target(pShip.GetTarget(), guidance_lifetime, max_angular_accel)
  ↓   else:
  ↓     forward = pShip.GetWorldRotation() * emitter.GetDirection()
  ↓     velocity = normalize(forward) * launch_speed
  ↓     torpedo.target_ship = None  (dumbfire, no homing)
  ↓ register torpedo with engine.appc.projectiles registry
  ↓ TGSoundManager.PlaySound(launch_sound)
  ↓ (existing PR 2a) _num_ready-- ; _last_fire_time = monotonic()
  ↓ (existing PR 2a) _firing = True → False immediately (discrete shot)

per-frame, host_loop:
  update_torpedoes(dt):
    for each active torpedo:
      if torp.target_ship and torp.age < torp.guidance_lifetime:
        # Steer toward target, limited by max_angular_accel
        desired = normalize(target_pos - torp.pos) * speed
        torp.velocity = clamp_turn(torp.velocity, desired, max_angular_accel * dt)
      torp.pos += torp.velocity * dt
      torp.age += dt
      if torp.age >= TTL:
        expire(torp)
        continue
      # Collision check against all ships except source
      for ship in all_ships:
        if ship is torp.source_ship: continue
        if ship.IsDead(): continue
        if sphere_hit(torp.pos, ship.GetWorldLocation(), ship.GetRadius()):
          subsystem = pick_target_subsystem(ship, torp.pos)
          apply_hit(ship, torp.damage, torp.pos, source=torp.source_ship, subsystem=subsystem)
          spawn_hit_vfx(torp.pos)
          expire(torp)
          break
  # Push to renderer:
  set_torpedoes([build_render_data(t) for t in active])
  set_hit_vfx([{pos, age} for v in active_vfx])
  update_hit_vfx_ages(dt)
```

## Components

### Engine (Python)

**`engine/appc/projectiles.py` (new)** — runtime Torpedo entity + registry.

```python
class Torpedo(TGObject):
    """Per-shot runtime projectile. Visual fields populated by the SDK
    projectile script's CreateTorpedoModel call (one of 17 scripts in
    sdk/Build/scripts/Tactical/Projectiles/).
    """
    def __init__(self):
        super().__init__()
        # Position / motion
        self._position: TGPoint3 = TGPoint3(0, 0, 0)
        self._velocity: TGPoint3 = TGPoint3(0, 0, 0)
        self._age: float = 0.0
        self._ttl: float = 30.0  # max time-of-flight if no impact
        # Damage
        self._damage: float = 0.0
        self._damage_radius_factor: float = 0.0
        # Homing (None → dumbfire)
        self._target_ship = None
        self._guidance_lifetime: float = 0.0
        self._max_angular_accel: float = 0.0
        # Visual model fields — populated by CreateTorpedoModel
        self._core_texture: str = ""
        self._core_color = None         # TGColorA
        self._core_size_a: float = 0.0  # CreateTorpedoModel arg 3
        self._core_size_b: float = 0.0  # arg 4
        self._glow_texture: str = ""
        self._glow_color = None
        self._glow_size_a: float = 0.0  # arg 7
        self._glow_size_b: float = 0.0  # arg 8
        self._glow_size_c: float = 0.0  # arg 9
        self._flares_texture: str = ""
        self._flares_color = None
        self._num_flares: int = 0
        self._flares_size_a: float = 0.0  # arg 13
        self._flares_size_b: float = 0.0  # arg 14
        # Bookkeeping
        self._source_ship = None
        # Set when registered with the active list (id used for renderer dedup).
        self._id: int = 0

    # SDK surface — args verified against
    # sdk/Build/scripts/Tactical/Projectiles/PhotonTorpedo.py:22-45
    def CreateTorpedoModel(self, core_tex, core_color, core_a, core_b,
                                 glow_tex, glow_color, glow_a, glow_b, glow_c,
                                 flares_tex, flares_color, num_flares,
                                 flares_a, flares_b):
        self._core_texture = str(core_tex)
        self._core_color   = core_color
        self._core_size_a  = float(core_a)
        self._core_size_b  = float(core_b)
        self._glow_texture = str(glow_tex)
        self._glow_color   = glow_color
        self._glow_size_a  = float(glow_a)
        self._glow_size_b  = float(glow_b)
        self._glow_size_c  = float(glow_c)
        self._flares_texture = str(flares_tex)
        self._flares_color   = flares_color
        self._num_flares     = int(num_flares)
        self._flares_size_a  = float(flares_a)
        self._flares_size_b  = float(flares_b)

    def SetDamage(self, v): self._damage = float(v)
    def SetDamageRadiusFactor(self, v): self._damage_radius_factor = float(v)
    def SetGuidanceLifetime(self, v): self._guidance_lifetime = float(v)
    def SetMaxAngularAccel(self, v): self._max_angular_accel = float(v)
    def SetNetType(self, v): pass  # multiplayer; ignored in PR 2b


# Module-level registry of in-flight torpedoes.
_active: list[Torpedo] = []
_next_id = 1


def register(torpedo: Torpedo) -> None: ...
def expire(torpedo: Torpedo) -> None: ...
def update_all(dt: float, all_ships) -> list[tuple[Torpedo, ShipClass, Subsystem]]:
    """Advance every active torpedo by dt. Returns list of (torpedo,
    hit_ship, hit_subsystem) tuples that connected this tick — host_loop
    routes each through combat.apply_hit and spawn_hit_vfx, then expires.
    """
```

**`engine/appc/combat.py` (new)** — collision + damage routing.

```python
def sphere_hit(point: TGPoint3, sphere_center: TGPoint3, radius: float) -> bool:
    return distance_squared(point, sphere_center) <= radius * radius


def pick_target_subsystem(ship, hit_point_world):
    """Walk the ship's subsystem tree; return the subsystem whose
    hardpoint position is closest to hit_point AND within ~2× its radius.
    Falls back to ship.GetHull() if nothing matches.
    """


def apply_hit(ship, damage, hit_point, source, subsystem=None):
    """Route damage through shields → subsystem → hull bleed."""
    if subsystem is None:
        subsystem = pick_target_subsystem(ship, hit_point)

    # 1. Shields take it first
    shields = ship.GetShields()
    remaining = damage
    if shields is not None and shields.IsOn():
        face = shield_face_from_hit_point(ship, hit_point)
        shield_strength = shields.GetMaxShields(face)  # existing PR 1 surface
        absorbed = min(remaining, shield_strength)
        shields.DamageFace(face, absorbed)  # existing PR 1 surface
        remaining -= absorbed

    # 2. Bleed remainder to chosen subsystem
    if remaining > 0 and subsystem is not None:
        absorbed = min(remaining, subsystem.GetCondition())
        ship.DamageSystem(subsystem, absorbed)  # NEW method on DamageableObject
        remaining -= absorbed

    # 3. Bleed remainder to hull
    if remaining > 0:
        hull = ship.GetHull()
        if hull is not None:
            ship.DamageSystem(hull, remaining)

    # 4. Broadcast WeaponHitEvent
    evt = WeaponHitEvent()
    evt.SetSource(source)
    evt.SetTarget(ship)
    evt.SetDamage(damage)
    evt.SetHitPoint(hit_point)
    evt.SetSubsystem(subsystem)
    App.g_kEventManager.AddEvent(evt)
```

**`engine/appc/events.py` (extend)** — add `WeaponHitEvent` + `ET_WEAPON_HIT`.

```python
ET_WEAPON_HIT: int = 0x1100  # reserved range above ET_KEYBOARD_EVENT (0x1000)

class WeaponHitEvent(TGEvent):
    def __init__(self):
        super().__init__()
        self._event_type = ET_WEAPON_HIT
        self._source = None
        self._target = None
        self._damage: float = 0.0
        self._hit_point = None
        self._subsystem = None

    def Set/GetSource, Set/GetTarget, Set/GetDamage,
    Set/GetHitPoint, Set/GetSubsystem
```

**`engine/appc/objects.py` (extend)** — `DamageableObject.DamageSystem`.

```python
def DamageSystem(self, subsystem, amount: float) -> None:
    """Decrement subsystem._condition by amount. Floor at 0.
    Fires per-subsystem damaged-events on threshold crossings."""
    if subsystem is None:
        return
    new_condition = max(0.0, subsystem.GetCondition() - float(amount))
    subsystem.SetCondition(new_condition)
    # If this is the hull and condition just hit zero: ship dying.
    if subsystem is self.GetHull() and new_condition <= 0.0:
        self.SetDying(True)
```

**`engine/appc/properties.py` (extend)** — typed torpedo-script accessors on `WeaponSystemProperty`.

```python
# Existing class already has _torpedo_script_by_slot from PR 1's __getattr__
# catch-all; promote to typed accessors so PR 2b reads consistent values.
class WeaponSystemProperty(PoweredSubsystemProperty):
    def __init__(self, name: str = ""):
        super().__init__(name)
        self._torpedo_scripts: dict[int, str] = {}
        # ... existing fields

    def SetTorpedoScript(self, slot, module_name) -> None:
        self._torpedo_scripts[int(slot)] = str(module_name)

    def GetTorpedoScript(self, slot) -> str | None:
        return self._torpedo_scripts.get(int(slot))
```

**`engine/appc/subsystems.py` (extend)** — `TorpedoTube.Fire` spawns the torpedo.

```python
def Fire(self, target=None, offset=None) -> None:
    if not self.CanFire():
        return
    # PR 2a logic: flip _firing, decrement _num_ready, stamp _last_fire_time
    self._firing = True
    self._target = target
    self._target_offset = offset
    self._num_ready -= 1
    self._last_fire_time = time.monotonic()
    self._firing = False  # discrete-shot auto-stop

    # NEW: spawn the projectile
    parent = self.GetParentSubsystem()
    if parent is None:
        return  # detached tube — defensive
    parent_prop = parent.GetProperty()
    slot = self._compute_ammo_slot()  # see Open question 1
    script_name = (parent_prop.GetTorpedoScript(slot)
                   if parent_prop is not None else None)
    if not script_name:
        return  # no script bound, silent no-op (matches BC for unconfigured tubes)

    from engine.appc.projectiles import Torpedo, register
    import importlib
    mod = importlib.import_module(script_name)

    torp = Torpedo()
    torp._source_ship = _climb_to_ship(self)
    torp._position = _emitter_world_position(self)
    mod.Create(torp)  # fills CreateTorpedoModel + SetDamage + SetGuidanceLifetime etc.

    launch_speed = mod.GetLaunchSpeed()
    pShip = torp._source_ship
    if pShip.GetTarget() is not None:
        aim_target = pShip.GetTargetSubsystem() or pShip.GetTarget()
        aim_pt = aim_target.GetWorldLocation()
        torp._velocity = (aim_pt - torp._position).normalize() * launch_speed
        torp._target_ship = pShip.GetTarget()
    else:
        # Dumbfire: emitter local-direction * ship world rotation
        forward = pShip.GetWorldRotation() * self.GetDirection()
        torp._velocity = forward.normalize() * launch_speed
        torp._target_ship = None  # no homing

    register(torp)
    TGSoundManager.instance().PlaySound(mod.GetLaunchSound())
```

`_climb_to_ship(subsystem)` walks `GetParentSubsystem()` up until it finds the `ShipClass`. `_emitter_world_position(tube)` computes ship world pos + ship rotation × tube local position. `_compute_ammo_slot()` — see open questions.

**`engine/host_loop.py` (extend)** — per-frame projectile update + renderer push.

```python
def _advance_combat(ships, dt):
    """Advance torpedoes, route hits through damage, push to renderer."""
    from engine.appc.projectiles import update_all
    from engine.appc.combat import apply_hit
    from engine.appc.hit_vfx import spawn, update_ages, snapshot

    hits = update_all(dt, ships)
    for torpedo, ship, subsystem in hits:
        apply_hit(ship, torpedo._damage, torpedo._position,
                  source=torpedo._source_ship, subsystem=subsystem)
        spawn(torpedo._position)

    update_ages(dt)
    # Push to renderer
    _h.set_torpedoes(_build_torpedo_data())
    _h.set_hit_vfx(snapshot())
```

Bootstrap extension: register `MissionLib.FriendlyFireHandler` once mission is loaded.

**`engine/appc/hit_vfx.py` (new)** — small module for transient impact sprites. List of `(position, age)` pairs; `spawn(pos)` adds with age=0; `update_ages(dt)` increments and prunes >0.5s; `snapshot()` returns the list for renderer push.

### Native (C++) — two new render passes

**`native/src/renderer/torpedo_pass.{cc,h}`** — billboarded sprite composite.

For each torpedo in the per-frame list (pushed via `set_torpedoes(...)`):
- Three additive billboards at the same world position, camera-aligned quads:
  - Core: size derived from `core_size_a` × `core_size_b`, tinted by `core_color`.
  - Glow: larger size, lower opacity, tinted by `glow_color`.
  - Flares: `num_flares`-arm star, rotated slowly over time, tinted by `flares_color`.
- Additive blend. Depth-test on, depth-write off. Renders after solid geometry, before lens flares.

Shader: `torpedo.vert` (computes camera-aligned quad corners from world position + size), `torpedo.frag` (texture sample × color tint × additive).

**`native/src/renderer/hit_vfx_pass.{cc,h}`** — short-lived explosion sprite.

For each `(position, age)` pair pushed via `set_hit_vfx(...)`:
- Single additive billboard, scaling from 0→1 over 0.0–0.1s, fading 1→0 over 0.1–0.5s.
- Uses `TorpedoFlares.tga` as the impact texture (placeholder; PR 2c can swap in a proper impact sprite).
- Removed by the engine when age exceeds 0.5s (renderer just consumes the snapshot).

Shader: `hit_vfx.vert`/`.frag`. Similar to torpedo billboard with an extra `age` uniform driving size + alpha.

**`native/src/host/host_bindings.cc` (extend)** — Python bindings.

```cpp
m.def("set_torpedoes",
      [](const std::vector<TorpedoRenderData>& torpedoes) { /*…*/ },
      "Push current frame's torpedo list to the renderer.");

m.def("set_hit_vfx",
      [](const std::vector<HitVfxRenderData>& vfx) { /*…*/ },
      "Push current frame's hit-VFX list (position + age).");
```

`TorpedoRenderData` carries: position, core_texture, core_color, core_size_a, core_size_b, glow_texture, glow_color, glow_size_a/b/c, flares_texture, flares_color, num_flares, flares_size_a/b. Textures are loaded once + cached by name in the renderer.

### Pipeline integration

In `native/src/renderer/pipeline.cc`, add torpedo_pass and hit_vfx_pass after the existing lens_flare_pass. They share the same additive-blend / depth-test-on / depth-write-off setup so render order matters only relative to other transparent passes.

## Targeting

`TorpedoTube.Fire` reads `ship.GetTarget()` directly (existing PR 1 ship state). If non-None, additionally checks `ship.GetTargetSubsystem()` for sub-target. The initial velocity vector is computed in the Fire call; for homing, the target reference is stored on the torpedo and re-read each tick (so a moving target is tracked).

No cursor pick, no auto-acquire. **Manual cursor-aim is explicitly future work** — leave the surface free of "cursor target" plumbing so it can be added cleanly later without retrofitting.

## Hardpoint integration

Galaxy and other hardpoints already call `Torpedoes.SetTorpedoScript(0, "Tactical.Projectiles.PhotonTorpedo")` etc. The PR 1 catch-all stored these; PR 2b promotes `SetTorpedoScript`/`GetTorpedoScript` to typed accessors and reads them at Fire time. No hardpoint file edits needed.

## SFX

- **Launch sound**: from `mod.GetLaunchSound()` (e.g. `"Photon Torpedo"`). LoadTacticalSounds (called in PR 2a bootstrap) already registers all weapon sound names.
- **No impact sound in PR 2b** — defer to PR 2c (would need an explosion-sound asset bound to a name + a PlaySound call from `apply_hit`).
- **No phaser SFX changes** — phasers stay in PR 2a's Start-only state until PR 2c adds Loop sustain alongside visible beams.

## WeaponHitEvent + FriendlyFireHandler

`apply_hit` constructs a `WeaponHitEvent`, sets source/target/damage/hit_point/subsystem, and calls `g_kEventManager.AddEvent(evt)`. Both per-ship instance handlers (`ship.AddPythonFuncHandlerForInstance(ET_WEAPON_HIT, ...)`) and broadcast handlers fire.

`_bootstrap_firing_pipeline` (already in PR 2a) extends to register `MissionLib.FriendlyFireHandler` as a broadcast handler for `ET_WEAPON_HIT`. The SDK script reads `pEvent.GetSource()` + `pEvent.GetTarget()`, checks faction alignment, and queues XO dialogue when the player hits a friendly. The script already exists; we just need to wire the broadcast.

## Testing

### Unit tests

| File | Coverage |
|---|---|
| `tests/unit/test_torpedo_create_model.py` | `Torpedo.CreateTorpedoModel(...)` stores all 14 fields. Run against actual `Tactical.Projectiles.PhotonTorpedo.Create(t)` and assert fields match. |
| `tests/unit/test_torpedo_advance.py` | Position += velocity × dt. Age increments. TTL expires. Homing rotates velocity toward target; non-homing keeps straight-line velocity. Turn rate respects `max_angular_accel`. |
| `tests/unit/test_weapon_system_property_torpedo_script.py` | `SetTorpedoScript(0, "...")` / `GetTorpedoScript(0)` round-trip per slot. Default `None` for unset slots. |
| `tests/unit/test_sphere_hit.py` | `sphere_hit(p, c, r)` true when distance < r, false otherwise. |
| `tests/unit/test_pick_target_subsystem.py` | Hit near a hardpoint position → returns that subsystem. Hit at distance > 2×radius from any subsystem → returns hull. |
| `tests/unit/test_apply_hit_routing.py` | Shields-up: damage absorbed by shield face. Shields-down: damage to picked subsystem. Subsystem at zero: damage bleeds to hull. Hull at zero: ship dying. |
| `tests/unit/test_weapon_hit_event.py` | Event constructor, all Set/Get pairs, dispatch via `g_kEventManager`. Instance handler + broadcast handler both fire. |
| `tests/unit/test_damage_system_method.py` | `DamageableObject.DamageSystem(subsystem, amount)` decrements correctly; floors at zero; triggers `SetDying(True)` on hull-zero. |
| `tests/unit/test_hit_vfx_lifecycle.py` | `spawn` registers age=0; `update_ages` increments; pruned at >0.5s; `snapshot` returns current list. |

### Integration tests

| File | Coverage |
|---|---|
| `tests/integration/test_torpedo_lock_homes_to_target.py` | Galaxy at RED + locked target ahead. Right-click → torpedo's initial velocity vector points at the target ship. After several `_advance_combat` ticks, position is closer to target. Eventually collides; target hull (or chosen subsystem) condition decreases. |
| `tests/integration/test_torpedo_no_lock_dumbfires.py` | Galaxy at RED + no target. Right-click → torpedo flies along emitter forward direction (in ship-world frame). No homing. Expires on TTL without hitting (since no ship in front in the test setup). |
| `tests/integration/test_torpedo_targets_subsystem.py` | Galaxy + target lock + target-subsystem cycled to "Bridge". Fire → damage applied to the Bridge subsystem specifically, not just hull. |
| `tests/integration/test_friendly_fire_handler.py` | Friendly NPC ship in front, target-locked. Player fires; collision; `FriendlyFireHandler` broadcast handler invoked (assert the handler ran via mock or via state side-effects). |
| `tests/integration/test_weapon_hit_event_dispatched.py` | Per-ship instance handler installed via `AddPythonFuncHandlerForInstance(ET_WEAPON_HIT, ...)` receives the event with correct source/target/damage/subsystem. |

### Manual verification

After merge:
1. Build (`cmake --build build -j`).
2. Run (`./build/open_stbc`).
3. Load mission. Shift+3 → RED alert. C-toggle to lock a target.
4. Right-click → visible torpedo sprite leaves the tube, flies toward the target, impacts. Target ship's condition indicator (debug panel) shows decrement. Audible launch whoosh.
5. Right-click without target → torpedo flies straight ahead and disappears off into the distance.

## Open questions

1. **`_compute_ammo_slot()` for `TorpedoTube`** — Galaxy has 6 tubes and the torpedo system has up to N ammo slots. The tube doesn't currently know which slot to pull from. Two paths:
   - Tubes always pull from slot 0 (the parent system's default ammo). Simplest; matches single-ammo-type ships.
   - Tubes are assigned a slot index at hardpoint-load time (the SDK's `SetTorpedoScript(slot, ...)` already enumerates slots; we'd need to track which tube uses which slot).
   Recommend (1) for PR 2b; (2) is a polish item that adds slot-cycling support.

2. **Homing turn-rate math.** Spec says `max_angular_accel` limits the turn rate. The torpedo's velocity vector is rotated toward the desired heading by at most `max_angular_accel × dt` radians per frame. If the desired heading is within that cone, the velocity snaps to the desired heading. Approximate but stable.

3. **Damage radius factor.** Each script's `SetDamageRadiusFactor(...)` (e.g. PhotonTorpedo:0.13) is for splash damage on impact. PR 2b applies single-target damage only; splash is deferred to PR 2c.

4. **`SetNetType` from Multiplayer scripts.** PhotonTorpedo.py imports `Multiplayer.SpeciesToTorp` and calls `pTorp.SetNetType(...)`. Multiplayer is out of scope; the Torpedo's `SetNetType` method is a no-op accept.

5. **TTL value.** Currently 30s in the spec. The SDK doesn't seem to expose a torpedo TTL; the closest is `guidance_lifetime` (6s for Photon). 30s ≈ 5×guidance feels safe for "torpedo eventually expires off-screen". Tune by feel during PR 2b implementation.

## Implementation order

1. `WeaponSystemProperty.SetTorpedoScript`/`GetTorpedoScript` typed accessors. Tests.
2. `Torpedo` runtime class + `CreateTorpedoModel` + registry. Tests against real `PhotonTorpedo.Create(t)`.
3. `WeaponHitEvent` + `ET_WEAPON_HIT` in events.py.
4. `DamageableObject.DamageSystem` method.
5. `combat.py` — sphere_hit, pick_target_subsystem, apply_hit. Tests.
6. `TorpedoTube.Fire` extends to spawn projectile. Tests.
7. `hit_vfx.py` — spawn/update/snapshot.
8. `host_loop._advance_combat` wiring. Bootstrap `FriendlyFireHandler` registration.
9. Native: `torpedo_pass.{cc,h}` + shaders + `set_torpedoes` binding. Build verification.
10. Native: `hit_vfx_pass.{cc,h}` + shaders + `set_hit_vfx` binding.
11. Integration tests (5 files).
12. Manual verification in-game.
