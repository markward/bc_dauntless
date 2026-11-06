"""A subsystem's DAMAGE point (ShipSubsystem.GetDamagePoint): the centre a
weapon hit's footprint is measured from.

Measured on the original with stbc-oracle (catalogues of every subsystem of
twelve classes -- Galaxy, Sovereign, Akira, Nebula, Ambassador, Warbird, Bird
of Prey, Vor'cha, Keldon, Galor, Kessok Heavy, Marauder -- reading the game's
own GetDamagePoint): the damage point is the subsystem's position, unless
that position lies OUTSIDE the hull (a tube or tractor on the skin, a phaser
bank's point on its strip). Then it is the first ENTRY face of the hull
walking from the position toward the ship's centre, a further 0.050 GU in.
302 of 307 subsystems agree to 0.005 GU. Some walk outside the hull almost to
the centre (the Galaxy's Forward Tractor 2: damage point ~(0, 0, 0)), and the
Bird of Prey's hull and warp core walk through the centre to the far side.
The misses: the Galaxy's Aft Tractor 2 and the Marauder's aft tractor (0.05
GU outside the drawn mesh, inside the original's coarser hull: kept there,
moved 0.1 GU in here) and three Bird of Prey points where its mesh has
doubled faces. "Outside" is a majority vote of ray-crossing parities: the
drawn hulls are not watertight.

The geometry is the ship's high-LOD NIF as _dauntless_host.nif_shapes reads
it (model-space vertices, BC_MODEL_SCALE 0.01 to GU), traced by a small CPU
BVH here. Not the renderer's mesh trace (host_bindings.cc
trace_instance_for_python, K2's beam_trace): the damage point is a constant
of the model, needed headless (tests, the oracle's Dauntless duels) where no
renderer instance exists, and computed once per ship as its properties are
set up (ShipClass.SetupProperties -> assign). One BVH per model per process.

A ship with no resolvable NIF (mods without one, rocks, test ships built
without a script) keeps the position as its damage point, which is what
Dauntless used for every subsystem before this.
"""
from __future__ import annotations

BC_MODEL_SCALE = 0.01          # host_loop.BC_MODEL_SCALE: NIF units -> GU
DEPTH_GU = 0.050               # how far past the hull entry the point sits
_INSIDE_DIRS = tuple(tuple(c / (sum(x * x for x in v) ** 0.5) for c in v) for v in (
    (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1),
    (1, 1, 1), (-1, -1, 1), (1, -1, -1), (-1, 1, -1), (0.3, 0.9, 0.2)))

_meshes: dict = {}             # nif path -> _Bvh, or None when unloadable
_points: dict = {}             # (nif path, (x, y, z) position) -> damage point, GU


class _Bvh:
    """Triangles (v0, e1, e2) in model units, in a median-split box tree."""
    LEAF = 8

    def __init__(self, tris):
        self.tris = tris
        cent = [[t[0][k] + (t[1][k] + t[2][k]) / 3.0 for k in range(3)] for t in tris]
        self.nodes = []        # (lo, hi, left, right, triangle indices | None)
        self._build(list(range(len(tris))), cent)

    def _bounds(self, idx):
        lo = [1e30] * 3
        hi = [-1e30] * 3
        for i in idx:
            v0, e1, e2 = self.tris[i]
            for p in (v0, [v0[k] + e1[k] for k in range(3)], [v0[k] + e2[k] for k in range(3)]):
                for k in range(3):
                    if p[k] < lo[k]:
                        lo[k] = p[k]
                    if p[k] > hi[k]:
                        hi[k] = p[k]
        return lo, hi

    def _build(self, idx, cent):
        lo, hi = self._bounds(idx)
        n = len(self.nodes)
        self.nodes.append(None)
        if len(idx) <= self.LEAF:
            self.nodes[n] = (lo, hi, -1, -1, idx)
            return n
        ax = max(range(3), key=lambda k: hi[k] - lo[k])
        idx.sort(key=lambda i: cent[i][ax])
        m = len(idx) // 2
        left = self._build(idx[:m], cent)
        right = self._build(idx[m:], cent)
        self.nodes[n] = (lo, hi, left, right, None)
        return n

    def hits(self, o, d):
        """Every crossing of the ray o + t*d (t > 0): [(t, is_entry)]. An
        entry face's normal (e1 x e2) points back along the ray."""
        inv = [1.0 / d[k] if abs(d[k]) > 1e-12 else 1e30 for k in range(3)]
        found = []
        stack = [0]
        while stack:
            lo, hi, left, right, idx = self.nodes[stack.pop()]
            tmin, tmax = 0.0, 1e30
            ok = True
            for k in range(3):
                t1 = (lo[k] - o[k]) * inv[k]
                t2 = (hi[k] - o[k]) * inv[k]
                if t1 > t2:
                    t1, t2 = t2, t1
                if t1 > tmin:
                    tmin = t1
                if t2 < tmax:
                    tmax = t2
                if tmin > tmax:
                    ok = False
                    break
            if not ok:
                continue
            if idx is None:
                stack.append(left)
                stack.append(right)
                continue
            for i in idx:
                v0, e1, e2 = self.tris[i]
                px = d[1] * e2[2] - d[2] * e2[1]
                py = d[2] * e2[0] - d[0] * e2[2]
                pz = d[0] * e2[1] - d[1] * e2[0]
                det = e1[0] * px + e1[1] * py + e1[2] * pz
                if -1e-12 < det < 1e-12:
                    continue
                f = 1.0 / det
                sx, sy, sz = o[0] - v0[0], o[1] - v0[1], o[2] - v0[2]
                u = (sx * px + sy * py + sz * pz) * f
                if u < 0.0 or u > 1.0:
                    continue
                qx = sy * e1[2] - sz * e1[1]
                qy = sz * e1[0] - sx * e1[2]
                qz = sx * e1[1] - sy * e1[0]
                v = (d[0] * qx + d[1] * qy + d[2] * qz) * f
                if v < 0.0 or u + v > 1.0:
                    continue
                t = (e2[0] * qx + e2[1] * qy + e2[2] * qz) * f
                if t > 1e-6:
                    found.append((t, det > 0.0))
        return found


