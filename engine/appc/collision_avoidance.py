"""AI ship collision avoidance — full port of the SDK AvoidObstacles
preprocessor (sdk/Build/scripts/AI/Preprocessors.py:1621-2009).

The SDK movement scripts (BaseAI / CircleObject / IntelligentCircleObject)
only ever command a *desired heading + impulse fraction* via pCodeAI /
SetImpulse. In stock Bridge Commander the per-AI ``AvoidObstacles``
preprocessor sat in front of that AI and, when a collision was imminent,
overrode the heading + throttle to steer clear — which is why ramming an AI
ship was so hard. Our Phase-1 ship_motion integrator simply follows the
commanded vector, so that avoidance was missing entirely.

This module restores the FULL SDK behaviour. It is a direct port of
``AvoidObstacles`` (``NeedToAvoid`` ~1769-1842, ``AvoidObjects`` ~1844-1924,
``CalculateDirectionAppeal`` ~1926-1993, ``IsDirectionSafe`` ~1995-2009),
with the one architectural difference noted below.

Architecture note — global routine vs PreprocessingAI
-----------------------------------------------------
The SDK ``AvoidObstacles.Update`` returns ``PS_SKIP_ACTIVE`` while it is
actively overriding the course (suppressing the contained AI) and
``PS_NORMAL`` otherwise. Dauntless runs avoidance as a single global
per-tick routine (``tick_collision_avoidance``) called from
engine/core/loop.py AFTER ``tick_all_ai`` and BEFORE
``tick_all_ship_motion`` — not as a per-AI PreprocessingAI. Because it runs
after the AI has written its heading/throttle, "actively overriding" is the
global-routine analog of ``PS_SKIP_ACTIVE``: while evading, this routine
fully owns the ship's heading + thrust for that tick (it wins by running
last). We record that state per ship (``is_overriding``) so the behaviour is
observable/testable; not overriding == ``PS_NORMAL``.

Gating: only ships with an attached AI (``GetAI()`` is not None) are steered.
The player ship is driven by _PlayerControl with ``GetAI() == None``, so it
is never auto-avoided.
"""
import math
import random

from engine.appc.math import TGPoint3
from engine.appc.objects import PhysicsObjectClass
from engine.core.ids import implements

# ── SDK AvoidObstacles tunables (Preprocessors.py:1622-1665) ────────────────

# How far into the future we anticipate collisions (SDK fPredictionTime).
AVOID_PREDICTION_TIME_S = 15.0

# Minimum radius around the predicted position to search for incoming
# objects (SDK fMinimumRadius; "225 is about 40km").
AVOID_MINIMUM_RADIUS_GU = 225.0

# Personal space as a multiple of the ship's own radius (SDK fPersonalSpace).
AVOID_PERSONAL_SPACE_MULT = 2.5

# Re-evaluate at most this often when no threat is imminent (SDK
# fMaximumUpdateDelay); every tick (0.0, SDK fMinimumUpdateDelay) while
# actively evading.
AVOID_MAX_UPDATE_DELAY_S = 0.25
AVOID_MIN_UPDATE_DELAY_S = 0.0

# Impulse fraction along model-forward when the current forward is safe
# (SDK fSpeed = 1.0 if bFacingSafe else 0.0).
AVOID_SAFE_SPEED = 1.0
AVOID_UNSAFE_SPEED = 0.0

# Object class types we never bother avoiding (SDK lDontAvoidTypes). Resolved
# to engine classes lazily (App import) so module import stays cheap.
_DONT_AVOID_TYPE_NAMES = (
    "CT_PROXIMITY_CHECK",
    "CT_DEBRIS",
    "CT_TORPEDO",
    "CT_ASTEROID_FIELD",
    "CT_NEBULA",
)

# Deterministic RNG for the 8 sampled candidate flee directions
# (Preprocessors.py:1903-1912 uses App.TGPoint3_GetRandomUnitVector). A fixed
# seed makes evasion reproducible so tests can assert identical trajectories;
# the rest of the engine likewise seeds stdlib random where determinism
# matters (see engine/appc/particles.py). Seed 0xC0111DE ("collide").
_AVOID_RNG_SEED = 0xC0111DE
_rng = random.Random(_AVOID_RNG_SEED)

# Per-ship avoidance state, keyed by id(ship): last evaluation game-time, the
# cached (heading, speed) decision, and whether we are actively overriding
# (the PS_SKIP_ACTIVE analog). Survives across ticks; cleared by
# reset_avoidance_state().
_ship_state: dict = {}

