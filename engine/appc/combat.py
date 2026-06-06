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


PHASER_DEFAULT_DAMAGE_RADIUS = 0.15
"""Fallback splash radius (game units) used only when neither hardpoint nor
payload defines a SetDamageRadiusFactor. Phaser hardpoints in stock SDK
always write 0.15 explicitly, so this default is reached only by
hand-authored weapons that forget to declare a radius.
"""


def weapon_splash_radius(hardpoint_weapon, payload_template) -> float:
    """Resolve R_hit per spec §3.2.

    hardpoint_weapon: WeaponProperty on the firing ship's hardpoint, or None.
    payload_template: projectile-type template (e.g. PhotonTorpedo), or None
                      for phasers / non-projectile weapons.

    Returns the splash radius in game units. Hardpoint DRF overrides payload
    DRF when both are set and non-zero; falls back to the phaser default
    (0.15 GU) when neither is available.
    """
    if hardpoint_weapon is not None and hasattr(hardpoint_weapon, "GetDamageRadiusFactor"):
        drf = hardpoint_weapon.GetDamageRadiusFactor()
        if drf > 0.0:
            return float(drf)
    if payload_template is not None and hasattr(payload_template, "GetDamageRadiusFactor"):
        drf = payload_template.GetDamageRadiusFactor()
        if drf > 0.0:
            return float(drf)
    return PHASER_DEFAULT_DAMAGE_RADIUS


def _resolve_hit_point(host, ship_instances, ship,
                       ray_origin, ray_direction,
                       max_dist: float, fallback_point):
    """Three-tier hit-point fallback. Returns ``(point, normal)``.

    ``normal`` is a unit ``TGPoint3`` only when the mesh trace
    succeeded; sphere-entry and fallback paths return ``normal=None``.

    Tiers:
    1. Mesh trace via ``host.ray_trace_mesh`` (requires both host and
       a renderer InstanceId for this ship). Returns the surface point
       and the surface normal.
    2. Bounding-sphere entry. No normal available.
    3. ``fallback_point`` passed by the caller (torpedo position or
       phaser target_pos). No normal.
    """
    if host is None or ray_direction is None:
        return fallback_point, None
    iid = ship_instances.get(ship) if ship_instances is not None else None
    if iid is None:
        return fallback_point, None
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
            (px, py, pz), (nx, ny, nz), _t = result
            return TGPoint3(px, py, pz), TGPoint3(nx, ny, nz)
    center = ship.GetWorldLocation()
    radius = ship.GetRadius() if hasattr(ship, "GetRadius") else 0.0
    entry = ray_sphere_entry(ray_origin, ray_direction, max_dist,
                             center, radius)
    if entry is not None:
        return entry, None
    return fallback_point, None


def _body_frame_delta(ship, hit_point):
    """Convert ``hit_point - ship.GetWorldLocation()`` into the ship's
    body frame using the column-vector convention from CLAUDE.md.

    ``R = ship.GetWorldRotation()`` stores body axes as columns. To
    express ``delta_world`` in body coordinates we project onto each
    column: ``dx_body = dot(delta_world, R.GetCol(i))``. Equivalent to
    ``R.transpose() * delta_world`` for orthonormal R.

    Returns ``(dx, dy, dz)`` floats. If ``ship`` has no
    ``GetWorldRotation`` method (legacy test fakes), treats R as
    identity so body == world.
    """
    ship_pos = ship.GetWorldLocation()
    dx_w = hit_point.x - ship_pos.x
    dy_w = hit_point.y - ship_pos.y
    dz_w = hit_point.z - ship_pos.z
    if not hasattr(ship, "GetWorldRotation"):
        return (dx_w, dy_w, dz_w)
    R = ship.GetWorldRotation()
    cx = R.GetCol(0)
    cy = R.GetCol(1)
    cz = R.GetCol(2)
    return (
        dx_w * cx.x + dy_w * cx.y + dz_w * cx.z,
        dx_w * cy.x + dy_w * cy.y + dz_w * cy.z,
        dx_w * cz.x + dy_w * cz.y + dz_w * cz.z,
    )


def _subsystem_state_flags(sub) -> tuple:
    """Snapshot (IsDamaged, IsDisabled, IsDestroyed) as a 3-tuple of bools,
    diffable against a later snapshot via :func:`_diff_state`.

    Missing methods default to False so legacy test fixtures
    (pre-dating the full ShipSubsystem interface) keep working.
    """
    return (
        bool(sub.IsDamaged())   if hasattr(sub, "IsDamaged")   else False,
        bool(sub.IsDisabled())  if hasattr(sub, "IsDisabled")  else False,
        bool(sub.IsDestroyed()) if hasattr(sub, "IsDestroyed") else False,
    )


