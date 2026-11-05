"""ShipSubsystem hierarchy.

Mirrors sdk/Build/scripts/App.py:5578-7000 — runtime instances of the
property templates defined in engine/appc/properties.py.  Properties hold
the design-time data (mass, max condition, position); subsystems hold
the per-ship per-instance state (current condition, firing state, target).

Phase 1 ships rarely create subsystems explicitly — they live behind
``ShipClass.GetTorpedoSystem()`` etc., which return None by default until
``loadspacehelper`` populates them in Phase 2.  These classes exist so
that the few SDK call sites that DO obtain a subsystem (Bridge handlers,
mission scripts wiring weapon-fire events) get a real object with the
expected method surface rather than a NamedStub.
"""

import math as _math

from engine.appc.events import TGEventHandlerObject
from engine.appc.float_range_watcher import FloatRangeWatcher
from engine.appc.math import TGPoint3, TGMatrix3
from engine.core import step_memo
from engine.core.ids import implements
import engine.dev_mode as dev_mode
from engine.appc import ship_death as _ship_death
from engine.appc import passive_weapons
from engine.appc import native_combat
from engine.appc import death_check as _death_check
from engine.appc import effect_queue as _effect_queue
from engine.appc.native_combat import NativeField, NativeRefField


def subsystem_world_position(sub, ship=None):
    """World mount point of a subsystem: ship_loc + R · local_mount.

    Column-vector rotation convention (R · v); NO scale — BC stores mounts
    in world units relative to the ship centre. Returns the ship location if
    the subsystem has no 3D mount, and the origin if no ship is resolvable.

    ``ship`` may be passed explicitly (``SetHull`` attaches the Hull, so its
    ``_climb_to_ship()`` reaches its ship; an unattached root returns None).

    Inside an engine.core.step_memo block (the combat step) each mount is
    computed once: a firing phaser bank asks ~4 times a tick (strip emit
    point, arc test, aim, beam) and the held-weapon pump again, ~100 rebuilds
    of ship pose and articulation a tick at 64 ships. Every call still gets a
    fresh TGPoint3; whatever moves a ship or a part in the step forgets.
    """
    if step_memo.active():
        key = (id(sub), id(ship))
        found = _mounts.get(key)
        if found is None:
            p = _subsystem_world_position(sub, ship)
            found = _mounts[key] = (p.x, p.y, p.z)
        return TGPoint3(found[0], found[1], found[2])
    return _subsystem_world_position(sub, ship)


# (id(sub), id(ship arg)) -> mount (x, y, z), while a step_memo block is open.
_mounts = step_memo.table()


def _subsystem_world_position(sub, ship):
    """The computation itself; see subsystem_world_position."""
    if ship is None:
        ship = sub._climb_to_ship() if hasattr(sub, "_climb_to_ship") else None
    if ship is None or not hasattr(ship, "GetWorldLocation"):
        return TGPoint3(0.0, 0.0, 0.0)
    ship_pos = ship.GetWorldLocation()
    local = sub.GetPosition() if hasattr(sub, "GetPosition") else None
    if not isinstance(local, TGPoint3):
        return TGPoint3(ship_pos.x, ship_pos.y, ship_pos.z)
    # Follow the part this mount sits on, BEFORE rotating into world space:
    # articulation is a body-frame motion, so it composes inside R.
    # Identity for unrigged hulls, body mounts and deflection 0 — so the
    # overwhelming majority of calls are unchanged.
    from engine.appc.articulation import part_transform_point
    from engine.appc import physical_parents
    px, py, pz = part_transform_point(
        ship, (local.x, local.y, local.z),
        prop=physical_parents.property_of(sub))
    offset = TGPoint3(px, py, pz)
    if hasattr(ship, "GetWorldRotation"):
        rot = ship.GetWorldRotation()
        if isinstance(rot, TGMatrix3):
            offset.MultMatrixLeft(rot)   # R · offset (column-vector)
    return TGPoint3(ship_pos.x + offset.x,
                    ship_pos.y + offset.y,
                    ship_pos.z + offset.z)


_RESOLVE = object()


def target_offset_world(target, offset, mount_sub=_RESOLVE):
    """World point for a target-local aim `offset` on `target` -- 0x005852A0:
    target world pos + R·(offset·scale), a subsystem mount's offset first
    carried by the articulated part the mount sits on.

    `offset` is target-local and unscaled: what a subsystem lock hands over
    (`GetPositionTG()`, and the SDK's own
    `SetTargetOffset(pSubsystem.GetPosition())`), or a Manual Aim pick (the
    body point the ray hit on the posed hull, stored as it is).

    Aim points do not follow articulated parts (fire control native only,
    M5; Mark: "we dont need torpedoes to track articulated parts moving mid
    flight"). Only an offset that IS a subsystem's authored mount -- bit for
    bit its `GetPosition()` -- is posed, so a torpedo locked on a raised
    Bird of Prey wingtip flies at where the tip is drawn. Anything else (a
    pick, a stale pick, an NPC offset kept across a re-target, an offset
    within `authored_mount_subsystem`'s 1e-5 of a mount but not on it: M8.5)
    is a plain body-frame xyz, `body_point_world(target, offset)`.

    The Python copy of this transform: in-flight steering
    (`projectiles._steer_point`) and Manual Aim phasers
    (`host_loop._phaser_aim_point`) call it; a tube's aim is native. Its
    native twin is `weapon_geometry.cc` target_offset_world: CHANGE BOTH.

    `mount_sub`: the caller's own `authored_mount_subsystem(target, offset)`
    answer, when it has one (None: no mount) -- in-flight steering asks
    every tick for an offset that never changes, and the attribution scans
    every subsystem.
    """
    from engine.appc.part_severance import authored_mount_subsystem
    point = (offset.x, offset.y, offset.z)
    if mount_sub is _RESOLVE:
        mount_sub = authored_mount_subsystem(target, point)
    if mount_sub is None or not _is_own_mount(mount_sub, point):
        return body_point_world(target, point)
    from engine.appc.articulation import part_transform_point
    from engine.appc import physical_parents
    return body_point_world(target, part_transform_point(
        target, point, prop=physical_parents.property_of(mount_sub)))


def _is_own_mount(sub, point) -> bool:
    """Is `point` `sub`'s own authored mount, `==` per axis (-0.0 matches
    0.0, a NaN never matches)? M8.5: a point merely within 1e-5 of it is a
    plain point."""
    mount = sub.GetPosition()
    return (mount.GetX() == point[0] and mount.GetY() == point[1]
            and mount.GetZ() == point[2])


def body_point_world(target, point):
    """World point for a body-frame `point` (x, y, z) already carried by its
    part: target world pos + R·(point·scale), 0x005852A0's tail. No part
    pose is applied here -- `target_offset_world` posed a mount first; any
    other offset is this point as it is."""
    pos = target.GetWorldLocation()
    px, py, pz = point
    scale = float(target.GetScale()) if hasattr(target, "GetScale") else 1.0
    o = TGPoint3(px * scale, py * scale, pz * scale)
    rot = target.GetWorldRotation() if hasattr(target, "GetWorldRotation") else None
    if isinstance(rot, TGMatrix3):
        o.MultMatrixLeft(rot)
    return TGPoint3(pos.x + o.x, pos.y + o.y, pos.z + o.z)


def _is_offline(sub) -> bool:
    """True when a subsystem is disabled OR destroyed, OR its parent ship is
    out of action (dying/dead — inert coast), OR a radiation outage is live on
    the subsystem itself or the system it belongs to. Single source of truth
    for the capability gates (weapons, engines, sensors, shield generator,
    repair).
    Reads predicates at use-time so repair lifting condition releases the gate
    automatically on the next call."""
    if sub is None:
        return False
    if bool(sub.IsDisabled()) or bool(sub.IsDestroyed()):
        return True
    # Radiation outage (engine/appc/radiation.py): this subsystem, or the
    # system it belongs to. `is True`, never truthiness -- a stubbed fake
    # would answer a truthy _Stub.
    if getattr(sub, "_radiation_out", False) is True:
        return True
    parent = getattr(sub, "_parent_subsystem", None)
    if parent is not None and getattr(parent, "_radiation_out", False) is True:
        return True
    # implements, NOT hasattr. TGObject.__getattr__ vends a truthy _Stub for
    # any unknown name, so hasattr was vacuously True on every subsystem and
    # the guard never guarded anything -- every call fell through to
    # GetParentShip() and a full _out_of_action (two more MRO walks), including
    # for subsystems that do not define the method at all.
    #
    # The `from engine.appc import ship_death` that used to live here ran on
    # every call: 115,279 importlib lookups over 150 ticks at 100 ships. It is
    # at module scope now -- ship_death imports nothing from this module, so
    # there was never a cycle to break.
    if implements(sub, "GetParentShip"):
        if _ship_death._out_of_action(sub.GetParentShip()):
            return True
    return False


def impulse_online_fraction(ies) -> float:
    """Fraction in [0, 1] of a ship's impulse engine pods that are online.

    `ies` is the master ImpulseEngineSubsystem (or None). A pod is offline
    iff _is_offline(pod) (disabled OR destroyed). Returns:
      - 1.0 when ies is None or has no child pods (fallback ships);
      - 0.0 when the master itself is offline;
      - online_pods / total_pods otherwise.
    """
    if ies is None:
        return 1.0
    if _is_offline(ies):
        return 0.0
    n = ies.GetNumChildSubsystems()
    if n == 0:
        return 1.0
    # Plain loop, not sum(genexpr): this walks every pod of every ship every
    # tick, and at that volume the generator frame is not free -- the same
    # change was worth 3x on ids.implements.
    online = 0
    for i in range(n):
        if not _is_offline(ies.GetChildSubsystem(i)):
            online += 1
    return online / float(n)


# BC's shield charge cadence: the tick accumulates elapsed time and only does
# the per-facing charge work once the accumulator reaches this, then resets it.
# Threshold constant at 0x008E529C; see stbc-reference
# spec/ShieldFacingDamage.md section 6.1.
#
# NOTE the spec is graded reviewed-not-tested -- every routine on that path was
# read from the binary, never executed -- so this is a faithful reading, not a
# verified observation. It is adopted because it also matches the 0.5 s beam
# damage pulse the same document describes.
SHIELD_CHARGE_PERIOD_S = 0.5


def impulse_output_fraction(ies) -> float:
    """The scalar BC multiplies an impulse engine's authored limits by.

    Decompiled from stbc.exe's ImpulseEngineSubsystem::GetMaxSpeed
    (FUN_00561230), clean-room 2026-07-13:

        if IsDisabled() or not on: return 0
        cur = base                                 # property maxSpeed, prop+0x4C
        for each child pod:
            share = base / childCount
            if pod not disabled: share *= (1 - pod->conditionRatio)   # pod+0x34
            cur -= share               # a disabled pod costs its ENTIRE share
        if tractorBeam: cur *= (1 - dragFraction)
        clamp cur to [0, base]
        return cur * powerSetting                  # +0x90 — the SLIDER

    Expressed as a fraction of base. Two things to hold on to, both of which
    contradict the binary-pod model this supersedes (see
    docs/superpowers/specs/2026-06-10-impulse-engine-degradation-design.md §3):

      * pods are condition-WEIGHTED — a pod at 50% health costs half its share,
        so partial damage bleeds speed continuously rather than at a cliff;
      * the power term is the requested SLIDER fraction
        (GetPowerPercentageWanted), NOT received/normal power. A ship whose
        reactor is starving it still makes its requested speed. The slider's
        1.25 ceiling is applied AFTER the [0, base] clamp, so overdriving the
        engines really does buy 125% of the authored maximum.

    The tractor-drag term is not modelled: we have no IES->tractor link and no
    drag-fraction field (our tractor drag is positional — engine/appc/tractor.py).

    Returns 1.0 for a None subsystem (bare test ships), 0.0 when the master is
    offline or switched off.
    """
    if ies is None:
        return 1.0
    if _is_offline(ies) or not ies.IsOn():
        return 0.0
    n = ies.GetNumChildSubsystems()
    if n == 0:
        cur = 1.0
    else:
        # BC subtracts each pod's share of the base: share = 1/n, scaled by
        # (1 - conditionRatio) unless the pod is disabled (which costs the whole
        # share). Summing what each pod CONTRIBUTES is the same algebra —
        # cur = (1/n) * sum(disabled ? 0 : conditionRatio) — and lands exactly on
        # 0.0 with every pod out, where the subtraction form leaves float residue.
        contrib = 0.0
        for i in range(n):
            pod = ies.GetChildSubsystem(i)
            if not pod.IsDisabled():
                contrib += pod.GetConditionPercentage()
        cur = contrib / n
    cur = max(0.0, min(1.0, cur))
    return cur * ies.GetPowerPercentageWanted()


def active_impulse_emitters(player) -> list:
    """Active impulse-engine pods as wake emitters.

    Returns ``[{"key": int, "pos": (x, y, z), "size": float}]`` — one entry per
    ONLINE pod (not ``_is_offline``), positioned at its world mount and sized by
    its radius. Empty when there is no player, no impulse subsystem, or the
    master impulse subsystem is offline. When the master is online but exposes
    no child pods, falls back to a single emitter at the master's own mount so
    such ships still trail a wake. Read-only; safe to call every frame.
    """
    if player is None or not hasattr(player, "GetImpulseEngineSubsystem"):
        return []
    ies = player.GetImpulseEngineSubsystem()
    if ies is None or _is_offline(ies):
        return []

    emitters = []
    n = ies.GetNumChildSubsystems() if hasattr(ies, "GetNumChildSubsystems") else 0
    for i in range(n):
        pod = ies.GetChildSubsystem(i)
        if pod is None or _is_offline(pod):
            continue
        wp = subsystem_world_position(pod, player)
        radius = float(pod.GetRadius()) if hasattr(pod, "GetRadius") else 0.0
        # key = id(pod): safe as a per-emitter handle — pods are long-lived
        # per-mission objects, the tracker drops an emitter once its trail
        # empties (a reused id just starts a fresh trail), and reset_sdk_globals
        # clears the tracker on mission swap. Never used to compare across runs.
        emitters.append({"key": id(pod), "pos": (wp.x, wp.y, wp.z), "size": radius})

    if not emitters:
        # No discoverable online pods — fall back to the master mount so the
        # ship still trails a single wake while impulse is online.
        wp = subsystem_world_position(ies, player)
        radius = float(ies.GetRadius()) if hasattr(ies, "GetRadius") else 0.0
        emitters.append({"key": id(ies), "pos": (wp.x, wp.y, wp.z), "size": radius})
    return emitters


# Threshold states for the disabled/destroyed/operational event machine.
_THRESHOLD_OPERATIONAL = 0
_THRESHOLD_DISABLED    = 1
_THRESHOLD_DESTROYED   = 2


