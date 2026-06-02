# Subsystem-Failure Gameplay Consequences — Design

**Status:** spec drafted, awaiting user review
**Date:** 2026-06-02
**Author:** Mark Ward (with Claude)
**Roadmap:** [`2026-06-01-combat-damage-pipeline-design.md`](./2026-06-01-combat-damage-pipeline-design.md) — Project 5 of 5.
**Prior projects in this arc:**
- [`2026-06-01-mesh-accurate-hit-resolution-design.md`](./2026-06-01-mesh-accurate-hit-resolution-design.md)
- [`2026-06-01-subsystem-damage-propagation-design.md`](./2026-06-01-subsystem-damage-propagation-design.md)
- [`2026-06-01-shield-face-rotation-design.md`](./2026-06-01-shield-face-rotation-design.md)
- [`2026-06-01-damage-vfx-bridge-feedback-design.md`](./2026-06-01-damage-vfx-bridge-feedback-design.md)

## 1. Goal

Make the gameplay loop respond to subsystem damage. When a named subsystem reports `IsDisabled() == 1` or `IsDestroyed() == 1`, the corresponding capability stops working. Five capability gates, each reading its predicate at use-time so repair lifting condition auto-releases the gate with no extra coordination:

1. **Impulse engines** — clamp linear and angular target setpoints to zero; decay current velocity under a gentle disabled-engine drag.
2. **Weapons firing** — `StartFiring` is a no-op for any weapon system whose aggregated child state reports `IsDisabled`; in-progress fire stops cleanly.
3. **Sensors (player only)** — target list rows hide, target panel goes to empty state, affiliation forces to UNKNOWN, radar contacts blank.
4. **Shield generator** — per-tick regen skipped; stored `_charge_per_second` values are not mutated.
5. **Repair interaction** — verified, not redesigned. Gates auto-release when condition lifts above the disabled threshold.

Closes the combat damage pipeline arc. With this merged, the original symptom motivating the roadmap — "fire a phaser, nothing visibly happens" — is resolved end-to-end.

## 2. Locked decisions

- **Predicate at use-time.** No cached `_is_currently_disabled` flag. Every gate calls a shared helper `_is_offline(sub)` that returns `True` iff `sub.IsDisabled()` or `sub.IsDestroyed()`. Repair lifting condition is observed automatically on the next tick.
- **`IsDestroyed` is treated identically to `IsDisabled`.** A destroyed engine is also a disabled engine. The shared helper folds both into one check; no separate code paths.
- **Engines clamp both linear and angular.** The SDK puts `MaxAngularVelocity` / `MaxAngularAccel` directly on the `ImpulseEngines` hardpoint (`sdk/Build/scripts/ships/Hardpoints/galaxy.py:783-784`), and BC has no separate RCS / thrusters subsystem. A disabled impulse engine room kills both translation and rotation.
- **Engines decay gracefully via a drag fraction.** Target is clamped to zero; ramp step is scaled by `DISABLED_ENGINE_DRAG_FRACTION = 0.1`. A ship at full impulse coasts to a stop over ~10× the normal stop time. Same fraction applies to angular ramping. The integrator has no real drag model — this is the cheapest plausible decay rather than a true physical model.
- **Weapon-system gate is per-system, not per-bank.** `WeaponSystem.IsDisabled()` from Project 2 aggregates children — fires only when every child reports disabled. Existing per-emitter charge / arc / range gates continue to fire each bank independently when the parent gate doesn't block.
- **Sensor gate is player-scoped.** The UI consumers blank only when *the player's own* `SensorSubsystem` reports offline. AI consumers go through the SDK's existing `IsObjectKnown` flow unchanged.
- **Player's own panel chrome always renders.** Even with sensors dead, the player's left-side ShipDisplay panel keeps name / IFF / affiliation. The blanking applies only to external targets.
- **Radar contacts blank via existing visibility chain.** `update_target_list_visibility` sets every row invisible when player sensors are offline; the radar panel already filters on `row.IsVisible()`.
- **Shield-generator gate at `Update` entry.** Cheaper than per-face. Does not mutate `_charge_per_second`; the stored values are intact when condition lifts.
- **No repair redesign.** `RepairSubsystem` is `pass` today. Test gate-release via direct `SetCondition(max_condition)` or `SetDisabled(False)` mutation. Real repair is a follow-up project (see §6).

## 3. Architecture

### 3.1 Shared predicate