# Monotonic game clock advanced per tick (sum of dt), used for the adaptive
# update-delay cadence. Reset by reset_avoidance_state().
_clock_s = 0.0


def reset_avoidance_state() -> None:
    """Clear all per-ship state and reseed the RNG. Call between independent
    runs/missions so cadence and sampled directions are reproducible."""
    global _clock_s
    _ship_state.clear()
    _clock_s = 0.0
    _rng.seed(_AVOID_RNG_SEED)


def is_overriding(ship) -> bool:
    """Whether avoidance is currently overriding `ship`'s course this tick
    (the global-routine analog of the SDK's PS_SKIP_ACTIVE). Observable for
    tests/HUD."""
    st = _ship_state.get(id(ship))
    return bool(st and st.get("overriding"))


def _dont_avoid_types():
    import App
    out = []
    for name in _DONT_AVOID_TYPE_NAMES:
        cls = getattr(App, name, None)
        if isinstance(cls, type):
            out.append(cls)
    return tuple(out)


def _world_velocity(obj) -> TGPoint3:
    """Best-estimate world velocity: thrust velocity plus any active
    collision-response overlay. Mirrors collisions._resolve_body so the
    prediction matches the integrator the ship actually moves under.

    The obstacle list is every object in the set, so `obj` is regularly a
    Planet / Waypoint — an ObjectClass, with no GetVelocity (that starts at
    PhysicsObjectClass). implements(), NOT hasattr(): TGObject.__getattr__
    hands back a truthy _Stub for any missing engine method, so the old call
    reached a stub on every planet, every evaluation (heatmap ranks 7-10,
    4,924 hits). It was harmless — TGPoint3 floats its args and _Stub.__float__
    is 0.0, so the components landed on exactly the zero vector
    collisions._resolve_body forces for a planet — but it was churn, and it
    only stayed harmless by accident."""
    if implements(obj, "GetVelocity"):
        try:
            v = obj.GetVelocity()
            v = TGPoint3(v.x, v.y, v.z)
        except Exception:
            v = TGPoint3(0.0, 0.0, 0.0)
    else:
        # Planets/moons/suns/waypoints: fixed anchors, zero velocity.
        v = TGPoint3(0.0, 0.0, 0.0)
    cv = obj.__dict__.get("_collision_velocity")
    if cv is not None:
        v = v + cv
    return v


def _unitize(v: TGPoint3):
    """Return (unit_vector, length). Length 0 ⇒ returns (zero, 0.0)."""
    n = v.Length()
    if n < 1e-12:
        return TGPoint3(0.0, 0.0, 0.0), 0.0
    return TGPoint3(v.x / n, v.y / n, v.z / n), n


def _perpendicular_component(v: TGPoint3, axis: TGPoint3) -> TGPoint3:
    """Component of v perpendicular to axis: v - (v·â)â (SDK
    TGPoint3.GetPerpendicularComponent)."""
    a, alen = _unitize(axis)
    if alen == 0.0:
        return TGPoint3(v.x, v.y, v.z)
    d = v.x * a.x + v.y * a.y + v.z * a.z
    return TGPoint3(v.x - d * a.x, v.y - d * a.y, v.z - d * a.z)


def _random_unit_vector() -> TGPoint3:
    """Uniform random unit vector from the seeded RNG (analog of
    App.TGPoint3_GetRandomUnitVector)."""
    while True:
        x = _rng.uniform(-1.0, 1.0)
        y = _rng.uniform(-1.0, 1.0)
        z = _rng.uniform(-1.0, 1.0)
        n2 = x * x + y * y + z * z
        if 1e-6 < n2 <= 1.0:
            n = math.sqrt(n2)
            return TGPoint3(x / n, y / n, z / n)


# ── NeedToAvoid (Preprocessors.py:1769-1842) ────────────────────────────────


def _need_to_avoid(pa, va, personal_space, pb, vb, rb) -> bool:
    """Whether the ship at pa (velocity va) with the given personal-space
    radius must avoid the obstacle at pb (velocity vb, radius rb).

    Direct port: already-inside-personal-space ⇒ avoid; otherwise solve the
    relative-velocity quadratic for the soonest non-negative hit time and
    avoid if it falls within fPredictionTime.

    Vector-argument wrapper over _need_to_avoid_xyz. Callers on the hot path
    already hold the obstacle's components as scalars (the per-tick snapshot),
    and should use the scalar form directly rather than fetching a TGPoint3
    back out of the object -- GetWorldLocation was 671,586 calls over 150 ticks
    purely to re-supply coordinates the snapshot had already resolved.
    """
    return _need_to_avoid_xyz(pa.x, pa.y, pa.z, va.x, va.y, va.z,
                              personal_space,
                              pb.x, pb.y, pb.z, vb.x, vb.y, vb.z, rb)


