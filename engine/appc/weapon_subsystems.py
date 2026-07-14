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
from engine.appc.float_range_watcher import FloatRangeWatcher
from engine.appc.subsystems import (
    ShipSubsystem,
    PoweredSubsystem,
    _is_offline,
    subsystem_world_position,
)


# ── Torpedo spread-volley tuning (Python, no rebuild) ───────────────────────
# Divergence angle for spread volleys: each fanned torp launches this far off
# the base aim (tangent of 15°), so a Dual/Quad spread visibly splays before
# converging.  _SPREAD_DELAY is the hold-before-homing duration (s): the torp
# flies straight along its fanned launch direction, then homing engages and it
# curves back onto the target — a deferred fan then converge.
_SPREAD_DIVERGENCE_TAN = _math.tan(_math.radians(15.0))  # ≈0.268
_SPREAD_DELAY = 0.2


# ── Torpedo reload slots ───────────────────────────────────────────────────
# BC stores one float per MaxReady at TorpedoTube+0xAC
# (docs/gameplay/combat-and-damage.md:748).  We store the
# GAME TIME at which each slot began cooling; _SLOT_LOADED means "ready".
_SLOT_LOADED = -1.0


def _game_time() -> float:
    """The game clock — pause-frozen and frame-rate independent.

    NEVER time.monotonic(): wall time advances while the sim is frozen, which
    made every tube instantly reload on unpause.  Deferred import is the
    established idiom in this module (see _spawn_torpedo).

    The import lives INSIDE the try: an ImportError here must fall through to
    the same 0.0 sentinel as any other clock failure, not escape uncaught.

    The 0.0 fallback is silent by design (a per-frame weapon loop must never
    raise), but silent-and-permanent is dangerous here: CanFire's gate
    (0 - 0 = 0 < ImmediateDelay) and UpdateReload's gate (0 - 0 = 0 <
    ReloadDelay) both stay false forever once every stamp is 0.0, bricking
    every torpedo tube with no exception anywhere. Route the swallow through
    dev_mode.log_swallowed (same idiom as _broadcast_reload below) so a
    developer can see it happened instead of just watching torpedoes stop
    reloading."""
    try:
        import App
        return float(App.g_kUtopiaModule.GetGameTime())
    except Exception as _e:
        from engine import dev_mode
        dev_mode.log_swallowed("torpedo tube _game_time clock read", _e)
        return 0.0


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


def _emitter_world_direction(emitter, ship) -> TGPoint3:
    """The emitter's mount direction rotated into WORLD space.

    This is what BC's Weapon::CalculateRoughDirection returns.  Evidence:
    AI/Preprocessors.py:447-456 dots the result against a world-space target
    delta, and AI/PlainAI/IntelligentCircleObject.py:204,234 converts it
    world->model explicitly ("Change it to model space").

    DISTINCT from GetDirection(), which stays MODEL space — ConditionTorpsReady
    .py:128 dots that against a model-space restriction vector.  Do not conflate.

    Orphaned emitter (no owning ship): return the un-rotated body direction.

    Guards on hasattr, not isinstance(emitter, ShipSubsystem): _emitter_in_arc
    reuses this helper with duck-typed test doubles (see
    tests/unit/test_property_set_orientation.py::_FakeEmitter) that implement
    GetDirection() without subclassing ShipSubsystem.
    """
    local = emitter.GetDirection() if hasattr(emitter, "GetDirection") else None
    if not isinstance(local, TGPoint3):
        local = TGPoint3(0.0, 1.0, 0.0)     # BC model-forward default
    world = TGPoint3(local.x, local.y, local.z)
    if ship is not None and hasattr(ship, "GetWorldRotation"):
        rot = ship.GetWorldRotation()
        if isinstance(rot, TGMatrix3):
            world.MultMatrixLeft(rot)       # v_world = R . v_body (column-vector)
    return world


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
    world_dir = _emitter_world_direction(emitter, ship)

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



