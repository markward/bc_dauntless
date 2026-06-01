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
