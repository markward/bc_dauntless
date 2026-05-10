# Scale System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply `SHIP_SCALE=0.1` to ship meshes and `ASTRO_SCALE=10` to planet/star positions and meshes so visual sizes match their Python-defined radii.

**Architecture:** All scaling is applied on the Python side by building TRS world matrices before sending to C++. A new `engine/scale.py` module holds the three named constants. `host_loop.py` replaces the single `_world_matrix_row_major` function with two typed builders (`_ship_world_matrix`, `_astro_world_matrix`) and post-processes sun descriptors in `_aggregate_suns`. No C++ changes are required.

**Tech Stack:** Python, GLM 4×4 matrices (column-major in C++, row-major in Python), pytest

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `engine/scale.py` | Three scale constants — single source of truth |
| Create | `tests/unit/test_scale_constants.py` | Verify constant values and module import |
| Modify | `engine/host_loop.py` | Two typed matrix builders, split instance dicts, sun scaling, camera constants |
| Create | `tests/host/test_world_matrices.py` | Unit tests for `_ship_world_matrix` and `_astro_world_matrix` |
| Modify | `tests/unit/test_host_loop_suns.py` | Add test for ASTRO_SCALE applied to sun descriptors |

---

### Task 1: Create `engine/scale.py`

**Files:**
- Create: `engine/scale.py`
- Create: `tests/unit/test_scale_constants.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_scale_constants.py

def test_scale_constants_exist():
    from engine.scale import SHIP_SCALE, ASTRO_SCALE, PLANET_NIF_NATIVE_RADIUS
    assert SHIP_SCALE == 0.1
    assert ASTRO_SCALE == 10.0
    assert PLANET_NIF_NATIVE_RADIUS == 45.0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_scale_constants.py -v
```

Expected: `FAILED` — `ModuleNotFoundError: No module named 'engine.scale'`

- [ ] **Step 3: Create `engine/scale.py`**

```python
# engine/scale.py
SHIP_SCALE               = 0.1
ASTRO_SCALE              = 10.0
PLANET_NIF_NATIVE_RADIUS = 45.0
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_scale_constants.py -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add engine/scale.py tests/unit/test_scale_constants.py
git commit -m "feat(scale): add engine/scale.py with SHIP_SCALE, ASTRO_SCALE, PLANET_NIF_NATIVE_RADIUS"
```

---

### Task 2: Add `_ship_world_matrix` to `host_loop.py`

**Files:**
- Modify: `engine/host_loop.py` (add function, import scale constants)
- Create: `tests/host/test_world_matrices.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/host/test_world_matrices.py
import pytest


def _make_pose(x, y, z, radius=0.0):
    """Minimal stand-in for a ship or planet object with the pose API."""
    from engine.appc.math import TGPoint3, TGMatrix3

    class _Pose:
        def __init__(self):
            self._loc = TGPoint3(x, y, z)
            self._rot = TGMatrix3()  # identity by default
            self._radius = radius

        def GetWorldLocation(self):
            return self._loc

        def GetWorldRotation(self):
            return self._rot

        def GetRadius(self):
            return self._radius

    return _Pose()


def test_ship_world_matrix_scales_mesh_not_position():
    """Identity rotation: upper-left 3×3 scaled by SHIP_SCALE, translation unchanged."""
    from engine import host_loop
    from engine.scale import SHIP_SCALE

    pose = _make_pose(100.0, 200.0, 300.0)
    m = host_loop._ship_world_matrix(pose)

    assert len(m) == 16
    # Upper-left 3×3: identity × SHIP_SCALE
    assert m[0]  == pytest.approx(SHIP_SCALE)   # row0 col0
    assert m[5]  == pytest.approx(SHIP_SCALE)   # row1 col1
    assert m[10] == pytest.approx(SHIP_SCALE)   # row2 col2
    # Off-diagonal rotation elements → 0
    assert m[1]  == pytest.approx(0.0)
    assert m[4]  == pytest.approx(0.0)
    # Translation column: unchanged world position
    assert m[3]  == pytest.approx(100.0)
    assert m[7]  == pytest.approx(200.0)
    assert m[11] == pytest.approx(300.0)
    # Homogeneous row
    assert m[12] == pytest.approx(0.0)
    assert m[13] == pytest.approx(0.0)
    assert m[14] == pytest.approx(0.0)
    assert m[15] == pytest.approx(1.0)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/host/test_world_matrices.py::test_ship_world_matrix_scales_mesh_not_position -v
```

