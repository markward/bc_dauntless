# Collision Response Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ships, asteroids, moons, and planets collide — taking speed-dependent impact damage at the contact point (A) and exchanging momentum so velocities/headings change (B) — without any rigid-body physics engine.

**Architecture:** One new module `engine/appc/collisions.py` runs a per-render-frame O(n²) sphere-overlap pass over all collidables. On an *approaching* overlap it injects a mass-weighted impulse into a new decaying per-object `_collision_velocity` overlay (B), de-penetrates positions, and routes KE-based damage through the existing `combat.apply_hit` (A). The overlay is consumed/decayed inside `collisions.py` itself (once per frame, for every collidable) — the kinematic integrators (`ship_motion.py`, `_PlayerControl`) are left byte-identical. One small edit makes `_PlayerControl` write `SetVelocity` so the player's world velocity is authoritative for the collision math.

**Tech Stack:** Python 3, pytest, existing engine math (`engine/appc/math.TGPoint3`), existing `combat.apply_hit` damage path.

**Spec:** `docs/superpowers/specs/2026-06-11-collision-response-design.md`

---

## Deviations from spec (intentional, faithful to intent)

1. **Spec §7 hook location.** The spec put the overlay-consume hook inside both integrators. This plan instead consumes/decays the overlay inside `collisions.py` (`_apply_overlay_all`, top of `tick_collisions`), applied uniformly to every collidable once per frame. Same intent (additive, guarded, byte-identical) but the integrators are untouched and the player-path open question dissolves.
2. **New `_PlayerControl.SetVelocity` writes.** Required plumbing not in the spec: the AI integrator already calls `ship.SetVelocity(...)`, but `_PlayerControl` does not, so `player.GetVelocity()` would be stale. Task 5 makes it authoritative. Pure addition; no behaviour change to motion.

---

## File Structure

| File | Responsibility |
|---|---|
| `engine/appc/collisions.py` (new) | All collision logic: constants, body resolution, pair response, overlay apply/decay, collidable enumeration, `tick_collisions` entry point. |
| `engine/host_loop.py` (modify) | (a) `_PlayerControl` writes `SetVelocity`; (b) one `tick_collisions(...)` call per frame after `_advance_combat`. |
| `tests/unit/test_collisions.py` (new) | Unit tests for every public/helper function. |

---

## Task 1: Module scaffold — constants, body resolution, KE damage helper

**Files:**
- Create: `engine/appc/collisions.py`
- Test: `tests/unit/test_collisions.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_collisions.py`:

```python
import App
import pytest
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass
from engine.appc.planet import Planet_Create


def _reset_app_state():
    App.g_kSetManager._sets.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _ship(x, mass, vx, radius=1.0):
    s = ShipClass()
    s.SetTranslateXYZ(x, 0.0, 0.0)
    s.SetRadius(radius)
    s.SetMass(mass)
    s.SetVelocity(TGPoint3(vx, 0.0, 0.0))
    return s


def test_resolve_body_ship_is_movable_with_inverse_mass():
    from engine.appc.collisions import _resolve_body
    b = _resolve_body(_ship(5.0, 1000.0, 3.0))
    assert b.is_movable is True
    assert b.inv_mass == pytest.approx(1.0 / 1000.0)
    assert b.center.x == pytest.approx(5.0)
    assert b.radius == pytest.approx(1.0)
    assert b.velocity.x == pytest.approx(3.0)


def test_resolve_body_zero_mass_ship_uses_fallback():
    from engine.appc.collisions import _resolve_body, COLLISION_FALLBACK_MASS
    s = ShipClass(); s.SetRadius(1.0)  # mass defaults to 0.0
    b = _resolve_body(s)
    assert b.inv_mass == pytest.approx(1.0 / COLLISION_FALLBACK_MASS)


def test_resolve_body_planet_is_immovable():
    from engine.appc.collisions import _resolve_body
    p = Planet_Create(170.0, "")
    p.SetTranslateXYZ(0.0, 0.0, 0.0)
    b = _resolve_body(p)
    assert b.is_movable is False
    assert b.inv_mass == 0.0
    assert b.velocity.x == 0.0 and b.velocity.y == 0.0 and b.velocity.z == 0.0


def test_resolve_body_includes_collision_overlay_in_velocity():
    from engine.appc.collisions import _resolve_body
    s = _ship(0.0, 1000.0, 2.0)
    s._collision_velocity = TGPoint3(5.0, 0.0, 0.0)
    b = _resolve_body(s)
    assert b.velocity.x == pytest.approx(7.0)  # 2.0 thrust + 5.0 overlay


def test_ke_damage_scales_with_velocity_squared():
    from engine.appc.collisions import _ke_damage
    inv_sum = 1.0 / 500.0  # mu = 500
    d1 = _ke_damage(inv_sum, -10.0)
    d2 = _ke_damage(inv_sum, -20.0)
    assert d2 == pytest.approx(4.0 * d1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_collisions.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.appc.collisions'`.

