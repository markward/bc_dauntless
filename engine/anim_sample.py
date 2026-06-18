"""Keyframe sampling for the bridge camera walk-on cutscene.

Pure Python; mirrors the native pose_sampler's interpolation (translation
LERP, rotation SLERP, t clamped to the key range) so the camera glide
matches what the renderer would produce. Quaternions are (x, y, z, w).
"""
import math


def _bracket(keys, t):
    """Return (i0, i1, u) bracketing time t in a time-sorted key list, with
    u the [0,1] fraction between them. Clamps to the endpoints."""
    if not keys:
        return None
    if t <= keys[0][0]:
        return (0, 0, 0.0)
    if t >= keys[-1][0]:
        last = len(keys) - 1
        return (last, last, 0.0)
    lo, hi = 0, len(keys) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if keys[mid][0] <= t:
            lo = mid
        else:
            hi = mid
    t0, t1 = keys[lo][0], keys[hi][0]
    u = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
    return (lo, hi, u)


def sample_translation(keys, t):
    """LERP keys = [(time, x, y, z), ...] at time t -> (x, y, z)."""
    br = _bracket(keys, t)
    if br is None:
        return (0.0, 0.0, 0.0)
    i0, i1, u = br
    a, b = keys[i0], keys[i1]
    return (a[1] + (b[1] - a[1]) * u,
            a[2] + (b[2] - a[2]) * u,
            a[3] + (b[3] - a[3]) * u)


def _slerp(q0, q1, u):
    dot = q0[0] * q1[0] + q0[1] * q1[1] + q0[2] * q1[2] + q0[3] * q1[3]
    if dot < 0.0:                      # shortest path
        q1 = (-q1[0], -q1[1], -q1[2], -q1[3])
        dot = -dot
    if dot > 0.9995:                   # near-parallel: nlerp
        res = tuple(q0[i] + (q1[i] - q0[i]) * u for i in range(4))
    else:
        theta = math.acos(max(-1.0, min(1.0, dot)))
        st = math.sin(theta)
        w0 = math.sin((1.0 - u) * theta) / st
        w1 = math.sin(u * theta) / st
        res = tuple(q0[i] * w0 + q1[i] * w1 for i in range(4))
    n = math.sqrt(sum(c * c for c in res)) or 1.0
    return (res[0] / n, res[1] / n, res[2] / n, res[3] / n)


def sample_rotation(keys, t):
    """SLERP keys = [(time, x, y, z, w), ...] at time t -> (x, y, z, w)."""
    br = _bracket(keys, t)
    if br is None:
        return (0.0, 0.0, 0.0, 1.0)
    i0, i1, u = br
    q0 = keys[i0][1:5]
    q1 = keys[i1][1:5]
    return _slerp(q0, q1, u)


def quat_rotate(q, v):
    """Rotate 3-vector v by quaternion q=(x,y,z,w): v + 2w(t) + 2(q.xyz x t)
    where t = q.xyz x v."""
    x, y, z, w = q
    vx, vy, vz = v
    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)
    return (vx + w * tx + (y * tz - z * ty),
            vy + w * ty + (z * tx - x * tz),
            vz + w * tz + (x * ty - y * tx))
