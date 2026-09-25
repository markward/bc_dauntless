"""Rigid poses for articulated ship parts (spec 2026-09-25 §3, §4.1, §6).

A pose is (R, t): R a 3x3 rotation as a tuple of ROW tuples, t a 3-tuple. It
draws a body-frame point x of the part at R·x + t. R = Rz(rz)·Ry(ry)·Rx(rx)
with angles in degrees -- rotate about body X first, then Y, then Z --
right-handed and column-vector (CLAUDE.md). R and t are about the body
ORIGIN, never the anchor: that is what lets an author move the anchor without
moving any pose (spec §2.3, option A). The anchor only shapes the SWING
between poses (`interpolate`).

All values are SHIP units, body frame. `matrix4_model` is the one converter
to the renderer's MODEL units.
"""

import math

IDENTITY = (((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
            (0.0, 0.0, 0.0))


def _mat_mul(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3))
                       for j in range(3)) for i in range(3))


def _mat_vec(m, v):
    return tuple(m[i][0] * v[0] + m[i][1] * v[1] + m[i][2] * v[2]
                 for i in range(3))


def _transpose(m):
    return tuple(tuple(m[j][i] for j in range(3)) for i in range(3))


def euler_to_matrix(rx, ry, rz):
    """R = Rz(rz)·Ry(ry)·Rx(rx), degrees."""
    x, y, z = (math.radians(float(a)) for a in (rx, ry, rz))
    cx, sx, cy, sy, cz, sz = (math.cos(x), math.sin(x), math.cos(y),
                              math.sin(y), math.cos(z), math.sin(z))
    Rx = ((1.0, 0.0, 0.0), (0.0, cx, -sx), (0.0, sx, cx))
    Ry = ((cy, 0.0, sy), (0.0, 1.0, 0.0), (-sy, 0.0, cy))
    Rz = ((cz, -sz, 0.0), (sz, cz, 0.0), (0.0, 0.0, 1.0))
    return _mat_mul(Rz, _mat_mul(Ry, Rx))


def matrix_to_euler(R):
    """Inverse of `euler_to_matrix` (degrees). At gimbal lock (|ry| = 90)
    rx is set to 0 and rz absorbs the remaining rotation."""
    sy = -R[2][0]
    sy = max(-1.0, min(1.0, sy))
    ry = math.asin(sy)
    if abs(sy) < 1.0 - 1e-12:
        rx = math.atan2(R[2][1], R[2][2])
        rz = math.atan2(R[1][0], R[0][0])
    else:
        rx = 0.0
        rz = math.atan2(-R[0][1], R[1][1])
    return (math.degrees(rx), math.degrees(ry), math.degrees(rz))


def pose_from6(p6):
    tx, ty, tz, rx, ry, rz = (float(v) for v in p6)
    return (euler_to_matrix(rx, ry, rz), (tx, ty, tz))


def pose_to6(pose):
    R, t = pose
    rx, ry, rz = matrix_to_euler(R)
    return (float(t[0]), float(t[1]), float(t[2]), rx, ry, rz)


def apply(pose, x):
    R, t = pose
    r = _mat_vec(R, x)
    return (r[0] + t[0], r[1] + t[1], r[2] + t[2])


def apply_vector(pose, v):
    return _mat_vec(pose[0], v)


def inverse_apply(pose, x):
    R, t = pose
    return _mat_vec(_transpose(R), (x[0] - t[0], x[1] - t[1], x[2] - t[2]))


def is_identity(pose, eps=1e-9):
    R, t = pose
    I = IDENTITY[0]
    return (all(abs(R[i][j] - I[i][j]) <= eps for i in range(3) for j in range(3))
            and all(abs(c) <= eps for c in t))


def _axis_angle_matrix(axis, degrees):
    n = math.sqrt(sum(float(a) * float(a) for a in axis))
    if n <= 0.0:
        return IDENTITY[0]
    x, y, z = (float(a) / n for a in axis)
    th = math.radians(float(degrees))
    c, s, C = math.cos(th), math.sin(th), 1.0 - math.cos(th)
    return ((c + x * x * C, x * y * C - z * s, x * z * C + y * s),
            (y * x * C + z * s, c + y * y * C, y * z * C - x * s),
            (z * x * C - y * s, z * y * C + x * s, c + z * z * C))


