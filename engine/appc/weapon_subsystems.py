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
import random

from engine.appc.math import TGPoint3, TGMatrix3
from engine.appc.float_range_watcher import FloatRangeWatcher
from engine.appc.subsystems import (
    ShipSubsystem,
    PoweredSubsystem,
    _is_offline,
    subsystem_world_position,
)


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


def _resolve_fire_sound(prop) -> str:
    """Returns the FireSound name (typed accessor) or empty string."""
    if prop is None or not hasattr(prop, "GetFireSound"):
        return ""
    return prop.GetFireSound() or ""



def _spawn_projectile(emitter, mod, *, drf_override=0.0):
    """Spawn an in-flight projectile from `emitter` using SDK module `mod`.

    Shared by torpedo tubes and pulse-weapon cannons. Builds a Torpedo at the
    emitter's world position, runs mod.Create to populate visuals/behaviour,
    applies drf_override (the launcher's DamageRadiusFactor) when > 0, and
    launches it BC-faithfully (audited §2.4.1): straight out the tube's
    authored Direction (skewed +0.033 x Right when IsSkewFire) rotated to
    world, at GetLaunchSpeed(), plus the firing ship's own linear velocity —
    the aim point never steers the launch.  Registers it and plays
    mod.GetLaunchSound.  Returns the Torpedo, or None if mod is unusable.
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

    # ── Launch trajectory (audited §2.4.1): the aim point NEVER steers the
    # launch. Direction = tube-local Direction (skew: + 0.033 x Right, local
    # frame, fixed sign) rotated to world; speed from the Python projectile
    # module; plus the firing ship's own linear velocity.
    local_dir = None
    got = emitter.GetDirection() if hasattr(emitter, "GetDirection") else None
    if isinstance(got, TGPoint3):
        local_dir = TGPoint3(got.x, got.y, got.z)
    if local_dir is None:
        local_dir = TGPoint3(0.0, 1.0, 0.0)
    if getattr(emitter, "IsSkewFire", None) and emitter.IsSkewFire():
        right = emitter.GetRight() if hasattr(emitter, "GetRight") else None
        if isinstance(right, TGPoint3):
            local_dir = TGPoint3(local_dir.x + 0.033 * right.x,
                                 local_dir.y + 0.033 * right.y,
                                 local_dir.z + 0.033 * right.z)
    world_dir = TGPoint3(local_dir.x, local_dir.y, local_dir.z)
    if source_ship is not None and hasattr(source_ship, "GetWorldRotation"):
        rot = source_ship.GetWorldRotation()
        from engine.appc.math import TGMatrix3
        if isinstance(rot, TGMatrix3):
            world_dir.MultMatrixLeft(rot)
    length = world_dir.Length()
    ship_vel = (source_ship.GetVelocityTG()
                if source_ship is not None and hasattr(source_ship, "GetVelocityTG")
                else TGPoint3(0.0, 0.0, 0.0))
    if not isinstance(ship_vel, TGPoint3):
        ship_vel = TGPoint3(0.0, 0.0, 0.0)
    if length > 1e-6:
        torp._velocity = TGPoint3(
            world_dir.x / length * launch_speed + ship_vel.x,
            world_dir.y / length * launch_speed + ship_vel.y,
            world_dir.z / length * launch_speed + ship_vel.z,
        )

    # Homing state (guidance-only; does not shape the launch).  Task 7 audited
    # flow: "Fire stamps the homing state" — read the EMITTER's own _target
    # (stamped by TorpedoTube.Fire's gated targeted path, cleared/absent on
    # the dumb path / FireDumb), NOT the ship's target lock.  Previously this
    # read source_ship.GetTarget() directly, which meant even a dumbfire
    # inherited the ship's lock; that's wrong per the audited split.
    target_ship = getattr(emitter, "_target", None)
    if (target_ship is not None
            and hasattr(target_ship, "IsDead") and not target_ship.IsDead()):
        torp._target_ship = target_ship
    else:
        torp._target_ship = None

    register(torp)

    if hasattr(mod, "GetLaunchSound"):
        sound_name = mod.GetLaunchSound()
        if sound_name:
            TGSoundManager.instance().PlaySound(sound_name)

    return torp


def _post_weapon_fired(weapon) -> None:
    """Post ET_WEAPON_FIRED: Source = the firing weapon, Destination = the
    owning ship (resolved via ``_climb_to_ship``).  Shared by TorpedoTube.Fire
    (posted AFTER ET_TORPEDO_FIRED — see TorpedoTube._broadcast_weapon_fired)
    and PhaserBank.Fire (posted on the was-not-firing edge, Task 10, audited
    §1.6/§6 — the SDK surface for the event bounds it to (weapon, owner ship)
    regardless of weapon type)."""
    import App
    from engine import dev_mode
    try:
        evt = App.TGEvent_Create()
        evt.SetEventType(App.ET_WEAPON_FIRED)
        evt.SetSource(weapon)
        evt.SetDestination(weapon._climb_to_ship())
        App.g_kEventManager.AddEvent(evt)
    except Exception as _e:
        dev_mode.log_swallowed("ET_WEAPON_FIRED broadcast", _e)


class _EnergyWeaponFireMixin:
    """Shared Fire/CanFire/StopFiring/UpdateCharge for PhaserBank / PulseWeapon
    / TractorBeam.  Per-emitter state initialised by _init_energy_weapon_state.
    Each class also has _firing (False at init), _target/_target_offset (None).

    SFX trigger looks up the property's FireSound name and asks TGSoundManager
    to play it.  Tries "<name> Start" first (phaser convention), falls back to
    bare "<name>" (tractor convention).  Names map to WAV assets via
    sdk/Build/scripts/LoadTacticalSounds.py invoked at audio init.
    """

    def _aim_in_arc(self, target) -> bool:
        """Firing-arc gate in the weapon's OWN fire path (spec §2.4: the
        dispatch-level `_emitter_in_arc` checks moved here, logic unchanged,
        when StartFiring became a tick-arm — BC puts arc in the weapon's fire
        path, not in the system tick).  Aim originates at this emitter's
        mount Position (research doc § Bug F); no target → ship-forward."""
        ship = self._climb_to_ship() if hasattr(self, "_climb_to_ship") else None
        if target is not None:
            aim_world = _resolve_bank_aim_world(self, target)
        else:
            aim_world = _resolve_aim_world(ship, None)
        return _emitter_in_arc(self, ship, aim_world)

    def CanFire(self) -> int:
        """Audited §1.6, three gates (the invented refire-hysteresis is
        gone — this asymmetry between the two charge branches below IS
        BC's hysteresis, no separate latch needed):

          * ship alive — a dead ship's weapons never fire.
          * charge — ``> 0`` to SUSTAIN an already-firing beam, but
            ``>= MinFiringCharge`` to START one.  A depleted bank that
            auto-stopped must climb back to MinFiringCharge (no extra
            headroom) before it can restart.
          * disabled-product — the bank's own condition times the parent
            system's condition must clear the authored DisabledPercentage
            threshold (``GetOverallConditionPercentage`` in the audit); a
            damaged system throttles a healthy bank the same way a
            damaged bank throttles a healthy system.

        The existing parent-IsOn gate is unchanged (BC gates power
        elsewhere, not inside this predicate)."""
        parent = self.GetParentSubsystem()
        on = parent is not None and parent.IsOn()
        if not on:
            return 0
        ship = self._climb_to_ship() if hasattr(self, "_climb_to_ship") else None
        if ship is not None and hasattr(ship, "IsDead") and ship.IsDead():
            return 0
        if self._firing:
            charged = self._charge_level > 0.0
        else:
            charged = self._charge_level >= self._min_firing_charge
        if not charged:
            return 0
        # `parent` is guaranteed non-None here (the IsOn gate above already
        # returned 0 otherwise); GetDisabledPercentage() lives on self
        # (ShipSubsystem field, sane 0.25 default) so this never raises even
        # on a bank with no property bound.
        combined = self.GetConditionPercentage() * parent.GetConditionPercentage()
        if self.GetDisabledPercentage() >= combined:
            return 0
        return 1

    def Fire(self, target=None, offset=None) -> bool:
        """Returns True when the beam is firing after this call — the tick's
        try_fire_weapon consumes the explicit bool (§3.3 step 5)."""
        if not self.CanFire():
            return False
        if not self._aim_in_arc(target):
            return False
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
        return True

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
                # continuous discharge.  Restart requires climbing back to
                # MinFiringCharge (CanFire's start/sustain asymmetry —
                # audited §1.6, no headroom on top of it).
                # Route via StopFiring so the looped SFX handle is silenced.
                self.StopFiring()
        else:
            parent = self.GetParentSubsystem()
            if parent is None or parent.IsOn():
                power_factor = max(0.0, parent.GetNormalPowerPercentage()
                                    if parent is not None else 1.0)
                # Audited §1.6: recharge also scales with the bank's OWN
                # condition — a damaged bank recharges proportionally
                # slower.  (BC's audited non-local 1.25x boost near a
                # friendly starbase never triggers in single-player — no
                # code path applies it; documented here, not implemented.)
                condition_factor = self.GetConditionPercentage()
                headroom = self._max_charge - self._charge_level
                if headroom > 0.0:
                    want = min(self._recharge_rate * power_factor
                               * condition_factor * dt, headroom)
                    self._charge_level += want

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

    Surface the SDK actually calls on a leaf weapon.  IsMemberOfGroup, IsDumbFire,
    SetSkewFire, and IsSkewFire are now implemented for the BC-faithful dispatch
    tick (weapon-firing-mechanics.md §3.1/§2.10).  DELIBERATELY ABSENT (verified
    zero SDK call sites on a tube): SetFiring, GetTargetID,
    GetOverallConditionPercentage, IsInArc, CanHit.  IsInArc/CanHit are additionally
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
        # BC Weapon+0x9C — inter-shot delay accumulator for TryFireWeapon.
        self._fire_timer: float = 0.0

    def Fire(self, target=None, offset=None, **kwargs) -> None:
        """Discrete shot.  Subclasses implement — the payload differs per weapon."""
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

    def IsMemberOfGroup(self, g) -> int:
        """Weapon::IsMemberOfGroup (0x00583240). Group ids are 1-BASED bits
        in the property's Groups mask; group 0 means 'all weapons'."""
        g = int(g)
        if g == 0:
            return 1
        prop = self.GetProperty()
        get = getattr(prop, "GetGroups", None) if prop is not None else None
        mask = get() if callable(get) else 0
        return 1 if (int(mask) & (1 << (g - 1))) else 0

    def IsDumbFire(self) -> int:
        """Weapon::IsDumbFire (0x00583270, property+0x48). Only torpedo
        tubes are dumbfire-capable in our surface (AI/Preprocessors.py:458)."""
        return 0


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
        # Round-robin cursor into child emitters (tractor _engage_beam; the
        # BC tick uses _last_weapon_idx below instead).
        self._next_emitter_index: int = 0
        # ── BC tick state (weapon-firing-mechanics.md §3.1-3.3) ──────────
        self._force_update: bool = False    # +0xAC: bypass 0.33s delay this tick
        self._group_fire_mode: int = 0      # +0xB0: published working group
        self._last_weapon_idx: int = -1     # +0xB4: round-robin cursor
        self._firing_chain_mode: int = 0    # +0xB8: active chain index
        self._last_group_fired: int = -1    # +0xBC: resume input, -1 sentinel
        self._target_list: list = []        # +0xC4: pruned per tick
        self._fire_timer: float = 0.0       # BC Weapon+0x9C: inter-shot delay
        # Held-trigger state (press = StartFiring arms, release = StopFiring
        # disarms).  host_loop._pump_held_weapons runs update_weapons once per
        # frame for every system with _fire_held set.
        self._fire_held: bool = False
        self._held_target = None
        self._held_offset = None
        # _HeldFireWeaponSystem and TorpedoSystem set this via SetSingleFire;
        # guard so the base class always has it too.
        self._single_fire = getattr(self, "_single_fire", False)

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

    def IsDumbFire(self) -> int:
        """Weapon systems are not dumbfire-capable by default. Only TorpedoTube
        (which is a Weapon, not a system) overrides this to return 1."""
        return 0

    def IsMemberOfGroup(self, g) -> int:
        """WeaponSystem::IsMemberOfGroup (0x00583240). Group ids are 1-BASED bits
        in the property's Groups mask; group 0 means 'all weapons'.

        Inherited by PhaserBank, PulseWeapon, TractorBeam (leaf emitters that are
        also WeaponSystem subclasses)."""
        g = int(g)
        if g == 0:
            return 1
        prop = self.GetProperty()
        get = getattr(prop, "GetGroups", None) if prop is not None else None
        mask = get() if callable(get) else 0
        return 1 if (int(mask) & (1 << (g - 1))) else 0

    def SetForceUpdate(self, flag) -> None:  self._force_update = bool(flag)
    def GetForceUpdate(self) -> int:         return 1 if self._force_update else 0

    def GetFiringChains(self) -> list:
        prop = self.GetProperty()
        get = getattr(prop, "GetFiringChains", None) if prop is not None else None
        chains = get() if callable(get) else []
        return chains if isinstance(chains, list) else []

    def SetFiringChainMode(self, n) -> None:
        """WeaponSystem::SetFiringChainMode (0x00584FA0): clamped below the
        chain count. This is what BC's tactical 'torpedo spread' toggle calls."""
        chains = self.GetFiringChains()
        hi = max(0, len(chains) - 1)
        self._firing_chain_mode = max(0, min(int(n), hi))

    def GetFiringChainMode(self) -> int:     return self._firing_chain_mode

    def SetGroupFireMode(self, g) -> None:   self._group_fire_mode = int(g)
    def GetGroupFireMode(self) -> int:       return self._group_fire_mode

    def _active_chain_groups(self) -> list:
        """Ordered group ids of the active chain; [0] ('all weapons') when
        the ship authors no chains (67 of 70 stock hardpoints)."""
        chains = self.GetFiringChains()
        if not chains:
            return [0]
        _label, groups = chains[self._firing_chain_mode % len(chains)]
        return list(groups) if groups else [0]

    def _resolve_working_group(self) -> int:
        """§3.2 step 3 — LastGroupFired is an INPUT: keep firing the group we
        last fired while it is still in the chain; else the chain's first."""
        groups = self._active_chain_groups()
        if self._last_group_fired != -1 and self._last_group_fired in groups:
            return self._last_group_fired
        return groups[0]

    def _add_target(self, target) -> None:
        if target is not None and target not in self._target_list:
            self._target_list.append(target)

    def _prune_targets(self) -> None:
        """§3.2 step 2 — unlink anything dead or unresolvable."""
        self._target_list = [
            t for t in self._target_list
            if t is not None
            and not (hasattr(t, "IsDead") and t.IsDead())
        ]

    def GetNumTargets(self) -> int:          return len(self._target_list)

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
        """Arms the tick (BC StartFiring reads no spread/skew state — §2.10).
        The actual dispatch is update_weapons, pumped per frame by host_loop;
        SetForceUpdate(1) + one immediate update makes a tap fire this frame
        (SDK FireWeapons does exactly StartFiring + SetForceUpdate(1))."""
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
        # Engageability gate (per-class hook, e.g. PhaserSystem's global fire
        # range): an out-of-range trigger must NOT latch _fire_held — an AI
        # re-calls StartFiring every tick, and a latched-but-unengageable held
        # state would flicker fire/stop each frame (the "ship's horn" loop).
        if (target is not None and hasattr(self, "_can_engage")
                and not self._can_engage(self.GetParentShip(), target)):
            return
        self._add_target(target)
        self._held_target = target
        self._held_offset = offset
        self._fire_held = True
        self.SetForceUpdate(1)
        self.update_weapons(0.0)

    def StopFiring(self, *args) -> None:
        self._fire_held = False
        self._held_target = None
        self._held_offset = None
        self._target_list = []
        self._last_group_fired = -1
        for i in range(self.GetNumWeapons()):
            w = self.GetWeapon(i)
            if w is not None and hasattr(w, "StopFiring"):
                w.StopFiring()

    def StopFiringAtTarget(self, pTarget) -> None:
        """SDK Preprocessors.py:274/469 — alias for StopFiring() since
        headless doesn't model multi-target firing state."""
        self.StopFiring()

    def IsFiring(self) -> int:
        if self._fire_held:
            return 1
        for i in range(self.GetNumWeapons()):
            w = self.GetWeapon(i)
            if w is not None and hasattr(w, "IsFiring") and w.IsFiring():
                return 1
        return 0

    def GetTarget(self):                          return self._target
    def SetTarget(self, target) -> None:          self._target = target
    def GetWeaponSystemType(self) -> int:         return self._weapon_system_type
    def SetWeaponSystemType(self, v) -> None:     self._weapon_system_type = int(v)

    # SDK-faithful aliases over the child-subsystem API.
    # TacticalInterfaceHandlers.FireWeapons (PR 2) reads these.
    def GetNumWeapons(self) -> int:               return self.GetNumChildSubsystems()
    def GetWeapon(self, i: int):                  return self.GetChildSubsystem(i)

    # ── BC tick engine (weapon-firing-mechanics.md §3.2/§3.3) ───────────────
    # This IS the live dispatch path: StartFiring (above) arms the tick and
    # host_loop._pump_held_weapons runs update_weapons once per armed system
    # per frame.

    # BC inter-shot delay threshold (TryFireWeapon, 0x00584E40).
    FIRE_TIMER_THRESHOLD = 0.33

    def try_fire_weapon(self, weapon, dt, target, offset) -> bool:
        """TryFireWeapon (0x00584E40), §3.3. Plain bool — BC has no tri-state."""
        if self._force_update:
            weapon._fire_timer = self.FIRE_TIMER_THRESHOLD   # bypass this tick
        else:
            weapon._fire_timer = getattr(weapon, "_fire_timer", 0.0) + dt
        if not weapon.IsFiring() and weapon._fire_timer < self.FIRE_TIMER_THRESHOLD:
            return False
        # Re-seed reads the PRE-EXISTING state: a continuously-firing weapon
        # zeroes; everything else draws fresh. BC's draw distribution is
        # unverified in the corpus — uniform(0, 0.33) is our choice.
        if weapon.IsFiring():
            weapon._fire_timer = 0.0
        else:
            weapon._fire_timer = random.uniform(0.0, self.FIRE_TIMER_THRESHOLD)
        if not weapon.CanFire():
            weapon.StopFiring()      # what makes a beam vanish on charge-out
            return False
        before = self._fired_counter(weapon)
        result = weapon.Fire(target, offset)
        if self._weapon_did_fire(weapon, result, before):
            return True
        # §3.3 step 6: clear target, retry against the system target list.
        weapon._target = None
        for entry in list(self._target_list):
            if entry is None or (hasattr(entry, "IsDead") and entry.IsDead()):
                continue
            before = self._fired_counter(weapon)
            result = weapon.Fire(entry, offset)
            if self._weapon_did_fire(weapon, result, before):
                return True
        return False

    @staticmethod
    def _fired_counter(weapon):
        """Stub-safe read of the test-fake `fired` shot counter.

        NOT hasattr: TGObject.__getattr__ manufactures a truthy _Stub for any
        unknown public name, so hasattr(weapon, "fired") is vacuously True on
        every REAL weapon — `before` became a _Stub, `_weapon_did_fire`'s
        counter comparison silently evaluated False, and every successful
        discrete shot fell into the §3.3 step-6 retry and fired TWICE (seen
        as a double ammo debit).  The stub-heatmap phantom lesson: our own
        probes must read the instance dict, not hasattr."""
        d = getattr(weapon, "__dict__", None)
        return d.get("fired") if isinstance(d, dict) else None

    @staticmethod
    def _weapon_did_fire(weapon, result, before) -> bool:
        """Success detection, in priority order: explicit True/False returned
        by Fire (all production weapons since the tick rewire), a test fake's
        `fired` counter increment, else IsFiring() (held beams)."""
        if isinstance(result, bool):
            return result
        if before is not None:
            return weapon.fired > before
        return bool(weapon.IsFiring())

    def update_weapons(self, dt) -> bool:
        """UpdateWeapons (0x00584930), §3.2. Returns did_fire."""
        did_fire = False
        ship = self.GetParentShip()
        if ship is not None and hasattr(ship, "IsDead") and ship.IsDead():
            return False
        self._prune_targets()
        target = self._target_list[0] if self._target_list else None
        offset = getattr(self, "_held_offset", None)
        groups = self._active_chain_groups()
        working = self._resolve_working_group()
        start_group = working
        # Round-robin base: captured ONCE before the group-retry loop, not
        # re-read live. self._last_weapon_idx only mutates on a successful
        # fire, and a successful fire always breaks out to the next tick
        # (single-fire breaks the inner loop; multi-fire exhausts the group
        # and `fired_this_group` stops group-advance) — so reading it live
        # inside the delta loop double-counted the just-fired slot instead
        # of advancing to the next group member.
        base_idx = self._last_weapon_idx
        while True:
            self.SetGroupFireMode(working)
            n = self.GetNumWeapons()
            fired_this_group = False
            for delta in range(1, n + 1):
                idx = (base_idx + delta) % n if n else 0
                weapon = self.GetWeapon(idx)
                if weapon is None or not weapon.IsMemberOfGroup(working):
                    continue
                if self.try_fire_weapon(weapon, dt, target, offset):
                    did_fire = fired_this_group = True
                    self._last_weapon_idx = idx
                    self._last_group_fired = working
                    if self._single_fire:
                        break
                else:
                    weapon._target = None      # ClearTarget, NOT a timer reset
                    if self.GetNumTargets() == 0 and weapon.IsDumbFire():
                        weapon.FireDumb(0, 1)
            if fired_this_group or len(groups) <= 1:
                break
            # §3.2 step 7: advance to the next group in the chain, wrapping.
            working = groups[(groups.index(working) + 1) % len(groups)]
            if working == start_group:
                self._last_group_fired = -1
                break
        self._force_update = False    # one-tick bypass, consumed
        return did_fire


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
        # Selected ammo slot.  None == "lowest populated slot" (the historical
        # default); an int selects that slot when it is populated.  UI type
        # cycling (weapon_config.cycle_torpedo_type) drives this via
        # SetCurrentAmmoSlot / CycleAmmoType so both the readout and the
        # per-shot power cost track the chosen type.
        self._selected_slot = None
        # Ship-wide fire stagger (Task 7, audited): GAME time of the last
        # torpedo launched by ANY tube on this system.  A fresh system inits
        # to -1000.0 (same convention as TorpedoTube._last_fire_time) so the
        # first shot always passes the 0.5s stagger gate.  Skew-fire tubes
        # are exempt (TorpedoTube.CanFire checks IsSkewFire() first).
        self._last_system_fire_time: float = -1000.0

    def StartFiring(self, target=None, offset=None) -> None:
        """Arm the BC tick (base StartFiring) behind the ammo reserve gate.

        A finite ammo type (hardpoint-declared max) with no rounds left cannot
        fire; unlimited/undeclared types never gate.  The per-launch ammo debit
        lives in TorpedoTube._spawn_torpedo (one round per torpedo actually
        spawned).  Launches chain across tubes via firing_chain walk-out with
        stagger delay, each firing straight out the tube's authored direction
        (BC-faithful per §2.4.1), never aimed at a target."""
        ammo = self.GetCurrentAmmoType()
        finite = ammo is not None and not getattr(ammo, "_unlimited", True)
        if finite and ammo.GetAvailable() <= 0:
            return
        super().StartFiring(target, offset)

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

    def SetSkewFire(self, flag) -> None:
        """Pure broadcast to child tubes (0x0057B1C0) — NO system-level
        state; audited §2.10. Dormant in stock play (zero SDK call sites)."""
        for i in range(self.GetNumWeapons()):
            w = self.GetWeapon(i)
            if w is not None and hasattr(w, "SetSkewFire"):
                w.SetSkewFire(flag)


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
# system on a representative 120 GU.  A target drifting past this drops the
# beam (update_weapons re-checks _can_engage per frame; the ENGAGE intent
# persists so the beam re-acquires when back in range).
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
    """Energy-emitter aggregator base (PhaserSystem, PulseWeaponSystem).

    Since the BC tick rewire the shared dispatch lives on WeaponSystem
    (StartFiring arms the tick, host_loop._pump_held_weapons runs
    update_weapons per frame).  This class only keeps the SingleFire mode
    and the _can_engage fire-range hook.

    SingleFire(1): one eligible emitter fires per tick, round-robin via
    _last_weapon_idx.  SingleFire(0): the tick walks the whole group.

    Subclasses override _can_engage(ship, target) to add a fire-range gate
    (phasers do; pulse weapons don't — a bolt's lifetime bounds its range).
    StartFiring consults it (no latch out of range) and the host_loop pump
    re-checks it per frame (held burst stops when the target drifts out).
    """
    def __init__(self, name: str = ""):
        super().__init__(name)
        self._single_fire: int = 0

    def GetSingleFire(self) -> int:                 return self._single_fire
    def SetSingleFire(self, v) -> None:             self._single_fire = int(v)

    def _can_engage(self, ship, target) -> bool:
        """Fire-range gate hook. Default: no gate. PhaserSystem overrides."""
        return True

    def StartFiring(self, target=None, offset=None) -> None:
        """No-target bail (regression guard): SDK FireWeapons dispatches
        pShip.GetTarget(), which is legitimately None (no target selected).
        Energy weapons (phaser/pulse/tractor) have nothing to aim/fire at
        with no target — latching _fire_held here left host_loop's per-frame
        damage loop stopping each bank (target is None) while the AI/UI
        re-called StartFiring every tick, producing a fire/stop flicker with
        SFX spam (and, for pulse weapons, real forward bolts with no
        target). Torpedo dumbfire is unaffected: it lives on the WeaponSystem
        base, which legitimately arms with target=None."""
        if target is None:
            return
        super().StartFiring(target=target, offset=offset)


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
        # BC ships an uninitialized-stack-damage bug for out-of-range levels
        # (the audit's own recommendation is to clamp on write rather than
        # reproduce the corruption) — clamp to the three defined levels.
        self._power_level = max(0, min(2, int(level)))

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

    Rides the shared BC tick (WeaponSystem.StartFiring arms, host_loop's
    pump runs update_weapons per frame).  Unlike PhaserSystem its emitters
    fire discrete projectile bolts and it keeps the base's no-op _can_engage
    (no fire-range gate — a bolt's lifetime bounds its range, so the only
    fire gates are arc + charge + cooldown).
    """
    pass


class TractorBeamSystem(_HeldFireWeaponSystem):
    """Tractor-beam aggregator.

    A tractor is a UI *toggle* (StartFiring = engage, StopFiring =
    toggle-off).  Unlike phasers/pulse it does NOT ride the generic BC tick:
    its per-frame maintenance (update_weapons below) keeps the ENGAGE intent
    (`_fire_held`) alive even when the beam can't currently grip — shields
    up, out of range, out of arc — and re-acquires automatically when the
    geometry allows.  `_pump_self_managed` tells host_loop's pump to call
    update_weapons directly instead of hard-stopping via the generic
    `_can_engage` / detectability gates (which would kill the intent).
    The hardpoints set SingleFire(1), so exactly one beam locks the target.

    Unlike phasers/pulse, a firing tractor does NOT auto-stop on charge
    depletion (TractorBeam.UpdateCharge sustains it), and per frame
    engine.appc.tractor.advance_tractors applies the mode's physics to the
    target.  `_engage_state` caches per-mode engagement geometry (the captured
    HOLD world-point / TOW body-frame offset); it is invalidated on StopFiring
    and on any mode change.
    """
    # host_loop._pump_held_weapons: skip the generic hard-stop gates and hand
    # the frame straight to update_weapons (it owns its own stop conditions).
    _pump_self_managed = True
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
        re-acquires each frame via update_weapons), so the button stays "On"
        even if the beam momentarily isn't gripping."""
        return 1 if self._fire_held else 0

    def StartFiring(self, target=None, offset=None) -> None:
        """Record the held ENGAGE intent even when the target isn't immediately
        grippable, so update_weapons re-acquires the beam when the geometry
        allows.  (Mirrors WeaponSystem.StartFiring but records intent BEFORE
        the engageability check instead of bailing.)"""
        if not self.IsOn() or target is None:
            return
        if _is_offline(self):
            return
        if _cloak_blocks_fire(self):
            return
        self._add_target(target)
        self._fire_held = True
        self._held_target = target
        self._held_offset = offset
        ship = self.GetParentShip()
        if self._can_engage(ship, target):
            self._engage_beam(target, offset, ship)

    def IsFiring(self) -> int:
        """Instantaneous BEAM state only — deliberately NOT OR'd with
        `_fire_held` like the base: the engaged-but-not-gripping intent is
        surfaced separately via IsEngaged() (the HUD toggle reads that)."""
        return 1 if self._any_child_firing() else 0

    def _can_engage(self, ship, target) -> bool:
        # Range gate AND shield gate: a tractor grips only targets whose shields
        # are down (disabled / offline / not equipped / depleted).
        return (_target_within_range_gu(ship, target, TRACTOR_MAX_RANGE_GU)
                and _target_tractorable(target))

    def update_weapons(self, dt=0.0) -> bool:
        """Per-frame held-fire maintenance with arc/shield re-acquisition
        (the tractor's whole tick — replaces the base BC group walk; was
        retry_held_fire before the tick rewire).

        Unlike phasers/pulse (whose held burst hard-stops when the target
        leaves range), a tractor stays ENGAGED until the player toggles it
        off: if the firing emitter swings out of arc on a tight turn — or the
        target raises shields / drifts out of range — the beam switches off
        but `_fire_held` is kept, so it re-fires automatically from any
        in-arc emitter the moment the geometry allows again.
        """
        if not self._fire_held or self._held_target is None:
            return False
        if not self.IsOn():
            return False
        if _is_offline(self):
            self.StopFiring()           # system disabled — fully disengage
            return False
        ship = self.GetParentShip()
        target = self._held_target
        if hasattr(target, "IsDead") and target.IsDead():
            self.StopFiring()           # target gone — fully disengage
            return False
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
        if not engageable:
            return False
        # Re-dispatch one eligible in-arc emitter if none is currently firing.
        for i in range(self.GetNumWeapons()):
            em = self.GetWeapon(i)
            if em is not None and em.IsFiring():
                return False
        return self._engage_beam(target, self._held_offset, ship)

    def _engage_beam(self, target, offset, ship) -> bool:
        """Fire one eligible in-arc emitter (SingleFire round-robin via
        _next_emitter_index) or every eligible emitter (multi-fire).  This is
        the old shared `_dispatch_one_or_all` dispatch, kept tractor-local:
        beams are sustained grips, not the discrete BC tick cadence."""
        n = self.GetNumWeapons()
        if n == 0:
            return False
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
                    self._next_emitter_index = (idx + 1) % n
                    return True
            return False
        fired = False
        for i in range(n):
            emitter = self.GetWeapon(i)
            if emitter is None:
                continue
            aim_world = _resolve_bank_aim_world(emitter, target)
            if not _emitter_in_arc(emitter, ship, aim_world):
                continue
            if hasattr(emitter, "CanFire") and emitter.CanFire():
                emitter.Fire(target, offset)
                fired = True
        return fired

    def StopFiring(self, *args) -> None:
        self._engage_state = None
        super().StopFiring(*args)


class PhaserBank(_EnergyWeaponFireMixin, WeaponSystem):
    """Individual phaser emitter under a parent PhaserSystem
    (WeaponSystemProperty WST_PHASER).  Charge fields populated by Pass 4
    from the parent PhaserProperty (galaxy.py:209-214 for typical values).
    Inherits CanFire/StopFiring/UpdateCharge from the mixin; Fire wraps the
    mixin's implementation to post ET_WEAPON_FIRED (Task 10).
    """
    def __init__(self, name: str = ""):
        super().__init__(name)
        _init_energy_weapon_state(self)
        self._firing: bool = False
        self._target = None
        self._target_offset = None

    def Fire(self, target=None, offset=None) -> bool:
        """Wraps the shared beam-fire mixin to post ET_WEAPON_FIRED on the
        was-not-firing edge — the same edge the mixin already uses for the
        SFX one-shot (Task 10, audited §1.6/§6; spec §7). TractorBeam and
        PulseWeapon do not post this event yet — out of scope for the
        "phaser safe group"."""
        was_firing = self._firing
        fired = _EnergyWeaponFireMixin.Fire(self, target, offset)
        if fired and not was_firing:
            _post_weapon_fired(self)
        return fired

    def GetMaxCharge(self) -> float:                return self._max_charge
    def GetMinFiringCharge(self) -> float:          return self._min_firing_charge
    def GetNormalDischargeRate(self) -> float:      return self._normal_discharge_rate
    def GetRechargeRate(self) -> float:             return self._recharge_rate
    def GetChargeLevel(self) -> float:              return self._charge_level

    def GetChargePercentage(self) -> float:
        """0.0 when the parent system is off or this bank is disabled
        (Task 10, audited §1.6/§7.4) — otherwise the WeaponsDisplay would
        keep showing a charge bar for a bank that cannot fire."""
        if self._max_charge <= 0.0:
            return 0.0
        parent = self.GetParentSubsystem()
        if parent is not None and not parent.IsOn():
            return 0.0
        if self.IsDisabled():
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
    # CanFire always takes the ">= MinFiringCharge" branch (never the
    # ">0 sustain" branch, since _firing is always False here) and
    # UpdateCharge always takes the RECHARGE branch (see below). Re-arm is
    # therefore already "at exactly MinFiringCharge, no headroom" (Task 10,
    # audited §1.6) — the per-shot cooldown (SetCooldownTime, BoP 0.2s) is
    # the anti-flutter mechanism, not charge hysteresis.

    def CanFire(self) -> int:
        if self._cooldown_remaining > 0.0:
            return 0
        return _EnergyWeaponFireMixin.CanFire(self)

    def Fire(self, target=None, offset=None) -> bool:
        """Returns True when a bolt launched — a discrete shooter reports
        IsFiring() False right after a successful shot, so the tick's
        try_fire_weapon needs the explicit bool (else its §3.3 step-6 retry
        would double-fire every successful shot)."""
        if not self.CanFire():
            return False
        if not self._aim_in_arc(target):
            return False
        prop = self.GetProperty()
        script = prop.GetModuleName() if (prop is not None and hasattr(prop, "GetModuleName")) else ""
        if not script:
            return False
        import importlib
        try:
            mod = importlib.import_module(script)
        except ImportError:
            return False
        _spawn_projectile(self, mod, drf_override=self.GetDamageRadiusFactor())
        # Discrete drain: dump accumulated charge + start cooldown. No held beam.
        self._charge_level = 0.0
        self._cooldown_remaining = self.GetCooldownTime()
        return True

    def UpdateCharge(self, dt: float) -> None:
        if self._cooldown_remaining > 0.0:
            self._cooldown_remaining = max(0.0, self._cooldown_remaining - dt)
        # _firing stays False for pulse weapons, so the mixin takes the
        # RECHARGE branch; CanFire re-arms at exactly MinFiringCharge (no
        # headroom — see the class docstring above).
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
        never below — MinFiringCharge (so charge stays ``> 0`` and the
        mixin's CanFire sustain branch keeps returning true), gated by
        parent power: if the line goes down the beam drops.  When idle we
        fall back to the mixin's normal condition-scaled recharge.
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
            # Charge stays > 0 while sustaining — no depletion auto-stop.
            return
        # Idle fall-through note: an idle TractorBeamSystem doesn't want power
        # (_wants_power False -> factor zeroed by the pump), so the mixin's
        # factor-scaled recharge is 0 while idle. Harmless by design: the firing
        # sustain path never drains below _min_firing_charge, so CanFire's
        # start-branch (>= MinFiringCharge) passes at the floor — charge above
        # the floor has no gameplay effect for tractors.
        super().UpdateCharge(dt)


# ── Torpedo fire gates (Task 7, audited) ────────────────────────────────────
# BC's targeted torpedo fire resolves a static aim point (no lead/intercept)
# and rejects it outside a square +/-30 degree cone about the tube's authored
# Direction, checked yaw and pitch INDEPENDENTLY.  Neither step touches the
# launch trajectory itself (that stays BC-faithful per Task 6: straight out
# the tube's Direction, aim never steers the shot) -- they are pure FIRE
# gates: fail either and the tube posts ET_WEAPON_FIRE_FAILED and does not
# launch at all.

_TORPEDO_CONE_HALF_ANGLE = 0.5235984   # BC's literal, NOT math.radians(30)


def _resolve_torpedo_aim_point(tube, target):
    """0x005852A0: target world pos + tube aim offset scaled by target world
    scale and rotated by target world rotation. None => unresolvable (the
    caller posts ET_WEAPON_FIRE_FAILED). No speed/velocity/intercept enters."""
    if target is None or not hasattr(target, "GetWorldLocation"):
        return None
    if hasattr(target, "IsDead") and target.IsDead():
        return None
    pos = target.GetWorldLocation()
    offset = getattr(tube, "_target_offset", None)
    if not isinstance(offset, TGPoint3):
        return TGPoint3(pos.x, pos.y, pos.z)
    scale = float(target.GetScale()) if hasattr(target, "GetScale") else 1.0
    o = TGPoint3(offset.x * scale, offset.y * scale, offset.z * scale)
    rot = target.GetWorldRotation() if hasattr(target, "GetWorldRotation") else None
    if isinstance(rot, TGMatrix3):
        o.MultMatrixLeft(rot)
    return TGPoint3(pos.x + o.x, pos.y + o.y, pos.z + o.z)


def _in_torpedo_cone(tube, ship, aim_point) -> bool:
    """0x0057DA90->0x0057DC10: square +/-30 degree cone about the tube
    direction, yaw and pitch checked INDEPENDENTLY via atan2; forward must
    be > 0.  No occlusion test -- firing through an asteroid is legal
    (audited)."""
    mount = tube._emitter_world_position()
    to_aim = aim_point - mount
    if to_aim.Length() < 1e-6:
        return False
    d = tube.GetDirection() if hasattr(tube, "GetDirection") else None
    r = tube.GetRight() if hasattr(tube, "GetRight") else None
    if not isinstance(d, TGPoint3):
        d = TGPoint3(0.0, 1.0, 0.0)
    if not isinstance(r, TGPoint3):
        r = TGPoint3(1.0, 0.0, 0.0)
    u = TGPoint3(d.y * r.z - d.z * r.y,      # up = dir x right (local)
                 d.z * r.x - d.x * r.z,
                 d.x * r.y - d.y * r.x)
    rot = ship.GetWorldRotation() if (ship is not None
              and hasattr(ship, "GetWorldRotation")) else None
    basis = []
    for v in (d, r, u):
        w = TGPoint3(v.x, v.y, v.z)
        if isinstance(rot, TGMatrix3):
            w.MultMatrixLeft(rot)
        basis.append(w)
    fwd = basis[0].Dot(to_aim)
    if fwd <= 0.0:
        return False
    yaw = _math.atan2(abs(basis[1].Dot(to_aim)), fwd)
    pitch = _math.atan2(abs(basis[2].Dot(to_aim)), fwd)
    return yaw <= _TORPEDO_CONE_HALF_ANGLE and pitch <= _TORPEDO_CONE_HALF_ANGLE


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
        # Skew-fire flag — persistent across firing, set by TorpedoSystem or mission.
        self._skew_fire: bool = False

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
        powered AND num_ready > 0 AND the SHIP-WIDE 0.5s stagger has expired
        AND this tube is not itself disabled (spec §3.3 audited gate 2) AND
        the ImmediateDelay refire gate has expired AND ammo is available.

        ImmediateDelay is a REFIRE GATE, not a fire->launch latency: it prevents
        rapid double-fires. Hardpoint values run 0.25s (galaxy) to 5.0s.
        The volley-level ammo reserve gate also lives on the parent
        TorpedoSystem.StartFiring; this per-tube check additionally covers
        direct CanFire() callers that bypass StartFiring.

        The stagger gate (Task 7, audited) throttles the WHOLE SYSTEM to one
        launch per 0.5s of game time: a single tap that would otherwise fire
        every ready tube in the working group in the same tick now only
        launches the first one (it stamps parent._last_system_fire_time; the
        rest fail this gate within the same tick since gameTime delta is 0).
        Skew-fire tubes are exempt — they're the deliberately-desynced spread
        pattern, not the ship-wide volley.
        """
        parent = self.GetParentSubsystem()
        if parent is None or not parent.IsOn():
            return 0
        if (not self.IsSkewFire() and parent is not None
                and _game_time() - getattr(parent, "_last_system_fire_time", -1000.0) <= 0.5):
            return 0
        if self._num_ready <= 0:
            return 0
        # Audited gate 2 (spec §3.3): this tube must not itself be disabled
        # (condition damaged at/below DisabledPercentage). Distinct from the
        # PARENT power-on check above — a healthy powered-on TorpedoSystem
        # can still have individual tubes crippled by hull damage.
        if self.IsDisabled():
            return 0
        if _game_time() - self._last_fire_time < self._immediate_delay:
            return 0
        if self._ammo_exhausted():
            return 0
        return 1

    def Fire(self, target=None, offset=None) -> bool:
        """Returns True when a torpedo launched — discrete shooter, so the
        tick's try_fire_weapon needs the explicit bool (see PulseWeapon.Fire).

        Task 7 audited gates, applied AFTER CanFire (power/stagger/reload/
        ammo) passes:

          * targeted path (``target`` is not None): resolve the static aim
            point (no lead — Task 7 audited), then the +/-30 degree square
            cone about the tube's Direction.  Either failure posts
            ET_WEAPON_FIRE_FAILED and returns False WITHOUT consuming a
            round or starting the stagger/reload cooldown — a rejected shot
            never fires.  Only on success does this stamp ``_target``/
            ``_target_offset`` — "Fire stamps the homing state"; a
            downstream FireDumb()/dumb call (target=None) never does, so
            _spawn_projectile's homing lookup (reading THIS tube's
            ``_target``) stays None for a dumbfire.
          * dumb path (``target`` is None): straight to bookkeeping, no aim
            resolve, no cone — matches BC (FireDumb has no target to gate).
        """
        if not self.CanFire():
            return False
        if target is not None:
            aim_point = _resolve_torpedo_aim_point(self, target)
            if aim_point is None:
                self._broadcast_weapon_fire_failed()
                return False
            if not _in_torpedo_cone(self, self._climb_to_ship(), aim_point):
                self._broadcast_weapon_fire_failed()
                return False
            self._target = target
            self._target_offset = offset
        else:
            # Dumb path: clear any stale lock left by a previous targeted
            # shot, so _spawn_projectile's homing lookup (reading this
            # tube's own _target) can't home a dumbfire on a target the
            # player no longer has selected.
            self._target = None
            self._target_offset = None
        self._firing = True
        now = _game_time()
        self._num_ready -= 1
        self._last_fire_time = now
        parent = self.GetParentSubsystem()
        if parent is not None:
            parent._last_system_fire_time = now
        self._start_slot_cooldown(now)

        self._spawn_torpedo()

        # BC's order (audited): ET_TORPEDO_FIRED (posted inside _spawn_torpedo,
        # once the projectile exists) THEN ET_WEAPON_FIRED, then the
        # player-only ET_TORPEDO_AMMO_CONSUMED.
        self._broadcast_weapon_fired()
        self._broadcast_ammo_consumed_if_player()

        # Discrete-shot — auto-stop after launch.
        self._firing = False
        return True

    def _broadcast_weapon_fired(self) -> None:
        """Post ET_WEAPON_FIRED: Source = the TUBE, Destination = the owning
        ship.  Posted AFTER ET_TORPEDO_FIRED on every successful launch
        (weapon-firing-mechanics.md §1.5/§2.4, audited).  Delegates to the
        module-level ``_post_weapon_fired`` shared with PhaserBank.Fire
        (Task 10)."""
        _post_weapon_fired(self)

    def _broadcast_weapon_fire_failed(self) -> None:
        """Post ET_WEAPON_FIRE_FAILED: Destination = the TUBE.  Posted when a
        targeted fire fails the aim-point resolve or the +/-30 degree cone
        (audited; no shipped SDK script listens — defined for fidelity +
        mod surface)."""
        import App
        from engine import dev_mode
        try:
            evt = App.TGEvent_Create()
            evt.SetEventType(App.ET_WEAPON_FIRE_FAILED)
            evt.SetDestination(self)
            App.g_kEventManager.AddEvent(evt)
        except Exception as _e:
            dev_mode.log_swallowed("ET_WEAPON_FIRE_FAILED broadcast", _e)

    def _broadcast_ammo_consumed_if_player(self) -> None:
        """Post ET_TORPEDO_AMMO_CONSUMED, but ONLY when the firing ship is
        the player ship (BC locality gate — audited).  Source = the TUBE,
        Destination = the ship, mirroring ET_WEAPON_FIRED."""
        ship = self._climb_to_ship()
        import App
        try:
            if ship is None or ship is not App.Game_GetCurrentPlayer():
                return
        except Exception:
            return
        from engine import dev_mode
        try:
            evt = App.TGEvent_Create()
            evt.SetEventType(App.ET_TORPEDO_AMMO_CONSUMED)
            evt.SetSource(self)
            evt.SetDestination(ship)
            App.g_kEventManager.AddEvent(evt)
        except Exception as _e:
            dev_mode.log_swallowed("ET_TORPEDO_AMMO_CONSUMED broadcast", _e)

    def _spawn_torpedo(self) -> None:
        """Look up the parent system's GetTorpedoScript(0), import the SDK
        projectile module, instantiate a Torpedo, call <module>.Create(t)
        to populate visuals + behaviour, launch it BC-faithfully (straight
        out the tube's authored direction + inherited ship velocity — see
        _spawn_projectile), and play the launch sound.

        Silent no-op when no script is bound (matches BC for unconfigured
        tubes).  Per-tube slot routing is a future polish item — PR 2b
        always pulls from slot 0.
        """
        parent = self.GetParentSubsystem()
        if parent is None:
            return
        # Per-launch ammo debit (moved here from TorpedoSystem.StartFiring's
        # volley accounting when StartFiring became a pure tick-arm): expend
        # one round of the parent's selected type per torpedo launched.
        # Finite types only — unlimited/undeclared magazines never decrement.
        ammo = (parent.GetCurrentAmmoType()
                if hasattr(parent, "GetCurrentAmmoType") else None)
        if ammo is not None and not getattr(ammo, "_unlimited", True):
            ammo.AddAvailable(-1)
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
                                 drf_override=self.GetDamageRadiusFactor())
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

    def IsDumbFire(self) -> int:
        """Torpedo tubes are dumbfire-capable in BC (no guidance).
        Overrides Weapon.IsDumbFire() which returns 0."""
        return 1

    def SetSkewFire(self, flag) -> None:
        """Set skew-fire flag on this tube.  The flag is persistent and
        survives StopFiring (never cleared by firing lifecycle)."""
        self._skew_fire = bool(flag)

    def IsSkewFire(self) -> int:
        """Return 1 if skew-fire is enabled on this tube, else 0."""
        return 1 if self._skew_fire else 0