Expected: `FAILED` — `AttributeError: module 'engine.host_loop' has no attribute '_ship_world_matrix'`

- [ ] **Step 3: Add `_ship_world_matrix` to `host_loop.py`**

Add this import at the top of `engine/host_loop.py` with the other imports:

```python
from engine.scale import SHIP_SCALE, ASTRO_SCALE, PLANET_NIF_NATIVE_RADIUS
```

Add this function directly below the existing `_world_matrix_row_major` (do not remove the old function yet):

```python
def _ship_world_matrix(ship) -> list:
    """Row-major TRS mat4 for a ship: mesh scaled by SHIP_SCALE, position unchanged."""
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

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/host/test_world_matrices.py::test_ship_world_matrix_scales_mesh_not_position -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/host/test_world_matrices.py
git commit -m "feat(scale): add _ship_world_matrix applying SHIP_SCALE to mesh"
```

---

### Task 3: Add `_astro_world_matrix` to `host_loop.py`

**Files:**
- Modify: `engine/host_loop.py`
- Modify: `tests/host/test_world_matrices.py` (add new test to the existing file)

- [ ] **Step 1: Write the failing test**

Append to `tests/host/test_world_matrices.py`:

```python
def test_astro_world_matrix_scales_mesh_and_position():
    """Identity rotation, radius=170: position × ASTRO_SCALE, mesh scale from radius."""
    from engine import host_loop
    from engine.scale import ASTRO_SCALE, PLANET_NIF_NATIVE_RADIUS

    pose = _make_pose(100.0, 200.0, 300.0, radius=170.0)
    m = host_loop._astro_world_matrix(pose)

    expected_mesh_scale = 170.0 * ASTRO_SCALE / PLANET_NIF_NATIVE_RADIUS  # ≈ 37.78

    assert len(m) == 16
    # Upper-left 3×3: identity × expected_mesh_scale
    assert m[0]  == pytest.approx(expected_mesh_scale)
    assert m[5]  == pytest.approx(expected_mesh_scale)
    assert m[10] == pytest.approx(expected_mesh_scale)
    # Off-diagonal rotation elements → 0
    assert m[1]  == pytest.approx(0.0)
    assert m[4]  == pytest.approx(0.0)
    # Translation column: position × ASTRO_SCALE
    assert m[3]  == pytest.approx(100.0 * ASTRO_SCALE)
    assert m[7]  == pytest.approx(200.0 * ASTRO_SCALE)
    assert m[11] == pytest.approx(300.0 * ASTRO_SCALE)
    # Homogeneous row
    assert m[15] == pytest.approx(1.0)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/host/test_world_matrices.py::test_astro_world_matrix_scales_mesh_and_position -v
```

Expected: `FAILED` — `AttributeError: module 'engine.host_loop' has no attribute '_astro_world_matrix'`

- [ ] **Step 3: Add `_astro_world_matrix` to `host_loop.py`**

Add directly below `_ship_world_matrix`:

```python
def _astro_world_matrix(obj) -> list:
    """Row-major TRS mat4 for a planet/moon: position × ASTRO_SCALE, mesh scale
    derived from GetRadius() so the visual radius equals python_radius * ASTRO_SCALE."""
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

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/host/test_world_matrices.py -v
```

Expected: both tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/host/test_world_matrices.py
git commit -m "feat(scale): add _astro_world_matrix applying ASTRO_SCALE to planet mesh and position"
```

---

### Task 4: Wire new matrix builders into `run()`, remove old function

**Files:**
- Modify: `engine/host_loop.py`

The `run()` function currently uses a single `instances` dict for both ships and planets, and a single `_world_matrix_row_major` for both. Split into `ship_instances` and `planet_instances` so the correct matrix builder is called for each.

No new tests are needed — the existing integration test `test_run_M1_Basic_for_a_few_ticks` (which runs 5 ticks headless) covers the wiring end-to-end.

- [ ] **Step 1: Replace the ship loop init block in `run()`**

In `engine/host_loop.py`, find the block starting at `nif_to_handle: dict[str, int] = {}` and replace the lines that build `instances` through the ship loop. Replace from `nif_to_handle: dict[str, int] = {}` to end of the ship verbose block as follows:

Old block (lines ~383–414):
```python
        # Per-NIF cache so the same mesh isn't reloaded once per ship.
        nif_to_handle: dict[str, int] = {}
        instances: dict[object, object] = {}  # ship -> InstanceId
        ships_seen = 0
        for ship in _iter_ships(verbose=verbose):
            ...
            iid = r.create_instance(handle)
            r.set_world_transform(iid, _world_matrix_row_major(ship))
            instances[ship] = iid
        if verbose:
            print(f"[host_loop] ships seen by iterator: {ships_seen}; "
                  f"instances created: {len(instances)}", flush=True)