def hinge_pose(pivot, axis, degrees):
    """The legacy hinge (spec §6): rotation about the line through `pivot`
    along `axis`. R = rot(axis, degrees), t = pivot - R·pivot."""
    R = _axis_angle_matrix(axis, degrees)
    rp = _mat_vec(R, pivot)
    return (R, (pivot[0] - rp[0], pivot[1] - rp[1], pivot[2] - rp[2]))


def _to_quat(R):
    tr = R[0][0] + R[1][1] + R[2][2]
    if tr > 0.0:
        s = math.sqrt(tr + 1.0) * 2.0
        return (0.25 * s, (R[2][1] - R[1][2]) / s, (R[0][2] - R[2][0]) / s,
                (R[1][0] - R[0][1]) / s)
    if R[0][0] > R[1][1] and R[0][0] > R[2][2]:
        s = math.sqrt(1.0 + R[0][0] - R[1][1] - R[2][2]) * 2.0
        return ((R[2][1] - R[1][2]) / s, 0.25 * s, (R[0][1] + R[1][0]) / s,
                (R[0][2] + R[2][0]) / s)
    if R[1][1] > R[2][2]:
        s = math.sqrt(1.0 + R[1][1] - R[0][0] - R[2][2]) * 2.0
        return ((R[0][2] - R[2][0]) / s, (R[0][1] + R[1][0]) / s, 0.25 * s,
                (R[1][2] + R[2][1]) / s)
    s = math.sqrt(1.0 + R[2][2] - R[0][0] - R[1][1]) * 2.0
    return ((R[1][0] - R[0][1]) / s, (R[0][2] + R[2][0]) / s,
            (R[1][2] + R[2][1]) / s, 0.25 * s)


def _from_quat(q):
    w, x, y, z = q
    return ((1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
            (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
            (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)))


def _slerp(q0, q1, u):
    d = sum(a * b for a, b in zip(q0, q1))
    if d < 0.0:
        q1, d = tuple(-c for c in q1), -d
    if d > 0.9995:
        q = tuple(a + (b - a) * u for a, b in zip(q0, q1))
    else:
        th = math.acos(d)
        s0 = math.sin((1.0 - u) * th) / math.sin(th)
        s1 = math.sin(u * th) / math.sin(th)
        q = tuple(s0 * a + s1 * b for a, b in zip(q0, q1))
    n = math.sqrt(sum(c * c for c in q))
    return tuple(c / n for c in q)


def interpolate(pose0, pose1, anchor, u):
    """Spec §4.1: the part swings about `anchor` while the anchor travels
    straight. R(u) = slerp(R0, R1, u); anchor(u) = lerp(R0·a+t0, R1·a+t1, u);
    x(u) = R(u)·(x - a) + anchor(u). Exact end poses for ANY anchor."""
    u = max(0.0, min(1.0, float(u)))
    if u <= 0.0:
        return pose0
    if u >= 1.0:
        return pose1
    R = _from_quat(_slerp(_to_quat(pose0[0]), _to_quat(pose1[0]), u))
    a0, a1 = apply(pose0, anchor), apply(pose1, anchor)
    au = tuple(p + (q - p) * u for p, q in zip(a0, a1))
    ra = _mat_vec(R, anchor)
    return (R, (au[0] - ra[0], au[1] - ra[1], au[2] - ra[2]))


def matrix4_model(pose, model_to_ship):
    """Column-major 4x4 for the native node transform: rotation R, and the
    translation converted SHIP -> MODEL units (divided by `model_to_ship`)."""
    R, t = pose
    k = 1.0 / float(model_to_ship)
    return (R[0][0], R[1][0], R[2][0], 0.0,
            R[0][1], R[1][1], R[2][1], 0.0,
            R[0][2], R[1][2], R[2][2], 0.0,
            t[0] * k, t[1] * k, t[2] * k, 1.0)
