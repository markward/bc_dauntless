# E1M1 docking/undocking lifecycle spine — design

**Date:** 2026-07-08
**Status:** Approved for planning
**Scope:** Phases A + B + C (the motion spine). Phases D (exterior `Placement`
cutscene camera) and E (character root motion) are deferred — see *Deferred work*.

## Problem

Mission E1M1 drives a four-beat docking lifecycle entirely from the unchanged
BC SDK scripts: undock from the drydock → warp to Starbase 12 → dock with
Starbase 12 → undock from the starbase. The mechanical spine already runs
(`SetDocked`, the dock button, `ET_DOCK` dispatch, the `TGSequence` /
`CharacterAction` framework, and the real `FollowWaypoints`-driven undock
motion). Three engine primitives that the SDK calls are missing or unsound,
and the Starbase leg has never been verified end to end.

All three are **engine-primitive gaps**: the fix is to implement the Appc
surface the SDK already invokes. No SDK edits, no new game logic. Silent
`_Stub` / undefined-name no-ops are the through-line — each gap is a call the
SDK makes that currently does nothing (or returns an unstable stub) instead of
the work the script assumes happened.

### Ground-truth SDK entry points

- `sdk/Build/scripts/Maelstrom/Episode1/E1M1/E1M1.py` — `DockButtonClicked`
  (1237), `UndockCutscene` (2494), `SpecialDockSequence` (3010),
  `ReenablePlayerDrydockCollisions` (1325).
- `sdk/Build/scripts/AI/Compound/DockWithStarbase.py`,
  `UndockFromStarbase.py` — the compound auto-dock/undock AI graphs.
- `sdk/Build/scripts/AI/PlainAI/FollowWaypoints.py` — the Helm leaf AI backing
  `UndockAI` and the Starbase graphs; its `TurnToward` (265) is the only
  steering command it issues.
- `sdk/Build/scripts/AI/PlainAI/TurnToOrientation.py` — a *different* AI that
  already reaches our working turn controller (the reuse target for Phase B).

## Confirmed gap analysis

| # | Gap | Severity | Status |
|---|-----|----------|--------|
| A | `ET_PLAYER_DOCKED_WITH_STARBASE` / `ET_TRACTOR_TARGET_DOCKED` undefined → fresh `_NamedStub` per access, `int()==0` | Latent | Real; nothing keys on them in E1M1 today |
| B | `PhysicsObjectClass.TurnTowardOrientation` is `pass` — `FollowWaypoints` can't turn | **Primary blocker** | Real; Starbase curved approach wedges forever |
| C | `LineCollides` silent truthy stub → `IsInViewOfInsidePoints` always 0; whole Starbase leg unverified | Correctness + untested | Real |

The brief ranked `LineCollides` as the Starbase blocker; investigation showed
the true blocker is `TurnTowardOrientation`. `LineCollides` is a secondary
correctness bug (interior-prop save/restore), not a hard wedge.

## Architecture

One feature branch (`feat/e1m1-docking-lifecycle` off `main`), one spec, three
implementation phases. A is independent; B is the core; C depends on B. Each
phase keeps the `scripts/check_tests.sh` gate green. Phases A/B/C are pure
Python — no `native/` rebuild.

---

## Phase A — Dock-event soundness (XS)

### Design

`App.py:__getattr__` (~1925) only memoizes `WC_`/`KY_` names; every other
undefined attribute returns a **fresh** `_NamedStub` that is truthy but
`int()`s to `0` and is not stable across accesses. So any handler keyed on
`App.ET_PLAYER_DOCKED_WITH_STARBASE` compared against an event fired with the
"same" name would never match — a latent never-dispatch.

Allocate both as real literal-int constants in the bridge/docking block
(siblings of `ET_DOCK = 1066`) at the next free slots (~1078–1079), staying
**below the 1200 dynamic-allocator floor** (`Game_GetNextEventType`) so they
never collide with runtime-allocated ids.

### Data flow

No behavior change in E1M1 today — nothing fires or listens for either event
in the mission. This makes the constants *sound* so the lifecycle's
dock/undock notifications (and the tractor-dock path) have stable, distinct
integer identities when a listener is eventually attached.

### Testing

Extend `BRIDGE_ET_NAMES` in `tests/unit/test_bridge_event_constants.py` so the
existing assertions (`type(v) is int`, all distinct, all `< 1200`) cover both
new names. That test fails today for these names (they resolve to `_NamedStub`)
and passes once the constants are added — the RED→GREEN gate for Phase A.

---

## Phase B — Waypoint steering (S)

### The reuse discovery

