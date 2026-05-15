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

from engine.appc.events import TGEventHandlerObject
from engine.appc.math import TGPoint3, TGMatrix3


def _resolve_aim_world(ship, target):
    """Unit vector in world space from ship → target, or ship-forward if no target."""
    if (ship is not None and target is not None
            and hasattr(target, "GetWorldLocation")
            and hasattr(ship, "GetWorldLocation")):
        ship_pos   = ship.GetWorldLocation()
        target_pos = target.GetWorldLocation()
        dx = target_pos.x - ship_pos.x
        dy = target_pos.y - ship_pos.y
        dz = target_pos.z - ship_pos.z
        length = (dx * dx + dy * dy + dz * dz) ** 0.5
        if length > 1e-6:
            return TGPoint3(dx / length, dy / length, dz / length)
    # Fallback: ship's body +Y axis rotated into world.
    fwd = TGPoint3(0.0, 1.0, 0.0)
    if ship is not None and hasattr(ship, "GetWorldRotation"):
        rot = ship.GetWorldRotation()
        if isinstance(rot, TGMatrix3):
            fwd.MultMatrixLeft(rot)
    length = (fwd.x * fwd.x + fwd.y * fwd.y + fwd.z * fwd.z) ** 0.5
    if length > 1e-6:
        return TGPoint3(fwd.x / length, fwd.y / length, fwd.z / length)
    return TGPoint3(0.0, 1.0, 0.0)


def _emitter_in_arc(emitter, ship, aim_world):
    """Returns True if `aim_world` (unit vector) lies inside the emitter's
    firing arc, rotated into world space via the ship's rotation.

    Emitters with explicit SetArcWidthAngles / SetArcHeightAngles use a
    yaw × pitch rectangular cone.  Bare emitters (no arc setters — i.e.
    torpedo tubes) fall back to a 90° dot-product check against the
    emitter's SetDirection.
    """
    if not hasattr(emitter, "GetDirection"):
        return True
    try:
        local_dir = emitter.GetDirection()
    except Exception:
        return True
    if not isinstance(local_dir, TGPoint3):
        return True
    # Rotate emitter direction into world space.
    world_dir = TGPoint3(local_dir.x, local_dir.y, local_dir.z)
    if ship is not None and hasattr(ship, "GetWorldRotation"):
        rot = ship.GetWorldRotation()
        if isinstance(rot, TGMatrix3):
            world_dir.MultMatrixLeft(rot)

    # Emitter without explicit arc bounds (torpedo tubes) — fall back to
    # a 90° dot-product cone.  ShipSubsystem always exposes a typed
    # GetArcWidthAngles() returning wide defaults, so the trigger for the
    # arc check is the _arc_set flag set by SetProperty when an
    # EnergyWeaponProperty actually supplied bounds.  Bare test emitters
    # (no _arc_set attr at all) use the same typed-tuple probe as before.
    use_arc_check = getattr(emitter, "_arc_set", None)
    if use_arc_check is None:
        arc_w = None
        if hasattr(emitter, "GetArcWidthAngles"):
            try:
                arc_w = emitter.GetArcWidthAngles()
            except Exception:
                arc_w = None
        use_arc_check = isinstance(arc_w, tuple) and len(arc_w) == 2
    if not use_arc_check:
        return (world_dir.x * aim_world.x
              + world_dir.y * aim_world.y
              + world_dir.z * aim_world.z) > 0.0
    arc_w = emitter.GetArcWidthAngles()

    # Rotate Right axis into world too.
    right_local = emitter.GetRight() if hasattr(emitter, "GetRight") else TGPoint3(1.0, 0.0, 0.0)
    world_right = TGPoint3(right_local.x, right_local.y, right_local.z)
    if ship is not None and hasattr(ship, "GetWorldRotation"):
        rot = ship.GetWorldRotation()
        if isinstance(rot, TGMatrix3):
            world_right.MultMatrixLeft(rot)
    # Up = Direction × Right (right-handed body frame).
    world_up = TGPoint3(
        world_dir.y * world_right.z - world_dir.z * world_right.y,
        world_dir.z * world_right.x - world_dir.x * world_right.z,
        world_dir.x * world_right.y - world_dir.y * world_right.x,
    )

    # Project aim onto body frame.
    fwd_dot   = world_dir.x   * aim_world.x + world_dir.y   * aim_world.y + world_dir.z   * aim_world.z
    right_dot = world_right.x * aim_world.x + world_right.y * aim_world.y + world_right.z * aim_world.z
    up_dot    = world_up.x    * aim_world.x + world_up.y    * aim_world.y + world_up.z    * aim_world.z

    import math as _math
    yaw   = _math.atan2(right_dot, fwd_dot)
    pitch = _math.asin(max(-1.0, min(1.0, up_dot)))

    yaw_lo, yaw_hi = arc_w
    arc_h = emitter.GetArcHeightAngles() if hasattr(emitter, "GetArcHeightAngles") else None
    if not (isinstance(arc_h, tuple) and len(arc_h) == 2):
        # Arc width set but height missing — allow any pitch.
        return yaw_lo <= yaw <= yaw_hi
    pitch_lo, pitch_hi = arc_h
    return (yaw_lo <= yaw <= yaw_hi) and (pitch_lo <= pitch <= pitch_hi)