def _need_to_avoid_xyz(pax, pay, paz, vax, vay, vaz, personal_space,
                       pbx, pby, pbz, vbx, vby, vbz, rb) -> bool:
    """Scalar core of _need_to_avoid. Identical maths, no vector objects."""
    # Already within personal space + their radius?
    dx = pbx - pax; dy = pby - pay; dz = pbz - paz
    dist = math.sqrt(dx * dx + dy * dy + dz * dz)
    if dist < (personal_space + rb):
        return True

    # Relative velocity (ours minus theirs) and the collision quadratic.
    vdx = vax - vbx; vdy = vay - vby; vdz = vaz - vbz
    a = vdx * vdx + vdy * vdy + vdz * vdz
    if a <= 0.0:
        return False  # no relative motion: already handled the overlap case

    # vPosDiff = ship - object  (note the sign vs dp above)
    px = pax - pbx; py = pay - pby; pz = paz - pbz
    b = 2.0 * (px * vdx + py * vdy + pz * vdz)
    radius_sum = personal_space + rb
    c = -(radius_sum * radius_sum) + (px * px + py * py + pz * pz)

    hit_time = -1.0
    sqrt_part = b * b - 4.0 * a * c
    if sqrt_part >= 0.0:
        sq = math.sqrt(sqrt_part)
        t1 = (-b + sq) / (2.0 * a)
        t2 = (-b - sq) / (2.0 * a)
        # SDK four-case root selection: take the soonest non-negative root.
        if t1 < t2:
            hit_time = t1 if t1 >= 0.0 else t2
        else:
            hit_time = t2 if t2 >= 0.0 else t1

    if hit_time >= 0.0 and hit_time < AVOID_PREDICTION_TIME_S:
        return True
    return False


# ── CalculateDirectionAppeal (Preprocessors.py:1926-1993) ───────────────────


def _calculate_direction_appeal(forward, test_dir, dir_info) -> float:
    """Score a candidate flee direction against every obstacle's direction
    info. Direct port of CalculateDirectionAppeal.

    dir_info entries: (vDirection, vVelocity, fBlockedDot, fFavorability),
    where vDirection is the unit ship→obstacle direction.
    """
    overall = 0.0
    for (vDirection, vVelocity, blocked_dot, favorability,
         vux, vuy, vuz, vel_significant, dpx, dpy, dpz) in dir_info:
        dot = (test_dir.x * vDirection.x + test_dir.y * vDirection.y
               + test_dir.z * vDirection.z)

        if dot >= blocked_dot:
            # Inside the blocked cone: full favorability (and SDK 'continue's,
            # skipping the velocity/forward terms for this obstacle).
            # NOTE: matches the SDK's `continue` — fAppeal is set but not added.
            continue
        else:
            if dot >= 0.0:
                try:
                    appeal = favorability - (2.0 * favorability
                                             * (blocked_dot - dot) / blocked_dot)
                except ZeroDivisionError:
                    appeal = -favorability
            else:
                appeal = (favorability * dot * 0.5) + (favorability * (1.0 + dot))

        overall += appeal * 2.0

        # Similar calculations against the obstacle's velocity. The unitised
        # velocity and the obstacle's own perpendicular component are hoisted
        # into dir_info -- see _avoid_objects. Only test_dir varies here, so
        # only its perpendicular component is computed, and in scalars.
        if vel_significant:
            vdot = vux * test_dir.x + vuy * test_dir.y + vuz * test_dir.z
            appeal = (abs(vdot) - 0.5) * 2.0 * favorability
            overall += appeal

            # Avoid moving in front of the obstacle: compare the perpendicular
            # components (the SDK's `if 1:` branch is always taken).
            tpx = test_dir.x - vdot * vux
            tpy = test_dir.y - vdot * vuy
            tpz = test_dir.z - vdot * vuz
            tplen = math.sqrt(tpx * tpx + tpy * tpy + tpz * tpz)
            if tplen >= 1e-12:
                pdot = ((tpx / tplen) * dpx + (tpy / tplen) * dpy
                        + (tpz / tplen) * dpz)
            else:
                pdot = 0.0
            overall += pdot * favorability

        # A little goodness for staying near our forward vector.
        overall += (forward.x * vDirection.x + forward.y * vDirection.y
                    + forward.z * vDirection.z) * 0.1

    return overall


