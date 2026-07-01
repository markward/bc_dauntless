"""TGModelProperty hierarchy + manager.

See docs/superpowers/specs/2026-05-08-model-property-manager-design.md.
"""


class TGModelProperty:
    def __init__(self, name: str):
        self._name = name
        self._data: dict = {}
        # Mount point in model-local coordinates. None until SetPosition
        # populates it. Stored at the root because two different SDK
        # base classes use the same slot with different signatures:
        # SubsystemProperty.SetPosition(x, y, z)   (sdk App.py:9149) and
        # PositionOrientationProperty.SetPosition(TGPoint3) (App.py:9107).
        # Both fell through to __getattr__'s data-bag before this fix.
        self._position = None

    def GetName(self):
        # Real Appc returns a TGString (App.py:436 binds CompareC on it); SDK
        # callers chain ``GetName().CompareC(name, 1)`` to match named mounts
        # (MissionLib.GetPositionOrientationFromProperty). _TGString subclasses
        # str, so every plain-string use site is unaffected.
        from engine.appc.localization import _TGString
        return _TGString(self._name)

    def SetName(self, value: str) -> None:
        self._name = value

    def __bool__(self) -> bool:
        return True

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self._name!r}>"

    def SetPosition(self, *args) -> None:
        """Mount position in model-local coordinates.

        Accepts both SDK overloads in one dispatch so neither form
        leaks to the data-bag catch-all:

        - ``SetPosition(x, y, z)`` — SubsystemProperty form
          (galaxy.py: ``DorsalPhaser1.SetPosition(0, 1.27, 0.5)``).
        - ``SetPosition(TGPoint3)`` — PositionOrientationProperty form
          (galaxy.py: ``Viewscreen.SetPosition(ViewscreenPosition)``).
        """
        from engine.appc.math import TGPoint3
        if len(args) == 3:
            self._position = TGPoint3(
                float(args[0]), float(args[1]), float(args[2])
            )
        elif len(args) == 1 and args[0] is not None:
            p = args[0]
            self._position = TGPoint3(float(p.x), float(p.y), float(p.z))

    def GetPosition(self):
        """Return a fresh TGPoint3 copy of the stored position, or None
        if SetPosition was never called. SDK semantics: callers may
        mutate the returned value (e.g. via MultMatrixLeft) without
        affecting the template.
        """
        if self._position is None:
            return None
        from engine.appc.math import TGPoint3
        return TGPoint3(self._position.x, self._position.y, self._position.z)

    def GetPositionTG(self):
        # SDK exposes both GetPosition (NiPoint3) and GetPositionTG
        # (TGPoint3). Our shim doesn't distinguish; both return TGPoint3.
        return self.GetPosition()

    def __getattr__(self, attr: str):
        if attr.startswith("Set"):
            field = attr[3:]
            data = self._data
            cls_name = type(self).__name__
            def setter(*args):
                data[(field, _hashable_key(args[:-1]))] = args[-1]
                # Empirical consumer tracking: if any arg is a TGColorA, log
                # which shim setter received it (off unless harness enables).
                import App as _App
                if _App._color_consumer_tracker.is_enabled():
                    for a in args:
                        if isinstance(a, _App.TGColorA):
                            import sys as _sys
                            frame = _sys._getframe(1)
                            _App._color_consumer_tracker.record(
                                f"{cls_name}.{attr}", a,
                                frame.f_code.co_filename, frame.f_lineno,
                            )
                            break
            return setter
        if attr.startswith("Get"):
            field = attr[3:]
            data = self._data
            def getter(*args):
                return data.get((field, _hashable_key(args)), None)
            return getter
        raise AttributeError(attr)


def _copy_point(p):
    """Fresh TGPoint3 copy, or None if the source is None.

    Matches SDK semantics where Get*() returns a copy callers can mutate
    (e.g. via MultMatrixLeft) without affecting the template.
    """
    if p is None:
        return None
    from engine.appc.math import TGPoint3
    return TGPoint3(p.x, p.y, p.z)


def _hashable_key(args: tuple) -> tuple:
    """Convert a tuple of args into a hashable key.

    Falls back to repr() for any element that isn't hashable (e.g.
    TGPoint3, which defines __eq__ but not __hash__). This keeps the
    data-bag tolerant of SDK setters that pass unhashable arguments
    such as SetOrientation(forward_vec, up_vec).
    """
    try:
        hash(args)
        return args
    except TypeError:
        return tuple(
            a if _is_hashable(a) else repr(a)
            for a in args
        )


def _is_hashable(value) -> bool:
    try:
        hash(value)
        return True
    except TypeError:
        return False


# ── Subclass hierarchy ────────────────────────────────────────────────────────
# Subclasses are thin: only class-level constants. All Set*/Get* behaviour is
# inherited from the data-bag base.

