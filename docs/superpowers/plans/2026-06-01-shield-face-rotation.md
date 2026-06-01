# Rotation-correct Shield Face Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the world-frame dominant-axis selection in `engine.appc.combat._shield_face_from_hit_point` with a body-frame transform via the existing `_body_frame_delta` helper, so shield-face damage attribution is correct when the target ship is rotated.

**Architecture:** Single-file behaviour change. `_shield_face_from_hit_point` keeps its `(ship, hit_point) -> int` signature; only the source of the dominant-axis triple changes from raw world delta to `_body_frame_delta(ship, hit_point)`. Legacy fixture compatibility is inherited from `_body_frame_delta`'s identity fallback for ships without `GetWorldRotation`.

**Tech Stack:** Python 3, `engine.appc.math` (TGPoint3, TGMatrix3 with `MakeXRotation`/`MakeYRotation`/`MakeZRotation`/`MakeRotation`/`GetCol`), pytest. No new dependencies.

**Spec:** [`docs/superpowers/specs/2026-06-01-shield-face-rotation-design.md`](../specs/2026-06-01-shield-face-rotation-design.md).
**Branch:** `feature/shield-face-rotation` (already created from `main`).

## File Structure

- **Modify:** `engine/appc/combat.py` — rewrite `_shield_face_from_hit_point` body (lines 186-204). No signature, no other function, no module-level change.
- **Create:** `tests/unit/test_shield_face_from_hit_point.py` — new unit test file matching the existing `tests/unit/` layout (e.g. peer file `tests/unit/test_apply_hit_routing.py`).
- **Verify-only:** `tests/unit/test_apply_hit_routing.py`, `tests/integration/test_phaser_damage_applied_through_apply_hit.py` — must continue to pass without modification.

---

### Task 1: Write the new test file with failing rotation cases

**Files:**
- Create: `tests/unit/test_shield_face_from_hit_point.py`

- [ ] **Step 1: Write the test file**

