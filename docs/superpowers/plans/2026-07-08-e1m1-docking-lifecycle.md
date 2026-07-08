# E1M1 Docking/Undocking Lifecycle Spine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the three engine-primitive gaps that block the E1M1 undock→warp→dock→undock lifecycle: sound dock-event constants, real waypoint steering, and a working Starbase-12 line-of-sight test — then verify the whole flow live.

**Architecture:** Implement only the Appc primitives the unchanged SDK already calls. Phase A adds two real event-type ints. Phase B wires `FollowWaypoints`' steering call (`TurnTowardOrientation`) into the existing, tested `ShipClass.TurnDirectionsToDirections` orientation controller. Phase C implements `LineCollides` as a bounding-sphere segment test and live-verifies the Starbase leg.

**Tech Stack:** Python 3 engine shim (`engine/appc/`), pytest + ctest gate (`scripts/check_tests.sh`), the C++ host binary `build/dauntless` (not rebuilt — all A/B/C changes are pure Python).

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-07-08-e1m1-docking-lifecycle-design.md`.
- **Never edit the SDK tree** (`sdk/Build/scripts/`). Implement engine primitives only.
- **Work directly on `main`** (per user direction — no feature branch this pass). Verify `git branch --show-current` is `main` before AND after every commit.
- **Commit with an explicit pathspec** (`git commit <paths> -m …`, never a bare `git commit`) — a concurrent session may have unrelated staged/modified files (`native/tools/dump_nif_tree/dump_nif_tree.cc` and two untracked probe files were present at plan time; leave them alone).
- **End every commit message** with: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- **Test gate:** run `scripts/check_tests.sh` before declaring a task done; it must exit 0 (or fail only on the baselined `tests/known_failures.txt` entries). A/B/C are pure Python, so `pytest` alone covers the change, but the gate is the merge bar.
- **Rotation convention:** column-vector, right-handed. World-forward = `GetWorldRotation().GetCol(1)`, world-up = `GetCol(2)`, world-right = `GetCol(0)`. Never `GetRow`.
- **Game units:** all spatial values are GU; never introduce `*_m`/`*_mps` names.

---

## File Structure

- `App.py` — add two `ET_*` int constants in the bridge/docking block (Phase A).
- `tests/unit/test_bridge_event_constants.py` — extend `BRIDGE_ET_NAMES` (Phase A).
- `engine/appc/ships.py` — add `ShipClass.TurnTowardOrientation` override (Phase B).
- `tests/unit/test_turn_toward_orientation.py` — new; B convergence + delegation (Phase B).
- `tests/integration/test_follow_waypoints_smoke.py` — add a non-collinear-waypoint convergence test (Phase B).
- `engine/appc/objects.py` — implement `PhysicsObjectClass.LineCollides` (Phase C).
- `tests/unit/test_line_collides.py` — new; segment-vs-sphere cases (Phase C).
- `docs/superpowers/plans/2026-07-08-e1m1-docking-lifecycle.md` — this plan; Phase C's live-verify results appended to the Verification section.

---

## Task 1 — Phase A: dock-event constants (real ints)

**Files:**
- Modify: `App.py` (after `ET_REPORT = 1077`, line 922)
- Test: `tests/unit/test_bridge_event_constants.py:5-11` (the `BRIDGE_ET_NAMES` list)

**Interfaces:**
- Produces: `App.ET_PLAYER_DOCKED_WITH_STARBASE = 1078`, `App.ET_TRACTOR_TARGET_DOCKED = 1079` — real distinct ints below the 1200 allocator floor.

- [ ] **Step 1: Add the two names to the test list (failing test)**

In `tests/unit/test_bridge_event_constants.py`, append both names to `BRIDGE_ET_NAMES`:

```python
BRIDGE_ET_NAMES = [
    "ET_ST_BUTTON_CLICKED", "ET_COMMUNICATE", "ET_HAIL", "ET_SCAN",
    "ET_SET_COURSE", "ET_ALL_STOP", "ET_DOCK", "ET_MANAGE_POWER",
    "ET_MANEUVER", "ET_HAILABLE_CHANGE", "ET_SENSORS_SHIP_IDENTIFIED",
    "ET_CLOAK_COMPLETED", "ET_DECLOAK_COMPLETED", "ET_CHARACTER_MENU",
    "ET_CONTACT_STARFLEET", "ET_ORBIT_PLANET", "ET_AI_ORBITTING",
    "ET_PLAYER_DOCKED_WITH_STARBASE", "ET_TRACTOR_TARGET_DOCKED",
]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_bridge_event_constants.py::test_bridge_event_constants_are_distinct_ints -v`
Expected: FAIL — `assert all(type(v) is int ...)` is False because the two new names resolve to `_NamedStub` (not `int`).

- [ ] **Step 3: Add the constants in App.py**

Insert immediately after `ET_REPORT = 1077` (line 922), before the blank line at 923:

```python
# Dock lifecycle notifications. Fired when the player completes a dock with a
# starbase (ET_PLAYER_DOCKED_WITH_STARBASE) and when a tractored target finishes
# docking (ET_TRACTOR_TARGET_DOCKED). Real distinct ints so any future handler
# keyed on them dispatches; without this App.__getattr__ hands back a fresh
# unstable _NamedStub (int()==0) per access. 1078/1079 are the next free values
# in this block (1077 = ET_REPORT is the current high), below the 1200
# Game_GetNextEventType allocator floor.
ET_PLAYER_DOCKED_WITH_STARBASE = 1078
ET_TRACTOR_TARGET_DOCKED       = 1079
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_bridge_event_constants.py -v`
Expected: PASS (both distinct-int and `<1200` tests, now covering the two new names).

- [ ] **Step 5: Commit**

```bash
git branch --show-current   # must print: main
git add App.py tests/unit/test_bridge_event_constants.py
git commit App.py tests/unit/test_bridge_event_constants.py -m "feat(events): define ET_PLAYER_DOCKED_WITH_STARBASE + ET_TRACTOR_TARGET_DOCKED