def _init_energy_weapon_state(self):
    """Shared init for PhaserBank/PulseWeapon/TractorBeam runtime state.

    Field names mirror EnergyWeaponProperty.  Pass 4 copies the property
    values onto these attributes after instantiation; until then they're
    all zero.
    """
    self._max_charge: float = 0.0
    self._min_firing_charge: float = 0.0
    self._normal_discharge_rate: float = 0.0
    self._recharge_rate: float = 0.0
    self._charge_level: float = 0.0


def _resolve_fire_sound(prop) -> str:
    """Returns the FireSound name (typed accessor) or empty string."""
    if prop is None or not hasattr(prop, "GetFireSound"):
        return ""
    return prop.GetFireSound() or ""


class _EnergyWeaponFireMixin:
    """Shared Fire/CanFire/StopFiring/UpdateCharge for PhaserBank / PulseWeapon
    / TractorBeam.  Per-emitter state initialised by _init_energy_weapon_state.
    Each class also has _firing (False at init), _target/_target_offset (None).

    SFX trigger looks up the property's FireSound name and asks TGSoundManager
    to play it.  Tries "<name> Start" first (phaser convention), falls back to
    bare "<name>" (tractor convention).  Names map to WAV assets via
    sdk/Build/scripts/LoadTacticalSounds.py invoked at audio init.
    """

    def CanFire(self) -> int:
        parent = self.GetParentSubsystem()
        on = parent is not None and parent.IsOn()
        charged = self._charge_level >= self._min_firing_charge
        return 1 if (on and charged) else 0

    def Fire(self, target=None, offset=None) -> None:
        if not self.CanFire():
            return
        self._firing = True
        self._target = target
        self._target_offset = offset
        self._play_fire_sfx()

    def StopFiring(self) -> None:
        self._firing = False

    def IsFiring(self) -> int:
        return 1 if self._firing else 0

    def UpdateCharge(self, dt: float) -> None:
        if self._firing:
            self._charge_level = max(
                0.0, self._charge_level - self._normal_discharge_rate * dt
            )
            if self._charge_level < self._min_firing_charge:
                self._firing = False
        else:
            parent = self.GetParentSubsystem()
            if parent is not None and parent.IsOn():
                self._charge_level = min(
                    self._max_charge,
                    self._charge_level + self._recharge_rate * dt,
                )

    def _play_fire_sfx(self) -> None:
        name = _resolve_fire_sound(self.GetProperty())
        if not name:
            return
        from engine.audio.tg_sound import TGSoundManager
        mgr = TGSoundManager.instance()
        played = mgr.PlaySound(name + " Start")
        if played is None:
            mgr.PlaySound(name)


