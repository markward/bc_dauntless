# engine/ui/glow_region_overlay.py
"""Glow-region debug overlay geometry for the Ship Property Viewer.

Pure Python (no GL/CEF). Produces world-space DebugCylinder dicts consumed by
the renderer's debug volume pass via engine.renderer.set_debug_cylinders.

The geometry comes from the SAME hardpoint-baked GlowRegion* data the glow
controller registers with the shader (engine.appc.subsystem_glow.
baked_region_ops), so the drawn wireframes match the live glow volumes by
construction. Every subsystem is scanned — including ones the controller does
not drive yet — so any authored region is visible.
"""
from __future__ import annotations

import math
from typing import List, Tuple

from engine.appc.subsystem_glow import (
    baked_region_ops, resolve_baked_region, _position_tuple,
)
from engine.ui.ship_property_viewer import _iter_subsystems

Vec3 = Tuple[float, float, float]

# Wireframe colour — distinct from the yellow phaser strips / cyan arcs.
GLOW_COLOR = (1.0, 0.55, 0.1)   # orange


def _body_to_world(v: Vec3, ship_pos, rot) -> Vec3:
    """ship_pos + R · v (column-vector; mounts/regions are world-scale body
    offsets, so no scale — same math as subsystem_world_position)."""
    from engine.appc.math import TGPoint3
    p = TGPoint3(v[0], v[1], v[2])
    if rot is not None:
        p.MultMatrixLeft(rot)   # R · p
    return (ship_pos.x + p.x, ship_pos.y + p.y, ship_pos.z + p.z)


def _rotate_dir(v: Vec3, rot) -> Vec3:
    """R · v for a direction (no translation)."""
    from engine.appc.math import TGPoint3
    p = TGPoint3(v[0], v[1], v[2])
    if rot is not None:
        p.MultMatrixLeft(rot)
    m = math.sqrt(p.x * p.x + p.y * p.y + p.z * p.z) or 1.0
    return (p.x / m, p.y / m, p.z / m)


def _rotate_vec(v: Vec3, rot) -> Vec3:
    """R · v for a vector, preserving magnitude (no normalize)."""
    from engine.appc.math import TGPoint3
    p = TGPoint3(v[0], v[1], v[2])
    if rot is not None:
        p.MultMatrixLeft(rot)
    return (p.x, p.y, p.z)


def _cylinder(center: Vec3, axis: Vec3, radius: float, length: float) -> dict:
    return {
        "center": center,
        "axis": axis,
        "radius": float(radius),
        "length": float(length),
        "color": GLOW_COLOR,
    }


def _box(center: Vec3, ex: Vec3, ey: Vec3, ez: Vec3) -> dict:
    return {"center": center, "ex": ex, "ey": ey, "ez": ez, "color": GLOW_COLOR}


def _basis_from(forward: Vec3, up: Vec3) -> Tuple[Vec3, Vec3, Vec3]:
    """Normalized box-local (right, forward, up), right = normalize(forward x up).

    Defensive: forward/up are normalized even though the rotate tool already
    hands back orthonormal vectors, so a malformed authored orientation still
    yields a usable (if degenerate-safe) basis rather than a garbage box.
    """
    def _norm(v: Vec3) -> Vec3:
        m = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) or 1.0
        return (v[0] / m, v[1] / m, v[2] / m)

    f = _norm(forward)
    u = _norm(up)
    r = (f[1] * u[2] - f[2] * u[1],
         f[2] * u[0] - f[0] * u[2],
         f[0] * u[1] - f[1] * u[0])
    return _norm(r), f, u


def build_glow_region_overlay(ship, selected_name: str = None,
                              show_all: bool = True,
                              pending: dict = None) -> Tuple[List[dict], List[dict]]:
    """World-space debug-volume dicts for baked glow regions on `ship`.

    Returns `(cylinders, boxes)` — cylinder/sphere regions become
    DebugCylinder dicts (`engine.renderer.set_debug_cylinders`); box regions
    become DebugBox dicts (`engine.renderer.set_debug_boxes`).

    Selection-scoped: `show_all` (the Glow Regions toggle) draws every
    subsystem's regions; otherwise only the subsystem whose GetName() matches
    `selected_name` (the SELECTED light node) contributes — so a light's
    wireframe shows ONLY while that light node is the selected element, never
    for its parent subsystem or a different selection. No selection + toggle
    off → ([], []).

    `pending` maps subsystem NAME → a baked-shaped region spec (a staged but
    unsaved Edit Light edit). It is CONSULTED for the spec of a drawn region
    (so a selected light's live edit previews before Save), but presence in
    `pending` does NOT itself force drawing — a previously-edited light no
    longer persists on screen once you select away. Edit Light selects the
    light node it opens on, so the staged edit still previews live. A `None`
    value (a staged light removal) draws nothing for that subsystem — it
    hides the baked region rather than falling back to it.

    Cylinder regions map directly (baked_region_ops pre-shifts the centre by
    the aft extent). Sphere regions are drawn as their circumscribing cylinder
    (radius r, length 2r, centred on the sphere) along the ship body-up axis —
    a wire cage, not an exact sphere, but enough to see position and size.
    Box regions map directly to a world-space oriented wire box: the centre
    plus three body-axis edge vectors carrying the half-extent magnitudes.
    """
    if ship is None or not hasattr(ship, "GetWorldLocation"):
        return [], []
    if not show_all and not selected_name:
        return [], []

    pending = pending or {}
    ship_pos = ship.GetWorldLocation()
    rot = ship.GetWorldRotation() if hasattr(ship, "GetWorldRotation") else None

    out: List[dict] = []
    boxes: List[dict] = []
    for sub in _iter_subsystems(ship):
        name = sub.GetName() if hasattr(sub, "GetName") else ""
        if not show_all and name != selected_name:
            continue
        pos = _position_tuple(sub)
        if name in pending:
            spec = pending[name]
            op = resolve_baked_region(spec, pos) if spec is not None else None
            ops = [op] if op is not None else []
        else:
            prop = sub.GetProperty() if hasattr(sub, "GetProperty") else None
            ops = baked_region_ops(prop, pos, name)
        for op in ops:
            if op[0] == "cylinder":
                _kind, center, axis, radius, length = op
                out.append(_cylinder(
                    _body_to_world(center, ship_pos, rot),
                    _rotate_dir(axis, rot), radius, length))
            elif op[0] == "box":
                _kind, center, half, forward, up = op
                right, fwd, upv = _basis_from(forward, up)
                boxes.append(_box(
                    _body_to_world(center, ship_pos, rot),
                    _rotate_vec((right[0] * half[0], right[1] * half[0],
                                 right[2] * half[0]), rot),
                    _rotate_vec((fwd[0] * half[1], fwd[1] * half[1],
                                 fwd[2] * half[1]), rot),
                    _rotate_vec((upv[0] * half[2], upv[1] * half[2],
                                 upv[2] * half[2]), rot)))
            else:  # sphere
                _kind, center, radius = op
                up = _rotate_dir((0.0, 0.0, 1.0), rot)   # ship body-up
                world_c = _body_to_world(center, ship_pos, rot)
                base = (world_c[0] - up[0] * radius,
                        world_c[1] - up[1] * radius,
                        world_c[2] - up[2] * radius)
                out.append(_cylinder(base, up, radius, 2.0 * radius))
    return out, boxes