Real distinct ints (1078/1079) in the bridge block; previously undefined
and resolved to unstable _NamedStub (int()==0) per access. Extends
test_bridge_event_constants coverage.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
git branch --show-current   # must still print: main
```

---

## Task 2 — Phase B: `ShipClass.TurnTowardOrientation` delegation

**Files:**
- Modify: `engine/appc/ships.py` (add method near `TurnTowardLocation` / `TurnDirectionsToDirections`, ~line 405)
- Test: `tests/unit/test_turn_toward_orientation.py` (create)

**Interfaces:**
- Consumes: existing `ShipClass.TurnDirectionsToDirections(primary_from, primary_to, secondary_from=None, secondary_to=None) -> float` (`ships.py:248`), `ShipClass.GetWorldRotation().GetCol(1|2)`, `engine.appc.ship_motion._step_ship_motion(ship, dt)`.
- Produces: `ShipClass.TurnTowardOrientation(vForward, vUp)` — turns the ship so world-forward → `vForward` and world-up → `vUp`, by writing the body-frame angular-velocity setpoint via the shared controller. Overrides the `PhysicsObjectClass.TurnTowardOrientation` no-op (`objects.py:460`), which stays a no-op for non-ship props.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_turn_toward_orientation.py`:

```python
"""ShipClass.TurnTowardOrientation must steer the ship's forward/up onto the
commanded vectors — the 2-arg form AI.PlainAI.FollowWaypoints.TurnToward calls
(sdk/.../FollowWaypoints.py:276). It delegates to the tested
TurnDirectionsToDirections controller; FollowWaypoints could not turn before
this (PhysicsObjectClass.TurnTowardOrientation was a no-op)."""
from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.ships import ShipClass
from engine.appc.subsystems import ImpulseEngineSubsystem
from engine.appc.ship_motion import _step_ship_motion

_DT = 1.0 / 60.0


def _galaxy_ship():
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    ies = ImpulseEngineSubsystem("IES")
    ies.SetMaxSpeed(6.3)
    ies.SetMaxAccel(1.5)
    ies.SetMaxAngularVelocity(0.28)
    ies.SetMaxAngularAccel(0.12)
    ship.SetImpulseEngineSubsystem(ies)
    return ship


def _fwd_dot(ship, target_fwd):
    fwd = ship.GetWorldRotation().GetCol(1)
    d = TGPoint3(target_fwd.x, target_fwd.y, target_fwd.z); d.Unitize()
    return fwd.x * d.x + fwd.y * d.y + fwd.z * d.z


def test_turn_toward_orientation_converges_off_axis():
    """From an arbitrary attitude, commanding a fixed target forward/up each
    tick must land the nose on target and hold it (no hunting)."""
    ship = _galaxy_ship()
    Rx = TGMatrix3(); Rx.MakeRotation(1.1, TGPoint3(1.0, 0.0, 0.0))
    Rz = TGMatrix3(); Rz.MakeRotation(2.3, TGPoint3(0.0, 0.0, 1.0))
    ship.SetMatrixRotation(Rx.MultMatrix(Rz))

    target_fwd = TGPoint3(0.6, 0.8, 0.0); target_fwd.Unitize()
    target_up = TGPoint3(0.0, 0.0, 1.0)

    history = []
    for _ in range(int(20.0 * 60)):
        ship.TurnTowardOrientation(target_fwd, target_up)
        _step_ship_motion(ship, _DT)
        history.append(_fwd_dot(ship, target_fwd))

    assert history[-1] > 0.999, f"never converged: {history[-1]:.3f}"
    assert min(history[-300:]) > 0.995, "hunting after alignment"


def test_turn_toward_orientation_writes_body_setpoint():
    """One call must write a non-None body-frame angular-velocity setpoint
    (proves delegation actually reached the controller, not the no-op stub)."""
    ship = _galaxy_ship()
    target_fwd = TGPoint3(1.0, 0.0, 0.0)   # 90° off the +Y nose
    target_up = TGPoint3(0.0, 0.0, 1.0)
    ship.TurnTowardOrientation(target_fwd, target_up)
    sp = ship.GetTargetAngularVelocitySetpoint()
    assert sp is not None
    assert (sp.x * sp.x + sp.y * sp.y + sp.z * sp.z) > 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_turn_toward_orientation.py -v`
