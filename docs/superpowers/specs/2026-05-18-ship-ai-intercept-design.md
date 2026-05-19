# Ship AI Intercept — Design

**Status:** brainstormed 2026-05-18. Next step: implementation plan in `docs/superpowers/plans/`.

**Builds on:** [Ship AI Motion slice](2026-05-18-ship-ai-motion-design.md) (merged 2026-05-18 as `bb3b27c`; row/col follow-up `68f6220`). That slice delivered the integrator, the angular-velocity solver `TurnDirectionsToDirections`, the math helpers `GetPredictedPosition` and `GetRelativePositionInfo`, and the `SetImpulse` alias. This slice consumes all of them.

**Pulls forward from:** [Ship AI Runtime deferred plan](../deferred/2026-05-18-ship-ai-runtime.md) — closes Step 5 item 4 (`PlainAI.Intercept`) and finishes the Step 4 motion-API list except for the renderer-side warp visuals.

## Goal

Make `PlainAI("Intercept")` actually close on a target. After this slice, a hostile spawned far from the player flies in via in-system warp + impulse braking and halts at the SDK's intercept distance, marking itself `US_DONE`. The slice does NOT introduce a custom Intercept implementation — it fills the engine API holes the real SDK [`Intercept.py`](../../../sdk/Build/scripts/AI/PlainAI/Intercept.py) calls into.

## Non-goals

