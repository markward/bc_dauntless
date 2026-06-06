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


def _is_offline(sub) -> bool:
    """True when a subsystem is disabled OR destroyed.

    Project 5 single source of truth for the five capability gates
    (engines, weapons, sensors, shield generator, repair-verify).
    Reads predicates at use-time so repair lifting condition releases
    the gate automatically on the next call.
    """
    if sub is None:
        return False
    return bool(sub.IsDisabled()) or bool(sub.IsDestroyed())


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
        self._targetable: int = 0
        self._primary: int = 0
        self._disabled_percentage: float = 0.25
        # Explicit damage/destroyed flags.  SetDamaged/SetDestroyed let tests
        # and the damage system force these states independently of _condition;
        # the predicate methods also fall back to condition-based derivation so
        # both paths stay consistent (e.g. applying condition damage will also
        # make IsDestroyed() true when condition hits zero).
        self._damaged: bool = False
        self._destroyed: bool = False
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
        """Ship world location + emitter local position rotated into world frame.

        SDK SetPosition values are already in world units relative to the
        ship's centre of mass — confirmed via the 2026-05-16 hardpoint-
        scale instrumentation (see
        docs/instrumented_experiments/2026-05-15-hardpoint-scale-investigation.md).
        BC applies no scale factor; `world = ship_loc + rotate(local_pos)`.
        """
        ship = self._climb_to_ship()
        if ship is None:
            return TGPoint3(0.0, 0.0, 0.0)
        ship_pos = ship.GetWorldLocation()
        local = self.GetPosition() if hasattr(self, "GetPosition") else None
        if not isinstance(local, TGPoint3):
            return TGPoint3(ship_pos.x, ship_pos.y, ship_pos.z)
        offset = TGPoint3(local.x, local.y, local.z)
        if hasattr(ship, "GetWorldRotation"):
            rot = ship.GetWorldRotation()
            if isinstance(rot, TGMatrix3):
                offset.MultMatrixLeft(rot)
        return TGPoint3(ship_pos.x + offset.x,
                        ship_pos.y + offset.y,
                        ship_pos.z + offset.z)

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
        # Right = up × forward (matches WeaponProperty.SetOrientation
        # derivation; the arc gate's up = direction × right reconstructs
        # this same up vector).
        world_right = TGPoint3(
            world_up.y * world_forward.z - world_up.z * world_forward.y,
            world_up.z * world_forward.x - world_up.x * world_forward.z,
            world_up.x * world_forward.y - world_up.y * world_forward.x,
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

        # Rodrigues: rotate world_forward around world_up by yaw.
        c, s = _math.cos(yaw), _math.sin(yaw)
        u_dot_f = (world_up.x * world_forward.x
                 + world_up.y * world_forward.y
                 + world_up.z * world_forward.z)
        # u × f
        ux_fx_y = world_up.y * world_forward.z - world_up.z * world_forward.y
        ux_fx_z = world_up.z * world_forward.x - world_up.x * world_forward.z
        ux_fx_w = world_up.x * world_forward.y - world_up.y * world_forward.x
        emit_dir = TGPoint3(
            world_forward.x * c + ux_fx_y * s + world_up.x * u_dot_f * (1.0 - c),
            world_forward.y * c + ux_fx_z * s + world_up.y * u_dot_f * (1.0 - c),
            world_forward.z * c + ux_fx_w * s + world_up.z * u_dot_f * (1.0 - c),
        )

        return TGPoint3(
            center.x + emit_dir.x * length,
            center.y + emit_dir.y * length,
            center.z + emit_dir.z * length,
        )

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

    # ── Runtime predicates consumed by AI/Preprocessors.py ───────────────────
    # SDK App.py:5652-5657 — native methods on ShipSubsystem.  Phase 1 stubs
    # return SDK-faithful defaults; richer hooks (per-subsystem criticality
    # flags, LOS to subsystem position) land alongside the consumers that
    # need them.

    def IsCritical(self) -> int:
        """SDK Preprocessors.py:963 — rating heuristic. Phase 1 default 0
        (no subsystem is flagged critical until SubsystemProperty data
        flows into _critical via SetCritical)."""
        return 0

    def IsTargetable(self) -> int:
        """SDK Preprocessors.py:953-954, 829 — AI iterates subsystems and
        only adds those reporting IsTargetable()=1 to the rating list.
        Phase 1 treats every ShipSubsystem as targetable; subclasses /
        property-driven overrides can return 0 once they need to model
        un-targetable internals (e.g. crew quarters)."""
        return 1

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

    def IsHittableFromLocation(self, vWorldLoc) -> float:
        """SDK Preprocessors.py:980 — `fHittable = pSubsystem.IsHittableFromLocation(pOurShip.GetWorldLocation())`.
        Native Appc returns a scalar (0.0..1.0) reflecting LOS / occlusion
        from the firing ship's location to the subsystem position. Phase 1
        treats every subsystem as fully hittable (no occlusion model);
        real geometry support lands when the renderer carries collision
        meshes."""
        return 1.0


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

        from engine.appc.projectiles import Torpedo, register
        from engine.appc.math import TGPoint3
        from engine.audio.tg_sound import TGSoundManager

        torp = Torpedo()
        source_ship = self._climb_to_ship()
        torp._source_ship = source_ship
        torp._position = self._emitter_world_position()

        mod.Create(torp)

        # §3.2 DRF override: if the launching tube has a non-zero
        # DamageRadiusFactor (set by the hardpoint script, e.g.
        # galaxy.py ForwardTorpedo1.SetDamageRadiusFactor(0.20)),
        # it overrides the payload value set by mod.Create above.
        # host_loop passes the torpedo as hardpoint_weapon to apply_hit,
        # so torp._damage_radius_factor must carry the launcher value.
        tube_drf = self.GetDamageRadiusFactor()
        if tube_drf > 0.0:
            torp._damage_radius_factor = tube_drf

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


class HullSubsystem(ShipSubsystem):
    """Live hull state.  Hull isn't a powered subsystem — it just tracks
    condition (max + current) so damage logic can read GetMaxCondition()."""
    pass


class SensorSubsystem(PoweredSubsystem):
    def __init__(self, name: str = ""):
        super().__init__(name)
        self._base_sensor_range: float = 0.0
        self._max_probes: int = 0
        # Objects whose existence is known to the sensor system.
        # Populated by the game loop / radar sweep logic.  Default is
        # empty (nothing known), matching the initial unscanned state.
        self._known_objects: set = set()

    def GetBaseSensorRange(self) -> float:           return self._base_sensor_range
    def SetBaseSensorRange(self, v) -> None:         self._base_sensor_range = float(v)
    def GetMaxProbes(self) -> int:                   return self._max_probes
    def SetMaxProbes(self, v) -> None:               self._max_probes = int(v)

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
        except Exception:
            pass

    def RemoveKnownObject(self, obj) -> None:
        """Remove *obj* from known contacts."""
        try:
            self._known_objects.discard(obj.GetObjID())
        except Exception:
            pass


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

    def GetCurShields(self, face: int) -> float:
        """SDK-facing alias of GetCurrentShields (matches Appc method name).

        Used by SDK PlainAI/IntelligentCircleObject.py:176-179 for
        shield-bias orbit positioning."""
        return self.GetCurrentShields(face)

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

    def GetShieldPercentage(self) -> float:
        """Aggregate ratio of total current shields to total max,
        across all 6 faces. Returns 1.0 when no face has max set
        (unshielded ship) so SelectTarget rating treats them as
        "shields not a factor" rather than "shields critically low."""
        total_max = sum(self._max_shields)
        if total_max <= 0:
            return 1.0
        total_cur = sum(self._current_shields)
        return total_cur / total_max

    def GetShieldChargePerSecond(self, face: int) -> float:
        return self._charge_per_second[int(face)]

    def SetShieldChargePerSecond(self, face: int, value: float) -> None:
        self._charge_per_second[int(face)] = float(value)

    def Update(self, dt: float) -> None:
        """Per-tick regen: current += charge_per_second * dt, clamped to max.

        Faces with max==0 are skipped so unshielded faces never accumulate.

        Disabled-generator gate (Project 5 §4.4): when _is_offline(self),
        skip the whole loop. _charge_per_second values are NOT mutated;
        repair restores regen at the original rates on the next call.

        Powered-down gate: when the generator is not IsOn (alert level
        is GREEN, or nothing has raised shields yet), regen is suppressed.
        ShipClass.SetAlertLevel drains the face values to zero on the same
        transition; this gate just prevents Update from leaking charge
        back in.
        """
        if _is_offline(self):
            return
        if not self.IsOn():
            return
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

    Three pools mirror Appc (App.py:5739-5754):

    * **available** — instantaneous surplus from generation, refilled
      each tick.  Weapons drain this first.
    * **main battery** — capped reserve (PowerProperty.MainBatteryLimit)
      that absorbs surplus and surrenders it when available runs out.
    * **backup battery** — emergency reserve.  Reserved for the per-tick
      flow implementation; the runtime arithmetic ops here treat it as
      passive storage only.

    Arithmetic ops do NOT partial-drain: callers (TorpedoTube.Fire,
    PhaserBank power debit, etc.) treat a return of 0 as "did not have
    enough power, do nothing" and a return of 1 as "billed in full".
    """
    def __init__(self, name: str = ""):
        super().__init__(name)
        self._available_power: float = 0.0
        self._main_battery_power: float = 0.0
        self._backup_battery_power: float = 0.0

    def GetAvailablePower(self) -> float:           return self._available_power
    def SetAvailablePower(self, v) -> None:         self._available_power = float(v)
    def GetMainBatteryPower(self) -> float:         return self._main_battery_power
    def SetMainBatteryPower(self, v) -> None:       self._main_battery_power = float(v)
    def GetBackupBatteryPower(self) -> float:       return self._backup_battery_power
    def SetBackupBatteryPower(self, v) -> None:     self._backup_battery_power = float(v)

    def AddPower(self, amount) -> None:
        self._available_power += float(amount)

    def DeductPower(self, amount) -> int:
        amt = float(amount)
        if amt > self._available_power:
            return 0
        self._available_power -= amt
        return 1

    def StealPower(self, amount) -> int:
        amt = float(amount)
        if amt > self._available_power + self._main_battery_power:
            return 0
        from_avail = min(amt, self._available_power)
        self._available_power -= from_avail
        self._main_battery_power -= (amt - from_avail)
        return 1

    def StealPowerFromReserve(self, amount) -> int:
        amt = float(amount)
        if amt > self._available_power + self._main_battery_power:
            return 0
        from_main = min(amt, self._main_battery_power)
        self._main_battery_power -= from_main
        self._available_power -= (amt - from_main)
        return 1

    # ── Per-tick flow ─────────────────────────────────────────────────────
    # Walked from GameLoop.tick. Sums idle drain across the parent ship's
    # powered subsystems, applies generation, and routes surplus / deficit
    # through the battery pools. The available pool is refilled to the
    # tick's surplus so weapons can spend it via DeductPower / StealPower
    # within the same tick.

    _IDLE_DRAIN_SLOTS = (
        "GetSensorSubsystem", "GetImpulseEngineSubsystem",
        "GetWarpEngineSubsystem", "GetShieldSubsystem",
        "GetPhaserSystem", "GetTorpedoSystem",
        "GetPulseWeaponSystem", "GetTractorBeamSystem",
        "GetRepairSubsystem",
    )

    def _compute_idle_drain(self) -> float:
        ship = self.GetParentShip()
        if ship is None:
            return 0.0
        total = 0.0
        for getter_name in self._IDLE_DRAIN_SLOTS:
            getter = getattr(ship, getter_name, None)
            if getter is None:
                continue
            sub = getter()
            if sub is None:
                continue
            if not hasattr(sub, "IsOn") or not sub.IsOn():
                continue
            if not hasattr(sub, "GetNormalPowerPerSecond"):
                continue
            total += float(sub.GetNormalPowerPerSecond() or 0.0)
        return total

    def Update(self, dt: float) -> None:
        prop = self.GetProperty()
        if prop is None:
            return
        output = float(prop.GetPowerOutput() or 0.0)
        main_cap = float(prop.GetMainBatteryLimit() or 0.0)
        idle_drain = self._compute_idle_drain()

        gen = output * dt
        drain = idle_drain * dt
        net = gen - drain

        if net >= 0.0:
            self._main_battery_power = min(
                main_cap, self._main_battery_power + net
            )
            self._available_power = net
            return

        # Deficit — pull from main, then backup.  Subsystems still
        # "run" (we don't simulate brown-out yet); the only observable
        # is a drained reserve.
        deficit = -net
        from_main = min(deficit, self._main_battery_power)
        self._main_battery_power -= from_main
        remaining = deficit - from_main
        if remaining > 0.0:
            from_backup = min(remaining, self._backup_battery_power)
            self._backup_battery_power -= from_backup
        self._available_power = 0.0


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


# ── Sensor-visibility update ──────────────────────────────────────────────────

def update_target_list_visibility(target_menu, ships, player, range_units: float = 30000.0) -> None:
    """Flip STSubsystemMenu.SetVisible/SetNotVisible on each row based
    on the ship's distance from the player.

    Args:
        target_menu: the STTargetMenu singleton (or any object exposing
            GetObjectEntry).
        ships: iterable of ship objects expected to be in the menu.
        player: the player ship (for distance computation).
        range_units: maximum range to consider visible. Default 30000
            game units; replace with SensorProperty.GetMaxRange once
            the sensor data is plumbed.

    Real Appc filters by sensor subsystem state (charged, undamaged,
    not jammed). Phase-2 takes only range into account; the property
    chain will be wired in a later iteration.

    Project 5 sensor gate (§4.3): when the player's own SensorSubsystem
    reports _is_offline, every row in the menu goes invisible regardless
    of range. The radar panel and target-list view both filter on
    row.IsVisible(), so contacts disappear automatically.
    """
    from engine.appc.target_menu import STSubsystemMenu
    if player is None:
        return
    sensors = (player.GetSensorSubsystem()
               if hasattr(player, "GetSensorSubsystem") else None)
    if _is_offline(sensors):
        for ship in ships:
            row = target_menu.GetObjectEntry(ship)
            if row is None or not isinstance(row, STSubsystemMenu):
                continue
            row.SetNotVisible()
        return
    px, py, pz = _get_xyz(player)
    range_sq = range_units * range_units
    for ship in ships:
        row = target_menu.GetObjectEntry(ship)
        if row is None or not isinstance(row, STSubsystemMenu):
            continue
        sx, sy, sz = _get_xyz(ship)
        dx, dy, dz = sx - px, sy - py, sz - pz
        if dx * dx + dy * dy + dz * dz <= range_sq:
            row.SetVisible()
        else:
            row.SetNotVisible()


def _get_xyz(ship) -> tuple:
    """Read a ship's world-space position as a tuple of floats. Adapts
    to whichever accessor the shim exposes. Falls back to (0, 0, 0) so
    the helper is safe to call against a ship that hasn't been
    positioned yet (e.g. just spawned)."""
    # GetTranslate() returns a TGPoint3 with .x, .y, .z attributes.
    for name in ("GetTranslate", "GetWorldLocation", "GetTranslation", "GetPosition",
                 "GetTranslateXYZ"):
        if hasattr(ship, name):
            try:
                t = getattr(ship, name)()
                # TGPoint3 / any object with .x .y .z
                if hasattr(t, "x") and hasattr(t, "y") and hasattr(t, "z"):
                    return (float(t.x), float(t.y), float(t.z))
                # plain tuple or list
                if isinstance(t, (tuple, list)) and len(t) == 3:
                    return (float(t[0]), float(t[1]), float(t[2]))
            except Exception:
                pass
    # Last resort — direct attribute access for the simplest possible shim.
    if hasattr(ship, "_position"):
        try:
            p = ship._position
            if hasattr(p, "x") and hasattr(p, "y") and hasattr(p, "z"):
                return (float(p.x), float(p.y), float(p.z))
            if isinstance(p, (tuple, list)) and len(p) == 3:
                return (float(p[0]), float(p[1]), float(p[2]))
        except Exception:
            pass
    return (0.0, 0.0, 0.0)
