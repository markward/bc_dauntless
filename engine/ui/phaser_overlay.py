# engine/ui/phaser_overlay.py
"""Phaser strip & firing-arc debug overlay geometry for the Ship Property Viewer.

Pure Python (no GL/CEF). Produces PhaserBeamDescriptor dicts consumed by the
renderer's phaser pass via engine.renderer.set_spv_overlay_beams.

Spec: docs/superpowers/specs/2026-06-16-spv-phaser-strips-and-arcs-design.md
"""
from __future__ import annotations

import math
from typing import List, Optional, Tuple

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


def _arc_direction(fwd: Vec3, up: Vec3, right: Vec3,
                   yaw: float, pitch: float) -> Vec3:
    """Aim direction at (yaw about Up, pitch about the yawed Right axis).
    Mirrors the yaw/pitch decomposition in engine.appc.weapon_subsystems.

    Sign note: weapon_subsystems measures pitch as asin((fwd×right)·aim),
    so positive pitch = toward (fwd×right), i.e. upward when right points
    left (the BC convention). Rotating around right_yaw by -pitch achieves
    this: _rodrigues(radial, right_yaw, -pitch) lifts toward world-up for
    positive pitch angles."""
    radial = _rodrigues(fwd, up, yaw)
    right_yaw = _norm(_rodrigues(right, up, yaw))  # renormalise for float drift
    return _rodrigues(radial, right_yaw, -pitch)


def build_arc_beams(bank, ship) -> List[dict]:
    """Cyan wireframe of a bank's firing envelope: 4 swept edges of the
    yaw×pitch rectangle at radius = Length × ARC_RADIUS_SCALE around the
    mount Position."""
    length = float(bank.GetLength()) * ARC_RADIUS_SCALE
    if length <= 0.0:
        return []
    pos, fwd, up, right = _bank_world_frame(bank, ship)
    yaw_lo, yaw_hi = bank.GetArcWidthAngles()
    pitch_lo, pitch_hi = bank.GetArcHeightAngles()

    def _edge(yaw_of_t, pitch_of_t) -> List[Vec3]:
        pts: List[Vec3] = []
        for i in range(ARC_SAMPLES + 1):
            t = i / ARC_SAMPLES
            d = _arc_direction(fwd, up, right, yaw_of_t(t), pitch_of_t(t))
            pts.append(_add(pos, _scale(d, length)))
        return pts

    def _yaw(t):
        return yaw_lo + (yaw_hi - yaw_lo) * t

    def _pitch(t):
        return pitch_lo + (pitch_hi - pitch_lo) * t

    beams: List[dict] = []
    beams += _polyline(_edge(_yaw, lambda t: pitch_hi), ARC_COLOR)   # top
    beams += _polyline(_edge(_yaw, lambda t: pitch_lo), ARC_COLOR)   # bottom
    beams += _polyline(_edge(lambda t: yaw_lo, _pitch), ARC_COLOR)   # left
    beams += _polyline(_edge(lambda t: yaw_hi, _pitch), ARC_COLOR)   # right
    return beams


def phaser_banks(ship) -> "List[PhaserBank]":
    """All PhaserBank subsystems on `ship` (uses the SPV's own enumeration)."""
    from engine.appc.weapon_subsystems import PhaserBank
    from engine.ui.ship_property_viewer import _iter_subsystems
    return [s for s in _iter_subsystems(ship) if isinstance(s, PhaserBank)]


def build_phaser_overlay(ship, selected_name: Optional[str] = None,
                         banks: Optional[List] = None) -> List[dict]:
    """Yellow strips for every phaser bank, plus a cyan firing arc for the
    bank whose GetName() matches `selected_name` (if it is a phaser bank).
    Pass `banks` to bypass enumeration (tests / pre-fetched lists).
    selected_name=None or "" both suppress the arc."""
    if ship is None:
        return []
    if banks is None:
        banks = phaser_banks(ship)
    beams = build_strip_beams(banks, ship)
    if selected_name:
        sel = next((b for b in banks if b.GetName() == selected_name), None)
        if sel is not None:
            beams += build_arc_beams(sel, ship)
    return beams


def build_strip_beams(banks, ship) -> List[dict]:
    """Yellow beams tracing each bank's emitter strip: the single arc of
    radius=Length around the mount Position, swept across ArcWidthAngles around
    Up. This arc is the locus of all beam emit points — ShipSubsystem.
    _strip_emit_position emits from `Position + Length × direction`, using only
    Length — so it *is* the physical lit strip on the hull.

    We deliberately do NOT draw an inner rim at Length−Width or end-caps: the
    SDK `Width` is unused by the emit math and its meaning is unvalidated
    (docs/instrumented_experiments/hardpoint_handling_research.md flags it
    "Unvalidated"). Drawing it produced spurious pie-wedges reaching into the
    saucer centre that do not correspond to any real emitter geometry."""
    beams: List[dict] = []
    for bank in banks:
        length = float(bank.GetLength())
        if length <= 0.0:
            continue
        pos, fwd, up, _right = _bank_world_frame(bank, ship)
        yaw_lo, yaw_hi = bank.GetArcWidthAngles()
        pts: List[Vec3] = []
        for i in range(STRIP_SAMPLES + 1):
            yaw = yaw_lo + (yaw_hi - yaw_lo) * (i / STRIP_SAMPLES)
            radial = _rodrigues(fwd, up, yaw)
            pts.append(_add(pos, _scale(radial, length)))
        beams += _polyline(pts, STRIP_COLOR)
    return beams
