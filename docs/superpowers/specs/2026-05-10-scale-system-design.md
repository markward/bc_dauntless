# Scale System Design

**Date:** 2026-05-10
**Status:** Approved — ready for implementation

## Problem

The renderer currently ignores all Python-defined scale parameters. Every object renders at its NIF authoring size regardless of the radius or scale set in the mission script. This produces two visible errors:

1. **Planets render at NIF native size (~90 units diameter)** instead of their Python-defined radius (e.g. 170 units for Biranu's planet, 4000 for its sun).
2. **Ships render at NIF native size**, which is vastly larger than planets at their correct visual radius — ships appear bigger than planets.

There is no scale component in the world matrices sent to the renderer today. Matrices are pure rotation + translation.

## Chosen Approach: Two named scale tiers, encoded in the world matrix (Phase 1)

Scale is applied entirely on the Python side by building TRS (Translation × Rotation × Scale) matrices before sending them to C++. A 4×4 matrix already encodes uniform scale in its upper-left 3×3; no C++ changes are required.

Two object categories are established now. Their world-matrix builders are intentionally named to match the two-pass rendering architecture deferred to Phase 2.

## Scale Constants (`engine/scale.py`)

```python
SHIP_SCALE               = 0.1   # ship/weapon/hardpoint/shield mesh scale
ASTRO_SCALE              = 10.0  # planet and star position + mesh scale
PLANET_NIF_NATIVE_RADIUS = 45.0  # all planet NIFs are ~90 units diameter
```

These three constants are the single source of truth for all scaling decisions. No other file should hardcode a scale multiplier.

## Object Categories

### Ship-tier

Includes: ships, hardpoints, shield geometry, weapons.

- **Mesh scale:** `SHIP_SCALE` (0.1) applied to the upper-left 3×3 of the world matrix.
- **World position:** unchanged — ships move in raw game units.
- **Camera follow distances** (`CAM_BACK_DIST`, `CAM_UP_DIST`) and fixed camera eye position scale by `SHIP_SCALE`.
- **Note:** hardpoints, shields, and weapons are not yet rendered in Phase 1. When they are, their offsets (expressed in ship-local game units) must be multiplied by `SHIP_SCALE` before use in world-space calculations.

### Astro-tier

Includes: planets, moons, suns.

- **Mesh scale (planets/moons):** `obj.GetRadius() * ASTRO_SCALE / PLANET_NIF_NATIVE_RADIUS` — maps the ~45-unit NIF sphere to the correct visual radius in world space.
- **World position:** multiplied by `ASTRO_SCALE` in the translation column.
- **Sun radius and corona radius** (procedural sphere, no NIF): multiplied by `ASTRO_SCALE` before emission to the renderer.

## World Matrix Builders

The old `_world_matrix_row_major` is replaced by two typed functions in `engine/host_loop.py`.

**Ships** (mesh scaled, position unchanged):
```python
def _ship_world_matrix(ship):
    loc = ship.GetWorldLocation()
    rot = ship.GetWorldRotation()
    s = SHIP_SCALE
    return [
        rot._m[0][0]*s, rot._m[0][1]*s, rot._m[0][2]*s, loc.x,
        rot._m[1][0]*s, rot._m[1][1]*s, rot._m[1][2]*s, loc.y,
        rot._m[2][0]*s, rot._m[2][1]*s, rot._m[2][2]*s, loc.z,
        0.0,            0.0,            0.0,            1.0,
    ]
```

**Planets and moons** (mesh and position both scaled):
```python
def _astro_world_matrix(obj):
    loc = obj.GetWorldLocation()
    rot = obj.GetWorldRotation()
    s = obj.GetRadius() * ASTRO_SCALE / PLANET_NIF_NATIVE_RADIUS
    return [
        rot._m[0][0]*s, rot._m[0][1]*s, rot._m[0][2]*s, loc.x * ASTRO_SCALE,
        rot._m[1][0]*s, rot._m[1][1]*s, rot._m[1][2]*s, loc.y * ASTRO_SCALE,
        rot._m[2][0]*s, rot._m[2][1]*s, rot._m[2][2]*s, loc.z * ASTRO_SCALE,
        0.0,            0.0,            0.0,            1.0,
    ]
```

## Camera Changes

| Parameter | Before | After | Reason |
|-----------|--------|-------|--------|
| `CAM_BACK_DIST` | 600 | `600 * SHIP_SCALE` = 60 | Follow ship at correct visual distance |
| `CAM_UP_DIST` | 200 | `200 * SHIP_SCALE` = 20 | Match ship visual height |
| Fixed eye Z | 1500 | `1500 * SHIP_SCALE` = 150 | Match ship visual size |
| Far clip | 100,000 | 2,000,000 | Accommodate astro positions (sun at ~600k units) |
| Near clip | 1.0 | 1.0 | Unchanged; adequate for ship-scale features |

## Affected Files

| File | Change |
|------|--------|
| `engine/scale.py` | **New** — three scale constants |
| `engine/host_loop.py` | Replace `_world_matrix_row_major` with `_ship_world_matrix` and `_astro_world_matrix`; update camera constants; update sun position/radius emission |

No C++ changes. The renderer already accepts a 4×4 matrix; encoding scale there is sufficient.

---

## Deferred Work: Two-Pass Rendering (Option C)

**Why this is deferred:** In Phase 1, ships remain near the origin while planets and stars are hundreds of thousands of units away. They never share meaningful depth competition in the same camera shot, so a single depth buffer with a wide near/far range is acceptable despite poor precision at astro distances.

**Why it will be needed:** The moment a ship navigates to a waypoint near a planet and both appear in the same camera frame, z-fighting becomes unavoidable. A 24-bit depth buffer with near=1/far=2M provides essentially zero depth precision beyond ~50k units. Every space sim that renders objects from metres to planetary scale solves this the same way: two render passes sharing a view matrix but using different projection matrices, with a depth-buffer clear between them.

### What Phase 2 must implement

1. **`SpaceTier` enum** — `Ship` and `Astro` variants added to `scenegraph::Instance` (or as a parallel lookup table).
2. **`set_instance_tier` Python binding** — lets `host_loop.py` tag each instance at creation time.
3. **Two-pass render loop** in the C++ renderer:
   - Pass 1 — Astro tier: projection with `near=1000, far=10,000,000`. Draw all astro instances.
   - Depth buffer clear.
   - Pass 2 — Ship tier: projection with `near=0.5, far=50,000`. Draw all ship instances.
   - Both passes use the same view matrix (same camera eye/target/up).
4. **Optional:** logarithmic depth buffer within each pass for finer precision on large scenes.

### What Phase 1 already provides that makes this easy

- `SHIP_SCALE` and `ASTRO_SCALE` constants define the two tiers conceptually — the vocabulary is in place.
- `_ship_world_matrix` and `_astro_world_matrix` map 1:1 to the tier tag — no positional conventions need to change.
- Ship and planet world positions are already in their final coordinate conventions (ships in raw game units; planets/stars in `game_unit * ASTRO_SCALE`).

### Trigger condition

Implement when: a mission script places a ship within visual range of a planet or star and both must be visible in the same camera frame without z-fighting.
