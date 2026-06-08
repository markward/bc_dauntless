# Smooth Motion Under Variable Frame Rate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate visible motion judder on the player ship and AI ships when the render frame rate differs from the fixed 60 Hz sim rate.

**Architecture:** Two independent Python-side fixes in `engine/host_loop.py` plus two new pure helper modules. (1) Feed the camera springs the real wall-clock frame delta instead of the fixed sim tick, so the player ship stops swimming. (2) Interpolate non-player ship transforms between the previous and current sim state by `alpha = accumulator / TICK_DT`, so AI ships stop stepping in discrete 60 Hz jumps. No renderer/native changes — the renderer already accepts a fresh world transform every frame.

**Tech Stack:** Python 3.13, pytest. Math types from `engine/appc/math.py` (`TGPoint3`, `TGMatrix3` — column-vector convention, see `CLAUDE.md`).

**Spec:** `docs/superpowers/specs/2026-06-08-smooth-motion-variable-framerate-design.md`

**Testing note:** Per project memory, the full pytest suite OOMs the host. Always run focused subsets (the exact `pytest ...::test_name` or single-file invocations given in each task). Never run bare `uv run pytest`.

---

## File Structure

- **Create** `engine/core/interpolate.py` — pure interpolation math: `lerp_point`, `nlerp_rotation`, `lerp_transform`. No engine/global state.
- **Create** `engine/core/transform_buffer.py` — `TransformBuffer`: per-instance previous/current `(loc, rot)` snapshot bookkeeping + `sample(iid, alpha)`. Pure (no renderer, no `App`).
- **Create** `tests/unit/test_interpolate.py` — unit tests for the math module.
- **Create** `tests/unit/test_transform_buffer.py` — unit tests for the bookkeeping module.
- **Modify** `engine/host_loop.py`:
  - Extract `_world_matrix_from(loc, rot, s)` from `_ship_world_matrix` / `_astro_world_matrix` (DRY).
  - Change the camera call to pass `_player_dt` instead of `TICK_DT`.
  - Wire `TransformBuffer` into the per-frame transform-sync block.
- **Modify** `tests/host/test_world_matrices.py` — add a direct test for `_world_matrix_from`.
- **Create** `tests/cameras/test_chase_framerate_independence.py` — regression test that the chase spring converges independent of frame count for equal elapsed time.

---

## Task 1: Pure interpolation math (`engine/core/interpolate.py`)

