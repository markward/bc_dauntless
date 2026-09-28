"""One in-system warp flight for every ship (in-system-warp spec, section 1).

``ShipClass.InSystemWarp`` (the SDK entry point, AI/PlainAI/Intercept.py:214)
and the player's dashes all record a ``WarpFlight`` on the ship's
``_insystem_warp_transit``; ``ship_motion`` hands every tick of it to
``step``. The flight owns the motion only -- warp-engine state, VFX and the
region hand-off belong to its callers.

Coordinates. Paths are planned in SYSTEM coordinates
(``engine.systems.warp_path`` is pure math on system-space tuples). The ship
itself stays set-local: ``to_system`` / ``to_local`` convert through its
containing set's frame anchor (``engine.systems.frames``), which is zero for
an unmapped set and for a ship in no set -- there the numbers pass through
untouched, so a warp inside one unmapped set runs exactly the old arithmetic.

Targets:

* a ship (AI Intercept) -- tracked live. While the straight line to it keeps
  every body's comfort keep-out the flight flies that line exactly as the old
  integrator did (re-aimed every tick, landing on the drop edge); otherwise
  it follows ``plan_path``'s smooth curve, and keeps following it (no
  per-tick return to the straight line) until the target has moved more
  than max(1,000 GU, 5 % of the remaining distance) since the last plan
  (ruling R8). Every plan after the first continues the heading already
  flown (``start_dir``), so a re-plan never snaps the nose. Never drops out
  (ruling R2);
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
    HEADING_DASH_GUPS, Obstacle, drop_out, keep_out_gu, plan_path,
    set_course_speed,
)

# R8: an AI flight's routed path is re-planned only when the target has moved
# more than max(this, REPLAN_FRACTION x remaining distance) since the plan.
REPLAN_MIN_GU = 1000.0
REPLAN_FRACTION = 0.05

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

def _chord_clear(p, q, obstacles) -> bool:
    """True when the segment p->q keeps every body's COMFORT keep-out -- the
    test plan_path uses to keep a trip straight (``keep_out_gu``: radius +
    comfort margin, halved toward an endpoint inside it (R5), none for a
    body holding an endpoint). Agreeing with the planner means a flight is
    straight exactly when the planner would have drawn a straight line."""
    ux, uy, uz = q[0] - p[0], q[1] - p[1], q[2] - p[2]
    l2 = ux * ux + uy * uy + uz * uz
    for o in obstacles:
        c, r = o.center, o.radius_gu
        near = min(math.dist(p, c), math.dist(q, c))
        need = keep_out_gu(r, near, comfort=True)
        if need is None:
            continue
        wx, wy, wz = c[0] - p[0], c[1] - p[1], c[2] - p[2]
        t = 0.0 if l2 <= 0.0 else min(max((wx * ux + wy * uy + wz * uz) / l2, 0.0), 1.0)
        closest = (p[0] + t * ux, p[1] + t * uy, p[2] + t * uz)
        if math.dist(closest, c) < need:
            return False
    return True


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
    """100 x the AUTHORED impulse max: the warp engines cruise, so a shot-out
    impulse pod must not slow the transit (the authored figure is a ship-size
    proxy). Unchanged from the pre-flight integrator."""
    from engine.appc.ships import ShipClass
    getter = getattr(ship, "GetImpulseEngineSubsystem", None)
    ies = getter() if getter is not None else None
    base = ies.GetAuthoredMaxSpeed() if ies is not None else 0.0
    if base <= 0.0:
        base = ShipClass.IN_SYSTEM_WARP_FALLBACK_BASE
    return ShipClass.IN_SYSTEM_WARP_SPEED_FACTOR * base


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

def step(ship, dt: float) -> None:
    """Advance one tick of the ship's flight (``_insystem_warp_transit``)."""
    flight = ship._insystem_warp_transit
    if flight.target is None:
        _step_heading(ship, flight, dt)
    elif isinstance(flight.target, tuple):
        _step_destination(ship, flight, dt)
    else:
        _step_ship_target(ship, flight, dt)


