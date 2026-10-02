"""Large scenery rocks collide with the player (rock-fields spec section 2).

The native near band streams large rocks around the player and reports each
swept touch (`renderer.rockfield_drain_contacts()`: point, normal, rock
centre, rock radius, rel speed, pen; VIEW space; normal points rock -> ship).
This module is the sim-side response, pumped from host_loop beside the
minor-rock contacts -- never from a render feed.

A scenery rock is immovable (it is not an object), so the ship takes the
full impulse and the full de-penetration, exactly as against a planet. With
shields up (combat.shields_block) the rock meets the shield BUBBLE, the same
ellipsoid collisions._bubble_contact gives real rocks, and the damage
cascades through the facing; shields down, it is a kinetic hull hit that
bypasses shields (the AddDamage collision primitive).

Scenery is not an object: no ET_OBJECT_COLLISION, ET_PLANET_COLLISION or
ET_CLOAKED_COLLISION is posted. apply_hit's own WeaponHitEvent (source None,
as AddDamage) still is.

Limitation: contacts are VIEW-space, so a touch is applied only while the
player's containing set IS the viewed set. A player seen from another region
(an in-space cutscene in a different set) gets no scenery collisions.

Muted while dashing or in the "warp" set -- minor_contact._muted, the same
rule as the minor-rock responses.
"""
from engine.appc.math import TGPoint3


def reset() -> None:
    """Mission swap. The response is stateless today (the native band owns
    the per-rock cooldown); kept so host_loop's reset stays symmetric."""


def shield_inflate(player) -> float:
    """SHIELD_ELLIPSOID_AXIS_SCALE when combat.shields_block(player), else 0.0."""
    from engine.appc import combat
    if player is not None and combat.shields_block(player):
        return combat.SHIELD_ELLIPSOID_AXIS_SCALE
    return 0.0


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def respond(player, contact: dict, ship_instances=None):
    """Apply one large-rock touch. Returns {"shielded": bool, "damage": float,
    "impulse": (x, y, z)} when it responded, None when it did not (receding,
    shield bubble missed, player not in the viewed set)."""
    from engine.appc import collisions, combat
    from engine.appc.hit_feedback import SHIELD_SPLASH_REACH_PER_RADIUS
    from engine.rocks import far_dials
    from engine.systems import frames

    view = frames.viewing_set()
    if view is None or frames.containing_set(player) is not view:
        return None
    rock_r = float(contact["rock_radius"])
    ship = collisions._resolve_body(player)
    rock = collisions._Body(None, TGPoint3(*contact["rock_centre"]), rock_r,
                            0.0, False, TGPoint3(0.0, 0.0, 0.0),
                            TGPoint3(0.0, 0.0, 0.0), 1.0)

    shielded = False
    shield_point = None
    bubble = None
    if combat.shields_block(player):
        shielded = True
        bubble = collisions._bubble_contact(ship, rock)
        if bubble is collisions._BUBBLE_MISS:
            return None
    if bubble is not None:
        shield_point, n_out, pen = bubble
        n = (-n_out[0], -n_out[1], -n_out[2])
        point = shield_point
    else:
        # Hull path; also a shielded ship whose bubble has no geometry (no
        # hull box) or already holds the rock's centre.
        n = tuple(float(c) for c in contact["normal"])
        pen = float(contact["pen"])
        point = TGPoint3(*contact["point"])

    v = ship.velocity
    v_rel = _dot((v.x, v.y, v.z), n)
    if v_rel >= 0.0:
        return None      # receding: the debounce, as _respond_pair

    k = -(1.0 + collisions.COLLISION_RESTITUTION) * v_rel
    impulse = (k * n[0], k * n[1], k * n[2])
    cv = collisions._ensure_overlay(player)
    cv.x += impulse[0]
    cv.y += impulse[1]
    cv.z += impulse[2]
    p = player.GetTranslate()
    player.SetTranslateXYZ(p.x + n[0] * pen, p.y + n[1] * pen, p.z + n[2] * pen)

    damage = (collisions._ke_damage(ship.inv_mass, v_rel)
              * far_dials.get("collide_damage_scale")
              * min(1.0, rock_r / far_dials.get("collide_ref_radius_gu")))

    # The ship's own hull: trace from just outside the contact back in.
    # _trace_own_hull wants the normal pointing OUT of the ship (ship -> rock).
    n_out_ship = TGPoint3(-n[0], -n[1], -n[2])
    pt, hit_n = collisions._trace_own_hull(
        ship_instances, ship, point, n_out_ship,
        2.0 * (ship.contact + rock_r))
    # Slip direction: the ship's velocity with its normal part removed.
    tv = (v.x - v_rel * n[0], v.y - v_rel * n[1], v.z - v_rel * n[2])
    tl = _dot(tv, tv) ** 0.5
    tangent = TGPoint3(tv[0] / tl, tv[1] / tl, tv[2] / tl) if tl > 1e-6 else None
    # source=None: scenery has no object; AddDamage's collision primitive
    # (objects.py) already passes None through apply_hit.
    combat.apply_hit(player, damage, pt, None, normal=hit_n,
                     ship_instances=ship_instances, weapon_type="collision",
                     hit_tangent=tangent,
                     decal_radius=collisions.scuff_radius_gu(rock_r, pen),
                     decal_dent=1.0, bypass_shields=not shielded,
                     shield_point=shield_point, single_impact=True,
                     shield_radius=rock_r / SHIELD_SPLASH_REACH_PER_RADIUS)
    return {"shielded": shielded, "damage": damage, "impulse": impulse}


def pump(player, contacts=None, session=None) -> list:
    """Drain (or take `contacts`), skip all when muted (dashing / "warp" set),
    respond to each; returns the non-None results."""
    if contacts is None:
        from engine import renderer
        contacts = renderer.rockfield_drain_contacts()
    if player is None or not contacts:
        return []
    from engine.rocks import minor_contact
    if minor_contact._muted(player):
        return []
    instances = getattr(session, "ship_instances", None)
    out = []
    for c in contacts:
        r = respond(player, c, ship_instances=instances)
        if r is not None:
            out.append(r)
    return out
