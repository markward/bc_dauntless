"""Render interpolation math: blend two sim states for a render frame.

Pure functions, no engine/global state. Used by the host loop to draw
non-player ships at `lerp(prev, cur, alpha)` so their discrete 60 Hz
motion reads as smooth at any render refresh rate.

Rotation uses normalized-lerp of the basis columns followed by
Gram-Schmidt re-orthonormalization, matching the column-vector
convention in CLAUDE.md and the smoothing in
`engine/cameras/chase.py:_advance_smoothing`. Per-tick deltas are tiny
(<= a few degrees at 60 Hz), so nlerp is visually indistinguishable
from slerp and never hits the degenerate 180-degree case.
"""

import math

from engine.appc.math import TGMatrix3, TGPoint3


def lerp_point(a: TGPoint3, b: TGPoint3, alpha: float) -> TGPoint3:
    return TGPoint3(
        a.x + alpha * (b.x - a.x),
        a.y + alpha * (b.y - a.y),
        a.z + alpha * (b.z - a.z),
    )


def _norm(v: TGPoint3) -> TGPoint3:
    m = math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z)
    return TGPoint3(v.x / m, v.y / m, v.z / m)


def nlerp_rotation(a: TGMatrix3, b: TGMatrix3, alpha: float) -> TGMatrix3:
    """Blend basis columns of a toward b, then Gram-Schmidt orthonormalize.

    Keeps forward (col 1) as the primary axis, projects up (col 2)
    perpendicular to it, derives right (col 0) via forward x up. Body
    axes are right-handed (det = +1).
    """
    blended = [None, None, None]
    for i in range(3):
        s = a.GetCol(i)
        l = b.GetCol(i)
        blended[i] = TGPoint3(
            s.x + alpha * (l.x - s.x),
            s.y + alpha * (l.y - s.y),
            s.z + alpha * (l.z - s.z),
        )

    f = _norm(blended[1])
    u_in = blended[2]
    dot_uf = u_in.x * f.x + u_in.y * f.y + u_in.z * f.z
    u = _norm(TGPoint3(
        u_in.x - dot_uf * f.x,
        u_in.y - dot_uf * f.y,
        u_in.z - dot_uf * f.z,
    ))
    r = TGPoint3(
        f.y * u.z - f.z * u.y,
        f.z * u.x - f.x * u.z,
        f.x * u.y - f.y * u.x,
    )

    out = TGMatrix3()
    out.SetCol(0, r)
    out.SetCol(1, f)
    out.SetCol(2, u)
    return out


def lerp_transform(prev_loc, prev_rot, cur_loc, cur_rot, alpha):
    """Return interpolated (loc, rot) for a render frame."""
    return lerp_point(prev_loc, cur_loc, alpha), nlerp_rotation(prev_rot, cur_rot, alpha)