Expected: FAIL — `TurnTowardOrientation` resolves to the `PhysicsObjectClass` no-op (returns None, writes no setpoint), so `test_...writes_body_setpoint` fails on `sp is not None` and `test_...converges_off_axis` fails (nose never moves).

- [ ] **Step 3: Implement the override**

In `engine/appc/ships.py`, add to `ShipClass` (place right after `TurnDirectionsToDirections`, before the next unrelated method, ~line 405):

```python
def TurnTowardOrientation(self, vForward, vUp):
    """Steer world-forward onto vForward and world-up onto vUp.

    The 2-arg orientation form AI.PlainAI.FollowWaypoints.TurnToward
    (sdk/.../FollowWaypoints.py:276) commands. BC's PhysicsObjectClass
    exposes this; we service it on ShipClass by supplying the ship's
    CURRENT forward/up as the 'from' vectors and delegating to the shared
    turn-rate-limited controller (TurnDirectionsToDirections), which writes
    the body-frame angular-velocity setpoint that ship_motion integrates.
    Non-ship physics props keep the PhysicsObjectClass no-op (no IES / no
    turn controller; they never follow waypoints)."""
    R = self.GetWorldRotation()
    primary_from = R.GetCol(1)    # current world forward (model-Y)
    secondary_from = R.GetCol(2)  # current world up
    self.TurnDirectionsToDirections(primary_from, vForward,
                                    secondary_from, vUp)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_turn_toward_orientation.py -v`
