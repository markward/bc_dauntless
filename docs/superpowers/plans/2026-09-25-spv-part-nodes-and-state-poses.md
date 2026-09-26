# SPV Part Nodes and Full Per-State Poses — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-hinge, angle-per-state part rig with an Anchor + full rigid pose per state + Breakage, authored in the Ship Property Viewer as nested child nodes.

**Architecture:** A pure pose-maths module (`engine/appc/part_pose.py`) defines poses, the swing interpolation and the legacy hinge conversion. `ArticulatedPartProperty` stores anchor / transition time / per-state poses / break fraction and still loads the old calls. A new native binding takes a full node matrix; the runtime then switches every consumer from angles to poses; the Bird of Prey data migrates; finally the SPV Model Parts pane becomes a node tree with right-click menus, a toast, and gizmo editing of anchors and poses.

**Tech Stack:** Python 3 (`engine/appc/`, `engine/ui/`), C++20 + glm + pybind11 (`native/src/host/`), CEF JS/HTML/CSS (`native/assets/ui-cef/`), pytest, gtest/ctest.

**Spec:** `docs/superpowers/specs/2026-09-25-spv-part-nodes-and-state-poses-design.md`

## Global Constraints

- **Shared checkout, destructive git BANNED:** never `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage explicit pathspecs only. Temporary mutation: `cp` to scratch, mutate, `cp` back, `diff` to prove the restore.
- **NEVER run `./build/dauntless`** in any form (no `--help` either: it launches the game).
- **ONE build tree** at `<worktree>/build/`: `cmake -B build -S . && cmake --build build -j`; never cmake inside `native/`.
- **Gate:** `scripts/check_tests.sh`; clean = `OK — no new failures. 1 known failure(s) still baselined.`
- **After mutating `engine/appc/hardpoint_overrides.py`** delete `engine/appc/__pycache__/hardpoint_overrides.cpython-*.pyc` (a same-size edit within one mtime second leaves stale bytecode).
- **Units:** poses, anchors, part boxes and mounts are SHIP units, body frame; node matrices are MODEL units; `MODEL_TO_SHIP = 0.01`. The ONE ship→model conversion is in `host_loop._sync_ship_articulation`.
- **Pose convention (spec §3):** a body point `x` of the part is drawn at `R·x + t`; `R = Rz(rz)·Ry(ry)·Rx(rx)` (degrees; rotate about body X, then Y, then Z), right-handed, column-vector; `R`, `t` are about the body ORIGIN, never the anchor.
- **States are exactly** `"cruise"`, `"yellow"`, `"red"`, `"warp"`. UI labels: Cruising, Yellow Alert, Red Alert, Warp.
- **Python 1.5 safety** for anything the writer emits: numbers and strings only, no `True`/`False`, no f-strings.
- **Byte-identical for unrigged ships:** no rig → no pose → no call.
- **A real BC hull is THREE levels** (part → `__NDL_MultiMtl_Node` → mesh); fixtures mirror it.

## Review Focus

1. **Moving the anchor must not move authored poses** (spec §2.3, option A). Pinned by `test_moving_the_anchor_leaves_end_poses_unchanged` (Task 1) and `test_anchor_move_leaves_state_poses` (Task 8).
2. **A transition interrupted mid-move** starts from the current pose, never snaps. Pinned by `test_interrupted_transition_starts_from_the_current_pose` (Task 4).
3. **A severed part is never re-posed** (its zero override must survive). Pinned by the existing `test_a_detached_part_is_not_repose_by_the_render_sync`, re-pointed in Task 4.
4. **Legacy hardpoint files keep loading** with identical motion. Pinned by `test_legacy_hinge_matches_old_rodrigues_everywhere` (Task 2) and the migration equivalence test (Task 5).
5. **A pose authored without an anchor is impossible from the UI**, and removing the anchor under existing poses is refused. Pinned by `test_add_transformation_without_anchor_toasts_and_changes_nothing` and `test_remove_anchor_with_poses_is_refused` (Task 6).

---

### Task 1: `part_pose` — pose maths, swing, legacy hinge conversion

**Files:**
- Create: `engine/appc/part_pose.py`
- Test: `tests/unit/test_part_pose.py`

**Interfaces:**
- Produces (all pure; a "pose" is `(R, t)` with `R` a 3×3 tuple-of-row-tuples, `t` a 3-tuple; a "pose6" is `(tx, ty, tz, rx, ry, rz)` in ship units / degrees):
  - `IDENTITY` — `(((1,0,0),(0,1,0),(0,0,1)), (0,0,0))` as floats
  - `euler_to_matrix(rx, ry, rz) -> R`
  - `matrix_to_euler(R) -> (rx, ry, rz)`
  - `pose_from6(p6) -> pose`, `pose_to6(pose) -> p6`
  - `apply(pose, x) -> x'`, `apply_vector(pose, v) -> v'`, `inverse_apply(pose, x) -> x0`
  - `is_identity(pose, eps=1e-9) -> bool`
  - `hinge_pose(pivot, axis, degrees) -> pose`
  - `interpolate(pose0, pose1, anchor, u) -> pose`
  - `matrix4_model(pose, model_to_ship) -> tuple of 16 floats` (column-major, translation divided by `model_to_ship`)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_part_pose.py`:

```python
"""Pose maths for articulated parts (spec 2026-09-25 §3, §4.1, §6).

A pose (R, t) draws a body point x at R·x + t, R = Rz·Ry·Rx (degrees, body X
then Y then Z), about the body ORIGIN -- never the anchor, which is what lets
the anchor move without moving any authored pose (spec §2.3, option A).
"""
import math

import pytest

from engine.appc import part_pose as pp


def _rodrigues(point, pivot, axis, degrees):
    """The OLD hinge maths, verbatim in spirit (articulation._rotate_about):
    the reference the legacy conversion must match."""
    n = math.sqrt(sum(a * a for a in axis))
    ax, ay, az = (a / n for a in axis)
    th = math.radians(degrees)
    vx, vy, vz = (point[i] - pivot[i] for i in range(3))
    c, s = math.cos(th), math.sin(th)
    dot = ax * vx + ay * vy + az * vz
    cx, cy, cz = ay * vz - az * vy, az * vx - ax * vz, ax * vy - ay * vx
    return (pivot[0] + vx * c + cx * s + ax * dot * (1 - c),
            pivot[1] + vy * c + cy * s + ay * dot * (1 - c),
            pivot[2] + vz * c + cz * s + az * dot * (1 - c))


def test_euler_order_is_x_then_y_then_z():
    """THE convention pin. R = Rz·Ry·Rx: a point on +Y rotated 90 about X
    goes to +Z, and THEN 90 about Z leaves +Z where it is."""
    R = pp.euler_to_matrix(90.0, 0.0, 90.0)
    assert pp.apply((R, (0.0, 0.0, 0.0)), (0.0, 1.0, 0.0)) == pytest.approx(
        (0.0, 0.0, 1.0), abs=1e-12)
    # and +X: 90 about X keeps +X; 90 about Z takes it to +Y
    assert pp.apply((R, (0.0, 0.0, 0.0)), (1.0, 0.0, 0.0)) == pytest.approx(
        (0.0, 1.0, 0.0), abs=1e-12)


def test_matrix_to_euler_round_trips():
    for e in [(10.0, 20.0, 30.0), (-45.0, 0.0, 0.0), (0.0, -80.0, 170.0),
              (0.0, 0.0, 0.0)]:
        R = pp.euler_to_matrix(*e)
        R2 = pp.euler_to_matrix(*pp.matrix_to_euler(R))
        for r1, r2 in zip(R, R2):
            assert r1 == pytest.approx(r2, abs=1e-9)


def test_pose6_round_trips():
    p6 = (0.1, -0.2, 0.3, 12.0, -34.0, 56.0)
    assert pp.pose_to6(pp.pose_from6(p6)) == pytest.approx(p6, abs=1e-9)


def test_inverse_apply_undoes_apply():
    pose = pp.pose_from6((0.5, 0.0, -0.25, 30.0, 10.0, -20.0))
    x = (1.0, 2.0, 3.0)
    assert pp.inverse_apply(pose, pp.apply(pose, x)) == pytest.approx(x)


def test_vectors_rotate_but_never_translate():
    pose = pp.pose_from6((9.0, 9.0, 9.0, 0.0, 0.0, 90.0))
    assert pp.apply_vector(pose, (1.0, 0.0, 0.0)) == pytest.approx(
        (0.0, 1.0, 0.0), abs=1e-12)


def test_identity_is_identity():
    assert pp.is_identity(pp.IDENTITY)
    assert pp.is_identity(pp.pose_from6((0, 0, 0, 0, 0, 0)))
    assert not pp.is_identity(pp.pose_from6((0, 0, 0, 1e-3, 0, 0)))


@pytest.mark.parametrize("deg", [45.0, -45.0, 0.0, 17.5])
def test_legacy_hinge_matches_old_rodrigues_everywhere(deg):
    """Migration (spec §6): anchor p, R = rot(n, θ), t = p - R·p reproduces
    the old Rodrigues hinge at every point -- the BoP's numbers."""
    pivot, axis = (-0.16, 0.0, 0.05), (0.0, 1.0, 0.0)
    pose = pp.hinge_pose(pivot, axis, deg)
    for x in [(1.0, 0.45, -0.67), (-1.0, 0.0, -0.7), (0.0, 0.0, 0.0)]:
        assert pp.apply(pose, x) == pytest.approx(
            _rodrigues(x, pivot, axis, deg), abs=1e-12)


def test_interpolation_hits_both_end_poses_for_any_anchor():
    p0 = pp.pose_from6((0, 0, 0, 0, 0, 0))
    p1 = pp.pose_from6((0.2, 0.1, 0.0, 0.0, 30.0, 0.0))
    x = (1.0, 0.5, -0.5)
    for anchor in [(0, 0, 0), (-0.16, 0, 0.05), (3.0, -2.0, 1.0)]:
        assert pp.apply(pp.interpolate(p0, p1, anchor, 0.0), x) == pytest.approx(
            pp.apply(p0, x))
        assert pp.apply(pp.interpolate(p0, p1, anchor, 1.0), x) == pytest.approx(
            pp.apply(p1, x))


def test_the_midpoint_swings_on_the_arc_not_the_chord():
    """A hinge about the anchor: halfway, the tip is on the circle about the
    anchor, not on the straight line between its end positions."""
    anchor, axis = (0.0, 0.0, 0.0), (0.0, 1.0, 0.0)
    p0, p1 = pp.hinge_pose(anchor, axis, 0.0), pp.hinge_pose(anchor, axis, 90.0)
    tip = (1.0, 0.0, 0.0)
    mid = pp.apply(pp.interpolate(p0, p1, anchor, 0.5), tip)
    assert math.dist(mid, anchor) == pytest.approx(1.0, abs=1e-9)
    chord_mid = tuple((a + b) / 2 for a, b in zip(pp.apply(p0, tip),
                                                  pp.apply(p1, tip)))
    assert math.dist(mid, chord_mid) > 0.2


def test_legacy_hinge_interpolation_is_the_old_linear_angle_ease():
    """With the anchor on the hinge axis, the swing IS the old linear angle
    ease: halfway between 0 and 45 degrees is exactly 22.5 degrees."""
    pivot, axis = (-0.16, 0.0, 0.05), (0.0, 1.0, 0.0)
    mid = pp.interpolate(pp.hinge_pose(pivot, axis, 0.0),
                         pp.hinge_pose(pivot, axis, 45.0), pivot, 0.5)
    x = (-1.0, 0.45, -0.67)
    assert pp.apply(mid, x) == pytest.approx(_rodrigues(x, pivot, axis, 22.5),
                                             abs=1e-9)


def test_moving_the_anchor_leaves_end_poses_unchanged():
    """Spec §2.3 option A, at the maths level: the anchor changes the path
    only. Same end poses, two anchors, different midpoints."""
    p0 = pp.pose_from6((0, 0, 0, 0, 0, 0))
    p1 = pp.pose_from6((0.0, 0.0, 0.3, 0.0, 40.0, 0.0))
    x = (1.0, 0.0, 0.0)
    a, b = (0.0, 0.0, 0.0), (0.8, 0.0, 0.0)
    assert pp.apply(pp.interpolate(p0, p1, a, 1.0), x) == pytest.approx(
        pp.apply(pp.interpolate(p0, p1, b, 1.0), x))
    assert pp.apply(pp.interpolate(p0, p1, a, 0.5), x) != pytest.approx(
        pp.apply(pp.interpolate(p0, p1, b, 0.5), x))


def test_model_matrix_is_column_major_and_scales_translation():
    """The native binding's matrix: M·[x_model,1] must equal the pose applied
    in ship units, rescaled to model units."""
    pose = pp.pose_from6((0.3, -0.1, 0.2, 10.0, 20.0, 30.0))
    m = pp.matrix4_model(pose, 0.01)
    assert len(m) == 16
    x_ship = (0.5, 0.25, -0.75)
    x_model = tuple(c / 0.01 for c in x_ship)
    col = lambda j: m[4 * j:4 * j + 4]               # column-major columns
    out = tuple(col(0)[r] * x_model[0] + col(1)[r] * x_model[1]
                + col(2)[r] * x_model[2] + col(3)[r] for r in range(3))
    want = tuple(c / 0.01 for c in pp.apply(pose, x_ship))
    assert out == pytest.approx(want, abs=1e-6)
    assert (m[3], m[7], m[11], m[15]) == (0.0, 0.0, 0.0, 1.0)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_part_pose.py -q`
Expected: `ModuleNotFoundError: No module named 'engine.appc.part_pose'`.

- [ ] **Step 3: Implement `engine/appc/part_pose.py`**

