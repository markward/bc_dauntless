"""Ship Property Viewer — logic core (camera, projection, descriptors, picking).

Pure Python: no GL or CEF imports. See
docs/superpowers/specs/2026-06-08-ship-property-viewer-design.md
"""
from __future__ import annotations

import math
from typing import List, Optional, Tuple

from engine.appc.math import TGPoint3, TGMatrix3


# Canonical implementation lives in engine.appc.subsystems so the renderer,
# camera, and Ship Property Viewer all share one source of truth.
from engine.appc.subsystems import subsystem_world_position  # noqa: F401


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
    GetPosition() are skipped (cannot be placed in space).

    `parent_index` links a child pod/bank/tube to its aggregator's descriptor
    index (the subsystem-list accordion groups on it); None for top-level
    categories and for children whose parent has no mount (the enumeration
    yields parents before their children, so the parent is always already
    indexed when it exists)."""
    out: List[dict] = []
    index_of: dict = {}   # id(subsystem) -> descriptor index
    for sub in _iter_subsystems(ship):
        local = sub.GetPosition() if hasattr(sub, "GetPosition") else None
        if local is None:
            continue
        # Pass the known ship: the Hull/root subsystem's _climb_to_ship()
        # returns None, which would otherwise place its pin at the origin.
        w = subsystem_world_position(sub, ship)
        props = _properties_for(sub, local)
        parent = getattr(sub, "GetParentSubsystem", lambda: None)()
        index_of[id(sub)] = len(out)
        out.append({
            "name":       props["name"],
            "icon_id":    _icon_id_for(sub),
            "world_pos":  (w.x, w.y, w.z),
            "state":      _state_for(sub),
            "targetable": _targetable_for(sub),
            "condition_pct": _condition_pct_for(sub),
            "parent_index": index_of.get(id(parent)) if parent is not None else None,
            "properties": props,
        })
    # Object emitters — non-damageable mount markers (shuttle bay, probe
    # launcher). Distinct "mount" kind/state so the pin renderer can style
    # them apart from damageable subsystems; never targetable.
    emitters = ship.GetObjectEmitters() if hasattr(ship, "GetObjectEmitters") else []
    from engine.ui import damage_icons as _damage_icons
    for em in emitters:
        local = em.GetPosition() if hasattr(em, "GetPosition") else None
        if local is None:
            continue
        w = subsystem_world_position(em, ship)
        out.append({
            "name":       em.GetName(),
            "icon_id":    _damage_icons.ICON_SYSTEM_FALLBACK,  # "System" fallback glyph (damage_icons.ICON_SYSTEM_FALLBACK)
            "world_pos":  (w.x, w.y, w.z),
            "state":      "mount",
            "kind":       "mount",
            "targetable": False,
            "condition_pct": None,
            "parent_index": None,
            "properties": {"name": em.GetName(),
                           "emitted_type": em.GetEmittedObjectType()},
        })
    return out


def _iter_subsystems(ship):
    """Yield damage-relevant subsystems of a ship. Mirrors
    engine.ui.ship_display_panel._iter_damage_subsystems. Falls back to
    iterating the ship directly only when that module cannot be imported
    (e.g. test stubs run without the full UI stack); real enumeration
    errors are allowed to propagate rather than be masked."""
    try:
        from engine.ui.ship_display_panel import _iter_damage_subsystems
    except ImportError:
        return list(ship)
    return list(_iter_damage_subsystems(ship))


def _icon_id_for(sub) -> int:
    from engine.ui import damage_icons
    return damage_icons.icon_num_for_subsystem(sub)


def _state_for(sub) -> str:
    """healthy/damaged/disabled/destroyed — mirrors
    engine.ui.ship_display_panel._row_state (boolean predicate ladder).
    Missing predicate methods on stub objects are treated as False."""
    def _is(name: str) -> bool:
        m = getattr(sub, name, None)
        if m is None:
            return False
        try:
            return bool(m())
        except Exception:
            return False
    if _is("IsDestroyed"):
        return "destroyed"
    if _is("IsDisabled"):
        return "disabled"
    if _is("IsDamaged"):
        return "damaged"
    return "healthy"


def _targetable_for(sub) -> bool:
    """True when the AI/target-menu would list this subsystem (hardpoint
    SetTargetable flag). Missing method (stub objects) → False."""
    m = getattr(sub, "IsTargetable", None)
    if m is None:
        return False
    try:
        return bool(m())
    except Exception:
        return False


def _condition_pct_for(sub):
    """Condition as an int percentage 0..100, or None when unavailable."""
    m = getattr(sub, "GetConditionPercentage", None)
    if m is None:
        return None
    try:
        return int(round(float(m()) * 100.0))
    except Exception:
        return None


def _properties_for(sub, pos) -> dict:
    def _safe(getter, default=None):
        try:
            return getter()
        except Exception:
            return default
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


# ---------------------------------------------------------------------------
# Pin picking
# ---------------------------------------------------------------------------

PIN_RADIUS_PT = 9.0  # click target radius in logical points (DPI-independent)


def pick_pin(cursor_x: float, cursor_y: float, descriptors: List[dict],
             cam: "OrbitCamera", viewport: Tuple[int, int],
             device_scale_factor: float = 1.0) -> Optional[int]:
    """Index of the nearest visible pin whose screen disc contains the cursor,
    or None. Nearest-by-screen-distance wins on overlap; first pin wins on
    exact tie (strict-less-than after the first candidate).

    cursor/viewport are in physical framebuffer pixels (the same space the GL
    render uses), so the logical-point click radius is scaled by
    device_scale_factor to match the rendered pin size on HiDPI displays."""
    best_idx: Optional[int] = None
    radius_px = PIN_RADIUS_PT * (device_scale_factor if device_scale_factor > 0.0 else 1.0)
    best_d2 = radius_px * radius_px
    for i, d in enumerate(descriptors):
        sx, sy, _depth, visible = project(d["world_pos"], cam, viewport)
        if not visible:
            continue
        dx, dy = sx - cursor_x, sy - cursor_y
        d2 = dx*dx + dy*dy
        if d2 < best_d2 or (best_idx is None and d2 <= best_d2):
            best_d2 = d2
            best_idx = i
    return best_idx