class PositionOrientationProperty(TGModelProperty):
    """Bare-position / orientation property — viewscreen anchors,
    first-person camera mounts, etc. SDK App.py:9106-9107 binds typed
    SetOrientation(forward, up, right) and SetPosition(TGPoint3); both
    landed in the data-bag prior to typed setters.
    """

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._forward = None
        self._up = None
        self._right = None

    def SetOrientation(self, forward, up, right) -> None:
        self._forward = _copy_point(forward)
        self._up = _copy_point(up)
        self._right = _copy_point(right)

    def GetForward(self):
        return _copy_point(self._forward)

    def GetUp(self):
        return _copy_point(self._up)

    def GetRight(self):
        return _copy_point(self._right)


class ObjectEmitterProperty(PositionOrientationProperty):
    """Emitter point on a hull (shuttle / probe / decoy launch position).

    SDK hierarchy: ObjectEmitterProperty extends PositionOrientationProperty.
    Hardpoint scripts populate position, orientation, and emitted object type
    via SetPosition / SetOrientation / SetEmittedObjectType; the LaunchObject
    action reads them back to compute world-frame launch transforms.
    """

    OEP_UNKNOWN = 0
    OEP_SHUTTLE = 1
    OEP_PROBE   = 2
    OEP_DECOY   = 3

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._emitted_type = self.OEP_UNKNOWN
        # _position / _forward / _up / _right + their setters/getters
        # come from PositionOrientationProperty / TGModelProperty.

    def SetEmittedObjectType(self, t):
        self._emitted_type = int(t)

    def GetEmittedObjectType(self):
        return self._emitted_type


class EngineGlowProperty(TGModelProperty):
    pass


class SubsystemProperty(TGModelProperty):
    def __init__(self, name: str = ""):
        super().__init__(name)
        self._targetable = 1
        # SDK App.py:9148-9150 exposes SetPosition2D / GetPosition2D
        # on SubsystemProperty for the 2D damage-display panel layout.
        # Distinct from the 3D mount Position hoisted on TGModelProperty.
        self._position_2d: tuple = (0.0, 0.0)
        # WeaponsDisplay icon descriptors. SDK App.py:9232-9239 declares
        # SetIconNum / SetIconPositionX / SetIconPositionY /
        # SetIconAboveShip on WeaponProperty, and 9265-9278 adds the
        # IndicatorIcon triplet on EnergyWeaponProperty. We hoist all
        # seven onto the subsystem base so torpedo, phaser, tractor, and
        # pulse hardpoints share one typed path — single setters
        # round-tripped through the data-bag, but IsIconAboveShip (the
        # SDK's canonical predicate accessor — see WeaponsDisplay.py:412)
        # has no Get/Set spelling and crashed the consumer. Coordinates
        # are pixel-space against the SDK's 640x480 reference; the panel
        # divides by 640/480 to obtain fractions. icon_num=0 mirrors the
        # SDK's Destroyed-slot fallback in Icons/WeaponIcons.py:55-56.
        #
        # NOTE: _icon_num here is the WeaponsDisplay arc-icon number
        # (e.g. 330/340/350/360 for phaser arc shapes, 370 for torpedo
        # glyphs). It is unrelated to the DamageDisplay glyph number,
        # which is derived from the runtime subsystem CLASS via
        # engine.ui.damage_icons.icon_num_for_subsystem() and is NOT
        # stored as a property field. Do not wire SetIconNum(0..9) on
        # damage hardpoints expecting it to set the damage glyph.
        self._icon_num: int = 0
        self._icon_position_x_px: float = 0.0
        self._icon_position_y_px: float = 0.0
        self._icon_above_ship: int = 0
        self._indicator_icon_num: int = 0
        self._indicator_icon_position_x_px: float = 0.0
        self._indicator_icon_position_y_px: float = 0.0

    def IsTargetable(self) -> int:
        return self._targetable

    def GetTargetable(self) -> int:
        return self._targetable

    def SetTargetable(self, value) -> None:
        self._targetable = int(value)

    def SetPosition2D(self, x, y) -> None:
        self._position_2d = (float(x), float(y))

    def GetPosition2D(self) -> tuple:
        return self._position_2d

    # ── WeaponsDisplay icon setters/getters ──────────────────────────────
    def SetIconNum(self, n) -> None:
        self._icon_num = int(n)

    def GetIconNum(self) -> int:
        return self._icon_num

    def SetIconPositionX(self, x) -> None:
        self._icon_position_x_px = float(x)

    def GetIconPositionX(self) -> float:
        return self._icon_position_x_px

    def SetIconPositionY(self, y) -> None:
        self._icon_position_y_px = float(y)

    def GetIconPositionY(self) -> float:
        return self._icon_position_y_px

    def SetIconAboveShip(self, v) -> None:
        self._icon_above_ship = int(v)

    def IsIconAboveShip(self) -> int:
        return self._icon_above_ship

    def SetIndicatorIconNum(self, n) -> None:
        self._indicator_icon_num = int(n)

    def GetIndicatorIconNum(self) -> int:
        return self._indicator_icon_num

    def SetIndicatorIconPositionX(self, x) -> None:
        self._indicator_icon_position_x_px = float(x)

    def GetIndicatorIconPositionX(self) -> float:
        return self._indicator_icon_position_x_px

    def SetIndicatorIconPositionY(self, y) -> None:
        self._indicator_icon_position_y_px = float(y)

    def GetIndicatorIconPositionY(self) -> float:
        return self._indicator_icon_position_y_px


