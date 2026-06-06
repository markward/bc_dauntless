# Subsystem Damage Propagation — Design

**Status:** drafted, awaiting user review
**Date:** 2026-06-01
**Author:** Mark Ward (with Claude)
**Project:** 2 of 5 in the [Combat Damage Pipeline roadmap](./2026-06-01-combat-damage-pipeline-design.md).
**Upstream dependency:** [Project 1 — Mesh-accurate hit resolution](./2026-06-01-mesh-accurate-hit-resolution-design.md) (complete, merged).

> **Attribution-decision section superseded by [2026-06-06-damage-attribution-design.md](./2026-06-06-damage-attribution-design.md).** The "closest within 2× radius" rule described in this doc is no longer authoritative — spherical-splash with multi-subsystem weighted allocation replaces it. The parent-aggregator predicates (`IsDamaged`, `IsDisabled`, `IsDestroyed` derived from children) defined here remain valid and continue to apply.

## 1. Goal

Make weapon hits actually damage subsystems, so the ShipDisplay panel's Engines / Weapons / Sensors / Shield Generator damage list populates after sustained fire on a target.

Two narrow fixes:

1. Replace [`engine.appc.combat.pick_target_subsystem`](../../../engine/appc/combat.py) so it walks the ship's real subsystem tree by body-frame proximity to the (already mesh-accurate) hit point, instead of degenerating to hull on every call.
2. Add parent-aggregator predicates on `WeaponSystem` so the four weapon-system parents (`PhaserSystem`, `TorpedoSystem`, `PulseWeaponSystem`, `TractorBeamSystem`) report `IsDamaged`/`IsDisabled`/`IsDestroyed` derived from their hardpoint children's state. ShipDisplay then surfaces the damage rows without any panel-side change.

Hit-point input is trusted: Project 1's [`_resolve_hit_point`](../../../engine/appc/combat.py) gives both the torpedo and phaser loops a mesh-accurate world point before they call `apply_hit`. This project consumes that point; it does not re-trace.

## 2. Diagnosis (what's broken today)

