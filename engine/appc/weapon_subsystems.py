"""Weapon subsystem hierarchy — split out of engine.appc.subsystems.

Holds the weapon classes (WeaponSystem and its descendants), the
_EnergyWeaponFireMixin, and the weapon-only module helpers. These are part
of engine.appc.subsystems' public surface and are re-exported from there, so
callers continue to ``from engine.appc.subsystems import PhaserSystem`` etc.

The base classes (ShipSubsystem, PoweredSubsystem) and the shared
subsystem-state/position predicates (_is_offline, subsystem_world_position)
stay in engine.appc.subsystems; we import them UP from there. Because of that
import direction, this module must never be imported before
engine.appc.subsystems has finished loading (the façade re-export at the
bottom of subsystems.py guarantees the normal load order).
"""

import math as _math

from engine.appc.math import TGPoint3, TGMatrix3
from engine.appc.subsystems import (
    ShipSubsystem,
    PoweredSubsystem,
    _is_offline,
    subsystem_world_position,
)


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


def _resolve_bank_aim_world(bank, target):
    """Unit vector from a bank's mount Position (world) → target.

    The firing arc originates at the bank's mount point on the ship's
    hull, NOT at the ship's centre of mass and NOT at the strip emit
    point.  Galaxy DorsalPhaser1's Position = (0, 1.27, 0.5) sits a
    full GU forward of ship centre; at close range the two aims
    disagree by tens of degrees, causing arcs to gate inconsistently
    between the fire-time check and the per-tick re-check.  See
    research doc § "Bug F".

    Falls back to ship-pos based aim when the bank has no parent ship
    (legacy fixtures, unit tests).
    """
    if bank is None or target is None or not hasattr(target, "GetWorldLocation"):
        return _resolve_aim_world(None, target)
    if not hasattr(bank, "_emitter_world_position"):
        ship = bank._climb_to_ship() if hasattr(bank, "_climb_to_ship") else None
        return _resolve_aim_world(ship, target)
    origin = bank._emitter_world_position()
    target_pos = target.GetWorldLocation()
    dx = target_pos.x - origin.x
    dy = target_pos.y - origin.y
    dz = target_pos.z - origin.z
    length = (dx * dx + dy * dy + dz * dz) ** 0.5
    if length > 1e-6:
        return TGPoint3(dx / length, dy / length, dz / length)
    # Degenerate: bank Position coincides with target — fall back to
    # ship-forward so the arc gate has a sensible direction to test.
    ship = bank._climb_to_ship() if hasattr(bank, "_climb_to_ship") else None
    return _resolve_aim_world(ship, None)


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

    # Up: rotate the stored body up axis directly into world space.
    up_local = emitter.GetUp() if hasattr(emitter, "GetUp") else TGPoint3(0.0, 0.0, 1.0)
    world_up = TGPoint3(up_local.x, up_local.y, up_local.z)
    if ship is not None and hasattr(ship, "GetWorldRotation"):
        rot = ship.GetWorldRotation()
        if isinstance(rot, TGMatrix3):
            world_up.MultMatrixLeft(rot)

    # Right = world_forward × world_up. Under the right-handed convention
    # (post 2026-06-18 un-mirror: AlignToVectors builds forward × up, det > 0,
    # and the renderer draws R with no reflection) this equals R·(forward×up)
    # = R·GetCol(0) = the TRUE starboard axis the player sees. Deriving it as a
    # cross of the rotated forward/up keeps gate and beam in one frame and is
    # handedness-correct without reading the stored _right. Matches
    # _strip_emit_position. See tests/unit/test_phaser_arc_handedness.py and
    # docs/superpowers/plans/2026-06-18-render-handedness-unmirror.md.
    world_right = TGPoint3(
        world_dir.y * world_up.z - world_dir.z * world_up.y,
        world_dir.z * world_up.x - world_dir.x * world_up.z,
        world_dir.x * world_up.y - world_dir.y * world_up.x,
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
    # Looped SFX handle started by Fire(), stopped by StopFiring().
    self._loop_handle = None
    # Refire hysteresis.  Cleared the moment the bank auto-stops because
    # of depletion; restored once charge climbs past
    # _min_firing_charge + REFIRE_HEADROOM_FRACTION × _max_charge.
    # Without this the bank "blinks" — drops below min for one tick,
    # back above min the next, fires for one frame, repeats.
    # SDK has no setter for this threshold (confirmed against
    # EnergyWeaponProperty); 20% of MaxCharge is a feel-tuned nominal.
    self._armed: bool = True


def _resolve_fire_sound(prop) -> str:
    """Returns the FireSound name (typed accessor) or empty string."""
    if prop is None or not hasattr(prop, "GetFireSound"):
        return ""
    return prop.GetFireSound() or ""


def _spawn_projectile(emitter, mod, *, drf_override=0.0):
    """Spawn an in-flight projectile from `emitter` using SDK module `mod`.

    Shared by torpedo tubes and pulse-weapon cannons. Builds a Torpedo at the
    emitter's world position, runs mod.Create to populate visuals/behaviour,
    applies drf_override (the launcher's DamageRadiusFactor) when > 0, computes
    homing velocity toward the firing ship's live target lock (else dumbfire
    along the emitter/ship forward), registers it, and plays mod.GetLaunchSound.
    Returns the Torpedo, or None if mod is unusable.
    """
    from engine.appc.projectiles import Torpedo, register
    from engine.appc.math import TGPoint3
    from engine.audio.tg_sound import TGSoundManager

    torp = Torpedo()
    source_ship = emitter._climb_to_ship()
    torp._source_ship = source_ship
    torp._position = emitter._emitter_world_position()

    mod.Create(torp)

    # §3.2 DRF override: if the launching tube has a non-zero
    # DamageRadiusFactor (set by the hardpoint script, e.g.
    # galaxy.py ForwardTorpedo1.SetDamageRadiusFactor(0.20)),
    # it overrides the payload value set by mod.Create above.
    # host_loop passes the torpedo as hardpoint_weapon to apply_hit,
    # so torp._damage_radius_factor must carry the launcher value.
    if drf_override > 0.0:
        torp._damage_radius_factor = drf_override

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
            got = emitter.GetDirection()
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

    return torp


class _EnergyWeaponFireMixin:
    """Shared Fire/CanFire/StopFiring/UpdateCharge for PhaserBank / PulseWeapon
    / TractorBeam.  Per-emitter state initialised by _init_energy_weapon_state.
    Each class also has _firing (False at init), _target/_target_offset (None).

    SFX trigger looks up the property's FireSound name and asks TGSoundManager
    to play it.  Tries "<name> Start" first (phaser convention), falls back to
    bare "<name>" (tractor convention).  Names map to WAV assets via
    sdk/Build/scripts/LoadTacticalSounds.py invoked at audio init.
    """

    # Refire hysteresis headroom (fraction of MaxCharge).  Once a bank
    # auto-stops via depletion, it must recharge MinFiringCharge + this
    # fraction × MaxCharge before CanFire returns true again.
    REFIRE_HEADROOM_FRACTION = 0.20

    # Power debited per charge unit recovered during UpdateCharge.  BC's
    # SDK has no per-charge cost field on EnergyWeaponProperty — this is
    # engine-side, tunable.  1.0 means 1 power unit per 1 charge unit;
    # Galaxy's 8 phaser banks × 0.08/s recharge × 1.0 = 0.64 power/s
    # while all eight refill in parallel, vs the warp core's 1000/s
    # output — negligible while the grid is healthy, but enough to
    # halt recharge once the main battery bottoms out.
    POWER_COST_PER_CHARGE = 1.0

    def CanFire(self) -> int:
        parent = self.GetParentSubsystem()
        on = parent is not None and parent.IsOn()
        if not on:
            return 0
        if not self._armed:
            return 0
        charged = self._charge_level >= self._min_firing_charge
        return 1 if charged else 0

    def Fire(self, target=None, offset=None) -> None:
        if not self.CanFire():
            return
        # Edge-trigger the SFX. AI scripts call StartFiring on every
        # evaluation tick; without this gate, each call would spawn a
        # fresh "Phaser Loop" _PlayingSound handle and overwrite
        # self._loop_handle, orphaning every prior handle so they loop
        # forever (no Stop reference). Symptom: continuous phaser SFX
        # during NPC-vs-NPC fights even after all banks deplete.
        was_firing = self._firing
        self._firing = True
        self._target = target
        self._target_offset = offset
        if not was_firing:
            self._play_fire_sfx()

    def StopFiring(self) -> None:
        was_firing = self._firing
        self._firing = False
        if was_firing and self._loop_handle is not None:
            self._loop_handle.Stop()
            self._loop_handle = None

    def IsFiring(self) -> int:
        return 1 if self._firing else 0

    def UpdateCharge(self, dt: float) -> None:
        if self._firing:
            self._charge_level = max(
                0.0, self._charge_level - self._normal_discharge_rate * dt
            )
            if self._charge_level <= 0.0:
                # Depletion auto-stop. BC's banks discharge all the way
                # to 0 while firing (visible on the WeaponsDisplay as the
                # full black → red → yellow → green sweep during recharge)
                # — MinFiringCharge gates fire-start only, not the
                # continuous discharge. _armed stays cleared until the
                # bank recharges past the hysteresis threshold below.
                self._armed = False
                # Route via StopFiring so the looped SFX handle is silenced.
                self.StopFiring()
        else:
            parent = self.GetParentSubsystem()
            if parent is not None and parent.IsOn():
                headroom = self._max_charge - self._charge_level
                if headroom > 0.0:
                    want = min(self._recharge_rate * dt, headroom)
                    if self._bill_recharge(want):
                        self._charge_level += want
            # Re-arm once we cleared the headroom threshold.
            if not self._armed:
                refire_threshold = (self._min_firing_charge
                                    + self.REFIRE_HEADROOM_FRACTION * self._max_charge)
                if self._charge_level >= refire_threshold:
                    self._armed = True

    def _play_fire_sfx(self) -> None:
        """Play the firing bank's Start one-shot + Loop sustained tone.

        Both are attached to the firing ship's scene node so they
        position correctly in 3D space — the WAVs are LS_3D, but a bare
        Play() with no attach_node lands the source at world origin.
        Matches the pattern engine/audio/engine_rumble.py uses for ship-
        attached looping sounds.
        """
        name = _resolve_fire_sound(self.GetProperty())
        if not name:
            return
        from engine.audio.tg_sound import TGSoundManager
        mgr = TGSoundManager.instance()
        attach_node = self._firing_ship_node_id()

        start_snd = mgr.GetSound(name + " Start")
        if start_snd is None:
            # Tractor convention: bare name has no " Start"/" Loop" pair.
            start_snd = mgr.GetSound(name)
        if start_snd is not None:
            start_snd.Play(attach_node=attach_node)

        loop_snd = mgr.GetSound(name + " Loop")
        if loop_snd is not None:
            loop_snd.SetLooping(True)
            self._loop_handle = loop_snd.Play(attach_node=attach_node)

    def _firing_ship_node_id(self) -> int:
        """Walk parent_subsystem → parent_ship → GetSceneNodeId. Returns
        0 (no attachment) when any link is missing — playback degrades
        to world-origin rather than crashing on legacy fixtures."""
        parent_sys = self.GetParentSubsystem() if hasattr(self, "GetParentSubsystem") else None
        if parent_sys is None:
            return 0
        parent_ship = parent_sys.GetParentShip() if hasattr(parent_sys, "GetParentShip") else None
        if parent_ship is None:
            return 0
        getter = getattr(parent_ship, "GetSceneNodeId", None)
        return int(getter()) if getter else 0

    def _bill_recharge(self, charge_amount: float) -> int:
        """Charge POWER_COST_PER_CHARGE × charge_amount against the firing
        ship's PowerSubsystem.  Returns 1 if billed (or if the gate
        doesn't apply — ship has no PowerSubsystem, or its
        PowerSubsystem has no bound PowerProperty meaning a Phase-1
        test stub without a power plant).  Returns 0 if the gate
        engaged and the grid couldn't cover it — UpdateCharge skips
        the refill that tick."""
        if charge_amount <= 0.0:
            return 1
        ship = self._climb_to_ship()
        if ship is None:
            return 1
        ps = ship.GetPowerSubsystem() if hasattr(ship, "GetPowerSubsystem") else None
        if ps is None or ps.GetProperty() is None:
            return 1
        cost = float(charge_amount) * self.POWER_COST_PER_CHARGE
        return ps.StealPower(cost)


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

    # ── Parent-aggregator predicates ───────────────────────────────────
    # WeaponSystem parents own their hardpoint emitters (PhaserBank,
    # TorpedoTube, PulseWeapon, TractorBeam) as _children. Damage lands
    # on the children via apply_hit's spherical-splash loop, which walks
    # every non-hull subsystem and weights damage by proximity to the
    # impact point; the parent surfaces aggregated state to SDK/UI
    # consumers without storing its own condition pool.
    #
    # Locked semantics from the combat damage pipeline roadmap:
    #   IsDamaged   = self._damaged or any(c.IsDamaged() or c.IsDestroyed() for c in children)
    #   IsDisabled  = children and all(c.IsDisabled()  for c in children)
    #   IsDestroyed = self._destroyed or (children and all(c.IsDestroyed() for c in children))
    #
    # Empty-children edge: a weapon system with no hardpoints falls
    # through to the condition-based ShipSubsystem predicates. A default-
    # constructed parent (condition == max_condition) still reports zero;
    # leaf emitters with damaged condition report the damage themselves.

    def IsDamaged(self) -> int:
        if not self._children:
            # Leaf emitter (no sub-hardpoints): use condition-based predicate.
            return ShipSubsystem.IsDamaged(self)
        if self._damaged:
            # Honour the explicit flag set by ShipSubsystem.SetDamaged.
            return 1
        for c in self._children:
            if c.IsDamaged() or c.IsDestroyed():
                return 1
        return 0

    def IsDisabled(self) -> int:
        if not self._children:
            # Leaf emitter: use condition-based predicate.
            return ShipSubsystem.IsDisabled(self)
        for c in self._children:
            if not c.IsDisabled():
                return 0
        return 1

    def IsDestroyed(self) -> int:
        if not self._children:
            # Leaf emitter: use condition-based predicate.
            return ShipSubsystem.IsDestroyed(self)
        if self._destroyed:
            # Honour the explicit flag set by ShipSubsystem.SetDestroyed.
            return 1
        for c in self._children:
            if not c.IsDestroyed():
                return 0
        return 1

    def StartFiring(self, target=None, offset=None) -> None:
        if not self.IsOn():
            return
        # Disabled-weapons gate: when every child reports disabled (Project 2
        # aggregation), the parent IsDisabled is 1 — block fire. Spec §4.2.
        if _is_offline(self):
            return
        n = self.GetNumWeapons()
        if n == 0:
            return
        # Resolve aim per-bank: the firing arc originates at each bank's
        # mount Position, not the ship centre. See research doc § Bug F.
        ship = self.GetParentShip()

        start = self._next_emitter_index % n
        for delta in range(n):
            idx = (start + delta) % n
            emitter = self.GetWeapon(idx)
            if emitter is None:
                continue
            aim_world = (_resolve_bank_aim_world(emitter, target)
                         if target is not None
                         else _resolve_aim_world(ship, None))
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

    def StopFiringAtTarget(self, pTarget) -> None:
        """SDK Preprocessors.py:274/469 — alias for StopFiring() since
        headless doesn't model multi-target firing state."""
        self.StopFiring()

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
    def __init__(self, name: str, launch_speed: float = 0.0, power_cost: float = 0.0):
        self._name = name
        # SDK TorpedoRun.py:130 / StationaryAttack.py:78 use launch speed to
        # predict the torpedo's intercept point.  Real BC tunes this per ammo
        # type via the hardpoint scripts; Phase 1 keeps a single scalar.
        self._launch_speed = float(launch_speed)
        # SDK Preprocessors.py:563 reads GetPowerCost() to *rate* ammo types;
        # the C++ Appc engine also bills it from PowerSubsystem each shot.
        # Sourced from the projectile script's GetPowerCost() at seed time.
        self._power_cost = float(power_cost)

    def GetAmmoName(self) -> str:
        return self._name

    def GetLaunchSpeed(self) -> float:
        """SDK TorpedoRun.py:130 — used to predict torpedo intercept points."""
        return float(self._launch_speed)

    def GetPowerCost(self) -> float:
        """SDK App.py:9570 — per-shot power debit billed against the firing
        ship's PowerSubsystem.  Stock values: Photon=20, Quantum=30,
        Klingon=40, PhasedPlasma=40, Cardassian=10, FusionBolt=10,
        PositronTorpedo=10, KessokDisruptor=30 — see
        sdk/Build/scripts/Tactical/Projectiles/*.py."""
        return float(self._power_cost)

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

    def GetCurrentAmmoType(self):
        """SDK TorpedoRun.py:130 / StationaryAttack.py:78 — returns the
        currently-selected ammo type, or None if no ammo configured.

        Phase 1 semantics: returns the lowest-numbered loaded slot's ammo.
        Real BC tracks a separate "selected" slot via UI cycling; until a
        body needs that distinction, lowest-slot is a faithful default."""
        if not self._ammo_by_slot:
            return None
        lowest_slot = min(self._ammo_by_slot.keys())
        return self._ammo_by_slot[lowest_slot]


# Global phaser fire-range gate. Reconstructed from disassembly:
# Appc.dll exposes PhaserBank_GetMaxPhaserRange (sdk/.../App.py:11511) as
# a per-bank getter that nothing in the SDK ever sets — the engine fills
# it in internally from a single global ("phaser beam range normalisation"
# at 0x008E53DC). Player observation in stock BC (Galaxy class, HUD reading
# ~123 km when phasers still engaged) gives 700 GU = 122.5 km. Per-bank
# MaxDamageDistance (60.0 for Galaxy, 70.0 for Sovereign, etc.) controls
# damage falloff shape, not the firing gate.
PHASER_MAX_RANGE_GU = 700.0


class PhaserSystem(WeaponSystem):
    # Power-level constants from sdk/.../App.py:6444-6446.
    PP_LOW = 0
    PP_HIGH = 1

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._power_level = self.PP_HIGH
        self._single_fire: int = 0
        self._aimed_weapon: int = 0
        # True while the player is holding LBUTTON.  Set by StartFiring,
        # cleared by StopFiring.  The per-frame combat tick retries banks
        # that have re-charged above MinFiringCharge while held.
        self._fire_held: bool = False
        self._held_target = None
        self._held_offset = None

    def SetPowerLevel(self, level) -> None:
        self._power_level = int(level)

    def GetPowerLevel(self) -> int:
        return self._power_level

    def GetSingleFire(self) -> int:                 return self._single_fire
    def SetSingleFire(self, v) -> None:             self._single_fire = int(v)
    def GetAimedWeapon(self) -> int:                return self._aimed_weapon
    def SetAimedWeapon(self, v) -> None:            self._aimed_weapon = int(v)

    def _target_in_system_range(self, ship, target) -> bool:
        """True iff `target` is within global phaser fire range
        (PHASER_MAX_RANGE_GU, ≈122.5 km — see module-level comment).

        BC's phaser fire-range gate is a single engine-wide constant,
        not per-bank: MaxDamageDistance scales damage falloff only.
        No charge drain, no beam, no SFX when the target is beyond
        the global range.

        Legacy fixture support: if either ship or target lacks
        GetWorldLocation, returns True so non-positional tests keep
        their previous behaviour.
        """
        if ship is None or target is None:
            return False
        if not hasattr(ship, "GetWorldLocation") or not hasattr(target, "GetWorldLocation"):
            return True
        sp = ship.GetWorldLocation()
        tp = target.GetWorldLocation()
        dx, dy, dz = tp.x - sp.x, tp.y - sp.y, tp.z - sp.z
        dist_sq = dx*dx + dy*dy + dz*dz
        return dist_sq <= PHASER_MAX_RANGE_GU * PHASER_MAX_RANGE_GU

    def StartFiring(self, target=None, offset=None) -> None:
        """Dispatch — fires the next eligible PhaserBank.

        Galaxy and most stock BC ships set SetSingleFire(1) on their
        phaser system, meaning only one bank is firing at any given
        moment; depletion cycles to the next ready bank.  When
        SetSingleFire(0) every eligible bank fires simultaneously.

        Sets _fire_held so retry_held_fire() can re-fire banks as they
        recharge while the trigger stays down.
        """
        if not self.IsOn() or target is None:
            return
        # Disabled-weapons gate: parent aggregates child IsDisabled (Project 2).
        # When all banks are disabled the parent flips disabled and we bail.
        # Spec §4.2.
        if _is_offline(self):
            return
        ship = self.GetParentShip()
        if not self._target_in_system_range(ship, target):
            return
        self._fire_held = True
        self._held_target = target
        self._held_offset = offset
        self._currently_firing = []
        self._dispatch_one_or_all(target, offset, ship)

    def StopFiring(self, *args) -> None:
        self._fire_held = False
        self._held_target = None
        self._held_offset = None
        super().StopFiring(*args)

    def retry_held_fire(self) -> None:
        """Re-attempt firing while LBUTTON is held.  In SingleFire mode
        only re-fires when no bank is currently firing — preserving the
        one-bank-at-a-time cadence.  In multi-fire mode tops up any
        bank that climbed back past its CanFire threshold."""
        if not self._fire_held or self._held_target is None:
            return
        if not self.IsOn():
            return
        # Disabled-weapons gate: system flipped disabled mid-burst —
        # stop firing cleanly (clears _fire_held + walks _currently_firing
        # to call bank.StopFiring on each). Spec §4.2.
        if _is_offline(self):
            self.StopFiring()
            return
        ship = self.GetParentShip()
        target = self._held_target
        if hasattr(target, "IsDead") and target.IsDead():
            self.StopFiring()
            return
        if not self._target_in_system_range(ship, target):
            # Target has drifted out of range during a held-fire burst.
            # Stop the held state entirely — re-engaging requires a fresh trigger.
            self.StopFiring()
            return
        if self._single_fire:
            # If any bank is still firing, don't dispatch another — wait
            # for the active bank to deplete before round-robin advances.
            for i in range(self.GetNumWeapons()):
                bank = self.GetWeapon(i)
                if bank is not None and bank.IsFiring():
                    return
        self._dispatch_one_or_all(target, self._held_offset, ship)

    def _dispatch_one_or_all(self, target, offset, ship) -> None:
        """SingleFire: fire one eligible bank starting from the round-robin
        cursor, then advance the cursor.  Otherwise fire every eligible
        bank simultaneously.

        Aim is resolved per-bank via _resolve_bank_aim_world so each
        bank's arc gate sees the direction from its own mount Position
        to the target — see research doc § Bug F.
        """
        n = self.GetNumWeapons()
        if n == 0:
            return
        if self._single_fire:
            start = self._next_emitter_index % n
            for delta in range(n):
                idx = (start + delta) % n
                bank = self.GetWeapon(idx)
                if bank is None:
                    continue
                aim_world = _resolve_bank_aim_world(bank, target)
                if not _emitter_in_arc(bank, ship, aim_world):
                    continue
                if hasattr(bank, "CanFire") and bank.CanFire():
                    bank.Fire(target, offset)
                    self._currently_firing.append(idx)
                    self._next_emitter_index = (idx + 1) % n
                    return
            return
        # Multi-bank — every eligible bank engages.
        for i in range(n):
            bank = self.GetWeapon(i)
            if bank is None:
                continue
            aim_world = _resolve_bank_aim_world(bank, target)
            if not _emitter_in_arc(bank, ship, aim_world):
                continue
            if hasattr(bank, "CanFire") and bank.CanFire():
                bank.Fire(target, offset)
                self._currently_firing.append(i)


class PulseWeaponSystem(WeaponSystem):
    """Pulse-weapon (disruptor/cannon) aggregator.

    Like PhaserSystem but its emitters fire discrete projectile bolts (no
    beam, no global range gate — projectile lifetime bounds range). Honors
    SingleFire: round-robin one cannon when set, fire all eligible cannons
    when clear. Held-fire is driven per-frame by retry_held_fire from
    host_loop._advance_combat.
    """
    def __init__(self, name: str = ""):
        super().__init__(name)
        self._single_fire: int = 0
        self._fire_held: bool = False
        self._held_target = None
        self._held_offset = None

    def GetSingleFire(self) -> int:        return self._single_fire
    def SetSingleFire(self, v) -> None:    self._single_fire = int(v)

    def StartFiring(self, target=None, offset=None) -> None:
        """Dispatch — fires pulse cannons per SingleFire mode.

        SingleFire(1) round-robins one eligible cannon per trigger;
        SingleFire(0) fires every eligible cannon together. Sets
        _fire_held so retry_held_fire() re-engages cannons as they
        clear cooldown + recharge while the trigger stays down.

        No range gate (unlike PhaserSystem): a pulse bolt's lifetime
        bounds its range, so the only fire gates are arc + charge +
        cooldown.
        """
        if not self.IsOn() or target is None:
            return
        # Disabled-weapons gate: parent aggregates child IsDisabled (Project 2).
        if _is_offline(self):
            return
        self._fire_held = True
        self._held_target = target
        self._held_offset = offset
        self._currently_firing = []
        self._dispatch_one_or_all(target, offset, self.GetParentShip())

    def StopFiring(self, *args) -> None:
        self._fire_held = False
        self._held_target = None
        self._held_offset = None
        super().StopFiring(*args)

    def retry_held_fire(self) -> None:
        """Re-attempt firing while the trigger is held. Cannons that are
        still on cooldown / under-charged are skipped by their own
        CanFire(); this just re-runs the dispatch each frame so cannons
        re-engage as they recover."""
        if not self._fire_held or self._held_target is None:
            return
        if not self.IsOn():
            return
        # Disabled-weapons gate: system flipped disabled mid-burst — stop
        # cleanly (clears _fire_held + walks _currently_firing).
        if _is_offline(self):
            self.StopFiring()
            return
        target = self._held_target
        if hasattr(target, "IsDead") and target.IsDead():
            self.StopFiring()
            return
        self._dispatch_one_or_all(target, self._held_offset, self.GetParentShip())

    def _dispatch_one_or_all(self, target, offset, ship) -> None:
        """SingleFire: fire one eligible cannon starting from the round-robin
        cursor, then advance the cursor. Otherwise fire every eligible
        cannon simultaneously.

        Aim is resolved per-cannon via _resolve_bank_aim_world so each
        cannon's arc gate sees the direction from its own mount Position
        to the target — mirrors PhaserSystem._dispatch_one_or_all.
        """
        n = self.GetNumWeapons()
        if n == 0:
            return
        if self._single_fire:
            start = self._next_emitter_index % n
            for delta in range(n):
                idx = (start + delta) % n
                cannon = self.GetWeapon(idx)
                if cannon is None:
                    continue
                aim_world = _resolve_bank_aim_world(cannon, target)
                if not _emitter_in_arc(cannon, ship, aim_world):
                    continue
                if hasattr(cannon, "CanFire") and cannon.CanFire():
                    cannon.Fire(target, offset)
                    self._currently_firing.append(idx)
                    self._next_emitter_index = (idx + 1) % n
                    return
            return
        # Multi-fire — every eligible cannon engages.
        for i in range(n):
            cannon = self.GetWeapon(i)
            if cannon is None:
                continue
            aim_world = _resolve_bank_aim_world(cannon, target)
            if not _emitter_in_arc(cannon, ship, aim_world):
                continue
            if hasattr(cannon, "CanFire") and cannon.CanFire():
                cannon.Fire(target, offset)
                self._currently_firing.append(i)


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
        # Per-shot cooldown countdown. Set to GetCooldownTime() at Fire,
        # decremented in UpdateCharge; gates CanFire while > 0.
        self._cooldown_remaining: float = 0.0

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

    # ── Discrete-shot firing (overrides the beam mixin behaviour) ───────────
    # Pulse cannons fire projectile bolts, not held beams: Fire spawns one
    # bolt, dumps accumulated charge, and starts a per-shot cooldown. There
    # is no looping SFX and _firing never stays True — so the mixin's
    # UpdateCharge always takes the RECHARGE branch (see below).

    def CanFire(self) -> int:
        if self._cooldown_remaining > 0.0:
            return 0
        return _EnergyWeaponFireMixin.CanFire(self)

    def Fire(self, target=None, offset=None) -> None:
        if not self.CanFire():
            return
        prop = self.GetProperty()
        script = prop.GetModuleName() if (prop is not None and hasattr(prop, "GetModuleName")) else ""
        if not script:
            return
        import importlib
        try:
            mod = importlib.import_module(script)
        except ImportError:
            return
        # Power gate — silent no-op if the grid can't cover the shot
        # (matches torpedoes). Charge is NOT drained on a blocked shot.
        if not self._debit_pulse_power(mod):
            return
        _spawn_projectile(self, mod, drf_override=self.GetDamageRadiusFactor())
        # Discrete drain: dump accumulated charge + start cooldown. No held beam.
        self._charge_level = 0.0
        self._cooldown_remaining = self.GetCooldownTime()
        self._armed = False  # re-arms in UpdateCharge once past the refire threshold

    def _debit_pulse_power(self, mod) -> int:
        """Bill the firing ship's PowerSubsystem for this bolt's GetPowerCost().

        Mirrors TorpedoTube._debit_power: returns 1 if billed (or if the gate
        doesn't apply — ship has no PowerSubsystem, or its PowerSubsystem has
        no bound PowerProperty meaning a Phase-1 test stub without a power
        plant). Returns 0 if the gate engaged and the grid couldn't cover the
        cost — caller treats that as a silent no-op.
        """
        ship = self._climb_to_ship()
        if ship is None:
            return 1
        ps = ship.GetPowerSubsystem() if hasattr(ship, "GetPowerSubsystem") else None
        if ps is None or ps.GetProperty() is None:
            return 1
        cost = float(mod.GetPowerCost()) if hasattr(mod, "GetPowerCost") else 0.0
        if cost <= 0.0:
            return 1
        return ps.StealPower(cost)

    def UpdateCharge(self, dt: float) -> None:
        if self._cooldown_remaining > 0.0:
            self._cooldown_remaining = max(0.0, self._cooldown_remaining - dt)
        # _firing stays False for pulse weapons, so the mixin takes the
        # RECHARGE branch and re-arms via the existing hysteresis threshold.
        _EnergyWeaponFireMixin.UpdateCharge(self, dt)

    def StopFiring(self) -> None:
        # Discrete weapon — no _loop_handle to silence; just clear target refs.
        self._firing = False
        self._target = None
        self._target_offset = None


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
        if not self._debit_power():
            # Insufficient power: silent no-op (matches BC — UI never
            # pops a "low power" dialog mid-combat, the tube just
            # doesn't fire).  Tube stays loaded; higher-level dispatch
            # may round-robin to a different tube or AI may retry.
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

    def _debit_power(self) -> int:
        """Bill the firing ship's PowerSubsystem for this shot's cost.

        Returns 1 if billed in full (or if the gate doesn't apply —
        ship has no PowerSubsystem, or its PowerSubsystem has no bound
        PowerProperty meaning this is a Phase-1 test stub without a
        power plant).  Returns 0 if the gate engaged and combined
        available + main battery couldn't cover the cost — caller
        treats that as a silent no-op.
        """
        ship = self._climb_to_ship()
        if ship is None:
            return 1
        ps = ship.GetPowerSubsystem() if hasattr(ship, "GetPowerSubsystem") else None
        if ps is None or ps.GetProperty() is None:
            return 1
        parent = self.GetParentSubsystem()
        ammo = parent.GetCurrentAmmoType() if (
            parent is not None and hasattr(parent, "GetCurrentAmmoType")
        ) else None
        cost = float(ammo.GetPowerCost()) if (
            ammo is not None and hasattr(ammo, "GetPowerCost")
        ) else 0.0
        if cost <= 0.0:
            return 1
        return ps.StealPower(cost)

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

        _spawn_projectile(self, mod, drf_override=self.GetDamageRadiusFactor())

    def StopFiring(self) -> None:
        self._firing = False

    def FireDumb(self, iReserved=0, iForce=1) -> None:
        """SDK Preprocessors.py:458 — `pTube.FireDumb(0, 1)` in the
        dumb-fire path. Routes through the regular Fire() so the
        ET_WEAPON_HIT combat broadcast still fires.

        iReserved/iForce kept for SDK signature compatibility; the
        target/offset come from upstream FireScript state in Phase 1.
        """
        self.Fire(target=None, offset=None)

    def CalculateRoughDirection(self):
        """SDK Preprocessors.py:456 — returns the tube's local forward
        vector. Per-tube arcs are deferred to Slice D; until then, all
        tubes share the parent ship's forward vector. Orphaned tubes
        (no parent ship) return the model's +Y axis as a safe default."""
        import App
        return App.TGPoint3_GetModelForward()

    def IsFiring(self) -> int:
        return 1 if self._firing else 0

    def UpdateReload(self, dt: float) -> None:
        if self._num_ready >= self._max_ready:
            return
        import time as _time
        if _time.monotonic() - self._last_fire_time >= self._reload_delay:
            self._num_ready += 1
            self._last_fire_time = _time.monotonic()