Expected: PASS (both).

- [ ] **Step 5: Guard the shared controller's existing tests**

Run: `uv run pytest tests/unit/test_turn_directions.py tests/unit/test_turn_directions_convergence.py tests/unit/test_turn_toward_location.py -v`
Expected: PASS (unchanged — the override reuses `TurnDirectionsToDirections`, does not modify it).

- [ ] **Step 6: Commit**

```bash
git branch --show-current   # must print: main
git add engine/appc/ships.py tests/unit/test_turn_toward_orientation.py
git commit engine/appc/ships.py tests/unit/test_turn_toward_orientation.py -m "feat(ai): ShipClass.TurnTowardOrientation delegates to turn controller

FollowWaypoints steered via TurnTowardOrientation, which hit the
PhysicsObjectClass no-op stub — ships could not turn to chase a waypoint.
Delegate to the existing tested TurnDirectionsToDirections controller.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
git branch --show-current   # must still print: main
```

---

## Task 3 — Phase B: FollowWaypoints reaches a non-collinear waypoint

**Files:**
- Test: `tests/integration/test_follow_waypoints_smoke.py` (add one test)

**Interfaces:**
- Consumes: `ShipClass.TurnTowardOrientation` (Task 2), `PlainAI_Create`, `FollowWaypoints` script module, `engine.appc.ship_motion._step_ship_motion`.
- Produces: nothing new — regression proof that the steering fix makes a curved approach converge, not just a straight one.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_follow_waypoints_smoke.py`:

```python
def test_follow_waypoints_turns_to_offset_waypoint():
    """With TurnTowardOrientation wired, a ship facing +Y must turn toward a
    waypoint that is NOT dead ahead and close the bearing. Before the fix the
    ship flew straight along +Y forever (TurnTowardOrientation was a no-op)."""
    from engine.appc.math import TGPoint3
    from engine.appc.ship_motion import _step_ship_motion

    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours._hull = HullSubsystem("H")
    ours._hull.SetMaxCondition(1000.0)
    ies = ImpulseEngineSubsystem("IES")
    ies.SetMaxSpeed(120.0); ies.SetMaxAccel(50.0)
    ies.SetMaxAngularVelocity(0.5); ies.SetMaxAngularAccel(0.3)
    ours._impulse_engine_subsystem = ies
    pSet.AddObjectToSet(ours, "Ours")

    # Waypoint 90° off the +Y nose (dead abeam to starboard).
    other = ShipClass(); other.SetTranslateXYZ(4000.0, 0.0, 0.0)
    other._hull = HullSubsystem("H"); other._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(other, "WP1")

    plain = PlainAI_Create(ours, "TestAI")
    plain.SetScriptModule("FollowWaypoints")
    inst = plain.GetScriptInstance()
    inst.SetTargetWaypointName("WP1")

    def bearing_dot():
        fwd = ours.GetWorldRotation().GetCol(1)
        d = TGPoint3(4000.0 - ours.GetTranslate().x,
                     0.0 - ours.GetTranslate().y,
                     0.0 - ours.GetTranslate().z)
        d.Unitize()
        return fwd.x * d.x + fwd.y * d.y + fwd.z * d.z

    start_dot = bearing_dot()
    # Re-command on the AI cadence, integrate at 60 Hz between commands.
    for _ in range(600):            # 10 s
        inst.Update()
        _step_ship_motion(ours, 1.0 / 60.0)
    end_dot = bearing_dot()

    assert end_dot > start_dot + 0.2, (
        f"nose did not turn toward the offset waypoint: {start_dot:.3f} -> {end_dot:.3f}")