**Files:**
- Create: `engine/core/interpolate.py`
- Test: `tests/unit/test_interpolate.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_interpolate.py
"""Pure-function unit tests for render interpolation math."""

import math

from engine.appc.math import TGMatrix3, TGPoint3
from engine.core.interpolate import lerp_point, nlerp_rotation, lerp_transform


def _det(m: TGMatrix3) -> float:
    a = m._m
    return (
        a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1])
        - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
        + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0])
    )


def test_lerp_point_endpoints_and_midpoint():
    a = TGPoint3(0.0, 0.0, 0.0)
    b = TGPoint3(10.0, -4.0, 2.0)
    assert (lerp_point(a, b, 0.0).x, lerp_point(a, b, 0.0).y, lerp_point(a, b, 0.0).z) == (0.0, 0.0, 0.0)
    assert (lerp_point(a, b, 1.0).x, lerp_point(a, b, 1.0).y, lerp_point(a, b, 1.0).z) == (10.0, -4.0, 2.0)
    mid = lerp_point(a, b, 0.5)
    assert (mid.x, mid.y, mid.z) == (5.0, -2.0, 1.0)


def test_nlerp_rotation_alpha_zero_returns_prev():
    prev = TGMatrix3(); prev.MakeYRotation(0.0)
    cur = TGMatrix3(); cur.MakeYRotation(math.radians(40.0))
    out = nlerp_rotation(prev, cur, 0.0)
    for i in range(3):
        for j in range(3):
            assert out._m[i][j] == prev._m[i][j]


def test_nlerp_rotation_alpha_one_matches_cur():
    prev = TGMatrix3(); prev.MakeYRotation(0.0)
    cur = TGMatrix3(); cur.MakeYRotation(math.radians(40.0))
    out = nlerp_rotation(prev, cur, 1.0)
    for i in range(3):
        for j in range(3):
            assert abs(out._m[i][j] - cur._m[i][j]) < 1e-9


def test_nlerp_rotation_stays_orthonormal():
    prev = TGMatrix3(); prev.MakeYRotation(0.0)
    cur = TGMatrix3(); cur.MakeYRotation(math.radians(40.0))
    out = nlerp_rotation(prev, cur, 0.5)
    # columns unit length
    for i in range(3):
        c = out.GetCol(i)
        assert abs(math.sqrt(c.x * c.x + c.y * c.y + c.z * c.z) - 1.0) < 1e-6
    # right-handed
    assert abs(_det(out) - 1.0) < 1e-6


def test_nlerp_rotation_midpoint_is_between():
    prev = TGMatrix3(); prev.MakeYRotation(0.0)
    cur = TGMatrix3(); cur.MakeYRotation(math.radians(40.0))
    out = nlerp_rotation(prev, cur, 0.5)
    # forward column (col 1) is invariant under Y-rotation; sample col 0
    # (ship-right) whose angle should land between 0 and 40 degrees.
    r = out.GetCol(0)
    ang = math.degrees(math.atan2(r.z, r.x))  # MakeYRotation: col0 = (c,0,-s)
    assert -40.0 < ang < 0.0  # between identity and -40deg about z-component


def test_lerp_transform_blends_both():
    pl = TGPoint3(0.0, 0.0, 0.0)
    cl = TGPoint3(4.0, 0.0, 0.0)
    pr = TGMatrix3(); pr.MakeYRotation(0.0)
    cr = TGMatrix3(); cr.MakeYRotation(math.radians(30.0))
    loc, rot = lerp_transform(pl, pr, cl, cr, 0.5)
    assert (loc.x, loc.y, loc.z) == (2.0, 0.0, 0.0)
    assert abs(_det(rot) - 1.0) < 1e-6
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_interpolate.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.core.interpolate'`

- [ ] **Step 3: Write the implementation**

```python
# engine/core/interpolate.py
"""Render interpolation math: blend two sim states for a render frame.

Pure functions, no engine/global state. Used by the host loop to draw
non-player ships at `lerp(prev, cur, alpha)` so their discrete 60 Hz
motion reads as smooth at any render refresh rate.

Rotation uses normalized-lerp of the basis columns followed by
Gram-Schmidt re-orthonormalization, matching the column-vector
convention in CLAUDE.md and the smoothing in
`engine/cameras/chase.py:_advance_smoothing`. Per-tick deltas are tiny
(<= a few degrees at 60 Hz), so nlerp is visually indistinguishable
from slerp and never hits the degenerate 180-degree case.
"""

import math

from engine.appc.math import TGMatrix3, TGPoint3


def lerp_point(a: TGPoint3, b: TGPoint3, alpha: float) -> TGPoint3:
    return TGPoint3(
        a.x + alpha * (b.x - a.x),
        a.y + alpha * (b.y - a.y),
        a.z + alpha * (b.z - a.z),
    )


def _norm(v: TGPoint3) -> TGPoint3:
    m = math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z)
    return TGPoint3(v.x / m, v.y / m, v.z / m)


def nlerp_rotation(a: TGMatrix3, b: TGMatrix3, alpha: float) -> TGMatrix3:
    """Blend basis columns of a toward b, then Gram-Schmidt orthonormalize.

    Keeps forward (col 1) as the primary axis, projects up (col 2)
    perpendicular to it, derives right (col 0) via forward x up. Body
    axes are right-handed (det = +1).
    """
    blended = [None, None, None]
    for i in range(3):
        s = a.GetCol(i)
        l = b.GetCol(i)
        blended[i] = TGPoint3(
            s.x + alpha * (l.x - s.x),
            s.y + alpha * (l.y - s.y),
            s.z + alpha * (l.z - s.z),
        )

    f = _norm(blended[1])
    u_in = blended[2]
    dot_uf = u_in.x * f.x + u_in.y * f.y + u_in.z * f.z
    u = _norm(TGPoint3(
        u_in.x - dot_uf * f.x,
        u_in.y - dot_uf * f.y,
        u_in.z - dot_uf * f.z,
    ))
    r = TGPoint3(
        f.y * u.z - f.z * u.y,
        f.z * u.x - f.x * u.z,
        f.x * u.y - f.y * u.x,
    )

    out = TGMatrix3()
    out.SetCol(0, r)
    out.SetCol(1, f)
    out.SetCol(2, u)
    return out


def lerp_transform(prev_loc, prev_rot, cur_loc, cur_rot, alpha):
    """Return interpolated (loc, rot) for a render frame."""
    return lerp_point(prev_loc, cur_loc, alpha), nlerp_rotation(prev_rot, cur_rot, alpha)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_interpolate.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/core/interpolate.py tests/unit/test_interpolate.py
git commit -m "feat(core): pure render-interpolation math (lerp/nlerp transform)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Transform snapshot bookkeeping (`engine/core/transform_buffer.py`)

**Files:**
- Create: `engine/core/transform_buffer.py`
- Test: `tests/unit/test_transform_buffer.py`

The buffer stores previous and current `(loc, rot)` per render instance id and returns the interpolated sample. It is pure — the host loop reads live transforms and builds matrices; the buffer only holds and blends them.

Per-frame contract (enforced by the host loop in Task 5):
- When `>= 1` sim tick fired this frame *and it was not a mission-swap frame*: call `roll()` (cur -> prev for every known iid), run ticks, then `set_current(iid, loc, rot)` for each non-player ship, then `prune(live_iids)`.
- On a mission-swap frame: `reset_all()` then `set_current(...)` for each ship (prev seeded equal to cur, no smear across the discontinuity).
- A previously unseen iid passed to `set_current` seeds prev = cur automatically (covers first frame and newly spawned ships).
- Every frame: `sample(iid, alpha)` returns the blended `(loc, rot)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_transform_buffer.py
"""Unit tests for the render transform snapshot buffer."""