A fully-implemented, turn-rate-and-acceleration-limited orientation controller
already exists: `ShipClass.TurnDirectionsToDirections(primary_from, primary_to,
secondary_from, secondary_to)` (`engine/appc/ships.py:248–404`). It:

1. Computes the primary alignment axis·angle (`pf × pt`, `acos(pf·pt)`), with
   degenerate-collinear handling.
2. Adds a signed secondary roll constraint around the primary axis.
3. Caps the commanded magnitude at `√(2·MaxAngularAccel·θ)` so the ship
   decelerates into alignment instead of overshooting/hunting.
4. Converts world→body frame (`v_body = Rᵀ·v_world`, column-vector `GetCol`).
5. Clamps per-axis to `GetMaxAngularVelocity()`.
6. Writes `_target_angular_velocity_setpoint` via
   `SetTargetAngularVelocityDirect`.

`ship_motion._step_ship_motion` (`ship_motion.py:215–233`) then ramps
`_current_angular_velocity` toward that setpoint under `MaxAngularAccel` and
caps at `MaxAngularVelocity`, and `_integrate_rotation` (292+) applies it —
exactly the chosen **turn-rate-limited** behavior.

This controller is already reached by the SDK's `AI.PlainAI.TurnToOrientation`.
It is **not** reached by `FollowWaypoints`, which steers via
`pShip.TurnTowardOrientation(vForward, vUp)` → the `PhysicsObjectClass`
no-op stub (`engine/appc/objects.py:460`).

### Design

Override `TurnTowardOrientation(vForward, vUp)` on **`ShipClass`** (not the
base `PhysicsObjectClass`) to delegate to the existing controller:

```
def TurnTowardOrientation(self, vForward, vUp):
    R = self.GetWorldRotation()
    primary_from   = R.GetCol(1)   # current world forward (model-Y)
    secondary_from = R.GetCol(2)   # current world up
    self.TurnDirectionsToDirections(primary_from, vForward,
                                    secondary_from, vUp)
```

- `TurnTowardOrientation(vForward, vUp)` semantics (from BC Appc + the
  `FollowWaypoints.TurnToward` caller at line 265): rotate the ship so its
  forward aligns to `vForward` and its up to `vUp`. `vForward` is the unit
  direction to the destination; `vUp` is the recomputed orthonormal up.
- Delegation maps the 2-arg "target only" form onto the 4-arg
  "from→to" controller by supplying the ship's *current* forward/up as the
  `from` vectors.
- The base `PhysicsObjectClass.TurnTowardOrientation` **stays a no-op**:
  non-ship physics props have no IES / turn controller and never follow
  waypoints. Only `ShipClass` gets the real behavior.

### Data flow

`FollowWaypoints.Update` (0.5 s AI cadence) computes destination + up →
`TurnToward` → `TurnTowardOrientation` → `TurnDirectionsToDirections` writes
the body-frame setpoint → every 60 Hz physics tick `ship_motion` ramps and
integrates it. The setpoint persists between AI ticks, so the turn is smooth
despite the coarse AI cadence. `SetSpeed` (already working) continues to drive
translation along model-forward; the two together produce a banking approach
that tracks the waypoint.

### Sub-task B2 — cutscene-call crash audit

`SetupCutscene` / `FinishedUndocking` (in `DockWithStarbase.py`) call
`top_window` / set methods (`ToggleCinematicWindow`, `ForceBridgeVisible`,
`IsBridgeVisible`, `MakeRenderedSet`, `ChangeRenderedSet`, `Camera.Placement`,
`CutsceneCameraBegin/End`). `top_window.py` has **no `_Stub` catch-all**, so an
unimplemented method raises `AttributeError` (a hard crash), not a silent
no-op. Spot-checks confirm `IsBridgeVisible` (131), `ForceBridgeVisible` (137),
`ToggleCinematicWindow` (252), `MakeRenderedSet` (`sets.py:509`) exist. This
sub-task is a *complete* grep of every method those two functions call against
the classes that back them, fixing or stubbing any genuine gap found.
(`Camera.Placement` intentionally no-ops until Phase D — that path returns
early on a missing mode rather than crashing; confirm that early-return, don't
implement the mode here.)

### Testing

- Unit: after `ship.TurnTowardOrientation(off_axis_forward, up)`, simulate N
  `ship_motion` ticks and assert `GetWorldForwardTG()` converges monotonically
  toward `off_axis_forward` and settles without hunting (no sign flips in the
  residual angle past a threshold).
- Integration: a `FollowWaypoints` instance steering a ship to a
  **non-collinear** waypoint reaches it (leaf returns `US_DONE`) within a tick
  budget; a regression that today's straight-line-only behavior would fail.
- Guard the existing `TurnToOrientation`/`TurnDirectionsToDirections` tests
  stay green (shared controller).