```python
# engine/appc/subsystems.py — module level (alongside other helpers)
def _is_offline(sub) -> bool:
    """True when a subsystem is disabled OR destroyed.
    Both states gate capability identically per Project 5 spec."""
    if sub is None:
        return False
    return bool(sub.IsDisabled()) or bool(sub.IsDestroyed())
```

Every gate calls this. Importable from anywhere; the helper is the canonical answer to "is this subsystem effectively offline?".

### 3.2 Gate sites

| # | Capability                | Site                                                                                                       | Predicate target                           |
|---|---------------------------|------------------------------------------------------------------------------------------------------------|--------------------------------------------|
| 1 | Player linear throttle    | `engine/host_loop.py:_PlayerControl.GetTargetSpeed`                                                        | `player.GetImpulseEngineSubsystem()`       |
| 2 | Player angular targets    | `engine/host_loop.py:_PlayerControl.apply` (after key resolution, before ramp)                             | `player.GetImpulseEngineSubsystem()`       |
| 3 | AI linear + angular       | `engine/appc/ship_motion.py:_step_ship_motion`                                                             | `ship.GetImpulseEngineSubsystem()`         |
| 4a| Weapons — StartFiring     | `engine/appc/subsystems.py:WeaponSystem.StartFiring` + `PhaserSystem.StartFiring`                          | `self` (the parent weapon system)          |
| 4b| Weapons — held-fire retry | `engine/appc/subsystems.py:PhaserSystem.retry_held_fire`                                                   | `self`                                     |
| 4c| Weapons — mid-tick stop   | `engine/host_loop.py:_advance_combat` per-system block                                                     | `sys_` (the ship's PhaserSystem)           |
| 5 | Sensors — visibility      | `engine/appc/subsystems.py:update_target_list_visibility`                                                  | `player.GetSensorSubsystem()` (player only)|
| 6 | Sensors — affiliation     | `engine/ui/ship_display_panel.py:_affiliation_for`                                                         | same                                       |
| 7 | Sensors — target resolve  | `engine/ui/ship_display_panel.py:_resolve_ship_for_role` (ROLE_TARGET only; player role unaffected)        | same                                       |
| 8 | Shield generator regen    | `engine/appc/subsystems.py:ShieldSubsystem.Update` (early return at function entry)                        | `self`                                     |

## 4. Per-gate detail

### 4.1 Engines — linear and angular drag

`engine/appc/ship_motion.py` exports the tuning constant:

```python
DISABLED_ENGINE_DRAG_FRACTION = 0.1
```

**Player site** — `_PlayerControl`:

- `GetTargetSpeed(player)` — at function entry, when `_is_offline(self._get_ies(player))`, return `0.0` unconditionally.
- `apply(player, dt, h)` — after computing `pitch_target / yaw_target / roll_target` from keys, when `_is_offline(IES)`:
  - Set all three angular targets to `0.0`.
  - Use `_max_accel(player) * DISABLED_ENGINE_DRAG_FRACTION * dt` for the linear ramp step.
  - Use `_angular_accel(player) * DISABLED_ENGINE_DRAG_FRACTION * dt` for the angular ramp step.

**AI site** — `_step_ship_motion`:

- After resolving `target_speed` and `target_av_*` from setpoints, check `_is_offline(ship.GetImpulseEngineSubsystem())`. When offline:
  - Override `target_speed = 0.0`.
  - Override `target_av_x = target_av_y = target_av_z = 0.0`.
  - Multiply `step` (`_max_accel(ship) * dt`) by `DISABLED_ENGINE_DRAG_FRACTION`.
  - Multiply `ang_step` (`_max_angular_accel(ship) * dt`) by `DISABLED_ENGINE_DRAG_FRACTION`.

**Edge case** — ship with no `ImpulseEngineSubsystem` (bare `ShipClass()` test fixtures): `_is_offline(None)` returns `False`. Existing `FALLBACK_MAX_ACCEL` semantics preserved.

### 4.2 Weapons — parent-system gate

`WeaponSystem.StartFiring` (subsystems.py:899) — insert `if _is_offline(self): return` immediately after the existing `IsOn()` check. Inherited by `TorpedoSystem`, `PulseWeaponSystem`, `TractorBeamSystem`.

`PhaserSystem.StartFiring` (subsystems.py:1107) — same gate inserted after the existing `IsOn()` / `target is None` early-out.

`PhaserSystem.retry_held_fire` (subsystems.py:1125) — when `_is_offline(self)`, call `self.StopFiring()` and return. StopFiring clears `_fire_held` and walks `_currently_firing` to stop each bank.

`_advance_combat` (host_loop.py:259-262) — after fetching `sys_ = ship.GetPhaserSystem()`, before invoking `retry_held_fire` or the per-bank loop: when `_is_offline(sys_)`, call `sys_.StopFiring()` and `continue` to the next ship.

**Torpedo semantics:** in-flight torpedoes propagate regardless of launcher state. No gating on `projectiles.update_all` — once a torpedo has launched, the launcher's later failure does not despawn or stall it. Matches stock BC.

### 4.3 Sensors — player-scoped UI blank

New helper in `engine/ui/ship_display_panel.py` (the three UI gates all live in this file or are tightly coupled to it; a new module isn't justified):

```python
def player_sensors_offline() -> bool:
    """True iff the player's own SensorSubsystem reports offline."""
    from engine.appc.subsystems import _is_offline
    from engine.core.game import Game_GetCurrentGame
    game = Game_GetCurrentGame()
    player = game.GetPlayer() if game else None
    if player is None:
        return False
    sensors = player.GetSensorSubsystem() if hasattr(player, "GetSensorSubsystem") else None
    return _is_offline(sensors)
```

**Three UI sites:**

- `update_target_list_visibility(target_menu, ships, player, range_units)` — at function entry, when `player_sensors_offline()`, iterate menu rows and call `row.SetNotVisible()` on each, then return. The radar (`sensors_panel.py`) reads `row.IsVisible() != 1` and skips invisible rows; target_list_view similarly. No per-panel change needed beyond the visibility flip.

- `_affiliation_for(ship, player)` — when `ship is not player` and `player_sensors_offline()`, return `"UNKNOWN"` regardless of mission group membership. Player's own row is unaffected because `ship is player` short-circuits.

- `_resolve_ship_for_role(role)` — when `role != ROLE_PLAYER` and `player_sensors_offline()`, return `None`. The target panel goes to its existing no-target empty state. Player role still resolves to the player ship.

**SDK predicates unchanged:** AI ships' use of `IsObjectKnown` continues through the SDK's stock flow. The player-scoped gate is purely UI-side.

### 4.4 Shield generator — regen freeze

`ShieldSubsystem.Update(dt)` (subsystems.py:1706):

```python
def Update(self, dt: float) -> None:
    if _is_offline(self):
        return
    # ... existing per-face regen loop unchanged
```

`_charge_per_second` values are not mutated. When the generator's condition is restored above `_disabled_percentage * _max_condition`, the next `Update` call regens at the original rates. Damage via `ApplyDamage` remains independent of `Update` — a disabled generator can still take incoming hits and drain to zero.

### 4.5 Repair — verification only

`RepairSubsystem` is currently `pass` (subsystems.py:1865). Project 5 does not redesign repair.

The verification gates auto-release works:
- Tests mutate condition directly via `SetCondition(max_condition)` or `SetDisabled(False)`.
- All five gate predicates read condition at use-time, so the gate flips back to "permitted" on the next call.

Recorded as an open question in §6: how the production repair flow will exercise gate-release end-to-end once `RepairSubsystem` is implemented for real.

## 5. Tests

### 5.1 Unit tests (one per gate, TDD)

- **`tests/test_engines_disabled_clamps_throttle.py`**
  - Player ship with disabled IES → `GetTargetSpeed` returns 0 regardless of `impulse_level`.
  - Player ship with destroyed IES (condition = 0) → same.
  - AI ship with disabled IES + non-zero `_speed_setpoint` → `_step_ship_motion` decays `_current_speed` at drag-fraction rate.
  - AI ship with disabled IES + non-zero `_target_angular_velocity_setpoint` → angular components decay at drag-fraction rate.
  - Repair (`SetCondition(max_condition)`) → throttle response restored on next call; ramp returns to full rate.

- **`tests/test_weapons_disabled_blocks_fire.py`**
  - PhaserSystem with all four children disabled → `StartFiring` is a no-op (no `bank.Fire` calls).
  - PhaserSystem with one healthy + three disabled → `StartFiring` fires the healthy bank.
  - Mid-fire: a bank is firing, then all children flip disabled, then `_advance_combat` runs → `bank.StopFiring` called, no `apply_hit` invocations.
  - `retry_held_fire` with `_fire_held=True` then system flips disabled → next call calls `StopFiring`, clears `_fire_held`.
  - Repair one child → next `StartFiring` fires that child.

- **`tests/test_sensors_disabled_blanks_target_ui.py`**
  - Player sensors disabled → `_resolve_ship_for_role(ROLE_TARGET)` returns None; `_resolve_ship_for_role(ROLE_PLAYER)` still returns the player.
  - `_affiliation_for(enemy_ship, player)` returns `"UNKNOWN"` when player sensors disabled, even though `enemy_ship` is in `EnemyGroup`.
  - `_affiliation_for(player, player)` still returns `"FRIENDLY"` (self short-circuit).
  - `update_target_list_visibility` flips every row to invisible when player sensors disabled.
  - Repair → next call restores affiliation and visibility.

- **`tests/test_shield_generator_disabled_stops_regen.py`**
  - Generator disabled, face below max → `Update(dt)` leaves `_current_shields[f]` unchanged.
  - Generator at max condition → regen runs normally and clamps at `_max_shields`.
  - Repair → regen resumes at the original `_charge_per_second`; the stored values were never mutated.
  - `ApplyDamage` on a disabled generator still drains the face (drain is independent of regen).

### 5.2 Integration test

**`tests/integration/test_engines_disabled_decays_velocity.py`**

End-to-end: ship at full impulse, damage to disable, observe decay, repair, observe recovery.

1. Build ship with full impulse engine subsystem (`SetMaxCondition(100)`, populated `MaxSpeed` / `MaxAccel`).
2. Set `_speed_setpoint` to full forward; tick a few seconds → `_current_speed ≈ MaxSpeed`.
3. `IES.SetCondition(threshold * 0.99)` — flip below disabled threshold.
4. Tick further; assert `_current_speed` decays toward 0 at the drag-fraction rate (not the full MaxAccel rate).
5. `IES.SetCondition(max_condition)` — repair.
6. Tick further; assert `_current_speed` ramps back up toward the setpoint at full rate.

### 5.3 Visual smoke

Documented mission steps for manual verification:

1. `cmake -B build -S . && cmake --build build -j && ./build/dauntless`
2. In the default mission, target an enemy and fire phasers until the enemy's Engines row goes red on the ShipDisplay panel → observe enemy ship's velocity decay.
3. Continue firing until the enemy's Weapons row goes red → observe enemy stops firing back.
4. Take enough hits yourself that your Sensors row goes red → observe target list blanks and the right-side panel goes to empty state.
5. Take enough hits that your Shield Generator row goes red → observe a depleted face does not regen.
6. Repair test (using a temporary debug REPL or hotkey to lift conditions; tooling for this is out of scope — Project 5 just confirms the predicate-based design makes it possible).

## 6. Open questions

- **`RepairSubsystem` is `pass`.** This project verifies that gates release when condition lifts, but the production repair flow has no implementation. Suggested follow-up: Project 6 — Damage repair subsystem, designing the queue / priority / per-second condition recovery rate, with real SDK-faithful behaviour. Not in scope here.
- **Visual smoke for the repair-release case** depends on either a debug repair hotkey or the eventual real `RepairSubsystem`. Without one of those, the manual visual confirmation of gate-release is currently impossible; the unit tests cover the contract via direct condition mutation.
- **`DISABLED_ENGINE_DRAG_FRACTION = 0.1`** is chosen by feel. Tunable; documented as the only magic number introduced by this project. If playtesting wants a different decay feel, it's a one-line change.

## 7. Non-goals

- Power-subsystem-driven gating (disabled `PowerSubsystem` taking the whole ship offline). Not listed in the roadmap.
- Repair queue / priority redesign (see §6 — flagged as follow-up).
- AI behavioural reactions beyond what the SDK already does. `Preprocessors.py` already rates targets and selects subsystems using `IsDisabled / IsDamaged`; that flow continues to work unchanged.
- Mission-script hooks for "subsystem disabled" events. No real consumer.
- Multiplayer / save-load implications. Save state already serialises `_condition` fields; gates derive from condition, so save/load works without change.
- Mid-tick gating on already-launched torpedoes. Once a torpedo has left the tube, it propagates regardless of the launcher's later state.

## 8. Parking lot

- Player-side debug REPL or hotkey for forcing subsystem repair, to enable visual-smoke verification of gate-release. Useful tooling but not gameplay; could ship alongside the next project that needs it.
- True drag model on the integrator. The drag fraction is a stand-in for actual rigid-body damping; if a future physics rewrite introduces real linear damping, the disabled-engine gate naturally simplifies to "clamp target, let drag handle decay" with no extra constant.
- Sensor LOS / scanning that activates `IsObjectKnown` for the player (per the comment in `_resolve_ship_for_role`). Currently we trust `SetTarget`; a real scan model would replace the `player_sensors_offline()` short-circuit with a proper known-objects gate.
