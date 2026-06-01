# Subsystem Damage Propagation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make weapon hits damage real subsystems and surface that damage on the ShipDisplay panel, by replacing the degenerate `pick_target_subsystem` with a body-frame proximity walk and adding parent-aggregator predicates on `WeaponSystem`.

**Architecture:** Two narrow code changes — (1) rewrite `pick_target_subsystem` in `engine/appc/combat.py` to walk `ship.GetSubsystems()` plus each weapon system's `_children`, comparing body-frame distances against per-subsystem `2 × radius` gates, with hull as the fallback; (2) override `IsDamaged`/`IsDisabled`/`IsDestroyed` on the `WeaponSystem` base class so the four weapon-system subclasses surface their children's aggregated state. Three new test files cover the picker, the aggregation, and end-to-end ShipDisplay snapshot behaviour.

**Tech Stack:** Python 3 (engine layer), `pytest` (focused subsets only — never the full suite, per CLAUDE.md memory), `TGPoint3`/`TGMatrix3` math via `engine.appc.math`. Column-vector rotation convention throughout.

**Spec:** [docs/superpowers/specs/2026-06-01-subsystem-damage-propagation-design.md](../specs/2026-06-01-subsystem-damage-propagation-design.md)
**Roadmap:** [docs/superpowers/specs/2026-06-01-combat-damage-pipeline-design.md](../specs/2026-06-01-combat-damage-pipeline-design.md)
**Branch:** `feature/subsystem-damage-propagation` (already created off `main`; spec committed at HEAD).

---

## Background facts the implementer needs