from engine.appc.math import TGMatrix3, TGPoint3
from engine.core.transform_buffer import TransformBuffer


def _ident():
    m = TGMatrix3(); m.MakeIdentity(); return m


def test_new_iid_seeds_prev_equal_to_cur_no_smear():
    buf = TransformBuffer()
    buf.set_current(7, TGPoint3(10.0, 0.0, 0.0), _ident())
    loc, _rot = buf.sample(7, 0.0)
    assert (loc.x, loc.y, loc.z) == (10.0, 0.0, 0.0)
    loc1, _ = buf.sample(7, 1.0)
    assert (loc1.x, loc1.y, loc1.z) == (10.0, 0.0, 0.0)  # prev == cur


def test_roll_then_set_current_interpolates_across_last_tick():
    buf = TransformBuffer()
    buf.set_current(7, TGPoint3(0.0, 0.0, 0.0), _ident())  # frame 0 seed
    buf.roll()                                             # frame 1: cur -> prev
    buf.set_current(7, TGPoint3(4.0, 0.0, 0.0), _ident())  # new cur
    loc, _ = buf.sample(7, 0.0)
    assert loc.x == 0.0          # alpha 0 -> prev
    loc, _ = buf.sample(7, 0.5)
    assert loc.x == 2.0          # midpoint
    loc, _ = buf.sample(7, 1.0)
    assert loc.x == 4.0          # alpha 1 -> cur


def test_zero_tick_frame_keeps_state():
    buf = TransformBuffer()
    buf.set_current(7, TGPoint3(0.0, 0.0, 0.0), _ident())
    buf.roll()
    buf.set_current(7, TGPoint3(4.0, 0.0, 0.0), _ident())
    # A 0-tick frame: no roll, no set_current. Sampling still works and
    # alpha grows toward cur as the accumulator fills.
    loc, _ = buf.sample(7, 0.75)
    assert loc.x == 3.0


def test_reset_all_clears_stale_state():
    buf = TransformBuffer()
    buf.set_current(7, TGPoint3(0.0, 0.0, 0.0), _ident())
    buf.roll()
    buf.set_current(7, TGPoint3(999.0, 0.0, 0.0), _ident())
    buf.reset_all()
    # After a swap: re-seed; first sample renders at live, no smear.
    buf.set_current(7, TGPoint3(5.0, 0.0, 0.0), _ident())
    loc, _ = buf.sample(7, 0.0)
    assert loc.x == 5.0
    loc, _ = buf.sample(7, 1.0)
    assert loc.x == 5.0


