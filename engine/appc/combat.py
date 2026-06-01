"""Combat collision + damage routing.

Called by host_loop._advance_combat after engine.appc.projectiles.
update_all reports a torpedo hit.  Routes damage shields-face → picked
subsystem → hull bleed, then broadcasts WeaponHitEvent so mission
handlers (FriendlyFireHandler etc.) see the hit.
"""
from engine.appc.math import TGPoint3


def sphere_hit(point, center, radius: float) -> bool:
    """Point-in-sphere test using squared distance (no sqrt)."""
    dx = point.x - center.x
    dy = point.y - center.y
    dz = point.z - center.z
    r = float(radius)
    return (dx * dx + dy * dy + dz * dz) <= r * r


def ray_sphere_entry(origin, direction, max_dist: float,
                     center, radius: float):
    """Return the entry point of the ray (origin, unit `direction`) into
    the sphere (`center`, `radius`), or `None` if the ray's segment of
    length `max_dist` misses the sphere.

    If `origin` is already inside the sphere, returns `origin` (the
    "entry" degenerates to the start of the ray).
    """
    if radius <= 0.0:
        return None
    ox = origin.x - center.x
    oy = origin.y - center.y
    oz = origin.z - center.z
    b = ox * direction.x + oy * direction.y + oz * direction.z
    c = ox * ox + oy * oy + oz * oz - radius * radius
    if c <= 0.0:
        return origin
    if b >= 0.0:
        return None
    disc = b * b - c
    if disc < 0.0:
        return None
    t_enter = -b - disc ** 0.5
    if t_enter < 0.0 or t_enter > max_dist:
        return None
    return TGPoint3(
        origin.x + direction.x * t_enter,
        origin.y + direction.y * t_enter,
        origin.z + direction.z * t_enter,
    )


def _resolve_hit_point(host, ship_instances, ship,
                       ray_origin, ray_direction,
                       max_dist: float, fallback_point):
    """Three-tier hit-point fallback:

    1. If `host` exposes `ray_trace_mesh` AND `ship` has a renderer
       `InstanceId` in `ship_instances`, run the mesh trace; on hit,
       return the returned surface point.
    2. Else, if both `host` and `iid` were present (so the mesh trace
       ran and missed, or the binding wasn't available), fall back to
       the bounding-sphere entry point when the ray segment intersects
       it.
    3. Otherwise — no host, no iid, or the sphere also missed — return
       `fallback_point` (the caller's pre-project legacy point:
       `torpedo._position` for projectiles, `target_pos` for phasers).
       Preserves headless and broken-binding behaviour.
    """
    if host is None or ray_direction is None:
        return fallback_point
    iid = ship_instances.get(ship) if ship_instances is not None else None
    if iid is None:
        return fallback_point
    if hasattr(host, "ray_trace_mesh"):
        try:
            result = host.ray_trace_mesh(
                iid,
                (ray_origin.x, ray_origin.y, ray_origin.z),
                (ray_direction.x, ray_direction.y, ray_direction.z),
                max_dist,
            )
        except Exception:
            # Native trace errors must not kill a combat tick; degrade to sphere entry.
            result = None
        if result is not None:
            (px, py, pz), _normal, _t = result
            return TGPoint3(px, py, pz)
    center = ship.GetWorldLocation()
    radius = ship.GetRadius() if hasattr(ship, "GetRadius") else 0.0
    entry = ray_sphere_entry(ray_origin, ray_direction, max_dist,
                             center, radius)
    if entry is not None:
        return entry
    return fallback_point


