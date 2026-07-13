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
    avoid if it falls within fPredictionTime."""
    # Already within personal space + their radius?
    dx = pb.x - pa.x; dy = pb.y - pa.y; dz = pb.z - pa.z
    dist = math.sqrt(dx * dx + dy * dy + dz * dz)
    if dist < (personal_space + rb):
        return True

    # Relative velocity (ours minus theirs) and the collision quadratic.
    vdx = va.x - vb.x; vdy = va.y - vb.y; vdz = va.z - vb.z
    a = vdx * vdx + vdy * vdy + vdz * vdz
    if a <= 0.0:
        return False  # no relative motion: already handled the overlap case

    # vPosDiff = ship - object  (note the sign vs dp above)
    px = pa.x - pb.x; py = pa.y - pb.y; pz = pa.z - pb.z
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
    for vDirection, vVelocity, blocked_dot, favorability in dir_info:
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

        # Similar calculations against the obstacle's velocity.
        vel_dir, _ = _unitize(vVelocity)
        if (vel_dir.x * vel_dir.x + vel_dir.y * vel_dir.y
                + vel_dir.z * vel_dir.z) > 0.0625:
            vdot = (vel_dir.x * test_dir.x + vel_dir.y * test_dir.y
                    + vel_dir.z * test_dir.z)
            appeal = (abs(vdot) - 0.5) * 2.0 * favorability
            overall += appeal

            # Avoid moving in front of the obstacle: compare the perpendicular
            # components (the SDK's `if 1:` branch is always taken).
            test_perp = _perpendicular_component(test_dir, vVelocity)
            dir_perp = _perpendicular_component(vDirection, vVelocity)
            test_perp, _ = _unitize(test_perp)
            dir_perp, _ = _unitize(dir_perp)
            pdot = (test_perp.x * dir_perp.x + test_perp.y * dir_perp.y
                    + test_perp.z * dir_perp.z)
            appeal = pdot * favorability
            overall += appeal

        # A little goodness for staying near our forward vector.
        overall += (forward.x * vDirection.x + forward.y * vDirection.y
                    + forward.z * vDirection.z) * 0.1

    return overall


def _is_direction_safe(test_dir, dir_info) -> bool:
    """Whether test_dir points clear of every obstacle's blocked cone (SDK
    IsDirectionSafe)."""
    for vDirection, _vVelocity, blocked_dot, _favorability in dir_info:
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
        dir_info.append((unit, TGPoint3(vb.x, vb.y, vb.z),
                         blocked_dot, favorability))

    if not dir_info:
        return None, None

    flee_dir = None
    flee_appeal = -1.0e20

    # First, test the opposite of each obstacle direction.
    for vDirection, _vel, _bd, _fav in dir_info:
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

    avoid_list = []
    for other in iter_set_objects(pSet):
        if other is ship:
            continue
        # Per-pair collision mask (DamageableObject.EnableCollisionsWith),
        # honoured symmetrically exactly as collisions.resolve_collisions does:
        # a ship docking with a starbase calls EnableCollisionsWith(pStarbase, 0)
        # (AI.Compound.DockWithStarbase.SetupCutscene) precisely so it can fly
        # right up to it — avoidance must not then evade the dock target and
        # override the docking AI's steering (E6M2 fly-in flew off otherwise).
        try:
            if (other.GetObjID() in _collision_disabled_ids(ship)
                    or ship.GetObjID() in _collision_disabled_ids(other)):
                continue
        except Exception:
            pass
        # Type filtering: skip blacklisted class types (SDK NeedToAvoid first
        # check, via IsTypeOf against lDontAvoidTypes). We read the obstacle's
        # type with isinstance against the engine's CT_* classes.
        if isinstance(other, blacklist):
            continue
        try:
            ob_loc = other.GetWorldLocation()
            ob_r = float(other.GetRadius())
        except Exception:
            continue
        if ob_r <= 0.0:
            continue
        # Prefilter: only objects within check_radius of the predicted
        # position (SDK GetNearObjects).
        dx = ob_loc.x - predicted.x
        dy = ob_loc.y - predicted.y
        dz = ob_loc.z - predicted.z
        if (dx * dx + dy * dy + dz * dz) > (check_radius * check_radius):
            continue
        ob_vel = _world_velocity(other)
        if _need_to_avoid(ship_loc, ship_vel, personal_space,
                          ob_loc, ob_vel, ob_r):
            avoid_list.append((TGPoint3(ob_loc.x, ob_loc.y, ob_loc.z),
                               ob_vel, ob_r))

    return _avoid_objects(ship, ship.GetWorldForwardTG(), avoid_list,
                          previous_heading=previous_heading)


# ── Per-tick driver (loop.py call site — do NOT rename) ─────────────────────


def tick_collision_avoidance(dt: float = 1.0 / 60.0) -> None:
    """Override the heading + thrust of every AI ship on an imminent
    collision course. Call once per tick after tick_all_ai, before
    tick_all_ship_motion.

    Adaptive cadence (SDK Update/GetNextUpdateTime): when not actively
    evading, a ship is only re-evaluated every fMaximumUpdateDelay (0.25 s);
    while overriding, it re-evaluates every tick (fMinimumUpdateDelay = 0.0).
    Between evaluations the cached decision is re-applied while overriding."""
    global _clock_s
    _clock_s += dt

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