```python
"""Rigid poses for articulated ship parts (spec 2026-09-25 §3, §4.1, §6).

A pose is (R, t): R a 3x3 rotation as a tuple of ROW tuples, t a 3-tuple. It
draws a body-frame point x of the part at R·x + t. R = Rz(rz)·Ry(ry)·Rx(rx)
with angles in degrees -- rotate about body X first, then Y, then Z --
right-handed and column-vector (CLAUDE.md). R and t are about the body
ORIGIN, never the anchor: that is what lets an author move the anchor without
moving any pose (spec §2.3, option A). The anchor only shapes the SWING
between poses (`interpolate`).

All values are SHIP units, body frame. `matrix4_model` is the one converter
to the renderer's MODEL units.
"""

import math

IDENTITY = (((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
            (0.0, 0.0, 0.0))


def _mat_mul(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3))
                       for j in range(3)) for i in range(3))


def _mat_vec(m, v):
    return tuple(m[i][0] * v[0] + m[i][1] * v[1] + m[i][2] * v[2]
                 for i in range(3))


def _transpose(m):
    return tuple(tuple(m[j][i] for j in range(3)) for i in range(3))


def euler_to_matrix(rx, ry, rz):
    """R = Rz(rz)·Ry(ry)·Rx(rx), degrees."""
    x, y, z = (math.radians(float(a)) for a in (rx, ry, rz))
    cx, sx, cy, sy, cz, sz = (math.cos(x), math.sin(x), math.cos(y),
                              math.sin(y), math.cos(z), math.sin(z))
    Rx = ((1.0, 0.0, 0.0), (0.0, cx, -sx), (0.0, sx, cx))
    Ry = ((cy, 0.0, sy), (0.0, 1.0, 0.0), (-sy, 0.0, cy))
    Rz = ((cz, -sz, 0.0), (sz, cz, 0.0), (0.0, 0.0, 1.0))
    return _mat_mul(Rz, _mat_mul(Ry, Rx))


def matrix_to_euler(R):
    """Inverse of `euler_to_matrix` (degrees). At gimbal lock (|ry| = 90)
    rx is set to 0 and rz absorbs the remaining rotation."""
    sy = -R[2][0]
    sy = max(-1.0, min(1.0, sy))
    ry = math.asin(sy)
    if abs(sy) < 1.0 - 1e-12:
        rx = math.atan2(R[2][1], R[2][2])
        rz = math.atan2(R[1][0], R[0][0])
    else:
        rx = 0.0
        rz = math.atan2(-R[0][1], R[1][1])
    return (math.degrees(rx), math.degrees(ry), math.degrees(rz))


def pose_from6(p6):
    tx, ty, tz, rx, ry, rz = (float(v) for v in p6)
    return (euler_to_matrix(rx, ry, rz), (tx, ty, tz))


def pose_to6(pose):
    R, t = pose
    rx, ry, rz = matrix_to_euler(R)
    return (float(t[0]), float(t[1]), float(t[2]), rx, ry, rz)


def apply(pose, x):
    R, t = pose
    r = _mat_vec(R, x)
    return (r[0] + t[0], r[1] + t[1], r[2] + t[2])


def apply_vector(pose, v):
    return _mat_vec(pose[0], v)


def inverse_apply(pose, x):
    R, t = pose
    return _mat_vec(_transpose(R), (x[0] - t[0], x[1] - t[1], x[2] - t[2]))


def is_identity(pose, eps=1e-9):
    R, t = pose
    I = IDENTITY[0]
    return (all(abs(R[i][j] - I[i][j]) <= eps for i in range(3) for j in range(3))
            and all(abs(c) <= eps for c in t))


def _axis_angle_matrix(axis, degrees):
    n = math.sqrt(sum(float(a) * float(a) for a in axis))
    if n <= 0.0:
        return IDENTITY[0]
    x, y, z = (float(a) / n for a in axis)
    th = math.radians(float(degrees))
    c, s, C = math.cos(th), math.sin(th), 1.0 - math.cos(th)
    return ((c + x * x * C, x * y * C - z * s, x * z * C + y * s),
            (y * x * C + z * s, c + y * y * C, y * z * C - x * s),
            (z * x * C - y * s, z * y * C + x * s, c + z * z * C))


def hinge_pose(pivot, axis, degrees):
    """The legacy hinge (spec §6): rotation about the line through `pivot`
    along `axis`. R = rot(axis, degrees), t = pivot - R·pivot."""
    R = _axis_angle_matrix(axis, degrees)
    rp = _mat_vec(R, pivot)
    return (R, (pivot[0] - rp[0], pivot[1] - rp[1], pivot[2] - rp[2]))


def _to_quat(R):
    tr = R[0][0] + R[1][1] + R[2][2]
    if tr > 0.0:
        s = math.sqrt(tr + 1.0) * 2.0
        return (0.25 * s, (R[2][1] - R[1][2]) / s, (R[0][2] - R[2][0]) / s,
                (R[1][0] - R[0][1]) / s)
    if R[0][0] > R[1][1] and R[0][0] > R[2][2]:
        s = math.sqrt(1.0 + R[0][0] - R[1][1] - R[2][2]) * 2.0
        return ((R[2][1] - R[1][2]) / s, 0.25 * s, (R[0][1] + R[1][0]) / s,
                (R[0][2] + R[2][0]) / s)
    if R[1][1] > R[2][2]:
        s = math.sqrt(1.0 + R[1][1] - R[0][0] - R[2][2]) * 2.0
        return ((R[0][2] - R[2][0]) / s, (R[0][1] + R[1][0]) / s, 0.25 * s,
                (R[1][2] + R[2][1]) / s)
    s = math.sqrt(1.0 + R[2][2] - R[0][0] - R[1][1]) * 2.0
    return ((R[1][0] - R[0][1]) / s, (R[0][2] + R[2][0]) / s,
            (R[1][2] + R[2][1]) / s, 0.25 * s)


def _from_quat(q):
    w, x, y, z = q
    return ((1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
            (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
            (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)))


def _slerp(q0, q1, u):
    d = sum(a * b for a, b in zip(q0, q1))
    if d < 0.0:
        q1, d = tuple(-c for c in q1), -d
    if d > 0.9995:
        q = tuple(a + (b - a) * u for a, b in zip(q0, q1))
    else:
        th = math.acos(d)
        s0 = math.sin((1.0 - u) * th) / math.sin(th)
        s1 = math.sin(u * th) / math.sin(th)
        q = tuple(s0 * a + s1 * b for a, b in zip(q0, q1))
    n = math.sqrt(sum(c * c for c in q))
    return tuple(c / n for c in q)


def interpolate(pose0, pose1, anchor, u):
    """Spec §4.1: the part swings about `anchor` while the anchor travels
    straight. R(u) = slerp(R0, R1, u); anchor(u) = lerp(R0·a+t0, R1·a+t1, u);
    x(u) = R(u)·(x - a) + anchor(u). Exact end poses for ANY anchor."""
    u = max(0.0, min(1.0, float(u)))
    if u <= 0.0:
        return pose0
    if u >= 1.0:
        return pose1
    R = _from_quat(_slerp(_to_quat(pose0[0]), _to_quat(pose1[0]), u))
    a0, a1 = apply(pose0, anchor), apply(pose1, anchor)
    au = tuple(p + (q - p) * u for p, q in zip(a0, a1))
    ra = _mat_vec(R, anchor)
    return (R, (au[0] - ra[0], au[1] - ra[1], au[2] - ra[2]))


def matrix4_model(pose, model_to_ship):
    """Column-major 4x4 for the native node transform: rotation R, and the
    translation converted SHIP -> MODEL units (divided by `model_to_ship`)."""
    R, t = pose
    k = 1.0 / float(model_to_ship)
    return (R[0][0], R[1][0], R[2][0], 0.0,
            R[0][1], R[1][1], R[2][1], 0.0,
            R[0][2], R[1][2], R[2][2], 0.0,
            t[0] * k, t[1] * k, t[2] * k, 1.0)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_part_pose.py -q`
Expected: all pass.

- [ ] **Step 5: Gate and commit**

Run `scripts/check_tests.sh` (expect the clean line), then:

```bash
git add engine/appc/part_pose.py tests/unit/test_part_pose.py
git commit -m "feat(articulation): part_pose -- rigid poses, swing about an anchor, legacy hinge

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `ArticulatedPartProperty` — anchor, transition, state poses, break fraction

**Files:**
- Modify: `engine/appc/articulated_part.py`
- Test: `tests/unit/test_articulated_part_poses.py` (create)

**Interfaces:**
- Consumes: `part_pose.pose_from6`, `hinge_pose`, `IDENTITY`, `STATES`.
- Produces on `ArticulatedPartProperty`:
  - setters `SetAnchor(x,y,z)`, `SetTransitionSeconds(s)`, `SetStatePose(state, tx,ty,tz, rx,ry,rz)`, `SetBreakFraction(f)`; legacy `SetPivot`, `SetAxis`, `SetStateAngle`, `SetDetachFraction` still accepted.
  - readers: `anchor` (3-tuple or None), `transition_seconds` (float, default 2.0), `pose_for(state) -> pose` (IDENTITY when unset), `pose6_for(state) -> p6 or None` (None when unset), `authored_states() -> tuple` (states with a pose, in STATES order), `break_fraction` (float or None).
  - `detach_fraction` stays as a read-only alias of `break_fraction` (its consumers are not touched until Task 4).
  - The OLD readers `pivot`, `axis`, `angle_for`, `angle_range` stay for now (Task 4 removes the consumers; Task 5 removes the readers).

**Legacy semantics (spec §3, §6):** legacy calls are stored as they arrive; on any READ of the new surface, a part that has any `SetStateAngle` but no `SetStatePose` for that state converts: `anchor = pivot` (default `(0,0,0)` when `SetPivot` was never called), `pose = hinge_pose(pivot, axis, angle)`. `SetStatePose` for a state wins over a legacy angle for the same state. `SetDetachFraction(f)` sets `break_fraction`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_articulated_part_poses.py`:

```python
"""ArticulatedPartProperty's pose surface (spec 2026-09-25 §3, §6)."""
import pytest

from engine.appc import articulated_part as ap
from engine.appc import part_pose as pp


def test_a_fresh_part_is_static_and_unbreakable():
    p = ap.ArticulatedPartProperty_Create("left wing")
    assert p.anchor is None
    assert p.transition_seconds == 2.0
    assert p.break_fraction is None
    assert p.authored_states() == ()
    for s in ap.STATES:
        assert pp.is_identity(p.pose_for(s))
        assert p.pose6_for(s) is None


def test_state_pose_round_trips():
    p = ap.ArticulatedPartProperty_Create("left wing")
    p.SetAnchor(-0.16, 0.0, 0.05)
    p.SetStatePose("warp", 0.1, 0.0, 0.2, 0.0, 30.0, 0.0)
    assert p.anchor == (-0.16, 0.0, 0.05)
    assert p.pose6_for("warp") == pytest.approx((0.1, 0.0, 0.2, 0.0, 30.0, 0.0))
    assert p.authored_states() == ("warp",)


def test_an_unknown_state_is_rejected():
    p = ap.ArticulatedPartProperty_Create("left wing")
    with pytest.raises(ValueError):
        p.SetStatePose("REd", 0, 0, 0, 0, 0, 0)


def test_transition_seconds_and_break_fraction():
    p = ap.ArticulatedPartProperty_Create("left wing")
    p.SetTransitionSeconds(3.5)
    p.SetBreakFraction(0.25)
    assert p.transition_seconds == 3.5
    assert p.break_fraction == 0.25
    assert p.detach_fraction == 0.25, "the old reader aliases the new value"


def test_legacy_detach_fraction_sets_break_fraction():
    p = ap.ArticulatedPartProperty_Create("head")
    p.SetDetachFraction(0.3)
    assert p.break_fraction == 0.3


def test_legacy_hinge_converts_to_anchor_and_poses():
    p = ap.ArticulatedPartProperty_Create("left wing")
    p.SetPivot(-0.16, 0.0, 0.05)
    p.SetAxis(0.0, 1.0, 0.0)
    p.SetStateAngle("cruise", 45.0)
    p.SetStateAngle("red", 0.0)
    assert p.anchor == (-0.16, 0.0, 0.05)
    x = (-1.0, 0.45, -0.67)
    want = pp.apply(pp.hinge_pose((-0.16, 0.0, 0.05), (0.0, 1.0, 0.0), 45.0), x)
    assert pp.apply(p.pose_for("cruise"), x) == pytest.approx(want)
    assert pp.is_identity(p.pose_for("red"))
    assert set(p.authored_states()) == {"cruise", "red"}


def test_legacy_hinge_without_a_pivot_anchors_at_the_origin():
    """Spec §10: matches today's default pivot."""
    p = ap.ArticulatedPartProperty_Create("fin")
    p.SetStateAngle("cruise", 10.0)
    assert p.anchor == (0.0, 0.0, 0.0)


def test_an_explicit_pose_wins_over_a_legacy_angle():
    p = ap.ArticulatedPartProperty_Create("left wing")
    p.SetStateAngle("warp", 45.0)
    p.SetStatePose("warp", 0, 0, 0, 0, 0, 0)
    assert pp.is_identity(p.pose_for("warp"))
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_articulated_part_poses.py -q` — Expected: `AttributeError` on `anchor`.

- [ ] **Step 3: Implement**

In `engine/appc/articulated_part.py`: in `__init__` add `self._anchor = None`, `self._transition = 2.0`, `self._poses = {}` (state -> p6), `self._pivot_set = False`. Keep `self._detach` as the single store for the break fraction. Add:

```python
    # ---- the pose surface (spec 2026-09-25) -------------------------------
    def SetAnchor(self, x, y, z):
        self._anchor = (float(x), float(y), float(z))

    def SetTransitionSeconds(self, seconds):
        self._transition = float(seconds)

    def SetStatePose(self, state, tx, ty, tz, rx, ry, rz):
        if state not in STATES:
            raise ValueError(
                "unknown articulation state %r; expected one of %r"
                % (state, STATES))
        self._poses[state] = tuple(float(v) for v in (tx, ty, tz, rx, ry, rz))

    def SetBreakFraction(self, fraction):
        self._detach = float(fraction)

    @property
    def anchor(self):
        """Swing centre (ship units, body frame), or None. A legacy hinge
        with no explicit anchor anchors at its pivot."""
        if self._anchor is not None:
            return self._anchor
        if self._angles:
            return self._pivot
        return None

    @property
    def transition_seconds(self):
        return self._transition

    @property
    def break_fraction(self):
        """Fraction of the ship's MAX hull accumulated ON this part that
        shears it, or None (never breaks)."""
        return self._detach

    def pose6_for(self, state):
        """(tx,ty,tz,rx,ry,rz) authored for `state`, or None. A legacy angle
        converts through the hinge."""
        if state in self._poses:
            return self._poses[state]
        if state in self._angles:
            from engine.appc import part_pose
            return part_pose.pose_to6(part_pose.hinge_pose(
                self._pivot, self._axis, self._angles[state]))
        return None

    def pose_for(self, state):
        """The part's pose in `state`; the NIF pose (identity) when unset."""
        from engine.appc import part_pose
        if state in self._poses:
            return part_pose.pose_from6(self._poses[state])
        if state in self._angles:
            return part_pose.hinge_pose(self._pivot, self._axis,
                                        self._angles[state])
        return part_pose.IDENTITY

    def authored_states(self):
        return tuple(s for s in STATES
                     if s in self._poses or s in self._angles)
```

`SetPivot` keeps writing `self._pivot`. Leave `detach_fraction` returning `self._detach`. Update the module docstring's format paragraph to list the new calls first and say the legacy four are still read.

- [ ] **Step 4: Run** `uv run pytest tests/unit/test_articulated_part_poses.py tests/unit/test_articulated_part.py -q` — all pass.

- [ ] **Step 5: Gate and commit**

```bash
git add engine/appc/articulated_part.py tests/unit/test_articulated_part_poses.py
git commit -m "feat(articulation): anchor, transition, per-state poses, break fraction on the part template

Legacy SetPivot/SetAxis/SetStateAngle/SetDetachFraction still load and
convert through the hinge.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Native `set_instance_node_transform`

**Files:**
- Modify: `native/src/host/host_bindings.cc` (beside `set_instance_node_rotation`, ~line 2256)
- Modify: `engine/host_io.py` (name table ~line 58; wrapper beside `set_instance_node_rotation` ~line 634)
- Test: `tests/unit/test_host_io_node_transform.py` (create)

**Interfaces:**
- Produces: Python `host_io.set_instance_node_transform(iid, node_name, m16) -> bool`; native `set_instance_node_transform(iid, node_name, m16)` where `m16` is a sequence of 16 floats, column-major, MODEL units, parent space. Override = `M · local_transform`; identity `M` erases the override. `set_instance_node_rotation` stays until Task 4 removes its last caller.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_host_io_node_transform.py`:

```python
"""host_io.set_instance_node_transform: the node-matrix binding (spec §5)."""
from engine import host_io


def test_the_binding_is_in_the_facade_table():
    """A binding missing from the table is how features have shipped inert."""
    assert "set_instance_node_transform" in host_io._BINDING_NAMES


def test_headless_or_fake_iid_is_false_not_an_error(monkeypatch):
    monkeypatch.setattr(host_io, "_h", None)
    assert host_io.set_instance_node_transform(3, "left wing",
                                               (1.0,) + (0.0,) * 15) is False


def test_the_matrix_is_passed_as_sixteen_floats(monkeypatch):
    seen = []

    class _H:
        def set_instance_node_transform(self, iid, node, m16):
            seen.append((iid, node, tuple(m16)))
            return True

    monkeypatch.setattr(host_io, "_h", _H())
    m = tuple(float(i) for i in range(16))
    assert host_io.set_instance_node_transform(7, "left wing", m) is True
    assert seen == [(7, "left wing", m)]
```

Before writing it, read `engine/host_io.py` lines ~40-70 and ~630-660: use the table's real name (the plan calls it `_BINDING_NAMES`; if it is named differently, use the real name in both the test and the edit) and mirror `set_instance_node_rotation`'s headless / fake-iid handling exactly.

- [ ] **Step 2: Run** — expect failure (name not in table / no attribute).

- [ ] **Step 3: Implement**

In `host_bindings.cc`, after `set_instance_node_rotation`:

```cpp
    m.def("set_instance_node_transform",
          [](scenegraph::InstanceId id, const std::string& node_name,
             const std::vector<float>& m16) -> bool {
              // A full rigid pose per node (spec 2026-09-25 §5): the override
              // becomes M * local, M column-major in the node's PARENT
              // (model) space, MODEL units. Identity clears the override so a
              // part at its NIF pose leaves an EMPTY map (static node walk).
              if (m16.size() != 16) return false;
              auto* in = g_world.get(id);
              if (!in) return false;
              const assets::Model* m2 = resolve_model(in->model_handle);
              if (!m2) return false;
              const int idx = renderer::resolve_overridden_node(
                  *m2, node_name, in->node_overrides);
              if (idx < 0) return false;
              glm::mat4 M(1.0f);
              for (int c = 0; c < 4; ++c)
                  for (int r = 0; r < 4; ++r)
                      M[c][r] = m16[static_cast<std::size_t>(c * 4 + r)];
              if (M == glm::mat4(1.0f)) {
                  in->node_overrides.erase(idx);
                  return true;
              }
              in->node_overrides[idx] =
                  M * m2->nodes[static_cast<std::size_t>(idx)].local_transform;
              return true;
          },
          py::arg("iid"), py::arg("node_name"), py::arg("m16"),
          "Set a named node's pose: override = M * local, M a column-major "
          "4x4 (16 floats) in the node's PARENT space, MODEL units. Identity "
          "clears the override. False when the instance, model or node is "
          "absent, or m16 is not 16 values.");
```

