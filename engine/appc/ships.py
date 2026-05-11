from engine.appc.objects import DamageableObject


class ShipClass(DamageableObject):
    WG_INVALID = 0
    WG_PRIMARY = 1
    WG_SECONDARY = 2
    WG_TERTIARY = 3
    WG_TRACTOR = 4
    GREEN_ALERT = 0
    YELLOW_ALERT = 1
    RED_ALERT = 2

    def __init__(self):
        super().__init__()
        self._ai = None
        self._net_type: int = 0
        # Subsystem slots — None until populated by hardpoint loader.
        # SDK callers commonly chain `pShip.GetTorpedoSystem().GetNumAmmoTypes()`
        # but typically guard with `if pSystem:` first.  See sdk/.../App.py:5394+.
        self._sensor_subsystem = None
        self._impulse_engine_subsystem = None
        self._warp_engine_subsystem = None
        self._torpedo_system = None
        self._phaser_system = None
        self._pulse_weapon_system = None
        self._tractor_beam_system = None
        # Hull is created lazily by SetupProperties() when a HullProperty is
        # found in the property set (SDK App.py:5382-5383).  Stays None for
        # ships with no hardpoint applied.
        self._hull = None
        # Targeting state
        self._target = None
        self._target_subsystem = None
        # Lifecycle flags — IsDocked/IsDying/IsDead drive cutscene + game-over
        # branching in MissionLib and per-mission scripts.  Defaults are
        # the "alive, undocked, not dying" state that a freshly-spawned ship
        # has at mission start.
        self._docked = False
        self._dying = False
        self._dead = False

    def SetAI(self, ai) -> None:
        self._ai = ai

    def GetAI(self):
        return self._ai

    def SetNetType(self, net_type: int) -> None:
        self._net_type = net_type

    def GetNetType(self) -> int:
        return self._net_type

    # ── Subsystem accessors ──────────────────────────────────────────────────
    # Mirror sdk/.../App.py:5394-5455.  Loaders that need to populate these
    # call the matching Set*Subsystem method (Phase 2 hardpoint integration).

    def GetSensorSubsystem(self):                 return self._sensor_subsystem
    def SetSensorSubsystem(self, s) -> None:      self._sensor_subsystem = s
    def GetImpulseEngineSubsystem(self):          return self._impulse_engine_subsystem
    def SetImpulseEngineSubsystem(self, s) -> None: self._impulse_engine_subsystem = s
    def GetWarpEngineSubsystem(self):             return self._warp_engine_subsystem
    def SetWarpEngineSubsystem(self, s) -> None:  self._warp_engine_subsystem = s
    def GetTorpedoSystem(self):                   return self._torpedo_system
    def SetTorpedoSystem(self, s) -> None:        self._torpedo_system = s
    def GetPhaserSystem(self):                    return self._phaser_system
    def SetPhaserSystem(self, s) -> None:         self._phaser_system = s
    def GetPulseWeaponSystem(self):               return self._pulse_weapon_system
    def SetPulseWeaponSystem(self, s) -> None:    self._pulse_weapon_system = s
    def GetTractorBeamSystem(self):               return self._tractor_beam_system
    def SetTractorBeamSystem(self, s) -> None:    self._tractor_beam_system = s
    def GetHull(self):                            return self._hull
    def SetHull(self, h) -> None:                 self._hull = h

    # ── Property -> subsystem dispatch ───────────────────────────────────────
    # Walks self.GetPropertySet() and copies template values onto the live
    # ship + subsystems.  Mirrors SDK loadspacehelper.py:94 — called once,
    # right after the hardpoint module's LoadPropertySet() populates the set.
    #
    # Scope: Ship (mass, inertia), Impulse, Warp, Hull.  Other subsystems
    # (phasers, shields, sensors, torpedoes, repair, cloak, power) keep their
    # constructor defaults until a caller proves they need plumbing.

    def SetupProperties(self) -> None:
        from engine.appc.properties import (
            ShipProperty, ImpulseEngineProperty, WarpEngineProperty,
            HullProperty,
        )
        from engine.appc.subsystems import HullSubsystem

        for prop in self.GetPropertySet().GetPropertyList():
            if isinstance(prop, ShipProperty):
                m = prop.GetMass()
                if m is not None: self.SetMass(m)
                ri = prop.GetRotationalInertia()
                if ri is not None: self.SetRotationalInertia(ri)
            elif isinstance(prop, ImpulseEngineProperty):
                self._copy_powered_subsystem_fields(prop, self._impulse_engine_subsystem)
                ies = self._impulse_engine_subsystem
                if ies is not None:
                    for src, setter in (
                        (prop.GetMaxSpeed,           ies.SetMaxSpeed),
                        (prop.GetMaxAccel,           ies.SetMaxAccel),
                        (prop.GetMaxAngularVelocity, ies.SetMaxAngularVelocity),
                        (prop.GetMaxAngularAccel,    ies.SetMaxAngularAccel),
                    ):
                        v = src()
                        if v is not None: setter(v)
            elif isinstance(prop, WarpEngineProperty):
                self._copy_powered_subsystem_fields(prop, self._warp_engine_subsystem)
            elif isinstance(prop, HullProperty):
                # Only the FIRST HullProperty is the main hull — galaxy.py
                # registers "Hull" first then "Bridge" as a child component.
                # GetHull() must return the primary hull (SDK App.py:5382).
                if self._hull is None:
                    self._hull = HullSubsystem(prop.GetName() or "Hull")
                    mc = prop.GetMaxCondition()
                    if mc is not None: self._hull.SetMaxCondition(mc)

    @staticmethod
    def _copy_powered_subsystem_fields(prop, subsystem) -> None:
        if subsystem is None:
            return
        mc = prop.GetMaxCondition()
        if mc is not None: subsystem.SetMaxCondition(mc)
        np = prop.GetNormalPowerPerSecond()
        if np is not None: subsystem.SetNormalPowerPerSecond(np)

    # ── Targeting ────────────────────────────────────────────────────────────
    def GetTarget(self):                          return self._target
    def SetTarget(self, target) -> None:          self._target = target
    def GetTargetSubsystem(self):                 return self._target_subsystem
    def SetTargetSubsystem(self, s) -> None:      self._target_subsystem = s

    # ── Lifecycle state ──────────────────────────────────────────────────────
    def IsDocked(self) -> int:    return 1 if self._docked else 0
    def SetDocked(self, v) -> None:
        self._docked = bool(v)
    def IsDying(self) -> int:     return 1 if self._dying else 0
    def SetDying(self, v) -> None:
        self._dying = bool(v)
    def IsDead(self) -> int:      return 1 if self._dead else 0
    def SetDead(self, v=True) -> None:
        # Single-arg form (truthy) and zero-arg form (sets dead) both used.
        new_dead = bool(v) if v is not True else True
        was_dead = self._dead
        self._dead = new_dead
        if new_dead and not was_dead:
            from engine.appc import ship_lifecycle
            ship_lifecycle.publish_destroyed(self)

    # ── Subsystem iteration ───────────────────────────────────────────────────
    # Phase 1 ships have no subsystems registered for matching; these stubs
    # terminate while-loops that follow the SDK pattern:
    #   kIter = pShip.StartGetSubsystemMatch(type)
    #   pSub  = pShip.GetNextSubsystemMatch(kIter)
    #   while (pSub != None): ...

    def StartGetSubsystemMatch(self, match_type=None):
        return None

    def GetNextSubsystemMatch(self, iterator=None):
        return None

    def EndGetSubsystemMatch(self, iterator=None):
        pass