```

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_follow_waypoints_smoke.py::test_follow_waypoints_turns_to_offset_waypoint -v`
Expected: PASS with Task 2 in place. (Sanity: it would FAIL on `main` before Task 2 — the bearing dot stays flat because the ship never turns.)

- [ ] **Step 3: Run the whole file**

Run: `uv run pytest tests/integration/test_follow_waypoints_smoke.py -v`
Expected: PASS (both tests).

- [ ] **Step 4: Commit**

```bash
git branch --show-current   # must print: main
git add tests/integration/test_follow_waypoints_smoke.py
git commit tests/integration/test_follow_waypoints_smoke.py -m "test(ai): FollowWaypoints turns toward an offset waypoint

Regression proof for the TurnTowardOrientation steering fix — a curved
approach converges instead of flying straight past.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
git branch --show-current   # must still print: main
```

---

## Task 4 — Phase B2: cutscene-call crash audit

**Files:**
- Audit only (grep); modify `engine/appc/top_window.py` or `engine/appc/sets.py` ONLY if a genuine missing method is found.

**Interfaces:**
- Produces: certainty that `SetupCutscene` / `FinishedUndocking` won't `AttributeError`-crash. No new interface unless a gap is found.

- [ ] **Step 1: List every engine call the two cutscene functions make**

Run:
```bash
sed -n '/^def SetupCutscene/,/^def /p;/^def FinishedUndocking/,/^def /p' sdk/Build/scripts/AI/Compound/DockWithStarbase.py
```
Note every `App.<X>`, `pTopWindow.<M>`, `pSet.<M>`, `Camera.<M>` call.

- [ ] **Step 2: Verify each method exists on its backing class**

For each `top_window`/set method observed, run e.g.:
```bash
grep -nE "def (ToggleCinematicWindow|ForceBridgeVisible|IsBridgeVisible|StopForcingBridgeVisible|MakeRenderedSet|ChangeRenderedSet)" engine/appc/top_window.py engine/appc/sets.py
```
Known-present at plan time: `IsBridgeVisible` (top_window.py:131), `ForceBridgeVisible` (137), `ToggleCinematicWindow` (252), `MakeRenderedSet` (sets.py:509). Confirm the full observed list; `top_window.py` has NO `_Stub` catch-all, so any absent method is a hard crash.

- [ ] **Step 3: Resolve findings**

- If every method is present: record "audit clean — no gap" as a comment in the Verification section of this plan (Step 4 of Task 6). No code change; **skip to Task 5** (no commit for this task).
- If a method is genuinely missing: implement it minimally on its backing class following the neighboring methods' pattern (e.g. a `top_window` visibility flag toggle), add a one-assert unit test in the matching `tests/unit/test_*` file, run it, and commit with an explicit pathspec + the standard co-author trailer. (`Camera.Placement` is NOT a gap to fix here — it intentionally returns early on the missing "Placement" mode until deferred Phase D; confirm it early-returns rather than raising.)

---

## Task 5 — Phase C: `LineCollides` segment-vs-sphere test

**Files:**
- Modify: `engine/appc/objects.py` (add `PhysicsObjectClass.LineCollides`)
- Test: `tests/unit/test_line_collides.py` (create)

**Interfaces:**
- Consumes: `self.GetWorldLocation()`, `self.GetRadius()` (both on `PhysicsObjectClass`/`ObjectClass`), `engine.appc.math.TGPoint3`.
- Produces: `PhysicsObjectClass.LineCollides(p1, p2) -> int` — 1 if the segment p1→p2 crosses the receiver's bounding-sphere surface (center = world location, radius = `GetRadius()`), else 0. Called as `pStarbase.LineCollides(vPos, playerPos)` in `IsInViewOfInsidePoints` (`DockWithStarbase.py:368`): interior point → player crosses the hull sphere when the player is outside (not visible) but not when the player is inside the bay (visible).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_line_collides.py`:

```python
"""PhysicsObjectClass.LineCollides(p1, p2): does the segment cross the object's
bounding-sphere surface? Backs AI.Compound.DockWithStarbase.IsInViewOfInsidePoints
(sdk/.../DockWithStarbase.py:368). Was an unimplemented silent truthy _NamedStub."""
from engine.appc.math import TGPoint3
from engine.appc.objects import PhysicsObjectClass


def _obj_at(x, y, z, radius):
    o = PhysicsObjectClass()
    o.SetTranslateXYZ(x, y, z)
    o.SetRadius(radius)
    return o


def test_interior_point_to_outside_crosses_surface():
    """One endpoint inside the sphere, one outside -> crosses -> collides."""
    o = _obj_at(0.0, 0.0, 0.0, 100.0)
    inside = TGPoint3(10.0, 0.0, 0.0)      # inside radius 100
    outside = TGPoint3(500.0, 0.0, 0.0)    # well outside
    assert o.LineCollides(inside, outside) == 1


def test_both_endpoints_inside_no_crossing():
    """Both endpoints inside the sphere -> no surface crossing -> clear."""
    o = _obj_at(0.0, 0.0, 0.0, 100.0)
    a = TGPoint3(10.0, 0.0, 0.0)
    b = TGPoint3(-20.0, 30.0, 0.0)
    assert o.LineCollides(a, b) == 0


def test_segment_passing_through_sphere_collides():
    """Both endpoints outside but the segment passes through -> collides."""
    o = _obj_at(0.0, 0.0, 0.0, 100.0)
    a = TGPoint3(-500.0, 0.0, 0.0)
    b = TGPoint3(500.0, 0.0, 0.0)
    assert o.LineCollides(a, b) == 1


def test_segment_clear_of_sphere_misses():
    """Both endpoints outside and the segment never nears the sphere -> clear."""
    o = _obj_at(0.0, 0.0, 0.0, 100.0)
    a = TGPoint3(-500.0, 400.0, 0.0)
    b = TGPoint3(500.0, 400.0, 0.0)        # closest approach y=400 > r=100
    assert o.LineCollides(a, b) == 0


def test_degenerate_zero_length_segment_inside():
    """A zero-length segment inside the sphere does not cross the surface."""
    o = _obj_at(0.0, 0.0, 0.0, 100.0)
    p = TGPoint3(5.0, 0.0, 0.0)
    assert o.LineCollides(p, p) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_line_collides.py -v`
Expected: FAIL — `LineCollides` is unimplemented; the `_NamedStub` it resolves to is truthy but not callable-returning-int in the way asserted (raises or returns a stub, not `0`/`1`).

- [ ] **Step 3: Implement `LineCollides`**

In `engine/appc/objects.py`, replace nothing — add a real method to `PhysicsObjectClass` (near the other geometry helpers). Sphere-surface-crossing test:

```python
def LineCollides(self, p1, p2) -> int:
    """1 if the segment p1->p2 crosses this object's bounding-sphere surface,
    else 0. 'Crosses the surface' = the closest point on the segment is within
    GetRadius() of the centre AND at least one endpoint is outside the radius
    (so a segment fully inside the sphere is clear, and one that grazes past
    outside the radius is clear). Sphere-clearance fidelity matches the rest of
    the collision layer; full mesh collision is out of scope. Backs
    AI.Compound.DockWithStarbase.IsInViewOfInsidePoints."""
    c = self.GetWorldLocation()
    r = self.GetRadius()
    if r <= 0.0:
        return 0
    ax, ay, az = p1.x - c.x, p1.y - c.y, p1.z - c.z
    bx, by, bz = p2.x - c.x, p2.y - c.y, p2.z - c.z
    da = (ax * ax + ay * ay + az * az) ** 0.5
    db = (bx * bx + by * by + bz * bz) ** 0.5
    r2 = r * r
    # Both endpoints inside -> segment stays inside -> no surface crossing.
    if da <= r and db <= r:
        return 0
    # Closest point on the segment to the centre.
    dx, dy, dz = bx - ax, by - ay, bz - az
    seg2 = dx * dx + dy * dy + dz * dz
    if seg2 <= 1e-12:
        # Degenerate segment (a point). Inside-both handled above; a lone
        # point outside does not "cross" the surface.
        return 0
    t = -(ax * dx + ay * dy + az * dz) / seg2
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    cx, cy, cz = ax + dx * t, ay + dy * t, az + dz * t
    closest2 = cx * cx + cy * cy + cz * cz
    # At least one endpoint is outside (checked above). If the segment reaches
    # within the radius, it crosses the surface.
    return 1 if closest2 <= r2 else 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_line_collides.py -v`