class ShipSubsystem(TGEventHandlerObject):
    # Mirrored into the native combat row on every write (native_combat).
    _condition = NativeField(float)
    _max_condition = NativeField(float)
    _disabled_percentage = NativeField(float)
    _destroyed = NativeField(bool)
    # Read with `is True` by _is_offline, so mirrored as identity with True.
    _radiation_out = NativeField(native_combat.IS_TRUE)
    _radius = NativeField(float, key="Subsystem._radius")
    _parent_subsystem = NativeRefField("Subsystem")
    _parent_ship = NativeRefField("Object")
    # Properties are shared templates with no hook at construction: a
    # property gets its row the first time a subsystem references it.
    # A write bumps the part-map generation too: physical_parents.property_of
    # reads it (native_combat.PartKeyRefField).
    _property = native_combat.PartKeyRefField("Property", lazy=True)
    # Weapon-fire inputs (phase 1b): the ordered children (a weapon system's
    # banks / tubes), the mount geometry and the firing arc.
    _children = native_combat.NativeRefList("Subsystem")
    # The mount point part_for_mount keys on: a write bumps the part-map
    # generation (native_combat.PartKeyField).
    _position = native_combat.PartKeyField(native_combat.VEC3)
    _direction = NativeField(native_combat.VEC3)
    _up = NativeField(native_combat.VEC3)
    _right = NativeField(native_combat.VEC3)
    _arc_width_lo = NativeField(float)
    _arc_width_hi = NativeField(float)
    _arc_height_lo = NativeField(float)
    _arc_height_hi = NativeField(float)
    _arc_set = NativeField(bool)
    # Phaser-strip length (K2 reads it for the emitter position).
    _length = NativeField(float)
    # A phaser bank's pulse damage and R_hit (K2 applies the pulse in the
    # walk: native damage Task 4), copied from its property.
    _max_damage = NativeField(float)
    _max_damage_distance = NativeField(float)
    _damage_radius_factor = NativeField(float)
    # In its bay's repair queue (RepairSubsystem._queue keeps it, ruling I3):
    # a write below max emits REPAIR_ADD only when this is False.
    # Native damage (Task 3) reads these through the mirror too: the
    # membership, the threshold state machine's state, the two flags, and
    # each condition watcher (adopted by CondWatcherField: its check count
    # and committed value).
    _in_repair_queue = NativeField(bool)
    _threshold_state = NativeField(int)
    _invincible = NativeField(bool)
    # GetRepairComplexity, which the native repair piece reads per worked
    # item (subsystem_step.h THE REPAIR PIECE).
    _repair_complexity = NativeField(float)
    _critical = NativeField(bool)
    _combined_watcher = native_combat.CondWatcherField(
        _effect_queue.WATCH_COMBINED)
    _condition_watcher = native_combat.CondWatcherField(
        _effect_queue.WATCH_CONDITION)

    def __init__(self, name: str = ""):
        super().__init__()
        # Registered first, so every field below pushes as it is written.
        native_combat.register(self, "Subsystem")
        self._name = name
        self._property = None
        self._parent_ship = None
        self._parent_subsystem = None
        self._child_subsystem = None
        self._radiation_out = False
        self._in_repair_queue = False
        self._children: list["ShipSubsystem"] = []
        self._condition = 1.0
        self._max_condition = 1.0
        # Lazily-created FloatRangeWatcher on GetConditionPercentage(),
        # handed out by GetCombinedPercentageWatcher() (Bridge/Characters/
        # Brex.py:108 registers hull-status thresholds on it). Lazy so the
        # thousands of subsystems that never hand one out pay nothing.
        self._combined_watcher = None
        # Lazily-created FloatRangeWatcher on GetConditionPercentage(), handed
        # out by GetConditionWatcher(). SEPARATE from _combined_watcher: each
        # consumer registers and removes range checks BY INDEX, so sharing one
        # watcher would let the engineer's status reports and the AI's
        # ConditionSystemBelow disturb each other's registrations.
        self._condition_watcher = None
        self._radius = 0.0
        self._position = TGPoint3(0.0, 0.0, 0.0)
        # Body-space mounting axes — defaults match the SDK convention
        # (firing along +Y, right side along +X, up along +Z).
        # SetProperty mirrors the hardpoint values across when a property
        # is bound (forward=Direction, up=Up, right=up×forward).
        self._direction = TGPoint3(0.0, 1.0, 0.0)
        self._right     = TGPoint3(1.0, 0.0, 0.0)
        self._up        = TGPoint3(0.0, 0.0, 1.0)
        # Arc/damage data mirrored from EnergyWeaponProperty.  Defaults
        # leave the gate fully open so non-arc emitters (torpedo tubes)
        # don't get accidentally restricted.
        import math as _math
        self._arc_width_lo:  float = -_math.pi
        self._arc_width_hi:  float =  _math.pi
        self._arc_height_lo: float = -_math.pi / 2
        self._arc_height_hi: float =  _math.pi / 2
        self._max_damage:          float = 0.0
        self._max_damage_distance: float = 0.0
        # Mirrored from WeaponProperty.SetDamageRadiusFactor.  Used by
        # weapon_splash_radius() to resolve the hit sphere.  0.0 = not set
        # (caller falls back to payload DRF or phaser default 0.15).
        self._damage_radius_factor: float = 0.0
        # Phaser-strip arc radius from Position (0 = point emitter).
        # SDK SetLength: distance from the strip's curvature centre to
        # the rim along the firing direction. See research doc § Bug D.
        self._length:              float = 0.0
        # Phaser-strip lateral dimension perpendicular to Length.
        # Mirrored from EnergyWeaponProperty.SetWidth; distinct from
        # _phaser_width (the beam thickness).
        self._width:               float = 0.0
        # Texture tiles per world unit along the beam (0 = stretch once).
        self._length_texture_tile_per_unit: float = 0.0
        # Phaser-specific beam geometry — mirrored from PhaserProperty.
        # 0 on non-phaser subsystems; descriptor builder gates on these.
        self._phaser_width: float = 0.0
        self._main_radius:  float = 0.0
        self._core_scale:   float = 0.0
        # Phaser beam colours (RGBA tuples).  Neutral defaults are fine
        # because the bank only emits beams when SetProperty has populated
        # them from a PhaserProperty hardpoint.
        self._outer_shell_color: tuple = (1.0, 1.0, 1.0, 1.0)
        self._inner_shell_color: tuple = (1.0, 1.0, 1.0, 1.0)
        self._outer_core_color:  tuple = (1.0, 1.0, 1.0, 1.0)
        self._inner_core_color:  tuple = (1.0, 1.0, 1.0, 1.0)
        self._texture_name: str = ""
        # Prism geometry + taper + scroll — full BC-faithful set.
        self._num_sides: int = 6
        self._taper_radius: float = 0.01
        self._taper_ratio: float = 0.25
        self._taper_min_length: float = 5.0
        self._taper_max_length: float = 30.0
        self._perimeter_tile: float = 1.0
        self._texture_speed: float = 0.0
        # Flag set True only when a property actually supplied typed arc
        # data (EnergyWeaponProperty hierarchy).  Emitters without it
        # (torpedo tubes) fall back to a 90° dot-product cone.
        self._arc_set: bool = False
        # Shared identity fields populated by SetupProperties.
        self._critical: int = 0
        # Default targetable so a subsystem whose hardpoint never set the flag
        # still shows/targets; SetupProperties copies the property's value on
        # top (SubsystemProperty defaults to 1 as well). IsTargetable() reads
        # this field — a hardpoint SetTargetable(0) (e.g. an asteroid's Shield
        # Generator / Power Plant) is what hides a subsystem from the menu.
        self._targetable: int = 1
        self._primary: int = 0
        self._disabled_percentage: float = 0.25
        # Current threshold state; transitions fire ET_SUBSYSTEM_DISABLED /
        # DESTROYED / OPERATIONAL (stock BC posts these from C++
        # ShipSubsystem::SetCondition; EngineerCharacterHandlers +
        # AI Conditions consume them).
        self._threshold_state: int = _THRESHOLD_OPERATIONAL
        # Repair-time divisor mirrored from the hardpoint property
        # (SubsystemProperty.SetRepairComplexity — every stock hardpoint
        # authors it). Higher = slower repair. Default 1.0 = neutral.
        self._repair_complexity: float = 1.0
        # Explicit damage/destroyed flags.  SetDamaged/SetDestroyed let tests
        # and the damage system force these states independently of _condition;
        # the predicate methods also fall back to condition-based derivation so
        # both paths stay consistent (e.g. applying condition damage will also
        # make IsDestroyed() true when condition hits zero).
        self._damaged: bool = False
        self._destroyed: bool = False
        # Per-subsystem invincibility (SDK ShipSubsystem.SetInvincible,
        # App.py:5666-5667). MissionLib.MakeSubsystemsInvincible marks a
        # subsystem (and, recursively, its children) immune so a capture-
        # mission's warp core survives while the rest of the ship is fought
        # down. Real bool — combat.apply_hit gates the per-subsystem hit on it.
        self._invincible: bool = False
        # WeaponsDisplay icon descriptor mirrored from SubsystemProperty.
        # The ShipDisplay panel snapshot reads these without walking back
        # to the property template. Coordinates are pixel-space against
        # the SDK's 640x480 reference; the panel divides at the display
        # boundary. _icon_num == 0 is the "no icon" sentinel (matches the
        # SDK Destroyed-slot fallback in Icons/WeaponIcons.py:55-56) —
        # tractor beams and GenericTemplate emitters set it explicitly so
        # the panel can skip them cleanly.
        self._icon_num: int = 0
        self._icon_position_x_px: float = 0.0
        self._icon_position_y_px: float = 0.0
        self._icon_above_ship: int = 0
        self._indicator_icon_num: int = 0
        self._indicator_icon_position_x_px: float = 0.0
        self._indicator_icon_position_y_px: float = 0.0
        # DamageDisplay panel coord (pixel-space against SDK's 640x480
        # reference). Mirrored from SubsystemProperty.SetPosition2D.
        self._position_2d: tuple = (0.0, 0.0)

    def GetName(self) -> str:
        return self._name

    def SetName(self, name: str) -> None:
        self._name = name

    def GetDisplayName(self) -> str:
        # SDK: Appc.ShipSubsystem_GetDisplayName (App.py:5591) — localized
        # TGString. Our subsystem _names are already the human-readable
        # hardpoint names ("Port Nacelle"), so return _name, matching the
        # ObjectClass.GetDisplayName fallback. Must be defined here (not
        # inherited): ShipSubsystem extends TGEventHandlerObject, not
        # ObjectClass, and TGObject.__getattr__ would vend a _Stub.
        return self._name

    def GetProperty(self):
        return self._property

    def SetProperty(self, prop) -> None:
        self._property = prop
        # Mirror mounting axes + position onto the subsystem so per-emitter
        # spawn position and direction-gating consult the hardpoint values
        # rather than falling through to TGObject's stub catch-all.
        if prop is None:
            return
        if hasattr(prop, "GetPosition"):
            p = prop.GetPosition()
            if isinstance(p, TGPoint3):
                self._position = TGPoint3(p.x, p.y, p.z)
        if hasattr(prop, "GetDirection"):
            d = prop.GetDirection()
            if isinstance(d, TGPoint3):
                self._direction = TGPoint3(d.x, d.y, d.z)
        if hasattr(prop, "GetRight"):
            r = prop.GetRight()
            if isinstance(r, TGPoint3):
                self._right = TGPoint3(r.x, r.y, r.z)
        if hasattr(prop, "GetUp"):
            u = prop.GetUp()
            if isinstance(u, TGPoint3):
                self._up = TGPoint3(u.x, u.y, u.z)
        # hasattr is misleading on TGObject subclasses (fallback __getattr__
        # synthesizes Get* / Set* for any name and the synthesized getter
        # returns None when the key isn't set).  Only mirror when the return
        # value matches the expected shape.
        if hasattr(prop, "GetArcWidthAngles"):
            val = prop.GetArcWidthAngles()
            if isinstance(val, tuple) and len(val) == 2:
                self._arc_width_lo, self._arc_width_hi = float(val[0]), float(val[1])
                self._arc_set = True
        if hasattr(prop, "GetArcHeightAngles"):
            val = prop.GetArcHeightAngles()
            if isinstance(val, tuple) and len(val) == 2:
                self._arc_height_lo, self._arc_height_hi = float(val[0]), float(val[1])
                self._arc_set = True
        if hasattr(prop, "GetMaxDamage"):
            val = prop.GetMaxDamage()
            if isinstance(val, (int, float)):
                self._max_damage = float(val)
        if hasattr(prop, "GetMaxDamageDistance"):
            val = prop.GetMaxDamageDistance()
            if isinstance(val, (int, float)):
                self._max_damage_distance = float(val)
        if hasattr(prop, "GetDamageRadiusFactor"):
            val = prop.GetDamageRadiusFactor()
            if isinstance(val, (int, float)):
                self._damage_radius_factor = float(val)
        if hasattr(prop, "GetLength"):
            val = prop.GetLength()
            if isinstance(val, (int, float)):
                self._length = float(val)
        if hasattr(prop, "GetWidth"):
            val = prop.GetWidth()
            if isinstance(val, (int, float)):
                self._width = float(val)
        if hasattr(prop, "GetLengthTextureTilePerUnit"):
            val = prop.GetLengthTextureTilePerUnit()
            if isinstance(val, (int, float)):
                self._length_texture_tile_per_unit = float(val)
        # Phaser-specific fields.  The typed getters live on PhaserProperty
        # (not the EnergyWeaponProperty base) so isinstance-check by
        # return-value type — non-phaser properties' data-bag fallback
        # returns None.
        if hasattr(prop, "GetPhaserWidth"):
            v = prop.GetPhaserWidth()
            if isinstance(v, (int, float)): self._phaser_width = float(v)
        if hasattr(prop, "GetMainRadius"):
            v = prop.GetMainRadius()
            if isinstance(v, (int, float)): self._main_radius = float(v)
        if hasattr(prop, "GetCoreScale"):
            v = prop.GetCoreScale()
            if isinstance(v, (int, float)): self._core_scale = float(v)
        for getter, attr in (
            ("GetOuterShellColor", "_outer_shell_color"),
            ("GetInnerShellColor", "_inner_shell_color"),
            ("GetOuterCoreColor",  "_outer_core_color"),
            ("GetInnerCoreColor",  "_inner_core_color"),
        ):
            if hasattr(prop, getter):
                v = getattr(prop, getter)()
                if isinstance(v, tuple) and len(v) == 4:
                    setattr(self, attr, v)
        if hasattr(prop, "GetTextureName"):
            v = prop.GetTextureName()
            if isinstance(v, str):
                self._texture_name = v
        for getter, attr in (
            ("GetNumSides",       "_num_sides"),
            ("GetTaperRadius",    "_taper_radius"),
            ("GetTaperRatio",     "_taper_ratio"),
            ("GetTaperMinLength", "_taper_min_length"),
            ("GetTaperMaxLength", "_taper_max_length"),
            ("GetPerimeterTile",  "_perimeter_tile"),
            ("GetTextureSpeed",   "_texture_speed"),
        ):
            if hasattr(prop, getter):
                v = getattr(prop, getter)()
                if isinstance(v, (int, float)):
                    setattr(self, attr,
                             int(v) if attr == "_num_sides" else float(v))
        # WeaponsDisplay icon descriptor — typed on SubsystemProperty;
        # the data-bag stubs on bare TGObject return non-int garbage so
        # gate on isinstance to keep stubs from poisoning the mirror.
        for getter, attr, coerce in (
            ("GetIconNum",                  "_icon_num",                       int),
            ("GetIconPositionX",            "_icon_position_x_px",             float),
            ("GetIconPositionY",            "_icon_position_y_px",             float),
            ("IsIconAboveShip",             "_icon_above_ship",                int),
            ("GetIndicatorIconNum",         "_indicator_icon_num",             int),
            ("GetIndicatorIconPositionX",   "_indicator_icon_position_x_px",   float),
            ("GetIndicatorIconPositionY",   "_indicator_icon_position_y_px",   float),
        ):
            if hasattr(prop, getter):
                v = getattr(prop, getter)()
                if isinstance(v, (int, float)):
                    setattr(self, attr, coerce(v))
        # DamageDisplay placement — typed on SubsystemProperty,
        # returned as a (x, y) tuple. Same defensive isinstance gate as
        # the icon mirror above so data-bag stubs don't poison the value.
        if hasattr(prop, "GetPosition2D"):
            v = prop.GetPosition2D()
            if (isinstance(v, tuple) and len(v) == 2
                and all(isinstance(c, (int, float)) for c in v)):
                self._position_2d = (float(v[0]), float(v[1]))

    def IsTypeOf(self, cls) -> int:
        """SDK class-id check — AI/Preprocessors.py:153:
        `pSystem.IsTypeOf(pExistingSystem.GetObjType())`.

        `cls` is a `CT_*` int type tag (whose registered class is a Property
        class — `CT_WEAPON_SYSTEM` -> `WeaponSystemProperty`, ...), NOT a
        subsystem class, so it must be resolved through the shared
        engine.appc.subsystem_types table before
        testing — a `PhaserSystem`'s own `_property` is a
        `WeaponSystemProperty` template (see ships.py `SetupProperties`),
        never a `PhaserProperty`, so comparing `cls` against `_property`
        directly (the historical implementation) can never answer the
        most-specific CT_* constants correctly.

        `PhaserSystem.IsTypeOf(CT_WEAPON_SYSTEM)` must be 1 (a phaser system
        IS a weapon system); `PhaserSystem.IsTypeOf(CT_TORPEDO_SYSTEM)` must
        be 0. Leaf emitters (PhaserBank/PulseWeapon/TractorBeam/TorpedoTube)
        answer `IsTypeOf(CT_ENERGY_WEAPON)`/`IsTypeOf(CT_WEAPON)` from the
        table too (AI/Preprocessors.py:993 `RateSubsystemForTargeting`,
        loadspacehelper.py:229,242) and, being leaf emitters rather than
        weapon-system containers, correctly answer 0 for
        `IsTypeOf(CT_WEAPON_SYSTEM)`.

        `cls` may be a fall-through stub (e.g. App.CT_UNKNOWN_THING
        returns an App._NamedStub instance), or an int tag with no subsystem
        class behind it; `subsystem_class_for_ct` returns None for both and
        this method answers 0. It also still accepts a Property class passed
        directly, for engine callers that have one to hand.

        No property-based fallback: this is a class-identity check,
        independent of whether SetProperty has ever run — see
        engine.appc.subsystem_types, whose table now covers every CT_*
        constant any real SDK caller passes to a ShipSubsystem.IsTypeOf
        (verified by grep across sdk/Build/scripts/ — task 3b fix).
        """
        from engine.appc.subsystem_types import subsystem_class_for_ct
        target = subsystem_class_for_ct(cls)
        if target is None:
            return 0
        return 1 if isinstance(self, target) else 0

    def GetObjType(self):
        """The subsystem's own most-specific `CT_*` int type tag.

        Returns exactly what `IsTypeOf`/`StartGetSubsystemMatch` accept: the
        SDK round-trips this value straight back into both
        (AI/Preprocessors.py:153, ConditionCriticalSystemBelow.py:76).

        SDK consumers: Conditions/ConditionCriticalSystemBelow.py:76 (one
        child ConditionSystemBelow per critical subsystem, keyed by this) and
        AI/Preprocessors.py:153 (FireScript's weapon-system matching). This
        was implemented nowhere, so it fell through to TGObject.__getattr__'s
        truthy `_Stub`, StartGetSubsystemMatch(stub) hit its `else: return
        iter(())` branch, and the caller matched zero subsystems — silently,
        forever. See engine.appc.subsystem_types for why this needs a shared
        table rather than just returning `type(self)`.
        """
        from engine.appc.subsystem_types import ct_for_subsystem
        return ct_for_subsystem(self)

    def GetParentShip(self):
        """The owning ShipClass, from ANY depth in the subsystem chain.

        ⚠️ CLIMBS. `ShipClass._attach_subsystem` sets `_parent_ship` only on
        TOP-LEVEL subsystems, so an emitter added beneath a weapon system with
        `AddChildSubsystem` has none of its own. Returning that bare field was
        a live FATAL crash:

            ConditionPulseReady.py:161  pEvent.SetSource(pWeapon.GetParentShip())
            ConditionPulseReady.py:172  ShipClass_Cast(pEvent.GetSource())  -> None
            ConditionPulseReady.py:179  pShip.GetPulseWeaponSystem()
            AttributeError: 'NoneType' object has no attribute ...

        — and it unwound straight out of the host frame loop, killing the game
        mid-combat. `pWeapon` there is a pulse-weapon EMITTER, i.e. a child.

        Our own code already knew and routed around it (see
        `weapon_subsystems.CalculateRoughDirection`'s docstring, which says to
        use `_climb_to_ship()` and NOT this). The SDK cannot route around our
        surface: BC's `GetParentShip` answers for any subsystem in the chain,
        so ours must too.
        """
        if self._parent_ship is not None:
            return self._parent_ship
        return self._climb_to_ship()

    def SetParentShip(self, ship) -> None:
        self._parent_ship = ship

    def GetParentSubsystem(self):
        return self._parent_subsystem

    def GetChildSubsystem(self):
        return self._child_subsystem

    def GetCondition(self) -> float:
        return self._condition

    def SetCondition(self, value: float) -> None:
        """Floor at zero. Combat damage routes through here (see
        engine/appc/objects.py). Any condition left below max auto-enqueues
        this subsystem on the owning ship's repair bay — the synchronous
        equivalent of stock's ET_SUBSYSTEM_HIT -> RepairSubsystem::
        HandleHitEvent chain. Below max is damaged however it got there, so a
        raise that stays short of max queues too: a subsystem a script brings
        back from destroyed is repaired the rest of the way (Mark, 2026-10-23).
        AddToRepairList owns all validation (duplicate / destroyed / undamaged
        reject).

        Every condition write, a script's included, is the one write
        (objects.write_condition): a critical subsystem left at zero kills the
        ship and a >0 -> 0 crossing routes the breach / hull cascade, both at
        the tick boundary unless the ship is invincible by then
        (engine/appc/death_check.py, rulings M3, M5)."""
        self._set_condition(value)

    def _set_condition(self, value, killer=None, ship=None) -> None:
        """SetCondition's body. `killer` (the firing ship) and `ship` (whom
        the write is charged to, default the owning ship) come from
        DamageableObject.DamageSystem via objects.write_condition.

        With native combat on the native condition chain stands in
        (native damage Task 3; native_combat.set_condition), else -- or when
        it hands back -- this body, the reference."""
        if native_combat._switch and native_combat.set_condition(
                self, value, killer, ship):
            return
        before = self._condition
        self._condition = max(0.0, float(value))
        self._condition_changed()
        if (not self._in_repair_queue
                and self._condition < self.GetMaxCondition()):
            # Added at delivery (REPAIR_ADD; native damage M2) -- only when
            # not queued already (ruling I3): a bay's own tick of an item it
            # works emits nothing.
            _effect_queue.emit(_effect_queue.REPAIR_ADD, self)
        if self._condition <= 0.0:
            _death_check.note_write(
                ship if ship is not None else self._owning_ship(),
                self, before, killer)

    def SetConditionPercentage(self, fraction) -> None:
        """SDK ShipSubsystem.SetConditionPercentage (App.py:5665): condition =
        `fraction` x GetMaxCondition(), through SetCondition -- the same write
        as weapon damage, so it posts the same subsystem events, enqueues the
        repair and reaches the death check (campaign bug 2, decided
        2026-11-02). GetMaxCondition, not _max_condition, so the value reads
        back through GetConditionPercentage (E3M5's 15% clamp compares it)."""
        self.SetCondition(float(fraction) * self.GetMaxCondition())

    def _auto_enqueue_for_repair(self) -> None:
        ship = self._owning_ship()
        if ship is None:
            return
        try:
            bay = ship.GetRepairSubsystem()
            if bay is not None and hasattr(bay, "AddToRepairList"):
                bay.AddToRepairList(self)
        except Exception as _e:
            dev_mode.log_swallowed("repair auto-enqueue", _e)

    def GetMaxCondition(self) -> float:
        # The property template is the authoritative max-condition, mirroring
        # BC's C++ subsystems which delegate max to their property. This matters
        # when a mission mutates the max AFTER load via the property — e.g. E1M2
        # CreateDebris does pHull.GetProperty().SetMaxCondition(300) then
        # SetCondition(300) to peg an asteroid at full health. Properties are
        # SHARED templates (one per ship class), so per-ship current condition
        # stays in self._condition while the (per-class) max comes from here.
        prop = self._property
        if prop is not None:
            try:
                pm = prop.GetMaxCondition()
            except Exception:
                pm = None
            if pm is not None and float(pm) > 0.0:
                return float(pm)
        return self._max_condition

    def SetMaxCondition(self, value: float) -> None:
        # SDK App.py:5601 — also seed current condition when bumping max from
        # the default so freshly-loaded ships start undamaged.
        v = float(value)
        if self._condition == self._max_condition:
            self._condition = v
        self._max_condition = v
        self._condition_changed()

    def _condition_changed(self) -> None:
        """Push the fresh condition FRACTION into the combined and condition
        watchers (if ever handed out), then advance the disabled/destroyed/
        operational state machine. Called from every _condition/
        _max_condition mutation path — all writes route through SetCondition/
        SetMaxCondition (combat damage in engine/appc/objects.py calls
        SetCondition).

        The state changes at once; what it REPORTS is queued to the tick
        boundary (native damage M2; engine/appc/effect_queue.py, THE DAMAGE
        KINDS): a watcher with checks commits now and queues COND_WATCH, a
        state change queues SUBSYS_EVENT."""
        eq = _effect_queue
        if self._combined_watcher is not None:
            self._combined_watcher._update_queued(
                self.GetConditionPercentage(), self, eq.WATCH_COMBINED)
        if self._condition_watcher is not None:
            self._condition_watcher._update_queued(
                self.GetConditionPercentage(), self, eq.WATCH_CONDITION)
        new_state = self._threshold_state_now()
        old_state = self._threshold_state
        if new_state != old_state:
            self._threshold_state = new_state
            if new_state == _THRESHOLD_DESTROYED:
                eq.emit(eq.SUBSYS_EVENT, self, eq.SUBSYS_DESTROYED)
            elif new_state == _THRESHOLD_DISABLED and old_state == _THRESHOLD_OPERATIONAL:
                eq.emit(eq.SUBSYS_EVENT, self, eq.SUBSYS_DISABLED)
            elif new_state == _THRESHOLD_OPERATIONAL:
                eq.emit(eq.SUBSYS_EVENT, self, eq.SUBSYS_OPERATIONAL)
            # destroyed -> disabled (partial repair from zero) is silent.

    def _deliver_threshold_event(self, which) -> None:
        """SUBSYS_EVENT's delivery: post the threshold event; a destroyed
        subsystem's also queues its internal blast."""
        from engine.appc import effect_queue as eq
        if which == eq.SUBSYS_DESTROYED:
            self._fire_threshold_event("ET_SUBSYSTEM_DESTROYED")
            # SPIKE (damage redesign): the blast, drawn only where it
            # reaches the hull (engine/appc/internal_blast.py).
            try:
                from engine.appc import internal_blast
                internal_blast.queue(self)
            except Exception as _e:
                import engine.dev_mode as _dm
                _dm.log_swallowed("internal blast queue", _e)
        elif which == eq.SUBSYS_DISABLED:
            self._fire_threshold_event("ET_SUBSYSTEM_DISABLED")
        else:
            self._fire_threshold_event("ET_SUBSYSTEM_OPERATIONAL")

    def _threshold_state_now(self) -> int:
        if self.IsDestroyed():
            return _THRESHOLD_DESTROYED
        if self.IsDisabled():
            return _THRESHOLD_DISABLED
        return _THRESHOLD_OPERATIONAL

    def GetConditionPercentage(self) -> float:
        mx = self.GetMaxCondition()
        if mx <= 0:
            return 0.0
        # Clamp: a mission may set condition above the (possibly lowered) max;
        # 100% is the ship's intended full health, never an overflowing bar.
        return max(0.0, min(1.0, self._condition / mx))

    def GetCombinedConditionPercentage(self) -> float:
        # SDK aggregates self + child subsystems; Phase 1 ships have no
        # children so this collapses to the same value.
        return self.GetConditionPercentage()

    def GetDamage(self) -> float:
        return max(0.0, self.GetMaxCondition() - self._condition)

    def GetRepairPointsNeeded(self) -> int:
        return int(max(0.0, self.GetMaxCondition() - self._condition))

    def Repair(self, points) -> None:
        """SDK App.py:5671 — add repair points to condition, clamped to
        [current, max]. Routed through SetCondition so the condition
        watchers and threshold state machine react."""
        if points is None:
            return
        points = float(points)
        if points <= 0.0:
            return
        self.SetCondition(min(self.GetMaxCondition(), self._condition + points))

    def GetRadius(self) -> float:
        return self._radius

    def SetRadius(self, value: float) -> None:
        self._radius = float(value)

    def GetPositionTG(self) -> TGPoint3:
        return TGPoint3(self._position.x, self._position.y, self._position.z)

    def GetPosition(self) -> TGPoint3:
        return self.GetPositionTG()

    def GetDirection(self) -> TGPoint3:
        return TGPoint3(self._direction.x, self._direction.y, self._direction.z)

    def SetDirection(self, v) -> None:
        if isinstance(v, TGPoint3):
            self._direction = TGPoint3(v.x, v.y, v.z)

    def GetRight(self) -> TGPoint3:
        return TGPoint3(self._right.x, self._right.y, self._right.z)

    def SetRight(self, v) -> None:
        if isinstance(v, TGPoint3):
            self._right = TGPoint3(v.x, v.y, v.z)

    def GetUp(self) -> TGPoint3:
        return TGPoint3(self._up.x, self._up.y, self._up.z)

    def SetUp(self, v) -> None:
        if isinstance(v, TGPoint3):
            self._up = TGPoint3(v.x, v.y, v.z)

    # Mirror BC's PhaserBank API names — sdk App.py:6478-6489.
    def GetOrientationForward(self) -> TGPoint3: return self.GetDirection()
    def GetOrientationUp(self)      -> TGPoint3: return self.GetUp()
    def GetOrientationRight(self)   -> TGPoint3: return self.GetRight()

    def GetArcWidthAngles(self) -> tuple:
        return (self._arc_width_lo, self._arc_width_hi)

    def GetArcHeightAngles(self) -> tuple:
        return (self._arc_height_lo, self._arc_height_hi)

    def GetMaxDamage(self) -> float:
        return self._max_damage

    def GetMaxDamageDistance(self) -> float:
        return self._max_damage_distance

    def GetDamageRadiusFactor(self) -> float:
        return self._damage_radius_factor

    def SetDamageRadiusFactor(self, v) -> None:
        self._damage_radius_factor = float(v)

    def GetLength(self) -> float:
        return self._length

    def GetWidth(self) -> float:
        return self._width

    def GetLengthTextureTilePerUnit(self) -> float:
        return self._length_texture_tile_per_unit

    # WeaponsDisplay icon descriptor — mirrored from SubsystemProperty.
    # Returns the SDK-faithful zero/0 defaults on subsystems without a
    # bound property so callers don't need to None-check before reading.
    def GetIconNum(self) -> int:                          return self._icon_num
    def GetIconPositionX(self) -> float:                  return self._icon_position_x_px
    def GetIconPositionY(self) -> float:                  return self._icon_position_y_px
    def IsIconAboveShip(self) -> int:                     return self._icon_above_ship
    def GetIndicatorIconNum(self) -> int:                 return self._indicator_icon_num
    def GetIndicatorIconPositionX(self) -> float:         return self._indicator_icon_position_x_px
    def GetIndicatorIconPositionY(self) -> float:         return self._indicator_icon_position_y_px

    def GetPosition2D(self) -> tuple:
        return self._position_2d

    # Phaser-specific accessors (return defaults on non-phaser subsystems).
    def GetPhaserWidth(self) -> float:        return self._phaser_width
    def GetMainRadius(self) -> float:         return self._main_radius
    def GetCoreScale(self) -> float:          return self._core_scale
    def GetOuterShellColor(self) -> tuple:    return self._outer_shell_color
    def GetInnerShellColor(self) -> tuple:    return self._inner_shell_color
    def GetOuterCoreColor(self) -> tuple:     return self._outer_core_color
    def GetInnerCoreColor(self) -> tuple:     return self._inner_core_color
    def GetTextureName(self) -> str:          return self._texture_name
    def GetNumSides(self) -> int:             return self._num_sides
    def GetTaperRadius(self) -> float:        return self._taper_radius
    def GetTaperRatio(self) -> float:         return self._taper_ratio
    def GetTaperMinLength(self) -> float:     return self._taper_min_length
    def GetTaperMaxLength(self) -> float:     return self._taper_max_length
    def GetPerimeterTile(self) -> float:      return self._perimeter_tile
    def GetTextureSpeed(self) -> float:       return self._texture_speed

    def GetWorldLocation(self) -> TGPoint3:
        # Direct attachment sets _parent_ship; child subsystems (pods/nacelles
        # added via AddChildSubsystem) only have _parent_subsystem, so climb the
        # chain to the ship. Without this, off-centre pods returned the bare
        # local mount near the origin — weapon aim at a locked nacelle fired
        # well off screen even though the reticle (which passes the ship
        # explicitly) located it correctly.
        ship = self._parent_ship
        if ship is None:
            ship = self._climb_to_ship()
        if ship is not None:
            return subsystem_world_position(self, ship)
        return self.GetPositionTG()

    def GetDamagePoint(self) -> TGPoint3:
        return self.GetPositionTG()

    def _climb_to_ship(self):
        """Walk parent-subsystem chain until a ShipClass is found.  Used
        by emitters that need their owning ship for world-space math."""
        # Direct attachment: ShipClass._attach_subsystem set _parent_ship.
        if self._parent_ship is not None:
            return self._parent_ship
        # ⚠️ Reads each ancestor's `_parent_ship` FIELD, never its
        # GetParentShip() — that method now delegates HERE when its own field
        # is None, so calling it would recurse back into this loop. Reading the
        # field is also what makes a malformed (cyclic) chain terminate rather
        # than blow the stack; `seen` bounds it explicitly.
        seen = set()
        node = self.GetParentSubsystem()
        while node is not None and id(node) not in seen:
            seen.add(id(node))
            owner = getattr(node, "_parent_ship", None)
            if owner is not None:
                return owner
            node = node.GetParentSubsystem() if hasattr(node, "GetParentSubsystem") else None
        return None

    def _emitter_world_position(self) -> TGPoint3:
        """World position of this emitter mount: ship_loc + R · local.
        Delegates to the module-level subsystem_world_position helper."""
        return subsystem_world_position(self)

    def _strip_emit_position(self, target_world) -> TGPoint3:
        """Closest point on a phaser-strip arc to ``target_world``.

        Galaxy / Sovereign / etc. phaser banks describe a curved strip,
        not a straight line: the rim lies on a sphere of radius
        ``Length`` around ``Position``, swept across ``ArcWidthAngles``
        around the ``Up`` axis. The beam emerges from whichever point on
        the arc is closest (in angular yaw) to the target.

        Algorithm (see research doc § "Strip emit point algorithm"):

        1. Rotate Position + Forward + Up into world space via the
           ship's body→world rotation.
        2. world_right = world_up × world_forward (right-handed; closes
           the basis used by the arc gate).
        3. Project (target - world_position) onto (forward, right).
        4. yaw = atan2(right_proj, fwd_proj).
        5. Clamp yaw to ``ArcWidthAngles``.
        6. Rodrigues-rotate ``world_forward`` around ``world_up`` by the
           clamped yaw to get the emit direction.
        7. emit = world_position + Length × emit_direction.

        Point emitters (``Length == 0``) collapse to
        ``_emitter_world_position()``.
        """
        center = self._emitter_world_position()
        length = self.GetLength() if hasattr(self, "GetLength") else 0.0
        if length <= 0.0:
            return center
        ship = self._climb_to_ship()
        if ship is None:
            return center
        rot = ship.GetWorldRotation() if hasattr(ship, "GetWorldRotation") else None
        if not isinstance(rot, TGMatrix3):
            return center

        # Body-frame basis rotated into world space.
        world_forward = TGPoint3(self._direction.x, self._direction.y, self._direction.z)
        world_forward.MultMatrixLeft(rot)
        world_up = TGPoint3(self._up.x, self._up.y, self._up.z)
        world_up.MultMatrixLeft(rot)
        # Right = forward × up. Under the right-handed convention (post
        # 2026-06-18 un-mirror) this is R·(forward×up) = R·GetCol(0) = true
        # starboard, matching the arc gate (_emitter_in_arc) so the beam
        # emerges on the same side the gate admits. See docs/superpowers/plans/
        # 2026-06-18-render-handedness-unmirror.md.
        world_right = TGPoint3(
            world_forward.y * world_up.z - world_forward.z * world_up.y,
            world_forward.z * world_up.x - world_forward.x * world_up.z,
            world_forward.x * world_up.y - world_forward.y * world_up.x,
        )

        # Project target offset onto the (forward, right) plane.
        dx = target_world.x - center.x
        dy = target_world.y - center.y
        dz = target_world.z - center.z
        fwd_proj   = dx * world_forward.x + dy * world_forward.y + dz * world_forward.z
        right_proj = dx * world_right.x   + dy * world_right.y   + dz * world_right.z

        # Yaw, clamped to the bank's horizontal arc.
        if fwd_proj == 0.0 and right_proj == 0.0:
            yaw = 0.0
        else:
            yaw = _math.atan2(right_proj, fwd_proj)
        yaw_lo = getattr(self, "_arc_width_lo", -_math.pi)
        yaw_hi = getattr(self, "_arc_width_hi",  _math.pi)
        yaw = max(yaw_lo, min(yaw_hi, yaw))

        # Rotate world_forward toward world_right by yaw, in their (orthonormal)
        # plane: emit = cos(yaw)·forward + sin(yaw)·right. Because yaw was
        # measured as atan2(right_proj, fwd_proj) against the SAME world_right,
        # a +yaw target gives an emit on the +right (target) side — the beam
        # faces the target. (Replaces the old up×forward Rodrigues, whose sin
        # term pointed along -world_right under the right-handed convention.)
        c, s = _math.cos(yaw), _math.sin(yaw)
        emit_dir = TGPoint3(
            world_forward.x * c + world_right.x * s,
            world_forward.y * c + world_right.y * s,
            world_forward.z * c + world_right.z * s,
        )

        return TGPoint3(
            center.x + emit_dir.x * length,
            center.y + emit_dir.y * length,
            center.z + emit_dir.z * length,
        )

    def GetNextTargetableChildSubsystem(self):
        return None

    def GetConditionWatcher(self):
        """FloatRangeWatcher on this subsystem's condition FRACTION (0.0-1.0).

        SDK consumer: Conditions/ConditionSystemBelow.py:94 — the most-used
        condition in the AI (31 call sites). It registers a range check at its
        threshold and reads GetWatchedVariable() for the initial state. This
        returned a hardcoded None, so AddRangeCheck raised inside the condition's
        __init__, ConditionScript swallowed it, and the condition sat at status 0
        forever — the AI never learned that a subsystem had been damaged.
        """
        if self._condition_watcher is None:
            self._condition_watcher = FloatRangeWatcher(
                self.GetConditionPercentage())
        return self._condition_watcher

    def GetCombinedPercentageWatcher(self):
        """FloatRangeWatcher on this subsystem's condition FRACTION
        (GetConditionPercentage). Lazily created, seeded with the current
        fraction so the first mutation is measured from real state.
        SDK consumer: pShip.GetHull().GetCombinedPercentageWatcher()
        (Bridge/Characters/Brex.py:108, EngineerCharacterHandlers.py) —
        but the base-class implementation serves ANY subsystem asked."""
        if self._combined_watcher is None:
            self._combined_watcher = FloatRangeWatcher(
                self.GetConditionPercentage())
        return self._combined_watcher

    def _owning_ship(self):
        """Resolve the ship owning this subsystem. Top-level subsystems have
        _parent_ship set by ShipClass._attach_subsystem; child subsystems
        (AddChildSubsystem) only have _parent_subsystem — walk up."""
        obj, hops = self, 0
        while obj is not None and hops < 16:
            ship = getattr(obj, "_parent_ship", None)
            if ship is not None:
                return ship
            obj = getattr(obj, "_parent_subsystem", None)
            hops += 1
        return None

    def _fire_threshold_event(self, event_attr: str) -> None:
        """Broadcast a threshold event: source=this subsystem, destination=
        owning ship (EngineerCharacterHandlers filters destination against the
        player; AI Conditions match the ship). Raise-safe, same pattern as
        CloakingSubsystem._fire — a missing event manager never breaks
        condition mutation (unit fixtures mutate subsystems with no App)."""
        try:
            import App
            ship = self._owning_ship()
            evt = App.TGEvent_Create()
            evt.SetEventType(getattr(App, event_attr))
            evt.SetSource(self)
            evt.SetDestination(ship if ship is not None else self)
            App.g_kEventManager.AddEvent(evt)
        except Exception as _e:
            dev_mode.log_swallowed("subsystem threshold event", _e)

    # ── Child-subsystem walking ──────────────────────────────────────────────
    # SDK consumers iterate child subsystems via GetNumChildSubsystems +
    # GetChildSubsystem(i) (e.g. E2M2 PrepMarauder, E5M2 CreateGeronimo).
    # Hardpoints register TractorBeamProperty etc. as children of the parent
    # WeaponSystemProperty; SetupProperties Pass 4 materialises live children
    # from those property templates.

    def GetNumChildSubsystems(self) -> int:
        return len(self._children)

    def GetChildSubsystem(self, arg=None):
        if arg is None:
            return None
        if isinstance(arg, int):
            if 0 <= arg < len(self._children):
                return self._children[arg]
            return None
        if isinstance(arg, str):
            for c in self._children:
                if c.GetName() == arg:
                    return c
            return None
        return None

    def AddChildSubsystem(self, sub: "ShipSubsystem") -> None:
        sub._parent_subsystem = self
        self._children.append(sub)
        native_combat.push_field(self, "_children")   # an in-place append
        # A new weapon under a weapon system: the passive weapons walk's cached
        # list for the owning ship is stale (engine/appc/passive_weapons.py).
        # A system not yet attached has no ship; attaching it invalidates.
        ship = self._climb_to_ship()
        if ship is not None:
            passive_weapons.invalidate(ship)
            native_combat.push_mount_order(ship)     # combat._iter_subsystems

    def GetCritical(self) -> int:                       return self._critical
    def SetCritical(self, v) -> None:                   self._critical = int(v)
    def GetTargetable(self) -> int:                     return self._targetable
    def SetTargetable(self, v) -> None:                 self._targetable = int(v)
    def GetPrimary(self) -> int:                        return self._primary
    def SetPrimary(self, v) -> None:                    self._primary = int(v)
    def GetDisabledPercentage(self) -> float:           return self._disabled_percentage
    def SetDisabledPercentage(self, v) -> None:         self._disabled_percentage = float(v)

    def GetRepairComplexity(self) -> float:            return self._repair_complexity
    def SetRepairComplexity(self, v) -> None:
        v = float(v)
        self._repair_complexity = v if v > 0.0 else 1.0

    # ── Runtime predicates consumed by AI/Preprocessors.py ───────────────────
    # SDK App.py:5652-5657 — native methods on ShipSubsystem.  Phase 1 stubs
    # return SDK-faithful defaults; richer hooks (per-subsystem criticality
    # flags, LOS to subsystem position) land alongside the consumers that
    # need them.

    def IsCritical(self) -> int:
        """SDK Preprocessors.py:963 — true when destroying this subsystem
        destroys the ship.  Reflects the `_critical` flag set from hardpoint
        SubsystemProperty data via SetCritical (every hardpoint flags the
        hull and warp core critical).  The death sequence reads this to
        decide whether a zero-condition subsystem kills the ship."""
        return 1 if self._critical else 0

    def IsTargetable(self) -> int:
        """SDK Preprocessors.py:953-954, 829 — AI iterates subsystems and
        only adds those reporting IsTargetable()=1 to the rating list; the
        target-menu builder (RebuildShipMenu) likewise hides untargetable
        subsystems. The flag is copied from the hardpoint property in
        SetupProperties (SubsystemProperty.SetTargetable). An asteroid's
        Shield Generator / Power Plant set SetTargetable(0), so they never
        appear in the target list."""
        return 1 if self._targetable else 0

    def IsDisabled(self) -> int:
        """SDK Preprocessors.py:823, 974 — condition has fallen at or below
        DisabledPercentage × MaxCondition. Mirrors the same heuristic the
        rating loop applies via GetDisabledPercentage() / GetMaxCondition()
        / GetCondition(); kept consistent so callers and raters agree."""
        if self._max_condition <= 0.0:
            return 0
        threshold = self._disabled_percentage * self._max_condition
        return 1 if self._condition <= threshold else 0

    def IsDamaged(self) -> int:
        """Returns 1 if the subsystem has taken any damage (condition below
        max) or the explicit _damaged flag is set, 0 when fully healthy.

        Condition-based derivation: damaged = 0 < condition < max_condition.
        The explicit SetDamaged flag lets tests and the damage system
        force the state without touching condition fields."""
        if self._damaged:
            return 1
        if self._max_condition > 0.0 and 0.0 < self._condition < self._max_condition:
            return 1
        return 0

    def SetDamaged(self, value) -> None:
        """Explicitly mark this subsystem as damaged (or clear the flag)."""
        self._damaged = bool(value)

    def IsDestroyed(self) -> int:
        """Returns 1 if the subsystem is permanently destroyed (condition == 0)
        or the explicit _destroyed flag is set, 0 otherwise."""
        if self._destroyed:
            return 1
        if self._max_condition > 0.0 and self._condition <= 0.0:
            return 1
        return 0

    def SetDestroyed(self, value) -> None:
        """Explicitly mark this subsystem as destroyed (or clear the flag)."""
        self._destroyed = bool(value)

    # Invincibility (SDK ShipSubsystem.SetInvincible, App.py:5666-5667). Real
    # 0/1 getter so combat.apply_hit reads a genuine flag, not a truthy _Stub.
    def IsInvincible(self) -> int:
        return 1 if self._invincible else 0

    def SetInvincible(self, value) -> None:
        self._invincible = bool(value)

    def IsHittableFromLocation(self, vWorldLoc) -> float:
        """SDK Preprocessors.py:980 — `fHittable = pSubsystem.IsHittableFromLocation(pOurShip.GetWorldLocation())`.
        Native Appc returns a scalar (0.0..1.0) reflecting LOS / occlusion
        from the firing ship's location to the subsystem position. Phase 1
        treats every subsystem as fully hittable (no occlusion model);
        real geometry support lands when the renderer carries collision
        meshes."""
        return 1.0