def ShipClass_Create(class_name: str = "") -> ShipClass:
    """Construct a ShipClass with default empty subsystem instances.

    Mirrors Appc's ShipClass constructor which allocates default subsystem
    objects so that `pShip.GetTorpedoSystem().SetAmmoType(...)` works on a
    freshly-created ship before SetupProperties is called.  Mission scripts
    rely on this pattern (E2M0:720, E2M2:467, E5M2:307, E3M5:243) without
    null-guarding — so the ships factory must hand back a fully-furnished
    ship instance.
    """
    from engine.appc.subsystems import (
        TorpedoSystem, PhaserSystem, PulseWeaponSystem, TractorBeamSystem,
        SensorSubsystem, ImpulseEngineSubsystem, WarpEngineSubsystem,
    )
    ship = ShipClass()
    ship.SetName(class_name)
    ship.SetTorpedoSystem(TorpedoSystem("Torpedo System"))
    ship.SetPhaserSystem(PhaserSystem("Phaser System"))
    ship.SetPulseWeaponSystem(PulseWeaponSystem("Pulse Weapon System"))
    ship.SetTractorBeamSystem(TractorBeamSystem("Tractor Beam System"))
    ship.SetSensorSubsystem(SensorSubsystem("Sensor Subsystem"))
    ship.SetImpulseEngineSubsystem(ImpulseEngineSubsystem("Impulse Engines"))
    ship.SetWarpEngineSubsystem(WarpEngineSubsystem("Warp Engines"))
    return ship


def ShipClass_GetObject(pSet, name: str) -> "ShipClass | None":
    if pSet is None:
        from engine.appc.sets import SetClass_GetNull
        pSet = SetClass_GetNull()
    obj = pSet.GetObject(name)
    if isinstance(obj, ShipClass):
        return obj
    return None


def ShipClass_Cast(obj) -> "ShipClass | None":
    if isinstance(obj, ShipClass):
        return obj
    return None


def ShipClass_GetObjectByID(obj_id: int) -> "ShipClass | None":
    from engine.core.ids import get_object_by_id
    obj = get_object_by_id(obj_id)
    if isinstance(obj, ShipClass):
        return obj
    return None
