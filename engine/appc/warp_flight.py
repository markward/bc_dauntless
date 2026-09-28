"""One in-system warp flight for every ship (in-system-warp spec, section 1).

``ShipClass.InSystemWarp`` (the SDK entry point, AI/PlainAI/Intercept.py:214)
and the player's dashes all record a ``WarpFlight`` on the ship's
``_insystem_warp_transit``; ``ship_motion`` hands every tick of it to
``step``. The flight owns the motion -- VFX and the region hand-off belong
to its callers, and so does the dashes' warp-engine state (dash.py). An "ai"
flight's WES_* state is managed here (``begin_ai_warp`` / ``end_ai_warp``):
WES_WARP_INITIATED and a hold at acceptance while the ship's articulated
parts swing to their warp pose, WES_WARPING while it flies, WES_NOT_WARPING
at every end (Mark's option A, 2026-09-28).

Coordinates. Paths are planned in SYSTEM coordinates
(``engine.systems.warp_path`` is pure math on system-space tuples). The ship
itself stays set-local: ``to_system`` / ``to_local`` convert through its
containing set's frame anchor (``engine.systems.frames``), which is zero for
an unmapped set and for a ship in no set -- there the numbers pass through
untouched, so a warp inside one unmapped set runs exactly the old arithmetic.

Targets:

* a ship (AI Intercept) -- tracked live. Each tick the line to the target's
  LIVE drop point is judged with the planner's own keep-out test
  (``warp_path.line_clear``), with hysteresis: a curve hands over to the
  straight line once that line keeps the comfort margin, and the straight
  line holds while it keeps the hard clearance. Straight, the nose leads a
  moving target (aims at the intercept point, when that line is clear too)
  and the flight ends on the drop edge of the target where it IS. Curved,
  it follows ``plan_path``'s smooth curve, re-planned only when the target
  has moved more than max(1,000 GU, 5 % of the remaining distance) since the
  last plan (ruling R8); a spent plan is re-planned, never "arrived at".
  Every plan after the first is pinned to the heading flown (``start_dir``)
  and never comes closer to a body than the ship already is; a plan the pin
  cannot hold is pivoted onto on the spot. Off a curve the nose turns at
  most ``AI_WARP_TURN_RATE_RAD_S``. Never drops out (ruling R2);
* a ``(point, end_dir)`` destination in system coordinates (Set Course) --
  planned once (``end_dir`` None since 1eb145a5: the dash arrives facing its
  travel and turns afterwards);
* ``None`` with a ``heading`` -- open-ended, ended by body drop-out
  (``warp_path.drop_out``) at ``standoff_of(body)`` from the body's centre.

The ship faces its path's tangent every tick (up kept as close as possible to
its current up), and its velocity is published along it so the camera smear
and speed readouts see the cruise.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

from engine.appc.math import TGPoint3
from engine.systems import frames
from engine.systems.warp_path import (
    HEADING_DASH_GUPS, Obstacle, drop_out, line_clear, plan_path,
    set_course_speed,
)

# R8: an AI flight's routed path is re-planned only when the target has moved
# more than max(this, REPLAN_FRACTION x remaining distance) since the plan.
REPLAN_MIN_GU = 1000.0
REPLAN_FRACTION = 0.05
# The most an AI warp's nose turns per second where it is not following a
# planned curve (straight at the live target, or pivoting onto a new plan):
# pi rad/s, 3 deg a tick at 60 Hz. A curve's own heading changes are its
# curvature x the step (the planner keeps them gentle).
AI_WARP_TURN_RATE_RAD_S = math.pi
# A target "velocity" above this (a frame change, a teleport) is not led.
_LEAD_MAX_GUPS = 1.0e6

_ZERO = (0.0, 0.0, 0.0)


def _default_standoff(obstacle: Obstacle) -> float:
    """One radius above the surface (ruling R1's default)."""
    return 2.0 * obstacle.radius_gu


@dataclass(eq=False)
class WarpFlight:
    # A ship, a (point, end_dir) destination in system coordinates, or None
    # for a heading flight.
    target: Any = None
    heading: tuple | None = None           # unit, system axes
    speed_policy: str = "ai"               # "ai" | "set_course" | "heading"
    exit_policy: str = "keep_pre_warp"     # | "rest" | "engaged_impulse"
    engaged_speed: float = 0.0
    # Heading drop-out standoff from a body's centre (R1). Task 5 supplies the
    # player's region-arrival standoff.
    standoff_of: Callable[[Obstacle], float] = _default_standoff
    drop_distance: float = 0.0             # AI: stop this far from the target
    # None | "arrived" | "body" | "stopped" | "aborted"
    ended_reason: str | None = None
    drop_point: tuple | None = None        # where it ended, system coordinates
    # Engine-private flight state.
    _obstacles: list | None = field(default=None, repr=False)
    _path: Any = field(default=None, repr=False)
    _s: float = field(default=0.0, repr=False)
    _plan_target: tuple | None = field(default=None, repr=False)
    _speed: float | None = field(default=None, repr=False)
    # The direction the ship last moved in (system axes), so a re-plan
    # continues it (plan_path's start_dir) instead of snapping the nose.
    _last_dir: tuple | None = field(default=None, repr=False)
    # AI ship target: None before the first tick, then whether it is flying
    # straight at the live target (True) or a planned curve (False).
    _straight: bool | None = field(default=None, repr=False)
    # The target's system position last tick (its velocity, for the lead).
    _target_prev: tuple | None = field(default=None, repr=False)
    # "ai" policy: seconds the ship waits, from acceptance, for its
    # articulated parts to reach their warp pose (``begin_ai_warp``), and how
    # long it has waited so far.
    _parts_hold: float = field(default=0.0, repr=False)
    _held: float = field(default=0.0, repr=False)


# ── frames ────────────────────────────────────────────────────────────────

def _anchor(ship) -> tuple:
    f = frames.frame_of_object(ship)
    return _ZERO if f is None else f.anchor_gu


def to_system(ship, local_xyz) -> tuple:
    """A point in the ship's set-local coordinates, in system coordinates.
    Identity (the same numbers) for an unmapped set or no set."""
    a = _anchor(ship)
    if a == _ZERO:
        return tuple(local_xyz)
    return (local_xyz[0] + a[0], local_xyz[1] + a[1], local_xyz[2] + a[2])


def to_local(ship, system_xyz) -> tuple:
    """Inverse of to_system."""
    a = _anchor(ship)
    if a == _ZERO:
        return tuple(system_xyz)
    return (system_xyz[0] - a[0], system_xyz[1] - a[1], system_xyz[2] - a[2])


def target_local(ship, target):
    """The target's position in the ship's set-local coordinates; its raw
    position when either is in no set; None when they are in different
    frames (they never interact)."""
    ship_set = frames.containing_set(ship)
    target_set = frames.containing_set(target)
    p = target.GetWorldLocation()
    if ship_set is None or target_set is None:
        return (p.x, p.y, p.z)
    off = frames.offset_between(ship_set, target_set)
    if off is None:
        return None
    if off == _ZERO:
        return (p.x, p.y, p.z)
    return (p.x + off[0], p.y + off[1], p.z + off[2])


def obstacles_for(ship) -> list:
    """The bodies a warp from this ship must clear, in system coordinates:
    the system map's bodies when its set is mapped, the set's own Planet/Sun
    objects (set-local == system for a one-set frame) otherwise, [] in no
    set."""
    pSet = frames.containing_set(ship)
    f = frames.frame_of(pSet)
    if f is None:
        return []
    if f.key[0] == "system":
        from engine.systems import resolve
        m = resolve.map_of(f.key[1])
        if m is None:
            return []
        return [Obstacle(b.name, tuple(float(c) for c in b.position_gu),
                         float(b.radius_gu)) for b in m.bodies]
    from engine.appc.planet import Planet
    out = []
    for obj in pSet.GetClassObjectList(Planet):   # Sun is a Planet
        p = obj.GetWorldLocation()
        out.append(Obstacle(obj.GetName(), (p.x, p.y, p.z),
                            float(obj.GetRadius())))
    return out


# ── geometry helpers ──────────────────────────────────────────────────────

def _chord_clear(p, q, obstacles, comfort=True, hold=False) -> bool:
    """True when the segment p->q keeps every body's keep-out: the planner's
    own test (``warp_path.line_clear`` -- same spheres, same tolerance), so a
    flight is straight exactly when the planner would draw a straight line."""
    return line_clear(p, q, obstacles, comfort, hold)


def _turn_toward(a, b, max_angle):
    """Unit direction ``b``, or -- when it is more than ``max_angle`` from
    ``a`` -- ``a`` turned ``max_angle`` toward it. ``a`` None: ``b``."""
    if a is None:
        return b
    dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
    if dot >= math.cos(max_angle):
        return b
    w = (b[0] - a[0] * dot, b[1] - a[1] * dot, b[2] - a[2] * dot)
    n = math.sqrt(w[0] * w[0] + w[1] * w[1] + w[2] * w[2])
    if n < 1e-12:                           # dead astern: turn about up
        w = (a[1], -a[0], 0.0)
        n = math.hypot(a[0], a[1])
        if n < 1e-12:
            w, n = (0.0, a[2], -a[1]), math.hypot(a[1], a[2])
    c, sn = math.cos(max_angle), math.sin(max_angle) / n
    h = (a[0] * c + w[0] * sn, a[1] * c + w[1] * sn, a[2] * c + w[2] * sn)
    k = math.sqrt(h[0] * h[0] + h[1] * h[1] + h[2] * h[2])
    return (h[0] / k, h[1] / k, h[2] / k)


def _face(ship, direction) -> None:
    """Point the nose along ``direction``, keeping up as close as possible to
    the ship's current up."""
    R = ship.GetWorldRotation()
    up = R.GetCol(2)
    fwd = TGPoint3(*direction)
    k = fwd.x * up.x + fwd.y * up.y + fwd.z * up.z
    if abs(k) > 0.999999:
        # Nose onto the old up: rebuild up from the old right (up = right x fwd).
        right = R.GetCol(0)
        up = TGPoint3(right.y * fwd.z - right.z * fwd.y,
                      right.z * fwd.x - right.x * fwd.z,
                      right.x * fwd.y - right.y * fwd.x)
    ship.AlignToVectors(fwd, up)


def _set_local(ship, system_xyz) -> None:
    ship.SetTranslateXYZ(*to_local(ship, system_xyz))


def _ai_speed(ship) -> float:
    """The fixed in-system warp speed, the same for every ship as in BC
    (ShipClass.IN_SYSTEM_WARP_SPEED_GUPS); ``ship`` is unused."""
    from engine.appc.ships import ShipClass
    return ShipClass.IN_SYSTEM_WARP_SPEED_GUPS


def _policy_speed(ship, flight) -> float:
    """The flight's cruise speed, by its speed policy (spec table)."""
    if flight._speed is None:
        if flight.speed_policy == "set_course":
            flight._speed = set_course_speed(flight._path.length_gu)
        elif flight.speed_policy == "heading":
            flight._speed = HEADING_DASH_GUPS
        else:
            flight._speed = _ai_speed(ship)
    return flight._speed


# ── the AI flight's warp state ────────────────────────────────────────────

def _parts_time(ship) -> float:
    """The parts' hold for an AI warp: the time the ship's articulated parts
    need to reach their warp pose plus one sim tick (they start moving on the
    tick after the state flips), as dash._parts_time. 0.0 -- no hold -- for a
    ship with no parts to move. Fail-open."""
    try:
        from engine.appc import articulation
        t = articulation.time_to_reach(ship, "warp")
    except Exception:  # noqa: BLE001 - never block a warp on a rig read
        return 0.0
    if t <= 0.0:
        return 0.0
    from engine.core.loop import TICK_DELTA
    return t + TICK_DELTA


def begin_ai_warp(ship, flight) -> None:
    """An "ai" flight was just accepted (InSystemWarp). With parts to move,
    enter WES_WARP_INITIATED and hold (``step``) until they settle; with
    none, WES_WARPING at once. The player's dash policies manage their own
    state in dash.py and never come here."""
    from engine.appc import warp_state
    from engine.appc.subsystems import WarpEngineSubsystem
    flight._parts_hold = _parts_time(ship)
    warp_state.set_state(ship, WarpEngineSubsystem.WES_WARP_INITIATED
                         if flight._parts_hold > 0.0
                         else WarpEngineSubsystem.WES_WARPING)


def end_ai_warp(ship, flight) -> None:
    """An "ai" flight ended, by arrival or any abort: back to
    WES_NOT_WARPING, so the parts return to cruise (the dash's drop-out does
    the same; nothing is left to glide out of)."""
    if getattr(flight, "speed_policy", None) != "ai":
        return
    from engine.appc import warp_state
    from engine.appc.subsystems import WarpEngineSubsystem
    warp_state.set_state(ship, WarpEngineSubsystem.WES_NOT_WARPING)


# ── ending ────────────────────────────────────────────────────────────────

def _finish(ship, flight, reason, system_xyz, direction) -> None:
    """End the flight at ``system_xyz`` travelling along ``direction`` and
    apply its exit policy."""
    if flight.exit_policy == "rest":
        speed = 0.0
        ship._current_speed = 0.0
    elif flight.exit_policy == "engaged_impulse":
        speed = float(flight.engaged_speed)
        ship._current_speed = speed
    else:                                   # keep_pre_warp
        speed = ship._current_speed
    ship.SetVelocity(TGPoint3(direction[0] * speed, direction[1] * speed,
                              direction[2] * speed))
    flight.drop_point = tuple(system_xyz)
    ship._end_in_system_warp(reason)
    if flight.speed_policy == "ai":
        # One warp per StopInSystemWarp cycle (Intercept's contract).
        ship._warp_consumed = True


# ── the tick ──────────────────────────────────────────────────────────────

def step(ship, dt: float) -> bool:
    """Advance one tick of the ship's flight (``_insystem_warp_transit``).

    False while an "ai" flight holds for its parts (``begin_ai_warp``): the
    flight does not move the ship that tick, and the caller flies its normal
    impulse orders instead -- the SDK's Intercept keeps turning it at the
    target and skips its own speed control while InSystemWarp returns 1, so
    it cruises on at the speed it last ordered. The tick that completes the
    hold enters WES_WARPING and flies. True otherwise."""
    flight = ship._insystem_warp_transit
    if flight._parts_hold > 0.0:
        if _abort_if_target_gone(ship, flight):
            return True
        flight._held += dt
        if flight._held < flight._parts_hold - 1e-9:
            return False
        flight._parts_hold = 0.0
        from engine.appc import warp_state
        from engine.appc.subsystems import WarpEngineSubsystem
        warp_state.set_state(ship, WarpEngineSubsystem.WES_WARPING)
    if flight.target is None:
        _step_heading(ship, flight, dt)
    elif isinstance(flight.target, tuple):
        _step_destination(ship, flight, dt)
    else:
        _step_ship_target(ship, flight, dt)
    return True


def _abort_if_target_gone(ship, flight) -> bool:
    """End a ship-target flight whose target is gone or has left the ship's
    frame (they never interact); True when it did."""
    target = flight.target
    if target is None or isinstance(target, tuple):
        return False
    if (hasattr(target, "GetWorldLocation")
            and target_local(ship, target) is not None):
        return False
    ship._end_in_system_warp("aborted")
    ship._warp_consumed = True
    return True


def _step_ship_target(ship, flight, dt) -> None:
    if _abort_if_target_gone(ship, flight):
        return
    target = flight.target
    t_local = target_local(ship, target)
    if flight._obstacles is None:
        flight._obstacles = obstacles_for(ship)
    drop = float(flight.drop_distance)
    p = ship.GetTranslate()
    p_local = (p.x, p.y, p.z)
    p_sys, t_sys = to_system(ship, p_local), to_system(ship, t_local)
    obstacles = flight._obstacles

    # Straight or curved, judged every tick against the LIVE drop point with
    # the planner's own keep-out test, with hysteresis so the two never
    # alternate: a curve hands over to the straight line once the line keeps
    # the comfort margin; the straight line holds while it keeps the hard
    # clearance. Both hold the ship's current gap (``hold``) once it moves.
    hold = flight._last_dir is not None
    remaining = math.dist(p_sys, t_sys)
    if remaining > drop:
        k = drop / remaining
        drop_sys = tuple(t - (t - q) * k for t, q in zip(t_sys, p_sys))
    else:
        drop_sys = p_sys
    comfort = flight._straight is not True
    flight._straight = _chord_clear(p_sys, drop_sys, obstacles, comfort, hold)
    v_t = _target_velocity(flight, t_sys, dt)
    if flight._straight:
        flight._path = None
        lead = _lead_point(p_sys, t_sys, v_t, _ai_speed(ship), drop)
        if lead is not t_sys and not _chord_clear(p_sys, lead, obstacles,
                                                  False, hold):
            v_t = _ZERO                     # leading would cut a body: pursue
        _straight_at_target(ship, flight, dt, p_local, t_local, drop, v_t)
        return

    if (flight._path is None or math.dist(t_sys, flight._plan_target)
            > max(REPLAN_MIN_GU, REPLAN_FRACTION * remaining)):
        # The flight's first plan picks its own heading (the ship faces it
        # at once, as the straight line does); every later plan -- R8
        # re-plans and a straight line turning back into a curve -- is
        # pinned to the direction the ship is flying, and holds its gap.
        flight._path = plan_path(p_sys, t_sys, obstacles,
                                 start_dir=flight._last_dir)
        flight._plan_target = t_sys
        flight._s = 0.0
    if flight._s == 0.0 and flight._last_dir is not None:
        # A plan the pin could not hold (the target swung behind): pivot on
        # the spot onto its first tangent at the turn rate, then fly it.
        first = flight._path.tangent_at(0.0)
        h = _turn_toward(flight._last_dir, first, AI_WARP_TURN_RATE_RAD_S * dt)
        if h is not first:
            _face(ship, h)
            flight._last_dir = h
            ship.SetVelocity(TGPoint3(0.0, 0.0, 0.0))
            return
    # A plan is never "arrived at": its end is where the target WAS. Spent
    # before the live drop point came into clear view, it is re-planned.
    _advance_along(ship, flight, dt, _ai_speed(ship),
                   flight._path.length_gu - drop, arrive=False)


def _target_velocity(flight, t_sys, dt) -> tuple:
    """The target's velocity from its last two positions (zero on the first
    tick, or across an implausible jump -- a frame change)."""
    prev, flight._target_prev = flight._target_prev, t_sys
    if prev is None or dt <= 0.0:
        return _ZERO
    v = tuple((a - b) / dt for a, b in zip(t_sys, prev))
    if math.sqrt(sum(c * c for c in v)) > _LEAD_MAX_GUPS:
        return _ZERO
    return v


def _lead_point(p, t, v, speed, drop):
    """Where to aim to meet a target at ``t`` moving at ``v``: its position
    at the first time tau >= 0 with |t + v tau - p| = drop + speed tau, or
    ``t`` itself when it is not moving or cannot be caught."""
    if v == _ZERO:
        return t
    w = tuple(a - b for a, b in zip(t, p))
    a = sum(c * c for c in v) - speed * speed
    b = 2.0 * (sum(x * y for x, y in zip(w, v)) - speed * drop)
    c = sum(x * x for x in w) - drop * drop
    if abs(a) < 1e-9:
        roots = [-c / b] if abs(b) > 1e-12 else []
    else:
        disc = b * b - 4.0 * a * c
        if disc < 0.0:
            return t
        r = math.sqrt(disc)
        roots = [(-b - r) / (2.0 * a), (-b + r) / (2.0 * a)]
    tau = min((x for x in roots if x >= 0.0), default=None)
    if tau is None:
        return t
    return tuple(a_ + v_ * tau for a_, v_ in zip(t, v))


def _straight_at_target(ship, flight, dt, p, t, drop, v_t=_ZERO) -> None:
    """The pre-flight integrator's arithmetic, kept in set-local coordinates:
    an unobstructed warp at a stationary target it already faces moves along
    the same chord at the same speed as before WarpFlight. A moving target is
    led (``v_t``); the nose turns at most ``AI_WARP_TURN_RATE_RAD_S``; the
    flight ends on the drop edge of the LIVE target."""
    dx, dy, dz = t[0] - p[0], t[1] - p[1], t[2] - p[2]
    d = (dx * dx + dy * dy + dz * dz) ** 0.5
    if d <= max(drop, 1e-9):
        # Already on the drop edge: end without touching the velocity, as
        # the old integrator did.
        flight.drop_point = to_system(ship, p)
        ship._end_in_system_warp("arrived")
        ship._warp_consumed = True
        return
    u = (dx / d, dy / d, dz / d)
    warp_speed = _ai_speed(ship)
    # Aim where the target will be met (a moving target is led, so a
    # crossing or closing one is intercepted, not chased round), turning at
    # the turn rate. A stationary target the nose is already on -- the old
    # integrator's case -- gives ``u`` itself, bit for bit.
    aim = u
    lead = _lead_point(p, t, v_t, warp_speed, drop)
    if lead is not t:
        la = tuple(a - b for a, b in zip(lead, p))
        n = math.sqrt(sum(c * c for c in la))
        if n > 1e-9:
            aim = (la[0] / n, la[1] / n, la[2] / n)
    h = _turn_toward(flight._last_dir, aim, AI_WARP_TURN_RATE_RAD_S * dt)
    _face(ship, h)
    flight._last_dir = h
    remaining = d - drop
    step_gu = warp_speed * dt
    if step_gu >= remaining:
        # Land on the drop edge of the LIVE target.
        end = (t[0] - u[0] * drop, t[1] - u[1] * drop, t[2] - u[2] * drop)
        ship.SetTranslateXYZ(*end)
        _finish(ship, flight, "arrived", to_system(ship, end), h)
    else:
        ship.SetTranslateXYZ(p[0] + h[0] * step_gu, p[1] + h[1] * step_gu,
                             p[2] + h[2] * step_gu)
        ship.SetVelocity(TGPoint3(h[0] * warp_speed, h[1] * warp_speed,
                                  h[2] * warp_speed))


def _advance_along(ship, flight, dt, speed, s_end, arrive=True) -> None:
    """Move ``speed * dt`` along the flight's path, ending at arc length
    ``s_end`` (the path end, or the AI drop edge short of it). With
    ``arrive`` False, reaching ``s_end`` does not end the flight: the path
    is dropped for a re-plan."""
    path = flight._path
    s_end = max(s_end, flight._s)
    s = flight._s + speed * dt
    if s >= s_end:
        end = path.point_at(s_end)
        tangent = path.tangent_at(s_end)
        _set_local(ship, end)
        _face(ship, tangent)
        flight._last_dir = tangent
        if arrive:
            _finish(ship, flight, "arrived", end, tangent)
        else:
            flight._path = None
            ship.SetVelocity(TGPoint3(tangent[0] * speed, tangent[1] * speed,
                                      tangent[2] * speed))
        return
    flight._s = s
    tangent = path.tangent_at(s)
    _set_local(ship, path.point_at(s))
    _face(ship, tangent)
    flight._last_dir = tangent
    ship.SetVelocity(TGPoint3(tangent[0] * speed, tangent[1] * speed,
                              tangent[2] * speed))


def _step_destination(ship, flight, dt) -> None:
    if flight._path is None:
        point, end_dir = flight.target
        p = ship.GetTranslate()
        flight._path = plan_path(to_system(ship, (p.x, p.y, p.z)), point,
                                 obstacles_for(ship), end_dir=end_dir)
        flight._s = 0.0
    _advance_along(ship, flight, dt, _policy_speed(ship, flight),
                   flight._path.length_gu)


def _step_heading(ship, flight, dt) -> None:
    if flight._obstacles is None:
        flight._obstacles = obstacles_for(ship)
    h = flight.heading
    speed = _policy_speed(ship, flight)
    p = ship.GetTranslate()
    p_sys = to_system(ship, (p.x, p.y, p.z))
    _face(ship, h)
    step_gu = speed * dt
    dp = drop_out(p_sys, h, speed, flight._obstacles, flight.standoff_of)
    if dp is not None and math.dist(p_sys, dp) <= step_gu:
        _set_local(ship, dp)
        _finish(ship, flight, "body", dp, h)
        return
    _set_local(ship, (p_sys[0] + h[0] * step_gu, p_sys[1] + h[1] * step_gu,
                      p_sys[2] + h[2] * step_gu))
    ship.SetVelocity(TGPoint3(h[0] * speed, h[1] * speed, h[2] * speed))