# BC draw modes (ship-subsystems.md:164-189).  Per-class assignment below.
#
# The spec's "tractor = mode 0" decision (docs/superpowers/specs/
# 2026-07-05-power-management-system-design.md §Decisions 2) is SUPERSEDED by
# measured ground truth (q10 — tools/probes/results/q10_battery_drain.txt): the
# manual/UI were right that the tractor pulls from the MAIN battery, but neither
# the RE doc's mode-1 (backup-first) row NOR the mode-0 conduit path describes
# the gameplay draw correctly. The tractor does a DIRECT main-battery steal that
# bypasses the conduit budget entirely and is unscaled by the slider — see
# PSM_DIRECT_MAIN / TractorBeamSystem.DRAWS_DIRECT_FROM_MAIN below.
PSM_MAIN_FIRST = 0
PSM_BACKUP_FIRST = 1
PSM_BACKUP_ONLY = 2
# q10: a dedicated-source consumer that siphons the main battery directly,
# bypassing the per-interval conduit budget and UNSCALED by the power-slider
# percentage (measured 600 flat with sliders 1.25, not 600*1.25). Used by
# TractorBeamSystem via the DRAWS_DIRECT_FROM_MAIN class flag, which is what
# the native pump actually branches on (subsystem_step.h THE POWER PIECE).
PSM_DIRECT_MAIN = 3