class HullProperty(SubsystemProperty):
    pass


class PowerProperty(SubsystemProperty):
    pass


class WeaponProperty(SubsystemProperty):
    """Base for every emitter template. Stores the per-emitter body-frame
    basis (Direction = forward / firing axis, Up = arc-plane normal,
    Right = side axis) so SetDirection / SetRight / SetOrientation calls
    from hardpoints land in typed slots rather than TGObject's catch-all.
    """
    def __init__(self, name: str = ""):
        super().__init__(name)
        from engine.appc.math import TGPoint3
        # SDK convention: firing along body +Y, right along body +X,
        # up along body +Z. Holds until a hardpoint overrides via
        # SetOrientation / SetDirection / SetRight.
        self._direction = TGPoint3(0.0, 1.0, 0.0)
        self._right     = TGPoint3(1.0, 0.0, 0.0)
        self._up        = TGPoint3(0.0, 0.0, 1.0)
        # SDK App.py:9230 — WeaponProperty.GetDamageRadiusFactor.
        # Hardpoint scripts call SetDamageRadiusFactor on each emitter
        # template (e.g. peregrine.py:153, keldon.py:252); the live
        # ShipSubsystem mirrors this via SetProperty.
        self._damage_radius_factor: float = 0.0

    def GetDirection(self):
        from engine.appc.math import TGPoint3
        return TGPoint3(self._direction.x, self._direction.y, self._direction.z)

    def SetDirection(self, v) -> None:
        from engine.appc.math import TGPoint3
        if isinstance(v, TGPoint3):
            self._direction = TGPoint3(v.x, v.y, v.z)

    def GetRight(self):
        from engine.appc.math import TGPoint3
        return TGPoint3(self._right.x, self._right.y, self._right.z)

    def SetRight(self, v) -> None:
        from engine.appc.math import TGPoint3
        if isinstance(v, TGPoint3):
            self._right = TGPoint3(v.x, v.y, v.z)

    def GetUp(self):
        from engine.appc.math import TGPoint3
        return TGPoint3(self._up.x, self._up.y, self._up.z)

    def SetUp(self, v) -> None:
        from engine.appc.math import TGPoint3
        if isinstance(v, TGPoint3):
            self._up = TGPoint3(v.x, v.y, v.z)

    # Mirror BC's PhaserBank / PhaserProperty accessor names —
    # sdk App.py:6478-6489 (PhaserBank) and App.py:9287-9292
    # (PhaserProperty). Callers use either spelling interchangeably.
    def GetOrientationForward(self):
        return self.GetDirection()

    def GetOrientationUp(self):
        return self.GetUp()

    def GetOrientationRight(self):
        return self.GetRight()

    def SetOrientation(self, forward, up) -> None:
        """Set the body-frame orientation from a (forward, up) pair.

        SDK signature: ``PhaserProperty.SetOrientation(forward, up)``
        (App.py:9320). Right = Forward × Up gives a right-handed body basis, so
        ``GetRight()`` is the true starboard axis (post 2026-06-18 un-mirror).
        Without this typed setter the call falls through TGModelProperty's
        data-bag and every bank stays at the default (firing +Y) — i.e. every
        phaser arc is centred on the ship's nose. See research doc Bug B and
        docs/superpowers/plans/2026-06-18-render-handedness-unmirror.md.
        """
        from engine.appc.math import TGPoint3
        if not (isinstance(forward, TGPoint3) and isinstance(up, TGPoint3)):
            return
        self._direction = TGPoint3(forward.x, forward.y, forward.z)
        self._up        = TGPoint3(up.x, up.y, up.z)
        # Right-handed basis: Right = Forward × Up.
        self._right = TGPoint3(
            forward.y * up.z - forward.z * up.y,
            forward.z * up.x - forward.x * up.z,
            forward.x * up.y - forward.y * up.x,
        )

    def GetDamageRadiusFactor(self) -> float:
        return self._damage_radius_factor

    def SetDamageRadiusFactor(self, v) -> None:
        self._damage_radius_factor = float(v)


