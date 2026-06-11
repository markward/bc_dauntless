"""AI ship collision avoidance — reimplements the original Appc autopilot's
obstacle avoidance.

The SDK movement scripts (BaseAI / CircleObject / IntelligentCircleObject)
only ever command a *desired heading + impulse fraction* via pCodeAI /
SetImpulse. In stock Bridge Commander the C++ autopilot integrated that
command together with obstacle avoidance, which is why ramming an AI ship
was so hard at every difficulty. Our Phase-1 ship_motion integrator simply
follows the commanded vector, so that avoidance was missing entirely.

This pass restores it. Once per tick, after tick_all_ai has written each
ship's heading and before tick_all_ship_motion integrates, every
AI-controlled ship that is on an imminent collision course with another
body has its heading overridden to steer clear. It runs for ALL AI ships at
ALL times, independent of difficulty/AI mode — a safety reflex that takes
priority over normal maneuvering, exactly as the user requested.

Gating: only ships with an attached AI (GetAI() is not None) are steered.
The player ship is driven by _PlayerControl with GetAI() == None, so it is
never auto-avoided. Threats are every other collidable (ships + planets);
the avoider always keeps its commanded forward thrust and only its turn is
overridden.
"""
import math

from engine.appc.math import TGPoint3
from engine.appc.objects import PhysicsObjectClass

# Look-ahead window: only react to collisions predicted within this many
# seconds. Short enough that ships don't swerve around distant traffic,
# long enough that a limited turn rate can still clear the obstacle.
# Capital ships turn slowly, so this needs real lead time — at a ~6 GU/s
# closing speed, 12 s is ~70 GU of warning.
AVOID_HORIZON_S = 12.0

# Extra clearance added to the combined radii when deciding whether a
# predicted closest approach counts as "imminent" (game units).
AVOID_MARGIN_GU = 25.0

# Impulse fraction commanded along the escape heading during evasion. Full
# ahead — this is an emergency maneuver that overrides the AI's throttle.
AVOID_SPEED_FRACTION = 1.0


def _world_velocity(obj) -> TGPoint3:
    """Best-estimate world velocity: thrust velocity plus any active
    collision-response overlay. Mirrors collisions._resolve_body so the
    prediction matches the integrator the ship actually moves under."""
    try:
        v = obj.GetVelocity()
        v = TGPoint3(v.x, v.y, v.z)
    except Exception:
        v = TGPoint3(0.0, 0.0, 0.0)
    cv = obj.__dict__.get("_collision_velocity")
    if cv is not None:
        v = v + cv
    return v


def _perpendicular(v: TGPoint3) -> TGPoint3:
    """A unit vector perpendicular to v (for head-on escapes where the
    miss vector is degenerate). Cross with whichever world axis is least
    aligned to v to avoid a near-zero cross product."""
    ax = abs(v.x); ay = abs(v.y); az = abs(v.z)
    if ax <= ay and ax <= az:
        axis = TGPoint3(1.0, 0.0, 0.0)
    elif ay <= az:
        axis = TGPoint3(0.0, 1.0, 0.0)
    else:
        axis = TGPoint3(0.0, 0.0, 1.0)
    # cross(v, axis)
    cx = v.y * axis.z - v.z * axis.y
    cy = v.z * axis.x - v.x * axis.z
    cz = v.x * axis.y - v.y * axis.x
    out = TGPoint3(cx, cy, cz)
    length = out.Length()
    if length < 1e-9:
        return TGPoint3(1.0, 0.0, 0.0)
    return TGPoint3(out.x / length, out.y / length, out.z / length)


