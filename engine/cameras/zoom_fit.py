"""Target-zoom framing maths: fit the whole target in frame, never behind
the player.

Spec: docs/superpowers/specs/2026-10-20-target-zoom-fit-design.md (rules
R1-R7, section 5). This is a DELIBERATE departure from BC (spec section 7):
BC stands the zoom camera off by a radius-derived distance and can crop or
bury the target; we measure the target's hull box and solve the distance at
which every corner fits the frustum shrunk by ``FIT_MARGIN``.

Pure maths on plain tuples; ``loc`` needs ``.x .y .z`` and ``rot`` needs
``GetCol(i)`` (column-vector convention: world = loc + R.v). Game units only.
"""
import math
from dataclasses import dataclass

FIT_MARGIN = 0.10
SMOOTH_TAU_S = 0.25


@dataclass(frozen=True)
class TargetExtent:
    centre: tuple
    axes: tuple      # three world-space unit columns, or None for a sphere
    half: tuple      # box half-extents, or None for a sphere
    radius: float


def _xyz(v):
    return (float(v.x), float(v.y), float(v.z))


def target_extent(obj, loc, rot):
    from engine.appc.camera_modes import _target_radius
    from engine.appc.combat import _hull_box_for
    radius = _target_radius(obj)
    pos = _xyz(loc)
    box = _hull_box_for(obj)
    if box is None:
        return TargetExtent(pos, None, None, radius)
    (cx, cy, cz), half = box
    axes = tuple(_xyz(rot.GetCol(i)) for i in range(3))
    centre = tuple(pos[i] + axes[0][i] * cx + axes[1][i] * cy + axes[2][i] * cz
                   for i in range(3))
    return TargetExtent(centre, axes, tuple(half), radius)


def _unit(v):
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if n < 1e-12:
        return (0.0, 0.0, 0.0)
    return (v[0] / n, v[1] / n, v[2] / n)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def fit_distance(ext, forward, up, fov_y_rad, aspect, margin=FIT_MARGIN):
    """Eye-to-centre distance along -forward at which ``ext`` fits the
    frustum shrunk by ``1 - margin``."""
    k = 1.0 - margin
    tan_v = math.tan(fov_y_rad / 2.0)
    tan_h = tan_v * aspect
    if ext.axes is None:
        return ext.radius / (k * math.sin(math.atan(min(tan_v, tan_h))))
    fwd = _unit(forward)
    upv = _unit(up)
    right = _cross(fwd, upv)
    d = 0.0
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            for sz in (-1.0, 1.0):
                s = (sx * ext.half[0], sy * ext.half[1], sz * ext.half[2])
                q = tuple(ext.axes[0][i] * s[0] + ext.axes[1][i] * s[1]
                          + ext.axes[2][i] * s[2] for i in range(3))
                x, y, z = _dot(q, right), _dot(q, upv), _dot(q, fwd)
                d = max(d, abs(x) / (k * tan_h) - z, abs(y) / (k * tan_v) - z)
    return d


def surface_distance(ext, forward):
    """Distance from the centre along -forward to where that ray leaves the
    box (slab method) or sphere."""
    if ext.axes is None:
        return ext.radius
    back = _unit(tuple(-c for c in forward))
    t = math.inf
    for a, h in zip(ext.axes, ext.half):
        c = abs(_dot(back, a))
        if c > 1e-12:
            t = min(t, h / c)
    return t


def zoom_target_distance(*, d_fit, zoom, player_dist, r_player, d_surface):
    """R4 + R6: scale the fit, spill to the player's near side, stay outside
    the target's surface, and never go behind the player."""
    d = min(d_fit * zoom, player_dist - r_player)
    d = max(d, d_surface)
    d = min(d, player_dist)
    return max(d, 0.0)


class DistanceSmoother:
    """Exponential approach (tau 0.25 s); snaps on a new key or ``dt=None``;
    ``dt == 0`` (paused) returns the held value."""

    def __init__(self):
        self._key = None
        self._val = None
        self._has = False

    def reset(self):
        self._key = None
        self._val = None
        self._has = False

    def step(self, key, d, dt):
        if dt is None or not self._has or key != self._key:
            self._key, self._val, self._has = key, d, True
            return d
        if dt <= 0.0:
            return self._val
        a = 1.0 - math.exp(-dt / SMOOTH_TAU_S)
        self._val += (d - self._val) * a
        return self._val
