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
        """SDK semantic: ``speed`` is a *fraction* of the ship's
        ImpulseEngine max speed (0.0..1.0, or negative for reverse).

        Evidence in sdk/.../AI/PlainAI/: Flee.py:38 names the argument
        ``fSpeedFraction``; PhaserSweep.py:92 is ``SetSpeedFraction``;
        FollowObject.py:67 defaults ``fGoFastSpeed = 1.0`` and
        multiplies by fuzzy weights in [0, 1] before passing through
        SetImpulse. By contrast SetSpeed takes an absolute m/s value
        (Intercept.py:243 passes ``fSpeed = fMaxSpeed``).

        We multiply by MaxSpeed here so the integrator can keep
        treating ``_speed_setpoint`` as absolute m/s — that keeps the
        single integration path simple and matches the way the
        player-control code on the live path already produces
        absolute m/s.

        Fallback for ships without an IES (or with MaxSpeed == 0):
        store as-is. Many headless tests construct bare ShipClass
        instances and rely on the literal-pass-through behaviour;
        this guard avoids breaking them and matches the pattern in
        _PlayerControl._max_accel.
        """
        ies = self.GetImpulseEngineSubsystem()
        max_speed = ies.GetMaxSpeed() if ies is not None else 0.0
        if max_speed > 0.0:
            speed = float(speed) * max_speed
        self.SetSpeed(speed, direction, frame)

    def GetSpeedSetpoint(self):
        return getattr(self, "_speed_setpoint", None)

    def SetTargetAngularVelocityDirect(self, vec) -> None:
        # Defensive copy — vec is a TGPoint3 the caller may mutate.
        from engine.appc.math import TGPoint3
        self._target_angular_velocity_setpoint = TGPoint3(vec.x, vec.y, vec.z)

    def GetTargetAngularVelocitySetpoint(self):
        return getattr(self, "_target_angular_velocity_setpoint", None)

    # ── Pure-math kinematic helpers ──────────────────────────────────────────
    # No state read/written beyond the explicit arg list (GetPredictedPosition)
    # or the ship's world transform (GetRelativePositionInfo).  SDK signatures
    # live on PhysicsObjectClass; canonical callers are AI.PlainAI.TurnToOrientation
    # and the Intercept family.
    def GetPredictedPosition(self, p, v, a, t):
        """Kinematic forecast: p + v*t + 0.5*a*t²."""
        t2_half = 0.5 * t * t
        return TGPoint3(
            p.x + v.x * t + a.x * t2_half,
            p.y + v.y * t + a.y * t2_half,
            p.z + v.z * t + a.z * t2_half,
        )

    def GetRelativePositionInfo(self, target_vec):
        """Geometry of a world-space point relative to this ship.

        Returns (diff_vec, distance, unit_dir, angle_off_forward_rad)
        where diff_vec = target - ship_world_location,
        distance = |diff_vec|, unit_dir = diff_vec / distance
        (zero vec if distance ≈ 0), and angle_off_forward is the angle
        between unit_dir and the ship's world-forward (model-Y mapped
        through GetWorldRotation()).
        """
        import math as _math
        loc = self.GetWorldLocation()
        diff = TGPoint3(
            target_vec.x - loc.x,
            target_vec.y - loc.y,
            target_vec.z - loc.z,
        )
        distance = diff.Length()
        if distance < 1e-9:
            return diff, 0.0, TGPoint3(0.0, 0.0, 0.0), 0.0
        unit = TGPoint3(diff.x / distance, diff.y / distance, diff.z / distance)
        # World-forward = R · model_forward = column 1 of R; see
        # CLAUDE.md ↦ "Rotation matrix convention".
        forward = self.GetWorldRotation().GetCol(1)
        # Clamp to acos domain to guard against FP drift outside [-1, 1].
        cos_a = unit.x * forward.x + unit.y * forward.y + unit.z * forward.z
        if cos_a > 1.0: cos_a = 1.0
        elif cos_a < -1.0: cos_a = -1.0
        angle = _math.acos(cos_a)
        return diff, distance, unit, angle

    def TurnDirectionsToDirections(self, primary_from, primary_to,
                                   secondary_from=None, secondary_to=None) -> float:
        """Compute the angular velocity needed to rotate primary_from
        onto primary_to (and secondary_from onto secondary_to around
        the primary axis), call SetTargetAngularVelocityDirect, return
        an estimate of seconds until alignment completes.

        Called by AI.PlainAI.TurnToOrientation.Update (sdk/.../
        TurnToOrientation.py) each tick (0.5 s cadence).

        Algorithm:
          1. Primary alignment: axis = pf × pt; angle = acos(pf · pt).
             Degenerate case (vectors collinear, angle ≈ π): pick an
             arbitrary perpendicular axis (cross with world up; if
             still collinear, cross with world right).
          2. Secondary constraint (skipped when secondary_from or
             secondary_to has magnitude 0): compute signed roll angle
             between projections of sf and st onto the plane
             perpendicular to primary_to. Add roll * primary_to to
             the angular velocity.
          3. Clamp per-axis magnitude to GetMaxAngularVelocity()
             (FALLBACK_MAX_ACCEL when the IES isn't populated).
          4. SetTargetAngularVelocityDirect(angular_velocity).
          5. Return total_angle / max_angular_velocity (loose
             estimate; TurnToOrientation uses it only when
             bDoneOnLineup=1, and that's gated separately).
        """
        import math as _math

        # Normalised copies — avoid mutating caller vecs.
        pf = TGPoint3(primary_from.x, primary_from.y, primary_from.z); pf.Unitize()
        pt = TGPoint3(primary_to.x, primary_to.y, primary_to.z); pt.Unitize()

        # 1. Primary alignment.
        cos_a = pf.Dot(pt)
        if cos_a > 1.0: cos_a = 1.0
        elif cos_a < -1.0: cos_a = -1.0
        primary_angle = _math.acos(cos_a)

        axis = pf.Cross(pt)
        axis_len = axis.Length()
        if axis_len < 1e-9:
            # Collinear: either aligned (angle 0, return zero AV) or
            # opposite (angle π, need a perpendicular axis).
            if primary_angle < 1e-6:
                axis = TGPoint3(0.0, 0.0, 0.0)
            else:
                # Pick an arbitrary perpendicular.
                world_up = TGPoint3(0.0, 0.0, 1.0)
                candidate = pf.Cross(world_up)
                if candidate.Length() < 1e-6:
                    world_right = TGPoint3(1.0, 0.0, 0.0)
                    candidate = pf.Cross(world_right)
                candidate.Unitize()
                axis = candidate
        else:
            axis.Scale(1.0 / axis_len)  # unit primary rotation axis

        # Angular velocity contribution from primary: magnitude = angle.
        av_x = axis.x * primary_angle
        av_y = axis.y * primary_angle
        av_z = axis.z * primary_angle

        # 2. Secondary constraint.
        # SDK callers (AI/PlainAI/Defensive.py:125, AI/PlainAI/TorpedoRun.py:207)
        # invoke the 2-arg form — no secondary alignment.  Treat that as the
        # zero-magnitude case the algorithm already handles.
        if secondary_from is None or secondary_to is None:
            sf_len = 0.0
            st_len = 0.0
        else:
            sf_len = (secondary_from.x ** 2 + secondary_from.y ** 2 + secondary_from.z ** 2) ** 0.5
            st_len = (secondary_to.x ** 2 + secondary_to.y ** 2 + secondary_to.z ** 2) ** 0.5
        roll_angle = 0.0
        if sf_len > 1e-9 and st_len > 1e-9:
            # Project sf and st onto the plane perpendicular to pt.
            sf = TGPoint3(secondary_from.x, secondary_from.y, secondary_from.z)
            st = TGPoint3(secondary_to.x, secondary_to.y, secondary_to.z)
            sf_proj = TGPoint3(
                sf.x - pt.x * sf.Dot(pt),
                sf.y - pt.y * sf.Dot(pt),
                sf.z - pt.z * sf.Dot(pt),
            )
            st_proj = TGPoint3(
                st.x - pt.x * st.Dot(pt),
                st.y - pt.y * st.Dot(pt),
                st.z - pt.z * st.Dot(pt),
            )
            sf_proj.Unitize(); st_proj.Unitize()
            cos_roll = sf_proj.Dot(st_proj)
            if cos_roll > 1.0: cos_roll = 1.0
            elif cos_roll < -1.0: cos_roll = -1.0
            roll_angle = _math.acos(cos_roll)
            # Sign: positive if (sf_proj × st_proj) is along +pt.
            sign_axis = sf_proj.Cross(st_proj)
            if sign_axis.Dot(pt) < 0.0:
                roll_angle = -roll_angle
            av_x += pt.x * roll_angle
            av_y += pt.y * roll_angle
            av_z += pt.z * roll_angle

        # 3. Clamp per-axis to MaxAngularVelocity. Uses the same
        # IES-populated guard as ship_motion._max_angular_accel.
        ies = self.GetImpulseEngineSubsystem()
        if ies is not None and ies.GetMaxAngularVelocity() > 0.0:
            max_av = ies.GetMaxAngularVelocity()
        else:
            max_av = 1.0e9  # ship_motion.FALLBACK_MAX_ACCEL parallel
        def _clamp(v, m):
            if v > m: return m
            if v < -m: return -m
            return v
        av_x = _clamp(av_x, max_av)
        av_y = _clamp(av_y, max_av)
        av_z = _clamp(av_z, max_av)

        # 4. Write the setpoint.
        result = TGPoint3(av_x, av_y, av_z)
        self.SetTargetAngularVelocityDirect(result)

        # 5. ETA estimate.
        total_angle = abs(primary_angle) + abs(roll_angle)
        if max_av > 1e-9:
            return float(total_angle / max_av)
        return 0.0

    def TurnTowardDirection(self, direction_vec) -> float:
        """Set the angular-velocity setpoint to rotate world-forward
        onto a world-space direction vector.

        Distinct from TurnTowardLocation: this entry point takes a
        direction (the caller has already done the
        target − ship_location subtraction, or is passing an
        arbitrary world-space heading). SDK callers:
        AI/PlainAI/FollowObject.py:148, EvadeTorps.py:137,
        Flee.py:142, MoveToObjectSide.py, Warp.py:388,
        AI/Preprocessors.py:1705 (Defensive override direction).

        Returns the ETA estimate from TurnDirectionsToDirections (a
        non-negative float in seconds); Flee/Warp capture it to
        schedule their next AI update. Zero-length direction is a
        no-op — any prior setpoint is preserved.
        """
        d = TGPoint3(direction_vec.x, direction_vec.y, direction_vec.z)
        if d.Length() < 1e-9:
            return 0.0
        d.Unitize()
        forward = self.GetWorldRotation().GetCol(1)
        zero = TGPoint3(0.0, 0.0, 0.0)
        return self.TurnDirectionsToDirections(forward, d, zero, zero)

    def TurnTowardLocation(self, target_vec) -> None:
        """Set the angular velocity setpoint to rotate this ship to face
        a world-space point.

        Thin wrapper on TurnDirectionsToDirections: compute the unit
        direction from ship to target, read current world-forward from
        column 1 of the world rotation (see CLAUDE.md ↦ "Rotation matrix
        convention"), call the solver with (forward, target_dir,
        zero, zero) so primary alignment runs but no secondary roll
        constraint applies. If the ship is already at the target (zero
        distance) this is a no-op so any prior setpoint is preserved
        and the solver doesn't see a NaN direction.

        Called by AI.PlainAI.Intercept.Update each tick to face the
        predicted intercept point.
        """
        loc = self.GetWorldLocation()
        diff = TGPoint3(
            target_vec.x - loc.x,
            target_vec.y - loc.y,
            target_vec.z - loc.z,
        )
        if diff.Length() < 1e-9:
            return
        diff.Unitize()
        forward = self.GetWorldRotation().GetCol(1)
        zero = TGPoint3(0.0, 0.0, 0.0)
        self.TurnDirectionsToDirections(forward, diff, zero, zero)

    def InSystemWarp(self, target, distance) -> int:
        """Teleport-to-near-target sub-light warp.

        Stateless model: if target is None or the ship is already within
        `distance` of the target, return 0 without moving. Otherwise
        compute unit dir = (target - ship).normalize(), translate the
        ship to (target − unit_dir · distance), and return 1.

        ``_current_speed`` is left untouched. Intercept.Update calls
        this every AI tick when ``fMaximumSpeed == 1e20`` (BasicAttack's
        default), and once a ship is rotating (Slice H wired
        TurnTowardDirection), it routinely drifts a few cm across the
        warp threshold from one tick to the next. Resetting speed on
        each crossing would clobber the integrator's acceleration ramp
        — the symptom user reported as "ships barely move, no firing"
        even after the speed/scale fix landed in Slice I.
        Semantically the teleport is "instant transit," not "stop"; if
        the AI body wants the ship to slow down, the speed setpoint it
        writes on the next tick will pull current_speed down through
        the normal ramp.

        SDK callers (Intercept.Update) invoke this each AI tick. The
        stateless model converges: one teleport per warp request,
        subsequent ticks find distance ≤ fDistance and return 0.

        Visual streaks / camera flash / multi-frame animation will hook
        in via a later renderer-side warp pass. The kinematic teleport
        stays correct; visuals stack on top.
        """
        if target is None:
            return 0
        if self.__dict__.get("_warp_consumed", False):
            # Already warped at least once since the last
            # StopInSystemWarp — return 0 so the AI body drives normal
            # motion instead of re-teleporting (even if target switches
            # or distance drifts outside the threshold).
            return 0
        ship_loc = self.GetWorldLocation()
        target_loc = target.GetWorldLocation()
        diff = TGPoint3(
            target_loc.x - ship_loc.x,
            target_loc.y - ship_loc.y,
            target_loc.z - ship_loc.z,
        )
        d = diff.Length()
        if d <= distance:
            # Already inside the threshold — record convergence so future
            # boundary drifts don't bounce the ship back to the surface.
            self._warp_consumed = True
            return 0
        # Unit dir ship → target, then arrival = target − unit · distance.
        diff.Scale(1.0 / d)
        self.SetTranslateXYZ(
            target_loc.x - diff.x * distance,
            target_loc.y - diff.y * distance,
            target_loc.z - diff.z * distance,
        )
        self._warp_consumed = True
        return 1

    def StopInSystemWarp(self) -> None:
        """Clear the consumed-warp flag so a fresh warp can fire.

        SDK Intercept.LostFocus calls this; in stock Appc it cancels
        the multi-tick warp animation. We model it as "drop the lock,"
        letting the next InSystemWarp call retrigger normally.
        """
        self.__dict__.pop("_warp_consumed", None)

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
    def GetCloakingSubsystem(self):
        """Returns None — Phase 1 ships have no cloaking subsystem.
        SDK FedAttack/NonFedAttack gate cloak usage on this being
        truthy; None keeps the non-cloak path active."""
        return None
    def GetHull(self):                            return self._hull
    def SetHull(self, h) -> None:                 self._hull = h

    def GetSubsystems(self) -> list:
        """Return every populated top-level subsystem on this ship.

        SDK Preprocessors.py:865 — `for pSubsystem in pShipTarget.GetSubsystems():`
        is how AI walks a ship's subsystems when rating which one to target.
        Order matches GetSubsystemByProperty's slot inventory; callers that
        rely on a specific traversal order pass through GetTargetableSubsystems
        anyway, which flattens out non-targetable shells into children."""
        return [s for s in (
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
        ) if s is not None]

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
            # Look up each slot's torpedo script from the bound
            # TorpedoSystemProperty (galaxy.py:1010 sets slot 0 to
            # "Tactical.Projectiles.PhotonTorpedo"), import it, and
            # read GetLaunchSpeed() — so GetCurrentAmmoType() exposes
            # the real launch speed.
            #
            # Why this matters: FireScript.GetWeaponInfo reads
            # GetCurrentAmmoType().GetLaunchSpeed() and feeds the
            # result into PredictTargetLocation, which divides
            # distance by speed. The previous code seeded every slot
            # with the shared App.AT_ONE stub (launch_speed=0),
            # triggering ZeroDivisionError mid-tick the moment a
            # FireScript dispatched at a torp system — silently
            # killing all enemy weapons fire.
            from engine.appc.subsystems import TorpedoAmmoType
            ts_prop = ts.GetProperty()
            for slot in range(tube_count):
                ammo = _resolve_torpedo_ammo(ts_prop, slot)
                ts.AddAmmoType(ammo)

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
    def SetTarget(self, target) -> None:
        """Accepts a string name OR an object reference.

        SDK pattern (AI/Preprocessors.py:1260 — SelectTarget.Update):
        ``pOurShip.SetTarget(self.sCurrentTarget)`` where sCurrentTarget is
        always a string. The Appc C++ side resolves the name to the
        matching object within the ship's containing set; Python callers
        that already have an object reference pass it directly.

        String inputs resolve via the containing set's name table; None or
        unresolvable strings null the target out.

        Fallback: when no containing set is available (common in headless
        tests and headless Phase-1 missions that build ships outside a
        SetClass), resolve against the active STTargetMenu's ship entries.
        This mirrors CycleTarget's SetTarget(name) usage in
        sdk/.../TacticalInterfaceHandlers.py:709,733 which resolves against
        whatever object pool the target-menu rows were built from.
        """
        if isinstance(target, str):
            pSet = self.GetContainingSet()
            if pSet is not None:
                self._target = pSet.GetObject(target)
            else:
                # No containing set — fall back to the target menu's ship rows.
                resolved = None
                try:
                    from engine.appc.target_menu import STTargetMenu_GetTargetMenu
                    menu = STTargetMenu_GetTargetMenu()
                    if menu is not None:
                        child = menu.GetFirstChild()
                        while child is not None:
                            if hasattr(child, "GetShip"):
                                candidate = child.GetShip()
                                if candidate is not None and candidate.GetName() == target:
                                    resolved = candidate
                                    break
                            child = menu.GetNextChild(child)
                except Exception:
                    pass
                self._target = resolved
        else:
            self._target = target
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
        """Return an iterator over subsystems matching `match_type`.

        `match_type` is one of the CT_* class constants from App.py
        (e.g. CT_WEAPON_SYSTEM = WeaponSystemProperty). Match by
        isinstance check against the subsystem's class hierarchy —
        WeaponSystem and its subclasses (PhaserSystem, TorpedoSystem,
        PulseWeaponSystem, TractorBeamSystem) match CT_WEAPON_SYSTEM.

        Returns an opaque iterator handle. `None` filter terminates
        immediately (SDK pattern: callers expect either matches or a
        clean exit; mid-walk None is undefined)."""
        # Function-local imports — App imports ships at module level,
        # so a top-level `import App` here would loop. Same for
        # WeaponSystem (sibling module also imported by App).
        import App
        from engine.appc.subsystems import (
            ShipSubsystem, WeaponSystem, SensorSubsystem, ImpulseEngineSubsystem,
            WarpEngineSubsystem, ShieldSubsystem, HullSubsystem,
        )
        if match_type is None:
            return iter(())
        candidates = [
            self._sensor_subsystem, self._impulse_engine_subsystem,
            self._warp_engine_subsystem, self._torpedo_system,
            self._phaser_system, self._pulse_weapon_system,
            self._tractor_beam_system, self._shield_subsystem,
            self._power_subsystem, self._repair_subsystem, self._hull,
        ]
        # SDK CT_* constants → subsystem class. SDK callers commonly pass
        # one of CT_WEAPON_SYSTEM (FireScript), CT_SENSOR_SUBSYSTEM
        # (NoSensorsEvasive's ConditionSystemDisabled),
        # CT_WARP_ENGINE_SUBSYSTEM (WarpBeforeDeath), CT_HULL_SUBSYSTEM /
        # CT_SHIELD_SUBSYSTEM / CT_IMPULSE_ENGINE_SUBSYSTEM
        # (SelectTarget.RateSubsystemForTargeting).
        if match_type is App.CT_WEAPON_SYSTEM:
            target_class = WeaponSystem
        elif match_type is App.CT_SENSOR_SUBSYSTEM:
            target_class = SensorSubsystem
        elif match_type is App.CT_IMPULSE_ENGINE_SUBSYSTEM:
            target_class = ImpulseEngineSubsystem
        elif match_type is App.CT_WARP_ENGINE_SUBSYSTEM:
            target_class = WarpEngineSubsystem
        elif match_type is App.CT_SHIELD_SUBSYSTEM:
            target_class = ShieldSubsystem
        elif match_type is App.CT_HULL_SUBSYSTEM:
            target_class = HullSubsystem
        elif match_type is App.CT_SHIP_SUBSYSTEM:
            # ShipSubsystem is the base class — every subsystem matches.
            target_class = ShipSubsystem
        else:
            # Unknown match type — return empty iter so SDK while-loops
            # terminate cleanly.
            return iter(())
        return iter([s for s in candidates if s is not None and isinstance(s, target_class)])

    def GetNextSubsystemMatch(self, iterator=None):
        """Pull the next subsystem from an iterator returned by
        StartGetSubsystemMatch. Returns None when exhausted (SDK
        while-loop termination contract)."""
        if iterator is None:
            return None
        try:
            return next(iterator)
        except StopIteration:
            return None

    def EndGetSubsystemMatch(self, iterator=None):
        """No-op cleanup hook. Python iterators are GC'd; SDK callers
        invoke this for symmetry with the native Appc iterator API."""
        pass