Expected: PASS (all five).

- [ ] **Step 5: Commit**

```bash
git branch --show-current   # must print: main
git add engine/appc/objects.py tests/unit/test_line_collides.py
git commit engine/appc/objects.py tests/unit/test_line_collides.py -m "feat(physics): implement PhysicsObjectClass.LineCollides (segment vs sphere)

Was a silent truthy _NamedStub, so DockWithStarbase.IsInViewOfInsidePoints
always returned 0. Sphere-surface-crossing test; backs the Starbase inside-
point line-of-sight check.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
git branch --show-current   # must still print: main
```

---

## Task 6 — Phase C: full gate + end-to-end live-verify

**Files:**
- Modify: `docs/superpowers/plans/2026-07-08-e1m1-docking-lifecycle.md` (append results to Verification below)

**Interfaces:** none — this is the acceptance gate for the whole plan.

- [ ] **Step 1: Run the full machine gate**

Run: `scripts/check_tests.sh`
Expected: exits 0, or fails only on the baselined `tests/known_failures.txt` entries. Any other failure is a regression this plan introduced — fix before proceeding.

- [ ] **Step 2: Launch the game in developer mode**

Run: `./build/dauntless --developer`
(If the binary is stale/missing: `cmake -B build -S . && cmake --build build -j`, then rerun. A/B/C changed no C++, so a rebuild should not be needed.)

- [ ] **Step 3: Drive the E1M1 lifecycle**

In-game: pause menu → **Load Mission…** → Maelstrom → Episode 1 → E1M1. Then:
1. Click the **Dock** button to trigger `UndockCutscene` → confirm the ship physically undocks and flies to "Way 1" (drydock undock still works — straight-line path).
2. Set course / warp to Starbase 12.
3. At Starbase 12, dock (Helm → Dock Starbase 12) → confirm the `DockWithStarbase` compound AI drives the ship along the docking waypoints and the ship **turns to track the curved approach** (the Task 2 fix), advancing `SetupCutscene → EnterStarbase → PlayerDocked → RepairShipFully/ReloadShip`.
4. Undock from the starbase → confirm `UndockFromStarbase` runs `SetupExitPositions → ExitStarbase → Undocked` without wedging.

- [ ] **Step 4: Record observations in this plan**

