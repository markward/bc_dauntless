from engine.appc.objects import DamageableObject
from engine.appc.math import TGPoint3


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
        self._shield_subsystem = None
        self._power_subsystem = None
        self._repair_subsystem = None
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
        # Ship-level identity populated by SetupProperties from ShipProperty.
        self._genus: int = 0
        self._species: int = 0
        self._affiliation: int = 0
        self._ship_name: str = ""
        self._ai_string: str = ""
        self._damage_resolution: float = 0.0
        self._model_filename: str = ""
        self._stationary: int = 0
        self._death_explosion_sound: str = ""
        # Alert level — GREEN at spawn matches MissionLib.py:605, which
        # explicitly resets the player to GREEN_ALERT on mission start.
        # BC's BridgeHandlers.SetAlertLevel forwards the event to the
        # XO menu (see sdk/.../BridgeHandlers.py:194); shield/weapon
        # side-effects happen downstream of XO, not here.
        self._alert_level: int = ShipClass.GREEN_ALERT
        # Setpoints are AI-written; _current_* are integrator-owned and
        # ramp toward those setpoints each tick.
        # Setpoints default to None (no AI input yet) — explicitly stored
        # as real instance attrs so getattr() returns None instead of the
        # TGObject __getattr__ _Stub fallback. The integrator's
        # no-setpoint early-out depends on this.
        self._speed_setpoint = None
        self._target_angular_velocity_setpoint = None
        self._current_speed: float = 0.0
        self._current_angular_velocity: TGPoint3 = TGPoint3(0.0, 0.0, 0.0)

    def SetAI(self, ai) -> None:
        self._ai = ai

    def GetAI(self):
        return self._ai

    # ── Motion setpoints (AI-driven, no physics yet) ─────────────────────────
    # Stay, GoForward, Intercept, et al. call SetSpeed/SetTargetAngularVelocityDirect
    # each AI tick. The Phase-1 slice records the most-recent setpoint so tests
    # can assert "Stay drove speed to 0 and angular velocity to zero." The full
    # PD-solver + Bullet integration lives in the deferred Step 4 of the AI
    # runtime plan.

    def SetSpeed(self, speed, direction, frame) -> None:
        # Defensively copy the direction vec — many SDK call sites pass
        # App.TGPoint3_GetModelForward() (a fresh constant per call,
        # safe) but others reuse a stack-local TGPoint3 and mutate it
        # after the call. Copying here makes SetSpeed's contract
        # independent of caller hygiene. Mirrors the existing copy in
        # SetTargetAngularVelocityDirect.
        self._speed_setpoint = (
            float(speed),
            TGPoint3(direction.x, direction.y, direction.z),
            int(frame),
        )

    def SetImpulse(self, speed, direction, frame) -> None:
        """SDK alias used by AI.PlainAI.GoForward.Update (sdk/.../GoForward.py).

        Records into the same _speed_setpoint tuple as SetSpeed —
        downstream the integrator can't tell which entry point the AI
        used."""
        self.SetSpeed(speed, direction, frame)

    def GetSpeedSetpoint(self):
        return getattr(self, "_speed_setpoint", None)

    def SetTargetAngularVelocityDirect(self, vec) -> None:
        # Defensive copy — vec is a TGPoint3 the caller may mutate.
        from engine.appc.math import TGPoint3
        self._target_angular_velocity_setpoint = TGPoint3(vec.x, vec.y, vec.z)

    def GetTargetAngularVelocitySetpoint(self):
        return getattr(self, "_target_angular_velocity_setpoint", None)

    def SetNetType(self, net_type: int) -> None:
        self._net_type = net_type

    def GetNetType(self) -> int:
        return self._net_type

    # ── Ship-level identity ──────────────────────────────────────────────────
    def GetGenus(self) -> int:                          return self._genus
    def SetGenus(self, v) -> None:                      self._genus = int(v)
    def GetSpecies(self) -> int:                        return self._species
    def SetSpecies(self, v) -> None:                    self._species = int(v)
    def GetAffiliation(self) -> int:                    return self._affiliation
    def SetAffiliation(self, v) -> None:                self._affiliation = int(v)
    def GetShipName(self) -> str:                       return self._ship_name
    def SetShipName(self, v) -> None:                   self._ship_name = str(v)
    def GetAIString(self) -> str:                       return self._ai_string
    def SetAIString(self, v) -> None:                   self._ai_string = str(v)
    def GetDamageResolution(self) -> float:             return self._damage_resolution
    def SetDamageResolution(self, v) -> None:           self._damage_resolution = float(v)
    def GetModelFilename(self) -> str:                  return self._model_filename
    def SetModelFilename(self, v) -> None:              self._model_filename = str(v)
    def IsStationary(self) -> int:                      return self._stationary
    def SetStationary(self, v) -> None:                 self._stationary = int(v)
    def GetDeathExplosionSound(self) -> str:            return self._death_explosion_sound
    def SetDeathExplosionSound(self, v) -> None:        self._death_explosion_sound = str(v)

    # ── Alert level ──────────────────────────────────────────────────────────
    # SDK callers: MissionLib.py:605 (reset to GREEN at mission start),
    # BridgeHandlers.py:1442 (bridge crew behavior keys off this).
    def GetAlertLevel(self) -> int:                     return self._alert_level

    def SetAlertLevel(self, v) -> None:
        """Apply the alert-level → weapon-power policy.

        Red alert powers phasers / torpedoes / pulse weapons on; any other
        level powers them off.  Tractor stays under manual control (mirrors
        BC: tractor is toggled by its own UI, not by alert).  In stock BC
        this side-effect flows through the XO menu after BridgeHandlers.
        SetAlertLevel; we collapse that layer until the bridge menu system
        is wired.
        """
        self._alert_level = int(v)
        on = (self._alert_level == ShipClass.RED_ALERT)
        for slot in (self._phaser_system, self._torpedo_system,
                     self._pulse_weapon_system):
            if slot is None:
                continue
            if on:
                slot.TurnOn()
                slot.SetPowerPercentageWanted(1.0)
            else:
                slot.TurnOff()
                slot.SetPowerPercentageWanted(0.0)

    # ── Subsystem accessors ──────────────────────────────────────────────────
    # Mirror sdk/.../App.py:5394-5455.  Loaders that need to populate these
    # call the matching Set*Subsystem method (Phase 2 hardpoint integration).

    def _attach_subsystem(self, s):
        """Wire a freshly-attached subsystem back to this ship so emitters
        can climb the parent chain to reach the ShipClass at fire-time."""
        if s is not None and hasattr(s, "SetParentShip"):
            s.SetParentShip(self)
        return s

    def GetSensorSubsystem(self):                 return self._sensor_subsystem
    def SetSensorSubsystem(self, s) -> None:      self._sensor_subsystem = self._attach_subsystem(s)
    def GetImpulseEngineSubsystem(self):          return self._impulse_engine_subsystem
    def SetImpulseEngineSubsystem(self, s) -> None: self._impulse_engine_subsystem = self._attach_subsystem(s)
    def GetWarpEngineSubsystem(self):             return self._warp_engine_subsystem
    def SetWarpEngineSubsystem(self, s) -> None:  self._warp_engine_subsystem = self._attach_subsystem(s)
    def GetTorpedoSystem(self):                   return self._torpedo_system
    def SetTorpedoSystem(self, s) -> None:        self._torpedo_system = self._attach_subsystem(s)
    def GetPhaserSystem(self):                    return self._phaser_system
    def SetPhaserSystem(self, s) -> None:         self._phaser_system = self._attach_subsystem(s)
    def GetPulseWeaponSystem(self):               return self._pulse_weapon_system
    def SetPulseWeaponSystem(self, s) -> None:    self._pulse_weapon_system = self._attach_subsystem(s)
    def GetTractorBeamSystem(self):               return self._tractor_beam_system
    def SetTractorBeamSystem(self, s) -> None:    self._tractor_beam_system = self._attach_subsystem(s)

    # ── Weapon-group lookup by WG_* enum ─────────────────────────────────────
    # Matches sdk/.../TacticalInterfaceHandlers.py:387-405 dispatch.  PR 2's
    # FireWeapons event handler calls this; included now so the surface is
    # ready when that wiring lands.
    def GetWeaponSystemGroup(self, eGroup: int):
        if eGroup == ShipClass.WG_PRIMARY:
            return self._phaser_system
        if eGroup == ShipClass.WG_SECONDARY:
            return self._torpedo_system
        if eGroup == ShipClass.WG_TERTIARY:
            return self._pulse_weapon_system
        if eGroup == ShipClass.WG_TRACTOR:
            return self._tractor_beam_system
        return None

    def GetShieldSubsystem(self):                 return self._shield_subsystem
    def SetShieldSubsystem(self, s) -> None:      self._shield_subsystem = s
    # SDK-facing alias — pShip.GetShields() in mission scripts and SDK helpers.
    def GetShields(self):                         return self._shield_subsystem
    def GetPowerSubsystem(self):                  return self._power_subsystem
    def SetPowerSubsystem(self, s) -> None:       self._power_subsystem = s
    def GetRepairSubsystem(self):                 return self._repair_subsystem
    def SetRepairSubsystem(self, s) -> None:      self._repair_subsystem = s
    def GetHull(self):                            return self._hull
    def SetHull(self, h) -> None:                 self._hull = h

    def GetSubsystemByProperty(self, prop):
        """Find the live subsystem whose source property is `prop`.

        Mirrors sdk/.../App.py:5438 — the SDK calls this from
        loadspacehelper.AdjustShipForDifficulty to map each
        SubsystemProperty in the ship's property set to its live
        subsystem instance.  Returns None if no slot matches.
        """
        for sub in (
            self._sensor_subsystem,
            self._impulse_engine_subsystem,
            self._warp_engine_subsystem,
            self._torpedo_system,
            self._phaser_system,
            self._pulse_weapon_system,
            self._tractor_beam_system,
            self._shield_subsystem,
            self._power_subsystem,
            self._repair_subsystem,
            self._hull,
        ):
            if sub is not None and sub.GetProperty() is prop:
                return sub
        return None

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
            HullProperty, SensorProperty, ShieldProperty,
            WeaponSystemProperty, TorpedoTubeProperty,
            PowerProperty, RepairSubsystemProperty,
        )
        from engine.appc.subsystems import HullSubsystem
        import App

        def _copy_name(prop, receiver):
            if receiver is None: return
            n = prop.GetName()
            if n: receiver.SetName(n)

        for prop in self.GetPropertySet().GetPropertyList():
            if isinstance(prop, ShipProperty):
                for src, setter in (
                    (prop.GetMass,                 self.SetMass),
                    (prop.GetRotationalInertia,    self.SetRotationalInertia),
                    (prop.GetGenus,                self.SetGenus),
                    (prop.GetSpecies,              self.SetSpecies),
                    (prop.GetAffiliation,          self.SetAffiliation),
                    (prop.GetShipName,             self.SetShipName),
                    (prop.GetAIString,             self.SetAIString),
                    (prop.GetDamageResolution,     self.SetDamageResolution),
                    (prop.GetModelFilename,        self.SetModelFilename),
                    (prop.GetStationary,           self.SetStationary),
                    (prop.GetDeathExplosionSound,  self.SetDeathExplosionSound),
                ):
                    v = src()
                    if v is not None: setter(v)
            elif isinstance(prop, ImpulseEngineProperty):
                self._copy_powered_subsystem_fields(prop, self._impulse_engine_subsystem)
                ies = self._impulse_engine_subsystem
                if ies is not None:
                    _copy_name(prop, ies)
                    ies.SetProperty(prop)
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
                if self._warp_engine_subsystem is not None:
                    _copy_name(prop, self._warp_engine_subsystem)
                    self._warp_engine_subsystem.SetProperty(prop)
            elif isinstance(prop, HullProperty):
                # Only the FIRST HullProperty is the main hull — galaxy.py
                # registers "Hull" first then "Bridge" as a child component.
                # GetHull() must return the primary hull (SDK App.py:5382).
                if self._hull is None:
                    self._hull = HullSubsystem(prop.GetName() or "Hull")
                    self._hull.SetProperty(prop)
                    for src, setter in (
                        (prop.GetMaxCondition,        self._hull.SetMaxCondition),
                        (prop.GetCritical,            self._hull.SetCritical),
                        (prop.GetTargetable,          self._hull.SetTargetable),
                        (prop.GetPrimary,             self._hull.SetPrimary),
                        (prop.GetRadius,              self._hull.SetRadius),
                        (prop.GetDisabledPercentage,  self._hull.SetDisabledPercentage),
                    ):
                        v = src()
                        if v is not None: setter(v)
            elif isinstance(prop, SensorProperty):
                self._copy_powered_subsystem_fields(prop, self._sensor_subsystem)
                sens = self._sensor_subsystem
                if sens is not None:
                    _copy_name(prop, sens)
                    sens.SetProperty(prop)
                    for src, setter in (
                        (prop.GetBaseSensorRange, sens.SetBaseSensorRange),
                        (prop.GetMaxProbes,       sens.SetMaxProbes),
                    ):
                        v = src()
                        if v is not None: setter(v)
            elif isinstance(prop, ShieldProperty):
                self._copy_powered_subsystem_fields(prop, self._shield_subsystem)
                ss = self._shield_subsystem
                if ss is not None:
                    _copy_name(prop, ss)
                    ss.SetProperty(prop)
                    for face in range(ShieldProperty.NUM_SHIELDS):
                        mx = prop.GetMaxShields(face)
                        if mx is not None: ss.SetMaxShields(face, mx)
                        cr = prop.GetShieldChargePerSecond(face)
                        if cr is not None: ss.SetShieldChargePerSecond(face, cr)
            elif isinstance(prop, WeaponSystemProperty):
                wst = prop.GetWeaponSystemType()
                receiver = {
                    WeaponSystemProperty.WST_PHASER:  self._phaser_system,
                    WeaponSystemProperty.WST_TORPEDO: self._torpedo_system,
                    WeaponSystemProperty.WST_PULSE:   self._pulse_weapon_system,
                    WeaponSystemProperty.WST_TRACTOR: self._tractor_beam_system,
                }.get(wst)
                if receiver is not None:
                    _copy_name(prop, receiver)
                    self._copy_powered_subsystem_fields(prop, receiver)
                    receiver.SetProperty(prop)
                    if wst is not None: receiver.SetWeaponSystemType(wst)
                    # Phaser-only extras (no-op for other receivers).
                    if wst == WeaponSystemProperty.WST_PHASER:
                        sf = prop.GetSingleFire()
                        if sf is not None: receiver.SetSingleFire(sf)
                        aw = prop.GetAimedWeapon()
                        if aw is not None: receiver.SetAimedWeapon(aw)
            elif isinstance(prop, PowerProperty):
                ps = self._power_subsystem
                if ps is not None:
                    _copy_name(prop, ps)
                    ps.SetProperty(prop)
                    mc = prop.GetMaxCondition()
                    if mc is not None: ps.SetMaxCondition(mc)
            elif isinstance(prop, RepairSubsystemProperty):
                rs = self._repair_subsystem
                if rs is not None:
                    _copy_name(prop, rs)
                    self._copy_powered_subsystem_fields(prop, rs)
                    rs.SetProperty(prop)

        # Pass 2 — seed torpedo tubes (idempotent).
        ts = self._torpedo_system
        if ts is not None and ts.GetNumAmmoTypes() == 0:
            tube_count = sum(
                1
                for prop in self.GetPropertySet().GetPropertyList()
                if isinstance(prop, TorpedoTubeProperty)
            )
            for _ in range(tube_count):
                ts.AddAmmoType(App.AT_ONE)

        # Pass 3 — drop slots the hardpoint never claimed.  ShipClass_Create
        # pre-allocates every subsystem so SDK callers can chain
        # `pShip.GetTorpedoSystem().SetAmmoType(...)` without null-guarding;
        # SetProperty above wired up the slots whose template was actually in
        # the property set.  A None back-reference here means the hardpoint
        # never registered the matching SubsystemProperty — that slot is a
        # default-construction leak and should not appear in target panels,
        # difficulty scaling, or any "what does this ship have" query.
        for attr in (
            "_sensor_subsystem", "_impulse_engine_subsystem",
            "_warp_engine_subsystem", "_torpedo_system",
            "_phaser_system", "_pulse_weapon_system",
            "_tractor_beam_system", "_shield_subsystem",
            "_power_subsystem", "_repair_subsystem",
        ):
            sub = getattr(self, attr)
            if sub is not None and sub.GetProperty() is None:
                setattr(self, attr, None)

        # Pass 4 — child weapons.  For each child WeaponProperty in the set,
        # instantiate the matching live subsystem and attach it under the
        # parent WeaponSystem slot via AddChildSubsystem.  Skip when the
        # parent slot was scrubbed in Pass 3 (orphan hardpoint).
        #
        # Idempotent — if the parent already has children, this pass is a
        # no-op for the corresponding property type.
        from engine.appc.properties import (
            PhaserProperty, PulseWeaponProperty,
            TractorBeamProperty as _TBP, TorpedoTubeProperty as _TTP,
        )
        from engine.appc.subsystems import (
            PhaserBank, PulseWeapon, TractorBeam, TorpedoTube,
        )

        def _copy_energy_weapon_fields(child, prop):
            """Copy MaxCharge/MinFiringCharge/Normal-Discharge/Recharge from
            property to runtime emitter.  Seeds charge to full on init."""
            v = prop.GetMaxCharge()
            if v is not None: child._max_charge = float(v)
            v = prop.GetMinFiringCharge()
            if v is not None: child._min_firing_charge = float(v)
            v = prop.GetNormalDischargeRate()
            if v is not None: child._normal_discharge_rate = float(v)
            v = prop.GetRechargeRate()
            if v is not None: child._recharge_rate = float(v)
            # Fresh ships spawn with phasers/pulse/tractors fully charged.
            child._charge_level = child._max_charge

        def _copy_pulse_weapon_fields(child, prop):
            v = prop.GetCooldownTime()
            if v is not None: child._cooldown_time = float(v)

        def _copy_torpedo_tube_fields(tube, prop):
            """Copy reload constants, then preload tubes to MaxReady."""
            v = prop.GetImmediateDelay()
            if v is not None: tube._immediate_delay = float(v)
            v = prop.GetReloadDelay()
            if v is not None: tube._reload_delay = float(v)
            v = prop.GetMaxReady()
            if v is not None: tube._max_ready = int(v)
            tube._num_ready = tube._max_ready

        _CHILD_DISPATCH = (
            (PhaserProperty,      "_phaser_system",        PhaserBank),
            (PulseWeaponProperty, "_pulse_weapon_system",  PulseWeapon),
            (_TBP,                "_tractor_beam_system",  TractorBeam),
            (_TTP,                "_torpedo_system",       TorpedoTube),
        )
        # Build a "parent already populated" guard so re-runs are no-ops.
        _parents_with_children = set()
        for _, attr, _ in _CHILD_DISPATCH:
            p = getattr(self, attr)
            if p is not None and p.GetNumChildSubsystems() > 0:
                _parents_with_children.add(attr)

        for prop in self.GetPropertySet().GetPropertyList():
            # Use type(prop) not isinstance — we want the leaf classes only.
            for prop_cls, parent_attr, child_cls in _CHILD_DISPATCH:
                if type(prop) is not prop_cls:
                    continue
                if parent_attr in _parents_with_children:
                    break
                parent = getattr(self, parent_attr)
                if parent is None:
                    break  # parent scrubbed; orphan property
                child = child_cls(prop.GetName() or "")
                child.SetProperty(prop)
                mc = prop.GetMaxCondition()
                if mc is not None: child.SetMaxCondition(mc)

                if isinstance(child, PhaserBank):
                    _copy_energy_weapon_fields(child, prop)
                elif isinstance(child, PulseWeapon):
                    _copy_energy_weapon_fields(child, prop)
                    _copy_pulse_weapon_fields(child, prop)
                elif isinstance(child, TractorBeam):
                    _copy_energy_weapon_fields(child, prop)
                elif isinstance(child, TorpedoTube):
                    _copy_torpedo_tube_fields(child, prop)

                parent.AddChildSubsystem(child)
                break

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
        ShieldSubsystem, PowerSubsystem, RepairSubsystem,
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
    ship.SetShieldSubsystem(ShieldSubsystem("Shield Generator"))
    ship.SetPowerSubsystem(PowerSubsystem("Power Plant"))
    ship.SetRepairSubsystem(RepairSubsystem("Engineering"))
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