- **Column-vector convention (CLAUDE.md).** `R = obj.GetWorldRotation()` is a `TGMatrix3` whose **columns** are the body axes in world space. `R.GetCol(0)` = body-right, `R.GetCol(1)` = body-forward, `R.GetCol(2)` = body-up. To convert a world-space delta to body frame, project onto each column: `dx_body = dot(delta_world, R.GetCol(0))`, etc. This is equivalent to `Rᵀ · delta_world` for orthonormal `R`. **Never use `GetRow(*)`** when reading rotation — that's the regression pattern unified away in branch `worktree-matrix-convention-unify`.
- **`TGPoint3` API.** Fields: `.x`, `.y`, `.z` (read/write floats). Constructor: `TGPoint3(x, y, z)`. There is no `dot()` helper — compute `dx*dx + dy*dy + dz*dz` inline. See [engine/appc/math.py](../../../engine/appc/math.py).
- **Subsystem body-frame position.** Each `ShipSubsystem` carries `self._position: TGPoint3` set during hardpoint Pass 4 of `ShipClass.SetupProperties` ([engine/appc/ships.py:778-861](../../../engine/appc/ships.py#L778-L861)). Read via `sub.GetPosition()` ([engine/appc/subsystems.py:506-507](../../../engine/appc/subsystems.py#L506-L507)).
- **Subsystem radius.** `sub.GetRadius()` returns `self._radius` ([engine/appc/subsystems.py:497-498](../../../engine/appc/subsystems.py#L497-L498)).
- **Top-level subsystem walk.** `ship.GetSubsystems()` returns the canonical list of non-None top-level subsystems: Sensors, ImpulseEngine, WarpEngine, Torpedo, Phaser, PulseWeapon, TractorBeam, Shield, Power, Repair, Hull ([engine/appc/ships.py:544-564](../../../engine/appc/ships.py#L544-L564)).
- **Hardpoint children.** Each weapon-system parent has `_children: list[ShipSubsystem]` populated by `parent.AddChildSubsystem(child)` in hardpoint Pass 4. PhaserBank under `_phaser_system`, TorpedoTube under `_torpedo_system`, PulseWeapon under `_pulse_weapon_system`, TractorBeam under `_tractor_beam_system`.
- **`WeaponSystem` base class.** Defined at [engine/appc/subsystems.py:796](../../../engine/appc/subsystems.py#L796). Inherits `ShipSubsystem`'s condition-derived `IsDamaged`/`IsDisabled`/`IsDestroyed` ([engine/appc/subsystems.py:714-752](../../../engine/appc/subsystems.py#L714-L752)). Four subclasses: `TorpedoSystem` (908), `PhaserSystem` (949), `PulseWeaponSystem` (1062), `TractorBeamSystem` (1066).
- **`apply_hit` path (no change needed).** `apply_hit` at [engine/appc/combat.py:162-205](../../../engine/appc/combat.py#L162-L205) calls `ship.DamageSystem(subsystem, absorb)`. `DamageableObject.DamageSystem` accepts any subsystem reference and decrements its `_condition`; it's already child-aware via `SetCondition` ([engine/appc/objects.py:357-373](../../../engine/appc/objects.py#L357-L373)).
- **ShipDisplay consumer.** `_damage_states` at [engine/ui/ship_display_panel.py:388-404](../../../engine/ui/ship_display_panel.py#L388-L404) walks `_DAMAGE_SUBSYSTEMS = (("Engines", "GetImpulseEngineSubsystem"), ("Weapons", "GetPhaserSystem"), ("Sensors", "GetSensorSubsystem"), ("Shield Generator", "GetShieldSubsystem"))`. Calls `IsDestroyed`/`IsDisabled`/`IsDamaged` in that priority order via `_subsystem_state`. Damaged → "damaged"; below disabled threshold → "disabled"; condition 0 → "destroyed".
- **Galaxy headless spawn.** `loadspacehelper.CreateShip("Galaxy", None, "player", None, 0, 0)` builds a fully-configured Galaxy through Pass 1-4. Pattern verified by `test_loadspacehelper_create_galaxy_populates_player_impulse_max_speed` at [tests/unit/test_ship_setup_properties.py:225-243](../../../tests/unit/test_ship_setup_properties.py#L225-L243).
- **Pytest runner.** Always use focused subsets: `uv run pytest tests/unit/foo.py tests/integration/bar.py -v`. Never `uv run pytest` (the full suite OOMs the host, per CLAUDE.md memory).
- **Legacy fakes.** The existing test file [tests/unit/test_pick_target_subsystem.py](../../../tests/unit/test_pick_target_subsystem.py) uses a `_FakeShip` that exposes `GetChildSubsystem(i)` / `GetNumChildSubsystems()` but NOT `GetSubsystems()` or `GetWorldRotation()`. The new picker keeps them green via the §3.6 fallback in the spec — see Task 1 Step 3 below.

---

## File map

**Modified:**
- [engine/appc/combat.py](../../../engine/appc/combat.py) — add `_body_frame_delta` helper, rewrite `pick_target_subsystem`.
- [engine/appc/subsystems.py](../../../engine/appc/subsystems.py) — add three predicate overrides on `WeaponSystem`.

**Added:**
- `tests/unit/test_pick_target_subsystem_production.py` — six picker tests against real `ShipClass` and subsystem instances.
- `tests/unit/test_weapon_system_aggregation.py` — predicate aggregation tests parametrised across the four subclasses.
- `tests/integration/test_ship_display_weapons_damage.py` — Galaxy-built end-to-end through the ShipDisplay snapshot helper.

**Untouched (explicitly out of scope):**
- `engine/appc/combat.py:_shield_face_from_hit_point` (Project 3)
- `engine/appc/hit_vfx.py` (Project 4)
- `engine/appc/ship_motion.py`, `engine/ui/sensors_panel.py`, `engine/ui/target_list_view.py` (Project 5)
- `engine/host_loop.py:_advance_combat`, `engine/appc/projectiles.py` (Project 1)
- `engine/appc/subsystems.py:ShipSubsystem.GetWorldLocation` (rotation-naive; sidestepped, not fixed)
- `engine/appc/objects.py:DamageableObject.DamageSystem` (already child-aware)

---

## Task 1 — Body-frame `pick_target_subsystem` (TDD, production tests first)

**Files:**
- Test: `tests/unit/test_pick_target_subsystem_production.py` (create)
- Modify: `engine/appc/combat.py` (rewrite `pick_target_subsystem` at lines 98-138; add `_body_frame_delta` helper)

### Step 1.1 — Write the failing production test file

- [ ] Create `tests/unit/test_pick_target_subsystem_production.py` with the following content:

```python
"""Production-path tests for pick_target_subsystem.

These build real ShipClass/WeaponSystem/PhaserBank/Subsystem instances
(no _FakeShip stubs) so they exercise the body-frame transform, the
GetSubsystems + _children walk, and the per-subsystem 2x-radius gate.
The legacy _FakeShip-based tests live in test_pick_target_subsystem.py
and verify the fallback branch.
"""
import math
import pytest

from engine.appc.combat import pick_target_subsystem
from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.ships import ShipClass
from engine.appc.subsystems import (
    HullSubsystem, PhaserBank, PhaserSystem, SensorSubsystem,
)


def _make_subsystem(cls, name, position, radius):
    """Construct a subsystem with body-frame position + radius set
    directly. Bypasses property-driven setup so each test is self-contained."""
    sub = cls(name)
    sub._position = TGPoint3(position[0], position[1], position[2])
    sub._radius = float(radius)
    return sub


def _make_ship(world_pos=(0.0, 0.0, 0.0), rotation=None):
    """Build a bare ShipClass with explicit world position + rotation.

    No SetupProperties pass; the test assembles its own subsystem tree
    via direct slot assignment so each scenario is independent."""
    ship = ShipClass()
    ship.SetWorldLocation(TGPoint3(*world_pos))
    if rotation is not None:
        ship.SetMatrixRotation(rotation)
    return ship


def _attach_hull(ship, radius=5.0):
    hull = _make_subsystem(HullSubsystem, "Hull", (0.0, 0.0, 0.0), radius)
    hull._parent_ship = ship
    ship.SetHull(hull)
    return hull


def _attach_phaser_system_with_bank(ship, bank_position, bank_radius):
    """Mount a PhaserSystem parent with a single PhaserBank child at
    `bank_position` body-frame, radius `bank_radius`. Returns the bank."""
    parent = PhaserSystem("Phasers")
    parent._parent_ship = ship
    parent._position = TGPoint3(0.0, 0.0, 0.0)
    parent._radius = 0.0
    ship._phaser_system = parent
    bank = _make_subsystem(PhaserBank, "BankFL", bank_position, bank_radius)
    parent.AddChildSubsystem(bank)
    return bank


def test_picks_hardpoint_under_weapon_system():
    """Hit near a PhaserBank's body-frame position picks the bank, not
    the parent PhaserSystem, not the hull."""
    ship = _make_ship()
    hull = _attach_hull(ship, radius=5.0)
    bank = _attach_phaser_system_with_bank(ship,
                                           bank_position=(2.0, 0.0, 1.0),
                                           bank_radius=0.5)
    picked = pick_target_subsystem(ship, TGPoint3(2.1, 0.0, 1.0))
    assert picked is bank
    assert picked is not hull


def test_picks_leaf_top_level_subsystem():
    """Hit near the SensorSubsystem's body-frame position picks it."""
    ship = _make_ship()
    _attach_hull(ship, radius=5.0)
    sensor = _make_subsystem(SensorSubsystem, "Sensors", (0.0, 1.5, 0.0), 0.4)
    sensor._parent_ship = ship
    ship._sensor_subsystem = sensor
    picked = pick_target_subsystem(ship, TGPoint3(0.0, 1.55, 0.0))
    assert picked is sensor


def test_falls_back_to_hull_when_no_subsystem_in_range():
    """Hit far from every mounted subsystem returns the hull."""
    ship = _make_ship()
    hull = _attach_hull(ship, radius=5.0)
    _attach_phaser_system_with_bank(ship, bank_position=(2.0, 0.0, 0.0),
                                    bank_radius=0.5)
    picked = pick_target_subsystem(ship, TGPoint3(0.0, 50.0, 0.0))
    assert picked is hull


def test_rotation_invariance():
    """The picker uses the body-frame transform. Rotating the ship 90
    degrees about world-Z moves its body-X axis along world-Y, so a hit
    at world (0, 2.1, 0) should still pick the bank at body (2, 0, 0)."""
    R = TGMatrix3().MakeZRotation(math.pi / 2.0)
    ship = _make_ship(rotation=R)
    _attach_hull(ship, radius=5.0)
    bank = _attach_phaser_system_with_bank(ship,
                                           bank_position=(2.0, 0.0, 0.0),
                                           bank_radius=0.5)
    picked = pick_target_subsystem(ship, TGPoint3(0.0, 2.1, 0.0))
    assert picked is bank


def test_closest_of_two_in_range_wins():
    """Two overlapping in-range hardpoints; the closer one wins."""
    ship = _make_ship()
    _attach_hull(ship, radius=5.0)
    parent = PhaserSystem("Phasers")
    parent._parent_ship = ship
    ship._phaser_system = parent
    near = _make_subsystem(PhaserBank, "Near", (2.0, 0.0, 0.0), 2.0)
    far = _make_subsystem(PhaserBank, "Far", (3.0, 0.0, 0.0), 2.0)
    parent.AddChildSubsystem(near)
    parent.AddChildSubsystem(far)
    picked = pick_target_subsystem(ship, TGPoint3(2.1, 0.0, 0.0))
    assert picked is near


def test_hull_never_iterated_as_candidate():
    """Hull radius is enormous; without hull-exclusion it would swallow
    every hit. The picker must skip hull during the walk and only return
    it as a fallback."""
    ship = _make_ship()
    hull = _attach_hull(ship, radius=100.0)
    bank = _attach_phaser_system_with_bank(ship,
                                           bank_position=(2.0, 0.0, 0.0),
                                           bank_radius=0.5)
    picked = pick_target_subsystem(ship, TGPoint3(2.0, 0.0, 0.0))
    assert picked is bank
    assert picked is not hull
```

### Step 1.2 — Run the new test file and confirm 5 of 6 fail

- [ ] Run: `uv run pytest tests/unit/test_pick_target_subsystem_production.py -v`
- Expected: `test_falls_back_to_hull_when_no_subsystem_in_range` passes (the degenerate picker happens to do the right thing here); the other five fail. The exact failure mode is "hull returned instead of the expected subsystem" because the current picker calls `ship.GetNumChildSubsystems()` which `ShipClass` doesn't define.

### Step 1.3 — Rewrite `pick_target_subsystem` and add the body-frame helper

- [ ] Replace lines 98-138 of [engine/appc/combat.py](../../../engine/appc/combat.py) (the existing `pick_target_subsystem`) with:

```python
def _body_frame_delta(ship, hit_point):
    """Convert ``hit_point - ship.GetWorldLocation()`` into the ship's
    body frame using the column-vector convention from CLAUDE.md.

    ``R = ship.GetWorldRotation()`` stores body axes as columns. To
    express ``delta_world`` in body coordinates we project onto each
    column: ``dx_body = dot(delta_world, R.GetCol(i))``. Equivalent to
    ``R.transpose() * delta_world`` for orthonormal R.

    Returns ``(dx, dy, dz)`` floats. If ``ship`` has no
    ``GetWorldRotation`` method (legacy test fakes), treats R as
    identity so body == world.
    """
    ship_pos = ship.GetWorldLocation()
    dx_w = hit_point.x - ship_pos.x
    dy_w = hit_point.y - ship_pos.y
    dz_w = hit_point.z - ship_pos.z
    if not hasattr(ship, "GetWorldRotation"):
        return (dx_w, dy_w, dz_w)
    R = ship.GetWorldRotation()
    cx = R.GetCol(0)
    cy = R.GetCol(1)
    cz = R.GetCol(2)
    return (
        dx_w * cx.x + dy_w * cx.y + dz_w * cx.z,
        dx_w * cy.x + dy_w * cy.y + dz_w * cy.z,
        dx_w * cz.x + dy_w * cz.y + dz_w * cz.z,
    )


def pick_target_subsystem(ship, hit_point):
    """Return the subsystem closest to ``hit_point`` in the ship's body
    frame, gated by ``d <= 2 * sub.GetRadius()``. Walks every top-level
    subsystem in ``ship.GetSubsystems()`` plus the ``_children`` of each
    weapon-system parent. Hull is excluded from the walk and only
    returned as the fallback when no candidate passes the gate.

    Falls back to ``ship.GetHull()`` if no subsystem is in range, or
    ``None`` if there is no hull either.

    Legacy fixture support: if ``ship`` lacks ``GetSubsystems``, walks
    ``GetChildSubsystem(i)`` for ``i in range(GetNumChildSubsystems())``
    so the pre-existing ``_FakeShip`` tests stay green.
    """
    hull = ship.GetHull() if hasattr(ship, "GetHull") else None

    # Build the candidate list. Hull is never iterated.
    candidates: list = []
    if hasattr(ship, "GetSubsystems"):
        for s in ship.GetSubsystems():
            if s is None or s is hull:
                continue
            candidates.append(s)
            # Hardpoint children mounted under weapon-system parents.
            children = getattr(s, "_children", None)
            if children:
                candidates.extend(children)
    else:
        # Legacy fallback for _FakeShip-style stubs.
        n = ship.GetNumChildSubsystems() if hasattr(ship, "GetNumChildSubsystems") else 0
        for i in range(n):
            s = ship.GetChildSubsystem(i)
            if s is not None and s is not hull:
                candidates.append(s)

    bx, by, bz = _body_frame_delta(ship, hit_point)

    best = None
    best_dist_sq = float("inf")
    for sub in candidates:
        pos = sub.GetPosition() if hasattr(sub, "GetPosition") else None
        if pos is None:
            continue
        r = sub.GetRadius() if hasattr(sub, "GetRadius") else 0.0
        dx = bx - pos.x
        dy = by - pos.y
        dz = bz - pos.z
        d_sq = dx * dx + dy * dy + dz * dz
        if d_sq > (2.0 * r) ** 2:
            continue
        if d_sq < best_dist_sq:
            best = sub
            best_dist_sq = d_sq
    if best is not None:
        return best
    return hull
```

### Step 1.4 — Re-run the production tests, confirm all six pass

- [ ] Run: `uv run pytest tests/unit/test_pick_target_subsystem_production.py -v`
- Expected: 6 passed.

### Step 1.5 — Run the legacy picker tests and confirm they still pass

- [ ] Run: `uv run pytest tests/unit/test_pick_target_subsystem.py -v`
- Expected: 4 passed (the four pre-existing tests from the file).

### Step 1.6 — Run the broader combat-adjacent test set and confirm no regressions

- [ ] Run: `uv run pytest tests/unit/test_pick_target_subsystem.py tests/unit/test_pick_target_subsystem_production.py tests/integration/test_phaser_damage_applied_through_apply_hit.py -v`
- Expected: All pass. The Project 1 integration tests in particular keep working because `apply_hit` still receives a valid subsystem reference from the rewritten picker (a real subsystem or the hull) and the rest of the routing is unchanged.

### Step 1.7 — Commit

- [ ] Run:

```bash
git add tests/unit/test_pick_target_subsystem_production.py engine/appc/combat.py
git commit -m "$(cat <<'EOF'
feat(combat): pick_target_subsystem walks real subsystems in body frame

Rewrite pick_target_subsystem to iterate ship.GetSubsystems() plus each
weapon-system parent's _children, comparing body-frame distances against
per-subsystem 2x-radius gates. Hull is excluded from the walk and only
returned as the fallback. New _body_frame_delta helper applies the
column-vector convention (R.GetCol(*)) per CLAUDE.md.

Legacy _FakeShip-based unit tests keep passing via a GetChildSubsystem
fallback when the ship has no GetSubsystems method.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2 — Parent-aggregator predicates on `WeaponSystem`

**Files:**
- Test: `tests/unit/test_weapon_system_aggregation.py` (create)
- Modify: `engine/appc/subsystems.py` (add three methods on `WeaponSystem` at ~line 808)

### Step 2.1 — Write the failing aggregation test file

- [ ] Create `tests/unit/test_weapon_system_aggregation.py` with the following content:

```python
"""WeaponSystem parents aggregate their children's damage state.

Locked semantics (combat damage pipeline roadmap):
  IsDamaged   = any(child.IsDamaged()   for child in children)
  IsDisabled  = bool(children) and all(child.IsDisabled()  for child in children)
  IsDestroyed = bool(children) and all(child.IsDestroyed() for child in children)

Empty-children parents report all zeros (no hardpoints == no row).
Run for all four WeaponSystem subclasses to confirm the override on the
base class flows through every concrete weapon system.
"""
import pytest

from engine.appc.subsystems import (
    PhaserBank, PhaserSystem, PulseWeapon, PulseWeaponSystem,
    TorpedoSystem, TorpedoTube, TractorBeam, TractorBeamSystem,
)


# (parent_cls, child_cls) pairs covering every WeaponSystem subclass.
WEAPON_FAMILIES = [
    (PhaserSystem, PhaserBank),
    (TorpedoSystem, TorpedoTube),
    (PulseWeaponSystem, PulseWeapon),
    (TractorBeamSystem, TractorBeam),
]


def _make_child(cls, name, max_condition=100.0, condition=None,
                disabled_percentage=0.25):
    child = cls(name)
    child._max_condition = float(max_condition)
    child._condition = float(condition if condition is not None
                             else max_condition)
    child._disabled_percentage = float(disabled_percentage)
    return child


@pytest.mark.parametrize("parent_cls,child_cls", WEAPON_FAMILIES)
def test_empty_children_all_zero(parent_cls, child_cls):
    parent = parent_cls("Parent")
    assert parent.IsDamaged() == 0
    assert parent.IsDisabled() == 0
    assert parent.IsDestroyed() == 0


@pytest.mark.parametrize("parent_cls,child_cls", WEAPON_FAMILIES)
def test_any_damaged_child_makes_parent_damaged(parent_cls, child_cls):
    parent = parent_cls("Parent")
    parent.AddChildSubsystem(_make_child(child_cls, "A", condition=50.0))
    parent.AddChildSubsystem(_make_child(child_cls, "B", condition=100.0))
    assert parent.IsDamaged() == 1
    assert parent.IsDisabled() == 0
    assert parent.IsDestroyed() == 0


@pytest.mark.parametrize("parent_cls,child_cls", WEAPON_FAMILIES)
def test_all_disabled_children_make_parent_disabled(parent_cls, child_cls):
    parent = parent_cls("Parent")
    # disabled_percentage 0.25 means condition <= 25.0 == disabled.
    parent.AddChildSubsystem(_make_child(child_cls, "A", condition=10.0))
    parent.AddChildSubsystem(_make_child(child_cls, "B", condition=20.0))
    assert parent.IsDisabled() == 1
    assert parent.IsDamaged() == 1
    assert parent.IsDestroyed() == 0
    # Add a healthy sibling: parent flips back to not-disabled.
    parent.AddChildSubsystem(_make_child(child_cls, "C", condition=100.0))
    assert parent.IsDisabled() == 0


@pytest.mark.parametrize("parent_cls,child_cls", WEAPON_FAMILIES)
def test_all_destroyed_children_make_parent_destroyed(parent_cls, child_cls):
    parent = parent_cls("Parent")
    parent.AddChildSubsystem(_make_child(child_cls, "A", condition=0.0))
    parent.AddChildSubsystem(_make_child(child_cls, "B", condition=0.0))
    assert parent.IsDestroyed() == 1
    assert parent.IsDisabled() == 1
    assert parent.IsDamaged() == 1
    # Add a healthy sibling: parent flips back to not-destroyed.
    parent.AddChildSubsystem(_make_child(child_cls, "C", condition=100.0))
    assert parent.IsDestroyed() == 0


@pytest.mark.parametrize("parent_cls,child_cls", WEAPON_FAMILIES)
def test_mixed_damaged_and_destroyed(parent_cls, child_cls):
    parent = parent_cls("Parent")
    parent.AddChildSubsystem(_make_child(child_cls, "A", condition=50.0))  # damaged
    parent.AddChildSubsystem(_make_child(child_cls, "B", condition=0.0))   # destroyed
    assert parent.IsDamaged() == 1
    assert parent.IsDestroyed() == 0   # not ALL destroyed
    assert parent.IsDisabled() == 0    # not ALL disabled
```

### Step 2.2 — Run and confirm every aggregation test fails

- [ ] Run: `uv run pytest tests/unit/test_weapon_system_aggregation.py -v`
- Expected: All 20 tests fail. Failure mode is "parent reports 0 even though children are damaged/disabled/destroyed" — the inherited `ShipSubsystem` predicates look at the parent's own `_condition`, which is never touched.

### Step 2.3 — Add the three predicate overrides on `WeaponSystem`

- [ ] Open [engine/appc/subsystems.py](../../../engine/appc/subsystems.py). Find the `WeaponSystem` class definition at line 796. Locate the end of `__init__` (line ~815, just before `def StartFiring`). Insert the three overrides immediately above `StartFiring`:

```python
    # ── Parent-aggregator predicates ───────────────────────────────────
    # WeaponSystem parents own their hardpoint emitters (PhaserBank,
    # TorpedoTube, PulseWeapon, TractorBeam) as _children. Damage lands
    # on the children via apply_hit -> pick_target_subsystem -> ship.
    # DamageSystem(child); the parent surfaces aggregated state to
    # SDK/UI consumers without storing its own condition pool.
    #
    # Locked semantics from the combat damage pipeline roadmap:
    #   IsDamaged   = any(child.IsDamaged()  for child in children)
    #   IsDisabled  = children and all(child.IsDisabled()  for child in children)
    #   IsDestroyed = children and all(child.IsDestroyed() for child in children)
    #
    # Empty-children edge: a weapon system with no hardpoints reports
    # all zeros (ShipDisplay omits the row).

    def IsDamaged(self) -> int:
        for c in self._children:
            if c.IsDamaged():
                return 1
        return 0

    def IsDisabled(self) -> int:
        if not self._children:
            return 0
        for c in self._children:
            if not c.IsDisabled():
                return 0
        return 1

    def IsDestroyed(self) -> int:
        if not self._children:
            return 0
        for c in self._children:
            if not c.IsDestroyed():
                return 0
        return 1
```

(Plain `for`/`return` loops rather than `any()`/`all()` so a `tests/unit/test_subsystems_isdamaged.py`-style debugger trace shows which child tripped the predicate. Behaviour is identical.)

### Step 2.4 — Re-run the aggregation tests, confirm all pass

- [ ] Run: `uv run pytest tests/unit/test_weapon_system_aggregation.py -v`
- Expected: 20 passed.

### Step 2.5 — Run the existing subsystem tests, confirm no regressions

- [ ] Run: `uv run pytest tests/unit/ -k "subsystem or weapon or phaser or torpedo or pulse or tractor" -v`
- Expected: All pass. Leaf subsystems (`SensorSubsystem`, `ImpulseEngineSubsystem`, `ShieldSubsystem`) keep their inherited `ShipSubsystem` predicates because the override is on `WeaponSystem` only.

### Step 2.6 — Commit

- [ ] Run:

```bash
git add tests/unit/test_weapon_system_aggregation.py engine/appc/subsystems.py
git commit -m "$(cat <<'EOF'
feat(subsystems): WeaponSystem parents aggregate children's damage state

Override IsDamaged/IsDisabled/IsDestroyed on the WeaponSystem base class
so PhaserSystem, TorpedoSystem, PulseWeaponSystem, and TractorBeamSystem
all derive their state from their hardpoint children (PhaserBank,
TorpedoTube, PulseWeapon, TractorBeam). Empty-children parents report
all zeros. Leaf top-level subsystems (Sensors/Engines/Shield) keep their
inherited condition-derived predicates.

This is the structural fix that lets the ShipDisplay Weapons row light
up when phaser hits land on a hardpoint via pick_target_subsystem.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3 — Integration test: ShipDisplay flips the Weapons row

**Files:**
- Test: `tests/integration/test_ship_display_weapons_damage.py` (create)

### Step 3.1 — Write the failing integration test file

- [ ] Create `tests/integration/test_ship_display_weapons_damage.py` with:

```python
"""End-to-end: damage a PhaserBank on a Galaxy, confirm the ShipDisplay
panel's _damage_states tuple includes the Weapons row.

Uses direct DamageSystem calls to seed the bank's condition rather than
running _advance_combat ticks. This isolates the project's actual
change (parent aggregation + picker) from shield-charge tuning and
weapon-timing variance. Visual confirmation of the full firing pipeline
is a manual smoke step documented in the spec.
"""
import App
import loadspacehelper

from engine.ui.ship_display_panel import _damage_states


def _build_galaxy():
    App.g_kSetManager._sets.clear()
    ship = loadspacehelper.CreateShip("Galaxy", None, "player", None, 0, 0)
    assert ship is not None
    return ship


def _phaser_banks(ship):
    parent = ship.GetPhaserSystem()
    assert parent is not None, "Galaxy must have a phaser system"
    banks = list(parent._children)
    assert banks, "Galaxy must have at least one mounted phaser bank"
    return banks


def test_damaging_one_phaser_bank_surfaces_weapons_damaged_row():
    ship = _build_galaxy()
    banks = _phaser_banks(ship)
    target_bank = banks[0]
    # Drop the bank into the damaged band: half of MaxCondition, comfortably
    # above the disabled threshold (default DisabledPercentage 0.25).
    seed = target_bank.GetMaxCondition() * 0.5
    ship.DamageSystem(target_bank, seed)

    phasers = ship.GetPhaserSystem()
    assert phasers.IsDamaged() == 1
    assert phasers.IsDisabled() == 0
    assert phasers.IsDestroyed() == 0

    rows = _damage_states(ship)
    assert ("Weapons", "damaged") in rows


def test_disabling_all_phaser_banks_surfaces_weapons_disabled_row():
    ship = _build_galaxy()
    banks = _phaser_banks(ship)
    # Drive every bank below its disabled threshold.
    for bank in banks:
        threshold = bank.GetMaxCondition() * bank.GetDisabledPercentage()
        # Push to half the disabled threshold so we're firmly below it.
        target_condition = max(0.1, threshold * 0.5)
        damage = bank.GetCondition() - target_condition
        ship.DamageSystem(bank, damage)

    phasers = ship.GetPhaserSystem()
    assert phasers.IsDisabled() == 1
    assert phasers.IsDestroyed() == 0

    rows = _damage_states(ship)
    assert ("Weapons", "disabled") in rows


def test_destroying_all_phaser_banks_surfaces_weapons_destroyed_row():
    ship = _build_galaxy()
    banks = _phaser_banks(ship)
    for bank in banks:
        ship.DamageSystem(bank, bank.GetCondition())

    phasers = ship.GetPhaserSystem()
    assert phasers.IsDestroyed() == 1

    rows = _damage_states(ship)
    assert ("Weapons", "destroyed") in rows
```

### Step 3.2 — Run the integration test and confirm three failures

- [ ] Run: `uv run pytest tests/integration/test_ship_display_weapons_damage.py -v`
- Expected: 3 passed if Tasks 1 and 2 are merged in this branch. (The aggregation predicate from Task 2 and the picker rewrite from Task 1 are the prerequisites; if you've executed the plan in order they're already in place when you reach Task 3.)
- If any test fails here, do NOT skip ahead. Diagnose:
  - "IsDamaged returns 0 after seeding" → check Task 2's override is in `WeaponSystem`, not `ShipSubsystem`.
  - "rows tuple is empty" → confirm `engine/ui/ship_display_panel.py`'s `_DAMAGE_SUBSYSTEMS` still includes `("Weapons", "GetPhaserSystem")`.
  - "Galaxy has no phaser banks" → confirm `ship.GetPhaserSystem()._children` is populated after `loadspacehelper.CreateShip`; if not, Pass 4 of `SetupProperties` may not have run for this fixture.

### Step 3.3 — Commit

- [ ] Run:

```bash
git add tests/integration/test_ship_display_weapons_damage.py
git commit -m "$(cat <<'EOF'
test(ship_display): end-to-end Weapons damage row populates on bank hits

New integration test spawns a headless Galaxy via loadspacehelper,
seeds damage directly into individual PhaserBank instances via
ship.DamageSystem, then asserts the ShipDisplay _damage_states snapshot
flips the Weapons row to damaged / disabled / destroyed in the three
seeded scenarios. Direct DamageSystem seeding isolates the structural
change (picker + WeaponSystem aggregation) from shield-charge tuning.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4 — Cross-cutting verification

**Files:** none modified.

### Step 4.1 — Run the focused test bundle covering everything this branch touches

- [ ] Run:

```
uv run pytest \
  tests/unit/test_pick_target_subsystem.py \
  tests/unit/test_pick_target_subsystem_production.py \
  tests/unit/test_weapon_system_aggregation.py \
  tests/integration/test_ship_display_weapons_damage.py \
  tests/integration/test_phaser_damage_applied_through_apply_hit.py \
  tests/unit/test_subsystems_isdamaged.py \
  tests/unit/test_subsystems_isdisabled.py \
  tests/unit/test_subsystems_isdestroyed.py \
  -v
```

(Skip any of the last three filenames if they don't exist — they're the existing leaf-predicate test files and may have different names; verify with `ls tests/unit/ | grep -i 'is_\(damaged\|disabled\|destroyed\)'` first.)

- Expected: all pass. If any leaf-predicate test fails, the override on `WeaponSystem` has bled onto `ShipSubsystem` somehow — re-verify Task 2 Step 2.3 inserted the methods inside `class WeaponSystem`, not above it.

### Step 4.2 — Visual smoke (manual, document the result inline)

- [ ] Run:

```bash
cmake -B build -S . && cmake --build build -j
```

- Expected: clean build. Per CLAUDE.md, build only from the project root, never from inside `native/`; binary lives at `build/dauntless`.

- [ ] Run:

```bash
./build/dauntless
```

- [ ] In-game: launch E1M1. Open the ShipDisplay panel for the target. Fire phasers at the target until shields drop on at least one face. Continue firing.
- Expected: the ShipDisplay damage list shows at least one row (Weapons, Engines, Sensors, or Shield Generator) after sustained fire, before the hull breaks. Confirm visually; capture the result as a note in the next commit message (or skip the commit if everything matches and there's no additional change).
- If no rows appear at all: hardpoint radii on Galaxy's PhaserBanks may be ~0, making the 2x-radius gate degenerate. Note this finding in the spec's parking lot (§6) but do NOT introduce a minimum-radius floor in this project — that's the explicit follow-up trigger described in the spec.

### Step 4.3 — Final branch state check

- [ ] Run: `git log --oneline main..HEAD`
- Expected: at least four commits — the spec commit (from the brainstorming phase) plus the three feat/test commits from Tasks 1, 2, 3.

### Step 4.4 — Use the finishing-a-development-branch skill

- [ ] Invoke the `superpowers:finishing-a-development-branch` skill to decide whether to merge directly, open a PR, or hand off for code review. Do not push or merge without going through that flow.

---

## Definition of done (mirrors spec §8)

- `pick_target_subsystem` walks real subsystems by body-frame proximity and returns either a top-level leaf, a hardpoint child, or hull.
- `WeaponSystem` subclasses report aggregated `IsDamaged`/`IsDisabled`/`IsDestroyed` from `_children`.
- All previously-green tests still pass; new tests cover picker behaviour, rotation invariance, parent aggregation, and the end-to-end ShipDisplay-populates scenario.
- Visual smoke: ShipDisplay damage list shows rows for affected systems after sustained fire in E1M1.
