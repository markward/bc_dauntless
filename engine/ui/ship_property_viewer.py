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

# Module-level (not function-local) so tests can monkeypatch
# `spv.baked_glow_regions` and have both `_light_region_spec` and
# `_light_annotation` observe the patch.
from engine.appc.subsystem_glow import baked_glow_regions, _position_tuple


# ---------------------------------------------------------------------------
# Orbit camera and world→screen projection
# ---------------------------------------------------------------------------

Vec3 = Tuple[float, float, float]

_MAX_PITCH = math.pi / 2.0 - 1e-3  # avoid forward ∥ up (gimbal) in _look_at


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0]-b[0], a[1]-b[1], a[2]-b[2])


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0]+b[0], a[1]+b[1], a[2]+b[2])


def _scale(a: Vec3, s: float) -> Vec3:
    return (a[0]*s, a[1]*s, a[2]*s)


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


def region_spec_to_calls(index, spec):
    """Full ordered SetGlowRegion* call list for a region spec (baked-shaped:
    radius=(r,), extent=(aft,fore), scale=(sx,sy,sz), position/axis 3-tuples)."""
    shape = spec["shape"]
    px, py, pz = spec["position"]
    calls = [("SetGlowRegionShape", (index, shape)),
             ("SetGlowRegionPosition", (index, px, py, pz))]
    if shape == "Cylinder":
        ax, ay, az = spec["axis"]
        calls.append(("SetGlowRegionAxis", (index, ax, ay, az)))
        calls.append(("SetGlowRegionRadius", (index, spec["radius"][0])))
        aft, fore = spec["extent"]
        calls.append(("SetGlowRegionExtent", (index, aft, fore)))
    elif shape == "Box":
        sx, sy, sz = spec["scale"]
        calls.append(("SetGlowRegionScale", (index, sx, sy, sz)))
        ori = spec.get("orientation")
        if ori is not None and not _is_identity_orientation(ori):
            (fx, fy, fz), (ux, uy, uz) = ori
            calls.append(("SetGlowRegionOrientation", (index, fx, fy, fz, ux, uy, uz)))
    else:  # Sphere
        calls.append(("SetGlowRegionRadius", (index, spec["radius"][0])))
    return calls


def emitter_spec_to_calls(index, spec):
    """Full ordered SetLightEmitter* call list for one emitter spec (Task 3).
    Point omits axis/length; strip/cone include them; all carry colour+intensity."""
    kind = spec["kind"]
    px, py, pz = spec["position"]
    r, g, b = spec["color"]
    calls = [
        ("SetLightEmitterKind", (index, kind)),
        ("SetLightEmitterPosition", (index, px, py, pz)),
        ("SetLightEmitterRadius", (index, float(spec["radius"]))),
        ("SetLightEmitterColor", (index, float(r), float(g), float(b))),
        ("SetLightEmitterIntensity", (index, float(spec["intensity"]))),
    ]
    if kind in ("strip", "cone"):
        ax, ay, az = spec["axis"]
        calls.append(("SetLightEmitterAxis", (index, ax, ay, az)))
        calls.append(("SetLightEmitterLength", (index, float(spec["length"]))))
    return calls


def _is_identity_orientation(ori, eps=1e-6):
    (fx, fy, fz), (ux, uy, uz) = ori
    return (abs(fx) < eps and abs(fy - 1.0) < eps and abs(fz) < eps and
            abs(ux) < eps and abs(uy) < eps and abs(uz - 1.0) < eps)


def _light_region_spec(sub):
    """Region-0 spec (baked-shaped) for the modal pre-fill; from-scratch default
    when the subsystem has no baked region."""
    prop = sub.GetProperty() if hasattr(sub, "GetProperty") else None
    pos = _position_tuple(sub) or (0.0, 0.0, 0.0)
    regions = baked_glow_regions(prop)
    if regions:
        r = regions[0]
        return {"shape": r["shape"],
                "position": r["position"] or pos,
                "axis": r["axis"] or (0.0, -1.0, 0.0),
                "radius": r["radius"] or (0.25,),
                "extent": r["extent"] or (0.0, 2.0),
                "scale": r["scale"] or (0.25, 0.25, 0.25),
                "orientation": r.get("orientation") or ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0))}
    return {"shape": "Sphere", "position": pos, "axis": (0.0, -1.0, 0.0),
            "radius": (0.25,), "extent": (0.0, 2.0), "scale": (0.25, 0.25, 0.25),
            "orientation": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0))}