class PoweredSubsystem(ShipSubsystem):
    """Powered subsystem — consumes power, has a target power level."""

    # Class constants an instance may override, mirrored for the native
    # power piece (subsystem_step.h THE POWER PIECE; NativeClassDefault: a
    # subclass with its own value declares its own, never a plain attribute).
    POWER_MODE = native_combat.NativeClassDefault(native_combat.INDEX,
                                                  PSM_MAIN_FIRST)
    # q10 (tools/probes/results/q10_battery_drain.txt): a subsystem whose draw
    # is a DIRECT main-battery steal — bypasses the conduit budget and is NOT
    # scaled by _power_percentage_wanted. Only TractorBeamSystem sets this True;
    # every conduit-routed consumer leaves it False and draws by POWER_MODE.
    DRAWS_DIRECT_FROM_MAIN = native_combat.NativeClassDefault(bool, False)

    # Mirrored: the native power piece reads and writes them (subsystem_
    # step.h THE POWER PIECE); K0's holding tractor reads _normal_power and
    # _efficiency (its starvation stop); the motion kernel reads the slider
    # (impulse_output_fraction).
    _is_on = native_combat.NativeField(bool)
    _normal_power = native_combat.NativeField(float)
    _power_percentage_wanted = native_combat.NativeField(float)
    _power_wanted = native_combat.NativeField(float)
    _power_received = native_combat.NativeField(float)
    _efficiency = native_combat.NativeField(float)
    _power_factor = native_combat.NativeField(float)

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._normal_power = 0.0
        self._current_power = 0.0
        # On/off state — TurnOn/TurnOff drive gating in WeaponSystem.StartFiring
        # and the shield-raise pathway.
        #
        # ⚠️ This default does NOT match BC: the original PoweredSubsystem
        # constructor sets m_isOn = 1 (stbc_reference spec/PoweredSubsystem.md).
        # We default OFF because cold phasers/torpedoes at spawn is the
        # live-verified behaviour here (see the NeedPower work), and BC reaches
        # that through the power grid rather than this flag. Subclasses whose
        # BC-faithful state is "on" override it: Sensor, ImpulseEngine,
        # WarpEngine, Repair, and Shield.
        #
        # Do NOT flip this to True to fix a "system X is dead at spawn" bug —
        # that powers weapons up at spawn. Override in the subclass instead.
        self._is_on: bool = False
        self._power_percentage_wanted: float = 1.0   # BC spawns at 100%
        self._power_wanted: float = 0.0              # per-tick demand  (+0x8C)
        self._power_received: float = 0.0            # per-tick receipt (+0x88)
        self._efficiency: float = 1.0                # received/wanted  (+0x94)
        self._power_factor: float = 1.0              # received/(normal*dt) (+0x98)
        self._power_source = None

    def GetNormalPowerPerSecond(self) -> float:
        return self._normal_power

    def SetNormalPowerPerSecond(self, value: float) -> None:
        self._normal_power = float(value)

    def GetPowerPerSecond(self) -> float:
        return self._current_power

    def SetPowerPerSecond(self, value: float) -> None:
        self._current_power = float(value)

    def TurnOn(self) -> None:                              self._is_on = True
    def TurnOff(self) -> None:                             self._is_on = False
    def IsOn(self) -> int:                                 return 1 if self._is_on else 0

    def SetPowerPercentageWanted(self, pct) -> None:
        pct = float(pct)
        if pct < 0.0:
            pct = 0.0
        if pct > 1.25:
            pct = 1.25
        old = self._power_percentage_wanted
        self._power_percentage_wanted = pct
        # BC FUN_00562430: rescale current demand in place.
        if old != 0.0:
            self._power_wanted = self._power_wanted * pct / old
        self._fire("ET_SUBSYSTEM_POWER_CHANGED")

    def GetPowerPercentageWanted(self) -> float:           return self._power_percentage_wanted
    def GetPowerWanted(self) -> float:                     return self._power_wanted
    def SetPowerWanted(self, v) -> None:                   self._power_wanted = float(v)
    def GetNormalPowerWanted(self) -> float:               return self._normal_power
    def GetPowerReceived(self) -> float:                   return self._power_received
    def GetPowerPercentage(self) -> float:                 return self._efficiency
    def GetNormalPowerPercentage(self) -> float:           return self._power_factor
    def SetPowerSource(self, src) -> None:                 self._power_source = src

    def Turn(self, on) -> None:
        if on:
            self.TurnOn()
        else:
            self.TurnOff()

    def _wants_power(self) -> bool:
        return bool(self._is_on)

    # The per-tick draw (the pump's rules for this consumer: not wanting
    # power zeroes it, a free consumer is full function, DRAWS_DIRECT_FROM_
    # MAIN steals, every other draws by its POWER_MODE) is NATIVE ONLY:
    # subsystem_step.h THE POWER PIECE (phase 6 Task 8).



    # ── Subsystem event emission ─────────────────────────────────────────────

    def _fire(self, event_attr: str) -> None:
        """Broadcast a subsystem event with the owning ship as both source AND
        destination — mirrors ship_death._broadcast_destroyed.  Raise-safe so
        a missing event manager never breaks the state machine.

        The destination MUST be the ship: target-scoped method handlers
        (Preprocessors.py) only fire when ``event.GetDestination() is pTarget``.
        Falls back to ``self`` for a parentless subsystem (unit fixtures)."""
        try:
            import App
            ship = self.GetParentShip() if hasattr(self, "GetParentShip") else None
            owner = ship if ship is not None else self
            evt = App.TGEvent_Create()
            evt.SetEventType(getattr(App, event_attr))
            evt.SetSource(owner)
            evt.SetDestination(owner)
            App.g_kEventManager.AddEvent(evt)
        except Exception as _e:
            dev_mode.log_swallowed("subsystem event broadcast", _e)



class HullSubsystem(ShipSubsystem):
    """Live hull state.  Hull isn't a powered subsystem — it just tracks
    condition (max + current) so damage logic can read GetMaxCondition().

    The hull is critical by nature: every ship hardpoint sets
    ``Hull.SetCritical(1)``, and a ship whose hull reaches zero is
    destroyed.  Default ``_critical = 1`` so even a hull built without the
    hardpoint property flow (tests, minimally-constructed ships) still
    triggers the death sequence on hull-zero.  The property flow may
    re-assert this via SetCritical, but never clears it (no hardpoint
    flags the hull non-critical)."""

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._critical = 1


class SensorSubsystem(PoweredSubsystem):
    # Mirrored into the native combat row on every write (native_combat).
    # The two id containers are also mutated IN PLACE: every such site calls
    # native_combat.push_ids (AddProbe, Add/RemoveKnownObject,
    # sensor_contacts.on_exited_set's clear).
    _base_sensor_range = NativeField(float)
    _probe_ids = NativeField(list)
    _known_objects = NativeField(set)

    def __init__(self, name: str = ""):
        super().__init__(name)
        # Sensors are ON during normal operation — unlike weapons (powered only
        # at RED alert) a functioning sensor array is always running; BC only
        # reports IsOn()==0 when the subsystem is destroyed/disabled. The base
        # PoweredSubsystem defaults _is_on False (right for weapons), so override
        # it here. Without this, SDK gates that check pSensors.IsOn() short-
        # circuit: e.g. E1M2's ScanHandler bails to the generic "Scan Area"
        # acknowledgement instead of running the mission scan (nothing in the
        # engine's ship-power path ever turned sensors on).
        self._is_on: bool = True
        self._base_sensor_range: float = 0.0
        self._max_probes: int = 0
        # BC +0xC8 NumProbes (live counter, seeded from MaxProbes) and the
        # +0xAC..+0xBC probe list, which holds OBJECT IDS, not pointers
        # (sensor-subsystem.md; 2026-10-07-sensor-probes-design.md).
        self._num_probes: int = 0
        self._probe_ids: list = []
        # Objects whose existence is known to the sensor system.
        # Populated by the game loop / radar sweep logic.  Default is
        # empty (nothing known), matching the initial unscanned state.
        self._known_objects: set = set()

    def GetBaseSensorRange(self) -> float:           return self._base_sensor_range
    def SetBaseSensorRange(self, v) -> None:         self._base_sensor_range = float(v)
    def GetMaxProbes(self) -> int:                   return self._max_probes
    def SetMaxProbes(self, v) -> None:               self._max_probes = int(v)

    def GetNumProbes(self) -> int:                   return self._num_probes
    def SetNumProbes(self, v) -> None:               self._num_probes = int(v)

    def AddProbe(self, obj_id) -> None:
        """BC AddProbe (@0x00567010): remember a launched probe by object ID."""
        self._probe_ids.append(int(obj_id))
        native_combat.push_ids(self, "_probe_ids", self._probe_ids)

    def probes(self) -> list:
        """The live probes, in launch order. An ID that no longer resolves
        (the object was deleted) is dropped, as BC garbage-collects dead
        probes while walking the list. Fast-exits on an empty list -- this is
        now a per-frame hot path (sensor_detection._live_probes) and the
        common case is zero probes."""
        if not self._probe_ids:
            return []
        from engine.core.ids import get_object_by_id
        live, keep = [], []
        for oid in self._probe_ids:
            obj = get_object_by_id(oid)
            if obj is not None:
                live.append(obj)
                keep.append(oid)
        self._probe_ids = keep
        return live

    def GetIdentificationTime(self) -> float:
        """BC's identification dwell (RE'd: a hard-coded 4.0 s, no setter);
        here the live `identification_time_s` dial."""
        from engine.appc import sensor_dials
        return sensor_dials.get("identification_time_s")

    def IsObjectKnown(self, obj) -> int:
        """Returns 1 if *obj* is in the known-contacts set, 0 otherwise.

        The SDK ShieldsDisplay.SetShipIcon gate (line 329-338) checks this
        before showing a target panel — unknown contacts render no data.
        """
        try:
            return 1 if obj.GetObjID() in self._known_objects else 0
        except Exception:
            return 0

    def AddKnownObject(self, obj) -> None:
        """Register *obj* as a known sensor contact."""
        try:
            self._known_objects.add(obj.GetObjID())
            native_combat.push_ids(self, "_known_objects", self._known_objects)
        except Exception as _e:
            dev_mode.log_swallowed("AddKnownObject", _e)

    def RemoveKnownObject(self, obj) -> None:
        """Remove *obj* from known contacts."""
        try:
            self._known_objects.discard(obj.GetObjID())
            native_combat.push_ids(self, "_known_objects", self._known_objects)
        except Exception as _e:
            dev_mode.log_swallowed("RemoveKnownObject", _e)

    def ScanAllObjects(self):
        """Active area scan (Science menu "Scan Area").

        The SDK's ``ScienceMenuHandlers.Scan`` and ``E1M2.ScanComplete`` do
        ``pSeq = pSensors.ScanAllObjects(); pSeq.Play()`` — E1M2 with no None
        guard — so this must ALWAYS return a real, playable ``TGSequence``.

        The sequence carries a single script action that, when played, arms a
        scan identification for every unknown contact in the scanning ship's
        set, one identification time apart (see
        ``sensor_identification.schedule_area_scan``). Deferring the work into
        the played action matches the SDK contract that playing the sequence *is*
        the scan; it also de-dupes against the passive per-tick sweep."""
        import App
        seq = App.TGSequence_Create()
        ship = self.GetParentShip()
        if ship is None and hasattr(self, "_climb_to_ship"):
            ship = self._climb_to_ship()
        if ship is not None:
            try:
                action = App.TGScriptAction_Create(
                    "engine.appc.sensor_identification",
                    "ScanAllObjectsAction", ship.GetObjID())
                seq.AddAction(action)
            except Exception as _e:
                dev_mode.log_swallowed("ScanAllObjects build", _e)
        return seq

    def IdentifyObject(self, pTarget) -> None:
        """Single-target scan (Science "Scan Object" via
        ``Actions.ShipScriptActions.ScanObject``). BC (RE'd) schedules a
        DEFERRED identification on its player-only contact manager, so this
        arms one identification-time later rather than identifying at once.
        Player-only, like BC's; a no-op on any other ship's sensors, and
        when there is no player."""
        from engine.appc import sensor_contacts
        owner = self._owner_ship()
        if owner is None or owner is not sensor_contacts.current_player():
            return
        sensor_contacts.schedule_scan(pTarget, self.GetIdentificationTime())

    def ForceObjectIdentified(self, pTarget) -> None:
        """Immediate identification (BC @0x005678B0), bypassing the dwell.
        SDK ``HelmMenuHandlers.SetupOrbitMenuFromSet`` uses it so orbitable
        planets are targetable; MissionLib.IdentifyObjects, E3M4 and E4M4 use
        it on mission ships. Player-only, like BC's contact manager (every
        entry point gated on GetParentShip() == GetPlayerShip()): a no-op on
        any other ship's sensors, and when there is no player. All four SDK
        callers pass the player's sensors. None-safe and de-duped (a no-op if
        *pTarget* is None or already known)."""
        from engine.appc import sensor_contacts, sensor_identification
        owner = self._owner_ship()
        if owner is None or owner is not sensor_contacts.current_player():
            return
        sensor_identification._identify_one(self, pTarget)

    # ── Range bands + visibility (BC RE'd: sensor-subsystem.md) ───────────
    def _owner_ship(self):
        ship = self.GetParentShip()
        if ship is None and hasattr(self, "_climb_to_ship"):
            ship = self._climb_to_ship()
        return ship

    def GetSensorRange(self) -> float:
        """BC's GetSensorRange: base x normal-power% x condition%, 0 when
        offline. Delegates to the one rule, sensor_detection.effective_sensor_range."""
        ship = self._owner_ship()
        if ship is None:
            return 0.0
        from engine.appc.sensor_detection import effective_sensor_range
        return float(effective_sensor_range(ship))

    def _band_distance(self, obj):
        """Centre distance owner->obj in GU, or None when not in the same set."""
        ship = self._owner_ship()
        if ship is None or obj is None:
            return None
        pset = ship.GetContainingSet()
        if pset is None or obj.GetContainingSet() is not pset:
            return None
        ox, oy, oz = _get_xyz(ship)
        tx, ty, tz = _get_xyz(obj)
        return ((tx - ox) ** 2 + (ty - oy) ** 2 + (tz - oz) ** 2) ** 0.5

    def _own_band(self, obj, fraction) -> bool:
        """Owner-only band test: centre distance within *fraction* of this
        subsystem's own effective range, same set."""
        d = self._band_distance(obj)
        r = self.GetSensorRange()
        return d is not None and r > 0.0 and d <= r * fraction

    def _probe_band(self, obj, fraction) -> bool:
        """Any live probe, in the owner's set, whose own band covers obj
        (BC: IsObjectNear/IsObjectFar fall back to walking the probe list)."""
        ship = self._owner_ship()
        pset = ship.GetContainingSet() if ship is not None else None
        if pset is None or obj is None or obj.GetContainingSet() is not pset:
            return False
        for probe in self.probes():
            ps = probe.GetSensorSubsystem() if implements(probe, "GetSensorSubsystem") else None
            if (ps is not None and probe.GetContainingSet() is pset
                    and ps._own_band(obj, fraction)):
                return True
        return False

    def IsObjectNear(self, obj) -> int:
        """Within near_fraction (BC: half) of sensor range -- the owner's or
        a live probe's own (sub-project 4). Pure distance."""
        from engine.appc import sensor_dials
        nf = sensor_dials.get("near_fraction")
        return 1 if (self._own_band(obj, nf) or self._probe_band(obj, nf)) else 0

    def IsObjectFar(self, obj) -> int:
        """Within full sensor range -- the owner's or a live probe's own."""
        return 1 if (self._own_band(obj, 1.0) or self._probe_band(obj, 1.0)) else 0

    def IsObjectVisible(self, obj) -> int:
        """BC's IsObjectVisible (@0x005671D0): BC's same-set gate, then the
        one rule, sensor_detection.can_detect -- which carries BC's power,
        cloak, nebula-jam, over-boost, range and memory steps (probes:
        sensor-model sub-project 4) plus our occlusion, nebula-core and
        cloak-contest extensions. BC's target list and radar call this same
        function (RE xrefs 0x00538D86, 0x005443D7), so the SDK's direct
        callers and our list agree by construction
        (2026-10-06-sensor-overboost-memory-design.md). The set gate stays
        here because can_detect's range branch has none: cross-set torpedo
        guidance hands it an offset distance."""
        ship = self._owner_ship()
        if ship is None or obj is None:
            return 0
        pset = ship.GetContainingSet()
        if pset is None or obj.GetContainingSet() is not pset:
            return 0
        from engine.appc.sensor_detection import can_detect
        return 1 if can_detect(ship, obj) else 0


