"""ShipSubsystem.IsHittableFromLocation: is a subsystem in the line of fire?

The stock AI rates every subsystem it might target (SDK AI/Preprocessors.py
RateSubsystemForTargeting) and adds 1 to the rating of one that is hittable
from its own position, so it prefers the ones it can reach.

Measured on the original with stbc-oracle: the game's own answer for every
subsystem of fourteen ship classes, from shooter points on a 10-degree sphere
at 20, 57 and 150 GU around each ship (736,668 answers). It is 0 or 1, never
in between, and it is this rule for every kind of subsystem:

    Trace from the shooter toward the subsystem's position (GetPosition). It
    is hittable when the trace meets the hull AT OR BEFORE that position, and
    that first hull crossing is within the subsystem's radius of it.

So the position must sit no more than its radius behind the first surface a
shot from there would meet. A subsystem inside the hull is hittable from the
side whose skin is near it. A trace that misses the hull altogether, or meets
it only beyond the position, does not count: a phaser bank on the outside of
its strip (its position is the middle of its arc, PhaserBank.GetPositionTG)
answers yes only from the directions where the hull lies just in front of it
-- the Akira's dorsal banks from below, the Galaxy's ventral banks from
nowhere at all. Agreement with the original (tests/oracle/
survey_hittable_vs_original.py): 99.8% for hull, systems, sensors, engines and
bridges, 98.6% for warp cores, 99.7% for torpedo tubes, 99.9% for phaser banks,
99.8% for tractors and 100% for pulse weapons, alike at 20, 57 and 150 GU.

The hull is the ship's high-detail model as damage_point.py reads it (the
same BVH, built once per model when the ship's properties are set up), traced
by its native copy (hull_trace.cc) when the module is built. Not the
renderer's mesh trace: that needs a live render instance, which a headless
run, a test, or a ship the player has never been near does not have. Model
frame, NIF units: the shooter is carried into the ship's frame through its
world transform and scale, and the position is the subsystem's rest point
(a part that has moved, like a Bird of Prey's wing, is traced at rest). A ship with no model (a mod without a NIF, a test
ship built without a script) keeps the old answer, 1.0.
"""
from __future__ import annotations

from engine.appc import damage_point


def _mesh_for(ship):
    """The ship's hull BVH, or None. Cached on the ship (the NIF path lookup
    imports the ship's script)."""
    d = ship.__dict__ if hasattr(ship, "__dict__") else None
    if d is not None and "_hull_los_mesh" in d:
        return d["_hull_los_mesh"]
    path = damage_point._nif_path(ship)
    bvh = damage_point._mesh(path) if path else None
    if d is not None:
        d["_hull_los_mesh"] = bvh
    return bvh


def hittable_from(sub, ship, loc) -> float:
    """1.0 when `sub` on `ship` is hittable from world point `loc`, else 0.0
    (the rule above). 1.0 when there is no ship, no point or no model."""
    if ship is None or loc is None:
        return 1.0
    bvh = _mesh_for(ship)
    if bvh is None:
        return 1.0
    try:
        w = ship.GetWorldLocation()
        R = ship.GetWorldRotation()
        scale = damage_point.BC_MODEL_SCALE * float(ship.GetScale() or 1.0)
    except Exception:  # noqa: BLE001 - not a placed ship: the old answer
        return 1.0
    cols = [R.GetCol(i) for i in range(3)]

    def model(p):                              # world -> model frame, NIF units
        dx, dy, dz = p.x - w.x, p.y - w.y, p.z - w.z
        return [(c.x * dx + c.y * dy + c.z * dz) / scale for c in cols]

    o = model(loc)
    # The position at rest, as the model is: a cannon on a Bird of Prey's
    # wing answers as if the wing were not raised (measured: the posed
    # point agrees on 3% of directions, the rest point on all of them).
    p = sub.GetPositionTG()
    target = [p.x / scale, p.y / scale, p.z / scale]
    v = [target[k] - o[k] for k in range(3)]
    dist = (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) ** 0.5
    if dist <= 1e-9:
        return 1.0
    d = [x / dist for x in v]
    first = bvh.first_hit(o, d)
    if first is None or first > dist:
        return 0.0
    try:
        radius = float(sub.GetRadius() or 0.0) / scale
    except Exception:  # noqa: BLE001 - a radius-less subsystem tests the point only
        radius = 0.0
    return 1.0 if dist - first <= radius else 0.0