def _light_annotation(sub):
    """(has_baked_light, light_region) for a subsystem. `light_region` is the
    baked region-0 spec if the subsystem has one, else a from-scratch Sphere
    default (used to pre-fill Add Light Volume). Any subsystem is light-capable
    now — no impulse/warp/sensor gate."""
    prop = sub.GetProperty() if hasattr(sub, "GetProperty") else None
    has = bool(baked_glow_regions(prop))
    return has, _light_region_spec(sub)


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
    # Post-pass: annotate every subsystem descriptor with its light volume.
    # `light` = a baked region 0 exists; `light_region` = that baked spec or a
    # from-scratch default (any subsystem is light-capable — see the light-node
    # design). Re-walk in the SAME order + skip rule as the build loop.
    di = 0
    for sub in _iter_subsystems(ship):
        local = sub.GetPosition() if hasattr(sub, "GetPosition") else None
        if local is None:
            continue
        has, region = _light_annotation(sub)
        out[di]["light"] = has
        out[di]["light_region"] = region
        di += 1
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
        "radius":    _safe(getattr(sub, "GetRadius", lambda: None)),
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


# ---------------------------------------------------------------------------
# Transform gizmo
# ---------------------------------------------------------------------------
GIZMO_LENGTH_FRAC = 0.22   # arrow length as a fraction of orbit distance
GIZMO_MIN_LENGTH  = 0.30   # floor so it never collapses when zoomed in close
GIZMO_PICK_PT     = 8.0    # click threshold to a projected shaft, logical pts


def gizmo_length(cam: "OrbitCamera") -> float:
    """World length of each arrow — proportional to orbit distance so the
    gizmo keeps a near-constant apparent size at any zoom (fixed FOV)."""
    return max(GIZMO_MIN_LENGTH, cam.distance * GIZMO_LENGTH_FRAC)


def gizmo_axes(R):
    """The three unit body axes in world space (column-vector convention):
    X=starboard GetCol(0), Y=forward GetCol(1), Z=up GetCol(2)."""
    def col(k):
        c = R.GetCol(k)
        return _norm((c.x, c.y, c.z))
    return (col(0), col(1), col(2))


def world_from_body(ship, body_pos):
    """ship_loc + R * body_pos (column-vector R, no scale) — the world point
    of a body-frame position. Mirrors subsystem_world_position but takes an
    explicit body position (so a pending/dragged position can be placed)."""
    loc = ship.GetWorldLocation()
    off = TGPoint3(body_pos[0], body_pos[1], body_pos[2])
    rot = ship.GetWorldRotation() if hasattr(ship, "GetWorldRotation") else None
    if isinstance(rot, TGMatrix3):
        off.MultMatrixLeft(rot)
    return (loc.x + off.x, loc.y + off.y, loc.z + off.z)


def rotate_about_axis(vec, k, angle_rad):
    """Rodrigues rotation of body-frame `vec` about basis axis e_k (k in 0/1/2),
    returned normalized. Falls back to the normalized input on a degenerate
    result."""
    kx = (1.0 if k == 0 else 0.0, 1.0 if k == 1 else 0.0, 1.0 if k == 2 else 0.0)
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    dot = kx[0]*vec[0] + kx[1]*vec[1] + kx[2]*vec[2]
    cross = (kx[1]*vec[2] - kx[2]*vec[1],
             kx[2]*vec[0] - kx[0]*vec[2],
             kx[0]*vec[1] - kx[1]*vec[0])
    out = (vec[0]*c + cross[0]*s + kx[0]*dot*(1.0 - c),
           vec[1]*c + cross[1]*s + kx[1]*dot*(1.0 - c),
           vec[2]*c + cross[2]*s + kx[2]*dot*(1.0 - c))
    n = math.sqrt(out[0]**2 + out[1]**2 + out[2]**2)
    if n < 1e-9:
        vn = math.sqrt(vec[0]**2 + vec[1]**2 + vec[2]**2) or 1.0
        return (vec[0]/vn, vec[1]/vn, vec[2]/vn)
    return (out[0]/n, out[1]/n, out[2]/n)


def orthonormalize_basis(forward, up):
    """Re-orthonormalize a (forward, up) box-orientation basis after either
    vector has been rotated independently: normalize `forward`, then
    Gram-Schmidt `up` against it (`up - (up·f)*f`, normalized) so the pair
    stays unit-length and mutually perpendicular. Right is derived by
    consumers as `forward x up`, so it isn't stored here."""
    f = _norm(forward)
    u = _sub(up, _scale(f, _dot(up, f)))
    return f, _norm(u)