class ImpulseEngineSubsystem(PoweredSubsystem):
    """Live impulse-engine state.  Speed/accel limits come from the
    matching ImpulseEngineProperty template via ShipClass.SetupProperties()."""

    # The authored limits, mirrored for the motion kernel (native motion
    # phase 2): always rebound by the setters below, never mutated. KNOWN,
    # NOT GUARDED: the mirror float()s them, so a string written straight
    # into one mirrors as a number where Python would raise; no engine
    # writer does this (the setters store floats).
    _max_speed = NativeField(float)
    _max_accel = NativeField(float)
    _max_angular_velocity = NativeField(float)
    _max_angular_accel = NativeField(float)

    def __init__(self, name: str = ""):
        super().__init__(name)
        # Engines run from spawn — same rationale as SensorSubsystem above:
        # the PoweredSubsystem off/0.0 default is right for weapons (RED-alert
        # powered), but BC ships fly under engine power from creation, and SDK
        # gates read that state: HelmCharacterHandlers.OrbitPlanet and
        # {Helm,}MenuHandlers.SetCourse divert to the XO "need power to
        # engines" warning when GetPowerPercentageWanted() == 0.0, and
        # WarpPressed blocks warp when the warp engines are not IsOn()
        # (currently deferred in warp_gates for exactly this false-positive).
        self._is_on = True
        self._power_percentage_wanted = 1.0
        self._max_speed = 0.0
        self._max_accel = 0.0
        self._max_angular_velocity = 0.0
        self._max_angular_accel = 0.0

    # ── Authored limits ──────────────────────────────────────────────────────
    # The values the hardpoint wrote (BC: the ImpulseEngineProperty template,
    # prop+0x4C..). NOT BC surface — engine-internal, for the "does this ship
    # have populated limits at all" guards and for readouts that want the
    # ship's nominal figure rather than its damaged one. Everything BC exposes
    # to Python derates these; see impulse_output_fraction.
    def GetAuthoredMaxSpeed(self) -> float:       return self._max_speed
    def GetAuthoredMaxAccel(self) -> float:       return self._max_accel
    def GetAuthoredMaxAngularVelocity(self) -> float:
        return self._max_angular_velocity
    def GetAuthoredMaxAngularAccel(self) -> float:
        return self._max_angular_accel

    def SetMaxSpeed(self, v: float) -> None:  self._max_speed = float(v)
    def SetMaxAccel(self, v: float) -> None:  self._max_accel = float(v)
    def SetMaxAngularVelocity(self, v: float) -> None:
        self._max_angular_velocity = float(v)
    def SetMaxAngularAccel(self, v: float) -> None:
        self._max_angular_accel = float(v)

    # ── Live limits (BC FUN_00561230 and siblings) ───────────────────────────
    # Counter-intuitively, BC's GetMaxSpeed is the LIVE, damage-and-power-
    # adjusted figure — not the authored one. The SDK relies on that: the AI's
    # Intercept/Ram/MoveToObjectSide/FollowWaypoints all command
    # GetImpulseEngineSubsystem().GetMaxSpeed(), so a damaged NPC asks only for
    # the speed it can actually make.
    def GetMaxSpeed(self) -> float:
        return self._max_speed * impulse_output_fraction(self)

    def GetMaxAccel(self) -> float:
        return self._max_accel * impulse_output_fraction(self)

    def GetMaxAngularVelocity(self) -> float:
        return self._max_angular_velocity * impulse_output_fraction(self)

    def GetMaxAngularAccel(self) -> float:
        return self._max_angular_accel * impulse_output_fraction(self)

    # ── Cached live limits (+0xAC..+0xB8) ────────────────────────────────────
    # In BC these four are plain reads of cached floats; the SWIG wrapper for
    # GetCurMaxSpeed (0x0061B640) is literally
    # PyFloat_FromDouble(*(float*)(this + 0xAC)). Their per-tick writer is
    # presumed to be ImpulseEngineSubsystem::Update (~0x005617E0, an address
    # range that holds no functions in our Ghidra dump), so whether the cache
    # equals the live value verbatim or lags it (spool-up) is NOT established —
    # SSDiag.py:114 prints both as "Maximum/current max speed", which implies
    # they can diverge. We model the cache as exact; if a spool-up ever turns
    # up, it belongs here and nowhere else.
    #
    # GetCurMaxSpeed is read by the NPC torpedo preprocessor
    # (AI/Preprocessors.py:523) to weight torp types against how fast the
    # target can run.
    def GetCurMaxSpeed(self) -> float:           return self.GetMaxSpeed()
    def GetCurMaxAccel(self) -> float:           return self.GetMaxAccel()
    def GetCurMaxAngularVelocity(self) -> float: return self.GetMaxAngularVelocity()
    def GetCurMaxAngularAccel(self) -> float:    return self.GetMaxAngularAccel()


class _DewarpDrive:
    """One warp-in slide: exit point -> placement, held at `rotation`."""
    __slots__ = ("start", "end", "rotation", "elapsed")

    def __init__(self, start, end, rotation):
        self.start = start
        self.end = end
        self.rotation = rotation
        self.elapsed = 0.0


class WarpEngineSubsystem(PoweredSubsystem):
    # Warp-state constants from sdk/.../App.py:6700-6707.
    # SDK consumers: WarpSequence.py, mission scripts checking warp transitions.
    WES_NOT_WARPING       = 0
    WES_WARP_INITIATED    = 1
    WES_WARP_BEGINNING    = 2
    WES_WARP_ENDING       = 3
    WES_WARPING           = 4
    WES_DEWARP_INITIATED  = 5
    WES_DEWARP_BEGINNING  = 6
    WES_DEWARP_ENDING     = 7

    # The inbound half of the FSM. Only these states carry a completion
    # deadline: the SDK fires TransitionToState(WES_DEWARP_*) and expects the
    # engine to run the dewarp out (Actions/EffectScriptActions.py:226) — with
    # no completion the ship is stranded mid-warp forever.
    DEWARP_STATES = frozenset(
        (WES_DEWARP_INITIATED, WES_DEWARP_BEGINNING, WES_DEWARP_ENDING))

    # Used when a script transitions to a dewarp state without ever setting a
    # warp effect time (GetWarpEffectTime() == 0.0).
    DEFAULT_DEWARP_SECONDS = 2.0

    # Warp-in slide length (warp-in spec 6.1, "Timing"): 2.0 s from
    # TransitionToState(WES_DEWARP_INITIATED) -- BC's fixed stage length,
    # independent of any warp effect time set on the engine.
    DEWARP_DRIVE_SECONDS = DEFAULT_DEWARP_SECONDS

    # 120 ticks of 1/60 sum to 2.0 - 2e-15: without this slack a 2.0 s span
    # would land one tick late. Shared by the drive and the state transition
    # so a ship stops warping on the same tick it lands.
    _LAND_EPSILON = 1e-9

    def __init__(self, name: str = ""):
        super().__init__(name)
        # Powered from spawn, like ImpulseEngineSubsystem — see the comment
        # there (SDK engines-off gates false-positive on the weapons default).
        self._is_on = True
        self._power_percentage_wanted = 1.0
        self._warp_sequence = None
        self._warp_effect_time = 0.0
        self._warp_state = self.WES_NOT_WARPING
        # Seconds left on an engine-driven dewarp transition; None when no
        # transition is pending. See TransitionToState / tick_transition.
        self._transition_remaining = None
        # Active warp-in slide, or None. See _begin_dewarp_drive.
        self._dewarp_drive = None

    def SetPlacement(self, placement) -> None:
        """The PlacementObject this ship arrives at (warp-in spec 6.1)."""
        self._placement = placement

    def GetPlacement(self):
        return getattr(self, "_placement", None)

    def GetWarpExitLocation(self):
        """Where an arriving ship starts its slide: the placement's location,
        pulled back along the placement's forward (GetCol(1)) by
        slide_radii x the ship's radius. With no placement, the ship itself."""
        from engine.appc import warp_in_dials, warp_state
        ship = self.GetParentShip()
        placement = self.GetPlacement()
        if placement is None:
            return ship.GetWorldLocation()
        loc = placement.GetWorldLocation()
        fwd = placement.GetWorldRotation().GetCol(1)
        d = warp_in_dials.get("slide_radii") * warp_state.warp_in_radius(ship)
        from engine.appc.math import TGPoint3
        return TGPoint3(loc.x - fwd.x * d, loc.y - fwd.y * d, loc.z - fwd.z * d)

    def GetWarpExitRotation(self):
        placement = self.GetPlacement()
        if placement is None:
            return self.GetParentShip().GetWorldRotation()
        return placement.GetWorldRotation()

    def GetWarpSequence(self):
        return self._warp_sequence

    def SetWarpSequence(self, seq) -> None:
        self._warp_sequence = seq
        # Conditions/ConditionWarpingToSet.py:69 (SequenceSet) casts
        # GetDestination() to WarpEngineSubsystem and re-reads
        # GetWarpSequence() off it — the event carries no payload, it is a
        # "something changed, go re-check" ping, so it is posted unguarded.
        # Without this the condition only ever evaluated at construction:
        # correct, but never timely.  See docs/reference/engine/event-emitter-gaps.md #12.
        import App
        evt = App.TGEvent_Create()
        evt.SetEventType(App.ET_SET_WARP_SEQUENCE)
        evt.SetSource(self)
        evt.SetDestination(self)
        App.g_kEventManager.AddEvent(evt)

    def GetWarpEffectTime(self) -> float:
        return self._warp_effect_time

    def SetWarpEffectTime(self, t: float) -> None:
        self._warp_effect_time = float(t)

    def GetWarpState(self) -> int:
        return self._warp_state

    def SetWarpState(self, state) -> None:
        """SDK setter — sets the state outright, with no transition. Clearing
        to WES_NOT_WARPING cancels any pending dewarp completion."""
        self._warp_state = int(state)
        if self._warp_state == self.WES_NOT_WARPING:
            self._transition_remaining = None

    def TransitionToState(self, state) -> None:
        """SDK `WarpEngineSubsystem_TransitionToState` (App.py:6747): enter a
        state that the ENGINE then runs to completion. The SDK's NPC warp-in
        (Actions/EffectScriptActions.py:225-226) sets WES_WARPING and then
        transitions to WES_DEWARP_INITIATED, and never touches the state
        again — so a dewarp transition must land back on WES_NOT_WARPING by
        itself, or the ship stays 'warping' for the rest of the mission."""
        self._warp_state = int(state)
        if self._warp_state in self.DEWARP_STATES:
            t = self.GetWarpEffectTime()
            self._transition_remaining = t if t > 0.0 else self.DEFAULT_DEWARP_SECONDS
        else:
            self._transition_remaining = None
        # Warp-in slide (spec 6.1): only DEWARP_INITIATED starts it, and only
        # with a placement. The SDK sequence's later SetWarpStage calls
        # (DEWARP_ENDING at +1.5 s, NOT_WARPING at +3.0 s) leave it alone.
        if (self._warp_state == self.WES_DEWARP_INITIATED
                and self._dewarp_drive is None
                and self.GetPlacement() is not None):
            self._begin_dewarp_drive()

    # -- Warp-in dewarp drive (warp-in spec 6.1) ----------------------------
    #
    # While driving, the ship's position is lerped (smoothstep) from its warp
    # exit point onto the placement over DEWARP_DRIVE_SECONDS of game time,
    # velocity and spin held at zero and heading held at the placement's. Its
    # motion integrator skips it (warp_state.is_arriving) and its weapons are
    # held silent (weapon_subsystems._dewarp_blocks_fire). Our rule, not
    # recovered BC behaviour: the reference is silent on the slide.

    def is_dewarp_driving(self) -> bool:
        return self._dewarp_drive is not None

    def _begin_dewarp_drive(self) -> None:
        ship = self.GetParentShip()
        if ship is None:
            return
        placement = self.GetPlacement()
        self._dewarp_drive = _DewarpDrive(
            self.GetWarpExitLocation(), placement.GetWorldLocation(),
            placement.GetWorldRotation())
        # K1 reads the slide (FireDumb's hold) from the ship's row.
        native_combat.push_arriving(ship)
        self._hold_ship(ship, self._dewarp_drive.start)
        self._stop_ship_weapons(ship)

    def _hold_ship(self, ship, pos) -> None:
        ship.SetTranslate(pos)
        ship.SetMatrixRotation(self._dewarp_drive.rotation)
        zero = TGPoint3(0.0, 0.0, 0.0)
        ship.SetVelocity(zero)
        ship.SetAngularVelocity(zero)
        ship._current_speed = 0.0
        ship._current_angular_velocity = TGPoint3(0.0, 0.0, 0.0)

    @staticmethod
    def _stop_ship_weapons(ship) -> None:
        """Stop every weapon system already firing when the slide starts --
        the fire gate only blocks NEW fire, and the fire control walk keeps
        firing a latched target (same reasoning as CloakingSubsystem._stop_weapons).
        StopFiring on the system clears the latch and stops each bank."""
        for getter in ("GetPhaserSystem", "GetPulseWeaponSystem",
                       "GetTorpedoSystem", "GetTractorBeamSystem"):
            try:
                fn = getattr(ship, getter, None)
                system = fn() if callable(fn) else None
                if system is not None and implements(system, "StopFiring"):
                    system.StopFiring()
            except Exception as _e:
                dev_mode.log_swallowed("dewarp weapons stop", _e)

    def _end_dewarp_drive(self) -> None:
        self._dewarp_drive = None
        self._placement = None
        native_combat.push_arriving(self.GetParentShip())

    def step_dewarp_drive(self, dt: float) -> None:
        """Advance the warp-in slide by `dt` seconds of game time; on landing
        snap exactly onto the placement and clear it. A dead / dying / setless
        ship is released without being moved. Driven by
        engine.appc.warp_state.tick_warp_states."""
        drive = self._dewarp_drive
        if drive is None:
            return
        ship = self.GetParentShip()
        if (ship is None or ship.IsDead() or ship.IsDying()
                or ship.GetContainingSet() is None):
            self._end_dewarp_drive()
            return
        drive.elapsed += float(dt)
        t = drive.elapsed / self.DEWARP_DRIVE_SECONDS
        if drive.elapsed >= self.DEWARP_DRIVE_SECONDS - self._LAND_EPSILON:
            self._hold_ship(ship, drive.end)
            self._end_dewarp_drive()
            return
        k = t * t * (3.0 - 2.0 * t)
        a, b = drive.start, drive.end
        self._hold_ship(ship, TGPoint3(a.x + (b.x - a.x) * k,
                                       a.y + (b.y - a.y) * k,
                                       a.z + (b.z - a.z) * k))

    def tick_transition(self, dt: float) -> None:
        """Advance a pending dewarp transition; land on WES_NOT_WARPING when it
        expires. Driven by engine.appc.warp_state.tick_warp_states."""
        remaining = self._transition_remaining
        if remaining is None:
            return
        remaining -= float(dt)
        if remaining <= self._LAND_EPSILON:
            self._warp_state = self.WES_NOT_WARPING
            self._transition_remaining = None
        else:
            self._transition_remaining = remaining

    def IsWarping(self) -> bool:
        """True for every state other than WES_NOT_WARPING — the same test BC's
        own scripts make (WarpSequence.py:638, HelmMenuHandlers.py:2465)."""
        return self._warp_state != self.WES_NOT_WARPING


