"""Manual Aim -- BC's "mouse pick fire" (H key / Felix's "Manual Aim" button).

The SDK owns the toggle chain (DefaultKeyboardBinding.py:154 WC_H ->
ET_INPUT_TOGGLE_PICK_FIRE -> TacticalControlHandlers.TogglePickFire ->
TacticalControlWindow.SetMousePickFire). This module is the C++-only half
the SDK never sees: each sim tick, while the flag is on and the view is
exterior, unproject the cursor through the gameplay camera, trace it against
the TARGETED ship's hull, and store the hit on the player as a target-local
offset (ShipClass.set_manual_target_offset). Off the hull -> revert to the
subsystem lock (UseTargetOffsetTG(0), E3M1.FixTargeting's rule).

Spec + the five stated assumptions: docs/superpowers/specs/
2026-09-15-manual-aim-pick-fire-design.md
"""
from __future__ import annotations

import math
from typing import Optional, Tuple

Vec3 = Tuple[float, float, float]


class AimCamera:
    """Gameplay camera params, duck-compatible with the interface
    engine.ui.ship_property_viewer.project expects (eye()/up() methods,
    target/fov_y_rad/near/far attributes) -- the SAME shape the reticle text
    projects with, so the pick lands where the cursor is drawn."""

    def __init__(self, eye: Vec3, target: Vec3, up: Vec3,
                 fov_y_rad: float, near: float, far: float):
        self._eye = (float(eye[0]), float(eye[1]), float(eye[2]))
        self.target = (float(target[0]), float(target[1]), float(target[2]))
        self._up = (float(up[0]), float(up[1]), float(up[2]))
        self.fov_y_rad = float(fov_y_rad)
        self.near = float(near)
        self.far = float(far)

    def eye(self) -> Vec3:
        return self._eye

    def up(self) -> Vec3:
        return self._up


def _sub(a, b):   return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def _cross(a, b): return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
def _norm(v):
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return (v[0] / n, v[1] / n, v[2] / n) if n > 1e-12 else None


def cursor_ray(cursor_xy, viewport, cam) -> Optional[Tuple[Vec3, Vec3]]:
    """(origin, unit direction) in world space for a cursor pixel.

    Exact inverse of ship_property_viewer.project (_look_at + _perspective):
    pixel -> NDC (top-left origin, y flipped) -> view-space direction at unit
    depth (x = ndc_x·tan(fov/2)·aspect, y = ndc_y·tan(fov/2), z = -1) ->
    world via the camera basis (right s = f×up, true up u = s×f, forward f).
    `cursor_xy` and `viewport` must be in the SAME pixel space (host_loop
    passes framebuffer pixels for both). None when the viewport or the
    camera basis is degenerate."""
    w, h = viewport
    if w <= 0 or h <= 0:
        return None
    eye = cam.eye()
    f = _norm(_sub(cam.target, eye))
    if f is None:
        return None
    s = _norm(_cross(f, cam.up()))
    if s is None:
        return None
    u = _cross(s, f)
    aspect = float(w) / float(h)
    tan_half = math.tan(cam.fov_y_rad / 2.0)
    ndc_x = 2.0 * float(cursor_xy[0]) / float(w) - 1.0
    ndc_y = 1.0 - 2.0 * float(cursor_xy[1]) / float(h)
    vx = ndc_x * tan_half * aspect
    vy = ndc_y * tan_half
    d = _norm((s[0] * vx + u[0] * vy + f[0],
               s[1] * vx + u[1] * vy + f[1],
               s[2] * vx + u[2] * vy + f[2]))
    if d is None:
        return None
    return eye, d


# ── Per-tick pick (sim side) ────────────────────────────────────────────────
# The gameplay camera is only known on the RENDER side of the frame
# (host_loop's r.set_camera call); note_camera parks it here -- data only,
# no game-state mutation on the render side -- and the next sim tick's
# update() reads it (one frame of camera lag, invisible at 60 Hz).
_last_cam: Optional[AimCamera] = None


def note_camera(eye, target, up, fov_y_rad, near, far) -> None:
    global _last_cam
    _last_cam = AimCamera(eye, target, up, fov_y_rad, near, far)


def last_camera() -> Optional[AimCamera]:
    return _last_cam


def reset() -> None:
    """Mission swap / tests: forget the noted camera."""
    global _last_cam
    _last_cam = None


def _revert(player) -> bool:
    if player.is_using_target_offset():
        player.UseTargetOffsetTG(0)
    return False


def update(*, player, tcw, ship_instances, is_exterior: bool,
           cursor_fb=None, viewport_fb=None, cam=None, ray_trace=None) -> bool:
    """One sim tick of Manual Aim. The ONLY game-state mutation in this
    module: sets or clears the player's manual target offset.

    Returns True while a hull pick is live. Every other path -- flag off,
    bridge view, no target / dead target, target has no render instance,
    cursor off the hull -- reverts to UseTargetOffsetTG(0) (assumption 3:
    revert immediately, never hold the last hit).

    Only the CURRENT target's hull is traced (assumption 2: no retarget on
    hover). The hit is stored target-local and UNSCALED, the same frame the
    SDK's own offset producers use (pSubsystem.GetPosition()), so
    _resolve_torpedo_aim_point / _phaser_aim_point's pos + R·(o·scale) lands
    back on the picked point."""
    from engine import host_io
    from engine.appc import combat
    from engine.appc.math import TGPoint3

    if player is None:
        return False
    probe = getattr(type(player), "is_using_target_offset", None)
    if not callable(probe):
        return False
    if not is_exterior or tcw is None or not tcw.GetMousePickFire():
        return _revert(player)
    target = player.GetTarget()
    if target is None or (hasattr(target, "IsDead") and target.IsDead()):
        return _revert(player)
    iid = ship_instances.get(target) if ship_instances is not None else None
    if iid is None:
        return _revert(player)
    if cam is None:
        cam = _last_cam
    if cursor_fb is None:
        cursor_fb = host_io.cursor_pos()
    if viewport_fb is None:
        viewport_fb = host_io.framebuffer_size()
    if cam is None or cursor_fb is None:
        return _revert(player)
    ray = cursor_ray(cursor_fb, viewport_fb, cam)
    if ray is None:
        return _revert(player)
    origin, direction = ray
    if ray_trace is None:
        ray_trace = host_io.ray_trace_mesh
    try:
        hit = ray_trace(iid, origin, direction, cam.far)
    except Exception:
        # A native trace error must not kill the sim tick; treat as a miss.
        hit = None
    if hit is None:
        return _revert(player)
    (px, py, pz), _normal, _t = hit
    dx, dy, dz = combat._body_frame_delta(target, TGPoint3(px, py, pz))
    scale = float(target.GetScale()) if hasattr(target, "GetScale") else 1.0
    if scale <= 1e-9:
        scale = 1.0
    player.set_manual_target_offset(TGPoint3(dx / scale, dy / scale, dz / scale))
    return True
