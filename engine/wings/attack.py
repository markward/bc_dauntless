"""Attack-slot geometry: shield-face reads and flank points. Pure: no App."""
import math

from engine.wings.assess import dist

FACE_AXES = {0: (0, 1, 0), 1: (0, -1, 0), 2: (0, 0, 1), 3: (0, 0, -1),
             4: (-1, 0, 0), 5: (1, 0, 0)}
ENVELOP_ORDER = (1, 4, 5, 2, 3)


def weakest_face(faces):
    if not faces:
        return None
    i = min(range(len(faces)), key=lambda k: (faces[k], k))
    return i, faces[i]


def focus_dirs(face, n, arc_deg=25.0):
    x, y, z = (float(c) for c in FACE_AXES[face])
    if n <= 0:
        return ()
    about_x = face in (2, 3)
    out = []
    for i in range(n):
        deg = 0.0 if n == 1 else -arc_deg + 2.0 * arc_deg * i / (n - 1)
        c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
        if about_x:
            out.append((x, y * c - z * s, y * s + z * c))
        else:
            out.append((x * c - y * s, x * s + y * c, z))
    return tuple(out)


def envelop_dirs(n):
    return tuple(FACE_AXES[ENVELOP_ORDER[i % len(ENVELOP_ORDER)]]
                 for i in range(n))


def slot_point(target_pos, rot_cols, body_dir, standoff_gu):
    c0, c1, c2 = rot_cols
    dx, dy, dz = body_dir
    return tuple(target_pos[k] + (c0[k] * dx + c1[k] * dy + c2[k] * dz)
                 * standoff_gu for k in range(3))


def assign_slots(candidates, points, prev=None):
    """name -> slot index. `prev` (name -> index, last tick's) keeps each
    previous holder that is still a candidate on its index while that index
    exists (final review I2: re-pairing from scratch swapped holders every
    few seconds); the vacated slots go to the other candidates, nearest
    pair first."""
    names = {c.name for c in candidates}
    out, used = {}, set()
    for name, j in sorted((prev or {}).items()):
        if name in names and 0 <= j < len(points) and j not in used:
            out[name] = j
            used.add(j)
    pairs = sorted(
        (dist(c.pos, p), c.name, j)
        for c in candidates if c.name not in out
        for j, p in enumerate(points) if j not in used)
    for _d, name, j in pairs:
        if name in out or j in used:
            continue
        out[name] = j
        used.add(j)
    return out