def _is_direction_safe(test_dir, dir_info) -> bool:
    """Whether test_dir points clear of every obstacle's blocked cone (SDK
    IsDirectionSafe)."""
    for entry in dir_info:
        vDirection, blocked_dot = entry[0], entry[2]
        dot = (test_dir.x * vDirection.x + test_dir.y * vDirection.y
               + test_dir.z * vDirection.z)
        if dot >= blocked_dot:
            return False
    return True


# ── AvoidObjects (Preprocessors.py:1844-1924) ───────────────────────────────


def _avoid_objects(ship, forward, avoid_list, previous_heading=None):
    """Given the ship, its world-forward, and the obstacles to avoid (each a
    (pb, vb, rb) tuple), return (heading, speed) or (None, None). Direct port
    of AvoidObjects + the appeal search.

    `previous_heading`, when supplied, is also entered into the appeal contest.
    The SDK re-rolls 8 fresh random directions every evasion tick, which makes
    the chosen heading thrash and prevents a committed escape under a fast
    turn rate. Re-testing the heading we're already flying lets a still-good
    choice win, so the ship commits to one arc instead of jittering — the same
    spirit as the SDK testing the current forward direction."""
    if not avoid_list:
        return None, None

    ship_loc = ship.GetWorldLocation()
    ship_r = ship.GetRadius()

    dir_info = []
    for pb, vb, rb in avoid_list:
        vd = TGPoint3(pb.x - ship_loc.x, pb.y - ship_loc.y, pb.z - ship_loc.z)
        unit, distance = _unitize(vd)
        if distance <= 0.0:
            # Co-located: can't pick a direction away from it.
            continue
        blocked_angle = math.atan((rb + ship_r) / distance)
        blocked_dot = math.cos(blocked_angle)
        favorability = -AVOID_MINIMUM_RADIUS_GU / distance
        # Precompute everything about this obstacle that the per-candidate
        # scorer would otherwise redo for EVERY test direction. _unitize(vel)
        # and the perpendicular component of vDirection about vel depend only
        # on the obstacle, and the scorer is called once per candidate
        # direction with the same dir_info -- so they were being recomputed
        # ~63 times each, allocating a TGPoint3 every time. TGPoint3.__init__
        # was the single hottest line in the sim at 2.58 M calls / 150 ticks.
        #
        # Stored as bare floats, not vectors: the scorer needs components, and
        # rebuilding a TGPoint3 to read .x/.y/.z back out is the allocation
        # this exists to remove.
        vux, vuy, vuz = 0.0, 0.0, 0.0
        vel_significant = False
        dpx, dpy, dpz = unit.x, unit.y, unit.z
        vlen = math.sqrt(vb.x * vb.x + vb.y * vb.y + vb.z * vb.z)
        if vlen >= 1e-12:
            vux, vuy, vuz = vb.x / vlen, vb.y / vlen, vb.z / vlen
            # The SDK gate: a unit vector's squared length is 1, so this is
            # "the obstacle is actually moving" expressed as the port has it.
            vel_significant = (vux * vux + vuy * vuy + vuz * vuz) > 0.0625
            # Perpendicular component of vDirection about the velocity axis,
            # then unitised -- both obstacle-constant.
            d = unit.x * vux + unit.y * vuy + unit.z * vuz
            dpx = unit.x - d * vux
            dpy = unit.y - d * vuy
            dpz = unit.z - d * vuz
            dplen = math.sqrt(dpx * dpx + dpy * dpy + dpz * dpz)
            if dplen >= 1e-12:
                dpx, dpy, dpz = dpx / dplen, dpy / dplen, dpz / dplen
            else:
                dpx = dpy = dpz = 0.0
        dir_info.append((unit, TGPoint3(vb.x, vb.y, vb.z),
                         blocked_dot, favorability,
                         vux, vuy, vuz, vel_significant, dpx, dpy, dpz))

    if not dir_info:
        return None, None

    flee_dir = None
    flee_appeal = -1.0e20

    # First, test the opposite of each obstacle direction.
    for entry in dir_info:
        vDirection = entry[0]
        test = TGPoint3(-vDirection.x, -vDirection.y, -vDirection.z)
        appeal = _calculate_direction_appeal(forward, test, dir_info)
        if appeal > flee_appeal:
            flee_appeal = appeal
            flee_dir = test

    # Then 8 sampled random directions from the seeded RNG.
    for _ in range(8):
        test = _random_unit_vector()
        appeal = _calculate_direction_appeal(forward, test, dir_info)
        if appeal > flee_appeal:
            flee_appeal = appeal
            flee_dir = test

    # Finally, re-test the heading we are already committed to (if any) so a
    # working escape keeps winning instead of being abandoned for a fresh
    # random sample each tick.
    if previous_heading is not None:
        appeal = _calculate_direction_appeal(forward, previous_heading, dir_info)
        if appeal >= flee_appeal:
            flee_appeal = appeal
            flee_dir = TGPoint3(previous_heading.x, previous_heading.y,
                                previous_heading.z)

    # Speed depends on whether our CURRENT forward is safe.
    facing_safe = _is_direction_safe(forward, dir_info)
    speed = AVOID_SAFE_SPEED if facing_safe else AVOID_UNSAFE_SPEED

    return flee_dir, speed