def test_prune_drops_absent_iids():
    buf = TransformBuffer()
    buf.set_current(7, TGPoint3(0.0, 0.0, 0.0), _ident())
    buf.set_current(8, TGPoint3(0.0, 0.0, 0.0), _ident())
    buf.prune({7})
    assert buf.has(7)
    assert not buf.has(8)


def test_sample_unknown_iid_returns_none():
    buf = TransformBuffer()
    assert buf.sample(99, 0.5) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_transform_buffer.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.core.transform_buffer'`

- [ ] **Step 3: Write the implementation**

```python
# engine/core/transform_buffer.py
"""Per-instance previous/current transform snapshots for render interpolation.

Holds the last two sim-state transforms for each render instance id and
returns `lerp(prev, cur, alpha)` for the current render frame. Pure: no
renderer, no App, no global state. See the per-frame contract in the
implementation plan and the design spec.
"""

from engine.core.interpolate import lerp_transform


class TransformBuffer:
    def __init__(self):
        self._prev = {}  # iid -> (loc, rot)
        self._cur = {}   # iid -> (loc, rot)

    def has(self, iid) -> bool:
        return iid in self._cur

    def roll(self) -> None:
        """Promote current snapshots to previous (start of a tick batch)."""
        self._prev = dict(self._cur)

    def set_current(self, iid, loc, rot) -> None:
        """Record the post-tick live transform. Seeds prev = cur for a
        previously unseen iid so the first rendered frame does not smear."""
        self._cur[iid] = (loc, rot)
        if iid not in self._prev:
            self._prev[iid] = (loc, rot)

    def reset_all(self) -> None:
        """Forget all snapshots (mission swap / scene discontinuity)."""
        self._prev.clear()
        self._cur.clear()

    def prune(self, live_iids) -> None:
        """Drop iids not present in live_iids (despawned instances)."""
        live = set(live_iids)
        for iid in [k for k in self._cur if k not in live]:
            self._cur.pop(iid, None)
            self._prev.pop(iid, None)

    def sample(self, iid, alpha):
        """Return interpolated (loc, rot) for iid, or None if unknown."""
        cur = self._cur.get(iid)
        if cur is None:
            return None
        prev = self._prev.get(iid, cur)
        return lerp_transform(prev[0], prev[1], cur[0], cur[1], alpha)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_transform_buffer.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/core/transform_buffer.py tests/unit/test_transform_buffer.py
git commit -m "feat(core): TransformBuffer for prev/cur render-interp snapshots

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Extract `_world_matrix_from` (DRY refactor, behavior-preserving)

`_ship_world_matrix` and `_astro_world_matrix` share an identical
matrix-build body. Extract it so the interpolation path (Task 5) can
build the same matrix from an interpolated `(loc, rot)` without an object
to read from.

**Files:**
- Modify: `engine/host_loop.py` (`_ship_world_matrix` ~L1498-1513, `_astro_world_matrix` ~L1516-1537)
- Test: `tests/host/test_world_matrices.py`

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/host/test_world_matrices.py
def test_world_matrix_from_matches_manual_build():
    from engine.appc.math import TGMatrix3, TGPoint3
    from engine.host_loop import _world_matrix_from

    rot = TGMatrix3(); rot.MakeYRotation(0.0)  # identity-ish, det +1
    loc = TGPoint3(3.0, -2.0, 5.0)
    m = _world_matrix_from(loc, rot, 0.5)
    # det(rot) > 0 -> X body axis negated; scale 0.5 on all axes.
    assert m[3] == 3.0 and m[7] == -2.0 and m[11] == 5.0  # translation
    assert m[0] == rot._m[0][0] * -0.5  # col0 negated by flip
    assert m[1] == rot._m[0][1] * 0.5
    assert m[15] == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/host/test_world_matrices.py::test_world_matrix_from_matches_manual_build -q`