class ShipSubsystem(TGEventHandlerObject):
    def __init__(self, name: str = ""):
        super().__init__()
        self._name = name
        self._property = None
        self._parent_ship = None
        self._parent_subsystem = None
        self._child_subsystem = None
        self._children: list["ShipSubsystem"] = []
        self._condition = 1.0
        self._max_condition = 1.0
        self._radius = 0.0
        self._position = TGPoint3(0.0, 0.0, 0.0)
        # Body-space mounting axes — defaults match the SDK convention
        # (firing along +Y, right side along +X).  SetProperty mirrors the
        # hardpoint values across when a property is bound.
        self._direction = TGPoint3(0.0, 1.0, 0.0)
        self._right     = TGPoint3(1.0, 0.0, 0.0)
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
        # Flag set True only when a property actually supplied typed arc
        # data (EnergyWeaponProperty hierarchy).  Emitters without it
        # (torpedo tubes) fall back to a 90° dot-product cone.
        self._arc_set: bool = False
        # Shared identity fields populated by SetupProperties.
        self._critical: int = 0
        self._targetable: int = 0
        self._primary: int = 0
        self._disabled_percentage: float = 0.25

    def GetName(self) -> str:
        return self._name

    def SetName(self, name: str) -> None:
        self._name = name

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

    def IsTypeOf(self, cls) -> int:
        """SDK class-id check. Returns 1 when this subsystem's source
        property is an instance of `cls`, else 0.

        `cls` may be a fall-through stub (e.g. App.CT_UNKNOWN_THING
        returns an App._NamedStub instance), so guard with
        isinstance(cls, type) before testing.
        """
        if self._property is None or not isinstance(cls, type):
            return 0
        return 1 if isinstance(self._property, cls) else 0

    def GetParentShip(self):
        return self._parent_ship

    def SetParentShip(self, ship) -> None:
        self._parent_ship = ship

    def GetParentSubsystem(self):
        return self._parent_subsystem

    def GetChildSubsystem(self):
        return self._child_subsystem

    def GetCondition(self) -> float:
        return self._condition

    def SetCondition(self, value: float) -> None:
        """Floor at zero. DamageSystem (Task 4) routes hits through here."""
        self._condition = max(0.0, float(value))

    def GetMaxCondition(self) -> float:
        return self._max_condition

    def SetMaxCondition(self, value: float) -> None:
        # SDK App.py:5601 — also seed current condition when bumping max from
        # the default so freshly-loaded ships start undamaged.
        v = float(value)
        if self._condition == self._max_condition:
            self._condition = v
        self._max_condition = v

    def GetConditionPercentage(self) -> float:
        if self._max_condition <= 0:
            return 0.0
        return self._condition / self._max_condition

    def GetCombinedConditionPercentage(self) -> float:
        # SDK aggregates self + child subsystems; Phase 1 ships have no
        # children so this collapses to the same value.
        return self.GetConditionPercentage()

    def GetDamage(self) -> float:
        return self._max_condition - self._condition

    def GetRepairPointsNeeded(self) -> int:
        return int(self._max_condition - self._condition)

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

    def GetArcWidthAngles(self) -> tuple:
        return (self._arc_width_lo, self._arc_width_hi)

    def GetArcHeightAngles(self) -> tuple:
        return (self._arc_height_lo, self._arc_height_hi)

    def GetMaxDamage(self) -> float:
        return self._max_damage

    def GetMaxDamageDistance(self) -> float:
        return self._max_damage_distance

    def GetWorldLocation(self) -> TGPoint3:
        if self._parent_ship is not None:
            base = self._parent_ship.GetWorldLocation()
            return TGPoint3(
                base.x + self._position.x,
                base.y + self._position.y,
                base.z + self._position.z,
            )
        return self.GetPositionTG()

    def GetDamagePoint(self) -> TGPoint3:
        return self.GetPositionTG()

    def _climb_to_ship(self):
        """Walk parent-subsystem chain until a ShipClass is found.  Used
        by emitters that need their owning ship for world-space math."""
        # Direct attachment: ShipClass._attach_subsystem set _parent_ship.
        if self._parent_ship is not None:
            return self._parent_ship
        node = self.GetParentSubsystem()
        while node is not None:
            if hasattr(node, "GetParentShip") and node.GetParentShip() is not None:
                return node.GetParentShip()
            node = node.GetParentSubsystem() if hasattr(node, "GetParentSubsystem") else None
        return None

    def _emitter_world_position(self) -> TGPoint3:
        """Ship world location + emitter local position scaled and rotated
        into world frame.

        SDK SetPosition values are normalized to the ship's extent (roughly
        [-1, +1]).  We scale them by ship.GetRadius() to recover a
        meaningful world-space offset, then rotate by the ship's world
        rotation.
        """
        ship = self._climb_to_ship()
        if ship is None:
            return TGPoint3(0.0, 0.0, 0.0)
        ship_pos = ship.GetWorldLocation()
        local = self.GetPosition() if hasattr(self, "GetPosition") else None
        if not isinstance(local, TGPoint3):
            return TGPoint3(ship_pos.x, ship_pos.y, ship_pos.z)
        scale = float(ship.GetRadius()) if hasattr(ship, "GetRadius") else 1.0
        offset = TGPoint3(local.x * scale, local.y * scale, local.z * scale)
        if hasattr(ship, "GetWorldRotation"):
            rot = ship.GetWorldRotation()
            if isinstance(rot, TGMatrix3):
                offset.MultMatrixLeft(rot)
        return TGPoint3(ship_pos.x + offset.x,
                        ship_pos.y + offset.y,
                        ship_pos.z + offset.z)

    def GetNextTargetableChildSubsystem(self):
        return None

    def GetConditionWatcher(self):
        return None

    def GetCombinedPercentageWatcher(self):
        return None

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

    def GetCritical(self) -> int:                       return self._critical
    def SetCritical(self, v) -> None:                   self._critical = int(v)
    def GetTargetable(self) -> int:                     return self._targetable
    def SetTargetable(self, v) -> None:                 self._targetable = int(v)
    def GetPrimary(self) -> int:                        return self._primary
    def SetPrimary(self, v) -> None:                    self._primary = int(v)
    def GetDisabledPercentage(self) -> float:           return self._disabled_percentage
    def SetDisabledPercentage(self, v) -> None:         self._disabled_percentage = float(v)


