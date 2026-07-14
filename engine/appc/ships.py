from engine.appc.objects import DamageableObject
from engine.appc.math import TGPoint3
from engine.appc.subsystems import PoweredSubsystem
import engine.dev_mode as dev_mode


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
        # Ships default to HAILABLE in native Appc — missions call
        # SetHailable(FALSE) to REMOVE specific ships from the bridge Hail menu
        # (E1M2 debris/asteroids; E3/E6 hulks, probes, transports, Keldon,
        # Warbird — 21 such calls across the SDK vs only planets/stations that
        # opt IN via SetHailable(TRUE)). Overrides ObjectClass's default of
        # non-hailable set by super().__init__(). This is why E1M2's "Facility"
        # (a FedOutpost ship) is hailable without any explicit call.
        self._hailable = True
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
        # Powered consumers in attach order — this list IS the BC draw priority
        # (mirrors BC's linked list of powered subsystems).  PowerSubsystem's
        # per-interval pump walks it in order so earlier-attached systems get
        # first claim on the conduit budget.  Populated by _attach_subsystem.
        self._powered_consumers: list = []
        # Cloaking device — None on most ships (only birdofprey, warbird,
        # vorcha, sunbuster, kessok*, matankeldon declare one). Created on
        # demand by SetupProperties when a CloakingSubsystemProperty is found.
        self._cloaking_subsystem = None
        # ObjectEmitter mount markers (shuttle bay, probe launcher, etc.) — not
        # subsystems: no condition, not targetable.  Populated by SetupProperties
        # Pass 6; starts empty.
        self._object_emitters = []
        # Hull is created lazily by SetupProperties() when a HullProperty is
        # found in the property set (SDK App.py:5382-5383).  Stays None for
        # ships with no hardpoint applied.
        self._hull = None
        # Targeting state
        self._target = None
        self._target_subsystem = None
        # IsDocked drives cutscene + game-over branching in MissionLib and
        # per-mission scripts. Freshly-spawned ships are undocked. (_dying /
        # _dead are initialised by DamageableObject, which owns IsDying/IsDead.)
        self._docked = False
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
        # Fresnel-rim intensity, from the hardpoint stats' optional
        # 'SpecularCoef' key (loadspacehelper calls SetSpecularKs when the
        # ship's GetShipStats() defines it). None = not authored; the
        # renderer-side default applies (see host_loop rim registration).
        self._specular_ks = None
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
        # Active in-system-warp transit: (target, drop_distance) while the
        # ship is cruising toward a warp drop point, else None. Written by
        # InSystemWarp, advanced per tick by ship_motion._step_in_system_warp,
        # aborted by StopInSystemWarp / SetAI / ClearAI. Eager-init (real
        # attr, not the truthy TGObject __getattr__ _Stub) — the integrator
        # branches on it every tick.
        self._insystem_warp_transit = None

    def SetAI(self, ai, *_extra) -> None:
        # SDK QuickBattle.StartSimulation2 calls SetAI(ai, 0, 0); the trailing
        # flags (bDeleteOld / bActivate) are engine-internal and ignored here.
        # A change of orders aborts any in-flight in-system warp — the transit
        # belongs to the AI that requested it (SDK Intercept owns the warp and
        # cancels via StopInSystemWarp on LostFocus) — and announces the old
        # tree's end via ET_AI_DONE (ConditionPlayerOrbitting's leave-orbit
        # trigger; HelmCharacterHandlers.AIDone).
        old = self._ai
        self._ai = ai
        self._insystem_warp_transit = None
        if old is not None and old is not ai:
            self._deactivate_ai_tree(old)
            from engine.appc.ai_driver import fire_ai_done
            fire_ai_done(self, old)

    def ClearAI(self, *_extra) -> None:
        # SDK callers: pPlayer.ClearAI() (MissionLib.SetPlayerAI(ctrl, None))
        # and pShip.ClearAI(0, pOldAI) (HelmMenuHandlers fleet override); the
        # flags (bDelete / pOldAI) are engine-internal and ignored here.
        # Must be overridden here: the ObjectClass.ClearAI stub is a no-op and
        # would leave the installed AI driving the ship forever. Announces the
        # ended tree via ET_AI_DONE, like SetAI above.
        old = self._ai
        self._ai = None
        self._insystem_warp_transit = None
        if old is not None:
            self._deactivate_ai_tree(old)
            from engine.appc.ai_driver import fire_ai_done
            fire_ai_done(self, old)

    @staticmethod
    def _deactivate_ai_tree(ai) -> None:
        """Clear tree-activation AND focus state across `ai`'s whole subtree.

        `ai_driver._reconcile_active` tracks the active-node set PER ROOT
        (``root_ai._active_nodes``), so a node's ``_is_active_in_tree`` flag
        can only be cleared by the same root that set it. That breaks the
        SDK's real re-parenting idiom (HelmMenuHandlers.OverrideAIInternal):
        ``pOverrideAI.AddAI(pOldAI, 2)`` grafts the SAME old AI object onto a
        new root at lower priority, THEN ``pShip.ClearAI(0, pOldAI)`` detaches
        it from the ship (bDelete=0 — reuse, not destroy), THEN
        ``pShip.SetAI(pOverrideAI)`` installs the new root. Without this,
        every node under the detached root stays latched
        ``_is_active_in_tree = True`` from when the OLD root was ticking it
        directly — so when the new root's dispatch reaches those same nodes
        again, ``SetActive()``'s edge guard swallows the transition
        entirely: a ``ConditionalAI`` never re-registers its condition list
        (a re-armed ``ConditionTimer`` never re-fires; a polling condition's
        ``Activate()``-started timer never restarts).

        The FOCUS lifecycle has exactly the same per-root latching design
        (``root_ai._focused_preprocessors``, ``node._has_focus``,
        ``node._got_focus_called`` — see ``ai_driver._reconcile_focus``) and so
        needs exactly the same teardown, for three reasons:

        * ``AI/PlainAI/Warp.LostFocus`` (:217) RE-ENABLES THE COLLISIONS IT
          DISABLED. Detach a warping ship's AI without dispatching it and the
          ship is permanently non-collidable.
        * In the fleet-override idiom above, ``SetActive()`` re-fires on the
          old subtree when the priority list falls back to it — but
          ``GotFocus()`` could not, because ``_got_focus_called`` was still
          latched from the old root. Re-activated but never re-focused is a
          self-contradictory state (``StarbaseAttack.GotFocus`` starts firing;
          it would never run again).
        * ``HasFocus()`` stayed 1 on detached nodes, so
          ``ArtificialIntelligence.GetFocusAIs()`` reported nodes that are on
          no focus path at all.

        Called from both detach points (``ClearAI`` and the old-AI branch of
        ``SetAI``) so a tree is always deactivated the moment it stops being
        *this* ship's installed AI, whether or not it goes on to live as a
        child of something else.
        """
        get_tree = getattr(ai, "GetAllAIsInTree", None)
        if not callable(get_tree):
            return
        # Local import: ai_driver imports engine.appc.ai, and ships is imported
        # from the driver's dispatch path — keep the module-level graph acyclic
        # (this file already uses local imports for fire_ai_done above).
        from engine.appc.ai_driver import _dispatch_lost_focus
        for node in get_tree():
            # Focus teardown first: the script's LostFocus() cleanup may want to
            # touch a node that is still nominally active (Warp's StopTowing).
            # _dispatch_lost_focus calls the script's LostFocus() and clears BOTH
            # _has_focus and the _got_focus_called latch.
            if node.HasFocus():
                _dispatch_lost_focus(node)
            set_inactive = getattr(node, "SetInactive", None)
            if callable(set_inactive):
                set_inactive()
        # The root's own bookkeeping lists: a detached root is not ticking, so
        # nothing would ever reconcile these again. Leaving them populated keeps
        # strong references to a torn-down tree and, if the root is re-installed
        # later, would make the next reconciliation diff against a stale snapshot.
        ai._focused_preprocessors = []
        ai._active_nodes = []

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
        SetImpulse. By contrast SetSpeed takes an absolute GU/s value
        (Intercept.py:243 passes ``fSpeed = fMaxSpeed``). BC's internal
        unit is "game units per second"; the helm tooltip displays via
        ConvertGameUnitsToKilometers (see engine.units).

        We multiply by MaxSpeed here so the integrator can keep
        treating ``_speed_setpoint`` as absolute GU/s — that keeps the
        single integration path simple and matches the way the
        player-control code on the live path already produces
        absolute GU/s.

        Fallback for ships without an IES (or with MaxSpeed == 0):
        store as-is. Many headless tests construct bare ShipClass
        instances and rely on the literal-pass-through behaviour;
        this guard avoids breaking them and matches the
        MaxSpeed-populated guard in ship_motion._effective_motion /
        _PlayerControl.GetTargetSpeed.
        """
        ies = self.GetImpulseEngineSubsystem()
        max_speed = ies.GetAuthoredMaxSpeed() if ies is not None else 0.0
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
          3. Cap the commanded magnitude at √(2·MaxAngularAccel·θ) so
             the ship can always decelerate into alignment instead of
             overshooting and hunting.
          4. Convert the world-frame axis·angle vector to BODY frame
             (v_body = Rᵀ·v_world) — the integrator treats the setpoint
             as body-frame pitch/roll/yaw rates.
          5. Clamp per-axis magnitude to GetMaxAngularVelocity()
             (FALLBACK_MAX_ACCEL when the IES isn't populated).
          6. SetTargetAngularVelocityDirect(angular_velocity).
          7. Return total_angle / max_angular_velocity (loose
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

        # 3. Deceleration-aware magnitude. The raw command (|ω| = remaining
        # angle per second) saturates at MaxAngularVelocity for any large
        # angle; with a finite MaxAngularAccel the integrator then can't
        # shed that rate before alignment and the nose overshoots and hunts
        # (±MaxAngVel²/2·MaxAngAccel each swing — ±19° for a Galaxy). Cap
        # the command at √(2·a·θ), the highest rate from which the ship can
        # still stop within the remaining angle; near alignment the
        # proportional θ/s command is already below the cap and gives the
        # smooth terminal taper.
        ies = self.GetImpulseEngineSubsystem()
        total_angle = (av_x * av_x + av_y * av_y + av_z * av_z) ** 0.5
        max_aa = ies.GetMaxAngularAccel() if ies is not None else 0.0
        if max_aa and max_aa > 0.0 and total_angle > 1e-9:
            stop_cap = _math.sqrt(2.0 * max_aa * total_angle)
            if stop_cap < total_angle:
                k = stop_cap / total_angle
                av_x *= k; av_y *= k; av_z *= k

        # 4. World → body frame. The integrator (ship_motion.
        # _integrate_rotation) interprets the setpoint as BODY-frame rates
        # (pitch about body X, roll about body Y, yaw about body Z,
        # post-multiplied R·Δ). The axis·angle vector built above is WORLD
        # frame; feeding it through unconverted is only correct near
        # identity attitude — at an arbitrary attitude the ship turns about
        # the wrong axes, re-aims, and hunts forever (live symptom: the
        # nose waves in circles and never lands on the target).
        # v_body = Rᵀ·v_world; with column-vector R the rows of Rᵀ are the
        # body axes, so each body component is a column dot product.
        R = self.GetWorldRotation()
        c0, c1, c2 = R.GetCol(0), R.GetCol(1), R.GetCol(2)
        b_x = c0.x * av_x + c0.y * av_y + c0.z * av_z
        b_y = c1.x * av_x + c1.y * av_y + c1.z * av_z
        b_z = c2.x * av_x + c2.y * av_y + c2.z * av_z

        # 5. Clamp per-axis to MaxAngularVelocity. Uses the same
        # IES-populated guard as ship_motion._effective_motion.
        if ies is not None and ies.GetMaxAngularVelocity() > 0.0:
            max_av = ies.GetMaxAngularVelocity()
        else:
            max_av = 1.0e9  # ship_motion.FALLBACK_MAX_ACCEL parallel
        def _clamp(v, m):
            if v > m: return m
            if v < -m: return -m
            return v
        b_x = _clamp(b_x, max_av)
        b_y = _clamp(b_y, max_av)
        b_z = _clamp(b_z, max_av)

        # 6. Write the setpoint (body frame).
        self.SetTargetAngularVelocityDirect(TGPoint3(b_x, b_y, b_z))

        # 7. ETA estimate.
        eta_angle = abs(primary_angle) + abs(roll_angle)
        if max_av > 1e-9:
            return float(eta_angle / max_av)
        return 0.0

    def TurnTowardOrientation(self, vForward, vUp):
        """Steer world-forward onto vForward and world-up onto vUp.

        The 2-arg orientation form AI.PlainAI.FollowWaypoints.TurnToward
        (sdk/.../FollowWaypoints.py:276) commands. BC's PhysicsObjectClass
        exposes this; we service it on ShipClass by supplying the ship's
        CURRENT forward/up as the 'from' vectors and delegating to the shared
        turn-rate-limited controller (TurnDirectionsToDirections), which writes
        the body-frame angular-velocity setpoint that ship_motion integrates.
        Non-ship physics props keep the PhysicsObjectClass no-op (no IES / no
        turn controller; they never follow waypoints)."""
        R = self.GetWorldRotation()
        primary_from = R.GetCol(1)    # current world forward (model-Y)
        secondary_from = R.GetCol(2)  # current world up
        self.TurnDirectionsToDirections(primary_from, vForward,
                                        secondary_from, vUp)

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

    # In-system warp transit speed = this factor × the ship's impulse
    # MaxSpeed — deliberately the same 100× as the player's Ctrl+I boost
    # (_PlayerControl.WARP_BOOST_FACTOR) so AI-ordered warps and manual
    # boosts cross a system at the same rate. BC's microwarp is a visible
    # multi-second cruise, never an instant teleport.
    IN_SYSTEM_WARP_SPEED_FACTOR = 100.0
    # Base speed for ships without a populated IES (bare test rigs) —
    # parallels _PlayerControl.IMPULSE_UNIT legacy fallback.
    IN_SYSTEM_WARP_FALLBACK_BASE = 50.0
    # The ship must be pointing at the target (within ~10°) before the warp
    # engages — BC ships visibly turn onto the warp vector first, and the
    # caller (SDK Intercept.Update) keeps steering via TurnTowardLocation
    # until we accept.
    IN_SYSTEM_WARP_FACING_COS = 0.985

    def InSystemWarp(self, target, distance) -> int:
        """Begin (or report) a sub-light warp toward `target`.

        Multi-frame transit model: when the ship is beyond `distance` of the
        target AND its nose is on the target (IN_SYSTEM_WARP_FACING_COS),
        record a transit (target, drop_distance) and return 1. The per-tick
        integrator (ship_motion._step_in_system_warp) then cruises the ship
        in a straight line at IN_SYSTEM_WARP_SPEED_FACTOR × MaxSpeed until
        it reaches (target − unit_dir · distance), where the transit ends
        and `_warp_consumed` latches. While a transit is active this returns
        1 without re-engaging (SDK bWarping semantics — Intercept skips its
        normal speed control during the warp).

        Not facing yet → return 0 and do nothing: the SDK caller keeps
        turning the ship (TurnTowardLocation runs every Intercept update)
        and re-calls until we accept.

        ``_current_speed`` is left untouched throughout. Intercept.Update
        calls this every AI tick when ``fMaximumSpeed == 1e20``
        (BasicAttack's default), and once a ship is rotating it routinely
        drifts a few cm across the warp threshold from one tick to the
        next. Resetting speed on each crossing would clobber the
        integrator's acceleration ramp — the "ships barely move, no firing"
        symptom from Slice I.

        The `_warp_consumed` latch keeps the historical convergence
        contract: one warp per StopInSystemWarp cycle, so boundary drifts
        or target switches don't re-warp the ship (see
        tests/unit/test_in_system_warp_preserves_speed.py).
        """
        if target is None:
            return 0
        if self._insystem_warp_transit is not None:
            return 1
        if self.__dict__.get("_warp_consumed", False):
            # Already warped since the last StopInSystemWarp — the AI body
            # drives normal motion now.
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
        # Facing gate: nose must be on the target before the jump.
        fwd = self.GetWorldRotation().GetCol(1)
        cos_face = (fwd.x * diff.x + fwd.y * diff.y + fwd.z * diff.z) / d
        if cos_face < self.IN_SYSTEM_WARP_FACING_COS:
            return 0
        self._insystem_warp_transit = (target, float(distance))
        return 1

    def IsDoingInSystemWarp(self) -> int:
        """Whether the ship is mid in-system-warp (the SDK
        ShipClass.IsDoingInSystemWarp query). AvoidObstacles uses this to
        skip collision steering during a warp, because the warp check does
        its own clearance (Preprocessors.py:1692-1693).

        True while a transit recorded by InSystemWarp is still being
        advanced by the integrator. The explicit ``_doing_in_system_warp``
        flag remains honoured for tests / future warp-VFX passes."""
        if self._insystem_warp_transit is not None:
            return 1
        return 1 if self.__dict__.get("_doing_in_system_warp", False) else 0

    def StopInSystemWarp(self) -> None:
        """Abort any active transit and clear the consumed-warp latch so a
        fresh warp can fire.

        SDK Intercept.LostFocus calls this; in stock Appc it cancels the
        multi-tick warp animation. Ours drops both the in-flight transit
        and the lock, letting the next InSystemWarp call retrigger.
        """
        self._insystem_warp_transit = None
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

    def IsImmobile(self) -> bool:
        """True when this ship must be treated as a fixed anchor: either the
        mission flagged it per-instance (SetStatic) or the hardpoint flagged
        the class stationary (SetStationary). Honoured by the motion
        integrator, collision response, and collision avoidance so stations /
        drydocks neither drift nor rotate. Both backing flags are set in
        __init__, so these are safe direct calls (no _Stub hazard)."""
        return bool(self.IsStatic()) or bool(self.IsStationary())

    def GetDeathExplosionSound(self) -> str:            return self._death_explosion_sound
    def SetDeathExplosionSound(self, v) -> None:        self._death_explosion_sound = str(v)
    # SWIG surface: loadspacehelper.py:85 forwards the hardpoint stats'
    # optional 'SpecularCoef'. Was a silent _Stub no-op before this existed.
    def GetSpecularKs(self):                            return self._specular_ks
    def SetSpecularKs(self, v) -> None:                 self._specular_ks = float(v)

    def GetShipProperty(self):
        """Return this ship's ShipProperty from its property set, or None.

        SWIG surface App.py:5418. Absent here, ``GetShipProperty()`` fell
        through TGObject.__getattr__ to a truthy _Stub, so
        Effects.GetDeathExplosionSound() -> getattr(mod, _Stub) raised
        ``TypeError: attribute name must be string, not '_Stub'`` inside the
        AsteroidExploding death script (swallowed by RunDeathScript). Mirrors
        the ShipProperty selection in the SetupProperties copy loop below.
        """
        from engine.appc.properties import ShipProperty
        ps = self.GetPropertySet()
        if ps is None:
            return None
        for prop in ps.GetPropertyList():
            if isinstance(prop, ShipProperty):
                return prop
        return None

    # ── Alert level ──────────────────────────────────────────────────────────
    # SDK callers: MissionLib.py:605 (reset to GREEN at mission start),
    # BridgeHandlers.py:1442 (bridge crew behavior keys off this).
    def GetAlertLevel(self) -> int:                     return self._alert_level

    def SetAlertLevel(self, v) -> None:
        """Apply the alert-level → power policy for weapons and shields.

        Red alert powers phasers / torpedoes / pulse weapons on; any other
        level powers them off.  Tractor stays under manual control (mirrors
        BC: tractor is toggled by its own UI, not by alert).

        Shields raise at YELLOW or RED and drop at GREEN.  Raising snaps
        every face to its max; dropping drains every face to zero.  This
        collapses BC's gradual charge-up/down into an instant transition
        — good enough for Phase 1 gameplay.

        In stock BC these side-effects flow through the XO menu after
        BridgeHandlers.SetAlertLevel; we collapse that layer until the
        bridge menu system is wired.
        """
        self._alert_level = int(v)
        weapons_on = (self._alert_level == ShipClass.RED_ALERT)
        for slot in (self._phaser_system, self._torpedo_system,
                     self._pulse_weapon_system):
            if slot is None:
                continue
            if weapons_on:
                slot.TurnOn()
                slot.SetPowerPercentageWanted(1.0)
            else:
                slot.TurnOff()
                slot.SetPowerPercentageWanted(0.0)

        shields = self._shield_subsystem
        if shields is not None:
            shields_on = (self._alert_level in
                          (ShipClass.YELLOW_ALERT, ShipClass.RED_ALERT))
            if shields_on:
                shields.TurnOn()          # TurnOn override snaps faces to max
                shields.SetPowerPercentageWanted(1.0)
            else:
                shields.TurnOff()         # TurnOff override drains faces to 0
                shields.SetPowerPercentageWanted(0.0)

    # ── Subsystem accessors ──────────────────────────────────────────────────
    # Mirror sdk/.../App.py:5394-5455.  Loaders that need to populate these
    # call the matching Set*Subsystem method (Phase 2 hardpoint integration).

    def _attach_subsystem(self, s):
        """Wire a freshly-attached subsystem back to this ship so emitters
        can climb the parent chain to reach the ShipClass at fire-time.

        Powered subsystems are also registered as power consumers in attach
        order (the BC draw priority) so PowerSubsystem's per-interval pump can
        walk them.  PowerSubsystem itself inherits ShipSubsystem (it generates
        power, not consumes it) so it is never registered here."""
        if s is not None and hasattr(s, "SetParentShip"):
            s.SetParentShip(self)
        if isinstance(s, PoweredSubsystem) and s not in self._powered_consumers:
            self._powered_consumers.append(s)   # attach order = BC draw priority
        return s

    def AddPoweredConsumer(self, subsystem) -> None:
        """Register a PoweredSubsystem as a power consumer (public alias of the
        attach-order registration in _attach_subsystem).  Wires the parent ship
        back-ref too so a consumer added this way can climb to the ship.  Used
        by tests and any call site that attaches a consumer outside the typed
        Set*Subsystem slots."""
        self._attach_subsystem(subsystem)

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
    def SetTractorBeamSystem(self, s) -> None:
        self._tractor_beam_system = self._attach_subsystem(s)
        # The tractor is a manual toggle available at ALL alert levels — unlike
        # the phaser/torpedo/pulse weapons, which SetAlertLevel powers on only at
        # red alert. Power it on when equipped so the player can engage it any
        # time; StartFiring/StopFiring is the actual on/off (a powered but
        # unfired tractor has no effect — advance_tractors only acts on firing
        # beams). A default-empty system with no emitters stays a harmless no-op.
        if self._tractor_beam_system is not None and hasattr(
                self._tractor_beam_system, "TurnOn"):
            self._tractor_beam_system.TurnOn()

    # ── Weapon-group lookup by WG_* enum ─────────────────────────────────────
    # Matches sdk/.../TacticalInterfaceHandlers.py:387-405 dispatch.  PR 2's
    # FireWeapons event handler calls this; included now so the surface is
    # ready when that wiring lands.
    def GetWeaponSystemGroup(self, eGroup: int):
        if eGroup == ShipClass.WG_PRIMARY:
            # Primary fire is phasers. When the ship has no phaser banks
            # (e.g. the Klingon Bird of Prey, whose main energy weapon is
            # its disruptors) fall back to the pulse-weapon system so
            # primary fire — left mouse / F — drives the disruptors. Every
            # ship is handed a default-empty PhaserSystem by the ships
            # factory, so the test is "no banks" (GetNumWeapons() == 0),
            # not "is None". Only callers are the SDK FireWeapons handlers,
            # so this affects firing only. A ship that has both (e.g.
            # vorcha: disruptor beams + cannons) keeps phasers on primary.
            phasers = self._phaser_system
            if phasers is None or phasers.GetNumWeapons() == 0:
                pulse = self._pulse_weapon_system
                if pulse is not None and pulse.GetNumWeapons() > 0:
                    return pulse
            return phasers
        if eGroup == ShipClass.WG_SECONDARY:
            return self._torpedo_system
        if eGroup == ShipClass.WG_TERTIARY:
            return self._pulse_weapon_system
        if eGroup == ShipClass.WG_TRACTOR:
            return self._tractor_beam_system
        return None

    def GetShieldSubsystem(self):                 return self._shield_subsystem
    def SetShieldSubsystem(self, s) -> None:      self._shield_subsystem = self._attach_subsystem(s)
    # SDK-facing alias — pShip.GetShields() in mission scripts and SDK helpers.
    def GetShields(self):                         return self._shield_subsystem
    def GetPowerSubsystem(self):                  return self._power_subsystem
    def SetPowerSubsystem(self, s) -> None:       self._power_subsystem = self._attach_subsystem(s)
    def GetRepairSubsystem(self):                 return self._repair_subsystem
    def SetRepairSubsystem(self, s) -> None:      self._repair_subsystem = self._attach_subsystem(s)
    def GetCloakingSubsystem(self):
        """Return the ship's cloaking device, or None if it has none.
        SDK CloakShip.CheckCloak (Preprocessors.py:2111) and the
        FedAttack/NonFedAttack doctrines gate cloak usage on this being
        truthy; None keeps the non-cloak path active for ships with no
        CloakingSubsystemProperty in their hardpoint."""
        return self._cloaking_subsystem

    def IsCloaked(self) -> int:
        """1 if the ship's cloak has fully engaged, else 0. Ships with no
        cloaking subsystem are never cloaked. SDK ShipClass.IsCloaked.

        Must be a real 0/1, not a truthy __getattr__ _Stub: HelmMenuHandlers.
        ShipIdentified gates hail-button creation on `not pShip.IsCloaked()`, so
        a stub suppressed the Hail button for every non-cloaking ship/station —
        e.g. E1M2's "Haven Facility" never appeared."""
        cloak = self._cloaking_subsystem
        return 1 if (cloak is not None and cloak.IsCloaked()) else 0

    def IsTryingToCloak(self) -> int:
        """1 while the ship's cloak is mid-transition (cloaking), else 0.
        SDK ShipClass.IsTryingToCloak."""
        cloak = self._cloaking_subsystem
        return 1 if (cloak is not None and cloak.IsTryingToCloak()) else 0
    def SetCloakingSubsystem(self, s) -> None: self._cloaking_subsystem = self._attach_subsystem(s)
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
            self._cloaking_subsystem,
            self._hull,
        ) if s is not None]

    def GetObjectEmitters(self) -> list:
        """Return the ship's ObjectEmitter mount markers (shuttle/probe/decoy
        launch points). Not subsystems — viewer-only, never targetable."""
        return list(self._object_emitters)

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
            self._cloaking_subsystem,
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
            CloakingSubsystemProperty,
        )
        from engine.appc.subsystems import HullSubsystem, CloakingSubsystem
        from engine.appc.subsystems import CLOAK_TRANSITION_DURATION
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
                # The FIRST HullProperty is the primary hull; GetHull() must
                # return it (SDK App.py:5382). Additional HullProperties (e.g.
                # galaxy.py's non-primary "Bridge") attach as children of the
                # primary hull so they are damageable + viewer-visible. Plain
                # children of a targetable parent stay out of the AI loop.
                if self._hull is not None and self._hull.GetProperty() is prop:
                    pass  # re-run: primary already bound to this property
                else:
                    receiver = None
                    if self._hull is None:
                        self._hull = HullSubsystem(prop.GetName() or "Hull")
                        self._hull.SetProperty(prop)
                        receiver = self._hull
                    elif self._hull.GetChildSubsystem(prop.GetName()) is None:
                        receiver = HullSubsystem(prop.GetName() or "Bridge")
                        receiver.SetProperty(prop)
                        self._hull.AddChildSubsystem(receiver)
                    if receiver is not None:
                        for src, setter in (
                            (prop.GetMaxCondition,        receiver.SetMaxCondition),
                            (prop.GetCritical,            receiver.SetCritical),
                            (prop.GetTargetable,          receiver.SetTargetable),
                            (prop.GetPrimary,             receiver.SetPrimary),
                            (prop.GetRadius,              receiver.SetRadius),
                            (prop.GetDisabledPercentage,  receiver.SetDisabledPercentage),
                            (prop.GetRepairComplexity,    receiver.SetRepairComplexity),
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
                    # SingleFire flows to any system that models it. Phasers
                    # and pulse cannons both honour SetSingleFire (phasers
                    # round-robin one bank, pulse cannons one cannon when set;
                    # both fire all eligible when clear). Hardpoints call
                    # SetSingleFire on the WeaponSystemProperty (e.g.
                    # birdofprey.py DisruptorCannons.SetSingleFire(0),
                    # warbird.py DisruptorCannons.SetSingleFire(1)).
                    if hasattr(receiver, "SetSingleFire"):
                        sf = prop.GetSingleFire()
                        if sf is not None: receiver.SetSingleFire(sf)
                    # AimedWeapon is phaser-only.
                    if wst == WeaponSystemProperty.WST_PHASER:
                        aw = prop.GetAimedWeapon()
                        if aw is not None: receiver.SetAimedWeapon(aw)
            elif isinstance(prop, PowerProperty):
                ps = self._power_subsystem
                if ps is not None:
                    _copy_name(prop, ps)
                    ps.SetProperty(prop)
                    mc = prop.GetMaxCondition()
                    if mc is not None: ps.SetMaxCondition(mc)
                    tg = prop.GetTargetable()
                    if tg is not None: ps.SetTargetable(tg)
                    # Seed battery pools to full so a fresh ship can fire
                    # before the first per-tick refill (matches the SDK
                    # WarpCore which the C++ side initialises at full
                    # charge during ship construction).
                    mbl = prop.GetMainBatteryLimit()
                    if mbl is not None: ps.SetMainBatteryPower(float(mbl))
                    bbl = prop.GetBackupBatteryLimit()
                    if bbl is not None: ps.SetBackupBatteryPower(float(bbl))
            elif isinstance(prop, RepairSubsystemProperty):
                rs = self._repair_subsystem
                if rs is not None:
                    _copy_name(prop, rs)
                    self._copy_powered_subsystem_fields(prop, rs)
                    rs.SetProperty(prop)
            elif isinstance(prop, CloakingSubsystemProperty):
                # Cloak is create-on-demand: most ships have no cloak so the
                # factory does NOT pre-allocate one (unlike shields/power/etc.).
                # A CloakingSubsystemProperty in the set means this hull is
                # cloak-capable — build the subsystem and attach it. Idempotent
                # on re-run: reuse the existing instance bound to this property.
                cl = self._cloaking_subsystem
                if cl is None or cl.GetProperty() is not prop:
                    cl = CloakingSubsystem(prop.GetName() or "Cloaking Device")
                    self.SetCloakingSubsystem(cl)
                _copy_name(prop, cl)
                self._copy_powered_subsystem_fields(prop, cl)
                cl.SetProperty(prop)
                # CloakStrength -> transition duration: strength 100 = canonical
                # CLOAK_TRANSITION_DURATION; duration scales inversely with
                # strength (a weaker device cloaks proportionally slower).
                strength = prop.GetCloakStrength()
                if strength is not None and float(strength) > 0.0:
                    cl._transition_duration = (
                        CLOAK_TRANSITION_DURATION * 100.0 / float(strength)
                    )

        # Pass 2 — seed one torpedo ammo type per DECLARED ammo slot (idempotent).
        ts = self._torpedo_system
        if ts is not None and ts.GetNumAmmoTypes() == 0:
            tube_count = sum(
                1
                for prop in self.GetPropertySet().GetPropertyList()
                if isinstance(prop, TorpedoTubeProperty)
            )
            # BC declares a ship's selectable ammo as SLOTS on the
            # TorpedoSystemProperty (sovereign.py:609+ — per slot SetTorpedoScript
            # + SetMaxTorpedoes, then SetNumAmmoTypes(N)), NOT one type per tube.
            # Seed range(N), naming each by the projectile module's GetName()
            # (Photon/Quantum/Phased) and carrying its declared max as the reserve.
            # The SDK then curates this list at runtime with ZERO UI-side
            # filtering: QuickBattle.RemoveAmmoType prunes PhasedPlasma; missions
            # LoadAmmoType top up. Tubes are launchers and matter only for spread
            # (GetSpreadOptions) — ammo TYPES are an independent declaration.
            #
            # Legacy/undeclared hulls (no SetNumAmmoTypes, or a plain
            # WeaponSystemProperty) fall back to a single unlimited Photon type
            # when they have tubes — preserving the non-zero launch speed the
            # ZeroDivisionError guard in FireScript.PredictTargetLocation needs.
            ts_prop = ts.GetProperty()
            declared = ts_prop.GetNumAmmoTypes() if ts_prop is not None else None
            if not declared or declared <= 0:
                declared = 1 if tube_count > 0 else 0
            for slot in range(declared):
                ts.AddAmmoType(_resolve_torpedo_ammo(ts_prop, slot))

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
            tube._resize_slots()     # one reload slot per MaxReady, all loaded

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
                tg = prop.GetTargetable()
                if tg is not None: child.SetTargetable(tg)

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

        # Pass 5 — engine pods.  EngineProperty leaves attach to the matching
        # powered aggregator by EngineType (EP_IMPULSE -> impulse, EP_WARP ->
        # warp).  BC uses no dedicated engine-leaf class — pods are plain
        # ShipSubsystems (sdk/.../App.py declares EngineProperty but no
        # EngineSubsystem).  Idempotent: skip a parent already seeded with
        # children on a prior run.  A scrubbed (None) aggregator means the
        # hardpoint registered no powered aggregator property; pods are then
        # dropped rather than fabricating a zero-speed engine.
        from engine.appc.properties import EngineProperty
        from engine.appc.subsystems import ShipSubsystem as _ShipSubsystem
        _engine_parent_for = {
            EngineProperty.EP_IMPULSE: self._impulse_engine_subsystem,
            EngineProperty.EP_WARP:    self._warp_engine_subsystem,
        }
        _engine_parents_seeded = {
            id(p) for p in _engine_parent_for.values()
            if p is not None and p.GetNumChildSubsystems() > 0
        }
        for prop in self.GetPropertySet().GetPropertyList():
            if type(prop) is not EngineProperty:
                continue
            parent = _engine_parent_for.get(prop.GetEngineType())
            if parent is None or id(parent) in _engine_parents_seeded:
                continue
            pod = _ShipSubsystem(prop.GetName() or "")
            pod.SetProperty(prop)
            for src, setter in (
                (prop.GetMaxCondition,       pod.SetMaxCondition),
                (prop.GetCritical,           pod.SetCritical),
                (prop.GetTargetable,         pod.SetTargetable),
                (prop.GetPrimary,            pod.SetPrimary),
                (prop.GetRadius,             pod.SetRadius),
                (prop.GetDisabledPercentage, pod.SetDisabledPercentage),
                (prop.GetRepairComplexity,   pod.SetRepairComplexity),
            ):
                v = src()
                if v is not None:
                    setter(v)
            parent.AddChildSubsystem(pod)

        # Pass 6 — object emitters.  ObjectEmitterProperty templates become
        # ObjectEmitter mount markers (shuttle bay, probe launcher). Not
        # subsystems: no condition, not targetable. Idempotent by name.
        from engine.appc.properties import ObjectEmitterProperty
        from engine.appc.object_emitter import ObjectEmitter
        _existing_emitters = {e.GetName() for e in self._object_emitters}
        for prop in self.GetPropertySet().GetPropertyList():
            if not isinstance(prop, ObjectEmitterProperty):
                continue
            if (prop.GetName() or "") in _existing_emitters:
                continue
            emitter = ObjectEmitter(prop)
            emitter.SetParentShip(self)
            self._object_emitters.append(emitter)
            _existing_emitters.add(prop.GetName() or "")

    @staticmethod
    def _copy_powered_subsystem_fields(prop, subsystem) -> None:
        if subsystem is None:
            return
        mc = prop.GetMaxCondition()
        if mc is not None: subsystem.SetMaxCondition(mc)
        # Targetable drives target-menu visibility (RebuildShipMenu) + AI
        # subsystem rating; must come from the hardpoint (e.g. an asteroid's
        # Shield Generator sets SetTargetable(0)), not the engine default.
        tg = prop.GetTargetable()
        if tg is not None: subsystem.SetTargetable(tg)
        np = prop.GetNormalPowerPerSecond()
        if np is not None: subsystem.SetNormalPowerPerSecond(np)
        # DisabledPercentage drives IsDisabled() — must come from the hardpoint
        # (e.g. Galaxy sensor 0.50), not the engine default 0.25, so every
        # powered subsystem's "disabled" gate matches the game and the UI.
        dp = prop.GetDisabledPercentage()
        if dp is not None: subsystem.SetDisabledPercentage(dp)
        rc = prop.GetRepairComplexity()
        if rc is not None: subsystem.SetRepairComplexity(rc)

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
        old_target = self._target
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
                except Exception as _e:
                    dev_mode.log_swallowed("resolve target via target menu", _e)
                self._target = resolved
        else:
            self._target = target
        # Fire ET_TARGET_WAS_CHANGED only on an actual change of the
        # RESOLVED object (not the raw name/object passed in — SelectTarget
        # calls this every tick with a string, and re-resolving the same
        # name must not spam the event). Set the new target BEFORE firing
        # (above) so a re-entrant handler that calls SetTarget again sees
        # the new state, per AddEvent's synchronous dispatch.
        #
        # Deliberately UNguarded (no try/except around AddEvent), matching
        # sets.py's ET_ENTERED_SET/ET_EXITED_SET — the closest analog (a
        # real gameplay event with the ship as destination, consumed by the
        # same bridge modules). events.py:AddEvent documents destination
        # dispatch as intentionally unguarded so a crashing handler surfaces
        # rather than vanishing; several of this event's consumers
        # (Camera, HelmMenuHandlers, ScienceMenuHandlers) have never once
        # run in this engine, so swallowing here would hide the first real
        # signal of a bug in code that has never executed.
        if self._target is not old_target:
            import App
            evt = App.TGEvent_Create()
            evt.SetEventType(App.ET_TARGET_WAS_CHANGED)
            evt.SetSource(self)
            evt.SetDestination(self)
            App.g_kEventManager.AddEvent(evt)
    def GetTargetSubsystem(self):                 return self._target_subsystem
    def SetTargetSubsystem(self, s) -> None:      self._target_subsystem = s

    # ── Lifecycle state ──────────────────────────────────────────────────────
    def IsDocked(self) -> int:    return 1 if self._docked else 0
    def SetDocked(self, v) -> None:
        self._docked = bool(v)
    # IsDying / SetDying / IsDead / SetDead live on DamageableObject, where BC
    # declares them (App.py:5363-5365).

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

        The CT_* -> subsystem-class table lives in
        engine.appc.subsystem_types (shared with GetObjType/IsTypeOf — see
        that module for why a shared table exists at all).

        Returns an opaque iterator handle. `None` filter terminates
        immediately (SDK pattern: callers expect either matches or a
        clean exit; mid-walk None is undefined)."""
        # Function-local import — App imports ships at module level, so a
        # top-level import here would loop; subsystem_types itself imports
        # App lazily for the same reason.
        from engine.appc.subsystem_types import subsystem_class_for_ct
        if match_type is None:
            return iter(())
        candidates = [
            self._sensor_subsystem, self._impulse_engine_subsystem,
            self._warp_engine_subsystem, self._torpedo_system,
            self._phaser_system, self._pulse_weapon_system,
            self._tractor_beam_system, self._shield_subsystem,
            self._power_subsystem, self._repair_subsystem,
            self._cloaking_subsystem, self._hull,
        ]
        # SDK CT_* constants → subsystem class. SDK callers commonly pass
        # one of CT_WEAPON_SYSTEM (FireScript), CT_SENSOR_SUBSYSTEM
        # (NoSensorsEvasive's ConditionSystemDisabled),
        # CT_WARP_ENGINE_SUBSYSTEM (WarpBeforeDeath), CT_HULL_SUBSYSTEM /
        # CT_SHIELD_SUBSYSTEM / CT_IMPULSE_ENGINE_SUBSYSTEM
        # (SelectTarget.RateSubsystemForTargeting), CT_PHASER_SYSTEM /
        # CT_TORPEDO_SYSTEM / etc. (Conditions/ConditionCriticalSystemBelow
        # via pSubsystem.GetObjType()). CT_SHIP_SUBSYSTEM is the base class —
        # every subsystem matches. Unknown/stub match_type -> subsystem_class_
        # for_ct returns None -> empty iter, so SDK while-loops terminate
        # cleanly.
        target_class = subsystem_class_for_ct(match_type)
        if target_class is None:
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

    # --- Death script (SDK App.py:5476-5478) --------------------------------
    # Missions attach a per-object death callback:
    #   pObject.SetDeathScript(__name__ + ".AsteroidExploding")
    # BC's engine runs it (single arg = the dying object) when the object
    # begins dying — our ship_death.begin() calls RunDeathScript there.
    def SetDeathScript(self, qualified_name) -> None:
        """Store a "module.func" death callback, invoked once when the ship
        begins its death throes."""
        self._death_script = qualified_name

    def GetDeathScript(self):
        """Return the stored death-script name, or None if none set. Read via
        __dict__ because TGObject.__getattr__ returns a truthy _Stub for
        missing attrs (the shim idiom)."""
        return self.__dict__.get("_death_script")

    def RunDeathScript(self) -> None:
        """Resolve and call the stored death script with this ship as the sole
        argument (SDK signature: def Func(TGObject)). Raise-safe: a stubbed VFX
        helper inside the script must never abort the death sequence."""
        name = self.__dict__.get("_death_script")
        if not name or not isinstance(name, str):
            return
        from engine.appc.events import _resolve_handler
        fn = _resolve_handler(name)
        if fn is None:
            return
        try:
            fn(self)
        except Exception as _e:
            dev_mode.log_swallowed("run death script " + name, _e)


def _resolve_torpedo_ammo(ts_prop, slot: int):
    """Build the TorpedoAmmoType for declared ammo ``slot`` from the hardpoint's
    TorpedoSystemProperty.

    Per slot the property stores the projectile script
    (``SetTorpedoScript(slot, "Tactical.Projectiles.<X>")``, sovereign.py:609+)
    and a capacity (``SetMaxTorpedoes(slot, n)``).  Each projectile module
    exposes ``GetName()`` — the canonical ammo name MissionLib matches on
    (PhotonTorpedo2→"Photon", QuantumTorpedo→"Quantum", PhasedPlasma→"Phased") —
    plus ``GetLaunchSpeed()`` and ``GetPowerCost()``.  We import lazily and read
    all three.

    The name comes from ``GetName()``, NOT the module leaf: the leaf
    "PhotonTorpedo2" doesn't end in "Torpedo" and "PhasedPlasma" isn't a torpedo
    at all, so a leaf-strip heuristic leaks those raw into the Type selector —
    the bug this fixes.  ``declared_max`` is the property's SetMaxTorpedoes(slot):
    an int (incl. 0) when declared, or ``None`` (undeclared → unlimited reserve).

    Falls back to ``("Photon", 19.0)`` with an unlimited reserve if the slot has
    no script or the import fails — Photon's 19 GU/s avoids the divide-by-zero in
    FireScript.PredictTargetLocation that a launch_speed of 0 would cause.
    """
    from engine.appc.subsystems import TorpedoAmmoType
    # Photon defaults — used for the unbound-slot path and any import failure.
    # PowerCost 20.0 matches PhotonTorpedo.py:65.
    PHOTON_LAUNCH_SPEED = 19.0
    PHOTON_POWER_COST = 20.0
    script_name = None
    declared_max = None
    if ts_prop is not None:
        if hasattr(ts_prop, "GetTorpedoScript"):
            script_name = ts_prop.GetTorpedoScript(slot)
        if hasattr(ts_prop, "GetMaxTorpedoes"):
            # None on a plain WeaponSystemProperty (magic getter) or an
            # undeclared slot → unlimited reserve.
            declared_max = ts_prop.GetMaxTorpedoes(slot)
    if not script_name:
        return TorpedoAmmoType("Photon",
                               launch_speed=PHOTON_LAUNCH_SPEED,
                               power_cost=PHOTON_POWER_COST,
                               max_torpedoes=declared_max)
    try:
        leaf = script_name.split(".")[-1]
        mod = __import__(script_name, None, None, [leaf])
        if hasattr(mod, "GetName"):
            name = mod.GetName()
        else:
            # Fallback only if the module has no GetName(): strip the projectile
            # class's "Torpedo" suffix so "PhotonTorpedo" reads as "Photon".
            name = leaf[:-len("Torpedo")] if leaf.endswith("Torpedo") else leaf
        launch_speed = float(mod.GetLaunchSpeed()) if hasattr(mod, "GetLaunchSpeed") else PHOTON_LAUNCH_SPEED
        power_cost = float(mod.GetPowerCost()) if hasattr(mod, "GetPowerCost") else 0.0
        return TorpedoAmmoType(name, launch_speed=launch_speed, power_cost=power_cost,
                               max_torpedoes=declared_max, script=script_name)
    except Exception:
        return TorpedoAmmoType("Photon",
                               launch_speed=PHOTON_LAUNCH_SPEED,
                               power_cost=PHOTON_POWER_COST,
                               max_torpedoes=declared_max)


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


_UNSET = object()  # sentinel for ShipClass_GetObjectByID dispatch


def ShipClass_GetObjectByID(pSet_or_id, obj_id=_UNSET) -> "ShipClass | None":
    """Accept both 1-arg (obj_id) and 2-arg (pSet, obj_id) SDK calling conventions.

    The real Appc signature is GetObjectByID(pSet, id); many SDK scripts pass a
    null set as the first argument.  Our headless version ignores the set.

    Dispatch is sentinel-based so that a caller passing None as the explicit id
    (2-arg SDK form: ShipClass_GetObjectByID(SetClass_GetNull(), None)) is
    correctly treated as the 2-arg form rather than collapsing to 1-arg."""
    if obj_id is _UNSET:
        # 1-arg engine form: ShipClass_GetObjectByID(id)
        real_id = pSet_or_id
    else:
        # 2-arg SDK form: ShipClass_GetObjectByID(pSet, id)
        real_id = obj_id
    from engine.core.ids import get_object_by_id
    obj = get_object_by_id(real_id)
    if isinstance(obj, ShipClass):
        return obj
    return None
