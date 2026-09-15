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