class PoweredSubsystem(ShipSubsystem):
    """Powered subsystem — consumes power, has a target power level."""
    def __init__(self, name: str = ""):
        super().__init__(name)
        self._normal_power = 0.0
        self._current_power = 0.0
        # On/off state — TurnOn/TurnOff drive gating in WeaponSystem.StartFiring
        # and the shield-raise pathway.  Default off matches the SDK; a fresh
        # ship is unpowered until ShipClass.SetAlertLevel(RED) or a mission
        # script explicitly turns systems on.
        self._is_on: bool = False
        self._power_percentage_wanted: float = 0.0

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
    def SetPowerPercentageWanted(self, pct) -> None:       self._power_percentage_wanted = float(pct)
    def GetPowerPercentageWanted(self) -> float:           return self._power_percentage_wanted


class WeaponSystem(PoweredSubsystem):
    """Weapon system — has firing state and an optional target.

    Reparented under PoweredSubsystem because every weapon system in BC
    has a power line.  See sdk/.../App.py:6361 (WeaponSystem inherits
    PoweredSubsystem there).

    Sequential firing (PR 2a): StartFiring picks the next eligible
    emitter in round-robin order, fires it, and advances the cursor.
    Matches Galaxy's SetSingleFire(1) loadout.  Multi-fire / firing-chain
    modes are future work (FiringChainString hardpoint field).
    """
    def __init__(self, name: str = ""):
        super().__init__(name)
        self._target = None
        self._weapon_system_type: int = 0
        # Round-robin cursor into child emitters and the set of indices
        # currently firing (for StopFiring to halt the right ones).
        self._next_emitter_index: int = 0
        self._currently_firing: list = []

    def StartFiring(self, target=None, offset=None) -> None:
        if not self.IsOn():
            return
        n = self.GetNumWeapons()
        if n == 0:
            return
        # Resolve the aim direction in world space.  If the ship has a
        # target, point at it; otherwise assume "straight ahead" using
        # the ship's body +Y axis rotated into world.
        ship = self.GetParentShip()
        aim_world = _resolve_aim_world(ship, target)

        start = self._next_emitter_index % n
        for delta in range(n):
            idx = (start + delta) % n
            emitter = self.GetWeapon(idx)
            if emitter is None:
                continue
            if not _emitter_in_arc(emitter, ship, aim_world):
                continue
            if hasattr(emitter, "CanFire") and emitter.CanFire():
                emitter.Fire(target, offset)
                self._currently_firing.append(idx)
                self._next_emitter_index = (idx + 1) % n
                return
        # No eligible emitter — silent no-op.

    def StopFiring(self, *args) -> None:
        for idx in self._currently_firing:
            emitter = self.GetWeapon(idx)
            if emitter is not None and hasattr(emitter, "StopFiring"):
                emitter.StopFiring()
        self._currently_firing = []

    def IsFiring(self) -> int:
        return 1 if self._currently_firing else 0

    def GetTarget(self):                          return self._target
    def SetTarget(self, target) -> None:          self._target = target
    def GetWeaponSystemType(self) -> int:         return self._weapon_system_type
    def SetWeaponSystemType(self, v) -> None:     self._weapon_system_type = int(v)

    # SDK-faithful aliases over the child-subsystem API.
    # TacticalInterfaceHandlers.FireWeapons (PR 2) reads these.
    def GetNumWeapons(self) -> int:               return self.GetNumChildSubsystems()
    def GetWeapon(self, i: int):                  return self.GetChildSubsystem(i)


class TorpedoAmmoType:
    """A loaded torpedo ammo type — exposes the SDK GetAmmoName surface.

    Real BC Appc has a TorpedoAmmoType class with per-instance ammo properties
    (damage, blast radius, etc.); Phase 1 only needs the name for the
    MissionLib.SetTotalTorpsAtStarbase / LoadTorpedoes lookup pattern, which
    compares ``pTorpType.GetAmmoName() == "Photon"``.
    """
    def __init__(self, name: str):
        self._name = name

    def GetAmmoName(self) -> str:
        return self._name

    def __repr__(self) -> str:
        return f"<TorpedoAmmoType {self._name!r}>"