class EnergyWeaponProperty(WeaponProperty):
    """Energy-weapon hardpoint template — phasers, pulse cannons, tractors.

    Charge model (sdk/.../App.py:9271-9274): MaxCharge is the reservoir cap,
    MinFiringCharge is the gate to start firing, NormalDischargeRate drains
    charge while firing, RechargeRate fills it when idle.  Typical galaxy.py
    values: max=5, min=3, discharge=1.0/s, recharge=0.08/s.
    """
    def __init__(self, name: str = ""):
        super().__init__(name)
        self._max_charge: float = 0.0
        self._min_firing_charge: float = 0.0
        self._normal_discharge_rate: float = 0.0
        self._recharge_rate: float = 0.0
        self._fire_sound: str = ""
        # Arc bounds — radians.  Hardpoints call SetArcWidthAngles /
        # SetArcHeightAngles to set firing cone limits.  Defaults are
        # full-sphere (no gate); typed setters narrow them.
        import math as _math
        self._arc_width_lo:  float = -_math.pi
        self._arc_width_hi:  float =  _math.pi
        self._arc_height_lo: float = -_math.pi / 2
        self._arc_height_hi: float =  _math.pi / 2
        self._max_damage:           float = 0.0
        self._max_damage_distance:  float = 0.0
        # Phaser-strip length along the Right axis (galaxy.py: 1.5–1.7).
        # 0.0 = treat the emitter as a point.
        self._length:               float = 0.0
        # Phaser-strip width -- the strip's lateral dimension perpendicular
        # to Length. Distinct from PhaserWidth (the beam thickness on
        # PhaserProperty). Galaxy banks use 1.01-1.69 GU; the value is the
        # second axis of the strip's surface patch.  Without this typed
        # setter the SDK ``SetWidth(1.35)`` calls fall through to the
        # data-bag and are silently dropped. See research doc Bug C.
        self._width:                float = 0.0
        # Texture tiling along the beam.  SDK convention: tiles per
        # world unit of beam length.  Galaxy phasers use 0.5 (one full
        # texture every 2 world units).  PhaserLights.tga is 32x32 so
        # without tiling it stretches across the whole beam and dilutes
        # the alpha gradient.
        self._length_texture_tile_per_unit: float = 0.0

    def GetLength(self) -> float:
        return self._length

    def SetLength(self, v) -> None:
        self._length = float(v)

    def GetWidth(self) -> float:
        return self._width

    def SetWidth(self, v) -> None:
        self._width = float(v)

    def GetLengthTextureTilePerUnit(self) -> float:
        return self._length_texture_tile_per_unit

    def SetLengthTextureTilePerUnit(self, v) -> None:
        self._length_texture_tile_per_unit = float(v)

    def GetArcWidthAngles(self) -> tuple:
        return (self._arc_width_lo, self._arc_width_hi)

    def SetArcWidthAngles(self, lo, hi) -> None:
        self._arc_width_lo = float(lo)
        self._arc_width_hi = float(hi)

    def GetArcHeightAngles(self) -> tuple:
        return (self._arc_height_lo, self._arc_height_hi)

    def SetArcHeightAngles(self, lo, hi) -> None:
        self._arc_height_lo = float(lo)
        self._arc_height_hi = float(hi)

    def GetMaxDamage(self) -> float:
        return self._max_damage

    def SetMaxDamage(self, v) -> None:
        self._max_damage = float(v)

    def GetMaxDamageDistance(self) -> float:
        return self._max_damage_distance

    def SetMaxDamageDistance(self, v) -> None:
        self._max_damage_distance = float(v)

    def GetMaxCharge(self) -> float:
        return self._max_charge

    def SetMaxCharge(self, v) -> None:
        self._max_charge = float(v)

    def GetMinFiringCharge(self) -> float:
        return self._min_firing_charge

    def SetMinFiringCharge(self, v) -> None:
        self._min_firing_charge = float(v)

    def GetNormalDischargeRate(self) -> float:
        return self._normal_discharge_rate

    def SetNormalDischargeRate(self, v) -> None:
        self._normal_discharge_rate = float(v)

    def GetRechargeRate(self) -> float:
        return self._recharge_rate

    def SetRechargeRate(self, v) -> None:
        self._recharge_rate = float(v)

    def GetFireSound(self) -> str:
        return self._fire_sound

    def SetFireSound(self, v) -> None:
        self._fire_sound = str(v)