class ShieldSubsystem(PoweredSubsystem):
    """Six-face shield generator.

    Faces indexed by ShieldProperty.FRONT_SHIELDS..RIGHT_SHIELDS (0..5).
    SetMaxShields seeds current to that max when current was 0 — mirrors
    HullSubsystem.SetMaxCondition so freshly-loaded ships start fully shielded.
    """
    FRONT_SHIELDS  = 0
    REAR_SHIELDS   = 1
    TOP_SHIELDS    = 2
    BOTTOM_SHIELDS = 3
    LEFT_SHIELDS   = 4
    RIGHT_SHIELDS  = 5
    NUM_SHIELDS    = 6

    # Every rebind re-pushes the derived has_shields flag; SetMaxShields
    # (the one in-place writer) pushes it itself. The face lists are
    # mirrored for the native hit (native damage Task 3): every in-place
    # writer below pushes the list it wrote, before anything it then posts
    # (damage-map-refresh §6: SetMaxShields, SetCurrentShields, Update's
    # ramp refresh, offline drain and regen, ApplyDamage).
    _max_shields = native_combat.HasShieldsField()
    _current_shields = native_combat.NativeFloatList()
    _ramp_fraction = native_combat.RampField()
    # Mirrored for the native shield piece (phase 6 A1, Task 3;
    # native/src/combat/include/dauntless/combat/subsystem_step.h THE SHIELD
    # PIECE): the regen rates (SetShieldChargePerSecond writes in place and
    # pushes), the cadence carry, and the seven watchers (adopted, so each
    # value and check they take reaches the row).
    _charge_per_second = native_combat.NativeFloatList()
    _charge_accum = NativeField(float)
    _shield_watchers = native_combat.ShieldWatchersField()

    def __init__(self, name: str = ""):
        super().__init__(name)
        # PoweredSubsystem defaults _is_on False, which is right for weapons
        # (cold phasers/torpedoes at spawn are live-verified faithful) but
        # wrong here: BC's PoweredSubsystem constructor sets m_isOn = 1
        # (stbc_reference spec/PoweredSubsystem.md), and its damage path never
        # reads the flag at all — ShipClass::TestHit gates on the facing's
        # charge fraction (> 0.1), and an unpowered generator reaches that by
        # having its charge drained on the 0.5 s tick. Defaulting off here meant
        # every ship spawned at GREEN absorbed nothing until something called
        # SetAlertLevel — which nothing does for NPCs — while the HUD drew a
        # full bar off the seeded face charge.
        self._is_on: bool = True
        self._max_shields:       list[float] = [0.0] * self.NUM_SHIELDS
        self._current_shields:   list[float] = [0.0] * self.NUM_SHIELDS
        self._charge_per_second: list[float] = [0.0] * self.NUM_SHIELDS
        # The face fraction the absorption ramp reads. BC refreshes it on
        # the charge tick, not on every hit or store (ShieldFacingDamage.md
        # §7.2; visible in the captures as the hull share stepping once per
        # ~0.53 s rather than per pulse). None = no tick yet: read live.
        self._ramp_fraction: list = [None] * self.NUM_SHIELDS
        # FloatRangeWatchers handed to SDK consumers. Indices 0..5 are the
        # per-face watchers (Conditions/ConditionSingleShieldBelow.py:110,
        # GetShieldWatcher(side)), each watching its face FRACTION
        # (current / max). Index 6 (NUM_SHIELDS) is BC's COMBINED/overall
        # shields watcher (Bridge/Characters/Brex.py:107 GetShieldWatcher(6)),
        # watching GetShieldPercentage(). All driven from SetCurrentShields
        # and Update.
        self._shield_watchers: list = [
            FloatRangeWatcher() for _ in range(self.NUM_SHIELDS + 1)
        ]
        # Carry for BC's 0.5 s charge cadence (see Update). Declared HERE, not
        # conjured by a `getattr(self, ..., 0.0)` default in Update: an
        # attribute that is absent from a fresh instance's __dict__ is
        # invisible to anything that serialises by walking it, and 39 SDK
        # classes round-trip through __getstate__/__setstate__.
        self._charge_accum: float = 0.0

    def GetShieldWatcher(self, face: int):
        """FloatRangeWatcher on a face's FRACTION for faces 0..5
        (Conditions/ConditionSingleShieldBelow.py:110, eWhichShield);
        index 6 (NUM_SHIELDS) is the COMBINED shields watcher on
        GetShieldPercentage() (Bridge/Characters/Brex.py:107)."""
        return self._shield_watchers[int(face)]

    def GetCombinedPercentageWatcher(self):
        """The COMBINED shields watcher — same object as GetShieldWatcher(6).
        SDK consumer: EngineerCharacterHandlers hull/shield status parity."""
        return self._shield_watchers[self.NUM_SHIELDS]

    def HasShields(self) -> int:
        """True only when at least one face has real shield capacity.

        Unshielded hulls (e.g. asteroids, whose ShieldProperty declares all six
        faces at MaxShields=0) still get a ShieldSubsystem so SDK code can chain
        GetShields() without null-guarding, but they have no actual shields. The
        target list uses this to suppress the shield bar rather than showing the
        100% that GetShieldPercentage() reports for a zero-max shield (that 1.0
        is deliberate — it tells the AI 'shields are not a factor here')."""
        return 1 if sum(self._max_shields) > 0.0 else 0

    def GetMaxShields(self, face: int) -> float:
        return self._max_shields[int(face)]

    def SetMaxShields(self, face: int, value: float) -> None:
        f = int(face)
        v = float(value)
        if self._current_shields[f] == 0.0:
            self._current_shields[f] = v
            native_combat.push_field(self, "_current_shields")
        self._max_shields[f] = v
        native_combat.push_has_shields(self)    # in place: no descriptor sees it
        native_combat.push_field(self, "_max_shields")

    def GetCurrentShields(self, face: int) -> float:
        return self._current_shields[int(face)]

    def SetCurrentShields(self, face: int, value: float) -> None:
        f = int(face)
        self._current_shields[f] = float(value)
        native_combat.push_field(self, "_current_shields")   # in place
        # Keep the face watcher's value fresh so a Condition reading
        # GetWatchedVariable() right after a damage write sees the new
        # fraction (ConditionSingleShieldBelow.py:122 reads it at setup).
        self._shield_watchers[f]._update(self.GetSingleShieldPercentage(f))
        # The combined watcher tracks the same mutation.
        self._shield_watchers[self.NUM_SHIELDS]._update(
            self.GetShieldPercentage())

    def SetCurShields(self, face: int, value: float) -> None:
        """SDK-facing alias of SetCurrentShields (matches Appc method name)."""
        self.SetCurrentShields(face, value)

    def GetCurShields(self, face: int) -> float:
        """SDK-facing alias of GetCurrentShields (matches Appc method name).

        Used by SDK PlainAI/IntelligentCircleObject.py:176-179 for
        shield-bias orbit positioning."""
        return self.GetCurrentShields(face)

    # ── Override TurnOff/TurnOn to carry face-state semantics ────────────────
    # Any path that powers shields down (alert→GREEN, slider→0%, future
    # ShieldsDown SDK handler) must produce identical face state.  Putting
    # the logic here means the caller just calls TurnOff()/TurnOn() and the
    # face drain/raise follows automatically — no duplication in callers.

    # Powering the generator down and back up PRESERVES every face's charge.
    #
    # These two overrides used to drain every face to zero on TurnOff and snap
    # every face to max on TurnOn, both claiming to "mirror BC". Since
    # ShipClass.SetAlertLevel calls them on every transition, that made
    # green -> yellow a free, instant, unlimited shield recharge. Confirmed in
    # play 2026-08-19.
    #
    # BC does the opposite: SaveToStream (0x56AB60) persists m_curShields[i]
    # per facing through a power-down, so the charge survives. The off-state is
    # expressed by short-circuiting the QUERIES — see GetSingleShieldPercentage
    # — rather than by destroying the state.
    #
    # Regen is NOT gated on IsOn (stbc-oracle bible §5.3 S5; the native
    # shield piece, subsystem_step.h THE SHIELD PIECE): a powered-down
    # generator keeps regenerating the charge it is preserving.

    def TurnOff(self) -> None:
        """Power down the generator. Face charge is PRESERVED, not drained —
        every consumer sees "no shields" through the percentage queries."""
        super().TurnOff()

    def TurnOn(self) -> None:
        """Power up the generator. Face charge is RESTORED as it was, not
        snapped to max. Refilling is regen's job (the native shield piece,
        subsystem_step.h THE SHIELD PIECE), and waiting for it is the only
        way to get shields back."""
        super().TurnOn()

    def GetNumShields(self) -> int:
        """Facing count — a fixed 6, matching BC.

        Real Appc surface: SWIG binds it at sdk/Build/scripts/App.py:6364
        (`ShieldClass.GetNumShields`). No SDK script calls it, which is why it
        went missing for so long, but our own consumers do.

        It must exist rather than fall through to TGObject.__getattr__: the
        _Stub that returned is TRUTHY and coerces to 0, so a caller writing
        `range(int(shields.GetNumShields()))` iterates nothing and reports an
        empty result with no error. That is what blanked the AI inspector's
        `shield_percent_by_facing` for every ship.
        """
        return self.NUM_SHIELDS

    def GetSingleShieldPercentage(self, face: int) -> float:
        """current/max for the face; 0.0 when max==0 (unshielded face).

        SDK caller MissionLib.IsAnyShieldBreached treats anything <0.05 as
        a breach, so the max==0 case must return 0.0, not raise.

        Returns 0.0 while the generator is OFF, whatever charge is stored.
        This is the query short-circuit that expresses the off-state, now that
        TurnOff preserves the charge instead of destroying it — every consumer
        (the HUD arcs in ui/ship_display_panel, the target list in
        ui/target_list_view, the SDK shield conditions) sees exactly what it
        saw when the faces were zeroed.

        The 0.0 is OUR choice, matching our own prior observable behaviour.
        The clean-room note reads BC's GetShieldPercentage (0x56A540) as
        returning 1.0 here, but it is graded reviewed-not-tested and a 1.0
        would paint FULL shield bars on a ship whose shields are down — the
        exact bug the shields-default-on work had to fix once already. Settle
        it in-game before adopting it.
        """
        f = int(face)
        # NUM_SHIELDS (6) is one past the last face, yet E3M2's CoreDamage
        # (E3M2.py:1389) passes it on every ET_ENVIRONMENT_DAMAGE with shields
        # up -- indexing it crashed the host loop. BC's answer is unmeasured;
        # the SDK author means "overall shields", so read the whole generator.
        if f == self.NUM_SHIELDS:
            return self.GetShieldPercentage() if self.IsOn() else 0.0
        mx = self._max_shields[f]
        if mx == 0.0:
            return 0.0
        if not self.IsOn():
            return 0.0
        return self._current_shields[f] / mx

    def GetShieldPercentage(self) -> float:
        """Aggregate ratio of total current shields to total max,
        across all 6 faces. Returns 1.0 when no face has max set
        (unshielded ship) so SelectTarget rating treats them as
        "shields not a factor" rather than "shields critically low."""
        total_max = sum(self._max_shields)
        if total_max <= 0:
            return 1.0
        # Same off-state short-circuit as GetSingleShieldPercentage, and for
        # the same reason: TurnOff now preserves the stored charge, so the
        # query is what has to report "down". Kept BELOW the unshielded check
        # so an asteroid still reads 1.0 ("shields not a factor") rather than
        # 0.0 ("critically low"), which is what SelectTarget rates on.
        if not self.IsOn():
            return 0.0
        total_cur = sum(self._current_shields)
        return total_cur / total_max

    def GetShieldChargePerSecond(self, face: int) -> float:
        return self._charge_per_second[int(face)]

    def SetShieldChargePerSecond(self, face: int, value: float) -> None:
        self._charge_per_second[int(face)] = float(value)
        native_combat.push_field(self, "_charge_per_second")   # in place

    # ── The per-tick regen is NATIVE ONLY (phase 6 Task 8) ──────────────
    # native/src/combat/include/dauntless/combat/subsystem_step.h THE SHIELD
    # PIECE is the one implementation (the Python Update was deleted). What
    # it does, and the evidence for it:
    # * BC's 0.5 s charge cadence: ShieldClass's tick (0x0056A230, vtable
    #   slot 25) accumulates elapsed time into +0x154 and does the per-face
    #   charge work once the accumulator reaches 0.5 (0x008E529C), resetting
    #   it unconditionally (stbc-reference spec/ShieldFacingDamage.md §6.1);
    #   the rate is per second against the accumulated dt.
    # * The charge tick refreshes `_ramp_fraction` (ApplyDamage's fraction).
    # * Disabled or destroyed (_is_offline): every face drops to zero and
    #   stays there until repaired (stbc-oracle bible §5.3 S6).
    # * No alert-level, IsOn or power-setting gate on regen (bible §5.3 S5:
    #   9.2-9.5/s at red, yellow and green alike, and at 50 % power).
    # * Each face watcher is fed its fraction, then the combined watcher
    #   (Conditions/ConditionSingleShieldBelow.py's crossings).

    def ApplyDamage(self, face: int, amount: float) -> float:
        """Absorb a hit on the face; return what reaches the hull.

        Not a strict cascade. BC's shield branch (clean-room
        ShieldFacingDamage.md §3.3, `ShipClass::ApplyWeaponHit`) computes a
        pass-through fraction `b` from the face's fraction `f` BEFORE the hit:

            f ≥ 0.6        b = 0
            0.1 < f < 0.6  b = 0.6 · (1 − 2·(f − 0.1))   (linear, 0 → 0.6)
            f ≤ 0.1        the face is bypassed: everything reaches the hull

        the face absorbs the complement `(1 − b)·D`, and if that drives it
        below zero the overdraw is added to the bleed. Measured on the
        original exe (stbc-oracle bible §5.2, 350 hits pooled): hull share
        0 at f ≥ 0.6, 0.20 at 0.40–0.45, 0.49 at 0.15–0.20, and 1.00 below
        0.1. A front face
        preset to 50 % passes 39 % of a Kessok volley; at 25 %, 75 % (S3).

        Two things the capture shows that the spec text does not: below
        f = 0.1 the face is BYPASSED — `phaser_high_front_57_face25` holds
        the face at 641 of 8000 (f = 0.08) while every pulse goes whole to
        the hull, so the spec's `b = 0.6 at f ≤ 0.1` is not what the exe
        does; and the fraction is the one refreshed on the charge tick
        (`_ramp_fraction`), which is why the hull share steps once per
        ~0.53 s and not per pulse.

        Does not trigger regen, fire events, or mutate any other face.
        """
        f = int(face)
        amt = float(amount)
        cur = self._current_shields[f]
        mx = self._max_shields[f]
        if mx <= 0.0 or cur <= 0.0:
            return amt
        frac = self._ramp_fraction[f]
        if frac is None:
            frac = cur / mx
        if frac <= 0.1:
            return amt                              # bypassed entirely
        if frac >= 0.6:
            b = 0.0
        else:
            b = 0.6 * (1.0 - 2.0 * (frac - 0.1))
        new = cur - (1.0 - b) * amt
        if new >= 0.0:
            self._current_shields[f] = new
            native_combat.push_field(self, "_current_shields")   # in place
            return b * amt
        self._current_shields[f] = 0.0
        native_combat.push_field(self, "_current_shields")       # in place
        return b * amt - new


class PowerSubsystem(ShipSubsystem):
    """Power plant — drives the ship's energy budget.

    Inherits ShipSubsystem (not PoweredSubsystem) to match SDK
    App.py:5710 where PowerSubsystem inherits ShipSubsystem directly.
    It generates power rather than consuming it.

    Three pools mirror Appc (App.py:5739-5754):

    * **available** — per-interval conduit-budget sum (budget-at-interval-start),
      refilled each tick.  Consumers draw against conduit counters.
    * **main battery** — capped reserve (PowerProperty.MainBatteryLimit)
      that absorbs surplus and surrenders it when available runs out.
    * **backup battery** — emergency reserve drained only via
      StealPowerFromReserve (backup-only path).

    StealPower / StealPowerFromReserve are SDK API surface for direct
    reservoir drains (main-only / backup-only, return amount taken, float
    0.0 falsy).  Engine has no callers — SDK scripts and tests only.
    """
    # Mirrored for the native power piece (subsystem_step.h THE POWER
    # PIECE), which writes them back through its C applier.
    _available_power = NativeField(float)
    _main_battery_power = NativeField(float)
    _backup_battery_power = NativeField(float)
    _main_conduit_current = NativeField(float)
    _backup_conduit_current = NativeField(float)
    _interval_elapsed = NativeField(float)
    _power_dispensed = NativeField(float)
    _power_wanted_total = NativeField(float)
    _breach_fired = NativeField(bool)
    # Adopted, pushing the plant's watcher state (native_combat).
    _main_battery_watcher = native_combat.PowerWatcherField(0)
    _backup_battery_watcher = native_combat.PowerWatcherField(1)

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._available_power: float = 0.0
        self._main_battery_power: float = 0.0
        self._backup_battery_power: float = 0.0
        # Conduit / interval tracking (Task 2: battery/conduit surface).
        self._main_conduit_current: float = 0.0
        self._backup_conduit_current: float = 0.0
        self._interval_elapsed: float = 0.0
        self._power_dispensed: float = 0.0
        self._power_wanted_total: float = 0.0
        # FloatRangeWatchers handed to Conditions/ConditionPowerBelow.py:44-46;
        # each watches its battery FRACTION (power / limit), driven from Update.
        self._main_battery_watcher = FloatRangeWatcher()
        self._backup_battery_watcher = FloatRangeWatcher()
        # Task 5: breach guard — fires exactly once when the reactor is destroyed.
        # TODO(save): persist _breach_fired in __getstate__/__setstate__ —
        # reload mid-breach re-arms on a dying ship.
        self._breach_fired: bool = False

    def GetAvailablePower(self) -> float:           return self._available_power
    def SetAvailablePower(self, v) -> None:         self._available_power = float(v)
    def GetMainBatteryPower(self) -> float:         return self._main_battery_power
    def SetMainBatteryPower(self, v) -> None:       self._main_battery_power = float(v)
    def GetBackupBatteryPower(self) -> float:       return self._backup_battery_power
    def SetBackupBatteryPower(self, v) -> None:     self._backup_battery_power = float(v)

    def SetProperty(self, prop) -> None:
        """Override to fill batteries to their limits on bind (BC FUN_005636D0).

        Ships spawn with batteries full so they can fire / shield before the
        first per-tick refill.  Delegates the rest of the property-mirror work
        to the ShipSubsystem base implementation."""
        super().SetProperty(prop)
        if prop is not None:
            self._main_battery_power = float(prop.GetMainBatteryLimit() or 0.0)
            self._backup_battery_power = float(prop.GetBackupBatteryLimit() or 0.0)

    def _prop_f(self, getter_name: str) -> float:
        """Read a float from the PowerProperty; returns 0.0 when no property
        is bound or the getter returns None (unset data-bag key)."""
        prop = self.GetProperty()
        if prop is None:
            return 0.0
        if getattr(type(prop), getter_name, None) is None:
            fv = getattr(prop, "_field_value", None)
            if fv is not None:
                return float(fv(getter_name[3:]) or 0.0)
        return float(getattr(prop, getter_name)() or 0.0)

    def GetMainBatteryLimit(self) -> float:
        """Main-battery cap from the PowerProperty (App.py:5743).

        ConditionPowerBelow.py:79 divides GetMainBatteryPower() by this to
        seed its initial state; 0.0 when no property is wired."""
        return self._prop_f("GetMainBatteryLimit")

    def GetBackupBatteryLimit(self) -> float:
        """Backup-battery cap from the PowerProperty (App.py:5744).

        Used by ConditionPowerBelow.py:77 for the reserve-only initial state."""
        return self._prop_f("GetBackupBatteryLimit")

    def GetPowerOutput(self) -> float:
        """Rated output scaled by condition (BC health-scaling asymmetry).

        The EPS plant delivers less power when damaged — scaled by
        GetConditionPercentage() just like GetMainConduitCapacity."""
        return self._prop_f("GetPowerOutput") * self.GetConditionPercentage()

    # Two views of conduit capacity (q10):
    #   * The RATED view (_rated_*) is the physical throughput the EPS conduit
    #     can carry per second: authored capacity, main health-scaled. The
    #     per-interval budget tick uses THIS so the seeded budget is
    #     min(battery, rated*condPct*elapsed) — the battery clamp lives in the
    #     tick's min, not double-applied here.
    #   * The SDK-facing getters (GetMainConduitCapacity /
    #     GetBackupConduitCapacity) additionally clamp by the remaining battery
    #     charge so SDK AdjustPower / IsPowerDraining / PowerDisplay.Update see
    #     the deliverable capacity shrink as a battery runs dry — this is what
    #     drove the original's observed impulse/warp/sensor throttle at ~1% main
    #     (q10 s38->s39).

    def _rated_main_conduit_capacity(self) -> float:
        """Health-scaled main conduit throughput (no battery clamp).  Internal
        per-interval budget input."""
        return self._prop_f("GetMainConduitCapacity") * self.GetConditionPercentage()

    def _rated_backup_conduit_capacity(self) -> float:
        """Backup conduit throughput — NOT health-scaled (BC asymmetry: the
        backup EPS path is hardened).  Internal per-interval budget input."""
        return self._prop_f("GetBackupConduitCapacity")

    def GetMaxMainConduitCapacity(self) -> float:
        """Raw (undamaged, un-clamped) main conduit capacity from the
        PowerProperty — AdjustPower's ceiling reference."""
        return self._prop_f("GetMainConduitCapacity")

    def GetMainConduitCapacity(self) -> float:
        """SDK-facing main conduit capacity: health-scaled AND battery-limited
        (q10). Returns min(main_battery, rated*conditionPct) so AdjustPower
        engages once the main battery runs dry."""
        return min(self._main_battery_power, self._rated_main_conduit_capacity())

    def GetBackupConduitCapacity(self) -> float:
        """SDK-facing backup conduit capacity: battery-limited, NOT health-scaled
        (BC asymmetry). Returns min(backup_battery, rated_backup) (q10)."""
        return min(self._backup_battery_power, self._rated_backup_conduit_capacity())

    def GetPowerDispensed(self) -> float:
        """Total power dispensed to consumers this tick (filled by Task 4)."""
        return self._power_dispensed

    def GetPowerWanted(self) -> float:
        """Sum of power wanted by all consumers this tick (filled by Task 4)."""
        return self._power_wanted_total

    def GetMainBatteryWatcher(self):
        """FloatRangeWatcher on the main-battery FRACTION
        (Conditions/ConditionPowerBelow.py:46)."""
        return self._main_battery_watcher

    def GetBackupBatteryWatcher(self):
        """FloatRangeWatcher on the backup-battery FRACTION
        (Conditions/ConditionPowerBelow.py:44, bReserveOnly path)."""
        return self._backup_battery_watcher

    def AddPower(self, amount) -> None:
        self._available_power += float(amount)

    def DeductPower(self, amount) -> int:
        amt = float(amount)
        if amt > self._available_power:
            return 0
        self._available_power -= amt
        return 1

    def StealPower(self, amount) -> float:
        """Drain up to `amount` from the main battery; return the float amount
        actually taken.  Main-battery-only — does not touch available or backup.

        Returns 0.0 when the main battery is empty (falsy).  Partial steals
        return the amount taken (truthy).  SDK API surface; engine has no
        callers."""
        take = min(float(amount), self._main_battery_power)
        self._main_battery_power -= take
        return take

    def StealPowerFromReserve(self, amount) -> float:
        """Drain up to `amount` from the backup battery; return the float
        amount actually taken.  Backup-battery-only — does not touch available
        or main.  0.0 return is falsy; positive return is truthy."""
        take = min(float(amount), self._backup_battery_power)
        self._backup_battery_power -= take
        return take

    # ── Per-tick flow (native: THE POWER PIECE, below) ───────────────────
    # The interval the native piece reads (pushed as the POWER_INTERVAL
    # global). Between intervals the conduit budgets are unchanged; the
    # watcher fractions are updated every tick so the FloatRangeWatcher fires
    # promptly on StealPower drains between ticks.

    POWER_INTERVAL: float = 1.0   # seconds of game time; BC constant 0x892E20


    def _trigger_breach(self) -> None:
        """Called once when the reactor is destroyed (Task 5 — manual p.16:
        "Reaching 0% causes a warp-core breach and destroys the ship").

        Gate parity with objects.py:_route_zero_crossing: only a TARGETABLE
        power plant may breach.  Inert objects (asteroids) carry a hidden,
        non-targetable Power Plant (SetTargetable(0)); when the death cascade
        zeroes it, it must NOT throw a warp-core explosion with its unique VFX
        (shockwave + wound).  ``_breach_fired`` is still set so we do not
        re-evaluate every tick — the plant is marked "handled" even though
        no breach is emitted.

        Targetable path only: the plant's crossing goes to the one death
        path (controller ruling R9), a ZERO_CROSS checked at the tick
        boundary (engine/appc/death_check.py). There, unless the ship is
        invincible by then:

        * warp_core_breach.arm(ship) — queues the breach VFX (shockwave ring +
          hull wound records), spawned on the next warp_core_breach.advance() (driven
          by the game loop). It deals no damage; the source ship's collateral
          comes from its faithful splash (splash_damage, via ship_death.begin).
        * ship_death.begin(ship) — starts the source ship's own death sequence
          (which also queues its splash damage), unless the ship is already
          dying or dead (e.g. the hull-zero cascade already began it).

        Raise-safe: a missing parent ship or import error must never crash
        the power tick."""
        try:
            from engine.appc.objects import _is_targetable
            if not _is_targetable(self):
                return
            ship = self.GetParentShip()
            if ship is None:
                return
            # The one death path (R9): the plant's crossing, checked at the
            # tick boundary like a write's (death_check.note_breach), which
            # re-reads invincibility there (rulings M1, M5, R5). The plant
            # stays handled (_breach_fired): making the ship vulnerable later
            # kills nothing retroactively (R4).
            from engine.appc import death_check
            death_check.note_breach(ship, self)
        except Exception as _e:
            import engine.dev_mode as dev_mode
            dev_mode.log_swallowed("warp core breach trigger", _e)

    # ── The plant's tick is NATIVE ONLY (phase 6 Task 8) ────────────────
    # subsystem_step.h THE POWER PIECE is the one implementation of the
    # plant's Update and its consumer pump (the Python Update, _update_flow,
    # _pump_consumers, _draw and each consumer's _update_power were
    # deleted). BC's 1 s interval (FUN_005636D0 / 0x892E20): elapsed time
    # accumulates; at POWER_INTERVAL the clock RESETS to 0, the reactor (if
    # not offline) fills main, spills to backup, discards the rest, and the
    # conduit budgets are recomputed UNCONDITIONALLY from the RATED
    # capacities (docs/reference/gameplay/ship-subsystems.md:122-127). The
    # pump runs every tick in attach order (BC draw priority); the battery
    # watchers are fed each tick (Conditions/ConditionPowerBelow.py). A
    # destroyed plant latches _breach_fired and runs _trigger_breach once.








