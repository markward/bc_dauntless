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


_EPS = 1e-9


def _norm_or_none(v: TGPoint3):
    """Unit vector, or None when the magnitude is ~0 (degenerate)."""
    m = math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z)
    if m < _EPS:
        return None
    return TGPoint3(v.x / m, v.y / m, v.z / m)


def _norm(v: TGPoint3) -> TGPoint3:
    # Backstop: a degenerate vector unitizes to body-forward rather than
    # raising ZeroDivisionError. Callers that care handle None via
    # _norm_or_none; this keeps any stray normalize crash-free.
    return _norm_or_none(v) or TGPoint3(0.0, 1.0, 0.0)


def _first_valid_col(idx: int, mats, fallback: TGPoint3) -> TGPoint3:
    for mat in mats:
        n = _norm_or_none(mat.GetCol(idx))
        if n is not None:
            return n
    return fallback


def _any_perpendicular(f: TGPoint3) -> TGPoint3:
    """A unit vector perpendicular to f (f assumed unit)."""
    # Cross f with whichever world axis it's least aligned to.
    axis = TGPoint3(0.0, 0.0, 1.0) if abs(f.z) < 0.9 else TGPoint3(1.0, 0.0, 0.0)
    p = TGPoint3(
        f.y * axis.z - f.z * axis.y,
        f.z * axis.x - f.x * axis.z,
        f.x * axis.y - f.y * axis.x,
    )
    return _norm_or_none(p) or TGPoint3(0.0, 0.0, 1.0)


def nlerp_rotation(a: TGMatrix3, b: TGMatrix3, alpha: float) -> TGMatrix3:
    """Blend basis columns of a toward b, then Gram-Schmidt orthonormalize.

    Keeps forward (col 1) as the primary axis, projects up (col 2)
    perpendicular to it, derives right (col 0) via forward x up. Body
    axes are right-handed (det = +1).

    Robust against degenerate inputs: a freshly-spawned ship can carry a
    zero-column rotation (e.g. AlignToVectors fed a degenerate forward), and
    the renderer must never crash sampling it. When the blended forward/up are
    near-zero we fall back to a valid endpoint column (b then a), then to a
    sane default, so the result is always a proper orthonormal matrix.
    """
    blended = [None, None, None]
    for i in range(3):
        col_a = a.GetCol(i)
        col_b = b.GetCol(i)
        blended[i] = TGPoint3(
            col_a.x + alpha * (col_b.x - col_a.x),
            col_a.y + alpha * (col_b.y - col_a.y),
            col_a.z + alpha * (col_b.z - col_a.z),
        )

    # blended[0] (right) is discarded; re-derived below as f x u to keep the basis right-handed.
    f = _norm_or_none(blended[1]) \
        or _first_valid_col(1, (b, a), TGPoint3(0.0, 1.0, 0.0))
    u_in = blended[2]
    dot_uf = u_in.x * f.x + u_in.y * f.y + u_in.z * f.z
    u = _norm_or_none(TGPoint3(
        u_in.x - dot_uf * f.x,
        u_in.y - dot_uf * f.y,
        u_in.z - dot_uf * f.z,
    ))
    if u is None:
        # Blended up was zero or parallel to forward: re-orthogonalize a valid
        # endpoint up against forward, else pick any perpendicular axis.
        u_src = _first_valid_col(2, (b, a), _any_perpendicular(f))
        d = u_src.x * f.x + u_src.y * f.y + u_src.z * f.z
        u = _norm_or_none(TGPoint3(
            u_src.x - d * f.x, u_src.y - d * f.y, u_src.z - d * f.z,
        )) or _any_perpendicular(f)
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


def lerp_transform(
    prev_loc: TGPoint3, prev_rot: TGMatrix3,
    cur_loc: TGPoint3, cur_rot: TGMatrix3,
    alpha: float,
) -> tuple:
    """Return interpolated (loc, rot) for a render frame."""
    return lerp_point(prev_loc, cur_loc, alpha), nlerp_rotation(prev_rot, cur_rot, alpha)
