"""Torpedo runtime projectile + in-flight registry.

The Torpedo class is a data carrier; the SDK projectile scripts
(sdk/Build/scripts/Tactical/Projectiles/*.py) populate it via
CreateTorpedoModel + SetDamage/SetDamageRadiusFactor/SetGuidance-
Lifetime/SetMaxAngularAccel.  Engine never embeds projectile data —
it always reads from the bound script per shot.

Disruptor bolts (CreateDisruptorModel) are a different render family from
torpedoes: BC builds them as a procedural two-color tapered-tube mesh, not a
textured quad (audited weapon-firing-mechanics.md §5.5).  Torpedo stores the
authentic shell/core colors + length/width in dedicated fields; the torpedo
quad fields are left at their __init__ defaults for a disruptor bolt.

Module-level _active registry holds in-flight torpedoes; update_all
advances motion, runs collision, returns the list of (torpedo, hit_ship,
hit_point, hit_normal) tuples for host_loop to route through combat.apply_hit.
"""
import math

from engine.appc.math import TGPoint3
from engine.core.ids import TGObject


class Torpedo(TGObject):
    """Runtime projectile.  Torpedo-style visual fields populated by
    CreateTorpedoModel (textured core+glow+flares quads); disruptor-style
    bolts populated by CreateDisruptorModel (authentic procedural
    tapered-tube fields — a disruptor never touches the quad fields).
    Behaviour fields set by SetDamage/SetGuidanceLifetime/SetMaxAngularAccel.
    """
    __slots__ = (
        "_position", "_velocity", "_age", "_ttl",
        "_damage", "_damage_radius_factor",
        "_target_ship",
        "_guidance_lifetime", "_guidance_initial", "_max_angular_accel",
        "_last_seen_target_pos", "_last_target_vel",
        "_source_ship", "_id",
        "_core_texture", "_core_color", "_core_size_a", "_core_size_b",
        "_glow_texture", "_glow_color", "_glow_size_a", "_glow_size_b", "_glow_size_c",
        "_flares_texture", "_flares_color", "_num_flares",
        "_flares_size_a", "_flares_size_b",
        "_is_disruptor", "_shell_color", "_bolt_core_color",
        "_bolt_length", "_bolt_width",
    )

    def __init__(self):
        super().__init__()
        self._position = TGPoint3(0.0, 0.0, 0.0)
        self._velocity = TGPoint3(0.0, 0.0, 0.0)
        self._age = 0.0
        self._ttl = 60.0
        self._damage = 0.0
        self._damage_radius_factor = 0.0
        self._target_ship = None
        self._guidance_lifetime = 4.0
        self._guidance_initial = 4.0
        self._max_angular_accel = 0.125
        self._last_seen_target_pos = None
        self._last_target_vel = None
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
        self._is_disruptor   = False
        self._shell_color    = None
        self._bolt_core_color = None
        self._bolt_length    = 0.0
        self._bolt_width     = 0.0

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
        self._is_disruptor   = False   # idempotent-safe if a script calls both

    def CreateDisruptorModel(self, outer_shell_color, outer_core_color,
                             length, width) -> None:
        """Populate the bolt's render fields for a disruptor/pulse-weapon shot.

        BC builds a procedural two-color tapered-tube bolt, NOT a textured
        quad (audited weapon-firing-mechanics.md §5.5): a 12-segment
        longitudinal ring swept around the travel axis, cross-section taper
        profile {0.9927, 0.9727, 0.9273, 0.7273} x width, vertex-colored by
        the outer shell + core colors, re-oriented to velocity each frame by
        the renderer.  No texture, no light, no controller.  We store the
        authentic construction args directly; the torpedo quad fields
        (core/glow textures, sizes, flares) stay at their __init__ defaults
        — a disruptor bolt never touches them.
        """
        self._is_disruptor    = True
        self._shell_color     = outer_shell_color
        self._bolt_core_color = outer_core_color
        self._bolt_length     = float(length)
        self._bolt_width      = float(width)

    def SetDamage(self, v) -> None:               self._damage = float(v)
    def SetDamageRadiusFactor(self, v) -> None:   self._damage_radius_factor = float(v)
    def GetDamageRadiusFactor(self) -> float:     return self._damage_radius_factor
    def SetGuidanceLifetime(self, v) -> None:
        self._guidance_lifetime = float(v)
        self._guidance_initial = float(v)
    def SetLifetime(self, v) -> None:             self._ttl = float(v)
    def SetMaxAngularAccel(self, v) -> None:      self._max_angular_accel = float(v)
    def SetNetType(self, v) -> None:              pass  # multiplayer; ignored in PR 2b

    def GetWorldLocation(self) -> TGPoint3:
        """Current in-flight position. Mirrors ObjectClass.GetWorldLocation()
        so a Torpedo can serve as its own GetNode() anchor for
        TGSoundManager launch sounds (see GetNode below) -- update_all
        replaces `_position` wholesale each tick, so this always reads the
        live value, never a stale snapshot."""
        return self._position

    def GetVelocityTG(self) -> TGPoint3:
        """Current in-flight velocity as a FRESH copy. Mirrors
        ObjectClass.GetVelocityTG() (objects.py:453). The copy is
        load-bearing: SDK EvadeTorps.UpdateTorpInfo:114-115 does
        ``vVelocity = pTorp.GetVelocityTG(); vVelocity.Subtract(pShip...)`` --
        handing back the live vector would let that in-place Subtract corrupt
        the torpedo's real velocity."""
        return TGPoint3(self._velocity.x, self._velocity.y, self._velocity.z)

    def GetNode(self):
        """Weak node handle mirroring ObjectClass.GetNode(), so
        TGSound.AttachToNode(torp.GetNode()) can ride the torpedo the same
        way it rides a ship. BC does exactly this for torpedo launch sounds
        (sdk/Build/scripts/MissionLib.py:3284-3296:
        `pSound.AttachToNode(pTorp.GetNode())`). Weak so a queued launch
        sound never keeps an expired torpedo alive."""
        from engine.appc.objects import _ObjectNodeRef
        return _ObjectNodeRef(self)


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