def pick_target_subsystem(ship, hit_point):
    """Return the subsystem whose hardpoint position is closest to
    hit_point AND within ~2× its radius.  Falls back to ship.GetHull().
    """
    best = None
    best_dist_sq = float("inf")
    n = ship.GetNumChildSubsystems() if hasattr(ship, "GetNumChildSubsystems") else 0
    for i in range(n):
        sub = ship.GetChildSubsystem(i)
        if sub is None:
            continue
        # Prefer world location (production path: subsystem._parent_ship is
        # set, GetWorldLocation returns ship_world + subsystem_local).  Fall
        # back to GetPosition when the test stub doesn't have it (some fake
        # subsystem classes in unit tests expose only GetPosition).
        pos = None
        if hasattr(sub, "GetWorldLocation"):
            try:
                pos = sub.GetWorldLocation()
            except Exception:
                pos = None
        if pos is None and hasattr(sub, "GetPosition"):
            try:
                pos = sub.GetPosition()
            except Exception:
                pos = None
        if pos is None:
            continue
        r = sub.GetRadius() if hasattr(sub, "GetRadius") else 0.0
        dx = hit_point.x - pos.x
        dy = hit_point.y - pos.y
        dz = hit_point.z - pos.z
        d_sq = dx * dx + dy * dy + dz * dz
        if d_sq > (2.0 * r) ** 2:
            continue
        if d_sq < best_dist_sq:
            best = sub
            best_dist_sq = d_sq
    if best is not None:
        return best
    return ship.GetHull() if hasattr(ship, "GetHull") else None


def _shield_face_from_hit_point(ship, hit_point) -> int:
    """Map a world hit-point to a shield-face index (0-5 per
    ShieldProperty.NUM_SHIELDS).  Front/Rear/Top/Bottom/Left/Right by
    dominant axis of (hit_point - ship_pos) in world frame.

    Proper transform through ship.GetWorldRotation() is a future
    polish item — for PR 2b the world-axis approximation is fine
    while ships in test setups are placed without rotation.
    """
    ship_pos = ship.GetWorldLocation()
    dx = hit_point.x - ship_pos.x
    dy = hit_point.y - ship_pos.y
    dz = hit_point.z - ship_pos.z
    abs_x, abs_y, abs_z = abs(dx), abs(dy), abs(dz)
    if abs_y >= abs_x and abs_y >= abs_z:
        return 0 if dy >= 0 else 1
    if abs_z >= abs_x:
        return 2 if dz >= 0 else 3
    return 4 if dx <= 0 else 5


def apply_hit(ship, damage: float, hit_point, source, subsystem=None) -> None:
    """Route `damage` to `ship`: shields face first → picked subsystem
    → hull bleed.  Broadcast WeaponHitEvent at the end so per-ship and
    broadcast handlers (MissionLib.FriendlyFireHandler) react.
    """
    from engine.appc.events import WeaponHitEvent
    import App

    if subsystem is None:
        subsystem = pick_target_subsystem(ship, hit_point)

    remaining = float(damage)

    # 1. Shields take it first.
    shields = ship.GetShields() if hasattr(ship, "GetShields") else None
    if shields is not None and hasattr(shields, "ApplyDamage"):
        face = _shield_face_from_hit_point(ship, hit_point)
        remaining = shields.ApplyDamage(face, remaining)

    # 2. Bleed remainder to picked subsystem (skip if subsystem is the hull —
    #    the hull-bleed branch below handles that).
    hull = ship.GetHull() if hasattr(ship, "GetHull") else None
    if remaining > 0.0 and subsystem is not None and subsystem is not hull:
        if hasattr(ship, "DamageSystem"):
            current = subsystem.GetCondition() if hasattr(subsystem, "GetCondition") else remaining
            absorb = min(remaining, current)
            ship.DamageSystem(subsystem, absorb)
            remaining -= absorb

    # 3. Bleed final remainder to hull.
    if remaining > 0.0 and hull is not None and hasattr(ship, "DamageSystem"):
        ship.DamageSystem(hull, remaining)

    # 4. Broadcast WeaponHitEvent.  Setting destination = ship so per-ship
    #    instance handlers fire alongside broadcast handlers.
    evt = WeaponHitEvent()
    evt.SetSource(source)
    evt.SetTarget(ship)
    evt.SetDamage(damage)
    evt.SetHitPoint(hit_point)
    evt.SetSubsystem(subsystem)
    if isinstance(ship, App.TGEventHandlerObject):
        evt.SetDestination(ship)
    App.g_kEventManager.AddEvent(evt)