(`<vector>` is already available via pybind11/stl; if the file lacks `#include <pybind11/stl.h>`, check how other bindings accept lists and follow that.)

In `host_io.py`: add `"set_instance_node_transform"` to the table and a wrapper mirroring `set_instance_node_rotation`'s guards:

```python
def set_instance_node_transform(iid, node_name: str, m16) -> bool:
    """Set `node_name`'s pose on instance `iid`: a column-major 4x4 (16
    floats) in the node's PARENT space, MODEL units, applied as M * local.
    Identity clears the override. False headless, on a fake iid, or when the
    model has no such node -- "nothing to articulate", never "binding
    missing" (a stale build trips validate_bindings() at boot)."""
```

with the body copied from `set_instance_node_rotation`'s guard structure, calling `_h.set_instance_node_transform(iid, node_name, [float(v) for v in m16])`.

- [ ] **Step 4: Build and run**

Run: `cmake --build build -j && uv run pytest tests/unit/test_host_io_node_transform.py -q` — pass. Then confirm the built module has it:
`uv run python -c "import sys; sys.path.insert(0,'build/python'); import _dauntless_host as h; print(hasattr(h,'set_instance_node_transform'))"` → `True`.

- [ ] **Step 5: Gate and commit**

```bash
git add native/src/host/host_bindings.cc engine/host_io.py tests/unit/test_host_io_node_transform.py
git commit -m "feat(host): set_instance_node_transform -- a full pose matrix per node

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: The runtime switches from angles to poses

**Files:**
- Modify: `engine/appc/articulation.py`, `engine/appc/part_severance.py`, `engine/appc/hull_bounds.py`, `engine/host_loop.py` (`_articulate_emitter_light` ~1470-1510, `_sync_ship_articulation` ~7118-7165), `engine/host_io.py` (remove `set_instance_node_rotation` wrapper + table entry), `native/src/host/host_bindings.cc` (remove `set_instance_node_rotation`), `engine/ui/ship_property_viewer_panel.py` (only the two references to `_articulation_angles`/`angle_for` that break — keep its UI behaviour; Task 6 rewrites it), `engine/ui/glow_region_overlay.py` (docstring only)
- Modify tests: every file in this list that fails after the change, re-pointed at poses without weakening what it asserts: `tests/conftest.py`, `tests/unit/test_articulation.py`, `test_articulation_states.py`, `test_hull_bounds_parts.py`, `test_hull_breakup.py`, `test_part_severance.py`, `test_part_severance_emitters.py`, `test_spv_anchor_pose.py`, `test_spv_part_box_overlay.py`, `test_spv_part_controls.py`, `test_spv_pin_pose_cache.py`, `test_subsystem_part_parenting.py`, `test_apply_hit_articulated_splash.py`, `test_emitter_lights_follow_parts.py`, `test_target_offset_articulation.py`, `tests/ui/test_ship_property_viewer_panel_part.py`
- Test: `tests/unit/test_articulation_transitions.py` (create)

**Interfaces:**
- Consumes: `part_pose.*`, `ArticulatedPartProperty.anchor/transition_seconds/pose_for/authored_states/break_fraction`, `host_io.set_instance_node_transform`.
- Produces in `articulation`:
  - `pose_for_part(ship, part) -> pose` — reads `ship._articulation_poses[name]`, IDENTITY when absent.
  - `target_pose(part, state) -> pose` — `part.pose_for(state)`.
  - `tick_ship(ship, dt)` — advances transitions (below).
  - `part_transform_point(ship, point, part=None)` — unchanged signature; applies the live pose.
  - `part_transform_vector(ship, vec, part_name) -> vec` — rotation only.
  - `force_pose(ship, state_or_None)` — snaps `_articulation_poses` (None → every part identity) and clears transitions.
  - `force_part_pose(ship, part_name, pose)` — snaps ONE part, every other part identity (Task 6 uses it).
  - Removed: `rotation_for`, `point_at_angle`, `vector_at_angle`, `angle_for_part`, `ease_angle`, `target_angle`, `_part_range`, `_swing_range`, `TRAVEL_SECONDS`, the `Part` NamedTuple, `_rotate_about`.
- Ship state: `ship._articulation_poses` ({name: pose}) replaces `ship._articulation_angles`; `ship._articulation_transitions` ({name: (pose0, target_state, u)}).

**Transition rule (spec §4.1):** per tick, for each part: `target = part.pose_for(state)`. If there is no transition, or its `target_state` differs from `state`, and the current pose is not already equal to `target` (within `1e-9`, via `part_pose`'s element compare), start a new one: `pose0 = current pose`, `u = 0`. Advance `u += dt / max(part.transition_seconds, 1e-6)`; current pose = `part_pose.interpolate(pose0, target, anchor, u)` with `anchor = part.anchor or (0,0,0)`; at `u >= 1` store `target` exactly and drop the transition.

- [ ] **Step 1: Write the new failing tests**

Create `tests/unit/test_articulation_transitions.py`:

```python
"""Transitions between state poses (spec 2026-09-25 §4.1)."""
import math

import pytest

from engine.appc import articulation, articulated_part as ap, part_pose as pp


def _part():
    p = ap.ArticulatedPartProperty_Create("left wing")
    p.SetAnchor(0.0, 0.0, 0.0)
    p.SetTransitionSeconds(2.0)
    p.SetStatePose("cruise", 0.0, 0.0, 0.0, 0.0, 90.0, 0.0)
    return p


class _Ship:
    def __init__(self, part, state):
        self._part, self.state = part, state
        self._articulation_leaf = "rigtest"


@pytest.fixture
def rig(monkeypatch):
    part = _part()
    monkeypatch.setattr(articulation, "rig_for",
                        lambda leaf: (part,) if leaf == "rigtest" else ())
    monkeypatch.setattr(articulation, "state_for", lambda ship: ship.state)
    return part


def _tip(ship, part):
    return pp.apply(articulation.pose_for_part(ship, part), (1.0, 0.0, 0.0))


def test_a_transition_takes_transition_seconds(rig):
    ship = _Ship(rig, "cruise")
    articulation.tick_ship(ship, 1.0)
    assert 0.0 < math.dist(_tip(ship, rig), (1.0, 0.0, 0.0)) < math.sqrt(2)
    articulation.tick_ship(ship, 1.0)
    assert _tip(ship, rig) == pytest.approx(
        pp.apply(rig.pose_for("cruise"), (1.0, 0.0, 0.0)), abs=1e-9)


def test_interrupted_transition_starts_from_the_current_pose(rig):
    """Review focus #2: never snaps back to the start."""
    ship = _Ship(rig, "cruise")
    articulation.tick_ship(ship, 1.0)
    mid = _tip(ship, rig)
    ship.state = "red"                     # red = NIF pose (identity)
    articulation.tick_ship(ship, 1e-6)
    assert math.dist(_tip(ship, rig), mid) < 1e-3, "must not jump"
    articulation.tick_ship(ship, 5.0)
    assert _tip(ship, rig) == pytest.approx((1.0, 0.0, 0.0), abs=1e-9)


def test_a_settled_part_does_not_restart(rig):
    ship = _Ship(rig, "cruise")
    articulation.tick_ship(ship, 5.0)
    articulation.tick_ship(ship, 0.1)
    assert not getattr(ship, "_articulation_transitions", {})


def test_force_part_pose_poses_only_that_part(rig):
    ship = _Ship(rig, "red")
    articulation.force_part_pose(ship, "left wing", rig.pose_for("cruise"))
    assert _tip(ship, rig) == pytest.approx(
        pp.apply(rig.pose_for("cruise"), (1.0, 0.0, 0.0)))
    articulation.force_pose(ship, None)
    assert _tip(ship, rig) == pytest.approx((1.0, 0.0, 0.0))