# ── TestCourseOverride (Preprocessors.py:1713-1767) ─────────────────────────


def _test_course_override(ship, previous_heading=None):
    """Build the avoid list for `ship` and return the (heading, speed)
    override, or (None, None). Direct port of TestCourseOverride."""
    pSet = ship.GetContainingSet()
    if pSet is None:
        return None, None

    ship_loc = ship.GetWorldLocation()
    ship_vel = _world_velocity(ship)
    ship_r = ship.GetRadius()

    # Predict our location fPredictionTime ahead (acceleration ~= 0, so this
    # is p + v·t, matching GetPredictedPosition with a = 0).
    predicted = TGPoint3(
        ship_loc.x + ship_vel.x * AVOID_PREDICTION_TIME_S,
        ship_loc.y + ship_vel.y * AVOID_PREDICTION_TIME_S,
        ship_loc.z + ship_vel.z * AVOID_PREDICTION_TIME_S,
    )
    travel = TGPoint3(predicted.x - ship_loc.x,
                      predicted.y - ship_loc.y,
                      predicted.z - ship_loc.z).Length()

    personal_space = ship_r * AVOID_PERSONAL_SPACE_MULT
    check_radius = travel + personal_space
    if check_radius < AVOID_MINIMUM_RADIUS_GU:
        check_radius = AVOID_MINIMUM_RADIUS_GU

    from engine.appc.ship_iter import iter_set_objects
    blacklist = _dont_avoid_types()

    from engine.appc.collisions import _collision_disabled_ids
    from engine.appc.hull_bounds import (has_hull_bounds, hull_spheres_near,
                                         bound_radius as hull_bound_radius)

    avoid_list = []
    # Loop-invariant: depends on `ship`, not on the obstacle, so it was being
    # rebuilt once per PAIR for one answer per ship.
    try:
        ship_disabled = _collision_disabled_ids(ship)
        ship_obj_id = ship.GetObjID()
    except Exception:
        ship_disabled, ship_obj_id = frozenset(), None

    check_radius_sq = check_radius * check_radius
    px, py, pz = predicted.x, predicted.y, predicted.z
    # Scalar copies for the gate: the loop below runs once per obstacle and
    # attribute access on the ship's vectors is not free at that volume.
    slx, sly, slz = ship_loc.x, ship_loc.y, ship_loc.z
    svx, svy, svz = ship_vel.x, ship_vel.y, ship_vel.z

    # Everything observer-independent is resolved once per tick, not once per
    # (observer, obstacle) pair. See obstacle_snapshot.
    for (other, ox, oy, oz, ob_r, ob_vel, gate_r, ob_id,
         ob_disabled) in obstacle_snapshot(pSet):
        if other is ship:
            continue
        # DISTANCE FIRST. Every test below it is a `continue`, so their order
        # among themselves cannot change which obstacles end up in avoid_list --
        # only how much work is done reaching that answer. This is an all-pairs
        # loop nested inside a loop over all AI ships, so the ordering was the
        # whole cost.
        dx = ox - px
        dy = oy - py
        dz = oz - pz
        if (dx * dx + dy * dy + dz * dz) > check_radius_sq:
            continue

        # ── Whole-body convergence gate ────────────────────────────────
        # Test the obstacle's bounding sphere before expanding it into pieces.
        # Conservative: every piece lies inside the sphere, so if the sphere is
        # not on a collision course within the prediction window, no piece of it
        # can be. Only converging obstacles pay for expansion.
        #
        # This is the filter the proximity query is not. Measured over 40,320
        # pair-samples at 64 ships: 47.7% pass the 225 GU proximity query,
        # 1.48% are actually converging -- a ~32x tighter predicate.
        #
        # gate_r is max(GetRadius(), the piece-derived bound), resolved in the
        # snapshot: GetRadius() alone is unsound because host_loop only derives
        # it from the model AABB when the SDK left it at 0, so an authored
        # radius can be smaller than the geometry.
        #
        # _need_to_avoid's "already inside personal space" clause returns True
        # regardless of velocity, so a body already overlapping is never gated
        # out.
        if not _need_to_avoid_xyz(slx, sly, slz, svx, svy, svz,
                                  personal_space, ox, oy, oz,
                                  ob_vel.x, ob_vel.y, ob_vel.z, gate_r):
            continue

        # Per-pair collision mask (DamageableObject.EnableCollisionsWith),
        # honoured symmetrically exactly as collisions.resolve_collisions does:
        # a ship docking with a starbase calls EnableCollisionsWith(pStarbase, 0)
        # (AI.Compound.DockWithStarbase.SetupCutscene) precisely so it can fly
        # right up to it — avoidance must not then evade the dock target and
        # override the docking AI's steering (E6M2 fly-in flew off otherwise).
        if (ob_id in ship_disabled
                or (ship_obj_id is not None and ship_obj_id in ob_disabled)):
            continue
        # Past the gate. Only obstacles that could actually collide reach
        # here, so building the vector the pieces path needs is now rare --
        # it used to be a GetWorldLocation() on every pair.
        ob_loc = TGPoint3(ox, oy, oz)

        if has_hull_bounds(other):
            # MEASURED DEAD END, do not retry without new evidence. Passing the
            # geometric bound here instead of check_radius (travel + ob_travel +
            # personal_space, ~64 GU median vs the 225 GU floor) is tighter for
            # 100% of pairs and still culls NOTHING: ships in a fight sit 20-40
            # GU apart, so every piece of every obstacle is legitimately inside
            # it. Three live runs at 33 ships moved gl.avoidance 14.1/19.6/21.3
            # against a 16.2/21.9 baseline -- pure noise.
            #
            # The pieces are not wasted work; they are genuinely near. Making
            # avoidance scale therefore means fewer pieces (a coarse hull for
            # avoidance rather than the 128-leaf collision decomposition) or a
            # cheaper cadence -- NOT a tighter cull.
            pieces = hull_spheres_near(other, predicted, check_radius)
        else:
            pieces = [(ob_loc, ob_r)]
        for piece_loc, piece_r in pieces:
            if piece_r <= 0.0:
                continue
            if _need_to_avoid(ship_loc, ship_vel, personal_space,
                              piece_loc, ob_vel, piece_r):
                avoid_list.append((TGPoint3(piece_loc.x, piece_loc.y,
                                            piece_loc.z),
                                   ob_vel, piece_r))

    return _avoid_objects(ship, ship.GetWorldForwardTG(), avoid_list,
                          previous_heading=previous_heading)


