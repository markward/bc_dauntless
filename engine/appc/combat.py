"""Combat collision + damage routing.

Called by host_loop._advance_combat after engine.appc.projectiles.
update_all reports a torpedo hit.  Routes damage shields-face → picked
subsystem → hull bleed, then broadcasts WeaponHitEvent so mission
handlers (FriendlyFireHandler etc.) see the hit.
"""
from engine.appc.math import TGPoint3
import engine.dev_mode as dev_mode


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


def _subsystem_world_position(ship, subsystem):
    """Return the world-space position of `subsystem` on `ship`.

    Per CLAUDE.md's column-vector convention, body->world is
    `v_world = R · v_body`. SDK `TGPoint3.MultMatrixLeft(R)` already
    computes that in place. We construct a fresh point to avoid
    mutating the subsystem's stored position.

    Legacy fakes without `GetWorldRotation` get identity R, so
    `world_pos = ship_pos + body_pos`.
    """
    ship_pos = ship.GetWorldLocation()
    body_pos = subsystem.GetPosition()
    if not hasattr(ship, "GetWorldRotation"):
        return TGPoint3(
            ship_pos.x + body_pos.x,
            ship_pos.y + body_pos.y,
            ship_pos.z + body_pos.z,
        )
    R = ship.GetWorldRotation()
    p = TGPoint3(body_pos.x, body_pos.y, body_pos.z)
    p.MultMatrixLeft(R)
    p.x += ship_pos.x
    p.y += ship_pos.y
    p.z += ship_pos.z
    return p


def _splash_weight(r_sub: float, r_hit: float, d: float) -> float:
    """Linear falloff weight for splash damage attribution.

    `r_sub`  — subsystem catchment radius
    `r_hit`  — weapon splash radius
    `d`      — distance from impact point to subsystem world position

    Returns 1.0 when the impact is inside (or on the surface of) the
    subsystem sphere, decays linearly to 0 at the combined-sphere edge,
    and is exactly 0 at or beyond. A zero `r_hit` degenerate weapon
    returns 0.0 with no division by zero.
    """
    if r_hit <= 0.0:
        return 0.0
    raw = (r_sub + r_hit - d) / r_hit
    if raw <= 0.0:
        return 0.0
    if raw >= 1.0:
        return 1.0
    return raw


def _pick_primary_subsystem_for_dispatch(allocations):
    """Return the subsystem with the highest splash weight in
    `allocations`, ties broken by first appearance, or None if the list
    is empty or every weight is zero.

    `allocations` is an iterable of `(subsystem, weight)` tuples
    produced by the apply_hit resolver loop. The hit_feedback.dispatch
    consumer wants a single subsystem so the per-stage severity
    classifier (shield-only / hull-pen / critical-fail) can decide
    which subsystem's state transition to report.
    """
    primary = None
    best = 0.0
    for sub, w in allocations:
        if w > best:
            best = w
            primary = sub
    return primary


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