- `pick_target_subsystem` calls `ship.GetNumChildSubsystems()` guarded by `hasattr`. `ShipClass` doesn't expose that method (it's only on `ShipSubsystem`), so the guard always falls through, the loop runs zero times, and the function returns `ship.GetHull()` unconditionally. Damage routes shields → hull, skipping every subsystem.
- The four `WeaponSystem` subclasses inherit `ShipSubsystem`'s condition-derived `IsDamaged`/`IsDisabled`/`IsDestroyed`. Because nothing calls `DamageSystem(parent, …)` on a weapon-system parent — only on its hardpoint children — the parent's own `_condition` never decrements, and the predicates stay at 0 even after every child is destroyed. ShipDisplay's Weapons row never lights up.
- `ShipSubsystem.GetWorldLocation()` at [engine/appc/subsystems.py:558-566](../../../engine/appc/subsystems.py#L558-L566) composes `ship_world + subsystem_local` *without* applying ship rotation, so its result is wrong for any rotated ship. This is its own bug; fixing it is not in scope here. The body-frame transform chosen below sidesteps this getter so the bug doesn't contaminate the picker.

## 3. Design decisions

### 3.1 Body-frame proximity for the picker

`pick_target_subsystem(ship, hit_point)` works entirely in the ship's body frame:

1. `delta_world = hit_point − ship.GetWorldLocation()`.
2. `R = ship.GetWorldRotation()` — a column-vector `TGMatrix3` per CLAUDE.md.
3. Project onto each column: `delta_body.x = delta_world · R.GetCol(0)`, `delta_body.y = delta_world · R.GetCol(1)`, `delta_body.z = delta_world · R.GetCol(2)`. This is `Rᵀ · delta_world`, valid because `R` is orthonormal. Never `GetRow(*)` — that was the regression pattern unified away in [`worktree-matrix-convention-unify`](../../../CLAUDE.md).
4. Compare `delta_body` to each subsystem's `sub.GetPosition()` — already body-frame local from hardpoint Pass 4 in [engine/appc/ships.py:778-861](../../../engine/appc/ships.py#L778-L861).

**Why body and not world:** the math is identical for orthonormal `R` (distance is invariant), but body frame lets us read each subsystem's already-stored body-frame `_position` directly without composing it back to world space — which would require either `R · sub._position` per iteration or trusting the rotation-naive `GetWorldLocation()`. Body frame is the cheapest correct path and makes the rotation-invariance unit test trivial to write.

### 3.2 Candidate set: real subsystems + hardpoint children, hull excluded

The candidate list is built once per call:

```
candidates = [s for s in ship.GetSubsystems() if s is not ship.GetHull()]
for s in list(candidates):
    candidates.extend(s._children)   # PhaserBank, TorpedoTube, PulseWeapon, TractorBeam
```

Hull is **never** iterated as a candidate; it is only the fallback when no subsystem passes the range gate. This prevents the hull's giant radius (e.g. Galaxy ≈ 200m) from swallowing every hit by virtue of being central.

### 3.3 Range gate: `d_body ≤ 2 × sub.GetRadius()`

Per-subsystem cutoff. A subsystem is in range only if the squared body-frame distance is within `(2 × sub.GetRadius())²`. Closest in-range candidate wins; ties resolve by iteration order (stable, deterministic).

If no candidate passes the gate, return `ship.GetHull()`. If no hull either, return `None`.

### 3.4 Parent-aggregator predicates on `WeaponSystem`

Override the three predicates on the `WeaponSystem` base class (not a mixin, not per-subclass duplication). All four subclasses inherit automatically. Leaf top-level subsystems (`SensorSubsystem`, `ImpulseEngineSubsystem`, `ShieldSubsystem`) keep their existing condition-derived predicates from `ShipSubsystem`.

Locked semantics (from the roadmap):

```python
def IsDamaged(self) -> int:
    if self._damaged:
        return 1
    return 1 if any(c.IsDamaged() or c.IsDestroyed() for c in self._children) else 0

def IsDisabled(self) -> int:
    return 1 if self._children and all(c.IsDisabled() for c in self._children) else 0

def IsDestroyed(self) -> int:
    if self._destroyed:
        return 1
    return 1 if self._children and all(c.IsDestroyed() for c in self._children) else 0
```

Empty-children edge: a weapon system with no hardpoints reports all zeros. That matches the desired ShipDisplay behaviour (no row for a system that doesn't exist on this hull).

The `or c.IsDestroyed()` term in `IsDamaged` and the `self._damaged` /
`self._destroyed` early returns are corrections to the literal pseudocode
above: `ShipSubsystem.IsDamaged` returns 0 at condition=0, and the
explicit-flag escape hatches inherited from `ShipSubsystem.SetDamaged` /
`SetDestroyed` must still take effect on a parent with children. These
adjustments were discovered during TDD; see the test file at
`tests/unit/test_weapon_system_aggregation.py`.

The parent retains its inherited `_condition`/`_max_condition` storage — we don't remove the fields. That keeps pickling, save/load, and any property-copy code untouched. The overrides simply ignore the parent's own pool in favour of the children's.

### 3.5 Damage routing — no change

`apply_hit` already calls `ship.DamageSystem(subsystem, absorb)` with whatever the picker returns. With a `PhaserBank` returned, `DamageSystem` decrements that child's `_condition` directly. The parent's aggregated predicate flips on the next call. ShipDisplay's `_damage_states` walks `GetPhaserSystem()` and friends and reads the right state for free.

### 3.6 Legacy-fixture fallback in the picker

Existing tests at [tests/unit/test_pick_target_subsystem.py](../../../tests/unit/test_pick_target_subsystem.py) build a `_FakeShip` that exposes `GetChildSubsystem(i)`/`GetNumChildSubsystems()` and no `GetWorldRotation`. The new picker keeps them green:

- If `ship.GetSubsystems` is missing, fall back to the legacy walk over `GetChildSubsystem(i)` indexed by `GetNumChildSubsystems()`.
- If `ship.GetWorldRotation` is missing, treat `R` as identity (body == world).

These guards are bounded to the two methods the legacy fakes don't have. We do not add `try/except` around per-iteration `GetPosition`/`GetRadius` calls — internal-code trust per CLAUDE.md.

## 4. Architecture

### 4.1 Files modified

- [engine/appc/combat.py](../../../engine/appc/combat.py)
  - New private helper `_body_frame_delta(ship, hit_point)` returning a `(dx, dy, dz)` tuple. Identity-rotation fallback when `ship.GetWorldRotation` is absent. This helper is reusable by Project 3's shield-face fix but is not consumed there in this project.
  - Rewrite `pick_target_subsystem` to use the new picker described in §3.
- [engine/appc/subsystems.py](../../../engine/appc/subsystems.py)
  - Add `IsDamaged` / `IsDisabled` / `IsDestroyed` overrides on `class WeaponSystem(PoweredSubsystem)`. Three methods, ~10 lines total with docstrings.

### 4.2 Files added (tests)

- `tests/unit/test_pick_target_subsystem_production.py` — six tests against real `ShipClass`/`WeaponSystem`/`PhaserBank` instances.
- `tests/unit/test_weapon_system_aggregation.py` — predicate tests, parametrised across the four `WeaponSystem` subclasses.
- `tests/integration/test_ship_display_weapons_damage.py` — end-to-end through the ShipDisplay snapshot.

### 4.3 Files explicitly NOT touched

- `_shield_face_from_hit_point` in `combat.py` — still world-axis. **Project 3** fixes it using the same body-frame helper this project introduces.
- `engine/appc/hit_vfx.py` — **Project 4.**
- `engine/appc/ship_motion.py`, `engine/ui/sensors_panel.py`, `engine/ui/target_list_view.py` — **Project 5.**
- `engine/host_loop.py:_advance_combat`, `engine/appc/projectiles.py` — Project 1 already wired the resolved hit point through.
- `ShipSubsystem.GetWorldLocation()` — known rotation-naive; out of scope. Body-frame transform sidesteps it.
- `engine/appc/objects.py:DamageableObject.DamageSystem` — already child-aware via `SetCondition`; no change.

## 5. Tests

All test runs use focused `uv run pytest <files>` — never the full suite (OOMs the host per memory).

### 5.1 Unit — `pick_target_subsystem` (production path)

1. **picks_hardpoint_under_weapon_system** — `PhaserSystem` parent with a `PhaserBank` child at body-frame `(2, 0, 1)` radius `0.5`. Hit world `(2.1, 0, 1)`, identity rotation. Asserts picker returns the `PhaserBank`.
2. **picks_leaf_top_level_subsystem** — hit near `SensorSubsystem`'s body-frame position. Asserts picker returns the sensor.
3. **falls_back_to_hull_when_no_subsystem_in_range** — hit far from every subsystem. Asserts `ship.GetHull()`.
4. **rotation_invariance** — `PhaserBank` at body `(2, 0, 0)` radius `0.5`. Rotate ship 90° about world-Z so body-X points along world-Y. Fire at world `(0, 2.1, 0)`. Asserts the `PhaserBank` is picked. This is the test that proves the body-frame transform.
5. **closest_of_two_in_range_wins** — two overlapping hardpoints, hit closer to one. Asserts the closer one.
6. **hull_never_iterated_as_candidate** — hull radius 100, hardpoint radius 0.5 at body `(2, 0, 0)`. Hit at world `(2.0, 0, 0)`. Asserts hardpoint, not hull.

The four pre-existing legacy tests in [tests/unit/test_pick_target_subsystem.py](../../../tests/unit/test_pick_target_subsystem.py) stay green via the §3.6 fallback.

### 5.2 Unit — parent aggregation

In `tests/unit/test_weapon_system_aggregation.py`, parametrised across `PhaserSystem`, `TorpedoSystem`, `PulseWeaponSystem`, `TractorBeamSystem`:

1. **empty_children_all_zero** — no children. All three predicates return 0.
2. **any_damaged_child_makes_parent_damaged** — one of two children below max. `IsDamaged() == 1`, others 0.
3. **all_disabled_children_make_parent_disabled** — every child below the disabled threshold. `IsDisabled() == 1`. Add a healthy sibling — parent flips back to 0.
4. **all_destroyed_children_make_parent_destroyed** — every child at condition 0. `IsDestroyed() == 1`. Add a healthy sibling — back to 0.
5. **mixed_damaged_and_destroyed** — one damaged, one destroyed. `IsDamaged() == 1`, `IsDestroyed() == 0`, `IsDisabled() == 0`.

### 5.3 Integration — ShipDisplay flips Weapons row

`tests/integration/test_ship_display_weapons_damage.py`:

1. Build a Galaxy headlessly via `loadspacehelper`.
2. Grab the first `PhaserBank` under `ship.GetPhaserSystem()._children`. Read its `_max_condition` and call `ship.DamageSystem(bank, max_condition * 0.5)` to push it into the damaged band.
3. Assert `ship.GetPhaserSystem().IsDamaged() == 1`, `IsDisabled() == 0`, `IsDestroyed() == 0`.
4. Call `_damage_states(ship)` from [engine/ui/ship_display_panel.py](../../../engine/ui/ship_display_panel.py). Assert `("Weapons", "damaged")` is in the result tuple.
5. Drive all banks below the disabled threshold → `("Weapons", "disabled")`. Drive to zero → `("Weapons", "destroyed")`.

Direct `DamageSystem` calls rather than running `_advance_combat` ticks: faster, deterministic, isolates the project's actual change (parent aggregation surfacing through ShipDisplay).

### 5.4 Visual smoke (manual)

```bash
cmake -B build -S . && cmake --build build -j
./build/dauntless
```

Launch E1M1, fire at the target until shields drop on a face, continue firing. Confirm the ShipDisplay damage list shows rows for at least the Weapons row before the hull breaks. Documented in the implementation plan as a step the implementer performs and reports back on.

## 6. Risks & parking lot

- **Hardpoint radii may be small or zero for some emitters.** A `PhaserBank` with `radius = 0` has a zero-area catchment and falls through to hull on every hit. We accept this in v1 — per-class vulnerability tables were rejected by the roadmap and the SDK data is what we get. If smoke surfaces systematic radius-0 hardpoints making the picker useless, revisit with a minimum-radius floor in a follow-up.
- **Empty-children parents report all-zero even if some upstream code damaged the parent's own `_condition` directly.** Aggregation is the locked semantics; this is acceptable.
- **`ShipSubsystem.GetWorldLocation()` remains rotation-naive.** Out of scope; the picker doesn't use it. Future cleanup.
- **`_body_frame_delta` helper is added in `combat.py` but only consumed by the picker.** Project 3's shield-face fix will reuse it. Acceptable — the helper has one clear purpose and is well-named.

## 7. Non-goals

- Re-running the mesh trace inside the picker. The hit point is already resolved upstream; trust the input.
- Fixing the shield-face mapping. **Project 3.**
- Damage VFX, audio cues, camera shake. **Project 4.**
- Subsystem-failure gameplay consequences (disabled engines clamping impulse, disabled weapons gating `StartFiring`, disabled sensors blanking target list, etc.). **Project 5.**
- Per-class hardcoded vulnerability tables. Rejected by the roadmap.
- BVH or any acceleration structure for the picker. The candidate set is small (≲20 subsystems per ship); linear scan is fine.

## 8. Definition of done

- `pick_target_subsystem` walks real subsystems by body-frame proximity and returns either a top-level leaf, a hardpoint child, or hull.
- `WeaponSystem` subclasses report aggregated `IsDamaged`/`IsDisabled`/`IsDestroyed` from their `_children`.
- All previously-green tests still pass; the new unit and integration tests cover picker behaviour, rotation invariance, parent aggregation, and the ShipDisplay-populates scenario.
- Visual smoke: ShipDisplay damage list shows rows for affected systems after sustained fire in E1M1.
