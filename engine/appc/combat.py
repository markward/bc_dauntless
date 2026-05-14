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


def pick_target_subsystem(ship, hit_point):
    """Return the subsystem whose hardpoint position is closest to
    hit_point AND within ~2× its radius.  Falls back to ship.GetHull().
    """
    best = None
    best_dist_sq = float("inf")
    n = ship.GetNumChildSubsystems() if hasattr(ship, "GetNumChildSubsystems") else 0
    for i in range(n):
        sub = ship.GetChildSubsystem(i)
        if sub is None or not hasattr(sub, "GetPosition"):
            continue
        pos = sub.GetPosition()
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