class PhaserProperty(EnergyWeaponProperty):
    """Phaser-beam template — adds layered colour + geometry over the
    EnergyWeaponProperty base.

    SDK setters (see sdk/Build/scripts/ships/Hardpoints/galaxy.py:418-438):
    - SetPhaserWidth(w):       outer beam half-width in world units
    - SetMainRadius(r):        inner beam half-width (overrides core scaling)
    - SetCoreScale(s):         inner-core width as fraction of outer (0.5 typical)
    - SetOuterShellColor(c):   outer halo tint (orange-red on Fed phasers)
    - SetInnerShellColor(c):   second outer tint (often same as outer)
    - SetOuterCoreColor(c):    bright transition tint (light tan on Fed)
    - SetInnerCoreColor(c):    central bright core (near-white on Fed)

    Colours stored as RGBA tuples; SDK passes TGColorA, we coerce on set.
    """
    def __init__(self, name: str = ""):
        super().__init__(name)
        # Geometry — defaults match BC's typical Federation phaser.
        self._phaser_width: float = 0.30
        self._main_radius:  float = 0.15
        self._core_scale:   float = 0.50
        # Colour layers — RGBA tuples.  Default to a neutral white so a
        # property without explicit Set*Color reads as visible-but-bland
        # rather than transparent.
        self._outer_shell_color: tuple = (1.0, 1.0, 1.0, 1.0)
        self._inner_shell_color: tuple = (1.0, 1.0, 1.0, 1.0)
        self._outer_core_color:  tuple = (1.0, 1.0, 1.0, 1.0)
        self._inner_core_color:  tuple = (1.0, 1.0, 1.0, 1.0)
        # Beam texture (relative path under game/).
        self._texture_name: str = ""
        # Beam geometry — full BC-faithful set.
        self._num_sides: int = 6              # prism side count
        self._taper_radius: float = 0.01      # half-width at endpoints
        self._taper_ratio: float = 0.25       # fraction of beam length used for taper
        self._taper_min_length: float = 5.0   # taper length floor
        self._taper_max_length: float = 30.0  # taper length ceiling
        self._perimeter_tile: float = 1.0     # texture repeats around circumference
        self._texture_speed: float = 0.0      # U-axis scroll (texels/sec)

    def GetPhaserWidth(self) -> float:      return self._phaser_width
    def SetPhaserWidth(self, v) -> None:    self._phaser_width = float(v)
    def GetMainRadius(self) -> float:       return self._main_radius
    def SetMainRadius(self, v) -> None:     self._main_radius = float(v)
    def GetCoreScale(self) -> float:        return self._core_scale
    def SetCoreScale(self, v) -> None:      self._core_scale = float(v)
    def GetNumSides(self) -> int:           return self._num_sides
    def SetNumSides(self, v) -> None:       self._num_sides = int(v)
    def GetTaperRadius(self) -> float:      return self._taper_radius
    def SetTaperRadius(self, v) -> None:    self._taper_radius = float(v)
    def GetTaperRatio(self) -> float:       return self._taper_ratio
    def SetTaperRatio(self, v) -> None:     self._taper_ratio = float(v)
    def GetTaperMinLength(self) -> float:   return self._taper_min_length
    def SetTaperMinLength(self, v) -> None: self._taper_min_length = float(v)
    def GetTaperMaxLength(self) -> float:   return self._taper_max_length
    def SetTaperMaxLength(self, v) -> None: self._taper_max_length = float(v)
    def GetPerimeterTile(self) -> float:    return self._perimeter_tile
    def SetPerimeterTile(self, v) -> None:  self._perimeter_tile = float(v)
    def GetTextureSpeed(self) -> float:     return self._texture_speed
    def SetTextureSpeed(self, v) -> None:   self._texture_speed = float(v)

    @staticmethod
    def _coerce_color(c) -> tuple:
        # TGColorA exposes .r/.g/.b/.a; tuples pass through.
        if hasattr(c, "r") and hasattr(c, "g") and hasattr(c, "b"):
            a = getattr(c, "a", 1.0)
            return (float(c.r), float(c.g), float(c.b), float(a))
        if isinstance(c, tuple) and len(c) >= 3:
            return (float(c[0]), float(c[1]), float(c[2]),
                    float(c[3]) if len(c) > 3 else 1.0)
        return (1.0, 1.0, 1.0, 1.0)

    def GetOuterShellColor(self) -> tuple:  return self._outer_shell_color
    def SetOuterShellColor(self, c) -> None: self._outer_shell_color = self._coerce_color(c)
    def GetInnerShellColor(self) -> tuple:  return self._inner_shell_color
    def SetInnerShellColor(self, c) -> None: self._inner_shell_color = self._coerce_color(c)
    def GetOuterCoreColor(self) -> tuple:   return self._outer_core_color
    def SetOuterCoreColor(self, c) -> None:  self._outer_core_color  = self._coerce_color(c)
    def GetInnerCoreColor(self) -> tuple:   return self._inner_core_color
    def SetInnerCoreColor(self, c) -> None:  self._inner_core_color  = self._coerce_color(c)

    def GetTextureName(self) -> str:        return self._texture_name
    def SetTextureName(self, name) -> None: self._texture_name = str(name)


class PulseWeaponProperty(EnergyWeaponProperty):
    """Pulse-weapon template — energy-weapon charge model plus a per-shot
    cooldown timer.  Galaxy.py has no pulse cannons; vorcha/marauder do
    (SetCooldownTime values 0.3-1.6 seconds per cannon).
    """
    def __init__(self, name: str = ""):
        super().__init__(name)
        self._cooldown_time: float = 0.0
        self._module_name: str = ""

    def GetCooldownTime(self) -> float:
        return self._cooldown_time

    def SetCooldownTime(self, v) -> None:
        self._cooldown_time = float(v)

    def GetModuleName(self) -> str:
        return self._module_name

    def SetModuleName(self, v) -> None:
        self._module_name = str(v)


class TractorBeamProperty(PhaserProperty):
    """Tractor-beam emitter template.

    BC renders a tractor as a textured beam exactly like a phaser (galaxy.py's
    AftTractor2 sets NumSides / MainRadius / the four shell+core colours /
    TractorBeam.tga / TextureSpeed — the same beam-visual surface phasers use),
    so this inherits PhaserProperty's coercing colour setters and typed beam
    getters.  Ship building routes by *exact* property type (ships.py
    _CHILD_DISPATCH uses ``type(prop) is prop_cls``), so being a PhaserProperty
    subclass does NOT mis-route a tractor emitter into a phaser bank.
    """
    pass