Expected: FAIL — `ImportError: cannot import name '_world_matrix_from'`

- [ ] **Step 3: Add `_world_matrix_from` and route both builders through it**

Insert this new function immediately above `_ship_world_matrix` in `engine/host_loop.py`:

```python
def _world_matrix_from(loc, rot, s: float) -> list:
    """Row-major TRS mat4 from an explicit (loc, rot) and combined scale s.

    Shared by _ship_world_matrix, _astro_world_matrix, and the render
    interpolation path. Applies the determinant-normalization X-flip
    (see _ship_world_matrix docstring) so every rendered instance reaches
    the GPU with det < 0 under glFrontFace(GL_CW).
    """
    flip = -1.0 if _rot_determinant(rot) > 0.0 else 1.0
    sx = s * flip
    return [
        rot._m[0][0]*sx, rot._m[0][1]*s, rot._m[0][2]*s, loc.x,
        rot._m[1][0]*sx, rot._m[1][1]*s, rot._m[1][2]*s, loc.y,
        rot._m[2][0]*sx, rot._m[2][1]*s, rot._m[2][2]*s, loc.z,
        0.0,             0.0,            0.0,            1.0,
    ]
```

Then replace the body of `_ship_world_matrix` from `s = natural_scale * py_scale` through the `return [...]` block with:

```python
    s = natural_scale * py_scale
    return _world_matrix_from(loc, rot, s)
```

And identically replace the tail of `_astro_world_matrix` from `s = natural_scale * py_scale` through its `return [...]` block with:

```python
    s = natural_scale * py_scale
    return _world_matrix_from(loc, rot, s)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/host/test_world_matrices.py -q`
Expected: PASS (existing tests + the new one). The existing `_ship_world_matrix`/`_astro_world_matrix` tests prove the refactor is behavior-preserving.

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/host/test_world_matrices.py
git commit -m "refactor(host): extract _world_matrix_from shared by ship/astro/interp

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Camera dt fix (player-ship judder)

The chase/tracking springs do correct `1 - exp(-dt/tau)` smoothing but
are called with a fixed `TICK_DT` every render frame, so they lurch at
non-60 Hz refresh rates. Pass the real wall-clock `_player_dt` instead.

**Files:**
- Modify: `engine/host_loop.py` (`_compute_camera` call at ~L2514-2516)
- Test: `tests/cameras/test_chase_framerate_independence.py`

- [ ] **Step 1: Write the failing regression test**

This test documents and guards the invariant the fix relies on: for the
same total elapsed wall time, the chase spring must converge to nearly
the same smoothed basis regardless of how many frames it took. (It fails
today only if someone later breaks the spring; the host-loop call-site
change itself is verified by the smoke test in Step 4 and manual review.)

```python
# tests/cameras/test_chase_framerate_independence.py
"""The chase rotation spring must be frame-rate independent: equal
elapsed wall time => equal smoothed basis, regardless of frame count.
This is the invariant that makes feeding wall-clock dt (not a fixed
TICK_DT) to the camera correct. Regression guard for host_loop's
_compute_camera dt."""

import math

from engine.appc.math import TGMatrix3
from engine.cameras.chase import _ChaseCamera


def _yaw(angle_deg):
    m = TGMatrix3(); m.MakeYRotation(math.radians(angle_deg)); return m


def _converge(n_frames, total_time, target):
    cam = _ChaseCamera()
    dt = total_time / n_frames
    start = _yaw(0.0)
    cam.compute_camera(_loc(), start, dt=dt)  # seed
    for _ in range(n_frames):
        cam.compute_camera(_loc(), target, dt=dt)
    return cam._smoothed_rot.GetCol(1)  # forward column


def _loc():
    from engine.appc.math import TGPoint3
    return TGPoint3(0.0, 0.0, 0.0)


def test_chase_spring_same_elapsed_time_converges_equally():
    target = _yaw(45.0)
    coarse = _converge(10, 1.0, target)    # 10 fps for 1s
    fine = _converge(240, 1.0, target)     # 240 fps for 1s
    # Forward columns should match closely despite 24x frame-count gap.
    assert abs(coarse.x - fine.x) < 1e-3
    assert abs(coarse.y - fine.y) < 1e-3
    assert abs(coarse.z - fine.z) < 1e-3
```

