"""Ship Property Viewer — logic core (camera, projection, descriptors, picking).

Pure Python: no GL or CEF imports. See
docs/superpowers/specs/2026-06-08-ship-property-viewer-design.md
"""
from __future__ import annotations

import math
from typing import List, Optional, Tuple

from engine.appc.math import TGPoint3, TGMatrix3


def subsystem_world_position(sub) -> TGPoint3:
    """World mount point of a subsystem: ship location + body->world rotated
    local mount. No scale factor (BC stores mounts in world units relative to
    the ship centre — see engine/appc/subsystems.py:769). Returns the ship
    location if the subsystem has no 3D mount."""
    ship = sub._climb_to_ship() if hasattr(sub, "_climb_to_ship") else None
    if ship is None or not hasattr(ship, "GetWorldLocation"):
        return TGPoint3(0.0, 0.0, 0.0)
    ship_pos = ship.GetWorldLocation()
    local = sub.GetPosition() if hasattr(sub, "GetPosition") else None
    if not isinstance(local, TGPoint3):
        return TGPoint3(ship_pos.x, ship_pos.y, ship_pos.z)
    offset = TGPoint3(local.x, local.y, local.z)
    if hasattr(ship, "GetWorldRotation"):
        rot = ship.GetWorldRotation()
        if isinstance(rot, TGMatrix3):
            offset.MultMatrixLeft(rot)  # R . offset (column-vector)
    return TGPoint3(ship_pos.x + offset.x,
                    ship_pos.y + offset.y,
                    ship_pos.z + offset.z)


# ---------------------------------------------------------------------------
# Orbit camera and world→screen projection
# ---------------------------------------------------------------------------

Vec3 = Tuple[float, float, float]


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0]-b[0], a[1]-b[1], a[2]-b[2])


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]


def _norm(a: Vec3) -> Vec3:
    m = math.sqrt(_dot(a, a)) or 1.0
    return (a[0]/m, a[1]/m, a[2]/m)


class OrbitCamera:
    """Orbit around a target. yaw/pitch in radians; distance in game units.

    Orientation uses a fixed world basis (+Y is BC forward; +Z up) — this is a
    standalone inspection scene, not the gameplay flight camera, so the
    no-world-up rule (which governs the in-game camera) does not apply here."""

    def __init__(self, target: Vec3, distance: float,
                 yaw: float = 0.0, pitch: float = 0.0,
                 fov_y_rad: float = math.radians(45.0),
                 near: float = 0.05, far: float = 1.0e6):
        self.target = target
        self.distance = distance
        self.yaw = yaw
        self.pitch = pitch
        self.fov_y_rad = fov_y_rad
        self.near = near
        self.far = far

    def eye(self) -> Vec3:
        cp = math.cos(self.pitch)
        # yaw about Z (up), pitch lifts toward +Z.
        dir_to_eye = (
            -math.sin(self.yaw) * cp,
            -math.cos(self.yaw) * cp,
            math.sin(self.pitch),
        )
        return (self.target[0] + dir_to_eye[0] * self.distance,
                self.target[1] + dir_to_eye[1] * self.distance,
                self.target[2] + dir_to_eye[2] * self.distance)

    def up(self) -> Vec3:
        return (0.0, 0.0, 1.0)


def _look_at(eye: Vec3, target: Vec3, up: Vec3):
    """Right-handed view matrix as 4x4 row-list (row-major)."""
    f = _norm(_sub(target, eye))      # forward
    s = _norm(_cross(f, up))          # right
    u = _cross(s, f)                  # true up
    return [
        [ s[0],  s[1],  s[2], -_dot(s, eye)],
        [ u[0],  u[1],  u[2], -_dot(u, eye)],
        [-f[0], -f[1], -f[2],  _dot(f, eye)],
        [ 0.0,   0.0,   0.0,   1.0],
    ]


def _perspective(fov_y: float, aspect: float, near: float, far: float):
    fy = 1.0 / math.tan(fov_y / 2.0)
    fx = fy / aspect
    nf = 1.0 / (near - far)
    return [
        [fx,  0.0, 0.0,                   0.0],
        [0.0, fy,  0.0,                   0.0],
        [0.0, 0.0, (far + near) * nf,     2.0 * far * near * nf],
        [0.0, 0.0, -1.0,                  0.0],
    ]


def _mat_vec4(m, v):
    return [sum(m[r][c] * v[c] for c in range(4)) for r in range(4)]


def project(world: Vec3, cam: "OrbitCamera",
            viewport: Tuple[int, int]) -> Tuple[float, float, float, bool]:
    """Project a world point to screen pixels (top-left origin).

    Returns (sx, sy, ndc_depth, visible). visible is False when the point is
    behind the camera or outside the clip volume."""
    w, h = viewport
    aspect = (w / h) if h else 1.0
    view = _look_at(cam.eye(), cam.target, cam.up())
    proj = _perspective(cam.fov_y_rad, aspect, cam.near, cam.far)
    vp = [[sum(proj[r][k] * view[k][c] for k in range(4)) for c in range(4)]
          for r in range(4)]
    clip = _mat_vec4(vp, [world[0], world[1], world[2], 1.0])
    if clip[3] <= 1e-6:
        return (0.0, 0.0, 0.0, False)
    ndc_x, ndc_y, ndc_z = clip[0]/clip[3], clip[1]/clip[3], clip[2]/clip[3]
    visible = -1.0 <= ndc_z <= 1.0
    sx = (ndc_x * 0.5 + 0.5) * w
    sy = (1.0 - (ndc_y * 0.5 + 0.5)) * h   # flip Y to top-left origin
    return (sx, sy, ndc_z, visible)