---

## Phase C — Starbase dock/undock verification + `LineCollides` (M)

### Design

With B in place the compound AI graph should track its waypoints. Two things
remain:

**`LineCollides`** — implement as a real segment-vs-object test. `LineCollides`
is not defined anywhere in `engine/`; it resolves to a truthy `_NamedStub`, so
`if not pStarbase.LineCollides(...)` in `IsInViewOfInsidePoints`
(`DockWithStarbase.py:368`) is always False and the LOS test always returns 0.
Scope the implementation to what the SDK needs: a **segment vs. bounding-sphere
(`GetRadius`) clearance / line-of-sight test** across candidate objects in the
set — matching the fidelity of the rest of our collision layer (`collisions.py`
is sphere/AABB-based; full mesh collision is out of scope). Return whether the
segment intersects any blocking object.

Effects fixed: (a) `IsInViewOfInsidePoints` returns a real bool, so the
"already inside the starbase" branch is chosen correctly; (b) the interior-prop
save/restore in `SetupDockPositions` / `FinishedUndocking` records and restores
displaced objects.

**End-to-end live-verify** is a first-class deliverable of this phase, not an
afterthought — this is the largest previously-untested stretch. Drive
`./build/dauntless --developer` → Load Mission → Maelstrom E1M1 and execute the
full lifecycle, confirming the `DockingSequence` advances through
`SetupCutscene → EnterStarbase → PlayerDocked → RepairShipFully/ReloadShip →
PrepareUndock → ExitStarbase → Undocked` without wedging, and the drydock
`UndockAI` still reaches "Way 1". Capture observed behavior (what renders,
where it stalls if it does) so any residual gap becomes the next spec's input.

### Immobility interaction

Static-object immobility (merged 2026-07-08) makes the drydocks solid immovable
walls. The live-verify explicitly checks the player, flying out under `UndockAI`
and approaching the starbase, does not bump the Station / Nightingale / other
drydocks — `AvoidObstacles` should handle it; confirm empirically.

### Testing

- Unit: `LineCollides` — clear hit, clear miss, endpoint-inside-radius,
  degenerate zero-length segment, multi-object set (nearest blocker).
- Integration: `IsInViewOfInsidePoints` returns a real bool for a known
  geometry (inside vs. outside the starbase inside-points).
- Manual: the live-verify pass above (documented in the plan's verification
  section, not automatable headless).

---

## Deferred work

- **Phase D — exterior `Placement` cutscene camera.** The undock sequence's
  `PlacementWatch("DryDock","player","Cam Pos 1")` needs a `"Placement"` camera
  mode registered in `bridge_set.py:_MODE_FACTORY`; today it pushes no mode and
  the exterior sweep never renders (player sees the normal chase cam — cosmetic,
  not a wedge). A reference implementation exists at `622be12f` on the unmerged
  `feat/mission-view-camera-input-locks` branch. **Decision:** defer until after
  A–C; when picked up, first audit `622be12f` to decide port-vs-fresh, then plan.
- **Phase E — character root motion.** `CharacterAction._do_play`
  (`engine/appc/ai.py:1199`) executes only speak/say types; `AT_MOVE` /
  `AT_TURN` / `AT_WATCH_ME` / `AT_STOP_WATCHING_ME` are recognized-but-silent
  no-ops, so Picard's scripted walk-to-chair in the undock interior cutscene
  doesn't happen. This is NOT covered by the 2026-06-17 camera walk-on plan
  (camera-only, explicitly defers crew walk-ons) and `feat/character-walk-on` is
  a stale mispointed branch. Builds on the existing skinned-character /
  placement-animation infra. Its own spec later.

## Non-goals

- Explicit docking-port APIs (`GetDockingPoint`, `DockingPort`,
  `GetNumDockingPorts`, `AT_DOCK`) — stubbed, but the game never uses them; it
  drives everything off named waypoints + model hardpoint properties.
- Full mesh-level collision for `LineCollides` (sphere-clearance suffices).
- Any SDK script edits.

## Risks

- **B delegation semantics.** If `TurnTowardOrientation`'s forward/up mapping is
  wrong, the ship turns about the wrong axes and hunts. Mitigated by the
  monotonic-convergence unit test and reuse of the already-correct world→body
  conversion in the shared controller.
- **Shared checkout.** Multiple sessions switch branches in this one checkout.
  Verify branch before AND after every commit; commit with explicit pathspec.
- **`LineCollides` scope creep.** Keep it sphere-clearance; do not chase mesh
  fidelity the rest of the engine doesn't have.
- **C live-verify may surface a further gap** (e.g. a proximity/repair edge).
  That's an expected output, captured as the next spec's input rather than
  expanded in-scope here.