- [ ] **Step 3: Write minimal implementation**

Create `engine/appc/collisions.py`:

```python
"""Per-frame collision detection + response for ships and space bodies.

Reuses the weapons-system collision/damage primitives: a sphere-overlap
broadphase, combat.apply_hit for impact damage (A), and a mass-weighted
impulse injected into a decaying per-object _collision_velocity overlay (B).
No rigid-body physics engine — the kinematic integrators are untouched; the
overlay is applied and decayed here, once per render frame, for every
collidable.

Spec: docs/superpowers/specs/2026-06-11-collision-response-design.md
"""
import math
from dataclasses import dataclass

from engine.appc.math import TGPoint3

# -- Tuning constants (single home; see spec §9) --
COLLISION_RESTITUTION = 0.2      # bounciness e; mostly inelastic crunch
COLLISION_DAMAGE_COEFF = 1.0     # KE -> hull-damage-points (calibrated in Task 7)
COLLISION_DECAY_TAU = 0.5        # collision-velocity overlay decay time constant (s)
COLLISION_FALLBACK_MASS = 1.0e4  # nominal mass for a ship reporting GetMass()==0


@dataclass
class _Body:
    obj: object
    center: TGPoint3
    radius: float
    inv_mass: float
    is_movable: bool
    velocity: TGPoint3   # world thrust velocity + current overlay


def _overlay_vec(obj):
    """Read-only: the object's collision overlay, or None if never collided."""
    return getattr(obj, "_collision_velocity", None)


def _ensure_overlay(obj):
    """Get-or-create the mutable overlay vector (called only on impulse inject)."""
    cv = getattr(obj, "_collision_velocity", None)
    if cv is None:
        cv = TGPoint3(0.0, 0.0, 0.0)
        obj._collision_velocity = cv
    return cv


def _resolve_body(obj) -> "_Body":
    """Snapshot an object into a _Body. Ships are movable (inverse mass from
    GetMass, fallback when zero); planets/moons/suns are immovable. Velocity
    is the world thrust velocity plus any active collision overlay."""
    from engine.appc.ships import ShipClass
    center = obj.GetWorldLocation()
    radius = obj.GetRadius()
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
    cv = _overlay_vec(obj)
    if cv is not None:
        v = TGPoint3(v.x + cv.x, v.y + cv.y, v.z + cv.z)
    return _Body(obj, center, radius, inv_mass, movable, v)


def _ke_damage(inv_sum: float, v_rel: float) -> float:
    """KE-of-closing-speed damage: COEFF * 0.5 * mu * v_rel**2, mu = 1/inv_sum."""
    mu = 1.0 / inv_sum
    return COLLISION_DAMAGE_COEFF * 0.5 * mu * v_rel * v_rel
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_collisions.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/collisions.py tests/unit/test_collisions.py
git commit -m "feat(collisions): body resolution + KE damage scaffold"
```

---

## Task 2: Pair response — detection, impulse, de-penetration, damage

**Files:**
- Modify: `engine/appc/collisions.py`
- Test: `tests/unit/test_collisions.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_collisions.py`:

```python
def test_symmetric_head_on_equal_opposite_impulse():
    from engine.appc.collisions import _resolve_body, _respond_pair
    a = _ship(0.0, 1000.0, +10.0)
    b = _ship(1.5, 1000.0, -10.0)  # overlapping (dist 1.5 < r 1 + r 1... use radius)
    a.SetRadius(1.0); b.SetRadius(1.0)
    ba, bb = _resolve_body(a), _resolve_body(b)
    hit = _respond_pair(ba, bb, 1.0 / 60.0, host=None, ship_instances=None)
    assert hit is not None
    # Equal masses -> equal & opposite overlays along +/-x.
    assert a._collision_velocity.x == pytest.approx(-b._collision_velocity.x)
    assert a._collision_velocity.x < 0.0   # A (left) pushed further left
    assert b._collision_velocity.x > 0.0   # B (right) pushed further right


def test_mismatched_mass_light_ship_recoils_more():
    from engine.appc.collisions import _resolve_body, _respond_pair
    light = _ship(0.0, 1000.0, +10.0)
    heavy = _ship(1.5, 5000.0, -10.0)
    light.SetRadius(1.0); heavy.SetRadius(1.0)
    _respond_pair(_resolve_body(light), _resolve_body(heavy),
                  1.0 / 60.0, host=None, ship_instances=None)
    assert abs(light._collision_velocity.x) > abs(heavy._collision_velocity.x)


def test_ship_vs_immovable_planet_bounces_planet_fixed():
    from engine.appc.collisions import _resolve_body, _respond_pair
    ship = _ship(0.0, 1000.0, +10.0)
    ship.SetRadius(1.0)
    planet = Planet_Create(2.0, "")
    planet.SetTranslateXYZ(2.5, 0.0, 0.0)  # dist 2.5 < r1 + r2.0 = 3.0
    pre = planet.GetTranslate().x
    _respond_pair(_resolve_body(ship), _resolve_body(planet),
                  1.0 / 60.0, host=None, ship_instances=None)
    assert ship._collision_velocity.x < 0.0          # ship recoils
    assert planet.GetTranslate().x == pytest.approx(pre)  # planet unmoved
    assert _overlay(planet) is None                  # planet got no impulse


def _overlay(obj):
    from engine.appc.collisions import _overlay_vec
    return _overlay_vec(obj)


def test_receding_pair_is_ignored():
    from engine.appc.collisions import _resolve_body, _respond_pair
    a = _ship(0.0, 1000.0, -10.0)   # moving away from b
    b = _ship(1.5, 1000.0, +10.0)
    a.SetRadius(1.0); b.SetRadius(1.0)
    hit = _respond_pair(_resolve_body(a), _resolve_body(b),
                        1.0 / 60.0, host=None, ship_instances=None)
    assert hit is None
    assert _overlay(a) is None and _overlay(b) is None


def test_non_overlapping_pair_is_ignored():
    from engine.appc.collisions import _resolve_body, _respond_pair
    a = _ship(0.0, 1000.0, +10.0)
    b = _ship(50.0, 1000.0, -10.0)  # far apart
    a.SetRadius(1.0); b.SetRadius(1.0)
    assert _respond_pair(_resolve_body(a), _resolve_body(b),
                         1.0 / 60.0, host=None, ship_instances=None) is None


def test_respond_pair_invokes_apply_hit_for_both_ships(monkeypatch):
    import engine.appc.combat as combat
    calls = []
    monkeypatch.setattr(combat, "apply_hit",
                        lambda ship, dmg, *a, **k: calls.append((ship, dmg)))
    from engine.appc.collisions import _resolve_body, _respond_pair
    a = _ship(0.0, 1000.0, +10.0); a.SetRadius(1.0)
    b = _ship(1.5, 1000.0, -10.0); b.SetRadius(1.0)
    _respond_pair(_resolve_body(a), _resolve_body(b),
                  1.0 / 60.0, host=None, ship_instances=None)
    assert len(calls) == 2
    assert {id(a), id(b)} == {id(calls[0][0]), id(calls[1][0])}
    assert all(dmg > 0.0 for _, dmg in calls)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_collisions.py -q`
Expected: FAIL with `ImportError: cannot import name '_respond_pair'`.

- [ ] **Step 3: Write minimal implementation**

Append to `engine/appc/collisions.py`:

```python
def _respond_pair(a: "_Body", b: "_Body", dt: float, host, ship_instances):
    """Resolve one body pair. On an approaching overlap: inject a
    mass-weighted impulse into each movable body's overlay, de-penetrate
    positions, and apply KE damage via combat.apply_hit. Returns the
    (a.obj, b.obj, contact_point, v_rel) tuple if they collided, else None.

    The `v_rel < 0` (approaching) gate is the debounce: once the impulse
    reverses relative velocity, later frames read receding and do nothing
    while the spheres still overlap (spec §5)."""
    dx = b.center.x - a.center.x
    dy = b.center.y - a.center.y
    dz = b.center.z - a.center.z
    dist2 = dx * dx + dy * dy + dz * dz
    sum_r = a.radius + b.radius
    if dist2 >= sum_r * sum_r:
        return None
    dist = math.sqrt(dist2)
    if dist < 1e-9:
        return None  # concentric: degenerate normal, skip
    nx, ny, nz = dx / dist, dy / dist, dz / dist

    # Closing speed along the normal (negative = approaching).
    rvx = b.velocity.x - a.velocity.x
    rvy = b.velocity.y - a.velocity.y
    rvz = b.velocity.z - a.velocity.z
    v_rel = rvx * nx + rvy * ny + rvz * nz
    if v_rel >= 0.0:
        return None  # receding / resting: debounce

    inv_sum = a.inv_mass + b.inv_mass
    if inv_sum <= 0.0:
        return None  # two immovables

    # Mass-weighted impulse magnitude.
    j = -(1.0 + COLLISION_RESTITUTION) * v_rel / inv_sum
    if a.is_movable:
        cva = _ensure_overlay(a.obj)
        cva.x -= j * a.inv_mass * nx
        cva.y -= j * a.inv_mass * ny
        cva.z -= j * a.inv_mass * nz
    if b.is_movable:
        cvb = _ensure_overlay(b.obj)
        cvb.x += j * b.inv_mass * nx
        cvb.y += j * b.inv_mass * ny
        cvb.z += j * b.inv_mass * nz

    # Positional de-penetration, split by inverse mass.
    pen = sum_r - dist
    if a.is_movable:
        s = pen * a.inv_mass / inv_sum
        p = a.obj.GetTranslate()
        a.obj.SetTranslateXYZ(p.x - nx * s, p.y - ny * s, p.z - nz * s)
    if b.is_movable:
        s = pen * b.inv_mass / inv_sum
        p = b.obj.GetTranslate()
        b.obj.SetTranslateXYZ(p.x + nx * s, p.y + ny * s, p.z + nz * s)

    # KE impact damage routed through the existing weapons path.
    from engine.appc.combat import apply_hit
    damage = _ke_damage(inv_sum, v_rel)
    contact = TGPoint3(a.center.x + nx * a.radius,
                       a.center.y + ny * a.radius,
                       a.center.z + nz * a.radius)
    if a.is_movable:
        apply_hit(a.obj, damage, contact, source=b.obj,
                  normal=TGPoint3(nx, ny, nz),
                  host=host, ship_instances=ship_instances, weapon_type=None)
    if b.is_movable:
        apply_hit(b.obj, damage, contact, source=a.obj,
                  normal=TGPoint3(-nx, -ny, -nz),
                  host=host, ship_instances=ship_instances, weapon_type=None)

    return (a.obj, b.obj, contact, v_rel)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_collisions.py -q`
Expected: PASS (11 passed).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/collisions.py tests/unit/test_collisions.py
git commit -m "feat(collisions): mass-weighted pair response + KE damage"
```

---

## Task 3: Frame driver — overlay apply/decay + resolve all pairs

**Files:**
- Modify: `engine/appc/collisions.py`
- Test: `tests/unit/test_collisions.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_collisions.py`:

```python
def test_apply_overlay_moves_and_decays():
    from engine.appc.collisions import _apply_overlay_all, COLLISION_DECAY_TAU
    import math
    s = _ship(0.0, 1000.0, 0.0)
    s._collision_velocity = TGPoint3(6.0, 0.0, 0.0)
    dt = 1.0 / 60.0
    _apply_overlay_all([s], dt)
    assert s.GetTranslate().x == pytest.approx(6.0 * dt)
    assert s._collision_velocity.x == pytest.approx(6.0 * math.exp(-dt / COLLISION_DECAY_TAU))