```

New version:
```python
        # Per-NIF cache so the same mesh isn't reloaded once per ship.
        nif_to_handle: dict[str, int] = {}
        ship_instances: dict[object, object] = {}    # ship   -> InstanceId
        planet_instances: dict[object, object] = {}  # planet -> InstanceId
        ships_seen = 0
        for ship in _iter_ships(verbose=verbose):
            ships_seen += 1
            if verbose:
                cls = type(ship).__name__
                try:
                    sn = ship.GetScript()
                except Exception:
                    sn = "<no script>"
                print(f"[host_loop] consider ship: class={cls} script={sn!r}", flush=True)
            nif_path = _ship_nif_path(ship, verbose=verbose)
            if nif_path is None:
                continue
            handle = nif_to_handle.get(nif_path)
            if handle is None:
                tex_search = str(PROJECT_ROOT / "game" / DEFAULT_TEXTURE_SEARCH)
                try:
                    handle = r.load_model(nif_path, tex_search)
                except Exception as e:
                    if verbose:
                        print(f"[host_loop]   skip: load_model({nif_path}) raised: "
                              f"{type(e).__name__}: {e}", flush=True)
                    continue
                nif_to_handle[nif_path] = handle
            iid = r.create_instance(handle)
            r.set_world_transform(iid, _ship_world_matrix(ship))
            ship_instances[ship] = iid
        if verbose:
            print(f"[host_loop] ships seen by iterator: {ships_seen}; "
                  f"instances created: {len(ship_instances)}", flush=True)
```

- [ ] **Step 2: Replace the planet loop init block in `run()`**

Old planet loop (lines ~416–440):
```python
        planets_seen = 0
        planets_loaded = 0
        planet_tex_search = str(PROJECT_ROOT / "game" / DEFAULT_PLANET_TEXTURE_SEARCH)
        for planet in _iter_planets(verbose=verbose):
            planets_seen += 1
            nif_path = _planet_nif_path(planet, verbose=verbose)
            if nif_path is None:
                continue
            handle = nif_to_handle.get(nif_path)
            if handle is None:
                try:
                    handle = r.load_model(nif_path, planet_tex_search)
                except Exception as e:
                    if verbose:
                        print(f"[host_loop]   skip planet: load_model({nif_path}) raised: "
                              f"{type(e).__name__}: {e}", flush=True)
                    continue
                nif_to_handle[nif_path] = handle
            iid = r.create_instance(handle)
            r.set_world_transform(iid, _world_matrix_row_major(planet))
            instances[planet] = iid
            planets_loaded += 1
        if verbose:
            print(f"[host_loop] planets seen: {planets_seen}; "
                  f"planet instances created: {planets_loaded}", flush=True)
```

New version:
```python
        planets_seen = 0
        planet_tex_search = str(PROJECT_ROOT / "game" / DEFAULT_PLANET_TEXTURE_SEARCH)
        for planet in _iter_planets(verbose=verbose):
            planets_seen += 1
            nif_path = _planet_nif_path(planet, verbose=verbose)
            if nif_path is None:
                continue
            handle = nif_to_handle.get(nif_path)
            if handle is None:
                try:
                    handle = r.load_model(nif_path, planet_tex_search)
                except Exception as e:
                    if verbose:
                        print(f"[host_loop]   skip planet: load_model({nif_path}) raised: "
                              f"{type(e).__name__}: {e}", flush=True)
                    continue
                nif_to_handle[nif_path] = handle
            iid = r.create_instance(handle)
            r.set_world_transform(iid, _astro_world_matrix(planet))
            planet_instances[planet] = iid
        if verbose:
            print(f"[host_loop] planets seen: {planets_seen}; "
                  f"planet instances created: {len(planet_instances)}", flush=True)
```

- [ ] **Step 3: Update player fallback and verbose logging**

Old player fallback (line ~444):
```python
        player_set = App.g_kSetManager.GetSet(DEFAULT_PLAYER_SET)
        player = player_set.GetObject("player") if player_set is not None else None
        if player is None and instances:
            # Fallback: follow the first ship we found.
            player = next(iter(instances.keys()))