def _mesh(path):
    if path not in _meshes:
        bvh = None
        try:
            import _dauntless_host as h
            tris = []
            for shp in h.nif_shapes(path):
                if shp.get("hidden"):
                    continue
                V = shp["vertices"]
                for a, b, c in shp["triangles"]:
                    v0, v1, v2 = V[a], V[b], V[c]
                    tris.append((tuple(v0), tuple(v1[k] - v0[k] for k in range(3)),
                                 tuple(v2[k] - v0[k] for k in range(3))))
            bvh = _Bvh(tris) if tris else None
        except Exception:  # noqa: BLE001 - no host / unreadable NIF: no geometry
            bvh = None
        _meshes[path] = bvh
    return _meshes[path]


def _inside(bvh, p) -> bool:
    votes = sum(len(bvh.hits(p, d)) % 2 for d in _INSIDE_DIRS)
    return votes * 2 > len(_INSIDE_DIRS)


def damage_point(path, position):
    """The damage point (model frame, GU) of a subsystem at `position`
    (x, y, z GU) on the model at NIF `path`, or None with no geometry."""
    key = (path, position)
    if key in _points:
        return _points[key]
    bvh = _mesh(path)
    if bvh is None:
        return None
    s = BC_MODEL_SCALE
    P = (position[0] / s, position[1] / s, position[2] / s)
    n = (P[0] ** 2 + P[1] ** 2 + P[2] ** 2) ** 0.5
    out = position
    if n > 1e-9 and not _inside(bvh, P):
        d = (-P[0] / n, -P[1] / n, -P[2] / n)
        entries = sorted(t for t, entry in bvh.hits(P, d) if entry)
        if entries:
            k = entries[0] + DEPTH_GU / s
            out = tuple((P[i] + d[i] * k) * s for i in range(3))
    _points[key] = out
    return out


def _nif_path(ship):
    try:
        from engine.host_loop import _ship_nif_path
        return _ship_nif_path(ship)
    except Exception:  # noqa: BLE001 - no script / stats: no geometry
        return None


def assign(ship) -> None:
    """Set every subsystem's damage point from the ship's model
    (`_damage_point`, `_damage_point_set`); a ship with no model keeps
    each subsystem's position. Called once the ship's properties are set up."""
    from engine.appc.combat import _weapon_damageable_subsystems
    path = _nif_path(ship)
    if not path:
        return
    for sub in _weapon_damageable_subsystems(ship):
        pos = sub.GetPositionTG() if hasattr(sub, "GetPositionTG") else None
        if pos is None:
            continue
        dp = damage_point(path, (float(pos.x), float(pos.y), float(pos.z)))
        if dp is None:
            return
        sub.SetDamagePoint(dp)