```

- [ ] **Step 2: Run** — expect failures (`pose_for_part` missing).

- [ ] **Step 3: Rewrite `articulation.py`'s pose core**

Replace the angle machinery with the pose machinery per **Interfaces** and **Transition rule** above. `part_transform_point` keeps its attribution/severance logic and ends with:

```python
    pose = pose_for_part(ship, part)
    if part_pose.is_identity(pose):
        return point
    return part_pose.apply(pose, point)
```

`part_transform_vector(ship, vec, part_name)`: look up the part by name, return `part_pose.apply_vector(pose_for_part(ship, part), vec)` (identity → unchanged; detached → unchanged). `force_pose(ship, state)`: `{name: (IDENTITY if state is None else part.pose_for(state))}` into `ship._articulation_poses`, `ship._articulation_transitions = {}`; same try/except tolerance as today. Rewrite the module docstring's "FOUR STATES" / "FRAME AND MATH" / "THE SAME HINGE" sections for poses (keep the three-places-must-agree point; the three places are now the render sync's matrix, `part_transform_point`, and the inverse-pose box query).

- [ ] **Step 4: Switch the consumers**

- `part_severance.part_for_live_point`: replace the per-part `point_at_angle(part, point, -angle)` with `part_pose.inverse_apply(articulation.pose_for_part(ship, part), point)`, skipping identity poses. `rest_point_for_live_point`: same inverse.
- `hull_bounds._travel_reach(part, centre)`: replace the hinge-arc maths with the conservative bound that holds for any sequence of interrupted transitions (spec §10): with `a = part.anchor`, if `a is None` return `|centre|`; else `max(|apply(P, centre)| for P in [IDENTITY] + [part.pose_for(s) for s in part.authored_states()])` and `|centre - a| + max(|apply(P, a)| for the same P)`, returning the larger. Delete `_angle_extremes`. Update its docstring: the anchor travels inside the convex hull of its end positions and rotation preserves `|centre - a|`, so the bound encloses every reachable position.
- `host_loop._articulate_emitter_light`: replace the angle lookup + `point_at_angle`/`vector_at_angle` with the part's pose: positions through `part_pose.apply`, `direction`/`up` through `part_pose.apply_vector`; identity → return `d` untouched.
- `host_loop._sync_ship_articulation`: `pose = tuple(part_pose.pose_to6(articulation.pose_for_part(ship, p)) for p in parts)` for the change guard; per non-detached part push `host_io.set_instance_node_transform(iid, part.GetName(), part_pose.matrix4_model(articulation.pose_for_part(ship, part), articulation.MODEL_TO_SHIP))`. Keep the detached-part `continue` and the docstring's read-only / no-forced-pose points, rewritten for poses.
- Remove `set_instance_node_rotation` from `host_bindings.cc`, `host_io.py` (wrapper + table) once nothing calls it (`grep -rn set_instance_node_rotation engine native tests` must return nothing but the removal).
- `engine/ui/ship_property_viewer_panel.py`: only make it import and run (e.g. its `_baked_part_spec` may keep reading the legacy readers until Task 6); do not redesign it here.
- `tests/conftest.py`: `bop_fixture_rig()` becomes anchor + poses built with `part_pose.hinge_pose` from the same numbers (anchor `(±0.16, 0, 0.05)`, cruise/yellow/warp = hinge ±45°, red unset, `SetBreakFraction(0.20)`), emitted through `SetStatePose(*pose_to6(...))`.

- [ ] **Step 5: Re-point the existing tests**

Run `uv run pytest tests -q -x --deselect tests/unit/test_engineer_emitters.py::test_shield_level_change_announces` and fix each failure by translating angles to poses: a test that set `ship._articulation_angles = {name: part.angle_for("cruise")}` now sets `ship._articulation_poses = {name: part.pose_for("cruise")}`; a test that set a FRACTION of the cruise angle (`angle * deflection`) now uses `part_pose.interpolate(IDENTITY, part.pose_for("cruise"), part.anchor, deflection)` (exactly equivalent for a hinge, Task 1's `test_legacy_hinge_interpolation_is_the_old_linear_angle_ease`). Tests of retired functions (`rotation_for`, `ease_angle`, `TRAVEL_SECONDS`, the `Part` tuple) are deleted only when Task 1/4's new tests cover the same behaviour; list every deleted test in the report with the new test that replaces it. Never loosen an assertion to make it pass.

- [ ] **Step 6: Build, run everything, gate**

`cmake --build build -j`, then `uv run pytest tests/unit/test_articulation_transitions.py -q`, then `scripts/check_tests.sh` → clean line.

- [ ] **Step 7: Commit** (explicit pathspecs of every file touched)

```bash
git commit -m "refactor(articulation): the runtime moves from hinge angles to full poses

Each part eases a transition between state poses, swinging about its anchor
(spec 2026-09-25 §4). Every consumer -- mounts, pins, lights, splash,
targeting, severance attribution, hull bounds, the render sync -- reads the
pose; the renderer takes a node matrix. The BoP behaves identically: its
legacy hinge data converts exactly.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Migrate the Bird of Prey data and retire the legacy readers

**Files:**
- Modify: `engine/appc/hardpoint_overrides.py` (the `_birdofprey` part blocks — regenerated through the writer, never hand-edited), `engine/appc/articulated_part.py` (remove the public legacy READERS `pivot`, `axis`, `angle_for`, `angle_range` and `detach_fraction`; keep the legacy SETTERS), `engine/appc/articulation.py` (`detachable_for` reads `break_fraction`), `engine/appc/hardpoint_override_writer.py` (docstring: part calls are the new four), `tests/unit/test_authored_part_data.py` (invariants for the new fields)
- Test: `tests/unit/test_bop_pose_migration.py` (create)

**Interfaces:**
- Consumes: `ArticulatedPartProperty.pose6_for`, the writer's `set_part` / `emit` / `read_models_from_source`.
- Produces: the BoP's wings authored as `SetAnchor`, `SetTransitionSeconds(2.0)`, `SetStatePose` for cruise/yellow/warp, `SetBreakFraction(0.2)`; the head as only `SetBreakFraction` if the committed file has it (it does not today — do not add one).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_bop_pose_migration.py`:

```python
"""The committed Bird of Prey rig is in the new format and moves exactly as
the old hinge did (spec 2026-09-25 §6)."""
import math

import pytest

from engine.appc import hardpoint_overrides, part_pose as pp
from engine.appc.articulated_part import ArticulatedPartProperty

OLD = {  # the pre-migration hinge rig, the reference
    "left wing": ((-0.16, 0.0, 0.05), 45.0),
    "left wing01": ((0.16, 0.0, 0.05), -45.0),
}
AXIS = (0.0, 1.0, 0.0)


def _parts():
    import App
    mgr = App.g_kModelPropertyManager
    mgr.ClearLocalTemplates()
    try:
        hardpoint_overrides.apply("birdofprey")
        return {p.GetName(): p for p in getattr(mgr, "_local", {}).values()
                if isinstance(p, ArticulatedPartProperty)}
    finally:
        mgr.ClearLocalTemplates()


def test_the_committed_file_uses_only_the_new_calls():
    import inspect
    src = inspect.getsource(hardpoint_overrides._birdofprey)
    for legacy in ("SetPivot", "SetAxis", "SetStateAngle", "SetDetachFraction"):
        assert legacy not in src, legacy


@pytest.mark.parametrize("name", sorted(OLD))
def test_every_state_lands_where_the_old_hinge_put_it(name):
    pivot, cruise_deg = OLD[name]
    part = _parts()[name]
    assert part.anchor == pytest.approx(pivot)
    samples = [(-1.0, 0.45, -0.67), (1.0, 0.45, -0.67), (0.3, -0.2, 0.1)]
    for state, deg in (("cruise", cruise_deg), ("yellow", cruise_deg),
                       ("warp", cruise_deg), ("red", 0.0)):
        ref = pp.hinge_pose(pivot, AXIS, deg)
        for x in samples:
            assert pp.apply(part.pose_for(state), x) == pytest.approx(
                pp.apply(ref, x), abs=1e-9), (name, state)


@pytest.mark.parametrize("name", sorted(OLD))
def test_midway_to_cruise_is_the_old_half_angle(name):
    pivot, cruise_deg = OLD[name]
    part = _parts()[name]
    mid = pp.interpolate(pp.IDENTITY, part.pose_for("cruise"), part.anchor, 0.5)
    ref = pp.hinge_pose(pivot, AXIS, cruise_deg / 2.0)
    x = (math.copysign(1.0, pivot[0]), 0.45, -0.67)
    assert pp.apply(mid, x) == pytest.approx(pp.apply(ref, x), abs=1e-9)


def test_both_wings_still_break_at_twenty_percent_in_two_seconds():
    parts = _parts()
    for name in OLD:
        assert parts[name].break_fraction == pytest.approx(0.20)
        assert parts[name].transition_seconds == 2.0
```