def _step_ship_target(ship, flight, dt) -> None:
    target = flight.target
    if not hasattr(target, "GetWorldLocation"):
        ship._end_in_system_warp("aborted")
        ship._warp_consumed = True
        return
    t_local = target_local(ship, target)
    if t_local is None:                     # the target left this frame
        ship._end_in_system_warp("aborted")
        ship._warp_consumed = True
        return
    if flight._obstacles is None:
        flight._obstacles = obstacles_for(ship)
    drop = float(flight.drop_distance)
    p = ship.GetTranslate()
    p_local = (p.x, p.y, p.z)
    p_sys, t_sys = to_system(ship, p_local), to_system(ship, t_local)

    # Straight at the live target only while no path is being flown: once
    # on a curve, the ship keeps it until the target has moved past the R8
    # threshold. (A per-tick chord test would drop it onto the straight chord
    # the moment the bow swung wide enough to see past the body -- a heading
    # jump, then back onto a curve as the target moved: flip-flop.)
    if flight._path is None and _chord_clear(p_sys, t_sys, flight._obstacles):
        _straight_at_target(ship, flight, dt, p_local, t_local, drop)
        return

    remaining = math.dist(p_sys, t_sys)
    if (flight._path is None or math.dist(t_sys, flight._plan_target)
            > max(REPLAN_MIN_GU, REPLAN_FRACTION * remaining)):
        # The first plan chooses the heading; every later one continues the
        # heading already flown, so the nose never jumps at a re-plan.
        flight._path = plan_path(p_sys, t_sys, flight._obstacles,
                                 start_dir=flight._last_dir)
        flight._plan_target = t_sys
        flight._s = 0.0
    speed = _ai_speed(ship)
    _advance_along(ship, flight, dt, speed, flight._path.length_gu - drop)


def _straight_at_target(ship, flight, dt, p, t, drop) -> None:
    """The pre-flight integrator's arithmetic, kept in set-local coordinates:
    an unobstructed ship-target warp moves along the same chord at the same
    speed as before WarpFlight -- but not byte-for-byte, since the nose now
    faces the chord every tick (``_face``)."""
    dx, dy, dz = t[0] - p[0], t[1] - p[1], t[2] - p[2]
    d = (dx * dx + dy * dy + dz * dz) ** 0.5
    if d <= max(drop, 1e-9):
        # Already on the drop edge: end without touching the velocity, as
        # the old integrator did.
        flight.drop_point = to_system(ship, p)
        ship._end_in_system_warp("arrived")
        ship._warp_consumed = True
        return
    ux, uy, uz = dx / d, dy / d, dz / d
    _face(ship, (ux, uy, uz))
    flight._last_dir = (ux, uy, uz)
    warp_speed = _ai_speed(ship)
    remaining = d - drop
    step_gu = warp_speed * dt
    if step_gu >= remaining:
        end = (t[0] - ux * drop, t[1] - uy * drop, t[2] - uz * drop)
        ship.SetTranslateXYZ(*end)
        _finish(ship, flight, "arrived", to_system(ship, end), (ux, uy, uz))
    else:
        ship.SetTranslateXYZ(p[0] + ux * step_gu, p[1] + uy * step_gu,
                             p[2] + uz * step_gu)
        ship.SetVelocity(TGPoint3(ux * warp_speed, uy * warp_speed,
                                  uz * warp_speed))


def _advance_along(ship, flight, dt, speed, s_end) -> None:
    """Move ``speed * dt`` along the flight's path, ending at arc length
    ``s_end`` (the path end, or the AI drop edge short of it)."""
    path = flight._path
    s_end = max(s_end, flight._s)
    s = flight._s + speed * dt
    if s >= s_end:
        end = path.point_at(s_end)
        tangent = path.tangent_at(s_end)
        _set_local(ship, end)
        _face(ship, tangent)
        _finish(ship, flight, "arrived", end, tangent)
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