def _spawn_projectile(emitter, mod, *, drf_override=0.0,
                      spread_unit=None, homing_delay=0.0):
    """Spawn an in-flight projectile from `emitter` using SDK module `mod`.

    Shared by torpedo tubes and pulse-weapon cannons. Builds a Torpedo at the
    emitter's world position, runs mod.Create to populate visuals/behaviour,
    applies drf_override (the launcher's DamageRadiusFactor) when > 0, computes
    homing velocity toward the firing ship's live target lock (else dumbfire
    along the emitter/ship forward), registers it, and plays mod.GetLaunchSound.
    Returns the Torpedo, or None if mod is unusable.

    `spread_unit` (a world-space unit TGPoint3) tilts the launch direction
    sideways by _SPREAD_DIVERGENCE_TAN for a fan-out volley; `homing_delay`
    (s) is stamped onto the torp so homing is suppressed until it has flown
    straight along the fanned direction for that long.  Defaults (None / 0.0)
    keep every non-spread shot byte-identical.
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

    # Spread fan-out: tilt the launch direction sideways along spread_unit,
    # preserving the launch speed magnitude.  Skipped (velocity unchanged) if
    # no divergence requested, the velocity is degenerate, or the tilted
    # vector collapses to zero.
    if spread_unit is not None:
        speed = torp._velocity.Length()
        if speed > 1e-6:
            base = TGPoint3(
                torp._velocity.x / speed,
                torp._velocity.y / speed,
                torp._velocity.z / speed,
            )
            new = TGPoint3(
                base.x + _SPREAD_DIVERGENCE_TAN * spread_unit.x,
                base.y + _SPREAD_DIVERGENCE_TAN * spread_unit.y,
                base.z + _SPREAD_DIVERGENCE_TAN * spread_unit.z,
            )
            new_len = new.Length()
            if new_len > 1e-6:
                torp._velocity = TGPoint3(
                    new.x / new_len * speed,
                    new.y / new_len * speed,
                    new.z / new_len * speed,
                )

    torp._homing_start_age = float(homing_delay)

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
            if parent is None or parent.IsOn():
                factor = max(0.0, parent.GetNormalPowerPercentage()
                             if parent is not None else 1.0)
                headroom = self._max_charge - self._charge_level
                if headroom > 0.0:
                    want = min(self._recharge_rate * factor * dt, headroom)
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


def _cloak_blocks_fire(weapon_system) -> bool:
    """True when the owning ship is cloaked or mid-cloak, so it cannot fire.

    BC forces all weapons offline for as long as the cloak is engaged — you
    sacrifice offence for invisibility.  ``IsTryingToCloak()`` is true for both
    CLOAKING (fading out) and CLOAKED; a DECLOAKING ship is already committed to
    reappearing and may fire.  Cheap and raise-safe: ships with no cloak (the
    common case) climb to a None subsystem and fall straight through.
    """
    ship = (weapon_system.GetParentShip()
            if hasattr(weapon_system, "GetParentShip") else None)
    if ship is None:
        return False
    getter = getattr(ship, "GetCloakingSubsystem", None)
    if getter is None:
        return False
    cloak = getter()
    return cloak is not None and bool(cloak.IsTryingToCloak())


def _target_undetectable(weapon_system, target) -> bool:
    """True when the firing ship cannot detect *target* (fully cloaked, nebula
    lock-break, or degraded/offline sensors).

    Mirrors the authoritative per-tick chokepoint in host_loop._advance_combat
    (``can_detect(ship, target)`` → ``bank.StopFiring()``) at the *fire-
    initiation* points, so the warm-up SFX never starts on a shot the damage
    tick would immediately drop. Without this gate, an AI (or held trigger)
    re-firing every tick at a cloaked target produces a start/stop/restart SFX
    loop — the "ship's horn" bug.

    Raise-safe and cheap: a positionless / sensorless fixture reads back the
    fallback sensor range from ``can_detect`` and is therefore detectable, so
    non-cloak tests are unaffected. A weapon with no resolvable parent ship is
    treated as detectable (no gate)."""
    if target is None:
        return False
    ship = (weapon_system.GetParentShip()
            if hasattr(weapon_system, "GetParentShip") else None)
    if ship is None:
        return False
    try:
        from engine.appc.sensor_detection import can_detect
        return not can_detect(ship, target)
    except Exception:
        return False


class Weapon(ShipSubsystem):
    """BC leaf emitter — sdk/Build/scripts/App.py:5758 `class Weapon(ShipSubsystem)`.

    Deliberately NOT a PoweredSubsystem: in BC a weapon has no power, no IsOn
    and no charge.  Power lives on the parent WeaponSystem; charge lives on
    EnergyWeapon (App.py:6426-6440), which torpedo tubes do not inherit.

    Only the surface the SDK actually calls on a leaf weapon.  DELIBERATELY
    ABSENT (verified zero SDK call sites on a tube): SetFiring,
    IsMemberOfGroup, GetTargetID, IsDumbFire, GetOverallConditionPercentage,
    IsInArc, CanHit, SetSkewFire, IsSkewFire.  IsInArc/CanHit are additionally
    unspecifiable — their BC signatures cannot be recovered from the SDK.

    GetProperty/SetProperty are inherited from ShipSubsystem (subsystems.py:273).
    """

    def __init__(self, name: str = ""):
        super().__init__(name)
        # Seeded here, not in the subclass: IsFiring() must return a real 0 on a
        # fresh weapon.  Without this, __getattr__ hands back a truthy _Stub.
        self._firing: bool = False
        self._target = None
        self._target_offset = None

    def Fire(self, target=None, offset=None, **kwargs) -> None:
        """Discrete shot.  Subclasses implement — the payload differs per weapon
        (TorpedoTube.Fire additionally takes spread_unit/homing_delay for
        Dual/Quad spread volleys; see TorpedoSystem.StartFiring)."""
        raise NotImplementedError

    def CanFire(self) -> int:
        return 0

    def StopFiring(self) -> None:
        self._firing = False

    def IsFiring(self) -> int:
        return 1 if self._firing else 0

    def FireDumb(self, iReserved=0, iForce=1) -> None:
        """SDK AI/Preprocessors.py:458 — `pTube.FireDumb(0, 1)`.  Unguided shot,
        no target.

        The AI calls this WITHOUT checking CanFire() first, so it must be a
        silent no-op when the weapon is NOT READY.  That contract is met by the
        implementing subclass: TorpedoTube.Fire returns early on `not CanFire()`.

        Deliberately NOT gated on CanFire() here.  Doing so would make a subclass
        that has not implemented Fire() silently do nothing forever, instead of
        raising NotImplementedError — trading a loud programming error for the
        silent-failure pattern this engine is riddled with.  "Not ready" is a
        runtime state and must no-op; "not implemented" is a bug and must shout.

        iReserved/iForce are kept for SDK signature compatibility and unused.
        """
        self.Fire(target=None, offset=None)

    def CalculateRoughDirection(self) -> TGPoint3:
        """WORLD-space mount direction.  SDK AI/Preprocessors.py:456 and
        AI/PlainAI/IntelligentCircleObject.py:234.

        _climb_to_ship() — NOT GetParentShip().  ShipClass._attach_subsystem
        (ships.py:690-700) sets _parent_ship only on TOP-LEVEL subsystems.  A
        torpedo tube is a CHILD of the TorpedoSystem, so its _parent_ship is
        None and GetParentShip() would silently return None on every real tube.
        """
        return _emitter_world_direction(self, self._climb_to_ship())

    def CalculateWeaponAppeal(self) -> float:
        """SDK AI/PlainAI/IntelligentCircleObject.py:238.  The AI sums appeal
        across weapons facing a candidate heading and picks the best facing.

        BC's exact formula is not recoverable from the SDK, so this is an
        APPROXIMATION, not a reproduction: 1.0 for a functional weapon, 0.0 for
        a disabled one.  That yields "face the direction with the most working
        weapons", which matches the caller's intent.
        """
        return 0.0 if self.IsDisabled() else 1.0


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

    def ShouldBeAimed(self) -> int:
        """Does this weapon system have to bear on the target to fire?

        Decompiled stbc.exe (WeaponSystem::ShouldBeAimed, 0x00584070):

            iVar1 = FUN_00584050();                    // this->GetProperty()
            return *(undefined1 *)(iVar1 + 0x51);      // property->m_bAimedWeapon

        i.e. it is *purely* a read of the authored WeaponSystemProperty
        flag written by SetAimedWeapon (+0x51) — no per-class constant, no
        separate storage. The property ctor (0x0069afe0) defaults it to 0,
        and TorpedoSystemProperty's ctor (0x00693f60) does not override it,
        so an unauthored system is free-fire for every weapon type.

        Consumer: AI/Preprocessors.py:642-647 (FireScript.CheckGoodShot)
        skips the whole directional check when this is false.
        """
        prop = self.GetProperty()
        # getattr-with-default, not hasattr: our leaf emitters (PhaserBank,
        # TorpedoTube) also inherit WeaponSystem but carry a PhaserProperty /
        # TorpedoTubeProperty, which has no AimedWeapon byte. The SDK only
        # asks the aggregator, so falling back to the ctor default is inert.
        is_aimed = getattr(prop, "IsAimedWeapon", None)
        if is_aimed is None:
            return 0
        return is_aimed()

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
        # Cloak gate: a cloaked / cloaking ship cannot fire (BC rule).
        if _cloak_blocks_fire(self):
            return
        # Detectability gate: never fire (nor play warm-up SFX) at a target the
        # ship can't detect — cloaked, nebula-hidden, or out of sensor range.
        if _target_undetectable(self, target):
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
    def __init__(self, name: str, launch_speed: float = 0.0, power_cost: float = 0.0,
                 max_torpedoes=None, script=None):
        self._name = name
        # SDK TorpedoRun.py:130 / StationaryAttack.py:78 use launch speed to
        # predict the torpedo's intercept point.  Real BC tunes this per ammo
        # type via the hardpoint scripts; Phase 1 keeps a single scalar.
        self._launch_speed = float(launch_speed)
        # SDK Preprocessors.py:563 reads GetPowerCost() to *rate* ammo types;
        # the C++ Appc engine also bills it from PowerSubsystem each shot.
        # Sourced from the projectile script's GetPowerCost() at seed time.
        self._power_cost = float(power_cost)
        # Projectile module path (SDK App.py:9574 TorpedoAmmoType.GetTorpedoScript),
        # read by AI/Preprocessors.py:566,714.
        self._script = script
        # ── Reserve accounting (SDK GetMaxTorpedoes / GetNumAvailableTorpsToType).
        # max_torpedoes is the hardpoint's SetMaxTorpedoes(slot, n) for this slot.
        # ``None`` marks an UNDECLARED slot (legacy hulls / the Photon fallback):
        # the reserve is inert — no fire gate, no decrement — so those firing
        # paths stay byte-identical.  A declared int (incl. 0) is finite; the type
        # spawns fully loaded (ships are combat-ready; IsFullyLoaded true at start).
        self._unlimited = max_torpedoes is None
        self._max_torpedoes = 0 if max_torpedoes is None else int(max_torpedoes)
        self._available = self._max_torpedoes

    def GetAmmoName(self) -> str:
        return self._name

    def GetMaxTorpedoes(self) -> int:
        """SDK App.py:9572 — this type's capacity (MissionLib.IsFullyLoaded /
        SetMaxTorpsForPlayer compare against it)."""
        return self._max_torpedoes

    def SetMaxTorpedoes(self, n) -> None:
        # Declaring a max makes the type finite (App.py:9573).
        self._max_torpedoes = int(n)
        self._unlimited = False
        if self._available > self._max_torpedoes:
            self._available = self._max_torpedoes

    def GetTorpedoScript(self):
        return self._script

    def SetTorpedoScript(self, script) -> None:
        self._script = script

    def GetAvailable(self) -> int:
        """Rounds currently loaded for this type — the value the system exposes
        as GetNumAvailableTorpsToType(slot)."""
        return self._available

    def SetAvailable(self, n) -> None:
        n = int(n)
        self._available = n if self._unlimited else max(0, min(n, self._max_torpedoes))

    def AddAvailable(self, delta) -> None:
        """Load (+) or expend (-) rounds, clamped to [0, max].  No-op for an
        unlimited (undeclared-max) type."""
        if self._unlimited:
            return
        self._available = max(0, min(self._available + int(delta), self._max_torpedoes))

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
        # Keyed slot table, populated by AddAmmoType during hardpoint setup.
        # SetAmmoType(index) SELECTS a slot (mission/AI ammo switching);
        # it never writes here.  GetNumAmmoTypes counts populated slots.
        self._ammo_by_slot: dict = {}
        # Selected torpedo spread: how many tubes fire per trigger.
        # Single=1 (default), Dual=2, Quad=4.  Pure selection state — the
        # firing path does not consult it yet (future work).
        self._spread: int = 1
        # Selected ammo slot.  None == "lowest populated slot" (the historical
        # default); an int selects that slot when it is populated.  UI type
        # cycling (weapon_config.cycle_torpedo_type) drives this via
        # SetCurrentAmmoSlot / CycleAmmoType so both the readout and the
        # per-shot power cost track the chosen type.
        self._selected_slot = None

    # ── Spread selection state ─────────────────────────────────────────────
    # NOTE: the tube-count heuristic below is the v1 rule for "options the
    # loadout can fire".  BC's authored FiringChainString / firing groups are
    # a later refinement; until a body needs them, tube count is faithful.
    def GetSpreadOptions(self) -> list:
        """Spread counts this loadout can fire, derived from tube count.

        Single (1) is always available.  Dual (2) needs >=2 tubes, Quad (4)
        needs >=4 tubes.  Returned sorted ascending, e.g. [1], [1, 2] or
        [1, 2, 4]."""
        n = self.GetNumWeapons()
        options = [1]
        if n >= 2:
            options.append(2)
        if n >= 4:
            options.append(4)
        return options

    def GetSpread(self) -> int:
        """Current torpedo spread — tubes fired per trigger (Single=1,
        Dual=2, Quad=4).  Defaults to Single."""
        return self._spread

    def SetSpread(self, n) -> None:
        """Select the torpedo spread (Single=1 / Dual=2 / Quad=4).

        Silently clamps to a supported option: if ``n`` is not in
        GetSpreadOptions() the current value is left unchanged."""
        n = int(n)
        if n in self.GetSpreadOptions():
            self._spread = n

    def StartFiring(self, target=None, offset=None) -> None:
        """Fire GetSpread() torpedoes as a fan-out volley in one trigger.

        Single(1) delegates to the base round-robin single shot (byte-identical
        to the pre-spread path).  Dual(2)/Quad(4) pre-scan the eligible tubes,
        clamp the count to how many are actually ready+in-arc, then fire the
        first N with per-shot world divergence axes (±right / ±up) and a
        _SPREAD_DELAY hold-before-homing so the volley splays then converges.
        """
        if not self.IsOn():
            return
        if _is_offline(self):
            return
        if _cloak_blocks_fire(self):
            return
        n = self.GetNumWeapons()
        if n == 0:
            return
        ship = self.GetParentShip()

        # Reserve gate: a finite ammo type (hardpoint-declared max) with no
        # rounds left cannot fire.  Unlimited/undeclared types never gate, so
        # the legacy firing path stays byte-identical.
        ammo = self.GetCurrentAmmoType()
        finite = ammo is not None and not getattr(ammo, "_unlimited", True)
        if finite and ammo.GetAvailable() <= 0:
            return

        # Pre-scan eligible tubes in round-robin order (same aim/arc/CanFire
        # gates the base StartFiring applies per emitter).
        eligible: list[int] = []
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
                eligible.append(idx)

        effective = min(self.GetSpread(), len(eligible))
        # Can't launch more torpedoes than are loaded for a finite type.
        if finite:
            effective = min(effective, ammo.GetAvailable())

        # Torpedoes launched this trigger = growth of _currently_firing across
        # the fire, whichever branch runs (base appends 1, spread appends N).
        fired_before = len(self._currently_firing)

        if effective <= 1:
            # Straight single shot — unchanged.
            super().StartFiring(target, offset)
        else:
            # World divergence axes from the ship rotation (column-vector
            # convention: GetCol(0)=starboard, GetCol(2)=up).  A shim rotation
            # (not a real TGMatrix3) has no usable axes → fall back to a single
            # straight shot rather than crash.
            rot = ship.GetWorldRotation() if (
                ship is not None and hasattr(ship, "GetWorldRotation")) else None
            if not isinstance(rot, TGMatrix3):
                super().StartFiring(target, offset)
            else:
                right = rot.GetCol(0)
                up = rot.GetCol(2)
                axes = [
                    right,
                    TGPoint3(-right.x, -right.y, -right.z),
                    up,
                    TGPoint3(-up.x, -up.y, -up.z),
                ]
                for k in range(effective):
                    idx = eligible[k]
                    emitter = self.GetWeapon(idx)
                    emitter.Fire(target, offset,
                                 spread_unit=axes[k], homing_delay=_SPREAD_DELAY)
                    self._currently_firing.append(idx)
                    self._next_emitter_index = (idx + 1) % n

        # Expend one round of the current type per torpedo actually launched.
        if finite:
            consumed = len(self._currently_firing) - fired_before
            if consumed > 0:
                ammo.AddAvailable(-consumed)

    def GetNumAmmoTypes(self) -> int:
        return len(self._ammo_by_slot)

    # ── SDK ammo-type curation surface (all int-slot indexed) ─────────────────
    # QuickBattle.py:2924 prunes, missions (E3M1) load, MissionLib iterates.
    def RemoveAmmoType(self, slot) -> None:
        """Drop the ammo type at ``slot`` (QuickBattle.py:2924 removes every
        slot past index 1 to strip PhasedPlasma).  QuickBattle removes top-down
        within a single snapshot loop, so no interior gap survives for stock
        hulls and GetNumAmmoTypes()==len stays contiguous."""
        slot = int(slot)
        if slot in self._ammo_by_slot:
            del self._ammo_by_slot[slot]
            if self._selected_slot == slot:
                self._selected_slot = None

    def LoadAmmoType(self, slot, count) -> None:
        """Load (+) / unload (-) ``count`` rounds into the type at ``slot``
        (E3M1.py, MissionLib.LoadTorpedoes).  Clamped to [0, max] by the type."""
        ammo = self.GetAmmoType(slot)
        if ammo is not None and hasattr(ammo, "AddAvailable"):
            ammo.AddAvailable(int(count))

    def GetNumAvailableTorpsToType(self, slot) -> int:
        """Rounds currently loaded for the type at ``slot`` (E3M1.py:2888,
        MissionLib.IsFullyLoaded).  0 when the slot is absent."""
        ammo = self.GetAmmoType(slot)
        if ammo is not None and hasattr(ammo, "GetAvailable"):
            return ammo.GetAvailable()
        return 0

    def FillAmmoType(self, slot) -> None:
        """Top the type at ``slot`` back up to its max (SDK App.py:5981)."""
        ammo = self.GetAmmoType(slot)
        if ammo is not None and hasattr(ammo, "SetAvailable"):
            ammo.SetAvailable(ammo.GetMaxTorpedoes())

    def IsAmmoTypeSelectable(self, slot) -> bool:
        """Whether the type at ``slot`` can be selected/cycled to.

        BC gates the torpedo-type selector on availability, NOT declaration:
        ``GetNumAvailableTorpsToType(iType) > 0`` (AI/Preprocessors.py:537
        ChooseTorpType; the C++ HUD cycler uses the same rule).  So a slot
        declared with SetMaxTorpedoes(slot, 0) — e.g. a Sovereign's PhasedPlasma
        — is present in GetNumAmmoTypes() but never selectable, in missions as
        well as QuickBattle (which additionally hard-removes it).

        Our synthetic UNLIMITED types (the undeclared-max fallback for legacy /
        test hulls) report 0 available but represent an inexhaustible supply, so
        they always count as selectable."""
        ammo = self.GetAmmoType(slot)
        if ammo is None:
            return False
        if getattr(ammo, "_unlimited", False):
            return True
        return self.GetNumAvailableTorpsToType(slot) > 0

    def GetSelectableAmmoSlots(self) -> list:
        """Sorted slots the player can actually select — the live Type menu."""
        return [s for s in sorted(self._ammo_by_slot.keys())
                if self.IsAmmoTypeSelectable(s)]

    def GetCurrentAmmoTypeNumber(self) -> int:
        """SDK App.py:5977 — index of the selected ammo type."""
        return self.GetCurrentAmmoSlot()

    def GetAmmoTypeNumber(self) -> int:
        """SDK App.py:5985 alias used by Bridge handlers."""
        return self.GetCurrentAmmoSlot()

    def AddAmmoType(self, ammo_type) -> None:
        # Append into the next free slot.  This is the only writer of the
        # slot table (hardpoint setup); SetAmmoType merely selects a slot.
        self._ammo_by_slot[len(self._ammo_by_slot)] = ammo_type

    def SetAmmoType(self, ammo_index, _reload_arg=0) -> None:
        # SDK semantics: SELECT the ammo type at index `ammo_index` (0-based,
        # same domain as GetAmmoTypeNumber / range(GetNumAmmoTypes())).  Never
        # a store — hardpoint setup populates slots via AddAmmoType.  Call
        # sites: AI/Preprocessors.py:548,640 (int index from ChooseTorpType),
        # ShipScriptActions.py:400, MissionLib.py:611, E2M0.py:720
        # (App.AT_TWO = 1).  Second arg is always 0 in the SDK (reload
        # time/flag) — accepted, ignored.
        self.SetCurrentAmmoSlot(int(ammo_index))

    def GetAmmoType(self, slot: int):
        return self._ammo_by_slot.get(int(slot))

    def GetCurrentAmmoType(self):
        """SDK TorpedoRun.py:130 / StationaryAttack.py:78 — returns the
        currently-selected ammo type, or None if no ammo configured.

        Returns the selected slot's ammo when SetCurrentAmmoSlot / CycleAmmoType
        has chosen a populated slot; otherwise falls back to the lowest-numbered
        loaded slot (the historical default, preserved so pre-selection callers
        are byte-identical)."""
        if not self._ammo_by_slot:
            return None
        return self._ammo_by_slot[self.GetCurrentAmmoSlot()]

    def GetCurrentAmmoSlot(self) -> int:
        """The effective ammo slot: the explicit selection when set and
        populated, else the lowest populated slot.  Returns -1 when no ammo
        is loaded at all."""
        if not self._ammo_by_slot:
            return -1
        if self._selected_slot is not None and self._selected_slot in self._ammo_by_slot:
            return self._selected_slot
        return min(self._ammo_by_slot.keys())

    def SetCurrentAmmoSlot(self, slot) -> None:
        """Select the given ammo slot.  Ignored silently when the slot is not
        populated (leaves the current selection unchanged)."""
        slot = int(slot)
        if slot in self._ammo_by_slot:
            self._selected_slot = slot

    def CycleAmmoType(self) -> None:
        """Advance the selection to the next SELECTABLE slot (available > 0 or
        unlimited; sorted, wraps).  No-op with 0 or 1 selectable slots — so an
        empty declared type (e.g. PhasedPlasma, max 0) is skipped, never landed
        on."""
        slots = self.GetSelectableAmmoSlots()
        if len(slots) <= 1:
            return
        current = self.GetCurrentAmmoSlot()
        try:
            idx = slots.index(current)
        except ValueError:
            idx = 0
        self._selected_slot = slots[(idx + 1) % len(slots)]


# Global phaser fire-range gate. Reconstructed from disassembly:
# Appc.dll exposes PhaserBank_GetMaxPhaserRange (sdk/.../App.py:11511) as
# a per-bank getter that nothing in the SDK ever sets — the engine fills
# it in internally from a single global ("phaser beam range normalisation"
# at 0x008E53DC). Player observation in stock BC (Galaxy class, HUD reading
# ~123 km when phasers still engaged) gives 700 GU = 122.5 km. Per-bank
# MaxDamageDistance (60.0 for Galaxy, 70.0 for Sovereign, etc.) controls
# damage falloff shape, not the firing gate.
PHASER_MAX_RANGE_GU = 700.0

# Tractor-beam engagement range.  BC's tractor emitters carry a per-bank
# MaxDamageDistance ≈ 118-120 GU (galaxy.py AftTractor2 = 118, vorcha = 120);
# unlike phasers there is no single engine-wide constant, so we gate the whole
# system on a representative 120 GU.  A target drifting past this ends the held
# beam (retry_held_fire calls StopFiring via _can_engage), matching phasers.
TRACTOR_MAX_RANGE_GU = 120.0


# A tractor grips only when the target's shields hold less than this fraction
# of their aggregate maximum (i.e. effectively down).  Active shields deflect.
TRACTOR_SHIELD_DOWN_FRACTION = 0.05


def _target_tractorable(target) -> bool:
    """True iff a tractor beam can grip `target`: its shields are NOT actively
    protecting it — not equipped, offline (lowered), disabled (damaged), or
    depleted.  Active, charged shields deflect the beam (BC behaviour).

    Legacy fixtures with no shield API are gripple (returns True).
    """
    if target is None:
        return False
    getter = getattr(target, "GetShieldSubsystem", None)
    if getter is None:
        return True  # no shield API at all (non-ship targets / test stubs)
    shields = getter()
    if shields is None:
        return True  # not equipped
    if hasattr(shields, "IsDisabled") and shields.IsDisabled():
        return True  # disabled (damaged out)
    if hasattr(shields, "IsOn") and not shields.IsOn():
        return True  # offline / lowered
    # Online + undamaged: blocked only while the shields still hold charge.
    n = getattr(shields, "NUM_SHIELDS", 6)
    try:
        total_max = sum(shields.GetMaxShields(f) for f in range(n))
        if total_max <= 0.0:
            return True  # equipped subsystem but no shield facings
        total_cur = sum(shields.GetCurrentShields(f) for f in range(n))
        return (total_cur / total_max) < TRACTOR_SHIELD_DOWN_FRACTION
    except Exception:
        return False  # can't read charge — assume up (deflects)


def _target_within_range_gu(ship, target, max_range_gu: float) -> bool:
    """True iff `target` is within `max_range_gu` game units of `ship`.

    Shared fire-range gate for energy-weapon aggregators.  Legacy fixture
    support: if either object lacks GetWorldLocation, returns True so
    non-positional tests keep their previous behaviour.
    """
    if ship is None or target is None:
        return False
    if not hasattr(ship, "GetWorldLocation") or not hasattr(target, "GetWorldLocation"):
        return True
    sp = ship.GetWorldLocation()
    tp = target.GetWorldLocation()
    dx, dy, dz = tp.x - sp.x, tp.y - sp.y, tp.z - sp.z
    dist_sq = dx*dx + dy*dy + dz*dz
    return dist_sq <= max_range_gu * max_range_gu


class _HeldFireWeaponSystem(WeaponSystem):
    """Shared held-fire dispatch for energy-emitter aggregators
    (PhaserSystem, PulseWeaponSystem).

    Holds the SingleFire mode and the held-trigger state, and implements
    StartFiring / StopFiring / retry_held_fire / _dispatch_one_or_all.  The
    per-frame combat tick calls retry_held_fire so banks/cannons re-engage
    as they recharge while the trigger stays down.

    SingleFire(1): one eligible emitter fires per trigger, round-robin via
    _next_emitter_index.  SingleFire(0): every eligible emitter engages.

    Subclasses override _can_engage(ship, target) to add a fire-range gate
    (phasers do; pulse weapons don't — a bolt's lifetime bounds its range).
    """
    def __init__(self, name: str = ""):
        super().__init__(name)
        self._single_fire: int = 0
        self._fire_held: bool = False
        self._held_target = None
        self._held_offset = None

    def GetSingleFire(self) -> int:                 return self._single_fire
    def SetSingleFire(self, v) -> None:             self._single_fire = int(v)

    def _can_engage(self, ship, target) -> bool:
        """Fire-range gate hook. Default: no gate. PhaserSystem overrides."""
        return True

    def StartFiring(self, target=None, offset=None) -> None:
        if not self.IsOn() or target is None:
            return
        # Disabled-weapons gate: parent aggregates child IsDisabled (Project 2).
        # When all emitters are disabled the parent flips disabled and we bail.
        if _is_offline(self):
            return
        # Cloak gate: a cloaked / cloaking ship cannot fire (BC rule).
        if _cloak_blocks_fire(self):
            return
        # Detectability gate: don't start a held burst (nor its warm-up SFX) at
        # a target the ship can't detect. See _target_undetectable.
        if _target_undetectable(self, target):
            return
        ship = self.GetParentShip()
        if not self._can_engage(ship, target):
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
        """Re-attempt firing while the trigger is held.  In SingleFire mode
        only re-fires when no emitter is currently firing — preserving the
        one-at-a-time cadence (a no-op for discrete pulse cannons, which
        never stay IsFiring).  In multi-fire mode tops up any emitter that
        climbed back past its CanFire threshold."""
        if not self._fire_held or self._held_target is None:
            return
        if not self.IsOn():
            return
        # Disabled-weapons gate: system flipped disabled mid-burst — stop
        # cleanly (clears _fire_held + walks _currently_firing).
        if _is_offline(self):
            self.StopFiring()
            return
        ship = self.GetParentShip()
        target = self._held_target
        if hasattr(target, "IsDead") and target.IsDead():
            self.StopFiring()
            return
        # Detectability gate: the target cloaked / slipped into a nebula / left
        # sensor range mid-burst — stop the held state entirely so the warm-up
        # SFX doesn't restart every tick (the "ship's horn" loop). Re-engaging
        # requires a fresh trigger (or a fresh AI StartFiring once detectable).
        if _target_undetectable(self, target):
            self.StopFiring()
            return
        if not self._can_engage(ship, target):
            # Target drifted out of range during a held burst — stop the held
            # state entirely; re-engaging requires a fresh trigger.
            self.StopFiring()
            return
        if self._single_fire:
            # If any emitter is still firing, don't dispatch another — wait
            # for the active one to deplete before the round-robin advances.
            for i in range(self.GetNumWeapons()):
                emitter = self.GetWeapon(i)
                if emitter is not None and emitter.IsFiring():
                    return
        self._dispatch_one_or_all(target, self._held_offset, ship)

    def _dispatch_one_or_all(self, target, offset, ship) -> None:
        """SingleFire: fire one eligible emitter starting from the round-robin
        cursor, then advance the cursor.  Otherwise fire every eligible
        emitter simultaneously.

        Aim is resolved per-emitter via _resolve_bank_aim_world so each
        emitter's arc gate sees the direction from its own mount Position
        to the target — see research doc § Bug F.
        """
        n = self.GetNumWeapons()
        if n == 0:
            return
        if self._single_fire:
            start = self._next_emitter_index % n
            for delta in range(n):
                idx = (start + delta) % n
                emitter = self.GetWeapon(idx)
                if emitter is None:
                    continue
                aim_world = _resolve_bank_aim_world(emitter, target)
                if not _emitter_in_arc(emitter, ship, aim_world):
                    continue
                if hasattr(emitter, "CanFire") and emitter.CanFire():
                    emitter.Fire(target, offset)
                    self._currently_firing.append(idx)
                    self._next_emitter_index = (idx + 1) % n
                    return
            return
        # Multi-emitter — every eligible one engages.
        for i in range(n):
            emitter = self.GetWeapon(i)
            if emitter is None:
                continue
            aim_world = _resolve_bank_aim_world(emitter, target)
            if not _emitter_in_arc(emitter, ship, aim_world):
                continue
            if hasattr(emitter, "CanFire") and emitter.CanFire():
                emitter.Fire(target, offset)
                self._currently_firing.append(i)


class PhaserSystem(_HeldFireWeaponSystem):
    # Power-level constants from sdk/.../App.py:6444-6446 (three levels).
    # Values confirmed against the real BC engine (dev-console probe: HIGH=2,
    # LOW=0). PP_LOW is the "disable, don't destroy" mode — it deals no hull
    # damage, only subsystem damage (see combat.apply_hit `damage_hull`).
    PP_LOW = 0
    PP_MEDIUM = 1
    PP_HIGH = 2

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._power_level = self.PP_HIGH
        self._aimed_weapon: int = 0

    def SetPowerLevel(self, level) -> None:
        self._power_level = int(level)

    def GetPowerLevel(self) -> int:
        return self._power_level

    def GetAimedWeapon(self) -> int:                return self._aimed_weapon
    def SetAimedWeapon(self, v) -> None:            self._aimed_weapon = int(v)

    def _can_engage(self, ship, target) -> bool:
        return self._target_in_system_range(ship, target)

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
        return _target_within_range_gu(ship, target, PHASER_MAX_RANGE_GU)


class PulseWeaponSystem(_HeldFireWeaponSystem):
    """Pulse-weapon (disruptor/cannon) aggregator.

    Inherits the held-fire dispatch from _HeldFireWeaponSystem.  Unlike
    PhaserSystem its emitters fire discrete projectile bolts and it keeps the
    base's no-op _can_engage (no fire-range gate — a bolt's lifetime bounds
    its range, so the only fire gates are arc + charge + cooldown).  Held-fire
    is driven per-frame by retry_held_fire from host_loop._advance_combat.
    """
    pass


class TractorBeamSystem(_HeldFireWeaponSystem):
    """Tractor-beam aggregator.

    Shares the held-fire dispatch with PhaserSystem / PulseWeaponSystem: a
    tractor is a UI *toggle* (StartFiring = engage, StopFiring = toggle-off),
    and retry_held_fire (driven from host_loop._advance_combat) sustains the
    beam while the target stays in range.  The hardpoints set SingleFire(1),
    so the SingleFire branch keeps exactly one beam locked on the target.

    Unlike phasers/pulse, a firing tractor does NOT auto-stop on charge
    depletion (TractorBeam.UpdateCharge sustains it), and per frame
    engine.appc.tractor.advance_tractors applies the mode's physics to the
    target.  `_engage_state` caches per-mode engagement geometry (the captured
    HOLD world-point / TOW body-frame offset); it is invalidated on StopFiring
    and on any mode change.
    """
    # q10 ground truth (tools/probes/results/q10_battery_drain.txt): the tractor
    # is a DIRECT main-battery siphon — it bypasses the conduit budget and is
    # unscaled by the power slider (measured 600/s flat with sliders at 1.25).
    # This supersedes the spec's "tractor = conduit mode 0" decision; the manual
    # was right that it draws from Main, the RE doc's mode-1 (backup-first) row
    # is wrong-in-effect. _update_power branches on this flag instead of _draw.
    DRAWS_DIRECT_FROM_MAIN = True

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
        self._engage_state = None

    def _wants_power(self) -> bool:
        """The tractor siphons power only while a beam is actually held (a
        powered-but-idle tractor draws nothing — PowerDisplay's siphon
        semantics).  The draw is a DIRECT main-battery steal (DRAWS_DIRECT_FROM_MAIN,
        q10); the gate here is the firing state, not the alert-driven on/off flag."""
        return bool(self.IsOn()) and self._any_child_firing()

    def _any_child_firing(self) -> bool:
        """True if any child tractor-beam emitter is currently firing.  Same
        child-weapon walk PowerDisplay.HandleTractor uses."""
        for i in range(self.GetNumWeapons()):
            em = self.GetWeapon(i)
            if em is not None and em.IsFiring():
                return True
        return False

    def GetMode(self) -> int:
        return self._mode

    def SetMode(self, mode) -> None:
        new_mode = int(mode)
        if new_mode != self._mode:
            # A mode switch invalidates any captured engagement geometry
            # (e.g. HOLD's pinned world-point or TOW's body-frame offset).
            self._engage_state = None
        self._mode = new_mode

    def IsTryingToFire(self) -> int:
        return self.IsFiring()

    def IsEngaged(self) -> int:
        """The persistent toggle *intent*, independent of the instantaneous
        IsFiring() beam state.  The HUD / F2 menu tractor toggle reflects THIS:
        while engaged the beam auto-fires whenever the target is in range (and
        re-acquires each frame via retry_held_fire), so the button stays "On"
        even if the beam momentarily isn't gripping."""
        return 1 if self._fire_held else 0

    def StartFiring(self, target=None, offset=None) -> None:
        """Record the held ENGAGE intent even when the target isn't immediately
        grippable, so retry_held_fire re-acquires the beam when the geometry
        allows.  (Mirrors the base _HeldFireWeaponSystem.StartFiring but records
        intent BEFORE the engageability check instead of bailing.)"""
        if not self.IsOn() or target is None:
            return
        if _is_offline(self):
            return
        if _cloak_blocks_fire(self):
            return
        self._fire_held = True
        self._held_target = target
        self._held_offset = offset
        ship = self.GetParentShip()
        if self._can_engage(ship, target):
            self._currently_firing = []
            self._dispatch_one_or_all(target, offset, ship)

    def _can_engage(self, ship, target) -> bool:
        # Range gate AND shield gate: a tractor grips only targets whose shields
        # are down (disabled / offline / not equipped / depleted).
        return (_target_within_range_gu(ship, target, TRACTOR_MAX_RANGE_GU)
                and _target_tractorable(target))

    def retry_held_fire(self) -> None:
        """Per-frame held-fire maintenance with arc/shield re-acquisition.

        Unlike the base (which drops the whole held state when the target leaves
        range), a tractor stays ENGAGED until the player toggles it off: if the
        firing emitter swings out of arc on a tight turn — or the target raises
        shields / drifts out of range — the beam switches off but `_fire_held`
        is kept, so it re-fires automatically from any in-arc emitter the moment
        the geometry allows again.
        """
        if not self._fire_held or self._held_target is None:
            return
        if not self.IsOn():
            return
        if _is_offline(self):
            self.StopFiring()           # system disabled — fully disengage
            return
        ship = self.GetParentShip()
        target = self._held_target
        if hasattr(target, "IsDead") and target.IsDead():
            self.StopFiring()           # target gone — fully disengage
            return
        engageable = self._can_engage(ship, target)   # range + shields
        # Drop any emitter that can no longer hold the beam (out of range /
        # shields up / rotated out of arc).  Keep _fire_held so it re-acquires.
        for i in range(self.GetNumWeapons()):
            em = self.GetWeapon(i)
            if em is None or not em.IsFiring():
                continue
            aim = _resolve_bank_aim_world(em, target)
            if (not engageable) or (not _emitter_in_arc(em, ship, aim)):
                em.StopFiring()
                try:
                    self._currently_firing.remove(i)
                except ValueError:
                    pass
        if not engageable:
            return
        # Re-dispatch one eligible in-arc emitter if none is currently firing.
        for i in range(self.GetNumWeapons()):
            em = self.GetWeapon(i)
            if em is not None and em.IsFiring():
                return
        self._dispatch_one_or_all(target, self._held_offset, ship)

    def StopFiring(self, *args) -> None:
        self._engage_state = None
        super().StopFiring(*args)


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
        # FloatRangeWatcher handed to Conditions/ConditionPulseReady.py:163
        # (GetChargeWatcher()); watches the charge FRACTION (charge / max_charge)
        # so the condition's MinFiringCharge/MaxCharge threshold lines up.
        self._charge_watcher = FloatRangeWatcher()

    def GetMaxCharge(self) -> float:                return self._max_charge
    def GetMinFiringCharge(self) -> float:          return self._min_firing_charge
    def GetNormalDischargeRate(self) -> float:      return self._normal_discharge_rate
    def GetRechargeRate(self) -> float:             return self._recharge_rate
    def GetChargeLevel(self) -> float:              return self._charge_level
    def GetCooldownTime(self) -> float:             return self._cooldown_time

    def GetLaunchSpeed(self) -> float:
        """SDK AI/Preprocessors.py:778 (FireScript.GetWeaponInfo) — used to
        lead the AI's aim point on pulse-weapon fire (fTime = fDistance /
        fSpeed, Preprocessors.py:742). There is no authored per-weapon
        launch-speed field; the real value lives on the bound projectile
        module (e.g. Tactical/Projectiles/PulseDisruptor.py:43
        GetLaunchSpeed() -> 55.0), same as the launch speed Fire() itself
        uses via _spawn_projectile (weapon_subsystems.py:308). Resolve it
        the same way: PulseWeaponProperty.GetModuleName() names the
        projectile script; import it and read its GetLaunchSpeed(). Returns
        0.0 (not a hardcoded default) if the property, module name, module,
        or attribute is genuinely absent — matching _spawn_projectile's own
        missing-module fallback rather than inventing a number."""
        prop = self.GetProperty()
        script = prop.GetModuleName() if (prop is not None and hasattr(prop, "GetModuleName")) else ""
        if not script:
            return 0.0
        import importlib
        try:
            mod = importlib.import_module(script)
        except ImportError:
            return 0.0
        return float(mod.GetLaunchSpeed()) if hasattr(mod, "GetLaunchSpeed") else 0.0

    def GetChargeWatcher(self):
        """FloatRangeWatcher on the charge FRACTION
        (Conditions/ConditionPulseReady.py:163)."""
        return self._charge_watcher

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

    # Re-arm at exactly MinFiringCharge — no phaser-style headroom. Stock
    # pulse cannons have a tiny charge margin (BoP: MaxCharge 3.8,
    # MinFiringCharge 3.6); the phaser default (0.20·MaxCharge) would push
    # the refire threshold to 4.36 > MaxCharge, so the cannon could fire
    # exactly once and never re-arm. For pulse weapons the per-shot cooldown
    # (SetCooldownTime, BoP 0.2s) is the anti-flutter mechanism, not charge
    # hysteresis — so RechargeRate alone governs cadence (~9s from empty).
    REFIRE_HEADROOM_FRACTION = 0.0

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
        _spawn_projectile(self, mod, drf_override=self.GetDamageRadiusFactor())
        # Discrete drain: dump accumulated charge + start cooldown. No held beam.
        self._charge_level = 0.0
        self._cooldown_remaining = self.GetCooldownTime()
        self._armed = False  # re-arms in UpdateCharge once past the refire threshold

    def UpdateCharge(self, dt: float) -> None:
        if self._cooldown_remaining > 0.0:
            self._cooldown_remaining = max(0.0, self._cooldown_remaining - dt)
        # _firing stays False for pulse weapons, so the mixin takes the
        # RECHARGE branch and re-arms via the existing hysteresis threshold.
        _EnergyWeaponFireMixin.UpdateCharge(self, dt)
        # Drive the charge watcher with the charge FRACTION so
        # Conditions/ConditionPulseReady.py fires its ET_CHARGE_TOGGLE
        # crossing event (guard divide-by-zero → 0.0).
        self._charge_watcher._update(self.GetChargePercentage())

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

    def UpdateCharge(self, dt: float) -> None:
        """Sustained-hold charge model — overrides the phaser/pulse
        discharge-to-zero auto-stop.

        A tractor holds CONTINUOUSLY while engaged (you can pin a ship
        indefinitely), so a firing tractor must not deplete to 0 and stop the
        way a phaser bank does.  While firing we drain slowly toward — but
        never below — MinFiringCharge (so the beam stays armed and CanFire
        keeps returning true), gated by parent power: if the line goes down
        the beam drops.  When idle we fall back to the mixin's normal
        recharge + re-arm hysteresis.
        """
        if self._firing:
            parent = self.GetParentSubsystem()
            if parent is None or not parent.IsOn():
                # Power loss stops the beam (routes through StopFiring so the
                # looped SFX handle is silenced).
                self.StopFiring()
                return
            # Power starvation: the parent system draws through PowerSubsystem's
            # consumer model now (Task 4); when the grid can't feed the tractor
            # its efficiency collapses to zero while it still wants power, so the
            # beam drops (replaces the old per-tick StealPower gate).
            if (hasattr(parent, "GetPowerPercentage")
                    and parent.GetPowerPercentage() <= 0.0
                    and parent.GetNormalPowerWanted() > 0.0):
                self.StopFiring()
                return
            floor = self._min_firing_charge
            if self._charge_level > floor:
                self._charge_level = max(
                    floor, self._charge_level - self._normal_discharge_rate * dt
                )
            # _armed stays set while sustaining — no depletion auto-stop.
            return
        # Idle fall-through note: an idle TractorBeamSystem doesn't want power
        # (_wants_power False -> factor zeroed by the pump), so the mixin's
        # factor-scaled recharge is 0 while idle. Harmless by design: the firing
        # sustain path never drains below _min_firing_charge, StopFiring keeps
        # _armed set, and CanFire passes at the floor — charge above the floor
        # has no gameplay effect for tractors.
        super().UpdateCharge(dt)


