"""Torpedo runtime projectile + in-flight registry.

The Torpedo class is a data carrier; the SDK projectile scripts
(sdk/Build/scripts/Tactical/Projectiles/*.py) populate it via
CreateTorpedoModel + SetDamage/SetDamageRadiusFactor/SetGuidance-
Lifetime/SetMaxAngularAccel.  Engine never embeds projectile data —
it always reads from the bound script per shot.

Module-level _active registry holds in-flight torpedoes; update_all
advances motion, runs collision, returns the list of (torpedo, hit_ship,
hit_point) tuples for host_loop to route through combat.apply_hit.
"""
import math

from engine.appc.math import TGPoint3
from engine.core.ids import TGObject


class Torpedo(TGObject):
    """Runtime projectile.  Visual fields populated by CreateTorpedoModel;
    behaviour fields by SetDamage/SetGuidanceLifetime/SetMaxAngularAccel.
    """
    __slots__ = (
        "_position", "_velocity", "_age", "_ttl",
        "_damage", "_damage_radius_factor",
        "_target_ship", "_target_subsystem",
        "_guidance_lifetime", "_max_angular_accel",
        "_source_ship", "_id",
        "_core_texture", "_core_color", "_core_size_a", "_core_size_b",
        "_glow_texture", "_glow_color", "_glow_size_a", "_glow_size_b", "_glow_size_c",
        "_flares_texture", "_flares_color", "_num_flares",
        "_flares_size_a", "_flares_size_b",
    )

    def __init__(self):
        super().__init__()
        self._position = TGPoint3(0.0, 0.0, 0.0)
        self._velocity = TGPoint3(0.0, 0.0, 0.0)
        self._age = 0.0
        self._ttl = 30.0
        self._damage = 0.0
        self._damage_radius_factor = 0.0
        self._target_ship = None
        self._target_subsystem = None
        self._guidance_lifetime = 0.0
        self._max_angular_accel = 0.0
        self._source_ship = None
        self._id = 0
        self._core_texture   = ""
        self._core_color     = None
        self._core_size_a    = 0.0
        self._core_size_b    = 0.0
        self._glow_texture   = ""
        self._glow_color     = None
        self._glow_size_a    = 0.0
        self._glow_size_b    = 0.0
        self._glow_size_c    = 0.0
        self._flares_texture = ""
        self._flares_color   = None
        self._num_flares     = 0
        self._flares_size_a  = 0.0
        self._flares_size_b  = 0.0

    def CreateTorpedoModel(self,
            core_tex, core_color, core_a, core_b,
            glow_tex, glow_color, glow_a, glow_b, glow_c,
            flares_tex, flares_color, num_flares, flares_a, flares_b) -> None:
        self._core_texture   = str(core_tex)
        self._core_color     = core_color
        self._core_size_a    = float(core_a)
        self._core_size_b    = float(core_b)
        self._glow_texture   = str(glow_tex)
        self._glow_color     = glow_color
        self._glow_size_a    = float(glow_a)
        self._glow_size_b    = float(glow_b)
        self._glow_size_c    = float(glow_c)
        self._flares_texture = str(flares_tex)
        self._flares_color   = flares_color
        self._num_flares     = int(num_flares)
        self._flares_size_a  = float(flares_a)
        self._flares_size_b  = float(flares_b)

    def SetDamage(self, v) -> None:               self._damage = float(v)
    def SetDamageRadiusFactor(self, v) -> None:   self._damage_radius_factor = float(v)
    def GetDamageRadiusFactor(self) -> float:     return self._damage_radius_factor
    def SetGuidanceLifetime(self, v) -> None:     self._guidance_lifetime = float(v)
    def SetMaxAngularAccel(self, v) -> None:      self._max_angular_accel = float(v)
    def SetNetType(self, v) -> None:              pass  # multiplayer; ignored in PR 2b


# ── Registry ────────────────────────────────────────────────────────────────
_active: list[Torpedo] = []
_next_id: int = 1