def _evasion_heading(pa, va, ra, pb, vb, rb):
    """Return a world-space unit heading that steers A clear of B, or None
    if no collision is imminent within the look-ahead window.

    Trigger is *time to enter the danger zone* (separation reaching
    ra + rb + margin), not time to closest approach: for a head-on
    approach the spheres overlap well before the closest-approach instant,
    so triggering on CPA gives far too little warning. We solve
    |dp + dv·t| = safety for the earliest t > 0; if that entry is within
    the horizon (or the bodies are already inside safety), A is steered
    away from B's predicted closest-approach position (or perpendicular to
    the closing line for a dead-on approach).
    """
    # Relative position / velocity of B as seen from A.
    dpx = pb.x - pa.x; dpy = pb.y - pa.y; dpz = pb.z - pa.z
    dvx = vb.x - va.x; dvy = vb.y - va.y; dvz = vb.z - va.z

    dv2 = dvx * dvx + dvy * dvy + dvz * dvz
    if dv2 < 1e-9:
        return None  # no relative motion: not closing

    safety = ra + rb + AVOID_MARGIN_GU
    dp2 = dpx * dpx + dpy * dpy + dpz * dpz
    dp_dot_dv = dpx * dvx + dpy * dvy + dpz * dvz

    # Earliest time the separation reaches `safety`. Roots of
    # dv2·t² + 2(dp·dv)·t + (dp2 - safety²) = 0.
    c = dp2 - safety * safety
    if c <= 0.0:
        t_enter = 0.0  # already within the danger zone
    else:
        if dp_dot_dv >= 0.0:
            return None  # receding (or parallel): never enters
        disc = dp_dot_dv * dp_dot_dv - dv2 * c
        if disc <= 0.0:
            return None  # closest approach still clears safety
        t_enter = (-dp_dot_dv - math.sqrt(disc)) / dv2
        if t_enter > AVOID_HORIZON_S:
            return None  # not imminent yet

    # Steer away from where B will be at closest approach.
    t_cpa = -dp_dot_dv / dv2
    if t_cpa < 0.0:
        t_cpa = 0.0
    mx = dpx + dvx * t_cpa
    my = dpy + dvy * t_cpa
    mz = dpz + dvz * t_cpa
    miss = math.sqrt(mx * mx + my * my + mz * mz)
    if miss > 1e-3:
        return TGPoint3(-mx / miss, -my / miss, -mz / miss)
    return _perpendicular(TGPoint3(dvx, dvy, dvz))


def tick_collision_avoidance() -> None:
    """Override the heading of every AI ship on an imminent collision
    course. Call once per tick after tick_all_ai, before
    tick_all_ship_motion."""
    from engine.appc.ships import ShipClass
    from engine.appc.collisions import iter_collidables

    bodies = []
    for obj in iter_collidables():
        try:
            center = obj.GetWorldLocation()
            radius = obj.GetRadius()
        except Exception:
            continue
        bodies.append((obj, TGPoint3(center.x, center.y, center.z),
                       float(radius), _world_velocity(obj)))

    for obj, pa, ra, va in bodies:
        if not isinstance(obj, ShipClass):
            continue
        if obj.GetAI() is None:        # player / uncontrolled: never auto-steer
            continue

        # Pick the most urgent threat (smallest predicted miss). Evaluate
        # every other body and keep the evasion heading for the nearest
        # imminent collision.
        best_heading = None
        best_dist2 = 1e36
        for other, pb, rb, vb in bodies:
            if other is obj:
                continue
            heading = _evasion_heading(pa, va, ra, pb, vb, rb)
            if heading is None:
                continue
            d2 = ((pb.x - pa.x) ** 2 + (pb.y - pa.y) ** 2 + (pb.z - pa.z) ** 2)
            if d2 < best_dist2:
                best_dist2 = d2
                best_heading = heading

        if best_heading is not None:
            # Urgent evasive maneuver — overrides whatever heading AND
            # throttle the AI set this tick (it runs after tick_all_ai, so
            # it wins). The AI's commanded speed in combat is frequently
            # ~0 ("stop and turn"), so avoidance must engage the engines
            # itself or the ship just pivots in place.
            #
            # Turn the nose toward the escape heading and thrust along the
            # nose (model forward), like every other ship — ship_motion
            # drives velocity along the ship's facing, so a WORLD-space
            # thrust here makes the hull "magically" strafe sideways. Nose
            # thrust + turn banks the ship away on a natural arc.
            obj.TurnTowardDirection(best_heading)
            obj.SetImpulse(AVOID_SPEED_FRACTION, TGPoint3(0.0, 1.0, 0.0),
                           PhysicsObjectClass.DIRECTION_MODEL_SPACE)