```python
"""_shield_face_from_hit_point maps a world hit-point to a shield-face
index in the ship's body frame.

Face index conventions (ShieldSubsystem class constants):
    0 FRONT  ↔ body +Y
    1 REAR   ↔ body -Y
    2 TOP    ↔ body +Z
    3 BOTTOM ↔ body -Z
    4 LEFT   ↔ body -X
    5 RIGHT  ↔ body +X
"""
import math

import pytest

from engine.appc.combat import _shield_face_from_hit_point
from engine.appc.math import TGMatrix3, TGPoint3


# ── fixtures ────────────────────────────────────────────────────────────────


class _ShipWithRotation:
    """Minimal ship: world location + world rotation."""

    def __init__(self, loc: TGPoint3, R: TGMatrix3):
        self._loc = loc
        self._R = R

    def GetWorldLocation(self) -> TGPoint3:
        return self._loc

    def GetWorldRotation(self) -> TGMatrix3:
        return self._R


class _ShipNoRotation:
    """Legacy fixture: no GetWorldRotation — body == world via identity
    fallback in _body_frame_delta."""

    def __init__(self, loc: TGPoint3):
        self._loc = loc

    def GetWorldLocation(self) -> TGPoint3:
        return self._loc


def _hit(ship_loc: TGPoint3, world_offset: tuple[float, float, float]) -> TGPoint3:
    """Build a world hit-point at ship_loc + world_offset."""
    return TGPoint3(
        ship_loc.x + world_offset[0],
        ship_loc.y + world_offset[1],
        ship_loc.z + world_offset[2],
    )


# Constants kept local to avoid a class-attribute import; values are
# pinned by the ShieldSubsystem class constants in engine/appc/subsystems.py.
FRONT, REAR, TOP, BOTTOM, LEFT, RIGHT = 0, 1, 2, 3, 4, 5


# ── identity rotation: all six faces (regression) ───────────────────────────


@pytest.mark.parametrize(
    "world_offset, expected_face",
    [
        ((0.0,  10.0, 0.0),  FRONT),   # +Y
        ((0.0, -10.0, 0.0),  REAR),    # -Y
        ((0.0,  0.0,  10.0), TOP),     # +Z
        ((0.0,  0.0, -10.0), BOTTOM),  # -Z
        ((-10.0, 0.0, 0.0),  LEFT),    # -X
        ((10.0,  0.0, 0.0),  RIGHT),   # +X
    ],
)
def test_identity_rotation_all_faces(world_offset, expected_face):
    loc = TGPoint3(100.0, 200.0, 300.0)  # non-origin: exercises the delta.
    R = TGMatrix3()  # identity
    ship = _ShipWithRotation(loc, R)
    assert _shield_face_from_hit_point(ship, _hit(loc, world_offset)) == expected_face


# ── 90° yaw: nose points world +X ───────────────────────────────────────────
# MakeZRotation(-pi/2) gives R with R.GetCol(1) == (1, 0, 0) — ship-forward
# is world +X. Also R.GetCol(0) == (0, -1, 0) — ship-right is world -Y, so
# a hit from world +Y comes from the ship's LEFT (body -X).


def test_yaw_nose_to_plus_x_front():
    loc = TGPoint3(0.0, 0.0, 0.0)
    R = TGMatrix3().MakeZRotation(-math.pi / 2)
    ship = _ShipWithRotation(loc, R)
    assert _shield_face_from_hit_point(ship, _hit(loc, (10.0, 0.0, 0.0))) == FRONT


def test_yaw_nose_to_plus_x_rear():
    loc = TGPoint3(0.0, 0.0, 0.0)
    R = TGMatrix3().MakeZRotation(-math.pi / 2)
    ship = _ShipWithRotation(loc, R)
    assert _shield_face_from_hit_point(ship, _hit(loc, (-10.0, 0.0, 0.0))) == REAR


def test_yaw_nose_to_plus_x_left_from_world_plus_y():
    loc = TGPoint3(0.0, 0.0, 0.0)
    R = TGMatrix3().MakeZRotation(-math.pi / 2)
    ship = _ShipWithRotation(loc, R)
    # World +Y projects to body -X (ship-right column is world -Y).
    assert _shield_face_from_hit_point(ship, _hit(loc, (0.0, 10.0, 0.0))) == LEFT


def test_yaw_nose_to_plus_x_right_from_world_minus_y():
    loc = TGPoint3(0.0, 0.0, 0.0)
    R = TGMatrix3().MakeZRotation(-math.pi / 2)
    ship = _ShipWithRotation(loc, R)
    assert _shield_face_from_hit_point(ship, _hit(loc, (0.0, -10.0, 0.0))) == RIGHT


def test_yaw_nose_to_plus_x_top_unchanged():
    loc = TGPoint3(0.0, 0.0, 0.0)
    R = TGMatrix3().MakeZRotation(-math.pi / 2)
    ship = _ShipWithRotation(loc, R)
    # Z-axis rotation leaves up == world +Z.
    assert _shield_face_from_hit_point(ship, _hit(loc, (0.0, 0.0, 10.0))) == TOP


# ── 90° pitch: nose pitched down to world -Z ────────────────────────────────
# MakeXRotation(-pi/2) gives R.GetCol(1) == (0, 0, -1) (forward = world -Z)
# and R.GetCol(2) == (0, 1, 0) (up = world +Y).


def test_pitch_nose_to_minus_z_front_from_world_minus_z():
    loc = TGPoint3(0.0, 0.0, 0.0)
    R = TGMatrix3().MakeXRotation(-math.pi / 2)
    ship = _ShipWithRotation(loc, R)
    assert _shield_face_from_hit_point(ship, _hit(loc, (0.0, 0.0, -10.0))) == FRONT


def test_pitch_nose_to_minus_z_rear_from_world_plus_z():
    loc = TGPoint3(0.0, 0.0, 0.0)
    R = TGMatrix3().MakeXRotation(-math.pi / 2)
    ship = _ShipWithRotation(loc, R)
    assert _shield_face_from_hit_point(ship, _hit(loc, (0.0, 0.0, 10.0))) == REAR


def test_pitch_nose_to_minus_z_top_from_world_plus_y():
    loc = TGPoint3(0.0, 0.0, 0.0)
    R = TGMatrix3().MakeXRotation(-math.pi / 2)
    ship = _ShipWithRotation(loc, R)
    assert _shield_face_from_hit_point(ship, _hit(loc, (0.0, 10.0, 0.0))) == TOP


def test_pitch_nose_to_minus_z_bottom_from_world_minus_y():
    loc = TGPoint3(0.0, 0.0, 0.0)
    R = TGMatrix3().MakeXRotation(-math.pi / 2)
    ship = _ShipWithRotation(loc, R)
    assert _shield_face_from_hit_point(ship, _hit(loc, (0.0, -10.0, 0.0))) == BOTTOM


# ── non-axis-aligned rotation: all six faces driven by R.GetCol() ──────────
# For any rotation R, a hit at world offset = sign * R.GetCol(i) projects
# in the body frame to a vector dominant on body axis i with the matching
# sign. Drive each face directly from R's columns.


def _axis_for_face(face: int) -> tuple[int, float]:
    """Return (column_index, sign) such that body_offset = sign * GetCol(col)
    is the body-frame direction that maps to `face`."""
    # FRONT/REAR ↔ body +Y/-Y → column 1, sign +1/-1.
    # TOP/BOTTOM ↔ body +Z/-Z → column 2, sign +1/-1.
    # LEFT/RIGHT ↔ body -X/+X → column 0, sign -1/+1.
    return {
        FRONT:  (1, +1.0),
        REAR:   (1, -1.0),
        TOP:    (2, +1.0),
        BOTTOM: (2, -1.0),
        LEFT:   (0, -1.0),
        RIGHT:  (0, +1.0),
    }[face]


@pytest.mark.parametrize("face", [FRONT, REAR, TOP, BOTTOM, LEFT, RIGHT])
def test_non_axis_aligned_rotation_all_faces(face):
    # Generic rotation: pi/3 about axis (1, 2, 3) normalised. Picks a
    # non-axis-aligned R with no zeros in its columns.
    nx, ny, nz = 1.0, 2.0, 3.0
    n = math.sqrt(nx * nx + ny * ny + nz * nz)
    axis = TGPoint3(nx / n, ny / n, nz / n)
    R = TGMatrix3().MakeRotation(math.pi / 3, axis)
    loc = TGPoint3(50.0, -25.0, 12.0)
    ship = _ShipWithRotation(loc, R)
    col_idx, sign = _axis_for_face(face)
    col = R.GetCol(col_idx)
    world_offset = (sign * col.x * 10.0, sign * col.y * 10.0, sign * col.z * 10.0)
    assert _shield_face_from_hit_point(ship, _hit(loc, world_offset)) == face


# ── legacy fixture: no GetWorldRotation ─────────────────────────────────────


@pytest.mark.parametrize(
    "world_offset, expected_face",
    [
        ((0.0,  10.0, 0.0),  FRONT),
        ((0.0, -10.0, 0.0),  REAR),
        ((0.0,  0.0,  10.0), TOP),
        ((0.0,  0.0, -10.0), BOTTOM),
        ((-10.0, 0.0, 0.0),  LEFT),
        ((10.0,  0.0, 0.0),  RIGHT),
    ],
)
def test_legacy_ship_without_get_world_rotation(world_offset, expected_face):
    loc = TGPoint3(7.0, 8.0, 9.0)
    ship = _ShipNoRotation(loc)
    assert _shield_face_from_hit_point(ship, _hit(loc, world_offset)) == expected_face
```

