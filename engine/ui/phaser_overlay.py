# engine/ui/phaser_overlay.py
"""Phaser strip & firing-arc debug overlay geometry for the Ship Property Viewer.

Pure Python (no GL/CEF). Produces PhaserBeamDescriptor dicts consumed by the
renderer's phaser pass via engine.renderer.set_spv_overlay_beams.

Spec: docs/superpowers/specs/2026-06-16-spv-phaser-strips-and-arcs-design.md
"""
from __future__ import annotations

import math
from typing import List, Tuple

from engine.appc.subsystems import subsystem_world_position

Vec3 = Tuple[float, float, float]

# Sampling / sizing.
STRIP_SAMPLES = 24       # arc segments per strip rim sweep
ARC_SAMPLES = 24         # polyline segments per firing-arc edge
ARC_RADIUS_SCALE = 1.0   # firing-arc radius = Length * this (faithful = 1.0)
BEAM_WIDTH = 0.02        # thin overlay line half-width (game units)

# Colours (RGBA).
STRIP_COLOR = (1.0, 1.0, 0.0, 1.0)   # yellow
ARC_COLOR = (0.0, 1.0, 1.0, 1.0)     # cyan


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


def _rodrigues(v: Vec3, axis: Vec3, theta: float) -> Vec3:
    """Rotate v around unit `axis` by `theta` radians (right-handed)."""
    c = math.cos(theta)
    s = math.sin(theta)
    d = _dot(axis, v)
    cx = _cross(axis, v)
    k = d * (1.0 - c)
    return (v[0]*c + cx[0]*s + axis[0]*k,
            v[1]*c + cx[1]*s + axis[1]*k,
            v[2]*c + cx[2]*s + axis[2]*k)


def _beam(p0: Vec3, p1: Vec3, color) -> dict:
    """One PhaserBeamDescriptor dict for a straight overlay segment p0→p1."""
    return {
        "emitter": (p0[0], p0[1], p0[2]),
        "target":  (p1[0], p1[1], p1[2]),
        "color":   color,
        "width":   BEAM_WIDTH,
        "u_tiles": 1.0,
        "num_sides": 4,
        "taper_radius": BEAM_WIDTH,   # constant width (no endpoint taper)
        "taper_ratio": 0.0,
        "taper_min_length": 0.0,
        "taper_max_length": 1.0e6,
        "perimeter_tile": 1.0,
        "texture_speed": 0.0,
    }


def _polyline(points: List[Vec3], color) -> List[dict]:
    return [_beam(points[i], points[i+1], color) for i in range(len(points)-1)]


def _bank_world_frame(bank, ship):
    """(pos, forward, up, right) in world space for a phaser bank.

    Column-vector rotation: v_world = R · v_body via MultMatrixLeft(R).
    right = up × forward (matches engine.appc.subsystems convention)."""
    rot = ship.GetWorldRotation()
    fwd = bank.GetDirection()
    fwd.MultMatrixLeft(rot)
    up = bank.GetUp()
    up.MultMatrixLeft(rot)
    fwd_t = _norm((fwd.x, fwd.y, fwd.z))
    up_t = _norm((up.x, up.y, up.z))
    right_t = _norm(_cross(up_t, fwd_t))
    w = subsystem_world_position(bank, ship)
    return ((w.x, w.y, w.z), fwd_t, up_t, right_t)


def build_strip_beams(banks, ship) -> List[dict]:
    """Yellow beams tracing each bank's emitter strip: an arc of radius=Length
    around the mount Position swept across ArcWidthAngles around Up, plus an
    inner rim at Length−Width and two end-caps when Width>0."""
    beams: List[dict] = []
    for bank in banks:
        length = float(bank.GetLength())
        if length <= 0.0:
            continue
        pos, fwd, up, _right = _bank_world_frame(bank, ship)
        yaw_lo, yaw_hi = bank.GetArcWidthAngles()
        width = float(bank.GetWidth()) if hasattr(bank, "GetWidth") else 0.0
        inner = length - width
        outer_pts: List[Vec3] = []
        inner_pts: List[Vec3] = []
        for i in range(STRIP_SAMPLES + 1):
            yaw = yaw_lo + (yaw_hi - yaw_lo) * (i / STRIP_SAMPLES)
            radial = _rodrigues(fwd, up, yaw)
            outer_pts.append(_add(pos, _scale(radial, length)))
            if width > 0.0:
                inner_pts.append(_add(pos, _scale(radial, inner)))
        beams += _polyline(outer_pts, STRIP_COLOR)
        if width > 0.0 and inner_pts:
            beams += _polyline(inner_pts, STRIP_COLOR)
            beams.append(_beam(outer_pts[0], inner_pts[0], STRIP_COLOR))
            beams.append(_beam(outer_pts[-1], inner_pts[-1], STRIP_COLOR))
    return beams