```

New:
```python
        player_set = App.g_kSetManager.GetSet(DEFAULT_PLAYER_SET)
        player = player_set.GetObject("player") if player_set is not None else None
        if player is None and ship_instances:
            # Fallback: follow the first ship we found.
            player = next(iter(ship_instances.keys()))
```

Old verbose instance summary (line ~451):
```python
        if verbose:
            print(f"[host_loop] mission={mission_name}", flush=True)
            print(f"[host_loop] {len(instances)} render instance(s) created", flush=True)
            for ship, _iid in list(instances.items())[:5]:
```

New:
```python
        if verbose:
            print(f"[host_loop] mission={mission_name}", flush=True)
            total = len(ship_instances) + len(planet_instances)
            print(f"[host_loop] {total} render instance(s) created "
                  f"({len(ship_instances)} ships, {len(planet_instances)} planets)", flush=True)
            for ship, _iid in list(ship_instances.items())[:5]:
```

- [ ] **Step 4: Update the per-tick sync loop and cleanup**

Old per-tick sync (line ~492):
```python
            # Sync transforms for known instances.
            for ship, iid in instances.items():
                r.set_world_transform(iid, _world_matrix_row_major(ship))
```

New:
```python
            # Sync transforms for known instances.
            for ship, iid in ship_instances.items():
                r.set_world_transform(iid, _ship_world_matrix(ship))
            for planet, iid in planet_instances.items():
                r.set_world_transform(iid, _astro_world_matrix(planet))
```

Old cleanup (line ~540):
```python
        for iid in instances.values():
            r.destroy_instance(iid)
```

New:
```python
        for iid in ship_instances.values():
            r.destroy_instance(iid)
        for iid in planet_instances.values():
            r.destroy_instance(iid)
```

- [ ] **Step 5: Remove `_world_matrix_row_major`**

Delete the entire `_world_matrix_row_major` function (the old one, lines ~343–352) from `host_loop.py`. It is no longer called anywhere.

- [ ] **Step 6: Update the fixed-camera docstring comment**

Find the `OPEN_STBC_HOST_FIXED_CAMERA` doc comment in `run()` that references `(0, 0, 1500)` and update to `(0, 0, 150)` (it will be updated to that value in Task 6, so just leave a note or update now):

```python
      OPEN_STBC_HOST_FIXED_CAMERA=1 — ignore third-person follow; use a
                                      fixed camera at (0, 0, 150) looking
                                      at the world origin.
```

- [ ] **Step 7: Run the full test suite to verify no regressions**

```bash
uv run pytest tests/host/ tests/unit/ -v
```

Expected: all existing tests pass, new matrix tests pass. Tests gated on BC assets skip cleanly.

- [ ] **Step 8: Commit**

```bash
git add engine/host_loop.py
git commit -m "feat(scale): wire _ship_world_matrix/_astro_world_matrix into run(), remove old _world_matrix_row_major"
```

---

### Task 5: Apply `ASTRO_SCALE` to sun descriptors in `_aggregate_suns`

**Files:**
- Modify: `engine/host_loop.py` (`_aggregate_suns` function only)
- Modify: `tests/unit/test_host_loop_suns.py` (add one new test)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_host_loop_suns.py`:

```python
def test_aggregate_suns_applies_astro_scale(tmp_path):
    """Sun position, radius, and corona_radius are all multiplied by ASTRO_SCALE."""
    import App
    from engine.appc.planet import Sun_Create
    from engine import host_loop
    from engine.scale import ASTRO_SCALE
    import engine.host_loop as hl
    import pytest

    # Create a fake texture file so the sun passes the existence check.
    tex_dir = tmp_path / "game" / "data" / "Textures"
    tex_dir.mkdir(parents=True)
    (tex_dir / "SunBase.tga").write_bytes(b"FAKE")

    pSet = App.SetClass_Create()
    pSun = Sun_Create(4000.0, 2000.0, 0.0)  # radius=4000, atmosphere=2000
    pSun.SetTranslateXYZ(10.0, 20.0, 30.0)
    pSet.AddObjectToSet(pSun, "Sun")
    App.g_kSetManager.AddSet(pSet, "_test_agg_suns_astro_scale")

    original_root = hl.PROJECT_ROOT
    hl.PROJECT_ROOT = tmp_path
    try:
        result = host_loop._aggregate_suns()
    finally:
        hl.PROJECT_ROOT = original_root
        App.g_kSetManager.DeleteSet("_test_agg_suns_astro_scale")

    assert len(result) == 1
    d = result[0]
    assert d["position"] == pytest.approx((10.0 * ASTRO_SCALE,
                                           20.0 * ASTRO_SCALE,
                                           30.0 * ASTRO_SCALE))
    assert d["radius"]       == pytest.approx(4000.0 * ASTRO_SCALE)
    assert d["corona_radius"] == pytest.approx((4000.0 + 2000.0) * ASTRO_SCALE)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_host_loop_suns.py::test_aggregate_suns_applies_astro_scale -v
```