- Obstacle avoidance. `ProximityManager.GetLineIntersectObjects` already returns `()` at [engine/appc/planet.py:217](../../../engine/appc/planet.py#L217), so `Intercept.AdjustDestinationForLargeObstacles` is a no-op by construction. Real avoidance lands when the proximity subsystem itself gets real work.
- End-to-end test of `bMoveInFront=1` (the fly-by-attack branch used by `NonFedAttack`). We fix the latent `GetWorldForwardTG` row/col bug so the branch is correct when first exercised, but no integration test pins it this slice.
- Warp visuals — camera flash, streak particles, motion blur. `InSystemWarp` returns control after a stateless teleport; the renderer hook lands when those visual subsystems do.
- `FollowObject` / `CircleObject` / `Compound.BasicAttack`. Those sit on top of Intercept and unlock once this is in.

## Architecture

The slice is mostly bookkeeping. The SDK's `Intercept.Update` is already complete and runs end-to-end once its engine-side dependencies exist. Per-tick flow inside the SDK script (unchanged — just listed here as the contract this slice satisfies):

1. Look up target by name in containing set.
2. Estimate flight time `t = target_distance / GetMaxSpeed()`.
3. Predict target position via `GetPredictedPosition(target_loc, GetVelocityTG(), GetAccelerationTG(), t)`.
4. Cap predicted offset to `fMaxPredictionDistance = 100` units.
5. Compute destination as "intercept point on near side of target" (default `bMoveInFront=0`).
6. `AdjustDestinationForLargeObstacles` → no-op (proximity stub).
7. `TurnTowardLocation(destination)` — sets angular velocity setpoint to face the destination.
8. `GetRelativePositionInfo(destination)` — distance check.
9. If `distance < ship_radius` OR (`!bMoveInFront` AND `target_distance < fInterceptDistance`) → return `US_DONE`.
10. `bWarping = InSystemWarp(target, fInSystemWarpDistance)`. If 1, the ship teleported this tick; skip the brake-aware speed step.
11. Brake-aware speed: `fStopDist = MaxSpeed² / (2·MaxAccel)`. If `distance < fStopDist`, compute `fMaxVel = sqrt(MaxSpeed² − 2·MaxAccel·distance)` and clamp to current speed for a smooth deceleration. Cap to `self.fMaximumSpeed`.
12. `SetSpeed(fSpeed, ModelForward, MODEL_SPACE)` — picked up by the integrator we shipped last slice.

The integrator shipped in the Motion slice picks up the angular + linear setpoints written by steps 7 and 12 and applies them per 60 Hz tick. The Intercept AI cadence is ~0.4 s (with jitter); the integrator's per-tick behavior smooths motion between AI fires.

## Components

Five small additions to the engine. None of them touch the integrator or the loop.

### `engine/appc/ships.py` — three new methods

```python
def TurnTowardLocation(self, target_vec):
    """Rotate to face a world-space point. Thin wrapper on
    TurnDirectionsToDirections."""
    loc = self.GetWorldLocation()
    diff = TGPoint3(target_vec.x - loc.x,
                    target_vec.y - loc.y,
                    target_vec.z - loc.z)
    if diff.Length() < 1e-9:
        return
    diff.Unitize()
    # Current world-forward = R · model_forward = column 1 of R
    # (column-vector convention; matches the integrator + SDK).
    forward = self.GetWorldRotation().GetCol(1)
    zero = TGPoint3(0.0, 0.0, 0.0)
    self.TurnDirectionsToDirections(forward, diff, zero, zero)

def InSystemWarp(self, target, distance) -> int:
    """Teleport-to-near-target sub-light warp.

    If target is None or the ship is already within `distance`, return 0
    without moving. Otherwise teleport along the ship→target ray so the
    ship arrives at `target_loc - unit_dir * distance`, zero the integrator's
    current speed (so brake-aware control resumes cleanly on the next
    tick), and return 1.

    Stateless: Intercept calls this each Update; one teleport is enough
    because subsequent calls find distance ≤ fDistance and return 0.
    """
    if target is None:
        return 0
    ship_loc = self.GetWorldLocation()
    target_loc = target.GetWorldLocation()
    diff = TGPoint3(target_loc.x - ship_loc.x,
                    target_loc.y - ship_loc.y,
                    target_loc.z - ship_loc.z)
    d = diff.Length()
    if d <= distance:
        return 0
    diff.Scale(1.0 / d)  # unit dir ship→target
    # Arrival point: target minus unit * distance.
    self.SetTranslateXYZ(target_loc.x - diff.x * distance,
                         target_loc.y - diff.y * distance,
                         target_loc.z - diff.z * distance)
    self._current_speed = 0.0
    return 1

def StopInSystemWarp(self) -> None:
    """No-op in the stateless teleport model. SDK call sites
    (Intercept.LostFocus) require the method to exist."""
    pass
```

### `engine/appc/objects.py` — two changes

```python
# PhysicsObjectClass: new method, returns zero TGPoint3.
# Kinematic model: acceleration is the AI's per-tick ramp, not stored on
# the object. Returning zero degrades GetPredictedPosition to p + v·t,
# which is correct for ships at near-constant velocity post-ramp.
def GetAccelerationTG(self) -> TGPoint3:
    return TGPoint3(0.0, 0.0, 0.0)

# ObjectClass.GetWorldForwardTG: fix row/col convention.
# Same latent bug + same fix shape as GetRelativePositionInfo (commit
# 68f6220). Forward = R · model_forward = column 1 under the column-vector
# convention the integrator + SDK use.
def GetWorldForwardTG(self) -> TGPoint3:
    return self._rotation.GetCol(1)   # was GetRow(1)
```

### `App.py` — one cast shim

```python
def PhysicsObjectClass_Cast(obj):
    """Cast an arbitrary object to PhysicsObjectClass or None.
    Mirrors Planet_Cast / ShipClass_Cast."""
    from engine.appc.objects import PhysicsObjectClass
    return obj if isinstance(obj, PhysicsObjectClass) else None
```

That's the complete engine-side change. Six methods/functions across three files.

## Test plan

### Unit tests

| File | Count | Coverage |
|---|---|---|
| `tests/unit/test_turn_toward_location.py` (new) | ~5 | Target ahead → angular setpoint zero (already aligned); target behind → magnitude > 1 with perpendicular axis; target +X with identity rotation → angular velocity around -Z; target at ship location → no-op (no NaN); call writes to `_target_angular_velocity_setpoint` via the underlying solver. |
| `tests/unit/test_in_system_warp.py` (new) | ~6 | Far call teleports to `target − unit_dir · fDistance` (verify all three coords); near call (`distance ≤ fDistance`) returns 0 without moving; None target returns 0; teleport zeros `_current_speed`; returns 1 only when teleport occurred; `StopInSystemWarp()` is observably a no-op. |
| `tests/unit/test_physics_object_accel.py` (new) | ~2 | `PhysicsObjectClass.GetAccelerationTG()` returns a fresh zero `TGPoint3`; `App.PhysicsObjectClass_Cast` returns the input for `ShipClass` (subclass of PhysicsObjectClass) and `None` for a bare `ObjectClass` (e.g. `PlacementObject`). |
| `tests/unit/test_ship_motion.py` (modify) | +1 | Pin `GetWorldForwardTG` column-vector convention: ship yawed `+π/2` around Z → `GetWorldForwardTG()` returns world `-X`. Same shape as the `GetRelativePositionInfo` regression test from `68f6220`. |

### Integration test

| File | Count | Coverage |
|---|---|---|
| `tests/integration/test_ai_intercept_smoke.py` (new) | ~5 | Hostile at `(0, 5000, 0)` with `PlainAI('Intercept')` targeting `"player"` at origin, IES populated with `MaxSpeed=120`, `MaxAccel=50`. Run loop. Assertions: (a) after first AI tick, hostile's distance to player is within `fInSystemWarpDistance + ε` (proves warp fired and dropped the ship at the edge of that radius); (b) after enough ticks, AI status is `US_DONE`; (c) final hostile-player distance is `< fInterceptDistance + ship_radius`; (d) hostile's world-forward (via `GetWorldForwardTG`) points roughly at the player (`dot > 0.9`); (e) `_current_speed` ramped up after warp and back toward zero before halt (sanity that brake-aware control engaged). |

### Visible verification

`sdk/Build/scripts/Custom/Tutorial/Episode/AIIntercept/AIIntercept.py` (new) — sibling of the `AIMotion` mission. Spawns the player Galaxy at origin, a hostile Galaxy at `(0, 5000, 0)` with `PlainAI("Intercept")` targeting `"player"`. Default `fMaximumSpeed = 1.0e20` leaves warp enabled. User runs `./build/dauntless`, picks `AIIntercept` from the picker, sees the hostile pop in near the player then drift the final ~250 units under brake-aware impulse control before halting.

Like the `AIMotion` mission, the file lives in the gitignored SDK tree by design; the deferred-doc note describes the manual-preservation requirement if the SDK is ever nuked.

## File map

| File | Change | Lines (est) |
|---|---|---|
| `engine/appc/ships.py` | `TurnTowardLocation`, `InSystemWarp`, `StopInSystemWarp` | ~45 |
| `engine/appc/objects.py` | `GetAccelerationTG`, `GetWorldForwardTG` fix | ~10 |
| `App.py` | `PhysicsObjectClass_Cast` shim + export | ~6 |
| `tests/unit/test_turn_toward_location.py` | new, ~5 tests | ~110 |
| `tests/unit/test_in_system_warp.py` | new, ~6 tests | ~130 |
| `tests/unit/test_physics_object_accel.py` | new, ~2 tests | ~35 |
| `tests/unit/test_ship_motion.py` | +1 test (GetWorldForwardTG yaw) | ~15 |
| `tests/integration/test_ai_intercept_smoke.py` | new, ~5 tests | ~150 |
| `sdk/Build/scripts/Custom/Tutorial/Episode/AIIntercept/AIIntercept.py` | new mission (gitignored) | ~55 |
| `sdk/Build/scripts/Custom/Tutorial/Episode/AIIntercept/__init__.py` | new (gitignored) | 0 |
| `docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md` | strike Intercept; note avoidance + visuals follow-ups | ~15 |

Total: ~570 LOC across ~11 files. About 60 % of the size of the Motion slice — most of it is tests and the mission fixture; the engine surface added is genuinely small (6 new methods/functions, 1 latent-bug fix).

## Implementation sequencing (preview for the plan)

1. **`GetAccelerationTG` + `PhysicsObjectClass_Cast`** — smallest unblock; lets the prediction step in `Intercept.Update` run without `_Stub` fallthrough.
2. **`GetWorldForwardTG` fix + regression test** — same shape as the prior fix; bundled with step 1 since both touch `engine/appc/objects.py`.
3. **`TurnTowardLocation`** — wraps the existing solver; one unit test file.
4. **`InSystemWarp` + `StopInSystemWarp`** — stateless teleport; its own test file.
5. **Integration smoke** — exercise the full chain end-to-end.
6. **Visible mission + deferred-doc update** — close the slice.

Each task = one TDD cycle. Same shape as the Motion slice.

## Risks + open questions

1. **`GetAccelerationTG` returning zero** is correct for ships under AI motion-setpoint control (acceleration *is* the integrator's ramp, not a stored quantity). The SDK's `Intercept.Update` uses it as the `a` arg to `GetPredictedPosition(p, v, a, t)`. With `a = 0` the prediction degenerates to `p + v·t` — fine for ships at near-constant velocity, slightly inaccurate during the ramp. Action: accept the simplification; revisit only if intercept overshoots on rapidly-accelerating targets in practice.

2. **Stateless warp + Intercept's per-tick cadence.** `Intercept.Update` fires every ~0.4 s. On the first fire the ship is far → `InSystemWarp` teleports and returns 1, so the Intercept code skips its SetSpeed branch this tick. The integrator runs for ~24 ticks before the next AI fire; between fires the ship has no speed setpoint and the integrator drives `_current_speed` toward zero (already there because the warp zeroed it). Next AI fire: distance ≤ `fDistance`, so InSystemWarp returns 0, brake-aware speed engages. Verified flow; risk is low.

3. **`SetMatrixRotation` is not called by `InSystemWarp`.** The teleport only changes translation. So the ship arrives at the warp endpoint with whatever rotation it had — typically still pointing at the spawn-time orientation. The next AI fire calls `TurnTowardLocation`, which rewrites the angular setpoint and the integrator rotates the ship to face the (now-near) target over the next ~0.4 s. Acceptable; the visible result is a brief "pop-in then snap-orient" before the smooth approach.

4. **Teleport visual jarring.** Until renderer-side warp visuals (camera flash, streak particles, motion blur) land, `InSystemWarp` looks like the hostile teleporting. That's fine for headless tests; the visible mission documents the expected behavior in its docstring so users aren't surprised.

5. **`bMoveInFront=1` untested end-to-end.** The branch path is correct after the `GetWorldForwardTG` fix, but no integration test exercises it this slice. Compound AI like `NonFedAttack` will be the first real consumer. Action: defer to the combat slice that lands NonFedAttack.

## What this unlocks

After this slice merges:
- The `FollowObject` / `CircleObject` slice has every motion primitive it needs.
- The combat slice (`Compound.BasicAttack`) has Intercept available as a leaf — combined with weapon-firing preprocessors it produces engaging-and-firing hostile behavior.
- Renderer-side warp visuals (deferred) have a clear hook: `InSystemWarp` returns control after the teleport, and a renderer pass can interpolate the camera + emit streak effects over multiple frames in parallel.