class _RepairQueue(list):
    """A repair bay's queue: a list that keeps each subsystem's
    ``_in_repair_queue`` true exactly while it is a member (ruling I3), on
    every mutation -- the bay's own (add, completion, the priority toggle)
    and a caller's (``repair_ship_fully``'s ``clear``, a test's). A plain
    list member that is not a subsystem is carried unmarked.

    Its owning bay (``_owner``, set by RepairSubsystem) mirrors the queue's
    order and membership (the native repair piece walks it,
    subsystem_step.h THE REPAIR PIECE): every mutation below pushes the
    bay's ``_queue`` again. A queue rebound with some other list is pushed
    by the bay's descriptor, but its own in-place edits are not."""

    def __init__(self, owner=None):
        super().__init__()
        self._owner = owner

    def _pushed(self) -> None:
        owner = self.__dict__.get("_owner")
        if owner is not None:
            native_combat.push_field(owner, "_queue")

    def append(self, sub):
        list.append(self, sub)
        _mark_queued(sub, True)
        self._pushed()

    def insert(self, index, sub):
        list.insert(self, index, sub)
        _mark_queued(sub, True)
        self._pushed()

    def extend(self, subs):
        subs = list(subs)
        list.extend(self, subs)
        for sub in subs:
            _mark_queued(sub, True)
        self._pushed()

    def __iadd__(self, subs):
        self.extend(subs)
        return self

    # The in-place reorderings: membership is unchanged (sort, reverse) or
    # only repeated / emptied (*=), but the mirrored ORDER moves.
    def sort(self, *args, **kwargs):
        try:
            list.sort(self, *args, **kwargs)
        finally:
            self._pushed()

    def reverse(self):
        list.reverse(self)
        self._pushed()

    def __imul__(self, n):
        gone = list(self)
        list.__imul__(self, n)
        self._unmark(gone)
        self._pushed()
        return self

    def clear(self):
        gone = list(self)
        list.clear(self)
        self._unmark(gone)
        self._pushed()

    def pop(self, index=-1):
        sub = list.pop(self, index)
        self._unmark((sub,))
        self._pushed()
        return sub

    def remove(self, sub):
        list.remove(self, sub)
        self._unmark((sub,))
        self._pushed()

    def __delitem__(self, index):
        gone = self[index] if isinstance(index, slice) else (self[index],)
        list.__delitem__(self, index)
        self._unmark(gone)
        self._pushed()

    def __setitem__(self, index, value):
        if isinstance(index, slice):
            gone, value = self[index], list(value)
            new = value
        else:
            gone, new = (self[index],), (value,)
        list.__setitem__(self, index, value)
        self._unmark(gone)
        for sub in new:
            _mark_queued(sub, True)
        self._pushed()

    def discard(self, sub):
        """Remove `sub` by identity, if queued."""
        for i, s in enumerate(self):
            if s is sub:
                del self[i]
                return

    def _unmark(self, gone):
        for sub in gone:
            if not any(s is sub for s in self):
                _mark_queued(sub, False)


def _mark_queued(sub, queued: bool) -> None:
    if isinstance(sub, ShipSubsystem):
        sub._in_repair_queue = queued


def _notify_key(sub):
    """A queued subsystem's key in its bay's ``_cannot_complete_notified``:
    its mirror handle (``_nslot``), which the native repair piece keys the
    set by too (subsystem_step.h THE REPAIR PIECE), else -- an object the
    mirror has no row for -- its id(). A member whose row is dropped (or
    forgotten) changes key to its id(), so it can be told
    ET_REPAIR_CANNOT_BE_COMPLETED once more (accepted: rare, and both
    stages do the same)."""
    h = sub.__dict__.get("_nslot") if hasattr(sub, "__dict__") else None
    return h if type(h) is int else id(sub)


class RepairSubsystem(PoweredSubsystem):
    """Engineering / damage-control subsystem — the per-ship repair queue.

    SDK surface (App.py:6639-6662): AddSubsystem, AddToRepairList,
    IsBeingRepaired, plus the inherited ShipSubsystem/PoweredSubsystem
    methods. Queue semantics + tick formula are RE-verified
    (docs/reference/gameplay/ship-subsystems.md §Repair):
    duplicates rejected, destroyed (condition<=0) rejected, undamaged
    rejected; the first NumRepairTeams entries that are not destroyed are
    "being repaired".
    """

    # Mirrored for the native repair piece (subsystem_step.h THE REPAIR
    # PIECE): the queue's order and membership (pushed by _RepairQueue on
    # every change) and the notified set (the native piece writes it back
    # through its C applier).
    _queue = native_combat.NativeRefList("Subsystem")
    _cannot_complete_notified = native_combat.NotifiedSetField()

    def __init__(self, name: str = ""):
        super().__init__(name)
        # RE layout: +0x9C (isOn) inits to 1 — the bay ticks and draws
        # power without ever being switched on.
        self._is_on = True
        # Ordered repair queue (head = active). A list of subsystem refs that
        # keeps each member's _in_repair_queue (_RepairQueue); identity
        # comparisons throughout (TGObject __eq__ is not trusted).
        self._queue: list = _RepairQueue(self)
        # _notify_key(sub) of each member already notified
        # ET_REPAIR_CANNOT_BE_COMPLETED (destroyed-while-queued fires once,
        # not per tick): its mirror handle.
        self._cannot_complete_notified: set = set()
        # ET_REPAIR_INCREASE_PRIORITY posted with destination=this bay
        # (EngRepairPane click) routes to the toggle via the instance-
        # handler chain. Lazy-guarded: during App's own import the constant
        # isn't there yet; runtime construction always has App loaded.
        try:
            import App
            self.AddPythonFuncHandlerForInstance(
                App.ET_REPAIR_INCREASE_PRIORITY,
                "engine.appc.subsystems.HandleRepairPriorityEvent")
        except Exception as _e:
            dev_mode.log_swallowed("repair priority handler registration", _e)

    # ── Property readers (RepairSubsystemProperty data-bag) ────────────────
    def GetMaxRepairPoints(self) -> float:
        prop = self._property
        if prop is not None:
            v = prop.GetMaxRepairPoints()
            if v is not None:
                return float(v)
        return 0.0

    def GetNumRepairTeams(self) -> int:
        prop = self._property
        if prop is not None:
            v = prop.GetNumRepairTeams()
            if v is not None:
                return int(v)
        return 0

    # ── Queue ───────────────────────────────────────────────────────────────
    def AddToRepairList(self, sub) -> int:
        """Queue a damaged subsystem for repair. Returns 1 on add, 0 on
        reject (None / duplicate / destroyed / undamaged) — mirrors stock
        AddSubsystem which walks the list before insertion and explicitly
        checks condition > 0."""
        if sub is None or sub is True or sub is False:
            return 0
        if not hasattr(sub, "GetCondition"):
            return 0
        if any(s is sub for s in self._queue):
            return 0
        cond = sub.GetCondition()
        if cond <= 0.0:
            return 0
        if cond >= sub.GetMaxCondition():
            return 0
        self._queue.append(sub)
        self._fire_repair_event("ET_ADD_TO_REPAIR_LIST", sub, dest=self)
        return 1

    # SDK exposes both spellings for the same insert (App.py:6660-6661).
    AddSubsystem = AddToRepairList

    def _worked(self) -> list:
        """The items holding a team: the first NumRepairTeams queued items
        that are not destroyed. A destroyed item holds no team and does not
        slow the others (Mark, 2026-10-23); it stays queued, skipped. The
        repair pane draws its REPAIR list the same way."""
        live = [s for s in self._queue if s.GetCondition() > 0.0]
        return live[:self.GetNumRepairTeams()]

    def IsBeingRepaired(self, sub) -> int:
        """True iff sub holds a repair team (see _worked)."""
        return 1 if any(s is sub for s in self._worked()) else 0

    # ── The repair tick is NATIVE ONLY (phase 6 Task 8) ─────────────────
    # subsystem_step.h THE REPAIR PIECE is the one implementation
    # (ship-subsystems.md §Repair; stbc-oracle bible §16, R1-R5 within 3 %):
    #     raw     = MaxRepairPoints * bayConditionPct * dt
    #     perItem = raw / min(liveQueueCount, NumRepairTeams)
    #     gain_i  = perItem / target_i.RepairComplexity
    # Destroyed entries stay queued, fire ET_REPAIR_CANNOT_BE_COMPLETED
    # once, hold no team and are left out of the divisor; completion
    # removes the entry and fires ET_REPAIR_COMPLETED. No power-efficiency
    # term (Mark, 2026-10-23; a starved reactor is unmeasured, bible R6).



    # ── Event emission ──────────────────────────────────────────────────────
    def _fire_repair_event(self, event_attr: str, sub, dest=None) -> None:
        """TGObjPtrEvent with source=sub AND objptr=sub: the SDK
        RepairCompleted handler dereferences BOTH GetSource() and
        GetObjPtr() (EngineerCharacterHandlers.py:294-336). dest defaults
        to the owning ship (player filtering)."""
        try:
            import App
            if dest is None:
                ship = self._owning_ship()
                dest = ship if ship is not None else self
            evt = App.TGObjPtrEvent_Create()
            evt.SetEventType(getattr(App, event_attr))
            evt.SetSource(sub)
            evt.SetObjPtr(sub)
            evt.SetDestination(dest)
            App.g_kEventManager.AddEvent(evt)
        except Exception as _e:
            dev_mode.log_swallowed("repair event broadcast", _e)

    def HandleIncreasePriority(self, sub) -> None:
        """Stock's binary toggle (FUN_00565B50), NOT move-up-one: an entry
        within the first NumRepairTeams nodes (actively repaired) demotes
        to tail; a waiting entry promotes to head; unqueued is a no-op."""
        idx = next((i for i, s in enumerate(self._queue) if s is sub), None)
        if idx is None:
            return
        active = self.IsBeingRepaired(sub)
        del self._queue[idx]
        if active:
            self._queue.append(sub)
        else:
            self._queue.insert(0, sub)


# Default cloak/decloak transition length in seconds.  W5.T2 will overwrite
# the per-instance ``_transition_duration`` from the CloakingSubsystemProperty
# (CloakStrength); this module constant is the fallback for tests and ships
# built without the hardpoint property flow.
CLOAK_TRANSITION_DURATION: float = 4.5