class TorpedoSystem(WeaponSystem):
    def __init__(self, name: str = ""):
        super().__init__(name)
        # Keyed slot table — `SetAmmoType(slot, ammo)` is the SDK setter
        # mission scripts use to swap loadouts (E2M0 sets Birds-of-Prey to
        # AT_TWO photon torpedoes).  GetNumAmmoTypes counts populated slots.
        self._ammo_by_slot: dict = {}

    def GetNumAmmoTypes(self) -> int:
        return len(self._ammo_by_slot)

    def AddAmmoType(self, ammo_type) -> None:
        # Append into the next free slot.  Mission code uses either AddAmmoType
        # (during hardpoint setup) or SetAmmoType (during mission to override).
        self._ammo_by_slot[len(self._ammo_by_slot)] = ammo_type

    def SetAmmoType(self, ammo_or_slot, slot_or_ammo=None) -> None:
        # SDK signature: SetAmmoType(ammo_type, slot).  E2M0 calls
        # `pTorps.SetAmmoType(App.AT_TWO, 0)`.  Both args are ints so we
        # don't need to disambiguate by type — first arg = ammo, second = slot.
        if slot_or_ammo is None:
            self._ammo_by_slot[0] = ammo_or_slot
        else:
            self._ammo_by_slot[int(slot_or_ammo)] = ammo_or_slot

    def GetAmmoType(self, slot: int):
        return self._ammo_by_slot.get(int(slot))


class PhaserSystem(WeaponSystem):
    # Power-level constants from sdk/.../App.py:6444-6446.
    PP_LOW = 0
    PP_HIGH = 1

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._power_level = self.PP_HIGH
        self._single_fire: int = 0
        self._aimed_weapon: int = 0

    def SetPowerLevel(self, level) -> None:
        self._power_level = int(level)

    def GetPowerLevel(self) -> int:
        return self._power_level

    def GetSingleFire(self) -> int:                 return self._single_fire
    def SetSingleFire(self, v) -> None:             self._single_fire = int(v)
    def GetAimedWeapon(self) -> int:                return self._aimed_weapon
    def SetAimedWeapon(self, v) -> None:            self._aimed_weapon = int(v)

    def StartFiring(self, target=None, offset=None) -> None:
        """Multi-bank dispatch — fire every PhaserBank whose alert + arc +
        charge gates all pass.  Differs from torpedo round-robin: phasers
        engage simultaneously."""
        if not self.IsOn() or target is None:
            return
        ship = self.GetParentShip()
        aim_world = _resolve_aim_world(ship, target)
        self._currently_firing = []
        for i in range(self.GetNumWeapons()):
            bank = self.GetWeapon(i)
            if bank is None:
                continue
            if not _emitter_in_arc(bank, ship, aim_world):
                continue
            if hasattr(bank, "CanFire") and bank.CanFire():
                bank.Fire(target, offset)
                self._currently_firing.append(i)


class PulseWeaponSystem(WeaponSystem):
    pass


class TractorBeamSystem(WeaponSystem):
    # Tractor-beam mode constants from sdk/.../App.py:6774-6779.
    # SDK consumers: Preprocessors.py, AI/PlainAI/Warp.py, TowAway.py, etc.
    TBS_HOLD          = 0
    TBS_TOW           = 1
    TBS_PULL          = 2
    TBS_PUSH          = 3
    TBS_DOCK_STAGE_1  = 4
    TBS_DOCK_STAGE_2  = 5

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._mode = self.TBS_HOLD

    def GetMode(self) -> int:
        return self._mode

    def SetMode(self, mode) -> None:
        self._mode = int(mode)

    def IsTryingToFire(self) -> int:
        return self.IsFiring()


class PhaserBank(_EnergyWeaponFireMixin, WeaponSystem):
    """Individual phaser emitter under a parent PhaserSystem
    (WeaponSystemProperty WST_PHASER).  Charge fields populated by Pass 4
    from the parent PhaserProperty (galaxy.py:209-214 for typical values).
    Inherits Fire/CanFire/StopFiring/UpdateCharge from the mixin.
    """
    def __init__(self, name: str = ""):
        super().__init__(name)
        _init_energy_weapon_state(self)
        self._firing: bool = False
        self._target = None
        self._target_offset = None

    def GetMaxCharge(self) -> float:                return self._max_charge
    def GetMinFiringCharge(self) -> float:          return self._min_firing_charge
    def GetNormalDischargeRate(self) -> float:      return self._normal_discharge_rate
    def GetRechargeRate(self) -> float:             return self._recharge_rate
    def GetChargeLevel(self) -> float:              return self._charge_level

    def GetChargePercentage(self) -> float:
        if self._max_charge <= 0.0:
            return 0.0
        return self._charge_level / self._max_charge

    def SetChargeLevel(self, v) -> None:
        v = float(v)
        if v < 0.0:                self._charge_level = 0.0
        elif v > self._max_charge: self._charge_level = self._max_charge
        else:                      self._charge_level = v