Append a `## Verification` section with: which beats completed, whether the ship turned to track the Starbase approach (the key Task-2 signal), whether it bumped any drydock (immobility interaction — `AvoidObstacles` expected to prevent this), the Task-4 audit result ("clean" or what was fixed), and any residual gap discovered (which becomes the next spec's input — do NOT expand scope here).

- [ ] **Step 5: Commit the verification notes**

```bash
git branch --show-current   # must print: main
git add docs/superpowers/plans/2026-07-08-e1m1-docking-lifecycle.md
git commit docs/superpowers/plans/2026-07-08-e1m1-docking-lifecycle.md -m "docs(e1m1): live-verify results for docking lifecycle spine

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
git branch --show-current   # must still print: main
```

---

## Verification

### Machine gate — ✅ GREEN (2026-07-08)

`scripts/check_tests.sh`: build ok · pytest **0 failures** · ctest **0 failures** · **0** baselined known failures. All A/B/C changes are pure Python; no C++ regression. Commit range `96128263..f04cb4ae` (+ the emergent resolver + the cutscene-window fix).

### Emergent findings during execution

- **App.PhysicsObjectClass_GetObject was unimplemented (Task 3b, commit a0c2f2ea)** — the SDK `FollowWaypoints.Update` resolves its destination via this call *before* the `PlacementObject_GetObject` fallback (`FollowWaypoints.py:132`). Absent, it returned a truthy `_NamedStub`, so the `if pObject == None` guard never matched and every live waypoint AI's destination collapsed to garbage. This was the true, higher-impact sibling of the `TurnTowardOrientation` gap and is now fixed (mirrors `ShipClass_GetObject`'s type-filtered lookup). Without both fixes, live waypoint-following could not work.
- **MWT_CINEMATIC top-window was unseeded (Task 4, commit 7fa90d78)** — `DockWithStarbase.SetupCutscene` dereferences `FindMainWindow(MWT_CINEMATIC).GetObjID()` with no None-guard; the shim returned `None`, a latent `AttributeError` crash on the reachable focus path. Fixed by seeding `_CinematicWindow` (mirrors the existing `_OptionsWindow` precedent).
- **Out of scope (noted, not fixed):** `App.ET_SHOW_MISSION_LOG` appears undefined, making the XO menu's "Show Mission Log" handler dispatch miss via stub-identity hashing. Unrelated to docking; flagged for a future sweep.

### Live-verify checklist — PENDING (Mark to run at workstation)

Per the project's no-live-desktop-interaction guardrail, the in-game pass is run by Mark. Steps:

1. `./build/dauntless --developer` → pause menu → **Load Mission…** → Maelstrom → Episode 1 → **E1M1**.
2. **Undock from drydock:** click **Dock** button → `UndockCutscene` runs → confirm the ship physically undocks and flies to "Way 1" (straight-line path; should still work). Watch it does **not** bump the Station/Nightingale/other drydocks (immobility interaction; `AvoidObstacles` expected to prevent it).
3. **Warp to Starbase 12** (Set Course / warp point).
4. **Dock with Starbase 12** (Helm → Dock Starbase 12): confirm the `DockWithStarbase` compound AI drives the ship along the docking waypoints and — the key Task-2 signal — the ship **turns to track the curved approach** (before this work it flew straight past). Confirm the sequence advances `SetupCutscene → EnterStarbase → PlayerDocked → RepairShipFully/ReloadShip` without wedging, and the dock cutscene does not crash (Task-4 fix).
5. **Undock from the starbase:** confirm `UndockFromStarbase` runs `SetupExitPositions → ExitStarbase → Undocked` without wedging.
6. Record what actually happened here. Any residual gap becomes the next spec's input — do **not** expand scope in this plan.

_(Live-verify results to be appended by Mark.)_

---

## Self-review notes

- **Spec coverage:** Phase A → Task 1; Phase B core → Tasks 2–3; Phase B2 audit → Task 4; Phase C `LineCollides` → Task 5; Phase C live-verify + immobility check → Task 6. Deferred D/E carry no tasks (correct). All spec sections map to a task.
- **Types:** `TurnTowardOrientation(vForward, vUp)` (Task 2) is consumed by Task 3's FollowWaypoints run and matches the SDK 2-arg call; delegates to `TurnDirectionsToDirections(primary_from, primary_to, secondary_from, secondary_to)` (existing). `LineCollides(p1, p2) -> int` (Task 5) matches the `pStarbase.LineCollides(vPos, playerPos)` call site. Event names `ET_PLAYER_DOCKED_WITH_STARBASE` / `ET_TRACTOR_TARGET_DOCKED` consistent between App.py and the test.
- **No placeholders:** every code/test step shows complete code; commands have expected output.