class TorpedoTubeProperty(WeaponProperty):
    """Torpedo-tube template — per-tube reload timing.  Galaxy.py: each tube
    has immediate=0.25s, reload=40s (per-tube; six tubes give ~6.7s effective
    fire interval), MaxReady=1 (one shot queued before reload).
    """
    def __init__(self, name: str = ""):
        super().__init__(name)
        self._immediate_delay: float = 0.0
        self._reload_delay: float = 0.0
        self._max_ready: int = 0

    def GetImmediateDelay(self) -> float:
        return self._immediate_delay

    def SetImmediateDelay(self, v) -> None:
        self._immediate_delay = float(v)

    def GetReloadDelay(self) -> float:
        return self._reload_delay

    def SetReloadDelay(self, v) -> None:
        self._reload_delay = float(v)

    def GetMaxReady(self) -> int:
        return self._max_ready

    def SetMaxReady(self, v) -> None:
        self._max_ready = int(v)


class PoweredSubsystemProperty(SubsystemProperty):
    pass


class ShieldProperty(PoweredSubsystemProperty):
    FRONT_SHIELDS  = 0
    REAR_SHIELDS   = 1
    TOP_SHIELDS    = 2
    BOTTOM_SHIELDS = 3
    LEFT_SHIELDS   = 4
    RIGHT_SHIELDS  = 5
    NUM_SHIELDS    = 6

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._max_shields = [0.0] * self.NUM_SHIELDS
        self._charge_per_second = [0.0] * self.NUM_SHIELDS
        self._skin_shielding: int = 0
        self._shield_glow_decay: float = 1.0
        self._shield_glow_color = None

    def GetMaxShields(self, face):
        return self._max_shields[int(face)]

    def SetMaxShields(self, face, value):
        f = int(face)
        v = float(value)
        self._max_shields[f] = v

    def GetShieldChargePerSecond(self, face):
        return self._charge_per_second[int(face)]

    def SetShieldChargePerSecond(self, face, value):
        f = int(face)
        v = float(value)
        self._charge_per_second[f] = v

    def GetSkinShielding(self):
        return self._skin_shielding

    def SetSkinShielding(self, value):
        self._skin_shielding = int(value)

    def GetShieldGlowDecay(self):
        return self._shield_glow_decay

    def SetShieldGlowDecay(self, value):
        self._shield_glow_decay = float(value)

    def GetShieldGlowColor(self):
        return self._shield_glow_color

    def SetShieldGlowColor(self, color):
        self._shield_glow_color = color
        # Preserve the color-consumer tracker hook that TGModelProperty's
        # auto-synthesized setter used to provide.  Matches the shim's
        # _getframe(1) caller-attribution behavior in properties.py:32-43.
        import App as _App
        if _App._color_consumer_tracker.is_enabled():
            import sys as _sys
            frame = _sys._getframe(1)
            _App._color_consumer_tracker.record(
                "ShieldProperty.SetShieldGlowColor", color,
                frame.f_code.co_filename, frame.f_lineno,
            )


class SensorProperty(PoweredSubsystemProperty):
    pass


class RepairSubsystemProperty(PoweredSubsystemProperty):
    pass


class WeaponSystemProperty(PoweredSubsystemProperty):
    WST_UNKNOWN = 0
    WST_PHASER  = 1
    WST_TORPEDO = 2
    WST_PULSE   = 3
    WST_TRACTOR = 4

    def __init__(self, name: str = ""):
        super().__init__(name)
        # {slot: "Tactical.Projectiles.<Name>"} — populated by hardpoint
        # SetTorpedoScript calls; read at fire time to dispatch to the SDK
        # projectile script (galaxy.py, akira.py, vorcha.py etc. all set
        # slot 0 to PhotonTorpedo / KlingonTorpedo / etc.).
        self._torpedo_scripts: dict[int, str] = {}
        # Parsed firing chains: list of (label, [tube_indices]). Populated
        # by SetFiringChainString. Empty on most ships — only Galaxy and
        # Sovereign use a non-empty chain string in stock BC.
        self._firing_chains: list[tuple[str, list[int]]] = []

    def SetTorpedoScript(self, slot, module_name) -> None:
        self._torpedo_scripts[int(slot)] = str(module_name)

    def GetTorpedoScript(self, slot):
        return self._torpedo_scripts.get(int(slot))

    def SetFiringChainString(self, tg_string_or_str) -> None:
        """Parse a SDK-format firing-chain string into structured chains.

        Format (observed in galaxy.py:1006-1008 and sovereign.py):
        ``"<indices>;<label>;<indices>;<label>;..."`` where each
        ``<indices>`` segment is a sequence of single-digit tube-index
        characters and each ``<label>`` is an opaque chain name
        (Single/Dual/Quad on stock BC; the parser doesn't interpret
        them — player UI / AI selects chains by index).

        Accepts either a ``TGString`` handle (SDK pattern) or a bare
        Python ``str`` (engine call sites). The raw string is preserved
        on ``self._firing_chain_string`` for round-trip getters.
        """
        if hasattr(tg_string_or_str, "GetCString"):
            raw = str(tg_string_or_str.GetCString())
        else:
            raw = str(tg_string_or_str)
        self._firing_chain_string = raw
        chains: list[tuple[str, list[int]]] = []
        if raw:
            parts = raw.split(";")
            # Pair each indices segment with the following label; drop a
            # trailing unpaired indices segment rather than raising.
            i = 0
            while i + 1 < len(parts):
                indices_str = parts[i]
                label = parts[i + 1]
                indices = [int(ch) for ch in indices_str if ch.isdigit()]
                if indices:
                    chains.append((label, indices))
                i += 2
        self._firing_chains = chains

    def GetFiringChainString(self):
        """Return the raw chain string. The return type is _TGString —
        a ``str`` subclass that also satisfies the SDK ``.GetString()``
        / ``.GetCString()`` API — so equality against a plain ``str``
        and the SDK call-chain idiom both work."""
        raw = getattr(self, "_firing_chain_string", "")
        from engine.appc.localization import _TGString
        return _TGString(raw)

    def GetFiringChains(self) -> list[tuple[str, list[int]]]:
        return list(self._firing_chains)