def get_by_id(obj_id):
    """The in-flight torpedo whose GetObjID() matches, or None.

    Backs App.Torpedo_GetObjectByID (SDK PlainAI/EvadeTorps.py:110 looks up
    each incoming id this way). Tolerates a None id, matching
    ObjectClass_GetObjectByID (see tests/unit/test_object_get_by_id_null.py)."""
    if obj_id is None:
        return None
    for t in _active:
        if t.GetObjID() == obj_id:
            return t
    return None


# ── Incoming-torpedo detection (AIScriptAssist_* backing) ─────────────────────
# Backs the two AIScriptAssist entry points the SDK torpedo-evasion code calls
# (App.AIScriptAssist_TorpIsIncoming / _GetIncomingTorpIDsInSet). The RE'd
# symbol table gives their SIGNATURES but no body:
#   0x006063d0  TorpIsIncoming(PyObject*, float, long, int)  argfmt 'OOfli'
#   0x00473830  GetIncomingTorpIDsInSet(PyObject*, float, int, int)  'OOfii'
# so the metric below is derived from the SDK, not read off the binary --
# flagged inline where it is inference.

def _closing_time(observer, torp):
    """Estimated seconds until `torp` reaches `observer`, or None if it is not
    closing (moving away / parallel).

    INFERENCE (not from the binary): the caller passes a threshold named
    ``fDangerTimeThreshold`` in SECONDS (18.0 in ConditionIncomingTorps,
    3600.0 in PlainAI/EvadeTorps), and the SDK computes exactly this quantity
    downstream -- ``fIncomingSpeed = -relVel . dirToTorp; t = distance /
    fIncomingSpeed`` (AI/PlainAI/EvadeTorps.py:113-120). We reproduce that
    closing-time. The exact formula BC's engine used is unknown; this is the
    only dimensionally-consistent reading of a 'danger *time*' from the
    position + velocity state both entry points are handed."""
    o = observer.GetWorldLocation()
    p = torp.GetWorldLocation()
    d = TGPoint3(p.x - o.x, p.y - o.y, p.z - o.z)
    dist = d.Length()
    if dist < 1e-6:
        return 0.0                       # already on top of us
    rel = torp.GetVelocityTG()
    ov = observer.GetVelocityTG()
    rel = TGPoint3(rel.x - ov.x, rel.y - ov.y, rel.z - ov.z)
    inv = 1.0 / dist
    to_torp = TGPoint3(d.x * inv, d.y * inv, d.z * inv)
    closing = -rel.Dot(to_torp)          # >0 iff the torp is approaching
    if closing <= 1e-6:
        return None
    return dist / closing