def _resolve_torpedo_ammo(ts_prop, slot: int):
    """Build a TorpedoAmmoType for ``slot`` with launch_speed read from
    the configured projectile script.

    The TorpedoSystemProperty stores ``{slot: "Tactical.Projectiles.<Name>"}``
    populated by hardpoint setup (galaxy.py:1010,
    galor.py:168, etc.). Each projectile module exposes a
    ``GetLaunchSpeed()`` function. We import lazily and call it.

    Falls back to ``("Photon", 19.0)`` — the most common ammo — if the
    property has no script registered for this slot or the lookup
    fails. Photon's 19 m/s is what stock BC uses for any ship that
    hasn't overridden the slot, so it's a safer default than 0 (which
    causes a divide-by-zero in FireScript.PredictTargetLocation).
    """
    from engine.appc.subsystems import TorpedoAmmoType
    script_name = None
    if ts_prop is not None and hasattr(ts_prop, "GetTorpedoScript"):
        script_name = ts_prop.GetTorpedoScript(slot)
    if not script_name:
        return TorpedoAmmoType("Photon", launch_speed=19.0)
    try:
        leaf = script_name.split(".")[-1]
        mod = __import__(script_name, None, None, [leaf])
        launch_speed = float(mod.GetLaunchSpeed()) if hasattr(mod, "GetLaunchSpeed") else 19.0
        return TorpedoAmmoType(leaf, launch_speed=launch_speed)
    except Exception:
        return TorpedoAmmoType("Photon", launch_speed=19.0)


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