class TorpedoSystemProperty(WeaponSystemProperty):
    """Torpedo weapon system + its ammo-slot declaration.

    BC hardpoints declare the selectable ammo types on this property
    (sovereign.py:627-633): per slot ``SetMaxTorpedoes(slot, max)`` +
    ``SetTorpedoScript(slot, "Tactical.Projectiles.<X>")``, then one
    ``SetNumAmmoTypes(N)``.  SetupProperties reads this back to seed one
    TorpedoAmmoType per DECLARED slot.

    These are explicit (not the base data-bag magic) so ``GetNumAmmoTypes``
    defaults to 0 and ``GetMaxTorpedoes`` can return ``None`` for an undeclared
    slot — the seeding path treats that ``None`` as "undeclared / unlimited"
    (no reserve gate), while a declared max of 0 (e.g. PhasedPlasma) stays a
    real, empty slot.
    """

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._num_ammo_types: int = 0
        self._max_by_slot: dict[int, int] = {}

    def SetNumAmmoTypes(self, n) -> None:
        self._num_ammo_types = int(n)

    def GetNumAmmoTypes(self) -> int:
        return self._num_ammo_types

    def SetMaxTorpedoes(self, slot, max_torpedoes) -> None:
        self._max_by_slot[int(slot)] = int(max_torpedoes)

    def GetMaxTorpedoes(self, slot):
        # Returns the declared int (incl. 0), or None when this slot was never
        # declared — the seeding path's "undeclared / unlimited" signal.
        return self._max_by_slot.get(int(slot))


# Ship template — top-level data container for ship-class definitions
# (mass, model, affiliation, AI string, etc).  See sdk/.../GlobalPropertyTemplates.py
# and ships/Hardpoints/*.py for setter call sites.
class ShipProperty(TGModelProperty):
    pass


# Engine subsystems.  EngineProperty is the lightweight type-tagged form used
# by hardpoint scripts that need named per-engine entries (Port Warp, Star Warp).
# Impulse/WarpEngineProperty are powered-subsystem forms with speed/accel data.
class EngineProperty(SubsystemProperty):
    EP_IMPULSE = 0
    EP_WARP    = 1

    def __init__(self, name: str = "") -> None:
        super().__init__(name)
        self._engine_type = self.EP_IMPULSE

    def SetEngineType(self, t) -> None:
        self._engine_type = int(t)

    def GetEngineType(self) -> int:
        return self._engine_type


class ImpulseEngineProperty(PoweredSubsystemProperty):
    def __init__(self, name: str = "") -> None:
        super().__init__(name)
        self._engine_sound_name: str = ""

    def SetEngineSound(self, name: str) -> None:
        self._engine_sound_name = name

    def GetEngineSound(self) -> str:
        return self._engine_sound_name


class WarpEngineProperty(PoweredSubsystemProperty):
    pass


# Cloaking system — used by birdofprey, warbird, vorcha, sunbuster, kessok*
# (sdk/.../ships/Hardpoints/*).  Powered subsystem with a single domain-specific
# attribute (CloakStrength) plus the inherited subsystem fields.
class CloakingSubsystemProperty(PoweredSubsystemProperty):
    # CloakStrength rates how well the device cloaks (warbird.py sets 100.0).
    # The ship loader maps it to the cloak's transition duration — a fully-rated
    # device (100) cloaks in the canonical CLOAK_TRANSITION_DURATION; a weaker
    # device is proportionally slower. Defaults to 100.0 so an undeclared value
    # yields the canonical timing.
    def __init__(self, name: str = "") -> None:
        super().__init__(name)
        self._cloak_strength: float = 100.0

    def SetCloakStrength(self, v) -> None:
        self._cloak_strength = float(v)

    def GetCloakStrength(self) -> float:
        return self._cloak_strength


# ── Factory functions ─────────────────────────────────────────────────────────
# SDK call sites use App.XxxProperty_Create("Name") rather than the
# constructor directly. These mirror the SDK's Appc.new_XxxProperty pattern.