def test_apply_overlay_skips_objects_without_overlay():
    from engine.appc.collisions import _apply_overlay_all
    s = _ship(3.0, 1000.0, 0.0)
    _apply_overlay_all([s], 1.0 / 60.0)
    assert s.GetTranslate().x == pytest.approx(3.0)        # unmoved
    assert getattr(s, "_collision_velocity", None) is None  # not created


def test_resolve_collisions_returns_one_hit_per_overlapping_pair():
    from engine.appc.collisions import resolve_collisions
    a = _ship(0.0, 1000.0, +10.0); a.SetRadius(1.0)
    b = _ship(1.5, 1000.0, -10.0); b.SetRadius(1.0)
    c = _ship(50.0, 1000.0, 0.0);  c.SetRadius(1.0)  # isolated
    hits = resolve_collisions([a, b, c], 1.0 / 60.0)
    assert len(hits) == 1


def test_overlap_persistence_applies_damage_once(monkeypatch):
    import engine.appc.combat as combat
    calls = []
    monkeypatch.setattr(combat, "apply_hit",
                        lambda *a, **k: calls.append(1))
    from engine.appc.collisions import resolve_collisions
    a = _ship(0.0, 1000.0, +10.0); a.SetRadius(1.0)
    b = _ship(1.5, 1000.0, -10.0); b.SetRadius(1.0)
    resolve_collisions([a, b], 1.0 / 60.0)   # approaching: 2 hits
    n_after_first = len(calls)
    # Still overlapping but now receding (overlays reversed v_rel): no new damage.
    resolve_collisions([a, b], 1.0 / 60.0)
    assert n_after_first == 2
    assert len(calls) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_collisions.py -q`
Expected: FAIL with `ImportError: cannot import name '_apply_overlay_all'`.

- [ ] **Step 3: Write minimal implementation**

Append to `engine/appc/collisions.py`:

```python
def _apply_overlay_all(objects, dt: float) -> None:
    """Consume each object's collision overlay: displace by overlay*dt and
    decay the overlay toward zero. Objects that never collided have no
    _collision_velocity attribute and are skipped (byte-identical)."""
    decay = math.exp(-dt / COLLISION_DECAY_TAU)
    for o in objects:
        cv = getattr(o, "_collision_velocity", None)
        if cv is None or not (cv.x or cv.y or cv.z):
            continue
        p = o.GetTranslate()
        o.SetTranslateXYZ(p.x + cv.x * dt, p.y + cv.y * dt, p.z + cv.z * dt)
        cv.x *= decay
        cv.y *= decay
        cv.z *= decay


def resolve_collisions(objects, dt: float, host=None, ship_instances=None):
    """Snapshot every object into a _Body and resolve all unordered pairs.
    Returns the list of collision tuples from _respond_pair (for tests /
    debugging). De-penetration mutates positions in place; with n small and
    overlaps rare, later pairs reading slightly stale centres self-corrects
    next frame (spec §4)."""
    bodies = [_resolve_body(o) for o in objects]
    hits = []
    for i in range(len(bodies)):
        for k in range(i + 1, len(bodies)):
            hit = _respond_pair(bodies[i], bodies[k], dt, host, ship_instances)
            if hit is not None:
                hits.append(hit)
    return hits
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_collisions.py -q`
Expected: PASS (15 passed).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/collisions.py tests/unit/test_collisions.py
git commit -m "feat(collisions): overlay apply/decay + resolve_collisions driver"
```

---

## Task 4: Collidable enumeration + tick entry point

**Files:**
- Modify: `engine/appc/collisions.py`
- Test: `tests/unit/test_collisions.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_collisions.py`:

```python
def test_iter_collidables_yields_ships_and_planets_only():
    from engine.appc.collisions import iter_collidables
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "test")
    ship = _ship(0.0, 1000.0, 0.0); ship.SetRadius(1.0)
    planet = Planet_Create(170.0, ""); planet.SetTranslateXYZ(500.0, 0.0, 0.0)
    pSet.AddObjectToSet(ship, "Ship")
    pSet.AddObjectToSet(planet, "Planet")
    found = set(id(o) for o in iter_collidables())
    assert id(ship) in found
    assert id(planet) in found


def test_iter_collidables_skips_zero_radius():
    from engine.appc.collisions import iter_collidables
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "test")
    ship = ShipClass()  # radius defaults to 0.0
    pSet.AddObjectToSet(ship, "Ship")
    assert list(iter_collidables()) == []


def test_tick_collisions_resolves_live_set_pair():
    from engine.appc.collisions import tick_collisions
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "test")
    a = _ship(0.0, 1000.0, +10.0); a.SetRadius(1.0)
    b = _ship(1.5, 1000.0, -10.0); b.SetRadius(1.0)
    pSet.AddObjectToSet(a, "A")
    pSet.AddObjectToSet(b, "B")
    hits = tick_collisions(1.0 / 60.0, host=None, ship_instances=None)
    assert len(hits) == 1
    assert a._collision_velocity.x < 0.0 and b._collision_velocity.x > 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_collisions.py -q`
Expected: FAIL with `ImportError: cannot import name 'iter_collidables'`.

- [ ] **Step 3: Write minimal implementation**

Append to `engine/appc/collisions.py`:

```python
def iter_collidables():
    """Yield every collidable across all active sets: ships and asteroids
    (ShipClass) plus planets/moons/suns (Planet). isinstance filtering (not
    hasattr) is required — set membership includes _NamedStub objects whose
    __getattr__ answers True to any hasattr probe (see ship_iter.py)."""
    import App
    from engine.appc.ship_iter import iter_set_objects
    from engine.appc.ships import ShipClass
    from engine.appc.planet import Planet
    for pSet in App.g_kSetManager._sets.values():
        for obj in iter_set_objects(pSet):
            if isinstance(obj, (ShipClass, Planet)) and obj.GetRadius() > 0.0:
                yield obj


def tick_collisions(dt: float, host=None, ship_instances=None):
    """Per-frame entry point: consume overlays for every collidable, then
    detect + resolve all overlapping pairs. Returns the list of collision
    tuples. Call once per render frame after motion + player input have run."""
    objects = list(iter_collidables())
    _apply_overlay_all(objects, dt)
    return resolve_collisions(objects, dt, host=host, ship_instances=ship_instances)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_collisions.py -q`
Expected: PASS (18 passed).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/collisions.py tests/unit/test_collisions.py
git commit -m "feat(collisions): iter_collidables + tick_collisions entry point"
```

---

## Task 5: Make `_PlayerControl` write authoritative world velocity

**Why:** the AI integrator already calls `ship.SetVelocity(...)`, but `_PlayerControl` integrates position without it, so `player.GetVelocity()` is stale. The collision math reads `GetVelocity()` for every body; the player must report its real velocity.

**Files:**
- Modify: `engine/host_loop.py` — `_PlayerControl.apply`, the drift branch (~`engine/host_loop.py:868-871`) and the powered position-integration block (~`engine/host_loop.py:922-930`).
- Test: `tests/unit/test_player_control_velocity.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_player_control_velocity.py`:

```python
"""_PlayerControl.apply must publish the player's world velocity via
SetVelocity so downstream systems (collisions) read an authoritative value."""
import App
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass


class _FakeKeys:
    def __getattr__(self, name):
        return -1  # unique sentinel key codes; never "pressed"/"state"


class _FakeHost:
    keys = _FakeKeys()

    def key_pressed(self, code):
        return False

    def key_state(self, code):
        return False


def _powered_player():
    """Player ship with a populated impulse engine so f > 0 (powered flight)."""
    s = ShipClass()
    s.SetTranslateXYZ(0.0, 0.0, 0.0)
    s.SetRadius(1.0)
    return s


def test_player_control_publishes_velocity_when_moving():
    from engine.host_loop import _PlayerControl
    pc = _PlayerControl()
    player = _powered_player()
    pc._current_speed = 5.0  # already at speed along +Y forward (identity rot)
    pc.apply(player, 1.0 / 60.0, _FakeHost())
    v = player.GetVelocity()
    # Identity rotation -> forward is +Y (GetCol(1)); speed 5 -> v.y == 5.
    assert v.y == 5.0
    assert v.x == 0.0 and v.z == 0.0