- [ ] **Step 2: Run** — `test_the_committed_file_uses_only_the_new_calls` fails (the file still has `SetPivot`).

- [ ] **Step 3: Regenerate the BoP block through the writer**

Write a throwaway script in the scratchpad (do NOT commit it) that: `read_models(...)` the current `hardpoint_overrides.py` (read the writer's module to find the exact reader entry point and how `set_part` replaces a part), builds for each wing the new call list — `("SetAnchor", anchor)`, `("SetTransitionSeconds", (2.0,))`, one `("SetStatePose", (state,) + pose6)` per state in `part.authored_states()` except states whose pose is identity (red), `("SetBreakFraction", (fraction,))` — applies it with `set_part`, and writes the result with the writer's own emit + atomic write path. Diff the result: only the two `_birdofprey` part blocks may change. Delete the stale `.pyc` (Global Constraints).

- [ ] **Step 4: Retire the legacy readers**

Remove `pivot`, `axis`, `angle_for`, `angle_range`, `detach_fraction` properties from `ArticulatedPartProperty` (keep the legacy setters and their private stores, which `pose_for`/`anchor` still read). `articulation.detachable_for` reads `break_fraction`. `grep -rn "\.angle_for(\|\.detach_fraction\|\.pivot\b\|\.axis\b\|angle_range" engine tests` — fix every remaining reader (tests included) to the new surface. Update `tests/unit/test_authored_part_data.py`'s checker: `break_fraction` in (0, 1]; anchor finite when present; every pose6 finite; `transition_seconds` > 0; a part with any authored pose has an anchor; node-name check unchanged; plus a checker unit test for each new rule (a broken rig must be CAUGHT).

- [ ] **Step 5: Run and gate**

`uv run pytest tests/unit/test_bop_pose_migration.py tests/unit/test_authored_part_data.py tests/unit/test_hardpoint_overrides_canonical.py -q`, then `scripts/check_tests.sh` → clean.

- [ ] **Step 6: Commit** (explicit pathspecs)

```bash
git commit -m "refactor(articulation): migrate the Bird of Prey to anchors and state poses

Regenerated through the writer; every state and the mid-swing land exactly
where the old hinge put them. The legacy setters still load; the legacy
readers are gone.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: SPV part-node model (Python)

**Files:**
- Modify: `engine/ui/ship_property_viewer.py` (part-node selection state, `part_save_edits` for the new calls), `engine/ui/ship_property_viewer_panel.py` (part staging spec, node tree payload, actions, toast, lock, per-part posing, save)
- Delete / rewrite tests that assert the removed controls: `tests/unit/test_spv_part_controls.py`, `tests/unit/test_spv_model_parts_pane.py` (if present), `tests/ui/test_ship_property_viewer_panel_part.py` — replaced by the new file below; list every removed test and its replacement in the report.
- Test: `tests/ui/test_spv_part_nodes.py` (create)

**Interfaces:**
- Staged part spec (replaces `{"pivot","axis","angles","fraction"}`):
  `{"anchor": (x,y,z) | None, "transition": float, "poses": {state: p6}, "break": float | None}`.
  Baked spec comes from the template: `anchor=p.anchor`, `transition=p.transition_seconds`, `poses={s: p.pose6_for(s) for s in p.authored_states()}`, `break=p.break_fraction`.
- Node selection (module-level in `ship_property_viewer`, beside `_selected_model_part_name`): `select_part_node(part_name, kind)` / `selected_part_node() -> (part_name, kind) | None` where `kind` is `"anchor"`, `"breakage"`, or a state name; selecting a part ROW (existing `select_model_part`) clears the node selection; `reset_model_parts()` clears it too.
- Actions (panel `dispatch_event`):
  - `part/add_anchor:<name>` — anchor = the part's derived box centre (`_spv.selected_part_box`-style lookup via `self._model_part_nodes` bounds for `name`), or `(0,0,0)` if no box; no-op if present.
  - `part/add_state:<json {"name","state"}>` — refused with toast `"Add an anchor first — transformations swing around it"` when the effective anchor is None; no-op if that state already has a pose; else pose6 = `(0,0,0,0,0,0)`.
  - `part/make_breakable:<name>` — `break = 0.20`; no-op if present.
  - `part/remove:<json {"name","kind"}>` — removes that node; removing `"anchor"` while any pose exists is refused with toast `"Remove the transformations first — they swing around the anchor"`.
  - `part/select_node:<json {"name","kind"}>` — sets the node selection; clears subsystem/light/emitter selection like `model_parts/select` does.
  - `part/set_transition:<json {"name","seconds"}>` (seconds > 0), `part/set_break:<json {"name","percent"}>` (0 < percent ≤ 100 → `break = percent/100`).
  - Removed: `part/preview:`, `part/set_angle:`, `part/set_detach:`.
- Toast: `self._toast = (text, expires_at_wall_time)`; payload key `"toast": text | None` while unexpired (3 s, `time.monotonic()`).
- Posing: selecting a state node calls `articulation.force_part_pose(ship, name, pose_from6(p6))` and refreshes pins (`_refresh_world_positions`); selecting anything else (or `open()`/`close()`) calls `articulation.force_pose(ship, None)` and refreshes. Mount lock: `_mount_lock_state_and_reason()` → locked with reason `"Posing <Label> Transformation on <part> — mount editing is locked"` while a state node is selected; the `K` dev override keeps its existing lock behaviour.
- Payload `"model_parts"`: `{"expanded", "show_all", "selected_box", "toast", "mount_editing_enabled", "mount_editing_reason", "rows"}` where `rows` is a flat list in display order: part rows `{"kind": "part", "name", "depth": 0, "chosen", "dirty", "has_anchor", "missing_states": [...], "breakable"}` each followed by its child rows `{"kind": "anchor"|"state"|"breakage", "part", "state"?, "label", "depth": 1, "chosen", "value"?}` — `label` is `"Anchor"`, `"<Label> Transformation"`, `"Breakage"`; `value` is `transition` for the anchor and the break PERCENT for breakage.
- Save: `part_save_edits` emits, per part: `("SetAnchor", anchor)` if set, `("SetTransitionSeconds", (t,))` if an anchor is set, one `("SetStatePose", (state,)+p6)` per pose in STATES order, `("SetBreakFraction", (f,))` if set. A part whose spec is empty emits nothing (existing rule).

- [ ] **Step 1: Write the failing tests**

Create `tests/ui/test_spv_part_nodes.py`. Build the panel with the same fixture pattern as `tests/ui/test_ship_property_viewer_panel_part.py` (read it first; reuse its `make_panel` fixture shape and the fake nodes list for `model_nodes`, three-level, with `left wing` and `head`). Tests (each asserts on the payload or `_pending_part`, never on a private helper's return alone):

```python
def test_add_anchor_starts_at_the_parts_box_centre(make_panel): ...
    # dispatch part/add_anchor:left wing -> pending anchor == box centre;
    # the tree shows an "Anchor" child under "left wing"

def test_add_transformation_without_anchor_toasts_and_changes_nothing(make_panel): ...
    # part/add_state:{"name":"left wing","state":"warp"} with no anchor ->
    # payload toast == "Add an anchor first — transformations swing around it";
    # _pending_part unchanged; no "Warp Transformation" row

def test_each_state_can_be_added_once(make_panel): ...
    # add anchor, add warp twice -> exactly one Warp row; missing_states excludes warp

def test_remove_anchor_with_poses_is_refused(make_panel): ...
    # anchor + warp, remove anchor -> toast, anchor still present

def test_selecting_a_transformation_poses_only_that_part_and_locks_mounts(make_panel): ...
    # set a warp pose6 with ry=30 on "left wing"; select_node warp ->
    # ship._articulation_poses["left wing"] equals pose_from6(p6);
    # every other part identity; payload mount_editing_enabled is False with the reason;
    # a select_pin: action is refused

def test_selecting_anything_else_returns_to_the_nif_pose(make_panel): ...

def test_breakage_is_edited_as_a_percentage(make_panel): ...
    # make_breakable -> value 20; set_break percent 35 -> pending break 0.35;
    # set_break percent 0 and 150 are refused

def test_transition_seconds_must_be_positive(make_panel): ...

def test_save_emits_only_the_new_calls_and_round_trips(make_panel): ...
    # anchor + warp + breakable, save -> writer edits contain SetAnchor,
    # SetTransitionSeconds, SetStatePose("warp", ...), SetBreakFraction and none
    # of SetPivot/SetAxis/SetStateAngle/SetDetachFraction; read the emitted text
    # back with the writer's read_models_from_source and get the same calls

def test_every_part_edit_is_undoable(make_panel): ...
    # add anchor then undo -> no anchor
```

Write each body in full (the comments give the exact assertions). 

- [ ] **Step 2: Run** — expect failures on the new actions.

- [ ] **Step 3: Implement** per Interfaces, reusing the panel's existing patterns: `_effective_part`/`_stage_part_field` keep their whole-spec-per-edit shape with the new keys; the node tree is built in the method that builds `"model_parts"` today; action strings join `_dispatch_event_inner` beside the existing `model_parts/*` branches; every staging path sets `self._last_pushed = None`. Delete the `part/preview`, `part/set_angle`, `part/set_detach` branches and `_set_part_preview`; keep `_mount_lock_state_and_reason`'s `K`-override arm.

- [ ] **Step 4: Run** the new file plus `tests/unit -k "spv or part"` and the gate.

- [ ] **Step 5: Commit** (explicit pathspecs)

```bash
git commit -m "feat(spv): part rules are Anchor / State Transformation / Breakage nodes

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: SPV part tree in CEF

**Files:**
- Modify: `native/assets/ui-cef/js/ship_property_viewer.js` (`renderSPVModelParts`, remove `spvPartControlsHtml` and its three `window.shipPropertyViewerPart*` handlers), `native/assets/ui-cef/index.html` (context-menu items; toast element), `native/assets/ui-cef/css/hello.css`
- Test: `tests/ui/test_spv_part_tree_cef.py` (create) — static checks of the JS/HTML text, the project's existing style for CEF assertions (find an existing `tests/ui/*cef*` or JS-text test and follow it).

**Interfaces:**
- Consumes Task 6's payload `model_parts.rows`, `model_parts.toast`, and actions `part/*`.
- Rows render with the subsystem tree's classes (`spv-sys-row`, `spv-sys-row--child`, `--chosen`, `--dirty`, indent `10 + depth*14` px). Clicking a part row sends `model_parts/select:<name>`; a child row sends `part/select_node:{"name","kind"}`.
- Right-click on a part row opens the existing `#spv-ctxmenu` with part items: **Add Anchor** (hidden when `has_anchor`), **Add State Transformation ▸** listing `missing_states` as their labels (Cruising / Yellow Alert / Red Alert / Warp) — each sends `part/add_state:` — and **Make Breakable** (hidden when `breakable`). Right-click on a child row: **Remove** → `part/remove:`.
- The Anchor row, when chosen, renders an inline numeric field "Transition time (s)" → `part/set_transition:`. The Breakage row, when chosen, renders "Breaks off after taking [n]% of the ship's hull strength" → `part/set_break:` with `percent`.
- Toast: `#spv-toast`, top-centre of the SPV, shown while `model_parts.toast` is non-null, hidden otherwise.

- [ ] **Step 1: Write the failing static test** asserting: the three removed handler names are absent from the JS; `part/select_node:`, `part/add_anchor:`, `part/add_state:`, `part/make_breakable:`, `part/remove:`, `part/set_transition:`, `part/set_break:` each appear; `id="spv-toast"` exists in `index.html`; the labels `Add Anchor`, `Add State Transformation`, `Make Breakable`, `Transition time (s)`, `of the ship's hull strength` appear.

- [ ] **Step 2: Run** — fails.

- [ ] **Step 3: Implement** following `spvRowHtml`'s idioms and the existing context-menu code (`spvShowMenuItems`, `#spv-ctxmenu`); escape names exactly as `renderSPVModelParts` does today.

- [ ] **Step 4: Run** the test and the gate.

- [ ] **Step 5: Commit** (explicit pathspecs)

```bash
git commit -m "feat(spv): Model Parts renders as a node tree with menus, inline fields and a toast

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: SPV gizmos edit anchors and poses

**Files:**
- Modify: `engine/ui/ship_property_viewer_panel.py` (`_active_transform_target`, `_target_pos_of`, the transform-drag apply, `_rotate_target`, `_begin_ring_drag`, `_apply_ring_drag_angle`, `transform_coords`, `rotate_values`, `_mirror_target_rotation`, rotate/coord copy-paste-nudge branches that switch on `t[0] == "part"`)
- Test: `tests/ui/test_spv_part_gizmos.py` (create)

**Interfaces:**
- Transform targets replace `("part", name)` with `("part_anchor", name)` (anchor node selected) and `("part_pose", name, state)` (state node selected). A part ROW or Breakage node is not a transform target (None).
- `_target_pos_of`: anchor → the anchor; pose → the POSED anchor `apply(pose_from6(p6), anchor)`.
- Move tool: anchor → sets `anchor`; pose → the dragged body-frame delta `d` adds to the pose translation (`t += d`).
- Rotate tool: only for `("part_pose", name, state)`. Ring `k` (body axis `e_k`) by `d_body` radians about the grab-time posed anchor `q`: `R' = rot(e_k, d)·R_grab`, `t' = rot(e_k, d)·(t_grab − q) + q`; store `pose_to6((R', t'))`. The anchor node has no rotate target.
- `transform_coords()` for a pose shows its translation (`tx,ty,tz`); `rotate_values()` for a pose shows `rx, ry, rz` degrees and editing a field sets that Euler component.
- Mirror (`_mirror_target_rotation`): for a pose, reflect across ship X: `(tx,ty,tz,rx,ry,rz) → (−tx, ty, tz, rx, −ry, −rz)`; for an anchor, `x → −x`.

- [ ] **Step 1: Write the failing tests** (`tests/ui/test_spv_part_gizmos.py`, same fixture as Task 6):
  - `test_anchor_node_is_a_move_target_at_the_anchor`
  - `test_moving_the_anchor_node_sets_the_anchor`
  - `test_anchor_move_leaves_state_poses` — author a warp pose, move the anchor by `(0.1, 0, 0)`, assert the warp pose6 is unchanged (review focus #1)
  - `test_pose_move_adds_to_the_translation`
  - `test_pose_ring_drag_rotates_about_the_posed_anchor` — anchor `(−0.16, 0, 0.05)`, identity pose, ring 1 (Y) by +45° → the stored pose equals `hinge_pose(anchor, (0,1,0), 45)` to 1e-9 and the posed anchor stays put
  - `test_rotate_values_show_and_edit_the_euler_angles`
  - `test_mirror_reflects_a_pose_across_ship_x`
  - `test_a_part_row_or_breakage_node_has_no_gizmo`

- [ ] **Step 2: Run** — fail.

- [ ] **Step 3: Implement** per Interfaces; every `t[0] == "part"` branch becomes the two new kinds; use `part_pose` for all maths (`euler_to_matrix`, `matrix_to_euler`, `apply`) and `ship_property_viewer.rotate_about_axis` only for the ring-axis rotation matrix if convenient. `grep -n '"part"' engine/ui/ship_property_viewer_panel.py` must return no transform-target uses afterwards.

- [ ] **Step 4: Run** the new tests, Task 6's tests, and the gate.

- [ ] **Step 5: Commit** (explicit pathspecs)

```bash
git commit -m "feat(spv): Move and Rotate author a part's anchor and its state poses

Rotation is about the posed anchor; moving the anchor never moves a pose.
Not live-verified.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Live verification (Mark, after Task 8)

1. BoP in QuickBattle, SPV → Model Parts: `left wing` shows Anchor, Cruising / Yellow Alert / Warp Transformation, Breakage (migrated).
2. Select Warp Transformation: the wing takes the warp pose, mounts lock with the reason; Rotate a ring and Move — the wing follows; Save.
3. Warp: the wings swing (not slide) to the new pose.
4. Move the Anchor: the poses stay where they were; only the swing changes.
5. Right-click `head` → Add State Transformation without an anchor → toast, nothing added.
6. Breakage reads "Breaks off after taking 20% of the ship's hull strength".
7. Revert authored data afterwards if it was a test.
