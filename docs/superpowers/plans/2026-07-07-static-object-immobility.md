# Static-object Immobility + Per-pair Collision Masking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ships flagged immobile (`SetStatic`/`SetStationary`) actually stay put, and make per-pair `EnableCollisionsWith` real, so the E1M1 spacedock stops rotating/wiggling/drifting in front of the player at bridge-load.

**Architecture:** Add a `ShipClass.IsImmobile()` predicate (`IsStatic() or IsStationary()`) and honour it at the three runtime sites that ignore it today — the motion integrator (skip), collision response (treat as immovable like a planet), collision avoidance (don't steer). Separately, implement `DamageableObject.EnableCollisionsWith(pOther, bOn)` as a per-object set of disabled peer ObjIDs, and skip any pair either side has disabled inside `resolve_collisions`.

**Tech Stack:** Python 3, pytest. Pure-Python engine change — **no C++ / cmake rebuild**.

## Global Constraints

- **No C++ rebuild:** every change is in `engine/appc/*.py`. Do **not** touch `native/` or run cmake.
- **Test gate:** the authoritative gate is `scripts/check_tests.sh` (builds C++, runs pytest + ctest, diffs against `tests/known_failures.txt`). For fast per-task iteration run the specific pytest file; run the full gate before the final commit. A failure counts as pre-existing only if it is already in `tests/known_failures.txt`.
- **`_Stub` trap:** `TGObject.__getattr__` (`engine/core/ids.py:106`) returns a truthy `_Stub` for any unset attribute. Never read a lazily-set instance attribute with `getattr(obj, name, None)` — use `obj.__dict__.get(name, default)`. (`_static` and `_stationary` are set in `__init__`, so `IsStatic()`/`IsStationary()` are safe as direct calls; the new `_collision_disabled_ids` is lazy, so it must use the `__dict__` pattern.)
- **Rotation convention** (unchanged here, for context): column-vector matrices; world-forward is `GetWorldRotation().GetCol(1)`.
- **Spec:** `docs/superpowers/specs/2026-07-07-static-object-immobility-design.md`.

---

### Task 1: `ShipClass.IsImmobile()` predicate

**Files:**
- Modify: `engine/appc/ships.py` (add method near `IsStationary`/`SetStationary`, currently at `ships.py:585-586`)
- Test: `tests/unit/test_static_object_immobility.py` (create)

**Interfaces:**
- Consumes: existing `ObjectClass.IsStatic()` (`objects.py:474`), `ShipClass.IsStationary()` (`ships.py:585`).
- Produces: `ShipClass.IsImmobile(self) -> bool` — `True` when the ship is flagged static (per-instance `SetStatic`) or stationary (per-class hardpoint `SetStationary`). Consumed by Tasks 2, 3, 4.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_static_object_immobility.py`:

```python
import App
import pytest
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass


def _reset_app_state():
    App.g_kSetManager._sets.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def test_isimmobile_false_by_default():
    assert ShipClass().IsImmobile() is False


def test_isimmobile_true_when_static():
    s = ShipClass()
    s.SetStatic(True)
    assert s.IsImmobile() is True


def test_isimmobile_true_when_stationary():
    s = ShipClass()
    s.SetStationary(1)
    assert s.IsImmobile() is True


def test_isimmobile_true_when_both():
    s = ShipClass()
    s.SetStatic(True)
    s.SetStationary(1)
    assert s.IsImmobile() is True


def test_isimmobile_reverts_when_static_cleared():
    s = ShipClass()
    s.SetStatic(True)
    s.SetStatic(False)
    assert s.IsImmobile() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_static_object_immobility.py -v`
Expected: FAIL — `AttributeError` / the `_Stub` returned by `IsImmobile` is not `False` (method doesn't exist yet).

- [ ] **Step 3: Write minimal implementation**

In `engine/appc/ships.py`, immediately after the `IsStationary`/`SetStationary` pair (around `ships.py:586`), add:

```python
    def IsImmobile(self) -> bool:
        """True when this ship must be treated as a fixed anchor: either the
        mission flagged it per-instance (SetStatic) or the hardpoint flagged
        the class stationary (SetStationary). Honoured by the motion
        integrator, collision response, and collision avoidance so stations /
        drydocks neither drift nor rotate. Both backing flags are set in
        __init__, so these are safe direct calls (no _Stub hazard)."""
        return bool(self.IsStatic()) or bool(self.IsStationary())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_static_object_immobility.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/ships.py tests/unit/test_static_object_immobility.py
git commit -m "feat(physics): ShipClass.IsImmobile() predicate (static or stationary)"
```

---

### Task 2: Motion integrator skips immobile ships

**Files:**
- Modify: `engine/appc/ship_motion.py` — `_step_ship_motion` (currently `ship_motion.py:119`)
- Test: `tests/unit/test_static_object_immobility.py` (append)

**Interfaces:**
- Consumes: `ShipClass.IsImmobile()` (Task 1).
- Produces: no new symbol; behavioural guarantee that `_step_ship_motion(ship, dt)` is a no-op on the transform when `ship.IsImmobile()`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_static_object_immobility.py`:

```python
from engine.appc.objects import PhysicsObjectClass
from engine.appc.ship_motion import _step_ship_motion


def _rot_cols(ship):
    R = ship.GetWorldRotation()
    return [(R.GetCol(i).x, R.GetCol(i).y, R.GetCol(i).z) for i in range(3)]


def test_immobile_ship_does_not_translate_despite_speed_setpoint():
    s = ShipClass()
    s.SetStatic(True)
    s.SetTranslateXYZ(10.0, 20.0, 30.0)
    # A non-zero linear setpoint that would move a mobile ship.
    s.SetSpeed(50.0, TGPoint3(0.0, 1.0, 0.0),
               PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    _step_ship_motion(s, 1.0)
    p = s.GetTranslate()
    assert (p.x, p.y, p.z) == pytest.approx((10.0, 20.0, 30.0))


def test_immobile_ship_does_not_rotate_despite_angular_setpoint():
    s = ShipClass()
    s.SetStationary(1)
    before = _rot_cols(s)
    # A non-zero angular-velocity setpoint that would spin a mobile ship.
    s.SetTargetAngularVelocityDirect(TGPoint3(0.0, 1.0, 0.0))
    _step_ship_motion(s, 1.0)
    assert _rot_cols(s) == pytest.approx(before)


def test_mobile_ship_still_moves_control():
    # Guard: the early-return must not affect ordinary ships.
    s = ShipClass()
    s.SetTranslateXYZ(0.0, 0.0, 0.0)
    s.SetSpeed(50.0, TGPoint3(0.0, 1.0, 0.0),
               PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    _step_ship_motion(s, 1.0)
    p = s.GetTranslate()
    assert (p.x, p.y, p.z) != pytest.approx((0.0, 0.0, 0.0))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_static_object_immobility.py -k immobile_ship -v`
Expected: FAIL — the two `immobile_ship` tests fail (a mobile integrator moves/rotates the ship); `mobile_ship_still_moves_control` passes.

- [ ] **Step 3: Write minimal implementation**

In `engine/appc/ship_motion.py`, at the **very top** of `_step_ship_motion` (before the in-system-warp check at `ship_motion.py:130`), add:

```python
    # An immobile ship (SetStatic / SetStationary) is a fixed anchor: never
    # integrate a translation or rotation, whatever setpoint the Stay AI (or
    # anything else) wrote. Placed first so even a degenerate warp/setpoint
    # state can't move a station.
    if getattr(ship, "IsImmobile", None) is not None and ship.IsImmobile():
        return
```

(The `getattr` guard keeps this safe for any non-`ShipClass` object that could reach the integrator; `iter_ships()` only yields ships, but the guard costs nothing and documents intent.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_static_object_immobility.py -v`
Expected: PASS (all tests, including Task 1's).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/ship_motion.py tests/unit/test_static_object_immobility.py
git commit -m "fix(physics): motion integrator skips immobile ships (no drift/spin)"
```

---

### Task 3: Collision response treats immobile ships as immovable

**Files:**
- Modify: `engine/appc/collisions.py` — `_resolve_body` (currently `collisions.py:71-92`)
- Test: `tests/unit/test_collisions.py` (append)

**Interfaces:**
- Consumes: `ShipClass.IsImmobile()` (Task 1).
- Produces: `_resolve_body(obj)` returns `is_movable=False, inv_mass=0.0, velocity=(0,0,0)` for an immobile `ShipClass` (matching the existing planet branch). A mover colliding with it is de-penetrated/impulsed/damaged; the immobile body is not moved.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_collisions.py` (the module already defines `_ship(x, mass, vx, radius=1.0)` and the `_isolate` fixture):

```python
def test_resolve_body_immobile_ship_is_treated_as_immovable():
    from engine.appc.collisions import _resolve_body
    s = _ship(0.0, 500.0, 7.0, radius=2.0)
    s.SetStatic(True)
    b = _resolve_body(s)
    assert b.is_movable is False
    assert b.inv_mass == 0.0
    assert b.velocity.x == 0.0 and b.velocity.y == 0.0 and b.velocity.z == 0.0


def test_ship_vs_immobile_ship_bounces_mover_leaves_anchor_fixed():
    # Mirror of test_ship_vs_immovable_planet_bounces_planet_fixed, but the
    # fixed body is a SetStatic ship instead of a planet.
    from engine.appc.collisions import _resolve_body, _respond_pair
    anchor = _ship(0.0, 500.0, 0.0, radius=2.0)
    anchor.SetStationary(1)
    mover = _ship(3.0, 100.0, -10.0, radius=2.0)  # approaching along -x
    anchor_pos_before = anchor.GetTranslate()
    _respond_pair(_resolve_body(anchor), _resolve_body(mover))
    # Anchor unmoved (de-penetration only shoves the mover).
    ap = anchor.GetTranslate()
    assert (ap.x, ap.y, ap.z) == pytest.approx(
        (anchor_pos_before.x, anchor_pos_before.y, anchor_pos_before.z))
    # Anchor gains no collision overlay; mover does.
    assert anchor.__dict__.get("_collision_velocity") is None
    assert mover.__dict__.get("_collision_velocity") is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_collisions.py -k immobile -v`
Expected: FAIL — the immobile ship is still `is_movable=True` with non-zero `inv_mass`, and it gets shoved / gains an overlay.

- [ ] **Step 3: Write minimal implementation**

In `engine/appc/collisions.py`, change the movable/immovable branch inside `_resolve_body` (currently:)

```python
    if isinstance(obj, ShipClass):
        m = obj.GetMass()
        if m <= 0.0:
            m = COLLISION_FALLBACK_MASS
        inv_mass = 1.0 / m
        movable = True
        v = obj.GetVelocity()
    else:
        inv_mass = 0.0
        movable = False
        v = TGPoint3(0.0, 0.0, 0.0)
```

to:

```python
    if isinstance(obj, ShipClass) and not obj.IsImmobile():
        m = obj.GetMass()
        if m <= 0.0:
            m = COLLISION_FALLBACK_MASS
        inv_mass = 1.0 / m
        movable = True
        v = obj.GetVelocity()
    else:
        # Planets/moons/suns AND immobile ships (SetStatic / SetStationary):
        # fixed anchors. inv_mass 0 + zero velocity means the mover takes the
        # full de-penetration and impulse, exactly as it does against a planet.
        inv_mass = 0.0
        movable = False
        v = TGPoint3(0.0, 0.0, 0.0)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_collisions.py -v`
Expected: PASS (existing tests + the 2 new ones).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/collisions.py tests/unit/test_collisions.py
git commit -m "fix(physics): immobile ships are immovable in collision response"
```

---

### Task 4: Collision avoidance skips immobile ships

**Files:**
- Modify: `engine/appc/collision_avoidance.py` — `tick_collision_avoidance` (the per-ship loop, currently `collision_avoidance.py:438-443`)
- Test: `tests/unit/test_collision_avoidance.py` (append)

**Interfaces:**
- Consumes: `ShipClass.IsImmobile()` (Task 1).
- Produces: `tick_collision_avoidance` never records avoidance state for, nor steers, an immobile ship (even though it carries an AI).

- [ ] **Step 1: Write the failing test**

First check the top of `tests/unit/test_collision_avoidance.py` for its imports and any set/reset fixture, then append (adjust the reset-fixture name if the file uses a different one — most tests in this repo clear `App.g_kSetManager._sets`):

```python
def test_immobile_ship_with_ai_is_not_steered(monkeypatch):
    import App
    from engine.appc.ships import ShipClass
    from engine.appc import collision_avoidance as ca

    ca.reset_avoidance_state()

    # A stationary ship that (like the E1M1 docks) carries a Stay AI.
    dock = ShipClass()
    dock.SetStationary(1)
    dock.SetRadius(5.0)
    monkeypatch.setattr(dock, "GetAI", lambda: object())  # non-None AI

    # Make iter_collidables yield exactly this dock.
    monkeypatch.setattr(ca, "iter_collidables", lambda: iter([dock]))

    # If avoidance tried to steer it, it would call TestCourseOverride.
    called = []
    monkeypatch.setattr(ca, "_test_course_override",
                        lambda *a, **k: called.append(1) or (None, None))

    ca.tick_collision_avoidance(1.0 / 60.0)

    assert called == []                      # never evaluated
    assert ca.is_overriding(dock) is False   # no state recorded
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_collision_avoidance.py -k immobile -v`
Expected: FAIL — `_test_course_override` is called for the dock (`called == [1]`).

- [ ] **Step 3: Write minimal implementation**

In `engine/appc/collision_avoidance.py`, inside the `for obj in iter_collidables():` loop in `tick_collision_avoidance`, right after the existing AI gate (`collision_avoidance.py:441-442`):

```python
        if obj.GetAI() is None:        # player / uncontrolled: never auto-steer
            continue
```

add:

```python
        if obj.IsImmobile():           # stations/drydocks: anchored, never steered
            continue
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_collision_avoidance.py -v`
Expected: PASS (existing tests + the new one).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/collision_avoidance.py tests/unit/test_collision_avoidance.py
git commit -m "fix(physics): collision avoidance skips immobile ships"
```

---

### Task 5: `EnableCollisionsWith` per-pair primitive + read helper

**Files:**
- Modify: `engine/appc/objects.py` — add `EnableCollisionsWith` to `DamageableObject`, near `SetCollisionsOn`/`CanCollide` (currently `objects.py:601-614`)
- Modify: `engine/appc/collisions.py` — add module-level read helper `_collision_disabled_ids`
- Test: `tests/unit/test_collisions.py` (append)

**Interfaces:**
- Consumes: `TGObject.GetObjID()` (`engine/core/ids.py:103`) — stable per-object id.
- Produces:
  - `DamageableObject.EnableCollisionsWith(self, pOther, bOn) -> None` — `bOn` falsy disables collisions between `self` and `pOther` (stores `pOther.GetObjID()` in `self._collision_disabled_ids`); `bOn` truthy re-enables (removes it). Idempotent.
  - `collisions._collision_disabled_ids(obj) -> set|frozenset` — the object's disabled-peer id set, or an empty set if never set (`__dict__`-safe). Consumed by Task 6.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_collisions.py`:

```python
def test_enable_collisions_with_disables_and_reenables_pair():
    from engine.appc.collisions import _collision_disabled_ids
    a = _ship(0.0, 100.0, 0.0)
    b = _ship(1.0, 100.0, 0.0)

    # Fresh objects: empty disabled set, safe against the _Stub trap.
    assert _collision_disabled_ids(a) == set()

    a.EnableCollisionsWith(b, 0)          # disable a<->b
    assert b.GetObjID() in _collision_disabled_ids(a)

    a.EnableCollisionsWith(b, 1)          # re-enable
    assert b.GetObjID() not in _collision_disabled_ids(a)


def test_enable_collisions_with_is_idempotent():
    from engine.appc.collisions import _collision_disabled_ids
    a = _ship(0.0, 100.0, 0.0)
    b = _ship(1.0, 100.0, 0.0)
    a.EnableCollisionsWith(b, 0)
    a.EnableCollisionsWith(b, 0)          # twice
    assert len(_collision_disabled_ids(a)) == 1
    a.EnableCollisionsWith(b, 1)
    a.EnableCollisionsWith(b, 1)          # remove twice: no error
    assert _collision_disabled_ids(a) == set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_collisions.py -k enable_collisions -v`
Expected: FAIL — `ImportError` for `_collision_disabled_ids` (helper not defined). `EnableCollisionsWith` itself currently no-ops via `_Stub` but the helper import fails first.

- [ ] **Step 3: Write minimal implementation**

In `engine/appc/objects.py`, in `DamageableObject`, after `CanCollide` (around `objects.py:614`):

```python
    def EnableCollisionsWith(self, pOther, bOn) -> None:
        """SDK ``DamageableObject_EnableCollisionsWith`` (App.py:5355): toggle
        collision detection between THIS object and one specific other object,
        independent of the global SetCollisionsOn flag. E1M1 uses it to stop
        the docked player colliding with its drydock
        (``pDryDock.EnableCollisionsWith(pPlayer, 0)``), re-enabling after the
        undock cutscene. Stores the peer's stable ObjID; honoured by
        ``engine.appc.collisions.resolve_collisions`` (symmetric skip).
        """
        ids = self.__dict__.setdefault("_collision_disabled_ids", set())
        oid = pOther.GetObjID()
        if bOn:
            ids.discard(oid)   # re-enable this pair
        else:
            ids.add(oid)       # disable this pair
```

In `engine/appc/collisions.py`, add near the other `__dict__`-safe readers (after `_collisions_enabled`, around `collisions.py:60`):

```python
def _collision_disabled_ids(obj):
    """The set of peer ObjIDs this object has disabled collisions with via
    DamageableObject.EnableCollisionsWith, or an empty set. obj.__dict__ lookup
    (not getattr) to dodge TGObject.__getattr__'s truthy _Stub."""
    return obj.__dict__.get("_collision_disabled_ids", _EMPTY_DISABLED)


_EMPTY_DISABLED = frozenset()
```

(Define `_EMPTY_DISABLED` once at module scope; returning a shared frozenset avoids allocating a set per non-disabled object per frame. Place the constant above the function if your linter requires definition-before-use — either order works at runtime since the function body resolves it lazily.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_collisions.py -k enable_collisions -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/objects.py engine/appc/collisions.py tests/unit/test_collisions.py
git commit -m "feat(physics): implement per-pair DamageableObject.EnableCollisionsWith"
```

---

### Task 6: `resolve_collisions` skips disabled pairs (symmetric)

**Files:**
- Modify: `engine/appc/collisions.py` — `resolve_collisions` (currently `collisions.py:253-266`)
- Test: `tests/unit/test_collisions.py` (append)

**Interfaces:**
- Consumes: `_collision_disabled_ids(obj)` (Task 5).
- Produces: `resolve_collisions(objects, ...)` skips any pair where either object has disabled the other's ObjID — no impulse, de-penetration, damage, or returned hit for that pair. All other pairs behave exactly as before.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_collisions.py`:

```python
def test_resolve_collisions_skips_disabled_pair_either_direction():
    from engine.appc.collisions import resolve_collisions
    # Two overlapping, approaching ships that WOULD collide.
    a = _ship(0.0, 100.0, +10.0, radius=2.0)
    b = _ship(1.5, 100.0, -10.0, radius=2.0)

    # Disable from a's side only; skip must still be symmetric.
    a.EnableCollisionsWith(b, 0)
    hits = resolve_collisions([a, b])
    assert hits == []
    assert a.__dict__.get("_collision_velocity") is None
    assert b.__dict__.get("_collision_velocity") is None


def test_resolve_collisions_disabled_pair_leaves_other_pairs_colliding():
    from engine.appc.collisions import resolve_collisions
    # radius 2 each: boundary 0.8*(2+2)=3.2. Positions 0/1.6/3.2 make a-b and
    # b-c overlap (dist 1.6 < 3.2) while a-c sits exactly on the boundary
    # (dist 3.2, excluded), so only the two adjacent pairs are candidates.
    # Velocities a:+10, b:0, c:-10 make BOTH adjacent pairs approaching.
    a = _ship(0.0, 100.0, +10.0, radius=2.0)
    b = _ship(1.6, 100.0, 0.0, radius=2.0)
    c = _ship(3.2, 100.0, -10.0, radius=2.0)
    a.EnableCollisionsWith(b, 0)               # only a<->b disabled
    hits = resolve_collisions([a, b, c])
    pairs = {frozenset((id(x), id(y))) for (x, y, *_rest) in hits}
    assert frozenset((id(a), id(b))) not in pairs   # skipped
    assert frozenset((id(b), id(c))) in pairs        # still collides
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_collisions.py -k "disabled_pair" -v`
Expected: FAIL — the a↔b pair still collides (non-empty hits / overlays set).

- [ ] **Step 3: Write minimal implementation**

In `engine/appc/collisions.py`, in `resolve_collisions`, change the inner pair loop (currently:)

```python
    for i in range(len(bodies)):
        for k in range(i + 1, len(bodies)):
            hit = _respond_pair(bodies[i], bodies[k], ship_instances)
            if hit is not None:
                hits.append(hit)
```

to:

```python
    for i in range(len(bodies)):
        for k in range(i + 1, len(bodies)):
            a_obj, b_obj = bodies[i].obj, bodies[k].obj
            # Per-pair mask (DamageableObject.EnableCollisionsWith). Symmetric:
            # either side disabling the other exempts the pair.
            if (b_obj.GetObjID() in _collision_disabled_ids(a_obj)
                    or a_obj.GetObjID() in _collision_disabled_ids(b_obj)):
                continue
            hit = _respond_pair(bodies[i], bodies[k], ship_instances)
            if hit is not None:
                hits.append(hit)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_collisions.py -v`
Expected: PASS (all collision tests).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/collisions.py tests/unit/test_collisions.py
git commit -m "fix(physics): resolve_collisions honours per-pair EnableCollisionsWith"
```

---

### Task 7: E1M1 dock-cluster integration test (the repro)

**Files:**
- Test: `tests/integration/test_e1m1_dock_immobility.py` (create)

**Interfaces:**
- Consumes: everything from Tasks 1-6 (`IsImmobile`, motion skip, immovable collision, `EnableCollisionsWith`, pair skip).
- Produces: a regression test reproducing the bug's geometry — immobile docks stay put, the co-located player is not shoved out of its (collision-disabled) drydock.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_e1m1_dock_immobility.py`:

```python
"""Regression: E1M1 spacedock must hold station at bridge-load.

Reproduces the reported bug geometry: the player spawns at "DryDock Start",
co-located with the first Dry Dock (collisions between them disabled by the
mission), while nearby static docks must not drift/rotate even when a moving
object touches them. See docs/superpowers/specs/2026-07-07-static-object-
immobility-design.md.
"""
import App
import pytest
from engine.appc.math import TGPoint3
from engine.appc.objects import PhysicsObjectClass
from engine.appc.ships import ShipClass
from engine.appc.collisions import resolve_collisions
from engine.appc.ship_motion import _step_ship_motion


def _reset_app_state():
    App.g_kSetManager._sets.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _pos(o):
    p = o.GetTranslate()
    return (p.x, p.y, p.z)


def _rot_cols(o):
    R = o.GetWorldRotation()
    return [(R.GetCol(i).x, R.GetCol(i).y, R.GetCol(i).z) for i in range(3)]


def test_static_dock_does_not_move_under_setpoint_or_collision():
    # A static drydock carrying a Stay-style zero setpoint, plus a moving
    # intruder overlapping it.
    dock = ShipClass()
    dock.SetStatic(True)
    dock.SetStationary(1)
    dock.SetTranslateXYZ(0.0, 0.0, 0.0)
    dock.SetRadius(3.0)
    dock.SetMass(300.0)
    dock.SetSpeed(0.0, TGPoint3(0.0, 1.0, 0.0),
                  PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    dock.SetTargetAngularVelocityDirect(TGPoint3(0.0, 0.0, 0.0))

    intruder = ShipClass()
    # Collision boundary is 0.8*(rA+rB) = 0.8*(3+2) = 4.0; place it at 3.0 so
    # dist (3.0) < boundary (4.0) and the pair genuinely overlaps.
    intruder.SetTranslateXYZ(3.0, 0.0, 0.0)
    intruder.SetRadius(2.0)
    intruder.SetMass(100.0)
    intruder.SetVelocity(TGPoint3(-20.0, 0.0, 0.0))  # approaching

    dock_pos, dock_rot = _pos(dock), _rot_cols(dock)

    _step_ship_motion(dock, 1.0)         # integrator must not move it
    resolve_collisions([dock, intruder]) # collision must not move it

    assert _pos(dock) == pytest.approx(dock_pos)
    assert _rot_cols(dock) == pytest.approx(dock_rot)
    # The mover, by contrast, is affected (de-penetrated away from the anchor).
    assert intruder.__dict__.get("_collision_velocity") is not None


def test_docked_player_is_not_shoved_out_of_its_drydock():
    # Player co-located with the first Dry Dock (both at "DryDock Start"),
    # with collisions between them disabled — the mission's setup.
    player = ShipClass()
    player.SetTranslateXYZ(0.0, 0.0, 0.0)
    player.SetRadius(2.0)
    player.SetMass(100.0)
    player.SetVelocity(TGPoint3(0.5, 0.0, 0.0))  # tiny drift, as at undock start

    drydock = ShipClass()
    drydock.SetStatic(True)
    drydock.SetTranslateXYZ(0.2, 0.0, 0.0)  # essentially co-located, overlapping
    drydock.SetRadius(3.0)
    drydock.SetMass(300.0)

    drydock.EnableCollisionsWith(player, 0)  # mission: disable while docked

    player_pos = _pos(player)
    hits = resolve_collisions([player, drydock])

    assert hits == []                         # pair skipped
    assert _pos(player) == pytest.approx(player_pos)   # not de-penetrated out
    assert player.__dict__.get("_collision_velocity") is None
    assert _pos(drydock) == pytest.approx((0.2, 0.0, 0.0))


def test_reenabling_collisions_after_undock_restores_the_bump():
    # After the undock cutscene the mission calls EnableCollisionsWith(player, 1);
    # once clear, the pair collides normally again (proves re-enable works).
    player = ShipClass()
    player.SetTranslateXYZ(0.0, 0.0, 0.0)
    player.SetRadius(2.0)
    player.SetMass(100.0)
    player.SetVelocity(TGPoint3(10.0, 0.0, 0.0))  # moving toward the dock

    drydock = ShipClass()   # NOT static here: we assert the pair is live again
    drydock.SetTranslateXYZ(1.5, 0.0, 0.0)
    drydock.SetRadius(2.0)
    drydock.SetMass(300.0)

    drydock.EnableCollisionsWith(player, 0)
    drydock.EnableCollisionsWith(player, 1)   # re-enabled

    hits = resolve_collisions([player, drydock])
    assert hits != []                          # collides again
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_e1m1_dock_immobility.py -v`
Expected: PASS. This task adds no production code — it is the end-to-end regression, and each mechanism it relies on was already proven RED→GREEN in Tasks 1-6, so it should pass on first run. If any assertion fails, stop and diagnose: an interaction between the landed changes is the likely cause, and the failing assertion localises which one.

- [ ] **Step 3: (no implementation)**

No production code changes. If a test fails, return to the relevant task (1-6) and fix there, with its own failing unit test first.

- [ ] **Step 4: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: exits 0, or names only failures already listed in `tests/known_failures.txt`. Any other failure is a regression introduced here — fix it before committing.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_e1m1_dock_immobility.py
git commit -m "test(physics): E1M1 dock-cluster immobility regression"
```

---

## Self-Review notes (author)

- **Spec coverage:** A1 (collision immovable) → Task 3; A2 (motion skip) → Task 2; A3 (avoidance skip) → Task 4; predicate → Task 1; B1 (`EnableCollisionsWith` + read helper) → Task 5; B2 (pair skip) → Task 6; E1M1 integration repro → Task 7. Live in-game verification (spec §"Live in-game verification") is manual, done after the plan lands.
- **Deviation from spec (intentional):** the spec placed the A2 guard "after the in-system-warp check"; the plan places it at the very top of `_step_ship_motion` — a strict superset (an anchor never moves, even in a degenerate warp/setpoint state). No behavioural downside for real data (docks never warp).
- **Out of scope (unchanged):** rotational-inertia physics, save/load persistence of the flags/ids, huge-mass-threshold immobility — all deferred per the spec.
- **Type consistency:** `IsImmobile()` (Task 1) used verbatim in Tasks 2-4; `_collision_disabled_ids` (Task 5) consumed in Task 6; `EnableCollisionsWith(pOther, bOn)` signature stable across Tasks 5-7.