# ── Per-tick driver (loop.py call site — do NOT rename) ─────────────────────


def tick_collision_avoidance(dt: float = 1.0 / 60.0) -> None:
    """Override the heading + thrust of every AI ship on an imminent
    collision course. Call once per tick after tick_all_ai, before
    tick_all_ship_motion.

    ⚠️ NO LONGER WIRED INTO THE ENGINE. GameLoop.tick does not call this.
    Avoidance is the AvoidObstacles preprocessor, dispatched inside tick_all_ai
    as part of each ship's AI tree; see docs/engine/avoidance-duplication.md.

    Retained because tests/integration/test_collision_avoidance.py drives the
    steering behaviour through it, and it remains an honest way to exercise
    avoidance over every AI ship at once. It shares _test_course_override with
    the preprocessor path, so what those tests assert is still the live
    implementation -- but it is a TEST DRIVER now, not a production phase.
    Do not re-add a call to it from the game loop.

    The premise it was built on ("the SDK movement scripts only command a
    heading; the C++ autopilot steered around obstacles") was WRONG. BC's avoidance is
    ``AvoidObstacles``, a PREPROCESSOR in the AI tree (AI/Preprocessors.py:1621),
    which the engine swaps for a native node at bind time via
    ``PreprocessingAI::SetContainedAI`` -> ``GetOptimizedVersion`` (vtable +0x34,
    0x0048E570 / 0x0048EB20). It was never a separate autopilot layer.

    Measured on E3M1: the one AI ship carries an ``AvoidObstacles_NonLethal``
    node in its tree AND is steered by this function. tick_all_ai runs first,
    so the SDK preprocessor does a full obstacle scan and calls
    TurnTowardDirection/SetImpulse -- and then THIS function overwrites the
    result. Real missions pay for avoidance twice and discard the first answer.

    (combat_stress uses BasicAttack, which installs no AvoidObstacles, so every
    avoidance measurement taken against it is of this path alone.)

    Adaptive cadence (SDK Update/GetNextUpdateTime): when not actively
    evading, a ship is only re-evaluated every fMaximumUpdateDelay (0.25 s);
    while overriding, it re-evaluates every tick (fMinimumUpdateDelay = 0.0).
    Between evaluations the cached decision is re-applied while overriding."""
    global _clock_s
    _clock_s += dt
    # This is a per-tick entry point, so the world may have moved since the
    # last call. See invalidate_obstacle_snapshot.
    invalidate_obstacle_snapshot()

    from engine.appc.ships import ShipClass
    from engine.appc.collisions import iter_collidables

    live_ids = set()
    for obj in iter_collidables():
        if not isinstance(obj, ShipClass):
            continue
        if obj.GetAI() is None:        # player / uncontrolled: never auto-steer
            continue
        if obj.IsImmobile():           # stations/drydocks: anchored, never steered
            continue
        live_ids.add(id(obj))

        st = _ship_state.setdefault(
            id(obj), {"last_eval": -1e18, "heading": None,
                      "speed": None, "overriding": False})

        # In-system warp: never override; the warp check does its own
        # clearance (Preprocessors.py:1692-1693).
        try:
            in_warp = obj.IsDoingInSystemWarp()
        except Exception:
            in_warp = 0
        if in_warp:
            st["overriding"] = False
            st["heading"] = None
            st["speed"] = None
            st["last_eval"] = _clock_s
            continue

        delay = (AVOID_MIN_UPDATE_DELAY_S if st["overriding"]
                 else AVOID_MAX_UPDATE_DELAY_S)
        due = (_clock_s - st["last_eval"]) >= delay

        if due:
            prev = st["heading"] if st["overriding"] else None
            heading, speed = _test_course_override(obj, previous_heading=prev)
            st["last_eval"] = _clock_s
            st["heading"] = heading
            st["speed"] = speed
            st["overriding"] = heading is not None

        if st["overriding"] and st["heading"] is not None:
            # Actively evading — owns heading + thrust this tick (the
            # PS_SKIP_ACTIVE analog; runs after tick_all_ai so it wins).
            # Turn the nose toward the escape heading and thrust along model
            # forward; ship_motion drives velocity along the ship's facing,
            # so a model-space thrust banks the ship away on a natural arc.
            obj.TurnTowardDirection(st["heading"])
            obj.SetImpulse(st["speed"], TGPoint3(0.0, 1.0, 0.0),
                           PhysicsObjectClass.DIRECTION_MODEL_SPACE)

    # Drop state for ships that left play so the dict can't grow unbounded.
    for dead in [k for k in _ship_state if k not in live_ids]:
        del _ship_state[dead]


