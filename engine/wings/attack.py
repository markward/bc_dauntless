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


def _turn(d, deg, about_x):
    """`d` turned `deg` degrees about body x (top/bottom faces) or body z
    (every other face), the focus_dirs scheme."""
    x, y, z = (float(c) for c in d)
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    if about_x:
        return (x, y * c - z * s, y * s + z * c)
    return (x * c - y * s, x * s + y * c, z)


def focus_dirs(face, n, arc_deg=25.0):
    if n <= 0:
        return ()
    about_x = face in (2, 3)
    return tuple(
        _turn(FACE_AXES[face],
              0.0 if n == 1 else -arc_deg + 2.0 * arc_deg * i / (n - 1),
              about_x)
        for i in range(n))


def spread_dirs(dirs, n, wrap_deg=25.0):
    """n directions cycling `dirs`; each further wrap turns them another
    wrap_deg (about x for a top/bottom-led direction, else about z), so
    more holders than directions never share a point (review M2). Distinct
    for envelop's axes, 90 degrees apart, up to 14 wraps; only slot_all
    (disable, on envelop's axes) ever wraps."""
    out = []
    for i in range(n):
        d = dirs[i % len(dirs)]
        k = i // len(dirs)
        out.append(tuple(d) if k == 0 else
                   _turn(d, wrap_deg * k,
                         abs(d[2]) > max(abs(d[0]), abs(d[1]))))
    return tuple(out)


def envelop_dirs(n):
    return spread_dirs(tuple(FACE_AXES[f] for f in ENVELOP_ORDER), n)


def slot_point(target_pos, rot_cols, body_dir, standoff_gu):
    c0, c1, c2 = rot_cols
    dx, dy, dz = body_dir
    return tuple(target_pos[k] + (c0[k] * dx + c1[k] * dy + c2[k] * dz)
                 * standoff_gu for k in range(3))


def beam_range(distances):
    """The smallest positive full-damage distance (GU) of a holder's beam
    banks, or None with none."""
    live = [float(d) for d in distances if d is not None and d > 0.0]
    return min(live) if live else None


def holder_standoff(range_gu, lo, hi):
    """A slot-holder's standoff (ruling 2026-11-09): 0.8 x its beam range
    clamped to [lo, hi] (the cap wins if lo > hi); hi with no beam range.
    A fixed 120 GU sat far past every beam's full-damage distance (Galor
    30-40 GU, Akira 60 GU), so holding a slot there did little damage."""
    if range_gu is None:
        return hi
    return min(hi, max(lo, 0.8 * range_gu))


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


def secondary_count(n_members, share):
    """How many members are ordered onto the secondaries: n x share,
    rounded DOWN (Mark 2026-11-13), so the default 10% forces nobody in a
    wing under ten. The epsilon keeps 10 x 0.3 at 3 (binary floats)."""
    return max(0, int(math.floor(n_members * share + 1e-9)))


def assign_secondaries(candidates, secondaries, k, prev=None):
    """name -> secondary name for up to k candidates: the ones closest to
    any secondary, each taking the secondary nearest it (ties by name).
    `prev` (last tick's) keeps each holder that is still a candidate on its
    secondary while that is still listed, nearest first, so the share does
    not reshuffle every brain tick; the rest of the k are filled fresh."""
    secs = {s.name: s for s in secondaries}
    if k <= 0 or not secs or not candidates:
        return {}
    views = {c.name: c for c in candidates}

    def nearest(c):
        return min(secs.values(), key=lambda s: (dist(c.pos, s.pos), s.name))

    out = {}
    keep = sorted((dist(views[n].pos, secs[s].pos), n, s)
                  for n, s in (prev or {}).items()
                  if n in views and s in secs)
    for _d, n, s in keep[:k]:
        out[n] = s
    fresh = []
    for c in candidates:
        if c.name not in out:
            s = nearest(c)
            fresh.append((dist(c.pos, s.pos), c.name, s.name))
    for _d, n, s in sorted(fresh)[:k - len(out)]:
        out[n] = s
    return out