```

NOTE for the implementer: if `_PlayerControl.apply` with a bare `ShipClass()`
takes the `f <= 0` drift branch (no impulse engine → `impulse_online_fraction`
may return 0), the published velocity must still be correct — the drift branch
sets `SetVelocity` from `_drift_velocity`. Verify which branch runs by reading
`engine/host_loop.py:851-855`; if the bare ship drifts, set
`pc._drift_velocity = TGPoint3(0.0, 5.0, 0.0)` before `apply` and assert
`v.y == 5.0` instead. Adjust the test to match the branch actually taken — do
not change production code to force a branch.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_player_control_velocity.py -q`
Expected: FAIL — `player.GetVelocity()` returns the zero default (assert on `v.y == 5.0` fails).

- [ ] **Step 3: Write minimal implementation**

In `engine/host_loop.py`, in the **drift branch** of `_PlayerControl.apply`, add a `SetVelocity` before the early `return`. Change:

```python
            d = self._drift_velocity
            p = player.GetTranslate()
            player.SetTranslateXYZ(p.x + d.x * dt, p.y + d.y * dt, p.z + d.z * dt)
            return
```

to:

```python
            d = self._drift_velocity
            p = player.GetTranslate()
            player.SetTranslateXYZ(p.x + d.x * dt, p.y + d.y * dt, p.z + d.z * dt)
            player.SetVelocity(TGPoint3(d.x, d.y, d.z))
            return
```

In the **powered position-integration block**, change:

```python
        # Position integration (powered: velocity follows facing).
        if self._current_speed != 0.0:
            forward = player.GetWorldRotation().GetCol(1)
            p = player.GetTranslate()
            player.SetTranslateXYZ(
                p.x + forward.x * self._current_speed * dt,
                p.y + forward.y * self._current_speed * dt,
                p.z + forward.z * self._current_speed * dt,
            )
```

to:

```python
        # Position integration (powered: velocity follows facing).
        # Publish world velocity unconditionally so GetVelocity() is
        # authoritative for the collision system (zero when stationary).
        forward = player.GetWorldRotation().GetCol(1)
        vx = forward.x * self._current_speed
        vy = forward.y * self._current_speed
        vz = forward.z * self._current_speed
        player.SetVelocity(TGPoint3(vx, vy, vz))
        if self._current_speed != 0.0:
            p = player.GetTranslate()
            player.SetTranslateXYZ(p.x + vx * dt, p.y + vy * dt, p.z + vz * dt)
```

`TGPoint3` is already imported inside `apply` (see `engine/host_loop.py:849`).
The drift branch is earlier in the same method, where `TGPoint3` is also in
scope from that import — if the drift branch precedes the import line, add
`from engine.appc.math import TGPoint3` at the top of the branch, matching the
existing style.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_player_control_velocity.py -q`
Expected: PASS.

- [ ] **Step 5: Regression-check motion is unchanged**

Run: `uv run pytest tests/unit/test_ship_motion_stubs.py tests/unit/test_collisions.py -q`
Expected: PASS (no behavioural regression; SetVelocity is additive).

- [ ] **Step 6: Commit**

```bash
git add engine/host_loop.py tests/unit/test_player_control_velocity.py
git commit -m "feat(host_loop): _PlayerControl publishes authoritative world velocity"
```

---

## Task 6: Wire `tick_collisions` into the per-frame host loop

**Files:**
- Modify: `engine/host_loop.py` — add the call immediately after the `_advance_combat(...)` block (~`engine/host_loop.py:2601-2604`), inside the `if not pause.is_open:` block.

- [ ] **Step 1: Add the call**

After:

```python
                _advance_combat(
                    _all_ships_for_tick(), TICK_DT, host=_h,
                    ship_instances=(session.ship_instances if session is not None else None),
                )