def _matches_source(torp, firing_object_id, match_source) -> bool:
    """Firing-object match filter (param 4 / param 5).

    param 5 (``match_source``) = "is the source filter armed"
    (== ``self.sFiringObject is not None``). When it is NOT armed, every torp
    passes. When it IS armed, only torps fired by the object whose id is
    ``firing_object_id`` pass -- the module is "True if a given object has
    incoming torps FROM the specified firing object"
    (ConditionIncomingTorps.py:3-5), and Defense.py:34 passes the ship's
    attack target as that source.

    An armed filter with an unresolved id (== NULL_ID -- a named source that
    has not spawned yet, ConditionIncomingTorps.py:84) matches nothing:
    SetupInitialState:162 declines to count torps in exactly that case."""
    if not match_source:
        return True
    src = torp._source_ship
    if src is None:
        return False
    return src.GetObjID() == firing_object_id


def is_incoming(observer, torp, danger_threshold, firing_object_id,
                match_source) -> bool:
    """True iff `torp` passes the source filter AND will reach `observer`
    within `danger_threshold` seconds. Backs AIScriptAssist_TorpIsIncoming."""
    if not isinstance(torp, Torpedo):
        return False
    if not _matches_source(torp, firing_object_id, match_source):
        return False
    t = _closing_time(observer, torp)
    return t is not None and t <= danger_threshold


def incoming_ids(observer, danger_threshold, firing_object_id, match_source):
    """Object ids of every in-flight torpedo incoming on `observer`, applying
    the source filter. Backs AIScriptAssist_GetIncomingTorpIDsInSet.

    Scope note: BC scopes this to the ship's containing SetClass, but our
    torpedoes live only in the module-level _active registry, not in a set
    (see the linchpin design report). We iterate _active directly; torps from
    a distant set are geometrically far, so the closing-time threshold
    excludes them naturally."""
    return [t.GetObjID() for t in list(_active)
            if is_incoming(observer, t, danger_threshold, firing_object_id,
                           match_source)]


def update_all(dt: float, all_ships, *, ship_instances=None) -> list[tuple]:
    """Advance every active torpedo by dt.  Returns list of
    (torpedo, hit_ship, hit_point, hit_normal) tuples that connected this tick.
    Expired torpedoes (TTL or impact) are removed from _active.

    `ship_instances` is forwarded to combat._resolve_hit_point (the mesh
    trace routes through host_io); when omitted (headless tests, no renderer),
    hit_point degrades to the torpedo's post-advance position and hit_normal
    is None — matching the pre-project behaviour. `hit_normal` is the mesh
    surface normal (a TGPoint3) when the trace succeeds, else None; callers
    forward it to apply_hit so the persistent damage decal can render (a None
    normal suppresses the decal).
    """
    from engine.appc.combat import (sphere_hit, _resolve_hit_point)
    from engine.appc.math import TGPoint3

    hits: list[tuple] = []
    expired: list[Torpedo] = []

    for t in list(_active):
        # 1. Steer if homing within guidance window.
        if t._target_ship is not None and t._age < t._guidance_lifetime:
            _guide(t, dt)
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
                # Cast from OUTSIDE the hull along the travel direction, long
                # enough to cross it. A one-tick segment (prev_pos, seg_len) is
                # too short and, once the torpedo has penetrated, starts inside
                # the mesh — so ray_trace_mesh finds no entry surface and the
                # normal comes back None (suppressing the scorch decal). Backing
                # the origin up by the ship radius and spanning ~2x the radius
                # mirrors how the phaser trace (firing-ship -> target) succeeds.
                if aim_unit is not None:
                    radius = ship.GetRadius() if hasattr(ship, "GetRadius") else 0.0
                    backoff = radius + seg_len
                    ray_origin = TGPoint3(
                        t._position.x - aim_unit.x * backoff,
                        t._position.y - aim_unit.y * backoff,
                        t._position.z - aim_unit.z * backoff,
                    )
                    ray_max = 2.0 * radius + seg_len
                else:
                    ray_origin = prev_pos
                    ray_max = seg_len
                hit_point, hit_normal = _resolve_hit_point(
                    ship_instances=ship_instances, ship=ship,
                    ray_origin=ray_origin,
                    ray_direction=aim_unit,
                    max_dist=ray_max,
                    fallback_point=t._position,
                )
                hits.append((t, ship, hit_point, hit_normal))
                expired.append(t)
                break

    for t in expired:
        expire(t)

    return hits