Expected: `FAILED` — values do not yet have ASTRO_SCALE applied.

- [ ] **Step 3: Update `_aggregate_suns` in `host_loop.py`**

Replace the existing `_aggregate_suns` function:

```python
def _aggregate_suns() -> list:
    """Collect sun render descriptors with ASTRO_SCALE applied to position and radii."""
    from engine.appc.planet import aggregate_suns_for_renderer
    import App
    raw = aggregate_suns_for_renderer(
        PROJECT_ROOT, list(App.g_kSetManager._sets.values()))
    return [
        {
            "position": (
                d["position"][0] * ASTRO_SCALE,
                d["position"][1] * ASTRO_SCALE,
                d["position"][2] * ASTRO_SCALE,
            ),
            "radius":            d["radius"]       * ASTRO_SCALE,
            "base_texture_path": d["base_texture_path"],
            "corona_radius":     d["corona_radius"] * ASTRO_SCALE,
        }
        for d in raw
    ]
```

- [ ] **Step 4: Run all sun tests to verify pass**

```bash
uv run pytest tests/unit/test_host_loop_suns.py -v
```

Expected: all tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/unit/test_host_loop_suns.py
git commit -m "feat(scale): apply ASTRO_SCALE to sun position and radii in _aggregate_suns"
```

---

### Task 6: Update camera constants and far clip

**Files:**
- Modify: `engine/host_loop.py` (module-level constants and `run()` camera call)

- [ ] **Step 1: Write the failing test**

Append to `tests/host/test_world_matrices.py`:

```python
def test_camera_constants_match_ship_scale():
    """CAM_BACK_DIST and CAM_UP_DIST must be scaled by SHIP_SCALE relative to
    their original BC values (600 and 200 respectively)."""
    from engine import host_loop
    from engine.scale import SHIP_SCALE
    import pytest

    assert host_loop.CAM_BACK_DIST == pytest.approx(600.0 * SHIP_SCALE)
    assert host_loop.CAM_UP_DIST   == pytest.approx(200.0 * SHIP_SCALE)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/host/test_world_matrices.py::test_camera_constants_match_ship_scale -v
```

Expected: `FAILED` — current values are 600.0 and 200.0, not 60.0 and 20.0.

- [ ] **Step 3: Update module-level camera constants in `host_loop.py`**

Replace:
```python
# Camera-follow constants used by run() to position the third-person camera.
CAM_BACK_DIST = 600.0
CAM_UP_DIST   = 200.0
```

With:
```python
# Camera-follow constants scaled to match SHIP_SCALE (original BC values: 600, 200).
CAM_BACK_DIST = 600.0 * SHIP_SCALE
CAM_UP_DIST   = 200.0 * SHIP_SCALE
```

- [ ] **Step 4: Update the fixed camera eye and the far clip in `run()`**

Find the fixed-camera block in `run()`:
```python
            if fixed_camera:
                eye = (0.0, 0.0, 1500.0)
```

Change to:
```python
            if fixed_camera:
                eye = (0.0, 0.0, 1500.0 * SHIP_SCALE)
```

Find the `set_camera` call:
```python
            r.set_camera(eye=eye, target=target, up=up_vec,
                         fov_y_rad=1.0472, near=1.0, far=100000.0)
```

Change to:
```python
            r.set_camera(eye=eye, target=target, up=up_vec,
                         fov_y_rad=1.0472, near=1.0, far=2_000_000.0)
```

- [ ] **Step 5: Run all tests**

```bash
uv run pytest tests/host/ tests/unit/ -v
```

Expected: all tests pass (including BC-asset-gated tests skipping cleanly).

- [ ] **Step 6: Commit**

```bash
git add engine/host_loop.py tests/host/test_world_matrices.py
git commit -m "feat(scale): apply SHIP_SCALE to camera distances, far clip → 2,000,000"
```

---

## Done

Run the full suite one final time to confirm everything is green:

```bash
uv run pytest tests/ -v
```

All six commits together implement the scale system as specified in `docs/superpowers/specs/2026-05-10-scale-system-design.md`. Two-pass rendering (Option C) is documented in that spec under "Deferred Work" and is not part of this plan.