- [ ] **Step 2: Run the new test file against the current (unmodified) implementation**

Run: `uv run pytest tests/unit/test_shield_face_from_hit_point.py -v`

Expected:
- All six `test_identity_rotation_all_faces` parametrisations PASS (current world-frame code is correct under identity).
- All six `test_legacy_ship_without_get_world_rotation` parametrisations PASS (identity fallback is correct in both implementations).
- `test_yaw_nose_to_plus_x_front` FAILS (current code returns `RIGHT` (5) instead of `FRONT` (0)).
- `test_yaw_nose_to_plus_x_rear` FAILS (returns `LEFT` instead of `REAR`).
- `test_yaw_nose_to_plus_x_left_from_world_plus_y` FAILS (returns `FRONT` instead of `LEFT`).
- `test_yaw_nose_to_plus_x_right_from_world_minus_y` FAILS (returns `REAR` instead of `RIGHT`).
- `test_yaw_nose_to_plus_x_top_unchanged` PASSES (Z-axis yaw leaves world +Z dominance unchanged).
- `test_pitch_nose_to_minus_z_*` four cases FAIL.
- All six `test_non_axis_aligned_rotation_all_faces` parametrisations FAIL (except by coincidence).

Confirm the red bar. Do not commit this step — the test file is committed together with the fix in Task 3, so the repo never lands a known-failing test on its own.