def _seg_dist2(px, py, ax, ay, bx, by):
    """Squared distance from point p to segment a-b, in screen pixels."""
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 <= 1e-9:
        return (px - ax) ** 2 + (py - ay) ** 2
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    cx, cy = ax + t * dx, ay + t * dy
    return (px - cx) ** 2 + (py - cy) ** 2


def pick_gizmo_axis(cursor_x, cursor_y, origin, axes, length, cam, viewport,
                    device_scale_factor: float = 1.0):
    """Axis index (0/1/2) whose projected shaft is within the click threshold
    of the cursor, nearest wins; None if none. Cursor/viewport are framebuffer
    pixels (as in pick_pin), so the logical threshold is scaled by DSF."""
    thresh = GIZMO_PICK_PT * (device_scale_factor if device_scale_factor > 0 else 1.0)
    best_d2, best = thresh * thresh, None
    s0x, s0y, _z0, v0 = project(origin, cam, viewport)
    if not v0:
        return None
    for k, axis in enumerate(axes):
        tip = _add(origin, _scale(axis, length))
        s1x, s1y, _z1, v1 = project(tip, cam, viewport)
        if not v1:
            continue
        d2 = _seg_dist2(cursor_x, cursor_y, s0x, s0y, s1x, s1y)
        if d2 < best_d2:
            best_d2, best = d2, k
    return best


def _plane_basis(n):
    """Two orthonormal vectors spanning the plane perpendicular to unit `n`."""
    n = _norm(n)
    seed = (1.0, 0.0, 0.0) if abs(n[0]) < 0.9 else (0.0, 1.0, 0.0)
    u = _norm(_sub(seed, _scale(n, _dot(seed, n))))
    v = (n[1]*u[2] - n[2]*u[1], n[2]*u[0] - n[0]*u[2], n[0]*u[1] - n[1]*u[0])
    return u, v


def pick_gizmo_ring(cursor_x, cursor_y, origin, axes, length, cam, viewport,
                    device_scale_factor=1.0, samples=48):
    """Ring index (0/1/2) whose projected circle (in the plane perpendicular to
    axes[k]) is nearest the cursor, or None. Nearest within the click threshold."""
    thresh = GIZMO_PICK_PT * (device_scale_factor if device_scale_factor > 0 else 1.0)
    best_d2, best = thresh * thresh, None
    for k in range(3):
        u, v = _plane_basis(axes[k])
        pts = []
        for sidx in range(samples):
            a = 2.0 * math.pi * sidx / samples
            p = _add(origin, _add(_scale(u, length*math.cos(a)),
                                  _scale(v, length*math.sin(a))))
            sx, sy, _z, vis = project(p, cam, viewport)
            pts.append((sx, sy) if vis else None)
        for sidx in range(samples):
            a0, a1 = pts[sidx], pts[(sidx + 1) % samples]
            if a0 is None or a1 is None:
                continue
            d2 = _seg_dist2(cursor_x, cursor_y, a0[0], a0[1], a1[0], a1[1])
            if d2 < best_d2:
                best_d2, best = d2, k
    return best


def ring_drag_angle(cursor_x, cursor_y, origin, cam, viewport):
    """Cursor's screen angle around the projected gizmo centre (radians)."""
    ox, oy, _z, _vis = project(origin, cam, viewport)
    return math.atan2(cursor_y - oy, cursor_x - ox)


def axis_drag_param(cursor_x, cursor_y, origin, axis, length, cam, viewport):
    """World distance along `axis` (from origin) of the cursor's projection
    onto the screen-projected shaft. Reuses project() only (no unprojection):
    robust for the near-frontal views the SPV orbit produces. The caller keeps
    the drag-start origin fixed and applies (param_now - param_grab)."""
    s0x, s0y, _z0, v0 = project(origin, cam, viewport)
    tip = _add(origin, _scale(axis, length))
    s1x, s1y, _z1, v1 = project(tip, cam, viewport)
    if not (v0 and v1):
        return 0.0
    ax, ay = s1x - s0x, s1y - s0y
    l2 = ax * ax + ay * ay
    if l2 <= 1e-9:
        return 0.0
    f = ((cursor_x - s0x) * ax + (cursor_y - s0y) * ay) / l2  # fraction of length
    return f * length
