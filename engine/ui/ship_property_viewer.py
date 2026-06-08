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

_MAX_PITCH = math.pi / 2.0 - 1e-3  # avoid forward ∥ up (gimbal) in _look_at


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
        pitch = max(-_MAX_PITCH, min(_MAX_PITCH, self.pitch))
        cp = math.cos(pitch)
        # yaw about Z (up), pitch lifts toward +Z.
        dir_to_eye = (
            -math.sin(self.yaw) * cp,
            -math.cos(self.yaw) * cp,
            math.sin(pitch),
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


def build_descriptors(ship) -> List[dict]:
    """One descriptor per subsystem that has a 3D mount. Subsystems with no
    GetPosition() are skipped (cannot be placed in space)."""
    out: List[dict] = []
    for sub in _iter_subsystems(ship):
        local = sub.GetPosition() if hasattr(sub, "GetPosition") else None
        if local is None:
            continue
        w = subsystem_world_position(sub)
        props = _properties_for(sub)
        out.append({
            "name":       props["name"],
            "icon_id":    _icon_id_for(sub),
            "world_pos":  (w.x, w.y, w.z),
            "state":      _state_for(sub),
            "properties": props,
        })
    return out


def _iter_subsystems(ship):
    """Yield damage-relevant subsystems of a ship. Mirrors
    engine.ui.ship_display_panel._iter_damage_subsystems; kept thin so a stub
    ship iterable works in tests."""
    try:
        from engine.ui.ship_display_panel import _iter_damage_subsystems
        return list(_iter_damage_subsystems(ship))
    except Exception:
        return list(ship)  # stub fallback


def _icon_id_for(sub) -> int:
    from engine.ui import damage_icons
    return damage_icons.icon_num_for_subsystem(sub)


def _state_for(sub) -> str:
    """healthy/damaged/disabled/destroyed predicate ladder, mirroring
    ship_display_panel._row_state (which uses IsDestroyed/IsDisabled/IsDamaged).
    Falls back to GetCondition() for stub/simplified subsystems that lack
    those boolean methods."""
    try:
        if hasattr(sub, "IsDestroyed") and sub.IsDestroyed():
            return "destroyed"
        if hasattr(sub, "GetCondition") and not hasattr(sub, "IsDestroyed"):
            # stub path: no IsDestroyed, use condition <= 0
            if sub.GetCondition() <= 0.0:
                return "destroyed"
        if hasattr(sub, "IsDisabled") and sub.IsDisabled():
            return "disabled"
        if hasattr(sub, "IsDamaged") and sub.IsDamaged():
            return "damaged"
        if hasattr(sub, "GetCondition") and not hasattr(sub, "IsDamaged"):
            # stub path: no IsDamaged, use condition < 1
            if sub.GetCondition() < 1.0:
                return "damaged"
    except Exception:
        pass
    return "healthy"


def _properties_for(sub) -> dict:
    def _safe(getter, default=None):
        try:
            return getter()
        except Exception:
            return default
    pos = _safe(sub.GetPosition) if hasattr(sub, "GetPosition") else None
    return {
        "name":      _safe(getattr(sub, "GetName", lambda: None)) or "<unnamed>",
        "type":      type(sub).__name__,
        "condition": _safe(getattr(sub, "GetCondition", lambda: None)),
        "disabled":  bool(_safe(getattr(sub, "IsDisabled", lambda: False))),
        "position":  None if pos is None else (pos.x, pos.y, pos.z),
    }


# ---------------------------------------------------------------------------
# Orbit camera and world→screen projection
# ---------------------------------------------------------------------------

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