def PositionOrientationProperty_Create(name): return PositionOrientationProperty(name)
def HullProperty_Create(name):                return HullProperty(name)
def PowerProperty_Create(name):               return PowerProperty(name)
def PhaserProperty_Create(name):              return PhaserProperty(name)
def PulseWeaponProperty_Create(name):         return PulseWeaponProperty(name)
def TractorBeamProperty_Create(name):         return TractorBeamProperty(name)
def TorpedoTubeProperty_Create(name):         return TorpedoTubeProperty(name)
def ShieldProperty_Create(name):              return ShieldProperty(name)
def SensorProperty_Create(name):              return SensorProperty(name)
def RepairSubsystemProperty_Create(name):     return RepairSubsystemProperty(name)
def TorpedoSystemProperty_Create(name):       return TorpedoSystemProperty(name)
def ShipProperty_Create(name):                return ShipProperty(name)
def EngineProperty_Create(name):              return EngineProperty(name)
def ImpulseEngineProperty_Create(name):       return ImpulseEngineProperty(name)
def WarpEngineProperty_Create(name):          return WarpEngineProperty(name)
def WeaponSystemProperty_Create(name):        return WeaponSystemProperty(name)
def CloakingSubsystemProperty_Create(name):   return CloakingSubsystemProperty(name)
def ObjectEmitterProperty_Create(name):       return ObjectEmitterProperty(name)


def ObjectEmitterProperty_Cast(obj):
    """Lenient pass-through: returns obj if it's an ObjectEmitterProperty, else None.

    Rejects _NamedStub explicitly so undefined-attribute chains don't slip
    through and keep producing stub-tracker hits.
    """
    if obj is None:
        return None
    import App
    if isinstance(obj, App._NamedStub):
        return None
    if isinstance(obj, ObjectEmitterProperty):
        return obj
    return None


# ── TGModelPropertyManager ────────────────────────────────────────────────────
# loadspacehelper.py:90 calls ClearLocalTemplates() between ship loads, so the
# manager is genuinely stateful across hardpoint imports. App.py's singleton
# lives for the whole session.
#
# Renderer-only methods (RegisterFilter, AddFilter, ApplyFilters, etc.) are
# Phase 2 concerns; they fall through to App.py's _NamedStub via __getattr__.

class TGModelPropertyManager:
    LOCAL_TEMPLATES  = 0
    GLOBAL_TEMPLATES = 1

    def __init__(self):
        self._local: dict = {}
        self._global: dict = {}

    def _store(self, scope):
        return self._local if scope == self.LOCAL_TEMPLATES else self._global

    def RegisterLocalTemplate(self, prop):
        self._local[prop.GetName()] = prop

    def RegisterGlobalTemplate(self, prop):
        self._global[prop.GetName()] = prop

    def ClearLocalTemplates(self):
        self._local.clear()

    def ClearGlobalTemplates(self):
        self._global.clear()

    def FindByName(self, name, scope):
        return self._store(scope).get(name)

    def FindByNameAndType(self, name, type_cls, scope):
        prop = self._store(scope).get(name)
        return prop if isinstance(prop, type_cls) else None

    def IsLocalTemplate(self, prop):
        return prop in self._local.values()

    def IsGlobalTemplate(self, prop):
        return prop in self._global.values()

    def RemoveTemplate(self, prop):
        self._local  = {k: v for k, v in self._local.items()  if v is not prop}
        self._global = {k: v for k, v in self._global.items() if v is not prop}


# ── TGModelPropertyInstance / TGModelPropertyList ─────────────────────────────
# SDK call sites (loadspacehelper.py:171-189) iterate the result of
# GetPropertyList()/GetPropertiesByType() via TGBeginIteration / TGGetNumItems
# / TGGetNext / TGDoneIterating / TGDestroy. TGGetNext returns an "instance"
# wrapper exposing GetProperty() to extract the underlying TGModelProperty —
# see SDK App.py:2316-2342 for reference.

class _TGModelPropertyInstance:
    def __init__(self, prop):
        self._prop = prop

    def GetProperty(self):
        return self._prop


class _TGModelPropertyList:
    def __init__(self, props):
        self._props = list(props)
        self._index = 0

    def __iter__(self):
        # Preserve Python list() compatibility for tests/non-SDK callers.
        return iter(self._props)

    def TGBeginIteration(self):
        self._index = 0

    def TGGetNumItems(self):
        return len(self._props)

    def TGGetNext(self):
        prop = self._props[self._index]
        self._index += 1
        return _TGModelPropertyInstance(prop)

    def TGDoneIterating(self):
        self._index = 0

    def TGDestroy(self):
        pass


# ── TGModelPropertySet ────────────────────────────────────────────────────────
# Holds (node_name, prop) pairs. node_name (e.g. "Scene Root") is a renderer
# concept stored but unused in Phase 1.

class TGModelPropertySet:
    def __init__(self):
        self._entries: list = []

    def AddToSet(self, node_name, prop):
        self._entries.append((node_name, prop))

    def GetPropertyList(self):
        return _TGModelPropertyList([prop for _node, prop in self._entries])

    def GetPropertiesByType(self, type_cls):
        return _TGModelPropertyList(
            [prop for _node, prop in self._entries if isinstance(prop, type_cls)]
        )
