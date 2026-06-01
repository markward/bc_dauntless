# Rotation-correct shield face mapping — Design

**Status:** drafted, awaiting user review
**Date:** 2026-06-01
**Author:** Mark Ward (with Claude)
**Roadmap:** [`2026-06-01-combat-damage-pipeline-design.md`](./2026-06-01-combat-damage-pipeline-design.md) — Project 3 of 5.
**Prior projects:**
- [`2026-06-01-mesh-accurate-hit-resolution-design.md`](./2026-06-01-mesh-accurate-hit-resolution-design.md) — Project 1, merged. `apply_hit` now receives a real surface point in world space.
- [`2026-06-01-subsystem-damage-propagation-design.md`](./2026-06-01-subsystem-damage-propagation-design.md) — Project 2, merged. Introduced `_body_frame_delta(ship, hit_point)` in `engine/appc/combat.py`.

## 1. Goal

Make `engine.appc.combat._shield_face_from_hit_point` return the correct shield face when the target ship is rotated. The current implementation does dominant-axis selection on the **world-frame** delta `hit_point - ship_pos`, which is only correct when the target has identity rotation. Real targets in E1M1 are constantly yawed and pitched, so they get the wrong face dimmed on hits.

## 2. Problem statement

[engine/appc/combat.py:186-204](../../../engine/appc/combat.py#L186-L204) currently reads `(dx, dy, dz)` from the world-frame delta and picks the face by dominant absolute world axis. The docstring already flags this as future polish. This is that polish.

`_body_frame_delta(ship, hit_point)` was added in Project 2 ([engine/appc/combat.py:98-125](../../../engine/appc/combat.py#L98-L125)) and is already used by `pick_target_subsystem`. It applies the column-vector convention from CLAUDE.md: `dx_body = dot(delta_world, R.GetCol(i))`, with an identity-fallback when the ship lacks `GetWorldRotation` (legacy fixture support). The face mapper should reuse it.

## 3. Design decisions

- **Body-frame delta is computed inside `_shield_face_from_hit_point`.** Same call shape as `pick_target_subsystem`. The duplicate call from `apply_hit` (picker + face mapper) is twelve multiply-adds — dwarfed by the mesh ray-trace in Project 1. Threading a precomputed `(bx, by, bz)` through public signatures would clutter the surface for negligible gain.
- **Function signature unchanged.** `_shield_face_from_hit_point(ship, hit_point) -> int`. Callers in `apply_hit` are untouched.
- **Dominant-axis branch logic preserved verbatim.** Only the source of `(x, y, z)` changes: world → body.
- **Face-to-axis mapping is fixed by the `ShieldSubsystem` class constants** at [engine/appc/subsystems.py:1560-1565](../../../engine/appc/subsystems.py#L1560-L1565):

| Body axis dominance | Face name | Const value | Sign condition |
|---|---|---|---|
| +Y | FRONT_SHIELDS | 0 | `by >= 0` |
| −Y | REAR_SHIELDS | 1 | `by < 0` |
| +Z | TOP_SHIELDS | 2 | `bz >= 0` |
| −Z | BOTTOM_SHIELDS | 3 | `bz < 0` |
| −X | LEFT_SHIELDS | 4 | `bx <= 0` |
| +X | RIGHT_SHIELDS | 5 | `bx > 0` |

Per CLAUDE.md's column-vector convention: `R.GetCol(0)` is ship-right, `R.GetCol(1)` is ship-forward, `R.GetCol(2)` is ship-up. So positive body-X = RIGHT, positive body-Y = FRONT, positive body-Z = TOP. Cross-checked against [sdk/Build/scripts/ships/Hardpoints/galaxy.py](../../../sdk/Build/scripts/ships/Hardpoints/galaxy.py): forward torpedoes at Y=−0.25 are less negative than aft torpedoes at Y=−1.25, confirming forward = body +Y. Dorsal phasers at Z=0.5 vs ventral at Z=0.16 confirm up = body +Z.

- **LEFT/RIGHT sign matches existing behaviour.** The current world-frame implementation returns 4 if `dx <= 0` else 5. The body-frame implementation must return 4 if `bx <= 0` else 5, so LEFT == body −X side and RIGHT == body +X side. No sign flip vs. the current code on the LEFT/RIGHT branch.
- **Legacy fixture compatibility is inherited from `_body_frame_delta`.** When the ship lacks `GetWorldRotation`, `_body_frame_delta` returns the raw world delta. So `_FakeShip` fixtures from earlier tests continue to return the same face indices they always have.
- **Tie-breaking matches existing world-frame code.** The dominant-axis selection uses `>=` to break ties toward Y, then `>=` toward Z. Inside each branch, the sign comparison is `>=` for FRONT/TOP and `<=` for LEFT, so hits exactly on a face boundary (e.g. `(0, 0, 0)`) still resolve to the same index they did before. No change in behaviour at the boundary.

## 4. Implementation sketch

```python
def _shield_face_from_hit_point(ship, hit_point) -> int:
    """Body-frame dominant-axis selection via `_body_frame_delta`.

    FRONT/REAR ↔ ±body-Y, TOP/BOTTOM ↔ ±body-Z, LEFT/RIGHT ↔ ∓body-X,
    per ShieldSubsystem class constants and CLAUDE.md's column-vector
    rotation convention. Legacy fixtures lacking GetWorldRotation get
    identity R from _body_frame_delta and behave as before.
    """
    bx, by, bz = _body_frame_delta(ship, hit_point)
    abs_x, abs_y, abs_z = abs(bx), abs(by), abs(bz)
    if abs_y >= abs_x and abs_y >= abs_z:
        return 0 if by >= 0 else 1
    if abs_z >= abs_x:
        return 2 if bz >= 0 else 3
    return 4 if bx <= 0 else 5
```

## 5. Tests

New file `tests/appc/test_shield_face_from_hit_point.py`. Fixture builds a minimal ship object with:
- `GetWorldLocation()` returning a fixed `TGPoint3` (a non-origin location, to ensure the test exercises the delta and not the raw point).
- `GetWorldRotation()` returning a `TGMatrix3` constructed via `MakeXRotation`, `MakeYRotation`, `MakeZRotation`, or `MakeRotation` — never hand-built.

Cases:

1. **Identity rotation, all six faces.** Regression: hits along ±world-X, ±world-Y, ±world-Z map to the same indices as the prior world-frame implementation.
2. **90° yaw — ship's nose pointing world +X.** R = MakeZRotation(±π/2) (sign chosen so `R.GetCol(1) == (1, 0, 0)` to within tolerance). Hit from world +X → FRONT (0); hit from world −X → REAR (1); hit from world +Z → TOP (2); hit from world +Y → LEFT or RIGHT depending on rotation sign — assert the specific value matching the rotation direction chosen.
3. **90° pitch — ship's nose pitched down so it points world −Z.** R chosen so `R.GetCol(1) == (0, 0, -1)`. Hit from world −Z → FRONT (0); hit from world +Z → REAR (1); hit from world +Y → TOP or BOTTOM depending on pitch direction.
4. **Combined yaw + pitch.** R = MakeRotation or product of two `Make*Rotation`s. World hits chosen so the body-frame projection picks a unique face. Cover all six faces from non-trivial world directions.
5. **Legacy fixture without GetWorldRotation.** Ship object lacking the method returns the same indices as the world-frame implementation (identity fallback path through `_body_frame_delta`).

The existing regression tests in `test_apply_hit_routing.py` and `test_phaser_damage_applied_through_apply_hit.py` use identity-rotation ships and must continue to pass without modification.

## 6. Verification

Test commands (focused subsets — never `uv run pytest` against the whole tree per CLAUDE.md memory):

```bash
uv run pytest tests/appc/test_shield_face_from_hit_point.py -v
uv run pytest tests/appc/test_apply_hit_routing.py tests/integration/test_phaser_damage_applied_through_apply_hit.py -v
```

Visual smoke after green tests:

```bash
cmake -B build -S . && cmake --build build -j
./build/dauntless
```

Load E1M1, fire on a yawed/pitched target (e.g. the Warbird turning), confirm the dimmed shield arc on the target's ShipDisplay tracks the side of the ship taking the hit, independent of which world direction the player is firing from.

## 7. Out of scope

Per the roadmap (sections 4 & 5):
- Damage VFX, audio cues, camera shake — Project 4.
- Subsystem-failure gameplay consequences — Project 5.
- Per-face shield regen rule changes, shield bubble visual updates, shield arc rendering tweaks.
- Any change to `_body_frame_delta` itself or to `pick_target_subsystem`.
- Public API surface of `combat.py` (the helper module name, exported function names, signatures of `apply_hit`, `pick_target_subsystem`, `_shield_face_from_hit_point`).