- [ ] **Step 2: Run test to verify it passes (invariant already holds) or reveals a problem**

Run: `uv run pytest tests/cameras/test_chase_framerate_independence.py -q`
Expected: PASS — `chase._advance_smoothing` already uses `1 - exp(-dt/tau)`, which is frame-rate independent. (If it FAILS, the spring math itself is wrong and must be fixed before the host-loop change is meaningful — stop and investigate.)

- [ ] **Step 3: Change the host-loop camera call to wall-clock dt**

In `engine/host_loop.py`, the exterior-view camera call currently reads:

```python
                eye, target, up_vec = _compute_camera(
                    view_mode, director,
                    player=player, dt=TICK_DT)
```

Change `dt=TICK_DT` to `dt=_player_dt`:

```python
                eye, target, up_vec = _compute_camera(
                    view_mode, director,
                    player=player, dt=_player_dt)
```

`_player_dt` is defined earlier in the same loop body (the wall-clock
frame delta, clamped to `[0, MAX_FRAME_DT]` and forced to `0.0` while
paused), so the spring now advances in real time and freezes correctly
on pause. Leave the audio `tick_audio(..., dt=TICK_DT, ...)` call as-is
(out of scope).

- [ ] **Step 4: Run the host-loop smoke test to verify no regression**

Run: `uv run pytest tests/host/test_host_loop_unit.py::test_run_M1_Basic_for_a_few_ticks -q`
Expected: PASS, or SKIP if BC assets are absent. Must not error.

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/cameras/test_chase_framerate_independence.py
git commit -m "fix(camera): feed wall-clock dt to camera springs, not fixed TICK_DT

Player ship no longer swims/judders at non-60Hz refresh rates.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Wire AI-ship interpolation into the host loop

Use `TransformBuffer` to render non-player ships at `lerp(prev, cur,
alpha)`. The player ship keeps its existing live-transform push.

**Files:**
- Modify: `engine/host_loop.py` — buffer init (~L2167), swap handling (~L2380-2386), transform sync (~L2498-2504), alpha from accumulator.
- Test: `tests/host/test_host_loop_unit.py` (smoke), plus reuse the Task 1/2 unit suites.

- [ ] **Step 1: Initialize the buffer alongside the accumulator state**

In `engine/host_loop.py`, just after `_accumulator = 0.0` (~L2167), add:

```python
        from engine.core.transform_buffer import TransformBuffer
        _xform_buf = TransformBuffer()
```

- [ ] **Step 2: Roll the buffer at the start of each tick batch (non-swap frames)**

The current tick-batch block reads:

```python
            _player_dt = 0.0 if pause.is_open else min(max(_frame_dt, 0.0), MAX_FRAME_DT)
            for _ in range(_sim_ticks_this_frame):
                loop.tick()
```

Change it to roll the buffer before running ticks (so cur becomes prev),
and compute the render-interpolation alpha after the accumulator step:

```python
            _player_dt = 0.0 if pause.is_open else min(max(_frame_dt, 0.0), MAX_FRAME_DT)
            _interp_alpha = _accumulator / TICK_DT  # in [0, 1) after step_accumulator
            if _sim_ticks_this_frame > 0:
                _xform_buf.roll()
            for _ in range(_sim_ticks_this_frame):
                loop.tick()
```

- [ ] **Step 3: Reset the buffer on a mission-swap frame**

The current swap block reads:

```python
            if _sim_ticks_this_frame > 0:
                had_pending_swap = controller.pending_swap is not None
                controller._drain_pending_swap()
                if had_pending_swap:
                    director.snap()
            else:
                had_pending_swap = False
```

Add a buffer reset when a swap actually happened, so post-swap ships
seed fresh (no smear across the scene discontinuity):

```python
            if _sim_ticks_this_frame > 0:
                had_pending_swap = controller.pending_swap is not None
                controller._drain_pending_swap()
                if had_pending_swap:
                    director.snap()
                    _xform_buf.reset_all()
            else:
                had_pending_swap = False
```