```

add:

```python
                # Collision detection + response (ships/asteroids/moons/
                # planets). Runs once per render frame after motion + player
                # input, so every body's post-thrust position is current.
                # Reuses combat.apply_hit for impact damage; injects a
                # mass-weighted impulse into each body's decaying
                # _collision_velocity overlay. Spec
                # docs/superpowers/specs/2026-06-11-collision-response-design.md.
                from engine.appc import collisions
                collisions.tick_collisions(
                    TICK_DT, host=_h,
                    ship_instances=(session.ship_instances if session is not None else None),
                )
```

- [ ] **Step 2: Verify the module imports cleanly**

Run: `uv run python -c "import engine.host_loop"`
Expected: no output, exit 0 (no import/syntax error).

- [ ] **Step 3: Run the focused suite**

Run: `uv run pytest tests/unit/test_collisions.py tests/unit/test_player_control_velocity.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add engine/host_loop.py
git commit -m "feat(host_loop): drive tick_collisions once per render frame"
```

---

## Task 7: Calibrate `COLLISION_DAMAGE_COEFF` + manual verification

**Files:**
- Modify: `engine/appc/collisions.py` (the constant only)

- [ ] **Step 1: Log a representative ram's KE**

Build (do not commit) a throwaway snippet or use an existing mission to obtain, for two same-class capital ships closing at cruising impulse:
- each ship's real `GetMass()` (populated after `SetupProperties`),
- the cruising impulse speed in GU/s.

Compute `mu = m/2` (equal masses) and `KE = 0.5 * mu * v_rel**2`. Also compute a slow dock-bump case (`v_rel ≈ 0.1` GU/s). Record both KE values.

- [ ] **Step 2: Pick the coefficient**

Find a representative hull strength (`combat`/subsystem hull condition for that ship class). Set `COLLISION_DAMAGE_COEFF` so:
- full-impulse ram damage (`COEFF * KE_ram`) lands in the catastrophic band — multi-hundred hull points, near-fatal for that hull;
- dock-bump damage (`COEFF * KE_bump`) is single-digit / trivial.

Because damage ∝ v², one constant satisfies both. Update the constant in `engine/appc/collisions.py` and the spec §9 table.

- [ ] **Step 3: Confirm unit tests still pass with the new constant**

Run: `uv run pytest tests/unit/test_collisions.py -q`
Expected: PASS. (`test_ke_damage_scales_with_velocity_squared` is ratio-based and constant-agnostic; the others assert signs/structure, not absolute damage — confirm none hard-code the old coefficient.)

- [ ] **Step 4: Manual in-engine verification**

Build and run, then verify the three observable behaviours from the spec:

```bash
cmake --build build -j && ./build/dauntless
```

- Fly the player ship into another ship at speed → both visibly recoil, hull/shield damage + decals/VFX appear at the contact point (your A + B).
- Nudge another ship slowly → minor scrape, little damage.
- Fly into a planet/moon at speed → ship bounces off and takes heavy damage; the body does not move.

Confirm no console errors and that normal flight (no contact) feels identical to before.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/collisions.py docs/superpowers/specs/2026-06-11-collision-response-design.md
git commit -m "tune(collisions): calibrate COLLISION_DAMAGE_COEFF against ground-truth ram"
```

---

## Final verification

- [ ] Run the full focused suite for this feature:

Run: `uv run pytest tests/unit/test_collisions.py tests/unit/test_player_control_velocity.py tests/unit/test_ship_motion_stubs.py -q`
Expected: all PASS.

> ⚠️ Do **not** run the entire `uv run pytest` suite — the full bc_dauntless
> suite OOMs the host (>100 GB RAM). Always use the focused subset above.

- [ ] Confirm the spec's testing matrix (§10) is covered:
  1. Symmetric head-on → `test_symmetric_head_on_equal_opposite_impulse`
  2. Mismatched mass → `test_mismatched_mass_light_ship_recoils_more`
  3. Ship vs immovable → `test_ship_vs_immovable_planet_bounces_planet_fixed`
  4. Glancing low speed → `test_ke_damage_scales_with_velocity_squared`
  5. Overlap persistence → `test_overlap_persistence_applies_damage_once` + `test_receding_pair_is_ignored`
  6. Backward-compat → `test_apply_overlay_skips_objects_without_overlay`
