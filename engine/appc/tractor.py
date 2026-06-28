"""Per-frame tractor-beam EFFECT — moves the tractored target each tick.

A firing tractor emitter (one sustained grab beam per system; see
TractorBeamSystem on _HeldFireWeaponSystem) applies its mode's physics to the
locked target.  Modes (sdk/.../App.py:6774-6779):

    HOLD  — pin the target at the world-point it occupied when grabbed and
            damp its velocity to rest (stops a moving ship, holds it there).
    TOW   — lock the target at the offset (in the SOURCE body frame) it held
            when grabbed, so it follows the tower (per AI/PlainAI/Warp.py
            SetupTowing).
    PULL  — accelerate the target toward the source.
    PUSH  — accelerate the target away from the source.
    DOCK_STAGE_1 / DOCK_STAGE_2 — gentle guided PULL toward a dock standoff
            point just off the source (stub: no full staged docking handshake).

Force model — mass-aware + reciprocal (signed off in the design):

  * Each ship has a mass-scaled engagement *speed*:
        speed(m) = clamp(REF_SPEED · REF_MASS / m, 0, MAX_SPEED)
    so a shuttle (m≈10) is flung, a Galaxy (m≈120) is sluggish, and a starbase
    (m≈1e6) is effectively immovable — for free.  Non-ship bodies (planets,
    suns) are immovable (speed 0).  Mirrors collisions.py's inverse-mass split.
  * The effect is applied as a DIRECT position displacement each frame
    (SetTranslateXYZ), recomputed from live geometry — NOT a write to
    `_velocity` (the motion integrator overwrites that every frame for AI ships
    and skips setpoint-less ships entirely; see ship_motion._step_ship_motion).
    Because the force is recomputed each frame it self-corrects and needs no
    persistent decaying overlay (unlike collisions).
  * Reciprocity (Newton's 3rd law): PULL/PUSH/TOW/DOCK also move the SOURCE,
    opposite-direction, at speed(m_source) — momentum-consistent because
    speed(m)∝1/m.  HOLD anchors the target only (no source reaction).

Called once per tick from host_loop._advance_combat, after motion has set base
positions and before collisions.  No-ops for ships without a firing tractor, so
production combat for non-tractor ships stays byte-identical.
"""
from engine.appc.math import TGPoint3

# -- Tuning constants (tuned by feel; game units, 1 GU = 175 m) ---------------
TRACTOR_REFERENCE_MASS      = 100.0   # mid-hull reference (Galaxy ≈ 120)
TRACTOR_REFERENCE_SPEED_GUPS = 5.0    # engagement speed for a reference-mass hull
TRACTOR_MAX_SPEED_GUPS      = 20.0    # cap so a light hull isn't flung absurdly
TRACTOR_FALLBACK_MASS       = 1.0e4   # ship reporting mass<=0 → heavy (≈immovable);
                                      # matches collisions.COLLISION_FALLBACK_MASS
TRACTOR_TOW_DRAG_FRACTION   = 0.25    # how much a towed hull drags the tower
TRACTOR_DOCK_GENTLE_FRACTION = 0.4    # docking approach is gentler than a PULL
TRACTOR_STANDOFF_MARGIN_GU  = 3.0     # gap held beyond the combined hull radii so
                                      # PULL/DOCK settle the target NEAR the
                                      # emitting ship, never inside its hull

_EPS = 1e-6


def _standoff_distance(source, target) -> float:
    """Separation PULL/DOCK settle at: combined bounding-sphere radii + margin,
    so the target ends up just off the hull rather than clipping into it."""
    rs = source.GetRadius() if hasattr(source, "GetRadius") else 0.0
    rt = target.GetRadius() if hasattr(target, "GetRadius") else 0.0
    rs = rs if isinstance(rs, (int, float)) else 0.0
    rt = rt if isinstance(rt, (int, float)) else 0.0
    return rs + rt + TRACTOR_STANDOFF_MARGIN_GU


def _speed_for(obj) -> float:
    """Mass-scaled engagement speed (GU/s) for `obj`.  0 for immovable bodies
    (anything that isn't a ShipClass — planets, suns, stations-as-props)."""
    from engine.appc.ships import ShipClass
    if not isinstance(obj, ShipClass):
        return 0.0
    m = obj.GetMass() if hasattr(obj, "GetMass") else 0.0
    if m <= 0.0:
        m = TRACTOR_FALLBACK_MASS
    s = TRACTOR_REFERENCE_SPEED_GUPS * TRACTOR_REFERENCE_MASS / m
    return s if s < TRACTOR_MAX_SPEED_GUPS else TRACTOR_MAX_SPEED_GUPS


def _displace(obj, dx: float, dy: float, dz: float) -> None:
    """Add a world-space displacement to an object's position."""
    p = obj.GetWorldLocation()
    obj.SetTranslateXYZ(p.x + dx, p.y + dy, p.z + dz)


def _spring_toward(obj, dest, max_speed: float, dt: float) -> None:
    """Move `obj` toward world-point `dest`, capped at `max_speed` GU/s (snaps
    when within one step).  No-op for immovable objects (max_speed 0)."""
    if max_speed <= 0.0:
        return
    p = obj.GetWorldLocation()
    ex, ey, ez = dest.x - p.x, dest.y - p.y, dest.z - p.z
    elen = (ex*ex + ey*ey + ez*ez) ** 0.5
    if elen < _EPS:
        return
    step = max_speed * dt
    if elen <= step:
        obj.SetTranslateXYZ(dest.x, dest.y, dest.z)
    else:
        f = step / elen
        obj.SetTranslateXYZ(p.x + ex*f, p.y + ey*f, p.z + ez*f)