class PulseWeapon(_EnergyWeaponFireMixin, WeaponSystem):
    """Individual pulse-weapon emitter under a parent PulseWeaponSystem
    (WeaponSystemProperty WST_PULSE).  Energy-weapon charge surface plus
    per-shot cooldown timer; see ships/Hardpoints/vorcha.py for SetCooldownTime
    call sites.  Inherits Fire/CanFire/StopFiring/UpdateCharge from the mixin.
    """
    def __init__(self, name: str = ""):
        super().__init__(name)
        _init_energy_weapon_state(self)
        self._firing: bool = False
        self._target = None
        self._target_offset = None
        self._cooldown_time: float = 0.0

    def GetMaxCharge(self) -> float:                return self._max_charge
    def GetMinFiringCharge(self) -> float:          return self._min_firing_charge
    def GetNormalDischargeRate(self) -> float:      return self._normal_discharge_rate
    def GetRechargeRate(self) -> float:             return self._recharge_rate
    def GetChargeLevel(self) -> float:              return self._charge_level
    def GetCooldownTime(self) -> float:             return self._cooldown_time

    def GetChargePercentage(self) -> float:
        if self._max_charge <= 0.0:
            return 0.0
        return self._charge_level / self._max_charge

    def SetChargeLevel(self, v) -> None:
        v = float(v)
        if v < 0.0:                self._charge_level = 0.0
        elif v > self._max_charge: self._charge_level = self._max_charge
        else:                      self._charge_level = v


class TractorBeam(_EnergyWeaponFireMixin, WeaponSystem):
    """Individual tractor-beam emitter under a parent TractorBeamSystem
    (WeaponSystemProperty WST_TRACTOR).  Same energy-weapon charge model
    as phasers; see galaxy.py:853-854 for typical values (aft tractors
    recharge=0.5, forward tractors 0.3).  Inherits Fire/CanFire/StopFiring/
    UpdateCharge from the mixin.
    """
    def __init__(self, name: str = ""):
        super().__init__(name)
        _init_energy_weapon_state(self)
        self._firing: bool = False
        self._target = None
        self._target_offset = None

    def GetMaxCharge(self) -> float:                return self._max_charge
    def GetMinFiringCharge(self) -> float:          return self._min_firing_charge
    def GetNormalDischargeRate(self) -> float:      return self._normal_discharge_rate
    def GetRechargeRate(self) -> float:             return self._recharge_rate
    def GetChargeLevel(self) -> float:              return self._charge_level

    def GetChargePercentage(self) -> float:
        if self._max_charge <= 0.0:
            return 0.0
        return self._charge_level / self._max_charge

    def SetChargeLevel(self, v) -> None:
        v = float(v)
        if v < 0.0:                self._charge_level = 0.0
        elif v > self._max_charge: self._charge_level = self._max_charge
        else:                      self._charge_level = v