def apply_hit(ship, damage: float, hit_point, source, *,
              normal=None, host=None, ship_instances=None,
              weapon_type: str | None = None,
              hardpoint_weapon=None, payload_template=None,
              splash_radius: float | None = None,
              damage_hull: bool = True,
              bypass_shields: bool = False) -> None:
    """Apply `damage` to `ship` per the spherical-splash attribution model.

    Flow:
    1. Resolve splash radius `R_hit` from (hardpoint_weapon, payload_template).
    2. Apply shield attenuation on the impact-direction face.
    3. Damage the hull at full post-shield damage (unconditional).
    4. Walk every non-hull subsystem; for each whose damage sphere
       intersects the splash sphere, apply `D · w_i` independently.
    5. Dispatch hit_feedback with shield / subsystem / hull totals and
       the highest-weight subsystem as the "primary" for severity
       classification.
    6. Broadcast WeaponHitEvent carrying hit point, normal, splash
       radius, and primary subsystem.

    Kwargs:
        normal              — TGPoint3 surface normal at hit_point (mesh
                              trace), or None.
        host, ship_instances — passed to hit_feedback.dispatch.
        weapon_type         — "phaser" / "torpedo" / None. Used by dispatch
                              for audio routing.
        hardpoint_weapon    — WeaponProperty on the firing ship's hardpoint
                              (used to resolve R_hit). None for legacy callers.
        payload_template    — projectile-type template (used to resolve R_hit
                              when hardpoint DRF is not set). None for phasers.
        splash_radius       — explicit R_hit override in game units. When set,
                              supersedes the (hardpoint_weapon, payload_template)
                              resolution. Used by the warp-core breach to force a
                              1.3 GU blast. None for all weapon callers.
        damage_hull         — when False, the hull takes NO condition damage
                              (subsystems still take their weighted share). This
                              is the LIGHT (PP_LOW) phaser "disable, don't
                              destroy" mode verified by dev-console probe. The
                              hull is still flagged as struck for cosmetic
                              feedback (scorch decal, severity, audio), but the
                              persistent hull carve is suppressed. Defaults True
                              (FULL / torpedo / collision / explosion).
        bypass_shields      — when True, skip the shield cascade entirely and
                              route full damage to hull/subsystems. This is the
                              `AddDamage` explosion/collision primitive verified
                              by dev-console probe (shields do not absorb a warp-
                              core breach or a ramming impact). Defaults False
                              (normal weapon fire cascades through shields).
    """
    from engine.appc.events import WeaponHitEvent
    from engine.appc import hit_feedback
    import engine.dev_combat_cheats as _cheats
    import App

    r_hit = weapon_splash_radius(hardpoint_weapon, payload_template)
    if splash_radius is not None:
        r_hit = float(splash_radius)

    # -- Developer combat cheats (dev-mode only; no-ops in production). --
    # Resolve the player once, then apply: 2x player weapons (source is
    # player), god mode (target is player -> suppress all state mutation
    # but keep feedback), and disable-NPC-shields (target is not player).
    # Every getter ANDs with dev_mode, so a production build is unaffected.
    # Spec: docs/superpowers/specs/2026-06-08-developer-options-menu-design.md
    try:
        _game = App.Game_GetCurrentGame() if hasattr(App, "Game_GetCurrentGame") else None
        _player = _game.GetPlayer() if _game is not None and hasattr(_game, "GetPlayer") else None
    except Exception:
        _player = None
    _target_is_player = _player is not None and ship is _player
    _source_is_player = _player is not None and source is _player

    if _cheats.double_player_weapons_active() and _source_is_player:
        damage = float(damage) * 2.0

    # When god mode protects the player, mutation calls are skipped but the
    # absorbed_* amounts are still computed so hit feedback fires unchanged.
    _commit = not (_cheats.god_mode_active() and _target_is_player)

    # 1. Shields take the first bite. Identical to the pre-splash flow.
    remaining = float(damage)
    absorbed_shields = 0.0
    shields = ship.GetShields() if hasattr(ship, "GetShields") else None
    shields_on = bool(getattr(shields, "IsOn", lambda: 1)()) if shields is not None else False
    shields_disabled = bool(getattr(shields, "IsDisabled", lambda: 0)()) if shields is not None else False
    shields_destroyed = bool(getattr(shields, "IsDestroyed", lambda: 0)()) if shields is not None else False
    shields_online = (shields is not None and shields_on
                      and not shields_disabled and not shields_destroyed)
    # Disable-NPC-shields cheat: every non-player ship's shields stop
    # absorbing, so full damage reaches the hull/subsystems.
    if _cheats.disable_npc_shields_active() and not _target_is_player:
        shields_online = False
    # Explosion / collision primitive (AddDamage): bypass the shield cascade
    # entirely — full damage reaches the hull/subsystems, shield faces untouched.
    if bypass_shields:
        shields_online = False
    if shields_online and hasattr(shields, "ApplyDamage"):
        face = _shield_face_from_hit_point(ship, hit_point)
        before = remaining
        if _commit:
            remaining = shields.ApplyDamage(face, remaining)
        else:
            # God mode: compute the overflow WITHOUT draining the face, so
            # the shield flash still fires but the player's shields stay full.
            cur = (shields.GetCurrentShields(face)
                   if hasattr(shields, "GetCurrentShields") else before)
            remaining = max(0.0, remaining - cur)
        absorbed_shields = before - remaining

    post_shield = remaining
    absorbed_hull = 0.0
    absorbed_subsystem_total = 0.0
    allocations: list = []  # (subsystem, weight) for primary picking
    primary_transition = None

    hull = ship.GetHull() if hasattr(ship, "GetHull") else None

    if post_shield > 0.0:
        # 2. Hull takes full post-shield damage — UNLESS damage_hull is False
        #    (LIGHT phaser: subsystems only, hull HP untouched). `absorbed_hull`
        #    is still set so the hull reads as struck for cosmetic feedback
        #    (scorch decal, severity, audio); only the condition mutation and
        #    the hull carve (gated separately below via allow_hull_carve) are
        #    suppressed.
        if hull is not None and hasattr(ship, "DamageSystem"):
            if _commit and damage_hull:
                ship.DamageSystem(hull, post_shield)
            absorbed_hull = post_shield

        # 3. Each non-hull subsystem within the splash sphere takes a
        #    weighted share independently. Total can exceed post_shield.
        for sub in _iter_subsystems(ship):
            pos = sub.GetPosition() if hasattr(sub, "GetPosition") else None
            if pos is None:
                continue
            r_sub = sub.GetRadius() if hasattr(sub, "GetRadius") else 0.0
            h_world = _subsystem_world_position(ship, sub)
            dx = hit_point.x - h_world.x
            dy = hit_point.y - h_world.y
            dz = hit_point.z - h_world.z
            d = (dx * dx + dy * dy + dz * dz) ** 0.5
            if d >= r_sub + r_hit:
                continue
            w = _splash_weight(r_sub, r_hit, d)
            if w <= 0.0:
                continue
            allocations.append((sub, w))
            amount = post_shield * w
            if hasattr(ship, "DamageSystem"):
                before_flags = _subsystem_state_flags(sub)
                if _commit:
                    ship.DamageSystem(sub, amount)
                absorbed_subsystem_total += amount
                after_flags = _subsystem_state_flags(sub)
                transition = _diff_state(before_flags, after_flags)
                if transition is not None and primary_transition is None:
                    primary_transition = transition

    primary_subsystem = _pick_primary_subsystem_for_dispatch(allocations)

    # 4. Fan out VFX + audio + camera shake. Errors swallowed so the
    #    downstream WeaponHitEvent broadcast always runs.
    try:
        hit_feedback.dispatch(
            ship=ship, source=source, point=hit_point, normal=normal,
            damage=damage, subsystem=primary_subsystem,
            absorbed_shields=absorbed_shields,
            absorbed_subsystem=absorbed_subsystem_total,
            absorbed_hull=absorbed_hull,
            sub_transition=primary_transition,
            host=host, ship_instances=ship_instances,
            weapon_type=weapon_type,
            radius=r_hit,
            persist_decal=_commit,
            allow_hull_carve=damage_hull,
        )
    except Exception as _e:
        dev_mode.log_swallowed("hit_feedback.dispatch", _e)

    # 5. Broadcast WeaponHitEvent. The hull-vs-shield flag reuses the
    #    `post_shield > 0` branch above: any damage left after the facing
    #    absorbed its share reached the hull. Read by Conditions/
    #    ConditionAttacked + ConditionAttackedBy via IsHullHit().
    evt = WeaponHitEvent(is_hull_hit=(post_shield > 0.0))
    evt.SetSource(source)
    evt.SetTarget(ship)
    evt.SetDamage(damage)
    evt.SetHitPoint(hit_point)
    evt.SetNormal(normal)
    evt.SetRadius(r_hit)
    evt.SetSubsystem(primary_subsystem)
    if isinstance(ship, App.TGEventHandlerObject):
        evt.SetDestination(ship)
    App.g_kEventManager.AddEvent(evt)