def register(torpedo: Torpedo) -> None:
    global _next_id
    torpedo._id = _next_id
    _next_id += 1
    _active.append(torpedo)


def expire(torpedo: Torpedo) -> None:
    try:
        _active.remove(torpedo)
    except ValueError:
        pass


def update_all(dt: float, all_ships, *, host=None, ship_instances=None) -> list[tuple]:
    """Advance every active torpedo by dt.  Returns list of
    (torpedo, hit_ship, hit_point, hit_normal) tuples that connected this tick.
    Expired torpedoes (TTL or impact) are removed from _active.

    `host` and `ship_instances` are forwarded to combat._resolve_hit_point;
    when omitted (headless tests, no renderer), hit_point degrades to the
    torpedo's post-advance position and hit_normal is None — matching the
    pre-project behaviour. `hit_normal` is the mesh surface normal (a TGPoint3)
    when the trace succeeds, else None; callers forward it to apply_hit so the
    persistent damage decal can render (a None normal suppresses the decal).
    """
    from engine.appc.combat import (sphere_hit, _resolve_hit_point)
    from engine.appc.math import TGPoint3

    hits: list[tuple] = []
    expired: list[Torpedo] = []

    for t in list(_active):
        # 1. Steer if homing within guidance window.
        if t._target_ship is not None and t._age < t._guidance_lifetime:
            _steer_toward(t, t._target_ship, dt)
        # 2. Advance position + age.
        prev_pos = t._position
        t._position = t._position + t._velocity * dt
        t._age += dt
        if t._age >= t._ttl:
            expired.append(t)
            continue
        # 3. Collide.
        for ship in all_ships:
            if ship is t._source_ship:
                continue
            if ship.IsDead():
                continue
            if sphere_hit(t._position, ship.GetWorldLocation(), ship.GetRadius()):
                # Build the per-tick ray and resolve the hit point through
                # the three-tier fallback (mesh trace / sphere entry /
                # post-advance position).
                seg = t._position - prev_pos
                seg_len = seg.Length()
                # seg_len ~= 0 only if dt or velocity was zero this tick;
                # _resolve_hit_point treats `ray_direction=None` as "degrade
                # to fallback", which is what we want for a stationary tick.
                aim_unit = (TGPoint3(seg.x / seg_len, seg.y / seg_len, seg.z / seg_len)
                            if seg_len > 1e-9 else None)
                hit_point, hit_normal = _resolve_hit_point(
                    host=host, ship_instances=ship_instances, ship=ship,
                    ray_origin=prev_pos,
                    ray_direction=aim_unit,
                    max_dist=seg_len,
                    fallback_point=t._position,
                )
                hits.append((t, ship, hit_point, hit_normal))
                expired.append(t)
                break

    for t in expired:
        expire(t)

    return hits


def _steer_toward(torpedo: Torpedo, target_ship, dt: float) -> None:
    """Rotate torpedo._velocity toward target ship position by at most
    max_angular_accel × dt radians.  Preserves velocity magnitude.
    """
    target_pos = target_ship.GetWorldLocation()
    to_target = target_pos - torpedo._position
    dist = to_target.Length()
    if dist < 1e-6:
        return
    desired = TGPoint3(to_target.x / dist, to_target.y / dist, to_target.z / dist)

    speed = torpedo._velocity.Length()
    if speed < 1e-6:
        return
    current = TGPoint3(
        torpedo._velocity.x / speed,
        torpedo._velocity.y / speed,
        torpedo._velocity.z / speed,
    )

    cos_theta = max(-1.0, min(1.0, current.Dot(desired)))
    theta = math.acos(cos_theta)
    max_step = torpedo._max_angular_accel * dt
    if theta <= max_step or theta < 1e-6:
        new_dir = desired
    else:
        sin_theta = math.sin(theta)
        a = math.sin(theta - max_step) / sin_theta
        b = math.sin(max_step) / sin_theta
        new_dir = TGPoint3(
            current.x * a + desired.x * b,
            current.y * a + desired.y * b,
            current.z * a + desired.z * b,
        )
    torpedo._velocity = new_dir * speed