- [ ] **Step 4: Replace the ship transform-sync block with interpolated push**

The current sync block (inside `if not pause.is_open:`) reads:

```python
                # Sync transforms for known instances.
                if session is not None:
                    for ship, iid in session.ship_instances.items():
                        r.set_world_transform(iid, _ship_world_matrix(ship, BC_MODEL_SCALE))
                    for planet, iid in session.planet_instances.items():
                        ns = session.planet_natural_scale.get(planet, 1.0)
                        r.set_world_transform(iid, _astro_world_matrix(planet, ns))
```

Replace it with a version that captures non-player ship snapshots and
renders them interpolated, while the player ship and planets keep their
live transforms:

```python
                # Sync transforms for known instances.
                #
                # Player ship: pushed live (it is integrated per render
                # frame on wall-clock dt in _PlayerControl, so it is
                # already smooth in world space).
                #
                # Non-player ships: integrated on the fixed 60 Hz tick,
                # so they are rendered at lerp(prev, cur, _interp_alpha)
                # to hide the discrete steps. _xform_buf.roll() ran above
                # before this frame's ticks; here we capture the new
                # current state and push the interpolated pose.
                if session is not None:
                    _player_iid = session.ship_instances.get(player)
                    _live_ship_iids = []
                    for ship, iid in session.ship_instances.items():
                        if iid == _player_iid:
                            r.set_world_transform(
                                iid, _ship_world_matrix(ship, BC_MODEL_SCALE))
                            continue
                        _live_ship_iids.append(iid)
                        try:
                            _ps = float(ship.GetScale())
                        except Exception:
                            _ps = 1.0
                        _xform_buf.set_current(
                            iid, ship.GetWorldLocation(), ship.GetWorldRotation())
                        _sampled = _xform_buf.sample(iid, _interp_alpha)
                        _iloc, _irot = _sampled
                        r.set_world_transform(
                            iid, _world_matrix_from(_iloc, _irot, BC_MODEL_SCALE * _ps))
                    _xform_buf.prune(_live_ship_iids)
                    for planet, iid in session.planet_instances.items():
                        ns = session.planet_natural_scale.get(planet, 1.0)
                        r.set_world_transform(iid, _astro_world_matrix(planet, ns))
```

Note: `set_current` must run *before* `sample` so a newly spawned ship
seeds prev = cur and renders static-correct for its first frame.
`_interp_alpha` was computed in Step 2 from the post-step accumulator.

- [ ] **Step 5: Run the host-loop smoke test**

Run: `uv run pytest tests/host/test_host_loop_unit.py::test_run_M1_Basic_for_a_few_ticks tests/host/test_host_loop_unit.py::test_run_M1_Basic_player_unmoved_without_input -q`
Expected: PASS, or SKIP if BC assets are absent. Must not error — this exercises the buffer roll/capture/sample/prune path across real ticks.

- [ ] **Step 6: Run the interpolation unit suites once more (regression)**

Run: `uv run pytest tests/unit/test_interpolate.py tests/unit/test_transform_buffer.py tests/host/test_world_matrices.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add engine/host_loop.py
git commit -m "feat(host): interpolate non-player ship transforms between sim ticks

AI ships render at lerp(prev, cur, accumulator/TICK_DT) instead of
snapping to the latest 60Hz state, removing judder at high/variable
refresh rates. Player ship stays live; buffer resets on mission swap.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Final verification

- [ ] **Run all new + touched focused tests together:**

Run: `uv run pytest tests/unit/test_interpolate.py tests/unit/test_transform_buffer.py tests/cameras/test_chase_framerate_independence.py tests/host/test_world_matrices.py tests/host/test_host_loop_unit.py -q`
Expected: all PASS (host_loop asset-dependent tests may SKIP).

- [ ] **Manual acceptance (the real judder test):** build and run the host at an uncapped / high refresh rate, fly near AI ships, and confirm both player and AI ship motion read as smooth.

```bash
cmake -B build -S . && cmake --build build -j && ./build/dauntless
```

(Per project memory: shader edits would need a cmake reconfigure, but this change is Python-only, so a plain `cmake --build` — or just rerunning `./build/dauntless` if already built — suffices.)