class TorpedoTube(WeaponSystem):
    """Individual launcher under a parent TorpedoSystem.  Ammo-type tracking
    lives on the parent's slot table; this class owns per-tube reload state.

    Reload model (galaxy.py:28-30): ImmediateDelay=delay from fire request
    to launch, ReloadDelay=per-tube reload after firing, MaxReady=shots
    queued before reload begins.
    """
    def __init__(self, name: str = ""):
        super().__init__(name)
        self._num_ready: int = 0
        self._last_fire_time: float = float("-inf")
        self._immediate_delay: float = 0.0
        self._reload_delay: float = 0.0
        self._max_ready: int = 0
        self._firing: bool = False
        self._target = None
        self._target_offset = None

    def GetNumReady(self) -> int:                   return self._num_ready
    def SetNumReady(self, v) -> None:               self._num_ready = int(v)
    def IncNumReady(self) -> None:                  self._num_ready += 1
    def DecNumReady(self) -> None:                  self._num_ready -= 1
    def GetLastFireTime(self) -> float:             return self._last_fire_time
    def SetLastFireTime(self, v) -> None:           self._last_fire_time = float(v)
    def GetImmediateDelay(self) -> float:           return self._immediate_delay
    def GetReloadDelay(self) -> float:              return self._reload_delay
    def GetMaxReady(self) -> int:                   return self._max_ready

    def CanFire(self) -> int:
        parent = self.GetParentSubsystem()
        on = parent is not None and parent.IsOn()
        return 1 if (on and self._num_ready > 0) else 0

    def Fire(self, target=None, offset=None) -> None:
        if not self.CanFire():
            return
        self._firing = True
        self._target = target
        self._target_offset = offset
        self._num_ready -= 1
        import time as _time
        self._last_fire_time = _time.monotonic()

        # PR 2b: spawn the projectile via the bound SDK script.
        self._spawn_torpedo()

        # Discrete-shot — auto-stop after launch.  WeaponSystem's
        # _currently_firing list still tracks us until StopFiring is called.
        self._firing = False

    def _spawn_torpedo(self) -> None:
        """Look up the parent system's GetTorpedoScript(0), import the SDK
        projectile module, instantiate a Torpedo, call <module>.Create(t)
        to populate visuals + behaviour, compute initial velocity (homing
        if ship has a target lock, dumbfire from emitter direction
        otherwise), and play the launch sound.

        Silent no-op when no script is bound (matches BC for unconfigured
        tubes).  Per-tube slot routing is a future polish item — PR 2b
        always pulls from slot 0.
        """
        parent = self.GetParentSubsystem()
        if parent is None:
            return
        parent_prop = parent.GetProperty() if hasattr(parent, "GetProperty") else None
        if parent_prop is None or not hasattr(parent_prop, "GetTorpedoScript"):
            return
        script_name = parent_prop.GetTorpedoScript(0)
        if not script_name:
            return

        import importlib
        try:
            mod = importlib.import_module(script_name)
        except ImportError:
            return

        from engine.appc.projectiles import Torpedo, register
        from engine.appc.math import TGPoint3
        from engine.audio.tg_sound import TGSoundManager

        torp = Torpedo()
        source_ship = self._climb_to_ship()
        torp._source_ship = source_ship
        torp._position = self._emitter_world_position()

        mod.Create(torp)

        launch_speed = float(mod.GetLaunchSpeed()) if hasattr(mod, "GetLaunchSpeed") else 0.0

        target_ship = source_ship.GetTarget() if source_ship is not None else None
        if (target_ship is not None
                and hasattr(target_ship, "IsDead") and not target_ship.IsDead()):
            target_sub = (source_ship.GetTargetSubsystem()
                          if hasattr(source_ship, "GetTargetSubsystem") else None)
            aim_target = target_sub if target_sub is not None else target_ship
            aim_pt = aim_target.GetWorldLocation()
            direction = aim_pt - torp._position
            length = direction.Length()
            if length > 1e-6:
                torp._velocity = TGPoint3(
                    direction.x / length * launch_speed,
                    direction.y / length * launch_speed,
                    direction.z / length * launch_speed,
                )
            torp._target_ship = target_ship
            torp._target_subsystem = target_sub
        else:
            # The catch-all __getattr__ on TGObject returns a _Stub for any
            # missing attribute, so hasattr is misleading.  Probe for a valid
            # TGPoint3 explicitly via the type — defensive against the shim.
            forward = None
            try:
                got = self.GetDirection()
                if isinstance(got, TGPoint3):
                    forward = got
            except Exception:
                forward = None
            if forward is None:
                forward = TGPoint3(0.0, 1.0, 0.0)
            world_fwd = TGPoint3(forward.x, forward.y, forward.z)
            if source_ship is not None and hasattr(source_ship, "GetWorldRotation"):
                rot = source_ship.GetWorldRotation()
                # Same shim caveat — only use if it's a real TGMatrix3.
                from engine.appc.math import TGMatrix3
                if isinstance(rot, TGMatrix3):
                    world_fwd.MultMatrixLeft(rot)
            length = world_fwd.Length()
            if length > 1e-6:
                torp._velocity = TGPoint3(
                    world_fwd.x / length * launch_speed,
                    world_fwd.y / length * launch_speed,
                    world_fwd.z / length * launch_speed,
                )
            torp._target_ship = None

        register(torp)

        if hasattr(mod, "GetLaunchSound"):
            sound_name = mod.GetLaunchSound()
            if sound_name:
                TGSoundManager.instance().PlaySound(sound_name)

    def StopFiring(self) -> None:
        self._firing = False

    def IsFiring(self) -> int:
        return 1 if self._firing else 0

    def UpdateReload(self, dt: float) -> None:
        if self._num_ready >= self._max_ready:
            return
        import time as _time
        if _time.monotonic() - self._last_fire_time >= self._reload_delay:
            self._num_ready += 1
            self._last_fire_time = _time.monotonic()


class HullSubsystem(ShipSubsystem):
    """Live hull state.  Hull isn't a powered subsystem — it just tracks
    condition (max + current) so damage logic can read GetMaxCondition()."""
    pass


class SensorSubsystem(PoweredSubsystem):
    def __init__(self, name: str = ""):
        super().__init__(name)
        self._base_sensor_range: float = 0.0
        self._max_probes: int = 0

    def GetBaseSensorRange(self) -> float:           return self._base_sensor_range
    def SetBaseSensorRange(self, v) -> None:         self._base_sensor_range = float(v)
    def GetMaxProbes(self) -> int:                   return self._max_probes
    def SetMaxProbes(self, v) -> None:               self._max_probes = int(v)