def _diff_state(before: tuple, after: tuple):
    """Worst NEW state-flag, or None if no flag flipped False→True.

    Priority: destroyed > disabled > None. Pre-existing True flags are
    ignored — only False→True transitions count.

    The `damaged` flag is deliberately excluded from the CRITICAL trigger
    semantics: IsDamaged() typically returns condition < max_condition,
    so it flips True on every subsystem's first damage tick, which would
    promote every first hit to CRITICAL — too noisy. CRITICAL is reserved
    for "this subsystem stopped working" (disabled or destroyed).
    `_subsystem_state_flags` still snapshots all three flags so future
    consumers can read them, but `_diff_state` ignores the damaged one.
    """
    _b_dmg, b_dis, b_des = before
    _a_dmg, a_dis, a_des = after
    if a_des and not b_des:
        return "destroyed"
    if a_dis and not b_dis:
        return "disabled"
    return None


def _iter_subsystems(ship):
    """Yield every leaf subsystem on `ship`, excluding the hull.

    Walks `ship.GetSubsystems()` and for each top-level subsystem also
    yields the entries of its `_children` list (weapon-system parents
    expose hardpoint children there). Falls back to the legacy
    `GetNumChildSubsystems` / `GetChildSubsystem(i)` API for stub ships
    that predate `GetSubsystems`.

    Hull is excluded because the attribution resolver damages it
    unconditionally outside the iteration loop.
    """
    hull = ship.GetHull()

    if hasattr(ship, "GetSubsystems"):
        for s in ship.GetSubsystems():
            if s is None or s is hull:
                continue
            yield s
            children = getattr(s, "_children", None)
            if children:
                for c in children:
                    if c is not None and c is not hull:
                        yield c
        return

    n = ship.GetNumChildSubsystems()
    for i in range(n):
        s = ship.GetChildSubsystem(i)
        if s is not None and s is not hull:
            yield s


def pick_target_subsystem(ship, hit_point):
    """Return the subsystem closest to ``hit_point`` in the ship's body
    frame, gated by ``d <= 2 * sub.GetRadius()``. Walks every top-level
    subsystem in ``ship.GetSubsystems()`` plus the ``_children`` of each
    weapon-system parent. Hull is excluded from the walk and only
    returned as the fallback when no candidate passes the gate.

    Falls back to ``ship.GetHull()`` if no subsystem is in range, or
    ``None`` if there is no hull either.

    Legacy fixture support: if ``ship`` lacks ``GetSubsystems``, walks
    ``GetChildSubsystem(i)`` for ``i in range(GetNumChildSubsystems())``
    so the pre-existing ``_FakeShip`` tests stay green.
    """
    hull = ship.GetHull() if hasattr(ship, "GetHull") else None

    # Build the candidate list. Hull is never iterated.
    candidates: list = []
    if hasattr(ship, "GetSubsystems"):
        for s in ship.GetSubsystems():
            if s is None or s is hull:
                continue
            candidates.append(s)
            # Hardpoint children mounted under weapon-system parents.
            children = getattr(s, "_children", None)
            if children:
                candidates.extend(children)
    else:
        # Legacy fallback for _FakeShip-style stubs.
        n = ship.GetNumChildSubsystems() if hasattr(ship, "GetNumChildSubsystems") else 0
        for i in range(n):
            s = ship.GetChildSubsystem(i)
            if s is not None and s is not hull:
                candidates.append(s)

    bx, by, bz = _body_frame_delta(ship, hit_point)

    best = None
    best_dist_sq = float("inf")
    for sub in candidates:
        pos = sub.GetPosition() if hasattr(sub, "GetPosition") else None
        if pos is None:
            continue
        r = sub.GetRadius() if hasattr(sub, "GetRadius") else 0.0
        dx = bx - pos.x
        dy = by - pos.y
        dz = bz - pos.z
        d_sq = dx * dx + dy * dy + dz * dz
        if d_sq > (2.0 * r) ** 2:
            continue
        if d_sq < best_dist_sq:
            best = sub
            best_dist_sq = d_sq
    if best is not None:
        return best
    return hull


def _shield_face_from_hit_point(ship, hit_point) -> int:
    """Body-frame dominant-axis selection via :func:`_body_frame_delta`.

    Face indices follow the ``ShieldSubsystem`` class constants:
    FRONT/REAR ↔ ±body-Y, TOP/BOTTOM ↔ ±body-Z, LEFT/RIGHT ↔ ∓body-X,
    per CLAUDE.md's column-vector rotation convention
    (``R.GetCol(0)`` = ship-right, ``R.GetCol(1)`` = ship-forward,
    ``R.GetCol(2)`` = ship-up). Ships lacking ``GetWorldRotation``
    receive identity R from :func:`_body_frame_delta`, so legacy
    fixtures keep their pre-rotation behaviour.
    """
    bx, by, bz = _body_frame_delta(ship, hit_point)
    abs_x, abs_y, abs_z = abs(bx), abs(by), abs(bz)
    if abs_y >= abs_x and abs_y >= abs_z:
        return 0 if by >= 0 else 1
    if abs_z >= abs_x:
        return 2 if bz >= 0 else 3
    return 4 if bx <= 0 else 5