_LEAD_ACCEL_K = 0.5   # BC _DAT_008887A8 ≈ 0.5 — second-order lead term


def _target_visible(torpedo, target) -> bool:
    """Cloak/visibility check for the last-seen cache (BC 0x005AC450 via
    Guide). Observer is the FIRING ship; headless fixtures without a source
    ship count as visible."""
    src = torpedo._source_ship
    if src is None:
        return True
    try:
        from engine.appc.sensor_detection import can_detect
        return bool(can_detect(src, target))
    except Exception:
        return True


def _guide(torpedo, dt: float) -> None:
    """Torpedo::Guide (0x00578CB0), audited §5.5.
    Order: dead-target ballistic → cloak cache → second-order lead →
    linearly-decaying turn budget → clamped rotation, speed preserved."""
    target = torpedo._target_ship
    if target is None:
        return
    if hasattr(target, "IsDead") and target.IsDead():
        return                       # ballistic; NOT the cloak cache
    speed = torpedo._velocity.Length()
    if speed < 1e-6:
        return
    if _target_visible(torpedo, target):
        pos = target.GetWorldLocation()
        torpedo._last_seen_target_pos = TGPoint3(pos.x, pos.y, pos.z)
        vel = (target.GetVelocityTG()
               if hasattr(target, "GetVelocityTG") else TGPoint3(0, 0, 0))
        if not isinstance(vel, TGPoint3):
            vel = TGPoint3(0.0, 0.0, 0.0)
        to_t = pos - torpedo._position
        t_go = to_t.Length() / speed
        prev_vel = torpedo._last_target_vel
        if isinstance(prev_vel, TGPoint3) and dt > 1e-9:
            acc = TGPoint3((vel.x - prev_vel.x) / dt,
                           (vel.y - prev_vel.y) / dt,
                           (vel.z - prev_vel.z) / dt)
        else:
            acc = TGPoint3(0.0, 0.0, 0.0)
        torpedo._last_target_vel = TGPoint3(vel.x, vel.y, vel.z)
        aim = TGPoint3(
            pos.x + vel.x * t_go + _LEAD_ACCEL_K * acc.x * t_go * t_go,
            pos.y + vel.y * t_go + _LEAD_ACCEL_K * acc.y * t_go * t_go,
            pos.z + vel.z * t_go + _LEAD_ACCEL_K * acc.z * t_go * t_go,
        )
    else:
        aim = torpedo._last_seen_target_pos
        if aim is None:
            return
    to_aim = aim - torpedo._position
    dist = to_aim.Length()
    if dist < 1e-6:
        return
    desired = TGPoint3(to_aim.x / dist, to_aim.y / dist, to_aim.z / dist)
    current = TGPoint3(torpedo._velocity.x / speed,
                       torpedo._velocity.y / speed,
                       torpedo._velocity.z / speed)
    remaining = max(0.0, torpedo._guidance_lifetime - torpedo._age)
    initial = torpedo._guidance_initial if torpedo._guidance_initial > 1e-9 else 1.0
    max_step = (remaining / initial) * torpedo._max_angular_accel * dt
    cos_theta = max(-1.0, min(1.0, current.Dot(desired)))
    theta = math.acos(cos_theta)
    if theta <= max_step or theta < 1e-6:
        new_dir = desired
    else:
        sin_theta = math.sin(theta)
        a = math.sin(theta - max_step) / sin_theta
        b = math.sin(max_step) / sin_theta
        new_dir = TGPoint3(current.x * a + desired.x * b,
                           current.y * a + desired.y * b,
                           current.z * a + desired.z * b)
    torpedo._velocity = new_dir * speed