class TorpedoTube(Weapon):
    """Individual launcher under a parent TorpedoSystem.  Ammo-type tracking
    lives on the parent's slot table; this class owns per-tube reload state.

    Reload model recovered from stbc.exe
    (docs/gameplay/combat-and-damage.md:740-830):
    reload state is a per-slot timer array, one slot per MaxReady, driven by
    the GAME clock (not wall time, so a paused sim makes no reload progress).
    ImmediateDelay is a CanFire refire gate (gameTime - last_fire_time >=
    ImmediateDelay), not a fire-to-launch latency. ReloadDelay is the per-slot
    cooldown after firing.
    """
    def __init__(self, name: str = ""):
        super().__init__(name)          # Weapon.__init__ seeds _firing/_target
        self._num_ready: int = 0
        # GAME time. BC inits to -1000.0 (combat-and-damage.md:757) so a fresh
        # tube already satisfies the ImmediateDelay gate. NOT -inf: -inf poisons
        # any subtraction a caller might do on GetLastFireTime().
        self._last_fire_time: float = -1000.0
        self._immediate_delay: float = 0.0
        self._reload_delay: float = 0.0
        self._max_ready: int = 0
        # One slot per MaxReady. Value = game time cooling began; _SLOT_LOADED = ready.
        self._reload_timers: list[float] = []

    def _resize_slots(self) -> None:
        """(Re)build the per-slot reload array to MaxReady, all slots loaded.
        Called by ships.py after the hardpoint property is copied in."""
        self._reload_timers = [_SLOT_LOADED] * max(0, int(self._max_ready))

    def _ensure_slots(self) -> None:
        """Self-heal: rebuild _reload_timers if it has desynced from
        _max_ready. Production always calls _resize_slots() from
        ships.py:_copy_torpedo_tube_fields, but _max_ready is real SDK/test
        surface that can be set directly (six unit-test fixtures do exactly
        that) — without this, a tube that fires would stamp NO slot and
        UpdateReload would find nothing cooling, bricking the tube forever
        with no exception raised.  Called at the top of every method that
        reads or writes _reload_timers."""
        if len(self._reload_timers) != self._max_ready:
            self._resize_slots()

    def _start_slot_cooldown(self, now: float) -> None:
        """Put one loaded slot into cooldown, stamped at `now`."""
        self._ensure_slots()
        for i in range(len(self._reload_timers)):
            if self._reload_timers[i] == _SLOT_LOADED:
                self._reload_timers[i] = now
                return

    def _sync_slots_to_num_ready(self) -> None:
        """Keep _reload_timers consistent after a direct _num_ready mutation.

        SetNumReady/IncNumReady/DecNumReady are real SDK surface (App.py:
        6018-6020) — a mission can call them directly, bypassing Fire/
        ReloadTorpedo.  Without this, the slot array and _num_ready silently
        disagree: e.g. SetNumReady(0) left every slot LOADED, so UpdateReload
        found nothing cooling and the tube never refilled.

        Demotes/promotes the minimum number of slots needed to make exactly
        `_num_ready` (clamped to the slot count) read LOADED: demoted slots
        start cooling from now; promotion prefers the slot that has been
        cooling longest (smallest stamp), matching ReloadTorpedo's own
        "oldest cooling slot wins" rule."""
        self._ensure_slots()
        target = max(0, min(int(self._num_ready), len(self._reload_timers)))
        loaded_idx = [i for i, t in enumerate(self._reload_timers) if t == _SLOT_LOADED]
        cooling_idx = [i for i, t in enumerate(self._reload_timers) if t != _SLOT_LOADED]
        if len(loaded_idx) > target:
            now = _game_time()
            for i in loaded_idx[target:]:
                self._reload_timers[i] = now
        elif len(loaded_idx) < target:
            cooling_idx.sort(key=lambda i: self._reload_timers[i])
            need = target - len(loaded_idx)
            for i in cooling_idx[:need]:
                self._reload_timers[i] = _SLOT_LOADED

    def GetNumReady(self) -> int:                   return self._num_ready

    def _clamp_num_ready(self, v) -> None:
        """_num_ready must never exceed MaxReady, or fall below zero.

        These three setters are real SDK surface (App.py:6018-6020), so a
        mission can drive them directly.  Unclamped, _num_ready ran ahead of the
        slot array and _sync_slots_to_num_ready only clamped its own TARGET, not
        the field — so a 1-slot tube told SetNumReady(5) would launch FOUR
        torpedoes (Fire kept decrementing and spawning while
        _start_slot_cooldown found no loaded slot and silently no-op'd), and
        then never reload again (UpdateReload's `num_ready >= max_ready` guard
        held forever).  Neither failure raised.
        """
        self._num_ready = max(0, min(int(v), int(self._max_ready)))
        self._sync_slots_to_num_ready()

    def SetNumReady(self, v) -> None:
        self._clamp_num_ready(v)

    def IncNumReady(self) -> None:
        self._clamp_num_ready(self._num_ready + 1)

    def DecNumReady(self) -> None:
        self._clamp_num_ready(self._num_ready - 1)

    def GetLastFireTime(self) -> float:             return self._last_fire_time
    def SetLastFireTime(self, v) -> None:           self._last_fire_time = float(v)
    def GetImmediateDelay(self) -> float:           return self._immediate_delay
    def GetReloadDelay(self) -> float:              return self._reload_delay
    def GetMaxReady(self) -> int:                   return self._max_ready

    def _parent_ammo(self):
        """The parent TorpedoSystem's currently-selected ammo type, or None
        if there is no parent or no ammo type is configured.
        GetParentSubsystem() is always the TorpedoSystem this tube was
        AddChildSubsystem'd under."""
        parent = self.GetParentSubsystem()
        if parent is None:
            return None
        return parent.GetCurrentAmmoType()

    def _ammo_exhausted(self) -> bool:
        """True when the parent's selected ammo type is a FINITE magazine
        with zero rounds left (combat-and-damage.md:788 ReloadTorpedo,
        :823 CanFire — both require "Ammo available").  Unlimited/undeclared
        ammo (or no ammo configured at all) NEVER gates — mirrors the
        existing TorpedoSystem.StartFiring reserve-gate pattern so the
        legacy/undeclared firing path stays byte-identical."""
        ammo = self._parent_ammo()
        finite = ammo is not None and not getattr(ammo, "_unlimited", True)
        return finite and ammo.GetAvailable() <= 0

    def CanFire(self) -> int:
        """BC torpedo CanFire (combat-and-damage.md:822-826):
        powered AND num_ready > 0 AND the ImmediateDelay refire gate has
        expired AND ammo is available.

        ImmediateDelay is a REFIRE GATE, not a fire->launch latency: it prevents
        rapid double-fires. Hardpoint values run 0.25s (galaxy) to 5.0s.
        The volley-level ammo reserve gate also lives on the parent
        TorpedoSystem.StartFiring; this per-tube check additionally covers
        direct CanFire() callers that bypass StartFiring.
        """
        parent = self.GetParentSubsystem()
        if parent is None or not parent.IsOn():
            return 0
        if self._num_ready <= 0:
            return 0
        if _game_time() - self._last_fire_time < self._immediate_delay:
            return 0
        if self._ammo_exhausted():
            return 0
        return 1

    def Fire(self, target=None, offset=None, *,
             spread_unit=None, homing_delay=0.0) -> None:
        if not self.CanFire():
            return
        self._firing = True
        self._target = target
        self._target_offset = offset
        now = _game_time()
        self._num_ready -= 1
        self._last_fire_time = now
        self._start_slot_cooldown(now)

        # PR 2b: spawn the projectile via the bound SDK script.  spread_unit /
        # homing_delay are only non-default when the parent TorpedoSystem is
        # firing a Dual/Quad spread volley.
        self._spawn_torpedo(spread_unit=spread_unit, homing_delay=homing_delay)

        # Discrete-shot — auto-stop after launch.  WeaponSystem's
        # _currently_firing list still tracks us until StopFiring is called.
        self._firing = False

    def _spawn_torpedo(self, *, spread_unit=None, homing_delay=0.0) -> None:
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

        torp = _spawn_projectile(self, mod,
                                 drf_override=self.GetDamageRadiusFactor(),
                                 spread_unit=spread_unit,
                                 homing_delay=homing_delay)
        # ET_TORPEDO_FIRED carries the PROJECTILE as its source, so it can only be
        # posted once the projectile exists.  Posted here rather than inside
        # _spawn_projectile because that helper is shared with pulse cannons, and
        # q12 shows this event's destination is always a TorpedoTube.
        self._broadcast_torpedo_fired(torp)

    # FireDumb is inherited from Weapon — it was a byte-identical duplicate here,
    # and keeping the override would have skipped the base's new CanFire() gate.

    def UpdateReload(self, dt: float = 0.0) -> None:
        """Poll each cooling slot; reload one when ReloadDelay of GAME time has passed.

        `dt` is accepted for call-site compatibility (host_loop._advance_weapons)
        and DELIBERATELY IGNORED. _advance_weapons runs once per RENDER frame with
        a constant TICK_DT = 1/60 (host_loop.py:6054, :5525) — it is NOT inside the
        fixed-timestep sim loop. Integrating dt there would make reload frame-rate
        dependent: a Galaxy tube would reload in 20s on a 120Hz display. BC compares
        against the game clock instead (combat-and-damage.md:812-815).

        Power throttles the reload: a half-powered torpedo system reloads at half
        rate (existing behaviour, preserved).
        """
        self._ensure_slots()
        if self._num_ready >= self._max_ready:
            return
        parent = self.GetParentSubsystem()
        factor = (parent.GetNormalPowerPercentage()
                  if parent is not None else 1.0)
        # isinstance FIRST: `factor <= 0.0` cannot see a _Stub. TGObject.
        # __getattr__ hands back a truthy _Stub for a missing method, and
        # _Stub.__le__ returns False — so the guard did not fire, execution
        # reached the division, and `40.0 / _Stub` is 0.0 (__rtruediv__). A zero
        # delay makes `now - slot >= delay` true for every slot, so the tube
        # reloaded EVERY FRAME. The guard's intent ("no power => no reload")
        # was inverted into infinite ammo, silently.
        if not isinstance(factor, (int, float)) or factor <= 0.0:
            return
        delay = self._reload_delay / factor
        now = _game_time()
        for slot in self._reload_timers:
            if slot != _SLOT_LOADED and now - slot >= delay:
                self.ReloadTorpedo()      # loads the OLDEST cooling slot
                return                    # one round per tick, as BC does

    def ReloadTorpedo(self) -> None:
        """Load one round into the oldest cooling slot. BC FUN_0057D8A0
        (combat-and-damage.md:786-793).

        BC says "find slot with greatest timer". Its timers count UP while
        cooling, so the greatest timer is the slot cooling LONGEST. We store
        cooldown START stamps, so the equivalent is the SMALLEST stamp.

        Guarded on ammo availability (combat-and-damage.md:788 "if no ammo
        left: return") — a finite magazine at zero rounds must not keep
        topping tubes up to full while the ammo panel reads empty.
        Unlimited/undeclared ammo never gates (see _ammo_exhausted).

        DIVERGENCE (deliberate, documented): BC decrements the magazine here
        ("total_ammo_consumed++"). We already debit ammo at FIRE time, in
        TorpedoSystem.StartFiring. Debiting again here would double-count —
        this method only GATES on ammo, it never decrements it.
        Aligning the debit point with BC is a follow-up; it touches TorpedoSystem.
        """
        self._ensure_slots()
        if self._num_ready >= self._max_ready:
            return
        if self._ammo_exhausted():
            return
        oldest_i, oldest_t = -1, None
        for i in range(len(self._reload_timers)):
            t = self._reload_timers[i]
            if t == _SLOT_LOADED:
                continue
            if oldest_t is None or t < oldest_t:
                oldest_i, oldest_t = i, t
        if oldest_i < 0:
            return
        self._reload_timers[oldest_i] = _SLOT_LOADED
        self._num_ready += 1
        self._broadcast_reload()

    def _broadcast_reload(self) -> None:
        """Post ET_TORPEDO_RELOAD: Destination = the TUBE, NO Source.

        Both halves are MEASURED, from probe q12 against the original game
        (tools/probes/results/q12_torpedo_events.txt, e035):

            ET_TORPEDO_RELOAD | SRC None | DST TorpedoTube(name='Forward Torpedo 1' ready=1)

        Destination is load-bearing: ConditionTorpsReady.py:140 registers with a
        tube destination-filter, and :169 casts GetDestination() to a TorpedoTube.

        We previously set Source to the parent TorpedoSystem and labelled it "a
        CHOICE, not a finding". The probe says BC posts NO source. Corrected —
        do not re-add one.
        """
        import App
        from engine import dev_mode
        try:
            evt = App.TGEvent_Create()
            evt.SetEventType(App.ET_TORPEDO_RELOAD)
            evt.SetDestination(self)
            App.g_kEventManager.AddEvent(evt)
        except Exception as _e:
            dev_mode.log_swallowed("ET_TORPEDO_RELOAD broadcast", _e)

    def _broadcast_torpedo_fired(self, torp) -> None:
        """Post ET_TORPEDO_FIRED: Source = the PROJECTILE, Destination = the TUBE.

        Measured, from probe q12 against the original game
        (tools/probes/results/q12_torpedo_events.txt, e001):

            ET_TORPEDO_FIRED | SRC Torpedo(parent=13323 target=15013)
                             | DST TorpedoTube(name='Forward Torpedo 1' ready=0)

        ⚠️ THE DESTINATION IS DANGEROUS. Maelstrom/Episode7/Episode7.py:88-115
        listens for this event and DESTROYS pEvent.GetDestination() outright
        (MissionLib.SetConditionPercentage(pLauncher, 0)) on a 10% roll — the
        E7M1 phased-plasma story beat, where the unstable experimental torpedoes
        blow out the tube that fired them. Post this with the wrong destination
        and the game destroys the WRONG subsystem. It must be the TUBE.

        Posted UNCONDITIONALLY, for every torpedo: q12 captured `ammo=Photon` on
        every ET_TORPEDO_FIRED, so the engine does not filter by ammo type. The
        Phased-Plasma check lives in Episode7's HANDLER, not here.

        Only torpedo tubes post this. _spawn_projectile is shared with pulse
        cannons, hence the call site is here in TorpedoTube, not in that helper.
        """
        if torp is None:
            return
        import App
        from engine import dev_mode
        try:
            evt = App.TGEvent_Create()
            evt.SetEventType(App.ET_TORPEDO_FIRED)
            evt.SetSource(torp)
            evt.SetDestination(self)
            App.g_kEventManager.AddEvent(evt)
        except Exception as _e:
            dev_mode.log_swallowed("ET_TORPEDO_FIRED broadcast", _e)

    def UnloadTorpedo(self) -> None:
        """Remove one ready round; its slot goes back into cooldown.

        Mirrors BC's decompiled FUN_0057D9A0 (combat-and-damage.md:833-838),
        which stock BC calls on an ammo-type switch. SDK-facing surface only:
        our TorpedoSystem.SetAmmoType (weapon_subsystems.py — see its
        docstring) SELECTS a slot and explicitly ignores its second arg; it
        never calls UnloadTorpedo. As of this writing UnloadTorpedo has zero
        callers anywhere in this engine, the tests, or the SDK — do not infer
        that SetAmmoType wires it in."""
        if self._num_ready <= 0:
            return
        self._num_ready -= 1
        self._start_slot_cooldown(_game_time())