def apply_hit(ship, damage: float, hit_point, source, subsystem=None,
              *, normal=None, host=None, ship_instances=None,
              weapon_type: str | None = None) -> None:
    """Route `damage` to `ship`: shields face first → picked subsystem
    → hull bleed.  Then call hit_feedback.dispatch with the per-stage
    absorbed breakdown + subsystem state transition + surface normal,
    then broadcast WeaponHitEvent so per-ship and broadcast handlers
    (MissionLib.FriendlyFireHandler) react.

    normal — TGPoint3 surface normal at hit_point, or None if the
             mesh trace missed. Threaded to hit_feedback.dispatch.
    host, ship_instances — passed through to dispatch so it can
             fire host.shield_hit (the shield-bubble splash on
             SHIELD severity).
    weapon_type — "phaser" / "torpedo" / None. Consumed by dispatch
             to match SDK Effects.py audio semantics: phaser-on-shields
             is silent (stock BC has no PhaserShieldHit handler);
             torpedo-on-shields plays from g_lsWeaponExplosions
             (matching Effects.TorpedoShieldHit).

    Dispatch is wrapped in try/except so a renderer or audio crash
    cannot suppress the WeaponHitEvent broadcast.
    """
    from engine.appc.events import WeaponHitEvent
    from engine.appc import hit_feedback
    import App

    if subsystem is None:
        subsystem = pick_target_subsystem(ship, hit_point)

    remaining = float(damage)
    absorbed_shields = 0.0
    absorbed_subsystem = 0.0
    absorbed_hull = 0.0
    sub_transition = None
    hull = ship.GetHull() if hasattr(ship, "GetHull") else None

    # 1. Shields take it first — but only if the generator is powered
    #    (IsOn) AND not offline (disabled / destroyed via subsystem
    #    damage). At green alert the generator is down; once condition
    #    drops below DisabledPercentage the subsystem is offline. Either
    #    way damage flows straight to the picked subsystem / hull bleed.
    #    BC's bypass set: see combat-and-damage.md "Shield bypass paths".
    #    Fakes that don't implement IsOn default to on, so legacy unit
    #    tests keep working.
    shields = ship.GetShields() if hasattr(ship, "GetShields") else None
    shields_on = bool(getattr(shields, "IsOn", lambda: 1)()) if shields is not None else False
    # Disabled/destroyed defaults to 0 so fakes without these predicates
    # behave as before (online when IsOn).
    shields_disabled = bool(getattr(shields, "IsDisabled", lambda: 0)()) if shields is not None else False
    shields_destroyed = bool(getattr(shields, "IsDestroyed", lambda: 0)()) if shields is not None else False
    shields_online = (shields is not None and shields_on
                      and not shields_disabled and not shields_destroyed)
    if shields_online and hasattr(shields, "ApplyDamage"):
        face = _shield_face_from_hit_point(ship, hit_point)
        before_shields = remaining
        remaining = shields.ApplyDamage(face, remaining)
        absorbed_shields = before_shields - remaining

    # 2. Bleed remainder to picked subsystem (skip if subsystem is the hull —
    #    the hull-bleed branch below handles that).
    if remaining > 0.0 and subsystem is not None and subsystem is not hull \
            and hasattr(ship, "DamageSystem"):
        before_flags = _subsystem_state_flags(subsystem)
        current = subsystem.GetCondition() if hasattr(subsystem, "GetCondition") else remaining
        absorb = min(remaining, current)
        ship.DamageSystem(subsystem, absorb)
        absorbed_subsystem = absorb
        remaining -= absorb
        after_flags = _subsystem_state_flags(subsystem)
        sub_transition = _diff_state(before_flags, after_flags)

    # 3. Bleed final remainder to hull.
    if remaining > 0.0 and hull is not None and hasattr(ship, "DamageSystem"):
        ship.DamageSystem(hull, remaining)
        absorbed_hull = remaining
        remaining = 0.0

    # 4. Fan out VFX + audio + camera shake. Errors swallowed so the
    #    downstream WeaponHitEvent broadcast always runs.
    try:
        hit_feedback.dispatch(
            ship=ship, source=source, point=hit_point, normal=normal,
            damage=damage, subsystem=subsystem,
            absorbed_shields=absorbed_shields,
            absorbed_subsystem=absorbed_subsystem,
            absorbed_hull=absorbed_hull,
            sub_transition=sub_transition,
            host=host, ship_instances=ship_instances,
            weapon_type=weapon_type,
        )
    except Exception:
        # Dispatch failures must not suppress mission handlers below.
        pass

    # 5. Broadcast WeaponHitEvent.
    evt = WeaponHitEvent()
    evt.SetSource(source)
    evt.SetTarget(ship)
    evt.SetDamage(damage)
    evt.SetHitPoint(hit_point)
    evt.SetSubsystem(subsystem)
    if isinstance(ship, App.TGEventHandlerObject):
        evt.SetDestination(ship)
    App.g_kEventManager.AddEvent(evt)