---

### Task 2: Replace the function body to use the body-frame delta

**Files:**
- Modify: `engine/appc/combat.py:186-204`

- [ ] **Step 1: Replace the function body**

Find this block in [`engine/appc/combat.py`](../../../engine/appc/combat.py) at lines 186-204:

```python
def _shield_face_from_hit_point(ship, hit_point) -> int:
    """Map a world hit-point to a shield-face index (0-5 per
    ShieldProperty.NUM_SHIELDS).  Front/Rear/Top/Bottom/Left/Right by
    dominant axis of (hit_point - ship_pos) in world frame.

    Proper transform through ship.GetWorldRotation() is a future
    polish item — for PR 2b the world-axis approximation is fine
    while ships in test setups are placed without rotation.
    """
    ship_pos = ship.GetWorldLocation()
    dx = hit_point.x - ship_pos.x
    dy = hit_point.y - ship_pos.y
    dz = hit_point.z - ship_pos.z
    abs_x, abs_y, abs_z = abs(dx), abs(dy), abs(dz)
    if abs_y >= abs_x and abs_y >= abs_z:
        return 0 if dy >= 0 else 1
    if abs_z >= abs_x:
        return 2 if dz >= 0 else 3
    return 4 if dx <= 0 else 5
```

Replace with:

```python
def _shield_face_from_hit_point(ship, hit_point) -> int:
    """Body-frame dominant-axis selection via :func:`_body_frame_delta`.

    Face indices follow the ``ShieldSubsystem`` class constants:
    FRONT/REAR ↔ ±body-Y, TOP/BOTTOM ↔ ±body-Z, LEFT/RIGHT ↔ ∓body-X,
    per CLAUDE.md's column-vector rotation convention
    (``R.GetCol(0)`` = ship-right, ``R.GetCol(1)`` = ship-forward,
    ``R.GetCol(2)`` = ship-up). Ships lacking ``GetWorldRotation``
    receive identity R from :func:`_body_frame_delta`, so legacy
    fixtures keep their pre-rotation behaviour.
    """
    bx, by, bz = _body_frame_delta(ship, hit_point)
    abs_x, abs_y, abs_z = abs(bx), abs(by), abs(bz)
    if abs_y >= abs_x and abs_y >= abs_z:
        return 0 if by >= 0 else 1
    if abs_z >= abs_x:
        return 2 if bz >= 0 else 3
    return 4 if bx <= 0 else 5
```

- [ ] **Step 2: Run the new test file — all green**

Run: `uv run pytest tests/unit/test_shield_face_from_hit_point.py -v`

Expected: every test PASSES. No xfail / xpass.

---

### Task 3: Regression check — existing apply_hit and phaser-damage tests

**Files:**
- Verify-only: `tests/unit/test_apply_hit_routing.py`, `tests/integration/test_phaser_damage_applied_through_apply_hit.py`

- [ ] **Step 1: Run focused regression**

Run: `uv run pytest tests/unit/test_apply_hit_routing.py tests/integration/test_phaser_damage_applied_through_apply_hit.py -v`