def _zero_velocity(obj) -> None:
    """Best-effort velocity damp (HOLD).  Setpoint-driven ships have this
    re-derived by the motion integrator next frame; for drifting props it
    actually stops them."""
    if hasattr(obj, "SetVelocity"):
        obj.SetVelocity(TGPoint3(0.0, 0.0, 0.0))


def advance_tractors(ships, dt: float) -> None:
    """Apply every firing tractor's mode physics to its target for one tick."""
    if dt <= 0.0:
        return
    for ship in ships:
        getter = getattr(ship, "GetTractorBeamSystem", None)
        sys_ = getter() if getter is not None else None
        if sys_ is None or not sys_.IsFiring():
            continue
        mode = sys_.GetMode()
        for i in range(sys_.GetNumWeapons()):
            emitter = sys_.GetWeapon(i)
            if emitter is None or not emitter.IsFiring():
                continue
            target = getattr(emitter, "_target", None)
            if target is None:
                continue
            if hasattr(target, "IsDead") and target.IsDead():
                continue
            if not hasattr(target, "GetWorldLocation") or not hasattr(target, "SetTranslateXYZ"):
                continue
            _apply_mode(ship, sys_, target, mode, dt)


def _apply_mode(source, sys_, target, mode, dt: float) -> None:
    from engine.appc.weapon_subsystems import TractorBeamSystem as TBS

    sp = source.GetWorldLocation()
    tp = target.GetWorldLocation()
    dx, dy, dz = tp.x - sp.x, tp.y - sp.y, tp.z - sp.z
    L = (dx*dx + dy*dy + dz*dz) ** 0.5
    if L < _EPS:
        return  # coincident — no well-defined beam direction this frame
    ux, uy, uz = dx / L, dy / L, dz / L   # unit source → target
    s_t = _speed_for(target)
    s_s = _speed_for(source)

    if mode == TBS.TBS_PULL:
        # Pull the target to a STANDOFF off the source (combined hull radii +
        # margin), not all the way to its centre — so it settles near the hull
        # without being dragged inside.  Springs (mass-capped) toward the
        # standoff point: closes when far, holds at standoff, nudges back out if
        # too close.  Reciprocal: the source is drawn to the same standoff.
        standoff = _standoff_distance(source, target)
        desired_t = TGPoint3(sp.x + ux * standoff,
                             sp.y + uy * standoff,
                             sp.z + uz * standoff)
        _spring_toward(target, desired_t, s_t, dt)
        desired_s = TGPoint3(tp.x - ux * standoff,
                             tp.y - uy * standoff,
                             tp.z - uz * standoff)
        _spring_toward(source, desired_s, s_s, dt)
        return

    if mode == TBS.TBS_PUSH:
        # Target away from source; source recoils (reciprocal).
        _displace(target,  ux * s_t * dt,  uy * s_t * dt,  uz * s_t * dt)
        _displace(source, -ux * s_s * dt, -uy * s_s * dt, -uz * s_s * dt)
        return

    if mode == TBS.TBS_HOLD:
        # Pin the target at the world-point it occupied when grabbed; damp its
        # velocity.  Anchor-only — the source is unaffected.
        state = sys_._engage_state
        if not isinstance(state, dict) or state.get("hold_point") is None:
            sys_._engage_state = {"hold_point": TGPoint3(tp.x, tp.y, tp.z)}
            state = sys_._engage_state
        _spring_toward(target, state["hold_point"], s_t, dt)
        _zero_velocity(target)
        return

    if mode == TBS.TBS_TOW:
        # Lock the target at the offset (in the SOURCE body frame) it held when
        # grabbed, so it follows the tower.  Per AI/PlainAI/Warp.py SetupTowing.
        state = sys_._engage_state
        if not isinstance(state, dict) or state.get("tow_offset") is None:
            offset = TGPoint3(dx, dy, dz)              # world target − source
            R = source.GetWorldRotation()
            offset.MultMatrixLeft(R.Transpose())       # → source body frame
            sys_._engage_state = {"tow_offset": offset}
            state = sys_._engage_state
        desired = TGPoint3(state["tow_offset"].x,
                           state["tow_offset"].y,
                           state["tow_offset"].z)
        desired.MultMatrixLeft(source.GetWorldRotation())   # → world (rotated)
        desired = TGPoint3(sp.x + desired.x, sp.y + desired.y, sp.z + desired.z)
        _spring_toward(target, desired, s_t, dt)
        # Reciprocal drag: a heavy tow load tugs the tower toward it.
        drag = s_s * TRACTOR_TOW_DRAG_FRACTION
        _displace(source, ux * drag * dt, uy * drag * dt, uz * drag * dt)
        return

    if mode in (TBS.TBS_DOCK_STAGE_1, TBS.TBS_DOCK_STAGE_2):
        # Stub: gentle guided PULL toward a dock standoff just off the source
        # hull along the beam (no full staged docking handshake).
        standoff = _standoff_distance(source, target)
        dock = TGPoint3(sp.x + ux * standoff,
                        sp.y + uy * standoff,
                        sp.z + uz * standoff)
        _spring_toward(target, dock, s_t * TRACTOR_DOCK_GENTLE_FRACTION, dt)
        return