class CloakingSubsystem(PoweredSubsystem):
    """Cloaking device — the four-state cloak/decloak transition machine.

    Driven entirely through the method surface the SDK CloakShip preprocessor
    relies on (sdk/Build/scripts/AI/Preprocessors.py:2068, CheckCloak; also the
    FedAttack / NonFedAttack / CloakAttack doctrines and the CloakShip
    preprocessor):

        pCloak = pOurShip.GetCloakingSubsystem()
        if self.bCloakOn:
            if (not pCloak.IsCloaked()) and (not pCloak.IsCloaking()):
                pCloak.StartCloaking()
        else:
            if pCloak.IsCloaked():
                pCloak.StopCloaking()

    States:

    * ``CLOAK_DECLOAKED``  — fully visible (initial state).
    * ``CLOAK_CLOAKING``   — fading out; transition in progress.
    * ``CLOAK_CLOAKED``    — fully invisible.
    * ``CLOAK_DECLOAKING`` — fading back in; transition in progress.

    The transition timer (``_transition_elapsed``) is advanced by the native
    subsystem stage (subsystem_step.h THE CLOAK PIECE, walked from the game
    loop's subsystem update pass, after the shield and power pieces).  On
    crossing
    ``_transition_duration`` the machine snaps to CLOAKED / DECLOAKED and
    broadcasts the matching completion event (ET_CLOAK_COMPLETED /
    ET_DECLOAK_COMPLETED) via ``App.g_kEventManager`` — the same emission path
    used by ship_death._broadcast_destroyed.

    A disabled / destroyed cloaking device (PoweredSubsystem.IsDisabled() /
    IsDestroyed()) cannot hold or finish a cloak: while disabled it is forced
    back toward DECLOAKED rather than completing a pending cloak.  Logic only —
    the renderer hologram/fade VFX is out of scope for this task.
    """

    CLOAK_DECLOAKED  = 0
    CLOAK_CLOAKING   = 1
    CLOAK_CLOAKED    = 2
    CLOAK_DECLOAKING = 3

    # Mirrored into the native combat row on every write (native_combat).
    _cloak_state = NativeField(int)
    # The native cloak piece's transition clock (subsystem_step.h THE CLOAK
    # PIECE), written back through its C applier.
    _transition_elapsed = NativeField(float)
    _transition_duration = NativeField(float)

    # Cloak runs off the backup grid only — it is locked off the main conduit
    # so cloaking never starves the ship's other systems of main-battery power
    # (docs/reference/gameplay/ship-subsystems.md:185).
    POWER_MODE = native_combat.NativeClassDefault(native_combat.INDEX,
                                                  PSM_BACKUP_ONLY)

    # Power starvation: the cloak runs off the BACKUP battery; when that reserve
    # is exhausted the device can no longer hold the cloak (ship-subsystems.md:
    # 187-189). Gate on the reserve LEVEL, not instantaneous conduit efficiency:
    # efficiency (received/wanted) legitimately dips to 0 whenever the per-second
    # backup-conduit budget is momentarily spent — and for the whole first-second
    # warm-up — which would spuriously force-decloak a ship whose reserve is
    # nearly full (the 2026-07-07 "cloak then immediately decloak" bug). Threshold
    # 0.0 = strictly dry; tune from live play.
    MIN_RESERVE_TO_HOLD_CLOAK = 0.0

    # Reserve drain while cloaked (pw/s), drawn DIRECTLY from the backup battery
    # via StealPowerFromReserve — bypassing the backup-conduit throttle so a
    # sustained cloak genuinely depletes the reserve. Tunable here (no hardpoint
    # edit). Biased to the crossover: a healthy reactor out-refills this and
    # sustains cloak; a damaged one falls behind and the reserve empties, tripping
    # the MIN_RESERVE_TO_HOLD_CLOAK guard. Mark tunes by eye.
    CLOAK_RESERVE_DRAIN_PER_SECOND = native_combat.NativeClassDefault(
        float, 1000.0)
    # The native power piece's reserve snapshot (THE POWER PIECE).
    _backup_reserve = NativeField(float)

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._cloak_state: int = self.CLOAK_DECLOAKED
        self._transition_elapsed: float = 0.0
        # Per-instance so W5.T2 can set it from CloakStrength; defaults to the
        # module constant.
        self._transition_duration: float = CLOAK_TRANSITION_DURATION
        # Backup-battery level snapshotted each frame by the native pump (THE
        # POWER PIECE). The native cloak piece's starvation guard reads this
        # so it keys on true reserve depletion, not per-frame conduit
        # efficiency.
        # inf until the first power pump, so a cold-started cloak is never
        # decloaked before its reserve has even been sampled.
        self._backup_reserve: float = float("inf")

    # ── Intent (called by the SDK CloakShip preprocessor) ────────────────────

    def StartCloaking(self) -> None:
        """Begin cloaking.  No-op if already CLOAKED or CLOAKING; from
        DECLOAKED or mid-DECLOAKING this (re)starts the fade-out and broadcasts
        ET_CLOAK_BEGINNING (BC fires the BEGINNING event at transition start —
        Bridge/PowerDisplay.py:340, E2M0/E2M1)."""
        if self._cloak_state in (self.CLOAK_CLOAKED, self.CLOAK_CLOAKING):
            return
        self._cloak_state = self.CLOAK_CLOAKING
        self._transition_elapsed = 0.0
        self._cloak_dev_log("cloaking")
        self._fire("ET_CLOAK_BEGINNING")
        self._play_cloak_sfx("Cloak")
        # NOTE: cloaking no longer zeroes the shields. BC drops shields on cloak,
        # but a cloaked ship is untargetable so the drop had no combat effect —
        # and it left ships DEFENCELESS on decloak (shields back at zero). Shields
        # now keep their charge and recharge while hidden (see ShieldSubsystem.
        # Update's cloak-regen branch); a decloaking ship comes back protected.
        self._stop_weapons()

    def StopCloaking(self) -> None:
        """Begin decloaking.  No-op if already DECLOAKED or DECLOAKING; from
        CLOAKED or mid-CLOAKING this (re)starts the fade-in and broadcasts
        ET_DECLOAK_BEGINNING (SelectTarget re-rates the contact on this event —
        Preprocessors.py)."""
        if self._cloak_state in (self.CLOAK_DECLOAKED, self.CLOAK_DECLOAKING):
            return
        self._cloak_state = self.CLOAK_DECLOAKING
        self._transition_elapsed = 0.0
        self._cloak_dev_log("decloaking")
        self._fire("ET_DECLOAK_BEGINNING")
        self._play_cloak_sfx("Uncloak")

    def InstantCloak(self) -> None:
        """Jump straight to CLOAKED with no transition; fire ET_CLOAK_COMPLETED.
        No BEGINNING event — there is no transition to begin (matches BC)."""
        self._cloak_state = self.CLOAK_CLOAKED
        self._transition_elapsed = 0.0
        self._fire("ET_CLOAK_COMPLETED")

    def InstantDecloak(self) -> None:
        """Jump straight to DECLOAKED with no transition; fire ET_DECLOAK_COMPLETED."""
        self._cloak_state = self.CLOAK_DECLOAKED
        self._transition_elapsed = 0.0
        self._fire("ET_DECLOAK_COMPLETED")

    # ── State predicates (read by CloakShip.CheckCloak + doctrines) ──────────

    def IsCloaked(self) -> int:
        return 1 if self._cloak_state == self.CLOAK_CLOAKED else 0

    def IsCloaking(self) -> int:
        return 1 if self._cloak_state == self.CLOAK_CLOAKING else 0

    def IsDecloaking(self) -> int:
        return 1 if self._cloak_state == self.CLOAK_DECLOAKING else 0

    def IsTryingToCloak(self) -> int:
        """True whenever the cloak is "on" — i.e. the intent is to be cloaked.
        That is CLOAKING (fading out toward cloaked) or already CLOAKED.
        DECLOAKING / DECLOAKED both express the intent to be visible."""
        return 1 if self._cloak_state in (self.CLOAK_CLOAKING,
                                          self.CLOAK_CLOAKED) else 0


    def _wants_power(self) -> bool:
        """The cloak draws power only while the ship is trying to stay hidden
        (CLOAKING or CLOAKED) — NOT on the PoweredSubsystem on/off flag.  BC
        drains the cloak for the whole duration the device is engaged (warbird
        authors 1000 power/sec).  This replaces the old PowerSubsystem.
        _compute_idle_drain cloak special-case."""
        return bool(self.IsTryingToCloak())

    def GetTransitionFraction(self) -> float:
        """Visual cloak progress in [0, 1]: 0 = fully visible (DECLOAKED),
        1 = fully hidden (CLOAKED).  Ramps with the transition timer during
        CLOAKING (0→1) and back down during DECLOAKING (1→0).  The renderer
        drives the refraction / chromatic-dispersion strength off this — it is a
        pure read of the state machine and has no gameplay effect."""
        if self._cloak_state == self.CLOAK_DECLOAKED:
            return 0.0
        if self._cloak_state == self.CLOAK_CLOAKED:
            return 1.0
        dur = self._transition_duration if self._transition_duration > 0.0 else 1.0
        f = self._transition_elapsed / dur
        f = 0.0 if f < 0.0 else (1.0 if f > 1.0 else f)
        return f if self._cloak_state == self.CLOAK_CLOAKING else (1.0 - f)

    # ── Forced-decloak helper ────────────────────────────────────────────────

    def _force_decloak(self) -> None:
        """Snap the cloak state to DECLOAKED immediately, firing
        ET_DECLOAK_COMPLETED if the device was fully CLOAKED.

        Shared by the offline path (disabled/destroyed device) and the
        power-starvation path (backup battery exhausted).  Only acts when
        IsTryingToCloak() — i.e. CLOAKING or CLOAKED; calling it in any
        other state is a no-op."""
        if self._cloak_state not in (self.CLOAK_CLOAKING, self.CLOAK_CLOAKED):
            return
        was_cloaked = self._cloak_state == self.CLOAK_CLOAKED
        self._cloak_state = self.CLOAK_DECLOAKED
        self._transition_elapsed = 0.0
        self._cloak_dev_log("forced decloak")
        if was_cloaked:
            self._fire("ET_DECLOAK_COMPLETED")

    def _cloak_dev_log(self, verb: str) -> None:
        """Dev-mode-only transition trace. print(), not logging — the host
        configures no logging handler, so logging.* is swallowed. Matches the
        [viewscreen]/[ai] convention; off in production."""
        if not dev_mode.is_enabled():
            return
        ship = self.GetParentShip() if hasattr(self, "GetParentShip") else None
        name = ship.GetName() if (ship is not None and hasattr(ship, "GetName")) else "<ship>"
        print(f"[cloak] {name} -> {verb}")

    # ── Per-tick transition advance (game-loop subsystem update pass) ────────

    # ── The transition tick is NATIVE ONLY (phase 6 Task 8) ─────────────
    # subsystem_step.h THE CLOAK PIECE is the one implementation: a disabled
    # or destroyed device (IsDisabled / IsDestroyed) cannot hold a cloak and
    # is forced off (_force_decloak); a dry backup reserve (the pump's
    # _backup_reserve snapshot, keyed on CLOAK_RESERVE_DRAIN_PER_SECOND > 0)
    # forces it off too (MIN_RESERVE_TO_HOLD_CLOAK); otherwise the
    # transition completes at _transition_duration and fires its event.

    # ── Weapon coupling ───────────────────────────────────────────────────────

    def _stop_weapons(self) -> None:
        """Force the owning ship's weapons offline the instant the cloak engages.

        ``_cloak_blocks_fire`` (weapon_subsystems) already blocks *new* fire
        while IsTryingToCloak, but an already-firing beam keeps going until
        something calls StopFiring — so a ship that cloaks mid-volley would keep
        shooting.  BC drops weapons offline on cloak, so actively stop every
        weapon system here (same trigger path as the shield collapse — player
        toggle, AI doctrine, and mission scripts all funnel through
        StartCloaking).  Raise-safe: a bare cloak with no parent ship simply
        does nothing."""
        try:
            ship = self._climb_to_ship() if hasattr(self, "_climb_to_ship") else None
            if ship is None:
                return
            for getter in ("GetPhaserSystem", "GetPulseWeaponSystem",
                           "GetTorpedoSystem"):
                fn = getattr(ship, getter, None)
                system = fn() if callable(fn) else None
                if system is not None and hasattr(system, "StopFiring"):
                    system.StopFiring()
        except Exception as _e:
            dev_mode.log_swallowed("cloak weapons stop", _e)

    # ── Cloak transition SFX ─────────────────────────────────────────────────

    def _play_cloak_sfx(self, name: str) -> None:
        """Play the cloak/decloak transition sound as a 3D one-shot at the owning
        ship.  ``name`` is the sound-manager key — "Cloak" (sfx/cloak on.wav) or
        "Uncloak" (sfx/cloak off.wav), both loaded by LoadTacticalSounds.  Fires
        for every transition path (player toggle, AI doctrine, mission script)
        because they all funnel through StartCloaking / StopCloaking; the
        no-transition InstantCloak / InstantDecloak jumps stay silent (BC plays
        the sweep only on an actual transition).  Raise-safe: no sound manager
        (headless / tests) or a parentless cloak simply does nothing."""
        try:
            import App
            mgr = getattr(App, "g_kSoundManager", None)
            if mgr is None:
                return
            snd = mgr.GetSound(name)
            if snd is None:
                return
            ship = self._climb_to_ship() if hasattr(self, "_climb_to_ship") else None
            if ship is not None and hasattr(ship, "GetWorldLocation"):
                loc = ship.GetWorldLocation()
                snd.Play(position=(loc.x, loc.y, loc.z))
            else:
                snd.Play()
        except Exception as _e:
            dev_mode.log_swallowed("cloak sfx", _e)

    # _fire is inherited from PoweredSubsystem — cloak events use the same
    # ship-as-destination broadcast seam as ET_SUBSYSTEM_POWER_CHANGED.


# ── Module-level WarpEngineSubsystem helpers ─────────────────────────────────
# SDK callers (WarpSequence.py:95-282) reach for a class-level / engine-default
# warp effect time when sequencing the warp begin / end / flash actions:
#
#     pWS.AddAction(pWarpEndAction, pWarpBeginAction,
#                   App.WarpEngineSubsystem_GetWarpEffectTime() / 2.0)
#
# This is the default warp-transition duration in seconds, independent of any
# specific ship's warp engine.  Default 3.0s matches BC's warp animation length.

_warp_effect_time_default: float = 3.0


def WarpEngineSubsystem_GetWarpEffectTime() -> float:
    return _warp_effect_time_default


def WarpEngineSubsystem_SetWarpEffectTime(seconds: float) -> None:
    """Override the engine-default warp effect time (used by tests)."""
    global _warp_effect_time_default
    _warp_effect_time_default = float(seconds)


def _get_xyz(ship) -> tuple:
    """Read a ship's world-space position as a tuple of floats. Adapts
    to whichever accessor the shim exposes. Falls back to (0, 0, 0) so
    the helper is safe to call against a ship that hasn't been
    positioned yet (e.g. just spawned).

    ⚠️ The accessor probe is `implements()`, NOT `hasattr()`. hasattr is
    vacuously true for all five names on every TGObject — `__getattr__` vends a
    truthy `_Stub` — so the loop always "found" GetTranslate first, called the
    stub, and read `.x/.y/.z` off it as 0.0. Any TGObject whose class does not
    really define GetTranslate but does define a later accessor therefore
    resolved to the ORIGIN instead of its position. Measured, not reasoned:
    AT THE TIME this was found, Torpedo (projectiles.py) was a bare TGObject
    with a real GetWorldLocation and no GetTranslate, so it read (0,0,0)
    under hasattr and (0,500,0) under implements.

    That was latent, not live. `ObjectClass` really defines GetTranslate, so
    every ObjectClass descendant — ShipClass, Planet, PhysicsObjectClass,
    DamageableObject — resolved through the first accessor either way, and a
    census of the three call sites (perception.perceived_by,
    perception.measure_surface_gu_to, sensor_detection.can_detect) found only
    ObjectClass arguments. The full class scan puts exactly two families in the
    changed set, neither of which reaches any of them: Torpedo, and the
    ShipSubsystem/Weapon hierarchy. Running both implementations side by side
    over the whole test suite produced zero divergences.

    STALE AS OF the TransformStore migration
    (docs/superpowers/plans/2026-09-05-native-transform-ownership.md):
    Torpedo now extends `ObjectClass` (emitter gaps #6/#7) and no longer
    overrides GetWorldLocation or GetTranslate at all — both are inherited,
    unmodified, and store-backed. So a Torpedo DOES define a real
    GetTranslate today, and this loop resolves it through the FIRST
    accessor, same as any other ObjectClass. The two-paragraphs above are
    kept as the historical record of why `implements()` and not `hasattr()`
    was the fix; do not read them as describing Torpedo's current class.
    """
    # GetTranslate() returns a TGPoint3 with .x, .y, .z attributes.
    for name in ("GetTranslate", "GetWorldLocation", "GetTranslation", "GetPosition",
                 "GetTranslateXYZ"):
        if implements(ship, name):
            try:
                t = getattr(ship, name)()
                # TGPoint3 / any object with .x .y .z
                if hasattr(t, "x") and hasattr(t, "y") and hasattr(t, "z"):
                    return (float(t.x), float(t.y), float(t.z))
                # plain tuple or list
                if isinstance(t, (tuple, list)) and len(t) == 3:
                    return (float(t[0]), float(t[1]), float(t[2]))
            except Exception as _e:
                dev_mode.log_swallowed(f"ship position via {name}", _e)
    # Last resort — direct attribute access for the simplest possible shim.
    # Dead for every ObjectClass since the TransformStore migration: it no
    # longer has a `_position` attribute at all, and engine/core/ids.py's
    # TGObject.__getattr__ raises AttributeError (not a truthy _Stub) for
    # single-underscore names, so hasattr() here is a real, honest False for
    # it. Kept for non-ObjectClass duck-typed inputs (bare fakes/test
    # doubles that set `_position` directly without implementing any of the
    # accessors above) — do not delete.
    if hasattr(ship, "_position"):
        try:
            p = ship._position
            if hasattr(p, "x") and hasattr(p, "y") and hasattr(p, "z"):
                return (float(p.x), float(p.y), float(p.z))
            if isinstance(p, (tuple, list)) and len(p) == 3:
                return (float(p[0]), float(p[1]), float(p[2]))
        except Exception as _e:
            dev_mode.log_swallowed("ship position via _position attr", _e)
    return (0.0, 0.0, 0.0)


def HandleRepairPriorityEvent(pObject, pEvent):
    """Instance handler for ET_REPAIR_INCREASE_PRIORITY on a RepairSubsystem.
    Signature matches TGEventHandlerObject dispatch: fn(dest_object, event)."""
    sub = pEvent.GetObjPtr() if hasattr(pEvent, "GetObjPtr") else None
    if isinstance(pObject, RepairSubsystem) and sub is not None:
        pObject.HandleIncreasePriority(sub)
    pObject.CallNextHandler(pEvent)


_SUBSYSTEM_GETTERS = (
    "GetHull", "GetShieldSubsystem", "GetSensorSubsystem",
    "GetImpulseEngineSubsystem", "GetWarpEngineSubsystem",
    "GetPowerSubsystem", "GetRepairSubsystem", "GetTorpedoSystem",
    "GetPhaserSystem", "GetPulseWeaponSystem", "GetTractorBeamSystem",
    "GetCloakingSubsystem",
)


def iter_subsystems(ship):
    """The hull, then every top-level subsystem, each followed by its
    children, in a fixed order. Safe on None/partial ships: a getter that
    raises is skipped (and logged)."""
    if ship is None:
        return
    for name in _SUBSYSTEM_GETTERS:
        try:
            sub = getattr(ship, name, lambda: None)()
            if sub is None:
                continue
            children = [sub.GetChildSubsystem(i)
                        for i in range(sub.GetNumChildSubsystems())]
        except Exception as _e:
            dev_mode.log_swallowed("iter_subsystems", _e)
            continue
        yield sub
        for child in children:
            if child is not None:
                yield child


def repair_ship_fully(ship) -> None:
    """Dev/debug full repair — mirrors sdk Actions/ShipScriptActions.py
    RepairShipFully: every subsystem back to max condition. Also clears
    the repair queue (nothing left to fix). Safe on None/partial ships."""
    if ship is None:
        return
    for sub in iter_subsystems(ship):
        try:
            sub.SetCondition(sub.GetMaxCondition())
        except Exception as _e:
            dev_mode.log_swallowed("repair_ship_fully", _e)
    bay = getattr(ship, "GetRepairSubsystem", lambda: None)()
    if bay is not None and hasattr(bay, "_queue"):
        bay._queue.clear()


# ── Weapon subsystem hierarchy (split out into engine.appc.weapon_subsystems) ──
# The weapon classes are part of this module's public surface; they were moved to
# engine.appc.weapon_subsystems purely to shrink this file. ~30 call sites do
# ``from engine.appc.subsystems import PhaserSystem`` (etc.), so we re-export the
# weapon names here. weapon_subsystems imports the base classes
# (ShipSubsystem / PoweredSubsystem) and shared predicates UP from this module;
# resolving the weapon names lazily via module __getattr__ (PEP 562) keeps that a
# one-way dependency with NO import cycle, regardless of which module is imported
# first. The first access to any weapon name triggers the import, by which point
# both modules are fully loaded.
_WEAPON_EXPORTS = frozenset({
    "Weapon",
    "WeaponSystem",
    "TorpedoAmmoType",
    "TorpedoSystem",
    "PHASER_MAX_RANGE_GU",
    "PhaserSystem",
    "PulseWeaponSystem",
    "TractorBeamSystem",
    "PhaserBank",
    "PulseWeapon",
    "TractorBeam",
    "TorpedoTube",
    "_EnergyWeaponFireMixin",
    "_resolve_aim_world",
    "_resolve_bank_aim_world",
    "_emitter_in_arc",
    "_init_energy_weapon_state",
    "_resolve_fire_sound",
})


def __getattr__(name):
    """Lazily forward the weapon-subsystem names to engine.appc.weapon_subsystems
    (PEP 562). Keeps the weapon classes importable as ``engine.appc.subsystems.X``
    without an eager import that would create a cycle."""
    if name in _WEAPON_EXPORTS:
        from engine.appc import weapon_subsystems
        return getattr(weapon_subsystems, name)
    raise AttributeError("module %r has no attribute %r" % (__name__, name))


def __dir__():
    return sorted(list(globals().keys()) + list(_WEAPON_EXPORTS))


def impulse_fractions(ies):
    """``(online_fraction, output_fraction)`` from ONE walk over the pods.

    ``impulse_online_fraction`` and ``impulse_output_fraction`` are both called
    once per ship per tick from the motion path, and each iterates the same
    child-pod list -- two walks, two sets of GetChildSubsystem calls, for facts
    about the same objects. Together they were 0.81 s of ship motion's 1.57 s
    over 150 ticks at 100 ships.

    The two predicates genuinely differ and both are preserved verbatim:
    ``online`` counts pods that are not ``_is_offline`` (disabled OR destroyed
    OR parent out of action), while ``output`` weights by condition and treats
    only ``IsDisabled`` as forfeiting the pod's whole share. So this fuses the
    ITERATION, not the semantics.

    Equivalent to calling both, with one ordering difference that cannot change
    a result: ``impulse_output_fraction`` short-circuits on ``not IsOn()``
    before touching the pods, whereas this walks them first because the online
    fraction needs the walk regardless. Same values, in the switched-off case a
    walk that the separate call would have skipped.
    """
    if ies is None:
        return 1.0, 1.0
    if _is_offline(ies):
        return 0.0, 0.0
    n = ies.GetNumChildSubsystems()
    if n == 0:
        online, cur = 1.0, 1.0
    else:
        # _is_offline(pod) is three predicates: IsDisabled, IsDestroyed, and
        # "parent ship out of action" -- and that third one costs an
        # implements() MRO WALK plus GetParentShip plus a full _out_of_action,
        # per pod, for an answer that is identical across every pod on the
        # engine (they share one ship).
        #
        # It is not merely identical, it is already KNOWN: _is_offline(ies)
        # above returned False, and that call tested this same ship. So past
        # that early return the ship is established to be in action, and the
        # per-pod ship check cannot fire. Only valid when `ies` itself carries
        # GetParentShip -- otherwise _is_offline(ies) skipped the ship clause
        # and never established anything, so that case keeps the full call.
        #
        # Also fuses the double IsDisabled(): the loop asked each pod twice,
        # once inside _is_offline and once for the condition weighting.
        _ship_known_good = implements(ies, "GetParentShip")
        online_n = 0
        contrib = 0.0
        for i in range(n):
            pod = ies.GetChildSubsystem(i)
            disabled = bool(pod.IsDisabled())
            if _ship_known_good:
                offline = disabled or bool(pod.IsDestroyed())
            else:
                offline = _is_offline(pod)
            if not offline:
                online_n += 1
            if not disabled:
                contrib += pod.GetConditionPercentage()
        online = online_n / float(n)
        cur = contrib / n
    if not ies.IsOn():
        return online, 0.0
    cur = max(0.0, min(1.0, cur))
    return online, cur * ies.GetPowerPercentageWanted()