Expected: every test PASSES. These suites use `_FakeShip` (no `GetWorldRotation`) or identity-rotation ships, so the identity fallback in `_body_frame_delta` keeps the world-frame-equivalent behaviour they were written against.

If anything fails, STOP and debug — do not paper over. Per CLAUDE.md memory, never invoke the full `uv run pytest`; stick to the listed files.

---

### Task 4: Commit code + tests together

**Files:**
- `engine/appc/combat.py`
- `tests/unit/test_shield_face_from_hit_point.py`

- [ ] **Step 1: Stage and commit**

```bash
git add engine/appc/combat.py tests/unit/test_shield_face_from_hit_point.py
git commit -m "$(cat <<'EOF'
fix(combat): rotation-correct shield face mapping

_shield_face_from_hit_point now picks the dominant axis in the
target ship's body frame via _body_frame_delta, so rotated
targets get the correct shield face debited. Legacy ships
without GetWorldRotation fall through to identity R, matching
prior world-frame behaviour.

Roadmap: docs/superpowers/specs/2026-06-01-combat-damage-pipeline-design.md
Spec:    docs/superpowers/specs/2026-06-01-shield-face-rotation-design.md

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 2: Verify clean tree**

Run: `git status`
Expected: `nothing to commit, working tree clean` on `feature/shield-face-rotation`.

---

### Task 5: Visual smoke in `./build/dauntless`

**Files:**
- None — runtime check only.

- [ ] **Step 1: Build the engine**

Run from the repo root (NOT from inside `native/` per CLAUDE.md):

```bash
cmake -B build -S . && cmake --build build -j
```

Expected: build succeeds, `build/dauntless` binary exists.

- [ ] **Step 2: Launch and load E1M1**

Run: `./build/dauntless`

In-game: load mission E1M1. Identify a target ship whose yaw or pitch is non-trivial relative to world axes (the Warbird in E1M1 is a good target — it turns and pitches during the encounter).

- [ ] **Step 3: Verify the shield-arc dim tracks the ship's body, not world axes**

Fire phasers on the target. On its ShipDisplay panel, watch which shield arc dims:

- Hit the target's exposed flank (LEFT or RIGHT side of the ship's hull as you see it in 3D) → the LEFT or RIGHT shield arc dims, regardless of which world direction the beam travelled.
- Hit the target's nose or tail → FRONT or REAR dims.
- Hit dorsal or ventral → TOP or BOTTOM dims.

If, while the target is yawed away from world +Y, hitting its nose dims FRONT (instead of LEFT/RIGHT as in the broken world-frame code), the fix is working. If the dimmed arc still tracks world axes regardless of ship orientation, the code change didn't take effect — rebuild and re-launch.

- [ ] **Step 4: Note any issues, then exit**

If the visual smoke passes, you're done. If a behaviour seems off, capture which face dimmed for which hit direction and bring it back for a follow-up — do not patch blindly.

---

## Self-Review Notes

- **Spec coverage:** §3 design decisions all map to Task 2 (function body) and Task 1 (test cases). §4 implementation sketch matches Task 2 replacement code verbatim. §5 test cases 1-5 map to Task 1 test sections (identity, yaw, pitch, non-axis-aligned, legacy). §6 verification commands appear in Tasks 2-5.
- **No placeholders:** every code block is final; no TODO/TBD; every test case is parametrised with concrete expected values.
- **Type/name consistency:** `_shield_face_from_hit_point`, `_body_frame_delta`, face constants `FRONT/REAR/TOP/BOTTOM/LEFT/RIGHT = 0..5` consistent throughout. Fixture class names (`_ShipWithRotation`, `_ShipNoRotation`) used consistently.
- **Sign decisions documented in tests:** `MakeZRotation(-pi/2)` chosen so `R.GetCol(1) == (1, 0, 0)`; `MakeXRotation(-pi/2)` chosen so `R.GetCol(1) == (0, 0, -1)`. Comments above each block explain the choice so a reader doesn't have to re-derive it.