def course_override_for(node):
    """Engine-side ``AvoidObstacles.TestCourseOverride`` for a preprocessor node.

    Returns ``(direction, speed)`` exactly as the SDK method does — ``direction``
    is a TGPoint3 while overriding and None otherwise, which is what the SDK's
    ``Update`` tests for truthiness before steering.

    Overriding ONLY this method leaves the rest of the SDK node running
    verbatim: the ``PS_SKIP_ACTIVE`` return, the ``TurnTowardDirection`` /
    ``SetImpulse`` calls, the ``fUpdateDelay`` cadence, ``GetNextUpdateTime``
    (which our driver already honours, so the 0.25 s idle / every-tick evading
    cadence is preserved for free), and the pickle hooks. The only thing
    replaced is the world SCAN, which is the only part that was slow.

    ``vOverrideDirection`` carries the previous committed heading, which
    ``_avoid_objects`` uses for hysteresis — the SDK stores it on the node for
    exactly the same reason our per-ship state dict did.
    """
    ai = getattr(node, "pCodeAI", None)
    if ai is None:
        return None, 0.0
    ship = ai.GetShip() if hasattr(ai, "GetShip") else None
    if ship is None:
        return None, 0.0
    # __dict__, not getattr: an engine-backed node inherits TGObject's
    # __getattr__, which vends a truthy _Stub for a missing name and would make
    # "no previous override" read as a heading.
    prev = node.__dict__.get("vOverrideDirection") or None
    _SCAN_COUNT[0] += 1
    r = _test_course_override(ship, previous_heading=prev)
    if r[0] is not None:
        _SCAN_COUNT[1] += 1
    return r