class ImpulseEngineSubsystem(PoweredSubsystem):
    """Live impulse-engine state.  Speed/accel limits come from the
    matching ImpulseEngineProperty template via ShipClass.SetupProperties()."""

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._max_speed = 0.0
        self._max_accel = 0.0
        self._max_angular_velocity = 0.0
        self._max_angular_accel = 0.0

    def GetMaxSpeed(self) -> float:           return self._max_speed
    def SetMaxSpeed(self, v: float) -> None:  self._max_speed = float(v)
    def GetMaxAccel(self) -> float:           return self._max_accel
    def SetMaxAccel(self, v: float) -> None:  self._max_accel = float(v)
    def GetMaxAngularVelocity(self) -> float: return self._max_angular_velocity
    def SetMaxAngularVelocity(self, v: float) -> None:
        self._max_angular_velocity = float(v)
    def GetMaxAngularAccel(self) -> float:    return self._max_angular_accel
    def SetMaxAngularAccel(self, v: float) -> None:
        self._max_angular_accel = float(v)


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

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._warp_sequence = None
        self._warp_effect_time = 0.0
        self._warp_state = self.WES_NOT_WARPING

    def GetWarpSequence(self):
        return self._warp_sequence

    def SetWarpSequence(self, seq) -> None:
        self._warp_sequence = seq

    def GetWarpEffectTime(self) -> float:
        return self._warp_effect_time

    def SetWarpEffectTime(self, t: float) -> None:
        self._warp_effect_time = float(t)

    def GetWarpState(self) -> int:
        return self._warp_state

    def SetWarpState(self, state) -> None:
        self._warp_state = int(state)


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

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._max_shields:       list[float] = [0.0] * self.NUM_SHIELDS
        self._current_shields:   list[float] = [0.0] * self.NUM_SHIELDS
        self._charge_per_second: list[float] = [0.0] * self.NUM_SHIELDS

    def GetMaxShields(self, face: int) -> float:
        return self._max_shields[int(face)]

    def SetMaxShields(self, face: int, value: float) -> None:
        f = int(face)
        v = float(value)
        if self._current_shields[f] == 0.0:
            self._current_shields[f] = v
        self._max_shields[f] = v

    def GetCurrentShields(self, face: int) -> float:
        return self._current_shields[int(face)]

    def SetCurrentShields(self, face: int, value: float) -> None:
        self._current_shields[int(face)] = float(value)

    def SetCurShields(self, face: int, value: float) -> None:
        """SDK-facing alias of SetCurrentShields (matches Appc method name)."""
        self.SetCurrentShields(face, value)

    def GetSingleShieldPercentage(self, face: int) -> float:
        """current/max for the face; 0.0 when max==0 (unshielded face).

        SDK caller MissionLib.IsAnyShieldBreached treats anything <0.05 as
        a breach, so the max==0 case must return 0.0, not raise.
        """
        f = int(face)
        mx = self._max_shields[f]
        if mx == 0.0:
            return 0.0
        return self._current_shields[f] / mx

    def GetShieldChargePerSecond(self, face: int) -> float:
        return self._charge_per_second[int(face)]

    def SetShieldChargePerSecond(self, face: int, value: float) -> None:
        self._charge_per_second[int(face)] = float(value)

    def Update(self, dt: float) -> None:
        """Per-tick regen: current += charge_per_second * dt, clamped to max.

        Faces with max==0 are skipped so unshielded faces never accumulate.
        """
        dt = float(dt)
        for f in range(self.NUM_SHIELDS):
            mx = self._max_shields[f]
            if mx == 0.0:
                continue
            new = self._current_shields[f] + self._charge_per_second[f] * dt
            if new > mx:
                new = mx
            self._current_shields[f] = new

    def ApplyDamage(self, face: int, amount: float) -> float:
        """Drain current shields on the face; return damage overflow.

        Caller routes the returned overflow to hull. Does not trigger
        regen, fire events, or mutate any other face.
        """
        f = int(face)
        amt = float(amount)
        cur = self._current_shields[f]
        if amt <= cur:
            self._current_shields[f] = cur - amt
            return 0.0
        self._current_shields[f] = 0.0
        return amt - cur


class PowerSubsystem(ShipSubsystem):
    """Power plant — drives the ship's energy budget.

    Inherits ShipSubsystem (not PoweredSubsystem) to match SDK
    App.py:5710 where PowerSubsystem inherits ShipSubsystem directly.
    It generates power rather than consuming it.
    """
    pass


class RepairSubsystem(PoweredSubsystem):
    """Engineering / damage-control subsystem.  SDK App.py:6639 has
    RepairSubsystem(PoweredSubsystem) with internal repair-allocation
    state; Phase 1 ships only need the slot + property back-ref so the
    targets panel reflects the hardpoint."""
    pass


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