_SCAN_COUNT = [0, 0]


# ── Per-tick obstacle snapshot ──────────────────────────────────────────────
# Everything _test_course_override needs to know about an OBSTACLE is
# independent of who is looking at it: world position, velocity, radius, the
# piece-derived bound radius, its object id, its collision mask and whether its
# type is blacklisted. Only the tests are observer-dependent.
#
# Resolved per observer, that is O(ships x obstacles) calls for O(obstacles)
# distinct answers. Measured at 100 ships with avoidance running,
# _world_velocity alone was 562,840 calls over 150 ticks -- 3,752 per tick for
# ~101 real values -- and _test_course_override was 55% of the whole sim tick.
#
# Valid for exactly one tick and no longer. Avoidance runs inside tick_all_ai,
# and tick_all_ship_motion integrates AFTER it, so no obstacle moves during the
# walk: the AI writes setpoints, not positions. Stamped on the game clock so a
# new tick rebuilds rather than reusing stale geometry.
_snapshot_stamp = None
_snapshot_by_set: dict = {}


def _game_time():
    """Current game time, or None when there is no usable clock.

    None, not 0.0. A constant stamp makes the snapshot cache permanently valid
    and hands every caller last-known geometry forever -- which is exactly what
    happened when this read `GetGameTime()`: our TimerManager exposes
    `get_time()`, so every call hit the except, every tick stamped 0.0, and
    test_ai_ship_avoids_ship_charging_head_on failed because the charging ship
    never appeared to move. Returning None instead makes an unusable clock
    rebuild the snapshot every time -- slower, but never stale. For a system
    that decides whether ships crash into each other, that is the right
    direction to fail in.
    """
    try:
        import App as _App
        return float(_App.g_kTimerManager.get_time())
    except Exception:
        return None


def _build_obstacle_snapshot(pSet, blacklist) -> list:
    """One pass over the set, resolving every observer-independent quantity.

    Entries are plain tuples rather than objects: this is read once per
    observer per tick, so attribute access on a wrapper would give back what
    the snapshot exists to save.
    """
    from engine.appc.ship_iter import iter_set_objects
    from engine.appc.hull_bounds import has_hull_bounds, bound_radius
    from engine.appc.collisions import _collision_disabled_ids

    out = []
    for other in iter_set_objects(pSet):
        # Type filter and the zero-radius reject are properties of the
        # obstacle, so they belong here rather than in every observer's loop.
        if isinstance(other, blacklist):
            continue
        try:
            loc = other.GetWorldLocation()
            r = float(other.GetRadius())
        except Exception:
            continue
        if r <= 0.0:
            continue
        gate_r = r
        if has_hull_bounds(other):
            piece_bound = bound_radius(other)
            if piece_bound > gate_r:
                gate_r = piece_bound
        try:
            obj_id = other.GetObjID()
        except Exception:
            obj_id = None
        out.append((other, loc.x, loc.y, loc.z, r, _world_velocity(other),
                    gate_r, obj_id, _collision_disabled_ids(other)))
    return out


def obstacle_snapshot(pSet) -> list:
    """The current tick's snapshot for `pSet`, building it on first ask."""
    global _snapshot_stamp, _snapshot_by_set
    now = _game_time()
    if now is None:
        # No usable clock: never cache. See _game_time.
        return _build_obstacle_snapshot(pSet, _dont_avoid_types())
    if _snapshot_stamp != now:
        _snapshot_stamp = now
        _snapshot_by_set = {}
    key = id(pSet)
    snap = _snapshot_by_set.get(key)
    if snap is None:
        snap = _build_obstacle_snapshot(pSet, _dont_avoid_types())
        _snapshot_by_set[key] = snap
    return snap


def invalidate_obstacle_snapshot() -> None:
    """Drop the cache. Called at the top of every sim tick.

    EXPLICIT invalidation is the primary mechanism, not the game-clock stamp.
    Inferring "new tick" from a timestamp fails whenever a caller advances the
    world without advancing the clock -- which the integration tests do (they
    move a charging ship on rails and call the avoidance driver directly), and
    which froze the snapshot at its first build so the charger never appeared
    to move. The clock check is kept as a secondary net for anything that
    invalidates the world without going through a tick entry point.
    """
    global _snapshot_stamp, _snapshot_by_set
    _snapshot_stamp = None
    _snapshot_by_set = {}
